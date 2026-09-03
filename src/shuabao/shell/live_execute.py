"""Qt-free LIVE worker body shared by RunnerService and HeadlessRunner."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from shuabao.log_sink import install_live_logging, uninstall_live_logging
from shuabao.release_signing import ReleaseManifestError, canonical_manifest_sha256, verify_packaged_release_snapshot
from shuabao.subscription_client import (
    StartPermission,
    _device_fingerprint,
    _normalize_permit_request,
    check_start_permission,
    subscription_mode,
)
from shuabao.paths import get_canonical_app_data_dir
from shuabao.subscription_permit import (
    DevStartCapability,
    EntitlementPermit,
    InMemoryReplayStore,
    PersistentReplayStore,
    PermitVerificationContext,
    PermitVerificationError,
    PermitVerifier,
    VerifiedPermit,
    _load_public_keys_bytes,
    is_verified_permit,
)
LOGGER = logging.getLogger("ShuaBao")
LIVE_LOCK_NAME = "ShuaBao.live.lock"
LIVE_REPLAY_DB_NAME = "ShuaBao.live.replay.sqlite3"
_LIVE_REPLAY_STORE: InMemoryReplayStore | PersistentReplayStore | None = None
_TRUSTED_ISSUER_TOKEN = object()


@dataclass(frozen=True)
class _LiveIdentity:
    source_sha: str
    manifest_sha: str
    release_channel: str
    packaged: bool
    package_root: Path | None = None
    registry_path: Path | None = None
    registry_keys: Mapping[str, Ed25519PublicKey] | None = None


def _live_replay_store() -> InMemoryReplayStore | PersistentReplayStore:
    """Lazy cross-process replay store；初始化失败向上抛出，绝不静默回退内存存储。"""
    global _LIVE_REPLAY_STORE
    if _LIVE_REPLAY_STORE is None:
        _LIVE_REPLAY_STORE = PersistentReplayStore(
            get_canonical_app_data_dir() / LIVE_REPLAY_DB_NAME
        )
    return _LIVE_REPLAY_STORE

def start_permission_allows(permission: Any, *, root: Path | None = None) -> bool:
    """Only explicit off-mode dev capability or a verifier-produced permit can pass."""
    if isinstance(permission, DevStartCapability):
        if subscription_mode(os.environ) != "off" or root is None:
            return False
        identity = _live_identity(Path(root))
        return not identity.packaged and identity.release_channel in {"internal", "dev"}
    if not is_verified_permit(permission, issuer_token=_TRUSTED_ISSUER_TOKEN):
        return False
    try:
        return datetime.now(timezone.utc) <= permission.expires_at
    except (AttributeError, TypeError):
        return False


class PermissionDenied(RuntimeError):
    """订阅未授权：LIVE 入口 fail-closed，零 worker、零锁、零输入。"""


def _git_source_sha(root: Path) -> str:
    if not (root / ".git").exists():
        return ""
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
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _attested_registry_path(package_root: Path, manifest: dict[str, object]) -> Path:
    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise ValueError("manifest files 缺失")
    logical = "config/entitlement_public_keys.json"
    for entry in entries:
        if isinstance(entry, dict) and isinstance(entry.get("path"), str):
            relative = entry["path"].replace("\\", "/")
            if relative == logical or relative.endswith("/" + logical):
                return package_root / Path(entry["path"])
    raise ValueError("manifest 未绑定 entitlement registry")


def _live_identity(root: Path) -> _LiveIdentity:
    """Derive source identity from git or an authenticated frozen manifest."""
    if not getattr(sys, "frozen", False):
        source_sha = _git_source_sha(Path(root))
        return _LiveIdentity(
            source_sha,
            "",
            "internal" if source_sha else "",
            False,
            Path(root),
            Path(root) / "config" / "entitlement_public_keys.json",
        )

    package_root = Path(sys.executable).resolve().parent
    try:
        manifest, verified_files, _ = verify_packaged_release_snapshot(
            package_root,
            required_files=("config/entitlement_public_keys.json",),
        )
        source_sha = str(manifest.get("source_sha") or "").strip()
        channel = str(manifest.get("release_channel") or "").strip()
        actual_manifest_sha = canonical_manifest_sha256(manifest)
        if not source_sha or not channel:
            raise ValueError("签名 manifest 缺少 source_sha/release_channel")
        registry_path = _attested_registry_path(package_root, manifest)
        registry_key = str(registry_path.relative_to(package_root)).replace("\\", "/")
        registry_keys = _load_public_keys_bytes(verified_files[registry_key])
        return _LiveIdentity(
            source_sha,
            actual_manifest_sha,
            channel,
            True,
            package_root,
            registry_path,
            registry_keys,
        )
    except (OSError, ValueError, PermitVerificationError, ReleaseManifestError):
        return _LiveIdentity("", "", "", True)


def live_permit_request_context(root: Path, mode_id: str) -> dict[str, str] | None:
    """Return only an authenticated frozen release identity for permit issuance."""
    identity = _live_identity(Path(root))
    requested_mode = str(mode_id or "").strip()
    if (
        not identity.packaged
        or not identity.source_sha
        or not identity.manifest_sha
        or not identity.release_channel
        or not requested_mode
    ):
        return None
    context = {
        "source_sha": identity.source_sha,
        "release_manifest_sha256": identity.manifest_sha,
        "release_channel": identity.release_channel,
        "mode_id": requested_mode,
    }
    try:
        return _normalize_permit_request(context)
    except (TypeError, ValueError):
        return None


def check_live_start_permission(
    root: Path | None, mode_id: str, *, checker=None,
) -> StartPermission:
    """Every LIVE adapter uses the same authenticated request boundary."""
    checker = check_start_permission if checker is None else checker
    if subscription_mode() == "off":
        return checker()
    context = live_permit_request_context(root, mode_id) if root is not None else None
    if context is None:
        return StartPermission(
            False, subscription_mode(), code="PERMIT_IDENTITY_UNTRUSTED",
            message="发行身份未验证，LIVE 授权已阻断",
        )
    return checker(permit_request=context)


def resolve_live_permission(permission: Any, *, mode_id: str, root: Path) -> DevStartCapability | VerifiedPermit:
    """Resolve status DTOs into an explicit LIVE authorization artifact."""
    return _verify_live_permission(permission, mode_id=mode_id, root=root, consume_replay=True)


def live_permission_preflight(
    permission: StartPermission, *, mode_id: str, root: Path | None,
) -> tuple[bool, str, str]:
    """Verify readiness without consuming a permit or minting execution authority."""
    code = str(permission.code or "UNKNOWN")
    if permission.allowed:
        try:
            if root is None:
                # Injected source adapters may resolve their checkout at start.
                if (
                    permission.dev_capability is not None
                    and subscription_mode() == "off"
                    and not getattr(sys, "frozen", False)
                ):
                    return True, "DEV_OFF", "源码开发模式；LIVE 发行授权不适用"
                raise PermissionDenied("PERMIT_IDENTITY_UNTRUSTED")
            artifact = _verify_live_permission(
                permission, mode_id=mode_id, root=root, consume_replay=False,
            )
            if isinstance(artifact, DevStartCapability):
                return True, "DEV_OFF", "源码开发模式；LIVE 发行授权不适用"
            return True, "PERMIT_VERIFIED", "LIVE permit 已验签；启动时确认一次性授权"
        except PermissionDenied as exc:
            code = str(exc).rsplit(": ", 1)[-1]
    labels = {
        "LIVE_PENDING": "LIVE 授权待校验",
        "PERMIT_IDENTITY_UNTRUSTED": "发行身份未验证",
        "RELEASE_NOT_APPROVED": "发行未批准",
        "MODE_NOT_ALLOWED": "当前模式未批准",
        "PERMIT_MISSING": "permit 缺失",
        "ENTITLEMENT_UNREACHABLE": "服务不可达",
    }
    detail = labels.get(code)
    if detail is None:
        detail = "permit 无效" if code.startswith("PERMIT_") else (permission.message or "卡密未通过校验")
    return False, code, detail if code == "UNKNOWN" else f"{detail}（{code}）"


def _verify_live_permission(
    permission: Any, *, mode_id: str, root: Path, consume_replay: bool,
) -> DevStartCapability | VerifiedPermit:
    identity = _live_identity(Path(root))
    if isinstance(permission, StartPermission):
        # The server decision is authoritative.  A permit field on a denied
        # response must never be able to override ``allowed=False`` when a
        # caller invokes RunnerService/HeadlessRunner directly.  Shadow mode
        # records entitlement decisions only and cannot authorize LIVE.
        if not permission.allowed:
            code = str(permission.code or "PERMIT_REQUIRED")
            raise PermissionDenied(f"订阅未授权，LIVE 已拒绝启动: {code}")
        if permission.mode == "shadow":
            raise PermissionDenied("订阅未授权，LIVE 已拒绝启动: PERMIT_REQUIRED")
    dev_capability = permission if isinstance(permission, DevStartCapability) else None
    if isinstance(permission, StartPermission):
        dev_capability = permission.dev_capability
    if dev_capability is not None:
        if subscription_mode(os.environ) != "off":
            raise PermissionDenied("订阅未授权，LIVE 已拒绝启动: PERMIT_REQUIRED")
        if identity.packaged or identity.release_channel not in {"internal", "dev"}:
            raise PermissionDenied("订阅未授权，LIVE 已拒绝启动: PERMIT_DEV_PACKAGED")
        return dev_capability
    if isinstance(permission, StartPermission) and permission.mode == "off":
        raise PermissionDenied("订阅未授权，LIVE 已拒绝启动: PERMIT_REQUIRED")
    permit = getattr(permission, "permit", None)
    if not isinstance(permit, EntitlementPermit):
        raise PermissionDenied("订阅未授权，LIVE 已拒绝启动: PERMIT_MISSING")
    if (
        not identity.source_sha
        or not identity.manifest_sha
        or not identity.release_channel
        or identity.registry_path is None
        or identity.registry_keys is None
    ):
        raise PermissionDenied("订阅未授权，LIVE 已拒绝启动: PERMIT_IDENTITY_UNTRUSTED")
    try:
        context = PermitVerificationContext(
            device_id=_device_fingerprint(os.environ, allow_override=not identity.packaged),
            source_sha=identity.source_sha,
            release_manifest_sha256=identity.manifest_sha,
            release_channel=identity.release_channel,
            mode_id=str(mode_id),
            now=datetime.now(timezone.utc),
        )
        return PermitVerifier(
            identity.registry_keys,
            replay_store=_live_replay_store() if consume_replay else None,
            issuer_token=_TRUSTED_ISSUER_TOKEN if consume_replay else None,
        ).verify(permit, context)
    except PermitVerificationError as exc:
        raise PermissionDenied(f"订阅未授权，LIVE 已拒绝启动: {exc.code}") from exc
    except (OSError, sqlite3.Error) as exc:
        raise PermissionDenied(
            "订阅未授权，LIVE 已拒绝启动: PERMIT_REPLAY_STORE_UNAVAILABLE"
        ) from exc


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
    if not start_permission_allows(permission, root=root_dir):
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
