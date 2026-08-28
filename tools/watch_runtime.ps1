# Watch runtime: process, log lines, pngs, settings
# $local  = 原版 C# 程序的运行目录（%LocalAppData%\GameScript），用于对照官方行为
# $roam   = 原版官方 Settings.json
# 本项目（刷刷宝）自己的数据在 %LocalAppData%\ShuaBao
$ErrorActionPreference = "SilentlyContinue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$local = Join-Path $env:LOCALAPPDATA "GameScript"
$roam = Join-Path $env:APPDATA "GameScript\Settings\Settings.json"
$repoRoot = Split-Path -Parent $PSScriptRoot
$sampleRoot = Join-Path $repoRoot "docs\runtime_sample"
$metaDir = Get-ChildItem $sampleRoot -Directory -ErrorAction SilentlyContinue |
  Where-Object { $_.Name -like "session_*" } |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1
if (-not $metaDir) {
  $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
  $out = Join-Path $sampleRoot "session_$stamp"
  New-Item -ItemType Directory -Force -Path $out | Out-Null
} else {
  $out = $metaDir.FullName
}

$seenProc = @{}
$seenPng = @{}
$logLineCounts = @{}
$lastSettingsHash = ""
if (Test-Path $roam) {
  $lastSettingsHash = (Get-FileHash -LiteralPath $roam -Algorithm SHA256).Hash
}

$deadline = (Get-Date).AddHours(2)
Write-Output "WATCH_START out=$out t=$((Get-Date).ToString('o'))"

while ((Get-Date) -lt $deadline) {
  # process
  $procs = @(Get-Process -Name "GameScript" -ErrorAction SilentlyContinue)
  $alive = @{}
  foreach ($p in $procs) {
    $alive[$p.Id] = $true
    if (-not $seenProc.ContainsKey([string]$p.Id)) {
      $seenProc[[string]$p.Id] = $true
      Write-Output "PROC_START id=$($p.Id) start=$($p.StartTime)"
    }
  }
  foreach ($id in @($seenProc.Keys)) {
    if (-not $alive.ContainsKey([int]$id) -and -not $seenProc.ContainsKey("end-$id")) {
      $seenProc["end-$id"] = $true
      Write-Output "PROC_END id=$id t=$((Get-Date).ToString('HH:mm:ss'))"
    }
  }

  # settings
  if (Test-Path -LiteralPath $roam) {
    $h = (Get-FileHash -LiteralPath $roam -Algorithm SHA256).Hash
    if ($h -ne $lastSettingsHash) {
      $lastSettingsHash = $h
      $dest = Join-Path $out ("Settings." + (Get-Date -Format "HHmmss") + ".json")
      Copy-Item -LiteralPath $roam -Destination $dest -Force
      Write-Output "SETTINGS_CHANGE file=$dest"
    }
  }

  # pngs
  if (Test-Path -LiteralPath $local) {
    Get-ChildItem -LiteralPath $local -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object {
      if ($_.Extension -match '\.png|\.jpg') {
        $sig = "$($_.FullName)|$($_.Length)|$($_.LastWriteTime.Ticks)"
        if (-not $seenPng.ContainsKey($sig)) {
          $seenPng[$sig] = $true
          Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $out $_.Name) -Force
          Write-Output "PNG_NEW name=$($_.Name) len=$($_.Length)"
        }
      }
    }
  }

  # log incremental
  $day = Get-Date -Format "yyyyMMdd"
  $dayLog = Join-Path $local (Join-Path $day "log.log")
  if (Test-Path -LiteralPath $dayLog) {
    $lines = @(Get-Content -LiteralPath $dayLog -Encoding UTF8)
    $n = $lines.Count
    $key = $dayLog
    $prev = 0
    if ($logLineCounts.ContainsKey($key)) { $prev = [int]$logLineCounts[$key] }
    if ($n -gt $prev) {
      for ($i = $prev; $i -lt $n; $i++) {
        Write-Output ("LOG|" + $lines[$i])
      }
      $logLineCounts[$key] = $n
      Copy-Item -LiteralPath $dayLog -Destination (Join-Path $out "log_latest.log") -Force
    }
  }

  Start-Sleep -Seconds 2
}

Write-Output "WATCH_END timeout"
