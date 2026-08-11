"""Small, dependency-free JSONL protocol helpers for the OCR shadow worker."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

PROTOCOL_VERSION = 1


@dataclass(frozen=True)
class ShadowCandidate:
    name: str
    confidence: float

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "confidence": round(float(self.confidence), 4)}


@dataclass(frozen=True)
class ShadowResponse:
    seq: int
    status: str
    candidates: tuple[ShadowCandidate, ...] = ()
    elapsed_ms: float = 0.0
    reason: str | None = None
    cache_hit: bool = False

    @property
    def available(self) -> bool:
        return self.status == "ok"

    @classmethod
    def unavailable(cls, seq: int, reason: str, elapsed_ms: float = 0.0) -> "ShadowResponse":
        return cls(seq=seq, status="unavailable", reason=reason, elapsed_ms=elapsed_ms)

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "seq": self.seq,
            "status": self.status,
            "candidates": [c.as_dict() for c in self.candidates],
            "elapsed_ms": round(float(self.elapsed_ms), 3),
        }
        if self.reason:
            out["reason"] = self.reason
        return out


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def encode_request(request: dict[str, Any]) -> str:
    """Encode one request without allowing non-JSON values onto the pipe."""
    if "seq" not in request:
        raise ValueError("request requires seq")
    return json.dumps(request, ensure_ascii=False, separators=(",", ":"), default=_json_default)


def decode_response(line: str | bytes) -> dict[str, Any]:
    """Parse and minimally validate one worker response."""
    if isinstance(line, bytes):
        line = line.decode("utf-8")
    value = json.loads(line)
    if not isinstance(value, dict):
        raise ValueError("response must be an object")
    if not isinstance(value.get("seq"), int):
        raise ValueError("response seq must be an integer")
    status = value.get("status")
    if status not in {"ok", "unavailable"}:
        # Accept the compact legacy spelling used by early sidecar probes.
        if value.get("ok") is True:
            value["status"] = "ok"
        elif value.get("unavailable") is True:
            value["status"] = "unavailable"
        else:
            raise ValueError("response status must be ok or unavailable")
    candidates = value.get("candidates", [])
    if not isinstance(candidates, list):
        raise ValueError("response candidates must be a list")
    for candidate in candidates:
        if not isinstance(candidate, dict) or not isinstance(candidate.get("name"), str):
            raise ValueError("candidate requires name")
        if not isinstance(candidate.get("confidence"), (int, float)):
            raise ValueError("candidate requires numeric confidence")
    if not isinstance(value.get("elapsed_ms"), (int, float)):
        raise ValueError("response requires numeric elapsed_ms")
    return value


def panel_fingerprint(frame: Any, bbox: tuple[int, int, int, int] | list[int] | None = None) -> str:
    """Return a content fingerprint suitable for current-panel cache binding.

    ``frame`` may be a numpy array, bytes, a path-like object, or a Frame-like
    object with ``bgr``.  A bbox hashes only that panel when supplied; otherwise
    the complete frame is hashed.  The dimensions are included to avoid shape
    collisions between different captures with identical byte payloads.
    """
    value = getattr(frame, "bgr", frame)
    shape = getattr(value, "shape", None)
    if bbox is not None and shape is not None:
        x0, y0, x1, y1 = (int(v) for v in bbox)
        h, w = int(shape[0]), int(shape[1])
        x0, y0 = max(0, min(w, x0)), max(0, min(h, y0))
        x1, y1 = max(x0, min(w, x1)), max(y0, min(h, y1))
        value = value[y0:y1, x0:x1]
        shape = getattr(value, "shape", shape)
    if hasattr(value, "tobytes"):
        payload = value.tobytes()
        dimensions = "x".join(str(int(v)) for v in shape[:2]) if shape is not None else "?"
    elif isinstance(value, (bytes, bytearray, memoryview)):
        payload = bytes(value)
        dimensions = "bytes"
    else:
        try:
            payload = str(value).encode("utf-8")
        except Exception:
            payload = repr(value).encode("utf-8")
        dimensions = "value"
    return f"{dimensions}:{hashlib.md5(payload).hexdigest()}"
