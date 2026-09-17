@echo off
rem Double-click entry only: PowerShell files open in an editor when double-clicked.
rem All logic stays in tools\one_click_test.ps1; this file only forwards and pauses.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\one_click_test.ps1" %*
set "ONECLICK_EXIT=%ERRORLEVEL%"
echo.
echo exit code: %ONECLICK_EXIT%
pause
exit /b %ONECLICK_EXIT%
