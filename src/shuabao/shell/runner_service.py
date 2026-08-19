"""唯一 LIVE 入口。托盘/热键/按钮都必须走这里。"""

from __future__ import annotations

import builtins
import copy
import logging
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, QThread, Signal

from shuabao.settings import Settings
from shuabao.stop_signal import StopSignal
from shuabao.shell.mode_catalog import apply_mode_overlay, desktop_may_start
from shuabao.shell.runtime_status import (
    RUNNER_IDLE,
    RUNNER_RUNNING,
    RUNNER_STARTING,
    RUNNER_STOPPING,
)

LOGGER = logging.getLogger("ShuaBao")
LIVE_LOCK_NAME = "ShuaBao.live.lock"


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
        try:
            from shuabao.runtime_mediator import Mediator
        except Exception as exc:
            LOGGER.exception("failed to import RuntimeMediator")
            self.terminal_reason = f"RuntimeMediator 无法加载: {exc}"
            self._emit_status(False, "ERROR", 0, terminal_reason=self.terminal_reason)
            self.signals.log_emitted.emit(
                f"[启动失败] RuntimeMediator 无法加载，LIVE 已拒绝启动: {exc}",
                "error",
            )
            return

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

        real_print = builtins.print
        def hook_print(*args, **kwargs):
            text = " ".join(str(x) for x in args)
            if sys.stdout is not None:
                real_print(*args, **kwargs)
            log_type = "info"
            if "失败" in text or "中断" in text or "错误" in text or "timeout" in text:
                log_type = "error"
            elif "警告" in text or "miss" in text:
                log_type = "warn"
            self.signals.log_emitted.emit(text, log_type)

        builtins.print = hook_print
        try:
            self.mediator = Mediator(
                self.settings,
                self.root_dir,
                stop_signal=self.stop_signal,
                incident_dir=self.incident_dir,
            )
            self._start_trace()
            prepare = getattr(self.mediator, "prepare_live_dependencies", None)
            if not callable(prepare) or not prepare():
                health = getattr(self.mediator, "_ocr_bootstrap_health", None)
                self.terminal_reason = f"OCR不可用: {health}"
                self._emit_status(
                    False, self._phase_name(), 0,
                    terminal_reason=self.terminal_reason,
                    ocr_status="不可用",
                    last_action=self._last_action(),
                )
                self.signals.log_emitted.emit(
                    f"[启动失败] OCR True READY 未通过，LIVE 已拒绝启动: {health}",
                    "error",
                )
                return
            health = getattr(self.mediator, "_ocr_bootstrap_health", None) or {}
            self.ocr_status = "就绪" if health.get("healthy", True) else "不可用"
            self._emit_status(True, self._phase_name(), 0, ocr_status=self.ocr_status)
            self.mediator.run(max_steps=self.max_steps)
        except Exception as exc:
            self.terminal_reason = f"任务异常退出: {exc}"
            self.signals.log_emitted.emit(f"[异常] {self.terminal_reason}", "error")
            LOGGER.exception("worker failed")
        finally:
            if self.mediator is not None:
                self.mediator.set_trace(None)
                ocr_client = getattr(self.mediator, "_ocr_client", None)
                if ocr_client is not None:
                    try:
                        ocr_client.close()
                    except Exception:
                        LOGGER.exception("failed to close OCR sidecar")
            builtins.print = real_print
            count = getattr(self.mediator, "game_count", 0) if self.mediator else 0
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


def live_lock_path(app_data: Path) -> Path:
    return Path(app_data) / LIVE_LOCK_NAME


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
        self.runner_state = RUNNER_STOPPING
        if self.worker is not None:
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
