@echo off
chcp 936 >nul
title 停止心率服务
cd /d "%~dp0"

echo ============================================================
echo   停止心率服务与桌面悬浮窗
echo ============================================================
echo.
python "%~dp0stop_heartrate.py"
echo.
timeout /t 4 /nobreak >nul
