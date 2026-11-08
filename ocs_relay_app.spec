# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置：JY 答题助手 · 窗口版（无黑框 + 托盘）
#
# 不要直接用 pyinstaller 跑这个文件，请执行：
#     python tools/build_app.py
# 它会先把 console.html 注入 build/_gen/，再调用本配置。
#
# 与 ocs_relay.spec 的区别：
#   console=False          不弹黑框，像正常软件
#   入口是 tray_app.py     服务跑在后台线程，托盘提供「打开控制台 / 退出」
#   需要 pystray + Pillow（没装则退化为无托盘常驻）

import os

ROOT = os.path.abspath(os.path.dirname(SPEC))
ENTRY = os.path.join(ROOT, 'build', '_gen', 'tray_app.py')
ICON = os.path.join(ROOT, 'assets', 'jy.ico')
if not os.path.exists(ENTRY):
    raise SystemExit(
        '[ERROR] 找不到 build/_gen/tray_app.py\n'
        '        请改用：python tools/build_app.py'
    )

a = Analysis(
    [ENTRY],
    pathex=[ROOT],
    binaries=[],
    datas=[(os.path.join(ROOT, 'assets', 'jy.png'), 'assets')] if os.path.exists(
        os.path.join(ROOT, 'assets', 'jy.png')) else [],
    hiddenimports=[
        'flask', 'requests', 'werkzeug', 'jinja2', 'click',
        'logging.handlers', 'sqlite3',
        # 托盘（可选，缺失时代码自行降级）
        'pystray', 'pystray._win32', 'PIL', 'PIL._tkinter_finder',
    ],
    excludes=[
        'tkinter', 'unittest', 'pydoc_data', 'xmlrpc',
        'multiprocessing', 'concurrent.futures',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='JY-Relay',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,             # 窗口版：无黑框
    icon=ICON if os.path.exists(ICON) else None,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
