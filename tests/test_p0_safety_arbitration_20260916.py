"""P0 safety arbitration tests for TQTZ and equipment slots 2-6."""

from pathlib import Path
import time
from unittest.mock import MagicMock, patch
import numpy as np
import pytest

from shuabao.interaction_surface import InteractionSurface, PendingAction
from shuabao.mediator import LoopAction, PanelState, Phase
from shuabao.runtime_mediator import Mediator as RuntimeMediator
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult


def _make_frame() -> Frame:
    return Frame(bgr=np.zeros((900, 1600, 3), dtype=np.uint8))


def _make_match(name: str = "btn", x: int = 100, y: int = 100) -> MatchResult:
    return MatchResult(name, 0.95, x, y, 20, 20, x, y)


def test_p0_01_tqtz_and_affix_modal_same_frame_arbitrates_to_affix() -> None:
    """TQTZ + equipment affix modal同帧 -> 只能处理 affix，0 次 TQTZ。"""
    med = RuntimeMediator(Settings(), Path("."))
    med.phase = Phase.MAIN_LINE
    frame = _make_frame()

    affix_hit = _make_match("equipment_affix_0", 500, 500)
    tqtz_hit = _make_match("tqtz", 600, 100)

    clicks: list[str] = []

    def mock_act_click(hit: MatchResult, reason: str = "") -> bool:
        clicks.append(reason)
        return True

    med.act_click = mock_act_click

    def mock_find(f: Frame, targets: list[str] | str, **kwargs: object) -> MatchResult | None:
        target_list = [targets] if isinstance(targets, str) else list(targets)
        if any("tqtz" in t.lower() for t in target_list):
            return tqtz_hit
        return None

    with patch.object(med, "_find_equipment_affix_choice", return_value=affix_hit), \
         patch.object(med, "_find_game_exit", return_value=None), \
         patch.object(med, "find", side_effect=mock_find):
        res = med._tick_main_line(frame)
        assert res == LoopAction.Continue
        # Affix should be clicked, TQTZ must NOT be clicked
        assert "SelectEquipmentAffix" in clicks
        assert not any("tqtz" in c.lower() for c in clicks)


def test_p0_01_tqtz_and_center_panel_arbitrates_to_center_panel() -> None:
    """TQTZ + center card panel -> 中央面板拥有输入，0 次 TQTZ。"""
    med = RuntimeMediator(Settings(), Path("."))
    med.phase = Phase.MAIN_LINE
    frame = _make_frame()

    anchor_hit = _make_match("bond_hide_btn", 800, 600)

    with patch.object(med, "_selection_anchor", return_value=anchor_hit), \
         patch.object(med, "_find_equipment_affix_choice", return_value=None), \
         patch.object(med, "_tick_panel_fsm", return_value=LoopAction.Continue) as mock_panel, \
         patch.object(med, "_maybe_click_tqtz") as mock_tqtz:
        res = med._tick_main_line(frame)
        assert res == LoopAction.Continue
        mock_panel.assert_called_once()
        mock_tqtz.assert_not_called()


def test_p0_01_tqtz_and_hero_choice_arbitrates_to_hero() -> None:
    """TQTZ + hero choice -> hero choice 拥有输入，0 次 TQTZ。"""
    med = RuntimeMediator(Settings(), Path("."))
    med.phase = Phase.MAIN_LINE
    med._evolve_awaiting_hero_pick = True
    frame = _make_frame()

    anchor_hit = _make_match("hero_anchor", 800, 300)
    hero_hit = _make_match("evolution_card_0_rank_3", 666, 300)

    with patch.object(med, "_selection_anchor", return_value=anchor_hit), \
         patch.object(med, "_find_equipment_affix_choice", return_value=None), \
         patch.object(med, "_classify_choice_panel", return_value=None), \
         patch.object(med, "_find_evolution_choice", return_value=hero_hit), \
         patch.object(med, "act_click", return_value=True) as mock_click, \
         patch.object(med, "_maybe_click_tqtz") as mock_tqtz:
        res = med._tick_main_line(frame)
        assert res == LoopAction.Continue
        assert any(c[0][1] == "SelectEvolutionCard" for c in mock_click.call_args_list)
        mock_tqtz.assert_not_called()


def test_p0_01_tqtz_on_conflict_or_unknown_zero_input() -> None:
    """TQTZ + UNKNOWN / conflict surface -> zero input。"""
    med = RuntimeMediator(Settings(), Path("."))
    med.phase = Phase.MAIN_LINE
    frame = _make_frame()

    affix_hit = _make_match("equipment_affix_0", 500, 500)
    anchor_hit = _make_match("bond_hide_btn", 800, 600)

    with patch.object(med, "_find_equipment_affix_choice", return_value=affix_hit), \
         patch.object(med, "_selection_anchor", return_value=anchor_hit), \
         patch.object(med, "act_click") as mock_click, \
         patch.object(med, "_maybe_click_tqtz") as mock_tqtz:
        res = med._tick_main_line(frame)
        assert res == LoopAction.Continue
        mock_click.assert_not_called()
        mock_tqtz.assert_not_called()


def test_p0_01_pure_hud_tqtz_eligible() -> None:
    """纯 HUD + TQTZ -> TQTZ 正常执行。"""
    med = RuntimeMediator(Settings(), Path("."))
    med.phase = Phase.MAIN_LINE
    frame = _make_frame()

    with patch.object(med, "_find_equipment_affix_choice", return_value=None), \
         patch.object(med, "_selection_anchor", return_value=None), \
         patch.object(med, "_is_in_game_hud", return_value=True), \
         patch.object(med, "_auto_task_done", True), \
         patch.object(med, "_ensure_challenge_buttons", return_value=None), \
         patch.object(med, "_maybe_ensure_hero_panel_focus", return_value=None), \
         patch.object(med, "_maybe_click_tqtz", return_value=LoopAction.Continue) as mock_tqtz:
        res = med._tick_main_line(frame)
        assert res == LoopAction.Continue
        mock_tqtz.assert_called_once()


def test_p0_02_slots_2_to_6_zero_blind_clicks() -> None:
    """P0-02: slots 2-6 unknown / occupied / empty produce 0 input."""
    med = RuntimeMediator(Settings(), Path("."))
    med.phase = Phase.MAIN_LINE
    frame = _make_frame()

    med._equipment_next_at = time.time() + 100.0  # Slot 1 on cooldown
    med._equipment_round_next_at = 0.0
    med._equipment_round_current_slot = 2

    clicks: list[str] = []
    med.act_click = lambda hit, reason="": clicks.append(reason) or True

    action = med._maybe_upgrade_equipment(frame)
    assert action == LoopAction.Continue
    assert len(clicks) == 0


def test_p0_02_slot_1_upgrade_authorized_still_works() -> None:
    """P0-02: slot 1 authorized upgrade continues to function via right-click."""
    med = RuntimeMediator(Settings(), Path("."))
    frame = _make_frame()

    rclicks: list[str] = []
    med.act_right_click = lambda hit, reason="": rclicks.append(reason) or True

    with patch.object(med, "_slot1_upgrade_authorized", return_value=True), \
         patch.object(med, "_hud_button_hit", return_value=_make_match("slot_1", 1087, 737)), \
         patch.object(med, "_equipment_slot_fingerprint", return_value="fp123"):
        action = med._maybe_upgrade_equipment(frame)
        assert action == LoopAction.Continue
        assert "UpgradeEquipmentSlot1-max" in rclicks


def test_p0_02_equipment_step_advances_without_slot_2_to_6_hang() -> None:
    """P0-02: equipment step completes/advances cycle without hanging on slots 2-6."""
    med = RuntimeMediator(Settings(), Path("."))
    med.phase = Phase.MAIN_LINE
    med._l1_cycle_step = "equipment"
    frame = _make_frame()
    now = time.time()

    med._equipment_pending_until = 0.0
    med._equipment_next_at = now + 10.0
    with patch.object(med, "_selection_anchor", return_value=None), \
         patch.object(med, "_find_equipment_affix_choice", return_value=None), \
         patch.object(med, "_is_in_game_hud", return_value=True), \
         patch.object(med, "_auto_task_done", True), \
         patch.object(med, "_ensure_challenge_buttons", return_value=None), \
         patch.object(med, "_maybe_ensure_hero_panel_focus", return_value=None), \
         patch.object(med, "_slot1_upgrade_authorized", return_value=False):
        res = med._tick_main_line(frame)
        assert res == LoopAction.Continue
        # Step should advance to pickup smoothly
        assert med._l1_cycle_step == "pickup"
