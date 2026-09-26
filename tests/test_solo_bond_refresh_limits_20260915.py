from pathlib import Path
from unittest.mock import patch

import numpy as np

from shuabao.choice_policy import (
    PANEL_BOND, PanelCandidates, PolicyAction, PolicyDecision, SessionState, SlotCandidate,
    choose_action,
)
from shuabao.mediator import Mediator
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult


ROOT = Path(__file__).resolve().parents[1]


def _frame() -> Frame:
    return Frame(np.zeros((900, 1600, 3), dtype=np.uint8), hwnd=1, window_title="英雄三国KK")


def test_bond_refresh_cap_is_three_per_panel_group() -> None:
    med = Mediator(Settings(), ROOT)
    anchor = MatchResult("bond_hide_btn", 0.99, 580, 552, 10, 10, 580, 552)
    med._enter_panel_episode(_frame(), anchor, "bond", opened=True)
    assert med._choice_session.max_refreshes == 3


def test_bond_refresh_cost_follows_40_60_80_100_ladder() -> None:
    med = Mediator(Settings(), ROOT)
    assert [
        (setattr(med, "_bond_picks_round", picks), med._bond_refresh_price())[1]
        for picks in range(6)
    ] == [40, 60, 80, 100, 100, 100]


def test_refresh_exhaustion_selects_best_readable_card_even_outside_whitelist() -> None:
    med = Mediator(Settings(cards=["大圣"], bonds=["成长", "经济"]), ROOT)
    policy = med._policy_settings()
    slots = (
        SlotCandidate(index=0, name="普通白名单", confidence=0.99),
        SlotCandidate(index=1, name="白赚海盗", confidence=0.99),
        SlotCandidate(index=2, name="成长", confidence=0.99),
        SlotCandidate(index=3, name="祝福", confidence=0.99),
    )
    decision = choose_action(
        PanelCandidates(panel_kind=PANEL_BOND, slots=slots, can_refresh=False, settings=policy),
        SessionState(refreshes=3, max_refreshes=3),
    )
    assert (decision.action, decision.index) == (PolicyAction.SELECT_SLOT, 3)


def test_growth_or_economy_beats_current_advanced_pack_when_refresh_unavailable() -> None:
    med = Mediator(Settings(cards=["大圣"], bonds=["成长", "经济"]), ROOT)
    policy = med._policy_settings()
    decision = choose_action(
        PanelCandidates(
            panel_kind=PANEL_BOND,
            slots=(SlotCandidate(index=0, name="齐天大圣", confidence=0.99),
                   SlotCandidate(index=1, name="经济", confidence=0.99)),
            can_refresh=False,
            settings=policy,
        ),
        SessionState(refreshes=3, max_refreshes=3),
    )
    assert (decision.action, decision.index) == (PolicyAction.SELECT_SLOT, 1)


def test_unaffordable_bond_refresh_reselects_instead_of_hiding() -> None:
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
         patch("shuabao.mediator.choose_action", side_effect=(
             PolicyDecision(PolicyAction.REFRESH, None, "needs refresh"),
             PolicyDecision.select(0, "fallback"),
         )) as choose,
         patch.object(med, "_hud_wood_balance", return_value=39),
         patch.object(med, "_close_current_panel", return_value=close) as close_panel,
    ):
        choice = med._ocr_reward_choice(_frame(), "bond")
    assert choice != close
    close_panel.assert_not_called()
    assert choose.call_count == 2
    assert choose.call_args_list[-1].args[0].can_refresh is False
