# 刷刷宝打包脚本：构建 exe → 部署到桌面 → 建/更新桌面快捷方式。
#
# 打包前强制过发版门禁（tools/release_gate.py）。要跳过请显式加 -SkipGate，
# 并自己清楚为什么——门禁红着发版正是 8-12 连出两个紧急修复的原因。
param(
    [switch]$SkipGate,
    [switch]$NoDeploy
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$APP_NAME = "刷刷宝"
$APP_ID   = "ShuaBao"

$uvCommand = Get-Command uv -ErrorAction Stop
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    & $uvCommand.Source venv --python 3.11 .venv
}

& $uvCommand.Source pip install --python $python -r requirements-desktop.txt -r requirements-build.txt

if (-not $SkipGate) {
    Write-Host "[1/3] 发版门禁 ..." -ForegroundColor Cyan
    # 用开发环境跑门禁：.venv 只装了打包依赖（PySide6 + PyInstaller），
    # 没有 pytest/opencv，拿它跑会得到"0 passed"这种假失败。
    $gatePython = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $gatePython) {
        throw "PATH 上没有 python，无法跑门禁。装好开发环境，或明确知道后果时用 -SkipGate。"
    }
    & $gatePython tools\release_gate.py
    if ($LASTEXITCODE -ne 0) {
        throw "门禁未通过，已中止打包。修好再来，或明确知道后果时用 -SkipGate。"
    }
}

Write-Host "[2/3] PyInstaller 打包 ..." -ForegroundColor Cyan
& $python -m PyInstaller --noconfirm --clean "$APP_ID.spec"

$app = Join-Path $PSScriptRoot "dist\$APP_ID\$APP_ID.exe"
if (-not (Test-Path -LiteralPath $app)) {
    throw "构建结束但没有生成 $app"
}
Write-Host "已生成：$app" -ForegroundColor Green

if ($NoDeploy) { return }

Write-Host "[3/3] 部署到桌面并更新快捷方式 ..." -ForegroundColor Cyan
$version = (& $python -c "import sys; sys.path.insert(0,'src'); import gamescript; print(gamescript.__version__)").Trim()
$desktop = [Environment]::GetFolderPath("Desktop")
$target  = Join-Path $desktop "$APP_ID-$version"

if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "dist\$APP_ID") -Destination $target -Recurse

# 桌面只保留一个中文快捷方式，始终指向最新版本
$lnk = Join-Path $desktop "$APP_NAME.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($lnk)
$shortcut.TargetPath = Join-Path $target "$APP_ID.exe"
$shortcut.WorkingDirectory = $target
$shortcut.Description = "$APP_NAME · 重生魔兽刷刷刷单人挂机助手 $version"
$shortcut.Save()

Write-Host "已部署：$target" -ForegroundColor Green
Write-Host "快捷方式：$lnk" -ForegroundColor Green
Write-Host "提示：需要真实点击时请右键快捷方式以管理员身份运行。" -ForegroundColor Yellow
