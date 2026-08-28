"""shuabao.entitlement — thin Windows entitlement client."""
from .models import (
    EntitlementDeniedError,
    EntitlementError,
    EntitlementMode,
    EntitlementSnapshot,
    EntitlementStatus,
    EntitlementVerificationError,
)
from .service import EntitlementService
from .verifier import OfflineVerifier
from .device import device_fingerprint
from .storage import EntitlementStorage

__all__ = [
    "EntitlementService",
    "EntitlementSnapshot",
    "EntitlementStatus",
    "EntitlementMode",
    "EntitlementError",
    "EntitlementDeniedError",
    "EntitlementVerificationError",
    "OfflineVerifier",
    "device_fingerprint",
    "EntitlementStorage",
]
