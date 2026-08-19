#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""刷刷宝入口。控制中心在 src/shuabao/shell/，此处再导出保住测试。"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QLockFile
from PySide6.QtWidgets import QApplication, QMessageBox

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "src"))

from shuabao.shell.main_window import (  # noqa: E402
    APP_DATA,
    APP_ID,
    APP_NAME,
    APP_VERSION_LABEL,
    FETTER_LABELS,
    LOGGER,
    LOG_FILE,
    MUST_TAKE_TREASURES,
    NEGATIVE_TREASURES,
    OFFICIAL_BUILDS,
    SKILL_LABELS,
    SKILL_META,
    SKILL_PRESETS,
    SKILL_STEMS,
    NegativeTreasureGroup,
    SkillArchiveLevelGrid,
    SkillCardGrid,
)
from shuabao.shell.smart_main_window import MainWindow  # noqa: E402
from shuabao.shell.runner_service import (  # noqa: E402
    LogSignal,
    MediatorWorker,
    ModeNotEnabled,
    RunnerService,
)

_INSTANCE_LOCK: QLockFile | None = None


def _handle_unhandled_exception(exc_type, exc_value, exc_traceback):
    LOGGER.error("未处理异常", exc_info=(exc_type, exc_value, exc_traceback))
    QMessageBox.critical(
        None,
        f"{APP_NAME} 启动失败",
        f"程序遇到异常，详情已写入：\n{LOG_FILE}\n\n{exc_value}",
    )


def main():
    global _INSTANCE_LOCK
    app = QApplication(sys.argv)
    sys.excepthook = _handle_unhandled_exception

    _INSTANCE_LOCK = QLockFile(str(APP_DATA / f"{APP_ID}.lock"))
    if not _INSTANCE_LOCK.tryLock(100):
        QMessageBox.information(None, APP_NAME, "程序已经在运行。")
        return

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
