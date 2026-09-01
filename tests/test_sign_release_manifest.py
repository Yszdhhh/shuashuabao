from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
from pathlib import Path

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
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
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
