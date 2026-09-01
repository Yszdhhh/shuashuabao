# 开发桌面唯一入口：源码与 Web dist 不一致时先重建，再启动 Web 壳。
# 正式发行请使用 build_release.ps1；本脚本不部署、不改桌面快捷方式。
param(
    [switch]$SkipNpmCi
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

function Get-FileSha256([string]$Path) {
    $stream = [System.IO.File]::OpenRead($Path)
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([System.BitConverter]::ToString($sha256.ComputeHash($stream))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha256.Dispose()
        $stream.Dispose()
    }
}

function Write-Utf8NoBom([string]$Path, [string]$Content) {
    # Keep the development manifest readable by Python's strict UTF-8 JSON
    # loader when this script runs under Windows PowerShell 5.1.
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $utf8NoBom)
}

$sourceSha = (& git rev-parse HEAD).Trim()
if (-not $sourceSha) { throw "无法解析当前 Git 提交，拒绝启动开发壳。" }

$dist = Join-Path $PSScriptRoot "ui-v2\dist"
$index = Join-Path $dist "index.html"
$manifestPath = Join-Path $dist "build_manifest.json"
$repoDirty = @(& git status --porcelain --untracked-files=all)
$needsBuild = -not (Test-Path -LiteralPath $index -PathType Leaf) -or
    -not (Test-Path -LiteralPath $manifestPath -PathType Leaf) -or
    $repoDirty.Count -gt 0
if (-not $needsBuild) {
    try {
        $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
        $needsBuild = $manifest.schema_version -ne 1 -or
            $manifest.source_sha -ne $sourceSha -or
            ($repoDirty.Count -eq 0 -and $manifest.source_tree_clean -ne $true) -or
            $manifest.bridge_schema_version -ne 2 -or
            $manifest.index_sha256 -ne (Get-FileSha256 $index)
    }
    catch {
        $needsBuild = $true
    }
}

if ($needsBuild) {
    $npm = Get-Command npm -ErrorAction Stop
    Push-Location (Join-Path $PSScriptRoot "ui-v2")
    try {
        if (-not $SkipNpmCi -and -not (Test-Path -LiteralPath "node_modules" -PathType Container)) {
            & $npm.Source ci
            if ($LASTEXITCODE -ne 0) { throw "ui-v2 npm ci 失败。" }
        }
        & $npm.Source run build
        if ($LASTEXITCODE -ne 0) { throw "ui-v2 npm run build 失败。" }
    }
    finally {
        Pop-Location
    }
    $manifest = [ordered]@{
        schema_version = 1
        source_sha = $sourceSha
        # The bundle is a development artifact whenever *any* source file is
        # dirty, not only the UI files.  Marking this true for a mediator-only
        # edit would make WebShell reject the freshly rebuilt dist as a
        # supposedly clean manifest.
        source_tree_clean = ($repoDirty.Count -eq 0)
        index_sha256 = Get-FileSha256 $index
        bridge_schema_version = 2
        generated_at_utc = [DateTime]::UtcNow.ToString("o")
    }
    $manifestJson = $manifest | ConvertTo-Json -Depth 3
    Write-Utf8NoBom $manifestPath $manifestJson
    Write-Host "[dev] UI dist 已按 source_sha=$sourceSha 重建。" -ForegroundColor Green
}

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    $python = (Get-Command python -ErrorAction Stop).Source
}
$env:SHUABAO_SHELL = "web"
& $python (Join-Path $PSScriptRoot "desktop_app.py")
exit $LASTEXITCODE
