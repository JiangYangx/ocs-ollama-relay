@echo off
chcp 65001 >nul
title OCS Relay
cd /d "%~dp0"

echo.
echo ============================================
echo   OCS Web-Course Helper - Local Relay
echo ============================================
echo.

rem --- 1. Prefer the packaged EXE ---
if exist "OCS.exe" (
    echo [1/3] Found OCS.exe, starting...
    start "" "OCS.exe"
    goto :done
)

rem --- 2. Fall back to Python ---
echo [1/3] No EXE found, trying Python...
where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo [ERROR] Neither OCS.exe nor Python was found.
    echo.
    echo   Option A: build the EXE first  -^> run build.bat
    echo   Option B: install Python 3.8+  -^> https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

echo [2/3] Checking dependencies...
python -c "import flask, requests" 2>nul
if errorlevel 1 (
    echo       Installing flask and requests...
    python -m pip install flask requests -q
    if errorlevel 1 (
        echo [ERROR] Dependency install failed. Check your network.
        pause
        exit /b 1
    )
)

echo [3/3] Starting relay...
echo.
python ocs_relay.py

:done
echo.
echo Relay stopped.
pause
