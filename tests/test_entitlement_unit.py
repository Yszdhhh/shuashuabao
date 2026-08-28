"""Unit tests for the Windows entitlement client.

No network, no real Keygen, no Bridge.
Tests the status → allow/deny matrix, offline verifier, storage, and device fingerprint.
"""
from __future__ import annotations

import base64
import hashlib
import json
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, PublicFormat, PrivateFormat, NoEncryption
)

from shuabao.entitlement.models import (
    EntitlementDeniedError,
    EntitlementMode,
    EntitlementSnapshot,
    EntitlementStatus,
    EntitlementVerificationError,
)
from shuabao.entitlement.service import EntitlementService
from shuabao.entitlement.storage import EntitlementStorage
from shuabao.entitlement.verifier import OfflineVerifier


# ── Helpers ──────────────────────────────────────────────────────────────── #

def _make_key_pair():
    priv = Ed25519PrivateKey.generate()
    pub_pem = priv.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    return priv, pub_pem


def _make_token(priv_key: Ed25519PrivateKey, fingerprint: str, expires_at: float | None = None) -> dict:
    payload = {
        "license_id": "test-lic",
        "fingerprint": fingerprint,
        "plan": "pro_monthly",
        "expires_at": expires_at or (time.time() + 3600),
        "features": [],
    }
    json_bytes = json.dumps(payload).encode()
    cert = base64.b64encode(json_bytes).decode()
    sig = base64.b64encode(priv_key.sign(json_bytes)).decode()
    return {"certificate": cert, "signature": sig, "expires_at": payload["expires_at"]}


DEVICE_FP = hashlib.sha256(b"test-device").hexdigest()


# ── Status → allow/deny matrix ───────────────────────────────────────────── #

@pytest.mark.parametrize("status,expected", [
    (EntitlementStatus.TRIAL,     True),
    (EntitlementStatus.ACTIVE,    True),
    (EntitlementStatus.GRACE,     True),
    (EntitlementStatus.PAST_DUE,  False),
    (EntitlementStatus.EXPIRED,   False),
    (EntitlementStatus.SUSPENDED, False),
    (EntitlementStatus.REVOKED,   False),
    (EntitlementStatus.UNKNOWN,   False),
])
def test_allow_deny_matrix(status, expected):
    svc = EntitlementService(mode=EntitlementMode.DISABLED)
    snap = EntitlementSnapshot(status=status, source="test")
    assert svc.is_start_allowed(snap) is expected


# ── Disabled mode ─────────────────────────────────────────────────────────── #

def test_disabled_always_allows():
    svc = EntitlementService(mode=EntitlementMode.DISABLED)
    snap = svc.get_snapshot()
    assert snap.status == EntitlementStatus.ACTIVE
    assert snap.source == "disabled"
    # assert_start_allowed must not raise
    svc.assert_start_allowed()


# ── OfflineVerifier ───────────────────────────────────────────────────────── #

class TestOfflineVerifier:
    def setup_method(self):
        self.priv, self.pub_pem = _make_key_pair()
        self.verifier = OfflineVerifier(self.pub_pem, grace_seconds=0)

    def test_valid_token_passes(self):
        token = _make_token(self.priv, DEVICE_FP)
        payload = self.verifier.verify(
            token["certificate"], token["signature"],
            expected_fingerprint=DEVICE_FP,
        )
        assert payload["fingerprint"] == DEVICE_FP

    def test_wrong_device_denied(self):
        token = _make_token(self.priv, DEVICE_FP)
        with pytest.raises(EntitlementVerificationError, match="设备绑定"):
            self.verifier.verify(
                token["certificate"], token["signature"],
                expected_fingerprint="wrong-fingerprint",
            )

    def test_corrupted_cert_denied(self):
        token = _make_token(self.priv, DEVICE_FP)
        bad_cert = base64.b64encode(b"corrupted").decode()
        with pytest.raises(EntitlementVerificationError):
            self.verifier.verify(
                bad_cert, token["signature"],
                expected_fingerprint=DEVICE_FP,
            )

    def test_tampered_signature_denied(self):
        token = _make_token(self.priv, DEVICE_FP)
        bad_sig = base64.b64encode(b"\x00" * 64).decode()
        with pytest.raises(EntitlementVerificationError, match="签名无效"):
            self.verifier.verify(
                token["certificate"], bad_sig,
                expected_fingerprint=DEVICE_FP,
            )

    def test_expired_token_denied(self):
        token = _make_token(self.priv, DEVICE_FP, expires_at=time.time() - 7200)
        verifier_no_grace = OfflineVerifier(self.pub_pem, grace_seconds=0)
        with pytest.raises(EntitlementVerificationError, match="过期"):
            verifier_no_grace.verify(
                token["certificate"], token["signature"],
                expected_fingerprint=DEVICE_FP,
            )

    def test_expired_within_grace_allowed(self):
        """Token expired 1 hour ago but grace is 48 h → allow."""
        token = _make_token(self.priv, DEVICE_FP, expires_at=time.time() - 3600)
        verifier_grace = OfflineVerifier(self.pub_pem, grace_seconds=172_800)
        payload = verifier_grace.verify(
            token["certificate"], token["signature"],
            expected_fingerprint=DEVICE_FP,
        )
        assert payload["fingerprint"] == DEVICE_FP


# ── EntitlementService offline path ──────────────────────────────────────── #

class TestEntitlementServiceOffline:
    def setup_method(self, tmp_path=None):
        self.priv, self.pub_pem = _make_key_pair()

    def _make_svc(self, tmp_path: Path, license_key: str = "LK-TEST"):
        storage = EntitlementStorage(mode="test", data_dir=tmp_path)
        svc = EntitlementService(
            mode=EntitlementMode.TEST,
            bridge_url="http://127.0.0.1:9999",  # unreachable
            signing_public_key_pem=self.pub_pem,
            storage=storage,
        )
        svc._fingerprint = DEVICE_FP
        svc._license_key = license_key
        return svc

    def test_server_down_with_valid_cache_grace(self, tmp_path):
        svc = self._make_svc(tmp_path)
        token = _make_token(self.priv, DEVICE_FP, expires_at=time.time() + 3600)
        svc._storage.save_offline_token(token)
        snap = svc.get_snapshot()
        assert snap.status == EntitlementStatus.GRACE
        assert snap.source == "cache"

    def test_server_down_no_cache_unknown(self, tmp_path):
        svc = self._make_svc(tmp_path)
        snap = svc.get_snapshot()
        assert snap.status == EntitlementStatus.UNKNOWN

    def test_server_down_no_cache_denies(self, tmp_path):
        svc = self._make_svc(tmp_path)
        with pytest.raises(EntitlementDeniedError):
            svc.assert_start_allowed()

    def test_corrupted_cache_denies(self, tmp_path):
        svc = self._make_svc(tmp_path)
        # Store invalid JSON as token
        svc._storage.save_offline_token({"certificate": "bad", "signature": "bad"})
        snap = svc.get_snapshot()
        assert snap.status == EntitlementStatus.UNKNOWN

    def test_no_license_key_no_cache_unknown(self, tmp_path):
        svc = self._make_svc(tmp_path, license_key="")
        snap = svc.get_snapshot()
        assert snap.status == EntitlementStatus.UNKNOWN


# ── Storage ──────────────────────────────────────────────────────────────── #

def test_storage_disabled_no_write(tmp_path):
    st = EntitlementStorage(mode="disabled", data_dir=tmp_path)
    st.save_offline_token({"x": 1})
    assert st.load_offline_token() is None


def test_storage_test_file_backend(tmp_path):
    st = EntitlementStorage(mode="test", data_dir=tmp_path)
    # Force file backend (no real keyring in CI)
    st._keyring_ok = False
    token = {"certificate": "abc", "signature": "xyz"}
    st.save_offline_token(token)
    loaded = st.load_offline_token()
    assert loaded == token


def test_storage_corrupted_token_returns_none(tmp_path):
    st = EntitlementStorage(mode="test", data_dir=tmp_path)
    st._keyring_ok = False
    # Write unparseable JSON
    (tmp_path / "offline_entitlement_v1.TEST_ONLY.json").write_text("not-json")
    assert st.load_offline_token() is None


def test_storage_production_refuses_plaintext(tmp_path):
    st = EntitlementStorage(mode="production", data_dir=tmp_path)
    st._keyring_ok = False  # simulate no keyring
    with pytest.raises(RuntimeError, match="production"):
        st.save_offline_token({"x": 1})


# ── Device fingerprint ───────────────────────────────────────────────────── #

def test_device_fingerprint_stable():
    from shuabao.entitlement.device import device_fingerprint
    fp1 = device_fingerprint()
    fp2 = device_fingerprint()
    assert fp1["fingerprint"] == fp2["fingerprint"]
    assert len(fp1["fingerprint"]) == 64  # SHA-256 hex


def test_device_fingerprint_no_raw_in_log(caplog):
    import logging
    from shuabao.entitlement.device import device_fingerprint
    with caplog.at_level(logging.DEBUG, logger="shuabao.entitlement.device"):
        device_fingerprint()
    for record in caplog.records:
        # Raw CPU/GUID/disk values must not appear in log messages
        # (only truncated fingerprint prefix is allowed)
        assert "ProcessorNameString" not in record.message
        assert "MachineGuid" not in record.message


# ── Production mode strict config ────────────────────────────────────────── #

def test_production_requires_config():
    import os
    env = {"SHUABAO_ENTITLEMENT_MODE": "production"}
    removed = {"SHUABAO_BRIDGE_URL", "SHUABAO_SIGNING_PUBLIC_KEY_PEM"}
    with patch.dict(os.environ, env):
        for key in removed:
            os.environ.pop(key, None)
        with pytest.raises(RuntimeError, match="production"):
            EntitlementService.from_env()


def test_disabled_mode_from_env():
    import os
    with patch.dict(os.environ, {"SHUABAO_ENTITLEMENT_MODE": "disabled"}):
        svc = EntitlementService.from_env()
    assert svc._mode == EntitlementMode.DISABLED


# ── Snapshot.to_dict ─────────────────────────────────────────────────────── #

def test_snapshot_to_dict():
    now = time.time()
    snap = EntitlementSnapshot(status=EntitlementStatus.ACTIVE, source="online", last_checked_at=now)
    d = snap.to_dict()
    assert d["status"] == "ACTIVE"
    assert d["source"] == "online"
    assert d["last_checked_at"] == now
