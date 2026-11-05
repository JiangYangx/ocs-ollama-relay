# 更新日志

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [1.2.1] - 2026-11-04

### 修复：云端答题稳定性（来自实测反馈）

- **截断自动扩容**：思考型模型（GLM-5 / Qwen3 思考）在 token 上限太小时会把额度全花在思考链上，正文被截空，此前报「模型输出为空」。现在检测到 `finish_reason=length` 时自动把 token 上限翻倍（上限 4096）并重试一次，无需手工改配置。默认 `cloud_max_tokens` 256 → 1024。
- **模型存在性校验**：`vision_model` / `code_model` 填了当前后端不存在的模型（如智谱里填硅基流动的 Qwen）时自动回落主模型，不再白白失败一轮；控制台「配置体检」会主动提示哪些模型名有问题。
- 错误信息改为可行动：「模型输出为空」现在明确提示去调大 token 上限或关闭 CoT。

### 界面美化

- 配置区改为 **4 个标签页**：① 模型接入 ② 正确率增强 ③ 题库与订正 ④ 高级，不再一页平铺 20+ 项。
- 新增「**一键推荐**」：智谱免费 / 硅基流动免费 / 本地 Ollama 一键套用推荐配置（含 api_base、模型名、token 上限）。
- 新增「**云端 token 上限**」「并发数」控制台字段；开启 CoT 时弹出 token 不足警告。
- api_base / api_key 必填项红色标注，提示带完整正确示例。
- 保留 JY logo 与深色主题，移动端适配同步优化。



### 新增：正确率增强套件

- **题库优先（bank.json）**：控制台粘贴导入题库（支持块格式「题干 / A. 选项 / 答案：B」与单行「题干|A. xx|B. xx|答案：B」），命中直接返回、零模型消耗、零成本。选项带不带字母前缀都能命中；接口 `GET/POST/DELETE /api/bank`。
- **人工订正闭环（corrections.json）**：控制台「题库与订正」卡片里，从最近答题记录一键选用题目、填入正确答案，永久生效且优先级最高（订正 > 题库 > 缓存 > 模型）。接口 `GET/POST/DELETE /api/corrections`。
- **双模型交叉验证（verify_mode）**：`fast` = 备用模型复核，答案一致标注"高置信"、不一致标注"低置信"；`full` = 不一致时再用第三个**仲裁模型**（`arbitrate_model`，留空则只标注不仲裁）裁决，仲裁一致则改采仲裁答案。响应新增 `verify` 字段（agree / conflict / arbitrated）。
- **提示词学科预设（prompt_preset）**：法律 / 医学 / 数学 / 理工 / 英语五套审题提示，针对学科特点定制（如法律题提示"绝对化说法通常是错的"）。
- **CoT 先推理再作答（cot_mode）**：难题先输出简短分析再给答案，多选/计算题更准（稍慢）。
- 配置项新增：`bank_enabled` / `verify_mode` / `verify_model` / `arbitrate_model` / `prompt_preset` / `cot_mode`，控制台均已可视化。

### 修复

- 仲裁模型最初误用主模型（temperature=0 必然复述原答案），已改为独立 `arbitrate_model`。
- 题库/订正的题目 key 对选项做去字母前缀归一，OCS 请求（带 `A.` 前缀）与导入题库（纯文本）能命中同一条；仅填题干的订正也能命中。



### 安全加固（修复批次）

- **访问令牌**：新增 `auth_token` 配置。开启后所有接口（除 `/api/health`）需带 `X-Relay-Token` 请求头、`?token=` 参数或 `relay_token` Cookie，否则返回 401。局域网内他人无法再偷用你的服务、看到你的题目记录。
- **密钥回显掩码**：`/api/config` GET 对 `api_key` / `auth_token` 返回 `***` + 末 4 位；提交空值或 `***` 开头的值不会覆盖真实密钥。控制台不再明文暴露密钥。
- **隐私日志**：新增 `privacy_log` 开关，开启后日志中的题干与答案只显示首尾各 2 字 + 掩码（如 `隐私…*********`），适合录屏/投屏/分享日志场景。

### 稳定性与工程修复

- **缓存隔离**：缓存 key 加入 `backend` 与 `model`，切换后端/模型后同题不会命中旧模型缓存。
- **限流明确提示**：云端返回 HTTP 429 时立即中断重试链，报"云端限流（HTTP 429）"并给出放慢节奏的建议，不再误报为模型故障。
- **并发可调**：新增 `max_concurrency`（1–8，默认 1）。本地模型保持 1；云端可设 2–4 提升吞吐（修改需重启）。
- **失败可观测**：响应新增 `route`（text / code / image / image-fallback）字段与"路由模型未成功，由 X 兜底"提示；缓存未命中响应补齐 `cached: false` 字段。
- **跨平台自修复**：`apply_fix` 在 Linux / macOS 上用 `shutil.which("ollama")` 定位并以子进程方式拉起服务，日志落 relay.log，不再仅限 Windows。
- **打包**：exe 关闭 UPX 压缩（`upx=False`），降低杀毒软件误报率。
- **自测工具**：新增 `tools/test_vision.py`，生成带文字的测试图片，端到端验证图片题链路（云端视觉模型或本地链路）。
- 控制台移动端横向溢出修复（`.grid > *{min-width:0}` + 640px 断点适配）。



### 新增：云端大模型后端

- **双后端可切换**：`backend` 配置项支持 `ollama`（本地，默认）与 `openai`（OpenAI 兼容云端）。控制台一键切换，填 `api_base` + `api_key` 即用。
- 免费云端实测可用：智谱 GLM-4.5-Flash（全免费）、硅基流动 Qwen3-8B（永久免费）；任何 OpenAI 兼容服务均可接入。
- 云端请求自动带 `Authorization: Bearer`；`reasoning_content`（GLM-4.5 / Qwen3 思考模式）与正文分开清洗，思考链不会混进答案。
- 自检适配：云端模式显示"云端服务"、检查模型 id 是否存在；`list_models` 走 OpenAI `/v1/models`。

### 新增：题型自动路由

- **图片题**：`auto_route` 开启时，请求带 `images` 数组自动切换 `vision_model`（智谱 GLM-4V-Flash 免费 / 本地 qwen2.5vl）。OpenAI 分支构造多模态 `content` 数组；Ollama 分支走原生 `images` 参数。
- **代码题**：题干命中代码特征（```、def、function、SELECT 等 20+ 签名）时切换 `code_model`（如 Qwen3-8B）；未配置回落主模型。
- 接收 OCS 5.x 图片题字段：`images`（handler 解析器形式）与 `suggestion_title` / `suggestion_options`（拼入提示词辅助理解）。`_ocs_snippet()` 生成的配置已带这些字段，**旧配置的用户需重新复制**。
- 缓存 key 加入图片摘要，同题干不同图不再互相污染。
- 自检新增"题型路由"项：未配 vision_model 时警告"图片题将走主模型"。
- 新配置项：`backend` / `api_base` / `api_key` / `cloud_max_tokens` / `auto_route` / `vision_model` / `code_model`；环境变量 `BACKEND` / `API_BASE` / `API_KEY` 可覆盖。

### 注意

- 接云端后题目内容会发往外部服务器，README 使用须知已同步更新。
- OCS 图片题仅在 POST + OCS 5.1+ + 开启图片题优化时生效。

## [1.0.0] - 2025-11-01

首个稳定版本。单文件架构定型，附带 Windows 绿色单文件 exe。

### 核心

- **单文件中转服务**：`ocs_relay.py` 包含 Flask 服务、答题链路、自检修复全部逻辑，约 1400 行，不依赖任何自定义模块。
- **页面加载三级降级**：程序同目录的 `console.html` → 打包时注入的内嵌 base64 → 极简兜底页。任何情况下控制台都能打开，接口始终可用。
- **首次运行自举**：`config.json` 缺失时自动按默认值生成，无需手工准备。

### 答题链路

- **三级降级**：`think=False` → 不带 `think` 字段重试 → 切换备用模型。任一档成功即返回。
- **整题时间预算**：默认 50 秒硬截止（OCS 上限 60 秒），重试超时按剩余预算自动收缩 `per_timeout = min(request_timeout, max(3.0, 剩余 / 剩余次数 × 1.5))`。
- **8 步答案清洗**：剥离完整 / 未闭合 / 大写 / 带属性 / 带空格的 `<think>`、中文「思考：」段、「答案：」前缀、括号解释、包裹引号、选项字母前缀。
- **选项正文优先**：返回选项文字而非字母，走 OCS 文本精确匹配 → 相似度 0.6 → 字母下标三级回退，不受选项顺序影响。
- **多选 / 判断 / 填空**：按 `type` 构造不同提示词，多选支持多行、`|` 分隔、字母组合三种输出形态。
- **串行队列**：`BoundedSemaphore(1)` + 等待计数，上限 `max_queue=32`，避免并发抢显存导致全部变慢。
- **LRU + TTL 缓存**：默认 1024 条，同题秒回。
- **启动预热**：程序起来时跑一次空推理，第一题不用等模型加载。

### 节律控制

- **间隔补足**而非固定 `sleep`：`wait = max(0, 目标间隔 - 已耗时)`，推理本身够慢时不再追加。
- **右偏分布**：`max(u1, u2)` 两次均匀取大，小间隔少于大间隔。
- **缓存命中与失败同样延时**，避免"2ms 出答案""秒失败"成为机器特征。
- **`max_gap_ms` 保护**：距上一题超过 6 秒直接放行，防止长时间停顿后突然连发。

### 控制台

- 暗色主题，零 CDN 依赖，完全离线可用。
- 实时统计（已答 / 成功 / 缓存 / 失败）、最近答题表格、增量滚动日志。
- 在线改配置，保存即时生效（端口需重启），带完整校验。
- 一键复制 OCS 题库配置（`navigator.clipboard` + `execCommand` 双回退）。
- 8 项自检，失败项自带修复按钮。

### 接口

- `POST/GET /api/qa`：答题；无 `title` 时返回服务信息供 OCS 探测；`HEAD`/`OPTIONS` 恒 200/204。
- `GET /api/status`：统计 + 答题记录 + 增量日志。
- `GET/POST /api/config`：读写配置，原子写入，保留 `_` 注释键。
- `GET /api/diagnose` / `POST /api/fix`：自检与一键修复。
- `GET /api/health`：轻量健康检查。
- **错误也返回 200**（`success: false` + `error`），避免 OCS 卡片显示"连接失败"而看不到原因。

### 构建

- `tools/build_exe.py`：注入控制台 → 调用 PyInstaller，产出真正自包含的 `dist/OCS.exe`。
- `ocs_relay.spec` 从 `build/_gen/ocs_relay.py` 引导，未走构建脚本时给出明确报错提示。
- `build.bat` / `start.bat` 均为纯 ASCII，规避 Windows 中文乱码。

### 已知限制

- 单文件 exe 依赖 PyInstaller，易被杀软误报，需加白名单。
- 纯 CPU 跑 7B 模型每题 20~60 秒，属硬件限制。
- 无鉴权，默认仅监听 `127.0.0.1`；暴露到局域网需自行评估风险。
