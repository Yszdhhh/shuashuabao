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
