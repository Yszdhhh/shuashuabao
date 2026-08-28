"""Entitlement client states and DTOs.

Deliberately thin: no Keygen internals, no billing logic.
"""
from __future__ import annotations

from enum import Enum
from typing import Any


class EntitlementStatus(str, Enum):
    """Client-side canonical subscription states."""
    TRIAL      = "TRIAL"
    ACTIVE     = "ACTIVE"
    GRACE      = "GRACE"       # offline grace or past-due transient
    PAST_DUE   = "PAST_DUE"
    EXPIRED    = "EXPIRED"
    SUSPENDED  = "SUSPENDED"
    REVOKED    = "REVOKED"
    UNKNOWN    = "UNKNOWN"


class EntitlementMode(str, Enum):
    DISABLED   = "disabled"
    TEST       = "test"
    PRODUCTION = "production"


class EntitlementSnapshot:
    """Immutable point-in-time authorisation snapshot."""

    __slots__ = (
        "status", "expires_at", "offline_until",
        "device_id", "plan", "source", "last_checked_at", "message",
    )

    def __init__(
        self,
        *,
        status: EntitlementStatus,
        expires_at: float | None = None,
        offline_until: float | None = None,
        device_id: str = "",
        plan: str = "",
        source: str = "unknown",
        last_checked_at: float = 0.0,
        message: str = "",
    ) -> None:
        self.status = status
        self.expires_at = expires_at
        self.offline_until = offline_until
        self.device_id = device_id
        self.plan = plan
        self.source = source
        self.last_checked_at = last_checked_at
        self.message = message

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "expires_at": self.expires_at,
            "offline_until": self.offline_until,
            "device_id": self.device_id,
            "plan": self.plan,
            "source": self.source,
            "last_checked_at": self.last_checked_at,
            "message": self.message,
        }

    def __repr__(self) -> str:
        return (
            f"EntitlementSnapshot(status={self.status.value!r}, "
            f"source={self.source!r}, plan={self.plan!r})"
        )


# ── Exceptions ──────────────────────────────────────────────────────────── #

class EntitlementError(RuntimeError):
    """Base for all entitlement errors."""


class EntitlementDeniedError(EntitlementError):
    """RunnerService.start() blocked by entitlement gate."""


class EntitlementVerificationError(EntitlementError):
    """Offline token failed cryptographic or expiry verification."""
