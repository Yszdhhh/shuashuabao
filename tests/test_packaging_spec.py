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
