"""Closure A regression: formal web dashboard restarts recover saved授权.

Covers the seven required startup scenarios:
1. fresh install / no key        -> 未激活, zero network
2. saved ACTIVE credential       -> boot auto-validation restores 卡密有效
3. saved expired credential      -> 已过期, never auto-activates
4. backend unreachable           -> 网络异常, saved key untouched
5. release not approved          -> 发行未批准, distinct from 未激活
6. reopen formal dashboard       -> no card re-entry, no re-activate/rebind
7. start_run still re-probes LIVE permission with force=True
"""

import json
import os
import time
from pathlib import Path

import pytest

from shuabao.subscription_client import StartPermission, SUBSCRIPTION_LICENSE_KEY_ENV
from shuabao.shell import dashboard_facade as df_module
from shuabao.shell.dashboard_facade import DashboardFacade

PERMIT_REQUEST = {
    "source_sha": "a" * 40,
    "release_manifest_sha256": "b" * 64,
    "release_channel": "dev",
}


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture()
def enforce_env(monkeypatch):
    monkeypatch.setenv("SHUABAO_SUBSCRIPTION_MODE", "enforce")
    monkeypatch.setenv(SUBSCRIPTION_LICENSE_KEY_ENV, "saved-test-key")
    monkeypatch.setenv("SHUABAO_SUBSCRIPTION_DEVICE_FINGERPRINT", "fp-test")
    monkeypatch.delenv("SHUABAO_SUBSCRIPTION_BASE_URL", raising=False)
    return monkeypatch


@pytest.fixture()
def forbid_activation(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise AssertionError("startup validation must never activate/rebind")

    monkeypatch.setattr(df_module, "activate_device", _boom)


def _stub_permission(monkeypatch, **permission_kwargs):
    seen: list[dict] = []
    monkeypatch.setattr(
        df_module,
        "live_permit_request_context",
        lambda root, mode: {**PERMIT_REQUEST, "mode_id": mode},
    )

    def _checker(**kwargs):
        seen.append(kwargs)
        return StartPermission(**permission_kwargs)

    monkeypatch.setattr(df_module, "check_start_permission", _checker)

    def _live(root, mode_id, *, checker=None):
        return checker(permit_request={**PERMIT_REQUEST, "mode_id": mode_id})

    monkeypatch.setattr(df_module, "check_live_start_permission", _live)
    return seen


def _stub_preflight(monkeypatch, result):
    monkeypatch.setattr(df_module, "live_permission_preflight", lambda *a, **k: result)


def _wait(qapp, cond, timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if cond():
            return True
        qapp.processEvents()
        time.sleep(0.01)
    return False


def _subscription(facade: DashboardFacade) -> dict:
    return json.loads(facade.get_snapshot())["subscription"]


def test_fresh_install_without_key_shows_unactivated_and_no_network(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("SHUABAO_SUBSCRIPTION_MODE", "enforce")
    monkeypatch.delenv(SUBSCRIPTION_LICENSE_KEY_ENV, raising=False)
    calls = _stub_permission(
        monkeypatch,
        allowed=False, mode="enforce", status="UNKNOWN", code="CONFIG_LICENSE_MISSING",
        message="本机订阅 License Key 未配置",
    )
    f = DashboardFacade(tmp_path)
    sub = _subscription(f)
    assert sub["status"] == "未激活"
    assert sub["active"] is False
    assert calls == []


def test_saved_active_credential_recovers_on_boot(qapp, tmp_path, enforce_env, forbid_activation):
    calls = _stub_permission(
        enforce_env,
        allowed=True, mode="enforce", status="ACTIVE", code="OK",
        message="ok", would_allow=True, entitlement_valid=True,
    )
    _stub_preflight(enforce_env, (True, "PERMIT_VERIFIED", "LIVE permit 已验签"))
    f = DashboardFacade(tmp_path)
    assert f.refresh_subscription_status()  # explicit boot call
    assert _wait(qapp, lambda: f._subscription_cache is not None)

    sub = _subscription(f)
    assert sub["active"] is True
    assert sub["entitlement_valid"] is True
    assert sub["live_authorized"] is True
    assert sub["status"] == "卡密有效"
    assert calls, "boot validation must probe once"


def test_saved_expired_credential_maps_to_expired_without_reactivation(
    qapp, tmp_path, enforce_env, forbid_activation
):
    _stub_permission(
        enforce_env,
        allowed=False, mode="enforce", status="EXPIRED", code="EXPIRED",
        message="订阅已过期", entitlement_valid=False,
    )
    _stub_preflight(enforce_env, (False, "EXPIRED", "订阅已过期"))
    f = DashboardFacade(tmp_path)
    f.refresh_subscription_status()
    assert _wait(qapp, lambda: f._subscription_cache is not None)

    sub = _subscription(f)
    assert sub["active"] is False
    assert sub["status"] == "已过期"
    assert sub["status"] != "未激活"


def test_backend_unreachable_maps_to_network_error_and_keeps_saved_key(
    qapp, tmp_path, enforce_env, forbid_activation
):
    _stub_permission(
        enforce_env,
        allowed=False, mode="enforce", status="UNKNOWN",
        code="ENTITLEMENT_UNREACHABLE", message="订阅校验失败: timeout",
    )
    _stub_preflight(enforce_env, (False, "ENTITLEMENT_UNREACHABLE", "服务不可达"))
    f = DashboardFacade(tmp_path)
    f.refresh_subscription_status()
    assert _wait(qapp, lambda: f._subscription_cache is not None)

    sub = _subscription(f)
    assert sub["active"] is False
    assert sub["status"] == "网络异常"
    assert sub["status"] != "未激活"
    assert f._subscription_key(), "saved key must survive transport failure"


def test_backend_transport_failure_is_fail_closed_network_error(
    qapp, tmp_path, enforce_env, forbid_activation
):
    seen = _stub_permission(enforce_env)

    def _boom(**_kwargs):
        raise RuntimeError("dns down")

    enforce_env.setattr(df_module, "check_start_permission", _boom)

    def _live(root, mode_id, *, checker=None):
        return checker(permit_request={**PERMIT_REQUEST, "mode_id": mode_id})

    enforce_env.setattr(df_module, "check_live_start_permission", _live)
    _stub_preflight(enforce_env, (False, "ENTITLEMENT_UNREACHABLE", "服务不可达"))
    f = DashboardFacade(tmp_path)
    f.refresh_subscription_status()
    assert _wait(qapp, lambda: f._subscription_cache is not None)

    sub = _subscription(f)
    assert sub["status"] == "网络异常"
    assert seen == []


def test_release_not_approved_is_distinct_from_unactivated(
    qapp, tmp_path, enforce_env, forbid_activation
):
    _stub_permission(
        enforce_env,
        allowed=False, mode="enforce", status="UNKNOWN",
        code="RELEASE_NOT_APPROVED", message="发行未批准",
    )
    _stub_preflight(enforce_env, (False, "RELEASE_NOT_APPROVED", "发行未批准"))
    f = DashboardFacade(tmp_path)
    f.refresh_subscription_status()
    assert _wait(qapp, lambda: f._subscription_cache is not None)

    sub = _subscription(f)
    assert sub["status"] == "发行未批准"
    assert sub["status"] != "未激活"


def test_reopen_formal_dashboard_restores_saved_key_without_reentry(
    qapp, tmp_path, monkeypatch, forbid_activation
):
    monkeypatch.setenv("SHUABAO_SUBSCRIPTION_MODE", "enforce")
    monkeypatch.delenv(SUBSCRIPTION_LICENSE_KEY_ENV, raising=False)
    # Facade.__init__ back-fills os.environ directly from the DPAPI blob
    # (bypassing monkeypatch bookkeeping); snapshot/restore the whole env so
    # the process-level key never leaks into unrelated suites.
    saved_environ = os.environ.copy()
    monkeypatch.setattr(df_module, "load_saved_license_key", lambda _app_data: "saved-test-key")
    _stub_permission(
        monkeypatch,
        allowed=True, mode="enforce", status="ACTIVE", code="OK",
        message="ok", would_allow=True, entitlement_valid=True,
    )
    _stub_preflight(monkeypatch, (True, "PERMIT_VERIFIED", "LIVE permit 已验签"))

    try:
        f = DashboardFacade(tmp_path)
        boot = _subscription(f)
        # First paint shows the validating state, never 未激活.
        assert boot["status"] == "正在校验"
        # Init schedules the one-shot validation; processEvents drives it.
        assert _wait(qapp, lambda: f._subscription_cache is not None)
        sub = _subscription(f)
        assert sub["active"] is True
        assert sub["status"] == "卡密有效"
    finally:
        os.environ.clear()
        os.environ.update(saved_environ)


def test_start_run_still_forces_fresh_live_permission_probe(
    qapp, tmp_path, enforce_env, forbid_activation
):
    seen = _stub_permission(
        enforce_env,
        allowed=False, mode="enforce", status="EXPIRED", code="EXPIRED",
        message="订阅已过期", entitlement_valid=False,
    )
    _stub_preflight(enforce_env, (False, "EXPIRED", "订阅已过期"))
    f = DashboardFacade(tmp_path)
    f.refresh_subscription_status()
    assert _wait(qapp, lambda: f._subscription_cache is not None)
    probes_after_boot = len(seen)

    result = json.loads(f.start_run(json.dumps({"mode_id": "normal_farm"})))
    assert result["ok"] is False
    assert len(seen) > probes_after_boot, "start_run must re-probe (force=True)"


def test_refresh_without_saved_key_is_noop(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("SHUABAO_SUBSCRIPTION_MODE", "enforce")
    monkeypatch.delenv(SUBSCRIPTION_LICENSE_KEY_ENV, raising=False)
    seen = _stub_permission(monkeypatch)
    f = DashboardFacade(tmp_path)
    result = json.loads(f.refresh_subscription_status())
    assert result["error"] == "NO_SAVED_KEY"
    assert seen == []
    assert f._subscription_cache is None
