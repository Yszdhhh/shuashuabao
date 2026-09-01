from __future__ import annotations

import json

from shuabao.subscription_client import validate_entitlement


class _Response:
    def __init__(self, payload: dict):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def test_validate_entitlement_promotes_nested_expiry_for_all_dashboard_shells():
    payload = validate_entitlement(
        "test-key",
        env={"SHUABAO_SUBSCRIPTION_BASE_URL": "http://127.0.0.1:8000", "SHUABAO_SUBSCRIPTION_DEVICE_FINGERPRINT": "device"},
        opener=lambda *_args, **_kwargs: _Response({
            "valid": True,
            "can_start_runner": True,
            "status": "ACTIVE",
            "license": {"expires_at": "2027-08-31T14:56:58Z"},
        }),
    )

    assert payload["expires_at"] == "2027-08-31T14:56:58Z"


def test_validate_entitlement_rejects_remote_plain_http_before_network():
    called = False

    def opener(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("network must not be attempted")

    payload = validate_entitlement(
        "test-key",
        env={"SHUABAO_SUBSCRIPTION_BASE_URL": "http://subscription.example", "SHUABAO_SUBSCRIPTION_DEVICE_FINGERPRINT": "device"},
        opener=opener,
    )

    assert payload["code"] == "CONFIG_BASE_URL_INVALID"
    assert called is False
