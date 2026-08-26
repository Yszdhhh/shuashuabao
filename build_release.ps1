# 刷刷宝打包脚本：构建 exe → 部署到桌面 → 建/更新桌面快捷方式。
#
# 版本命名：用户可见为「刷刷宝 V0.1」；文件夹用 ASCII「ShuaBao-V0.1」。
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

# Node 只用于构建期；先锁定依赖并重新生成 Web 静态产物，避免把陈旧 dist 打进包。
$npm = Get-Command npm -ErrorAction Stop
Push-Location -LiteralPath (Join-Path $PSScriptRoot "ui-v2")
try {
    & $npm.Source ci
    if ($LASTEXITCODE -ne 0) { throw "ui-v2 npm ci 失败。" }
    & $npm.Source run build
    if ($LASTEXITCODE -ne 0) { throw "ui-v2 npm run build 失败。" }
}
finally {
    Pop-Location
}

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
$versionLabel = "V$version"
$desktop = [Environment]::GetFolderPath("Desktop")
$target  = Join-Path $desktop "$APP_ID-$versionLabel"
$archive = Join-Path $desktop "$APP_NAME-旧版归档"

# 归档桌面上旧版目录（ShuaBao-* / 历史 GameScript-*），只留当前这一份
if (-not (Test-Path -LiteralPath $archive)) {
    New-Item -ItemType Directory -Path $archive | Out-Null
}
Get-ChildItem -LiteralPath $desktop -Directory -ErrorAction SilentlyContinue |
    Where-Object {
        ($_.Name -like "$APP_ID-*" -or $_.Name -like "GameScript-*") -and
        ($_.FullName -ne $target)
    } |
    ForEach-Object {
        $dest = Join-Path $archive $_.Name
        if (Test-Path -LiteralPath $dest) {
            Remove-Item -LiteralPath $dest -Recurse -Force
        }
        Move-Item -LiteralPath $_.FullName -Destination $dest -Force
        Write-Host "已归档：$($_.Name)" -ForegroundColor DarkYellow
    }

if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "dist\$APP_ID") -Destination $target -Recurse

# 桌面快捷方式带版本号：「刷刷宝 V0.1」；清掉无版本的旧快捷方式
$lnkName = "$APP_NAME $versionLabel.lnk"
$lnk = Join-Path $desktop $lnkName
Get-ChildItem -LiteralPath $desktop -Filter "*.lnk" -ErrorAction SilentlyContinue |
    Where-Object {
        $_.Name -eq "$APP_NAME.lnk" -or
        $_.Name -like "$APP_NAME V*.lnk" -or
        $_.Name -like "GameScript*.lnk"
    } |
    Where-Object { $_.Name -ne $lnkName } |
    ForEach-Object {
        $dest = Join-Path $archive $_.Name
        Move-Item -LiteralPath $_.FullName -Destination $dest -Force
        Write-Host "已归档快捷方式：$($_.Name)" -ForegroundColor DarkYellow
    }

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($lnk)
$shortcut.TargetPath = Join-Path $target "$APP_ID.exe"
$shortcut.WorkingDirectory = $target
$shortcut.Description = "$APP_NAME $versionLabel · 重生魔兽刷刷刷单人挂机助手"
$shortcut.Save()

Write-Host "已部署：$target" -ForegroundColor Green
Write-Host "快捷方式：$lnk" -ForegroundColor Green
Write-Host "提示：需要真实点击时请右键快捷方式以管理员身份运行。" -ForegroundColor Yellow
