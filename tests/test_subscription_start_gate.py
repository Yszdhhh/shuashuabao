from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.settings import Settings
from shuabao.stop_signal import StopSignal
from shuabao.subscription_client import check_start_permission
from shuabao.shell.live_execute import execute_runtime_mediator


BASE_ENV = {
    "SHUABAO_SUBSCRIPTION_BASE_URL": "http://127.0.0.1:8000",
    "SHUABAO_SUBSCRIPTION_LICENSE_KEY": "pilot-license",
    "SHUABAO_SUBSCRIPTION_DEVICE_FINGERPRINT": "pilot-device-01",
}


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def _opener(payload):
    def open_fn(req, timeout):
        assert req.full_url.endswith("/v1/entitlements/validate")
        assert timeout == 3.0
        body = json.loads(req.data.decode("utf-8"))
        assert body["license_key"] == "pilot-license"
        assert body["hardware"]["fingerprint"] == "pilot-device-01"
        return _Response(payload)

    return open_fn


def test_off_is_zero_network_and_allows_start():
    called = False

    def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("off mode must not use network")

    result = check_start_permission(
        env={"SHUABAO_SUBSCRIPTION_MODE": "off"}, opener=fail_if_called
    )
    assert result.allowed is True
    assert result.status == "OFF"
    assert called is False


def test_enforce_active_allows_start():
    env = {**BASE_ENV, "SHUABAO_SUBSCRIPTION_MODE": "enforce"}
    result = check_start_permission(
        env=env,
        opener=_opener({
            "valid": True,
            "status": "ACTIVE",
            "can_start_runner": True,
            "code": "VALID",
            "message": "ok",
        }),
    )
    assert result.allowed is True
    assert result.would_allow is True
    assert result.status == "ACTIVE"


def test_enforce_expired_denies_start():
    env = {**BASE_ENV, "SHUABAO_SUBSCRIPTION_MODE": "enforce"}
    result = check_start_permission(
        env=env,
        opener=_opener({
            "valid": False,
            "status": "EXPIRED",
            "can_start_runner": False,
            "code": "EXPIRED",
            "message": "expired",
        }),
    )
    assert result.allowed is False
    assert result.would_allow is False
    assert result.status == "EXPIRED"


def test_shadow_denial_records_but_does_not_block():
    env = {**BASE_ENV, "SHUABAO_SUBSCRIPTION_MODE": "shadow"}
    result = check_start_permission(
        env=env,
        opener=_opener({
            "valid": False,
            "status": "REVOKED",
            "can_start_runner": False,
            "code": "REVOKED",
            "message": "revoked",
        }),
    )
    assert result.allowed is True
    assert result.would_allow is False
    assert result.status == "REVOKED"


def test_enforce_transport_failure_is_fail_closed():
    env = {**BASE_ENV, "SHUABAO_SUBSCRIPTION_MODE": "enforce"}

    def broken(*args, **kwargs):
        raise TimeoutError("boom")

    result = check_start_permission(env=env, opener=broken)
    assert result.allowed is False
    assert result.code == "ENTITLEMENT_UNREACHABLE"


def test_enforce_missing_fingerprint_is_fail_closed():
    env = {
        "SHUABAO_SUBSCRIPTION_MODE": "enforce",
        "SHUABAO_SUBSCRIPTION_BASE_URL": "http://127.0.0.1:8000",
        "SHUABAO_SUBSCRIPTION_LICENSE_KEY": "pilot-license",
    }
    result = check_start_permission(env=env)
    assert result.allowed is False
    assert result.code == "CONFIG_DEVICE_MISSING"


def test_live_body_denial_returns_before_runtime_mediator_creation(tmp_path):
    denied = type(
        "Permission",
        (),
        {
            "allowed": False,
            "mode": "enforce",
            "status": "EXPIRED",
            "code": "EXPIRED",
            "message": "expired",
            "would_allow": False,
        },
    )()

    with patch("shuabao.shell.live_execute.check_start_permission", return_value=denied), \
         patch.dict(sys.modules, {"shuabao.runtime_mediator": None}):
        result = execute_runtime_mediator(
            settings=Settings(ocr_mode="off"),
            root_dir=ROOT,
            incident_dir=tmp_path,
            stop_signal=StopSignal(),
            max_steps=1,
        )

    assert result["phase"] == "ERROR"
    assert result["mediator"] is None
    assert result["subscription_status"] == "EXPIRED"
    assert result["terminal_reason"] == "订阅未授权启动: EXPIRED/EXPIRED"
