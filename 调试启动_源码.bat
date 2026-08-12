@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 刷刷宝 - 源码调试启动

:: 开发用：直接跑 desktop_app.py 源码，能立刻看到未打包的改动。
:: 日常使用请用桌面「刷刷宝」快捷方式（打包版）。

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo 需要管理员权限才能真实点击游戏，正在提权...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

:: 优先用项目自带 venv，其次系统 Python；不再硬编码个人机器路径
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" desktop_app.py
    exit /b
)

where pythonw >nul 2>&1
if %errorlevel%==0 (
    start "" pythonw desktop_app.py
    exit /b
)

where python >nul 2>&1
if %errorlevel%==0 (
    python desktop_app.py
    exit /b
)

echo [错误] 没找到 Python。请先安装 Python 3.11，或运行 build_release.ps1 创建 .venv。
pause
