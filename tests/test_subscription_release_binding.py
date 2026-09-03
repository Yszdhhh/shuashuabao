from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from shuabao.shell import dashboard_facade as df_module
from shuabao.shell import live_execute
from shuabao.shell.dashboard_facade import DashboardFacade
from shuabao.subscription_client import StartPermission, check_start_permission, validate_entitlement


PERMIT_REQUEST = {
    "source_sha": "a" * 40,
    "release_manifest_sha256": "b" * 64,
    "release_channel": "dev",
    "mode_id": "lobby_hitch",
}
ENFORCE_ENV = {
    "SHUABAO_SUBSCRIPTION_MODE": "enforce",
    "SHUABAO_SUBSCRIPTION_BASE_URL": "http://127.0.0.1:8000",
    "SHUABAO_SUBSCRIPTION_LICENSE_KEY": "test-key",
    "SHUABAO_SUBSCRIPTION_DEVICE_FINGERPRINT": "device-test",
}


class _Response:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def _permit_payload() -> dict:
    return {
        "schema_version": 1,
        "product_id": "shuabao",
        "audience": "live-runner",
        "issuer": "shuabao-subscription",
        "permit_id": "permit-test",
        "jti": "permit-test",
        "license_id": "license-test",
        "device_id": "device-test",
        "device_fingerprint": "device-test",
        "release_channel": "dev",
        "source_sha": "a" * 40,
        "release_manifest_sha256": "b" * 64,
        "allowed_modes": ["lobby_hitch"],
        "features": ["automation"],
        "issued_at": "2026-09-03T12:00:00Z",
        "expires_at": "2026-09-03T12:15:00Z",
        "nonce": "nonce-test",
        "signature_algorithm": "Ed25519",
        "key_id": "shuabao-test-1",
        "signature": "c2ln",
    }


def test_validate_entitlement_sends_exact_release_bound_context() -> None:
    seen: list[dict] = []

    def opener(request, **_kwargs):
        seen.append(json.loads(request.data.decode("utf-8")))
        return _Response({"valid": False, "status": "EXPIRED", "can_start_runner": False})

    validate_entitlement(
        "test-key",
        env=ENFORCE_ENV,
        opener=opener,
        permit_request=PERMIT_REQUEST,
    )

    assert len(seen) == 1
    assert seen[0]["permit_request"] == PERMIT_REQUEST
    assert set(seen[0]) == {"license_key", "hardware", "permit_request"}


def test_validate_entitlement_rejects_malformed_context_before_network() -> None:
    called = False

    def opener(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("invalid permit request must not reach the network")

    result = validate_entitlement(
        "test-key",
        env=ENFORCE_ENV,
        opener=opener,
        permit_request={"source_sha": "a" * 40},
    )

    assert result["code"] == "CONFIG_PERMIT_REQUEST_INVALID"
    assert called is False


def test_check_start_permission_forwards_context_and_parses_permit() -> None:
    seen: list[dict] = []
    payload = {
        "valid": True,
        "can_start_runner": True,
        "status": "ACTIVE",
        "expires_at": "2026-12-31T00:00:00Z",
        "permit": _permit_payload(),
    }

    def opener(request, **_kwargs):
        seen.append(json.loads(request.data.decode("utf-8")))
        return _Response(payload)

    permission = check_start_permission(
        env=ENFORCE_ENV,
        opener=opener,
        permit_request=PERMIT_REQUEST,
    )

    assert permission.allowed is True
    assert permission.permit is not None
    assert permission.permit.release_channel == "dev"
    assert seen[0]["permit_request"] == PERMIT_REQUEST


def test_live_permit_context_comes_only_from_verified_packaged_identity(monkeypatch, tmp_path: Path) -> None:
    identity = live_execute._LiveIdentity(
        "a" * 40,
        "b" * 64,
        "dev",
        True,
        tmp_path,
        tmp_path / "config" / "entitlement_public_keys.json",
        {},
    )
    monkeypatch.setattr(live_execute, "_live_identity", lambda _root: identity)

    assert live_execute.live_permit_request_context(tmp_path, "lobby_hitch") == PERMIT_REQUEST

    monkeypatch.setattr(
        live_execute,
        "_live_identity",
        lambda _root: live_execute._LiveIdentity("", "", "", True),
    )
    assert live_execute.live_permit_request_context(tmp_path, "lobby_hitch") is None


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_dashboard_live_permission_cache_is_scoped_by_release_and_mode(
    monkeypatch,
    qapp,
    tmp_path: Path,
) -> None:
    runner = SimpleNamespace(root=tmp_path)
    facade = DashboardFacade(tmp_path, runner)
    calls: list[dict] = []
    permission = StartPermission(
        allowed=True,
        mode="enforce",
        status="ACTIVE",
        code="OK",
        would_allow=True,
        permit=None,
    )

    def context(_root: Path, mode_id: str):
        return {**PERMIT_REQUEST, "mode_id": mode_id}

    def checker(**kwargs):
        calls.append(kwargs)
        return permission

    monkeypatch.setattr(df_module, "live_permit_request_context", context)
    monkeypatch.setattr(df_module, "check_start_permission", checker)

    first = facade._subscription_permission(force=True, mode_id="lobby_hitch")
    cached = facade._subscription_permission(mode_id="lobby_hitch")
    other_mode = facade._subscription_permission(mode_id="normal_farm")

    assert first is cached is other_mode is permission
    assert calls == [
        {"permit_request": {**PERMIT_REQUEST, "mode_id": "lobby_hitch"}},
        {"permit_request": {**PERMIT_REQUEST, "mode_id": "normal_farm"}},
    ]
