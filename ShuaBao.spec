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

a = Analysis(
    [str(PROJECT_ROOT / "desktop_app.py")],
    pathex=[str(PROJECT_ROOT / "src")],
    binaries=[
        (str(SHIBOKEN_DLL), "PySide6"),
        (str(PYSIDE_ABI_DLL), "PySide6"),
    ],
    datas=[
        (str(PROJECT_ROOT / "assets"), "assets"),
        (str(PROJECT_ROOT / "config"), "config"),
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
    uac_admin=False,
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
