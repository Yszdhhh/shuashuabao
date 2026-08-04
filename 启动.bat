@echo off
chcp 65001 >nul
cd /d "%~dp0"

:: 检查 pythonw 是否可用（无终端窗口启动）
where pythonw >nul 2>&1
if %errorlevel%==0 (
    start "" pythonw desktop_app.py
    exit /b
)

:: 回退到 python（会带终端窗口）
where python >nul 2>&1
if %errorlevel%==0 (
    start "" python desktop_app.py
    exit /b
)

:: 都找不到
echo [错误] 未找到 Python，请先安装 Python 3.10+
pause
