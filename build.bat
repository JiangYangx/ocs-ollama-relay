@echo off
chcp 65001 >nul
title Build OCS Relay EXE (single file)
cd /d "%~dp0"

echo.
echo ============================================
echo   Building OCS-Relay single-file EXE
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found in PATH.
    echo         Install Python 3.8+ from https://www.python.org/downloads/
    echo         Remember to check "Add Python to PATH" during install.
    pause
    exit /b 1
)

echo [1/2] Installing dependencies...
python -m pip install --upgrade pip -q
python -m pip install flask requests pyinstaller -q
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies. Check your network.
    pause
    exit /b 1
)

echo [2/2] Building EXE (this may take 1-3 minutes)...
rem 用 tools\build_exe.py 而不是直接跑 spec，
rem 它会先把 console.html 内嵌进源码副本，再调用 PyInstaller。
python tools\build_exe.py
if errorlevel 1 (
    echo [ERROR] Build failed. See the messages above.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   Done!
echo   Output: dist\OCS.exe
echo   Copy dist folder anywhere and run the EXE.
echo ============================================
echo.
pause
