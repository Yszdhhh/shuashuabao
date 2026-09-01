# 刷刷宝打包脚本：构建 exe → 部署到桌面 → 建/更新桌面快捷方式。
#
# 版本命名：用户可见为「刷刷宝 V0.1」；文件夹用 ASCII「ShuaBao-V0.1」。
# 打包前强制过发版门禁（tools/release_gate.py）。要跳过请显式加 -SkipGate，
# 并自己清楚为什么——门禁红着发版正是 8-12 连出两个紧急修复的原因。
param(
    [switch]$SkipGate,
    [switch]$NoDeploy,
    [switch]$AllowDirty,
    [string]$SubscriptionBaseUrl = "",
    [ValidateSet("off", "shadow", "enforce")]
    [string]$SubscriptionMode = "enforce"
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$APP_NAME = "刷刷宝"
$APP_ID   = "ShuaBao"

$sourceSha = (& git rev-parse HEAD).Trim()
if (-not $sourceSha) {
    throw "无法解析当前 Git 提交，拒绝构建。"
}
$initialDirtyEntries = @(& git status --porcelain --untracked-files=all)
if ($initialDirtyEntries.Count -gt 0 -and -not $AllowDirty) {
    throw "工作区存在未提交修改，拒绝生成正式包；如需仅用于本地诊断，请显式使用 -AllowDirty。"
}

function Get-ReleaseFileSha256([string]$Path) {
    # Get-FileHash was added after the oldest Windows PowerShell supported by
    # the release launcher.  Use the .NET primitive so packaging can deploy
    # from either Windows PowerShell or PowerShell 7.
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

$uvCommand = Get-Command uv -ErrorAction Stop
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    & $uvCommand.Source venv --python 3.11 .venv
    if ($LASTEXITCODE -ne 0) { throw "创建主程序虚拟环境失败。" }
}

& $uvCommand.Source pip install --python $python -r requirements-desktop.txt -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw "主程序依赖安装失败。" }

# Node 只用于构建期；先锁定依赖并重新生成 Web 静态产物，避免把陈旧 dist 打进包。
$npm = Get-Command npm -ErrorAction Stop
Push-Location -LiteralPath (Join-Path $PSScriptRoot "ui-v2")
try {
    & $npm.Source ci
    if ($LASTEXITCODE -ne 0) { throw "ui-v2 npm ci 失败。" }
    & $npm.Source run build
    if ($LASTEXITCODE -ne 0) { throw "ui-v2 npm run build 失败。" }
}
finally {
    Pop-Location
}

# Record the exact source revision that produced the Web bundle.  The bundle
# itself is intentionally ignored by git, so this sidecar is the runtime
# handshake that prevents a stale ui-v2/dist from being silently packaged.
$uiDist = Join-Path $PSScriptRoot "ui-v2\dist"
$uiIndex = Join-Path $uiDist "index.html"
if (-not (Test-Path -LiteralPath $uiIndex -PathType Leaf)) {
    throw "UI 构建完成但缺少 ui-v2/dist/index.html"
}
$uiManifest = [ordered]@{
    schema_version       = 1
    source_sha           = $sourceSha
    source_tree_clean    = $true
    index_sha256         = Get-ReleaseFileSha256 $uiIndex
    bridge_schema_version = 2
    generated_at_utc     = [DateTime]::UtcNow.ToString("o")
}
$uiManifest | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath (Join-Path $uiDist "build_manifest.json") -Encoding utf8
Write-Host "已写入 UI 构建清单：$uiDist\build_manifest.json" -ForegroundColor DarkGray

Write-Host "[0/4] 准备并校验 OCR 模型 ..." -ForegroundColor Cyan
& $python tools\prepare_ocr_model.py
if ($LASTEXITCODE -ne 0) { throw "OCR 模型准备/校验失败，已中止打包。" }

if (-not $SkipGate) {
    Write-Host "[1/4] 发版门禁 ..." -ForegroundColor Cyan
    # 用开发环境跑门禁：.venv 只装了打包依赖（PySide6 + PyInstaller），
    # 没有 pytest/opencv，拿它跑会得到"0 passed"这种假失败。
    $gatePython = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $gatePython) {
        throw "PATH 上没有 python，无法跑门禁。装好开发环境，或明确知道后果时用 -SkipGate。"
    }
    & $gatePython tools\release_gate.py
    if ($LASTEXITCODE -ne 0) {
        throw "门禁未通过，已中止打包。修好再来，或明确知道后果时用 -SkipGate。"
    }
}

Write-Host "[2/4] PyInstaller 打包主程序 ..." -ForegroundColor Cyan
& $python -m PyInstaller --noconfirm --clean "$APP_ID.spec"
if ($LASTEXITCODE -ne 0) { throw "主程序打包失败。" }

$app = Join-Path $PSScriptRoot "dist\$APP_ID\$APP_ID.exe"
if (-not (Test-Path -LiteralPath $app)) {
    throw "构建结束但没有生成 $app"
}
Write-Host "已生成：$app" -ForegroundColor Green

# OCR 在独立进程运行，避免主界面加载 Paddle 的大体积二进制；但正式发行包必须
# 连同 worker、依赖和已校验模型一并交付，不能在冻结版静默降级为模板模式。
$ocrPython = Join-Path $PSScriptRoot ".venv-ocr\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $ocrPython)) {
    & $uvCommand.Source venv --python 3.11 .venv-ocr
    if ($LASTEXITCODE -ne 0) { throw "创建 OCR 虚拟环境失败。" }
}
& $uvCommand.Source pip sync --python $ocrPython requirements-ocr.lock
if ($LASTEXITCODE -ne 0) { throw "OCR 依赖安装失败。" }

Write-Host "[3/4] PyInstaller 打包 OCR worker 和模型 ..." -ForegroundColor Cyan
& $ocrPython -m PyInstaller --noconfirm --clean "ShuaBaoOCR.spec"
if ($LASTEXITCODE -ne 0) { throw "OCR worker 打包失败。" }
$ocrWorker = Join-Path $PSScriptRoot "dist\ShuaBaoOCR\ShuaBaoOCR.exe"
if (-not (Test-Path -LiteralPath $ocrWorker)) {
    throw "OCR worker 构建结束但没有生成 $ocrWorker"
}
$workerTarget = Join-Path $PSScriptRoot "dist\$APP_ID\vision"
cmd.exe /c "robocopy `"$(Split-Path -Parent $ocrWorker)`" `"$workerTarget`" /E /NJH /NJS /NFL /NDL & if %ERRORLEVEL% LEQ 7 (exit /b 0) else (exit /b %ERRORLEVEL%)" | Out-Null
if ($LASTEXITCODE -gt 7) { throw "复制 OCR worker 到发行目录失败。" }
Write-Host "已生成：$ocrWorker" -ForegroundColor Green

$releaseRoot = Join-Path $PSScriptRoot "dist\$APP_ID"

# Pin the non-secret subscription deployment settings beside the executable.
# A clean shortcut launch must not depend on the shell that happened to build
# the package.  License material is deliberately absent; it remains DPAPI/env
# only.  Remote endpoints must use HTTPS, while HTTP is limited to loopback.
$subscriptionUrl = if ($SubscriptionBaseUrl.Trim()) { $SubscriptionBaseUrl.Trim() } else { "http://127.0.0.1:8000" }
try {
    $parsedSubscriptionUrl = [Uri]$subscriptionUrl
    $loopbackHosts = @("127.0.0.1", "localhost", "::1")
    if (-not $parsedSubscriptionUrl.IsAbsoluteUri -or
        [string]::IsNullOrWhiteSpace($parsedSubscriptionUrl.Host) -or
        $parsedSubscriptionUrl.UserInfo -or
        ($parsedSubscriptionUrl.Scheme -eq "http" -and $loopbackHosts -notcontains $parsedSubscriptionUrl.Host.ToLowerInvariant()) -or
        ($parsedSubscriptionUrl.Scheme -notin @("http", "https"))) {
        throw "订阅服务地址必须使用 HTTPS 或 loopback HTTP，且不得包含凭据。"
    }
}
catch {
    throw "SubscriptionBaseUrl 无效：$($_.Exception.Message)"
}
$subscriptionRuntimePath = Join-Path $releaseRoot "subscription_runtime.json"
$subscriptionRuntime = [ordered]@{
    schema_version = 1
    base_url = $subscriptionUrl.TrimEnd("/")
    mode = $SubscriptionMode
    timeout_s = 3
}
$subscriptionRuntime | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $subscriptionRuntimePath -Encoding utf8
Write-Host "已写入订阅部署配置（不含卡密）：$subscriptionRuntimePath" -ForegroundColor DarkGray

# A live-input capture refuses to run unless the checked-out source commit,
# the packaged EXE and this sidecar agree. A version label alone is not a
# build identity. Keep the sidecar beside ShuaBao.exe so robocopy deployment
# carries the exact proof with the release.
$sourceDirtyEntries = @(& git status --porcelain --untracked-files=all)
$buildId = (& $python -c "import sys; sys.path.insert(0, 'src'); from shuabao.mediator import BUILD_ID; print(BUILD_ID)").Trim()
$releaseManifestPath = Join-Path $releaseRoot "release_manifest.json"
$releasePrefix = "$releaseRoot\"
$releaseEntries = @(
    Get-ChildItem -LiteralPath $releaseRoot -File -Recurse |
        Where-Object {
            $_.FullName -ne $releaseManifestPath -and
            $_.FullName -ne (Join-Path $releaseRoot "build_identity.json")
        } |
        ForEach-Object {
            [ordered]@{
                path = $_.FullName.Substring($releasePrefix.Length).Replace("\", "/")
                size_bytes = [int64]$_.Length
                sha256 = Get-ReleaseFileSha256 $_.FullName
            }
        }
)
$releaseManifest = [ordered]@{
    schema_version = 1
    source_sha = $sourceSha
    bridge_schema_version = 2
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    files = @($releaseEntries)
}
$releaseManifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $releaseManifestPath -Encoding utf8
$identity = [ordered]@{
    schema_version     = 1
    source_sha         = $sourceSha
    source_tree_clean  = ($sourceDirtyEntries.Count -eq 0)
    build_id           = $buildId
    exe_name           = (Split-Path -Leaf $app)
    exe_sha256         = Get-ReleaseFileSha256 $app
    bridge_schema_version = 2
    release_manifest_sha256 = Get-ReleaseFileSha256 $releaseManifestPath
    created_at_utc     = [DateTime]::UtcNow.ToString("o")
}
$identityPath = Join-Path (Split-Path -Parent $app) "build_identity.json"
$identity | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $identityPath -Encoding utf8
Write-Host "已写入构建身份：$identityPath" -ForegroundColor Green

if ($NoDeploy) { return }

Write-Host "[4/4] 部署到桌面并更新快捷方式 ..." -ForegroundColor Cyan
$version = (& $python -c "import sys; sys.path.insert(0,'src'); import shuabao; print(shuabao.__version__)").Trim()
$versionLabel = "V$version"
$desktop = [Environment]::GetFolderPath("Desktop")
$target  = Join-Path $desktop "$APP_ID"
$archive = Join-Path $desktop "$APP_NAME-旧版归档"
# 归档桌面上旧版目录（ShuaBao-* / 历史 GameScript-*），只留当前这一份
if (-not (Test-Path -LiteralPath $archive)) {
    New-Item -ItemType Directory -Path $archive | Out-Null
}
Get-ChildItem -LiteralPath $desktop -Directory -ErrorAction SilentlyContinue |
    Where-Object {
        ($_.Name -like "$APP_ID-*" -or $_.Name -like "GameScript-*") -and
        ($_.FullName -ne $target)
    } |
    ForEach-Object {
        $dest = Join-Path $archive $_.Name
        if (Test-Path -LiteralPath $dest) {
            Remove-Item -LiteralPath $dest -Recurse -Force
        }
        Move-Item -LiteralPath $_.FullName -Destination $dest -Force
        Write-Host "已归档：$($_.Name)" -ForegroundColor DarkYellow
    }

$srcDist = Join-Path $PSScriptRoot "dist\$APP_ID"
cmd.exe /c "robocopy `"$srcDist`" `"$target`" /MIR /NJH /NJS /NFL /NDL & if %ERRORLEVEL% LEQ 7 (exit /b 0) else (exit /b %ERRORLEVEL%)" | Out-Null
if ($LASTEXITCODE -gt 7) { throw "部署发行目录失败。" }

# Post-copy proof: the shortcut target must contain the exact sidecars emitted
# above. A partial or stale robocopy result is never accepted as a release.
$deployedIdentityPath = Join-Path $target "build_identity.json"
$deployedManifestPath = Join-Path $target "release_manifest.json"
if (-not (Test-Path -LiteralPath $deployedIdentityPath) -or
    -not (Test-Path -LiteralPath $deployedManifestPath)) {
    throw "部署目录缺少 build_identity.json 或 release_manifest.json。"
}
$deployedIdentity = Get-Content -LiteralPath $deployedIdentityPath -Raw | ConvertFrom-Json
if ($deployedIdentity.source_sha -ne $sourceSha -or
    $deployedIdentity.release_manifest_sha256 -ne (Get-ReleaseFileSha256 $deployedManifestPath) -or
    $deployedIdentity.source_tree_clean -ne $true) {
    throw "部署后的构建身份校验失败，拒绝更新快捷方式。"
}
$deployedManifest = Get-Content -LiteralPath $deployedManifestPath -Raw | ConvertFrom-Json
foreach ($entry in @($deployedManifest.files)) {
    $deployedFile = Join-Path $target (([string]$entry.path).Replace("/", "\"))
    if (-not (Test-Path -LiteralPath $deployedFile -PathType Leaf) -or
        (Get-ReleaseFileSha256 $deployedFile) -ne ([string]$entry.sha256).ToLowerInvariant()) {
        throw "部署文件哈希校验失败：$($entry.path)"
    }
}

# 统一桌面单一入口快捷方式：「刷刷宝.lnk」；归档旧版本快捷方式与看板快捷方式
$lnkName = "$APP_NAME.lnk"
$lnk = Join-Path $desktop $lnkName
Get-ChildItem -LiteralPath $desktop -Filter "*.lnk" -ErrorAction SilentlyContinue |
    Where-Object {
        $_.Name -eq "刷刷宝看板.lnk" -or
        $_.Name -like "$APP_NAME V*.lnk" -or
        $_.Name -like "GameScript*.lnk"
    } |
    ForEach-Object {
        $dest = Join-Path $archive $_.Name
        Move-Item -LiteralPath $_.FullName -Destination $dest -Force
        Write-Host "已归档旧快捷方式：$($_.Name)" -ForegroundColor DarkYellow
    }
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($lnk)
$shortcut.TargetPath = Join-Path $target "$APP_ID.exe"
$shortcut.Arguments = ""
$shortcut.WorkingDirectory = $target
$shortcut.Description = "$APP_NAME $versionLabel · 重生魔兽刷刷刷单人挂机助手"
$shortcut.Save()

Write-Host "已部署：$target" -ForegroundColor Green
Write-Host "快捷方式：$lnk" -ForegroundColor Green
Write-Host "提示：需要真实点击时请右键快捷方式以管理员身份运行。" -ForegroundColor Yellow
