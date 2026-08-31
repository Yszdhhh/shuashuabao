"""Qt-free LIVE worker body shared by RunnerService and HeadlessRunner."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from shuabao.log_sink import install_live_logging, uninstall_live_logging
from shuabao.settings import Settings
from shuabao.stop_signal import StopSignal
from shuabao.subscription_client import check_start_permission

LOGGER = logging.getLogger("ShuaBao")
LIVE_LOCK_NAME = "ShuaBao.live.lock"


def live_lock_path(app_data: Path) -> Path:
    return Path(app_data) / LIVE_LOCK_NAME


def execute_runtime_mediator(
    *,
    settings: Settings,
    root_dir: Path,
    incident_dir: str | Path,
    stop_signal: StopSignal,
    max_steps: int | None = None,
    log: Callable[[str, str], None] | None = None,
    should_abort: Callable[[], bool] | None = None,
    on_mediator: Callable[[Any], None] | None = None,
) -> dict[str, Any]:
    """Shared LIVE worker body: entitlement gate + RuntimeMediator + OCR + StopSignal.

    Entitlement is checked once, before RuntimeMediator is constructed.  The
    running worker is never polled or force-stopped because a subscription later
    changes state; the next LIVE start performs the next authoritative check.
    """
    result: dict[str, Any] = {
        "terminal_reason": "",
        "phase": "IDLE",
        "game_count": 0,
        "mediator": None,
        "ocr_status": "未启动",
        "subscription_status": "",
    }
    log_file = Path(incident_dir) / "live.log" if incident_dir else None
    sink, file_handler = install_live_logging(log=log, log_file=log_file)
    result["log_sink"] = sink
    mediator = None
    try:
        if should_abort and should_abort():
            result["terminal_reason"] = "启动前已请求停止"
            LOGGER.info("[启动] 已请求停止，取消本次启动")
            return result

        permission = check_start_permission()
        result["subscription_status"] = permission.status
        if permission.mode == "shadow":
            LOGGER.info(
                "[订阅][shadow] status=%s code=%s would_allow=%s",
                permission.status,
                permission.code,
                permission.would_allow,
            )
        elif permission.mode == "enforce":
            LOGGER.info(
                "[订阅][enforce] status=%s code=%s allowed=%s",
                permission.status,
                permission.code,
                permission.allowed,
            )
        if not permission.allowed:
            result["terminal_reason"] = (
                f"订阅未授权启动: {permission.status}/{permission.code}"
            )
            result["phase"] = "ERROR"
            LOGGER.error("[启动失败] %s", result["terminal_reason"])
            return result

        try:
            from shuabao.runtime_mediator import Mediator
        except Exception as exc:
            result["terminal_reason"] = f"RuntimeMediator 无法加载: {exc}"
            result["phase"] = "ERROR"
            LOGGER.error("[启动失败] RuntimeMediator 无法加载，LIVE 已拒绝启动: %s", exc)
            return result

        if should_abort and should_abort():
            result["terminal_reason"] = "启动前已请求停止"
            LOGGER.info("[启动] 已请求停止，取消本次启动")
            return result

        LOGGER.info("[live] execute_runtime_mediator start")
        mediator = Mediator(
            settings,
            root_dir,
            stop_signal=stop_signal,
            incident_dir=incident_dir,
        )
        result["mediator"] = mediator
        if on_mediator is not None:
            on_mediator(mediator)
        LOGGER.info("[live] RuntimeMediator ready")
        prepare = getattr(mediator, "prepare_live_dependencies", None)
        if not callable(prepare) or not prepare():
            health = getattr(mediator, "_ocr_bootstrap_health", None)
            result["terminal_reason"] = f"OCR不可用: {health}"
            result["ocr_status"] = "不可用"
            phase_val = getattr(mediator, "phase", None)
            result["phase"] = str(getattr(phase_val, "name", phase_val or "ERROR"))
            LOGGER.error("[启动失败] OCR True READY 未通过，LIVE 已拒绝启动: %s", health)
            return result
        health = getattr(mediator, "_ocr_bootstrap_health", None) or {}
        if health.get("skipped"):
            result["ocr_status"] = "模板模式（OCR未随包）" if health.get("reason") == "packaged_ocr_unavailable_template_mode" else "OCR已关闭"
        else:
            result["ocr_status"] = "就绪" if health.get("healthy", True) else "不可用"
        mediator.run(max_steps=max_steps)
    except Exception as exc:
        result["terminal_reason"] = f"任务异常退出: {exc}"
        LOGGER.exception("[异常] %s", result["terminal_reason"])
    finally:
        if mediator is not None:
            try:
                mediator.set_trace(None)
            except Exception:
                pass
            ocr_client = getattr(mediator, "_ocr_client", None)
            if ocr_client is not None:
                try:
                    ocr_client.close()
                except Exception:
                    LOGGER.exception("failed to close OCR sidecar")
        uninstall_live_logging(sink, file_handler)
        result["mediator"] = mediator
        result["game_count"] = getattr(mediator, "game_count", 0) if mediator else 0
        phase_val = getattr(mediator, "phase", None) if mediator else None
        result["phase"] = str(getattr(phase_val, "name", phase_val or result["phase"] or "IDLE"))
    return result


class PortableLiveLock:
    """QLockFile when Qt is up; flock/msvcrt otherwise. Same lock file name."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._qlock: Any = None
        self._fh: Any = None

    def try_lock(self, timeout_ms: int = 100) -> bool:
        try:
            from PySide6.QtCore import QLockFile as _QLockFile

            self._qlock = _QLockFile(str(self.path))
            if self._qlock.tryLock(int(timeout_ms)):
                return True
            self._qlock = None
            return False
        except Exception:
            self._qlock = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(self.path, "a+b")
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            if self._fh is not None:
                try:
                    self._fh.close()
                except Exception:
                    pass
                self._fh = None
            return False

    def unlock(self) -> None:
        if self._qlock is not None:
            try:
                self._qlock.unlock()
            except Exception:
                pass
            self._qlock = None
        if self._fh is not None:
            try:
                if os.name == "nt":
                    import msvcrt

                    self._fh.seek(0)
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                self._fh.close()
            except Exception:
                pass
            self._fh = None
