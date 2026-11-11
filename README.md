# JY 答题助手（JY Relay）

一个把「标准 HTTP 接口」转成「本地 Ollama / OpenAI 兼容云端模型」的桌面答题助手。
内置题型路由、结果缓存、多模型交叉验证、多模型投票、题库匹配，可打包为单文件 exe。

**v2.0：不再只是答题客户端的中转**——同时提供 OCS 原生接口和标准 `POST /v1/chat/completions`，
ChatBox / LobeChat / 任何只认 OpenAI 协议的客户端都能直接接进来。

**v1.5 起：打开就是首页**——状态、今天答了多少、正确率、平均耗时，加一个「开始答题」按钮；全部参数收进「⚙ 设置」，不懂模型也能用。

适用场景：本地大模型接入实验、多模型调度与路由实践、企业内部问答系统的协议适配层。

![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![Flask](https://img.shields.io/badge/flask-3.0%2B-green)
![License](https://img.shields.io/badge/license-MIT-orange)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey)
[![Release](https://img.shields.io/github/v/release/JiangYangx/ocs-ollama-relay?label=release&color=success)](https://github.com/JiangYangx/ocs-ollama-relay/releases/latest)

## 下载

👉 **[最新版本下载页](https://github.com/JiangYangx/ocs-ollama-relay/releases/latest)**

| 选这个 | 适合谁 | 文件 |
|---|---|---|
| **安装包**（推荐） | 普通使用者：双击安装，自动建桌面/开始菜单快捷方式，安装时可勾选开机自启 | `JY-Relay-Setup-<版本>.exe` |
| **免安装版** | 想放 U 盘或任意目录、不写系统的 | `JY-Relay.exe`（单文件，双击即用） |

> 程序未做代码签名，首次运行可能被 SmartScreen 或杀软拦一下 —— 点「更多信息 → 仍要运行」即可。
> Windows 用户下载安装包最省事；拿不准就看 [`docs/GETTING_STARTED.md`](docs/GETTING_STARTED.md)，图文步骤从零到能答题。


**双后端可切换**：

- **本地 Ollama**（默认）：离线、不外传数据、无费用，需要自己跑模型
- **云端 OpenAI 兼容接口**：无需显卡，支持智谱 GLM-5.3-Flash（免费档）、硅基流动 Qwen3-8B 等免费模型；⚠️ 题目会发往云端服务器

**题型自动路由**：图片题自动走视觉模型（如智谱 glm-4v-flash / 本地 qwen2.5vl），代码题走代码模型（如 Qwen3-8B），普通文本题走主模型。多模态客户端支持的 `images` 字段已内置（OCS 5.x 等脚本客户端兼容）。

**单文件设计**：全部后端逻辑集中在 `ocs_relay.py` 一个文件里，控制台页面在打包时内嵌，产出的 exe 无需任何附属文件。源码会先找同目录的 `console.html`，找不到才用内嵌版本 —— 改界面时不必重新打包就能看效果。

---

## 目录结构

```
ocs-ollama-relay/
├── ocs_relay.py            # 主程序：Flask 服务 + 推理链路 + 自检修复（核心）
├── console.html            # 网页控制台（暗色主题，零 CDN，可离线）
├── config.json             # 默认配置（首次运行若缺失会自动生成）
├── requirements.txt        # flask>=3.0, requests>=2.31
├── start.bat               # Windows 一键启动
├── build.bat               # Windows 一键打包
├── jy_store.py             # SQLite 持久化（题库/订正/缓存/历史/指标）
├── jy_prep.py              # 前置预处理（文本清洗 / 图片缩放 / 学科识别）
├── jy_rag.py               # 相似题检索（ngram 零依赖 / 可选向量）
├── jy_check.py             # 答案自检（越界字母 / 漏选 / 选项外文字）
├── jy_tiers.py             # 一键档位（极速 / 平衡 / 高正确率）
├── ocs_relay.spec          # PyInstaller 配置（由 build.bat 调用）
├── ocs_config_for_ocs.txt  # 客户端接入配置模板（JSON）
├── tools/
│   ├── build_exe.py        # 构建入口：注入控制台 → 调用 PyInstaller
│   ├── make_bank.py        # 题库转换器：CSV / Excel / TSV → 可导入题库
│   ├── fetch_ceval.py      # 拉取公开题库 C-Eval（52 学科 / 1.3 万题）
│   └── sample_bank.txt     # 示例题库（31 条公开通识题，验证用）
├── docs/
│   ├── GETTING_STARTED.md  # 给使用者的上手说明（不会代码也能照做）
│   ├── API.md              # 接口详解与调用示例
│   └── FAQ.md              # 常见问题排查
├── .github/
│   └── ISSUE_TEMPLATE/     # Issue 模板（Bug 报告 / 功能建议）
├── CHANGELOG.md
├── CONTRIBUTING.md         # 贡献指南
├── SECURITY.md             # 安全策略与漏洞报告方式
├── LICENSE
└── .gitignore
```

> 最小可用：**只要 `ocs_relay.py` 一个文件**（`pip install flask requests` 后直接跑），其余全部可缺省。

---

## 接云端免费大模型

不想装 Ollama / 没有显卡？两分钟切到云端（**注意：请求内容会发往云端**）：

1. [智谱开放平台](https://open.bigmodel.cn/) 注册 → 实名 → 创建 API Key免费档为 glm-5.3-flash 系列（控制台模型下拉里选带 flash 字样的型号）
2. 控制台 →「配置」→ 模型后端选「云端」→ 填入：

| 字段 | 值 |
|---|---|
| api_base | `https://open.bigmodel.cn/api/paas/v4` |
| 主模型 | `glm-5.3-flash`（以下拉列表里实际存在的免费型号为准） |
| 视觉模型 | `glm-4v-flash`（若下拉列表无此型号则留空） |

或用硅基流动（新用户送 2000 万 Token，Qwen3-8B 永久免费）：`api_base = https://api.siliconflow.cn/v1`，主模型 `Qwen/Qwen3-8B`。两家都需实名认证。

**题型路由**：有图自动用视觉模型、检测到代码特征（`def`/```/`SELECT` 等）自动用代码模型，均可在控制台覆盖。客户端配置请重新从控制台复制 —— 新配置带 `images` 字段，否则图片类请求收不到图。

---

## 快速开始

> 只是想把程序跑起来用、不打算读源码？看 [`docs/GETTING_STARTED.md`](docs/GETTING_STARTED.md)，
> 里面有「下载 exe → 配模型 → 粘客户端配置」的完整步骤，以及多人共用一台机器的做法。

### 第 1 步：准备 Ollama 和模型

```bash
ollama pull qwen2.5:7b-instruct
```

> 推荐 `qwen2.5:7b-instruct`：不输出思考链，速度比 R1 快 3~5 倍，答案也更干净。
> 显存/内存紧张可换 `qwen2.5:3b`。

### 第 2 步：启动中转

```bash
pip install -r requirements.txt
python ocs_relay.py
```

Windows 也可直接双击 `start.bat`（会自动检查并补装依赖）。

启动后自动打开控制台 `http://127.0.0.1:5000/`。

### 第 3 步：接入客户端

控制台 →「接入客户端」→ 点「复制配置」→ 粘贴到客户端的配置里。
也可以直接用仓库里的 [`ocs_config_for_ocs.txt`](ocs_config_for_ocs.txt)。

| 字段 | 值 |
|---|---|
| url | `http://127.0.0.1:5000/api/qa` |
| method | `post` |
| type | `GM_xmlhttpRequest` |
| contentType / responseType | `json` / `json` |
| data | `{"title":"${title}","options":"${options}","type":"${type}"}` |
| handler | `return (res) => [res.question, res.answer]` |

> 端口改了的话，`url` 和 `homepage` 要同步改。

---

## 命令行参数

```bash
python ocs_relay.py                       # 默认 127.0.0.1:5000，自动开控制台
python ocs_relay.py --port 5001           # 换端口
python ocs_relay.py --host 0.0.0.0        # 允许局域网访问（默认只监听本机）
python ocs_relay.py --model qwen2.5:3b    # 临时换模型
python ocs_relay.py --no-browser          # 不自动打开浏览器
python ocs_relay.py --no-warmup           # 跳过预热（启动更快，第一题会慢）
```

---

## 网页控制台

浏览器打开 `http://127.0.0.1:5000/`（v1.5 起启动即自动打开首页）：

- **首页**：状态 + 三个数字（今天答题 / 最近正确率 / 平均耗时）+「开始答题」三步接入 + 最近答题列表
- **设置**：v1.4 的全部四个标签页（模型接入 / 正确率增强 / 题库与订正 / 高级），外加「开机自启」「自动检查更新」开关
- **自检结果**：8 项检查，失败项自带「修复」按钮：
  - Ollama 未启动 → 自动尝试拉起 Ollama 进程
  - 模型未安装 → 新开窗口执行 `ollama pull`
  - 端口异常 → 自动换到空闲端口
  - 配置损坏 → 备份后用默认值重建
- **最近请求**：题目、答案、匹配方式、耗时，实时列表
- **在线配置**：改模型 / 端口 / 延时 / 预算，保存即时生效（端口除外），不用重启
- **运行日志**：实时滚动，可暂停；同时写入 `relay.log`
- **复制配置**：一键复制客户端接入配置（带 `navigator.clipboard` 与 `execCommand` 双重回退）

界面不引任何 CDN 资源，断网也能正常显示。

---

## 打包成单文件 exe

双击 `build.bat`，或手动执行：

```bash
pip install flask requests pyinstaller
python tools/build_exe.py
```

构建链路：`tools/build_exe.py` 读取 `console.html` → base64 注入到 `build/_gen/ocs_relay.py` 的 `_CONSOLE_B64` 占位符 → 调用 PyInstaller（读 `ocs_relay.spec`）→ 输出 `dist/JY-Relay.exe`。

这样 `ocs_relay.py` 源码里不会出现大段 base64，可读性不受影响。

产物：

```
dist/
  JY-Relay.exe      ← 单文件，双击即用（控制台已内嵌，无需其它文件）
  config.json      ← 配置，构建脚本自动复制
```

- 整个 `dist` 文件夹拷到别的电脑也能用（对方需自装 Ollama）
- 配置和日志写在 exe 同目录，便携，不写注册表
- 不想自动开浏览器：`JY-Relay.exe --no-browser`，或配置里 `auto_open_browser: false`

---

## 接口

| 路由 | 方法 | 说明 |
|---|---|---|
| `/api/qa` | POST / GET | 答题。`{"title","options","type"}`，`options` 每行一个选项 |
| `/api/qa` | HEAD / OPTIONS | 探测与 CORS 预检，始终 200 / 204 |
| `/api/status` | GET | 控制台轮询：统计 + 答题记录 + 增量日志 |
| `/api/config` | GET / POST | 读取 / 保存配置（带校验，即时生效） |
| `/api/diagnose` | GET | 自检 8 项 |
| `/api/fix` | POST | 一键修复（`start_ollama` / `pull_model` / `pull_fallback` / `change_port` / `reset_config`） |
| `/api/health` | GET | 简版健康检查 |
| `/api/bank` | GET / POST / DELETE | 题库：查状态 / 导入（`{"text": "..."}`）/ 清空 |
| `/api/bank/candidates` | GET / POST | 候选题：待确认列表 / 批量收录或丢弃 |
| `/api/quiz/sample` `/api/quiz/mark` `/api/quiz/stats` | GET / POST / GET | 抽样核对：抽题 / 回填对错 / 正确率统计 |
| `/api/config/import` | POST | 导入 `.jyconfig`（拒收 api_key） |
| `/api/bank/auto` | POST | 从 history.jsonl 自动建库（`{"force": false}`） |
| `/api/corrections` | GET / POST / DELETE | 人工订正：列表+最近答题 / 新增 / 删除（`?key=`） |
| **`/v1/chat/completions`** | POST | **OpenAI 兼容端点**：标准 `chat.completion` 结构，任何 OpenAI 客户端可直接接 |
| `/api/history` | GET | 答题历史分页 + 搜索（`?page=1&limit=50&q=关键词`） |
| `/api/wrong` | GET | 错题列表（`?limit=200`） |
| `/api/bank/import` | POST | 一键导入：multipart 文件（CSV / JSON / TXT）或 JSON body |
| `/api/accuracy` | GET / POST | 准确率档位：`{"mode":"fast|balanced|accurate"}`，一次改四项参数 |
| `/api/update/check` `/download` `/install` | GET / GET / POST | 检查更新 / 下载安装包 / 触发安装 |
| `/` | GET | 控制台页面 |

```bash
curl -X POST http://127.0.0.1:5000/api/qa \
  -H "Content-Type: application/json" \
  -d '{"title":"中国共产党的根本工作路线是","options":"A. 实事求是\nB. 群众路线\nC. 独立自主","type":"single"}'
```

```json
{
  "question": "中国共产党的根本工作路线是",
  "answer": "群众路线",
  "match": "exact",
  "model": "qwen2.5:7b-instruct",
  "cost": 1.83,
  "source": "vote",
  "confidence": "high",
  "votes": [
    {"model": "qwen2.5:7b-instruct", "answer": "群众路线"},
    {"model": "deepseek-r1:7b", "answer": "群众路线"}
  ],
  "success": true
}
```

### 用 OpenAI 客户端接入

```bash
curl -X POST http://127.0.0.1:5000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"单选题：1+1等于几？\nA. 2\nB. 3"}]}'
```

返回标准 `choices[0].message.content`，另带 `jy` 扩展字段（`source` / `confidence` / `votes` / `ms` / `cached`）。
ChatBox、LobeChat 之类把「API 地址」填 `http://127.0.0.1:5000/v1` 即可。

详见 [docs/API.md](docs/API.md)。

---

## 配置项

`config.json`（控制台里也能改，改完即时生效）：

| 键 | 默认 | 说明 |
|---|---|---|
| `backend` | `ollama` | `ollama` 本地 / `openai` 云端 OpenAI 兼容 |
| `api_base` / `api_key` | 空 | 云端必填；本地留空。key 只存本机 config.json |
| `cloud_max_tokens` | `1024` | 云端单次生成上限；思考型模型建议 1024+，被截断会自动扩容重试 |
| `model` | `qwen2.5:7b-instruct` | 主模型（普通文本题） |
| `fallback_model` | `deepseek-r1:7b` | 备用模型，主模型失败时自动切换 |
| `auto_route` | `true` | 按题型自动路由 |
| `vision_model` | 空 | 图片题模型，如 `glm-4v-flash` / 本地 `qwen2.5vl:7b`（须为当前后端存在的模型，否则自动回落主模型） |
| `code_model` | 空 | 代码题模型，如 `Qwen/Qwen3-8B`；空=走主模型 |
| `bank_enabled` | `true` | 题库优先：先查 bank.json（控制台导入），命中不走模型 |
| `verify_mode` | `off` | 交叉验证：`off` / `fast`（复核标注）/ `full`（复核+仲裁） |
| `verify_model` | 空 | 复核模型；空=fallback_model |
| `arbitrate_model` | 空 | full 模式两个模型不一致时的仲裁模型（建议第三个模型） |
| `prompt_preset` | `default` | 学科预设：default/law/medical/math/engineering/english |
| `cot_mode` | `false` | 难题先推理再作答（多选/计算题更准，稍慢） |
| `ollama_url` | `http://127.0.0.1:11434/api/generate` | Ollama 地址（仅本地后端） |
| `keep_alive` | `30m` | 模型驻留内存时长，避免每题重新加载（仅本地） |
| `num_ctx` | `4096` | 上下文窗口（仅本地） |
| `num_predict` | `1024` | 最多生成 token（仅本地） |
| `temperature` / `seed` | `0.0` / `42` | 确定性输出，同题同答案 |
| `port` | `5000` | 服务端口（改后需重启） |
| `max_concurrency` | `1` | 并发推理数（1–8）。本地模型保持 1；云端可设 2–4（改后需重启） |
| `auth_token` | 空 | 访问令牌。设置后所有接口（除 `/api/health`）需带 `X-Relay-Token` 头或 `?token=` 参数，否则 401 |
| `privacy_log` | `false` | 隐私日志：开启后日志中题干/答案掩码显示 |
| `answer_budget` | `50` | 整题总预算（秒），必须 < 58 |
| `request_timeout` | `100` | 单次请求超时上限（秒） |
| `max_queue` | `32` | 排队上限 |
| `cache_size` | `1024` | 内存缓存条数 |
| `human_delay` | `true` | 是否启用节律延时 |
| `delay_min_ms` / `delay_max_ms` | `500` / `1500` | 返回间隔范围 |
| `delay_on_cache` | `true` | 缓存命中也延时（建议开） |
| `max_gap_ms` | `6000` | 距上一题超过此值不再补时 |
| `auto_open_browser` | `true` | 启动后自动开控制台 |

环境变量 `OLLAMA_MODEL` / `OLLAMA_URL` / `BACKEND` / `API_BASE` / `API_KEY` 可覆盖对应配置。
以 `_` 开头的键是注释，保存配置时会被原样保留。

**v2.0 新增配置**：

| 键 | 默认 | 说明 |
|---|---|---|
| `vote_models` | `[]` | 参与投票的模型名列表，空 = 不投票。多个模型各投一票 |
| `vote_min` | `2` | 最高票达到该值才改写主模型答案 |
| `fast_path_max_len` | `80` | 题干短于该字数走快路（跳过投票/CoT/自检）；`0` = 关闭 |
| `verify_parallel` | `true` | 复核与主模型并行；本地 Ollama 自动降级 |
| `cache_normalize` | `true` | 缓存键忽略空格标点 |
| `bank_priority` | `true` | 题库/订正命中优先于模型答案 |
| `accuracy_mode` | `balanced` | `fast` / `balanced` / `accurate`，与档位按钮联动 |
| `api_mode` | `auto` | `auto` / `ocs` / `openai`：限定接受的请求形态 |
| `field_map` | `{}` | 字段名映射，如 `{"title":"question","options":"choices"}` |
| `response_format` | `text` | `text` 选项正文 / `letter` 仅字母 / `json` 完整结构 |
| `cors_allow_origin` | `""` | 允许的跨域来源；空 = 不发 CORS 头 |
| `lan_share` | `false` | 允许其他设备访问（无 `auth_token` 时自动回落本机） |
| `update_auto_download` | `false` | 发现新版自动下载安装包（仍需手动点安装） |
| `config_version` | `2` | 配置结构版本，老配置启动时自动补齐新键并备份 |

---

## 四轴能力（v2.0）

**正确率**

| 手段 | 触发 | 代价 |
|---|---|---|
| 题库 / 订正命中 | 题干+选项完全一致 | 0（毫秒级） |
| 相似题检索（RAG） | 同考点不同表述 | 推理一次 |
| 交叉验证复核 | `verify_mode=fast/full` | 多一次请求（可并行） |
| 多模型投票 | `vote_models` 非空且非快路 | 并发补票，不叠延迟 |
| CoT 先推理 | `cot_mode` 或难题自动 | token + 时间 |
| 答案自检重答 | `self_check` | 可疑时才触发 |

**速度**：快路（短单选直连）、并行复核、缓存归一化、题库命中不补节律。

**适配性**：OCS 原生 + OpenAI `/v1/chat/completions` 双协议；`api_mode` 限定形态；`field_map` 翻译字段；`response_format` 决定返回样子。

**便捷性**：准确率三档一键切；控制台「历史 / 错题 / 题库」数据页；题库拖文件导入；配置自动迁移；更新检测+下载。

---

## 题库从哪来

自带题库为空，命中率取决于你喂什么。三条路，按性价比排序：

| 来源 | 做法 | 题量参考 | 说明 |
|---|---|---|---|
| **CMMLU 公开数据集** | 下载 CSV → `tools/bank_converter.py` 转换 → 控制台拖入 | 67 科 1.16 万题 | 大学/高中/职业资格考试，每题带标准答案，CC BY-NC 4.0，个人学习用 |
| **自己收集的题库** | Word/Excel/TXT 里的题 → 转换器 | 看你攒多少 | 支持 `1. 题干 / A. xx / 答案：A`、单行题、判断题 |
| **历史自动沉淀** | 答过的题一键存进题库 | 越用越多 | 同一道题第二次出现就是毫秒级命中 |

**CMMLU 一秒钟拿下来**（走 HF 镜像，不用梯子）：

```bash
# 1) 下载（约 1MB 压缩包，解压出 134 个 CSV）
curl -L -o cmmlu.zip https://hf-mirror.com/datasets/haonan-li/cmmlu/resolve/main/cmmlu_v1_0_1.zip
unzip cmmlu.zip

# 2) 转换 + 推送（服务开着就自动分批导入，2 秒 1.1 万题）
python tools/bank_converter.py cmmlu/test --push http://127.0.0.1:5000

# 只要大学专业课
python tools/bank_converter.py cmmlu/test --subject college,computer --push http://127.0.0.1:5000

# 只转不推，产出一个可拖进控制台的 CSV
python tools/bank_converter.py cmmlu/test -o bank.csv
```

转换器自动识别三种输入：CMMLU/C-Eval/MMLU 风格（`Question,A,B,C,D,Answer`）、通用 CSV（题干/答案/选项）、纯文本题库。输出就是 `/api/bank/import` 吃的格式，也可以直接在控制台「题库」页拖进去。

**其他可查可抄的站点**（无批量导出，需手工整理后走转换器）：

- [考试酷](https://www.examcoo.com/index/ku) —— 公共题库永久免费查阅，学历/职业/计算机分类全
- [大学题库](https://dxxq.com/) —— 本科研究生课程题
- [考试宝](https://www.kaoshibao.com/) —— 支持上传 Word/Excel/TXT 自建题库，可导出
- [中国大学MOOC](https://www.icourse163.org/) / [学堂在线](https://www.xuetangx.com/) —— 课程测验原题
- [glm-cn/ncre](https://github.com/glm-cn/ncre) —— 计算机等级考试题库（分包 rar）

> 别碰需要付费下载券的文库站（人人文库、道客巴巴等），也不要用破解工具抓题库，账号风险远大于收益。

---

## 内置优化

**三级降级**
`think=False` → 失败则不带 `think` 字段重试 → 仍失败换备用模型。任何一档成功即返回。

**整题时间预算**
默认 50 秒内必返回（常见客户端超时上限 60 秒）。每次重试的超时按剩余预算自动收缩：`per_timeout = min(request_timeout, max(3.0, 剩余时间 / 剩余次数 × 1.5))`，最坏情况也不会被客户端超时截断。

**思考链清洗**
完整 / 未闭合 / 大写 / 带属性 / 带空格的 `<think>`、中文「思考：」段、「答案：」前缀、括号解释、包裹引号、选项字母前缀 —— 8 步流水线全部剥离。R1 系模型也不会把思考内容当成答案。

**答案匹配**
优先返回**选项正文**（走客户端文本精确匹配 → 相似度 0.6 → 字母下标三级回退），不受选项顺序影响。支持多选（多行 / `|` 分隔 / 字母组合）、多空填空。

**串行队列 + LRU 缓存 + 启动预热**
同一时刻只跑一次推理（`max_concurrency` 可调，云端可放宽），其余排队；重复题秒回（TTL + LRU，默认 1024 条）；缓存 key 含 backend / model / 图片摘要，换模型不会命中旧缓存；启动时预热一次，第一题不用干等。

**访问控制与隐私**
`auth_token` 一键开启接口鉴权（`X-Relay-Token` 头 / `?token=` 参数），防止局域网内他人盗用；控制台与配置接口对 `api_key` / `auth_token` 做掩码回显（`***` + 末 4 位），提交掩码值不会覆盖真实密钥；`privacy_log` 开启后日志中题干与答案掩码显示。

**正确率增强（v1.2.x）**
答题优先级：**人工订正 > 导入题库 > 缓存 > 双模型交叉验证的模型答案**。题库命中零成本秒回；答错的题在控制台一键订正后永久生效；`verify_mode=full` 时主模型与复核模型不一致会交给第三个仲裁模型裁决，响应 `verify` 字段标注置信情况（agree / conflict / arbitrated）。

**v1.4 知识闭环**
候选题库人工确认入库（模型答案不再自动进题库）、抽样核对真实正确率（按天曲线）、答题流一键答错标记、首次三步引导（3 分钟出第一道答案）、`.jyconfig` 配置迁移、局域网手机扫码接入、明暗主题与移动端适配。

**v1.3 成型版**
一键档位（极速 / 平衡 / 高正确率，参数协同写入）、答案自检（越界字母、多选漏选、选项外文字自动拦截重答）、SQLite 持久化（重启不丢缓存、题库命中 1ms 级）、相似题检索 RAG（ngram 零依赖，可选 Ollama 向量模型）、HTTP 连接复用（每题省 80~200ms）、云端失败自动切本地 Ollama、题库文件拖拽导入、实时 KPI（p50 / p95 / 命中率）与一键诊断包导出。

**题库自动积累（v1.2.2）**
答过的题自动记入 `history.jsonl`，控制台「题库与订正 → 从历史记录建库」一键沉淀成题库：交叉验证一致的题直接收录，前后答案不一致的题自动过滤。同一道题再出现就是毫秒级命中（实测 ~2ms，`cost=0`），且不随模型波动。自己的表格资料（CSV / Excel）用 `tools/make_bank.py` 一键转换后导入。

**公开题库接入（v1.2.3）**
`tools/fetch_ceval.py` 可从镜像拉取公开学术题库 **C-Eval**（52 个学科、13685 道单选题），转换后直接进库：

```bash
python tools/fetch_ceval.py --list                                # 看有哪些学科
python tools/fetch_ceval.py --subjects computer_network,law       # 只下指定学科
python tools/fetch_ceval.py --json bank.json                      # 全量，直接放到程序目录
```

实测 1.3 万条题库加载后内存约 68MB，命中 1.3ms、`cost=0`。

> **要清楚它的边界**：题库命中要求「题干一致」。C-Eval 是公开考试题，覆盖的是通用学科知识，**不会命中你课程的原题**。它的价值在于：① 验证整条题库链路；② 覆盖计算机/数学/法律等基础概念题。真正贴合你题目的题库只有三种来源——自己答过的历史、课程配套资料、同课程同学整理的题库（后者请注意版权与平台条款）。
>
> 数据许可证 **CC BY-NC-SA 4.0**：仅个人学习/研究使用，不得商用，再分发需保留署名与相同许可。脚本不含题库数据，只在运行时从镜像下载。

---

## 请求间隔控制（礼貌限流）

为避免对上游服务造成突发压力，每次返回前可按配置补足到 **500~1500ms 随机间隔**。

注意这不是简单地 `sleep`，而是**间隔补足**：`wait = max(0, 目标间隔 - 已耗时)`，即推理本身耗时够长时不再追加等待。

| 情况 | 行为 |
|---|---|
| 推理本身已超过目标间隔 | 不追加等待，直接返回 |
| 距上次请求已超过 `max_gap_ms`（6 秒） | 直接放行，不叠加延时 |
| 缓存命中 | 同样受间隔约束，保持节奏稳定 |
| 请求失败 | 同样受间隔约束，避免连续重试冲击上游 |

间隔分布右偏（`max(u1, u2)` 两次均匀取大），小间隔少于大间隔，整体更平缓。

> 该功能属于**客户端侧限流**，用于保护上游模型服务与目标系统。按需在控制台「高级」页调整或关闭（`human_delay=false`）。

---

## 常见问题

| 现象 | 处理 |
|---|---|
| 控制台显示 Ollama 未连接 | 点自检里的「修复」自动拉起；或手动打开小羊图标 |
| 主模型显示未找到 | 点「修复」自动 `ollama pull`；或手动执行 |
| 答题超时 | 7B 纯 CPU 每题 20~60s 属正常；换 `qwen2.5:3b` 或开 GPU 加速 |
| 端口被占 | 控制台改端口保存，重启后生效，客户端 URL 需同步改 |
| 答案明显乱猜 | 模型没有该题库的知识，冷门题无解，这是原理限制 |
| 改了配置没生效 | 除端口外都是即时生效；改端口需重启程序 |
| 双击 `build.bat` 中文乱码 | 脚本已改为纯 ASCII；仍乱码就用 `cmd` 手动执行 `python tools\build_exe.py` |
| exe 被杀软误报 | PyInstaller 单文件打包的通病，加白名单即可 |

更多排查见 [docs/FAQ.md](docs/FAQ.md)。

---

## 想改界面？

```bash
# 1. 编辑 console.html
# 2. 直接重启程序 —— 同目录的 console.html 优先级高于内嵌版本
python ocs_relay.py

# 3. 确认没问题后再打包，把新界面固化进 exe
python tools/build_exe.py
```

源码状态下 `_CONSOLE_B64` 是空字符串，`_load_console()` 按「同目录文件 → 内嵌 base64 → 极简兜底页」三级降级，任何情况下都能打开控制台。

---

## 参与贡献

1. Fork 本仓库，从 `main` 切出分支（`feat/xxx` 或 `fix/xxx`）
2. 保持单文件架构：新逻辑加进 `ocs_relay.py`，不要拆模块
3. 改完自测一遍：`python ocs_relay.py --no-browser` → 打开 `/` → 自检应 8/8 通过
4. 提交 PR，说明动机、改动点与验证方式

代码风格：4 空格缩进、行宽约 100、注释用中文、函数保持单一职责。

---

## 使用须知

**性质说明**

本项目是一个通用的 HTTP → 大模型协议中转服务，本身不含任何题库内容、不破解任何验证机制、不针对特定平台实现任何自动化登录或提交行为。它只做一件事：接收一段结构化文本（题目 + 选项），调用你指定的大模型，返回结构化的答案文本。

**数据与隐私**

- 本地 Ollama 后端完全离线，请求不离开本机。
- 切换云端后端后，请求内容会发往你所配置的第三方模型服务商，请自行评估并确认接受；`api_key` 仅保存在本机 `config.json`，控制台与接口回显均为掩码（`***` + 末 4 位）。
- 建议：局域网使用时设置 `auth_token`；对外分享日志或录屏时开启 `privacy_log`（日志掩码）。

**合规使用**

请在合法合规的场景下使用，包括但不限于：本地大模型接入测试、多模型路由与调度实验、企业内部问答系统的协议适配、教育场景的学习辅助工具研发。

使用者应自行遵守所接入系统/平台的服务条款以及当地法律法规。**将本软件用于违反服务条款、规避平台技术措施或其他不当用途，属于使用者个人的行为，与本项目作者无关。**

**免责**

本软件按「原样」提供，不附带任何明示或默示担保。因使用本软件产生的一切后果由使用者自行承担。详见 [LICENSE](LICENSE)。

---

## 许可证

[MIT](LICENSE)
