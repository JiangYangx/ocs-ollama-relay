@echo off
rem Build script for JY Relay (single-file exe). Pure ASCII only.
rem DO NOT add non-ASCII characters to this file (cmd parses it as GBK).
title Build JY Relay EXE (single file)
cd /d "%~dp0"

echo.
echo ============================================
echo   Building JY-Relay single-file EXE
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
rem tools\build_exe.py embeds console.html into a source copy first,
rem then calls PyInstaller with ocs_relay.spec.
python tools\build_exe.py
if errorlevel 1 (
    echo [ERROR] Build failed. See the messages above.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   Done!
echo   Output: dist\JY-Relay.exe
echo   Copy dist folder anywhere and run the EXE.
echo ============================================
echo.
pause
