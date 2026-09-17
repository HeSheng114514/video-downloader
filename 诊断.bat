@echo off
chcp 65001 >nul 2>nul
cd /d "%~dp0"
title Video Downloader - Diagnose
echo ============================================================
echo   Video Downloader - Environment Self Test
echo ============================================================
echo.
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.9+ first.
    pause
    exit /b 1
)
python "%~dp0run.py" --selftest
echo.
pause
