"""唯一 LIVE 入口。托盘/热键/按钮都必须走这里。

[Architecture & Boundary Statement]
RunnerService 当前运行于 Qt Host 进程内的托管 QThread (MediatorWorker)。
生命周期通过 RAII 锁持有、启动回滚、超时 terminate 兜底保证线程级可控，
但在遭遇底层 C/C++ 扩展或 Win32 原生死锁时无法实现 100% OS 进程隔离。
完全无损 OS 级隔离需后续迁移至独立 QProcess/Subprocess 模式。
"""

from __future__ import annotations

import copy
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QLockFile, QObject, QThread, Signal

from shuabao.settings import Settings
from shuabao.stop_signal import StopSignal
from shuabao.shell.live_execute import (
    LIVE_LOCK_NAME,
    execute_runtime_mediator,
    live_lock_path,
)
from shuabao.shell.mode_catalog import apply_mode_overlay, desktop_may_start
from shuabao.shell.runtime_status import (
    RUNNER_IDLE,
    RUNNER_RUNNING,
    RUNNER_STARTING,
    RUNNER_STOPPING,
)

LOGGER = logging.getLogger("ShuaBao")


class ModeNotEnabled(RuntimeError):
    """未验证运行方式：零 Mediator、零输入。"""


class LogSignal(QObject):
    log_emitted = Signal(str, str)
    # Kept at three arguments for existing shell/test integrations.
    status_changed = Signal(bool, str, int)
    # Detailed status: running, phase, game_count, terminal_reason,
    # ocr_status, last_action.
    status_updated = Signal(bool, str, int, str, str, str)


class MediatorWorker(QThread):
    def __init__(
        self,
        settings: Settings,
        root_dir: Path,
        max_steps: int | None = None,
        incident_dir: str | Path | None = None,
        stop_signal: StopSignal | None = None,
    ):
        super().__init__()
        self.settings = settings
        self.root_dir = root_dir
        self.max_steps = max_steps
        self.incident_dir = Path(incident_dir) if incident_dir else Path(root_dir) / "incidents"
        self.stop_signal = stop_signal or StopSignal()
        self.signals = LogSignal()
        self.mediator = None
        self._stop_requested = False
        self.terminal_reason = ""
        self.phase = "IDLE"
        self.ocr_status = "未启动"
        self.last_action = ""

    def _phase_name(self, mediator=None) -> str:
        value = getattr(mediator or self.mediator, "phase", None)
        return str(getattr(value, "name", value or self.phase or "IDLE"))

    def _last_action(self, mediator=None) -> str:
        med = mediator or self.mediator
        actions = getattr(med, "_trace_actions", None) if med is not None else None
        if actions and isinstance(actions[-1], dict):
            return str(actions[-1].get("reason") or actions[-1].get("action") or "")
        return str(getattr(med, "_tick_reason", "") or "") if med is not None else self.last_action

    def _terminal_reason_from_mediator(self) -> str:
        if self.terminal_reason:
            return self.terminal_reason
        if self._stop_requested:
            return "用户停止"
        med = self.mediator
        interrupt = str(getattr(med, "_interrupt_reason", "") or "") if med is not None else ""
        if interrupt:
            return interrupt
        phase = self._phase_name(med)
        if phase == "COMPLETE":
            return "已完成指定局数"
        stop_reason = str(getattr(self.stop_signal, "reason", "") or "")
        if stop_reason and stop_reason != "Mediator.stop()":
            return stop_reason
        if phase == "ERROR":
            return "运行错误"
        return "任务完成"

    def _emit_status(
        self,
        running: bool,
        phase: str,
        game_count: int = 0,
        *,
        terminal_reason: str = "",
        ocr_status: str = "",
        last_action: str = "",
    ) -> None:
        self.phase = str(phase or "IDLE")
        self.terminal_reason = str(terminal_reason or self.terminal_reason or "")
        if ocr_status:
            self.ocr_status = str(ocr_status)
        self.last_action = str(last_action or self.last_action or "")
        count = max(0, int(game_count or 0))
        self.signals.status_changed.emit(bool(running), self.phase, count)
        self.signals.status_updated.emit(
            bool(running), self.phase, count, self.terminal_reason,
            self.ocr_status, self.last_action,
        )

    def run(self):
        if self._stop_requested:
            self.terminal_reason = "启动前已请求停止"
            self._emit_status(False, "IDLE", 0, terminal_reason=self.terminal_reason)
            self.signals.log_emitted.emit("[启动] 已请求停止，取消本次启动", "info")
            return

        self._emit_status(True, "STARTING", 0, ocr_status="启动中")
        target = (self.settings.stage_targets or [
            f"{self.settings.stage1}-{self.settings.stage2}"
        ])[0]
        width, height = (self.settings.window_size or [1600, 900])[:2]
        difficulty = "英雄" if self.settings.auto_reputation else "普通"
        hero = (
            f"{self.settings.reputation_type}-{self.settings.reputation_level}"
            if self.settings.auto_reputation else "-"
        )
        learn = "开启" if self.settings.dry_run else "关闭"
        self.signals.log_emitted.emit(
            f"[启动] 刷图任务启动 | 学习模式={learn} | "
            f"关卡={target} | 关卡难度={difficulty} | 阵营={hero} | "
            f"分辨率={width}x{height} | 技能={self.settings.skills}",
            "info",
        )
        if self.settings.dry_run:
            self.signals.log_emitted.emit(
                "[学习模式] 只观察/记录，不向游戏发送真实点击",
                "info",
            )

        def _log(text: str, kind: str) -> None:
            self.signals.log_emitted.emit(text, kind)

        def _on_mediator(med: Any) -> None:
            self.mediator = med
            self._start_trace()

        result = execute_runtime_mediator(
            settings=self.settings,
            root_dir=self.root_dir,
            incident_dir=self.incident_dir,
            stop_signal=self.stop_signal,
            max_steps=self.max_steps,
            log=_log,
            should_abort=lambda: self._stop_requested,
            on_mediator=_on_mediator,
        )
        self.mediator = result.get("mediator") or self.mediator
        if result.get("ocr_status"):
            self.ocr_status = str(result["ocr_status"])
        if result.get("terminal_reason"):
            self.terminal_reason = str(result["terminal_reason"])
        count = int(result.get("game_count") or 0)
        reason = self._terminal_reason_from_mediator()
        self._emit_status(
            False, self._phase_name(), count,
            terminal_reason=reason,
            ocr_status=self.ocr_status,
            last_action=self._last_action(),
        )
        self.signals.log_emitted.emit(f"[结束] 任务运行结束（原因: {reason}）", "info")


    def _start_trace(self) -> str | None:
        try:
            now = datetime.now()
            trace_dir = self.incident_dir.parent / now.strftime("%Y%m%d")
            trace_path = trace_dir / f"trace_{now.strftime('%Y%m%d_%H%M%S')}.jsonl"
            self.mediator.set_trace(str(trace_path))
            self.signals.log_emitted.emit(f"[Trace] 自动 trace: {trace_path}", "info")
            return str(trace_path)
        except Exception as exc:
            self.signals.log_emitted.emit(f"[Trace] 无法开启 trace: {exc}", "error")
            return None

    def stop(self):
        self._stop_requested = True
        self.stop_signal.trigger("RunnerService stop requested")
        if self.mediator:
            self.mediator.stop()


def live_lock_busy(app_data: Path) -> bool:
    lock = QLockFile(str(live_lock_path(app_data)))
    if lock.tryLock(0):
        lock.unlock()
        return False
    return True


class RunnerService:
    """桌面唯一 LIVE 入口。未通过 desktop_may_start 则不创建 worker。"""

    def __init__(self, app_data: Path, root: Path):
        self.app_data = Path(app_data)
        self.root = Path(root)
        self.worker: MediatorWorker | None = None
        self.mode_id: str | None = None
        self.runner_state = RUNNER_IDLE
        self._live_lock: QLockFile | None = None
        self._started_settings: Settings | None = None
        # Entitlement gate — injected lazily from env; absent in disabled mode
        self._entitlement_service = None
        try:
            from shuabao.entitlement import EntitlementService
            self._entitlement_service = EntitlementService.from_env(data_dir=self.app_data / "entitlement")
        except Exception as _e:
            LOGGER.warning("EntitlementService init skipped: %s", _e)

    def _release_worker(self, worker: MediatorWorker) -> None:
        if self.worker is worker:
            self.release_after_finish(worker)

    def _wait_for_worker(self, worker: MediatorWorker, timeout_ms: int) -> None:
        try:
            if worker.wait(timeout_ms):
                return
            worker.terminate()
            if not worker.wait(timeout_ms):
                raise TimeoutError("RunnerService worker did not terminate")
        finally:
            if not worker.isRunning():
                self._release_worker(worker)

    def _reset_start_failure(self, lock: QLockFile) -> None:
        try:
            lock.unlock()
        finally:
            self._live_lock = None
            self.worker = None
            self.mode_id = None
            self.runner_state = RUNNER_IDLE
            self._started_settings = None


    def start(self, mode_id: str, settings_snapshot: Settings) -> MediatorWorker:
        if not desktop_may_start(mode_id):
            raise ModeNotEnabled(f"{mode_id} 未验证，不可从看板启动")
        if self.worker is not None:
            if self.worker.isRunning():
                raise RuntimeError("already running")
            self.release_after_finish(self.worker)
        # ── Entitlement gate ─────────────────────────────────────────────
        # Must run BEFORE lock acquisition and BEFORE MediatorWorker creation.
        # A running worker is never killed mid-run (mid-run expiry principle).
        if self._entitlement_service is not None:
            try:
                snap = self._entitlement_service.assert_start_allowed()
                LOGGER.info("entitlement gate: ALLOW status=%s source=%s", snap.status.value, snap.source)
            except Exception as _deny:
                LOGGER.warning("entitlement gate: DENY — %s", _deny)
                raise
        # ─────────────────────────────────────────────────────────────────
        snapshot = apply_mode_overlay(copy.deepcopy(settings_snapshot), mode_id)
        if mode_id == "follow_team":
            snapshot.cycle_num = int(snapshot.follow_cycle_num)
        elif mode_id == "lobby_hitch":
            snapshot.cycle_num = int(snapshot.hitch_cycle_num)
        lock = QLockFile(str(live_lock_path(self.app_data)))
        if not lock.tryLock(100):
            raise RuntimeError("ShuaBao.live.lock 已被占用（实验室或另一 LIVE）")
        try:
            self._live_lock = lock
            self.runner_state = RUNNER_STARTING
            self.mode_id = mode_id
            self._started_settings = copy.deepcopy(snapshot)
            worker = MediatorWorker(
                snapshot,
                self.root,
                incident_dir=self.app_data / "incidents",
                stop_signal=StopSignal(),
            )
            worker.finished.connect(lambda: self._release_worker(worker))
            self.worker = worker
            self.runner_state = RUNNER_RUNNING
            return worker
        except Exception:
            self._reset_start_failure(lock)
            raise

    def stop(self, timeout_ms: int | None = None) -> None:
        worker = self.worker
        if worker is None:
            return
        if not worker.isRunning():
            self._release_worker(worker)
            return
        self.runner_state = RUNNER_STOPPING
        try:
            worker.stop()
            if timeout_ms is not None:
                self._wait_for_worker(worker, max(0, int(timeout_ms)))
        finally:
            if not worker.isRunning():
                self._release_worker(worker)

    def release_after_finish(self, worker: MediatorWorker | None = None) -> None:
        if worker is not None and self.worker is not worker:
            return
        worker = worker or self.worker
        if worker is not None and worker.isRunning():
            return
        lock = self._live_lock
        try:
            if lock is not None:
                lock.unlock()
        finally:
            if self._live_lock is lock:
                self._live_lock = None
            self.runner_state = RUNNER_IDLE
            self.mode_id = None
            self._started_settings = None

    def started_settings(self) -> Settings | None:
        return self._started_settings
