@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY=python"
where python >nul 2>&1 || set "PY=py -3"
%PY% main.py sync-settings
echo.
pause
