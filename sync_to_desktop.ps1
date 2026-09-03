# 打包当前工作分支并部署到桌面（ShuaBao-Vx.y + 快捷方式）。
# 用法（在仓库根目录，Windows PowerShell）：
#   powershell -ExecutionPolicy Bypass -File .\sync_to_desktop.ps1 -SkipGate
# 需要本机已装 uv / Python。为避免部署时悄悄切走正在验收的版本，
# 此脚本绝不 fetch/checkout；需要更新分支时请由操作者先明确完成 git 操作。

param(
    [switch]$SkipGate
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$branch = (git branch --show-current).Trim()
if (-not $branch) {
    throw "当前不在命名分支上；请先切换到要发布的分支。"
}
$trackedChanges = @(& git status --porcelain --untracked-files=no)
if ($trackedChanges.Count -gt 0) {
    throw "工作区有已跟踪的未提交修改；请先提交或暂存，避免发布不可复现版本。"
}
$untrackedEntries = @(& git status --porcelain --untracked-files=all | Where-Object { $_.StartsWith("?? ") })
if ($untrackedEntries.Count -gt 0) {
    Write-Host "[sync] 保留 $($untrackedEntries.Count) 个用户未跟踪文件；仅为本地构建传入 -AllowDirty。" -ForegroundColor Yellow
}
Write-Host "[sync] build current branch $branch ..." -ForegroundColor Cyan

$gate = @()
if ($SkipGate) { $gate = @("-SkipGate") }
$dirty = @()
if ($untrackedEntries.Count -gt 0) { $dirty = @("-AllowDirty") }

Write-Host "[sync] build_release → Desktop ..." -ForegroundColor Cyan
& powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "build_release.ps1") @gate @dirty
if ($LASTEXITCODE -ne 0) { throw "build_release failed" }

Write-Host "[sync] 完成：桌面「刷刷宝.lnk」已指向 Desktop\ShuaBao\ShuaBao.exe；构建身份与发行清单已由 build_release 回验。" -ForegroundColor Green
