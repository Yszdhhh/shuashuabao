from pathlib import Path
import cv2
import numpy as np
import pytest

from shuabao.mediator import Mediator, Frame, Settings

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "solo_r2_20260925" / "bond_choice_f0342.png"


def test_stalled_bond_choice_selects_target_greed_without_hiding() -> None:
    assert FIXTURE_PATH.is_file(), f"Fixture missing: {FIXTURE_PATH}"
    bgr = cv2.imdecode(np.fromfile(str(FIXTURE_PATH), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert bgr is not None, "Failed to load fixture"
    frame = Frame(bgr=bgr)

    settings = Settings(dry_run=True, ocr_mode="live", bonds=["贪婪", "大圣"])
    med = Mediator(settings, ROOT)
    # Simulate main line stall condition
    med._main_line_stalled = lambda: True

    # 1. OCR choice recognizes greed at slot 3
    choice = med._ocr_reward_choice(frame, "bond")
    assert choice is not None
    # Must NOT be card_hide
    assert choice.name != "card_hide"
    # Must select greed on first frame
    assert "贪婪" in choice.name
    assert choice.x == 1152 and choice.y == 396
