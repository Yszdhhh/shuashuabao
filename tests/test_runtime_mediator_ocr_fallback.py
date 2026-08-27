"""Packaged OCR absence must degrade to the safe template-only policy."""

from __future__ import annotations

import sys
from pathlib import Path

from shuabao import runtime_mediator
from shuabao.settings import Settings


ROOT = Path(__file__).resolve().parents[1]


def test_frozen_package_without_sidecar_starts_in_template_mode(monkeypatch):
    class MissingSidecar:
        def __init__(self, **_kwargs) -> None:
            raise FileNotFoundError(
                "packaged OCR runtime missing: expected ShuaBaoOCR.exe under the ShuaBao distribution"
            )

    settings = Settings(ocr_mode="live")
    monkeypatch.setattr(runtime_mediator, "ProductionShadowClient", MissingSidecar)
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    mediator = runtime_mediator.Mediator(settings, ROOT)

    assert settings.ocr_mode == "off"
    assert mediator.prepare_live_dependencies() is True
    assert mediator._ocr_bootstrap_health == {
        "healthy": True,
        "skipped": True,
        "reason": "packaged_ocr_unavailable_template_mode",
    }
