# 拉取当前学习模式分支并打包部署到桌面（ShuaBao-Vx.y + 快捷方式）。
# 用法（在仓库根目录，Windows PowerShell）：
#   powershell -ExecutionPolicy Bypass -File .\同步到桌面.ps1
# 需要本机已装 uv / Python；门禁可加 -SkipGate 跳过。

param(
    [switch]$SkipGate,
    [string]$Branch = "cursor/learning-mode-replace-dry-run-bb96"
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

Write-Host "[sync] fetch + checkout $Branch ..." -ForegroundColor Cyan
git fetch origin $Branch
git checkout $Branch
git pull --ff-only origin $Branch

$gate = @()
if ($SkipGate) { $gate = @("-SkipGate") }

Write-Host "[sync] build_release → Desktop ..." -ForegroundColor Cyan
& powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "build_release.ps1") @gate
if ($LASTEXITCODE -ne 0) { throw "build_release failed" }

Write-Host "[sync] 完成后请看桌面「刷刷宝 V0.3」快捷方式；标题栏应是 V0.3，运行区有「学习模式」。" -ForegroundColor Green
