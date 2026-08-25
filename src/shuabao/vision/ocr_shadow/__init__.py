"""Persistent OCR shadow sidecar.

The package is deliberately free of Paddle imports.  The model lives in the
child process started by :class:`ShadowClient`.
"""

from .client import ShadowClient, ShadowCandidate, ShadowResponse, shadow_predict
from .protocol import (
    PROTOCOL_VERSION,
    decode_response,
    encode_request,
    panel_fingerprint,
)

__all__ = [
    "PROTOCOL_VERSION",
    "ShadowCandidate",
    "ShadowClient",
    "ShadowResponse",
    "decode_response",
    "encode_request",
    "panel_fingerprint",
    "shadow_predict",
]
