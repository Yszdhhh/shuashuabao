"""Cloud-audit scalar counterexamples for scheduler legality and evidence ordering."""

from __future__ import annotations

from dataclasses import replace

from shuabao.solo_scheduler import (
    KIND_RECOMMEND,
    KIND_WAIT_OR_OBSERVE,
    Fact,
    OwnerConfig,
    Snapshot,
    _build_candidates,
    decide,
)


def _snapshot(**changes) -> Snapshot:
    base = Snapshot(
        now=100.0,
        wood=Fact.observed(100, "hud"),
        skill_badge=Fact.observed(0, "hud"),
        treasure_badge=Fact.observed(0, "hud"),
        active_transaction=Fact.observed(False, "state"),
        evolution_locked=Fact.observed(False, "state"),
        panel_state=Fact.observed("CLOSED", "state"),
        swallow_guard_allows=Fact.observed(False, "guard"),
        bond_draw_price=Fact.observed(20, "model:draw"),
        bond_refresh_price=Fact.observed(40, "model:refresh"),
        owner=OwnerConfig(current_chain="bond"),
        safe_observe_entries=("skill_badge:existing_hud", "treasure_badge:existing_hud"),
    )
    return replace(base, **changes)


def test_two_unknown_badges_observe_instead_of_recommending_open() -> None:
    decision = decide(_snapshot(
        skill_badge=Fact.unknown("hud"),
        treasure_badge=Fact.unknown("hud"),
    ))
    assert decision.kind == KIND_WAIT_OR_OBSERVE
    assert set(decision.observe_gaps) == {"skill_badge", "treasure_badge"}


def test_refresh_requires_known_downstream_draw_price() -> None:
    decision = decide(_snapshot(bond_draw_price=Fact.unknown("model")))
    assert decision.chosen is None or decision.chosen.action_id != "bond_refresh"
    assert ("bond_refresh", "TARGET_PRICE_UNKNOWN") in decision.alternatives


def test_weak_unknown_skill_cannot_starve_observed_treasure() -> None:
    decision = decide(_snapshot(
        skill_badge=Fact.unknown("hud"),
        treasure_badge=Fact.observed(2, "hud"),
        service_wait_skill=Fact.observed(1000.0, "service"),
        service_wait_treasure=Fact.observed(10.0, "service"),
    ))
    assert decision.kind == KIND_WAIT_OR_OBSERVE
    assert decision.chosen is None or decision.chosen.action_id != "open_skill_panel"


def test_unknown_surface_cannot_recommend_action() -> None:
    decision = decide(_snapshot(
        active_transaction=Fact.unknown("state"),
        panel_state=Fact.unknown("state"),
        skill_badge=Fact.observed(1, "hud"),
    ))
    assert decision.kind == KIND_WAIT_OR_OBSERVE
    assert decision.chosen is None
    assert set(decision.observe_gaps) == {"active_transaction", "panel_state"}


def test_shown_model_price_keeps_provenance_in_candidate_cost() -> None:
    candidates = _build_candidates(_snapshot(
        shown_card_price=Fact.observed(20, "model:test"),
        shown_card_id=Fact.observed("card", "panel"),
    ))
    shown = next(c for c in candidates if c.action_id == "take_card:card")
    assert shown.costs[0].model_derived is True


def test_unrelated_safe_entry_is_not_reported_as_observation_path() -> None:
    decision = decide(_snapshot(
        skill_badge=Fact.unknown("hud"),
        safe_observe_entries=("wood:existing_hud",),
    ))
    assert "wood:existing_hud" not in decision.safe_entries
    assert decision.kind in {KIND_RECOMMEND, KIND_WAIT_OR_OBSERVE}
