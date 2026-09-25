from pathlib import Path
import cv2
import pytest
from shuabao.mediator import Mediator, Frame, Settings, MatchResult

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "solo_r2_20260925" / "hero_choice_f0300.png"


def test_solo_r2_hero_choice_selects_ssr_without_hiding() -> None:
    assert FIXTURE_PATH.is_file(), f"Fixture missing: {FIXTURE_PATH}"
    import numpy as np
    bgr = cv2.imdecode(np.fromfile(str(FIXTURE_PATH), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert bgr is not None, "Failed to load fixture"
    frame = Frame(bgr=bgr)

    settings = Settings(dry_run=True, ocr_mode="live")
    med = Mediator(settings, ROOT)
    # Ensure neither evolve pending nor feedback pending is active
    med._evolve_awaiting_hero_pick = False
    med._evolve_feedback_pending = False
    med._panel_opened_by_us = None

    # 1. Direct evolution choice recognition
    evo_choice = med._find_evolution_choice(frame)
    assert evo_choice is not None
    assert evo_choice.name == "evolution_card_0_rank_4"
    assert evo_choice.x == 666 and evo_choice.y == 300

    # 2. Panel classification avoids false treasure match
    anchor = med._selection_anchor(frame)
    assert anchor is not None
    assert med._classify_choice_panel(frame) != "treasure"
    kind = med._panel_kind_of(frame, anchor)
    assert kind != "treasure"
    assert kind == "card"

    # 3. Reward choice returns the hero card selection
    choice = med._find_reward_choice(frame, anchor)
    assert choice is not None
    ret_kind, ret_hit = choice
    assert ret_kind == "card"
    assert ret_hit.name == "evolution_card_0_rank_4"

    # 4. Hero choice modal must NEVER be closed/hidden
    close_hit = med._close_current_panel(frame, kind)
    assert close_hit is None
