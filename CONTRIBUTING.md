# 贡献指南

感谢你愿意为本项目做出贡献。

## 提交前

1. 先搜索已有的 [Issue](../../issues)，避免重复
2. 大改动请先开 Issue 讨论方案，避免白做功

## 开发约定

| 项目 | 约定 |
|---|---|
| 架构 | **保持单文件**：新逻辑写进 `ocs_relay.py`，不拆模块 |
| 前端 | 改 `console.html`，不引入 CDN 依赖，保持可离线 |
| 代码风格 | 4 空格缩进、行宽约 100、注释用中文、函数单一职责 |
| 兼容性 | Python 3.9+，Windows / Linux / macOS 三端可用 |

## 本地自测

```bash
# 1. 装依赖
pip install -r requirements.txt

# 2. 启动（不自动开浏览器）
python ocs_relay.py --no-browser

# 3. 打开 http://127.0.0.1:5000/ ，自检应全部通过

# 4. 用 curl 发一题验证链路
curl -X POST http://127.0.0.1:5000/api/qa \
  -H "Content-Type: application/json" \
  -d '{"title":"中国的首都是哪里","options":"A. 上海\nB. 北京","type":"single"}'
```

## 提交 PR

1. Fork → 从 `main` 切分支（`feat/xxx` 或 `fix/xxx`）
2. 提交信息用中文，格式：`fix: 修复 xxx` / `feat: 新增 xxx` / `docs: 更新 xxx`
3. PR 描述里写清：**动机、改动点、验证方式**（最好附 curl 或截图）
4. 确认没有提交个人数据（`config.json` 里的 key、`bank.json`、`corrections.json`、`relay.log`）

## 不要做的事

- 不要在 PR 中提交打包好的 `.exe`（走 Release 附件分发）
- 不要在代码或文档中加入针对特定平台的功能性描述
- 不要引入需要联网才能加载的前端资源

## 许可证

提交即表示你同意以 [MIT](LICENSE) 协议授权你的贡献。
