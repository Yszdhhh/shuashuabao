"""Make PySide6 sibling DLLs discoverable before frozen imports begin."""

import os
import sys
from pathlib import Path


_pyside_dir = Path(sys._MEIPASS) / "PySide6"
if _pyside_dir.is_dir():
    os.add_dll_directory(str(_pyside_dir))
    os.environ["PATH"] = f"{_pyside_dir}{os.pathsep}{os.environ.get('PATH', '')}"
