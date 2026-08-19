from __future__ import annotations

from unittest.mock import patch

from shuabao.choice_policy import (
    PANEL_SKILL,
    PanelCandidates,
    PolicyAction,
    PolicySettings,
    SessionState,
    SlotCandidate,
    _rank_skill_candidates,
    choose_action,
)


def test_smart_route_never_breaks_zero_preset_fail_closed_contract():
    decision = choose_action(
        PanelCandidates(
            panel_kind=PANEL_SKILL,
            slots=(SlotCandidate(index=0, name="candidate", confidence=1.0),),
            has_giveup=True,
            settings=PolicySettings(),
        ),
        SessionState(refreshes=99, max_refreshes=3),
    )
    assert decision.action is PolicyAction.CLOSE
    assert decision.index is None


def test_smart_route_never_breaks_exhausted_refresh_fail_closed_contract():
    decision = choose_action(
        PanelCandidates(
            panel_kind=PANEL_SKILL,
            slots=(
                SlotCandidate(
                    index=0,
                    name="outside",
                    family="outside-family",
                    confidence=1.0,
                ),
            ),
            has_giveup=True,
            settings=PolicySettings(
                skill_presets=("focus",),
                skill_focus_families=("focus-family",),
            ),
        ),
        SessionState(refreshes=3, max_refreshes=3),
    )
    assert decision.action is PolicyAction.CLOSE
    assert decision.index is None


def test_smart_route_role_score_cannot_promote_out_of_focus_card():
    settings = PolicySettings(
        skill_presets=("allowed",),
        skill_focus_families=("f1", "f2", "f3", "f4"),
        min_confidence=0.6,
    )
    slots = (
        SlotCandidate(
            index=0,
            name="allowed",
            family="f1",
            confidence=1.0,
            rarity="white",
        ),
        SlotCandidate(
            index=1,
            name="outside",
            family="outside-family",
            confidence=1.0,
            rarity="red",
        ),
    )
    with patch("shuabao.choice_policy.skill_role_rank", return_value=0):
        ranked = _rank_skill_candidates(slots, settings, ())
    assert ranked == [0]
