from pathlib import Path
from unittest.mock import patch
import cv2
import numpy as np
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


def test_two_card_hero_panel_beats_shared_skill_giveup_and_refresh_anchors() -> None:
    fixture = ROOT / "tests" / "fixtures" / "evolve_deadlock_20260926" / "hero_evolve_two_choice_f0030.png"
    assert fixture.is_file(), f"Fixture missing: {fixture}"
    bgr = cv2.imdecode(np.fromfile(str(fixture), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert bgr is not None
    frame = Frame(bgr)
    med = Mediator(Settings(dry_run=True, ocr_mode="off"), ROOT)

    anchor = med._selection_anchor(frame)
    assert anchor is not None
    assert anchor.name == "skill_refresh_btn"
    assert med._classify_choice_panel(frame) is None
    assert med._find_evolution_choice(frame, anchor).name == "evolution_card_1_rank_6"
    assert med._panel_kind_of(frame, anchor) == "card"
    assert med._find_reward_choice(frame, anchor) == ("card", med._find_evolution_choice(frame, anchor))


def test_hero_awaiting_does_not_click_or_hide_bond_panel() -> None:
    """When awaiting hero choice, an appearing bond panel must NOT be clicked as hero or hidden."""
    bond_fixture = ROOT / "tests" / "fixtures" / "solo_r2_20260925" / "bond_choice_f0342.png"
    assert bond_fixture.is_file(), f"Fixture missing: {bond_fixture}"
    import numpy as np
    bgr = cv2.imdecode(np.fromfile(str(bond_fixture), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert bgr is not None
    frame = Frame(bgr=bgr)

    settings = Settings(dry_run=True, ocr_mode="live")
    med = Mediator(settings, ROOT)
    # Simulate waiting for hero pick after evolve or hero card
    med._evolve_awaiting_hero_pick = True
    med._panel_opened_by_us = None

    # Must NOT click bond panel as hero (and must not blind-click left card 666, 300)
    choice = med._find_reward_choice(frame)
    assert choice is None, f"Expected None (zero input wait), got: {choice}"

    # Must NOT close/hide the panel while awaiting hero pick
    close_hit = med._close_current_panel(frame)
    assert close_hit is None


def test_hero_choice_unrecognized_fails_closed_without_blind_click() -> None:
    """Hero panel with unrecognized cards must fail closed with zero-input wait, never blind-clicking left card."""
    settings = Settings(dry_run=True, ocr_mode="live")
    med = Mediator(settings, ROOT)
    med._evolve_awaiting_hero_pick = True

    # Empty/dark frame with hero anchor 'hide'
    blank = np.zeros((900, 1600, 3), dtype=np.uint8)
    frame = Frame(bgr=blank)
    hero_anchor = MatchResult("hide", 0.95, 577, 591, 100, 30, 577, 591)

    with patch.object(med, "_find_evolution_choice", return_value=None), \
         patch.object(med, "_rarity_choice", return_value=None):
        choice = med._find_reward_choice(frame, hero_anchor)
        # Must return None (zero-input wait), NOT evolution_card_0_fallback @ (666, 300)
        assert choice is None

