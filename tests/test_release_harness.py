from __future__ import annotations

import hashlib
import base64
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from PyInstaller.archive.writers import CArchiveWriter

from shuabao import release_signing
from shuabao.release_signing import canonical_manifest_bytes
import tools.release_gate as release_gate
from tools.prepare_manifest_trust import HOOK_NAME, manifest_trust_hook_source, prepare_manifest_trust
from tools.release_harness import _canonical_manifest_sha256, audit_bundle, main


@pytest.fixture
def signing_key(monkeypatch):
    private = Ed25519PrivateKey.generate()
    monkeypatch.setattr(release_signing, "PINNED_MANIFEST_PUBLIC_KEYS", {"test-manifest": private.public_key()})
    return private


def _write_exe(bundle: Path, private: Ed25519PrivateKey) -> None:
    hook = bundle.parent / f"{HOOK_NAME}.py"
    hook.write_text(manifest_trust_hook_source({"test-manifest": private.public_key()}), encoding="utf-8")
    entry = bundle.parent / "desktop_app.py"
    entry.write_text("# Offline archive fixture; never executed.\n", encoding="utf-8")
    CArchiveWriter(str(bundle / "ShuaBao.exe"), [(HOOK_NAME, str(hook), True, "s1"), ("desktop_app", str(entry), True, "s1")], pylib_name="python311.dll")


def _sign_bundle(bundle: Path, private: Ed25519PrivateKey) -> None:
    path = bundle / "release_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["files"] = [
        {"path": item.relative_to(bundle).as_posix(), "size_bytes": item.stat().st_size, "sha256": hashlib.sha256(item.read_bytes()).hexdigest()}
        for item in sorted(bundle.rglob("*"))
        if item.is_file() and item.name not in release_signing.METADATA_FILE_EXCEPTIONS
    ]
    path.write_text(json.dumps(manifest), encoding="utf-8")
    canonical = canonical_manifest_bytes(manifest)
    (bundle / "release_manifest.json.sig").write_text(json.dumps({
        "schema_version": 1, "algorithm": "Ed25519", "key_id": "test-manifest",
        "manifest_sha256": _canonical_manifest_sha256(manifest),
        "signature": base64.urlsafe_b64encode(private.sign(canonical)).rstrip(b"=").decode("ascii"),
    }), encoding="utf-8")
    identity_path = bundle / "build_identity.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    identity["release_manifest_sha256"] = _canonical_manifest_sha256(manifest)
    identity["exe_sha256"] = hashlib.sha256((bundle / "ShuaBao.exe").read_bytes()).hexdigest()
    identity_path.write_text(json.dumps(identity), encoding="utf-8")


def _make_bundle(tmp_path: Path, private: Ed25519PrivateKey, *, timeout_s: int = 10, source_sha: str = "a" * 40, channel: str = "dev") -> tuple[Path, Path]:
    bundle = tmp_path / "ShuaBao"
    internal = bundle / "_internal"
    web_dist = internal / "web" / "dist"
    tls_dir = tmp_path / "python" / "DLLs"
    web_dist.mkdir(parents=True)
    tls_dir.mkdir(parents=True)

    exe = bundle / "ShuaBao.exe"
    exe.parent.mkdir(parents=True, exist_ok=True)
    _write_exe(bundle, private)
    for name, payload in (
        ("libssl-3-x64.dll", b"python-ssl"),
        ("libcrypto-3-x64.dll", b"python-crypto"),
    ):
        (tls_dir / name).write_bytes(payload)
        (internal / name).write_bytes(payload)
    (internal / "_ssl.pyd").write_bytes(b"python-ssl-extension")

    manifest = {
        "schema_version": 1,
        "source_sha": source_sha,
        "release_channel": channel,
        "bridge_schema_version": 2,
        "manifest_signature_status": "SIGNED",
        "files": [],
    }
    (bundle / "release_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (bundle / "subscription_runtime.json").write_text(
        json.dumps({
            "schema_version": 1,
            "base_url": "https://subscription.example",
            "mode": "enforce",
            "release_channel": channel,
            "timeout_s": timeout_s,
        }),
        encoding="utf-8",
    )
    (web_dist / "build_manifest.json").write_text(
        json.dumps({
            "schema_version": 1,
            "source_sha": source_sha,
            "source_tree_clean": True,
            "release_channel": channel,
            "bridge_schema_version": 2,
        }),
        encoding="utf-8",
    )
    config = internal / "config"
    config.mkdir()
    permit_public = Ed25519PrivateKey.generate().public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    (config / "entitlement_public_keys.json").write_text(json.dumps({
        "keys": {"test-permit": base64.b64encode(permit_public).decode("ascii")},
    }), encoding="utf-8")
    (bundle / "build_identity.json").write_text(
        json.dumps({
            "schema_version": 1,
            "source_sha": source_sha,
            "source_tree_clean": True,
            "version": "0.3",
            "exe_name": "ShuaBao.exe",
            "exe_sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
            "bridge_schema_version": 2,
            "release_channel": channel,
            "signature_status": "SIGNED",
            "release_manifest_sha256": _canonical_manifest_sha256(manifest),
        }),
        encoding="utf-8",
    )
    _sign_bundle(bundle, private)
    return bundle, tls_dir.parent


@pytest.mark.parametrize("channel", ["dev", "internal-pilot", "external-beta", "release"])
def test_release_harness_accepts_a_complete_signed_frozen_bundle(tmp_path: Path, signing_key, channel) -> None:
    bundle, python_root = _make_bundle(tmp_path, signing_key, channel=channel)
    report = audit_bundle(
        bundle,
        expected_source_sha="a" * 40,
        python_root=python_root,
        require_clean=True,
    )
    assert report["status"] == "PASS", report["errors"]


def test_release_harness_allows_the_separate_ocr_runtime_root(tmp_path: Path, signing_key) -> None:
    bundle, python_root = _make_bundle(tmp_path, signing_key)
    vision_internal = bundle / "vision" / "_internal"
    vision_internal.mkdir(parents=True)
    for name in ("_ssl.pyd", "libssl-3-x64.dll", "libcrypto-3-x64.dll"):
        (vision_internal / name).write_bytes((bundle / "_internal" / name).read_bytes())
    _sign_bundle(bundle, signing_key)

    report = audit_bundle(
        bundle,
        expected_source_sha="a" * 40,
        python_root=python_root,
        require_clean=True,
    )
    assert report["status"] == "PASS", report["errors"]


def test_release_harness_rejects_stale_identity_and_exe_hash(tmp_path: Path, signing_key) -> None:
    bundle, python_root = _make_bundle(tmp_path, signing_key)
    identity_path = bundle / "build_identity.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    identity["source_sha"] = "b" * 40
    identity["exe_sha256"] = "0" * 64
    identity_path.write_text(json.dumps(identity), encoding="utf-8")

    report = audit_bundle(bundle, expected_source_sha="a" * 40, python_root=python_root)
    assert report["status"] == "FAIL"
    assert any("source_sha_matches" in error for error in report["errors"])
    assert any("frozen_exe_hash_matches" in error for error in report["errors"])


def test_release_harness_rejects_foreign_or_duplicate_tls_dlls(tmp_path: Path, signing_key) -> None:
    bundle, python_root = _make_bundle(tmp_path, signing_key)
    (bundle / "libcrypto-3-x64.dll").write_bytes(b"foreign-poppler-dll")
    (bundle / "_internal" / "libssl-3-x64.dll").write_bytes(b"foreign-python-dll")

    report = audit_bundle(bundle, expected_source_sha="a" * 40, python_root=python_root)
    assert report["status"] == "FAIL"
    assert any("libcrypto-3-x64.dll_unique" in error for error in report["errors"])
    assert any("libssl-3-x64.dll_matches_python" in error for error in report["errors"])


def test_release_harness_rejects_short_https_timeout_and_baked_secret_field(tmp_path: Path, signing_key) -> None:
    bundle, python_root = _make_bundle(tmp_path, signing_key, timeout_s=3)
    runtime_path = bundle / "subscription_runtime.json"
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    runtime["license_key"] = "must-not-be-packaged"
    runtime_path.write_text(json.dumps(runtime), encoding="utf-8")
    _sign_bundle(bundle, signing_key)

    report = audit_bundle(bundle, expected_source_sha="a" * 40, python_root=python_root)
    assert report["status"] == "FAIL"
    assert any("subscription_runtime_no_secrets" in error for error in report["errors"])
    assert any("subscription_timeout_safe" in error for error in report["errors"])


@pytest.mark.parametrize(("field", "value", "check_name"), [
    ("schema_version", 2, "subscription_runtime_schema"),
    ("mode", "off", "subscription_mode_enforced"),
    ("release_channel", "release", "subscription_channel_matches_manifest"),
])
def test_release_harness_rejects_signed_runtime_policy_mismatch(
    tmp_path: Path, signing_key, field, value, check_name,
) -> None:
    bundle, _ = _make_bundle(tmp_path, signing_key)
    runtime_path = bundle / "subscription_runtime.json"
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    runtime[field] = value
    runtime_path.write_text(json.dumps(runtime), encoding="utf-8")
    _sign_bundle(bundle, signing_key)

    report = audit_bundle(bundle, expected_source_sha="a" * 40)

    assert report["status"] == "FAIL"
    assert report["checks"][check_name]["ok"] is False


@pytest.mark.parametrize("reuse_manifest_key", [False, True])
def test_release_harness_rejects_missing_or_reused_permit_trust(
    tmp_path: Path, signing_key, reuse_manifest_key: bool,
) -> None:
    bundle, _ = _make_bundle(tmp_path, signing_key)
    registry_path = bundle / "_internal" / "config" / "entitlement_public_keys.json"
    keys = {}
    if reuse_manifest_key:
        public_der = signing_key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        keys["reused-key"] = base64.b64encode(public_der).decode("ascii")
    registry_path.write_text(json.dumps({"keys": keys}), encoding="utf-8")
    _sign_bundle(bundle, signing_key)

    report = audit_bundle(bundle, expected_source_sha="a" * 40)

    assert report["status"] == "FAIL"
    failed = (
        "manifest_permit_key_separation"
        if reuse_manifest_key else "entitlement_registry_nonempty"
    )
    assert report["checks"][failed]["ok"] is False


@pytest.mark.parametrize("channel", ["dev", "internal-pilot", "external-beta", "release"])
def test_unsigned_frozen_bundle_is_rejected_on_every_channel(tmp_path, signing_key, channel):
    bundle, _ = _make_bundle(tmp_path, signing_key, channel=channel)
    (bundle / "release_manifest.json.sig").unlink()
    report = audit_bundle(bundle, expected_source_sha="a" * 40)
    assert report["status"] == "FAIL"
    assert "MANIFEST_SIGNATURE_MISSING" in report["checks"]["release_manifest_authenticated"]["detail"]


@pytest.mark.parametrize("fault,code", [
    ("unknown_key", "MANIFEST_KEY_UNKNOWN"),
    ("signature", "MANIFEST_SIGNATURE_INVALID"),
    ("manifest", "MANIFEST_HASH_MISMATCH"),
    ("file", "MANIFEST_FILE_MISMATCH"),
    ("trust", "MANIFEST_TRUST_ANCHOR_MISSING"),
])
def test_harness_propagates_production_verifier_failures(tmp_path, signing_key, monkeypatch, fault, code):
    bundle, _ = _make_bundle(tmp_path, signing_key)
    signature_path = bundle / "release_manifest.json.sig"
    signature = json.loads(signature_path.read_text(encoding="utf-8"))
    if fault == "unknown_key":
        signature["key_id"] = "untrusted"
    elif fault == "signature":
        signature["signature"] = base64.urlsafe_b64encode(b"x" * 64).rstrip(b"=").decode("ascii")
    elif fault == "manifest":
        path = bundle / "release_manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["source_sha"] = "b" * 40
        path.write_text(json.dumps(manifest), encoding="utf-8")
    elif fault == "file":
        (bundle / "_internal" / "_ssl.pyd").write_bytes(b"tampered")
    else:
        monkeypatch.setattr(release_signing, "PINNED_MANIFEST_PUBLIC_KEYS", {})
    signature_path.write_text(json.dumps(signature), encoding="utf-8")
    calls = []
    verifier = release_signing.verify_packaged_release_snapshot
    def observed(*args, **kwargs):
        calls.append(args[0])
        return verifier(*args, **kwargs)
    monkeypatch.setattr(release_signing, "verify_packaged_release_snapshot", observed)
    report = audit_bundle(bundle, expected_source_sha="a" * 40)
    assert calls == [bundle.resolve()]
    assert report["status"] == "FAIL"
    assert code in report["checks"]["release_manifest_authenticated"]["detail"]


def test_harness_rejects_manifest_source_identity_and_sidecar_hash_mismatch(tmp_path, signing_key):
    bundle, _ = _make_bundle(tmp_path, signing_key, source_sha="b" * 40)
    path = bundle / "build_identity.json"
    identity = json.loads(path.read_text(encoding="utf-8"))
    identity["release_manifest_sha256"] = "0" * 64
    path.write_text(json.dumps(identity), encoding="utf-8")
    report = audit_bundle(bundle, expected_source_sha="a" * 40)
    assert report["checks"]["release_manifest_authenticated"]["ok"]
    assert not report["checks"]["manifest_source_sha_matches"]["ok"]
    assert not report["checks"]["manifest_hash_matches"]["ok"]


def test_harness_rejects_signed_exe_with_a_different_compiled_public_key(tmp_path, signing_key):
    bundle, _ = _make_bundle(tmp_path, signing_key)
    _write_exe(bundle, Ed25519PrivateKey.generate())
    _sign_bundle(bundle, signing_key)
    report = audit_bundle(bundle, expected_source_sha="a" * 40)
    assert report["checks"]["release_manifest_authenticated"]["ok"]
    assert not report["checks"]["compiled_manifest_trust_matches"]["ok"]
    assert "differs from the operator registry" in report["checks"]["compiled_manifest_trust_matches"]["detail"]


def test_harness_refuses_operator_registry_inside_bundle(tmp_path, signing_key):
    bundle, _ = _make_bundle(tmp_path, signing_key)
    registry = bundle / "operator_keys.json"
    registry.write_text('{"keys": {}}', encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        main(["--bundle", str(bundle), "--manifest-public-keys", str(registry)])
    assert exc.value.code == 2


def _write_manifest_registry(path: Path, key_id: str, private: Ed25519PrivateKey) -> None:
    public_der = private.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    path.write_text(json.dumps({
        "keys": {key_id: base64.b64encode(public_der).decode("ascii")},
    }), encoding="utf-8")


def test_prepare_manifest_trust_emits_public_only_hook_and_checks_key_separation(tmp_path):
    manifest_private = Ed25519PrivateKey.generate()
    permit_private = Ed25519PrivateKey.generate()
    private_path = tmp_path / "manifest-private.pem"
    private_path.write_bytes(manifest_private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    public_path = tmp_path / "manifest-public.json"
    _write_manifest_registry(public_path, "operator-test", manifest_private)
    permit_path = tmp_path / "permit-public.json"
    _write_manifest_registry(permit_path, "permit-test", permit_private)
    hook_path = tmp_path / "hook.py"

    prepare_manifest_trust(
        private_path, public_path, "operator-test", hook_path,
        permit_public_keys_path=permit_path,
    )

    source = hook_path.read_text(encoding="utf-8")
    assert "operator-test" in source
    assert "manifest-private" not in source
    assert "private_bytes" not in source


def test_prepare_manifest_trust_rejects_private_key_inside_source(tmp_path):
    import tools.prepare_manifest_trust as trust

    private = Ed25519PrivateKey.generate()
    private_path = trust.ROOT / "build" / "test-manifest-private.pem"
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_bytes(private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    public_path = tmp_path / "manifest-public.json"
    _write_manifest_registry(public_path, "operator-test", private)
    try:
        with pytest.raises(ValueError, match="outside"):
            prepare_manifest_trust(
                private_path, public_path, "operator-test", tmp_path / "hook.py",
                permit_public_keys_path=public_path,
            )
    finally:
        private_path.unlink(missing_ok=True)


def test_prepare_manifest_trust_rejects_private_public_mismatch_and_reused_permit_key(tmp_path):
    manifest_private = Ed25519PrivateKey.generate()
    other_private = Ed25519PrivateKey.generate()
    private_path = tmp_path / "manifest-private.pem"
    private_path.write_bytes(manifest_private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    public_path = tmp_path / "manifest-public.json"
    _write_manifest_registry(public_path, "other", other_private)
    with pytest.raises(ValueError, match="does not match"):
        prepare_manifest_trust(
            private_path, public_path, "other", tmp_path / "hook.py",
            permit_public_keys_path=public_path,
        )

    _write_manifest_registry(public_path, "operator-test", manifest_private)
    with pytest.raises(ValueError, match="independent"):
        prepare_manifest_trust(
            private_path, public_path, "operator-test", tmp_path / "hook.py",
            permit_public_keys_path=public_path,
        )


def test_build_script_runs_harness_and_reads_shortcut_after_save() -> None:
    text = (Path(__file__).resolve().parents[1] / "build_release.ps1").read_text(encoding="utf-8")
    assert 'tools\\release_harness.py' in text
    assert '"--source-root", $PSScriptRoot' in text
    assert '"--bundle", $target' in text
    assert text.count('"--python-root", $pythonBasePrefix') == 2
    assert 'import sys; print(sys.base_prefix)' in text
    assert "$shortcutProof = $shell.CreateShortcut($lnk)" in text
    assert "$shortcutProof.TargetPath" in text
    assert "$shortcutProof.WorkingDirectory" in text
    assert "$runningDesktopProcesses = @(Get-Process -Name $APP_ID" in text
    assert "shuabao.versioned_install" in text
    assert "ShuaBaoLauncher.vbs" in text
    assert "拒绝切换 current" in text


def test_release_gate_scrubs_live_subscription_environment(monkeypatch) -> None:
    monkeypatch.setenv("SHUABAO_SUBSCRIPTION_MODE", "enforce")
    monkeypatch.setenv("SHUABAO_SUBSCRIPTION_BASE_URL", "https://live.example")
    captured: dict[str, object] = {}

    def fake_run(_argv, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(release_gate.subprocess, "run", fake_run)
    release_gate._run(["python", "-V"])
    child_env = captured["env"]
    assert isinstance(child_env, dict)
    assert "SHUABAO_SUBSCRIPTION_MODE" not in child_env
    assert "SHUABAO_SUBSCRIPTION_BASE_URL" not in child_env
    # The parent test process may still set an unrelated environment variable;
    # this check only proves the child gate environment is isolated.
    assert os.environ.get("SHUABAO_SUBSCRIPTION_MODE") == "enforce"
