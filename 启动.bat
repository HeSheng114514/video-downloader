@echo off
chcp 65001 >nul 2>nul
cd /d "%~dp0"
title Video Downloader

set "PY="
where pythonw >nul 2>nul && set "PY=pythonw"
where python  >nul 2>nul && if not defined PY set "PY=python"

if not defined PY (
    echo.
    echo   [ERROR] Python not found.
    echo   Please install Python 3.9+ from https://www.python.org/downloads/
    echo   Remember to check "Add python.exe to PATH" during installation.
    echo.
    pause
    exit /b 1
)

start "" %PY% "%~dp0run.py" %*
exit /b 0
