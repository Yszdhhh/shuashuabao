"""打包配置静态契约：ShuaBao.spec 与 requirements-desktop.txt。

不真正跑 PyInstaller，只验证 spec 源码里的关键声明：
web 前端产物被打进包、WebEngine 模块被 hiddenimports 兜底、
旧的 HTTP/WebView 依赖仍然被排除。
"""

from pathlib import Path
import re
import runpy
import sys
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _spec_text() -> str:
    return (PROJECT_ROOT / "ShuaBao.spec").read_text(encoding="utf-8")


@pytest.mark.parametrize("missing", [None, "libssl-3-x64.dll", "libcrypto-3-x64.dll"])
def test_spec_pins_python_tls_pair_even_if_analysis_selects_foreign_dlls(tmp_path, monkeypatch, missing):
    dll_dir = tmp_path / "python" / "DLLs"
    dll_dir.mkdir(parents=True)
    names = ("libssl-3-x64.dll", "libcrypto-3-x64.dll")
    for name in names:
        if name != missing:
            (dll_dir / name).write_bytes(b"test-only")
    monkeypatch.setattr(sys, "base_prefix", str(dll_dir.parent))
    trust_hook = tmp_path / "pyi_rth_manifest_trust.py"
    trust_hook.write_text("# test-only build hook", encoding="utf-8")
    monkeypatch.setenv("SHUABAO_BUILD_MANIFEST_TRUST_HOOK", str(trust_hook))
    collected = [("libssl-3-x64.dll", "foreign/poppler/ssl", "BINARY"),
                 ("PySide6/libcrypto-3-x64.dll", "foreign/poppler/crypto", "BINARY"),
                 ("_ssl.pyd", "python/_ssl.pyd", "EXTENSION")]
    analysis_calls = []

    def analysis(*args, **kwargs):
        analysis_calls.append(kwargs)
        return SimpleNamespace(binaries=collected.copy(), pure=[], scripts=[], datas=[])

    def execute():
        return runpy.run_path(str(PROJECT_ROOT / "ShuaBao.spec"), init_globals={
            "SPECPATH": str(PROJECT_ROOT), "Analysis": analysis,
            "PYZ": lambda *_a, **_kw: None, "EXE": lambda *_a, **_kw: None,
            "COLLECT": lambda *_a, **_kw: None,
        })

    if missing:
        with pytest.raises(RuntimeError, match="Python TLS dependency missing"):
            execute()
        assert not analysis_calls
    else:
        result = execute()
        assert result["a"].binaries == [
            (dest, str(dll_dir / Path(dest).name), kind) if Path(dest).name in names
            else (dest, source, kind) for dest, source, kind in collected
        ]
        for name in names:
            assert (str(dll_dir / name), ".") in analysis_calls[0]["binaries"]
        assert str(trust_hook) in analysis_calls[0]["runtime_hooks"]


def test_spec_bundles_web_dist() -> None:
    text = _spec_text()
    assert 'PROJECT_ROOT / "ui-v2" / "dist"' in text
    assert '"web"' in text and '"dist"' in text
    assert '"web" / "dist"' not in text, "打包目标必须是路径字符串，不能对 str 做 / 运算"


def test_spec_hiddenimports_include_qtwebengine_modules() -> None:
    text = _spec_text()
    for module in (
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebChannel",
    ):
        assert module in text, f"hiddenimports missing {module}"


def test_spec_uses_windowed_elevated_exe_with_app_icon() -> None:
    text = _spec_text()
    assert "console=False" in text
    assert 'icon=str(PROJECT_ROOT / "assets" / "branding" / "app_logo.ico")' in text
    assert "uac_admin=True" in text


def test_spec_places_shiboken_loader_dll_on_windows_search_path() -> None:
    text = _spec_text()
    assert "SHIBOKEN_DLL" in text
    assert '(str(SHIBOKEN_DLL), "PySide6")' in text
    assert '(str(PYSIDE_ABI_DLL), "PySide6")' in text


def test_spec_registers_pyside_dll_directory_before_imports() -> None:
    text = _spec_text()
    assert 'runtime_hooks=[str(PROJECT_ROOT / "packaging" / "pyi_rth_pyside6_path.py"), manifest_trust_hook]' in text
    hook = (PROJECT_ROOT / "packaging" / "pyi_rth_pyside6_path.py").read_text(encoding="utf-8")
    assert 'os.add_dll_directory(str(_pyside_dir))' in hook


def test_spec_excludes_host_icu_dll_that_breaks_qtcore() -> None:
    text = _spec_text()
    assert 'entry[0].lower() != "icuuc.dll"' in text


def test_mode_catalog_uses_frozen_resource_root() -> None:
    text = (PROJECT_ROOT / "src" / "shuabao" / "shell" / "mode_catalog.py").read_text(encoding="utf-8")
    assert 'getattr(sys, "_MEIPASS"' in text


def test_spec_excludes_legacy_http_and_webview_backends() -> None:
    text = _spec_text()
    assert 'excludes=["fastapi", "uvicorn", "webview"]' in text


def test_requirements_desktop_use_full_pyside6() -> None:
    req = (PROJECT_ROOT / "requirements-desktop.txt").read_text(encoding="utf-8")
    assert not any(
        line.strip().startswith("PySide6-Essentials") for line in req.splitlines()
    )
    assert any(line.startswith("PySide6>=") for line in req.splitlines())


def test_build_script_rebuilds_ui_before_pyinstaller() -> None:
    text = (PROJECT_ROOT / "build_release.ps1").read_text(encoding="utf-8")
    assert "& $npm.Source ci" in text
    assert "& $npm.Source run build" in text
    assert text.index("& $npm.Source run build") < text.index("PyInstaller 打包")


def test_packaged_web_launcher_selects_web_shell_and_isolated_data() -> None:
    text = (PROJECT_ROOT / "tools" / "launch_packaged_web_shell.vbs").read_text(encoding="utf-8")
    assert '"SHUABAO_SHELL") = "web"' in text
    assert "ShuaBaoWeb" in text
    assert 'ShellExecute root & "\\ShuaBao.exe"' in text
    assert '"open", 1' in text
    assert '"runas"' not in text


# --- 外发构建渠道与生产地址门禁（build_release.ps1 ReleaseChannel 契约） ---
# 静态契约测试：不跑构建，只验证打包脚本源码中的门禁与事实字段。
# build_release.ps1 是顶层顺序脚本，导入执行会真的开始打包，因此字符串/
# 结构断言是本仓库对打包脚本的一贯测法（见上方 test_build_script_* 系列）。


def _build_script_text() -> str:
    return (PROJECT_ROOT / "build_release.ps1").read_text(encoding="utf-8")


def test_build_script_declares_release_channel_with_dev_default() -> None:
    text = _build_script_text()
    assert 'ValidateSet("dev", "internal-pilot", "external-beta", "release")' in text
    assert '[string]$ReleaseChannel = "dev"' in text


def test_external_channels_reject_skip_gate_and_allow_dirty() -> None:
    text = _build_script_text()
    assert "external-beta/release 渠道禁止 -SkipGate" in text
    assert "external-beta/release 渠道禁止 -AllowDirty" in text


def test_external_channels_require_enforce_subscription_mode() -> None:
    text = _build_script_text()
    assert "external-beta/release 渠道要求 -SubscriptionMode enforce" in text


def test_diagnostic_build_uses_configured_subscription_endpoint() -> None:
    text = _build_script_text()
    assert "-not $subscriptionUrlInput -and -not $isExternalChannel" in text
    assert "$env:SHUABAO_SUBSCRIPTION_BASE_URL" in text


def test_packaged_subscription_timeout_allows_tunnel_cold_start() -> None:
    text = _build_script_text()
    assert "timeout_s = 10" in text


def test_external_channels_require_explicit_https_subscription() -> None:
    text = _build_script_text()
    assert "external-beta/release 订阅地址必须为显式 HTTPS" in text


def test_external_loopback_rejection_covers_full_loopback_range() -> None:
    # 旧的精确主机名列表（127.0.0.1/localhost/::1/[::1]）会错误放行
    # https://127.0.0.2 等 127.0.0.0/8 段地址；外发渠道必须改用
    # [System.Net.IPAddress].IsLoopback 按地址语义判定整个回环段。
    text = _build_script_text()
    assert "[System.Net.IPAddress]::TryParse" in text
    assert "[System.Net.IPAddress]::IsLoopback" in text
    assert '"localhost"' in text, "非 IP 主机名 localhost 必须按名称语义显式处理"



def test_external_loopback_rejection_covers_trailing_dot_names() -> None:
    # 复审 P1：精确比较 "localhost" 时，https://localhost. （FQDN 尾点形式）
    # 会在 TryParse 失败后 return $false，错误放行 external。名称判断必须
    # 先 TrimEnd('.') + ToLowerInvariant 再比较。
    text = _build_script_text()
    assert "TrimEnd('.')" in text
    assert "ToLowerInvariant()" in text

def test_dev_channel_keeps_loopback_default_and_switches() -> None:
    text = _build_script_text()
    assert text.count('"http://127.0.0.1:8000"') == 1, "loopback 默认值只能留在 dev/internal-pilot 分支"
    assert "[switch]$SkipGate" in text
    assert "[switch]$AllowDirty" in text


def test_ui_manifest_source_tree_clean_uses_initial_tracked_dirty_state() -> None:
    text = _build_script_text()
    assert "($initialTrackedDirtyEntries.Count -eq 0)" in text
    assert not re.search(r"source_tree_clean\s*=\s*\$true", text), "UI manifest 不得恒写 true"


def test_dev_channel_keeps_loopback_default_and_switches() -> None:
    text = _build_script_text()
    assert "$isExternalChannel" in text, "dev/internal-pilot 与外发渠道必须显式分流"
    assert text.count('"http://127.0.0.1:8000"') == 1, "loopback 默认值只能留在 dev/internal-pilot 分支"
    assert "[switch]$SkipGate" in text
    assert "[switch]$AllowDirty" in text


def test_release_channel_recorded_in_all_four_sidecars() -> None:
    text = _build_script_text()
    # UI build_manifest、subscription_runtime、release_manifest、build_identity 各一处
    assert len(re.findall(r"release_channel\s*=\s*\$ReleaseChannel", text)) == 4


def test_build_identity_records_channel_signature_fact() -> None:
    text = _build_script_text()
    assert '$manifestSignatureStatus = "SIGNED"' in text
    assert "signature_status   = $manifestSignatureStatus" in text

# --- 发行包运行时配置白名单（ShuaBao.spec 只打生产消费者） ---
# 已确认生产运行时读取的配置；dashboard_test_profiles 由 native UI 读取（保留防回归），
# mode_evidence 由 dashboard facade 读取（当前构建一致性，不能误删）。
RUNTIME_CONFIG_ALLOWLIST = {
    "mode_specs.json",
    "choice_lexicon.json",
    "game_mechanics_kb.json",
    "fetter_labels.json",
    "default_settings.json",
    "choice_policy.json",
    "stage_unlocks.json",
    "skill_meta.json",
    "skill_routes.json",
    "skill_card_rarity.json",
    "skill_labels.json",
    "skill_card_knowledge.json",
    "skill_card_catalog.json",
    "scenes.json",
    "skill_archive_unlocks.json",
    "official_strategy_defaults.json",
    "reputation_factions_kb.json",
    "bond_stack_catalog.json",
    "dashboard_test_profiles.json",
    "mode_evidence.json",
    "entitlement_public_keys.json",
}

# 无生产消费者的研究/证据/测试资料：保留源码，不随包分发。
# runtime_asset_manifest.json 仅被 tools/release_gate.py 从源码根读取。
NON_PRODUCTION_CONFIG_EXCLUDES = {
    "vision_profiles.proposed.yaml",
    "dashboard_mechanics.json",
    "bond_knowledge.json",
    "habit_preference.schema.json",
    "challenge_boss_catalog.json",
    "runtime_asset_manifest.json",
}


def _spec_whitelist() -> set[str]:
    import ast

    tree = ast.parse(_spec_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "RUNTIME_CONFIG_FILES"
            for t in node.targets
        ):
            assert isinstance(node.value, (ast.List, ast.Tuple)), "RUNTIME_CONFIG_FILES 必须是显式字面量列表"
            return {
                elt.value
                for elt in node.value.elts
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
            }
    raise AssertionError("ShuaBao.spec 缺少 RUNTIME_CONFIG_FILES 显式白名单")


def test_spec_whitelists_runtime_config_files_instead_of_whole_dir() -> None:
    text = _spec_text()
    assert '(str(PROJECT_ROOT / "config"), "config")' not in text, "整目录打包会泄漏研究/证据配置"
    assert _spec_whitelist() == RUNTIME_CONFIG_ALLOWLIST, (
        "白名单与已确认生产消费者不一致: "
        f"缺失={sorted(RUNTIME_CONFIG_ALLOWLIST - _spec_whitelist())} "
        f"多余={sorted(_spec_whitelist() - RUNTIME_CONFIG_ALLOWLIST)}"
    )


def test_spec_generates_config_tuple_for_every_whitelisted_file() -> None:
    text = _spec_text()
    # 每个白名单文件生成 (path, "config")；文件缺失时 PyInstaller 分析阶段直接报错。
    assert '(str(PROJECT_ROOT / "config" / name), "config")' in text
    assert "for name in RUNTIME_CONFIG_FILES" in text


def test_spec_excludes_non_production_config_files() -> None:
    whitelist = _spec_whitelist()
    for name in NON_PRODUCTION_CONFIG_EXCLUDES:
        assert name not in whitelist, f"{name} 无生产消费者，不得随包分发"


def test_runtime_config_allowlist_files_exist_in_source() -> None:
    for name in RUNTIME_CONFIG_ALLOWLIST:
        assert (PROJECT_ROOT / "config" / name).is_file(), f"config/{name} 缺失"

# --- 外发签名设施与运行时最小白名单 ---
# 静态契约测试：不执行构建，只验证 build_release.ps1 的 fail-closed 结构。


def test_external_channels_declare_explicit_signing_inputs_and_env_fallbacks() -> None:
    text = _build_script_text()
    for marker in (
        '[string]$ManifestSigningKeyPath = ""',
        '[string]$ManifestSigningKeyId = ""',
        '[string]$ManifestPublicKeysPath = ""',
        '[string]$AuthenticodeCertificateThumbprint = ""',
        '[string]$AuthenticodeTimestampUrl = ""',
        '[string]$SignToolPath = ""',
        '$env:SHUABAO_MANIFEST_SIGNING_KEY',
        '$env:SHUABAO_MANIFEST_SIGNING_KEY_ID',
        '$env:SHUABAO_MANIFEST_PUBLIC_KEYS_PATH',
        '$env:SHUABAO_AUTHENTICODE_CERT_THUMBPRINT',
        '$env:SHUABAO_AUTHENTICODE_TIMESTAMP_URL',
        '$env:SHUABAO_TIMESTAMP_URL',
        '$env:SHUABAO_SIGNTOOL_PATH',
    ):
        assert marker in text, f"缺少签名输入：{marker}"


def test_external_channels_fail_closed_before_expensive_build_without_real_signing_material() -> None:
    text = _build_script_text()
    preflight = text.index("缺少真实 Ed25519 manifest 私钥路径")
    for marker in ("Get-Command uv", "npm ci", "PyInstaller 打包主程序"):
        assert preflight < text.index(marker), f"签名门禁必须先于{marker}"
    assert "ManifestSigningKeyPath" in text and "ManifestSigningKeyId" in text
    assert "AuthenticodeCertificateThumbprint" in text and "AuthenticodeTimestampUrl" in text
    assert "tools\\prepare_manifest_trust.py" in text
    assert "operator" in text.lower() or "操作员" in text


def test_external_channels_sign_and_verify_manifest_after_generation() -> None:
    text = _build_script_text()
    assert "tools\\sign_release_manifest.py" in text
    assert "--private-key" in text
    assert "--key-id" in text
    assert "release_manifest.json.sig" in text
    assert '"--manifest-public-keys", $manifestPublicKeysPath' in text
    assert '$manifestSignatureStatus = "SIGNED"' in text


def test_external_channels_sign_both_exes_with_rfc3161_before_authenticode_validation() -> None:
    text = _build_script_text()
    assert "signtool.exe" in text
    assert "function Invoke-AuthenticodeSigning([string]$ExePath, [string]$Role)" in text
    assert "/fd SHA256" in text
    assert "/tr $timestampUrl" in text
    assert "/td SHA256" in text
    assert "/sha1 $certThumbprint" in text
    sign_hook = text.index("function Invoke-AuthenticodeSigning")
    verify_hook = text.index("Assert-AuthenticodeValid $ExePath $Role")
    invoke_main = text.index('Invoke-AuthenticodeSigning $app "主程序 EXE"')
    invoke_ocr = text.index('Invoke-AuthenticodeSigning $ocrWorker "OCR worker EXE"')
    assert sign_hook < verify_hook < invoke_main
    assert invoke_main < invoke_ocr

def test_release_manifest_entries_exclude_signature_sidecar_and_clear_stale_sig() -> None:
    text = _build_script_text()
    entries_block = text[text.index("$releaseEntries = @(") : text.index("$releaseManifest = [ordered]@{")]
    assert '$_.FullName -ne (Join-Path $releaseRoot "release_manifest.json.sig")' in entries_block
    assert entries_block.count("$_.FullName -ne ") == 3, "manifest、.sig 与 build_identity 都必须显式排除"
    manifest_block = text[text.index('$releaseManifestPath = Join-Path $releaseRoot "release_manifest.json"') : text.index("$releaseEntries = @(")]
    assert "Remove-Item -LiteralPath (Join-Path $releaseRoot \"release_manifest.json.sig\")" in manifest_block, "复用 dist 重建必须先移除陈旧 .sig"

def test_external_channels_fail_closed_when_signtool_unresolved_before_build() -> None:
    text = _build_script_text()
    resolve_call = text.index("$signtoolPath = Resolve-SignTool")
    guard = text.index("渠道找不到真实 signtool.exe")
    uv = text.index("Get-Command uv")
    assert guard > resolve_call, "解析失败后必须立即检查 signtool 是否解析成功"
    assert guard < uv, "signtool 缺失必须在依赖安装/打包之前显式阻断"

def test_external_channels_verify_signing_cert_exists_with_private_key() -> None:
    text = _build_script_text()
    assert '"Cert:\\CurrentUser\\My"' in text and '"Cert:\\LocalMachine\\My"' in text
    assert "$_.Thumbprint -eq $certThumbprint" in text
    assert "$_.HasPrivateKey" in text
    guard = text.index("找不到 thumbprint=$certThumbprint 的 Authenticode 证书")
    assert guard < text.index("Get-Command uv"), "证书缺失必须在构建副作用之前显式阻断"


def test_external_channels_run_gate_with_strict_release() -> None:
    text = _build_script_text()
    m = re.search(r"if \(\$isExternalChannel\) \{ \$gateArgs \+= .--strict-release. \}", text)
    assert m, "external-beta/release 渠道必须以 --strict-release 跑发版门禁"
    assert "& $gatePython @gateArgs" in text


def test_external_channels_verify_mode_evidence_before_packaging() -> None:
    text = _build_script_text()
    call_site = re.search(
        r"if \(\$isExternalChannel\) \{\s*Assert-ExternalModeEvidence \$sourceSha\s*\}",
        text,
    )
    assert call_site, "external 渠道必须在打包前调用模式证据核验"
    assert call_site.start() < text.index("PyInstaller 打包主程序")
    assert "mode_specs.json" in text and "mode_evidence.json" in text
    assert "$_.Value.live_enabled -eq $true -and $_.Value.desktop_start -eq $true" in text
    assert re.search(r"status\s+-ne .PASS.", text)
    assert re.search(r"\$entry\.source_sha\s+-ne \$SourceSha", text)
    assert text.count("无法解析（畸形 JSON）") >= 2


def test_build_script_deploys_versioned_install_and_stable_launcher() -> None:
    text = _build_script_text()
    assert "shuabao.versioned_install place" in text
    assert "shuabao.versioned_install promote" in text
    assert 'Join-Path $env:LOCALAPPDATA $APP_ID' in text
    assert "ShuaBaoLauncher.vbs" in text
    assert '$shortcut.TargetPath = $launcherVbs' in text
    assert 'Join-Path $target "$APP_ID.exe"' not in text
    assert 'robocopy `"$srcDist`" `"$target`" /MIR' not in text
    assert "version            = $version" in text
    assert text.index("versioned_install place") < text.index("versioned_install promote")
    assert text.index('throw "版本目录 harness 校验失败，拒绝切换 current。"') < text.index("versioned_install promote")


def test_build_script_archives_legacy_desktop_after_shortcut_proof() -> None:
    text = _build_script_text()
    deploy = text[text.index("if ($NoDeploy)"):]
    proof = deploy.index("桌面快捷方式不允许携带旧版本参数")
    assert deploy.index("versioned_install place") < proof
    assert deploy.index("versioned_install promote") < proof
    assert deploy.index("$shortcutProof = $shell.CreateShortcut($lnk)") < proof
    assert proof < deploy.index("已归档旧桌面可变安装目录")
    assert proof < deploy.index("已归档旧快捷方式")
    assert proof < deploy.index("Move-Item -LiteralPath $legacyDesktopInstall")


def test_every_frozen_channel_requires_signing_and_compiled_operator_trust() -> None:
    text = _build_script_text()
    assert '$manifestSignatureStatus = "SIGNED"' in text
    assert '"UNSIGNED"' not in text
    assert '所有 frozen 渠道均要求 -SubscriptionMode enforce' in text
    assert "signature_status   = $manifestSignatureStatus" in text
    assert text.index("tools\\prepare_manifest_trust.py") < text.index("Get-Command uv")
    assert "$env:SHUABAO_BUILD_MANIFEST_TRUST_HOOK = $manifestTrustHook" in text
    assert "$env:SHUABAO_BUILD_MANIFEST_TRUST_HOOK = $previousManifestTrustHook" in text
    assert not re.search(r"if \(\$isExternalChannel\)\s*\{\s*\$manifestSignaturePath", text)
    assert "missing build-time operator manifest trust hook" in _spec_text()


def test_external_channels_reject_in_tree_manifest_signing_key_before_build() -> None:
    text = _build_script_text()
    guard = text.index("manifest 私钥不得位于仓库根或其 build/dist/assets/src/config/ui-v2 子路径")
    uv = text.index("Get-Command uv")
    assert guard < uv, "私钥在树内检查必须发生在构建副作用之前"
    for marker in ('(Join-Path $repoRoot "build")', '(Join-Path $repoRoot "dist")', '(Join-Path $repoRoot "assets")', '(Join-Path $repoRoot "src")', '(Join-Path $repoRoot "config")', '(Join-Path $repoRoot "ui-v2")'):
        assert marker in text, f"私钥黑名单必须覆盖：{marker}"
    assert "Resolve-Path -LiteralPath $manifestKeyPath" in text


def test_build_identity_binds_canonical_manifest_hash_not_raw_bytes() -> None:
    text = _build_script_text()
    assert "release_manifest_sha256 = Get-CanonicalManifestSha256 $releaseManifestPath" in text
    assert "Get-CanonicalManifestSha256 $deployedManifestPath" in text
    assert "from shuabao.release_signing import canonical_manifest_sha256" in text
    assert "release_manifest_sha256 = Get-ReleaseFileSha256" not in text, "manifest 身份不得再使用原始文件字节哈希"
