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
    log_emitted = Signal(str, str)  # (text, level)
    status_changed = Signal(bool, str, int)  # (running, phase, game_count)


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
    def run(self):
        try:
            # LIVE 统一走 runtime_mediator：在 core Mediator 之上追加本局羁绊
            # 预设完成门闩，避免拿齐后继续按 F 抢占宝物/进化等调度窗口。
            from shuabao.runtime_mediator import Mediator
        except Exception as e:
            self.signals.log_emitted.emit(f"[错误] 无法加载 Mediator 自动化引擎: {e}", "error")
            self.signals.status_changed.emit(False, "错误", 0)
            return

        if self._stop_requested:
            self.signals.log_emitted.emit("[启动] 已请求停止，取消本次启动", "info")
            self.signals.status_changed.emit(False, "空闲", 0)
            return

        self.signals.status_changed.emit(True, "就绪", 0)
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
            self.mediator.run(max_steps=self.max_steps)
        except Exception as e:
            self.signals.log_emitted.emit(f"[异常] 任务异常退出: {e}", "error")
            LOGGER.exception("worker failed")
        finally:
            if self.mediator is not None:
                self.mediator.set_trace(None)
            builtins.print = real_print
            count = getattr(self.mediator, "game_count", 0) if self.mediator else 0
            self.signals.status_changed.emit(False, "空闲", count)
            self.signals.log_emitted.emit("[结束] 任务运行结束", "info")

    def _start_trace(self) -> str | None:
        try:
            now = datetime.now()
            trace_dir = self.incident_dir.parent / now.strftime("%Y%m%d")
            trace_path = trace_dir / f"trace_{now.strftime('%Y%m%d_%H%M%S')}.jsonl"
            self.mediator.set_trace(str(trace_path))
            self.signals.log_emitted.emit(f"[Trace] 自动 trace: {trace_path}", "info")
            return str(trace_path)
        except Exception as e:
            self.signals.log_emitted.emit(f"[Trace] 无法开启 trace: {e}", "error")
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
        lock = QLockFile(str(live_lock_path(self.app_data)))
        if not lock.tryLock(100):
            raise RuntimeError("ShuaBao.live.lock 已被占用（实验室或另一 LIVE）")
        self._live_lock = lock
        self.runner_state = RUNNER_STARTING
        self.mode_id = mode_id
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

    def started_settings(self) -> Settings | None:
        return self._started_settings
