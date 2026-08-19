# -*- mode: python ; coding: utf-8 -*-
"""Standalone ShuaBao OCR sidecar build.

Build this spec with the dedicated .venv-ocr interpreter.  The executable is a
console application so stdin/stdout JSONL pipes work, but the parent launches
it with CREATE_NO_WINDOW/SW_HIDE so users never see a console window.
"""

from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules


PROJECT_ROOT = Path(SPECPATH)

hiddenimports = []
for package in ("paddle", "paddleocr", "paddlex"):
    hiddenimports += collect_submodules(package)

datas = [
    (str(PROJECT_ROOT / "config" / "choice_lexicon.json"), "config"),
]
for package in ("paddleocr", "paddlex"):
    datas += collect_data_files(package)


a = Analysis(
    [str(PROJECT_ROOT / "ocr_worker_app.py")],
    pathex=[str(PROJECT_ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PySide6", "fastapi", "uvicorn", "webview"],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ShuaBaoOCR",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="ShuaBaoOCR",
)
