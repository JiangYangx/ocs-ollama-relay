# OCS 网课助手 · AI 答题中转服务

学习通 / 网课自动答题的本地推理通道：`OCS(脚本猫) → 本中转 → 本地 Ollama 或云端大模型`。

![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![Flask](https://img.shields.io/badge/flask-3.0%2B-green)
![License](https://img.shields.io/badge/license-MIT-orange)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey)

**双后端可切换**：

- **本地 Ollama**（默认）：离线、不外传数据、无费用，需要自己跑模型
- **云端 OpenAI 兼容接口**：无需显卡，支持智谱 GLM-4.5-Flash（全免费）、硅基流动 Qwen3-8B 等免费模型；⚠️ 题目会发往云端服务器

**题型自动路由**：图片题自动走视觉模型（如 GLM-4V-Flash / 本地 qwen2.5vl），代码题走代码模型（如 Qwen3-8B），普通文本题走主模型。OCS 端 5.x 的图片题优化（`images` 字段）已内置支持。

**单文件设计**：全部后端逻辑集中在 `ocs_relay.py` 一个文件里，控制台页面在打包时内嵌，产出的 exe 无需任何附属文件。源码会先找同目录的 `console.html`，找不到才用内嵌版本 —— 改界面时不必重新打包就能看效果。

---

## 目录结构

```
ocs-ollama-relay/
├── ocs_relay.py            # 主程序：Flask 服务 + 答题链路 + 自检修复（核心，约 1400 行）
├── console.html            # 网页控制台（暗色主题，零 CDN，可离线）
├── config.json             # 默认配置（首次运行若缺失会自动生成）
├── requirements.txt        # flask>=3.0, requests>=2.31
├── start.bat               # Windows 一键启动
├── build.bat               # Windows 一键打包
├── ocs_relay.spec          # PyInstaller 配置（由 build.bat 调用）
├── ocs_config_for_ocs.txt  # 可直接粘贴到 OCS 题库配置的 JSON
├── tools/
│   └── build_exe.py        # 构建入口：注入控制台 → 调用 PyInstaller
├── docs/
│   ├── API.md              # 接口详解与调用示例
│   └── FAQ.md              # 常见问题排查
├── CHANGELOG.md
├── LICENSE
└── .gitignore
```

> 最小可用：**只要 `ocs_relay.py` 一个文件**（`pip install flask requests` 后直接跑），其余全部可缺省。

---

## 接云端免费大模型

不想装 Ollama / 没有显卡？两分钟切到云端（**注意：题目会发往云端**）：

1. [智谱开放平台](https://open.bigmodel.cn/) 注册 → 实名 → 创建 API Key（GLM-4.5-Flash、GLM-4V-Flash 等全免费，无 token 上限）
2. 控制台 →「配置」→ 模型后端选「云端」→ 填入：

| 字段 | 值 |
|---|---|
| api_base | `https://open.bigmodel.cn/api/paas/v4` |
| 主模型 | `glm-4.5-flash` |
| 视觉模型 | `glm-4v-flash`（图片题） |

或用硅基流动（新用户送 2000 万 Token，Qwen3-8B 永久免费）：`api_base = https://api.siliconflow.cn/v1`，主模型 `Qwen/Qwen3-8B`。两家都需实名认证。

**题型路由**：有图自动用视觉模型、检测到代码特征（`def`/```/`SELECT` 等）自动用代码模型，均可在控制台覆盖。OCS 端配置请重新从控制台复制 —— 新配置带 `images` 字段，否则图片题收不到图。

---

## 快速开始

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

### 第 3 步：接入 OCS

控制台 →「接入 OCS」→ 点「复制配置」→ 粘贴到 OCS 的题库配置里。
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

浏览器打开 `http://127.0.0.1:5000/`：

- **运行状态**：已答 / 成功 / 缓存 / 失败，实时统计
- **自检结果**：8 项检查（Python、Ollama、主/备模型、端口、时间预算、配置、目录权限），失败项自带「修复」按钮：
  - Ollama 未启动 → 自动尝试拉起 Ollama 进程
  - 模型未安装 → 新开窗口执行 `ollama pull`
  - 端口异常 → 自动换到空闲端口
  - 配置损坏 → 备份后用默认值重建
- **最近答题**：题目、答案、匹配方式、耗时，实时列表
- **在线配置**：改模型 / 端口 / 延时 / 预算，保存即时生效（端口除外），不用重启
- **运行日志**：实时滚动，可暂停；同时写入 `relay.log`
- **复制配置**：一键复制 OCS 题库配置（带 `navigator.clipboard` 与 `execCommand` 双重回退）

界面不引任何 CDN 资源，断网也能正常显示。

---

## 打包成单文件 exe

双击 `build.bat`，或手动执行：

```bash
pip install flask requests pyinstaller
python tools/build_exe.py
```

构建链路：`tools/build_exe.py` 读取 `console.html` → base64 注入到 `build/_gen/ocs_relay.py` 的 `_CONSOLE_B64` 占位符 → 调用 PyInstaller（读 `ocs_relay.spec`）→ 输出 `dist/OCS.exe`。

这样 `ocs_relay.py` 源码里不会出现大段 base64，可读性不受影响。

产物：

```
dist/
  OCS.exe          ← 单文件，双击即用（控制台已内嵌，无需其它文件）
  config.json      ← 配置，构建脚本自动复制
```

- 整个 `dist` 文件夹拷到别的电脑也能用（对方需自装 Ollama）
- 配置和日志写在 exe 同目录，便携，不写注册表
- 不想自动开浏览器：`OCS.exe --no-browser`，或配置里 `auto_open_browser: false`

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
  "success": true
}
```

详见 [docs/API.md](docs/API.md)。

---

## 配置项

`config.json`（控制台里也能改，改完即时生效）：

| 键 | 默认 | 说明 |
|---|---|---|
| `backend` | `ollama` | `ollama` 本地 / `openai` 云端 OpenAI 兼容 |
| `api_base` / `api_key` | 空 | 云端必填；本地留空。key 只存本机 config.json |
| `cloud_max_tokens` | `256` | 云端单次生成上限 |
| `model` | `qwen2.5:7b-instruct` | 主模型（普通文本题） |
| `fallback_model` | `deepseek-r1:7b` | 备用模型，主模型失败时自动切换 |
| `auto_route` | `true` | 按题型自动路由 |
| `vision_model` | 空 | 图片题模型，如 `glm-4v-flash` / 本地 `qwen2.5vl:7b` |
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
| `num_predict` | `256` | 最多生成 token（仅本地） |
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

---

## 内置优化

**三级降级**
`think=False` → 失败则不带 `think` 字段重试 → 仍失败换备用模型。任何一档成功即返回。

**整题时间预算**
默认 50 秒内必返回（OCS 上限 60 秒）。每次重试的超时按剩余预算自动收缩：`per_timeout = min(request_timeout, max(3.0, 剩余时间 / 剩余次数 × 1.5))`，最坏情况也不会被 OCS 截断。

**思考链清洗**
完整 / 未闭合 / 大写 / 带属性 / 带空格的 `<think>`、中文「思考：」段、「答案：」前缀、括号解释、包裹引号、选项字母前缀 —— 8 步流水线全部剥离。R1 系模型也不会把思考内容当成答案。

**答案匹配**
优先返回**选项正文**（走 OCS 文本精确匹配 → 相似度 0.6 → 字母下标三级回退），不受选项顺序影响。支持多选（多行 / `|` 分隔 / 字母组合）、多空填空。

**串行队列 + LRU 缓存 + 启动预热**
同一时刻只跑一次推理（`max_concurrency` 可调，云端可放宽），其余排队；重复题秒回（TTL + LRU，默认 1024 条）；缓存 key 含 backend / model / 图片摘要，换模型不会命中旧缓存；启动时预热一次，第一题不用干等。

**访问控制与隐私**
`auth_token` 一键开启接口鉴权（`X-Relay-Token` 头 / `?token=` 参数），防止局域网内他人盗用；控制台与配置接口对 `api_key` / `auth_token` 做掩码回显（`***` + 末 4 位），提交掩码值不会覆盖真实密钥；`privacy_log` 开启后日志中题干与答案掩码显示。

**正确率增强（v1.2.x）**
答题优先级：**人工订正 > 导入题库 > 缓存 > 双模型交叉验证的模型答案**。题库命中零成本秒回；答错的题在控制台一键订正后永久生效；`verify_mode=full` 时主模型与复核模型不一致会交给第三个仲裁模型裁决，响应 `verify` 字段标注置信情况（agree / conflict / arbitrated）。

---

## 节律控制（降低机器特征）

每题返回前补足到 **500~1500ms 随机间隔**。注意这不是傻 `sleep`，而是**间隔补足**：`wait = max(0, 目标间隔 - 已耗时)`。

| 情况 | 行为 |
|---|---|
| 推理本身已超过目标间隔 | 不再追加，直接返回 |
| 距上一题已超过 `max_gap_ms`（6 秒） | 直接放行，不叠加延时 |
| 缓存命中 | 照样延时（否则 2ms 出答案，一眼是机器） |
| 请求失败 | 照样延时（避免「秒失败」成为特征） |

间隔分布右偏（`max(u1, u2)` 两次均匀取大），小间隔少于大间隔，接近真人反应时间。

> 延时只管理**本地返回时间**。页面上的点击节奏需在 OCS 设置里把答题间隔调到 5~8 秒。

---

## 常见问题

| 现象 | 处理 |
|---|---|
| 控制台显示 Ollama 未连接 | 点自检里的「修复」自动拉起；或手动打开小羊图标 |
| 主模型显示未找到 | 点「修复」自动 `ollama pull`；或手动执行 |
| 答题超时 | 7B 纯 CPU 每题 20~60s 属正常；换 `qwen2.5:3b` 或开 GPU 加速 |
| 端口被占 | 控制台改端口保存，重启后生效，OCS 的 URL 要同步改 |
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

## ⚠️ 使用须知

- 本地 Ollama 后端仅用于**本地模型推理技术学习**，程序不联网、不上传任何数据（除本机 Ollama）。
- **切换到云端后端后，题干 / 选项 / 题目图片会发往所配置的云端服务器**，请自行确认接受该隐私变化；api_key 只保存在本机 config.json，控制台回显已掩码。
- 建议：局域网使用时设置 `auth_token`；对外分享日志或录屏演示时开启 `privacy_log`。
- 自动答题违反学习通等平台的用户协议，存在封号风险，请自行评估后再决定是否使用。
- 本项目不含任何题库、不破解任何验证，仅做「大模型 → 标准接口」的协议适配。
- 因使用本软件产生的一切后果由使用者自行承担，作者不承担任何责任。详见 [LICENSE](LICENSE)。

---

## 许可证

[MIT](LICENSE)
