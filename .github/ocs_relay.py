#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OCS 网课题库助手 —— 本地中转服务（Ollama 版）·单文件版
=====================================================
整个程序只有这一个 .py 文件：控制台页面已以 base64 内嵌，无需任何附属文件。

职责：接收 OCS(脚本猫) 发来的题目 -> 组装 prompt -> 调用本地 Ollama -> 清洗答案 -> 返回 JSON

设计要点（均已实测验证）：
  1. 一个容器同时接受 GET / POST / HEAD / OPTIONS
     - HEAD   : OCS 后台"题库配置"卡片渲染时会探测，必须 200
     - OPTIONS: 兜底，返回 204 + CORS 头，防止任何预检被拦
  2. 默认关闭"思考链"（think=False），并做三层清洗，R1 系模型也不会污染答案
  3. 三级降级策略：think=False -> 不带 think 字段重试 -> 仍失败则换备用模型
  4. 多级答案解析：优先返回选项正文（走 OCS 文本匹配，最稳），退化为选项字母
  5. 串行队列：单题串行、多题排队，避免网页多线程请求把 CPU 打满导致全部超时
  6. 本地缓存 + 预热：重复题秒回，冷启动不计入答题耗时
  7. 节律控制：返回间隔补足到 U(500,1500)ms，缓存命中也照样延时
  8. 全链路日志：每题耗时、命中缓存与否、降级情况，便于定位问题

运行：
    python ocs_relay.py                 # 默认 127.0.0.1:5000，自动打开控制台
    python ocs_relay.py --port 5001     # 自定义端口
    python ocs_relay.py --no-browser    # 不自动打开浏览器
    python ocs_relay.py --no-warmup     # 跳过预热

打包（仍是单文件 exe）：
    pip install pyinstaller
    pyinstaller -F -n OCS中转 --collect-submodules werkzeug ocs_relay.py
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import logging
import os
import random
import re
import sys
import threading
import time
from collections import OrderedDict, deque

import requests
from flask import Flask, jsonify, request

# --------------------------------------------------------------------------- #
# 路径处理
#   打包成 exe 后：配置写到 exe 同级目录（便携，拷走就能用）
#   源码运行时：配置写到脚本同级目录
# --------------------------------------------------------------------------- #
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
    APP_VERSION = "1.2.1"
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    APP_VERSION = "1.2.1"

CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
LOG_PATH = os.path.join(BASE_DIR, "relay.log")

DEFAULT_CONFIG = {
    # ---------------- 后端类型 ----------------
    # ollama = 本地（默认，离线、不外传数据）
    # openai = OpenAI 兼容云端（晶谱 GLM / 硅基流动 Qwen 等，需填 api_base + api_key）
    "backend": "ollama",
    "ollama_url": "http://127.0.0.1:11434/api/generate",
    # 云端 OpenAI 兼容端点，填到 /v1 或 /v4 那一层即可：
    #   智谱 GLM   https://open.bigmodel.cn/api/paas/v4
    #   硅基流动    https://api.siliconflow.cn/v1
    "api_base": "",
    "api_key": "",                 # 云端密钥；本地 Ollama 可留空（Ollama 也兼容 OpenAI 协议）
    "cloud_max_tokens": 1024,      # 云端单次最多生成 token（思考型模型建议 1024+，太小会把正文截空）
    "model": "qwen2.5:7b-instruct",   # 首选：不产思考链，速度快 3~5 倍
    "fallback_model": "deepseek-r1:7b",
    # 题型路由（auto_route 开启时自动按题目内容选模型）：
    #   图片题（请求带 images）→ vision_model
    #   代码题（题干含代码特征）→ code_model
    #   其余 → model。某项未配置则回落主模型。
    "auto_route": True,
    "vision_model": "",               # 例：glm-4v-flash（智谱免费多模态）/ qwen2.5vl:7b（本地）
    "code_model": "",                 # 例：Qwen/Qwen3-8B；留空=代码题也走主模型

    # ---------------- 正确率增强 ----------------
    # 1) 题库优先：先查 bank.json（手工导入的题库），命中直接返回，不走模型
    "bank_enabled": True,
    # 2) 答错订正：corrections.json 里人工确认过的答案，优先级最高
    #    （控制台"答题记录"里一键订正写入）
    # 3) 双模型交叉验证：verify_mode
    #    off  = 不验证（最快）
    #    fast = 第二个模型复核，答案一致→高置信；不一致→标注"低置信"
    #    full = 不一致时再用主模型仲裁一次（最慢，正确率最高）
    "verify_mode": "off",             # off / fast / full
    "verify_model": "",               # 复核模型；留空=fallback_model
    "arbitrate_model": "",            # 仲裁模型（full 模式两模型不一致时找它裁决）；留空=不做仲裁
    # 4) 提示词预设：default/law/medical/math/engineering，按学科定制要求
    "prompt_preset": "default",
    # 5) CoT：难题先推理再作答（对多选/计算题提升明显，稍慢）
    "cot_mode": False,

    "keep_alive": "30m",              # 模型驻留内存时长，避免每题重新加载（仅 Ollama）
    "num_ctx": 4096,                  # 上下文窗口，题目够用且最省显存（仅 Ollama）
    "temperature": 0.0,               # 确定性输出，同题同答案
    "seed": 42,
    "num_predict": 1024,              # 最多生成 token，防止失控长文（仅 Ollama）

    # ---------------- 服务侧 ----------------
    "host": "127.0.0.1",
    "port": 5000,
    "request_timeout": 100,           # 单次模型请求超时(秒)
    "answer_budget": 50,              # 整题总预算(秒)，必须 < OCS 的 60s 超时
    "max_queue": 32,                  # 排队上限
    "max_concurrency": 1,             # 并发推理数：本地保持 1；云端可 2~4（需重启）
    "cache_size": 1024,               # 内存缓存条数
    "auth_token": "",                 # 访问令牌（非空则所有接口需携带；0.0.0.0 局域网暴露时强烈建议设置）
    "privacy_log": False,             # true=日志里题目打码（公用电脑建议开）
    "verbose": True,

    # ---------------- 节律 / 反特征 ----------------
    # 缓存命中也照样延时：OCS 本地题库缓存会让重复题瞬间返回，
    # 若"同一道题 2ms 就答完"会被看出是机器，所以命中也要等。
    "human_delay": True,
    "delay_min_ms": 500,
    "delay_max_ms": 1500,
    "delay_on_cache": True,           # 缓存命中是否也延时（建议 True）
    "jitter_model": True,             # 右偏分布，避免等间隔
    "max_gap_ms": 6000,               # 距上一题超过该值则不再补时（防"久无题突然连发"）

    # ---------------- 启动行为 ----------------
    "auto_open_browser": True,        # 启动后自动打开控制台
}

# 允许通过界面修改的字段及其类型（防止误传任意字段写坏配置）
EDITABLE_FIELDS = {
    "backend": str,
    "model": str,
    "fallback_model": str,
    "auto_route": bool,
    "vision_model": str,
    "code_model": str,
    "bank_enabled": bool,
    "verify_mode": str,
    "verify_model": str,
    "arbitrate_model": str,
    "prompt_preset": str,
    "cot_mode": bool,
    "api_base": str,
    "api_key": str,
    "cloud_max_tokens": int,
    "num_ctx": int,
    "num_predict": int,
    "temperature": float,
    "keep_alive": str,
    "port": int,
    "answer_budget": int,
    "request_timeout": int,
    "max_queue": int,
    "max_concurrency": int,
    "auth_token": str,
    "privacy_log": bool,
    "human_delay": bool,
    "delay_min_ms": int,
    "delay_max_ms": int,
    "delay_on_cache": bool,
    "verbose": bool,
    "auto_open_browser": bool,
}

_CFG_LOCK = threading.RLock()

# --------------------------------------------------------------------------- #
# 配置加载 / 保存
# --------------------------------------------------------------------------- #
def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
            cfg.update({k: v for k, v in user_cfg.items()
                        if v is not None and not k.startswith("_")})
        except Exception as e:
            print(f"[WARN] config.json 解析失败，使用默认配置: {e}")
    # 环境变量可覆盖（方便打包后免改文件）
    if os.environ.get("OLLAMA_MODEL"):
        cfg["model"] = os.environ["OLLAMA_MODEL"]
    if os.environ.get("OLLAMA_URL"):
        cfg["ollama_url"] = os.environ["OLLAMA_URL"]
    if os.environ.get("BACKEND"):
        cfg["backend"] = os.environ["BACKEND"]
    if os.environ.get("API_BASE"):
        cfg["api_base"] = os.environ["API_BASE"]
    if os.environ.get("API_KEY"):
        cfg["api_key"] = os.environ["API_KEY"]
    return cfg


def save_config(new_values: dict) -> tuple[bool, str]:
    """
    校验并写回 config.json，同时热更新内存中的 CFG。
    返回 (是否成功, 说明)。端口变更需要重启，其余即时生效。
    """
    cleaned, errors = {}, []
    for k, v in (new_values or {}).items():
        if k not in EDITABLE_FIELDS:
            continue
        typ = EDITABLE_FIELDS[k]
        try:
            if typ is bool:
                val = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "on")
            elif typ is int:
                val = int(float(v))
            elif typ is float:
                val = float(v)
            else:
                val = str(v).strip()
            cleaned[k] = val
        except Exception:
            errors.append(f"{k} 的值 {v!r} 无效")

    # 业务校验
    if "delay_min_ms" in cleaned and "delay_max_ms" in cleaned:
        if cleaned["delay_min_ms"] > cleaned["delay_max_ms"]:
            cleaned["delay_min_ms"], cleaned["delay_max_ms"] = (
                cleaned["delay_max_ms"], cleaned["delay_min_ms"])
    if cleaned.get("answer_budget", 50) >= 58:
        errors.append("整题预算必须小于 58 秒（OCS 超时为 60 秒）")
    if not (1 <= cleaned.get("port", 5000) <= 65535):
        errors.append("端口需在 1~65535 之间")
    if cleaned.get("delay_max_ms", 1500) > 15000:
        errors.append("延时上限不建议超过 15000ms")
    if not (1 <= cleaned.get("max_concurrency", 1) <= 8):
        errors.append("并发数需在 1~8 之间")
    if cleaned.get("verify_mode") not in (None, "off", "fast", "full"):
        errors.append("verify_mode 只能是 off / fast / full")
    if cleaned.get("prompt_preset") not in (None, *PROMPT_PRESETS.keys()):
        errors.append("prompt_preset 预设无效")
    # api_key 保护：空值或掩码值（*** 尾号）不覆盖已保存的 key
    if "api_key" in cleaned:
        v = cleaned["api_key"]
        if v == "" or v.startswith("***"):
            cleaned.pop("api_key")
    # auth_token 不写进日志
    log_kv = {k: ("***" if k in ("api_key", "auth_token") else v)
              for k, v in cleaned.items()}
    if errors:
        return False, "；".join(errors)

    with _CFG_LOCK:
        old_port = CFG.get("port")
        CFG.update(cleaned)
        # 保留原文件中的注释字段（下划线开头的键）
        out = {}
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    old = json.load(f)
                out = {k: v for k, v in old.items() if k.startswith("_")}
            except Exception:
                out = {}
        out.update({k: CFG[k] for k in DEFAULT_CONFIG})
        try:
            _dump_config(out)
        except Exception as e:
            return False, f"写入配置文件失败：{e}"

    need_restart = old_port != CFG.get("port")
    parts = []
    if need_restart:
        parts.append(f"端口从 {old_port} 改为 {CFG.get('port')}，需重启生效")
    if "max_concurrency" in cleaned:
        parts.append("并发数需重启生效")
    msg = "已保存并即时生效" if not parts else "已保存；" + "；".join(parts)
    log.info("配置已更新：%s", ", ".join(f"{k}={v}" for k, v in log_kv.items()))
    return True, msg


CFG = load_config()


# 写进 config.json 的说明字段（下划线开头，读配置时会被忽略，保存时原样保留）
CONFIG_COMMENTS = {
    "_后端": "backend=ollama 走本地（离线、不外传）；backend=openai 走云端 OpenAI 兼容接口。"
            "云端需填 api_base（如 https://open.bigmodel.cn/api/paas/v4）和 api_key",
    "_模型": "model / fallback_model。云端示例：glm-4.5-flash（智谱，全免费） / Qwen/Qwen3-8B（硅基流动，免费）"
            "本地示例：qwen2.5:7b-instruct / deepseek-r1:7b",
    "_题型路由": "auto_route=true 时自动按题选模型：带图走 vision_model（如 glm-4v-flash），"
              "代码题走 code_model，其余走 model。未配置的项回落主模型",
    "_安全": "auth_token 非空则所有接口需携带令牌（OCS 配置会自动带头；0.0.0.0 局域网时强烈建议）；"
            "privacy_log=true 日志里题目打码；api_key 只存本机且接口只回掩码",
    "_节律": "human_delay 总开关；每题返回前补足到 500~1500ms 的随机间隔；"
             "缓存命中也延时（delay_on_cache）；max_gap_ms 内才补时，避免久无题后突然连发",
}


def _dump_config(values: dict) -> None:
    """把说明字段 + 配置值写成 JSON（原子写入）。"""
    out = dict(CONFIG_COMMENTS)
    out.update({k: values[k] for k in DEFAULT_CONFIG if k in values})
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)


def ensure_config_file() -> None:
    """首次运行时没有 config.json 就按默认值生成一份，带说明，方便用户直接改文件。"""
    if os.path.exists(CONFIG_PATH):
        return
    try:
        _dump_config(CFG)
    except Exception:
        pass    # 目录不可写也不影响运行，控制台自检会提示

# --------------------------------------------------------------------------- #
# 日志：同时输出到控制台/文件 + 内存环形缓冲（供网页控制台实时拉取）
# --------------------------------------------------------------------------- #
LOG_RING: deque = deque(maxlen=400)
LOG_LOCK = threading.Lock()


_LOG_SEQ = [0]          # 全局单调递增日志序号，供前端增量拉取
_OLLAMA_STATE = {"ok": False, "detail": "未检测"}


class RingHandler(logging.Handler):
    def emit(self, record):
        try:
            msg = record.getMessage()
            if record.exc_info:
                msg += " | " + str(record.exc_info[1])
            with LOG_LOCK:
                _LOG_SEQ[0] += 1
                LOG_RING.append({
                    "i": _LOG_SEQ[0],
                    "t": time.strftime("%H:%M:%S", time.localtime(record.created)),
                    "level": record.levelname,
                    "msg": msg,
                })
        except Exception:
            pass


def _setup_logging():
    handlers = [logging.StreamHandler(sys.stdout)]
    try:
        from logging.handlers import RotatingFileHandler
        handlers.append(RotatingFileHandler(LOG_PATH, maxBytes=2 * 1024 * 1024,
                                            backupCount=3, encoding="utf-8"))
    except Exception:
        pass
    handlers.append(RingHandler())
    logging.basicConfig(
        level=logging.INFO if CFG.get("verbose", True) else logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
        force=True,
    )


_setup_logging()
log = logging.getLogger("oca")

# 最近答题记录（供控制台表格）
ANSWER_RING: deque = deque(maxlen=120)
ANSWER_LOCK = threading.Lock()
STATS = {"total": 0, "success": 0, "cache": 0, "fail": 0, "started_at": time.time()}

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False


# --------------------------------------------------------------------------- #
# 答案清洗
# --------------------------------------------------------------------------- #
# 完整思考块：<think ...>...</think>，兼容大小写、标签内空格(< think >)、属性
_THINK_BLOCK = re.compile(r"<\s*think\b[^>]*>.*?<\s*/\s*think\s*>", re.S | re.I)
# 未闭合的开标签（模型被截断时）
_THINK_OPEN = re.compile(r"<\s*think\b[^>]*>", re.I)
_CLOSE_TAG = re.compile(r"<\s*/\s*think\s*>", re.I)
# 中文模型偶尔自创的思考段标记
_CN_THINK = re.compile(
    r"(思考过程|分析过程|推理过程|思考[:：]|分析[:：])\s*[:：]?.*?(?=(最终答案|答案|结论|所以|选择)|$)",
    re.S,
)
# 前缀噪词："正确答案是"、"答案："
_ANS_PREFIX = re.compile(
    r"^\s*(最终答案|正确答案|答案|选项|答|answer|choice|correct answer)\s*(是|为)?\s*[:：]?\s*",
    re.I,
)
# 控制字符（除 \n \t）
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# 结尾括号解释
_TRAILING_EXPLAIN = re.compile(r"\s*[(（\[【][^()（）\[\]【】]{1,80}[)）\]】]\s*$")
# 结尾标点
_TRAILING_PUNCT = re.compile(r"[。．.，,；;：:、\s]+$")
# 答案自带的选项字母前缀："A. 实事求是" / "B、群众路线" / "C）独立自主"
_LEAD_LETTER = re.compile(r"^[A-Ha-h]\s*[.．、:：,，)）]\s*")
# 成对包裹的引号
_WRAP_QUOTE = re.compile(r'^["\'“”‘’「」』《》]+|["\'“”‘’「」』《》]+$')


def clean_answer(raw: str) -> str:
    """从模型输出中剥离思考链、前缀噪词，只留答案本体。"""
    if not raw:
        return ""
    s = raw.strip()

    # 1) 截断型思考链（无 </think> 闭合，模型被 num_predict 截断）：
    #    遇到 think 开标签却找不到闭合，说明整段都是思考，后面的"答案："才是真答案
    if _THINK_OPEN.search(s) and not _CLOSE_TAG.search(s):
        m = re.search(r"(?<![<\w])(答案|最终答案|正确答案)\s*[:：]", s)
        if m:
            s = s[m.start():]
        else:
            s = _THINK_OPEN.sub(" ", s)

    # 2) 掐掉最后一个 </think> 之前的所有内容（最常见、最有效）
    if _CLOSE_TAG.search(s):
        s = _CLOSE_TAG.split(s)[-1].strip()

    # 3) 清理完整 / 残留的 think 块
    s = _THINK_BLOCK.sub(" ", s)
    s = _THINK_OPEN.sub(" ", s)

    # 4) 中文思考段
    s = _CN_THINK.sub(" ", s)

    # 5) 去控制字符、压缩空白
    s = _CTRL.sub("", s)
    s = re.sub(r"[ \t\u3000]+", " ", s)
    s = re.sub(r"\n{2,}", "\n", s).strip()

    # 6) 取有效行。多选题答案可能跨行（每行一个选项），
    #    所以保留那些"看起来就是选项"的后续行，其余解释性行丢弃
    lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
    if not lines:
        return ""
    kept = [lines[0]]
    for ln in lines[1:]:
        # 后续行若是短句或带选项字母前缀，视为同属答案；出现"解释/因为/理由"等则停止
        if len(kept) >= 6:
            break
        if re.search(r"(解释|因为|理由|分析|综上|所以|因此|故选|Explanation)", ln):
            break
        if len(ln) <= 40 or _OPT_LINE.match(ln):
            kept.append(ln)
        else:
            break
    s = "\n".join(kept)

    # 7) 去前缀 "答案是："（对每一行都处理）
    s = "\n".join(_ANS_PREFIX.sub("", ln).strip() for ln in s.splitlines())

    # 8) 逐行做最终清理
    out = []
    for ln in s.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        ln = _TRAILING_EXPLAIN.sub("", ln).strip()          # 去掉括号解释
        ln = _ANS_PREFIX.sub("", ln).strip()                # 再剥一次"答案："
        ln = _LEAD_LETTER.sub("", ln).strip()               # 剥选项字母前缀
        ln = _TRAILING_PUNCT.sub("", ln).strip()            # 去结尾标点
        ln = _WRAP_QUOTE.sub("", ln).strip()                # 去包裹引号
        if ln:
            out.append(ln)
    return "\n".join(out).strip()


# --------------------------------------------------------------------------- #
# 选项解析
# --------------------------------------------------------------------------- #
_OPT_LINE = re.compile(r"^\s*([A-Ha-h])\s*[\.．、:：\)）]\s*(.*)$")


def split_options(options_text) -> list[dict]:
    """
    把 OCS 传来的 options 解析成 [{letter, text, raw}, ...]
    OCS 传的是"每行一个选项"的字符串，行内可能自带 "A." 前缀，也可能不带。
    兼容：字符串 / list / 带 \n 的 JSON 数组字符串。
    """
    if isinstance(options_text, (list, tuple)):
        lines = [str(x) for x in options_text]
    else:
        text = str(options_text or "")
        text = text.replace("\\n", "\n").replace("\r", "\n")
        lines = [ln for ln in text.split("\n")]

    out = []
    auto = 0
    for ln in lines:
        if not ln or not ln.strip():
            continue
        m = _OPT_LINE.match(ln)
        if m:
            letter = m.group(1).upper()
            body = m.group(2).strip()
            auto = ord(letter) - 64
        else:
            letter = chr(65 + auto) if auto < 8 else ""
            body = ln.strip()
            auto += 1
        # 过滤掉纯空选项
        if not body and not letter:
            continue
        out.append({"letter": letter, "text": body, "raw": ln.strip()})
    return out


def _norm(s: str) -> str:
    """规范化：去掉所有标点空白，转小写，用于文本比对。"""
    s = re.sub(r"[^\w\u4e00-\u9fff]", "", s or "")
    return s.lower()


def match_option(answer: str, opts: list[dict]) -> tuple[str, str, str]:
    """
    返回 (最终答案, 输出形式, 说明)
    原则：优先输出"选项正文"，让 OCS 走文本匹配，不受选项顺序影响；
          找不到对应正文时才退化为字母。
    """
    if not answer:
        return "", "empty", "模型无输出"

    letters_only = re.sub(r"[^A-Ha-h]", "", answer).upper()

    # 1) 多选题：答案是 "AC" 或 "A C" 形式
    if len(letters_only) > 1 and len(letters_only) <= len(opts):
        picked = [o for o in opts if o["letter"] in letters_only]
        if len(picked) == len(set(letters_only)) and picked:
            return "\n".join(o["text"] for o in picked), "multi-text", f"多选 {letters_only}"

    # 2) 单字母：直接映射为正文
    if len(letters_only) == 1 and len(answer.strip()) <= 3:
        for o in opts:
            if o["letter"] == letters_only:
                return o["text"], "single-text", f"字母 {letters_only}"
        return letters_only, "single-letter", "字母越界"

    # 3) 按行拆分（多选/多空答案每行一项），逐行精确匹配
    parts = [p.strip() for p in re.split(r"\r?\n|\|", answer) if p.strip()]
    if len(parts) > 1:
        picked, used = [], set()
        for part in parts:
            np_ = _norm(part)
            if not np_:
                continue
            hit = None
            for i, o in enumerate(opts):
                if i in used:
                    continue
                if _norm(o["text"]) == np_:
                    hit = (i, o)
                    break
            if hit is None:
                for i, o in enumerate(opts):
                    if i in used:
                        continue
                    no = _norm(o["text"])
                    if no and (no in np_ or np_ in no):
                        hit = (i, o)
                        break
            if hit:
                used.add(hit[0])
                picked.append(hit[1]["text"])
        if picked:
            return "\n".join(picked), "multi-text", f"多行匹配 {len(picked)} 项"
        # 多个空但都不是选项（填空题）：原样返回，用 | 连接
        return "|".join(parts), "raw-multi", "多空填空，原样返回"

    na = _norm(answer)

    # 4) 正文精确相等
    for o in opts:
        if _norm(o["text"]) == na and na:
            return o["text"], "exact", "文本精确匹配"

    # 5) 互相包含（答案含选项 或 选项含答案），取最长匹配
    best, best_len = None, 0
    for o in opts:
        no = _norm(o["text"])
        if not no:
            continue
        if no in na or (na and na in no):
            if len(no) > best_len:
                best, best_len = o, len(no)
    if best:
        return best["text"], "contains", "文本包含匹配"

    # 6) 兜底：原文返回（填空题走这条路）
    return answer, "raw", "无匹配，原样返回"


# --------------------------------------------------------------------------- #
# Prompt
# --------------------------------------------------------------------------- #
TYPE_HINT = {
    "single": "单选题，只有一个正确选项",
    "multiple": "多选题，可能有 2~4 个正确选项",
    "judgement": "判断题",
    "completion": "填空题",
    "fill": "填空题",
}


# 按学科定制的提示词预设（prompt_preset 配置项选择）
PROMPT_PRESETS = {
    "default": "",
    "law": "这是法律类题目。请依据现行有效的法律条文作答；说法绝对化（如「一律」「所有」）的选项通常是错的，注意甄别。\n",
    "medical": "这是医学类题目。注意「首选」「最主要」「最常见」等关键词，审题要看清是正向还是反向提问（如「错误的是」）。\n",
    "math": "这是数学/计算类题目。先在心中列式计算，再比对选项；不要凭感觉选。\n",
    "engineering": "这是理工类题目。注意单位换算与公式适用条件；概念辨析题抓住定义的核心要素。\n",
    "english": "这是英语类题目。注意时态、固定搭配与上下文逻辑；选词题先判断词性。\n",
}


def build_prompt(title: str, opts: list[dict], qtype: str,
                 preset: str = "default", cot: bool = False) -> str:
    qtype = (qtype or "unknown").lower()
    hint = TYPE_HINT.get(qtype, "选择题")

    if opts:
        opt_block = "\n".join(
            f"{o['letter']}. {o['text']}" if o["letter"] else o["text"] for o in opts
        )
        body = f"题目：{title}\n\n选项：\n{opt_block}"
    else:
        body = f"题目：{title}"

    if qtype in ("completion", "fill"):
        rule = "直接在答案行输出填空内容，多个空用「|」分隔。"
    elif qtype == "multiple":
        rule = "在答案行输出所有正确选项的完整文字，每行一个，不要只输出字母。"
    else:
        rule = "在答案行只输出正确选项的完整文字（原样照抄选项内容），不要输出字母、不要解释。"

    if cot:
        style = (
            "先在「分析：」后用一两句话简短推理，再换行输出「答案：」和最终答案。\n"
        )
        return (
            f"{body}\n\n"
            f"【要求】这是{hint}。{rule}\n"
            f"{PROMPT_PRESETS.get(preset, '')}"
            f"{style}"
            "答案："
        )
    return (
        f"{body}\n\n"
        f"【要求】这是{hint}。{rule}\n"
        f"{PROMPT_PRESETS.get(preset, '')}"
        "必须先输出「答案：」，然后紧接答案内容。不要输出思考过程，不要重复题目，不要解释理由。\n\n"
        "答案："
    )


# --------------------------------------------------------------------------- #
# 缓存
# --------------------------------------------------------------------------- #
class TTLCache:
    """简易 LRU + TTL 缓存，线程安全。"""

    def __init__(self, size: int = 1024, ttl: float = 86400):
        self.size = max(16, int(size))
        self.ttl = ttl
        self._data: OrderedDict[str, tuple[float, dict]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str):
        with self._lock:
            item = self._data.get(key)
            if not item:
                return None
            ts, val = item
            if time.time() - ts > self.ttl:
                self._data.pop(key, None)
                return None
            self._data.move_to_end(key)
            return val

    def set(self, key: str, val: dict):
        with self._lock:
            self._data[key] = (time.time(), val)
            self._data.move_to_end(key)
            while len(self._data) > self.size:
                self._data.popitem(last=False)

    def __len__(self):
        return len(self._data)


CACHE = TTLCache(CFG.get("cache_size", 1024))

# --------------------------------------------------------------------------- #
# 题库（bank.json）与人工订正（corrections.json）
#   题库优先：导入的题库命中 → 直接返回，不消耗模型
#   人工订正：控制台把答错的题改成正确答案 → 以后永远用人工答案，优先级最高
# --------------------------------------------------------------------------- #
BANK_PATH = os.path.join(BASE_DIR, "bank.json")
CORRECTIONS_PATH = os.path.join(BASE_DIR, "corrections.json")
_KB_LOCK = threading.Lock()


def _load_json_map(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_json_map(path: str, data: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def q_key(title: str, options_text: str = "", images: list | None = None) -> str:
    """题目唯一键：规范化题干 + 选项摘要。
    选项做"去字母前缀"处理，这样导入题库（纯文本选项）与 OCS 请求
    （带 A. B. 前缀）能命中同一条。"""
    sig = _norm(title)
    lines = [re.sub(r"^[A-Ha-h][.．、:：)）]\s*", "", l).strip()
             for l in re.split(r"[\n/|]|；|;", options_text or "") if l.strip()]
    ot = _norm("".join(lines))
    if ot:
        sig += f"#{hashlib.md5(ot.encode()).hexdigest()[:8]}"
    if images:
        sig += f"#img{len(images)}:{hashlib.md5('|'.join(images).encode()).hexdigest()[:8]}"
    return sig


BANK: dict = _load_json_map(BANK_PATH)          # key -> {answer, options, qtype, ts, hits}
CORRECTIONS: dict = _load_json_map(CORRECTIONS_PATH)  # key -> {answer, options, qtype, ts, note}


def bank_lookup(title: str, options_text: str, images: list | None = None):
    """依次查：人工订正 > 题库。返回 (答案, 来源) 或 (None, None)。
    控制台订正可能只填题干（无选项），所以精确 key 未命中时再试仅题干 key。"""
    if images:
        return None, None
    if not ((CFG.get("bank_enabled", True) and BANK) or CORRECTIONS):
        return None, None
    key = q_key(title, options_text)
    keys = [key]
    k2 = q_key(title)
    if k2 != key:
        keys.append(k2)
    for k in keys:
        if k in CORRECTIONS:
            rec = CORRECTIONS[k]
            rec["hits"] = rec.get("hits", 0) + 1
            with _KB_LOCK:
                _save_json_map(CORRECTIONS_PATH, CORRECTIONS)
            return rec.get("answer", ""), "人工订正"
    for k in keys:
        if CFG.get("bank_enabled", True) and k in BANK:
            rec = BANK[k]
            rec["hits"] = rec.get("hits", 0) + 1
            with _KB_LOCK:
                _save_json_map(BANK_PATH, BANK)
            return rec.get("answer", ""), "题库"
    return None, None


def parse_bank_text(text: str) -> tuple[list[dict], list[str]]:
    """
    解析导入的题库文本，支持两种格式（可混用）：
      A. 块格式（推荐，从文档直接复制）：
         题干……
         A. 选项1
         B. 选项2
         答案：B
      B. 单行格式：题干|A. 选项1|B. 选项2|答案：B
    返回 (条目列表, 错误列表)
    """
    entries, errors = [], []
    lines = [l.strip() for l in (text or "").replace("\r\n", "\n").split("\n")]

    def finalize(q: str, opts: list, ans: str, ln: int):
        if not q or not ans:
            errors.append(f"第{ln}行附近：缺题干或答案，已跳过")
            return
        entries.append({
            "question": q, "options": opts,
            "answer": ans.strip(), "qtype": "multiple" if len(
                re.sub(r"[^A-Ha-h]", "", ans)) > 1 else "single",
        })

    q, opts, qline = "", [], 0
    for i, line in enumerate(lines):
        if not line:
            continue
        if "|" in line and re.search(r"答案|answer", line, re.I):
            # 单行格式
            parts = [p.strip() for p in line.split("|") if p.strip()]
            ans = ""
            body = []
            for p in parts:
                m = re.match(r"^(?:答案|answer)[:：\s]*(.+)$", p, re.I)
                if m:
                    ans = m.group(1)
                else:
                    body.append(p)
            if body and ans:
                finalize(body[0], body[1:], ans, i + 1)
            else:
                errors.append(f"第{i+1}行：单行格式不完整，已跳过")
            continue
        m = re.match(r"^(?:答案|answer)[:：\s]*(.+)$", line, re.I)
        if m:
            finalize(q, opts, m.group(1), qline or i + 1)
            q, opts, qline = "", [], 0
            continue
        mo = re.match(r"^([A-Ha-h])[.．、:：)）]\s*(.+)$", line)
        if mo and q:
            opts.append(mo.group(2).strip())
        elif mo and not q:
            q = line          # 少见：题干本身以字母开头
        else:
            if q and opts:    # 新题开始但上一题没答案 → 报错
                errors.append(f"第{i+1}行前：题「{q[:20]}…」缺「答案：」行，已跳过")
                q, opts = line, []
                qline = i + 1
            elif q:
                q += " " + line
            else:
                q, qline = line, i + 1
    if q and not opts and not errors:
        errors.append(f"末尾题「{q[:20]}…」缺「答案：」行，已跳过")
    return entries, errors


def import_bank(text: str) -> tuple[int, int, list[str]]:
    """导入题库，返回 (新增, 更新, 错误)。"""
    entries, errors = parse_bank_text(text)
    added = updated = 0
    with _KB_LOCK:
        for e in entries:
            key = q_key(e["question"], "\n".join(e["options"]))
            if not key:
                continue
            if key in BANK:
                updated += 1
            else:
                added += 1
            BANK[key] = {
                "answer": e["answer"], "options": e["options"],
                "qtype": e["qtype"], "ts": time.time(),
                "hits": BANK.get(key, {}).get("hits", 0),
            }
        if entries:
            _save_json_map(BANK_PATH, BANK)
    return added, updated, errors


def add_correction(question: str, answer: str, options_text: str = "",
                   qtype: str = "single", note: str = "") -> bool:
    key = q_key(question, options_text)
    if not key or not (answer or "").strip():
        return False
    with _KB_LOCK:
        CORRECTIONS[key] = {
            "answer": answer.strip(), "options": options_text or "",
            "qtype": qtype, "note": note, "ts": time.time(),
            "question": (question or "")[:80],
        }
        _save_json_map(CORRECTIONS_PATH, CORRECTIONS)
    return True


def del_correction(key: str) -> bool:
    with _KB_LOCK:
        if key in CORRECTIONS:
            CORRECTIONS.pop(key)
            _save_json_map(CORRECTIONS_PATH, CORRECTIONS)
            return True
    return False

# --------------------------------------------------------------------------- #
# 推理队列：同一时刻最多 max_concurrency 路推理，其余排队
# 本地大模型请保持 1（并发会抢显存，反而全部变慢）；
# 云端后端可设 2~4 提升吞吐（受厂商并发限制约束）。
# --------------------------------------------------------------------------- #
_SEM = threading.BoundedSemaphore(max(1, int(CFG.get("max_concurrency", 1))))
_WAIT_LOCK = threading.Lock()
_WAITING = 0


def _acquire() -> bool:
    global _WAITING
    with _WAIT_LOCK:
        if _WAITING >= CFG.get("max_queue", 32):
            return False
        _WAITING += 1
    try:
        _SEM.acquire(timeout=float(CFG.get("answer_budget", 50)))
        return True
    except Exception:
        with _WAIT_LOCK:
            _WAITING -= 1
        return False
    finally:
        # 拿到锁后立刻归还计数
        with _WAIT_LOCK:
            if _WAITING > 0:
                _WAITING -= 1


def _release():
    try:
        _SEM.release()
    except ValueError:
        pass


# --------------------------------------------------------------------------- #
# 节律控制（反机器特征）
# --------------------------------------------------------------------------- #
"""
为什么不是简单 time.sleep(0.5~1.5)：

简单 sleep 只保证"至少"间隔 0.5s，但上面有串行队列，第二题在排队时已经
"等"过了 3 秒推理。若它一拿到锁立刻返回，实际间隔是 0.05s —— 排队越久，
返回越密集，反而更像机器。

所以这里做的是"间隔补足"：
    目标间隔 T = U(500,1500)ms
    距上一题返回已经过去 E 秒
    还需要等 max(0, T - E)
并额外加一个上限保护 MAX_GAP：若上一题至今已超过 6s，就不再追加，
避免"很久没题 -> 突然连发"这种同样可疑的形态。

另外 GAP_MAX 用右偏分布（两次均匀取大），让 0.5~1.5s 之间的小间隔
少于 1.2~1.6s 的大间隔，更接近人的反应时间分布。
"""
_RHYTHM_LOCK = threading.Lock()
_last_release_ts: float | None = None
MAX_GAP_MS = int(CFG.get("max_gap_ms", 6000))   # 超过这个间隔就不再补时


def _sample_delay_ms() -> float:
    lo = float(CFG.get("delay_min_ms", 500))
    hi = float(CFG.get("delay_max_ms", 1500))
    if hi < lo:
        lo, hi = hi, lo
    if CFG.get("jitter_model", True):
        # 右偏：两次均匀取最大值，分布重心靠近 hi
        return max(random.uniform(lo, hi), random.uniform(lo, hi))
    return random.uniform(lo, hi)


def pace_gate(apply_delay: bool = True) -> float:
    """在"即将返回给 OCS"之前调用，补足到目标间隔。返回实际等待毫秒。"""
    global _last_release_ts
    if not CFG.get("human_delay", True) or not apply_delay:
        with _RHYTHM_LOCK:
            _last_release_ts = time.time()
        return 0.0

    target = _sample_delay_ms() / 1000.0
    with _RHYTHM_LOCK:
        now = time.time()
        already = 0.0 if _last_release_ts is None else now - _last_release_ts
        # 已经间隔够久（>=目标）：wait 自然为 0，不必特殊分支；
        # 这也覆盖了"很久没出题"的情况 —— 直接放行，不会叠加延时
        wait = max(0.0, target - already)
        # 占位到"预计返回时刻"，并发下多线程不会重复计算同一段时间
        _last_release_ts = now + wait

    if wait > 0:
        time.sleep(wait)
    # 返回前用真实时刻校正，避免 sleep 抖动累积
    with _RHYTHM_LOCK:
        _last_release_ts = time.time()
    return wait * 1000


# --------------------------------------------------------------------------- #
# 模型调用（Ollama 本地 / OpenAI 兼容云端，按 backend 分支）
# --------------------------------------------------------------------------- #
_CODE_SIGNS = (
    "```", "def ", "def(", "function ", "const ", "let ", "var ",
    "public class", "private ", "import ", "from ", "#include",
    "SELECT ", "INSERT ", "UPDATE ", "DELETE ", "CREATE TABLE",
    "print(", "console.log", "printf(", "System.out",
    "<html", "</div", "for (", "while (", "if (", "=>",
)


def is_code_question(title: str, options_text: str = "") -> bool:
    """粗筛代码题：题干/选项里出现代码特征。宁可误判到 code_model，也不放过。"""
    text = f"{title}\n{options_text}"
    return any(sig in text for sig in _CODE_SIGNS)


AVAILABLE_MODELS: list[str] = []   # 最近一次成功拉取到的模型列表（由自检/配置接口写入）


def _model_exists(m: str) -> bool | None:
    """模型是否在可用列表里。列表为空（还没拉到）时返回 None=未知，不做判断。"""
    if not m or not AVAILABLE_MODELS:
        return None
    return any(str(x).lower() == m.lower() for x in AVAILABLE_MODELS)


def _pick_model(images: list, title: str, options_text: str) -> str:
    """题型路由：图片题 → vision_model，代码题 → code_model，其余 → model。
    若配置的专用模型在当前后端不存在（如智谱里填了硅基流动的 Qwen），
    自动回落主模型，避免白白失败一轮。"""
    main = CFG.get("model") or CFG.get("fallback_model")
    if not CFG.get("auto_route", True):
        return main
    if images:
        vm = CFG.get("vision_model")
        if vm:
            if _model_exists(vm) is False:
                log.warning("vision_model「%s」在当前后端不存在，图片题回落主模型", vm)
                return main
            return vm
        log.warning("收到图片题但未配置 vision_model，退回主模型（可能看不懂图）")
        return main
    if is_code_question(title, options_text):
        cm = CFG.get("code_model")
        if cm:
            if _model_exists(cm) is False:
                log.warning("code_model「%s」在当前后端不存在，代码题回落主模型", cm)
                return main
            return cm
    return main


def _norm_image(img: str) -> tuple[str, str]:
    """把 OCS 传来的图片统一成 (data_url, 纯base64)。"""
    img = (img or "").strip()
    m = re.match(r"^data:([^;]+);base64,(.*)$", img, re.S)
    if m:
        return img, m.group(2)
    # 纯 base64：靠前缀猜 MIME（/9j/=jpeg，iVBOR=png，其余按 png 兜底）
    if img.startswith("/9j/"):
        return "data:image/jpeg;base64," + img, img
    return "data:image/png;base64," + img, img


def _build_request(prompt: str, model: str, use_think_flag: bool,
                   images: list[str] | None = None) -> tuple[str, dict, dict]:
    """构造请求 url / body / headers。返回 (url, json, headers)。"""
    backend = (CFG.get("backend") or "ollama").lower()
    headers = {"Content-Type": "application/json"}
    stop = ["\n题目", "\n选项", "\n【要求】"]

    if backend == "openai":
        base = (CFG.get("api_base") or "").rstrip("/")
        if not base:
            raise RuntimeError("云端后端未配置 api_base（config.json 或控制台里填）")
        if not base.endswith("/chat/completions"):
            base = base + "/chat/completions"
        key = CFG.get("api_key") or ""
        if key:
            headers["Authorization"] = f"Bearer {key}"

        content: object = prompt
        if images:
            # OpenAI 多模态格式：content 变为 text + image_url 数组
            parts = [{"type": "text", "text": prompt}]
            for img in images[:4]:                     # 最多带 4 张，防请求过大
                du, _ = _norm_image(img)
                parts.append({"type": "image_url", "image_url": {"url": du}})
            content = parts
        body = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "stream": False,
            "temperature": CFG.get("temperature", 0.0),
            "max_tokens": int(CFG.get("cloud_max_tokens", 256)),
            "stop": stop,
        }
        return base, body, headers

    # Ollama 本地 /api/generate
    p = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "keep_alive": CFG.get("keep_alive", "30m"),
        "options": {
            "temperature": CFG.get("temperature", 0.0),
            "num_ctx": CFG.get("num_ctx", 4096),
            "num_predict": CFG.get("num_predict", 256),
            "seed": CFG.get("seed", 42),
            "stop": stop,
        },
    }
    if images:
        # Ollama 视觉模型（llava / qwen2.5vl 等）原生接受纯 base64 数组
        p["images"] = [_norm_image(i)[1] for i in images[:4]]
    if use_think_flag:
        p["think"] = False   # 新版 Ollama 支持；旧版会忽略此字段
    return CFG.get("ollama_url"), p, headers


def _extract_text(data: dict) -> tuple[str, str]:
    """从响应 JSON 提取 (正文, 思考链)。两者分开返回，由调用方分别清洗——
    避免思考链混进正文导致填空题答案里带「让我想一想」这类内容。"""
    backend = (CFG.get("backend") or "ollama").lower()
    if backend == "openai":
        try:
            msg = data["choices"][0]["message"] or {}
        except (KeyError, IndexError, TypeError):
            return "", ""
        content = msg.get("content") or ""
        # 部分云端把思考链放独立字段（GLM-4.5 / Qwen3 思考模式）
        think = msg.get("reasoning_content") or msg.get("reasoning") or ""
        return content, think
    raw = data.get("response", "") or ""
    think = data.get("thinking", "") or ""
    return raw, think


def _truncated(data: dict) -> bool:
    """判断本次响应是否被 token 上限截断（OpenAI finish_reason / Ollama done_reason）。"""
    try:
        ch = (data.get("choices") or [{}])[0]
        if ch.get("finish_reason") == "length":
            return True
    except Exception:
        pass
    return data.get("done_reason") == "length"


def _boost_tokens() -> bool:
    """遭遇截断时临时把 token 上限放大（2 倍，上限 4096），本次生效。
    思考型模型（GLM-5 / Qwen3 思考）在小额度下会把额度全花在思考链上，
    正文被截空——自动扩容比让用户改配置更省事。"""
    with _CFG_LOCK:
        cur = int(CFG.get("cloud_max_tokens", 256))
        if cur >= 4096:
            return False
        CFG["cloud_max_tokens"] = min(4096, max(cur * 2, 1024))
        CFG["num_predict"] = max(int(CFG.get("num_predict", 256)), CFG["cloud_max_tokens"])
        log.info("token 上限自动扩容：%d → %d（仅本次运行生效，可控制台持久化）", cur, CFG["cloud_max_tokens"])
    return True


def call_model(prompt: str, deadline: float | None = None,
               images: list[str] | None = None,
               preferred_model: str | None = None) -> tuple[str, str, float]:
    """
    返回 (清洗后答案, 使用的模型, 推理耗时)。失败抛异常。
    deadline: 绝对时间戳，整题预算的截止点。每次尝试的超时都会按剩余时间收缩，
              保证最坏重试 3 次也不会突破 OCS 的 60s 上限。
    preferred_model: 题型路由选出的主模型（图片/代码题可能是 vision/code 模型）。
    """
    timeout = float(CFG.get("request_timeout", 100))
    first = preferred_model or CFG.get("model") or CFG.get("fallback_model")
    t0 = time.time()

    # 降级链：路由模型 → 关思考字段 → 关字段重试 → 主模型兜底 → fallback
    attempts = [(first, True), (first, False)]
    main = CFG.get("model") or first
    if main != first:
        attempts.append((main, True))
    fb = CFG.get("fallback_model")
    if fb and fb not in (first, main):
        attempts.append((fb, True))

    last_err = None
    for idx, (m, use_think) in enumerate(attempts):
        # 按剩余预算收缩超时；剩余不足 3s 就放弃后续尝试，保证能按时返回
        per_timeout = timeout
        if deadline is not None:
            remain = deadline - time.time()
            if remain < 3:
                log.warning("整题预算耗尽，放弃剩余重试")
                break
            # 剩余时间在剩下的尝试间平分
            left_attempts = len(attempts) - idx
            per_timeout = min(timeout, max(3.0, remain / left_attempts * 1.5))
        try:
            url, body, headers = _build_request(prompt, m, use_think, images)
            r = requests.post(url, json=body, headers=headers, timeout=per_timeout)
            if r.status_code >= 400:
                if r.status_code == 429:
                    last_err = RuntimeError(
                        "云端限流（HTTP 429，请求太频繁）：免费档有每分钟请求数上限，"
                        "请放慢答题节奏（OCS 里调大答题间隔）或稍等 1 分钟重试"
                    )
                    log.warning("云端限流 429 (model=%s)", m)
                    break            # 限流时换模型也没用，直接停止重试
                last_err = RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
                log.warning("模型返回 %s (model=%s, think=%s)", r.status_code, m, use_think)
                continue
            data = r.json()
            content, think = _extract_text(data)
            ans = clean_answer(content)
            if not ans and think:
                if _truncated(data):
                    # 思考链吃满了 token 额度，正文还没开始就被截断：
                    # 自动放大 token 上限重试一次，而不是直接报"输出为空"
                    log.info("模型被截断（思考链占满 %s tokens），自动扩容重试",
                             body.get("max_tokens") or CFG.get("cloud_max_tokens"))
                    if _boost_tokens():
                        try:
                            url2, body2, headers2 = _build_request(prompt, m, use_think, images)
                            remain2 = (deadline - time.time()) if deadline else 30
                            if remain2 > 5:
                                r2 = requests.post(url2, json=body2, headers=headers2,
                                                   timeout=max(3.0, remain2))
                                if r2.status_code < 400:
                                    content, think = _extract_text(r2.json())
                                    ans = clean_answer(content) or clean_answer(think)
                        except Exception as e:
                            log.warning("扩容重试失败: %s", e)
                if not ans:
                    ans = clean_answer(think)   # 正文没答案时才看思考链（R1 等深链模型）
            if ans:
                return ans, m, time.time() - t0
            last_err = RuntimeError(
                "模型输出为空（多为 token 上限太小被截断）。"
                "请在控制台把「云端 token 上限」调大，或关闭 CoT 先推理模式"
            )
        except requests.exceptions.Timeout:
            last_err = RuntimeError(
                f"模型推理超时（整题预算 {CFG.get('answer_budget', 50)}s 内未完成）。"
                "本地 7B 纯 CPU 每题约 20~60s，建议换小模型 / 上 GPU / 改用云端后端"
            )
            log.warning("模型超时 (model=%s)", m)
        except requests.exceptions.ConnectionError as e:
            backend = (CFG.get("backend") or "ollama").lower()
            if backend == "openai":
                last_err = RuntimeError(
                    f"云端服务连不上（{CFG.get('api_base')}），请检查网络或 api_base 拼写"
                )
                log.error("无法连接云端模型服务: %s", CFG.get("api_base"))
            else:
                last_err = RuntimeError(
                    f"Ollama 未启动或端口不通（{CFG['ollama_url']}），请先打开右下角小羊图标"
                )
                log.error("无法连接 Ollama，请确认右下角小羊图标已运行")
            log.debug("详细错误: %s", e)
            break  # 连不上就没必要重试其它模型
        except Exception as e:
            last_err = RuntimeError(str(e))
            log.warning("模型调用异常: %s", e)

    raise last_err or RuntimeError("未知错误")


# --------------------------------------------------------------------------- #
# 核心：答题
# --------------------------------------------------------------------------- #
def _qlog(text, limit: int = 24) -> str:
    """日志里显示题目/答案。privacy_log 开启时打码，防止公用电脑留痕（#8）。"""
    s = (text or "")[:limit]
    if CFG.get("privacy_log") and s:
        s = s[:2] + "…" + "*" * max(1, len(s) - 2)
    return s


def _record_answer(result: dict, cached: bool):
    with ANSWER_LOCK:
        STATS["total"] += 1
        if cached:
            STATS["cache"] += 1
        if result.get("success"):
            STATS["success"] += 1
        else:
            STATS["fail"] += 1
        ANSWER_RING.append({
            "t": time.strftime("%H:%M:%S"),
            "q": (result.get("question") or "")[:60],
            "a": (result.get("answer") or "")[:40],
            "match": result.get("match") or "-",
            "cached": cached,
            "ok": bool(result.get("success")),
            "cost": result.get("cost"),
            "pace": result.get("pace_wait_ms"),
        })


def _letters_of(final: str, opts: list[dict]) -> str:
    """把答案文本反解为选项字母组合，用于交叉验证比对。"""
    if not final:
        return ""
    picked = []
    for o in opts:
        no, nf = _norm(o["text"]), None
        for part in re.split(r"[\n|]", final):
            np_ = _norm(part)
            if np_ and no and (np_ == no or np_ in no or no in np_):
                nf = o["letter"]
                break
        if nf:
            picked.append(nf)
    if picked:
        return "".join(sorted(picked))
    # 答案本身就是字母（如 "AC"）
    letters = re.sub(r"[^A-Ha-h]", "", final).upper()
    return "".join(sorted(letters)) if letters else _norm(final)[:20]


def _same_answer(a: str, b: str, opts: list[dict]) -> bool:
    """两个答案是否等价（字母组合或规范化文本一致）。"""
    if not a or not b:
        return False
    la, lb = _letters_of(a, opts), _letters_of(b, opts)
    if la and lb:
        return la == lb
    return _norm(a) == _norm(b)


def answer_question(title: str, options_text, qtype: str = "unknown",
                    images: list[str] | None = None,
                    suggestion: str = "") -> dict:
    total_t0 = time.time()
    images = images or []
    opts = split_options(options_text)

    # ---- 第 0 优先级：人工订正 > 导入题库（命中不耗模型、不受换模型影响） ----
    bank_ans, bank_src = bank_lookup(title, options_text, images)
    if bank_ans is not None:
        final, form, note = match_option(bank_ans, opts)
        if not final:                       # 订正答案没匹配上选项时原样给
            final, form, note = bank_ans, "raw", "原样返回"
        waited = pace_gate(True)
        result = {
            "question": title, "answer": final, "raw_answer": bank_ans,
            "options": [o["text"] for o in opts], "letters": [o["letter"] for o in opts],
            "match": form, "note": f"来源：{bank_src}", "model": bank_src,
            "has_images": False, "route": "bank", "cost": 0,
            "pace_wait_ms": round(waited), "total": round(time.time() - total_t0, 2),
            "cached": False, "success": bool(final),
        }
        log.info("Q: %s | A: %s (%s 命中, 节律%.0fms)",
                 _qlog(title), _qlog(final, 30), bank_src, waited)
        _record_answer(result, cached=False)
        return result

    flat_title = re.sub(r"\s+", "", title)
    flat_opts = "|".join(o["text"] for o in opts)
    # 图片参与缓存 key（同一题干不同图可能是不同题），用长度+摘要避免 key 过长；
    # 后端/模型也计入（#3），换模型后不会被旧缓存骗到
    img_sig = ""
    if images:
        joined = "|".join(images)
        img_sig = f"|img{len(images)}:{hashlib.md5(joined.encode()).hexdigest()[:10]}"
    route_sig = f"|{CFG.get('backend')}|{CFG.get('model')}"
    cache_key = f"{qtype}|{flat_title}|{flat_opts}{img_sig}{route_sig}"

    hit = CACHE.get(cache_key)
    if hit:
        # 缓存虽然秒回，也要遵守节律：否则同一道题 2ms 就出答案，一眼就是机器
        waited = pace_gate(CFG.get("delay_on_cache", True))
        log.info("Q: %s | A: %s (缓存命中, 节律等待 %.0fms)",
                 _qlog(title), _qlog(hit.get("answer"), 30), waited)
        out = {**hit, "cached": True, "pace_wait_ms": round(waited)}
        _record_answer(out, cached=True)
        return out

    if not _acquire():
        pace_gate(True)
        return {
            "question": title, "answer": "", "success": False,
            "error": "队列已满或等待超时", "cached": False,
        }
    try:
        prompt = build_prompt(title, opts, qtype,
                              preset=CFG.get("prompt_preset", "default"),
                              cot=bool(CFG.get("cot_mode")))
        if suggestion:
            # OCS 5.x 图片题附带的文字提示（如网页里题目周边文本），拼进题干帮助理解
            prompt = f"{prompt}\n【题目周边提示】\n{suggestion}\n答案："
        budget = float(CFG.get("answer_budget", 50))
        route_model = _pick_model(images, title, options_text)
        route_kind = ("image" if (images and route_model == (CFG.get("vision_model") or CFG.get("model")))
                      else "code" if (not images and route_model == (CFG.get("code_model") or CFG.get("model"))
                                      and is_code_question(title, options_text))
                      else "text" if not images else "image-fallback")
        raw_ans, model, cost = call_model(
            prompt, deadline=total_t0 + budget,
            images=images, preferred_model=route_model,
        )
        final, form, note = match_option(raw_ans, opts)
        # 路由模型没能出答案时，明确提示实际兜底情况（#5）
        if final and route_model != model:
            note = (note + "；" if note else "") + f"路由模型 {route_model} 未成功，由 {model} 兜底"

        # ---- 双模型交叉验证（verify_mode: fast=复核标注 / full=仲裁） ----
        verify = ""
        vmode = (CFG.get("verify_mode") or "off").lower()
        if vmode in ("fast", "full") and final and opts and not images:
            vmodel = (CFG.get("verify_model") or CFG.get("fallback_model")
                      or CFG.get("model") or "")
            remain = total_t0 + budget - time.time()
            if vmodel and vmodel != model and remain > 12:
                try:
                    raw2, m2, c2 = call_model(
                        prompt, deadline=total_t0 + budget,
                        preferred_model=vmodel)
                    final2, _, _ = match_option(raw2, opts)
                    if _same_answer(final, final2, opts):
                        verify = "agree"
                        note = (note + "；" if note else "") + "双模型交叉验证一致（高置信）"
                    else:
                        if vmode == "full":
                            arb = (CFG.get("arbitrate_model") or "").strip()
                            if arb and arb not in (model, vmodel):
                                try:
                                    raw3, m3, c3 = call_model(
                                        prompt, deadline=total_t0 + budget,
                                        preferred_model=arb)
                                    final3, _, _ = match_option(raw3, opts)
                                    cost += c3
                                    if final3 and _same_answer(final3, final2, opts):
                                        final, raw_ans, model = final3, raw3, m3
                                        verify = "arbitrated"
                                        note = (note + "；" if note else "") + \
                                            f"两个模型不一致，经 {m3} 仲裁后采用仲裁答案"
                                    else:
                                        verify = "conflict"
                                        note = (note + "；" if note else "") + \
                                            "双模型不一致且仲裁未定（低置信），建议人工核对"
                                except Exception:
                                    verify = "conflict"
                                    note = (note + "；" if note else "") + "双模型不一致（低置信），建议人工核对"
                            else:
                                verify = "conflict"
                                note = (note + "；" if note else "") + \
                                    "双模型不一致（低置信）；配置 arbitrate_model 可开启仲裁"
                        else:
                            verify = "conflict"
                            note = (note + "；" if note else "") + \
                                f"复核模型 {m2} 答案不同（低置信），建议人工核对"
                except Exception as e:
                    log.info("交叉验证复核失败（不影响主答案）：%s", e)
            elif vmodel and remain <= 12:
                log.info("剩余预算不足，跳过交叉验证")

        # 在返回前补足节律间隔（不是在此之前 sleep，见 pace_gate 注释）
        waited = pace_gate(True)

        result = {
            "question": title,
            "answer": final,
            "raw_answer": raw_ans,
            "options": [o["text"] for o in opts],
            "letters": [o["letter"] for o in opts],
            "match": form,
            "note": note,
            "model": model,
            "has_images": bool(images),
            "route": route_kind,
            "cost": round(cost, 2),
            "pace_wait_ms": round(waited),
            "total": round(time.time() - total_t0, 2),
            "cached": False,
            "verify": verify,
            "success": bool(final),
        }
        if final:
            CACHE.set(cache_key, result)
        _record_answer(result, cached=False)
        log.info(
            "Q: %s | A: %s (%s/%s, %s, 推理%.1fs + 节律%.0fms)%s",
            _qlog(title), _qlog(final, 30) or "<空>", route_kind, form, model,
            cost, waited,
            "" if form != "raw" else "  ← 未匹配到选项，原样返回",
        )
        return result
    finally:
        _release()


# --------------------------------------------------------------------------- #
# HTTP 路由
# --------------------------------------------------------------------------- #
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, HEAD, OPTIONS",
    "Access-Control-Allow-Headers": "*",
    "Access-Control-Max-Age": "86400",
}


@app.after_request
def add_cors(resp):
    for k, v in CORS_HEADERS.items():
        resp.headers[k] = v
    return resp


@app.before_request
def check_auth():
    """访问令牌鉴权（#1 安全）：config 里 auth_token 非空时，所有接口
    （除 /api/health）必须携带令牌，三选一：
      1. 请求头  X-Relay-Token: <token>     （OCS 题库配置用这种）
      2. URL参数 ?token=<token>             （浏览器直接访问用这种）
      3. Cookie  relay_token=<token>        （控制台记住后自动带）
    """
    tok = (CFG.get("auth_token") or "").strip()
    if not tok:
        return None                      # 未启用鉴权
    if request.path in ("/api/health",):
        return None                      # 健康检查豁免，便于探测
    got = (request.headers.get("X-Relay-Token")
           or request.args.get("token")
           or request.cookies.get("relay_token") or "")
    if got != tok:
        return jsonify({
            "error": "unauthorized",
            "hint": "需要访问令牌：请求头 X-Relay-Token，或 URL 加 ?token=...",
        }), 401
    return None


def _parse_request() -> tuple[str, str, str, list[str], str]:
    """
    从 GET query / POST json / POST form 中提取题目信息。
    返回 (title, options, type, images, suggestion)。
    images: OCS 5.x 图片题优化字段（base64 或 data URL 数组，用 handler 解析器传入）。
    suggestion: OCS 附带的题目文字提示（suggestion_title / suggestion_options 拼接）。
    """
    data = {}
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        if not data:
            data = request.form.to_dict()
    if not data:
        data = request.args.to_dict()

    title = data.get("title") or data.get("question") or data.get("q") or ""
    options = data.get("options") or data.get("option") or ""
    if isinstance(options, (list, tuple)):
        options = "\n".join(str(x) for x in options)
    qtype = data.get("type") or data.get("qtype") or "unknown"

    # 图片题：OCS 通过 {"handler": "return (env) => env.images"} 传入的 base64 数组
    images = data.get("images") or []
    if isinstance(images, str):
        images = [images] if images.strip() else []
    elif isinstance(images, dict):
        # 有的配置写成 {"images": [...]} 嵌套，做一次兼容
        images = images.get("list") or images.get("urls") or []
    images = [str(x).strip() for x in images if str(x).strip()][:8]

    # 文字辅助字段（OCS 5.x suggestion）
    st = str(data.get("suggestion_title") or "").strip()
    so = str(data.get("suggestion_options") or "").strip()
    parts = [x for x in (st, so) if x]
    suggestion = "\n".join(parts)

    return str(title).strip(), str(options), str(qtype), images, suggestion


def _handle():
    title, options, qtype, images, suggestion = _parse_request()
    if not title and not images:
        # OCS 探测/健康检查：直接 200，避免卡片显示"连接失败"
        return jsonify({
            "status": "ok",
            "service": "ocs-ollama-relay",
            "model": CFG.get("model"),
            "vision_model": CFG.get("vision_model") or None,
            "hint": "这是健康检查响应，请通过 POST 传 title / options（图片题另传 images）",
        })

    try:
        return jsonify(answer_question(title, options, qtype, images, suggestion))
    except Exception as e:
        log.exception("处理异常")
        # 失败也走节律，避免"秒失败"成为特征
        try:
            pace_gate(True)
        except Exception:
            pass
        return jsonify({
            "question": title, "answer": "", "success": False, "error": str(e),
        }), 200   # 仍返回 200，OCS 才能在 handler 里拿到 error 字段


@app.route("/api/qa", methods=["GET", "POST", "HEAD", "OPTIONS"])
def api_qa():
    if request.method == "OPTIONS":
        return "", 204
    if request.method == "HEAD":
        return "", 200
    return _handle()


def _ocs_snippet() -> str:
    """生成可直接粘贴到 OCS 的题库配置（端口跟随当前设置，含图片题字段；
    启用访问令牌时自动带上 X-Relay-Token 请求头）。"""
    port = int(CFG.get("port", 5000))
    entry = {
        "name": "本地AI中转",
        "homepage": f"http://127.0.0.1:{port}/",
        "url": f"http://127.0.0.1:{port}/api/qa",
        "method": "post",
        "type": "GM_xmlhttpRequest",
        "contentType": "json",
        "responseType": "json",
        "data": {
            "title": "${title}",
            "options": "${options}",
            "type": "${type}",
            # OCS 5.x 图片题：必须用 handler 解析器，且仅 POST 下生效
            "images": {"handler": "return (env) => env.images || []"},
            "suggestion_title": "${suggestion_title}",
            "suggestion_options": "${suggestion_options}",
        },
        "handler": "return (res) => [res.question, res.answer]",
    }
    tok = (CFG.get("auth_token") or "").strip()
    if tok:
        entry["headers"] = {"X-Relay-Token": tok}
    return json.dumps([entry], ensure_ascii=False, indent=2)


@app.route("/", methods=["GET", "HEAD"])
def index():
    """浏览器打开根路径 = 控制台。"""
    if request.method == "HEAD":
        return "", 200
    return CONSOLE_HTML


@app.route("/api/status", methods=["GET"])
def api_status():
    """控制台轮询：状态 + 统计 + 最近答题 + 增量日志。"""
    try:
        since = int(request.args.get("log_since", 0))
    except Exception:
        since = 0
    with LOG_LOCK:
        logs_all = list(LOG_RING)
    seq = _LOG_SEQ[0]
    logs = [{"i": l.get("i"), **l} for l in logs_all if l.get("i", 0) > since]

    with ANSWER_LOCK:
        answers = list(ANSWER_RING)
        stats = dict(STATS)

    return jsonify({
        "version": APP_VERSION,
        "ollama": _OLLAMA_STATE["ok"],
        "model": CFG.get("model"),
        "stats": stats,
        "answers": answers,
        "logs": logs,
        "log_seq": seq,
        "queue_waiting": _WAITING,
        "cache_size": len(CACHE),
    })


@app.route("/api/config", methods=["GET"])
def api_config_get():
    models = []
    try:
        models = [m["name"] for m in list_ollama_models(timeout=3)]
    except Exception:
        pass
    if models:
        AVAILABLE_MODELS[:] = models     # 供题型路由判断专用模型是否存在
    safe = {k: CFG.get(k) for k in DEFAULT_CONFIG}
    # 敏感值脱敏（#4）：密钥/令牌只回掩码，F12 也看不到明文
    for k in ("api_key", "auth_token"):
        v = safe.get(k)
        if v:
            safe[k] = "***" + str(v)[-4:]
    return jsonify({"config": safe, "models": models, "ocs_snippet": _ocs_snippet()})


@app.route("/api/config", methods=["POST"])
def api_config_post():
    data = request.get_json(silent=True) or {}
    ok, msg = save_config(data)
    return jsonify({"ok": ok, "message": msg})


# --------------------------- 题库与人工订正 API --------------------------- #

@app.route("/api/bank", methods=["GET"])
def api_bank_get():
    return jsonify({
        "enabled": bool(CFG.get("bank_enabled", True)),
        "count": len(BANK),
        "corrections": len(CORRECTIONS),
        "sample": list(BANK.values())[:3],
    })


@app.route("/api/bank", methods=["POST"])
def api_bank_import():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"ok": False, "message": "text 为空"}), 400
    added, updated, errors = import_bank(text)
    return jsonify({
        "ok": True, "added": added, "updated": updated,
        "errors": errors[:10], "total": len(BANK),
        "message": f"导入完成：新增 {added} 条，更新 {updated} 条"
                   + (f"，{len(errors)} 条格式有误被跳过" if errors else ""),
    })


@app.route("/api/bank", methods=["DELETE"])
def api_bank_clear():
    with _KB_LOCK:
        BANK.clear()
        _save_json_map(BANK_PATH, BANK)
    return jsonify({"ok": True, "message": "题库已清空"})


@app.route("/api/corrections", methods=["GET"])
def api_corr_get():
    """返回已存订正 + 最近 20 条答题记录（供控制台勾选订正）。"""
    with ANSWER_LOCK:
        recent = list(ANSWER_RING)[-20:][::-1]
    return jsonify({
        "corrections": [
            {"key": k, **{kk: v.get(kk) for kk in ("answer", "note", "hits", "question")}}
            for k, v in list(CORRECTIONS.items())[::-1][:50]
        ],
        "recent": recent,
    })


@app.route("/api/corrections", methods=["POST"])
def api_corr_add():
    data = request.get_json(silent=True) or {}
    q = (data.get("question") or "").strip()
    a = (data.get("answer") or "").strip()
    if not q or not a:
        return jsonify({"ok": False, "message": "题目与订正答案都不能为空"}), 400
    ok = add_correction(q, a, data.get("options", ""),
                        data.get("qtype", "single"), data.get("note", ""))
    if not ok:
        return jsonify({"ok": False, "message": "写入失败"}), 400
    log.info("人工订正：%s -> %s", _qlog(q), _qlog(a, 30))
    return jsonify({"ok": True, "message": "订正已保存，此题以后直接返回人工答案"})


@app.route("/api/corrections", methods=["DELETE"])
def api_corr_del():
    key = request.args.get("key", "")
    ok = del_correction(key)
    return jsonify({"ok": ok, "message": "已删除" if ok else "未找到该订正记录"})


@app.route("/api/diagnose", methods=["GET"])
def api_diagnose():
    try:
        return jsonify(diagnose())
    except Exception as e:
        log.exception("自检异常")
        return jsonify({"items": [{"id": "err", "label": "自检", "status": "fail",
                                   "detail": str(e), "fix": None, "hint": ""}],
                        "summary": {"ok": 0, "warn": 0, "fail": 1}, "models": []})


@app.route("/api/fix", methods=["POST"])
def api_fix():
    action = (request.get_json(silent=True) or {}).get("action", "")
    ok, msg = apply_fix(action)
    return jsonify({"ok": ok, "message": msg})


@app.route("/api/health", methods=["GET", "HEAD", "OPTIONS"])
def health():
    if request.method == "OPTIONS":
        return "", 204
    if request.method == "HEAD":
        return "", 200
    ok, detail = ping_ollama()
    return jsonify({
        "service": "ocs-ollama-relay",
        "version": APP_VERSION,
        "ollama": ok,
        "detail": detail,
        "model": CFG.get("model"),
        "cache": len(CACHE),
        "queue_waiting": _WAITING,
        "pace": (f"{CFG.get('delay_min_ms')}~{CFG.get('delay_max_ms')}ms"
                 if CFG.get("human_delay", True) else "已关闭"),
    })


# --------------------------------------------------------------------------- #
# 健康探测 + 预热
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# 自检引擎
# --------------------------------------------------------------------------- #
def _ollama_base() -> str:
    return CFG["ollama_url"].rsplit("/api/", 1)[0]


def list_ollama_models(timeout: float = 4.0) -> list[dict]:
    """返回 [{'name':..., 'size':bytes}, ...]；连接失败抛异常。按 backend 适配。"""
    backend = (CFG.get("backend") or "ollama").lower()
    out = []
    if backend == "openai":
        # OpenAI 兼容端点：GET {base}/models
        base = (CFG.get("api_base") or "").rstrip("/")
        if base.endswith("/chat/completions"):
            base = base[: -len("/chat/completions")]
        if not base:
            raise RuntimeError("云端后端未配置 api_base")
        headers = {}
        if CFG.get("api_key"):
            headers["Authorization"] = f"Bearer {CFG['api_key']}"
        r = requests.get(f"{base}/models", headers=headers, timeout=timeout)
        r.raise_for_status()
        for m in r.json().get("data", []):
            out.append({"name": m.get("id", ""), "size": 0})
        return out
    r = requests.get(f"{_ollama_base()}/api/tags", timeout=timeout)
    r.raise_for_status()
    for m in r.json().get("models", []):
        out.append({"name": m.get("name", ""), "size": m.get("size", 0)})
    return out


def _model_matches(want: str, installed: str) -> bool:
    """qwen2.5:7b-instruct 与 qwen2.5:7b-instruct-q4_K_M 视为同一模型。"""
    if not want or not installed:
        return False
    w, i = want.strip().lower(), installed.strip().lower()
    if w == i:
        return True
    if ":" not in w and i.split(":")[0] == w:
        return True
    return i.startswith(w)


def _port_free(host: str, port: int) -> tuple[bool, str]:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.6)
    try:
        # 能连上说明端口已被占用
        if s.connect_ex((host if host not in ("0.0.0.0", "") else "127.0.0.1", port)) == 0:
            return False, "端口已被占用"
        return True, "端口空闲"
    finally:
        s.close()


def _who_uses_port(port: int) -> str:
    """尽力找出占用端口的进程名（仅 Windows）。"""
    if os.name != "nt":
        return ""
    try:
        import subprocess
        out = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
        pids = set()
        for line in out.splitlines():
            if f":{port} " in line and "LISTENING" in line.upper():
                pids.add(line.split()[-1])
        if not pids:
            return ""
        names = []
        for pid in list(pids)[:3]:
            t = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ).stdout.strip()
            if t and "," in t:
                names.append(t.split(",")[0].strip('"'))
        return "、".join(dict.fromkeys(names))
    except Exception:
        return ""


def diagnose(deep: bool = False) -> dict:
    """
    逐项自检。返回 {items:[{id,label,status,detail,fix,fixed}], summary:{...}}
    status: ok / warn / fail；fix 为可执行的修复动作 id（前端显示按钮）
    """
    items: list[dict] = []

    def add(id_, label, status, detail, fix=None, hint=""):
        items.append({"id": id_, "label": label, "status": status,
                      "detail": detail, "fix": fix, "hint": hint})

    # 1 运行环境
    py = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info < (3, 8):
        add("python", "运行环境", "fail", f"Python {py} 版本过低", None, "需要 3.8 或更高")
    else:
        add("python", "运行环境", "ok",
            f"Python {py}" if not getattr(sys, "frozen", False) else "已打包为独立程序")

    # 2 模型服务（Ollama 本地 / 云端）
    backend = (CFG.get("backend") or "ollama").lower()
    svc_label = "云端服务" if backend == "openai" else "Ollama 服务"
    models = []
    try:
        models = list_ollama_models()
        where = CFG.get("api_base") if backend == "openai" else _ollama_base()
        add("ollama", svc_label, "ok", f"已连接（{where}），{len(models)} 个模型")
    except Exception as e:
        if backend == "openai":
            msg = f"云端连不上：{str(e)[:60]}"
            add("ollama", svc_label, "fail", msg, None,
                "请检查 api_base / api_key / 网络（云端不支持自动拉起）")
        else:
            msg = "无法连接"
            if isinstance(e, requests.exceptions.ConnectionError):
                msg = f"未启动或端口不通（{_ollama_base()}）"
            add("ollama", svc_label, "fail", msg, "start_ollama",
                "点击修复将尝试自动启动 Ollama")

    # 3 主模型
    want = CFG.get("model", "")
    if not models:
        add("model", "主模型", "warn", f"无法检查（{svc_label}未连接）")
    else:
        names = [m["name"] for m in models]
        hit = next((n for n in names if _model_matches(want, n)), None)
        if hit:
            size = next((m["size"] for m in models if m["name"] == hit), 0)
            gb = f"，{size/1024**3:.1f}GB" if size else ""
            add("model", "主模型", "ok", f"{hit} 已就绪{gb}")
        elif backend == "openai":
            add("model", "主模型", "fail", f"云端无 {want}",
                None, "请确认模型 id 拼写（如 glm-4.5-flash / Qwen/Qwen3-8B），或去控制台改")
        else:
            add("model", "主模型", "fail", f"未找到 {want}",
                "pull_model", "点击修复将自动执行 ollama pull（需联网下载数 GB）")
        # 备用模型只提示
        fb = CFG.get("fallback_model", "")
        if fb:
            if any(_model_matches(fb, n) for n in names):
                add("fallback", "备用模型", "ok", f"{fb} 已就绪")
            elif backend == "openai":
                add("fallback", "备用模型", "warn", f"云端无 {fb}（可选，不影响使用）")
            else:
                add("fallback", "备用模型", "warn", f"未安装 {fb}（可选，不影响使用）", "pull_fallback")

    # 4 端口：本程序已在监听该端口 = 正常；连不上才说明出问题
    port = int(CFG.get("port", 5000))
    listening, _ = _port_free("127.0.0.1", port)
    if not listening:
        add("port", "服务端口", "ok", f"{port} 正在监听，服务正常")
    else:
        owner = _who_uses_port(port)
        add("port", "服务端口", "fail",
            f"{port} 未在监听，服务可能已停止" + (f"（占用者：{owner}）" if owner else ""),
            "change_port", "点击修复将改用其它空闲端口（需重启）")
    # 5 整题预算必须小于 OCS 的 60s
    budget = int(CFG.get("answer_budget", 50))
    if budget >= 58:
        add("budget", "时间预算", "fail", f"整题预算 {budget}s 过大，会被 OCS 60s 超时截断",
            None, "请调小到 50s 以下")
    else:
        add("budget", "时间预算", "ok", f"整题预算 {budget}s（OCS 上限 60s）")

    # 6 配置文件
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                json.load(f)
            add("config", "配置文件", "ok", os.path.basename(CONFIG_PATH))
        except Exception as e:
            add("config", "配置文件", "fail", f"内容损坏：{str(e)[:60]}", "reset_config",
                "点击修复将用默认配置重建（原文件会备份）")
    else:
        add("config", "配置文件", "warn", "不存在，当前使用默认值", "reset_config")

    # 7 目录可写（配置写回需要）
    try:
        probe = os.path.join(BASE_DIR, ".write_test")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("1")
        os.remove(probe)
        add("writable", "目录权限", "ok", "可写入配置")
    except Exception as e:
        add("writable", "目录权限", "fail", f"不可写：{str(e)[:50]}",
            None, "请把程序放到有写权限的目录（不要放 C:\\Program Files）")

    # 8 题型路由（图片/代码题的模型配置提示）
    if CFG.get("auto_route", True):
        vm, cm = CFG.get("vision_model"), CFG.get("code_model")
        if not vm:
            add("route", "题型路由", "warn", "未配置视觉模型，图片题将走主模型（可能答不对）",
                None, "控制台填 vision_model，如 glm-4v-flash（智谱免费）或本地 qwen2.5vl:7b")
        else:
            cm_txt = f"，代码题 → {cm}" if cm else "，代码题 → 主模型"
            add("route", "题型路由", "ok", f"图片题 → {vm}{cm_txt}")
    else:
        add("route", "题型路由", "warn", "已关闭自动路由，所有题都走主模型")

    fails = sum(1 for i in items if i["status"] == "fail")
    warns = sum(1 for i in items if i["status"] == "warn")
    return {
        "items": items,
        "summary": {"ok": len(items) - fails - warns, "warn": warns, "fail": fails},
        "models": [m["name"] for m in models],
    }


def apply_fix(action: str) -> tuple[bool, str]:
    """执行一键修复。返回 (成功?, 说明)。Windows / Linux / macOS 均支持。"""
    if action == "start_ollama":
        import shutil, subprocess
        if os.name == "nt":
            candidates = [
                os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe"),
                os.path.join(os.environ.get("ProgramFiles", ""), "Ollama", "ollama.exe"),
            ]
            exe = next((c for c in candidates if c and os.path.exists(c)), None)
            if not exe:
                return False, "未在默认路径找到 Ollama，请手动打开右下角小羊图标"
            cmd = [exe, "serve"]
            popen_kw = {"creationflags": getattr(subprocess, "DETACHED_PROCESS", 0)}
        else:
            exe = shutil.which("ollama")
            if not exe:
                return False, "系统里没有 ollama 命令，请先安装：https://ollama.com/download"
            cmd = [exe, "serve"]
            popen_kw = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        try:
            subprocess.Popen(cmd, **popen_kw)
            for _ in range(20):
                time.sleep(0.5)
                try:
                    list_ollama_models(timeout=2)
                    return True, "Ollama 已启动并连接成功"
                except Exception:
                    continue
            return False, "Ollama 已启动，但 10 秒内未就绪，请稍后重试自检"
        except Exception as e:
            return False, f"启动失败：{e}"

    if action in ("pull_model", "pull_fallback"):
        import shutil, subprocess
        name = CFG.get("model") if action == "pull_model" else CFG.get("fallback_model")
        if not name:
            return False, "未配置模型名"
        if os.name == "nt":
            ollama_exe = None
            for c in [
                os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe"),
                os.path.join(os.environ.get("ProgramFiles", ""), "Ollama", "ollama.exe"),
            ]:
                if c and os.path.exists(c):
                    ollama_exe = c
                    break
            cmd = [ollama_exe, "pull", name] if ollama_exe else ["ollama", "pull", name]
            try:
                # 模型动辄数 GB，必须给用户看得见的进度窗口
                subprocess.Popen(cmd, creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
                return True, f"已在新窗口开始下载 {name}，完成后请重新自检"
            except Exception as e:
                return False, f"启动下载失败：{e}，请手动执行 ollama pull {name}"
        else:
            exe = shutil.which("ollama")
            if not exe:
                return False, "系统里没有 ollama 命令，请手动安装后执行 ollama pull"
            try:
                log_f = open(LOG_PATH, "ab")     # 下载进度追加进 relay.log
                subprocess.Popen([exe, "pull", name], stdout=log_f, stderr=log_f)
                return True, f"已在后台开始下载 {name}（进度见 relay.log），完成后请重新自检"
            except Exception as e:
                return False, f"启动下载失败：{e}，请手动执行 ollama pull {name}"

    if action == "change_port":
        for cand in (5001, 5002, 5003, 5050, 8080, 8000, 5010):
            ok, _ = _port_free("127.0.0.1", cand)
            if ok:
                ok2, msg = save_config({"port": cand})
                if ok2:
                    return True, f"已改为 {cand}，重启程序生效（OCS 的 URL 也要同步改）"
                return False, msg
        return False, "没找到可用端口，请手动指定"

    if action == "reset_config":
        try:
            if os.path.exists(CONFIG_PATH):
                bak = CONFIG_PATH + f".bak-{int(time.time())}"
                os.replace(CONFIG_PATH, bak)
            ok, msg = save_config(dict(DEFAULT_CONFIG))
            return (True, "配置已重建（原文件已备份）") if ok else (False, msg)
        except Exception as e:
            return False, f"重建失败：{e}"

    return False, f"未知修复动作：{action}"


def ping_ollama(timeout: float = 3.0) -> tuple[bool, str]:
    try:
        base = CFG["ollama_url"].rsplit("/api/", 1)[0]
        r = requests.get(f"{base}/api/tags", timeout=timeout)
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}"
        models = [m.get("name", "") for m in r.json().get("models", [])]
        want = CFG.get("model")
        if want and not any(m.split(":")[0] == want.split(":")[0] for m in models):
            return False, f"未找到模型 {want}，已安装：{', '.join(models) or '无'}"
        return True, f"已安装 {len(models)} 个模型"
    except requests.exceptions.ConnectionError:
        return False, f"无法连接 {CFG['ollama_url']}，请确认 Ollama 已启动"
    except Exception as e:
        return False, str(e)[:120]


def warmup():
    try:
        ok, detail = ping_ollama()
        if not ok:
            backend = (CFG.get("backend") or "ollama").lower()
            if backend == "openai":
                log.error("❌ 云端服务未就绪：%s", detail)
                log.error("   请检查 api_base / api_key / 网络，并在控制台自检里点修复")
            else:
                log.error("❌ Ollama 未就绪：%s", detail)
                log.error("   请先启动 Ollama（右下角小羊图标），并执行 ollama pull %s", CFG.get("model"))
            return
        log.info("✅ 模型服务就绪（%s），正在预热模型 %s ...", detail, CFG.get("model"))
        t0 = time.time()
        call_model("题目：1+1等于几?\n\n【要求】直接输出答案。\n\n答案：")
        log.info("✅ 预热完成，耗时 %.1fs（这段时间的等待不会计入答题）", time.time() - t0)
    except Exception as e:
        log.warning("预热失败（不影响使用）：%s", e)


# --------------------------------------------------------------------------- #
# 控制台页面
# --------------------------------------------------------------------------- #
# 查找顺序：exe 同目录 / 脚本同目录的 console.html -> 打包时注入的内嵌副本 -> 兜底页。
# 源码分发走第一种，改完 console.html 刷新浏览器即可，不用重新打包。
_CONSOLE_HTML_FILE = os.path.join(BASE_DIR, "console.html")

# 打包成 exe 时由 tools/build_exe.py 注入；源码状态下为空字符串。
_CONSOLE_B64 = ""

_FALLBACK_HTML = (
    "<html><meta charset='utf-8'><body style='font-family:sans-serif;"
    "background:#0d1017;color:#e7ecf3;padding:40px'>"
    "<h2>控制台页面缺失</h2>"
    "<p>请确认 console.html 与程序在同一目录。</p>"
    "<p>接口仍可正常使用：<code>POST /api/qa</code></p></body></html>"
)


def _console_candidates() -> list:
    paths = [_CONSOLE_HTML_FILE]
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            paths.insert(0, os.path.join(meipass, "console.html"))
    return paths


def _load_console() -> str:
    """加载控制台页面，逐级降级，保证任何情况下都有页面可看。"""
    for path in _console_candidates():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            continue
    if _CONSOLE_B64:
        try:
            return base64.b64decode(_CONSOLE_B64).decode("utf-8")
        except Exception as e:
            log.warning("内嵌控制台解码失败：%s", e)
    log.warning("未找到 console.html，控制台页面降级为极简版")
    return _FALLBACK_HTML


CONSOLE_HTML = _load_console()


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
def main():
    ensure_config_file()

    ap = argparse.ArgumentParser(description="OCS -> Ollama 中转服务")
    ap.add_argument("--host", default=CFG.get("host", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=CFG.get("port", 5000))
    ap.add_argument("--model", default=None)
    ap.add_argument("--no-warmup", action="store_true")
    ap.add_argument("--no-browser", action="store_true", help="启动时不自动打开控制台")
    args = ap.parse_args()

    if args.model:
        CFG["model"] = args.model
    if args.port:
        CFG["port"] = args.port

    model_line = str(CFG.get("model"))
    fb_line = str(CFG.get("fallback_model") or "无")
    url_line = f"http://{args.host}:{args.port}"

    print()
    print("  ────────────────────────────────────────────────")
    print(f"   OCS 中转服务   v{APP_VERSION}")
    print("  ────────────────────────────────────────────────")
    print(f"   控制台     {url_line}")
    print( "   答题接口   POST /api/qa")
    print(f"   主模型     {model_line}")
    print(f"   备用模型   {fb_line}")
    print("  ────────────────────────────────────────────────")
    print("   关闭此窗口即停止服务；配置可在网页控制台修改。")
    print()

    # 端口占用提前给出清晰提示，而不是抛一坨 traceback
    free, _ = _port_free(args.host, args.port)
    if not free:
        log.error("端口 %s 已被占用，请在控制台里改端口，或用 --port 指定其它端口", args.port)
        try:
            for cand in (5001, 5002, 5050, 8080):
                ok, _ = _port_free(args.host, cand)
                if ok:
                    log.warning("检测到可用端口 %s，可用 --port %s 重新启动", cand, cand)
                    break
        except Exception:
            pass

    def bg_health():
        """后台每 5 秒刷新一次 Ollama 状态，供控制台显示，避免每次轮询都打 Ollama。"""
        while True:
            try:
                ok, detail = ping_ollama(timeout=2.5)
                _OLLAMA_STATE.update(ok=ok, detail=detail)
            except Exception:
                _OLLAMA_STATE.update(ok=False, detail="检测失败")
            time.sleep(5)

    threading.Thread(target=bg_health, daemon=True).start()

    if not args.no_warmup:
        threading.Thread(target=warmup, daemon=True).start()

    if CFG.get("auto_open_browser", True) and not args.no_browser:
        def _open():
            time.sleep(1.2)
            try:
                import webbrowser
                webbrowser.open(f"http://{args.host}:{args.port}/")
            except Exception:
                pass
        threading.Thread(target=_open, daemon=True).start()

    # 关掉 werkzeug 的"开发服务器"警告，个人工具没必要制造焦虑
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    app.run(host=args.host, port=args.port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
