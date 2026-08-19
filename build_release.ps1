# 刷刷宝打包脚本：构建 OCR sidecar + 主 EXE → 部署到桌面 → 更新快捷方式。
#
# 版本命名：用户可见为「刷刷宝 V0.1」；文件夹用 ASCII「ShuaBao-V0.1」。
# 打包前强制过发版门禁。要跳过请显式加 -SkipGate，并自行承担风险。
param(
    [switch]$SkipGate,
    [switch]$NoDeploy
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$APP_NAME = "刷刷宝"
$APP_ID   = "ShuaBao"
$OCR_ID   = "ShuaBaoOCR"

$uvCommand = Get-Command uv -ErrorAction Stop
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$ocrPython = Join-Path $PSScriptRoot ".venv-ocr\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    & $uvCommand.Source venv --python 3.11 .venv
}

& $uvCommand.Source pip install --python $python -r requirements-desktop.txt -r requirements-build.txt

# OCR runtime is a first-class release dependency.  Build/release never falls
# back to a historical checkout or an unrelated Python installation.
& (Join-Path $PSScriptRoot "tools\bootstrap_shuabao_ocr.ps1")
if (-not (Test-Path -LiteralPath $ocrPython)) {
    throw "ShuaBao OCR runtime missing after bootstrap: $ocrPython"
}
& $ocrPython -m pip install -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw "failed to install OCR build requirements" }

if (-not $SkipGate) {
    Write-Host "[1/4] 发版门禁 ..." -ForegroundColor Cyan
    $gatePython = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $gatePython) {
        throw "PATH 上没有 python，无法跑门禁。装好开发环境，或明确知道后果时用 -SkipGate。"
    }
    & $gatePython tools\release_gate.py
    if ($LASTEXITCODE -ne 0) {
        throw "门禁未通过，已中止打包。"
    }
}

Write-Host "[2/4] 打包静默 OCR sidecar ..." -ForegroundColor Cyan
& $ocrPython -m PyInstaller --noconfirm --clean "$OCR_ID.spec"
if ($LASTEXITCODE -ne 0) { throw "ShuaBaoOCR 打包失败" }
$ocrDist = Join-Path $PSScriptRoot "dist\$OCR_ID"
$ocrExe = Join-Path $ocrDist "$OCR_ID.exe"
if (-not (Test-Path -LiteralPath $ocrExe)) {
    throw "OCR 构建结束但没有生成 $ocrExe"
}

Write-Host "[3/4] 打包 ShuaBao 主程序 ..." -ForegroundColor Cyan
& $python -m PyInstaller --noconfirm --clean "$APP_ID.spec"
if ($LASTEXITCODE -ne 0) { throw "ShuaBao 主程序打包失败" }

$appDir = Join-Path $PSScriptRoot "dist\$APP_ID"
$app = Join-Path $appDir "$APP_ID.exe"
if (-not (Test-Path -LiteralPath $app)) {
    throw "构建结束但没有生成 $app"
}

# Assemble one deployable directory.  The OCR onedir payload is copied under
# vision/ so its _internal DLL/package tree remains adjacent to ShuaBaoOCR.exe.
$visionTarget = Join-Path $appDir "vision"
if (Test-Path -LiteralPath $visionTarget) {
    Remove-Item -LiteralPath $visionTarget -Recurse -Force
}
New-Item -ItemType Directory -Path $visionTarget | Out-Null
Copy-Item -LiteralPath (Join-Path $ocrDist "*") -Destination $visionTarget -Recurse -Force

$modelSource = Join-Path $PSScriptRoot "models\ocr"
$modelTarget = Join-Path $appDir "models\ocr"
if (-not (Test-Path -LiteralPath (Join-Path $modelSource "PP-OCRv5_mobile_rec_infer"))) {
    throw "OCR 模型缺失，无法生成自包含发行包: $modelSource"
}
if (Test-Path -LiteralPath $modelTarget) {
    Remove-Item -LiteralPath $modelTarget -Recurse -Force
}
New-Item -ItemType Directory -Path $modelTarget -Force | Out-Null
Copy-Item -Path (Join-Path $modelSource "*") -Destination $modelTarget -Recurse -Force

Write-Host "已生成：$app" -ForegroundColor Green
Write-Host "OCR sidecar：$(Join-Path $visionTarget "$OCR_ID.exe")" -ForegroundColor Green

if ($NoDeploy) { return }

Write-Host "[4/4] 部署到桌面并更新快捷方式 ..." -ForegroundColor Cyan
$version = (& $python -c "import sys; sys.path.insert(0,'src'); import shuabao; print(shuabao.__version__)").Trim()
$versionLabel = "V$version"
$desktop = [Environment]::GetFolderPath("Desktop")
$target  = Join-Path $desktop "$APP_ID-$versionLabel"
$archive = Join-Path $desktop "$APP_NAME-旧版归档"

if (-not (Test-Path -LiteralPath $archive)) {
    New-Item -ItemType Directory -Path $archive | Out-Null
}
Get-ChildItem -LiteralPath $desktop -Directory -ErrorAction SilentlyContinue |
    Where-Object {
        ($_.Name -like "$APP_ID-*") -and ($_.FullName -ne $target)
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
Copy-Item -LiteralPath $appDir -Destination $target -Recurse

$lnkName = "$APP_NAME $versionLabel.lnk"
$lnk = Join-Path $desktop $lnkName
Get-ChildItem -LiteralPath $desktop -Filter "*.lnk" -ErrorAction SilentlyContinue |
    Where-Object {
        $_.Name -eq "$APP_NAME.lnk" -or $_.Name -like "$APP_NAME V*.lnk"
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
