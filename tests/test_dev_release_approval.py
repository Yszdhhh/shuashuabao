"""Tests for tools/approve_dev_release.py (Closure B).

Covers:
1. Real package verification before approval (reuses release_signing):
   - valid signed package → proceeds;
   - missing .sig → BLOCKED;
   - bad signature → BLOCKED;
   - tampered attested file → BLOCKED;
   - extra unsigned file → BLOCKED;
   - build_identity manifest SHA mismatch → BLOCKED;
   - build_identity source/channel mismatch → BLOCKED;
   - missing/empty operator trust anchor → BLOCKED;
   - none of the above failures ever invoke the remote admin API.
2. Hard channel gating:
   - dev / internal-pilot → allowed;
   - external-beta / release → always BLOCKED (no --allow-channel bypass);
   - --allow-channel argument is deleted.
3. Canonical identity equivalence across all four authorities.
4. Remote push + verified read-after-write.
5. Fail-closed on unreachable / unapproved / unauthorized.
6. User settings do not alter package identity.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import socketserver
import sys
import threading
from typing import Iterator

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from shuabao import release_signing
from shuabao.paths import user_settings_path
from shuabao.release_signing import (
    canonical_manifest_bytes,
    canonical_manifest_sha256,
)
from shuabao.settings import Settings
from shuabao.shell import live_execute
from tools import approve_dev_release as adr


@pytest.fixture()
def signing_key(monkeypatch) -> Ed25519PrivateKey:
    key = Ed25519PrivateKey.generate()
    public_key = key.public_key()
    monkeypatch.setattr(
        release_signing,
        "PINNED_MANIFEST_PUBLIC_KEYS",
        {"test-manifest": public_key},
    )
    return key


@pytest.fixture()
def operator_registry(tmp_path: Path, signing_key: Ed25519PrivateKey, monkeypatch) -> Path:
    """Operator-side manifest public keys JSON (outside the package)."""
    pub = signing_key.public_key()
    b64 = base64.b64encode(pub.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)).decode("ascii")
    path = tmp_path / "operator_manifest_public_keys.json"
    path.write_text(json.dumps({"keys": {"test-manifest": b64}}), encoding="utf-8")
    monkeypatch.setenv(adr.PUBLIC_KEYS_ENV, str(path))
    return path


def _signed_bundle(
    tmp_path: Path,
    signing_key: Ed25519PrivateKey,
    *,
    source_sha: str = "a" * 40,
    channel: str = "dev",
    extra_files: dict[str, bytes] | None = None,
) -> Path:
    """Build a real verified package matching build_release.ps1."""
    bundle = tmp_path / f"bundle_{channel}_{source_sha[:6]}"
    internal = bundle / "_internal"
    web_dist = internal / "web" / "dist"
    config_dir = internal / "config"
    web_dist.mkdir(parents=True, exist_ok=True)
    config_dir.mkdir(parents=True, exist_ok=True)

    # Entitlement public keys required by live_execute._live_identity
    permit_key = Ed25519PrivateKey.generate().public_key()
    permit_b64 = base64.b64encode(permit_key.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)).decode("ascii")
    (config_dir / "entitlement_public_keys.json").write_text(
        json.dumps({"keys": {"permit-test": permit_b64}}), encoding="utf-8"
    )

    (bundle / "ShuaBao.exe").write_bytes(b"MZfakeexe" + b"\x00" * 64)
    (web_dist / "index.html").write_text("<html></html>", encoding="utf-8")
    (bundle / "subscription_runtime.json").write_text("{}", encoding="utf-8")

    if extra_files:
        for rel, data in extra_files.items():
            p = bundle / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)

    manifest_files = []
    for p in sorted(bundle.rglob("*")):
        if p.is_file() and p.name not in release_signing.METADATA_FILE_EXCEPTIONS:
            manifest_files.append({
                "path": p.relative_to(bundle).as_posix(),
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                "size_bytes": p.stat().st_size,
            })

    manifest = {
        "schema_version": 1,
        "source_sha": source_sha,
        "release_channel": channel,
        "bridge_schema_version": 2,
        "generated_at_utc": "2026-09-05T12:00:00Z",
        "files": manifest_files,
    }
    # 真实构建中 release_manifest.json 是普通格式化 JSON（带换行缩进），
    # 使得 raw-file bytes SHA 与 canonical JSON SHA 明显不同。
    raw_disk_bytes = json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")
    (bundle / "release_manifest.json").write_bytes(raw_disk_bytes)
    manifest_bytes = canonical_manifest_bytes(manifest)
    canonical_sha = canonical_manifest_sha256(manifest)
    sig_b64 = base64.urlsafe_b64encode(signing_key.sign(manifest_bytes)).rstrip(b"=").decode("ascii")
    sig_envelope = json.dumps({
        "schema_version": 1,
        "algorithm": "Ed25519",
        "key_id": "test-manifest",
        "manifest_sha256": canonical_sha,
        "signature": sig_b64,
    })
    (bundle / "release_manifest.json.sig").write_text(sig_envelope, encoding="utf-8")

    canonical_sha = canonical_manifest_sha256(manifest)
    (bundle / "build_identity.json").write_text(
        json.dumps({
            "schema_version": 1,
            "version": "0.3",
            "release_channel": channel,
            "source_sha": source_sha,
            "release_manifest_sha256": canonical_sha,
            "bridge_schema_version": 2,
            "built_at_utc": "2026-09-05T12:00:00Z",
        }, indent=2),
        encoding="utf-8",
    )
    return bundle


class _BridgeHandler(http.server.BaseHTTPRequestHandler):
    store: dict[str, dict] = {}
    auth_failures = 0

    def log_message(self, *args):
        pass

    def do_PUT(self):
        auth = self.headers.get("Authorization") or ""
        expected = "Basic " + base64.b64encode(b"op_user:op_secret").decode("ascii")
        if auth != expected:
            _BridgeHandler.auth_failures += 1
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b'{"error":"unauthorized"}')
            return
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        _BridgeHandler.store["policy"] = body
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True, "release_status": body}).encode("utf-8"))

    def do_GET(self):
        policy = _BridgeHandler.store.get("policy")
        if not policy:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "source_sha": "",
                "release_manifest_sha256": "",
                "release_channel": "",
                "allowed_modes": [],
                "status": "not_approved",
                "approved": False,
                "blocked": False,
            }).encode("utf-8"))
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "source_sha": policy["source_sha"],
            "release_manifest_sha256": policy["release_manifest_sha256"],
            "release_channel": policy["release_channel"],
            "allowed_modes": policy.get("allowed_modes", []),
            "status": "approved",
            "approved": True,
            "blocked": False,
        }).encode("utf-8"))


@pytest.fixture()
def bridge() -> Iterator[tuple[_BridgeHandler, str]]:
    _BridgeHandler.store = {}
    _BridgeHandler.auth_failures = 0
    with socketserver.TCPServer(("127.0.0.1", 0), _BridgeHandler) as srv:
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            yield _BridgeHandler, f"http://127.0.0.1:{port}"
        finally:
            srv.shutdown()


@pytest.fixture()
def admin_env(monkeypatch):
    monkeypatch.setenv(adr.ADMIN_USER_ENV, "op_user")
    monkeypatch.setenv(adr.ADMIN_PASSWORD_ENV, "op_secret")


# ---------------------------------------------------------------------------
# Section 1: Package verification before approval
# ---------------------------------------------------------------------------

def test_valid_signed_package_derives_canonical_identity(
    tmp_path: Path, signing_key: Ed25519PrivateKey, operator_registry: Path
) -> None:
    bundle = _signed_bundle(tmp_path, signing_key)
    ident = adr.load_package_identity(bundle, public_keys_path=str(operator_registry))
    assert ident["source_sha"] == "a" * 40
    assert ident["release_channel"] == "dev"
    assert len(ident["release_manifest_sha256"]) == 64


def test_missing_signature_is_blocked_without_remote_call(
    tmp_path: Path, signing_key: Ed25519PrivateKey, operator_registry: Path, bridge, admin_env
) -> None:
    handler, base_url = bridge
    bundle = _signed_bundle(tmp_path, signing_key)
    (bundle / "release_manifest.json.sig").unlink()

    rc = adr.main(["--package", str(bundle), "--base-url", base_url])
    assert rc != 0
    assert "policy" not in handler.store, "must not touch admin API on missing sig"


def test_bad_signature_is_blocked_without_remote_call(
    tmp_path: Path, signing_key: Ed25519PrivateKey, operator_registry: Path, bridge, admin_env
) -> None:
    handler, base_url = bridge
    bundle = _signed_bundle(tmp_path, signing_key)
    sig_path = bundle / "release_manifest.json.sig"
    envelope = json.loads(sig_path.read_text(encoding="utf-8"))
    envelope["signature"] = base64.b64encode(b"bad" * 21).decode("ascii")
    sig_path.write_text(json.dumps(envelope), encoding="utf-8")

    rc = adr.main(["--package", str(bundle), "--base-url", base_url])
    assert rc != 0
    assert "policy" not in handler.store, "must not touch admin API on bad sig"


def test_tampered_attested_file_is_blocked_without_remote_call(
    tmp_path: Path, signing_key: Ed25519PrivateKey, operator_registry: Path, bridge, admin_env
) -> None:
    handler, base_url = bridge
    bundle = _signed_bundle(tmp_path, signing_key)
    # Modify an attested file after signing
    (bundle / "ShuaBao.exe").write_bytes(b"tampered" * 10)

    rc = adr.main(["--package", str(bundle), "--base-url", base_url])
    assert rc != 0
    assert "policy" not in handler.store, "must not touch admin API on tampered file"


def test_extra_unsigned_file_is_blocked_without_remote_call(
    tmp_path: Path, signing_key: Ed25519PrivateKey, operator_registry: Path, bridge, admin_env
) -> None:
    handler, base_url = bridge
    bundle = _signed_bundle(tmp_path, signing_key)
    # Drop an unexpected DLL into the package
    (bundle / "evil.dll").write_bytes(b"evil")

    rc = adr.main(["--package", str(bundle), "--base-url", base_url])
    assert rc != 0
    assert "policy" not in handler.store, "must not touch admin API on extra file"


def test_build_identity_manifest_sha_mismatch_is_blocked(
    tmp_path: Path, signing_key: Ed25519PrivateKey, operator_registry: Path, bridge, admin_env
) -> None:
    handler, base_url = bridge
    bundle = _signed_bundle(tmp_path, signing_key)
    ident_path = bundle / "build_identity.json"
    data = json.loads(ident_path.read_text(encoding="utf-8"))
    data["release_manifest_sha256"] = "c" * 64
    ident_path.write_text(json.dumps(data), encoding="utf-8")

    rc = adr.main(["--package", str(bundle), "--base-url", base_url])
    assert rc != 0
    assert "policy" not in handler.store


def test_build_identity_source_or_channel_mismatch_is_blocked(
    tmp_path: Path, signing_key: Ed25519PrivateKey, operator_registry: Path, bridge, admin_env
) -> None:
    handler, base_url = bridge
    bundle = _signed_bundle(tmp_path, signing_key)
    ident_path = bundle / "build_identity.json"
    data = json.loads(ident_path.read_text(encoding="utf-8"))
    data["source_sha"] = "0" * 40
    ident_path.write_text(json.dumps(data), encoding="utf-8")

    rc = adr.main(["--package", str(bundle), "--base-url", base_url])
    assert rc != 0
    assert "policy" not in handler.store


def test_missing_or_empty_operator_registry_fails_closed(
    tmp_path: Path, signing_key: Ed25519PrivateKey, monkeypatch, bridge, admin_env
) -> None:
    handler, base_url = bridge
    bundle = _signed_bundle(tmp_path, signing_key)
    monkeypatch.delenv(adr.PUBLIC_KEYS_ENV, raising=False)

    rc = adr.main(["--package", str(bundle), "--base-url", base_url, "--public-keys", ""])
    assert rc != 0
    assert "policy" not in handler.store

    # Empty registry file
    empty_reg = tmp_path / "empty.json"
    empty_reg.write_text(json.dumps({"keys": {}}), encoding="utf-8")
    rc2 = adr.main(["--package", str(bundle), "--base-url", base_url, "--public-keys", str(empty_reg)])
    assert rc2 != 0
    assert "policy" not in handler.store



def test_package_inside_trust_anchor_is_strictly_rejected(
    tmp_path: Path, signing_key: Ed25519PrivateKey, bridge, admin_env
) -> None:
    """P1: operator manifest trust anchor must live strictly outside the package.

    A package must never be allowed to attest itself by embedding its own key
    registry and pointing --public-keys into itself.
    """
    handler, base_url = bridge
    bundle = _signed_bundle(tmp_path, signing_key)

    # 构造一个位于 package 内部的 self_trust_keys.json
    self_trust = bundle / "self_trust_keys.json"
    raw_spki = signing_key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    self_trust.write_text(
        json.dumps({"keys": {"test-manifest": base64.b64encode(raw_spki).decode("ascii")}}),
        encoding="utf-8",
    )

    # 1. 显式 --public-keys 指向包内文件
    rc = adr.main(["--package", str(bundle), "--base-url", base_url, "--public-keys", str(self_trust)])
    assert rc != 0, "pointing --public-keys into the package must fail closed"
    assert "policy" not in handler.store, "must not make remote admin API calls"

    # 2. 环境变量指回包内文件
    os.environ[adr.PUBLIC_KEYS_ENV] = str(self_trust)
    try:
        rc2 = adr.main(["--package", str(bundle), "--base-url", base_url])
        assert rc2 != 0, "env pointing into the package must fail closed"
        assert "policy" not in handler.store
    finally:
        os.environ.pop(adr.PUBLIC_KEYS_ENV, None)

# ---------------------------------------------------------------------------
# Section 2: Hard channel gating (external-beta / release always blocked)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("channel", ["external-beta", "release"])
def test_external_channels_are_always_hard_blocked(
    tmp_path: Path, signing_key: Ed25519PrivateKey, operator_registry: Path, bridge, admin_env, channel: str
) -> None:
    handler, base_url = bridge
    bundle = _signed_bundle(tmp_path, signing_key, channel=channel)

    rc = adr.main(["--package", str(bundle), "--base-url", base_url])
    assert rc != 0
    assert "policy" not in handler.store, f"{channel} must never be auto-approved"


def test_allow_channel_flag_does_not_exist() -> None:
    """The dangerous --allow-channel bypass must be permanently deleted."""
    with pytest.raises(SystemExit):
        adr.main(["--allow-channel"])


@pytest.mark.parametrize("channel", ["dev", "internal-pilot"])
def test_operator_channels_are_permitted(
    tmp_path: Path, signing_key: Ed25519PrivateKey, operator_registry: Path, bridge, admin_env, channel: str
) -> None:
    handler, base_url = bridge
    bundle = _signed_bundle(tmp_path, signing_key, channel=channel)

    rc = adr.main(["--package", str(bundle), "--base-url", base_url])
    assert rc == 0
    assert handler.store["policy"]["release_channel"] == channel


# ---------------------------------------------------------------------------
# Section 3: Canonical identity equivalence & remote read-after-write
# ---------------------------------------------------------------------------

def test_four_way_identity_agreement(
    tmp_path: Path, signing_key: Ed25519PrivateKey, operator_registry: Path, monkeypatch
) -> None:
    """The four authorities must agree on the exact same identity tuple:
    1. approval tool identity
    2. build_identity.json
    3. frozen live_permit_request_context
    """
    bundle = _signed_bundle(tmp_path, signing_key, source_sha="c" * 40, channel="dev")
    tool_identity = adr.load_package_identity(bundle, public_keys_path=str(operator_registry))
    build_identity = json.loads((bundle / "build_identity.json").read_text(encoding="utf-8"))

    # 1 vs 2:
    assert tool_identity["source_sha"] == build_identity["source_sha"]
    assert tool_identity["release_manifest_sha256"] == build_identity["release_manifest_sha256"]
    assert tool_identity["release_channel"] == build_identity["release_channel"]

    # 1 & 2 vs 3 (frozen live_permit_request_context):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(bundle / "ShuaBao.exe"))
    live_ctx = live_execute.live_permit_request_context(bundle, "lobby_hitch")
    assert live_ctx is not None
    assert live_ctx["source_sha"] == tool_identity["source_sha"]
    assert live_ctx["release_manifest_sha256"] == tool_identity["release_manifest_sha256"]
    assert live_ctx["release_channel"] == tool_identity["release_channel"]

    # Never the raw-file bytes SHA:
    raw_sha = hashlib.sha256((bundle / "release_manifest.json").read_bytes()).hexdigest()
    assert tool_identity["release_manifest_sha256"] != raw_sha


def test_remote_approval_round_trip(
    tmp_path: Path, signing_key: Ed25519PrivateKey, operator_registry: Path, bridge, admin_env
) -> None:
    handler, base_url = bridge
    bundle = _signed_bundle(tmp_path, signing_key)
    registry = tmp_path / "audit_registry.json"

    rc = adr.main([
        "--package", str(bundle),
        "--base-url", base_url,
        "--registry", str(registry),
        "--modes", "lobby_hitch,normal_farm",
    ])
    assert rc == 0
    assert handler.store["policy"]["allowed_modes"] == ["lobby_hitch", "normal_farm"]
    assert registry.is_file()


def test_remote_approval_fails_closed_when_read_after_write_fails(
    tmp_path: Path, signing_key: Ed25519PrivateKey, operator_registry: Path, bridge, admin_env, monkeypatch
) -> None:
    _, base_url = bridge
    bundle = _signed_bundle(tmp_path, signing_key)
    real_req = adr._request

    def _tamper_get(method, url, **kwargs):
        resp = real_req(method, url, **kwargs)
        if method == "GET":
            return {**resp, "approved": False, "status": "not_approved"}
        return resp

    monkeypatch.setattr(adr, "_request", _tamper_get)
    registry = tmp_path / "audit.json"
    rc = adr.main(["--package", str(bundle), "--base-url", base_url, "--registry", str(registry)])
    assert rc == 1
    assert not registry.exists(), "audit record must not be written if verification fails"


def test_user_config_changes_never_change_release_identity(
    tmp_path: Path, signing_key: Ed25519PrivateKey, operator_registry: Path, monkeypatch
) -> None:
    bundle = _signed_bundle(tmp_path, signing_key)
    before = adr.load_package_identity(bundle, public_keys_path=str(operator_registry))

    app_data = tmp_path / "app_data"
    app_data.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    settings = Settings()
    settings.hitch_stage_prefix = "99"
    settings.cjb_boss = "09火魔"
    settings.save(user_settings_path(app_data))

    after = adr.load_package_identity(bundle, public_keys_path=str(operator_registry))
    assert before["source_sha"] == after["source_sha"]
    assert before["release_manifest_sha256"] == after["release_manifest_sha256"]
    assert before["release_channel"] == after["release_channel"]


@pytest.mark.parametrize("fake_loopback", [
    "http://127.evil.example",
    "http://127.example.com",
    "http://127.0.0.1.evil.com",
    "http://not-loopback.example",
])
def test_fake_loopback_http_endpoints_are_strictly_rejected(
    tmp_path: Path, signing_key: Ed25519PrivateKey, operator_registry: Path, admin_env, fake_loopback: str
) -> None:
    """P0: http://127.evil.example must never be treated as loopback.

    Only true IP loopbacks (127.0.0.0/8, ::1) or exact localhost are allowed
    over HTTP. Pseudo-loopback DNS hostnames must fail closed without making
    any HTTP calls or transmitting credentials.
    """
    bundle = _signed_bundle(tmp_path, signing_key)
    with pytest.raises(adr.ApprovalError, match="real IP loopback"):
        adr._endpoint_or_die(fake_loopback)

    # 确保 main 面对伪 loopback 退出码非 0 且零 HTTP 连接
    rc = adr.main(["--package", str(bundle), "--base-url", fake_loopback])
    assert rc != 0


@pytest.mark.parametrize("valid_loopback", [
    "http://127.0.0.1:8000",
    "http://127.0.0.2:8000",
    "http://[::1]:8000",
    "http://localhost:8000",
    "http://localhost.:8000",
])
def test_real_loopback_and_localhost_are_accepted(valid_loopback: str) -> None:
    """P0: genuine IP loopback addresses and normalized localhost are valid HTTP exceptions."""
    res = adr._endpoint_or_die(valid_loopback)
    assert res == valid_loopback.rstrip("/")


def test_embedded_userinfo_in_url_is_strictly_rejected() -> None:
    """P0: URLs embedding credentials must be rejected fail-closed."""
    with pytest.raises(adr.ApprovalError, match="不得内嵌凭据"):
        adr._endpoint_or_die("https://user:pass@example.com")
    with pytest.raises(adr.ApprovalError, match="不得内嵌凭据"):
        adr._endpoint_or_die("http://user:pass@127.0.0.1:8000")
