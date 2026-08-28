# -*- mode: python ; coding: utf-8 -*-
"""Standalone PaddleOCR worker bundled beside ShuaBao.exe."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, copy_metadata


PROJECT_ROOT = Path(SPECPATH)

datas = [
    (str(PROJECT_ROOT / "config" / "choice_lexicon.json"), "config"),
    (str(PROJECT_ROOT / "models" / "ocr"), "models/ocr"),
]
binaries = []
# `collect_all("paddle")` imports optional TensorRT/JIT modules while scanning and
# crashes the scanner on Windows.  The worker imports only text recognition, so
# ship package data and native libraries without recursively importing optional
# backends.
for package in ("paddle", "paddleocr", "paddlex", "cv2", "PIL", "bidi", "pypdfium2"):
    datas += collect_data_files(package)
    binaries += collect_dynamic_libs(package)
for distribution in ("paddlepaddle", "paddleocr", "paddlex", "numpy", "opencv-contrib-python", "Pillow", "python-bidi", "pypdfium2"):
    datas += copy_metadata(distribution)
hiddenimports = [
    "paddle.base.libpaddle",
    "bidi.algorithm",
    "pypdfium2",
    "paddleocr._models.text_recognition",
    "paddlex.inference.models.text_recognition",
    "paddlex.inference.models.text_recognition.predictor",
    "paddlex.inference.models.runners.paddle_static",
    # cv2 still imports NumPy's legacy compatibility namespace at runtime.
    "numpy.core",
    "numpy.core.multiarray",
    "numpy.core._multiarray_umath",
    "numpy._core",
    "numpy._core.multiarray",
    "numpy._core._multiarray_umath",
]

a = Analysis(
    [str(PROJECT_ROOT / "ocr_worker_app.py")],
    pathex=[str(PROJECT_ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="ShuaBaoOCR",
)
