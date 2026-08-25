"""唯一 LIVE 入口。托盘/热键/按钮都必须走这里。"""

from __future__ import annotations

import copy
import logging
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

    def start(self, mode_id: str, settings_snapshot: Settings) -> MediatorWorker:
        if not desktop_may_start(mode_id):
            raise ModeNotEnabled(f"{mode_id} 未验证，不可从看板启动")
        if self.worker is not None and self.worker.isRunning():
            raise RuntimeError("already running")
        snapshot = apply_mode_overlay(copy.deepcopy(settings_snapshot), mode_id)
        if mode_id == "follow_team":
            snapshot.cycle_num = int(snapshot.follow_cycle_num)
        elif mode_id == "lobby_hitch":
            snapshot.cycle_num = int(snapshot.hitch_cycle_num)
        snapshot.ocr_mode = "live"
        snapshot.ocr_repo_root = str(self.root)
        lock = QLockFile(str(live_lock_path(self.app_data)))
        if not lock.tryLock(100):
            raise RuntimeError("ShuaBao.live.lock 已被占用（实验室或另一 LIVE）")
        self._live_lock = lock
        self.runner_state = RUNNER_STARTING
        self.mode_id = mode_id
        self._started_settings = copy.deepcopy(snapshot)
        stop_signal = StopSignal()
        self.worker = MediatorWorker(
            snapshot,
            self.root,
            incident_dir=self.app_data / "incidents",
            stop_signal=stop_signal,
        )
        self.runner_state = RUNNER_RUNNING
        return self.worker

    def stop(self) -> None:
        if self.worker is None or not self.worker.isRunning():
            return
        self.runner_state = RUNNER_STOPPING
        self.worker.stop()

    def release_after_finish(self) -> None:
        if self._live_lock is not None:
            self._live_lock.unlock()
            self._live_lock = None
        self.runner_state = RUNNER_IDLE
        self.mode_id = None
        self._started_settings = None

    def started_settings(self) -> Settings | None:
        return self._started_settings
