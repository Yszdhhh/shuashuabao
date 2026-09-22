# 源码快速测试入口（薄壳）：在当前 HEAD + 本地改动上直接启动 Web 壳做实机测试。
# 证据等级 SOURCE_QUICK_TEST：≠ GT，≠ 卡密/授权验收。
# 不 pull、不切分支、不 reset；不改授权/permit/签名；UI 重建全部复用 run_desktop_dev.ps1。
param(
    # 仅供离线冒烟：不提权直接启动（无管理员权限时真实点击不可用）。
    [switch]$NoElevate,
    # 内部标记：本进程是提权后重新拉起的实例。
    [switch]$Elevated,
    # 可选解释器；缺省用本仓库 .venv，sibling worktree 没有 .venv 时用主仓库的 .venv。
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"

function Stop-QuickTest([string]$Message) {
    Write-Host "[quick_test] 失败：$Message" -ForegroundColor Red
    if ($Elevated) { Read-Host "按回车关闭窗口" | Out-Null }
    exit 1
}

# 提权方式与 live_scenario_launcher.ps1 相同（真实点击游戏需要管理员）。RunAs 重开后
# 环境变量不会带过去，所以下面所有 env 设置都发生在提权之后的这个进程里。
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin -and -not $NoElevate) {
    Write-Host "需要管理员权限才能真实点击游戏，正在提权..."
    $scriptPath = if ($PSCommandPath) { $PSCommandPath } else { Join-Path $PSScriptRoot "quick_test.ps1" }
    $relaunchArgs = "-NoLogo -NoProfile -ExecutionPolicy Bypass -Sta -File `"$scriptPath`" -Elevated"
    if ($Python) { $relaunchArgs += " -Python `"$Python`"" }
    Start-Process powershell.exe -ArgumentList $relaunchArgs -WorkingDirectory $PSScriptRoot -Verb RunAs
    exit 0
}

# 提权后的控制台是 OEM 代码页（936）；统一 UTF-8，避免中文路径/日志乱码。
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch {}
$env:PYTHONIOENCODING = "utf-8"

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$devScript = Join-Path $repoRoot "run_desktop_dev.ps1"
if (-not (Test-Path -LiteralPath (Join-Path $repoRoot "desktop_app.py") -PathType Leaf) -or
    -not (Test-Path -LiteralPath $devScript -PathType Leaf)) {
    Stop-QuickTest "仓库根定位失败：$repoRoot"
}
Set-Location -LiteralPath $repoRoot

# 清掉可能把源码进程带到卡密/发行授权路径上的变量。本机用户级环境变量永久设置了
# SHUABAO_SUBSCRIPTION_MODE=enforce / _BASE_URL，必须在进程内显式清掉。
$cleared = @(Get-ChildItem Env: | Where-Object {
    $_.Name -like "SHUABAO_SUBSCRIPTION_*" -or
    $_.Name -like "SHUABAO_*LICENSE*" -or
    $_.Name -eq "SHUABAO_CANDIDATE_SHA"
} | ForEach-Object { $_.Name })
foreach ($name in $cleared) { Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue }
# desktop_app.py 在 SHUABAO_SUBSCRIPTION_MODE 缺失时 setdefault("enforce")，只清不设等于
# 仍走正式授权；源码快速测试显式走 off（DevStartCapability，冻结包会强制 enforce）。
$env:SHUABAO_SUBSCRIPTION_MODE = "off"
$env:SHUABAO_SOURCE_QUICK_TEST = "1"
$env:SHUABAO_APP_DATA = Join-Path $env:LOCALAPPDATA "ShuaBao-dev"
# LIVE 输入锁与签名包共用：%LOCALAPPDATA%\ShuaBao\ShuaBao.live.lock
$env:SHUABAO_LIVE_LOCK_DIR = Join-Path $env:LOCALAPPDATA "ShuaBao"

$branch = (& git rev-parse --abbrev-ref HEAD 2>$null)
if ($LASTEXITCODE -ne 0) { Stop-QuickTest "无法解析分支" }
$head = (& git rev-parse HEAD 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $head) { Stop-QuickTest "无法解析 HEAD" }
$dirtyFiles = @(& git status --porcelain --untracked-files=all)
if ($LASTEXITCODE -ne 0) { Stop-QuickTest "git status 失败" }

if (-not $Python) {
    $local = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $local -PathType Leaf) {
        $Python = $local
    } else {
        $common = (& git rev-parse --path-format=absolute --git-common-dir 2>$null)
        if ($LASTEXITCODE -eq 0 -and $common) {
            $mainVenv = Join-Path (Split-Path -Parent $common.Trim()) ".venv\Scripts\python.exe"
            if (Test-Path -LiteralPath $mainVenv -PathType Leaf) { $Python = $mainVenv }
        }
    }
}
if (-not $Python) { Stop-QuickTest "找不到 .venv\Scripts\python.exe（可用 -Python 指定）" }

Write-Host "==============================================" -ForegroundColor Yellow
Write-Host " 源码快速测试 · 不做卡密验收" -ForegroundColor Yellow
Write-Host " 证据等级 SOURCE_QUICK_TEST（不是 GT，不是授权验收）" -ForegroundColor Yellow
Write-Host " 仓库：$repoRoot"
Write-Host " 分支：$($branch.Trim())"
Write-Host " HEAD：$($head.Trim())"
Write-Host " dirty 文件数：$($dirtyFiles.Count)"
Write-Host " 管理员：$isAdmin"
Write-Host " Python：$Python"
Write-Host " APP_DATA：$env:SHUABAO_APP_DATA"
Write-Host " LIVE 锁目录：$env:SHUABAO_LIVE_LOCK_DIR"
Write-Host " 已清除变量：$(if ($cleared.Count) { $cleared -join ', ' } else { '无' })"
Write-Host "==============================================" -ForegroundColor Yellow

# run_desktop_dev.ps1 负责 dist 过期检测 / npm build / build_manifest.json，然后启动
# desktop_app.py。构建失败时它抛错非零退出，这里直接报错，不回退加载旧 dist。
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $devScript -Python $Python
$code = $LASTEXITCODE
if ($code -ne 0) { Stop-QuickTest "run_desktop_dev.ps1 退出码 $code（UI 构建或启动失败，未回退旧 dist）" }
exit 0
