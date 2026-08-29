from __future__ import annotations

from shuabao.choice_policy import (
    PANEL_BOND,
    PANEL_SKILL,
    PANEL_TREASURE,
    PanelCandidates,
    PolicyAction,
    PolicySettings,
    SlotCandidate,
    choose_action,
)
from shuabao.policy.equipment_fsm import EquipmentFSM, EquipmentSlotState
from shuabao.policy.merchant_fsm import MerchantFSM, MerchantPhase


def slot(index: int, name: str | None, **kwargs: object) -> SlotCandidate:
    return SlotCandidate(index=index, name=name, confidence=0.95, **kwargs)


def test_skill_focus_miss_refreshes_without_filling_unselected_family() -> None:
    decision = choose_action(PanelCandidates(
        panel_kind=PANEL_SKILL,
        slots=(slot(0, "地震"),),
        can_refresh=True,
        settings=PolicySettings(
            skill_presets=("剑气",),
            skill_fill_empty_slots=False,
            skill_refresh_on_focus_miss=True,
        ),
    ))
    assert decision.action is PolicyAction.REFRESH

def test_skill_runtime_assembled_strict_never_fills_unselected_family() -> None:
    import json
    from pathlib import Path
    from shuabao.choice_policy import assemble_policy_settings
    from shuabao.settings import Settings

    policy_path = Path("config/choice_policy.json")
    policy_doc = json.loads(policy_path.read_text(encoding="utf-8")) if policy_path.exists() else {}

    # User configured only "剑气", currently owns 1 skill card "剑气"
    runtime_settings = assemble_policy_settings(
        settings=Settings(skills=["jq"]),
        skill_labels={"jq": "剑气"},
        fetter_labels={},
        policy_doc=policy_doc,
    )
    assert runtime_settings.skill_fill_empty_slots is False
    assert runtime_settings.skill_focus_families == ("剑气",)

    # Panel contains an unselected legal skill "地震" and no "剑气"
    decision = choose_action(PanelCandidates(
        panel_kind=PANEL_SKILL,
        slots=(slot(0, "地震", rarity="orange"),),
        can_refresh=True,
        settings=runtime_settings,
        owned_skill_cards=("剑气",),
    ))
    # Must refresh, never give up or pick unselected "地震".
    assert decision.action is PolicyAction.REFRESH

def test_treasure_negative_needs_explicit_allowlist_match() -> None:
    decision = choose_action(PanelCandidates(
        panel_kind=PANEL_TREASURE,
        slots=(slot(0, "压制", rarity="red"),),
        settings=PolicySettings(treasure_allow_negative=("未知卡",)),
    ))
    assert decision.action is PolicyAction.CLOSE


def test_treasure_negative_refreshes_when_button_is_verified() -> None:
    decision = choose_action(PanelCandidates(
        panel_kind=PANEL_TREASURE,
        slots=(slot(0, "压制", rarity="red"),),
        can_refresh=True,
        settings=PolicySettings(),
    ))
    assert decision.action is PolicyAction.REFRESH


def test_bond_slot_pressure_rejects_scatter_with_two_empty_slots() -> None:
    decision = choose_action(PanelCandidates(
        panel_kind=PANEL_BOND,
        slots=(slot(0, "体术", rarity="red"),),
        settings=PolicySettings(),
        free_slots=2,
    ))
    assert decision.action is PolicyAction.CLOSE

def test_bond_tier_cross_beats_non_crossing_gap_reduction() -> None:
    decision = choose_action(PanelCandidates(
        panel_kind=PANEL_BOND,
        slots=(slot(0, "二阶"), slot(1, "普通")),
        set_progress={
            "tier": {"have": 1, "need": 2, "members": ["一阶", "二阶"], "owned": ["一阶"]},
            "plain": {"have": 0, "need": 2, "members": ["普通", "另一张"], "owned": []},
        },
        settings=PolicySettings(bond_whitelist_mode="soft"),
        free_slots=1,
    ))
    assert (decision.action, decision.index) == (PolicyAction.SELECT_SLOT, 0)


def test_bond_zero_slots_accepts_only_merge_or_zero_cost() -> None:
    decision = choose_action(PanelCandidates(
        panel_kind=PANEL_BOND,
        slots=(slot(0, "免费", zero_cost=True), slot(1, "散卡")),
        settings=PolicySettings(bond_presets=("免费", "散卡")),
        free_slots=0,
    ))
    assert (decision.action, decision.index) == (PolicyAction.SELECT_SLOT, 0)


def test_merchant_requires_two_matching_frames_and_evicts_timeout() -> None:
    state = MerchantFSM().observe(True, "same", 1.0)
    assert state.phase is MerchantPhase.CONFIRMING
    state = state.observe(True, "same", 2.0)
    assert state.phase is MerchantPhase.READY
    state = state.begin_purchase(2.0, timeout_s=1.0)
    assert state.phase is MerchantPhase.VERIFYING
    state = state.observe(True, "same", 3.0)
    assert state.phase is MerchantPhase.EVICTED

def test_merchant_purchase_cap_requires_mutating_frames_between_actions() -> None:
    state = MerchantFSM()
    for count in range(5):
        fingerprint = f"frame-{count}"
        state = state.observe(True, fingerprint, float(count) * 2)
        state = state.observe(True, fingerprint, float(count) * 2 + 1)
        state = state.begin_purchase(float(count) * 2 + 1, timeout_s=5.0)
    state = state.observe(True, "frame-final", 11.0).observe(True, "frame-final", 12.0)
    assert state.purchases == 5
    assert state.begin_purchase(12.0, timeout_s=5.0) == state
    state = state.begin_reroll(12.0, timeout_s=5.0)
    assert state.rerolls == 1
    assert state.purchases == 0


def test_equipment_action_lease_deduplicates_pending_slot() -> None:
    state = EquipmentFSM().begin(2, 10.0, lease_s=1.0)
    assert state.slot_state(2) is EquipmentSlotState.LEASED
    assert state.begin(3, 10.5, lease_s=1.0) == state
    assert state.observe(11.0).slot_state(2) is EquipmentSlotState.QUARANTINED
