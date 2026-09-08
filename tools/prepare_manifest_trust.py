#!/usr/bin/env python3
"""Validate operator signing material and emit a public-only frozen runtime hook."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Mapping

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from shuabao.release_signing import ReleaseManifestError, load_manifest_public_keys
from tools.sign_release_manifest import _load_private_key

HOOK_NAME = "pyi_rth_manifest_trust"


def manifest_trust_hook_source(keys: Mapping[str, Ed25519PublicKey]) -> str:
    """The hook is compiled into the EXE; it never reads a runtime registry."""
    if not keys or any(not key_id.strip() or key_id != key_id.strip() for key_id in keys):
        raise ValueError("manifest trust registry must contain non-empty, trimmed key ids")
    entries = "".join(
        f"    {key_id!r}: _load_der_public_key(bytes.fromhex({key.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo).hex()!r})),\n"
        for key_id, key in sorted(keys.items())
    )
    return (
        "# Build-time operator public keys; no runtime file or environment lookup.\n"
        "from cryptography.hazmat.primitives.serialization import load_der_public_key as _load_der_public_key\n"
        "import shuabao.release_signing as _release_signing\n"
        "_release_signing.PINNED_MANIFEST_PUBLIC_KEYS = {\n"
        + entries
        + "}\n"
        "del _release_signing, _load_der_public_key\n"
    )


def require_external_key_path(path: Path, *forbidden_roots: Path) -> Path:
    resolved = path.resolve()
    if any(resolved.is_relative_to(root.resolve()) for root in forbidden_roots):
        raise ValueError("operator key material must be outside the source and bundle directories")
    if not resolved.is_file():
        raise ValueError("operator key file is missing")
    return resolved


def prepare_manifest_trust(
    private_key_path: Path, public_keys_path: Path, key_id: str, output_hook: Path,
    *, permit_public_keys_path: Path = ROOT / "config" / "entitlement_public_keys.json",
) -> None:
    private_key_path = require_external_key_path(private_key_path, ROOT)
    public_keys_path = require_external_key_path(public_keys_path, ROOT)
    keys = load_manifest_public_keys(public_keys_path)
    source = manifest_trust_hook_source(keys)
    public = _load_private_key(private_key_path).public_key()
    raw_public = public.public_bytes(Encoding.Raw, PublicFormat.Raw)
    if key_id not in keys or keys[key_id].public_bytes(Encoding.Raw, PublicFormat.Raw) != raw_public:
        raise ValueError("manifest private key does not match the selected operator public key")
    permit_keys = load_manifest_public_keys(permit_public_keys_path)
    if not permit_keys:
        raise ValueError("permit public-key registry must contain at least one Ed25519 key")
    manifest_raw = {key.public_bytes(Encoding.Raw, PublicFormat.Raw) for key in keys.values()}
    if any(key.public_bytes(Encoding.Raw, PublicFormat.Raw) in manifest_raw for key in permit_keys.values()):
        raise ValueError("manifest and permit signing keys must be independent")
    output_hook.parent.mkdir(parents=True, exist_ok=True)
    output_hook.write_text(source, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--public-keys", type=Path, required=True)
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--output-hook", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        prepare_manifest_trust(args.private_key, args.public_keys, args.key_id, args.output_hook)
    except (OSError, ValueError, ReleaseManifestError) as exc:
        print(f"BLOCKED: manifest signing material invalid: {exc}", file=sys.stderr)
        return 2
    print("Manifest operator key verified; public-only runtime hook prepared.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
