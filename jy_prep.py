#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""jy_prep —— 前置预处理（v1.3）

三件事：
  1. 文本清洗：网页复制来的题常带 HTML 标签、实体、广告行、大量空行
  2. 图片预处理：长边缩到 1280 + 锐化；灰度/降噪作为可选开关（默认关）
  3. 题目特征识别：题型、学科关键词（软标记）、复杂度（决定走轻量还是旗舰）

设计原则：
  - 清洗只作用于「送去模型的内容」，绝不改题库 key 的原文——
    否则同一道题因为多一个空格就查不到题库。
  - 所有函数失败都返回原值，预处理永远不能成为新的故障点。
"""
from __future__ import annotations

import base64
import io
import re

# ---------------------------------------------------------------- 文本清洗

_AD_LINE = re.compile(
    r"(扫码|扫一扫|关注公众号|微信公众号|加微信|点击关注|点赞收藏|转发|"
    r"版权所有|copyright|广告|推广|赞助|下载APP|打开APP|返回顶部|"
    r"上一篇|下一篇|相关阅读|热门推荐|免责声明)", re.I)

_TAG = re.compile(r"<[^>]{1,200}>")
_ENT = re.compile(r"&(#\d+|#x[0-9a-fA-F]+|[a-zA-Z]{2,8});")


def clean_text(text: str, remove_ads: bool = True) -> str:
    """去掉 HTML 标签、实体、广告行、多余空白。失败原样返回。"""
    if not text:
        return text or ""
    try:
        t = str(text).replace("\r\n", "\n").replace("\r", "\n")
        t = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", t)
        # 标签两侧是英文/数字时保留一个空格，中文之间直接删除（否则「中国 的 首都」）
        t = re.sub(r"(?<=[A-Za-z0-9])<[^>]{1,200}>", " ", t)
        t = _TAG.sub("", t)
        t = _ENT.sub(lambda m: _entity(m.group(1)), t)

        out = []
        for line in t.split("\n"):
            s = line.strip()
            s = re.sub(r"[ \t\u3000]{2,}", " ", s)
            if not s:
                continue
            if remove_ads and len(s) <= 40 and _AD_LINE.search(s):
                continue
            out.append(s)
        res = "\n".join(out).strip()
        return res or str(text).strip()
    except Exception:
        return text


def _entity(name: str) -> str:
    table = {"nbsp": " ", "amp": "&", "lt": "<", "gt": ">", "quot": '"',
             "apos": "'", "ldquo": "“", "rdquo": "”", "hellip": "…",
             "mdash": "—", "middot": "·", "times": "×", "divide": "÷"}
    if name.startswith("#x") or name.startswith("#X"):
        try:
            return chr(int(name[2:], 16))
        except Exception:
            return " "
    if name.startswith("#"):
        try:
            return chr(int(name[1:]))
        except Exception:
            return " "
    return table.get(name.lower(), " ")


def strip_option_prefix(s: str) -> str:
    return re.sub(r"^[A-Ha-h][.．、:：)）]\s*", "", (s or "").strip())


# ---------------------------------------------------------------- 图片预处理

def preprocess_image(data: str, max_side: int = 1280,
                     grayscale: bool = False, denoise: bool = False,
                     quality: int = 85) -> str:
    """输入 base64（可带 data: 前缀），输出压缩后的 base64 JPEG。
    没有 Pillow 时原样返回，不影响主流程。"""
    if not data:
        return data
    try:
        from PIL import Image, ImageFilter, ImageOps
    except Exception:
        return data
    try:
        raw = data
        prefix = ""
        if raw.startswith("data:"):
            head, _, raw = raw.partition(",")
            prefix = head + ","
        try:
            blob = base64.b64decode(raw, validate=False)
        except Exception:
            return data
        if len(blob) < 200:
            return data

        im = Image.open(io.BytesIO(blob))
        if im.mode in ("RGBA", "LA", "P"):
            bg = Image.new("RGB", im.size, (255, 255, 255))
            im = im.convert("RGBA")
            bg.paste(im, mask=im.split()[-1])
            im = bg
        elif im.mode != "RGB":
            im = im.convert("RGB")

        w, h = im.size
        long_side = max(w, h)
        if max_side and long_side > max_side:
            scale = max_side / float(long_side)
            im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))),
                           Image.LANCZOS)

        if grayscale:
            im = ImageOps.grayscale(im).convert("RGB")
        if denoise:
            im = im.filter(ImageFilter.MedianFilter(size=3))

        im = im.filter(ImageFilter.UnsharpMask(radius=1.4, percent=140, threshold=3))

        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=quality, optimize=True)
        out = base64.b64encode(buf.getvalue()).decode()
        return (prefix or "data:image/jpeg;base64,") + out
    except Exception:
        return data


# ---------------------------------------------------------------- 题目特征

_SUBJECT_KW = {
    "law": ["法条", "刑法", "民法", "合同法", "宪法", "诉讼", "侵权", "物权",
            "债权", "治安管理", "行政处罚", "劳动法", "公司法"],
    "medical": ["临床", "诊断", "病理", "解剖", "药理", "护理", "症状", "体征",
                "用药", "适应证", "禁忌证", "内科", "外科", "影像学"],
    "math": ["函数", "极限", "导数", "积分", "矩阵", "概率", "数列", "方程",
             "证明", "计算", "解为", "求值", "不等式", "向量", "微积分"],
    "engineering": ["电路", "电压", "受力", "扭矩", "热力学", "熵", "流速",
                    "应力", "材料", "编程", "算法", "复杂度", "数据结构",
                    "协议", "带宽", "进程", "线程"],
    "english": ["the ", "which of", "choose", "following", "grammar",
                "tense", "phrase", "paragraph"],
}

_CALC_KW = re.compile(r"(计算|求解|求值|证明|推导|化简|解方程|多少|几|概率|"
                      r"极限|积分|导数|矩阵|行列式|费率|折旧|收益率|方差)")
_CODE_KW = re.compile(r"(#include|def |class |public |void |printf|System\.out|"
                      r"时间复杂度|空间复杂度|输出结果|程序运行|以下代码)")


def detect_subject(title: str, options: str = "") -> str:
    """学科关键词软识别。只作为提示词附加，不改变路由决策。"""
    text = f"{title or ''} {(options or '')[:300]}"
    best, best_hit = "", 0
    low = text.lower()
    for subj, kws in _SUBJECT_KW.items():
        hit = sum(1 for k in kws if (k.lower() in low))
        if hit > best_hit:
            best, best_hit = subj, hit
    # 至少命中 2 个关键词才算识别成功，避免单字误判
    return best if best_hit >= 2 else ""


def is_complex(title: str, options: str, qtype: str = "") -> bool:
    """判断是否值得走旗舰模型 + CoT。
    复杂 = 多选 / 题干长 / 含计算推理词 / 含代码 / 选项多"""
    t = title or ""
    if (qtype or "").lower() in ("multiple", "multi"):
        return True
    if len(t) >= 60:
        return True
    if _CALC_KW.search(t):
        return True
    if _CODE_KW.search(t) or "```" in t:
        return True
    if len([x for x in (options or "").split("\n") if x.strip()]) >= 5:
        return True
    return False


def image_signature(images: list) -> str:
    import hashlib
    if not images:
        return ""
    joined = "|".join(images)
    return f"img{len(images)}:{hashlib.md5(joined.encode(errors='ignore')).hexdigest()[:10]}"
