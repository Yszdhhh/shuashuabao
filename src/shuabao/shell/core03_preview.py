"""CORE03 交互预览启动入口：启动独立测试环境的 Dashboard 交互预览。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# 确保 repo 根目录与 src 在 sys.path
_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_SRC = _ROOT / "src"
for _p in (_ROOT, _SRC):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from PySide6.QtWidgets import QApplication
from shuabao.shell.main_window import MainWindow, APP_NAME


def run_preview(app_data: Path | None = None) -> int:
    """运行独立预览窗口。"""
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow(app_data=app_data)
    window.setWindowTitle(f"{APP_NAME} - CORE03 交互预览")
    window.show()
    return app.exec()


def main() -> int:
    """启动 CORE03 交互预览应用。"""
    app_data_dir = os.environ.get("LOCALAPPDATA")
    preview_data = (Path(app_data_dir) / "ShuaBao") if app_data_dir else (_ROOT / "测试夹" / "CORE03_DASHBOARD_PREVIEW")
    return run_preview(app_data=preview_data)


if __name__ == "__main__":
    sys.exit(main())
