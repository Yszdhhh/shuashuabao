# Thin Windows menu for the existing tools/live_scenario_capture.py only.
# It discovers paths and forwards arguments; production logic stays in the tool.

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$ToolPath = Join-Path $RepoRoot "tools\live_scenario_capture.py"

if (-not (Test-Path -LiteralPath $ToolPath -PathType Leaf)) {
    throw "找不到现有工具：$ToolPath"
}

function Resolve-PythonPath {
    $venvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
        return $venvPython
    }

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        return $pythonCommand.Source
    }

    return $null
}

function Get-ExeCandidates {
    $desktop = [Environment]::GetFolderPath("Desktop")
    return @(
        (Join-Path $RepoRoot "dist\ShuaBao\ShuaBao.exe"),
        (Join-Path $RepoRoot "dist\ShuaBao.exe"),
        (Join-Path $desktop "ShuaBao\ShuaBao.exe"),
        (Join-Path $desktop "刷刷宝\ShuaBao.exe")
    )
}

function Resolve-AutomationExe {
    $candidatePaths = @(Get-ExeCandidates)
    $existing = @(
        $candidatePaths |
            Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
            ForEach-Object { Get-Item -LiteralPath $_ }
    )

    if ($existing.Count -gt 0) {
        $withIdentity = @(
            $existing |
                Where-Object {
                    Test-Path -LiteralPath (Join-Path $_.DirectoryName "build_identity.json") -PathType Leaf
                }
        )
        if ($withIdentity.Count -gt 0) {
            return ($withIdentity | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
        }
        return ($existing | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
    }

    # Keep the normal packaged location as the value passed to the existing
    # preflight. A missing file is then reported by that preflight, not by a
    # second launcher validation path.
    return $candidatePaths[0]
}

function Resolve-CaptureRoot {
    $preferred = @()
    if ($env:SHUABAO_CAPTURE_ROOT) {
        $preferred += $env:SHUABAO_CAPTURE_ROOT
    }
    $preferred += "C:\tmp\shuabao-captures"
    $preferred += (Join-Path $env:TEMP "shuabao-captures")
    $preferred += (Join-Path $RepoRoot "captures")

    $existing = $preferred | Where-Object { Test-Path -LiteralPath $_ -PathType Container }
    if ($existing) {
        return (Resolve-Path -LiteralPath ($existing | Select-Object -First 1)).Path
    }

    $fallback = Join-Path $env:TEMP "shuabao-captures"
    New-Item -ItemType Directory -Path $fallback -Force | Out-Null
    return (Resolve-Path -LiteralPath $fallback).Path
}

function Invoke-CaptureTool {
    param([Parameter(Mandatory = $true)][string[]]$CliArgs)

    if (-not $script:PythonPath) {
        throw "找不到 Python。请先创建 .venv 或把 Python 置于 PATH。"
    }

    & $script:PythonPath $ToolPath @CliArgs
    $exitCode = $LASTEXITCODE
    Write-Host "[launcher] tool exit code: $exitCode" -ForegroundColor DarkGray
}

function Wait-ForMenu {
    [void](Read-Host "按 Enter 返回菜单")
}

function Invoke-Readiness {
    Invoke-CaptureTool @("readiness", "--repo-root", $RepoRoot)
    Wait-ForMenu
}

function Invoke-TargetProbe {
    param(
        [Parameter(Mandatory = $true)][string]$Target,
        [Parameter(Mandatory = $true)][bool]$GroundTruthOnly
    )

    $cliArgs = @(
        "probe",
        "--target", $Target,
        "--out", $script:CaptureRoot,
        "--repo-root", $RepoRoot,
        "--continue-after-failure",
        "--generate"
    )

    if (-not $GroundTruthOnly) {
        $cliArgs += @(
            "--automation-exe", $script:AutomationExe,
            "--live-input",
            "--confirm-live-input"
        )
        if (-not (Test-Path -LiteralPath $script:AutomationExe -PathType Leaf)) {
            Write-Host "[launcher] 未找到 EXE；仍交给现有 preflight 处理：$script:AutomationExe" -ForegroundColor Yellow
        }
    }

    Write-Host "[launcher] target=$Target  ground_truth_only=$GroundTruthOnly" -ForegroundColor Cyan
    Write-Host "[launcher] capture_root=$script:CaptureRoot" -ForegroundColor DarkGray
    Write-Host "[launcher] automation_exe=$script:AutomationExe" -ForegroundColor DarkGray
    Invoke-CaptureTool $cliArgs
    Wait-ForMenu
}

function Get-LatestFailBundle {
    if (-not (Test-Path -LiteralPath $script:CaptureRoot -PathType Container)) {
        return $null
    }

    $summary = Get-ChildItem -LiteralPath $script:CaptureRoot -Recurse -File -Filter "*.json" -ErrorAction SilentlyContinue |
        Where-Object { $_.Directory.Name -eq "failures" } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $summary) {
        return $null
    }

    $bundle = $summary.Directory.Parent
    if ($bundle -and (Test-Path -LiteralPath (Join-Path $bundle.FullName "manifest.json") -PathType Leaf)) {
        return $bundle.FullName
    }
    return $null
}

function Open-LatestFailBundle {
    $bundle = Get-LatestFailBundle
    if (-not $bundle) {
        Write-Host "[launcher] 当前没有 FAIL/BLOCKED bundle：$script:CaptureRoot" -ForegroundColor Yellow
    } else {
        Write-Host "[launcher] 打开最新 FAIL bundle：$bundle" -ForegroundColor Green
        Invoke-Item -LiteralPath $bundle
    }
    Wait-ForMenu
}

function Reproduce-LatestFail {
    $bundle = Get-LatestFailBundle
    if (-not $bundle) {
        Write-Host "[launcher] 当前没有可 reproduce 的 FAIL/BLOCKED bundle：$script:CaptureRoot" -ForegroundColor Yellow
    } else {
        Write-Host "[launcher] reproduce：$bundle" -ForegroundColor Cyan
        Invoke-CaptureTool @("reproduce", "--bundle", $bundle, "--repo-root", $RepoRoot)
    }
    Wait-ForMenu
}

$script:PythonPath = Resolve-PythonPath
$script:AutomationExe = Resolve-AutomationExe
$script:CaptureRoot = Resolve-CaptureRoot

while ($true) {
    Write-Host ""
    Write-Host "刷刷宝 · 实机测试菜单" -ForegroundColor White
    Write-Host "repo: $RepoRoot" -ForegroundColor DarkGray
    Write-Host "exe : $script:AutomationExe" -ForegroundColor DarkGray
    Write-Host "out : $script:CaptureRoot" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "说明：2-5 只有 preflight 通过才会尝试操作游戏；6-7 只记录画面，不会自动点击。" -ForegroundColor Yellow
    Write-Host "测试开始后请放开鼠标；异常时按 f 留证，需要人工绕过时先 f、再人工处理、最后按 m。" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "1  启动前检查：看工具和运行环境是否准备好（不操作游戏）"
    Write-Host "2  背包吞噬丹：使用后确认真的消耗，且没有重复点击"
    Write-Host "3  黑商吞噬丹：刷新、找到、获取并确认；木材只记录，不购买"
    Write-Host "4  Boss 挑战：从 Boss 列表选目标，确认真的进入目的地"
    Write-Host "5  秘境进入：确认后必须看到真正的局内 HUD"
    Write-Host "6  时光之穴取证：记录人工走过的完整链路，不自动点击"
    Write-Host "7  传家宝取证：记录人工走过的完整链路，不自动选 Boss"
    Write-Host "8  打开最近一次失败：查看最新 FAIL/BLOCKED 证据目录"
    Write-Host "9  重放最近一次失败：离线生成并运行 Frozen Replay"
    Write-Host "0  退出"

    $choice = (Read-Host "请输入数字").Trim()
    switch ($choice) {
        "1" { Invoke-Readiness }
        "2" { Invoke-TargetProbe -Target "inventory_item" -GroundTruthOnly $false }
        "3" { Invoke-TargetProbe -Target "black_merchant" -GroundTruthOnly $false }
        "4" { Invoke-TargetProbe -Target "boss_challenge" -GroundTruthOnly $false }
        "5" { Invoke-TargetProbe -Target "secret_realm" -GroundTruthOnly $false }
        "6" { Invoke-TargetProbe -Target "time_cave" -GroundTruthOnly $true }
        "7" { Invoke-TargetProbe -Target "heirloom" -GroundTruthOnly $true }
        "8" { Open-LatestFailBundle }
        "9" { Reproduce-LatestFail }
        "0" { return }
        default { Write-Host "请输入 0-9。" -ForegroundColor Yellow }
    }
}
