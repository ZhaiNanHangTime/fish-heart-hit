@echo off
chcp 936 >nul
cd /d "%~dp0"

echo.
echo   ==========================================
echo      咸鱼突刺 · 心率控制台
echo   ==========================================
echo.
echo   正在打开图形界面...
echo.

start "" pythonw "%~dp0heartrate_gui.py"

if errorlevel 1 (
  echo   [错误] 启动失败，请确认已安装 Python
  pause
)
