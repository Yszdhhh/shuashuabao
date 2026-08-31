#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""刷刷宝入口。控制中心在 src/shuabao/shell/，此处再导出保住测试。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QLockFile
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "src"))

from shuabao.paths import migrate_legacy_data  # noqa: E402
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
    # 正式桌面入口必须校验订阅；测试/诊断可显式设置 off 或 shadow。
    had_subscription_mode = "SHUABAO_SUBSCRIPTION_MODE" in os.environ
    os.environ.setdefault("SHUABAO_SUBSCRIPTION_MODE", "enforce")
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    logo_ico = ROOT / "assets" / "branding" / "app_logo.ico"
    if not logo_ico.exists():
        logo_ico = ROOT / "assets" / "branding" / "app_logo.png"
    if logo_ico.exists():
        app.setWindowIcon(QIcon(str(logo_ico)))
    sys.excepthook = _handle_unhandled_exception

    APP_DATA.mkdir(parents=True, exist_ok=True)
    _INSTANCE_LOCK = QLockFile(str(APP_DATA / f"{APP_ID}.lock"))
    _INSTANCE_LOCK.setStaleLockTime(8000)
    _INSTANCE_LOCK.removeStaleLockFile()
    if not _INSTANCE_LOCK.tryLock(100):
        QMessageBox.information(None, APP_NAME, "程序已经在运行。若刚才已关掉窗口，请等几秒再开，或结束任务管理器里的 pythonw.exe。")
        if not had_subscription_mode:
            os.environ.pop("SHUABAO_SUBSCRIPTION_MODE", None)
        return

    # 旧数据目录一次性合并（幂等、只复制、不覆盖、不删源）；失败不阻塞启动。
    try:
        migrated = migrate_legacy_data(target_dir=APP_DATA)
        if migrated:
            LOGGER.info("[迁移] 目标=%s 合并 %d 项: %s", APP_DATA, len(migrated), ", ".join(migrated[:10]))
    except Exception:
        LOGGER.exception("[迁移] 旧目录合并失败（忽略，继续启动）")
    try:
        # 正式入口是 OD12 Web 看板；原生窗只保留给显式兼容诊断。Web 壳失败必须
        # 直接暴露错误，不能静默改成历史界面。
        shell_choice = os.environ.get("SHUABAO_SHELL", "web").strip().lower()
        if shell_choice == "native":
            window = MainWindow(app_data=APP_DATA)
        else:
            from shuabao.shell.web_config_shell import WebConfigShell

            window = WebConfigShell(app_data=APP_DATA, root=ROOT)
        window.show()
        sys.exit(app.exec())
    finally:
        if not had_subscription_mode:
            os.environ.pop("SHUABAO_SUBSCRIPTION_MODE", None)

if __name__ == "__main__":
    main()
