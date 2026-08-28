"""Ed25519 offline entitlement verifier — public key only.

Windows client contains ONLY the public key.
Private signing key stays on Bridge server side.

Security checks performed in order:
  1. Signature validity (Ed25519 over canonical JSON bytes)
  2. Device fingerprint binding
  3. Token expiry + grace window

Any failure raises EntitlementVerificationError with a generic message;
no signature internals are propagated to UI.
"""
from __future__ import annotations

import base64
import json
import logging
import time
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from .models import EntitlementVerificationError

_LOG = logging.getLogger(__name__)


class OfflineVerifier:
    """Verifies a SignedOfflineEntitlement from the Bridge.

    Args:
        public_key_pem: PEM-encoded Ed25519 PUBLIC key bytes.
            MUST be the server signing public key; NEVER the private key.
        grace_seconds: Extra seconds to allow past expires_at for offline grace.
            Defaults to 48 hours (172800 s).
    """

    def __init__(self, public_key_pem: bytes, grace_seconds: float = 172_800.0) -> None:
        self._public_key: Ed25519PublicKey = load_pem_public_key(public_key_pem)  # type: ignore[assignment]
        self.grace_seconds = float(grace_seconds)

    def verify(
        self,
        certificate: str,
        signature: str,
        *,
        expected_fingerprint: str,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Verify a signed offline entitlement.

        Returns the decoded payload dict on success.
        Raises EntitlementVerificationError on any failure (fail-closed).
        """
        # 1. Signature
        try:
            json_bytes = base64.b64decode(certificate)
            raw_sig = base64.b64decode(signature)
            self._public_key.verify(raw_sig, json_bytes)
            payload: dict[str, Any] = json.loads(json_bytes.decode("utf-8"))
        except InvalidSignature:
            _LOG.warning("offline entitlement: signature invalid")
            raise EntitlementVerificationError("签名无效")
        except Exception as exc:
            _LOG.warning("offline entitlement: verification error: %s", type(exc).__name__)
            raise EntitlementVerificationError("离线凭证解析失败")

        # 2. Device binding
        token_fp = payload.get("fingerprint", "")
        if token_fp != expected_fingerprint:
            _LOG.warning(
                "offline entitlement: device mismatch token_fp=%s expected=%s",
                token_fp[:8] + "…",
                expected_fingerprint[:8] + "…",
            )
            raise EntitlementVerificationError("设备绑定不匹配")

        # 3. Expiry + grace
        expires_ts = _parse_expires(payload.get("expires_at"))
        clock = time.time() if now is None else float(now)
        if expires_ts is not None and clock > expires_ts + self.grace_seconds:
            _LOG.info("offline entitlement: expired expires_at=%s grace=%.0fs", payload.get("expires_at"), self.grace_seconds)
            raise EntitlementVerificationError("离线凭证已过期")

        return payload


def _parse_expires(raw: Any) -> float | None:
    """Parse expires_at from ISO string or unix timestamp; None means never."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:
        return None
