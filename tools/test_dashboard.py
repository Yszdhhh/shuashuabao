#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Thin zero-input Test Dashboard.

The dashboard displays canonical identity/readiness evidence and delegates
all live preparation and preflight decisions to the existing tools. It does
not inspect windows, OCR, or input surfaces itself.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from gt_test_identity import PRODUCTION_SHA, evaluate_test_candidate  # noqa: E402

from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

CANONICAL_CAPTURE_TOOL = ROOT / "tools" / "live_scenario_capture.py"
CANONICAL_ONE_CLICK = ROOT / "tools" / "one_click_test.ps1"
PROFILE_NAME = "海盗+亡灵机制GT"
TARGET_NAME = "solo_ingame_chain"


def _parse_json_object(output: str) -> dict[str, Any] | None:
    text = str(output or "").strip()
    if not text:
        return None
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        if start < 0:
            return None
        try:
            value, _end = json.JSONDecoder().raw_decode(text[start:])
        except json.JSONDecodeError:
            return None
    return value if isinstance(value, dict) else None


def _blocked_reasons(report: dict[str, Any] | None) -> list[str]:
    if not isinstance(report, dict):
        return ["canonical report unavailable"]
    reasons = [str(item) for item in report.get("blocked_reasons") or []]
    for key in ("harness_identity", "test_candidate_identity", "identity", "preflight"):
        nested = report.get(key)
        if isinstance(nested, dict):
            reasons.extend(str(item) for item in nested.get("blocked_reasons") or [])
    unique: list[str] = []
    for reason in reasons:
        if reason and reason not in unique:
            unique.append(reason)
    return unique or [f"canonical status={report.get('status', 'BLOCKED')}"]


def get_identity_info() -> dict[str, Any]:
    """Display the canonical Test-candidate identity, without reimplementing it."""
    report = evaluate_test_candidate(ROOT)
    imported = str(report.get("imported_shuabao") or "")
    expected = (ROOT / "src" / "shuabao").resolve()
    imported_path = Path(imported).resolve() if imported else None
    package_valid = bool(
        imported_path
        and (imported_path == expected / "__init__.py" or expected in imported_path.parents)
    )
    return {
        "root": str(ROOT),
        "test_head": str(report.get("test_sha") or "unknown"),
        "prod_base": str(report.get("production_sha") or PRODUCTION_SHA),
        "imported_shuabao": imported,
        "package_valid": package_valid,
        "candidate_status": report.get("status"),
        "candidate_reasons": list(report.get("blocked_reasons") or []),
    }


def run_canonical_readiness(test_sha: str | None = None) -> dict[str, Any]:
    """Call the existing offline GT readiness command and return its JSON."""
    expected_test_sha = test_sha or get_identity_info()["test_head"]
    command = [
        sys.executable,
        str(CANONICAL_CAPTURE_TOOL),
        "readiness",
        "--repo-root",
        str(ROOT),
        "--production-source-root",
        str(ROOT),
        "--production-source-sha",
        PRODUCTION_SHA,
        "--test-candidate-sha",
        expected_test_sha,
        "--quick",
        "--json",
    ]
    try:
        result = subprocess.run(command, cwd=str(ROOT), capture_output=True, text=True, check=False)
    except OSError as exc:
        return {"status": "BLOCKED", "blocked_reasons": [f"canonical readiness unavailable: {exc}"]}
    report = _parse_json_object(result.stdout)
    if report is None:
        detail = result.stderr.strip() or f"exit code {result.returncode}"
        return {"status": "BLOCKED", "blocked_reasons": [f"canonical readiness unavailable: {detail}"]}
    report["_command_exit_code"] = result.returncode
    return report


def run_canonical_prepare() -> dict[str, Any]:
    """Run the canonical one-click preparation only; it never starts capture."""
    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(CANONICAL_ONE_CLICK),
        "-PrepareOnly",
    ]
    try:
        result = subprocess.run(command, cwd=str(ROOT), capture_output=True, text=True, check=False)
    except OSError as exc:
        return {"status": "BLOCKED", "blocked_reasons": [f"canonical preparation unavailable: {exc}"]}

    session_line = next(
        (line.strip() for line in result.stdout.splitlines() if line.strip().startswith("SESSION=")),
        "",
    )
    if not session_line:
        detail = result.stderr.strip() or f"exit code {result.returncode}"
        return {"status": "BLOCKED", "blocked_reasons": [f"canonical preparation unavailable: {detail}"]}
    session_dir = Path(session_line.split("=", 1)[1].strip())
    manifest_path = session_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"status": "BLOCKED", "blocked_reasons": [f"canonical preparation manifest unavailable: {exc}"]}
    if not isinstance(manifest, dict):
        return {"status": "BLOCKED", "blocked_reasons": ["canonical preparation manifest is not an object"]}
    manifest["session_dir"] = str(session_dir)
    manifest["_command_exit_code"] = result.returncode
    return manifest


def run_canonical_preflight(manifest: dict[str, Any]) -> dict[str, Any]:
    """Call the canonical zero-input live preflight for the prepared session."""
    session_dir = Path(str(manifest.get("session_dir") or ""))
    settings_path = Path(str(manifest.get("settings_path") or session_dir / "settings.json"))
    test_sha = str(manifest.get("test_sha") or manifest.get("candidate_head_sha") or "")
    command = [
        sys.executable,
        str(CANONICAL_CAPTURE_TOOL),
        "preflight",
        "--repo-root",
        str(ROOT),
        "--settings",
        str(settings_path),
        "--target",
        TARGET_NAME,
        "--production-source-root",
        str(ROOT),
        "--production-source-sha",
        PRODUCTION_SHA,
        "--test-candidate-sha",
        test_sha,
        "--json",
    ]
    environment = os.environ.copy()
    app_data = manifest.get("app_data")
    if app_data:
        environment["SHUABAO_APP_DATA"] = str(app_data)
    environment["SHUABAO_PRODUCTION_SOURCE_ROOT"] = str(ROOT)
    environment["SHUABAO_PRODUCTION_SOURCE_SHA"] = PRODUCTION_SHA
    environment["SHUABAO_TEST_CANDIDATE_SHA"] = test_sha
    for key, manifest_key in (
        ("SHUABAO_OCR_PYTHON", "ocr_python_path"),
        ("SHUABAO_OCR_MODEL_DIR", "ocr_model_path"),
    ):
        value = manifest.get(manifest_key)
        if value:
            environment[key] = str(value)
    try:
        result = subprocess.run(
            command,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
            env=environment,
        )
    except OSError as exc:
        return {"status": "BLOCKED", "blocked_reasons": [f"canonical preflight unavailable: {exc}"]}
    report = _parse_json_object(result.stdout)
    if report is None:
        detail = result.stderr.strip() or f"exit code {result.returncode}"
        return {"status": "BLOCKED", "blocked_reasons": [f"canonical preflight unavailable: {detail}"]}
    report["_command_exit_code"] = result.returncode
    return report


def run_canonical_gt_readiness() -> dict[str, Any]:
    """Combine canonical readiness, preparation, and zero-input preflight."""
    readiness = run_canonical_readiness()
    if readiness.get("ready_for_gt") is not True:
        return {
            "status": "BLOCKED",
            "phase": "readiness",
            "readiness": readiness,
            "blocked_reasons": _blocked_reasons(readiness),
        }

    manifest = run_canonical_prepare()
    if manifest.get("status") != "READY" or manifest.get("cannot_start_gt") is True:
        return {
            "status": "BLOCKED",
            "phase": "prepare",
            "readiness": readiness,
            "manifest": manifest,
            "blocked_reasons": _blocked_reasons(manifest),
        }

    preflight = run_canonical_preflight(manifest)
    if preflight.get("status") != "READY":
        return {
            "status": "BLOCKED",
            "phase": "preflight",
            "readiness": readiness,
            "manifest": manifest,
            "preflight": preflight,
            "blocked_reasons": _blocked_reasons(preflight),
        }
    return {
        "status": "READY",
        "readiness": readiness,
        "manifest": manifest,
        "preflight": preflight,
        "blocked_reasons": [],
    }


def canonical_ready_for_start(report: dict[str, Any] | None) -> bool:
    """Use only the combined canonical result as the Start authority."""
    return isinstance(report, dict) and report.get("status") == "READY"


def launch_canonical_one_click(
    report: dict[str, Any] | None,
    popen: Callable[..., Any] = subprocess.Popen,
) -> bool:
    """Fail closed, then launch the canonical one-click script."""
    if not canonical_ready_for_start(report):
        return False
    popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(CANONICAL_ONE_CLICK),
        ],
        cwd=str(ROOT),
    )
    return True


class TestDashboardWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ShuaBao Test Dashboard · 海盗+亡灵机制 GT")
        self.resize(780, 680)
        self._last_readiness: dict[str, Any] | None = None
        self._init_ui()
        self.refresh_identity()
        self.do_preflight(silent=True)

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        header = QLabel(
            "ShuaBao Test Dashboard\n"
            "Test branch: test/pirate-necromancy-gt-20260917 | "
            "Production anchor: fix/solo-live-regression-20260915"
        )
        header.setStyleSheet("background: #2b303c; color: #ffffff; padding: 14px; font-size: 14px;")
        layout.addWidget(header)

        identity_group = QGroupBox("Canonical Identity")
        identity_grid = QGridLayout(identity_group)
        self.lbl_root = QLabel("读取中...")
        self.lbl_head = QLabel("读取中...")
        self.lbl_base = QLabel("读取中...")
        self.lbl_import = QLabel("读取中...")
        self.lbl_status = QLabel("读取中...")
        for row, label, widget in (
            (0, "Test worktree", self.lbl_root),
            (1, "Test HEAD SHA", self.lbl_head),
            (2, "Production anchor SHA", self.lbl_base),
            (3, "Imported shuabao", self.lbl_import),
            (4, "GT Test Candidate", self.lbl_status),
        ):
            identity_grid.addWidget(QLabel(label), row, 0)
            identity_grid.addWidget(widget, row, 1)
        layout.addWidget(identity_group)

        profile_group = QGroupBox("Active Test Profile")
        profile_layout = QVBoxLayout(profile_group)
        profile_layout.addWidget(QLabel(PROFILE_NAME))
        profile_layout.addWidget(QLabel("目标：solo_ingame_chain；准备阶段只生成 isolated session evidence。"))
        layout.addWidget(profile_group)

        preflight_group = QGroupBox("Canonical Readiness / Preflight")
        preflight_layout = QVBoxLayout(preflight_group)
        self.lbl_pre_status = QLabel("状态：检测中...")
        self.lbl_pre_detail = QLabel("")
        self.lbl_pre_detail.setWordWrap(True)
        preflight_layout.addWidget(self.lbl_pre_status)
        preflight_layout.addWidget(self.lbl_pre_detail)
        layout.addWidget(preflight_group)

        buttons = QHBoxLayout()
        self.btn_preflight = QPushButton("刷新 canonical 预检（ZERO INPUT）")
        self.btn_preflight.clicked.connect(lambda: self.do_preflight(silent=False))
        buttons.addWidget(self.btn_preflight)
        self.btn_start = QPushButton("开始 canonical one-click")
        self.btn_start.setEnabled(False)
        self.btn_start.clicked.connect(self.on_start_test_clicked)
        buttons.addWidget(self.btn_start, 1)
        layout.addLayout(buttons)

        layout.addWidget(QLabel("执行日志（本 Dashboard 不发送游戏输入）"))
        self.log_txt = QPlainTextEdit()
        self.log_txt.setReadOnly(True)
        self.log_txt.setStyleSheet("background: #f8f9fa; font-family: Consolas, monospace; font-size: 12px;")
        layout.addWidget(self.log_txt, 1)

    def log(self, message: str) -> None:
        self.log_txt.appendPlainText(message)

    def refresh_identity(self) -> None:
        info = get_identity_info()
        self.lbl_root.setText(info["root"])
        self.lbl_head.setText(f"{info['test_head']} (Test HEAD)")
        self.lbl_base.setText(f"{info['prod_base']} (Production anchor)")
        import_status = "OK" if info["package_valid"] else "BLOCKED"
        self.lbl_import.setText(f"{info['imported_shuabao']} [{import_status}]")
        self.lbl_status.setText(str(info["candidate_status"]))
        self.log(f"[identity] Test HEAD: {info['test_head']}")
        self.log(f"[identity] Production anchor: {info['prod_base']}")
        self.log(f"[identity] Candidate status: {info['candidate_status']}")

    def do_preflight(self, silent: bool = False) -> dict[str, Any]:
        report = run_canonical_gt_readiness()
        self._last_readiness = report
        allowed = canonical_ready_for_start(report)
        self.btn_start.setEnabled(allowed)
        if allowed:
            preflight = report.get("preflight") or {}
            window = preflight.get("window") or {}
            ocr = preflight.get("ocr_bootstrap_health") or {}
            surface = preflight.get("start_surface") or {}
            lane = preflight.get("single_instance") or {}
            self.lbl_pre_status.setText("状态：READY（canonical）")
            self.lbl_pre_status.setStyleSheet("color: #188038; font-weight: bold;")
            self.lbl_pre_detail.setText(
                f"window={window.get('status')} hwnd={window.get('hwnd')} | "
                f"OCR={ocr.get('healthy')} | start_surface={surface.get('status')} | "
                f"single_instance={lane.get('status')}"
            )
            self.lbl_pre_detail.setStyleSheet("color: #188038;")
            self.log("[canonical] readiness/preparation/preflight = READY")
        else:
            reasons = _blocked_reasons(report)
            detail = "\n".join(f"• {reason}" for reason in reasons)
            self.lbl_pre_status.setText(f"状态：BLOCKED（{report.get('phase', 'canonical')}）")
            self.lbl_pre_status.setStyleSheet("color: #d93025; font-weight: bold;")
            self.lbl_pre_detail.setText(detail)
            self.lbl_pre_detail.setStyleSheet("color: #d93025;")
            self.log(f"[canonical] BLOCKED: {'; '.join(reasons)}")
            if not silent:
                QMessageBox.warning(self, "Canonical preflight blocked", detail)
        return report

    def on_start_test_clicked(self) -> None:
        report = self.do_preflight(silent=False)
        if not canonical_ready_for_start(report):
            self.log("[fail-closed] canonical readiness != READY; Popen skipped; ZERO INPUT")
            return
        try:
            launch_canonical_one_click(report)
        except OSError as exc:
            self.log(f"[blocked] canonical one-click launch failed: {exc}")
            QMessageBox.critical(self, "启动失败", str(exc))
            return
        self.log("[start] canonical one-click launched after canonical READY")


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("ShuaBao-Test-Dashboard")
    logo_ico = ROOT / "assets" / "branding" / "app_logo.ico"
    if logo_ico.exists():
        app.setWindowIcon(QIcon(str(logo_ico)))
    window = TestDashboardWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
