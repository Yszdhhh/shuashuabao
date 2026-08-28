"""
Real Compose E2E: Windows entitlement client ↔ local Bridge ↔ Real Keygen.

Requires SHUABAO_ENTITLEMENT_E2E=1 AND the Compose stack running on port 8000.
Skipped entirely otherwise -- safe to run in CI regression without Compose.

Public key: extracted from the Subscription Lab signing_key.pem (public portion only).
NEVER contains private key, Keygen admin token, or billing secret.
"""
import hashlib
import json
import os
import subprocess
import time
import uuid
from pathlib import Path
import pytest
import requests

from shuabao.entitlement.models import (
    EntitlementDeniedError,
    EntitlementMode,
    EntitlementSnapshot,
    EntitlementStatus,
)
from shuabao.entitlement.service import EntitlementService
from shuabao.entitlement.storage import EntitlementStorage
from shuabao.entitlement.verifier import OfflineVerifier

pytestmark = pytest.mark.skipif(
    os.environ.get("SHUABAO_ENTITLEMENT_E2E") != "1",
    reason="SHUABAO_ENTITLEMENT_E2E=1 required; Compose stack must be running",
)

BRIDGE_URL = os.environ.get("SHUABAO_BRIDGE_URL", "http://127.0.0.1:8000")

# Public key only -- extracted from signing_key.pem. No private key here.
TEST_PUBLIC_KEY_PEM = b"""\
-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEA+UyZW2IILqG4A22Nina1v8jeb4LKEkU9tiRZhZwjVms=
-----END PUBLIC KEY-----
"""


def _keygen_create_license(name: str = "e2e-license") -> str:
    """Create a license directly in Keygen container via Rails runner."""
    res = subprocess.run(
        [
            "docker", "exec", "shuashuabao-keygen", "bundle", "exec", "rails", "runner",
            f'a = Account.first; policy = a.policies.find_by!(name: "Pro Monthly Policy"); '
            f'lic = a.licenses.create!(policy: policy, name: "{name}"); puts lic.key',
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res.returncode == 0, f"Keygen license creation failed: {res.stderr}"
    lines = [l.strip() for l in res.stdout.strip().split("\n") if l.strip()]
    return lines[-1]


def _keygen_expire_license(license_key: str) -> None:
    """Set license expiry to 1 day in the past."""
    res = subprocess.run(
        [
            "docker", "exec", "shuashuabao-keygen", "bundle", "exec", "rails", "runner",
            f'a = Account.first; lic = a.licenses.find_by!(key: "{license_key}"); lic.update!(expiry: 1.day.ago)',
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res.returncode == 0, f"Keygen expire failed: {res.stderr}"


def _keygen_revoke_license(license_key: str) -> None:
    """Destroy/revoke license in Keygen."""
    res = subprocess.run(
        [
            "docker", "exec", "shuashuabao-keygen", "bundle", "exec", "rails", "runner",
            f'a = Account.first; lic = a.licenses.find_by(key: "{license_key}"); lic&.destroy!',
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res.returncode == 0, f"Keygen revoke failed: {res.stderr}"


@pytest.fixture(scope="module")
def bridge_online():
    """Fail fast if Bridge is unreachable."""
    try:
        r = requests.get(f"{BRIDGE_URL}/health", timeout=5)
        assert r.status_code == 200
    except Exception as e:
        pytest.skip(f"Bridge not reachable at {BRIDGE_URL}: {e}")


@pytest.fixture
def test_device_fp():
    """Deterministic unique device fingerprint for test isolation."""
    unique_id = uuid.uuid4().hex
    fp = hashlib.sha256(unique_id.encode()).hexdigest()
    return fp


# ─── 1. ACTIVE ───────────────────────────────────────────────────────────────

def test_e2e_active_allows_start(bridge_online, test_device_fp, tmp_path):
    """Active license on activated machine -> ACTIVE -> is_start_allowed True."""
    license_key = _keygen_create_license(name="active-test")
    hw = {"fingerprint": test_device_fp, "platform": "windows", "components": {}}

    # Activate device via Bridge
    r_act = requests.post(
        f"{BRIDGE_URL}/v1/devices/activate",
        json={"license_key": license_key, "hardware": hw},
        timeout=10,
    )
    assert r_act.status_code == 200, r_act.text

    # Client EntitlementService in test mode
    storage = EntitlementStorage(mode="test", data_dir=tmp_path)
    svc = EntitlementService(
        mode=EntitlementMode.TEST,
        bridge_url=BRIDGE_URL,
        signing_public_key_pem=TEST_PUBLIC_KEY_PEM,
        storage=storage,
        device_fingerprint_override=test_device_fp,
    )
    svc.set_license_key(license_key)

    snap = svc.get_snapshot()
    assert snap.status == EntitlementStatus.ACTIVE
    assert snap.source == "online"
    assert svc.is_start_allowed(snap) is True

    # Gate check does not raise
    gated_snap = svc.assert_start_allowed()
    assert gated_snap.status == EntitlementStatus.ACTIVE


# ─── 2. TRIAL ────────────────────────────────────────────────────────────────

def test_e2e_trial_allows_start(bridge_online, test_device_fp, tmp_path):
    """Claim fresh trial -> ACTIVE/TRIAL -> is_start_allowed True."""
    account_id = f"trial-acc-{uuid.uuid4().hex[:8]}"
    email = f"trial-{uuid.uuid4().hex[:8]}@example.com"
    hw = {"fingerprint": test_device_fp, "platform": "windows", "components": {}}

    # Claim trial on Bridge
    r_trial = requests.post(
        f"{BRIDGE_URL}/v1/trials/claim",
        json={"account_id": account_id, "email": email, "hardware": hw},
        timeout=10,
    )
    assert r_trial.status_code == 200, r_trial.text
    trial_data = r_trial.json()
    license_key = trial_data["license_key"]

    storage = EntitlementStorage(mode="test", data_dir=tmp_path)
    svc = EntitlementService(
        mode=EntitlementMode.TEST,
        bridge_url=BRIDGE_URL,
        signing_public_key_pem=TEST_PUBLIC_KEY_PEM,
        storage=storage,
        device_fingerprint_override=test_device_fp,
    )
    svc.set_license_key(license_key)

    snap = svc.get_snapshot()
    assert snap.status in (EntitlementStatus.TRIAL, EntitlementStatus.ACTIVE)
    assert svc.is_start_allowed(snap) is True
    assert svc.assert_start_allowed().status in (EntitlementStatus.TRIAL, EntitlementStatus.ACTIVE)


# ─── 3. EXPIRED ──────────────────────────────────────────────────────────────

def test_e2e_expired_denies_start(bridge_online, test_device_fp, tmp_path):
    """Expired license -> EXPIRED -> is_start_allowed False -> gate raises."""
    license_key = _keygen_create_license(name="expired-test")
    hw = {"fingerprint": test_device_fp, "platform": "windows", "components": {}}

    # Activate
    requests.post(
        f"{BRIDGE_URL}/v1/devices/activate",
        json={"license_key": license_key, "hardware": hw},
        timeout=10,
    )

    # Set expiry in Keygen to past
    _keygen_expire_license(license_key)

    storage = EntitlementStorage(mode="test", data_dir=tmp_path)
    svc = EntitlementService(
        mode=EntitlementMode.TEST,
        bridge_url=BRIDGE_URL,
        signing_public_key_pem=TEST_PUBLIC_KEY_PEM,
        storage=storage,
        device_fingerprint_override=test_device_fp,
    )
    svc.set_license_key(license_key)

    snap = svc.get_snapshot()
    assert snap.status == EntitlementStatus.EXPIRED
    assert svc.is_start_allowed(snap) is False

    with pytest.raises(EntitlementDeniedError) as exc_info:
        svc.assert_start_allowed()
    assert "EXPIRED" in str(exc_info.value) or "expired" in str(exc_info.value).lower()


# ─── 4. REVOKED ──────────────────────────────────────────────────────────────

def test_e2e_revoked_denies_start(bridge_online, test_device_fp, tmp_path):
    """Revoked/destroyed license -> REVOKED/EXPIRED -> is_start_allowed False -> gate raises."""
    license_key = _keygen_create_license(name="revoked-test")
    hw = {"fingerprint": test_device_fp, "platform": "windows", "components": {}}

    # Activate
    requests.post(
        f"{BRIDGE_URL}/v1/devices/activate",
        json={"license_key": license_key, "hardware": hw},
        timeout=10,
    )

    # Destroy in Keygen
    _keygen_revoke_license(license_key)

    storage = EntitlementStorage(mode="test", data_dir=tmp_path)
    svc = EntitlementService(
        mode=EntitlementMode.TEST,
        bridge_url=BRIDGE_URL,
        signing_public_key_pem=TEST_PUBLIC_KEY_PEM,
        storage=storage,
        device_fingerprint_override=test_device_fp,
    )
    svc.set_license_key(license_key)

    snap = svc.get_snapshot()
    assert snap.status in (EntitlementStatus.REVOKED, EntitlementStatus.EXPIRED, EntitlementStatus.UNKNOWN)
    assert svc.is_start_allowed(snap) is False

    with pytest.raises(EntitlementDeniedError):
        svc.assert_start_allowed()


# ─── 5. OFFLINE GRACE ────────────────────────────────────────────────────────

def test_e2e_offline_grace_allows_start(bridge_online, test_device_fp, tmp_path):
    """
    Online check primes signed offline cache; when Bridge is unreachable,
    offline verification validates cache within grace window -> GRACE -> is_start_allowed True.
    """
    license_key = _keygen_create_license(name="grace-test")
    hw = {"fingerprint": test_device_fp, "platform": "windows", "components": {}}

    # Activate
    requests.post(
        f"{BRIDGE_URL}/v1/devices/activate",
        json={"license_key": license_key, "hardware": hw},
        timeout=10,
    )

    storage = EntitlementStorage(mode="test", data_dir=tmp_path)
    # Online service to prime offline cache
    svc_online = EntitlementService(
        mode=EntitlementMode.TEST,
        bridge_url=BRIDGE_URL,
        signing_public_key_pem=TEST_PUBLIC_KEY_PEM,
        storage=storage,
        device_fingerprint_override=test_device_fp,
    )
    svc_online.set_license_key(license_key)
    snap_online = svc_online.get_snapshot()
    assert snap_online.status == EntitlementStatus.ACTIVE

    # Verify offline token was persisted in storage
    token = storage.load_offline_token()
    assert token is not None
    assert "certificate" in token
    assert "signature" in token

    # Simulate network failure: point to dead port
    svc_offline = EntitlementService(
        mode=EntitlementMode.TEST,
        bridge_url="http://127.0.0.1:19999",
        signing_public_key_pem=TEST_PUBLIC_KEY_PEM,
        storage=storage,
        device_fingerprint_override=test_device_fp,
    )
    svc_offline.set_license_key(license_key)

    snap_offline = svc_offline.get_snapshot()
    assert snap_offline.status == EntitlementStatus.GRACE
    assert snap_offline.source == "cache"
    assert svc_offline.is_start_allowed(snap_offline) is True
    assert svc_offline.assert_start_allowed().status == EntitlementStatus.GRACE


# ─── 6. WRONG DEVICE ─────────────────────────────────────────────────────────

def test_e2e_wrong_device_denies_offline(bridge_online, test_device_fp, tmp_path):
    """Signed offline token for Device A used on Device B -> UNKNOWN -> DENY."""
    license_key = _keygen_create_license(name="wrong-device-test")
    hw = {"fingerprint": test_device_fp, "platform": "windows", "components": {}}

    requests.post(
        f"{BRIDGE_URL}/v1/devices/activate",
        json={"license_key": license_key, "hardware": hw},
        timeout=10,
    )

    storage = EntitlementStorage(mode="test", data_dir=tmp_path)
    svc_online = EntitlementService(
        mode=EntitlementMode.TEST,
        bridge_url=BRIDGE_URL,
        signing_public_key_pem=TEST_PUBLIC_KEY_PEM,
        storage=storage,
        device_fingerprint_override=test_device_fp,
    )
    svc_online.set_license_key(license_key)
    svc_online.get_snapshot()

    # Now attempt to use same storage/token on a DIFFERENT machine fingerprint
    other_device_fp = hashlib.sha256(b"completely-different-machine").hexdigest()
    svc_wrong = EntitlementService(
        mode=EntitlementMode.TEST,
        bridge_url="http://127.0.0.1:19999",  # offline
        signing_public_key_pem=TEST_PUBLIC_KEY_PEM,
        storage=storage,
        device_fingerprint_override=other_device_fp,
    )
    svc_wrong.set_license_key(license_key)

    snap = svc_wrong.get_snapshot()
    assert snap.status == EntitlementStatus.UNKNOWN
    assert svc_wrong.is_start_allowed(snap) is False
    with pytest.raises(EntitlementDeniedError):
        svc_wrong.assert_start_allowed()


# ─── 7. CORRUPTED TOKEN ──────────────────────────────────────────────────────

def test_e2e_corrupted_token_denies(bridge_online, test_device_fp, tmp_path):
    """Corrupted/tampered token in storage -> fail closed -> UNKNOWN -> DENY."""
    storage = EntitlementStorage(mode="test", data_dir=tmp_path)
    storage.save_offline_token({
        "certificate": "eyJuYW1lIjoidGFtcGVyZWQifQ==",
        "signature": "AAAAINVALID_SIGNATURE_BYTES_HERE",
        "algorithm": "ED25519",
        "expires_at": "2099-01-01T00:00:00Z",
    })

    svc = EntitlementService(
        mode=EntitlementMode.TEST,
        bridge_url="http://127.0.0.1:19999",  # offline
        signing_public_key_pem=TEST_PUBLIC_KEY_PEM,
        storage=storage,
        device_fingerprint_override=test_device_fp,
    )
    svc.set_license_key("CORRUPTED-TEST-KEY")

    snap = svc.get_snapshot()
    assert snap.status == EntitlementStatus.UNKNOWN
    assert svc.is_start_allowed(snap) is False
    with pytest.raises(EntitlementDeniedError):
        svc.assert_start_allowed()


# ─── 8. SERVER DOWN + NO CACHE ───────────────────────────────────────────────

def test_e2e_server_down_no_cache_denies(tmp_path, test_device_fp):
    """Bridge unreachable and no offline cache -> fail closed -> UNKNOWN -> DENY."""
    storage = EntitlementStorage(mode="test", data_dir=tmp_path)
    svc = EntitlementService(
        mode=EntitlementMode.TEST,
        bridge_url="http://127.0.0.1:19999",  # dead port
        signing_public_key_pem=TEST_PUBLIC_KEY_PEM,
        storage=storage,
        device_fingerprint_override=test_device_fp,
    )
    svc.set_license_key("ANY-KEY-NO-SERVER")

    snap = svc.get_snapshot()
    assert snap.status == EntitlementStatus.UNKNOWN
    assert snap.source == "unavailable"
    assert svc.is_start_allowed(snap) is False
    with pytest.raises(EntitlementDeniedError):
        svc.assert_start_allowed()


# ─── 9. MID-RUN EXPIRY ───────────────────────────────────────────────────────

def test_e2e_mid_run_expiry_does_not_kill_current_run(bridge_online, test_device_fp, tmp_path):
    """
    Contract test: entitlement check runs ONLY at Runner start.
    Once started, a running worker is never polled or terminated mid-run.
    Next start explicitly re-validates and denies.
    """
    license_key = _keygen_create_license(name="mid-run-test")
    hw = {"fingerprint": test_device_fp, "platform": "windows", "components": {}}

    requests.post(
        f"{BRIDGE_URL}/v1/devices/activate",
        json={"license_key": license_key, "hardware": hw},
        timeout=10,
    )

    storage = EntitlementStorage(mode="test", data_dir=tmp_path)
    svc = EntitlementService(
        mode=EntitlementMode.TEST,
        bridge_url=BRIDGE_URL,
        signing_public_key_pem=TEST_PUBLIC_KEY_PEM,
        storage=storage,
        device_fingerprint_override=test_device_fp,
    )
    svc.set_license_key(license_key)

    # 1. Runner starts: gate allows
    start_snap = svc.assert_start_allowed()
    assert start_snap.status == EntitlementStatus.ACTIVE

    # 2. Mid-run: license expires on server
    _keygen_expire_license(license_key)

    # 3. Running session is undisturbed: no background kill signal exists in EntitlementService
    assert svc._last_snapshot is not None
    assert svc._last_snapshot.status == EntitlementStatus.ACTIVE

    # 4. Next start: fresh validation detects expiration and DENIES
    fresh_snap = svc.get_snapshot()
    assert fresh_snap.status == EntitlementStatus.EXPIRED
    assert svc.is_start_allowed(fresh_snap) is False
    with pytest.raises(EntitlementDeniedError):
        svc.assert_start_allowed()


# ─── 10. DISABLED MODE ──────────────────────────────────────────────────────

def test_e2e_disabled_mode_allows_start_unconditionally(tmp_path):
    """
    SHUABAO_ENTITLEMENT_MODE=disabled must return ACTIVE immediately with no network calls.
    """
    storage = EntitlementStorage(mode="disabled", data_dir=tmp_path)
    svc = EntitlementService(
        mode=EntitlementMode.DISABLED,
        bridge_url="http://127.0.0.1:19999",  # dead port -- proves no network I/O
        storage=storage,
    )
    snap = svc.get_snapshot()
    assert snap.status == EntitlementStatus.ACTIVE
    assert snap.source == "disabled"
    assert svc.is_start_allowed(snap) is True
    assert svc.assert_start_allowed().status == EntitlementStatus.ACTIVE
