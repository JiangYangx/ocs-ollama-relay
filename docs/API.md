# 接口文档

服务默认监听 `http://127.0.0.1:5000`。全部接口挂 `Access-Control-Allow-Origin: *`，允许 OCS（脚本猫的 `GM_xmlhttpRequest`）跨域直连。

## 访问令牌（v1.1.1+）

配置 `auth_token` 后，除 `/api/health` 外的所有接口需携带令牌（任选其一）：

- 请求头 `X-Relay-Token: <token>`（推荐，`_ocs_snippet()` 生成的配置自动带）
- 查询参数 `?token=<token>`
- Cookie `relay_token=<token>`

未携带或错误返回 `401 {"error": "unauthorized"}`。

**设计原则：错误也返回 HTTP 200。** 因为 OCS 的 `handler` 只在成功响应里取字段，返回 4xx/5xx 会让卡片直接显示"连接失败"，看不到具体原因。所以失败时返回 `success: false` + `error` 字段，由调用方判断。

---

## POST /api/qa — 答题

最核心的接口。

### 请求

```
POST /api/qa
Content-Type: application/json
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `title` | ✅ | 题干文本（也接受 `question` / `q` 别名） |
| `options` |  | 选项文本，**每行一个**（也接受 `option` 别名；传数组会自动用 `\n` 拼接） |
| `type` |  | `single` / `multiple` / `judge` / `fill` / `unknown`，影响提示词构造 |
| `images` |  | OCS 5.x 图片题字段，base64 或 data URL 数组（≤8 张，最多带 4 张给模型）。**有图时自动路由到 `vision_model`** |
| `suggestion_title` / `suggestion_options` |  | OCS 5.x 文字辅助字段，拼入提示词帮助理解 |

`options` 的每行推荐写成 `A. 内容` 的形式，解析器支持 `. ． 、 : ： ) ）` 等多种分隔符；不写字母也能识别，此时按行序推断。

图片题要求：OCS 5.1+、题库配置里 `"images": {"handler": "return (env) => env.images || []"}`（`_ocs_snippet()` 生成的配置已含）、且必须 POST。

```bash
curl -X POST http://127.0.0.1:5000/api/qa \
  -H "Content-Type: application/json" \
  -d '{
    "title": "中国共产党的根本工作路线是",
    "options": "A. 实事求是\nB. 群众路线\nC. 独立自主",
    "type": "single"
  }'
```

### 成功响应

```json
{
  "question": "中国共产党的根本工作路线是",
  "answer": "群众路线",
  "raw_answer": "B",
  "options": ["实事求是", "群众路线", "独立自主"],
  "letters": ["A", "B", "C"],
  "match": "exact",
  "note": "",
  "model": "qwen2.5:7b-instruct",
  "cost": 1.83,
  "pace_wait_ms": 1120,
  "total": 2.95,
  "success": true,
  "cached": false,
  "route": "text",
  "has_images": false
}
```

### 新增响应字段（v1.1.1+）

| 字段 | 说明 |
|---|---|
| `cached` | 是否缓存命中（缓存命中与未命中响应都会带此字段） |
| `route` | 本次路由：`text` / `code` / `image` / `image-fallback` |
| `has_images` | 请求是否携带图片 |
| `note` | 路由模型未成功由主模型兜底时，会追加说明 |

| 字段 | 说明 |
|---|---|
| `answer` | **最终答案，返回的是选项正文而非字母**，直接塞给 OCS |
| `raw_answer` | 模型原始输出（清洗后、匹配前），排查用 |
| `options` / `letters` | 解析出的选项正文 / 字母，与 `answer` 可对照 |
| `match` | 匹配方式：`exact` 文本精确 / `fuzzy` 相似度 / `letter` 字母下标 / `raw` 未匹配到（原样返回） |
| `note` | 匹配补充说明，通常为空 |
| `model` | 实际出答案的模型（可能已按题型路由到 vision/code 模型或降级到备用） |
| `has_images` | 本次是否带了图片（图片题走 `vision_model`） |
| `cost` | 推理耗时（秒） |
| `pace_wait_ms` | 为节律额外等待的毫秒数 |
| `total` | 端到端总耗时（秒） |
| `cached` | 是否命中缓存 |

### 失败响应

```json
{
  "question": "……",
  "answer": "",
  "success": false,
  "error": "Ollama 未启动或端口不通"
}
```

常见 `error`：`Ollama 未启动或端口不通`、`队列已满或等待超时`、`模型返回为空`、`所有模型尝试均失败`。

### 探测请求

不带 `title` 调用（或 `HEAD` / `OPTIONS`）时不会触发推理，直接返回服务信息 —— OCS 添加题库时用它探测连通性，因此**始终 200**：

```json
{
  "status": "ok",
  "service": "ocs-ollama-relay",
  "model": "qwen2.5:7b-instruct",
  "hint": "这是健康检查响应，请通过 POST 传 title / options"
}
```

---

## GET /api/status — 控制台轮询

控制台每 1.5 秒调一次。

| 参数 | 说明 |
|---|---|
| `log_since` | 只返回序号大于该值的日志，实现增量刷新（首次传 0） |

```json
{
  "version": "1.0.0",
  "ollama": true,
  "model": "qwen2.5:7b-instruct",
  "stats": {"total": 12, "success": 12, "cache": 3, "fail": 0},
  "answers": [
    {"t": "11:42:07", "q": "中国共产党的根本工作路线是", "a": "群众路线",
     "match": "exact", "cached": false, "ok": true, "cost": 1.83, "pace": 1120}
  ],
  "logs": [{"i": 41, "t": "11:42:07", "level": "INFO", "msg": "Q: … | A: …"}],
  "log_seq": 41,
  "queue_waiting": 0,
  "cache_size": 9
}
```

`answers` 最多保留 120 条，`logs` 最多 400 条（内存环形缓冲，重启即清）。

---

## GET /api/config — 读配置

```json
{
  "config": {"model": "qwen2.5:7b-instruct", "port": 5000, "...": "..."},
  "models": ["qwen2.5:7b-instruct:latest", "deepseek-r1:7b"],
  "ocs_snippet": "[{\"name\":\"本地Ollama\", ...}]"
}
```

- `config`：当前生效配置（只含 `DEFAULT_CONFIG` 里的键，`_` 开头的注释键不下发）
- `models`：本机 Ollama 已安装的模型；Ollama 不通时为 `[]`
- `ocs_snippet`：端口已代入的 OCS 题库配置 JSON 字符串，控制台「复制配置」用的就是它

---

## POST /api/config — 保存配置

```bash
curl -X POST http://127.0.0.1:5000/api/config \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen2.5:3b","delay_min_ms":800,"delay_max_ms":2000}'
```

只传要改的字段即可（白名单 `EDITABLE_FIELDS`，未知键会被忽略）。

```json
{"ok": true, "message": "已保存"}
```

校验规则（不通过则 `ok: false` 并返回原因）：

| 项 | 规则 |
|---|---|
| `answer_budget` | 必须 < 58（OCS 上限 60 秒） |
| `port` | 1 ~ 65535 |
| `delay_max_ms` | ≤ 15000 |
| `delay_min_ms` / `delay_max_ms` | 若 min > max 会自动交换 |
| 数值型字段 | 强制转型，非法值拒绝写入 |

写入是原子的（先写 `.tmp` 再 `os.replace`），`_` 开头的注释键原样保留。
**除 `port` 外都即时生效**；端口改动需重启程序。

---

## GET /api/diagnose — 自检

返回 8 项检查结果。

```json
{
  "items": [
    {"id": "python", "label": "Python 环境", "status": "ok",
     "detail": "3.11.9", "fix": null, "hint": ""},
    {"id": "ollama", "label": "Ollama 服务", "status": "ok", "detail": "已连接", "fix": null, "hint": ""},
    {"id": "model", "label": "主模型", "status": "ok", "detail": "qwen2.5:7b-instruct", "fix": null, "hint": ""},
    {"id": "fallback", "label": "备用模型", "status": "warn",
     "detail": "未安装 deepseek-r1:7b（可选，不影响使用）", "fix": "pull_fallback", "hint": ""},
    {"id": "port", "label": "服务端口", "status": "ok", "detail": "5000 正在监听，服务正常", "fix": "change_port", "hint": ""},
    {"id": "budget", "label": "时间预算", "status": "ok", "detail": "整题预算 50s（OCS 上限 60s）", "fix": null, "hint": ""},
    {"id": "config", "label": "配置文件", "status": "ok", "detail": "config.json", "fix": "reset_config", "hint": ""},
    {"id": "writable", "label": "目录权限", "status": "ok", "detail": "可写入配置", "fix": null, "hint": ""}
  ],
  "summary": {"ok": 7, "warn": 1, "fail": 0},
  "models": ["qwen2.5:7b-instruct:latest"]
}
```

`status` 三态：`ok` / `warn`（能跑，但有隐患）/ `fail`（跑不起来）。
`fix` 非空表示该项有可执行的修复动作，前端据此渲染按钮。

---

## POST /api/fix — 一键修复

```bash
curl -X POST http://127.0.0.1:5000/api/fix \
  -H "Content-Type: application/json" \
  -d '{"action":"start_ollama"}'
```

| action | 行为 |
|---|---|
| `start_ollama` | 尝试拉起本机 Ollama 进程，随后等待端口就绪 |
| `pull_model` | 新开窗口执行 `ollama pull <主模型>` |
| `pull_fallback` | 新开窗口执行 `ollama pull <备用模型>` |
| `change_port` | 扫描并从 5000 起找一个空闲端口写入配置（需重启生效） |
| `reset_config` | 先把现有 `config.json` 备份为 `config.json.bak`，再用默认值重建 |

```json
{"ok": true, "message": "已开始执行 ollama pull qwen2.5:7b-instruct（新窗口）"}
```

---

## GET /api/health — 简版健康检查

给外部监控 / 脚本用，比 `/api/status` 轻。

```json
{
  "service": "ocs-ollama-relay",
  "version": "1.0.0",
  "ollama": true,
  "detail": "ok",
  "model": "qwen2.5:7b-instruct",
  "cache": 9,
  "queue_waiting": 0,
  "pace": "500~1500ms"
}
```

`human_delay` 关闭时 `pace` 为 `"已关闭"`。

---

## GET / — 控制台

返回 `console.html` 页面内容（`text/html`）。支持 `HEAD`。

页面加载优先级：程序同目录的 `console.html` → 打包时内嵌的 base64 → 极简兜底页。所以源码状态下改完 HTML 刷新浏览器就能看到，不用重新打包。

---

# v2.0 新增接口

## POST /v1/chat/completions — OpenAI 兼容

任何只认 OpenAI 协议的客户端（ChatBox / LobeChat / 浏览器插件）都能直接接进来。

```bash
curl -X POST http://127.0.0.1:5000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"单选题：1+1等于几？\nA. 2\nB. 3"}]}'
```

响应是标准 `chat.completion`，另带非标准 `jy` 扩展字段：

```json
{
  "id": "chatcmpl-81d4047381bb1a9d",
  "object": "chat.completion",
  "created": 1794151991,
  "model": "qwen2.5:7b-instruct",
  "choices": [{"index": 0, "message": {"role": "assistant", "content": "A"},
               "finish_reason": "stop"}],
  "usage": {"prompt_tokens": 15, "completion_tokens": 1, "total_tokens": 16},
  "jy": {"cached": false, "confidence": "high", "ms": 7511.7,
         "source": "vote", "votes": []}
}
```

`content` 的内容由 `response_format` 决定：`text` 返回选项正文，`letter` 返回 `A`，`json` 返回完整结构字符串。

支持多模态 `content` 数组里的 `image_url`（会取出图片走视觉模型）。

## GET /api/history — 历史分页

| 参数 | 默认 | 说明 |
|---|---|---|
| `page` | 1 | 页码，从 1 开始 |
| `limit` | 50 | 每页条数（上限 200） |
| `q` | — | 关键词，匹配题干 |

```json
{"items": [{"id": 2, "q": "中国的首都", "a": "北京", "source": "bank",
            "confidence": "high", "ms": 12, "cached": False}],
 "page": 1, "pages": 1, "total": 2}
```

## GET /api/wrong — 错题

`?limit=200`。来自 `quiz` 表里 `correct=0` 的记录，按时间倒序。

```json
{"count": 3, "items": [{"q": "...", "a": "...", "t": 1794151991}]}
```

## POST /api/bank/import — 题库导入

两种调用方式：

**multipart 文件**（推荐）
```bash
curl -F "file=@bank.csv" http://127.0.0.1:5000/api/bank/import
```
CSV 前两列是「题干,答案」，可选第三列「选项」用 `|` 分隔；带表头会自动跳过。

**JSON body**
```json
{"items": [
  {"title": "中国的首都是哪里", "answer": "北京", "options": ["A. 北京", "B. 上海"]}
]}
```
题干字段兼容 `question` / `title` / `q` / `题目`，答案兼容 `answer` / `a` / `答案`，
选项可以是字符串数组，也可以是 `[{"key":"A","text":"北京"}]` 结构。

响应：`{"ok":true,"added":2,"updated":0,"total":12,"errors":[]}`

## GET|POST /api/accuracy — 准确率档位

一次设定同时改 `tier` + `verify_mode` + `cot_mode` + `self_check`，避免只调一项导致参数互相打架。

```bash
curl -X POST http://127.0.0.1:5000/api/accuracy \
  -H "Content-Type: application/json" -d '{"mode":"accurate"}'
```

| 档位 | tier | verify_mode | cot_mode | self_check | 适合 |
|---|---|---|---|---|---|
| `fast` | speed | off | false | false | 客观题海量刷 |
| `balanced` | balanced | fast | false | true | 日常默认 |
| `accurate` | accurate | full | true | true | 高分值难题 |

`GET` 返回 `{"mode":"balanced","presets":{...}}`。

## GET /api/update/check · /download · /install

- `check`：查 GitHub 最新 Release，返回 `latest` / `has_update` / `notes` / `has_asset`
- `download`：挑 Release 里的安装包下载到本地临时目录，返回路径
- `install`：执行下载好的安装包（Windows）

## 响应新增字段（v2.0）

`/api/qa` 与 `/v1/chat/completions` 的 `jy` 都带：

| 字段 | 取值 | 含义 |
|---|---|---|
| `source` | `model` / `vote` / `bank` / `correction` / `rag` / `cache` | 答案来源 |
| `confidence` | `high` / `medium` / `low` | 置信度（复核一致、投票达标、题库命中 → high） |
| `votes` | `[{"model":"...","answer":"..."}]` | 投票明细，未投票为空数组 |
| `response_format` | `text` / `letter` / `json` | 本次生效的返回形态 |

---

## 错误码约定

| HTTP | 场景 |
|---|---|
| 200 | 一切业务响应，包括答题失败（看 `success` 字段） |
| 204 | `OPTIONS` 预检 |
| 404 | 访问了不存在的路径 |
| 500 | 未捕获异常（正常情况不会发生，异常已被 `_handle` 兜住） |

没有 4xx —— 参数缺失时返回探测响应，参数非法时由配置校验返回 `ok: false`。
