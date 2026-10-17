@echo off
chcp 936 >nul
cd /d "%~dp0"
"%SystemRoot%\System32\wscript.exe" "%~dp0一键打开咸鱼总控.vbs" --stop
