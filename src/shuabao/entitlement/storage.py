"""Entitlement credential storage.

Production (mode=production): Windows DPAPI + Credential Manager (keyring).
Test (mode=test):              keyring fallback; file backend with TEST_ONLY marker.
Disabled (mode=disabled):      no-op; nothing written.

Security rules:
  - Production mode NEVER falls back to plaintext JSON storage.
  - Storage failure in production raises clearly; no silent fallback.
  - Raw tokens/secrets are not logged.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

_LOG = logging.getLogger(__name__)

_CREDENTIAL_SERVICE = "shuabao-entitlement"
_OFFLINE_TOKEN_KEY = "offline_entitlement_v1"
_LICENSE_KEY_KEY = "license_key_v1"
_DEVICE_KEY = "device_id_v1"


class EntitlementStorage:
    """Read/write entitlement credentials.

    Args:
        mode: "disabled" | "test" | "production"
        data_dir: Fallback directory for TEST ONLY file backend.
    """

    def __init__(self, mode: str, data_dir: Path | None = None) -> None:
        self._mode = mode
        self._data_dir = data_dir
        self._keyring_ok: bool | None = None  # lazy check

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def load_offline_token(self) -> dict[str, Any] | None:
        """Return cached signed offline entitlement dict, or None."""
        raw = self._read(_OFFLINE_TOKEN_KEY)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except Exception:
            _LOG.warning("entitlement storage: corrupted offline token; discarding")
            return None

    def save_offline_token(self, token: dict[str, Any]) -> None:
        self._write(_OFFLINE_TOKEN_KEY, json.dumps(token))

    def load_license_key(self) -> str | None:
        return self._read(_LICENSE_KEY_KEY)

    def save_license_key(self, key: str) -> None:
        self._write(_LICENSE_KEY_KEY, key)

    def load_device_id(self) -> str | None:
        return self._read(_DEVICE_KEY)

    def save_device_id(self, device_id: str) -> None:
        self._write(_DEVICE_KEY, device_id)

    # ------------------------------------------------------------------ #
    # Backend dispatch                                                     #
    # ------------------------------------------------------------------ #

    def _read(self, key: str) -> str | None:
        if self._mode == "disabled":
            return None
        if self._use_keyring():
            return self._keyring_read(key)
        return self._file_read(key)

    def _write(self, key: str, value: str) -> None:
        if self._mode == "disabled":
            return
        if self._use_keyring():
            self._keyring_write(key, value)
            return
        if self._mode == "production":
            raise RuntimeError(
                f"EntitlementStorage: keyring unavailable in production mode; "
                f"refusing plaintext fallback for key={key!r}"
            )
        # TEST ONLY file backend
        self._file_write(key, value)

    def _use_keyring(self) -> bool:
        if self._keyring_ok is None:
            try:
                import keyring  # type: ignore[import-untyped]
                keyring.get_password(_CREDENTIAL_SERVICE, "__probe__")
                self._keyring_ok = True
            except Exception:
                self._keyring_ok = False
        return self._keyring_ok

    def _keyring_read(self, key: str) -> str | None:
        try:
            import keyring  # type: ignore[import-untyped]
            return keyring.get_password(_CREDENTIAL_SERVICE, key)
        except Exception as exc:
            _LOG.warning("entitlement storage: keyring read failed: %s", type(exc).__name__)
            return None

    def _keyring_write(self, key: str, value: str) -> None:
        try:
            import keyring  # type: ignore[import-untyped]
            keyring.set_password(_CREDENTIAL_SERVICE, key, value)
        except Exception as exc:
            if self._mode == "production":
                raise RuntimeError(f"EntitlementStorage: keyring write failed: {exc}") from exc
            _LOG.warning("entitlement storage: keyring write failed: %s; using file fallback", type(exc).__name__)
            self._file_write(key, value)

    # ------------------------------------------------------------------ #
    # TEST ONLY file backend                                               #
    # ------------------------------------------------------------------ #

    def _file_path(self, key: str) -> Path:
        base = self._data_dir or (Path(os.environ.get("APPDATA", "C:/tmp")) / "shuabao" / "entitlement-test")
        base.mkdir(parents=True, exist_ok=True)
        return base / f"{key}.TEST_ONLY.json"

    def _file_read(self, key: str) -> str | None:
        # TEST ONLY — plaintext JSON on disk
        p = self._file_path(key)
        if p.exists():
            try:
                return p.read_text(encoding="utf-8")
            except Exception:
                return None
        return None

    def _file_write(self, key: str, value: str) -> None:
        # TEST ONLY — plaintext JSON on disk
        p = self._file_path(key)
        _LOG.debug("entitlement storage: TEST_ONLY file write → %s", p.name)  # path only, not value
        p.write_text(value, encoding="utf-8")
