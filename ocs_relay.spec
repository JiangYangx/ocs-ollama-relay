# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置：OCS 中转服务（绿色单文件 exe）
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
        'tkinter', 'unittest', 'pydoc_data', 'xmlrpc', 'sqlite3',
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
    name='OCS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                 # UPX 压缩会显著增加杀软误报率（#9），宁可大一点
    upx_exclude=[],
    runtime_tmpdir=None,       # 单文件模式
    console=True,              # 保留黑窗口：用户能看到日志、Ctrl+C 可退出
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
