"""EntitlementService — the unique subscription entry point for the Windows client.

Mode contract
─────────────
  SHUABAO_ENTITLEMENT_MODE=disabled (default)
      Completely transparent; is_start_allowed() always True; no network calls.
      Original RunnerService behaviour 100% preserved.

  SHUABAO_ENTITLEMENT_MODE=test
      Connects to local/test Bridge (SHUABAO_BRIDGE_URL, default http://127.0.0.1:8000).
      Real subscription gate.  Requires test signing public key (SHUABAO_SIGNING_PUBLIC_KEY_PEM).

  SHUABAO_ENTITLEMENT_MODE=production
      Full production; SHUABAO_BRIDGE_URL + SHUABAO_SIGNING_PUBLIC_KEY_PEM MUST be set.
      Absent config raises RuntimeError; NEVER silent-fallbacks to disabled/test.

Design
──────
  • No private key, Admin token, or Billing secret ever appears here.
  • Games logic (Mediator/FSM/OCR/etc.) is NOT imported; zero circular deps.
  • Mid-run expiry: never terminates a running worker.  Gate only on start().
  • EntitlementService is a singleton injected into RunnerService on __init__.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

import requests

from .device import device_fingerprint
from .models import (
    EntitlementDeniedError,
    EntitlementMode,
    EntitlementSnapshot,
    EntitlementStatus,
)
from .storage import EntitlementStorage
from .verifier import OfflineVerifier

_LOG = logging.getLogger(__name__)

# Statuses that allow RunnerService.start()
_ALLOW_STATUSES = {
    EntitlementStatus.TRIAL,
    EntitlementStatus.ACTIVE,
    EntitlementStatus.GRACE,
}

# Default offline grace: 48 hours in seconds
_DEFAULT_OFFLINE_GRACE_S = 172_800.0


class EntitlementService:
    """Thin entitlement client.

    Prefer factory method EntitlementService.from_env() for production/test use.
    """

    def __init__(
        self,
        *,
        mode: EntitlementMode = EntitlementMode.DISABLED,
        bridge_url: str = "http://127.0.0.1:8000",
        signing_public_key_pem: bytes | None = None,
        storage: EntitlementStorage | None = None,
        offline_grace_seconds: float = _DEFAULT_OFFLINE_GRACE_S,
        http_timeout: float = 10.0,
        device_fingerprint_override: str | None = None,
    ) -> None:
        self._mode = mode
        self._bridge_url = bridge_url.rstrip("/")
        self._storage = storage or EntitlementStorage(mode=mode.value)
        self._http_timeout = http_timeout
        self._offline_grace = offline_grace_seconds

        self._verifier: OfflineVerifier | None = None
        if signing_public_key_pem and mode != EntitlementMode.DISABLED:
            self._verifier = OfflineVerifier(
                signing_public_key_pem, grace_seconds=offline_grace_seconds
            )

        # Load persisted license key + device fingerprint once
        self._license_key: str = self._storage.load_license_key() or ""
        if device_fingerprint_override is not None:
            self._fingerprint = device_fingerprint_override
        else:
            fp_dict = device_fingerprint()
            self._fingerprint = fp_dict["fingerprint"]
        # Cache for in-run snapshot (not persisted across restarts)
        self._last_snapshot: EntitlementSnapshot | None = None
    # ------------------------------------------------------------------ #
    # Factory                                                              #
    # ------------------------------------------------------------------ #

    @classmethod
    def from_env(cls, data_dir=None) -> "EntitlementService":
        """Create from environment variables, including mode-level config validation."""
        raw_mode = os.environ.get("SHUABAO_ENTITLEMENT_MODE", "disabled").lower()
        try:
            mode = EntitlementMode(raw_mode)
        except ValueError:
            raise RuntimeError(
                f"Unknown SHUABAO_ENTITLEMENT_MODE={raw_mode!r}. "
                f"Valid values: disabled, test, production"
            )

        if mode == EntitlementMode.DISABLED:
            return cls(mode=mode, storage=EntitlementStorage(mode=mode.value, data_dir=data_dir))

        bridge_url = os.environ.get("SHUABAO_BRIDGE_URL", "http://127.0.0.1:8000")
        pem_str = os.environ.get("SHUABAO_SIGNING_PUBLIC_KEY_PEM", "")

        if mode == EntitlementMode.PRODUCTION and (not bridge_url or not pem_str):
            raise RuntimeError(
                "SHUABAO_ENTITLEMENT_MODE=production requires both "
                "SHUABAO_BRIDGE_URL and SHUABAO_SIGNING_PUBLIC_KEY_PEM to be set. "
                "Will NOT silent-fallback to disabled/test."
            )

        pem_bytes = pem_str.encode("utf-8").replace(b"\\n", b"\n") if pem_str else None
        storage = EntitlementStorage(mode=mode.value, data_dir=data_dir)
        svc = cls(
            mode=mode,
            bridge_url=bridge_url,
            signing_public_key_pem=pem_bytes,
            storage=storage,
        )
        # If a license key was supplied directly as env (useful for test harness)
        env_key = os.environ.get("SHUABAO_LICENSE_KEY", "")
        if env_key:
            svc.set_license_key(env_key)
        return svc

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def set_license_key(self, key: str) -> None:
        self._license_key = key
        self._storage.save_license_key(key)

    def get_snapshot(self) -> EntitlementSnapshot:
        """Return current entitlement snapshot.

        In disabled mode: instant synthetic ACTIVE snapshot, no I/O.
        In test/production: tries online validate, falls back to offline cache.
        """
        if self._mode == EntitlementMode.DISABLED:
            return EntitlementSnapshot(
                status=EntitlementStatus.ACTIVE,
                source="disabled",
                last_checked_at=time.time(),
                message="Entitlement disabled (bypass)",
            )

        snap = self._online_snapshot()
        if snap is not None:
            self._last_snapshot = snap
            return snap

        # Online failed — try offline cache
        snap = self._offline_cache_snapshot()
        if snap is not None:
            self._last_snapshot = snap
            return snap

        # No valid cache + no server
        _LOG.warning("entitlement: no valid cache and server unreachable → UNKNOWN/deny")
        snap = EntitlementSnapshot(
            status=EntitlementStatus.UNKNOWN,
            device_id=self._fingerprint[:16],
            source="unavailable",
            last_checked_at=time.time(),
            message="无法连接授权服务，且无有效离线凭证",
        )
        self._last_snapshot = snap
        return snap

    def is_start_allowed(self, snapshot: EntitlementSnapshot | None = None) -> bool:
        """True iff a new Runner start should be permitted."""
        snap = snapshot if snapshot is not None else self.get_snapshot()
        return snap.status in _ALLOW_STATUSES

    def assert_start_allowed(self) -> EntitlementSnapshot:
        """Calls get_snapshot() and raises EntitlementDeniedError if not allowed.

        Called by RunnerService.start() as the single authority gate.
        Returns the snapshot so caller can log/display it.
        """
        snap = self.get_snapshot()
        if not self.is_start_allowed(snap):
            raise EntitlementDeniedError(
                f"RunnerService.start() 被授权门禁拒绝: "
                f"status={snap.status.value} message={snap.message}"
            )
        return snap

    # ------------------------------------------------------------------ #
    # Online validate                                                      #
    # ------------------------------------------------------------------ #

    def _online_snapshot(self) -> EntitlementSnapshot | None:
        if not self._license_key:
            _LOG.debug("entitlement: no license key configured; skipping online validate")
            return None
        try:
            payload: dict[str, Any] = {
                "license_key": self._license_key,
                "hardware": {
                    "fingerprint": self._fingerprint,
                    "platform": "windows",
                    "components": {},
                },
            }
            resp = requests.post(
                f"{self._bridge_url}/v1/entitlements/validate",
                json=payload,
                timeout=self._http_timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            status = self._map_status(data.get("status", "UNKNOWN"))
            license_data = data.get("license") or {}
            expires_at = _parse_iso_ts(license_data.get("expires_at"))
            snap = EntitlementSnapshot(
                status=status,
                expires_at=expires_at,
                device_id=self._fingerprint[:16],
                plan=license_data.get("plan", ""),
                source="online",
                last_checked_at=time.time(),
                message=data.get("message", ""),
            )
            _LOG.info("entitlement online: status=%s", status.value)
            # Refresh offline token opportunistically
            self._refresh_offline_token(snap)
            return snap
        except requests.exceptions.ConnectionError:
            _LOG.info("entitlement: Bridge unreachable (connection refused)")
        except requests.exceptions.Timeout:
            _LOG.info("entitlement: Bridge timeout")
        except Exception as exc:
            _LOG.warning("entitlement: online validate error: %s: %s", type(exc).__name__, exc)
        return None

    def _refresh_offline_token(self, snap: EntitlementSnapshot) -> None:
        """Request a fresh signed offline token when status is ACTIVE/TRIAL/GRACE."""
        if snap.status not in _ALLOW_STATUSES:
            return
        if not self._verifier:
            return
        try:
            payload: dict[str, Any] = {
                "license_key": self._license_key,
                "hardware": {
                    "fingerprint": self._fingerprint,
                    "platform": "windows",
                    "components": {},
                },
            }
            resp = requests.post(
                f"{self._bridge_url}/v1/offline/issue",
                json=payload,
                timeout=self._http_timeout,
            )
            if resp.status_code == 200:
                token = resp.json()
                self._storage.save_offline_token(token)
                _LOG.debug("entitlement: offline token refreshed")
        except Exception as exc:
            _LOG.debug("entitlement: offline token refresh skipped: %s", type(exc).__name__)

    # ------------------------------------------------------------------ #
    # Offline cache                                                        #
    # ------------------------------------------------------------------ #

    def _offline_cache_snapshot(self) -> EntitlementSnapshot | None:
        if self._verifier is None:
            _LOG.debug("entitlement: no verifier; offline cache unavailable")
            return None
        token = self._storage.load_offline_token()
        if not token:
            return None
        cert = token.get("certificate", "")
        sig = token.get("signature", "")
        if not cert or not sig:
            return None
        try:
            payload = self._verifier.verify(
                cert, sig, expected_fingerprint=self._fingerprint
            )
        except Exception as exc:
            _LOG.warning("entitlement: offline token invalid: %s", exc)
            return None

        expires_at = _parse_iso_ts(token.get("expires_at"))
        offline_until = time.time() + self._offline_grace if expires_at else None
        snap = EntitlementSnapshot(
            status=EntitlementStatus.GRACE,
            expires_at=expires_at,
            offline_until=offline_until,
            device_id=self._fingerprint[:16],
            plan=payload.get("plan", ""),
            source="cache",
            last_checked_at=time.time(),
            message="离线缓存凭证有效",
        )
        _LOG.info("entitlement offline cache: GRACE plan=%s", snap.plan)
        return snap

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _map_status(raw: str) -> EntitlementStatus:
        try:
            return EntitlementStatus(raw.upper())
        except ValueError:
            return EntitlementStatus.UNKNOWN


def _parse_iso_ts(raw: Any) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:
        return None
