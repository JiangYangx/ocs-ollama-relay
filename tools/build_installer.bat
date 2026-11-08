@echo off
rem 一键出安装包：窗口版 exe + Inno Setup 打包
rem 前置：已 pip install pyinstaller（pystray pillow 可选）；已安装 Inno Setup 6
chcp 65001 >nul
cd /d "%~dp0.."

echo [1/2] 构建窗口版 exe ...
python tools/build_app.py || goto :err

echo [2/2] 生成安装包 ...
set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% (
  echo [WARN] 没找到 Inno Setup 6，请从 https://jrsoftware.org/isdl.php 安装后重试
  echo        本次的窗口版 exe 已在 dist\JY-Relay.exe，可直接分发
  exit /b 0
)
%ISCC% installer.iss || goto :err

echo.
echo [OK] 安装包已生成：dist\JY-Relay-Setup-1.5.0.exe
exit /b 0

:err
echo [ERROR] 构建失败，请查看上方日志
exit /b 1
