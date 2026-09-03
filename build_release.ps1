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
    [string]$SubscriptionMode = "enforce",
    [ValidateSet("dev", "internal-pilot", "external-beta", "release")]
    [string]$ReleaseChannel = "dev",
    [string]$ManifestSigningKeyPath = "",
    [string]$ManifestSigningKeyId = "",
    [string]$AuthenticodeCertificateThumbprint = "",
    [string]$AuthenticodeTimestampUrl = "",
    [string]$SignToolPath = ""
)
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

# 渠道门禁：external-beta/release 是对外发包，所有宽松逃生口一律封死。
$isExternalChannel = $ReleaseChannel -in @("external-beta", "release")
if ($isExternalChannel) {
    if ($SkipGate) { throw "external-beta/release 渠道禁止 -SkipGate：外发包必须通过完整发版门禁。" }
    if ($AllowDirty) { throw "external-beta/release 渠道禁止 -AllowDirty：外发包必须来自干净源码树。" }
    if ($SubscriptionMode -ne "enforce") { throw "external-beta/release 渠道要求 -SubscriptionMode enforce。" }
}

# 订阅地址在构建前统一解析并校验：外发渠道必须显式传 HTTPS 生产地址，
# 绝不静默回落 loopback；dev/internal-pilot 保留 loopback 默认值方便联调。
$subscriptionUrlInput = $SubscriptionBaseUrl.Trim()
if (-not $subscriptionUrlInput -and -not $isExternalChannel) {
    $subscriptionUrlInput = [string]$env:SHUABAO_SUBSCRIPTION_BASE_URL
}
function Test-HostIsLoopback([string]$UrlHost) {
    # 按地址语义判定整个回环段：127.0.0.0/8、::1 —— 精确主机名列表会漏掉
    # 127.0.0.2 这类同段地址。非 IP 主机名（如 localhost 的 FQDN 尾点形式
    # "localhost."、大小写变体）先归一化：TrimEnd('.') + ToLowerInvariant。
    $normalizedHost = $UrlHost.TrimEnd('.').ToLowerInvariant()
    if ($normalizedHost -eq "localhost") { return $true }
    $ip = $null
    if ([System.Net.IPAddress]::TryParse($normalizedHost.Trim("[]"), [ref]$ip)) {
        return [System.Net.IPAddress]::IsLoopback($ip)
    }
    return $false
}
if ($isExternalChannel) {
    if (-not $subscriptionUrlInput) {
        throw "external-beta/release 渠道必须显式传入 -SubscriptionBaseUrl，禁止静默回落 loopback 默认值。"
    }
    $parsedSubscriptionUrl = $null
    try { $parsedSubscriptionUrl = [Uri]$subscriptionUrlInput } catch { $parsedSubscriptionUrl = $null }
    if (-not $parsedSubscriptionUrl -or
        -not $parsedSubscriptionUrl.IsAbsoluteUri -or
        $parsedSubscriptionUrl.Scheme -ne "https" -or
        [string]::IsNullOrWhiteSpace($parsedSubscriptionUrl.Host) -or
        $parsedSubscriptionUrl.UserInfo -or
        (Test-HostIsLoopback $parsedSubscriptionUrl.Host)) {
        throw "external-beta/release 订阅地址必须为显式 HTTPS，禁止 loopback、空地址与凭据。"
    }
    $subscriptionUrl = $subscriptionUrlInput
}

else {
    $loopbackHosts = @("127.0.0.1", "localhost", "::1", "[::1]")
    $subscriptionUrl = if ($subscriptionUrlInput) { $subscriptionUrlInput } else { "http://127.0.0.1:8000" }
    try {
        $parsedSubscriptionUrl = [Uri]$subscriptionUrl
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
}

$APP_NAME = "刷刷宝"
$APP_ID   = "ShuaBao"

$sourceSha = (& git rev-parse HEAD).Trim()
if (-not $sourceSha) {
    throw "无法解析当前 Git 提交，拒绝构建。"
}
$initialDirtyEntries = @(& git status --porcelain --untracked-files=all)
$initialTrackedDirtyEntries = @(& git status --porcelain --untracked-files=no)
if ($initialDirtyEntries.Count -gt 0 -and -not $AllowDirty) {
    throw "工作区存在未提交修改，拒绝生成正式包；如需仅用于本地诊断，请显式使用 -AllowDirty。"
}
function Resolve-SignTool {
    $command = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $roots = @(
        (Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"),
        (Join-Path $env:ProgramFiles "Windows Kits\10\bin")
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Container) }
    $candidate = Get-ChildItem -Path $roots -Filter "signtool.exe" -File -Recurse -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1
    if ($candidate) { return $candidate.FullName }
    return $null
}

if ($isExternalChannel) {
    $manifestKeyPath = $ManifestSigningKeyPath.Trim()
    if (-not $manifestKeyPath) { $manifestKeyPath = $env:SHUABAO_MANIFEST_SIGNING_KEY_PATH }
    if (-not $manifestKeyPath) { $manifestKeyPath = $env:SHUABAO_MANIFEST_SIGNING_KEY }
    $manifestKeyId = if ($ManifestSigningKeyId.Trim()) { $ManifestSigningKeyId.Trim() } else { $env:SHUABAO_MANIFEST_SIGNING_KEY_ID }
    $certThumbprint = if ($AuthenticodeCertificateThumbprint.Trim()) {
        $AuthenticodeCertificateThumbprint.Trim().Replace(" ", "")
    } else {
        [string]$env:SHUABAO_AUTHENTICODE_CERT_THUMBPRINT
    }
    $timestampUrl = if ($AuthenticodeTimestampUrl.Trim()) {
        $AuthenticodeTimestampUrl.Trim()
    } elseif ($env:SHUABAO_AUTHENTICODE_TIMESTAMP_URL) {
        $env:SHUABAO_AUTHENTICODE_TIMESTAMP_URL
    } else {
        $env:SHUABAO_TIMESTAMP_URL
    }
    if (-not $manifestKeyPath -or -not (Test-Path -LiteralPath $manifestKeyPath -PathType Leaf)) {
        throw "external-beta/release 渠道缺少真实 Ed25519 manifest 私钥路径（-ManifestSigningKeyPath 或 SHUABAO_MANIFEST_SIGNING_KEY_PATH），请由操作员提供。"
    }
    $manifestKeyPath = (Resolve-Path -LiteralPath $manifestKeyPath).Path
    # 私钥绝不能随源码/打包目录泄露：拒绝仓库根及其 build/dist/assets/src/config/ui-v2
    # 子路径。本检查必须发生在任何构建副作用之前。
    $repoRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
    $forbiddenKeyRoots = @(
        $repoRoot,
        (Join-Path $repoRoot "build"),
        (Join-Path $repoRoot "dist"),
        (Join-Path $repoRoot "assets"),
        (Join-Path $repoRoot "src"),
        (Join-Path $repoRoot "config"),
        (Join-Path $repoRoot "ui-v2")
    )
    $keySeparator = [System.IO.Path]::DirectorySeparatorChar
    foreach ($forbiddenKeyRoot in $forbiddenKeyRoots) {
        if ($manifestKeyPath -eq $forbiddenKeyRoot -or
            $manifestKeyPath.StartsWith($forbiddenKeyRoot + $keySeparator, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "external-beta/release 渠道 manifest 私钥不得位于仓库根或其 build/dist/assets/src/config/ui-v2 子路径内：$manifestKeyPath。请将私钥迁移到仓库外的受保护位置。"
        }
    }
    if (-not $manifestKeyId) {
        throw "external-beta/release 渠道缺少 manifest key id（-ManifestSigningKeyId 或 SHUABAO_MANIFEST_SIGNING_KEY_ID），请由操作员提供。"
    }
    if ($certThumbprint -notmatch "^[0-9A-Fa-f]{40}$") {
        throw "external-beta/release 渠道缺少真实 Authenticode 证书 thumbprint，请由操作员提供。"
    }
    # Regex 只能证明格式，不能证明证书真实存在且可用：必须在构建前确认
    # CurrentUser/LocalMachine 个人存储中有该 thumbprint 且证书带私钥。
    $signingCert = $null
    foreach ($store in @("Cert:\CurrentUser\My", "Cert:\LocalMachine\My")) {
        if (Test-Path -LiteralPath $store) {
            $signingCert = Get-ChildItem -LiteralPath $store -ErrorAction SilentlyContinue |
                Where-Object { $_.Thumbprint -eq $certThumbprint -and $_.HasPrivateKey } |
                Select-Object -First 1
            if ($signingCert) { break }
        }
    }
    if (-not $signingCert) {
        throw "external-beta/release 渠道找不到 thumbprint=$certThumbprint 的 Authenticode 证书（或其无私钥），请由操作员导入真实证书。"
    }
    $parsedTimestamp = $null
    try { $parsedTimestamp = [Uri]$timestampUrl } catch { $parsedTimestamp = $null }
    if (-not $parsedTimestamp -or -not $parsedTimestamp.IsAbsoluteUri -or $parsedTimestamp.Scheme -ne "https") {
        throw "external-beta/release 渠道缺少有效 RFC3161 HTTPS timestamp URL，请由操作员提供。"
    }
    $signToolInput = $SignToolPath.Trim()
    if (-not $signToolInput) { $signToolInput = $env:SHUABAO_SIGNTOOL_PATH }
    if ($signToolInput) {
        if (-not (Test-Path -LiteralPath $signToolInput -PathType Leaf)) {
            throw "external-beta/release 渠道指定的 signtool.exe 不存在，请由操作员提供真实 Windows SDK 路径。"
        }
        $signtoolPath = (Resolve-Path -LiteralPath $signToolInput).Path
    } else {
        $signtoolPath = Resolve-SignTool
    }
    if (-not $signtoolPath) {
        throw "external-beta/release 渠道找不到真实 signtool.exe，请由操作员安装 Windows SDK 或显式传入 -SignToolPath。"
    }
    $releaseSigningSource = [System.IO.File]::ReadAllText((Join-Path $PSScriptRoot "src\shuabao\release_signing.py"))
    if ($releaseSigningSource -match 'PINNED_MANIFEST_PUBLIC_KEYS\s*:[^=]+=\s*\{\s*\}') {
        throw "external-beta/release 渠道阻断：运行时 PINNED_MANIFEST_PUBLIC_KEYS 仍为空；请由操作员编译真实 Ed25519 SPKI pin 后重试。"
    }
}

# Dev/internal packages remain explicitly unsigned; external packages claim SIGNED
# only because the signer and verifier below are mandatory before delivery.
$manifestSignatureStatus = if ($isExternalChannel) { "SIGNED" } else { "UNSIGNED" }

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

function Get-CanonicalManifestSha256([string]$Path) {
    # build_identity 绑定 manifest 的 canonical JSON SHA256（与签名 envelope 一致），
    # 不再使用原始文件字节哈希；两种哈希对同一清单通常不同。
    $code = "import json,sys; from pathlib import Path; sys.path.insert(0, str(Path(sys.argv[2]) / 'src')); from shuabao.release_signing import canonical_manifest_sha256; print(canonical_manifest_sha256(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))))"
    $sha = & $python -c $code $Path $PSScriptRoot
    if ($LASTEXITCODE -ne 0) { throw "canonical manifest sha256 计算失败：$Path" }
    return ([string]$sha).Trim()
}

function Write-Utf8NoBom([string]$Path, [string]$Content) {
    # Windows PowerShell 5.1's `Set-Content -Encoding utf8` writes a BOM.
    # Python's json.loads(..., encoding="utf-8") rejects that marker, so all
    # JSON sidecars consumed by the frozen runtime must be explicitly BOM-free.
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $utf8NoBom)
}

function Read-Utf8NoBom([string]$Path) {
    # Windows PowerShell 5.1 treats a BOM-free file as the active ANSI code
    # page when using bare Get-Content.  Release manifests contain Chinese
    # asset paths, so decode them explicitly before ConvertFrom-Json.
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    return [System.IO.File]::ReadAllText($Path, $utf8NoBom)
}

function Assert-ExternalModeEvidence([string]$SourceSha) {
    # 外发渠道硬阻断：mode_specs.json 中 live_enabled=true 且 desktop_start=true 的
    # 每个模式，必须在 mode_evidence.json 里有 status=PASS 且 source_sha==本次构建
    # 的真机证据。缺文件、畸形 JSON、MISSING 或 SHA 不一致一律拒绝；绝不把
    # MISSING/BLOCKED 当作通过。
    $specsPath = Join-Path $PSScriptRoot "config\mode_specs.json"
    $evidencePath = Join-Path $PSScriptRoot "config\mode_evidence.json"
    foreach ($path in @($specsPath, $evidencePath)) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "外发渠道阻断：缺少 $(Split-Path -Leaf $path)，无法核验模式真机证据。"
        }
    }
    try { $specs = Read-Utf8NoBom $specsPath | ConvertFrom-Json }
    catch { throw "外发渠道阻断：mode_specs.json 无法解析（畸形 JSON）：$($_.Exception.Message)" }
    try { $evidence = Read-Utf8NoBom $evidencePath | ConvertFrom-Json }
    catch { throw "外发渠道阻断：mode_evidence.json 无法解析（畸形 JSON）：$($_.Exception.Message)" }
    $required = @($specs.modes.PSObject.Properties | Where-Object {
        $_.Value.live_enabled -eq $true -and $_.Value.desktop_start -eq $true
    })
    if ($required.Count -eq 0) {
        throw "外发渠道阻断：mode_specs.json 没有任何 live_enabled+desktop_start 模式，证据清单异常。"
    }
    foreach ($mode in $required) {
        $entry = $null
        if ($evidence.modes -and $evidence.modes.PSObject.Properties[$mode.Name]) {
            $entry = $evidence.modes.PSObject.Properties[$mode.Name].Value
        }
        if (-not $entry) {
            throw "外发渠道阻断：模式 $($mode.Name) 缺少 mode_evidence.json 记录，拒绝外发。"
        }
        if ($entry.status -ne "PASS") {
            throw "外发渠道阻断：模式 $($mode.Name) 真机证据 status=$($entry.status)（必须 PASS），拒绝外发。"
        }
        if (-not $entry.source_sha -or $entry.source_sha -ne $SourceSha) {
            throw "外发渠道阻断：模式 $($mode.Name) 证据 source_sha 与本次构建 $SourceSha 不一致，拒绝外发。"
        }
    }
    Write-Host "外发模式证据核验通过：$($required.Count) 个 live 桌面模式绑定当前构建。" -ForegroundColor Green
}

function Assert-AuthenticodeValid([string]$ExePath, [string]$Role) {
    # 外发渠道硬阻断：主 EXE 与 OCR EXE 的 Authenticode 必须为 Valid。没有签名
    # 证书/signtool 设施时此检查自然失败；build_identity 里的 UNSIGNED 事实标记
    # 绝不能替代本检查。
    if (-not (Test-Path -LiteralPath $ExePath -PathType Leaf)) {
        throw "外发渠道阻断：$Role 不存在，无法核验 Authenticode 签名。"
    }
    $sig = Get-AuthenticodeSignature -LiteralPath $ExePath
    if (-not $sig -or $sig.Status -ne "Valid") {
        $sigStatus = if ($sig) { $sig.Status } else { "NotSigned" }
        throw "外发渠道阻断：$Role Authenticode Status=$sigStatus（必须 Valid），拒绝外发。"
    }
    Write-Host "Authenticode 校验通过：$Role" -ForegroundColor Green
}
function Invoke-AuthenticodeSigning([string]$ExePath, [string]$Role) {
    & $signtoolPath sign /sha1 $certThumbprint /fd SHA256 /tr $timestampUrl /td SHA256 $ExePath
    if ($LASTEXITCODE -ne 0) {
        throw "外发渠道阻断：$Role Authenticode 签名失败。"
    }
    Assert-AuthenticodeValid $ExePath $Role
}

# 外发渠道在依赖安装/打包之前 fail-closed：真机证据不齐就直接拒绝，不浪费构建。
if ($isExternalChannel) {
    Assert-ExternalModeEvidence $sourceSha
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
    source_tree_clean    = ($initialTrackedDirtyEntries.Count -eq 0)
    release_channel      = $ReleaseChannel
    index_sha256         = Get-ReleaseFileSha256 $uiIndex
    bridge_schema_version = 2
    generated_at_utc     = [DateTime]::UtcNow.ToString("o")
}
$uiManifestJson = $uiManifest | ConvertTo-Json -Depth 3
Write-Utf8NoBom (Join-Path $uiDist "build_manifest.json") $uiManifestJson
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
    $gateArgs = @("tools\release_gate.py")
    if ($isExternalChannel) { $gateArgs += "--strict-release" }
    & $gatePython @gateArgs
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

# 外发渠道先使用真实 Windows SDK signtool 对两个 EXE 做 SHA-256
# Authenticode + RFC3161 时间戳，再执行独立 Valid 校验；任何一步失败都拒绝。
if ($isExternalChannel) {
    Invoke-AuthenticodeSigning $app "主程序 EXE"
    Invoke-AuthenticodeSigning $ocrWorker "OCR worker EXE"
}

$releaseRoot = Join-Path $PSScriptRoot "dist\$APP_ID"

# Pin the non-secret subscription deployment settings beside the executable.
# A clean shortcut launch must not depend on the shell that happened to build
# the package.  License material is deliberately absent; it remains DPAPI/env
# only.  Remote endpoints must use HTTPS, while HTTP is limited to loopback.
$subscriptionRuntimePath = Join-Path $releaseRoot "subscription_runtime.json"
$subscriptionRuntime = [ordered]@{
    schema_version = 1
    base_url = $subscriptionUrl.TrimEnd("/")
    mode = $SubscriptionMode
    release_channel = $ReleaseChannel
    timeout_s = 10
}
$subscriptionRuntimeJson = $subscriptionRuntime | ConvertTo-Json -Depth 3
Write-Utf8NoBom $subscriptionRuntimePath $subscriptionRuntimeJson
Write-Host "已写入订阅部署配置（不含卡密）：$subscriptionRuntimePath" -ForegroundColor DarkGray

# A live-input capture refuses to run unless the checked-out source commit,
# the packaged EXE and this sidecar agree. A version label alone is not a
# build identity. Keep the sidecar beside ShuaBao.exe so robocopy deployment
# carries the exact proof with the release.
$sourceDirtyEntries = @(& git status --porcelain --untracked-files=all)
$sourceTrackedDirtyEntries = @(& git status --porcelain --untracked-files=no)
$buildId = (& $python -c "import sys; sys.path.insert(0, 'src'); from shuabao.mediator import BUILD_ID; print(BUILD_ID)").Trim()
$releaseManifestPath = Join-Path $releaseRoot "release_manifest.json"
# 复用 dist 重建时，旧的 release_manifest.json.sig 不能进入清单，也不能与新生成
# 的签名混用：先生成清单元数据，再移除陈旧签名并重新签名。
Remove-Item -LiteralPath (Join-Path $releaseRoot "release_manifest.json.sig") -Force -ErrorAction SilentlyContinue

$releasePrefix = "$releaseRoot\"
$releaseEntries = @(
    Get-ChildItem -LiteralPath $releaseRoot -File -Recurse |
        Where-Object {
            $_.FullName -ne $releaseManifestPath -and
            $_.FullName -ne (Join-Path $releaseRoot "release_manifest.json.sig") -and
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
    manifest_signature_status = $manifestSignatureStatus
    schema_version = 1
    source_sha = $sourceSha
    bridge_schema_version = 2
    release_channel = $ReleaseChannel
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    files = @($releaseEntries)
}
$releaseManifestJson = $releaseManifest | ConvertTo-Json -Depth 6
Write-Utf8NoBom $releaseManifestPath $releaseManifestJson
if ($isExternalChannel) {
    $manifestSignaturePath = "$releaseManifestPath.sig"
    try {
        & $python tools\sign_release_manifest.py --manifest $releaseManifestPath --private-key $manifestKeyPath --key-id $manifestKeyId
        if ($LASTEXITCODE -ne 0) { throw "manifest signer exited with code $LASTEXITCODE" }
        $verifyCode = "import json,sys; from pathlib import Path; source=Path(sys.argv[1]); root=Path(sys.argv[2]); sys.path.insert(0,str(source/'src')); from shuabao.release_signing import PINNED_MANIFEST_PUBLIC_KEYS,verify_manifest_signature; verify_manifest_signature(json.loads((root/'release_manifest.json').read_text(encoding='utf-8')),json.loads((root/'release_manifest.json.sig').read_text(encoding='utf-8')),PINNED_MANIFEST_PUBLIC_KEYS)"
        & $python -c $verifyCode $PSScriptRoot $releaseRoot
        if ($LASTEXITCODE -ne 0) { throw "runtime manifest signature verification failed" }
        Write-Host "release_manifest Ed25519 签名与固定 pin 校验通过。" -ForegroundColor Green
    }
    catch {
        Remove-Item -LiteralPath $manifestSignaturePath, $releaseManifestPath -Force -ErrorAction SilentlyContinue
        throw "外发渠道 manifest 签名/校验失败，拒绝交付：$($_.Exception.Message)"
    }
}
$ocrModelManifestPath = Join-Path $releaseRoot "vision\_internal\models\ocr\MODEL_MANIFEST.json"
if (-not (Test-Path -LiteralPath $ocrModelManifestPath -PathType Leaf)) {
    throw "发行目录缺少 OCR 模型清单，无法写入完整构建身份。"
}
$ocrModelManifestSha = Get-ReleaseFileSha256 $ocrModelManifestPath
$identity = [ordered]@{
    schema_version     = 1
    source_sha         = $sourceSha
    source_tree_clean  = ($sourceTrackedDirtyEntries.Count -eq 0)
    build_id           = $buildId
    exe_name           = (Split-Path -Leaf $app)
    exe_sha256         = Get-ReleaseFileSha256 $app
    bridge_schema_version = 2
    release_channel    = $ReleaseChannel
    signature_status   = $manifestSignatureStatus
    ocr_model_manifest_sha256 = $ocrModelManifestSha
    release_manifest_sha256 = Get-CanonicalManifestSha256 $releaseManifestPath
    created_at_utc     = [DateTime]::UtcNow.ToString("o")
}
$identityPath = Join-Path (Split-Path -Parent $app) "build_identity.json"
$identityJson = $identity | ConvertTo-Json -Depth 3
Write-Utf8NoBom $identityPath $identityJson
Write-Host "已写入构建身份：$identityPath" -ForegroundColor Green

# 统一的冻结包 harness：源码 pytest 通过并不代表 onedir EXE 可交付。
# 这里额外核对 EXE/manifest/UI 的 source_sha、EXE 哈希、Python TLS DLL 配对、
# 订阅 endpoint/超时和 Web 清单；它只读文件与 Git，不启动游戏、不发输入。
$releaseHarness = Join-Path $PSScriptRoot "tools\release_harness.py"
$harnessArgs = @(
    "--source-root", $PSScriptRoot,
    "--bundle", $releaseRoot
)
if (-not $AllowDirty) { $harnessArgs += "--require-clean" }
& $python $releaseHarness @harnessArgs
if ($LASTEXITCODE -ne 0) {
    throw "冻结包 harness 校验失败，拒绝继续部署。"
}

if ($NoDeploy) { return }

Write-Host "[4/4] 部署到桌面并更新快捷方式 ..." -ForegroundColor Cyan
$version = (& $python -c "import sys; sys.path.insert(0,'src'); import shuabao; print(shuabao.__version__)").Trim()
$versionLabel = "V$version"
$desktop = [Environment]::GetFolderPath("Desktop")
$target  = Join-Path $desktop "$APP_ID"
$archive = Join-Path $desktop "$APP_NAME-旧版归档"

# 先 fail-fast 检查旧桌面程序是否仍占用 ShuaBao.exe。robocopy /MIR 遇到锁定
# EXE 会长时间重试，表面像“同步成功但用户仍是旧版”；构建必须直接告诉操作员
# 哪些 PID 需要先正常退出，不能把锁等待当作部署进度。
$runningDesktopProcesses = @(Get-Process -Name $APP_ID -ErrorAction SilentlyContinue)
if ($runningDesktopProcesses.Count -gt 0) {
    $runningPids = ($runningDesktopProcesses | ForEach-Object { $_.Id }) -join ","
    throw "桌面同步前请先关闭 $APP_ID.exe（占用 PID: $runningPids），否则 robocopy 会锁等待。"
}

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
$deployedIdentity = Read-Utf8NoBom $deployedIdentityPath | ConvertFrom-Json
if ($deployedIdentity.source_sha -ne $sourceSha -or
    $deployedIdentity.release_manifest_sha256 -ne (Get-CanonicalManifestSha256 $deployedManifestPath) -or
    $deployedIdentity.source_tree_clean -ne $true) {
    throw "部署后的构建身份校验失败，拒绝更新快捷方式。"
}
$deployedManifest = Read-Utf8NoBom $deployedManifestPath | ConvertFrom-Json
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

# Save 后重新打开 .lnk 做读取验证；只设置 COM 对象而不回读，会把旧目标
# 或旧工作目录误当成同步成功，导致用户双击仍运行旧桌面副本。
$shortcutProof = $shell.CreateShortcut($lnk)
$expectedShortcutTarget = [System.IO.Path]::GetFullPath((Join-Path $target "$APP_ID.exe"))
$actualShortcutTarget = [System.IO.Path]::GetFullPath([string]$shortcutProof.TargetPath)
if (-not [System.String]::Equals($actualShortcutTarget, $expectedShortcutTarget, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "桌面快捷方式目标校验失败：实际=$actualShortcutTarget 期望=$expectedShortcutTarget"
}
$expectedShortcutWorkDir = [System.IO.Path]::GetFullPath($target).TrimEnd("\")
$actualShortcutWorkDir = [System.IO.Path]::GetFullPath([string]$shortcutProof.WorkingDirectory).TrimEnd("\")
if (-not [System.String]::Equals($actualShortcutWorkDir, $expectedShortcutWorkDir, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "桌面快捷方式工作目录校验失败：实际=$actualShortcutWorkDir 期望=$expectedShortcutWorkDir"
}
if (-not [string]::IsNullOrWhiteSpace([string]$shortcutProof.Arguments)) {
    throw "桌面快捷方式不允许携带旧版本参数：$($shortcutProof.Arguments)"
}

# 再对最终桌面目录跑一次同一 harness，证明 robocopy 后的文件没有陈旧/半
# 同步；任何失败都不算“已同步到桌面”。
$deployedHarnessArgs = @(
    "--source-root", $PSScriptRoot,
    "--bundle", $target
)
if (-not $AllowDirty) { $deployedHarnessArgs += "--require-clean" }
& $python $releaseHarness @deployedHarnessArgs
if ($LASTEXITCODE -ne 0) {
    throw "桌面发行目录 harness 校验失败，拒绝交付。"
}

Write-Host "已部署：$target" -ForegroundColor Green
Write-Host "快捷方式：$lnk" -ForegroundColor Green
Write-Host "提示：需要真实点击时请右键快捷方式以管理员身份运行。" -ForegroundColor Yellow
