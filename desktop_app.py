#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""刷刷宝入口。控制中心在 src/shuabao/shell/，此处再导出保住测试。"""

from __future__ import annotations

import os
import sys
import json
import argparse
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


def _load_packaged_subscription_config(root: Path) -> None:
    """Load sidecar deployment settings with frozen-channel fail-closed rules.

    External channels pin the sidecar endpoint and enforce subscription checks;
    dev/internal-pilot retain environment-first diagnostic behavior.  Missing
    or unknown channels also enforce in frozen packages.  The sidecar remains
    editable and unsigned, so external distribution still needs a signed
    manifest/Permit to prevent tampering.
    """
    if not getattr(sys, "frozen", False):
        return
    candidates = (
        Path(sys.executable).resolve().parent / "subscription_runtime.json",
        Path(root) / "subscription_runtime.json",
    )
    payload = None
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("schema_version") == 1:
            payload = data
            break
    if payload is None:
        os.environ["SHUABAO_SUBSCRIPTION_MODE"] = "enforce"
        return
    endpoint = str(payload.get("base_url") or "").strip()
    mode = str(payload.get("mode") or "").strip().lower()
    timeout = str(payload.get("timeout_s") or "").strip()
    channel = str(payload.get("release_channel") or "").strip().lower()
    if channel in {"external-beta", "release"}:
        # Empty sidecar endpoints must not fall through to env/default loopback.
        os.environ["SHUABAO_SUBSCRIPTION_BASE_URL"] = endpoint or "invalid-external-subscription-url"
        os.environ["SHUABAO_SUBSCRIPTION_MODE"] = "enforce"
    elif channel not in {"dev", "internal-pilot"}:
        if endpoint and "SHUABAO_SUBSCRIPTION_BASE_URL" not in os.environ:
            os.environ["SHUABAO_SUBSCRIPTION_BASE_URL"] = endpoint
        os.environ["SHUABAO_SUBSCRIPTION_MODE"] = "enforce"
    else:
        if endpoint and "SHUABAO_SUBSCRIPTION_BASE_URL" not in os.environ:
            os.environ["SHUABAO_SUBSCRIPTION_BASE_URL"] = endpoint
        if mode and "SHUABAO_SUBSCRIPTION_MODE" not in os.environ:
            os.environ["SHUABAO_SUBSCRIPTION_MODE"] = mode
    if timeout and "SHUABAO_SUBSCRIPTION_TIMEOUT_S" not in os.environ:
        os.environ["SHUABAO_SUBSCRIPTION_TIMEOUT_S"] = timeout


def _handle_unhandled_exception(exc_type, exc_value, exc_traceback):
    LOGGER.error("未处理异常", exc_info=(exc_type, exc_value, exc_traceback))
    QMessageBox.critical(
        None,
        f"{APP_NAME} 启动失败",
        f"程序遇到异常，详情已写入：\n{LOG_FILE}\n\n{exc_value}",
    )


def _write_subscription_check_report(path: Path, facade=None) -> bool:
    """Opt-in packaged smoke: verified TLS + the UI activation slot, never start a run.

    The key comes from the process environment/normal DPAPI load, not argv.
    Reports deliberately omit keys, device identifiers and free-form responses.
    """
    import ssl
    from shuabao.subscription_client import _subscription_ssl_context, _transport_error

    report = {"frozen": bool(getattr(sys, "frozen", False)),
              "executable": sys.executable, "openssl": ssl.OPENSSL_VERSION, "ok": False}
    try:
        context = _subscription_ssl_context()
        report["verified_tls"] = context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
        report["ca_count"] = len(context.get_ca_certs())
        report["ok"] = report["verified_tls"] and report["ca_count"] > 0
        if report["ok"] and facade is not None:
            result = json.loads(facade.activate_subscription(json.dumps({
                "key": os.environ.get("SHUABAO_SUBSCRIPTION_LICENSE_KEY", ""),
            })))
            report["ok"] = result.get("ok") is True
            report["status"] = result.get("status", "")
            report["expires_at"] = result.get("expires_at", "")
    except Exception as exc:
        report["ok"] = False
        report["error"] = _transport_error("订阅自检失败", exc)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report["ok"]


def main():
    global _INSTANCE_LOCK
    parser = argparse.ArgumentParser(add_help=False)
    checks = parser.add_mutually_exclusive_group()
    checks.add_argument("--tls-check-report", type=Path)
    checks.add_argument("--subscription-check-report", type=Path)
    args, _ = parser.parse_known_args()
    # 正式桌面入口必须校验订阅；测试/诊断可显式设置 off 或 shadow。
    _load_packaged_subscription_config(ROOT)
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

    if args.tls_check_report:
        sys.exit(0 if _write_subscription_check_report(args.tls_check_report) else 1)

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
        if shell_choice == "native" and not args.subscription_check_report:
            window = MainWindow(app_data=APP_DATA)
        else:
            from shuabao.shell.web_config_shell import WebConfigShell

            window = WebConfigShell(app_data=APP_DATA, root=ROOT)
        if args.subscription_check_report:
            ok = _write_subscription_check_report(args.subscription_check_report, window.facade)
            window.close()
            sys.exit(0 if ok else 1)
        window.show()
        sys.exit(app.exec())
    finally:
        if not had_subscription_mode:
            os.environ.pop("SHUABAO_SUBSCRIPTION_MODE", None)

if __name__ == "__main__":
    main()
