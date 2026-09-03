# -*- mode: python ; coding: utf-8 -*-
"""刷刷宝（ShuaBao）打包配置。

exe 文件名用 ASCII 的 ShuaBao.exe：中文文件名在 PyInstaller、命令行工具与部分
杀软白名单里容易出问题；用户看到的中文名由版本信息（ProductName/
FileDescription）和桌面快捷方式「刷刷宝」提供。

刻意不叫 GameScript.exe——参考目录里的原版 C# 程序就叫这个名字，同名会让
任务管理器、崩溃日志和快捷方式无法区分两个程序。
"""

from pathlib import Path
import shiboken6
import sys


PROJECT_ROOT = Path(SPECPATH)
SHIBOKEN_DLL = Path(shiboken6.__file__).resolve().parent / "shiboken6.abi3.dll"
PYSIDE_ABI_DLL = Path(sys.base_prefix) / "python3.dll"

# Qt dependency discovery can pick up Poppler's same-named OpenSSL DLLs from
# PATH. _ssl.pyd must ship with the pair from its own Python installation.
PYTHON_TLS_DLLS = {
    name: Path(sys.base_prefix) / "DLLs" / name
    for name in ("libssl-3-x64.dll", "libcrypto-3-x64.dll")
}
for path in PYTHON_TLS_DLLS.values():
    if not path.is_file():
        raise RuntimeError(f"Python TLS dependency missing: {path}")


# 发行包运行时配置显式白名单：只打包生产运行时确实读取的配置，替代整目录
# (config, config) 打包。文件缺失时 PyInstaller 分析阶段直接报错，不静默跳过。
RUNTIME_CONFIG_FILES = [
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
    "dashboard_test_profiles.json",  # native UI 测试档案（保留防功能回归）
    "mode_evidence.json",  # dashboard facade 当前构建一致性证据
    "entitlement_public_keys.json",  # signed manifest 验证后读取的 permit key registry
]
# 保留在源码、不随包分发（无生产消费者）：
# vision_profiles.proposed.yaml / dashboard_mechanics.json / bond_knowledge.json /
# habit_preference.schema.json / challenge_boss_catalog.json；
# runtime_asset_manifest.json 仅被 tools/release_gate.py 从源码根读取。

a = Analysis(
    [str(PROJECT_ROOT / "desktop_app.py")],
    pathex=[str(PROJECT_ROOT / "src")],
    binaries=[
        (str(SHIBOKEN_DLL), "PySide6"),
        (str(PYSIDE_ABI_DLL), "PySide6"),
        *[(str(path), ".") for path in PYTHON_TLS_DLLS.values()],
    ],
    datas=[
        (str(PROJECT_ROOT / "assets"), "assets"),
        *[(str(PROJECT_ROOT / "config" / name), "config") for name in RUNTIME_CONFIG_FILES],
        (str(PROJECT_ROOT / "ui-v2" / "dist"), str(Path("web") / "dist")),
    ],
    hiddenimports=[
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebChannel",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(PROJECT_ROOT / "packaging" / "pyi_rth_pyside6_path.py")],
    excludes=["fastapi", "uvicorn", "webview"],
    noarchive=False,
    optimize=1,
)
# The host's Poppler runtime leaks an incompatible ICU DLL through PATH; Qt resolves
# the system ICU correctly when this foreign binary is not bundled.
a.binaries[:] = [entry for entry in a.binaries if entry[0].lower() != "icuuc.dll"]
# Also replace any copies selected during dependency analysis (including
# nested destinations), so collection cannot reintroduce a foreign pair.
a.binaries[:] = [
    (dest, str(PYTHON_TLS_DLLS[Path(dest).name.lower()]), kind)
    if Path(dest).name.lower() in PYTHON_TLS_DLLS else (dest, source, kind)
    for dest, source, kind in a.binaries
]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ShuaBao",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=str(PROJECT_ROOT / "assets" / "branding" / "app_logo.ico"),
    # KK 平台与游戏以管理员运行；正式包必须同级，否则 UIPI 会丢弃 SendInput。
    uac_admin=True,
    version=str(PROJECT_ROOT / "packaging" / "windows_version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="ShuaBao",
)
