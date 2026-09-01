"""Qt-free LIVE worker body shared by RunnerService and HeadlessRunner."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from shuabao.log_sink import install_live_logging, uninstall_live_logging
from shuabao.subscription_client import (
    StartPermission,
    _device_fingerprint,
    subscription_mode,
)
from shuabao.subscription_permit import (
    DevStartCapability,
    EntitlementPermit,
    InMemoryReplayStore,
    PermitVerificationContext,
    PermitVerificationError,
    PermitVerifier,
    VerifiedPermit,
    load_public_keys,
)
LOGGER = logging.getLogger("ShuaBao")
LIVE_LOCK_NAME = "ShuaBao.live.lock"
_LIVE_REPLAY_STORE = InMemoryReplayStore()


def start_permission_allows(permission: Any) -> bool:
    """Only explicit dev capability or a verifier-produced permit can pass."""
    return isinstance(permission, (DevStartCapability, VerifiedPermit))


class PermissionDenied(RuntimeError):
    """订阅未授权：LIVE 入口 fail-closed，零 worker、零锁、零输入。"""


def _live_identity(root: Path) -> tuple[str, str, str]:
    source_sha = ""
    manifest_sha = ""
    release_channel = ""
    candidates = [Path(root)]
    executable_dir = Path(sys.executable).resolve().parent
    if executable_dir not in candidates:
        candidates.append(executable_dir)
    for candidate in candidates:
        try:
            payload = json.loads((candidate / "build_identity.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict):
            source_sha = str(payload.get("source_sha") or "").strip()
            manifest_sha = str(payload.get("release_manifest_sha256") or "").strip().lower()
            release_channel = str(payload.get("release_channel") or "").strip()
            if source_sha or manifest_sha or release_channel:
                break
    if not source_sha and (Path(root) / ".git").exists():
        try:
            proc = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=3,
                check=False,
            )
            if proc.returncode == 0:
                source_sha = proc.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return source_sha, manifest_sha, release_channel


def resolve_live_permission(permission: Any, *, mode_id: str, root: Path) -> DevStartCapability | VerifiedPermit:
    """Resolve status DTOs into an explicit LIVE authorization artifact."""
    if isinstance(permission, DevStartCapability):
        if subscription_mode(os.environ) == "off":
            return permission
        raise PermissionDenied("订阅未授权，LIVE 已拒绝启动: PERMIT_REQUIRED")
    if isinstance(permission, StartPermission):
        if permission.dev_capability is not None and subscription_mode(os.environ) == "off":
            return permission.dev_capability
        if permission.mode == "off":
            raise PermissionDenied("订阅未授权，LIVE 已拒绝启动: PERMIT_REQUIRED")
    permit = getattr(permission, "permit", None)
    if not isinstance(permit, EntitlementPermit):
        raise PermissionDenied("订阅未授权，LIVE 已拒绝启动: PERMIT_MISSING")
    source_sha, manifest_sha, identity_channel = _live_identity(Path(root))
    try:
        keys = load_public_keys(Path(root) / "config" / "entitlement_public_keys.json")
        context = PermitVerificationContext(
            device_id=_device_fingerprint(os.environ),
            source_sha=source_sha,
            release_manifest_sha256=manifest_sha,
            release_channel=str(os.environ.get("SHUABAO_RELEASE_CHANNEL") or identity_channel).strip(),
            mode_id=str(mode_id),
            now=datetime.now(timezone.utc),
        )
        return PermitVerifier(keys, replay_store=_LIVE_REPLAY_STORE).verify(permit, context)
    except PermitVerificationError as exc:
        raise PermissionDenied(f"订阅未授权，LIVE 已拒绝启动: {exc.code}") from exc


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
    permission: "DevStartCapability | VerifiedPermit | None" = None,
) -> dict[str, Any]:
    """Shared LIVE worker body: RuntimeMediator + OCR + StopSignal + LogEventSink."""
    result: dict[str, Any] = {
        "terminal_reason": "",
        "phase": "IDLE",
        "game_count": 0,
        "mediator": None,
        "ocr_status": "未启动",
    }
    if should_abort and should_abort():
        result["terminal_reason"] = "启动前已请求停止"
        LOGGER.info("[启动] 已请求停止，取消本次启动")
        return result
    if not start_permission_allows(permission):
        # fail-closed：直接调用且无有效权限时，不装日志、不建 Mediator、不初始化输入。
        result["terminal_reason"] = "订阅未授权，LIVE 已拒绝启动"
        result["phase"] = "ERROR"
        LOGGER.error("[启动失败] 订阅授权未通过，LIVE 已拒绝启动")
        return result
    log_file = Path(incident_dir) / "live.log" if incident_dir else None
    sink, file_handler = install_live_logging(log=log, log_file=log_file)
    result["log_sink"] = sink
    mediator = None
    try:
        try:
            from shuabao.runtime_mediator import Mediator
        except Exception as exc:
            result["terminal_reason"] = f"RuntimeMediator 无法加载: {exc}"
            result["phase"] = "ERROR"
            LOGGER.error("[启动失败] RuntimeMediator 无法加载，LIVE 已拒绝启动: %s", exc)
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
