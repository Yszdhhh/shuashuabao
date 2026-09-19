# Test-only one-click entry for the pirate/necromancy GT session.
# It only prepares an isolated session and forwards arguments to the existing
# tools/live_scenario_capture.py. No production launcher, lnk, mediator,
# capture or baseline file is modified, and no second capture loop exists here.
#
#   -WhatIf / -PrepareOnly : real zero-input preparation (profile applied,
#                            session files written, command printed, nothing run)
#
# Emergency stop during a live run stays Shift+F12 (production harness key).

param(
    [switch]$WhatIf,
    [switch]$PrepareOnly
)

$ErrorActionPreference = "Stop"
$DryRun = $WhatIf -or $PrepareOnly

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONIOENCODING = "utf-8"

$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
Set-Location -LiteralPath $RepoRoot
$ToolPath = Join-Path $RepoRoot "tools\live_scenario_capture.py"
if (-not (Test-Path -LiteralPath $ToolPath -PathType Leaf)) {
    throw "找不到现有采集工具：$ToolPath"
}
$ProfileName = "海盗+亡灵机制GT"

# Real input needs elevation; preparation never does. Quote the script path and
# wait, so a path with spaces cannot make the parent report a false success.
if (-not $DryRun -and -not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "[one-click] 需要管理员权限做真实输入，正在请求 UAC..." -ForegroundColor Yellow
    $child = Start-Process -FilePath "powershell.exe" -Verb RunAs -Wait -PassThru -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ('"' + $PSCommandPath + '"')
    )
    exit [int]$child.ExitCode
}

function Resolve-PythonPath {
    $candidates = @((Join-Path $RepoRoot ".venv\Scripts\python.exe"))
    $workspaceRoot = Split-Path (Split-Path $RepoRoot -Parent) -Parent
    $candidates += (Join-Path $workspaceRoot "GameScript-Local\.venv\Scripts\python.exe")
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    return $null
}

function Resolve-OcrPython {
    $candidates = @()
    if ($env:SHUABAO_OCR_PYTHON) { $candidates += $env:SHUABAO_OCR_PYTHON }
    $candidates += (Join-Path $RepoRoot ".venv-ocr\Scripts\python.exe")
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
        $model = if ((Split-Path $candidate -Leaf) -eq "PP-OCRv5_mobile_rec_infer") { $candidate } else { Join-Path $candidate "PP-OCRv5_mobile_rec_infer" }
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

function Invoke-Git {
    param([Parameter(Mandatory = $true)][string[]]$GitArgs)

    $output = & git -C $RepoRoot @GitArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "git $($GitArgs -join ' ') 失败（exit $LASTEXITCODE）：$output"
    }
    return ($output | Out-String).Trim()
}

$PythonPath = Resolve-PythonPath
if (-not $PythonPath) { throw "找不到 Python。请先创建 .venv 或把 Python 置于 PATH。" }

# Production SHA is a constant, never Test HEAD. Test SHA is this worktree HEAD.
$ProductionSha = "b52c69e2aa1f74b59506439cceba06535bc6234c"
$TestSha = Invoke-Git @("rev-parse", "HEAD")
if ($TestSha -notmatch '^[0-9a-f]{40}$') { throw "无法确定候选 HEAD SHA：$TestSha" }
$SrcStatus = Invoke-Git @("status", "--porcelain", "--untracked-files=all", "--", "src/shuabao")
if ($SrcStatus) {
    throw "候选 src/shuabao 不干净，fail closed；请先提交或还原：`r`n$SrcStatus"
}

$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$SessionDir = Join-Path $RepoRoot ("captures\pirate_necromancy_" + $Stamp)
$BundleRoot = Join-Path $SessionDir "bundles"
$SettingsPath = Join-Path $SessionDir "settings.json"
New-Item -ItemType Directory -Path $SessionDir -Force | Out-Null
New-Item -ItemType Directory -Path $BundleRoot -Force | Out-Null

# Keep the operator app data root: shuabao.paths.live_lock_path() derives
# ShuaBao.live.lock from it, so an isolated root would let this run and the
# normal dashboard RunnerService send real input at the same time. Only the
# settings file is per-session, passed explicitly via --settings; the capture
# tool never writes user_settings.json, and the licence gate is untouched.
$AppData = if ($env:SHUABAO_APP_DATA -and $env:SHUABAO_APP_DATA.Trim()) {
    $env:SHUABAO_APP_DATA.Trim()
} else {
    Join-Path $env:LOCALAPPDATA "ShuaBao"
}
$env:SHUABAO_APP_DATA = $AppData
# Candidate source identity must be in the environment before any shuabao import.
Remove-Item Env:SHUABAO_PRODUCTION_SOURCE_ROOT -ErrorAction SilentlyContinue
Remove-Item Env:SHUABAO_PRODUCTION_SOURCE_SHA -ErrorAction SilentlyContinue
Remove-Item Env:SHUABAO_TEST_CANDIDATE_SHA -ErrorAction SilentlyContinue
Remove-Item Env:SHUABAO_CANDIDATE_SHA -ErrorAction SilentlyContinue
$env:SHUABAO_PRODUCTION_SOURCE_ROOT = $RepoRoot
$env:SHUABAO_PRODUCTION_SOURCE_SHA = $ProductionSha
$env:SHUABAO_TEST_CANDIDATE_SHA = $TestSha
$OcrPython = Resolve-OcrPython
$OcrModelDir = Resolve-OcrModelDir
if ($OcrPython) { $env:SHUABAO_OCR_PYTHON = $OcrPython }
if ($OcrModelDir) { $env:SHUABAO_OCR_MODEL_DIR = $OcrModelDir }

# 1-12 等关卡来自 Settings.stage_targets（测试方案），不是 CLI --target。
$CliArgs = @(
    "capture",
    "--target", "solo_ingame_chain",
    "--out", $BundleRoot,
    "--repo-root", $RepoRoot,
    "--production-source-root", $RepoRoot,
    "--production-source-sha", $ProductionSha,
    "--test-candidate-sha", $TestSha,
    "--duration", "3600",
    "--max-ticks", "30000",
    "--interval", "0.15",
    "--continue-after-failure",
    "--live-input",
    "--confirm-live-input",
    "--allow-dev-source",
    "--settings", $SettingsPath
)
$ArgvPath = Join-Path $SessionDir "argv.json"
$ArgvRecord = [ordered]@{
    python = $PythonPath
    tool = $ToolPath
    args = $CliArgs
    env = [ordered]@{
        SHUABAO_APP_DATA = $AppData
        SHUABAO_PRODUCTION_SOURCE_ROOT = $RepoRoot
        SHUABAO_PRODUCTION_SOURCE_SHA = $ProductionSha
        SHUABAO_TEST_CANDIDATE_SHA = $TestSha
        SHUABAO_OCR_PYTHON = $OcrPython
        SHUABAO_OCR_MODEL_DIR = $OcrModelDir
    }
}
[System.IO.File]::WriteAllText($ArgvPath, ($ArgvRecord | ConvertTo-Json -Depth 6), [System.Text.UTF8Encoding]::new($false))

# Preparation runs the real production Settings/profile code, never a copy of it.
$PrepareScript = @'
import hashlib
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

root = Path(sys.argv[1])
session = Path(sys.argv[2])
profile_name = sys.argv[3]
app_data = Path(sys.argv[4])
operator_app_data = Path(sys.argv[5])
head_sha = sys.argv[6]
sys.path.insert(0, str(root / "tools"))
sys.path.insert(0, str(root / "src"))
from gt_test_identity import build_session_evidence
from shuabao.settings import Settings
from shuabao.shell.test_profiles import apply_profile, load_test_profiles

operator_path = None
for candidate in (app_data / "user_settings.json", operator_app_data / "user_settings.json"):
    if candidate.is_file():
        operator_path = candidate
        break
if operator_path is None:
    default_path = root / "config" / "default_settings.json"
    operator_path = default_path if default_path.is_file() else None

base = Settings.load(operator_path) if operator_path is not None else Settings()
profiles = load_test_profiles(root / "config" / "dashboard_test_profiles.json")
document = next((item for item in profiles if item["name"] == profile_name), None)
if document is None:
    raise SystemExit(f"内置测试方案缺失：{profile_name}")
settings = apply_profile(base, document)
settings.dry_run = False
# 若 profile 显式声明 auto_devour_dan，则遵循 profile 配置；否则默认 False 保留人工 GT
if "auto_devour_dan" in document.get("settings", {}):
    settings.auto_devour_dan = bool(document["settings"]["auto_devour_dan"])
else:
    settings.auto_devour_dan = False

settings_path = session / "settings.json"
payload = json.dumps(asdict(settings), ensure_ascii=False, indent=2)
settings_path.write_text(payload, encoding="utf-8")
invocation = json.loads((session / "argv.json").read_text(encoding="utf-8"))

manifest = {
    "session_schema_version": 1,
    "created_at": datetime.now().isoformat(timespec="seconds"),
    "test_only": True,
    "candidate_root": str(root),
    "candidate_head_sha": head_sha,
    "test_sha": head_sha,
    "profile_name": profile_name,
    "profile_settings": document["settings"],
    "operator_settings_source": str(operator_path) if operator_path else None,
    "app_data": str(app_data),
    "settings_path": str(settings_path),
    "settings_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    "invocation": invocation,
    "stage_targets": list(settings.stage_targets or []),
    "cycle_num": settings.cycle_num,
    "auto_secret_realm": bool(settings.auto_secret_realm),
    "auto_devour_dan": bool(settings.auto_devour_dan),
    "bond_advanced_unlock_s": settings.bond_advanced_unlock_s,
    "cards": list(settings.cards or []),
    "bonds": list(settings.bonds or []),
    "bond_must_take": list(settings.bond_must_take or []),
    "manual_gt_notes": [
        "普通丹随机伤害身份 protected：auto_devour_dan=false，本次运行不能自动证实丹身份，丹路线是 MANUAL_GT。",
        "海盗/亡灵机制是否真正闭环不由本次接线证明；未自然出现的面板只记 NOT_OBSERVED。",
    ],
}
evidence = build_session_evidence(
    repo_root=root,
    python_executable=sys.executable,
    settings_path=settings_path,
    operator_settings_source=operator_path,
    profile_name=profile_name,
    profile_config_path=root / "config" / "dashboard_test_profiles.json",
    ocr_python=os.environ.get("SHUABAO_OCR_PYTHON"),
    ocr_model_dir=os.environ.get("SHUABAO_OCR_MODEL_DIR"),
    expected_test_sha=head_sha,
)
manifest.update(evidence)
manifest["candidate_head_sha"] = head_sha
manifest["test_sha"] = evidence.get("test_sha") or head_sha
(session / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
print("SESSION=" + str(session))
print("SETTINGS=" + str(settings_path))
print("HEAD=" + head_sha)
print("TEST=" + str(manifest.get("test_sha") or head_sha))
print("PROD=" + str(manifest.get("production_sha") or ""))
if evidence.get("status") != "READY" or evidence.get("cannot_start_gt"):
    sys.exit(1)
'@

$OperatorAppData = Join-Path $env:LOCALAPPDATA "ShuaBao"
Write-Host "[one-click] 准备隔离会话：$SessionDir" -ForegroundColor Cyan
$prepareOutput = $PrepareScript | & $PythonPath - $RepoRoot $SessionDir $ProfileName $AppData $OperatorAppData $TestSha
if ($LASTEXITCODE -ne 0) { throw "会话准备失败（exit $LASTEXITCODE）。" }
$prepareOutput | ForEach-Object { Write-Host "[prepare] $_" -ForegroundColor DarkGray }
if (-not (Test-Path -LiteralPath $SettingsPath -PathType Leaf)) { throw "会话准备未写出 settings：$SettingsPath" }

$commandText = "`"$PythonPath`" `"$ToolPath`" " + (($CliArgs | ForEach-Object { if ($_ -match "\s") { "`"$_`"" } else { $_ } }) -join " ")
Write-Host "[one-click] candidate root=$RepoRoot production=$ProductionSha test=$TestSha src=clean" -ForegroundColor DarkGray
Write-Host "[one-click] SHUABAO_APP_DATA=$AppData" -ForegroundColor DarkGray
Write-Host "[one-click] 即将执行：" -ForegroundColor DarkGray
Write-Host "  $commandText" -ForegroundColor DarkGray

if ($DryRun) {
    Write-Host "[one-click] -WhatIf/-PrepareOnly：零输入准备完成，未启动任何运行。" -ForegroundColor Green
    Write-Host "[one-click] 会话文件：$SessionDir\settings.json / manifest.json / argv.json" -ForegroundColor Green
    return
}

$LogPath = Join-Path $SessionDir "run.log"
Write-Host "[one-click] 把游戏停在英雄三国地图页/建房弹窗/房间/选关页，然后不要再碰鼠标键盘。" -ForegroundColor Cyan
Write-Host "[one-click] 紧急停止：Shift+F12。p=PASS f=FAIL m=MANUAL_INTERVENTION 只记录证据。" -ForegroundColor Cyan
Write-Host "[one-click] 日志：$LogPath" -ForegroundColor Cyan
# PS 5.1 turns native stderr lines into NativeCommandError records; with
# $ErrorActionPreference=Stop that aborts the capture at the first stderr line
# (e.g. the ocr worker banner) and hides the real exit code.  Keep stderr as
# plain text for this call only, and write the log as UTF-8 (Tee-Object on
# 5.1 has no -Encoding and emits UTF-16).
$env:PYTHONUNBUFFERED = "1"
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText($LogPath, "", $utf8NoBom)
$previousEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    & $PythonPath $ToolPath @CliArgs 2>&1 | ForEach-Object {
        $line = if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.ToString() } else { [string]$_ }
        Write-Host $line
        [System.IO.File]::AppendAllText($LogPath, $line + [Environment]::NewLine, $utf8NoBom)
    }
    $exitCode = [int]$LASTEXITCODE
} finally {
    $ErrorActionPreference = $previousEap
}
Write-Host "[one-click] tool exit code: $exitCode" -ForegroundColor DarkGray
Write-Host "[one-click] bundle 目录：$BundleRoot（子目录 solo_ingame_chain_<时间戳>）" -ForegroundColor Cyan
Write-Host "[one-click] 会话证据：$SessionDir" -ForegroundColor Cyan
exit $exitCode
