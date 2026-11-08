@echo off
rem 一键出安装包：窗口版 exe + Inno Setup 打包
rem 前置：已 pip install pyinstaller（pystray pillow 可选）；已安装 Inno Setup 6
chcp 65001 >nul
cd /d "%~dp0.."

echo [1/2] 构建窗口版 exe ...
python tools/build_app.py || goto :err

echo [2/2] 生成安装包 ...
rem 安全：dist\config.json 可能被本机运行中的程序写入真实 api_key，
rem 打包前一律用仓库里的干净模板覆盖，避免把密钥发给别人。
echo       重置 dist\config.json 为默认模板 ...
copy /y config.json dist\config.json >nul
rem 版本号唯一来源：仓库根目录 VERSION（保证 exe/安装包/tag 三处一致）
set /p VER=<VERSION
if "%VER%"=="" (
  echo [ERROR] 读不到 VERSION 文件
  exit /b 1
)
echo       版本号：%VER%
rem Inno Setup 可能装在 系统级(Program Files) 或 仅当前用户(LocalAppData)
set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist %ISCC% (
  echo [WARN] 没找到 Inno Setup 6，请从 https://jrsoftware.org/isdl.php 安装后重试
  echo        本次的窗口版 exe 已在 dist\JY-Relay.exe，可直接分发
  exit /b 0
)
%ISCC% /DMyAppVersion=%VER% installer.iss || goto :err

echo.
echo [OK] 安装包已生成：dist\JY-Relay-Setup-*.exe
exit /b 0

:err
echo [ERROR] 构建失败，请查看上方日志
exit /b 1
