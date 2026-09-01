from __future__ import annotations

import base64
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from shuabao.shell import live_execute
from shuabao.shell.live_execute import PermissionDenied, resolve_live_permission, start_permission_allows
from shuabao.subscription_client import StartPermission
from shuabao.subscription_permit import (
    DevStartCapability,
    EntitlementPermit,
    PermitVerificationError,
    VerifiedPermit,
)



def _manifest(root: Path, private: Ed25519PrivateKey, *, tamper: bool = False, internal: bool = False) -> None:
    relative = "config/entitlement_public_keys.json"
    if internal:
        relative = "_internal/config/entitlement_public_keys.json"
    registry = root / relative
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text("{\"keys\": {}}", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "source_sha": "a" * 40,
        "release_channel": "stable",
        "files": [{
            "path": relative,
            "size_bytes": registry.stat().st_size,
            "sha256": hashlib.sha256(registry.read_bytes()).hexdigest(),
        }],
    }
    canonical = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    (root / "release_manifest.json").write_bytes(canonical)
    signature = b"0" * 64 if tamper else private.sign(canonical)
    envelope = {
        "schema_version": 1,
        "algorithm": "Ed25519",
        "key_id": "manifest",
        "manifest_sha256": hashlib.sha256(canonical).hexdigest(),
        "signature": base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii"),
    }
    (root / "release_manifest.json.sig").write_text(json.dumps(envelope), encoding="utf-8")
    (root / "build_identity.json").write_text(json.dumps({
        "source_sha": manifest["source_sha"],
        "release_manifest_sha256": hashlib.sha256(canonical).hexdigest(),
        "release_channel": manifest["release_channel"],
    }), encoding="utf-8")


def test_forged_verified_permit_is_not_executor_authorization():
    forged = VerifiedPermit("p", "l", "d", "stable", ("mode",), ("run",), datetime.now(timezone.utc), "k")
    assert not start_permission_allows(forged)


def test_direct_dev_capability_requires_off_mode(monkeypatch):
    monkeypatch.setenv("SHUABAO_SUBSCRIPTION_MODE", "enforce")
    assert not start_permission_allows(DevStartCapability.for_off())


def test_packaged_dev_capability_is_rejected(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "ShuaBao.exe"))
    with pytest.raises(PermissionDenied, match="PERMIT_DEV_PACKAGED"):
        resolve_live_permission(DevStartCapability.for_off(), mode_id="mode", root=tmp_path)


def test_channel_environment_override_is_ignored(monkeypatch):
    monkeypatch.setenv("SHUABAO_RELEASE_CHANNEL", "external-beta")
    private = Ed25519PrivateKey.generate()
    identity = live_execute._LiveIdentity(
        "a" * 40,
        "b" * 64,
        "stable",
        False,
        Path("."),
        Path("config") / "entitlement_public_keys.json",
        {"k": private.public_key()},
    )
    permit_data = {
        "schema_version": 1,
        "permit_id": "p",
        "jti": "p",
        "license_id": "l",
        "device_id": "device",
        "device_fingerprint": "device",
        "release_channel": "stable",
        "source_sha": "a" * 40,
        "release_manifest_sha256": "b" * 64,
        "allowed_modes": ["mode"],
        "features": ["run"],
        "issued_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "nonce": "n",
        "signature_algorithm": "Ed25519",
        "key_id": "k",
    }
    permit_data["signature"] = base64.urlsafe_b64encode(private.sign(json.dumps(permit_data, sort_keys=True, separators=(",", ":")).encode())).rstrip(b"=").decode()
    permit = EntitlementPermit.from_mapping(permit_data)
    root = Path(".")
    monkeypatch.setattr(live_execute, "_live_identity", lambda _root: identity)
    monkeypatch.setenv("SHUABAO_SUBSCRIPTION_DEVICE_FINGERPRINT", "device")
    assert resolve_live_permission(StartPermission(True, "enforce", permit=permit), mode_id="mode", root=root).permit_id == "p"



def test_frozen_registry_path_uses_authenticated_executable_root(tmp_path: Path, monkeypatch):
    private = Ed25519PrivateKey.generate()
    _manifest(tmp_path, private, internal=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "ShuaBao.exe"))
    manifest = json.loads((tmp_path / "release_manifest.json").read_text(encoding="utf-8"))
    caller_root = tmp_path / "caller-root"
    (caller_root / "_internal" / "config").mkdir(parents=True)
    (caller_root / "_internal" / "config" / "entitlement_public_keys.json").write_text("replaced", encoding="utf-8")
    relative = "_internal/config/entitlement_public_keys.json"
    monkeypatch.setattr(
        live_execute,
        "verify_packaged_release_snapshot",
        lambda *_a, **_kw: (manifest, {relative: (tmp_path / relative).read_bytes()}),
    )
    identity = live_execute._live_identity(caller_root)
    assert identity.registry_path == tmp_path / "_internal" / "config" / "entitlement_public_keys.json"

def test_tampered_entitlement_registry_is_rejected(tmp_path: Path):
    private = Ed25519PrivateKey.generate()
    _manifest(tmp_path, private)
    key = {"manifest": private.public_key()}
    from shuabao.release_signing import verify_packaged_release, ReleaseManifestError

    (tmp_path / "config" / "entitlement_public_keys.json").write_text("tampered", encoding="utf-8")
    with pytest.raises(ReleaseManifestError, match="MANIFEST_FILE_MISMATCH"):
        verify_packaged_release(tmp_path, pinned_keys=key, required_files=("config/entitlement_public_keys.json",))


def test_manifest_signature_success_and_failure(tmp_path: Path):
    private = Ed25519PrivateKey.generate()
    _manifest(tmp_path, private)
    from shuabao.release_signing import verify_packaged_release, ReleaseManifestError

    assert verify_packaged_release(tmp_path, pinned_keys={"manifest": private.public_key()})["source_sha"] == "a" * 40
    bad = {
        "schema_version": 1,
        "algorithm": "Ed25519",
        "key_id": "manifest",
        "manifest_sha256": hashlib.sha256((tmp_path / "release_manifest.json").read_bytes()).hexdigest(),
        "signature": base64.urlsafe_b64encode(b"0" * 64).rstrip(b"=").decode("ascii"),
    }
    (tmp_path / "release_manifest.json.sig").write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ReleaseManifestError, match="MANIFEST_SIGNATURE_INVALID"):
        verify_packaged_release(tmp_path, pinned_keys={"manifest": private.public_key()})


def test_manifest_attests_internal_config_layout(tmp_path: Path):
    private = Ed25519PrivateKey.generate()
    _manifest(tmp_path, private, internal=True)
    from shuabao.release_signing import verify_packaged_release

    manifest = verify_packaged_release(
        tmp_path,
        pinned_keys={"manifest": private.public_key()},
        required_files=("config/entitlement_public_keys.json",),
    )
    assert manifest["files"][0]["path"].startswith("_internal/")


def test_lone_surrogate_permit_text_is_malformed():
    payload = {
        "schema_version": 1,
        "permit_id": "p",
        "jti": "p",
        "license_id": "\ud800",
        "device_id": "d",
        "device_fingerprint": "d",
        "release_channel": "stable",
        "source_sha": "a" * 40,
        "release_manifest_sha256": "b" * 64,
        "allowed_modes": ["mode"],
        "features": ["run"],
        "issued_at": "2026-09-01T12:00:00Z",
        "expires_at": "2026-09-01T13:00:00Z",
        "nonce": "n",
        "signature_algorithm": "Ed25519",
        "key_id": "k",
        "signature": "AA",
    }
    with pytest.raises(PermitVerificationError, match="PERMIT_MALFORMED"):
        EntitlementPermit.from_mapping(payload)


def test_packaged_identity_mismatch_is_untrusted(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "ShuaBao.exe"))
    manifest = {"schema_version": 1, "source_sha": "a" * 40, "release_channel": "stable", "files": []}
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    (tmp_path / "release_manifest.json").write_bytes(manifest_bytes)
    (tmp_path / "build_identity.json").write_text(json.dumps({
        "source_sha": "wrong",
        "release_channel": "stable",
        "release_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
    }), encoding="utf-8")
    monkeypatch.setattr(live_execute, "verify_packaged_release_snapshot", lambda *_a, **_kw: (manifest, {}))
    identity = live_execute._live_identity(tmp_path)
    assert identity.source_sha == identity.manifest_sha == identity.release_channel == ""
    assert identity.packaged


def test_frozen_malformed_attested_registry_fails_closed(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "ShuaBao.exe"))
    relative = "_internal/config/entitlement_public_keys.json"
    registry_bytes = b"not-json"
    manifest = {
        "schema_version": 1,
        "source_sha": "a" * 40,
        "release_channel": "stable",
        "files": [{
            "path": relative,
            "size_bytes": len(registry_bytes),
            "sha256": hashlib.sha256(registry_bytes).hexdigest(),
        }],
    }
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    (tmp_path / "release_manifest.json").write_bytes(manifest_bytes)
    (tmp_path / "build_identity.json").write_text(json.dumps({
        "source_sha": "a" * 40,
        "release_channel": "stable",
        "release_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
    }), encoding="utf-8")
    monkeypatch.setattr(
        live_execute,
        "verify_packaged_release_snapshot",
        lambda *_a, **_kw: (manifest, {relative: registry_bytes}),
    )
    identity = live_execute._live_identity(tmp_path)
    assert identity.packaged and not identity.registry_keys
