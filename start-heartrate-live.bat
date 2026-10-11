@echo off
chcp 936 >nul
title Heart Rate Live - BLE 心率设备
echo ============================================================
echo  Heart Rate Live  -  reading BLE 心率设备 via BLE
echo.
echo  After it starts, open one of these in OBS browser source:
echo    http://127.0.0.1:8080/        full widget
echo    http://127.0.0.1:8080/plain   big number only
echo.
echo  Keep this window open. Press Ctrl+C to stop.
echo ============================================================
echo.
python "%~dp0heartrate_live.py" --port 8080
echo.
echo Service stopped.
pause
