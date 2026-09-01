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


class _DenyAllOpener:
    def __init__(self, payload: dict):
        self._payload = payload

    def __call__(self, *_args, **_kwargs):
        return _Response(self._payload)


_ALLOW = {
    "valid": True,
    "can_start_runner": True,
    "status": "ACTIVE",
    "license": {"expires_at": "2026-12-31T00:00:00Z"},
}
_ENFORCE_ENV = {
    "SHUABAO_SUBSCRIPTION_MODE": "enforce",
    "SHUABAO_SUBSCRIPTION_BASE_URL": "http://127.0.0.1:8000",
    "SHUABAO_SUBSCRIPTION_LICENSE_KEY": "test-key",
    "SHUABAO_SUBSCRIPTION_DEVICE_FINGERPRINT": "device",
}


def test_check_start_permission_enforce_allow_then_deny_sanitized():
    from shuabao.subscription_client import check_start_permission

    allow = check_start_permission(env=_ENFORCE_ENV, opener=_DenyAllOpener(_ALLOW))
    assert allow.allowed is True
    assert "test-key" not in str(allow)

    deny = check_start_permission(env=_ENFORCE_ENV, opener=_DenyAllOpener({"valid": False}))
    assert deny.allowed is False
    assert deny.would_allow is False
    assert "test-key" not in deny.message
    assert "test-key" not in str(deny)


# ---------------------------------------------------------------- 共享执行器深层门禁


def _executor_denied():
    from shuabao.subscription_client import StartPermission

    return StartPermission(
        allowed=False, mode="enforce", status="EXPIRED",
        code="ENTITLEMENT_EXPIRED", message="订阅状态不允许启动: EXPIRED",
    )


def _run_executor(tmp_path, *, permission, should_abort=None):
    from shuabao.settings import Settings
    from shuabao.shell.live_execute import execute_runtime_mediator
    from shuabao.stop_signal import StopSignal

    return execute_runtime_mediator(
        settings=Settings(),
        root_dir=tmp_path,
        incident_dir=tmp_path / "incidents",
        stop_signal=StopSignal(),
        permission=permission,
        should_abort=should_abort,
    )


def test_execute_runtime_mediator_fails_closed_without_permission(tmp_path):
    result = _run_executor(tmp_path, permission=None)
    assert result["phase"] == "ERROR"
    assert result["mediator"] is None
    assert result["terminal_reason"] == "订阅未授权，LIVE 已拒绝启动"
    assert not (tmp_path / "incidents" / "live.log").exists()


def test_execute_runtime_mediator_fails_closed_on_denied_permission(tmp_path):
    result = _run_executor(tmp_path, permission=_executor_denied())
    assert result["phase"] == "ERROR"
    assert result["mediator"] is None
    assert result["terminal_reason"] == "订阅未授权，LIVE 已拒绝启动"
    assert not (tmp_path / "incidents" / "live.log").exists()


def test_execute_runtime_mediator_denial_never_echoes_license_key(tmp_path):
    from shuabao.subscription_client import check_start_permission

    env = dict(_ENFORCE_ENV)
    env["SHUABAO_SUBSCRIPTION_LICENSE_KEY"] = "SECRET-LIVE-KEY-9"
    permission = check_start_permission(env=env, opener=_DenyAllOpener({"valid": False}))
    assert permission.allowed is False
    result = _run_executor(tmp_path, permission=permission)
    blob = json.dumps({k: v for k, v in result.items() if k != "log_sink"}, default=str)
    assert "SECRET-LIVE-KEY-9" not in blob


def test_execute_runtime_mediator_allowed_permission_reaches_mediator(tmp_path, monkeypatch):
    import sys
    import types
    from shuabao.subscription_client import StartPermission

    created = {}

    class FakeMediator:
        def __init__(self, settings, root_dir, *, stop_signal=None, incident_dir=None):
            created["ok"] = True

        def prepare_live_dependencies(self):
            return False

        def set_trace(self, *_a):
            pass

    fake = types.ModuleType("shuabao.runtime_mediator")
    fake.Mediator = FakeMediator
    monkeypatch.setitem(sys.modules, "shuabao.runtime_mediator", fake)

    allowed = StartPermission(allowed=True, mode="off", status="OFF", code="OFF", would_allow=True)
    result = _run_executor(tmp_path, permission=allowed)
    assert created.get("ok") is True, "有效权限必须放行到 Mediator 构造"
    assert result["mediator"] is not None


def test_execute_runtime_mediator_rejects_duck_typed_permission(tmp_path):
    class ForgedPermission:
        allowed = True

    result = _run_executor(tmp_path, permission=ForgedPermission())
    assert result["phase"] == "ERROR"
    assert result["mediator"] is None


def test_execute_runtime_mediator_stop_before_permission_gate(tmp_path):
    result = _run_executor(tmp_path, permission=None, should_abort=lambda: True)
    assert result["phase"] == "IDLE"
    assert result["terminal_reason"] == "启动前已请求停止"
    assert result["mediator"] is None
    assert not (tmp_path / "incidents" / "live.log").exists()
