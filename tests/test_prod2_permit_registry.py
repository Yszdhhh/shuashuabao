"""Production permit key rotation: shuabao-prod-2 registry + verify coverage."""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from shuabao.subscription_permit import (
    EntitlementPermit,
    PermitVerificationContext,
    PermitVerificationError,
    PermitVerifier,
    load_public_keys,
)

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config" / "entitlement_public_keys.json"
PROD2_SPKI_B64 = "MCowBQYDK2VwAyEAwhUpOiz+2LZNNnDOBCaQjVeQ61lZAI7DfATbAUCrFNY="
PROD2_SPKI_SHA256 = "884dfb991e631b3cb29f29360bbaafe73fd788a65e8bc4d25b361112e78bf1fb"
FIXTURE = ROOT / "tests" / "fixtures" / "prod2_signed_permit.json"
NOW = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)


def test_prod2_registry_loads():
    keys = load_public_keys(REGISTRY)
    assert "shuabao-prod-1" in keys
    assert "shuabao-prod-2" in keys


def test_prod2_is_ed25519_public_key():
    keys = load_public_keys(REGISTRY)
    assert isinstance(keys["shuabao-prod-2"], Ed25519PublicKey)


def test_prod2_fingerprint_matches_midplatform():
    raw = json.loads(REGISTRY.read_text(encoding="utf-8"))["keys"]["shuabao-prod-2"]
    der = base64.b64decode(raw)
    assert raw == PROD2_SPKI_B64
    assert hashlib.sha256(der).hexdigest() == PROD2_SPKI_SHA256


def test_prod1_still_loads_for_compat():
    keys = load_public_keys(REGISTRY)
    assert isinstance(keys["shuabao-prod-1"], Ed25519PublicKey)
    der = base64.b64decode(json.loads(REGISTRY.read_text(encoding="utf-8"))["keys"]["shuabao-prod-1"])
    assert hashlib.sha256(der).hexdigest() == (
        "edb85e258a12e06004ee3b1019fe14f091ea0545ae322251f4af392beed65d4a"
    )


def _prod2_context() -> PermitVerificationContext:
    return PermitVerificationContext(
        device_id="device-a",
        source_sha="a" * 40,
        release_manifest_sha256="b" * 64,
        release_channel="internal-pilot",
        mode_id="live",
        now=NOW,
    )


def test_prod2_signed_permit_verifies():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    keys = load_public_keys(REGISTRY)
    result = PermitVerifier(keys).verify(EntitlementPermit.from_mapping(payload), _prod2_context())
    assert result.permit_id == "pmt-prod2-fixture"


def test_unknown_key_id_rejected_against_prod_registry():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["key_id"] = "shuabao-prod-999"
    with pytest.raises(PermitVerificationError) as excinfo:
        PermitVerifier(load_public_keys(REGISTRY)).verify(
            EntitlementPermit.from_mapping(payload), _prod2_context()
        )
    assert excinfo.value.code == "PERMIT_KEY_UNKNOWN"


def test_tampered_prod2_permit_rejected():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["license_id"] = "lic-evil"
    with pytest.raises(PermitVerificationError) as excinfo:
        PermitVerifier(load_public_keys(REGISTRY)).verify(
            EntitlementPermit.from_mapping(payload), _prod2_context()
        )
    assert excinfo.value.code == "PERMIT_SIGNATURE_INVALID"
