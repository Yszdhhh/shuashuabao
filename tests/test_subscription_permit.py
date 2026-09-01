"""Signed entitlement permit 验证契约测试（TDD: 先 RED 后实现）。

覆盖：合法签名、canonical 形态、结构畸形、未知 schema/key、坏签名、
过期/未来签发、device/source/manifest/channel/mode 绑定、重放。
Ed25519 私钥仅存在于本测试进程内存，绝不落盘。
"""
from __future__ import annotations

import base64
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from shuabao.subscription_permit import (
    DevStartCapability,
    EntitlementPermit,
    InMemoryReplayStore,
    PermitVerificationContext,
    PermitVerificationError,
    PermitVerifier,
    load_public_keys,
)

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
KEY_ID = "test-ed25519-1"
PRIVATE_KEY = Ed25519PrivateKey.generate()
PUBLIC_KEY = PRIVATE_KEY.public_key()


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _permit_payload(**overrides: object) -> dict:
    payload = {
        "schema_version": 1,
        "permit_id": "pmt-0001",
        "jti": "pmt-0001",
        "license_id": "lic-0001",
        "device_id": "device-a",
        "device_fingerprint": "device-a",
        "release_channel": "stable",
        "source_sha": "a" * 40,
        "release_manifest_sha256": "b" * 64,
        "allowed_modes": ["live"],
        "features": ["run"],
        "issued_at": _iso(NOW - timedelta(minutes=1)),
        "expires_at": _iso(NOW + timedelta(hours=1)),
        "nonce": "nonce-0001",
        "signature_algorithm": "Ed25519",
        "key_id": KEY_ID,
    }
    payload.update(overrides)
    return payload


def _signed_permit(**overrides: object) -> EntitlementPermit:
    payload = _permit_payload(**overrides)
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    payload["signature"] = _b64url(PRIVATE_KEY.sign(canonical))
    return EntitlementPermit.from_mapping(payload)


def _context(**overrides: object) -> PermitVerificationContext:
    kwargs = {
        "device_id": "device-a",
        "source_sha": "a" * 40,
        "release_manifest_sha256": "b" * 64,
        "release_channel": "stable",
        "mode_id": "live",
        "now": NOW,
    }
    kwargs.update(overrides)
    return PermitVerificationContext(**kwargs)


def _verifier(**kwargs: object) -> PermitVerifier:
    return PermitVerifier({KEY_ID: PUBLIC_KEY}, **kwargs)


def _mapping_code(payload: object) -> str:
    with pytest.raises(PermitVerificationError) as excinfo:
        EntitlementPermit.from_mapping(payload)
    return excinfo.value.code


def _verify_code(permit: EntitlementPermit, context: PermitVerificationContext) -> str:
    with pytest.raises(PermitVerificationError) as excinfo:
        _verifier().verify(permit, context)
    return excinfo.value.code


def test_valid_permit_verifies_and_exposes_fields():
    verified = _verifier().verify(_signed_permit(), _context())

    assert verified.permit_id == "pmt-0001"
    assert verified.license_id == "lic-0001"
    assert verified.device_id == "device-a"
    assert verified.release_channel == "stable"
    assert verified.allowed_modes == ("live",)
    assert verified.features == ("run",)
    assert verified.key_id == KEY_ID
    assert verified.expires_at == NOW + timedelta(hours=1)


def test_canonical_payload_is_deterministic_and_excludes_signature():
    permit = _signed_permit()
    expected = json.dumps(
        _permit_payload(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")

    assert permit.canonical_payload() == expected
    assert permit.canonical_payload() == permit.canonical_payload()


def test_malformed_missing_required_field_rejected():
    payload = _permit_payload()
    del payload["nonce"]

    assert _mapping_code(payload) == "PERMIT_MALFORMED"


def test_malformed_unknown_extra_field_rejected():
    payload = _permit_payload(extra_field="surprise")

    assert _mapping_code(payload) == "PERMIT_MALFORMED"


def test_malformed_wrong_type_rejected():
    assert _mapping_code(_permit_payload(allowed_modes="live")) == "PERMIT_MALFORMED"
    assert _mapping_code(_permit_payload(nonce=12345)) == "PERMIT_MALFORMED"
    assert _mapping_code(_permit_payload(features=["run", 7])) == "PERMIT_MALFORMED"


def test_malformed_identity_pairs_must_match():
    assert _mapping_code(_permit_payload(jti="pmt-other")) == "PERMIT_MALFORMED"
    assert _mapping_code(_permit_payload(device_fingerprint="device-b")) == "PERMIT_MALFORMED"


def test_malformed_non_mapping_rejected():
    assert _mapping_code("not-a-mapping") == "PERMIT_MALFORMED"
    assert _mapping_code(None) == "PERMIT_MALFORMED"


def test_malformed_timestamp_shape_rejected():
    assert _mapping_code(_permit_payload(issued_at="2026-09-01T12:00:00")) == "PERMIT_MALFORMED"
    assert _mapping_code(_permit_payload(expires_at="not-a-time")) == "PERMIT_MALFORMED"


def test_unknown_schema_version_rejected():
    for bad in (2, "1"):
        payload = _permit_payload(schema_version=bad)
        payload["signature"] = "AAAA"
        assert _mapping_code(payload) == "PERMIT_SCHEMA_UNKNOWN"


def test_signature_algorithm_must_be_exactly_ed25519():
    payload = _permit_payload(signature_algorithm="ES256")
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    payload["signature"] = _b64url(PRIVATE_KEY.sign(canonical))

    assert _mapping_code(payload) == "PERMIT_MALFORMED"


def test_malformed_signature_encoding_rejected():
    payload = _permit_payload()
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    payload["signature"] = base64.urlsafe_b64encode(PRIVATE_KEY.sign(canonical)).decode()

    assert _mapping_code(payload) == "PERMIT_MALFORMED"


def test_empty_public_registry_fails_closed():
    verifier = PermitVerifier({})

    with pytest.raises(PermitVerificationError) as excinfo:
        verifier.verify(_signed_permit(), _context())

    assert excinfo.value.code == "PERMIT_KEY_UNKNOWN"


def test_unknown_key_id_rejected():
    assert _verify_code(_signed_permit(key_id="rogue-key"), _context()) == "PERMIT_KEY_UNKNOWN"


def test_production_registry_file_ships_empty_and_fails_closed():
    keys = load_public_keys(ROOT / "config" / "entitlement_public_keys.json")
    assert keys == {}

    with pytest.raises(PermitVerificationError) as excinfo:
        PermitVerifier(keys).verify(_signed_permit(), _context())

    assert excinfo.value.code == "PERMIT_KEY_UNKNOWN"




def test_garbage_signature_bytes_rejected():
    assert _verify_code(_permit_from_signature(b"\x00" * 64), _context()) == "PERMIT_SIGNATURE_INVALID"


def _permit_from_signature(signature: bytes) -> EntitlementPermit:
    payload = _permit_payload()
    payload["signature"] = _b64url(signature)
    return EntitlementPermit.from_mapping(payload)


def test_tampered_payload_rejected():
    payload = _permit_payload()
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    signature = _b64url(PRIVATE_KEY.sign(canonical))
    payload["license_id"] = "lic-evil"
    payload["signature"] = signature

    with pytest.raises(PermitVerificationError) as excinfo:
        _verifier().verify(EntitlementPermit.from_mapping(payload), _context())

    assert excinfo.value.code == "PERMIT_SIGNATURE_INVALID"


def test_future_issued_beyond_skew_rejected():
    permit = _signed_permit(issued_at=_iso(NOW + timedelta(minutes=10)))

    assert _verify_code(permit, _context()) == "PERMIT_NOT_YET_VALID"


def test_future_issued_within_skew_accepted():
    permit = _signed_permit(issued_at=_iso(NOW + timedelta(seconds=60)))

    assert _verifier().verify(permit, _context()).permit_id == "pmt-0001"


@pytest.mark.parametrize(
    "overrides, code",
    [
        ({"device_id": "device-b"}, "PERMIT_DEVICE_MISMATCH"),
        ({"source_sha": "c" * 40}, "PERMIT_SOURCE_MISMATCH"),
        ({"release_manifest_sha256": "d" * 64}, "PERMIT_MANIFEST_MISMATCH"),
        ({"release_channel": "beta"}, "PERMIT_CHANNEL_MISMATCH"),
        ({"mode_id": "boss"}, "PERMIT_MODE_NOT_ALLOWED"),
    ],
)
def test_binding_mismatches_rejected(overrides: dict, code: str):
    permit = _signed_permit()

    assert _verify_code(permit, _context(**overrides)) == code


def test_replay_store_rejects_duplicate_permit():
    store = InMemoryReplayStore()
    verifier = _verifier(replay_store=store)
    permit = _signed_permit()

    verifier.verify(permit, _context())
    with pytest.raises(PermitVerificationError) as excinfo:
        verifier.verify(permit, _context())

    assert excinfo.value.code == "PERMIT_REPLAY"


def test_replay_store_rejects_same_permit_id_with_new_nonce():
    store = InMemoryReplayStore()
    verifier = _verifier(replay_store=store)

    verifier.verify(_signed_permit(nonce="nonce-0001"), _context())
    with pytest.raises(PermitVerificationError) as excinfo:
        verifier.verify(_signed_permit(nonce="nonce-0002"), _context())

    assert excinfo.value.code == "PERMIT_REPLAY"


def test_replay_store_is_atomic_under_concurrency():
    store = InMemoryReplayStore()
    verifier = _verifier(replay_store=store)
    permit = _signed_permit()

    def attempt(_index: int) -> bool:
        try:
            verifier.verify(permit, _context())
            return True
        except PermitVerificationError as exc:
            assert exc.code == "PERMIT_REPLAY"
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(8)))

    assert results.count(True) == 1


def test_verifier_rejects_raw_mapping_as_permit():
    with pytest.raises(TypeError):
        _verifier().verify(_permit_payload(), _context())


def test_dev_start_capability_exists_only_for_off_mode():
    capability = DevStartCapability.for_off()

    assert capability.mode == "off"
    with pytest.raises(ValueError):
        DevStartCapability(mode="enforce")
    with pytest.raises(ValueError):
        DevStartCapability(mode="shadow")


def test_invalid_signature_does_not_consume_replay_slot():
    store = InMemoryReplayStore()
    verifier = PermitVerifier({KEY_ID: PUBLIC_KEY}, replay_store=store)

    with pytest.raises(PermitVerificationError) as excinfo:
        verifier.verify(_permit_from_signature(b"\x00" * 64), _context())
    assert excinfo.value.code == "PERMIT_SIGNATURE_INVALID"

    assert verifier.verify(_signed_permit(), _context()).permit_id == "pmt-0001"


def test_context_mismatch_does_not_consume_replay_slot():
    store = InMemoryReplayStore()
    verifier = PermitVerifier({KEY_ID: PUBLIC_KEY}, replay_store=store)

    with pytest.raises(PermitVerificationError) as excinfo:
        verifier.verify(_signed_permit(), _context(device_id="device-b"))
    assert excinfo.value.code == "PERMIT_DEVICE_MISMATCH"

    assert verifier.verify(_signed_permit(), _context()).permit_id == "pmt-0001"


def test_inverted_time_window_rejected_as_malformed():
    permit = _signed_permit(
        issued_at=_iso(NOW + timedelta(hours=2)),
        expires_at=_iso(NOW + timedelta(hours=1)),
    )

    assert _verify_code(permit, _context()) == "PERMIT_MALFORMED"


def test_load_public_keys_rejects_non_object_root(tmp_path):
    registry = tmp_path / "keys.json"
    registry.write_text('["not", "an", "object"]', encoding="utf-8")

    with pytest.raises(PermitVerificationError) as excinfo:
        load_public_keys(registry)
    assert excinfo.value.code == "PERMIT_KEY_REGISTRY_INVALID"


def test_load_public_keys_rejects_non_ed25519_key(tmp_path):
    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    der = rsa_key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    registry = tmp_path / "keys.json"
    registry.write_text(
        json.dumps({"keys": {"rsa-1": base64.b64encode(der).decode("ascii")}}),
        encoding="utf-8",
    )

    with pytest.raises(PermitVerificationError) as excinfo:
        load_public_keys(registry)
    assert excinfo.value.code == "PERMIT_KEY_REGISTRY_INVALID"


def test_load_public_keys_rejects_corrupt_der(tmp_path):
    registry = tmp_path / "keys.json"
    registry.write_text(
        json.dumps({"keys": {"k1": _b64url(b"\x00\x01\x02\x03")}}),
        encoding="utf-8",
    )

    with pytest.raises(PermitVerificationError) as excinfo:
        load_public_keys(registry)
    assert excinfo.value.code == "PERMIT_KEY_REGISTRY_INVALID"


def test_load_public_keys_normalizes_unsupported_algorithm(monkeypatch, tmp_path):
    registry = tmp_path / "keys.json"
    registry.write_text(
        json.dumps({"keys": {"k1": _b64url(b"\x30\x00")}}),
        encoding="utf-8",
    )

    def raise_unsupported(data):
        raise UnsupportedAlgorithm("unsupported key type")

    monkeypatch.setattr(
        "shuabao.subscription_permit.load_der_public_key", raise_unsupported
    )

    with pytest.raises(PermitVerificationError) as excinfo:
        load_public_keys(registry)
    assert excinfo.value.code == "PERMIT_KEY_REGISTRY_INVALID"
