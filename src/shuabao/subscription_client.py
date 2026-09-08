"""Thin Subscription Lab client used only at LIVE start boundaries.

The production game FSM must never know about Keygen/FOSSBilling/Keygate.  This
module consumes only the normalized ShuaBao entitlement contract exposed by the
Subscription Lab bridge.

Pilot configuration is intentionally environment-only so license material is
not persisted in dashboard settings or committed files.
"""
from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
import re
import socket
import sys
import uuid
from dataclasses import dataclass
import ssl
from pathlib import Path
from typing import Callable, Mapping, Any
from urllib import request as urllib_request
from urllib.error import URLError
from urllib.parse import urlsplit
from shuabao.subscription_permit import (
    DevStartCapability,
    EntitlementPermit,
    PermitVerificationError,
)

SUBSCRIPTION_MODE_ENV = "SHUABAO_SUBSCRIPTION_MODE"
SUBSCRIPTION_BASE_URL_ENV = "SHUABAO_SUBSCRIPTION_BASE_URL"
SUBSCRIPTION_LICENSE_KEY_ENV = "SHUABAO_SUBSCRIPTION_LICENSE_KEY"
SUBSCRIPTION_DEVICE_FP_ENV = "SHUABAO_SUBSCRIPTION_DEVICE_FINGERPRINT"
SUBSCRIPTION_TIMEOUT_ENV = "SHUABAO_SUBSCRIPTION_TIMEOUT_S"
VALID_MODES = {"off", "shadow", "enforce"}
PERMIT_REQUEST_FIELDS = (
    "source_sha",
    "release_manifest_sha256",
    "release_channel",
    "mode_id",
)
LIVE_MODE_IDS = frozenset({"normal_farm", "lobby_hitch", "follow_team", "lead_team"})
DEFAULT_LOCAL_BRIDGE_URL = "https://quebec-luis-flooring-kenneth.trycloudflare.com"

_KEY_FILE_NAME = "subscription.key"
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


@dataclass(frozen=True)
class StartPermission:
    allowed: bool
    mode: str
    status: str = "UNKNOWN"
    code: str = ""
    message: str = ""
    would_allow: bool | None = None
    expires_at: str = ""
    permit: EntitlementPermit | None = None
    dev_capability: DevStartCapability | None = None
    # Entitlement status is independent of a verified, release-bound LIVE permit.
    entitlement_valid: bool = False


def _subscription_ssl_context() -> ssl.SSLContext:
    """Use the Windows trust store in source and frozen desktop builds."""
    return ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH)


def _transport_error(prefix: str, exc: Exception) -> str:
    if isinstance(exc, URLError) and isinstance(exc.reason, Exception):
        exc = exc.reason
    if isinstance(exc, ssl.SSLCertVerificationError):
        return f"{prefix}: TLS 证书验证失败"
    if isinstance(exc, ssl.SSLError):
        # Only OpenSSL's symbolic error codes are safe to display; never echo
        # arbitrary exception text, which may contain request data.
        codes = [str(getattr(exc, field, "") or "") for field in ("library", "reason")]
        codes = [code for code in codes if code and all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for c in code)]
        detail = f" ({'/'.join(codes)})" if codes else ""
        return f"{prefix}: TLS 初始化/连接失败{detail}"
    return f"{prefix}: {type(exc).__name__}"


def _normalize_permit_request(
    value: Mapping[str, object] | None,
) -> dict[str, str] | None:
    """Return the exact server permit-request shape or reject it before I/O."""
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != set(PERMIT_REQUEST_FIELDS):
        raise ValueError("permit request fields mismatch")
    normalized: dict[str, str] = {}
    for field in PERMIT_REQUEST_FIELDS:
        raw = value.get(field)
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError(f"permit request field invalid: {field}")
        normalized[field] = raw.strip()
    if (
        not re.fullmatch(r"[0-9a-f]{40}", normalized["source_sha"])
        or not re.fullmatch(r"[0-9a-f]{64}", normalized["release_manifest_sha256"])
        or normalized["release_channel"] not in {"dev", "internal-pilot", "external-beta", "release"}
        or normalized["mode_id"] not in LIVE_MODE_IDS
    ):
        raise ValueError("permit request release identity invalid")
    return normalized


def validate_entitlement(
    license_key: str,
    *,
    env: Mapping[str, str] | None = None,
    opener: Callable[..., Any] | None = None,
    permit_request: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Validate one user-entered key against the Bridge contract.

    The key is accepted only as an in-memory argument; callers decide whether
    to retain it for the current process.  Error payloads intentionally omit
    request data so a key cannot leak through UI/log messages.
    """
    source = os.environ if env is None else env
    base_url = _base_url(source)
    fingerprint = _device_fingerprint(source, allow_override=not getattr(sys, "frozen", False))
    key = str(license_key or "").strip()
    if not base_url:
        code = _base_url_error(source)
        return {
            "valid": False, "status": "UNKNOWN", "code": code,
            "message": "订阅服务地址未配置" if code.endswith("MISSING") else "订阅服务地址必须使用 HTTPS 或 loopback HTTP",
        }
    if not key:
        return {
            "valid": False, "status": "UNKNOWN", "code": "CONFIG_LICENSE_MISSING",
            "message": "请输入 License Key",
        }
    if not fingerprint:
        return {
            "valid": False, "status": "UNKNOWN", "code": "CONFIG_DEVICE_MISSING",
            "message": "Pilot 设备指纹未配置",
        }
    try:
        normalized_permit_request = _normalize_permit_request(permit_request)
    except (TypeError, ValueError):
        return {
            "valid": False,
            "status": "UNKNOWN",
            "code": "CONFIG_PERMIT_REQUEST_INVALID",
            "message": "LIVE permit 发行身份字段无效",
        }
    body: dict[str, object] = {
        "license_key": key,
        "hardware": {
            "fingerprint": fingerprint,
            "components": {},
            "platform": "windows",
            "hostname": socket.gethostname() or None,
        },
    }
    if normalized_permit_request is not None:
        body["permit_request"] = normalized_permit_request
    req = urllib_request.Request(
        f"{base_url}/v1/entitlements/validate",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        if opener:
            resp_cm = opener(req, timeout=_timeout_seconds(source))
        else:
            resp_cm = urllib_request.urlopen(
                req, timeout=_timeout_seconds(source), context=_subscription_ssl_context()
            )
        with resp_cm as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return {
            "valid": False, "status": "UNKNOWN", "code": "ENTITLEMENT_UNREACHABLE",
            "message": _transport_error("订阅校验失败", exc),
        }
    if not isinstance(payload, dict):
        return {
            "valid": False, "status": "UNKNOWN", "code": "ENTITLEMENT_MALFORMED",
            "message": "订阅服务返回非对象",
        }
    license_data = payload.get("license")
    if not payload.get("expires_at") and isinstance(license_data, dict):
        payload["expires_at"] = license_data.get("expires_at") or ""
    return payload


def activate_device(
    license_key: str,
    *,
    env: Mapping[str, str] | None = None,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Bind a user-entered key to the configured Pilot device once."""
    source = os.environ if env is None else env
    base_url = _base_url(source)
    fingerprint = _device_fingerprint(source, allow_override=not getattr(sys, "frozen", False))
    key = str(license_key or "").strip()
    if not base_url:
        code = _base_url_error(source)
        return {
            "ok": False,
            "code": code,
            "message": "订阅服务地址未配置" if code.endswith("MISSING") else "订阅服务地址必须使用 HTTPS 或 loopback HTTP",
        }
    if not key or not fingerprint:
        return {"ok": False, "code": "CONFIG_MISSING", "message": "订阅服务、密钥或设备指纹未配置"}
    hardware = {
        "fingerprint": fingerprint,
        "components": {},
        "platform": "windows",
        "hostname": socket.gethostname() or None,
    }
    req = urllib_request.Request(
        f"{base_url}/v1/devices/activate",
        data=json.dumps({"license_key": key, "hardware": hardware}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        if opener:
            resp_cm = opener(req, timeout=_timeout_seconds(source))
        else:
            resp_cm = urllib_request.urlopen(
                req, timeout=_timeout_seconds(source), context=_subscription_ssl_context()
            )
        with resp_cm as response:
            return {"ok": True, "device": json.loads(response.read().decode("utf-8"))}
    except Exception as exc:
        return {"ok": False, "code": "DEVICE_ACTIVATION_FAILED", "message": _transport_error("设备激活失败", exc)}


def _env_text(env: Mapping[str, str], key: str) -> str:
    return str(env.get(key, "") or "").strip()


def _base_url(env: Mapping[str, str]) -> str:
    raw = _env_text(env, SUBSCRIPTION_BASE_URL_ENV) or DEFAULT_LOCAL_BRIDGE_URL
    try:
        parsed = urlsplit(raw)
        host = (parsed.hostname or "").lower().rstrip(".")
        # Credentials in a subscription URL are never needed and can leak via
        # logs/proxies.  Plain HTTP is restricted to the local bridge; remote
        # endpoints must use TLS.
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return ""
        if parsed.username or parsed.password:
            return ""
        if parsed.scheme == "http" and host not in _LOOPBACK_HOSTS:
            return ""
        return raw.rstrip("/")
    except (TypeError, ValueError):
        return ""


def _base_url_error(env: Mapping[str, str]) -> str:
    configured = _env_text(env, SUBSCRIPTION_BASE_URL_ENV)
    return "CONFIG_BASE_URL_INVALID" if configured else "CONFIG_BASE_URL_MISSING"


def _device_fingerprint(env: Mapping[str, str], *, allow_override: bool = True) -> str:
    """生产调用方可显式 allow_override=False 禁用环境变量指纹覆盖（fail-closed）；
    源码/dev 测试保持默认 True 可注入。"""
    configured = _env_text(env, SUBSCRIPTION_DEVICE_FP_ENV) if allow_override else ""
    if configured:
        return configured
    machine_guid = ""
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:
                machine_guid = str(winreg.QueryValueEx(key, "MachineGuid")[0])
        except OSError:
            pass
    seed = machine_guid or f"{uuid.getnode()}:{socket.gethostname()}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _key_path(app_data: Path) -> Path:
    return Path(app_data) / _KEY_FILE_NAME


def load_saved_license_key(app_data: Path) -> str:
    """Read the current user's DPAPI-protected license key, never settings JSON."""
    try:
        blob = base64.b64decode(_key_path(app_data).read_bytes())
        return _crypt_data(blob, protect=False).decode("utf-8").strip()
    except (OSError, ValueError, UnicodeDecodeError):
        return ""


def save_license_key(app_data: Path, license_key: str) -> bool:
    """Persist only a Windows-user-encrypted key after server validation succeeds."""
    try:
        protected = _crypt_data(license_key.encode("utf-8"), protect=True)
        path = _key_path(app_data)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64encode(protected))
        return True
    except (OSError, ValueError):
        return False


def _crypt_data(value: bytes, *, protect: bool) -> bytes:
    if os.name != "nt" or not value:
        raise ValueError("Windows DPAPI unavailable")

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    raw = (ctypes.c_byte * len(value)).from_buffer_copy(value)
    source = DATA_BLOB(len(value), raw)
    target = DATA_BLOB()
    call = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    if not call(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(target)):
        raise OSError("Windows DPAPI operation failed")
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(target.pbData)


def subscription_mode(env: Mapping[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    mode = _env_text(source, SUBSCRIPTION_MODE_ENV).lower() or "off"
    return mode if mode in VALID_MODES else "enforce"


def _timeout_seconds(env: Mapping[str, str]) -> float:
    raw = _env_text(env, SUBSCRIPTION_TIMEOUT_ENV)
    try:
        value = float(raw) if raw else 3.0
    except ValueError:
        value = 3.0
    return max(0.5, min(10.0, value))


def _deny(
    mode: str, code: str, message: str, *, status: str = "UNKNOWN",
    entitlement_valid: bool = False,
) -> StartPermission:
    if mode == "shadow":
        return StartPermission(
            allowed=True,
            mode=mode,
            status=status,
            code=code,
            message=message,
            would_allow=False,
            entitlement_valid=entitlement_valid,
        )
    return StartPermission(
        allowed=False,
        mode=mode,
        status=status,
        code=code,
        message=message,
        would_allow=False,
        entitlement_valid=entitlement_valid,
    )


def check_start_permission(
    *,
    env: Mapping[str, str] | None = None,
    opener: Callable[..., Any] | None = None,
    permit_request: Mapping[str, object] | None = None,
) -> StartPermission:
    """Validate the local Pilot entitlement exactly once before LIVE begins.

    ``off`` performs zero network I/O and only yields an explicit dev capability.
    ``shadow`` records the authoritative decision but never grants LIVE
    authorization. ``enforce`` fails closed on missing config, transport failure,
    malformed JSON, or ``can_start_runner != true``.

    The Pilot fingerprint is caller-provided test identity.  It is deliberately
    not advertised as a production HWID collector.
    """
    source = os.environ if env is None else env
    mode = subscription_mode(source)
    if mode == "off":
        return StartPermission(
            allowed=True,
            mode=mode,
            status="OFF",
            code="OFF",
            would_allow=True,
            dev_capability=DevStartCapability.for_off(),
        )

    license_key = _env_text(source, SUBSCRIPTION_LICENSE_KEY_ENV)
    base_url = _base_url(source)
    fingerprint = _device_fingerprint(source, allow_override=not getattr(sys, "frozen", False))
    if not base_url:
        code = _base_url_error(source)
        return _deny(
            mode,
            code,
            "订阅服务地址未配置" if code.endswith("MISSING") else "订阅服务地址必须使用 HTTPS 或 loopback HTTP",
        )
    if not license_key:
        return _deny(mode, "CONFIG_LICENSE_MISSING", "本机订阅 License Key 未配置")
    if not fingerprint:
        return _deny(mode, "CONFIG_DEVICE_MISSING", "Pilot 设备指纹未配置")

    if permit_request is None:
        payload = validate_entitlement(license_key, env=source, opener=opener)
    else:
        payload = validate_entitlement(
            license_key,
            env=source,
            opener=opener,
            permit_request=permit_request,
        )
    if payload.get("code") in {
        "CONFIG_BASE_URL_MISSING", "CONFIG_LICENSE_MISSING", "CONFIG_DEVICE_MISSING",
        "CONFIG_BASE_URL_INVALID", "CONFIG_PERMIT_REQUEST_INVALID",
        "ENTITLEMENT_UNREACHABLE", "ENTITLEMENT_MALFORMED",
    }:
        return _deny(mode, str(payload.get("code")), str(payload.get("message") or "订阅校验失败"))
    status = str(payload.get("status") or "UNKNOWN")
    code = str(payload.get("code") or "UNKNOWN")
    message = str(payload.get("message") or "")
    would_allow = bool(payload.get("valid")) and payload.get("can_start_runner") is True
    if not would_allow:
        return _deny(
            mode, code, message or f"订阅状态不允许启动: {status}", status=status,
            entitlement_valid=bool(payload.get("valid")),
        )
    raw_permit = payload.get("permit")
    if raw_permit is None:
        return _deny(
            mode,
            "PERMIT_MISSING",
            "订阅服务未返回 permit；enforce 模式必须返回有效签名 permit",
            status=status,
            entitlement_valid=True,
        )
    try:
        permit = EntitlementPermit.from_mapping(raw_permit)
    except PermitVerificationError as exc:
        return _deny(mode, exc.code, exc.message, status=status, entitlement_valid=True)
    return StartPermission(
        allowed=True,
        mode=mode,
        status=status,
        code=code,
        message=message,
        would_allow=True,
        expires_at=str(payload.get("expires_at") or ""),
        permit=permit,
        entitlement_valid=True,
    )
