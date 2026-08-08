@echo off
setlocal
set "APP=%~dp0dist\GameScript\GameScript.exe"
if not exist "%APP%" set "APP=%~dp0dist-candidate\GameScript\GameScript.exe"
if not exist "%APP%" set "APP=%~dp0dist-candidate3\GameScript\GameScript.exe"
if not exist "%APP%" set "APP=%~dp0dist-candidate2\GameScript\GameScript.exe"

if exist "%APP%" (
    start "" "%APP%"
    exit /b 0
)

powershell.exe -NoProfile -WindowStyle Hidden -Command ^
  "Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show('GameScript.exe not found. Run build_release.ps1 first.','GameScript') | Out-Null"
exit /b 1
