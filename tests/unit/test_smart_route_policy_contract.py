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
    assemble_policy_settings,
    choose_action,
)
from shuabao.settings import Settings


def test_zero_skill_configuration_still_closes_without_refresh_or_giveup():
    decision = choose_action(
        PanelCandidates(
            panel_kind=PANEL_SKILL,
            slots=(SlotCandidate(index=0, name="anything", confidence=1.0),),
            has_giveup=True,
            settings=PolicySettings(),
        )
    )
    assert decision.action is PolicyAction.CLOSE
    assert decision.index is None


def test_skill_attempt_budget_exhaustion_still_closes():
    settings = PolicySettings(
        skill_presets=("focus-card",),
        skill_focus_families=("focus-family",),
    )
    decision = choose_action(
        PanelCandidates(
            panel_kind=PANEL_SKILL,
            slots=(
                SlotCandidate(
                    index=0,
                    name="focus-card",
                    family="focus-family",
                    confidence=1.0,
                ),
            ),
            has_giveup=True,
            settings=settings,
        ),
        SessionState(attempts=12, max_attempts=12),
    )
    assert decision.action is PolicyAction.CLOSE
    assert decision.index is None


def test_skill_refresh_budget_exhaustion_still_closes_when_no_safe_focus_candidate():
    settings = PolicySettings(
        skill_presets=("focus-card",),
        skill_focus_families=("focus-family",),
    )
    decision = choose_action(
        PanelCandidates(
            panel_kind=PANEL_SKILL,
            slots=(
                SlotCandidate(
                    index=0,
                    name="outside-card",
                    family="outside-family",
                    confidence=1.0,
                ),
            ),
            has_giveup=True,
            settings=settings,
        ),
        SessionState(refreshes=3, max_refreshes=3),
    )
    assert decision.action is PolicyAction.CLOSE
    assert decision.index is None


def test_role_rank_only_reorders_already_legal_focused_candidates():
    settings = PolicySettings(
        skill_presets=("pure-damage", "team-amp"),
        skill_focus_families=("f1", "f2", "f3", "f4"),
        min_confidence=0.6,
    )
    slots = (
        SlotCandidate(
            index=0,
            name="pure-damage",
            family="f2",
            confidence=1.0,
            rarity="orange",
        ),
        SlotCandidate(
            index=1,
            name="team-amp",
            family="f2",
            confidence=1.0,
            rarity="orange",
        ),
        # Out of focus: a mocked strong role score must never make it eligible.
        SlotCandidate(
            index=2,
            name="outside",
            family="outside-family",
            confidence=1.0,
            rarity="red",
        ),
    )

    def fake_role_rank(name, *_args, **_kwargs):
        return {"team-amp": 0, "pure-damage": 2, "outside": 0}[name]

    with patch("shuabao.choice_policy.skill_role_rank", side_effect=fake_role_rank):
        ranked = _rank_skill_candidates(slots, settings, ())

    assert ranked == [1, 0]
    assert 2 not in ranked


def test_low_confidence_candidate_stays_ineligible_even_with_best_role_score():
    settings = PolicySettings(
        skill_presets=("low", "safe"),
        skill_focus_families=("f1", "f2", "f3", "f4"),
        min_confidence=0.8,
    )
    slots = (
        SlotCandidate(index=0, name="low", family="f1", confidence=0.79),
        SlotCandidate(index=1, name="safe", family="f1", confidence=0.99),
    )
    with patch("shuabao.choice_policy.skill_role_rank", return_value=0):
        ranked = _rank_skill_candidates(slots, settings, ())
    assert ranked == [1]


def test_runtime_assembly_carries_disabled_amplifier_tuning():
    settings = Settings(
        skills=["asj", "asjg", "assx", "jq"],
        smart_route_disabled_amplifiers=["assx"],
    )
    assembled = assemble_policy_settings(
        settings=settings,
        skill_labels={
            "asj": "奥术箭",
            "asjg": "奥术激光",
            "assx": "奥术射线",
            "jq": "剑气",
        },
        fetter_labels={},
        policy_doc={},
    )
    assert assembled.skill_disabled_amplifiers == ("assx",)
    assert len(assembled.skill_focus_families) == 4


def test_settings_normalizes_smart_route_disabled_amplifiers():
    parsed = Settings._from_dict(
        {"smart_route_disabled_amplifiers": ["assx", "assx", "asjg", ""]}
    )
    assert parsed.smart_route_disabled_amplifiers == ["assx", "asjg"]
