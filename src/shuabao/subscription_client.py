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
import socket
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Any
from urllib import request as urllib_request

SUBSCRIPTION_MODE_ENV = "SHUABAO_SUBSCRIPTION_MODE"
SUBSCRIPTION_BASE_URL_ENV = "SHUABAO_SUBSCRIPTION_BASE_URL"
SUBSCRIPTION_LICENSE_KEY_ENV = "SHUABAO_SUBSCRIPTION_LICENSE_KEY"
SUBSCRIPTION_DEVICE_FP_ENV = "SHUABAO_SUBSCRIPTION_DEVICE_FINGERPRINT"
SUBSCRIPTION_TIMEOUT_ENV = "SHUABAO_SUBSCRIPTION_TIMEOUT_S"
VALID_MODES = {"off", "shadow", "enforce"}
DEFAULT_LOCAL_BRIDGE_URL = "http://127.0.0.1:8000"
_KEY_FILE_NAME = "subscription.key"


@dataclass(frozen=True)
class StartPermission:
    allowed: bool
    mode: str
    status: str = "UNKNOWN"
    code: str = ""
    message: str = ""
    would_allow: bool | None = None


def validate_entitlement(
    license_key: str,
    *,
    env: Mapping[str, str] | None = None,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Validate one user-entered key against the Bridge contract.

    The key is accepted only as an in-memory argument; callers decide whether
    to retain it for the current process.  Error payloads intentionally omit
    request data so a key cannot leak through UI/log messages.
    """
    source = os.environ if env is None else env
    base_url = _base_url(source)
    fingerprint = _device_fingerprint(source)
    key = str(license_key or "").strip()
    if not base_url:
        return {
            "valid": False, "status": "UNKNOWN", "code": "CONFIG_BASE_URL_MISSING",
            "message": "订阅服务地址未配置",
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
    body = {
        "license_key": key,
        "hardware": {
            "fingerprint": fingerprint,
            "components": {},
            "platform": "windows",
            "hostname": socket.gethostname() or None,
        },
    }
    req = urllib_request.Request(
        f"{base_url}/v1/entitlements/validate",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with (opener or urllib_request.urlopen)(req, timeout=_timeout_seconds(source)) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return {
            "valid": False, "status": "UNKNOWN", "code": "ENTITLEMENT_UNREACHABLE",
            "message": f"订阅校验失败: {type(exc).__name__}",
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
    fingerprint = _device_fingerprint(source)
    key = str(license_key or "").strip()
    if not base_url or not key or not fingerprint:
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
        with (opener or urllib_request.urlopen)(req, timeout=_timeout_seconds(source)) as response:
            return {"ok": True, "device": json.loads(response.read().decode("utf-8"))}
    except Exception as exc:
        return {"ok": False, "code": "DEVICE_ACTIVATION_FAILED", "message": f"设备激活失败: {type(exc).__name__}"}


def _env_text(env: Mapping[str, str], key: str) -> str:
    return str(env.get(key, "") or "").strip()


def _base_url(env: Mapping[str, str]) -> str:
    return (_env_text(env, SUBSCRIPTION_BASE_URL_ENV) or DEFAULT_LOCAL_BRIDGE_URL).rstrip("/")


def _device_fingerprint(env: Mapping[str, str]) -> str:
    configured = _env_text(env, SUBSCRIPTION_DEVICE_FP_ENV)
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


def _deny(mode: str, code: str, message: str, *, status: str = "UNKNOWN") -> StartPermission:
    if mode == "shadow":
        return StartPermission(
            allowed=True,
            mode=mode,
            status=status,
            code=code,
            message=message,
            would_allow=False,
        )
    return StartPermission(
        allowed=False,
        mode=mode,
        status=status,
        code=code,
        message=message,
        would_allow=False,
    )


def check_start_permission(
    *,
    env: Mapping[str, str] | None = None,
    opener: Callable[..., Any] | None = None,
) -> StartPermission:
    """Validate the local Pilot entitlement exactly once before LIVE begins.

    ``off`` performs zero network I/O. ``shadow`` records the authoritative
    decision but never blocks LIVE. ``enforce`` fails closed on missing config,
    transport failure, malformed JSON, or ``can_start_runner != true``.

    The Pilot fingerprint is caller-provided test identity.  It is deliberately
    not advertised as a production HWID collector.
    """
    source = os.environ if env is None else env
    mode = subscription_mode(source)
    if mode == "off":
        return StartPermission(allowed=True, mode=mode, status="OFF", code="OFF", would_allow=True)

    base_url = _base_url(source)
    license_key = _env_text(source, SUBSCRIPTION_LICENSE_KEY_ENV)
    fingerprint = _device_fingerprint(source)
    if not base_url:
        return _deny(mode, "CONFIG_BASE_URL_MISSING", "订阅服务地址未配置")
    if not license_key:
        return _deny(mode, "CONFIG_LICENSE_MISSING", "本机订阅 License Key 未配置")
    if not fingerprint:
        return _deny(mode, "CONFIG_DEVICE_MISSING", "Pilot 设备指纹未配置")

    payload = validate_entitlement(license_key, env=source, opener=opener)
    if payload.get("code") in {
        "CONFIG_BASE_URL_MISSING", "CONFIG_LICENSE_MISSING", "CONFIG_DEVICE_MISSING",
        "ENTITLEMENT_UNREACHABLE", "ENTITLEMENT_MALFORMED",
    }:
        return _deny(mode, str(payload.get("code")), str(payload.get("message") or "订阅校验失败"))
    status = str(payload.get("status") or "UNKNOWN")
    code = str(payload.get("code") or "UNKNOWN")
    message = str(payload.get("message") or "")
    would_allow = bool(payload.get("valid")) and payload.get("can_start_runner") is True
    if not would_allow:
        return _deny(mode, code, message or f"订阅状态不允许启动: {status}", status=status)
    return StartPermission(
        allowed=True,
        mode=mode,
        status=status,
        code=code,
        message=message,
        would_allow=True,
    )
