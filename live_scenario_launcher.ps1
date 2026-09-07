# Thin Windows menu for the existing tools/live_scenario_capture.py only.
# It discovers paths and forwards arguments; production logic stays in the tool.

param([switch]$SettingsPanelSmokeTest)

$ErrorActionPreference = "Stop"

if (-not $SettingsPanelSmokeTest -and -not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    $scriptPath = if ($PSCommandPath) { $PSCommandPath } else { Join-Path $PSScriptRoot "live_scenario_launcher.ps1" }
    Start-Process powershell.exe -ArgumentList "-NoLogo -NoProfile -ExecutionPolicy Bypass -Sta -File `"$scriptPath`"" -WorkingDirectory $PSScriptRoot -Verb RunAs
    exit
}

$RepoRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
Set-Location -LiteralPath $RepoRoot
$ToolPath = Join-Path $RepoRoot "tools\live_scenario_capture.py"

if (-not (Test-Path -LiteralPath $ToolPath -PathType Leaf)) {
    throw "找不到现有工具：$ToolPath"
}
$script:LastToolExitCode = 0

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

function Resolve-OperatorSettingsPath {
    $override = [string]$env:SHUABAO_APP_DATA
    $base = if ($override.Trim()) { $override.Trim() } else { Join-Path $env:LOCALAPPDATA "ShuaBao" }
    $path = Join-Path $base "user_settings.json"
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        return (Resolve-Path -LiteralPath $path).Path
    }
    return $null
}

function Resolve-OcrPython {
    $candidates = @()
    if ($env:SHUABAO_OCR_PYTHON) { $candidates += $env:SHUABAO_OCR_PYTHON }
    $candidates += (Join-Path $RepoRoot ".venv-ocr\Scripts\python.exe")
    # The Harness worktree is intentionally small. Reuse the existing local OCR
    # environment read-only; this changes neither the production worktree nor
    # the production settings/package.
    $workspaceRoot = Split-Path (Split-Path $RepoRoot -Parent) -Parent
    $candidates += (Join-Path $workspaceRoot "GameScript-Local\.venv-ocr\Scripts\python.exe")
    return ($candidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1)
}

function Show-HarnessSettingsPanel {
    param([switch]$ConstructOnly)

    $source = if ($script:OperatorSettingsPath) { $script:OperatorSettingsPath } else { Join-Path $RepoRoot "config\default_settings.json" }
    $raw = if (Test-Path -LiteralPath $source -PathType Leaf) {
        try {
            [System.IO.File]::ReadAllText($source, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
        } catch {
            $reason = ($_.Exception.Message -split "`r?`n")[0]
            throw "临时设置面板无法读取 UTF-8 配置：$source`r`n$reason"
        }
    } else {
        [pscustomobject]@{}
    }
    function Value-OrDefault($Name, $Default) {
        $property = $raw.PSObject.Properties[$Name]
        if ($null -eq $property -or $null -eq $property.Value) { return $Default }
        return $property.Value
    }
    function Csv-Value($Name) {
        $value = Value-OrDefault $Name @()
        if ($value -is [System.Collections.IEnumerable] -and $value -isnot [string]) { return [string]::Join(",", @($value)) }
        return [string]$value
    }

    $form = New-Object System.Windows.Forms.Form
    $form.Text = "单人完整循环 · 临时 Harness 设置"
    $form.StartPosition = "CenterScreen"
    $form.Size = New-Object System.Drawing.Size(560, 460)
    $form.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 10)
    $form.TopMost = $true
    $note = New-Object System.Windows.Forms.Label
    $note.Text = "来源：$source`r`n仅生成 %TEMP%\shuabao-captures\live_harness_settings_<timestamp>.json；不会写正式 user_settings.json。"
    $note.AutoSize = $false; $note.Size = New-Object System.Drawing.Size(510, 48); $note.Location = [System.Drawing.Point]::new(20, 15)
    $note.ForeColor = [System.Drawing.Color]::DimGray; $form.Controls.Add($note)
    $fields = @(
        @{ Label = "目标关卡（逗号分隔）"; Name = "stage_targets"; Value = (Csv-Value "stage_targets") },
        @{ Label = "技能 short code（最多 4 个）"; Name = "skills"; Value = (Csv-Value "skills") },
        @{ Label = "羁绊（逗号分隔）"; Name = "bonds"; Value = (Csv-Value "bonds") },
        @{ Label = "传家宝 Boss（留空则跳过）"; Name = "cjb_boss"; Value = (Value-OrDefault "cjb_boss" "") },
        @{ Label = "时光之穴 Boss（留空则跳过）"; Name = "sgzx_boss"; Value = (Value-OrDefault "sgzx_boss" "") }
    )
    $controls = @{}
    $y = 74
    foreach ($field in $fields) {
        $label = New-Object System.Windows.Forms.Label
        $label.Text = $field.Label; $label.AutoSize = $true; $label.Location = [System.Drawing.Point]::new(20, ($y + 4)); $form.Controls.Add($label)
        $box = New-Object System.Windows.Forms.TextBox
        $box.Text = [string]$field.Value; $box.Size = New-Object System.Drawing.Size(285, 28); $box.Location = [System.Drawing.Point]::new(230, $y)
        $controls[$field.Name] = $box; $form.Controls.Add($box); $y += 42
    }
    $secret = New-Object System.Windows.Forms.CheckBox
    $secret.Text = "自动秘境"; $secret.Checked = [bool](Value-OrDefault "auto_secret_realm" $false); $secret.Location = [System.Drawing.Point]::new(20, $y); $form.Controls.Add($secret)
    $merchant = New-Object System.Windows.Forms.CheckBox
    $merchant.Text = "黑商"; $merchant.Checked = [bool](Value-OrDefault "merchant_enabled" $false); $merchant.Location = [System.Drawing.Point]::new(140, $y); $form.Controls.Add($merchant)
    $start = New-Object System.Windows.Forms.Button
    $start.Text = "保存临时设置并开始"; $start.Size = New-Object System.Drawing.Size(220, 38); $start.Location = [System.Drawing.Point]::new(295, ($y + 35))
    $start.Add_Click({
        $skills = @($controls["skills"].Text -split "[,;\s]+" | Where-Object { $_ })
        if ($skills.Count -gt 4) { [System.Windows.Forms.MessageBox]::Show("技能最多 4 个。", "临时 Harness 设置") | Out-Null; return }
        $raw.stage_targets = @($controls["stage_targets"].Text -split "[,;\s]+" | Where-Object { $_ })
        $raw.skills = $skills
        $raw.bonds = @($controls["bonds"].Text -split "[,;\s]+" | Where-Object { $_ })
        $raw.cjb_boss = $controls["cjb_boss"].Text.Trim()
        $raw.sgzx_boss = $controls["sgzx_boss"].Text.Trim()
        $raw.auto_secret_realm = [bool]$secret.Checked
        $raw.merchant_enabled = [bool]$merchant.Checked
        $raw.mode_id = "normal_farm"
        $raw.auto_create_room = $true
        $stamp = Get-Date -Format "yyyyMMdd_HHmmss_ffff"
        $script:HarnessSettingsPath = Join-Path $script:SoloCaptureRoot "live_harness_settings_$stamp.json"
        $json = $raw | ConvertTo-Json -Depth 12
        [System.IO.File]::WriteAllText($script:HarnessSettingsPath, $json, [System.Text.UTF8Encoding]::new($false))
        $form.DialogResult = [System.Windows.Forms.DialogResult]::OK
        $form.Close()
    })
    $form.Controls.Add($start)
    $cancel = New-Object System.Windows.Forms.Button
    $cancel.Text = "取消"; $cancel.Size = New-Object System.Drawing.Size(90, 38); $cancel.Location = [System.Drawing.Point]::new(190, ($y + 35))
    $cancel.Add_Click({ $form.Close() }); $form.Controls.Add($cancel)
    if ($ConstructOnly) {
        $form.Dispose()
        return $true
    }
    return $form.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK
}

function Resolve-SoloCaptureRoot {
    $path = Join-Path $env:TEMP "shuabao-captures"
    New-Item -ItemType Directory -Path $path -Force | Out-Null
    return (Resolve-Path -LiteralPath $path).Path
}

function Get-GitIdentity {
    $branch = (& git -C $RepoRoot rev-parse --abbrev-ref HEAD 2>$null).Trim()
    $sha = (& git -C $RepoRoot rev-parse HEAD 2>$null).Trim()
    if (-not $branch) { $branch = "unknown" }
    if (-not $sha) { $sha = "unknown" }
    return @{ Branch = $branch; Sha = $sha }
}

function Invoke-CaptureTool {
    param([Parameter(Mandatory = $true)][string[]]$CliArgs)

    if (-not $script:PythonPath) {
        throw "找不到 Python。请先创建 .venv 或把 Python 置于 PATH。"
    }

    $previousOcr = $env:SHUABAO_OCR_PYTHON
    if ($script:OcrPython) { $env:SHUABAO_OCR_PYTHON = $script:OcrPython }
    try {
        & $script:PythonPath $ToolPath @CliArgs
        $exitCode = [int]$LASTEXITCODE
    } finally {
        if ($null -eq $previousOcr) { Remove-Item Env:SHUABAO_OCR_PYTHON -ErrorAction SilentlyContinue } else { $env:SHUABAO_OCR_PYTHON = $previousOcr }
    }
    $script:LastToolExitCode = $exitCode
    Write-Host "[launcher] tool exit code: $exitCode" -ForegroundColor DarkGray
    if ($exitCode -ne 0) {
        Write-Host "[launcher] 工具失败；请查看上方 preflight/manifest 证据。" -ForegroundColor Red
    }
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
            "--confirm-live-input",
            "--allow-dev-source"
        )
        if ($script:OperatorSettingsPath) {
            $cliArgs += @("--settings", $script:OperatorSettingsPath)
        }
        if ($Target -eq "black_merchant") {
            $cliArgs += @("--duration", "600", "--max-ticks", "5000")
        } elseif ($Target -eq "lobby_search") {
            # End-to-end chain: no time/tick cap. It exits only after a verified
            # guest Ready (or the operator presses Shift+F12).
            $cliArgs += @("--until-success", "--interval", "0.15")
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

function Invoke-HitchRuntimeCapture {
    $cliArgs = @(
        "capture",
        "--target", "hitch_runtime",
        "--out", $script:CaptureRoot,
        "--repo-root", $RepoRoot,
        "--duration", "3600",
        "--max-ticks", "30000",
        "--continue-after-failure",
        "--generate",
        "--automation-exe", $script:AutomationExe,
        "--live-input",
        "--confirm-live-input",
        "--allow-dev-source"
    )
    if ($script:OperatorSettingsPath) {
        $cliArgs += @("--settings", $script:OperatorSettingsPath)
    }
    Write-Host "[launcher] 蹭车局内续跑：压力转移→自动任务/四挑战→结算存档→时光之穴/传家宝 Boss" -ForegroundColor Cyan
    Invoke-CaptureTool $cliArgs
}

function Invoke-SoloFullCycleCapture {
    if (-not (Show-HarnessSettingsPanel)) { return }
    $cliArgs = @(
        "capture",
        "--target", "solo_full_cycle",
        "--out", $script:SoloCaptureRoot,
        "--repo-root", $RepoRoot,
        "--duration", "5400",
        "--max-ticks", "40000",
        "--interval", "0.15",
        "--generate",
        "--automation-exe", $script:AutomationExe,
        "--live-input",
        "--confirm-live-input",
        "--allow-dev-source"
    )
    $cliArgs += @("--settings", $script:HarnessSettingsPath)
    Write-Host "[launcher] 单人完整循环：Production RuntimeMediator.tick()；首局闭环后仅在下一局业务证据确认时 PASS" -ForegroundColor Cyan
    Invoke-CaptureTool $cliArgs
}

function Invoke-SoloTakeoverCapture {
    Add-Type -AssemblyName Microsoft.VisualBasic
    $choices = "A Stage Select; B Mid-game HUD; C Skill/Bond/Treasure panel; D Pause; E Victory; F Archive Panel; G Heirloom; H NPC Hub"
    $selected = [Microsoft.VisualBasic.Interaction]::InputBox("选择起始 Ground Truth：`r`n$choices", "单人任意状态接管", "B")
    if (-not $selected) { return }
    $code = $selected.Trim().Substring(0, 1).ToUpperInvariant()
    $map = @{ A = "stage_select"; B = "midgame_hud"; C = "choice_panel"; D = "pause"; E = "victory"; F = "archive_panel"; G = "heirloom"; H = "npc_hub" }
    if (-not $map.ContainsKey($code)) { throw "请选择 A-H。" }
    $cliArgs = @(
        "capture", "--target", "solo_takeover", "--takeover-case", $map[$code],
        "--out", $script:SoloCaptureRoot, "--repo-root", $RepoRoot,
        "--duration", "600", "--max-ticks", "5000", "--interval", "0.15",
        "--generate", "--automation-exe", $script:AutomationExe,
        "--live-input", "--confirm-live-input", "--allow-dev-source"
    )
    if ($script:OperatorSettingsPath) { $cliArgs += @("--settings", $script:OperatorSettingsPath) }
    Write-Host "[launcher] 单人任意状态接管：$($map[$code])；仅调用 production Mediator.tick()" -ForegroundColor Cyan
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
$script:SoloCaptureRoot = Resolve-SoloCaptureRoot
$script:OperatorSettingsPath = Resolve-OperatorSettingsPath
$script:OcrPython = Resolve-OcrPython
$script:HarnessIdentity = Get-GitIdentity
$script:ProductionBaselineSha = "b15da05f4fd7313b02b2cc466e319d9683aa979c"

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

if ($SettingsPanelSmokeTest) {
    if (Show-HarnessSettingsPanel -ConstructOnly) {
        Write-Host "Settings panel construction: PASS"
        exit 0
    }
    exit 1
}

$script:MenuForm = New-Object System.Windows.Forms.Form
$script:MenuForm.Text = "刷刷宝 · Live 实机测试"
$script:MenuForm.StartPosition = "CenterScreen"
$script:MenuForm.Size = New-Object System.Drawing.Size(760, 700)
$script:MenuForm.MinimumSize = New-Object System.Drawing.Size(760, 700)
$script:MenuForm.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 10)
$script:MenuForm.TopMost = $true

$title = New-Object System.Windows.Forms.Label
$title.Text = "刷刷宝 Live 实机测试"
$title.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 18, [System.Drawing.FontStyle]::Bold)
$title.AutoSize = $true
$title.Location = [System.Drawing.Point]::new(22, 18)
$script:MenuForm.Controls.Add($title)

$status = New-Object System.Windows.Forms.Label
$status.Text = "核心验收仅保留两条完整链路：单人完整循环与蹭车局内续跑。`r`n12 会先打开临时设置面板；测试开始后放开鼠标，紧急停止用 Shift+F12；p/f/m 只用于留证据。"
$status.AutoSize = $false
$status.Size = New-Object System.Drawing.Size(700, 58)
$status.Location = [System.Drawing.Point]::new(24, 60)
$status.ForeColor = [System.Drawing.Color]::FromArgb(90, 60, 0)
$script:MenuForm.Controls.Add($status)

$paths = New-Object System.Windows.Forms.Label
$paths.Text = "Harness SHA: $($script:HarnessIdentity.Branch) @ $($script:HarnessIdentity.Sha)`r`nProduction baseline SHA: $script:ProductionBaselineSha`r`nRuntime source SHA: $($script:HarnessIdentity.Sha)  |  Runtime type: SOURCE_RUNTIME`r`nProduction package/EXE: $script:AutomationExe`r`n证据目录: $script:CaptureRoot  |  单人: $script:SoloCaptureRoot  |  mode_id: normal_farm"
$paths.AutoSize = $false
$paths.Size = New-Object System.Drawing.Size(700, 96)
$paths.Location = [System.Drawing.Point]::new(24, 118)
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
    $button.Location = [System.Drawing.Point]::new($Left, $Top)
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

Add-MenuButton "1  启动前检查`r`n    只检查环境、OCR 与窗口条件，不操作游戏" 24 230 { Invoke-Readiness } $blue
Add-MenuButton "12 单人完整循环（推荐）`r`n    临时设置→创房→选关→局内→结算→回房→下一把" 390 230 { Invoke-SoloFullCycleCapture } $green
Add-MenuButton "11 蹭车局内续跑`r`n    入局后接管→自动任务/四挑战→结算链路" 24 316 { Invoke-HitchRuntimeCapture } $green
Add-MenuButton "9  打开最新 FAIL bundle`r`n    直接查看最近失败/阻塞证据" 390 316 { Open-LatestFailBundle } $blue
Add-MenuButton "10 Reproduce 最新 FAIL`r`n    进入 Frozen Replay（离线回归）" 24 402 { Reproduce-LatestFail } $blue

$exitButton = New-Object System.Windows.Forms.Button
$exitButton.Text = "关闭菜单"
$exitButton.Size = New-Object System.Drawing.Size(706, 44)
$exitButton.Location = [System.Drawing.Point]::new(24, 500)
$exitButton.Add_Click({ $script:MenuForm.Close() })
$script:MenuForm.Controls.Add($exitButton)

$footer = New-Object System.Windows.Forms.Label
$footer.Text = "注意：不要同时启动普通刷刷宝。点击测试按钮后，本窗口暂时隐藏，黑色日志窗口显示运行状态；测试结束后按钮菜单自动回来。"
$footer.AutoSize = $false
$footer.Size = New-Object System.Drawing.Size(700, 48)
$footer.Location = [System.Drawing.Point]::new(24, 560)
$footer.ForeColor = [System.Drawing.Color]::Firebrick
$script:MenuForm.Controls.Add($footer)

[void]$script:MenuForm.ShowDialog()
exit $script:LastToolExitCode
