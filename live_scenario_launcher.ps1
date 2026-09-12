# Thin Windows menu for the existing tools/live_scenario_capture.py only.
# It discovers paths and forwards arguments; production logic stays in the tool.

param(
    [switch]$SettingsPanelSmokeTest,
    [string]$ProductionSourceRoot = "",
    [string]$ProductionSourceSha = ""
)

$ErrorActionPreference = "Stop"

if (-not $SettingsPanelSmokeTest -and -not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    $scriptPath = if ($PSCommandPath) { $PSCommandPath } else { Join-Path $PSScriptRoot "live_scenario_launcher.ps1" }
    $relaunchArgs = "-NoLogo -NoProfile -ExecutionPolicy Bypass -Sta -File `"$scriptPath`""
    if ($ProductionSourceRoot) { $relaunchArgs += " -ProductionSourceRoot `"$ProductionSourceRoot`"" }
    if ($ProductionSourceSha) { $relaunchArgs += " -ProductionSourceSha `"$ProductionSourceSha`"" }
    if ($SettingsPanelSmokeTest) { $relaunchArgs += " -SettingsPanelSmokeTest" }
    Start-Process powershell.exe -ArgumentList $relaunchArgs -WorkingDirectory $PSScriptRoot -Verb RunAs
    exit
}

$RepoRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
Set-Location -LiteralPath $RepoRoot
# The tool prints UTF-8, but an elevated console starts on the OEM codepage
# (936 on this machine).  Decoding UTF-8 as GBK turns the repo's Chinese path
# "G:\刷刷宝\..." into "G:\\鍒峰埛瀹漒\Worktrees\\...", i.e. one of the doubled
# backslashes becomes a lone "\W", and ConvertFrom-Json then dies with
# "Unrecognized escape sequence".  The launcher reported that as
# "candidate identity JSON unreadable (exit 0) / READY FOR GT: NO" — an
# identity failure that had nothing to do with the candidate.  Pin both ends
# to UTF-8 before any tool call.
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$ToolPath = Join-Path $RepoRoot "tools\live_scenario_capture.py"
$script:ProductionSourceRoot = if ($ProductionSourceRoot) { (Resolve-Path -LiteralPath $ProductionSourceRoot).Path } else { "" }
$script:ProductionSourceSha = if ($ProductionSourceSha) { $ProductionSourceSha.Trim().ToLowerInvariant() } else { "" }
if ($script:ProductionSourceSha -and ($script:ProductionSourceSha -notmatch '^[0-9a-f]{40}$')) {
    throw "Production candidate SHA 格式无效：$ProductionSourceSha"
}
if ($script:ProductionSourceRoot) {
    $env:SHUABAO_PRODUCTION_SOURCE_ROOT = $script:ProductionSourceRoot
} else {
    Remove-Item env:SHUABAO_PRODUCTION_SOURCE_ROOT -ErrorAction SilentlyContinue
}
if ($script:ProductionSourceSha) {
    $env:SHUABAO_PRODUCTION_SOURCE_SHA = $script:ProductionSourceSha
} else {
    Remove-Item env:SHUABAO_PRODUCTION_SOURCE_SHA -ErrorAction SilentlyContinue
}

if (-not (Test-Path -LiteralPath $ToolPath -PathType Leaf)) {
    throw "找不到现有工具：$ToolPath"
}
$script:LastToolExitCode = 0

function Resolve-PythonPath {
    $candidates = @(
        (Join-Path $RepoRoot ".venv\Scripts\python.exe")
    )
    $workspaceRoot = Split-Path (Split-Path $RepoRoot -Parent) -Parent
    $candidates += (Join-Path $workspaceRoot "GameScript-Local\.venv\Scripts\python.exe")
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        return $pythonCommand.Source
    }

    return $null
}

function Get-ExeCandidates {
    # Never pick a Desktop/old-worktree EXE. The live harness must load this
    # worktree's production source, or a package built from it.
    return @(
        (Join-Path $RepoRoot "dist\ShuaBao\ShuaBao.exe"),
        (Join-Path $RepoRoot "dist\ShuaBao.exe")
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

function Resolve-OcrModelDir {
    $candidates = @()
    if ($env:SHUABAO_OCR_MODEL_DIR) { $candidates += $env:SHUABAO_OCR_MODEL_DIR }
    $candidates += (Join-Path $RepoRoot "models\ocr")
    $workspaceRoot = Split-Path (Split-Path $RepoRoot -Parent) -Parent
    $candidates += (Join-Path $workspaceRoot "GameScript-Local\models\ocr")
    foreach ($candidate in $candidates) {
        $model = if ((Split-Path $candidate -Leaf) -eq "PP-OCRv5_mobile_rec_infer") {
            $candidate
        } else {
            Join-Path $candidate "PP-OCRv5_mobile_rec_infer"
        }
        if (
            (Test-Path -LiteralPath (Join-Path $model "inference.json") -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path $model "inference.pdiparams") -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path $model "inference.yml") -PathType Leaf)
        ) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return $null
}

function Read-HarnessSettingsSource {
    $source = if ($script:OperatorSettingsPath) { $script:OperatorSettingsPath } else { Join-Path $RepoRoot "config\default_settings.json" }
    try {
        $raw = [System.IO.File]::ReadAllText($source, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
    } catch {
        $reason = ($_.Exception.Message -split "`r?`n")[0]
        throw "Harness 无法读取 UTF-8 配置：$source`r`n$reason"
    }
    return @{ Path = $source; Value = $raw }
}

function Save-HarnessSettingsCopy {
    param([Parameter(Mandatory = $true)]$SettingsObject)

    $SettingsObject.mode_id = "normal_farm"
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss_ffff"
    $path = Join-Path $script:SoloCaptureRoot "live_harness_settings_$stamp.json"
    $json = $SettingsObject | ConvertTo-Json -Depth 12
    [System.IO.File]::WriteAllText($path, $json, [System.Text.UTF8Encoding]::new($false))
    return $path
}

function New-DashboardSettingsSnapshot {
    $loaded = Read-HarnessSettingsSource
    $path = Save-HarnessSettingsCopy $loaded.Value
    Write-Host "[launcher] 已只读复制正式看板设置：$($loaded.Path)" -ForegroundColor DarkGray
    Write-Host "[launcher] 本次隔离设置副本：$path" -ForegroundColor DarkGray
    return $path
}

function Show-HarnessSettingsPanel {
    param([switch]$ConstructOnly)

    $loaded = Read-HarnessSettingsSource
    $source = $loaded.Path
    $raw = $loaded.Value
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
    $form.Size = New-Object System.Drawing.Size(620, 590)
    $form.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 10)
    $form.TopMost = $true
    $note = New-Object System.Windows.Forms.Label
    $note.Text = "默认点击 12 会自动读取正式看板设置，无需在这里输入。`r`n来源：$source`r`n本页只生成临时覆盖，不会写正式 user_settings.json。"
    $note.AutoSize = $false; $note.Size = New-Object System.Drawing.Size(570, 62); $note.Location = [System.Drawing.Point]::new(20, 15)
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
    $toggleSpecs = @(
        @{ Label = "自动秘境"; Name = "auto_secret_realm" },
        @{ Label = "5-5 后关闭自动任务"; Name = "auto_close_main_line" },
        @{ Label = "存档/考古挑战"; Name = "auto_archaeology" },
        @{ Label = "自动羁绊"; Name = "auto_bond" },
        @{ Label = "自动宝物"; Name = "auto_treasure" },
        @{ Label = "自动装备"; Name = "auto_weapon" },
        @{ Label = "黑商"; Name = "merchant_enabled" }
    )
    $toggleControls = @{}
    $toggleY = $y
    for ($i = 0; $i -lt $toggleSpecs.Count; $i++) {
        $spec = $toggleSpecs[$i]
        $check = New-Object System.Windows.Forms.CheckBox
        $check.Text = $spec.Label
        $check.Checked = [bool](Value-OrDefault $spec.Name $false)
        $check.Location = [System.Drawing.Point]::new((20 + (($i % 2) * 290)), ($toggleY + ([math]::Floor($i / 2) * 30)))
        $check.AutoSize = $true
        $toggleControls[$spec.Name] = $check
        $form.Controls.Add($check)
    }
    $toggleY += ([math]::Ceiling($toggleSpecs.Count / 2) * 30)
    $start = New-Object System.Windows.Forms.Button
    $start.Text = "保存为下一次测试的临时覆盖"; $start.Size = New-Object System.Drawing.Size(250, 38); $start.Location = [System.Drawing.Point]::new(330, ($toggleY + 16))
    $start.Add_Click({
        $skills = @($controls["skills"].Text -split "[,;\s]+" | Where-Object { $_ })
        if ($skills.Count -gt 4) { [System.Windows.Forms.MessageBox]::Show("技能最多 4 个。", "临时 Harness 设置") | Out-Null; return }
        $raw.stage_targets = @($controls["stage_targets"].Text -split "[,;\s]+" | Where-Object { $_ })
        $raw.skills = $skills
        $raw.bonds = @($controls["bonds"].Text -split "[,;\s]+" | Where-Object { $_ })
        $raw.cjb_boss = $controls["cjb_boss"].Text.Trim()
        $raw.sgzx_boss = $controls["sgzx_boss"].Text.Trim()
        foreach ($spec in $toggleSpecs) {
            $raw.($spec.Name) = [bool]$toggleControls[$spec.Name].Checked
        }
        $script:HarnessSettingsPath = Save-HarnessSettingsCopy $raw
        $form.DialogResult = [System.Windows.Forms.DialogResult]::OK
        $form.Close()
    })
    $form.Controls.Add($start)
    $cancel = New-Object System.Windows.Forms.Button
    $cancel.Text = "取消"; $cancel.Size = New-Object System.Drawing.Size(90, 38); $cancel.Location = [System.Drawing.Point]::new(230, ($toggleY + 16))
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

function Get-HarnessIdentity {
    if (-not $script:PythonPath) {
        return @{
            ReadyForGt = $false
            Text = "Harness HEAD: unknown`r`nREADY FOR GT: NO`r`nBLOCKED: python unavailable"
            Json = $null
        }
    }
    $identityScript = Join-Path $RepoRoot "tools\live_scenario_capture.py"
    $identityArgs = @($identityScript, "identity", "--repo-root", $RepoRoot)
    if ($script:ProductionSourceRoot) {
        $identityArgs += @("--production-source-root", $script:ProductionSourceRoot)
    }
    if ($script:ProductionSourceSha) {
        $identityArgs += @("--production-source-sha", $script:ProductionSourceSha)
    }
    $identityArgs += @("--json")
    if ($script:AutomationExe -and (Test-Path -LiteralPath $script:AutomationExe -PathType Leaf)) {
        $identityArgs += @("--automation-exe", $script:AutomationExe)
    }
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $raw = & $script:PythonPath @identityArgs 2>&1
        $code = [int]$LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prevEap
    }
    $jsonText = [string]::Join("`n", @($raw | ForEach-Object { [string]$_ }))
    if (-not $jsonText.Trim()) {
        return @{
            ReadyForGt = $false
            Text = "Harness HEAD: unknown`r`nREADY FOR GT: NO`r`nBLOCKED: identity command failed (exit $code)"
            Json = $null
        }
    }
    try {
        $json = $jsonText | ConvertFrom-Json
    } catch {
        return @{
            ReadyForGt = $false
            Text = "Harness HEAD: unknown`r`nREADY FOR GT: NO`r`nBLOCKED: candidate identity JSON unreadable (exit $code)"
            Json = $null
        }
    }
    $ready = [bool]$json.ready_for_gt
    $readyText = if ($ready) { "YES" } else { "NO" }
    $textLines = @(
        "Harness HEAD: $($json.harness_head)",
        "Harness branch: $($json.harness_branch)",
        "Production source: $($json.production_source_root)",
        "Production candidate SHA: $($json.production_source_sha)",
        "Candidate source clean: $($json.production_source_clean)",
        "Candidate injection: $($json.candidate_source_injection)",
        "READY FOR GT: $readyText"
    )
    foreach ($reason in @($json.blocked_reasons)) {
        if ([string]$reason) { $textLines += "BLOCKED: $reason" }
    }
    return @{
        ReadyForGt = $ready
        Text = [string]::Join("`r`n", $textLines)
        Json = $json
    }
}

function Assert-ReadyForGt {
    if ($script:ReadyForGt) { return }
    throw "READY FOR GT = NO。正式验收按钮已锁定。请先用「1 启动前检查」查看身份门禁。"
}

function Invoke-CaptureTool {
    param([Parameter(Mandatory = $true)][string[]]$CliArgs)

    if (-not $script:PythonPath) {
        throw "找不到 Python。请先创建 .venv 或把 Python 置于 PATH。"
    }

    $previousOcr = $env:SHUABAO_OCR_PYTHON
    $previousOcrModel = $env:SHUABAO_OCR_MODEL_DIR
    $previousSourceRoot = $env:SHUABAO_PRODUCTION_SOURCE_ROOT
    $previousSourceSha = $env:SHUABAO_PRODUCTION_SOURCE_SHA
    if ($script:OcrPython) { $env:SHUABAO_OCR_PYTHON = $script:OcrPython }
    if ($script:OcrModelDir) { $env:SHUABAO_OCR_MODEL_DIR = $script:OcrModelDir }
    if ($script:ProductionSourceRoot) { $env:SHUABAO_PRODUCTION_SOURCE_ROOT = $script:ProductionSourceRoot }
    if ($script:ProductionSourceSha) { $env:SHUABAO_PRODUCTION_SOURCE_SHA = $script:ProductionSourceSha }
    try {
        & $script:PythonPath $ToolPath @CliArgs
        $exitCode = [int]$LASTEXITCODE
    } finally {
        if ($null -eq $previousOcr) { Remove-Item Env:SHUABAO_OCR_PYTHON -ErrorAction SilentlyContinue } else { $env:SHUABAO_OCR_PYTHON = $previousOcr }
        if ($null -eq $previousOcrModel) { Remove-Item Env:SHUABAO_OCR_MODEL_DIR -ErrorAction SilentlyContinue } else { $env:SHUABAO_OCR_MODEL_DIR = $previousOcrModel }
        if ($null -eq $previousSourceRoot) { Remove-Item Env:SHUABAO_PRODUCTION_SOURCE_ROOT -ErrorAction SilentlyContinue } else { $env:SHUABAO_PRODUCTION_SOURCE_ROOT = $previousSourceRoot }
        if ($null -eq $previousSourceSha) { Remove-Item Env:SHUABAO_PRODUCTION_SOURCE_SHA -ErrorAction SilentlyContinue } else { $env:SHUABAO_PRODUCTION_SOURCE_SHA = $previousSourceSha }
    }
    $script:LastToolExitCode = $exitCode
    Write-Host "[launcher] tool exit code: $exitCode" -ForegroundColor DarkGray
    if ($exitCode -eq 3) {
        Write-Host "[launcher] 启动前置条件未满足；请先还原并前台显示目标 KK/游戏窗口，再重试。" -ForegroundColor Yellow
    }
    if ($exitCode -ne 0) {
        Write-Host "[launcher] 工具失败；请查看上方 preflight/manifest 证据。" -ForegroundColor Red
    }
}

function Invoke-Readiness {
    $readinessArgs = @("readiness", "--repo-root", $RepoRoot)
    if ($script:ProductionSourceRoot) {
        $readinessArgs += @("--production-source-root", $script:ProductionSourceRoot)
    }
    if ($script:ProductionSourceSha) {
        $readinessArgs += @("--production-source-sha", $script:ProductionSourceSha)
    }
    Invoke-CaptureTool $readinessArgs
}

function Get-LiveRuntimeArgs {
    # Windows PowerShell 5.1 treats an empty Generic.List as $null, so a
    # Mandatory List parameter throws "无法将参数绑定到参数 CliArgs".
    # Return a plain array. Live ticks import this worktree's source; a leftover
    # dist EXE whose source_sha lags harness-only commits would fail-close
    # before any tick, so do not pass --automation-exe here.
    $runtimeArgs = @("--live-input", "--confirm-live-input", "--allow-dev-source")
    if ($script:ProductionSourceRoot) {
        $runtimeArgs += @("--production-source-root", $script:ProductionSourceRoot)
    }
    if ($script:ProductionSourceSha) {
        $runtimeArgs += @("--production-source-sha", $script:ProductionSourceSha)
    }
    return $runtimeArgs
}

function Invoke-TargetProbe {
    param(
        [Parameter(Mandatory = $true)][string]$Target,
        [Parameter(Mandatory = $true)][bool]$GroundTruthOnly
    )

    if (-not $GroundTruthOnly) {
        Assert-ReadyForGt
    }

    $cliArgs = @(
        "probe",
        "--target", $Target,
        "--out", $script:CaptureRoot,
        "--repo-root", $RepoRoot,
        "--continue-after-failure",
        "--generate"
    )
    if ($script:ProductionSourceRoot) {
        $cliArgs += @("--production-source-root", $script:ProductionSourceRoot)
    }
    if ($script:ProductionSourceSha) {
        $cliArgs += @("--production-source-sha", $script:ProductionSourceSha)
    }

    if (-not $GroundTruthOnly) {
        $cliArgs += @(Get-LiveRuntimeArgs)
        if ($script:OperatorSettingsPath) {
            $cliArgs += @("--settings", $script:OperatorSettingsPath)
        }
        if ($Target -eq "black_merchant") {
            $cliArgs += @("--duration", "600", "--max-ticks", "5000")
        } elseif ($Target -eq "heirloom") {
            $cliArgs += @("--duration", "90", "--max-ticks", "400")
        } elseif ($Target -eq "lobby_search") {
            # End-to-end chain: no time/tick cap. It exits only after a verified
            # guest Ready (or the operator presses Shift+F12).
            $cliArgs += @("--until-success", "--interval", "0.15")
        }
        if ($script:AutomationExe -and -not (Test-Path -LiteralPath $script:AutomationExe -PathType Leaf)) {
            Write-Host "[launcher] 本次使用已验证的源码运行时；不需要 worktree EXE。" -ForegroundColor DarkGray
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
    if ($script:AutomationExe -and -not (Test-Path -LiteralPath $script:AutomationExe -PathType Leaf)) {
        Write-Host "[launcher] 未找到 EXE；仍交给现有 preflight 处理：$script:AutomationExe" -ForegroundColor Yellow
    }
    Invoke-CaptureTool $cliArgs
}

function Invoke-HitchRuntimeCapture {
    Assert-ReadyForGt
    $cliArgs = @(
        "capture",
        "--target", "hitch_runtime",
        "--out", $script:CaptureRoot,
        "--repo-root", $RepoRoot,
        "--duration", "3600",
        "--max-ticks", "30000",
        "--continue-after-failure",
        "--generate"
    )
    $cliArgs += @(Get-LiveRuntimeArgs)
    if ($script:OperatorSettingsPath) {
        $cliArgs += @("--settings", $script:OperatorSettingsPath)
    }
    Write-Host "[launcher] 蹭车局内续跑：中途接管跳过压力转移→自动任务/四挑战→结算存档→时光之穴/传家宝 Boss" -ForegroundColor Cyan
    Invoke-CaptureTool $cliArgs
}

function Invoke-HitchLobbyChainCapture {
    Assert-ReadyForGt
    $cliArgs = @(
        "capture",
        "--target", "hitch_lobby_chain",
        "--out", $script:CaptureRoot,
        "--repo-root", $RepoRoot,
        # 5 full hitch rounds (hitch_cycle_num=5) do not fit in one hour.
        "--duration", "10800",
        "--max-ticks", "60000",
        "--interval", "0.15",
        "--continue-after-failure",
        "--generate"
    )
    $cliArgs += @(Get-LiveRuntimeArgs)
    if ($script:OperatorSettingsPath) {
        $cliArgs += @("--settings", $script:OperatorSettingsPath)
    }
    Write-Host "[launcher] PRIMARY HITCH_FULL_NATURAL_E2E：production Mediator.tick() 连续大厅蹭车链；Harness 不复制 FSM" -ForegroundColor Cyan
    Invoke-CaptureTool $cliArgs
}

function Invoke-PublicBackpackDepositProbe {
    Assert-ReadyForGt
    $cliArgs = @(
        "probe",
        "--target", "public_backpack_deposit",
        "--out", $script:CaptureRoot,
        "--repo-root", $RepoRoot,
        "--duration", "120",
        "--max-ticks", "1000",
        "--continue-after-failure",
        "--generate"
    )
    $cliArgs += @(Get-LiveRuntimeArgs)
    if ($script:OperatorSettingsPath) { $cliArgs += @("--settings", $script:OperatorSettingsPath) }
    Write-Host "[launcher] K 公共背包：物品栏除1号外至少两件；开包→个人格→公共格→关闭。不要手搬。" -ForegroundColor Cyan
    Invoke-CaptureTool $cliArgs
}

function Invoke-SoloIngameChainCapture {
    Assert-ReadyForGt
    $settingsPath = $script:HarnessSettingsPath
    $script:HarnessSettingsPath = $null
    if (-not $settingsPath -or -not (Test-Path -LiteralPath $settingsPath -PathType Leaf)) {
        $settingsPath = New-DashboardSettingsSnapshot
    } else {
        Write-Host "[launcher] 本次使用已保存的临时覆盖：$settingsPath" -ForegroundColor DarkGray
    }
    $cliArgs = @(
        "capture",
        "--target", "solo_ingame_chain",
        "--out", $script:SoloCaptureRoot,
        "--repo-root", $RepoRoot,
        "--duration", "3600",
        "--max-ticks", "30000",
        "--interval", "0.15",
        "--generate"
    )
    $cliArgs += @(Get-LiveRuntimeArgs)
    $cliArgs += @("--settings", $settingsPath)
    Write-Host "[launcher] 单人完整链路：沿用正式看板自动建房/局数/关卡；production 从大厅建房→选关→局内→战后" -ForegroundColor Cyan
    Invoke-CaptureTool $cliArgs
}

function Invoke-SoloSettingsPanel {
    if (Show-HarnessSettingsPanel) {
        [System.Windows.Forms.MessageBox]::Show(
            "临时覆盖已保存；下一次点击 12 时使用一次。之后会恢复为自动读取正式看板设置。",
            "单人局内链路 · 临时设置"
        ) | Out-Null
    }
}

function Invoke-SoloTakeoverCapture {
    Assert-ReadyForGt
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
        "--generate"
    )
    $cliArgs += @(Get-LiveRuntimeArgs)
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

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

function Show-LauncherError {
    param([string]$Message)
    [System.Windows.Forms.MessageBox]::Show(
        $Message,
        "刷刷宝 Live 实机测试启动失败",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error
    ) | Out-Null
}

try {
$script:PythonPath = Resolve-PythonPath
# ProductionSourceRoot means every live lane below uses the injected source
# runtime (`--allow-dev-source`) and never executes a packaged EXE.  Do not let
# an unrelated stale dist EXE veto that source-runtime identity.
$script:AutomationExe = if ($script:ProductionSourceRoot) { $null } else { Resolve-AutomationExe }
$script:CaptureRoot = Resolve-CaptureRoot
$script:SoloCaptureRoot = Resolve-SoloCaptureRoot
$script:OperatorSettingsPath = Resolve-OperatorSettingsPath
$script:OcrPython = Resolve-OcrPython
$script:OcrModelDir = Resolve-OcrModelDir

if ($SettingsPanelSmokeTest) {
    $smokeSettings = New-DashboardSettingsSnapshot
    try {
        [void]([System.IO.File]::ReadAllText($smokeSettings, [System.Text.Encoding]::UTF8) | ConvertFrom-Json)
        if (Show-HarnessSettingsPanel -ConstructOnly) {
            Write-Host "Settings snapshot and optional panel construction: PASS"
            exit 0
        }
    } finally {
        Remove-Item -LiteralPath $smokeSettings -ErrorAction SilentlyContinue
    }
    exit 1
}

$script:IdentityInfo = Get-HarnessIdentity
$script:ReadyForGt = [bool]$script:IdentityInfo.ReadyForGt

$script:MenuForm = New-Object System.Windows.Forms.Form
$script:MenuForm.Text = "刷刷宝 · Live 实机测试"
$script:MenuForm.StartPosition = "CenterScreen"
$script:MenuForm.Size = New-Object System.Drawing.Size(760, 860)
$script:MenuForm.MinimumSize = New-Object System.Drawing.Size(760, 860)
$script:MenuForm.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 10)
$script:MenuForm.TopMost = $true

$title = New-Object System.Windows.Forms.Label
$title.Text = "刷刷宝 Live 实机测试"
$title.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 18, [System.Drawing.FontStyle]::Bold)
$title.AutoSize = $true
$title.Location = [System.Drawing.Point]::new(22, 18)
$script:MenuForm.Controls.Add($title)

$status = New-Object System.Windows.Forms.Label
$status.Text = "PRIMARY = HITCH_FULL_NATURAL_E2E（13）：整条大厅蹭车链连续运行；单项入口仅作整链失败后的窄复现。`r`n公共背包首次只做 GT_CAPTURE/MANUAL_INTERVENTION，不猜转移动作。READY FOR GT = NO 时验收按钮锁定。紧急停止用 Shift+F12。"
$status.AutoSize = $false
$status.Size = New-Object System.Drawing.Size(700, 48)
$status.Location = [System.Drawing.Point]::new(24, 60)
$status.ForeColor = [System.Drawing.Color]::FromArgb(90, 60, 0)
$script:MenuForm.Controls.Add($status)

$paths = New-Object System.Windows.Forms.Label
$exeText = if ($script:AutomationExe) { $script:AutomationExe } else { "(source runtime, no worktree EXE)" }
$paths.Text = "$($script:IdentityInfo.Text)`r`nRuntime type: SOURCE_RUNTIME  |  EXE: $exeText`r`n证据目录: $script:CaptureRoot  |  单人: $script:SoloCaptureRoot"
$paths.AutoSize = $false
$paths.Size = New-Object System.Drawing.Size(700, 150)
$paths.Location = [System.Drawing.Point]::new(24, 110)
if ($script:ReadyForGt) {
    $paths.ForeColor = [System.Drawing.Color]::FromArgb(20, 90, 40)
} else {
    $paths.ForeColor = [System.Drawing.Color]::Firebrick
}
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
$locked = [System.Drawing.Color]::FromArgb(220, 220, 220)

function Invoke-TargetedProbeMenu {
    $probeForm = New-Object System.Windows.Forms.Form
    $probeForm.Text = "单项实机测试"
    $probeForm.StartPosition = "CenterScreen"
    $probeForm.Size = New-Object System.Drawing.Size(720, 620)
    $probeForm.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 10)
    $probeForm.TopMost = $true
    $note = New-Object System.Windows.Forms.Label
    $note.Text = "每个 Probe 只调用当前 production handler。缺前置则 ZERO INPUT。不要伪造 PASS。"
    $note.AutoSize = $false
    $note.Size = New-Object System.Drawing.Size(660, 40)
    $note.Location = [System.Drawing.Point]::new(20, 12)
    $probeForm.Controls.Add($note)
    $probes = @(
        @{ Key = "A"; Target = "choice_bond_skill"; Label = "A  羁绊 / 技能选卡" },
        @{ Key = "B"; Target = "treasure"; Label = "B  宝物" },
        @{ Key = "C"; Target = "hero_evolve"; Label = "C  英雄进化" },
        @{ Key = "D"; Target = "inventory_devour"; Label = "D  背包 - 吞噬丹" },
        @{ Key = "E"; Target = "inventory_hero_card"; Label = "E  背包 - 英雄卡" },
        @{ Key = "F"; Target = "black_merchant"; Label = "F  黑商" },
        @{ Key = "G"; Target = "archive_challenge"; Label = "G  存档挑战 1~8" },
        @{ Key = "H"; Target = "heirloom"; Label = "H  传家宝 / Boss" },
        @{ Key = "I"; Target = "secret_realm"; Label = "I  秘境" },
        @{ Key = "J"; Target = "lobby_search"; Label = "J  大厅搜房 / Join" },
        @{ Key = "K"; Target = "public_backpack_deposit"; Label = "K  公共背包 物品栏→个人→公共" }
    )
    for ($i = 0; $i -lt $probes.Count; $i++) {
        $spec = $probes[$i]
        $button = New-Object System.Windows.Forms.Button
        $button.Text = $spec.Label
        $button.Size = New-Object System.Drawing.Size(320, 42)
        $button.Location = [System.Drawing.Point]::new((20 + (($i % 2) * 340)), (60 + ([math]::Floor($i / 2) * 50)))
        $button.Tag = $spec.Target
        $button.Add_Click({
            $probeForm.Hide()
            try {
                if ([string]$this.Tag -eq "public_backpack_deposit") {
                    Invoke-PublicBackpackDepositProbe
                } else {
                    Invoke-TargetProbe -Target ([string]$this.Tag) -GroundTruthOnly $false
                }
            } finally {
                $probeForm.Show()
                $probeForm.Activate()
            }
        })
        $probeForm.Controls.Add($button)
    }
    $close = New-Object System.Windows.Forms.Button
    $close.Text = "返回主菜单"
    $close.Size = New-Object System.Drawing.Size(660, 36)
    $close.Location = [System.Drawing.Point]::new(20, 520)
    $close.Add_Click({ $probeForm.Close() })
    $probeForm.Controls.Add($close)
    [void]$probeForm.ShowDialog()
}

Add-MenuButton "1  启动前检查`r`n    环境 / OCR / production / 身份门禁，不操作游戏" 24 270 { Invoke-Readiness } $blue
Add-MenuButton "12 单人完整链路`r`n    大厅建房→选关→局内→战后；production tick()" $(if ($script:ReadyForGt) { 390 } else { 390 }) 270 { Invoke-SoloIngameChainCapture } $(if ($script:ReadyForGt) { $green } else { $locked })
Add-MenuButton "11 蹭车局内完整链路`r`n    已入局后接管→自动任务/四挑战→结算" 24 356 { Invoke-HitchRuntimeCapture } $(if ($script:ReadyForGt) { $green } else { $locked })
Add-MenuButton "13 PRIMARY HITCH_FULL_NATURAL_E2E`r`n    大厅→搜房→Ready→Pressure→整局→回厅→下一轮" 390 356 { Invoke-HitchLobbyChainCapture } $(if ($script:ReadyForGt) { $green } else { $locked })
Add-MenuButton "单项实机测试`r`n    A-K 只调 production handler" 24 442 { Invoke-TargetedProbeMenu } $(if ($script:ReadyForGt) { $green } else { $locked })
Add-MenuButton "9  打开最新 FAIL bundle`r`n    直接查看最近失败/阻塞证据" 390 442 { Open-LatestFailBundle } $blue
Add-MenuButton "10 Reproduce 最新 FAIL`r`n    进入 Frozen Replay（离线回归）" 24 528 { Reproduce-LatestFail } $blue
Add-MenuButton "单人临时设置（可选）`r`n    仅覆盖下一次 12；默认读取正式看板" 390 528 { Invoke-SoloSettingsPanel } $yellow

$exitButton = New-Object System.Windows.Forms.Button
$exitButton.Text = "关闭菜单"
$exitButton.Size = New-Object System.Drawing.Size(706, 44)
$exitButton.Location = [System.Drawing.Point]::new(24, 624)
$exitButton.Add_Click({ $script:MenuForm.Close() })
$script:MenuForm.Controls.Add($exitButton)

$footer = New-Object System.Windows.Forms.Label
$footer.Text = "注意：不要同时启动普通刷刷宝。UNKNOWN / 窗口身份不可信时 ZERO INPUT。点击测试按钮后本窗口暂时隐藏。"
$footer.AutoSize = $false
$footer.Size = New-Object System.Drawing.Size(700, 48)
$footer.Location = [System.Drawing.Point]::new(24, 680)
$footer.ForeColor = [System.Drawing.Color]::Firebrick
$script:MenuForm.Controls.Add($footer)

[void]$script:MenuForm.ShowDialog()
exit $script:LastToolExitCode
} catch {
    Show-LauncherError $_.Exception.Message
    exit 1
}
