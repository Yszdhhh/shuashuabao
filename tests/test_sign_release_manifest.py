from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "sign_release_manifest.py"


def _manifest(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source_sha": "a" * 40,
                "release_channel": "release",
                "files": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _key(path: Path) -> Ed25519PrivateKey:
    private = Ed25519PrivateKey.generate()
    path.write_bytes(
        private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return private


def _run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    child_env = {**os.environ, **(env or {})}
    child_env.setdefault("PYTHONIOENCODING", "utf-8")
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        cwd=ROOT,
        env=child_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def test_signer_emits_runtime_verifiable_envelope(tmp_path: Path) -> None:
    manifest = tmp_path / "release_manifest.json"
    key_path = tmp_path / "manifest-key.pem"
    _manifest(manifest)
    private = _key(key_path)
    original_key = key_path.read_bytes()

    proc = _run("--manifest", str(manifest), "--private-key", str(key_path), "--key-id", "manifest")

    assert proc.returncode == 0, proc.stderr
    signature_path = tmp_path / "release_manifest.json.sig"
    envelope = json.loads(signature_path.read_text(encoding="utf-8"))
    assert envelope["schema_version"] == 1
    assert envelope["algorithm"] == "Ed25519"
    assert envelope["key_id"] == "manifest"
    canonical = json.dumps(json.loads(manifest.read_text(encoding="utf-8")), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    assert envelope["manifest_sha256"] == hashlib.sha256(canonical).hexdigest()
    signature = base64.urlsafe_b64decode(envelope["signature"] + "==")
    private.public_key().verify(signature, canonical)
    assert key_path.read_bytes() == original_key


def test_signer_accepts_explicit_key_path_environment(tmp_path: Path) -> None:
    manifest = tmp_path / "release_manifest.json"
    key_path = tmp_path / "manifest-key.pem"
    _manifest(manifest)
    _key(key_path)
    env = {**__import__("os").environ, "SHUABAO_MANIFEST_SIGNING_KEY": str(key_path)}

    proc = _run("--manifest", str(manifest), "--key-id", "manifest", env=env)

    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "release_manifest.json.sig").is_file()


def test_signer_rejects_non_ed25519_key(tmp_path: Path) -> None:
    manifest = tmp_path / "release_manifest.json"
    key_path = tmp_path / "rsa.pem"
    _manifest(manifest)
    from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key

    key_path.write_bytes(
        generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )

    proc = _run("--manifest", str(manifest), "--private-key", str(key_path), "--key-id", "manifest")

    assert proc.returncode != 0
    assert "Ed25519" in proc.stderr
    assert not (tmp_path / "release_manifest.json.sig").exists()


def test_signer_requires_key_id_and_never_uses_implicit_key(tmp_path: Path) -> None:
    manifest = tmp_path / "release_manifest.json"
    key_path = tmp_path / "manifest-key.pem"
    _manifest(manifest)
    _key(key_path)

    proc = _run("--manifest", str(manifest), "--private-key", str(key_path))

    assert proc.returncode != 0
    assert "key-id" in proc.stderr

def test_signer_rejects_non_utf8_canonical_manifest_without_output(tmp_path: Path) -> None:
    manifest = tmp_path / "release_manifest.json"
    key_path = tmp_path / "manifest-key.pem"
    manifest.write_text(r'{"schema_version": 1, "value": "\ud800"}', encoding="utf-8")
    _key(key_path)

    proc = _run("--manifest", str(manifest), "--private-key", str(key_path), "--key-id", "manifest")

    assert proc.returncode != 0
    assert "不可规范化" in proc.stderr
    assert not (tmp_path / "release_manifest.json.sig").exists()


def test_canonical_manifest_sha256_matches_canonical_bytes() -> None:
    from shuabao.release_signing import canonical_manifest_bytes, canonical_manifest_sha256

    manifest = {"files": [], "release_channel": "release", "schema_version": 1, "source_sha": "a" * 40}
    assert canonical_manifest_sha256(manifest) == hashlib.sha256(canonical_manifest_bytes(manifest)).hexdigest()
    # 键序与空白差异必须得到同一摘要
    assert canonical_manifest_sha256({"schema_version": 1, "source_sha": "a" * 40, "release_channel": "release", "files": []}) == canonical_manifest_sha256(manifest)


def test_verify_manifest_files_rejects_extra_file_outside_metadata_exceptions(tmp_path: Path) -> None:
    from shuabao.release_signing import ReleaseManifestError, verify_manifest_files

    payload = b"attested"
    (tmp_path / "data.bin").write_bytes(payload)
    manifest = {"files": [{"path": "data.bin", "size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}]}
    assert verify_manifest_files(manifest, tmp_path) == {"data.bin": payload}

    for name in ("release_manifest.json", "release_manifest.json.sig", "build_identity.json"):
        (tmp_path / name).write_bytes(b"meta")
        assert verify_manifest_files(manifest, tmp_path) == {"data.bin": payload}

    (tmp_path / "evil_plugin.dll").write_bytes(b"x")
    with pytest.raises(ReleaseManifestError, match="MANIFEST_EXTRA_FILE"):
        verify_manifest_files(manifest, tmp_path)


def test_verify_manifest_files_allows_directories_and_attests_nested_files(tmp_path: Path) -> None:
    from shuabao.release_signing import verify_manifest_files

    registry = tmp_path / "config" / "_internal" / "entitlement_public_keys.json"
    registry.parent.mkdir(parents=True)
    registry.write_bytes(b"keys")
    manifest = {"files": [{
        "path": "config/_internal/entitlement_public_keys.json",
        "size_bytes": registry.stat().st_size,
        "sha256": hashlib.sha256(registry.read_bytes()).hexdigest(),
    }]}
    # 目录本身不参与 manifest 条目比较；只有 regular files 需要被 attest 或属于元数据例外。
    assert verify_manifest_files(manifest, tmp_path) == {"config/_internal/entitlement_public_keys.json": b"keys"}


def _signed_package(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from shuabao.release_signing import canonical_manifest_bytes

    package = tmp_path / "ShuaBao"
    package.mkdir()
    files = []
    for relative, payload in (
        ("config/entitlement_public_keys.json", b'{"keys": {}}'),
        ("subscription_runtime.json", b'{"schema_version":1}'),
        ("ShuaBao.exe", b"exe"),
    ):
        path = package / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        files.append({
            "path": relative,
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        })
    manifest = {
        "schema_version": 1,
        "source_sha": "a" * 40,
        "release_channel": "internal-pilot",
        "bridge_schema_version": 2,
        "files": files,
    }
    canonical = canonical_manifest_bytes(manifest)
    (package / "release_manifest.json").write_bytes(canonical)
    private = Ed25519PrivateKey.generate()
    envelope = {
        "schema_version": 1,
        "algorithm": "Ed25519",
        "key_id": "manifest",
        "manifest_sha256": hashlib.sha256(canonical).hexdigest(),
        "signature": base64.urlsafe_b64encode(private.sign(canonical)).rstrip(b"=").decode("ascii"),
    }
    (package / "release_manifest.json.sig").write_text(json.dumps(envelope), encoding="utf-8")
    return package, {"manifest": private.public_key()}


def test_verify_packaged_release_snapshot_reuses_process_cache(tmp_path: Path, monkeypatch) -> None:
    from shuabao import release_signing as rs

    rs.clear_packaged_release_verify_cache()
    package, keys = _signed_package(tmp_path)
    calls = {"n": 0}
    real = rs._verify_packaged_release

    def counted(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(rs, "_verify_packaged_release", counted)
    first = rs.verify_packaged_release_snapshot(
        package, pinned_keys=keys, required_files=("subscription_runtime.json",)
    )
    second = rs.verify_packaged_release_snapshot(
        package, pinned_keys=keys, required_files=("config/entitlement_public_keys.json",)
    )
    assert calls["n"] == 1
    assert first[0]["source_sha"] == second[0]["source_sha"]
    assert "config/entitlement_public_keys.json" in second[1]


def test_verify_cache_invalidates_when_manifest_changes(tmp_path: Path, monkeypatch) -> None:
    from shuabao import release_signing as rs

    rs.clear_packaged_release_verify_cache()
    package, keys = _signed_package(tmp_path)
    calls = {"n": 0}
    real = rs._verify_packaged_release

    def counted(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(rs, "_verify_packaged_release", counted)
    rs.verify_packaged_release_snapshot(package, pinned_keys=keys)
    (package / "release_manifest.json").write_bytes(b'{"schema_version": 1}')
    with pytest.raises(rs.ReleaseManifestError):
        rs.verify_packaged_release_snapshot(package, pinned_keys=keys)
    assert calls["n"] == 2


def test_verify_cache_fail_closed_without_rehash(tmp_path: Path, monkeypatch) -> None:
    from shuabao import release_signing as rs

    rs.clear_packaged_release_verify_cache()
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "release_manifest.json").write_text("{}", encoding="utf-8")
    (package / "release_manifest.json.sig").write_text("{}", encoding="utf-8")
    calls = {"n": 0}
    real = rs._verify_packaged_release

    def counted(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(rs, "_verify_packaged_release", counted)
    with pytest.raises(rs.ReleaseManifestError, match="MANIFEST_TRUST_ANCHOR_MISSING"):
        rs.verify_packaged_release_snapshot(package, pinned_keys={})
    with pytest.raises(rs.ReleaseManifestError, match="MANIFEST_TRUST_ANCHOR_MISSING"):
        rs.verify_packaged_release_snapshot(package, pinned_keys={})
    assert calls["n"] == 1
