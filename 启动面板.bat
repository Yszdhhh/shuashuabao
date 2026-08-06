@echo off
chcp 65001 >nul
cd /d "%~dp0"

:: 自动触发 UAC 管理员权限弹窗 (若未提权)
net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

:: 已具备管理员权限，使用绝对路径静默启动 GUI
set "PY=C:\Users\10639\AppData\Local\hermes\hermes-agent\venv\Scripts\pythonw.exe"
if exist "%PY%" (
    start "" "%PY%" desktop_app.py
    exit /b
)

set "PY2=C:\Users\10639\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe"
if exist "%PY2%" (
    start "" "%PY2%" desktop_app.py
    exit /b
)

where pythonw >nul 2>&1
if %errorlevel%==0 (
    start "" pythonw desktop_app.py
    exit /b
)

where python >nul 2>&1
if %errorlevel%==0 (
    start "" python desktop_app.py
    exit /b
)

echo [错误] 未找到 Python 环境！
pause
