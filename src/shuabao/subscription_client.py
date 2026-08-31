"""Thin Subscription Lab client used only at LIVE start boundaries.

The production game FSM must never know about Keygen/FOSSBilling/Keygate.  This
module consumes only the normalized ShuaBao entitlement contract exposed by the
Subscription Lab bridge.

Pilot configuration is intentionally environment-only so license material is
not persisted in dashboard settings or committed files.
"""
from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass
from typing import Callable, Mapping, Any
from urllib import request as urllib_request

SUBSCRIPTION_MODE_ENV = "SHUABAO_SUBSCRIPTION_MODE"
SUBSCRIPTION_BASE_URL_ENV = "SHUABAO_SUBSCRIPTION_BASE_URL"
SUBSCRIPTION_LICENSE_KEY_ENV = "SHUABAO_SUBSCRIPTION_LICENSE_KEY"
SUBSCRIPTION_DEVICE_FP_ENV = "SHUABAO_SUBSCRIPTION_DEVICE_FINGERPRINT"
SUBSCRIPTION_TIMEOUT_ENV = "SHUABAO_SUBSCRIPTION_TIMEOUT_S"
VALID_MODES = {"off", "shadow", "enforce"}


@dataclass(frozen=True)
class StartPermission:
    allowed: bool
    mode: str
    status: str = "UNKNOWN"
    code: str = ""
    message: str = ""
    would_allow: bool | None = None


def _env_text(env: Mapping[str, str], key: str) -> str:
    return str(env.get(key, "") or "").strip()


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

    base_url = _env_text(source, SUBSCRIPTION_BASE_URL_ENV).rstrip("/")
    license_key = _env_text(source, SUBSCRIPTION_LICENSE_KEY_ENV)
    fingerprint = _env_text(source, SUBSCRIPTION_DEVICE_FP_ENV)
    if not base_url:
        return _deny(mode, "CONFIG_BASE_URL_MISSING", "订阅服务地址未配置")
    if not license_key:
        return _deny(mode, "CONFIG_LICENSE_MISSING", "本机订阅 License Key 未配置")
    if not fingerprint:
        return _deny(mode, "CONFIG_DEVICE_MISSING", "Pilot 设备指纹未配置")

    body = {
        "license_key": license_key,
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
    open_fn = opener or urllib_request.urlopen
    try:
        with open_fn(req, timeout=_timeout_seconds(source)) as response:
            raw = response.read().decode("utf-8")
        payload = json.loads(raw)
    except Exception as exc:
        return _deny(mode, "ENTITLEMENT_UNREACHABLE", f"订阅校验失败: {type(exc).__name__}")

    if not isinstance(payload, dict):
        return _deny(mode, "ENTITLEMENT_MALFORMED", "订阅服务返回非对象")
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
