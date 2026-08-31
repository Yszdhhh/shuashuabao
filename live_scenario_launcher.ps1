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

function Invoke-Readiness {
    Invoke-CaptureTool @("readiness", "--repo-root", $RepoRoot)
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
        if ($Target -eq "black_merchant") {
            $cliArgs += @("--duration", "600", "--max-ticks", "5000")
        }
        if (-not (Test-Path -LiteralPath $script:AutomationExe -PathType Leaf)) {
            Write-Host "[launcher] 未找到 EXE；仍交给现有 preflight 处理：$script:AutomationExe" -ForegroundColor Yellow
        }
    }

    Write-Host "[launcher] target=$Target  ground_truth_only=$GroundTruthOnly" -ForegroundColor Cyan
    Write-Host "[launcher] capture_root=$script:CaptureRoot" -ForegroundColor DarkGray
    Write-Host "[launcher] automation_exe=$script:AutomationExe" -ForegroundColor DarkGray
    Invoke-CaptureTool $cliArgs
}

function Invoke-BossSeriesCapture {
    # Mediator.tick() so tqtz -> configured Boss -> post-game archive cards ->
    # time-cave/heirloom Boss fallback stay in one production route.
    $cliArgs = @(
        "capture",
        "--target", "boss_challenge",
        "--out", $script:CaptureRoot,
        "--repo-root", $RepoRoot,
        "--duration", "600",
        "--max-ticks", "5000",
        "--continue-after-failure",
        "--generate",
        "--automation-exe", $script:AutomationExe,
        "--live-input",
        "--confirm-live-input"
    )

    Write-Host "[launcher] Boss 系列整链：现有 Mediator.tick()；tqtz/Boss/结算→存档8项→时光之穴/传家宝兜底" -ForegroundColor Cyan
    Write-Host "[launcher] capture_root=$script:CaptureRoot" -ForegroundColor DarkGray
    Write-Host "[launcher] automation_exe=$script:AutomationExe" -ForegroundColor DarkGray
    if (-not (Test-Path -LiteralPath $script:AutomationExe -PathType Leaf)) {
        Write-Host "[launcher] 未找到 EXE；仍交给现有 preflight 处理：$script:AutomationExe" -ForegroundColor Yellow
    }
    Invoke-CaptureTool $cliArgs
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
}

function Reproduce-LatestFail {
    $bundle = Get-LatestFailBundle
    if (-not $bundle) {
        Write-Host "[launcher] 当前没有可 reproduce 的 FAIL/BLOCKED bundle：$script:CaptureRoot" -ForegroundColor Yellow
    } else {
        Write-Host "[launcher] reproduce：$bundle" -ForegroundColor Cyan
        Invoke-CaptureTool @("reproduce", "--bundle", $bundle, "--repo-root", $RepoRoot)
    }
}

$script:PythonPath = Resolve-PythonPath
$script:AutomationExe = Resolve-AutomationExe
$script:CaptureRoot = Resolve-CaptureRoot

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$script:MenuForm = New-Object System.Windows.Forms.Form
$script:MenuForm.Text = "刷刷宝 · Live 实机测试"
$script:MenuForm.StartPosition = "CenterScreen"
$script:MenuForm.Size = New-Object System.Drawing.Size(760, 720)
$script:MenuForm.MinimumSize = New-Object System.Drawing.Size(760, 720)
$script:MenuForm.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 10)
$script:MenuForm.TopMost = $true

$title = New-Object System.Windows.Forms.Label
$title.Text = "刷刷宝 Live 实机测试"
$title.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 18, [System.Drawing.FontStyle]::Bold)
$title.AutoSize = $true
$title.Location = New-Object System.Drawing.Point(22, 18)
$script:MenuForm.Controls.Add($title)

$status = New-Object System.Windows.Forms.Label
$status.Text = "点击按钮即可开始，不需要输入数字。2-5 会先通过 preflight；4 只跑 Boss→存档8项→传家宝，不会点秘境；5 单独测秘境，6 只取时光之穴证据。`r`n测试开始后放开鼠标；p=留成功证据，f=留失败证据，m=人工介入后继续。"
$status.AutoSize = $false
$status.Size = New-Object System.Drawing.Size(700, 58)
$status.Location = New-Object System.Drawing.Point(24, 60)
$status.ForeColor = [System.Drawing.Color]::FromArgb(90, 60, 0)
$script:MenuForm.Controls.Add($status)

$paths = New-Object System.Windows.Forms.Label
$paths.Text = "EXE: $script:AutomationExe`r`n证据目录: $script:CaptureRoot"
$paths.AutoSize = $false
$paths.Size = New-Object System.Drawing.Size(700, 42)
$paths.Location = New-Object System.Drawing.Point(24, 118)
$paths.ForeColor = [System.Drawing.Color]::DimGray
$script:MenuForm.Controls.Add($paths)

function Add-MenuButton {
    param(
        [string]$Text,
        [int]$Left,
        [int]$Top,
        [scriptblock]$Action,
        [System.Drawing.Color]$Color = [System.Drawing.Color]::WhiteSmoke
    )
    $button = New-Object System.Windows.Forms.Button
    $button.Text = $Text
    $button.Size = New-Object System.Drawing.Size(340, 76)
    $button.Location = New-Object System.Drawing.Point($Left, $Top)
    $button.TextAlign = [System.Drawing.ContentAlignment]::MiddleLeft
    $button.Padding = New-Object System.Windows.Forms.Padding(12, 0, 6, 0)
    $button.BackColor = $Color
    $button.Tag = $Action
    $button.Add_Click({
        $script:MenuForm.Hide()
        try {
            & $this.Tag
        } catch {
            [System.Windows.Forms.MessageBox]::Show(
                $_.Exception.Message,
                "启动失败",
                [System.Windows.Forms.MessageBoxButtons]::OK,
                [System.Windows.Forms.MessageBoxIcon]::Error
            ) | Out-Null
        } finally {
            $script:MenuForm.Show()
            $script:MenuForm.Activate()
        }
    })
    $script:MenuForm.Controls.Add($button)
}

$green = [System.Drawing.Color]::FromArgb(224, 244, 226)
$blue = [System.Drawing.Color]::FromArgb(225, 238, 250)
$yellow = [System.Drawing.Color]::FromArgb(255, 246, 210)

Add-MenuButton "1  启动前检查`r`n    只检查环境，不操作游戏" 24 170 { Invoke-Readiness } $blue
Add-MenuButton "2  背包道具`r`n    吞噬丹（羁绊≥4）/英雄卡" 390 170 { Invoke-TargetProbe -Target "inventory_item" -GroundTruthOnly $false } $green
Add-MenuButton "3  黑商 + 背包长测（推荐）`r`n    刷新/拿取/吞噬丹/英雄卡/神器，最长10分钟" 24 256 { Invoke-TargetProbe -Target "black_merchant" -GroundTruthOnly $false } $green
Add-MenuButton "4  Boss 系列整链（推荐）`r`n    tqtz→Boss→结算→存档8项→时光之穴/传家宝兜底" 390 256 { Invoke-BossSeriesCapture } $green
Add-MenuButton "5  秘境进入`r`n    从胜利后 NPC/确认页进入并验证 HUD" 24 342 { Invoke-TargetProbe -Target "secret_realm" -GroundTruthOnly $false } $green
Add-MenuButton "6  时光之穴 Boss fallback（实机）`r`n    已打开列表后自动选择最后可识别 Boss" 390 342 { Invoke-TargetProbe -Target "time_cave" -GroundTruthOnly $false } $green
Add-MenuButton "7  传家宝 Boss 选择`r`n    复用 cjb_boss 选择并验证真实 HUD" 24 428 { Invoke-TargetProbe -Target "heirloom" -GroundTruthOnly $false } $green
Add-MenuButton "8  打开最新 FAIL bundle`r`n    直接查看最近失败证据" 390 428 { Open-LatestFailBundle } $blue
Add-MenuButton "9  Reproduce 最新 FAIL`r`n    一键进入 Frozen Replay" 24 514 { Reproduce-LatestFail } $blue

$exitButton = New-Object System.Windows.Forms.Button
$exitButton.Text = "关闭菜单"
$exitButton.Size = New-Object System.Drawing.Size(340, 76)
$exitButton.Location = New-Object System.Drawing.Point(390, 514)
$exitButton.Add_Click({ $script:MenuForm.Close() })
$script:MenuForm.Controls.Add($exitButton)

$footer = New-Object System.Windows.Forms.Label
$footer.Text = "注意：不要同时启动普通刷刷宝。点击测试按钮后，本窗口暂时隐藏，黑色日志窗口显示运行状态；测试结束后按钮菜单自动回来。"
$footer.AutoSize = $false
$footer.Size = New-Object System.Drawing.Size(700, 48)
$footer.Location = New-Object System.Drawing.Point(24, 610)
$footer.ForeColor = [System.Drawing.Color]::Firebrick
$script:MenuForm.Controls.Add($footer)

[void]$script:MenuForm.ShowDialog()
