$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$uvCommand = Get-Command uv -ErrorAction Stop
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    & $uvCommand.Source venv --python 3.11 .venv
}

& $uvCommand.Source pip install --python $python -r requirements-desktop.txt -r requirements-build.txt
& $python -m PyInstaller --noconfirm --clean GameScript.spec

$app = Join-Path $PSScriptRoot "dist\GameScript\GameScript.exe"
if (-not (Test-Path -LiteralPath $app)) {
    throw "构建完成，但没有生成 $app"
}

Write-Host "已生成：$app"
