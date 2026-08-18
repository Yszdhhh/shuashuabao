$ErrorActionPreference = "SilentlyContinue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
# tools/ -> project root
# 导出对照用上游/旧版官方 GameScript 日志与配置到 docs/agent_shared_logs/official_raw
$root = Split-Path $PSScriptRoot -Parent
$dst = Join-Path $root "docs\agent_shared_logs"
$raw = Join-Path $dst "official_raw"
$exp = Join-Path $dst "exports"
New-Item -ItemType Directory -Force -Path $raw, $exp | Out-Null
$srcBase = Join-Path $env:LOCALAPPDATA "GameScript"
if (-not (Test-Path $srcBase)) { Write-Host "No $srcBase"; exit 1 }
Get-ChildItem $srcBase -Recurse -File | Where-Object { $_.Extension -match '\.log|\.png' } | ForEach-Object {
  $rel = $_.FullName.Substring($srcBase.Length).TrimStart('\') -replace '\\', '_'
  Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $raw $rel) -Force
  Write-Host "copy $rel"
}
$set = Join-Path $env:APPDATA "GameScript\Settings\Settings.json"
if (Test-Path $set) {
  Copy-Item $set (Join-Path $exp "Settings.latest.full.json") -Force
  # redacted via python if available
}
Write-Host "Done -> $dst\README.md"
