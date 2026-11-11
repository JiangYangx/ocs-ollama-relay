# 更新日志

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [2.0.3] - 2026-11-11

> 主题：让数字可信、让题库查得准、让启动有反馈。

### Added

- **正确率估算**：首页「最近正确率」不再永远显示 `—`。现在按「模型作答数 − 答错标记数」自动估算（排除题库/相似题/缓存命中的题，那些不反映模型能力）；人工核对过的题单独显示精确值，两种来源在界面上明确区分
- **内置题库升级合并**：导入标记从"导没导过"改为"哪个版本处理过"——升级安装包带了新题库时自动增量合并（只加题、更新同题答案，不删已有条目；人工订正优先级更高，不受影响）
- **`bank_no_delay` 开关**（设置 → 正确率增强）：题库命中跳过拟人节律，真毫秒级返回；默认关，批量答题场景建议保持关
- **导入进度横幅**：内置题库导入挪到后台线程，服务先起、页面先开，导入状态显示在首页横幅（窗口版不再"白屏等导入"）
- 题库条目引入 `verified` 字段：人工订正过的题命中标 `high`，纯导入的题标 `medium` 并提示可订正确认
- README 加桌面端 / 手机端截图

### Changed

- **RAG 相似题检索默认开启**（`rag_enable=true`，`rag_direct` 0.88→0.92，`rag_inject` 0.75→0.78）：题干有错字、标点差异也能命中题库；v2 配置自动迁移到 v3 时统一打开，不想要的在设置里关一次即可
- 配置模板同步到 v3 完整字段（此前模板停留在 1.x，缺 v2.0 新增项）

## [2.0.2] - 2026-11-11

### Added

- **安装包内置题库**：`bank/*.csv`（CMMLU 整理，共 12,868 条）随安装包分发，首次启动自动导入 SQLite，装完即可离线命中，不必自己找题库
- `bank/LICENSE-NOTICE.txt`：内置题库的出处、CC BY-NC 4.0 许可、署名与免责说明，随安装包一并复制到 `{app}\bank`

### Changed

- CSV 题库解析抽成 `csv_text_to_bank_text()`，`/api/bank/import` 与控制台导入共用同一套逻辑
- 自动导入只做一次（SQLite meta 标记 `bundled_bank_imported`），用户之后清空题库不会被再次塞回；已有 ≥1000 条题库时跳过，不覆盖既有积累

## [2.0.1] - 2026-11-11

### Added

- `DISCLAIMER.md`：完整免责声明（用途限定、明确禁止项、题库版权、准确性实测参考、无担保与责任限制、适用法律）
- README 顶部加醒目提示，`## 使用须知` 扩写为「使用须知与免责声明」

### Fixed

- 模型不守格式时（回一段英文分析、`正确答案：C`、`本题选 B`、`H` 之类越界字母），原逻辑把整段解释当答案返回。现按「明确指认字母 → 唯一出现的选项正文 → 末尾提到的选项」三级回捞
- 答案没能对上任何选项时仍可能标 `high`（实测出现过 `verify=agree` 但答案是 `H` 的「高置信错误」），现统一降为 `low` 并附提示

## [2.0.0] - 2026-11-08

> 主题：从「答题工具」变成「可被任何客户端调用的答题服务」。
> 四轴同时推进：正确率（投票）、速度（快路 + 并行复核）、适配性（OpenAI 兼容 + 字段映射）、便捷性（数据页 + 档位 + 自动迁移）。

### Added

**多模型投票（正确率）**
- `vote_models` / `vote_min`：配置多个模型各投一票，最高票达到阈值才改写主模型答案；主模型答案算第 1 票，其余模型**并发**补票（不把延迟乘上模型数）
- 结果新增 `source`（model / vote / bank / correction / rag / cache）与 `confidence`（high / medium / low），前端直接打徽章
- 票数不足时保留主模型答案，并在 `note` 里写明「最高 X 票，未达 Y 票」

**快路与并行复核（速度）**
- `fast_path_max_len`：短于该字数的单选直连模型，跳过投票 / CoT / 自检（填 0 关闭）
- `verify_parallel`：复核请求与主模型并行发出，整体耗时≈max(主, 复核) 而非两者相加；本地 Ollama 自动降级为串行（避免抢显存反而更慢）
- `cache_normalize`：缓存键忽略空格与标点，同一题换排版也能命中
- 题库 / 相似题命中改为沿用 `delay_on_cache` 开关，不再强制补节律

**适配层（适配性）**
- **`POST /v1/chat/completions`**：标准 OpenAI 响应结构，ChatBox / LobeChat / 各类插件可直接接入；额外带非标准 `jy` 扩展字段（source / confidence / votes / ms / cached）
- `api_mode`（auto / ocs / openai）：限定只收哪种请求形态
- `field_map`：字段名翻译，例如 `{"title":"question","options":"choices"}`
- `response_format`（text / letter / json）：`letter` 只回 A/B/C，`json` 回完整结构
- `cors_allow_origin`：按需发送 CORS 头（浏览器插件 / 网页前端跨域调用）
- 请求解析兼容 `options` 为 `[{"key":"A","text":"北京"}]` 结构化数组，也兼容字符串里塞 JSON 数组

**数据页（便捷性）**
- 控制台顶栏新增「历史 / 错题 / 题库」三个入口（全屏浮层，不打断原有布局）
- 历史：分页 + 关键词搜索 + 来源徽章 + 置信度 + 耗时 + 一键订正
- 错题：从 `quiz` 表按答错记录列出，直接订正
- 题库：拖文件导入（CSV / JSON / TXT）、文本粘贴导入、题库概况

**准确率档位**
- `GET/POST /api/accuracy`：fast / balanced / accurate 三档，一次设定同时改 `tier` + `verify_mode` + `cot_mode` + `self_check`，避免只调一项导致参数互相打架
- 设置页「正确率增强」顶部三个按钮，点一下即时生效

**新接口**
- `GET /api/wrong`：错题列表
- `POST /api/bank/import`：支持 multipart 文件（CSV/JSON/TXT）与 JSON body；CSV 自动识别表头；`items` 里的题干字段兼容 `question/title/q/题目`，答案兼容 `answer/a/答案`
- `GET /api/history?page=&limit=&q=`：改为分页 + 搜索，返回 `total` / `pages`
- `GET /api/update/download` + `POST /api/update/install`：自动挑 Release 里的安装包下载 / 安装
- `GET /api/accuracy`：返回三档预设内容，前端据此渲染

**配置与版本治理**
- `VERSION` 文件成为唯一版本来源：`ocs_relay.py` 运行时读、构建脚本注入兜底值、`installer.iss` 由 `build_installer.bat` 传入 `/DMyAppVersion`
- `config_version` 自动迁移：老配置启动时自动补齐新增项，**只补缺不改值**，动手前备份为 `config.json.bak.v{旧版本}`
- `lan_share` 开关进设置页；没有访问令牌时**双重保险**自动回落 `127.0.0.1`（保存时改回 false，启动时再兜一次）

### Changed
- `EDITABLE_FIELDS` 支持 list / dict 类型：`vote_models` 可直接填 `a, b, c`（逗号 / 中文逗号 / 换行都行），`field_map` 填 JSON 对象字符串
- 结果字典新增 `source` / `confidence` / `votes`，题库与相似题命中也标注来源
- 控制台「准确率增强」页重排：档位按钮 → 三件套 → 投票与速度 → 图片预处理

### Fixed
- **`options` 为结构化数组时变成 Python dict 字符串**：`[{"key":"A","text":"北京"}]` 以前会被 `str()` 成 `"{'key': 'A', 'text': '北京'}"`，导致答案匹配失败、答题结果里出现一坨 dict 文本。现在统一走 `_opt_to_line()` 转成 `A. 北京`
- **配置迁移永远不触发**：`DEFAULT_CONFIG` 自带 `config_version: 2`，合并后读到的永远是「最新版」。改为按文件里的原始值判断
- **题库 JSON 导入题干丢失**：`items` 里用 `title` 而非 `question` 时题干为空，选项整体错位成题干。现在兼容多种字段名，并在题干/答案缺失时直接跳过
- `/api/bank/import` 选项文本含 `|` 时会破坏单行格式，导入前替换为 `/`
- **窗口版 exe 吞掉命令行参数**：`tray_app.py` 里 `sys.argv = [argv0, "--no-browser"]` 把
  `--port` / `--model` 全部丢弃，`JY-Relay.exe --port 5098` 仍然监听 5000。现在保留原参数，
  端口按「命令行 > 配置文件」取
- **`tools/build_installer.bat` 在装了多个 Python 的机器上失败**：脚本直接调 `python`，
  可能指向没有 PyInstaller 的解释器。现在支持 `set PYTHON=...` 指定，并在打包前做依赖预检

### 使用提示
- 多模型投票在本地两个 7B 模型上会互相抢显存（实测 12s），**建议只在云端后端开启**；本地想快就把 `vote_models` 留空
- 升级后 `config.json` 会被自动补上十几个新配置项，原有值不动；如需回滚，用同目录的 `config.json.bak.v1`


## [1.5.0] - 2026-11-08

> 主题：像一个正经软件。功能不加不减，把「控制台」变成「答题助手」。

### Added
- **单入口首页**：打开只有状态、三个数字（今天答题 / 最近正确率 / 平均耗时）和「开始答题」，全部参数收进「⚙ 设置」
- **开始答题三步弹层**：复制配置 → 粘到客户端 → 手机扫码，不用翻文档
- **开机自启**：设置页一键开关（Windows 注册表 / Linux autostart / macOS LaunchAgent）
- **自动检查更新**：启动查 GitHub 最新 Release，有新版顶部提示条；3 秒超时静默失败，结果缓存 6 小时，可在设置关闭
- **错误说人话**：`/api/qa` 失败新增 `hint` 字段（模型没下载 / 密钥无效 / 限流 / 连不上，各给一句中文）
- **今日摘要接口**：`GET /api/summary`；`/api/status` 新增 `backend`
- **品牌图标**：`assets/jy.ico` / `jy.png`，exe 不再是默认图标

### Changed
- 首页文案去术语化：不出现 p50/p95/token/RAG；「最近答题」列表移到首页
- 档位说明改为「快一点 / 正常 / 准一点，参数自动配套」

### Fixed
- **打包配置误排除 `sqlite3`**：1.4.0 的 exe 可能因此无法持久化（题库/历史不落盘），1.5.0 重新打包后恢复，请务必更新

### 新增文件
- `tray_app.py`（托盘入口，可选依赖 pystray）、`tools/build_app.py`（窗口版构建）、
  `ocs_relay_app.spec`（无黑框打包配置）、`installer.iss` + `tools/build_installer.bat`（Windows 安装包）


## [1.4.0] - 2026-11-08

### Added
- **候选题库确认入库**：模型答过的题进入候选区，控制台逐条/批量「✓ 收录 / ✗ 丢弃」，同题多记录一并处理，防错题固化
- **真实正确率核对**：总览页「核对正确率」抽最近 20 题人工判断对错，按天累计正确率曲线（quiz 表持久化）
- **答题流 👎 标记**：答错的题一键标记（不改正答案，只进正确率统计）
- **首次三步引导**：未配置模型时自动弹出——选服务商 → 填 Key 测通 → 复制接入配置，可跳过、不再打扰
- **配置迁移**：导出 / 导入 `.jyconfig`（不含 api_key，导入一律拒收 api_key）
- **局域网二维码**：自动探测局域网 IP + 拼接令牌生成扫码链接（内嵌 qrcode-generator，离线可用）
- **明暗主题切换**（记忆偏好）与移动端单列布局
- 图片预处理开关进界面（缩放 / 灰度 / 降噪）
- 新接口：`/api/bank/candidates` GET/POST、`/api/quiz/sample`、`/api/quiz/mark`、`/api/quiz/stats`、`/api/config/import`；`/api/status` 新增 `lan_ip`

### Changed
- 答题流记录保留完整题干并携带 `hid`（历史 id），供订正与标记还原
- `history` 表新增 `status` 列（旧库自动迁移）；新增 `quiz` 表

## [1.3.1] - 2026-11-08

### Added
- 一键推荐新增 **DeepSeek** 与 **豆包（火山方舟）** 预设：自动写入后端地址（`https://api.deepseek.com` / `https://ark.cn-beijing.volces.com/api/v3`）与推荐模型名，OpenAI 兼容协议直连
- 推荐按钮文案改为明确标注「有免费档」，避免误解为唯一选择

### Changed
- 套用预设后的提示改为三步引导（填 Key → 拉取模型确认 → 保存自检）

## [1.3.0] - 2026-11-08

### 一键档位（三层协同预设）

- 控制台顶部新增档位条：**极速刷题 / 平衡日常 / 高正确率**，一键写入验证方式、CoT、token 上限、答题间隔与超时预算（三者协同，避免「档位说极速、token 太小反复重试反而更慢」）。
- 单项参数仍可覆盖；当前档位自动反推高亮。

### SQLite 持久化（jy_store.py）

- **缓存落库**：重启后昨天答过的题仍然秒回（L1 内存 LRU + L2 SQLite 写穿）。
- **题库 / 订正 / 历史 / 指标**统一进 `jy_data.db`（WAL 模式），旧 `bank.json` / `corrections.json` / `history.jsonl` 首次启动自动迁移（幂等）。
- **命中计数从「全量重写 json」改为「单行 UPDATE」**：题库上万条时命中耗时从 148ms → 1ms 级。
- 题库记录补齐 `question` 字段（此前只有题干摘要，RAG 与统计无法使用）。

### 相似题检索（jy_rag.py，默认关）

- 双后端：`ngram`（字符 2-gram + IDF 余弦，纯标准库零依赖）/ `vector`（Ollama embedding，如 bge-m3，需 numpy）。
- 相似度 ≥ `rag_direct`(0.88) 直接采用答案；`rag_inject`(0.75)~`rag_direct` 作为参考注入提示词。
- 索引缓存到 `rag_index.pkl`，题库变化自动后台重建。
- ⚠ 阈值必须随 embedding 模型重新校准；`all-MiniLM-L6-v2` 对中文无效，不要用。

### 答案自检（jy_check.py）

- 拦截五类低级错误：空答案、越界字母（只有 A~D 却答 E）、答案不在选项范围内（模型自造选项）、多选漏选、解释文字混入。
- 可自动修正的当场修正；不能的自动重答一次（带自纠正指令），预算不足时跳过并记录。

### 前置预处理（jy_prep.py）

- 文本：去 HTML 标签 / 实体 / 广告行 / 多余空白（只作用于送模型的内容，不碰题库 key）。
- 图片：长边缩放到 1280 + 锐化；灰度 / 降噪做成开关且**默认关**（图表、地图的颜色本身就是解题信息）。
- 学科关键词软识别（≥2 个关键词才生效，只补提示词预设）；复杂度判定（多选 / 长题干 / 计算词 → 自动开 CoT）。

### 网络与容错

- **HTTP Session 连接复用**：每题省一次 TCP+TLS 握手（云端实测 80~200ms）。
- **跨后端兜底**：云端超时 / 500 / 断网时自动切本地 Ollama（`local_fallback_url` + `local_fallback_model`），不再整题失败。
- 逐次指标落库：p50 / p95 / 命中率 / 来源分布（`/api/metrics`）。

### 控制台

- 顶部档位条 + 实时 KPI（p50 / p95 / 直接命中率）。
- 答题表新增「来源」列（题库 / 相似题 / 缓存 / 模型 / 图片 彩色徽章）与**行内一键订正**（✎ 写入后永久生效）。
- 题库文件**拖拽导入**：`.txt` 直读、`.csv` 自动识别「题干/选项/答案」列、`.json` 题库格式；GBK / UTF-8 自动探测。
- 新增接口：`/api/tiers` `/api/tier` `/api/metrics` `/api/rag` `/api/rag/rebuild` `/api/history` `/api/export/config` `/api/export/diagnose`（诊断 zip：脱敏配置 + 日志 + 环境 + 指标）。

### 说明

- v1.2.2 的自动建库保留原逻辑（防错过滤不变）；「人工确认入库」作为后续可选策略。
- 新文件 `jy_store.py` `jy_prep.py` `jy_rag.py` `jy_check.py` `jy_tiers.py` 全部为**可选导入**：任何一个缺失，程序退化为 v1.2 行为而不是起不来。

## [1.2.3] - 2026-11-07

### 新增：公开题库接入（C-Eval）

- **`tools/fetch_ceval.py`**：从镜像拉取公开学术题库 **C-Eval**（52 个学科、13685 道单选题，覆盖计算机 / 数学 / 法律 / 医学 / 经济 / 公务员 / 中学各科），自动去重并转成可导入格式：
  ```bash
  python tools/fetch_ceval.py --list                    # 看学科
  python tools/fetch_ceval.py --subjects computer_network,operating_system
  python tools/fetch_ceval.py --json bank.json          # 全量 1.3 万题，直接进库
  ```
  数据缓存在 `~/.cache/jy-relay/ceval`，重复运行不重复下载。许可证 **CC BY-NC-SA 4.0**：仅个人学习/研究使用，不得商用，再分发需保留署名与相同许可。
- **多行题干修复**：`make_bank.py` 输出时把题干/选项内的换行压平。此前代码题（C++ 片段）会被解析成多道残题，全量导入时 75 条报错，现在 **0 报错**。

### 修复：大题库命中变慢

- 题库命中原本每次都重写整个 `bank.json`。题库上万条时，一次命中要写 5MB，实测 **148ms**；改为命中计数攒 50 次落盘一次后降到 **1.3ms**，同时避免磁盘写放大。
- `bank_lookup` 的命中计数改为持锁更新，消除并发下的字典竞态。

## [1.2.2] - 2026-11-07

### 新增：题库自动积累（越用越准、越用越快）

- **答题历史落盘（history.jsonl）**：每次真实作答（缓存与题库命中除外）自动把题干、选项、答案、置信信息追加到 `history.jsonl`，为自动建库积累原料。
- **一键自动建库**：控制台「题库与订正」新增「从历史记录建库」，接口 `POST /api/bank/auto`。可信过滤规则：
  - 双模型交叉验证一致（`agree` / `arbitrated`）的题直接收录；
  - 同一题历史上出现过多答案、或验证冲突（`conflict`）的题自动过滤，不把偶发错误固化；
  - 题库已有的题默认跳过，重复执行幂等。
- 实测：题库命中 `cost=0`、整题耗时 **2~3ms**（关闭礼貌间隔时），对比模型推理 10~40s；开启间隔时时 ~1s（延迟是刻意加的，可在「高级」里调）。
- **题库转换器（tools/make_bank.py）**：把 CSV / TSV / Excel 一键转成可导入的题库文本或直接生成 `bank.json`。列名中英文自动识别，选项支持「一格合并」或 A/B/C/D 分列，编码自动探测（UTF-8 / GBK）。key 算法与主程序一致，生成的 `bank.json` 可直接命中。
- **示例题库（tools/sample_bank.txt）**：31 条公开通识题，用于验证导入链路与命中速度，也可作为通用知识兜底。
- `.gitignore` 增补 `history.jsonl`（个人答题数据，勿提交）。

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
