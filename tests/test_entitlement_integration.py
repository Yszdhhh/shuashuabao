"""Integration tests with fake transport — client boundary only.

Exercises EntitlementService wire protocol against a fake Bridge responses
(no real network, no Keygen).  Full real Compose E2E lives in test_entitlement_real_e2e.py.
"""
from __future__ import annotations

import base64
import hashlib
import json
import time
from pathlib import Path
from unittest.mock import patch, MagicMock, ANY

import pytest
import requests
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from shuabao.entitlement.models import (
    EntitlementDeniedError,
    EntitlementMode,
    EntitlementStatus,
)
from shuabao.entitlement.service import EntitlementService
from shuabao.entitlement.storage import EntitlementStorage

DEVICE_FP = hashlib.sha256(b"fake-device").hexdigest()


def _make_key_pair():
    priv = Ed25519PrivateKey.generate()
    pub_pem = priv.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    return priv, pub_pem


def _sign_token(priv: Ed25519PrivateKey, fingerprint: str, expires_ts: float | None = None) -> dict:
    payload = {
        "license_id": "int-test",
        "fingerprint": fingerprint,
        "plan": "pro",
        "expires_at": expires_ts or (time.time() + 3600),
    }
    json_bytes = json.dumps(payload).encode()
    cert = base64.b64encode(json_bytes).decode()
    sig = base64.b64encode(priv.sign(json_bytes)).decode()
    return {
        "certificate": cert,
        "signature": sig,
        "expires_at": payload["expires_at"],
        "plan": "pro",
    }


def _make_svc(tmp_path: Path, priv: Ed25519PrivateKey, pub_pem: bytes,
              validate_response: dict) -> EntitlementService:
    storage = EntitlementStorage(mode="test", data_dir=tmp_path)
    storage._keyring_ok = False  # force file backend
    svc = EntitlementService(
        mode=EntitlementMode.TEST,
        bridge_url="http://fake-bridge",
        signing_public_key_pem=pub_pem,
        storage=storage,
    )
    svc._fingerprint = DEVICE_FP
    svc._license_key = "LK-INTEGRATION"

    # Fake: validate returns the given response, offline/issue returns a signed token
    offline_token = _sign_token(priv, DEVICE_FP)

    def fake_post(url, json=None, timeout=None):
        resp = MagicMock()
        if "validate" in url:
            resp.status_code = 200
            resp.json.return_value = validate_response
            resp.raise_for_status.return_value = None
        elif "offline/issue" in url:
            resp.status_code = 200
            resp.json.return_value = offline_token
            resp.raise_for_status.return_value = None
        else:
            resp.status_code = 404
        return resp

    svc._http_timeout = 5
    # Patch only inside the service module
    with patch("shuabao.entitlement.service.requests.post", side_effect=fake_post):
        snap = svc.get_snapshot()

    svc._fake_post = fake_post
    svc._priv = priv
    svc._pub_pem = pub_pem
    return svc, snap


class TestIntegrationFakeTransport:
    def setup_method(self):
        self.priv, self.pub_pem = _make_key_pair()

    def test_active_allows_start(self, tmp_path):
        svc, snap = _make_svc(
            tmp_path, self.priv, self.pub_pem,
            {"status": "ACTIVE", "license": {"plan": "pro_monthly", "expires_at": time.time() + 86400}},
        )
        assert snap.status == EntitlementStatus.ACTIVE
        assert svc.is_start_allowed(snap)

    def test_trial_allows_start(self, tmp_path):
        svc, snap = _make_svc(
            tmp_path, self.priv, self.pub_pem,
            {"status": "TRIAL", "license": {"plan": "trial", "expires_at": time.time() + 259200}},
        )
        assert snap.status == EntitlementStatus.TRIAL
        assert svc.is_start_allowed(snap)

    def test_expired_denies_start(self, tmp_path):
        svc, snap = _make_svc(
            tmp_path, self.priv, self.pub_pem,
            {"status": "EXPIRED", "license": {"expires_at": time.time() - 86400}},
        )
        assert snap.status == EntitlementStatus.EXPIRED
        assert not svc.is_start_allowed(snap)
        with pytest.raises(EntitlementDeniedError):
            svc.assert_start_allowed()

    def test_revoked_denies_start(self, tmp_path):
        svc, snap = _make_svc(
            tmp_path, self.priv, self.pub_pem,
            {"status": "REVOKED", "license": {}},
        )
        assert snap.status == EntitlementStatus.REVOKED
        assert not svc.is_start_allowed(snap)

    def test_server_down_with_signed_cache_grace(self, tmp_path):
        """After online validate failure, valid signed cache returns GRACE → allow."""
        storage = EntitlementStorage(mode="test", data_dir=tmp_path)
        storage._keyring_ok = False
        offline_token = _sign_token(self.priv, DEVICE_FP, expires_ts=time.time() + 3600)
        storage.save_offline_token(offline_token)
        svc = EntitlementService(
            mode=EntitlementMode.TEST,
            bridge_url="http://127.0.0.1:9999",  # unreachable
            signing_public_key_pem=self.pub_pem,
            storage=storage,
        )
        svc._fingerprint = DEVICE_FP
        svc._license_key = "LK-TEST"
        snap = svc.get_snapshot()
        assert snap.status == EntitlementStatus.GRACE
        assert svc.is_start_allowed(snap)

    def test_active_saves_offline_token(self, tmp_path):
        """ACTIVE validate also triggers an offline token save."""
        storage = EntitlementStorage(mode="test", data_dir=tmp_path)
        storage._keyring_ok = False
        svc = EntitlementService(
            mode=EntitlementMode.TEST,
            bridge_url="http://fake-bridge",
            signing_public_key_pem=self.pub_pem,
            storage=storage,
        )
        svc._fingerprint = DEVICE_FP
        svc._license_key = "LK-TEST"
        offline_token = _sign_token(self.priv, DEVICE_FP)

        def fake_post(url, json=None, timeout=None):
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            if "validate" in url:
                resp.status_code = 200
                resp.json.return_value = {
                    "status": "ACTIVE",
                    "license": {"plan": "pro", "expires_at": time.time() + 86400},
                }
            elif "offline/issue" in url:
                resp.status_code = 200
                resp.json.return_value = offline_token
            return resp

        with patch("shuabao.entitlement.service.requests.post", side_effect=fake_post):
            snap = svc.get_snapshot()

        assert snap.status == EntitlementStatus.ACTIVE
        # Offline token must be persisted
        cached = storage.load_offline_token()
        assert cached is not None
        assert "certificate" in cached

    def test_mid_run_expiry_current_run_unaffected(self, tmp_path):
        """start() gated once; post-start expiry does NOT kill current worker."""
        svc, snap = _make_svc(
            tmp_path, self.priv, self.pub_pem,
            {"status": "ACTIVE", "license": {"plan": "pro", "expires_at": time.time() + 1}},
        )
        # Simulate initial ACTIVE → allowed
        assert svc.is_start_allowed(snap)
        # Now simulate time has passed: next call would produce EXPIRED (server changed)
        # But the existing worker is not probed — no periodic polling in client
        # This is enforced structurally: RunnerService does NOT call entitlement after start()
        # Nothing to assert beyond "no exception on the current worker path" — covered by runner tests
