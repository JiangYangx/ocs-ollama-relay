# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置：JY Relay 中转服务（绿色单文件 exe）
#
# 不要直接用 pyinstaller 跑这个文件，请执行：
#     python tools/build_exe.py
# 它会先把 console.html 注入到 build/_gen/ocs_relay.py，再调用本配置。
#
# 说明：控制台页面在构建时被内嵌进 Python 源码，所以这里不需要 --add-data，
#       产出的 exe 是真正自包含的单文件。

import os

ROOT = os.path.abspath(os.path.dirname(SPEC))
ENTRY = os.path.join(ROOT, 'build', '_gen', 'ocs_relay.py')
if not os.path.exists(ENTRY):
    raise SystemExit(
        '[ERROR] 找不到 build/_gen/ocs_relay.py\n'
        '        请改用：python tools/build_exe.py'
    )

a = Analysis(
    [ENTRY],
    pathex=[ROOT],
    binaries=[],
    datas=[],                     # 无外部数据文件，控制台已内嵌进源码
    hiddenimports=[
        'flask',
        'requests',
        'werkzeug',
        'jinja2',
        'click',
        'logging.handlers',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 排除无关大模块，显著减小体积
        # 注意：sqlite3 绝不能排除——jy_store 依赖它（v1.3+ 核心存储）
        'tkinter', 'unittest', 'pydoc_data', 'xmlrpc',
        'multiprocessing', 'concurrent.futures',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

ICON = os.path.join(ROOT, 'assets', 'jy.ico')

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
    upx=False,                 # UPX 压缩会显著增加杀软误报率（#9），宁可大一点
    upx_exclude=[],
    runtime_tmpdir=None,       # 单文件模式
    console=True,              # 控制台版保留黑窗口：能看日志、Ctrl+C 可退出
    icon=ICON if os.path.exists(ICON) else None,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
