"""A packaged LIVE run must refuse to start if its OCR worker is absent."""

from __future__ import annotations

import sys
from pathlib import Path

from shuabao import runtime_mediator
from shuabao.settings import Settings


ROOT = Path(__file__).resolve().parents[1]


def test_frozen_package_without_sidecar_blocks_live_start(monkeypatch):
    class MissingSidecar:
        def __init__(self, **_kwargs) -> None:
            raise FileNotFoundError(
                "packaged OCR runtime missing: expected ShuaBaoOCR.exe under the ShuaBao distribution"
            )

    settings = Settings(ocr_mode="live")
    monkeypatch.setattr(runtime_mediator, "ProductionShadowClient", MissingSidecar)
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    mediator = runtime_mediator.Mediator(settings, ROOT)

    assert settings.ocr_mode == "live"
    assert mediator.prepare_live_dependencies() is False
    assert mediator._ocr_bootstrap_health == {
        "healthy": False,
        "stage": "client",
        "reason": "packaged OCR runtime missing: expected ShuaBaoOCR.exe under the ShuaBao distribution",
    }


def test_live_ocr_retries_one_transient_start_failure(monkeypatch):
    created: list[object] = []

    class TransientStartClient:
        def __init__(self, **_kwargs) -> None:
            self.start_calls = 0
            self.rearm_calls = 0
            self.closed = False
            self.ready_reason = "ready_timeout"
            self.model_validated = False
            self.model_name = None
            self.model_hash = None
            created.append(self)

        def start(self) -> bool:
            self.start_calls += 1
            if self.start_calls == 1:
                return False
            self.ready_reason = None
            self.model_validated = True
            self.model_name = "test-model"
            self.model_hash = "test-hash"
            return True

        def rearm(self) -> None:
            self.rearm_calls += 1

        def ping(self, *, timeout_ms: int) -> bool:
            return True

        def warmup(self, *, timeout_ms: int) -> bool:
            return True

        def health_check(self) -> dict[str, object]:
            return {
                "healthy": True,
                "ready": True,
                "process_alive": True,
                "model_validated": self.model_validated,
                "model_name": self.model_name,
                "model_hash": self.model_hash,
                "ready_reason": self.ready_reason,
                "load_ms": 1.0,
            }

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(runtime_mediator, "ProductionShadowClient", TransientStartClient)
    mediator = runtime_mediator.Mediator(Settings(ocr_mode="live"), ROOT)

    assert mediator.prepare_live_dependencies() is True
    client = created[0]
    assert client.start_calls == 2
    assert client.rearm_calls == 1
    assert client.closed is False
    assert mediator._ocr_bootstrap_health["start_attempts"] == 2
