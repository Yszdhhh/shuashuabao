"""打包配置静态契约：ShuaBao.spec 与 requirements-desktop.txt。

不真正跑 PyInstaller，只验证 spec 源码里的关键声明：
web 前端产物被打进包、WebEngine 模块被 hiddenimports 兜底、
旧的 HTTP/WebView 依赖仍然被排除。
"""

from pathlib import Path
import re

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _spec_text() -> str:
    return (PROJECT_ROOT / "ShuaBao.spec").read_text(encoding="utf-8")


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
    assert 'runtime_hooks=[str(PROJECT_ROOT / "packaging" / "pyi_rth_pyside6_path.py")]' in text
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


def test_external_channels_require_explicit_https_subscription() -> None:
    text = _build_script_text()
    assert "external-beta/release 渠道必须显式传入 -SubscriptionBaseUrl" in text
    assert "external-beta/release 订阅地址必须为显式 HTTPS" in text
    assert "$loopbackHosts -contains" in text, "外发分支必须显式拒绝 loopback 主机"


def test_dev_channel_keeps_loopback_default_and_switches() -> None:
    text = _build_script_text()
    assert text.count('"http://127.0.0.1:8000"') == 1, "loopback 默认值只能留在 dev/internal-pilot 分支"
    assert "[switch]$SkipGate" in text
    assert "[switch]$AllowDirty" in text


def test_ui_manifest_source_tree_clean_uses_initial_dirty_state() -> None:
    text = _build_script_text()
    assert "($initialDirtyEntries.Count -eq 0)" in text
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


def test_build_identity_records_unsigned_signature_fact() -> None:
    text = _build_script_text()
    assert re.search(r'signature_status\s*=\s*"UNSIGNED"', text), "无签名设施时必须显式记录 UNSIGNED 事实"
