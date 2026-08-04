@echo off
chcp 65001 >nul
title 英雄三国挂机助手 (懒人系列之魔兽世界刷刷刷) · 本地刷图版

cd /d "%~dp0"

echo ==================================================
echo   GameScript-Local 本地刷图助手
echo ==================================================
echo.
echo [1] 启动 PySide6 原生桌面软件 (推荐)
echo [2] 启动 旧 Tkinter 原型
echo [3] 启动 Web 控制面板 (http://localhost:17880)
echo.

set /p choice=请选择启动方式 [默认 1]: 
if "%choice%"=="2" (
    echo 正在启动旧 Tkinter 原型...
    python controller.py
) else if "%choice%"=="3" (
    echo 正在启动 Web 控制面板...
    start "" "http://localhost:17880"
    python api_server.py
) else (
    echo 正在启动原生桌面软件...
    python desktop_app.py
)

pause
