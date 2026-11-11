#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""创建 GitHub Release 并上传 dist 下的安装包/单文件 exe。

用法：python tools/gh_release.py 2.0.2
凭据走 `git credential fill`，不在命令行或日志里出现 token。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://api.github.com"
REPO = "JiangYangx/ocs-ollama-relay"


def token() -> str:
    p = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        capture_output=True, text=True, cwd=ROOT,
        env={**os.environ, "https_proxy": "", "http_proxy": "",
             "HTTPS_PROXY": "", "HTTP_PROXY": ""},
    )
    for line in p.stdout.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("拿不到 GitHub 凭据，先 git push 一次让它存下来")


def body_for(ver: str) -> str:
    return f"""### 安装包现在自带题库

以前装完是空题库，还得自己去找数据。这次把 **CMMLU 整理题库（11,576 道，67 科）** 打进了安装包：

- 首次启动自动导入，1 秒级完成，之后这些题命中就是 `source=bank`、`cost=0`、毫秒级返回
- 只导入一次（SQLite meta 标记），你在控制台清空题库后**不会**被再塞回来
- 已有 ≥1000 条题库时自动跳过，不覆盖你自己攒的题
- 不想用：控制台「题库」页一键清空即可

题库来自公开数据集 [CMMLU](https://github.com/haonan-li/CMMLU)，**CC BY-NC 4.0，仅限非商业使用**，出处与署名见安装目录 `bank\\LICENSE-NOTICE.txt`。代码仓库本身仍不含题库数据（`bank/` 在 `.gitignore` 里），只有安装包附带。

### 两个文件选一个

| 文件 | 说明 |
|---|---|
| `JY-Relay-Setup-{ver}.exe` | 安装版（推荐）：带题库、开始菜单/桌面快捷方式、卸载程序 |
| `JY-Relay.exe` | 单文件绿色版：双击即用，**不含题库**，需自己导入 |

### 其他

- CSV 题库解析抽成独立函数，`/api/bank/import` 与控制台导入共用同一套规则，不会再出现两处行为不一致
- 安装包顺带带上 `README.md` 与 `DISCLAIMER.md`，装完能直接查

> ⚠️ 仅供技术学习与研究，禁止考试作弊、代考、刷课。模型与题库输出均不保证正确，详见 [DISCLAIMER.md](https://github.com/{REPO}/blob/main/DISCLAIMER.md)。
"""


def main() -> None:
    ver = sys.argv[1] if len(sys.argv) > 1 else open(os.path.join(ROOT, "VERSION")).read().strip()
    tag = f"v{ver}"
    tk = token()
    h = {"Authorization": f"Bearer {tk}", "Accept": "application/vnd.github+json",
         "X-GitHub-Api-Version": "2022-11-28"}
    s = requests.Session()
    # 直连被干扰时可用 GH_PROXY=http://127.0.0.1:59344 走本地代理
    px = os.environ.get("GH_PROXY") or ""
    if px:
        s.proxies = {"http": px, "https": px}
    else:
        s.trust_env = False
    s.headers.update(h)

    r = s.get(f"{API}/repos/{REPO}/releases/tags/{tag}", timeout=30)
    if r.status_code == 200:
        rel = r.json()
        print(f"Release {tag} 已存在：{rel['html_url']}")
    else:
        r = s.post(f"{API}/repos/{REPO}/releases", timeout=30,
                   json={"tag_name": tag, "name": f"v{ver}",
                         "body": body_for(ver), "draft": False,
                         "prerelease": False})
        if r.status_code not in (200, 201):
            raise SystemExit(f"创建 Release 失败 {r.status_code}: {r.text[:300]}")
        rel = r.json()
        print(f"Release 已创建：{rel['html_url']}")

    existing = {a["name"]: a["id"] for a in rel.get("assets", [])}
    upload = rel["upload_url"].split("{")[0]
    for fn in (f"JY-Relay-Setup-{ver}.exe", "JY-Relay.exe"):
        fp = os.path.join(ROOT, "dist", fn)
        if not os.path.exists(fp):
            print(f"跳过（不存在）：{fn}")
            continue
        if fn in existing:
            s.delete(f"{API}/repos/{REPO}/releases/assets/{existing[fn]}", timeout=30)
            print(f"已删除旧资产：{fn}")
        size = os.path.getsize(fp)
        print(f"上传 {fn}（{size/1048576:.1f} MB）…")
        with open(fp, "rb") as f:
            up = s.post(f"{upload}?name={requests.utils.quote(fn)}",
                        data=f, timeout=600,
                        headers={"Content-Type": "application/octet-stream"})
        if up.status_code not in (200, 201):
            raise SystemExit(f"上传失败 {up.status_code}: {up.text[:300]}")
        print(f"  ok  state={up.json().get('state')}  {up.json().get('browser_download_url')}")

    print("完成：", rel["html_url"])


if __name__ == "__main__":
    main()
