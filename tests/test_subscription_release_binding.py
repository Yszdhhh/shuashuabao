from __future__ import annotations

import json
import os
import base64
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from shuabao.shell import dashboard_facade as df_module
from shuabao.shell import live_execute
from shuabao.shell.dashboard_facade import DashboardFacade
from shuabao.subscription_client import StartPermission, check_start_permission, validate_entitlement
from shuabao.settings import Settings
from shuabao.subscription_permit import EntitlementPermit, InMemoryReplayStore
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


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
    monkeypatch.setattr(live_execute, "live_permit_request_context", context)
    monkeypatch.setattr(df_module, "check_start_permission", checker)
    monkeypatch.setenv("SHUABAO_SUBSCRIPTION_MODE", "enforce")

    first = facade._subscription_permission(force=True, mode_id="lobby_hitch")
    cached = facade._subscription_permission(mode_id="lobby_hitch")
    other_mode = facade._subscription_permission(mode_id="normal_farm")

    assert first is cached is other_mode is permission
    assert calls == [
        {"permit_request": {**PERMIT_REQUEST, "mode_id": "lobby_hitch"}},
        {"permit_request": {**PERMIT_REQUEST, "mode_id": "normal_farm"}},
    ]


@pytest.mark.parametrize("field,value", [
    ("source_sha", "not-a-source"),
    ("release_manifest_sha256", "manifest_stable_default"),
    ("release_channel", "stable"),
    ("mode_id", "unknown_mode"),
])
def test_malformed_release_identity_never_reaches_network(field, value):
    def opener(*_args, **_kwargs):
        pytest.fail("malformed release identity must fail before network")

    result = validate_entitlement(
        "test-key", env=ENFORCE_ENV, opener=opener,
        permit_request={**PERMIT_REQUEST, field: value},
    )
    assert result["code"] == "CONFIG_PERMIT_REQUEST_INVALID"


@pytest.mark.parametrize("identity", [
    live_execute._LiveIdentity("a" * 40, "b" * 64, "dev", False),
    live_execute._LiveIdentity("", "", "", True),
])
def test_live_entry_rejects_source_or_unverified_identity_without_query(monkeypatch, tmp_path, identity):
    monkeypatch.setenv("SHUABAO_SUBSCRIPTION_MODE", "enforce")
    monkeypatch.setattr(live_execute, "_live_identity", lambda _root: identity)

    def checker(**_kwargs):
        pytest.fail("no verified frozen identity must mean zero entitlement/permit requests")

    permission = live_execute.check_live_start_permission(tmp_path, "lobby_hitch", checker=checker)
    assert permission.allowed is False
    assert permission.code == "PERMIT_IDENTITY_UNTRUSTED"


@pytest.mark.parametrize("entry", ["dashboard", "runner", "headless", "native"])
def test_every_live_entry_sends_the_same_verified_identity(monkeypatch, qapp, tmp_path, entry):
    from shuabao.shell import headless_runner, main_window, runner_service

    identity = live_execute._LiveIdentity("a" * 40, "b" * 64, "dev", True)
    monkeypatch.setattr(live_execute, "_live_identity", lambda _root: identity)
    monkeypatch.setenv("SHUABAO_SUBSCRIPTION_MODE", "enforce")
    calls = []

    def checker(**kwargs):
        calls.append(kwargs)
        return StartPermission(False, "enforce", code="RELEASE_NOT_APPROVED")

    module = {"dashboard": df_module, "runner": runner_service, "headless": headless_runner, "native": main_window}[entry]
    monkeypatch.setattr(module, "check_start_permission", checker)
    if entry == "dashboard":
        DashboardFacade(tmp_path, SimpleNamespace(root=tmp_path))._subscription_permission(mode_id="lobby_hitch")
    elif entry == "runner":
        with pytest.raises(live_execute.PermissionDenied):
            runner_service.RunnerService(tmp_path, tmp_path).start("lobby_hitch", Settings())
    elif entry == "headless":
        with pytest.raises(live_execute.PermissionDenied):
            headless_runner.HeadlessRunner(tmp_path, tmp_path, mode_id="lobby_hitch").run_blocking(Settings())
    else:
        monkeypatch.setattr(main_window.QMessageBox, "warning", lambda *_args: None)
        window = SimpleNamespace(
            _is_running=lambda: False, selected_mode_id=lambda: "lobby_hitch",
            lbl_subscription=SimpleNamespace(setText=lambda _value: None),
            log=lambda *_args: None,
        )
        main_window.MainWindow.toggle_run(window)
    assert calls == [{"permit_request": PERMIT_REQUEST}]


@pytest.mark.parametrize("field,replacement", [
    ("source_sha", "c" * 40),
    ("release_manifest_sha256", "d" * 64),
    ("release_channel", "release"),
    ("mode_id", "normal_farm"),
    ("SHUABAO_SUBSCRIPTION_BASE_URL", "https://another.example"),
    ("SHUABAO_SUBSCRIPTION_DEVICE_FINGERPRINT", "another-device"),
    ("SHUABAO_SUBSCRIPTION_LICENSE_KEY", "another-key"),
])
def test_dashboard_cache_invalidates_each_authorization_binding(monkeypatch, qapp, tmp_path, field, replacement):
    for name, value in ENFORCE_ENV.items():
        monkeypatch.setenv(name, value)
    context = dict(PERMIT_REQUEST)
    monkeypatch.setattr(live_execute, "live_permit_request_context", lambda _root, mode: {**context, "mode_id": mode})
    monkeypatch.setattr(df_module, "live_permit_request_context", live_execute.live_permit_request_context)
    calls = []
    monkeypatch.setattr(df_module, "check_start_permission", lambda **kwargs: calls.append(kwargs) or StartPermission(False, "enforce"))
    facade = DashboardFacade(tmp_path, SimpleNamespace(root=tmp_path))
    first = facade._subscription_permission(mode_id="lobby_hitch")
    assert facade._subscription_permission(mode_id="lobby_hitch") is first
    if field.startswith("SHUABAO_"):
        monkeypatch.setenv(field, replacement)
    else:
        context[field] = replacement
    facade._subscription_permission(mode_id=context["mode_id"])
    assert len(calls) == 2
    assert "test-key" not in facade._subscription_cache_key


def test_dashboard_dto_drops_live_authorization_when_release_identity_changes(monkeypatch, qapp, tmp_path):
    for name, value in ENFORCE_ENV.items():
        monkeypatch.setenv(name, value)
    context = dict(PERMIT_REQUEST)
    facade = DashboardFacade(tmp_path, SimpleNamespace(root=tmp_path))
    monkeypatch.setattr(facade, "_permit_request_context", lambda _mode: dict(context))
    facade._subscription_cache = StartPermission(
        True, "enforce", status="ACTIVE", entitlement_valid=True,
    )
    facade._subscription_cache_key = facade._subscription_key(context)
    facade._subscription_cache_at = time.monotonic()
    facade._subscription_live_check = True, "PERMIT_VERIFIED", "LIVE permit 已验签"

    assert facade._subscription_dto()["live_authorized"] is True
    context["source_sha"] = "c" * 40
    changed = facade._subscription_dto()
    assert changed["entitlement_valid"] is True
    assert changed["live_authorized"] is False
    assert changed["live_code"] == "LIVE_PENDING"


def _signed_permission(monkeypatch, tmp_path, **overrides):
    key = Ed25519PrivateKey.generate()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    payload = {
        **_permit_payload(),
        "issued_at": (now - timedelta(seconds=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": (now + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **overrides,
    }
    payload.pop("signature")
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    payload["signature"] = base64.urlsafe_b64encode(key.sign(canonical)).rstrip(b"=").decode()
    identity = live_execute._LiveIdentity(
        "a" * 40, "b" * 64, "dev", True, tmp_path,
        tmp_path / "config/entitlement_public_keys.json", {"shuabao-test-1": key.public_key()},
    )
    monkeypatch.setenv("SHUABAO_SUBSCRIPTION_MODE", "enforce")
    monkeypatch.setattr(live_execute, "_live_identity", lambda _root: identity)
    monkeypatch.setattr(live_execute, "_device_fingerprint", lambda *_args, **_kwargs: "device-test")
    monkeypatch.setattr(live_execute, "_LIVE_REPLAY_STORE", InMemoryReplayStore())
    return StartPermission(
        True, "enforce", status="ACTIVE", permit=EntitlementPermit.from_mapping(payload),
        entitlement_valid=True,
    )


@pytest.mark.parametrize("change,expected", [
    ({"permit": None}, "PERMIT_MISSING"),
    ({"source_sha": "c" * 40}, "PERMIT_SOURCE_MISMATCH"),
])
def test_entitlement_valid_does_not_satisfy_live_preflight(monkeypatch, qapp, tmp_path, change, expected):
    permission = _signed_permission(monkeypatch, tmp_path, **{k: v for k, v in change.items() if k != "permit"})
    if "permit" in change:
        permission = replace(permission, permit=None)
    facade = DashboardFacade(tmp_path, SimpleNamespace(root=tmp_path))
    monkeypatch.setattr(df_module, "check_start_permission", lambda **_kwargs: permission)
    checks = json.loads(facade.validate_preflight(json.dumps("lobby_hitch")))["checks"]
    subscription = next(check for check in checks if check["id"] == "subscription")
    assert subscription["ok"] is False
    assert expected in subscription["detail"]


def test_denied_start_permission_cannot_be_overridden_by_a_valid_permit(monkeypatch, tmp_path):
    permission = _signed_permission(monkeypatch, tmp_path)
    denied = replace(permission, allowed=False, code="RELEASE_NOT_APPROVED")

    with pytest.raises(live_execute.PermissionDenied, match="RELEASE_NOT_APPROVED"):
        live_execute.resolve_live_permission(denied, mode_id="lobby_hitch", root=tmp_path)


def test_shadow_start_permission_never_authorizes_live_with_a_valid_permit(monkeypatch, tmp_path):
    permission = _signed_permission(monkeypatch, tmp_path)
    shadow = replace(permission, mode="shadow")

    with pytest.raises(live_execute.PermissionDenied, match="PERMIT_REQUIRED"):
        live_execute.resolve_live_permission(shadow, mode_id="lobby_hitch", root=tmp_path)


@pytest.mark.parametrize("code,label", [
    ("LIVE_PENDING", "LIVE 授权待校验"),
    ("RELEASE_NOT_APPROVED", "发行未批准"),
    ("PERMIT_MISSING", "permit 缺失"),
    ("PERMIT_SIGNATURE_INVALID", "permit 无效"),
    ("ENTITLEMENT_UNREACHABLE", "服务不可达"),
])
def test_preflight_distinguishes_authorization_failures(code, label, tmp_path):
    result = live_execute.live_permission_preflight(StartPermission(False, "enforce", code=code), mode_id="lobby_hitch", root=tmp_path)
    assert result[0] is False
    assert result[1] == code
    assert label in result[2]


def test_verified_preflight_does_not_consume_or_grant_execution_permit(monkeypatch, qapp, tmp_path):
    from shuabao.shell.runner_service import RunnerService

    permission = _signed_permission(monkeypatch, tmp_path)
    facade = DashboardFacade(tmp_path, SimpleNamespace(root=tmp_path))
    monkeypatch.setattr(df_module, "check_start_permission", lambda **_kwargs: permission)
    result = json.loads(facade.validate_preflight(json.dumps("lobby_hitch")))
    assert next(check for check in result["checks"] if check["id"] == "subscription")["ok"] is True
    inspection = live_execute._verify_live_permission(permission, mode_id="lobby_hitch", root=tmp_path, consume_replay=False)
    assert live_execute.start_permission_allows(inspection, root=tmp_path) is False
    runner = RunnerService(tmp_path, tmp_path)
    worker = runner.start("lobby_hitch", Settings(), permission=permission)
    try:
        assert live_execute.start_permission_allows(worker.permission, root=tmp_path) is True
    finally:
        runner.release_after_finish()
    with pytest.raises(live_execute.PermissionDenied, match="PERMIT_REPLAY"):
        runner.start("lobby_hitch", Settings(), permission=permission)
