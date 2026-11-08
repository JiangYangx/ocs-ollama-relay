#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JY 答题助手 · 托盘入口（v1.5，可选）

装了 pystray + Pillow 时：系统托盘图标 + 右键菜单（打开控制台 / 退出）。
没装也能跑：服务照常启动，只是没有托盘图标，用任务管理器结束进程即可。

    pip install pystray pillow
    python tray_app.py

打包后的「窗口版」exe（ocs_relay_app.spec）默认用本文件作为入口。
"""
from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)   # ocs_relay 的配置写在这里
    ASSET_DIR = getattr(sys, "_MEIPASS", BASE_DIR)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    ASSET_DIR = BASE_DIR
sys.path.insert(0, BASE_DIR)

# v2.0：保留用户传入的参数（--port / --model 等），只强制补 --no-browser。
# 旧写法 sys.argv = [argv0, "--no-browser"] 会把 --port 整个吞掉，
# 导致「exe --port 5098」仍然监听配置里的 5000。
_argv = list(sys.argv)
if "--no-browser" not in _argv:
    _argv.append("--no-browser")
sys.argv = _argv

PORT = 5000


def _argv_port() -> int:
    """命令行 --port 优先于配置文件里的端口。"""
    try:
        return int(sys.argv[sys.argv.index("--port") + 1])
    except (ValueError, IndexError):
        return 0


def _server_up(port: int) -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1.5):
            return True
    except Exception:
        return False


def _open_console(*_):
    webbrowser.open(f"http://127.0.0.1:{PORT}/")


def _quit(icon=None, item=None):
    os._exit(0)


def main() -> None:
    global PORT
    import ocs_relay  # noqa: E402  导入即完成配置加载（app.run 只在 __main__ 才执行）
    PORT = _argv_port() or int(ocs_relay.CFG.get("port", 5000))

    threading.Thread(target=ocs_relay.main, daemon=True).start()

    for _ in range(40):          # 最多等 20 秒服务起来
        if _server_up(PORT):
            break
        time.sleep(0.5)

    ico_path = os.path.join(ASSET_DIR, "assets", "jy.png")
    try:
        import pystray
        from PIL import Image
        image = Image.open(ico_path) if os.path.exists(ico_path) \
            else Image.new("RGB", (64, 64), "#4c8dff")
        menu = pystray.Menu(
            pystray.MenuItem("打开控制台", _open_console, default=True),
            pystray.MenuItem("退出", _quit),
        )
        icon = pystray.Icon("JY-Relay", image,
                            f"JY 答题助手 v{ocs_relay.APP_VERSION}", menu)
        if ocs_relay.CFG.get("auto_open_browser", True):
            _open_console()
        icon.run()
    except ImportError:
        print("[JY] 未安装 pystray（pip install pystray pillow），无托盘图标，服务继续运行。")
        print(f"[JY] 控制台：http://127.0.0.1:{PORT}/   关闭服务请结束本进程。")
        if ocs_relay.CFG.get("auto_open_browser", True):
            _open_console()
        while True:
            time.sleep(3600)


if __name__ == "__main__":
    main()
