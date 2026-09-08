#!/usr/bin/env python3
"""Sign a release manifest with an explicit Ed25519 private-key file."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.release_signing import (  # noqa: E402
    MANIFEST_SCHEMA_VERSION,
    ReleaseManifestError,
    canonical_manifest_bytes,
)

KEY_ENVS = ("SHUABAO_MANIFEST_SIGNING_KEY_PATH", "SHUABAO_MANIFEST_SIGNING_KEY")


def _load_private_key(path: Path) -> Ed25519PrivateKey:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"cannot read private key: {exc}") from exc
    key = None
    for loader in (serialization.load_pem_private_key, serialization.load_der_private_key):
        try:
            key = loader(raw, password=None)
            break
        except (TypeError, ValueError):
            continue
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("private key must be Ed25519; RSA/EC and encrypted keys are rejected")
    return key


def sign_manifest(manifest_path: Path, key_path: Path, key_id: str, output_path: Path) -> None:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise ValueError(f"cannot read manifest: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ValueError(f"manifest must be an object with schema_version={MANIFEST_SCHEMA_VERSION}")
    canonical = canonical_manifest_bytes(manifest)
    signature = _load_private_key(key_path).sign(canonical)
    envelope = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "algorithm": "Ed25519",
        "key_id": key_id,
        "manifest_sha256": hashlib.sha256(canonical).hexdigest(),
        "signature": base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii"),
    }
    output_path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--private-key", type=Path, default=None, help=f"Ed25519 key path (or {', '.join(KEY_ENVS)})")
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    env_key_path = next((os.environ[name] for name in KEY_ENVS if os.environ.get(name)), None)
    key_path = args.private_key or (Path(env_key_path) if env_key_path else None)
    if key_path is None:
        parser.error(f"--private-key or one of {', '.join(KEY_ENVS)} is required")
    if not args.key_id.strip():
        parser.error("--key-id must not be empty")
    output_path = args.output or args.manifest.with_name(args.manifest.name + ".sig")
    try:
        sign_manifest(args.manifest, key_path, args.key_id, output_path)
    except (OSError, ValueError, ReleaseManifestError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": "SIGNED", "manifest": str(args.manifest), "signature": str(output_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
