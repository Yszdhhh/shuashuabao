"""Headless / API adapter over RunnerService safety semantics.

No GUI. Same lock + OCR bootstrap + StopSignal + incident archive +
RuntimeMediator path as the desktop LIVE entry.
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from shuabao.incidents import default_incident_dir
from shuabao.settings import Settings
from shuabao.stop_signal import StopSignal
from shuabao.shell.live_execute import (
    LIVE_LOCK_NAME,
    PermissionDenied,
    PortableLiveLock,
    execute_runtime_mediator,
    live_lock_path,
    start_permission_allows,
)
from shuabao.subscription_client import check_start_permission
from shuabao.shell.mode_catalog import apply_mode_overlay, desktop_may_start
from shuabao.shell.runtime_status import RUNNER_IDLE, RUNNER_RUNNING, RUNNER_STARTING, RUNNER_STOPPING

LOGGER = logging.getLogger("ShuaBao")


class ModeNotEnabled(RuntimeError):
    """未验证运行方式：零 Mediator、零输入。"""


def _ensure_qt_core() -> Any:
    try:
        from PySide6.QtCore import QCoreApplication

        app = QCoreApplication.instance()
        if app is None:
            app = QCoreApplication(["shuabao-headless"])
        return app
    except Exception as exc:
        LOGGER.info("headless Qt core unavailable: %s", exc)
        return None


class HeadlessRunner:
    """Service-mode LIVE runner. Prefer RunnerService; never skip lock/OCR/StopSignal."""

    def __init__(
        self,
        app_data: Path,
        root: Path,
        *,
        mode_id: str = "normal_farm",
    ) -> None:
        self.app_data = Path(app_data)
        self.root = Path(root)
        self.mode_id = mode_id
        self.runner_state = RUNNER_IDLE
        self.mediator: Any = None
        self.stop_signal = StopSignal()
        self.terminal_reason = ""
        self.phase = "IDLE"
        self.ocr_status = "未启动"
        self._lock: PortableLiveLock | None = None
        self._qt_app: Any = None

    def _prepare_settings(self, settings: Settings) -> Settings:
        if not desktop_may_start(self.mode_id):
            raise ModeNotEnabled(f"{self.mode_id} 未验证，不可从服务入口启动")
        snapshot = apply_mode_overlay(copy.deepcopy(settings), self.mode_id)
        return snapshot

    def _cancelled_start_result(self, log_fn: Callable[[str, str], None] | None) -> dict[str, Any]:
        reason = self.stop_signal.reason or "启动前已请求停止"
        self.terminal_reason = reason
        self.phase = "IDLE"
        if log_fn is not None:
            log_fn("[启动] 已请求停止，取消本次启动", "info")
        return {
            "terminal_reason": reason,
            "phase": "IDLE",
            "game_count": 0,
            "mediator": None,
            "ocr_status": self.ocr_status or "未启动",
        }

    def run_blocking(
        self,
        settings: Settings,
        *,
        max_steps: int | None = None,
        log_fn: Callable[[str, str], None] | None = None,
        on_mediator: Callable[[Any], None] | None = None,
        permission=None,
        permission_checker=None,
    ) -> dict[str, Any]:
        # Reuse the existing StopSignal. Minting a new one here would drop
        # HeadlessRunner.stop() / API STOPPING that fired during STARTING.
        if self.stop_signal.is_set() or self.stop_signal.is_stopped():
            return self._cancelled_start_result(log_fn)
        if permission is None and permission_checker is not None:
            permission = permission_checker()
        if permission is None:
            permission = check_start_permission()
        if not start_permission_allows(permission):
            raise PermissionDenied("订阅未授权，LIVE 已拒绝启动")

        snapshot = self._prepare_settings(settings)
        incident_dir = self.app_data / "incidents"
        incident_dir.mkdir(parents=True, exist_ok=True)

        if self.stop_signal.is_set() or self.stop_signal.is_stopped():
            return self._cancelled_start_result(log_fn)

        self.runner_state = RUNNER_STARTING
        self._qt_app = _ensure_qt_core()

        def _log(text: str, kind: str) -> None:
            if log_fn is not None:
                log_fn(text, kind)

        def _capture(med: Any) -> None:
            self.mediator = med
            if on_mediator is not None:
                on_mediator(med)

        return self._run_with_lock(
            snapshot,
            max_steps=max_steps,
            log_fn=_log,
            on_mediator=_capture,
            incident_dir=incident_dir,
            permission=permission,
        )

    def _run_with_lock(
        self,
        snapshot: Settings,
        *,
        max_steps: int | None,
        log_fn: Callable[[str, str], None],
        on_mediator: Callable[[Any], None],
        incident_dir: Path,
        permission,
    ) -> dict[str, Any]:
        if self.stop_signal.is_set() or self.stop_signal.is_stopped():
            return self._cancelled_start_result(log_fn)
        lock = PortableLiveLock(live_lock_path(self.app_data))
        if not lock.try_lock(100):
            raise RuntimeError("ShuaBao.live.lock 已被占用（实验室或另一 LIVE）")
        self._lock = lock
        self.runner_state = RUNNER_RUNNING
        try:
            result = execute_runtime_mediator(
                settings=snapshot,
                root_dir=self.root,
                incident_dir=incident_dir,
                stop_signal=self.stop_signal,
                max_steps=max_steps,
                log=log_fn,
                should_abort=lambda: self.stop_signal.is_set(),
                on_mediator=on_mediator,
                permission=permission,
            )
            self.mediator = result.get("mediator")
            self.terminal_reason = str(result.get("terminal_reason") or "")
            self.phase = str(result.get("phase") or "IDLE")
            self.ocr_status = str(result.get("ocr_status") or self.ocr_status)
            return result
        finally:
            lock.unlock()
            self._lock = None
            self.runner_state = RUNNER_IDLE

    def stop(self) -> None:
        self.runner_state = RUNNER_STOPPING
        self.stop_signal.trigger("HeadlessRunner stop requested")
        if self.mediator is not None:
            try:
                self.mediator.stop()
            except Exception:
                pass


def default_headless_app_data() -> Path:
    return default_incident_dir().parent


__all__ = [
    "HeadlessRunner",
    "LIVE_LOCK_NAME",
    "ModeNotEnabled",
    "default_headless_app_data",
]
