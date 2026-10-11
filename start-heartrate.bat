@echo off
chcp 936 >nul
title 咸鱼突刺 · 心率直播服务
cd /d "%~dp0"

echo ============================================================
echo   咸鱼突刺 · 心率直播
echo ============================================================
echo.
echo [1/2] 启动心率读取服务 (端口 8080) ...
start "hr-service" /min python "%~dp0heartrate_live.py" --port 8080
timeout /t 4 /nobreak >nul

echo [2/2] 启动桌面悬浮窗 ...
start "" pythonw "%~dp0heartrate_hud.py"
timeout /t 2 /nobreak >nul

echo.
echo ============================================================
echo   启动完成
echo.
echo   OBS 浏览器源:  http://127.0.0.1:8080/
echo   大字简洁版:    http://127.0.0.1:8080/plain
echo   数据接口:      http://127.0.0.1:8080/hr
echo.
echo   悬浮窗操作: 左键拖动 / 右键菜单 / 双击换大小
echo   关闭服务:   运行 stop-heartrate.bat
echo ============================================================
echo.
timeout /t 6 /nobreak >nul
