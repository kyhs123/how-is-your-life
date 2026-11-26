@echo off
rem 双击这个文件打开网页界面；关掉这个黑窗口就退出。
chcp 65001 >nul
cd /d "%~dp0"
title 你过得怎么样 · 人生记录

if not exist ".venv\Scripts\life.exe" goto noenv

".venv\Scripts\life.exe" server --open
if errorlevel 1 goto failed
exit /b 0

:failed
echo.
echo [-] 上面是出错信息。窗口留着方便你抬头看，按任意键关掉。
pause
exit /b 1

:noenv
echo.
echo [-] 找不到 .venv\Scripts\life.exe —— 这个文件夹还没装好运行环境。
echo     先照 README.md 里「安装」那一段做一遍，再回来双击。
echo.
pause
exit /b 1
