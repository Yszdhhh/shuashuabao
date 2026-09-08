from __future__ import annotations

import json
import ssl
import sys
from urllib.error import URLError

from shuabao.subscription_client import activate_device, validate_entitlement


class _Response:
    def __init__(self, payload: dict):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def test_tls_initialization_failure_reports_safe_openssl_reason_before_network(monkeypatch):
    import shuabao.subscription_client as client

    error = ssl.SSLError(1, "sensitive-test-key and a private path")
    error.library, error.reason = "ASN1", "NOT_ENOUGH_DATA"

    def context():
        raise error

    def forbidden(*_args, **_kwargs):
        raise AssertionError("TLS initialization failure must not reach the network")

    monkeypatch.setattr(client, "_subscription_ssl_context", context)
    monkeypatch.setattr(client.urllib_request, "urlopen", forbidden)
    result = activate_device("sensitive-test-key", env={
        "SHUABAO_SUBSCRIPTION_BASE_URL": "https://subscription.example",
    })
    assert result["ok"] is False
    assert result["message"] == "设备激活失败: TLS 初始化/连接失败 (ASN1/NOT_ENOUGH_DATA)"


def test_wrapped_certificate_error_is_reported_without_raw_details():
    from shuabao.subscription_client import _transport_error

    error = URLError(ssl.SSLCertVerificationError(1, "private key/path"))
    assert _transport_error("失败", error) == "失败: TLS 证书验证失败"


def test_ssl_error_does_not_expose_non_symbolic_details():
    from shuabao.subscription_client import _transport_error

    error = ssl.SSLError(1, "sensitive-test-key")
    error.library, error.reason = "private path", "https://private.example"
    assert _transport_error("失败", error) == "失败: TLS 初始化/连接失败"


def test_subscription_requests_use_verified_tls_context(monkeypatch):
    import shuabao.subscription_client as client

    contexts = []

    def urlopen(_request, **kwargs):
        contexts.append(kwargs["context"])
        return _Response({"valid": True, "can_start_runner": True, "status": "ACTIVE"})

    monkeypatch.setattr(client.urllib_request, "urlopen", urlopen)
    env = {"SHUABAO_SUBSCRIPTION_BASE_URL": "https://subscription.example"}

    activate_device("test-key", env=env)
    validate_entitlement("test-key", env=env)

    assert len(contexts) == 2
    assert all(context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname for context in contexts)


def test_subscription_tls_failure_is_specific_and_does_not_echo_key(monkeypatch):
    import shuabao.subscription_client as client

    def urlopen(*_args, **_kwargs):
        raise ssl.SSLCertVerificationError(1, "certificate verification failed")

    monkeypatch.setattr(client.urllib_request, "urlopen", urlopen)
    result = activate_device(
        "sensitive-test-key",
        env={"SHUABAO_SUBSCRIPTION_BASE_URL": "https://subscription.example"},
    )

    assert result["code"] == "DEVICE_ACTIVATION_FAILED"
    assert result["message"] == "设备激活失败: TLS 证书验证失败"
    assert "sensitive-test-key" not in result["message"]


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

    allow_payload = dict(_ALLOW)
    allow_payload["permit"] = _permit_payload()
    allow = check_start_permission(env=_ENFORCE_ENV, opener=_DenyAllOpener(allow_payload))

    deny = check_start_permission(env=_ENFORCE_ENV, opener=_DenyAllOpener({"valid": False}))
    assert deny.allowed is False
    assert deny.would_allow is False
    assert "test-key" not in deny.message
    assert "test-key" not in str(deny)

def _permit_payload() -> dict:
    return {
        "schema_version": 1,
        "permit_id": "pmt-1",
        "jti": "pmt-1",
        "license_id": "lic-1",
        "device_id": "device-1",
        "device_fingerprint": "device-1",
        "product_id": "shuabao",
        "audience": "live-runner",
        "issuer": "shuabao-subscription",
        "release_channel": "stable",
        "source_sha": "a" * 40,
        "release_manifest_sha256": "b" * 64,
        "allowed_modes": ["normal_farm"],
        "features": ["run"],
        "issued_at": "2026-09-01T11:00:00Z",
        "expires_at": "2026-09-01T13:00:00Z",
        "nonce": "nonce-1",
        "signature_algorithm": "Ed25519",
        "key_id": "test-key",
        "signature": "c2ln",
    }


def test_check_start_permission_enforce_requires_server_permit():
    from shuabao.subscription_client import check_start_permission

    permission = check_start_permission(env=_ENFORCE_ENV, opener=_DenyAllOpener(_ALLOW))
    assert permission.allowed is False
    assert permission.code == "PERMIT_MISSING"
    assert permission.entitlement_valid is True


def test_check_start_permission_attaches_structurally_valid_permit():
    from shuabao.subscription_client import check_start_permission

    payload = dict(_ALLOW)
    payload["permit"] = _permit_payload()
    permission = check_start_permission(env=_ENFORCE_ENV, opener=_DenyAllOpener(payload))
    assert permission.allowed is True
    assert permission.permit is not None
    assert permission.permit.permit_id == "pmt-1"


def test_check_start_permission_rejects_malformed_permit():
    from shuabao.subscription_client import check_start_permission

    payload = dict(_ALLOW)
    payload["permit"] = {"schema_version": 1}
    permission = check_start_permission(env=_ENFORCE_ENV, opener=_DenyAllOpener(payload))
    assert permission.allowed is False
    assert permission.code == "PERMIT_MALFORMED"



def test_execute_runtime_mediator_rejects_ordinary_allowed_permission(tmp_path):
    from shuabao.subscription_client import StartPermission

    result = _run_executor(
        tmp_path,
        permission=StartPermission(True, "off", status="OFF", code="OFF", would_allow=True),
    )
    assert result["phase"] == "ERROR"
    assert result["mediator"] is None
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
    from shuabao.subscription_permit import DevStartCapability
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
    from shuabao.shell import live_execute
    monkeypatch.setenv("SHUABAO_SUBSCRIPTION_MODE", "off")
    monkeypatch.setattr(
        live_execute,
        "_live_identity",
        lambda root: live_execute._LiveIdentity("", "", "internal", False, root, root / "config" / "entitlement_public_keys.json"),
    )

    allowed = DevStartCapability.for_off()
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


def test_device_fingerprint_override_allowed_by_default():
    from shuabao.subscription_client import _device_fingerprint

    env = {"SHUABAO_SUBSCRIPTION_DEVICE_FINGERPRINT": "pilot-fp"}
    assert _device_fingerprint(env) == "pilot-fp"


def test_device_fingerprint_disallowed_override_falls_back_to_host_identity():
    from shuabao.subscription_client import _device_fingerprint

    env = {"SHUABAO_SUBSCRIPTION_DEVICE_FINGERPRINT": "pilot-fp"}
    fingerprint = _device_fingerprint(env, allow_override=False)
    assert fingerprint != "pilot-fp"
    assert len(fingerprint) == 64  # sha256 hex of MachineGuid / node+hostname seed


def test_packaged_subscription_calls_ignore_fingerprint_override(monkeypatch):
    import shuabao.subscription_client as client

    monkeypatch.setattr(client.sys, "frozen", True, raising=False)
    env = {
        "SHUABAO_SUBSCRIPTION_BASE_URL": "http://127.0.0.1:8000",
        "SHUABAO_SUBSCRIPTION_DEVICE_FINGERPRINT": "spoofed-device",
    }
    seen: list[dict] = []

    def opener(request, **_kwargs):
        seen.append(json.loads(request.data.decode("utf-8")))
        return _Response({"valid": False, "status": "UNKNOWN"})

    client.validate_entitlement("key", env=env, opener=opener)
    client.activate_device("key", env=env, opener=opener)

    assert len(seen) == 2
    assert all(item["hardware"]["fingerprint"] != "spoofed-device" for item in seen)
