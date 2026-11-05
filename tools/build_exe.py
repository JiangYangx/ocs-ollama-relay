#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打包成单文件 exe（自动把 console.html 内嵌进去）。

用法：
    python tools/build_exe.py

做的事：
    1. 读 console.html，base64 编码
    2. 复制 ocs_relay.py 到 build/_gen/，把其中的 _CONSOLE_B64 = "" 填上数据
    3. 对生成的文件跑 PyInstaller --onefile
    4. 把 config.json 复制到 dist/

这样源码里的 ocs_relay.py 始终是干净的（没有几百行 base64 垃圾），
只有构建产物才内嵌页面。
"""
from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEN_DIR = os.path.join(ROOT, "build", "_gen")
PLACEHOLDER = '_CONSOLE_B64 = ""'
WRAP = 120


def fail(msg: str) -> None:
    print(f"[ERROR] {msg}")
    sys.exit(1)


def main() -> None:
    src_py = os.path.join(ROOT, "ocs_relay.py")
    src_html = os.path.join(ROOT, "console.html")
    for p in (src_py, src_html):
        if not os.path.exists(p):
            fail(f"找不到 {p}")

    os.makedirs(GEN_DIR, exist_ok=True)

    raw = open(src_html, "rb").read()
    b64 = base64.b64encode(raw).decode("ascii")
    lines = "\n".join(b64[i:i + WRAP] for i in range(0, len(b64), WRAP))
    injected = '_CONSOLE_B64 = """\n' + lines + '\n"""'

    code = open(src_py, "r", encoding="utf-8").read()
    if PLACEHOLDER not in code:
        fail(f"ocs_relay.py 里找不到占位符 {PLACEHOLDER!r}，请检查文件是否被改动")
    code = code.replace(PLACEHOLDER, injected, 1)

    gen_py = os.path.join(GEN_DIR, "ocs_relay.py")
    with open(gen_py, "w", encoding="utf-8") as f:
        f.write(code)

    print(f"[1/3] 已内嵌 console.html（{len(raw)} 字节），生成 build/_gen/ocs_relay.py")

    spec = os.path.join(ROOT, "ocs_relay.spec")
    if not os.path.exists(spec):
        fail("找不到 ocs_relay.spec")

    print("[2/3] 开始 PyInstaller 打包（约 1~3 分钟）...")
    cmd = [sys.executable, "-m", "PyInstaller", spec, "--noconfirm", "--clean",
           "--distpath", os.path.join(ROOT, "dist"),
           "--workpath", os.path.join(ROOT, "build", "pyi")]
    rc = subprocess.call(cmd, cwd=ROOT)
    if rc != 0:
        fail("PyInstaller 打包失败，请查看上方日志")

    print("[3/3] 复制配置文件到 dist/ ...")
    cfg = os.path.join(ROOT, "config.json")
    if os.path.exists(cfg):
        shutil.copy2(cfg, os.path.join(ROOT, "dist", "config.json"))

    exe_name = "JY-Relay.exe" if os.name == "nt" else "JY-Relay"
    out = os.path.join(ROOT, "dist", exe_name)
    if os.path.exists(out):
        size = os.path.getsize(out) / 1024 / 1024
        print(f"\n[OK] 打包完成：{out}（{size:.1f} MB）")
    else:
        fail("打包结束但没找到产物，请检查 dist 目录")


if __name__ == "__main__":
    main()
