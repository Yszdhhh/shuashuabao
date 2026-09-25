from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.runtime_mediator import Mediator as RuntimeMediator  # noqa: E402
from shuabao.settings import Settings  # noqa: E402
from shuabao.vision.capture import Frame  # noqa: E402


def test_runtime_choice_classification_and_evolution_miss_without_recursion():
    med = RuntimeMediator(Settings(ocr_mode="off", dry_run=True), ROOT)
    frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), window_title="KK")
    med._panel_opened_by_us = None
    med._evolve_awaiting_hero_pick = False
    med._evolve_feedback_pending = False

    assert med._classify_choice_panel(frame) is None
    assert med._find_evolution_choice(frame) is None
