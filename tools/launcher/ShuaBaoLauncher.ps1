# Stable ShuaBao entry. Reads current.json, checks identity, starts app-*\ShuaBao.exe.
# No subscription, FSM, updater, or remote control.
$ErrorActionPreference = "Stop"
$installRoot = $null

function Show-LaunchFailure([string]$Message) {
    try {
        Add-Type -AssemblyName System.Windows.Forms | Out-Null
        [System.Windows.Forms.MessageBox]::Show($Message, "刷刷宝启动失败", [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error) | Out-Null
    } catch {
        try {
            $wscript = New-Object -ComObject WScript.Shell
            $wscript.Popup($Message, 0, "刷刷宝启动失败", 16) | Out-Null
        } catch {
            Write-Error $Message
        }
    }
    exit 1
}

try {
    $launcherDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $installRoot = Split-Path -Parent $launcherDir
    $pointerPath = Join-Path $installRoot "current.json"
    if (-not (Test-Path -LiteralPath $pointerPath -PathType Leaf)) {
        Show-LaunchFailure "缺少 current.json：`n$pointerPath`n请重新运行发行安装。"
    }
    $utf8 = New-Object System.Text.UTF8Encoding $false
    $pointer = [System.IO.File]::ReadAllText($pointerPath, $utf8) | ConvertFrom-Json
    $dirName = [string]$pointer.current
    if (-not $dirName -or $dirName -notmatch '^app-[0-9]+(\.[0-9]+)*-(dev|internal-pilot|external-beta|release)-[0-9a-f]{12}$') {
        Show-LaunchFailure "current.json 中的版本目录非法：'$dirName'"
    }
    $appDir = Join-Path $installRoot $dirName
    $exe = Join-Path $appDir "ShuaBao.exe"
    $identityPath = Join-Path $appDir "build_identity.json"
    if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
        Show-LaunchFailure "当前版本缺少 ShuaBao.exe：`n$appDir"
    }
    if (-not (Test-Path -LiteralPath $identityPath -PathType Leaf)) {
        Show-LaunchFailure "当前版本缺少 build_identity.json：`n$appDir"
    }
    $identity = [System.IO.File]::ReadAllText($identityPath, $utf8) | ConvertFrom-Json
    $sourceSha = ([string]$identity.source_sha).ToLowerInvariant()
    $channel = [string]$identity.release_channel
    $manifestSha = ([string]$identity.release_manifest_sha256).ToLowerInvariant()
    $expectedSha = ([string]$pointer.current_source_sha).ToLowerInvariant()
    $expectedChannel = [string]$pointer.current_release_channel
    $expectedManifest = ([string]$pointer.current_release_manifest_sha256).ToLowerInvariant()
    if ($expectedSha -and $sourceSha -ne $expectedSha) {
        Show-LaunchFailure "目标目录 source_sha 与 current.json 不一致。`n目录：$appDir"
    }
    if ($expectedChannel -and $channel -ne $expectedChannel) {
        Show-LaunchFailure "目标目录 release_channel 与 current.json 不一致。`n目录：$appDir"
    }
    if ($expectedManifest -and $manifestSha -ne $expectedManifest) {
        Show-LaunchFailure "目标目录 manifest SHA 与 current.json 不一致。`n目录：$appDir"
    }
    if (-not $sourceSha -or -not $channel) {
        Show-LaunchFailure "build_identity.json 缺少 source_sha 或 release_channel。`n目录：$appDir"
    }
    Start-Process -FilePath $exe -WorkingDirectory $appDir | Out-Null
} catch {
    $detail = $_.Exception.Message
    if (-not $detail) { $detail = "$_" }
    Show-LaunchFailure "稳定入口无法启动当前版本。`n$detail"
}
