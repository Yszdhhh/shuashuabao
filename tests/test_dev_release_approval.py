"""Closure B regressions: canonical identity, remote approval, config invariance.

1. The approval tool must derive its identity with the single canonical
   authority (``release_signing.canonical_manifest_sha256``) — never a
   raw-file SHA — and it must agree with ``build_identity.json`` and the
   frozen client's ``live_permit_request_context()`` for the same package.
2. Remote approval goes through the existing admin API over HTTPS/loopback,
   proves read-after-write via ``/v1/releases/status``, and fails closed on
   transport/auth/non-approved responses. Credentials never appear in output.
3. Mutating persisted user config never changes package release identity.
"""

import base64
import hashlib
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from PyInstaller.archive.writers import CArchiveWriter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))

import approve_dev_release as adr  # noqa: E402
from shuabao import release_signing  # noqa: E402
from shuabao.release_signing import canonical_manifest_bytes, canonical_manifest_sha256  # noqa: E402
from shuabao.shell import live_execute  # noqa: E402
from tools.prepare_manifest_trust import HOOK_NAME, manifest_trust_hook_source  # noqa: E402

SOURCE_SHA = "a" * 40


def _signed_bundle(tmp_path: Path, private: Ed25519PrivateKey, *, channel: str = "dev") -> Path:
    """Build a real signed package: manifest + .sig + build_identity + trust-hook EXE."""
    bundle = tmp_path / "ShuaBao"
    internal = bundle / "_internal"
    (internal / "config").mkdir(parents=True)
    (internal / "web" / "dist").mkdir(parents=True)

    hook = tmp_path / f"{HOOK_NAME}.py"
    hook.write_text(manifest_trust_hook_source({"test-manifest": private.public_key()}), encoding="utf-8")
    entry = tmp_path / "desktop_app.py"
    entry.write_text("# Offline archive fixture; never executed.\n", encoding="utf-8")
    CArchiveWriter(str(bundle / "ShuaBao.exe"),
                   [(HOOK_NAME, str(hook), True, "s1"), ("desktop_app", str(entry), True, "s1")],
                   pylib_name="python311.dll")

    permit_public = Ed25519PrivateKey.generate().public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    (internal / "config" / "entitlement_public_keys.json").write_text(
        json.dumps({"keys": {"test-permit": base64.b64encode(permit_public).decode("ascii")}}),
        encoding="utf-8",
    )
    (internal / "web" / "dist" / "build_manifest.json").write_text(
        json.dumps({"schema_version": 1, "source_sha": SOURCE_SHA, "source_tree_clean": True,
                    "release_channel": channel, "bridge_schema_version": 2}),
        encoding="utf-8",
    )
    (bundle / "subscription_runtime.json").write_text(
        json.dumps({"schema_version": 1, "base_url": "https://subscription.example",
                    "mode": "enforce", "release_channel": channel, "timeout_s": 10}),
        encoding="utf-8",
    )
    manifest_path = bundle / "release_manifest.json"
    manifest = {"schema_version": 1, "source_sha": SOURCE_SHA, "release_channel": channel,
                "bridge_schema_version": 2, "manifest_signature_status": "SIGNED", "files": []}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    identity_path = bundle / "build_identity.json"
    identity_path.write_text(json.dumps({"schema_version": 1, "source_sha": SOURCE_SHA,
                                         "release_channel": channel, "source_tree_clean": True,
                                         "release_manifest_sha256": "", "exe_sha256": ""}),
                             encoding="utf-8")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"] = [
        {"path": item.relative_to(bundle).as_posix(), "size_bytes": item.stat().st_size,
         "sha256": hashlib.sha256(item.read_bytes()).hexdigest()}
        for item in sorted(bundle.rglob("*"))
        if item.is_file() and item.name not in release_signing.METADATA_FILE_EXCEPTIONS
    ]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    canonical = canonical_manifest_sha256(manifest)
    (bundle / "release_manifest.json.sig").write_text(json.dumps({
        "schema_version": 1, "algorithm": "Ed25519", "key_id": "test-manifest",
        "manifest_sha256": canonical,
        "signature": base64.urlsafe_b64encode(
            private.sign(canonical_manifest_bytes(manifest))).rstrip(b"=").decode("ascii"),
    }), encoding="utf-8")
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    identity["release_manifest_sha256"] = canonical
    identity["exe_sha256"] = hashlib.sha256((bundle / "ShuaBao.exe").read_bytes()).hexdigest()
    identity_path.write_text(json.dumps(identity), encoding="utf-8")
    return bundle


@pytest.fixture
def signing_key(monkeypatch):
    private = Ed25519PrivateKey.generate()
    monkeypatch.setattr(release_signing, "PINNED_MANIFEST_PUBLIC_KEYS", {"test-manifest": private.public_key()})
    return private


# ------------------------------------------------------- canonical identity (P0-2)

def test_identity_uses_canonical_not_raw_file_sha(tmp_path, signing_key) -> None:
    bundle = _signed_bundle(tmp_path, signing_key)
    identity = adr.load_package_identity(bundle)
    raw = hashlib.sha256((bundle / "release_manifest.json").read_bytes()).hexdigest()
    parsed = json.loads((bundle / "release_manifest.json").read_text(encoding="utf-8"))
    assert identity["release_manifest_sha256"] == canonical_manifest_sha256(parsed)
    assert identity["release_manifest_sha256"] != raw, "raw-file SHA must never be the approval identity"


def test_four_way_identity_agreement(tmp_path, signing_key, monkeypatch) -> None:
    """approval tool == build_identity.json == frozen live_permit_request_context."""
    bundle = _signed_bundle(tmp_path, signing_key)
    tool_identity = adr.load_package_identity(bundle)

    build_identity = json.loads((bundle / "build_identity.json").read_text(encoding="utf-8"))
    assert tool_identity["release_manifest_sha256"] == build_identity["release_manifest_sha256"]
    assert tool_identity["source_sha"] == build_identity["source_sha"]
    assert tool_identity["release_channel"] == build_identity["release_channel"]

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(bundle / "ShuaBao.exe"), raising=False)
    context = live_execute.live_permit_request_context(bundle, "lobby_hitch")
    assert context is not None, "frozen client must derive an authenticated identity"
    assert context["source_sha"] == tool_identity["source_sha"]
    assert context["release_manifest_sha256"] == tool_identity["release_manifest_sha256"]
    assert context["release_channel"] == tool_identity["release_channel"]
    assert context["mode_id"] == "lobby_hitch"


def test_corrupt_package_is_refused(tmp_path, signing_key) -> None:
    bundle = _signed_bundle(tmp_path, signing_key)
    (bundle / "release_manifest.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(adr.ApprovalError, match="不可读"):
        adr.load_package_identity(bundle)


def test_missing_manifest_is_refused(tmp_path) -> None:
    empty = tmp_path / "pkg-missing"
    empty.mkdir()
    with pytest.raises(adr.ApprovalError, match="release_manifest"):
        adr.load_package_identity(empty)


def test_bad_source_sha_and_unknown_channel_refused(tmp_path, signing_key) -> None:
    bad = _signed_bundle(tmp_path / "sha-case", signing_key)
    manifest_path = bad / "release_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_sha"] = "short"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(adr.ApprovalError, match="source_sha"):
        adr.load_package_identity(manifest_path.parent)


# ------------------------------------------------------------- remote approval (4)

class _Bridge(BaseHTTPRequestHandler):
    def log_message(self, *_args) -> None:  # silence
        pass

    def do_PUT(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        auth = self.headers.get("Authorization") or ""
        store = self.server.store
        if not auth.startswith("Basic "):
            self._json(401, {"detail": "admin login required"})
            return
        if base64.b64decode(auth[6:]).decode() != "ops:hunter2":
            self._json(401, {"detail": "bad credentials"})
            return
        store["policy"] = body
        self._json(200, {"ok": True, "release_status": {"status": "approved", "approved": True}})

    def do_GET(self):
        from urllib.parse import parse_qs, urlsplit
        query = parse_qs(urlsplit(self.path).query)
        store = self.server.store
        policy = store.get("policy") or {}
        approved = (
            query.get("source_sha", [""])[0] == policy.get("source_sha")
            and query.get("release_manifest_sha256", [""])[0] == policy.get("release_manifest_sha256")
            and query.get("release_channel", [""])[0] == policy.get("release_channel")
        )
        self._json(200, {
            "approved": approved,
            "blocked": False,
            "status": "approved" if approved else "not_approved",
            "allowed_modes": sorted(policy.get("allowed_modes") or []),
            "source_sha": policy.get("source_sha", ""),
            "release_manifest_sha256": policy.get("release_manifest_sha256", ""),
            "release_channel": policy.get("release_channel", ""),
        })

    def _json(self, code, payload):
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


@pytest.fixture
def bridge():
    server = HTTPServer(("127.0.0.1", 0), _Bridge)
    server.store = {}
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def admin_env(monkeypatch):
    monkeypatch.setenv(adr.ADMIN_USER_ENV, "ops")
    monkeypatch.setenv(adr.ADMIN_PASSWORD_ENV, "hunter2")


def test_remote_approval_round_trip(tmp_path, signing_key, bridge, admin_env, capsys) -> None:
    server, base_url = bridge
    bundle = _signed_bundle(tmp_path, signing_key)
    registry = tmp_path / "audit.json"
    assert adr.main(["--package", str(bundle), "--base-url", base_url, "--registry", str(registry)]) == 0
    policy = server.store["policy"]
    identity = adr.load_package_identity(bundle)
    assert policy["source_sha"] == identity["source_sha"]
    assert policy["release_manifest_sha256"] == identity["release_manifest_sha256"]
    assert policy["release_channel"] == "dev"
    assert set(policy["allowed_modes"]) == set(adr.APPROVED_MODES)
    out = capsys.readouterr().out
    assert "approved:" in out
    assert "hunter2" not in out and "ops" not in out, "credentials must never be printed"
    audit = json.loads(registry.read_text(encoding="utf-8"))
    assert audit[0]["release_manifest_sha256"] == identity["release_manifest_sha256"]


def test_remote_approval_requires_credentials(tmp_path, signing_key, bridge, monkeypatch) -> None:
    _, base_url = bridge
    monkeypatch.delenv(adr.ADMIN_USER_ENV, raising=False)
    monkeypatch.delenv(adr.ADMIN_PASSWORD_ENV, raising=False)
    bundle = _signed_bundle(tmp_path, signing_key)
    assert adr.main(["--package", str(bundle), "--base-url", base_url]) == 1


def test_remote_approval_fails_closed_on_bad_credentials(tmp_path, signing_key, bridge, monkeypatch) -> None:
    _, base_url = bridge
    monkeypatch.setenv(adr.ADMIN_USER_ENV, "ops")
    monkeypatch.setenv(adr.ADMIN_PASSWORD_ENV, "wrong-password")
    bundle = _signed_bundle(tmp_path, signing_key)
    assert adr.main(["--package", str(bundle), "--base-url", base_url]) == 1


def test_remote_approval_fails_closed_when_unreachable(tmp_path, signing_key, admin_env) -> None:
    bundle = _signed_bundle(tmp_path, signing_key)
    assert adr.main(["--package", str(bundle), "--base-url", "http://127.0.0.1:9"]) == 1

def test_remote_approval_fails_closed_when_not_approved(tmp_path, signing_key, bridge, admin_env, monkeypatch) -> None:
    _, base_url = bridge
    bundle = _signed_bundle(tmp_path, signing_key)
    real_request = adr._request

    def _lying(method, url, **kwargs):
        result = real_request(method, url, **kwargs)
        if method == "GET":
            # Control plane accepted the write but reports the identity unapproved.
            return {**result, "approved": False, "status": "not_approved", "allowed_modes": []}
        return result

    monkeypatch.setattr(adr, "_request", _lying)
    registry = tmp_path / "audit.json"
    assert adr.main(["--package", str(bundle), "--base-url", base_url, "--registry", str(registry)]) == 1
    assert not registry.exists(), "unverified approval must not be recorded"


def test_non_https_remote_is_refused(tmp_path, signing_key, admin_env) -> None:
    bundle = _signed_bundle(tmp_path, signing_key)
    with pytest.raises(adr.ApprovalError, match="HTTPS"):
        adr.push_release_policy(adr.load_package_identity(bundle),
                                base_url="https://user:pass@subscription.example", modes=list(adr.APPROVED_MODES))
    assert adr.main(["--package", str(bundle), "--base-url", "http://subscription.example"]) == 1


def test_external_channel_requires_explicit_flag(tmp_path, signing_key, bridge, admin_env) -> None:
    _, base_url = bridge
    bundle = _signed_bundle(tmp_path / "ext", signing_key, channel="external-beta")
    registry = tmp_path / "audit.json"
    assert adr.main(["--package", str(bundle), "--base-url", base_url, "--registry", str(registry)]) == 1
    assert not registry.exists(), "refused runs must not write anything"
    assert adr.main(["--package", str(bundle), "--base-url", base_url, "--allow-channel"]) == 0


def test_unknown_mode_is_rejected(tmp_path, signing_key, bridge, admin_env) -> None:
    _, base_url = bridge
    bundle = _signed_bundle(tmp_path, signing_key)
    registry = tmp_path / "audit.json"
    assert adr.main([
        "--package", str(bundle), "--base-url", base_url, "--registry", str(registry),
        "--modes", "lobby_hitch,mystery_mode",
    ]) == 1
    assert not registry.exists()


# ------------------------------------------------------- identity invariance (B)

def test_user_config_changes_never_change_release_identity(tmp_path, signing_key) -> None:
    bundle = _signed_bundle(tmp_path, signing_key)
    before = adr.load_package_identity(bundle)

    app_data = tmp_path / "appdata" / "ShuaBao"
    app_data.mkdir(parents=True)
    user_settings = app_data / "user_settings.json"
    user_settings.write_text(json.dumps({"hitch_stage_prefix": "4,3", "cjb_boss": "01霍格",
                                         "skills": ["s1"]}, ensure_ascii=False), encoding="utf-8")
    user_settings.write_text(json.dumps({
        "hitch_stage_prefix": "9,8,7", "cjb_boss": "54莫阿姆", "sgzx_boss": "08巨形缝合怪",
        "hitch_cycle_num": 42, "hitch_after_goal": "arch",
        "skills": ["s9", "s8", "s7", "s6"], "bonds": ["贪婪"], "click_delay_ms": 350,
    }, ensure_ascii=False), encoding="utf-8")

    assert adr.load_package_identity(bundle) == before


def test_persistable_settings_exclude_release_identity_fields() -> None:
    from shuabao.settings import Settings
    from shuabao.shell.mode_catalog import collect_persistable_settings

    blob = collect_persistable_settings(Settings())
    for forbidden in ("source_sha", "release_manifest_sha256", "release_manifest",
                      "release_channel", "build_identity", "permit"):
        assert forbidden not in blob, f"{forbidden} must not persist into user settings"
