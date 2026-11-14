#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""创建 GitHub Release 并上传 dist 下的安装包/单文件 exe。

用法：python tools/gh_release.py 2.0.4
凭据走 `git credential fill`，不在命令行或日志里出现 token。
网络层全部用 curl 子进程（requests/OpenSSL 对 api.github.com 有 TLS 指纹干扰，会 SSL EOF；
curl 直连稳定）。推送 tag 前先跑一次 git push。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://api.github.com"
REPO = "JiangYangx/ocs-ollama-relay"

CLEAN_ENV = {k: v for k, v in os.environ.items()
             if k.lower() not in ("https_proxy", "http_proxy", "all_proxy")}


def token() -> str:
    p = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        capture_output=True, text=True, cwd=ROOT, env=CLEAN_ENV,
    )
    for line in p.stdout.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("拿不到 GitHub 凭据，先 git push 一次让它存下来")


def curl_json(method: str, url: str, tk: str, data: bytes | None = None,
              headers: dict | None = None, timeout: int = 120) -> tuple[int, dict | str]:
    """curl 子进程请求，返回 (status_code, 解析后的 JSON 或原始文本)。"""
    cmd = ["curl", "-sS", "--retry", "8", "--retry-all-errors",
           "--connect-timeout", "20", "--max-time", str(timeout),
           "-X", method, url,
           "-H", f"Authorization: Bearer {tk}",
           "-H", "Accept: application/vnd.github+json",
           "-H", "X-GitHub-Api-Version: 2022-11-28",
           "-w", "\n%{http_code}"]
    if data is not None:
        cmd += ["--data-binary", "@-"]
    for k, v in (headers or {}).items():
        cmd += ["-H", f"{k}: {v}"]
    p = subprocess.run(cmd, input=data, capture_output=True, env=CLEAN_ENV)
    out = p.stdout.decode("utf-8", "replace")
    if "\n" not in out:
        raise SystemExit(f"curl 无响应：{p.stderr.decode('utf-8', 'replace')[:300]}")
    body, _, code = out.rpartition("\n")
    try:
        parsed = json.loads(body) if body.strip() else {}
    except json.JSONDecodeError:
        parsed = body
    return int(code), parsed


def body_for(ver: str) -> str:
    return f"""### 明亮主题彻底修好

上一版截图暴露的两个界面问题都修了：

- **明亮模式卡片/顶栏残留深色**：根因是主题变量只覆盖了 3 个旧命名变量，实际样式用的是另一套。现在完整镜像 18 项组件级变量（输入框、代码块、表格、统计块、悬浮提示、开关……），并把所有硬编码深色改成变量引用
- **开关滑块错位压住文字**：滑块几何对齐（36×20 轨道 + 16px 滑块），明暗两种主题下都正确居中，颜色随主题走
- 顺手打磨：明亮模式浅色光晕背景、约 20 条组件级明亮覆盖、深色主题回归截图确认无变化

### 新的小功能

- 支持 `?theme=light|dark` 指定主题、`?view=home|adv` 直达首页/设置页（分享链接、远程指导、自动化截图都方便）
- 源码模式改 `console.html` 后刷新浏览器即生效，不用重启服务

### 两个文件选一个

| 文件 | 说明 |
|---|---|
| `JY-Relay-Setup-{ver}.exe` | 安装版（推荐）：带题库、快捷方式、卸载程序 |
| `JY-Relay.exe` | 单文件绿色版：双击即用，**不含题库**，需自己导入 |

> ⚠️ 仅供技术学习与研究，禁止考试作弊、代考、刷课。模型与题库输出均不保证正确，详见 [DISCLAIMER.md](https://github.com/{REPO}/blob/main/DISCLAIMER.md)。

**Full Changelog**: https://github.com/{REPO}/blob/main/CHANGELOG.md
"""


def main() -> None:
    ver = sys.argv[1] if len(sys.argv) > 1 else open(os.path.join(ROOT, "VERSION")).read().strip()
    tag = f"v{ver}"
    tk = token()

    code, rel = curl_json("GET", f"{API}/repos/{REPO}/releases/tags/{tag}", tk)
    if code == 200:
        print(f"Release {tag} 已存在：{rel['html_url']}")
    else:
        body = body_for(ver).encode("utf-8")
        code, rel = curl_json("POST", f"{API}/repos/{REPO}/releases", tk, data=body,
                              headers={"Content-Type": "application/json"})
        if code not in (200, 201):
            raise SystemExit(f"创建 Release 失败 {code}: {str(rel)[:300]}")
        print(f"Release 已创建：{rel['html_url']}")

    existing = {a["name"]: a["id"] for a in rel.get("assets", [])}
    upload = rel["upload_url"].split("{")[0]
    for fn in (f"JY-Relay-Setup-{ver}.exe", "JY-Relay.exe"):
        fp = os.path.join(ROOT, "dist", fn)
        if not os.path.exists(fp):
            print(f"跳过（不存在）：{fn}")
            continue
        if fn in existing:
            curl_json("DELETE", f"{API}/repos/{REPO}/releases/assets/{existing[fn]}", tk)
            print(f"已删除旧资产：{fn}")
        size = os.path.getsize(fp)
        print(f"上传 {fn}（{size/1048576:.1f} MB）…")
        code, up = curl_json("POST", f"{upload}?name={fn}", tk,
                             data=open(fp, "rb").read(),
                             headers={"Content-Type": "application/octet-stream"},
                             timeout=900)
        if code not in (200, 201):
            raise SystemExit(f"上传失败 {code}: {str(up)[:300]}")
        print(f"  ok  state={up.get('state')}  {up.get('browser_download_url')}")

    print("完成：", rel["html_url"])


if __name__ == "__main__":
    main()
