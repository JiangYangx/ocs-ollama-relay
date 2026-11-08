#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打包「窗口版」exe（无黑框 + 托盘，配合 installer.iss 出安装包）。

用法：
    pip install pystray pillow        # 可选：不装则无托盘
    python tools/build_app.py

流程与 build_exe.py 相同：注入 console.html → PyInstaller（ocs_relay_app.spec）。
产物：dist/JY-Relay.exe（窗口版）+ dist/config.json
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
    src_py = os.path.join(ROOT, "tray_app.py")
    dep_py = os.path.join(ROOT, "ocs_relay.py")
    src_html = os.path.join(ROOT, "console.html")
    for p in (src_py, dep_py, src_html):
        if not os.path.exists(p):
            fail(f"找不到 {p}")

    os.makedirs(GEN_DIR, exist_ok=True)

    raw = open(src_html, "rb").read()
    b64 = base64.b64encode(raw).decode("ascii")
    lines = "\n".join(b64[i:i + WRAP] for i in range(0, len(b64), WRAP))
    injected = '_CONSOLE_B64 = """\n' + lines + '\n"""'

    code = open(src_py, "r", encoding="utf-8").read()
    if PLACEHOLDER not in code:
        # tray_app 本身没有占位符，占位符在 ocs_relay.py 里——两者都要进 build/_gen
        pass

    # tray_app 与 ocs_relay 都放进 _gen，import ocs_relay 才能命中内嵌版
    for name, extra in (("tray_app.py", code), ("ocs_relay.py", None)):
        text = extra if extra is not None else open(
            os.path.join(ROOT, name), "r", encoding="utf-8").read()
        if PLACEHOLDER in text:
            text = text.replace(PLACEHOLDER, injected, 1)
        with open(os.path.join(GEN_DIR, name), "w", encoding="utf-8") as f:
            f.write(text)

    print(f"[1/3] 已内嵌 console.html（{len(raw)} 字节）到 build/_gen/")

    spec = os.path.join(ROOT, "ocs_relay_app.spec")
    if not os.path.exists(spec):
        fail("找不到 ocs_relay_app.spec")

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
        print(f"\n[OK] 窗口版打包完成：{out}（{size:.1f} MB）")
        print("     下一步：运行 tools/build_installer.bat 生成安装包")
    else:
        fail("打包结束但没找到产物，请检查 dist 目录")


if __name__ == "__main__":
    main()
