from pathlib import Path
from unittest.mock import patch

import numpy as np

from shuabao.choice_policy import PolicyAction, PolicyDecision, SlotCandidate
from shuabao.mediator import Mediator
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult


ROOT = Path(__file__).resolve().parents[1]


def _frame() -> Frame:
    return Frame(np.zeros((900, 1600, 3), dtype=np.uint8), hwnd=1, window_title="英雄三国KK")


def test_bond_refresh_cap_is_two_per_panel_group() -> None:
    med = Mediator(Settings(), ROOT)
    anchor = MatchResult("bond_hide_btn", 0.99, 580, 552, 10, 10, 580, 552)
    med._enter_panel_episode(_frame(), anchor, "bond", opened=True)
    assert med._choice_session.max_refreshes == 2


def test_bond_refresh_cost_follows_40_60_80_100_ladder() -> None:
    med = Mediator(Settings(), ROOT)
    assert [
        (setattr(med, "_bond_picks_round", picks), med._bond_refresh_price())[1]
        for picks in range(6)
    ] == [40, 60, 80, 100, 100, 100]


def test_unaffordable_bond_refresh_hides_instead_of_spending_or_fallback_pick() -> None:
    med = Mediator(Settings(), ROOT)
    close = MatchResult("bond_hide_btn", 0.99, 580, 552, 10, 10, 580, 552)
    slots = (SlotCandidate(index=0, name="非白名单", confidence=0.99),)
    with (
        patch.object(med, "_ocr_panel_slots", return_value=[{"index": 0, "name": "非白名单"}]),
        patch.object(med, "_slots_to_candidates", return_value=slots),
        patch.object(med, "_panel_can_refresh", return_value=True),
        patch.object(med, "_panel_has_giveup", return_value=False),
        patch.object(med, "_extract_live_set_progress", return_value=None),
        patch.object(med, "_bond_bar_occupancy", return_value=None),
        patch("shuabao.mediator.choose_action", return_value=PolicyDecision(PolicyAction.REFRESH, None, "needs refresh")),
        patch.object(med, "_hud_wood_balance", return_value=39),
        patch.object(med, "_close_current_panel", return_value=close),
    ):
        choice = med._ocr_reward_choice(_frame(), "bond")
    assert choice == close
