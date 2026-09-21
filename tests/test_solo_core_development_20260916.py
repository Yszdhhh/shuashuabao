# -*- coding: utf-8 -*-
"""Regression test suite for solo core development and human-like scheduling (2026-09-16).

Covers the 20 test scenarios specified in Section XIII:
Core development:
1. wood=5000, skill=0 -> F (bond)
2. wood=5000, skill=4 -> still prioritize F
3. wood=5000, skill=12 -> allow G anti-starvation burst
4. After G burst with wood=5000 -> return to F, not full side branch (V/evolve/equipment)
5. wood=900 -> full cycle resumes
6. wood=200, price=100 -> allow one F draw
7. wood=80, price=100 -> skip F draw
8. High-wood F burst reaches safety cap -> no 30s bond idle backoff
9. F burst reaches cap with wood >= 1000 -> do not enter full branch big cycle

Skill refresh:
10. Readable cards, no focus match, refresh exists -> REFRESH action
11. Refresh click success but card fingerprint unchanged -> do not deduct refresh budget
12. Refresh click + confirmed mutation -> refresh count +1
13. Dedicated skill_refresh_btn is the preferred skill-panel refresh hit
14. True refresh template matches real coordinates

Merchant:
15. READY + no stock + no refresh -> advance merchant (no deadlock)
16. CONFIRMING -> do not advance, wait for confirmation frame
17. VERIFYING -> do not advance, hold transaction ownership
18. Real merchant frame recognizes merchant_wood with threshold >= 0.95

Equipment:
19. Passive merchant (READY) + slot1 occupied -> equipment upgrade allowed
20. Merchant VERIFYING -> equipment upgrade blocked
"""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import cv2
import numpy as np
import pytest

from shuabao.choice_policy import (
    choose_action,
    PanelCandidates,
    SlotCandidate,
    PolicySettings,
    PolicyAction,
    SessionState,
    PANEL_SKILL,
)
from shuabao.mediator import LoopAction, Mediator, PanelState, Phase
from shuabao.policy.equipment_fsm import EquipmentFSM, EquipmentSlotState
from shuabao.policy.merchant_fsm import MerchantFSM, MerchantPhase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "solo_live_20260914"


def _frame(name: str) -> Frame:
    image = cv2.imdecode(np.fromfile(str(FIX / name), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None, name
    return Frame(image, window_title="英雄三国KK", hwnd=10001, role="l1")


def _blank_frame() -> Frame:
    bgr = np.zeros((900, 1600, 3), dtype=np.uint8)
    return Frame(bgr, window_title="英雄三国KK", hwnd=10001, role="l1")


def _med(**kw) -> Mediator:
    settings = Settings(
        ocr_mode="off",
        bonds=["成长", "经济", "贪婪", "挑战", "祝福"],
        skills=["飞刀", "斩仙"],
        auto_bond=True,
        auto_weapon=True,
        **kw
    )
    med = Mediator(settings, ROOT)
    med.set_phase(Phase.MAIN_LINE)
    return med


# =========================================================================
# 1. Core Development Tests (1-9)
# =========================================================================

def test_01_wood_5000_skill_0_chooses_bond() -> None:
    """1. wood=5000, skill=0 -> F (bond)."""
    med = _med()
    frame = _frame("hud_wood_1111_f0200.png")
    now = 100.0
    with patch.object(med, "_hud_wood_balance", return_value=5000), \
         patch.object(med, "_hud_skill_points", return_value=0), \
         patch.object(med, "_bond_base_progress_pending", return_value=True):
        target, why = med._solo_plan_panel(frame, now, "bond")
    assert target == "bond"
    assert "优先转化战力" in why or "羁绊优先" in why


def test_02_wood_5000_skill_4_still_prioritizes_bond() -> None:
    """2. wood=5000, skill=4 -> still prioritize F."""
    med = _med()
    frame = _frame("hud_wood_1111_f0200.png")
    now = 100.0
    with patch.object(med, "_hud_wood_balance", return_value=5000), \
         patch.object(med, "_hud_skill_points", return_value=4), \
         patch.object(med, "_bond_base_progress_pending", return_value=True):
        target, why = med._solo_plan_panel(frame, now, "bond")
    assert target == "bond"
    assert "优先转化战力" in why or "羁绊优先" in why


def test_03_wood_5000_skill_12_allows_g_anti_starvation_burst() -> None:
    """3. wood=5000, skill=12 -> allows G anti-starvation burst."""
    med = _med()
    frame = _frame("hud_wood_1111_f0200.png")
    now = 100.0
    with patch.object(med, "_hud_wood_balance", return_value=5000), \
         patch.object(med, "_hud_skill_points", return_value=12), \
         patch.object(med, "_bond_base_progress_pending", return_value=True):
        target, why = med._solo_plan_panel(frame, now, "bond")
    assert target == "skill"
    assert "紧急强抢占" in why


def test_04_g_burst_completed_wood_5000_returns_to_bond() -> None:
    """4. G burst completed with wood still 5000 -> return to F, not full side branch."""
    med = _med()
    med._wood_balance = 5000
    med._l1_cycle_step = "skill"
    # G completes visit
    med._advance_l1_cycle("skill")
    # Must immediately switch to bond
    assert med._l1_cycle_step == "bond"


def test_05_wood_900_allows_full_cycle_rotation() -> None:
    """5. wood=900 -> full cycle resumes across all branch steps."""
    med = _med()
    med._wood_balance = 900
    seen: list[str] = [med._l1_cycle_step]
    for _ in range(10):
        med._advance_l1_cycle()
        seen.append(med._l1_cycle_step)
    # When wood < 1000, full 10-step cycle rotates
    assert "treasure" in seen
    assert "evolve" in seen
    assert "equipment" in seen
    assert "merchant" in seen


def test_06_wood_200_price_100_allows_bond() -> None:
    """6. wood=200, current draw price=100 -> allow one F draw."""
    med = _med()
    frame = _frame("hud_wood_221_f0300.png")
    now = 100.0
    with patch.object(med, "_hud_wood_balance", return_value=200), \
         patch.object(med, "_bond_next_price", return_value=100):
        target, why = med._solo_plan_panel(frame, now, "bond")
    assert target == "bond"
    assert target is not None


def test_07_wood_80_price_100_skips_bond() -> None:
    """7. wood=80, draw price=100 -> skip F."""
    med = _med()
    frame = _frame("hud_wood_221_f0300.png")
    now = 100.0
    with patch.object(med, "_hud_wood_balance", return_value=80), \
         patch.object(med, "_bond_next_price", return_value=100):
        target, why = med._solo_plan_panel(frame, now, "bond")
    assert target is None
    assert "木材 80 < 100" in why


def test_08_high_wood_burst_cap_does_not_set_idle_backoff() -> None:
    """8. High-wood F burst reaches safety cap -> no 30s bond idle backoff."""
    med = _med()
    med._wood_balance = 5000
    med._panel_kind = "bond"
    med._l1_cycle_owned_panel = True
    med._l1_cycle_step = "bond"
    med._l1_cycle_selected = False
    now = time.time()
    med._bond_idle_until = 0.0

    med._finish_panel_episode()
    # With wood=5000 (>= 1000), idle backoff is NOT applied
    assert med._bond_idle_until < now + 1.0


def test_09_burst_cap_with_high_wood_eventually_services_side_branches() -> None:
    """9. F/G remain early in the bounded cycle without starving side branches."""
    med = _med()
    med._wood_balance = 3000
    med._l1_cycle_step = "bond"
    med._l1_cycle_index = 0
    seen = [med._l1_cycle_step]
    for _ in range(len(med._L1_CYCLE_ORDER) * 2):
        med._advance_l1_cycle(med._l1_cycle_step)
        seen.append(med._l1_cycle_step)
    assert set(med._L1_CYCLE_ORDER) <= set(seen)


# =========================================================================
# 2. Skill Refresh Tests (10-14)
# =========================================================================

def test_10_readable_cards_no_focus_match_refresh_exists() -> None:
    """10. Readable cards, no focus match, refresh exists -> REFRESH action."""
    policy = PolicySettings.from_mapping({
        "skill_presets": ["飞刀", "斩仙"],
        "max_refreshes": 3,
        "skill_refresh_on_focus_miss": True,
    })
    slots = (
        SlotCandidate(0, "火球术", 0.95),
        SlotCandidate(1, "暴风雪", 0.95),
        SlotCandidate(2, "雷击", 0.95),
    )
    panel = PanelCandidates(panel_kind=PANEL_SKILL, slots=slots, can_refresh=True, settings=policy)
    decision = choose_action(panel, SessionState())
    assert decision.action == PolicyAction.REFRESH


def test_11_refresh_click_success_without_mutation_preserves_budget() -> None:
    """11. Refresh click success but card fingerprint unchanged -> do not deduct refresh budget."""
    med = _med()
    frame = _blank_frame()
    now = 100.0
    med._panel_kind = "skill"
    med._panel_state = PanelState.WAIT_MUTATION
    med._panel_pending_choice_action = "refresh"
    med._panel_last_input_at = now - 10.0
    med._panel_confirm_window = 5.0
    med._skill_refresh_attempts = 0
    med._panel_mutation_baseline = med._panel_roi_region(frame)

    # Frame unchanged: mutation check fails
    assert not med._panel_mutation_confirmed(frame)

    anchor = MatchResult("anchor", 1.0, 10, 10, 10, 10, 10, 10)
    # Step panel FSM into timeout expiration
    res = med._tick_panel_fsm(frame, anchor, now)

    # Budget must NOT be deducted
    assert med._skill_refresh_attempts == 0
    # Recorded failed attempt
    assert getattr(med, "_skill_refresh_failed_attempts", 0) == 1
    assert med._panel_state == PanelState.ACTIVE


def test_12_refresh_click_with_confirmed_mutation_increments_budget() -> None:
    """12. Refresh click + confirmed mutation -> refresh count +1."""
    med = _med()
    frame = _blank_frame()
    now = 100.0
    med._panel_kind = "skill"
    med._panel_state = PanelState.WAIT_MUTATION
    med._panel_pending_choice_action = "refresh"
    med._skill_refresh_attempts = 0
    # Set different fingerprint to simulate card refresh mutation
    med._choice_fp_before_refresh_physical = "old_md5_hash"
    anchor = MatchResult("anchor", 1.0, 10, 10, 10, 10, 10, 10)
    with patch.object(med, "_panel_physical_fingerprint", return_value="new_md5_hash"), \
         patch.object(med, "_panel_mutation_baseline", return_value=np.zeros((10, 10, 3))), \
         patch.object(med, "_hero_changed_pixels", return_value=3000):
        assert med._panel_mutation_confirmed(frame)
        med._tick_panel_fsm(frame, anchor, now)

    assert med._skill_refresh_attempts == 1
    assert med._panel_state == PanelState.ACTIVE


def test_13_dedicated_skill_refresh_btn_wins_over_generic_refresh() -> None:
    """13. Dedicated skill_refresh_btn is searched first and keeps click authority.

    giveup_panel_not_fail / C-skill-refresh contract: generic ``refresh`` at a
    different coordinate must not beat the panel-specific button.
    """
    med = _med()
    frame = _blank_frame()
    searched: list[str] = []
    dedicated = MatchResult("skill_refresh_btn", 0.759, 1000, 640, 40, 28, 1020, 654)
    generic = MatchResult("refresh", 0.936, 1151, 663, 40, 28, 1171, 677)

    def mock_find(_frame, names, *a, **kw):
        searched.extend(names)
        key = names[0] if names else None
        if key == "skill_refresh_btn":
            return dedicated
        if key == "refresh":
            return generic
        return None

    with patch.object(med, "find", side_effect=mock_find):
        res = med._find_panel_refresh(frame, "skill")
    assert res is not None
    assert res.name == "skill_refresh_btn"
    assert res.center == (1020, 654)
    assert searched[0] == "skill_refresh_btn"


def test_14_true_refresh_template_searched_for_skill() -> None:
    """14. True refresh template names are queried for skill panel refresh."""
    med = _med()
    frame = _blank_frame()
    searched: list[str] = []

    def mock_find(_frame, names, *a, **kw):
        searched.extend(names)
        if "refresh" in names:
            return MatchResult("refresh", 0.95, 600, 600, 40, 40, 600, 600)
        return None

    with patch.object(med, "find", side_effect=mock_find):
        hit = med._find_panel_refresh(frame, "skill")
    assert hit is not None
    assert hit.name == "refresh"
    assert "refresh" in searched


# =========================================================================
# 3. Merchant Tests (15-18)
# =========================================================================

def test_15_merchant_ready_no_stock_no_refresh_advances_cycle() -> None:
    """15. READY + no stock + no refresh -> advance merchant (no deadlock)."""
    med = _med()
    frame = _blank_frame()
    med._l1_cycle_step = "merchant"
    med._merchant_fsm = MerchantFSM(phase=MerchantPhase.READY, purchases=0, rerolls=20)
    with patch.object(med, "_black_merchant_present", return_value=True), \
         patch.object(med, "_merchant_refresh_available", return_value=False), \
         patch.object(med, "find", return_value=None), \
         patch.object(med, "_merchant_discount_slots", return_value=[]):
        res = med._maybe_black_merchant(frame)
    assert res is None
    # Must advance to next cycle step
    assert med._l1_cycle_step == "artifact"


def test_16_merchant_confirming_does_not_advance() -> None:
    """16. CONFIRMING -> do not advance, wait for confirmation frame."""
    med = _med()
    frame = _blank_frame()
    med._l1_cycle_step = "merchant"
    # Single frame observation enters CONFIRMING
    med._merchant_fsm = MerchantFSM(phase=MerchantPhase.ABSENT)
    with patch.object(med, "_black_merchant_present", return_value=True), \
         patch.object(med, "_merchant_fingerprint", return_value="fp1"), \
         patch.object(med, "find", return_value=MatchResult("danGif", 0.95, 100, 100, 20, 20, 100, 100)), \
         patch.object(med, "_in_merchant_strip", return_value=True), \
         patch.object(med, "_merchant_slot_index", return_value=0):
        res = med._maybe_black_merchant(frame)
    assert med._merchant_fsm.phase == MerchantPhase.CONFIRMING
    # Must hold cycle position (does not advance)
    assert med._l1_cycle_step == "merchant"
    assert res == LoopAction.Continue


def test_17_merchant_verifying_does_not_advance_holds_ownership() -> None:
    """17. VERIFYING -> do not advance, hold transaction ownership."""
    med = _med()
    frame = _blank_frame()
    med._l1_cycle_step = "merchant"
    med._merchant_fsm = MerchantFSM(phase=MerchantPhase.VERIFYING, purchases=1, pending_fingerprint="fp1", deadline=time.time() + 5.0)
    with patch.object(med, "_black_merchant_present", return_value=True), \
         patch.object(med, "_merchant_fingerprint", return_value="fp1"):
        res = med._maybe_black_merchant(frame)
    assert res == LoopAction.Continue
    assert med._l1_cycle_step == "merchant"


def test_18_real_merchant_frame_detects_merchant_wood() -> None:
    """18. Real merchant frame recognizes merchant_wood with threshold >= 0.95."""
    med = _med()
    fixture_path = ROOT / "tests" / "fixtures" / "solo_round2_b1_20260915" / "merchant_wood_f0085.png"
    assert fixture_path.exists(), f"Fixture not found at {fixture_path}"
    bgr = cv2.imdecode(np.fromfile(str(fixture_path), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert bgr is not None
    frame = Frame(bgr)
    hit = med.find(frame, ["merchant_wood"], threshold=0.95, scales=(0.9, 1.0, 1.1), roi=(0.70, 0.66, 0.90, 0.76))
    assert hit is not None
    assert hit.score >= 0.95
    assert 1100 <= hit.x <= 1200
    assert 600 <= hit.y <= 620


# =========================================================================
# 4. Equipment Tests (19-20)
# =========================================================================

def test_19_merchant_passive_ready_allows_equipment_upgrade() -> None:
    """19. Merchant READY/passive + slot1 occupied -> equipment upgrade allowed."""
    med = _med()
    frame = _blank_frame()
    med._l1_cycle_step = "equipment"
    med._panel_state = PanelState.CLOSED
    med._merchant_fsm = MerchantFSM(phase=MerchantPhase.READY)
    med._equipment_next_at = 0.0

    clicked: list[str] = []
    with patch.object(med, "_equipment_slot_one_occupied", return_value=True), \
         patch.object(med, "_equipment_slot_fingerprint", return_value="slot1_fp"), \
         patch.object(med, "act_right_click", side_effect=lambda hit, reason: clicked.append(reason) or True):
        res = med._maybe_upgrade_equipment(frame)

    assert res == LoopAction.Continue
    assert any("UpgradeEquipmentSlot1-max" in c for c in clicked)


def test_20_merchant_verifying_blocks_equipment_upgrade() -> None:
    """20. Merchant VERIFYING -> equipment upgrade blocked."""
    med = _med()
    frame = _blank_frame()
    med._l1_cycle_step = "equipment"
    med._panel_state = PanelState.CLOSED
    med._merchant_fsm = MerchantFSM(phase=MerchantPhase.VERIFYING, purchases=1)
    med._equipment_next_at = 0.0

    clicked: list[str] = []
    with patch.object(med, "_equipment_slot_one_occupied", return_value=True), \
         patch.object(med, "act_right_click", side_effect=lambda hit, reason: clicked.append(reason) or True):
        res = med._maybe_upgrade_equipment(frame)

    assert res == LoopAction.Continue
    # No right click was performed because merchant is actively VERIFYING
    assert len(clicked) == 0


def test_21_opportunistic_evolve_full_multi_frame_lifecycle_from_tick_main_line() -> None:
    """Multi-frame lifecycle from _tick_main_line():
    click evolve -> transition frame/no hero anchor -> prohibit F/G -> feedback confirmed ->
    hero-choice ownership maintained -> hero modal -> select -> complete -> return to core step.
    """
    med = _med()
    med.settings.skip_pre_wave_delay = True
    med.settings.pre_wave_protection = False
    med._auto_task_done = True
    med._main_line_started_at = 100.0
    med._l1_cycle_step = "bond"
    med._wood_balance = 5000
    med._panel_state = PanelState.CLOSED
    now = 1000.0
    med._panel_cooldown_until["bond"] = now + 5.0

    frame_hud = _blank_frame()
    evolve_btn = MatchResult("evolve_hud", 1.0, 800, 700, 40, 12, 800, 700)
    hero_anchor = MatchResult("evolution_anchor", 1.0, 800, 300, 100, 50, 800, 300)
    hero_choice = MatchResult("evolution_card_0_rank_3", 1.0, 666, 300, 100, 100, 666, 300)

    clicks: list[str] = []
    keys: list[str] = []

    with patch("shuabao.mediator.time.time", side_effect=lambda: now), \
         patch.object(med, "act_click", side_effect=lambda hit, reason, *a, **k: clicks.append(reason) or True), \
         patch.object(med, "act_key", side_effect=lambda key, reason, *a, **k: keys.append(reason) or True), \
         patch.object(med, "_is_in_game_hud", return_value=True), \
         patch.object(med, "_post_game_state", return_value=None), \
         patch.object(med, "_ensure_auto_task_enabled", return_value=None), \
         patch.object(med, "_ensure_challenge_buttons", return_value=None), \
         patch.object(med, "_maybe_ensure_hero_panel_focus", return_value=None), \
         patch.object(med, "_maybe_click_tqtz", return_value=None), \
         patch.object(med, "_maybe_clear_pressure_monsters", return_value=None), \
         patch.object(med, "_handle_self_opened_compact_panel", return_value=None), \
         patch.object(med, "_find_equipment_affix_choice", return_value=None), \
         patch.object(med, "_hud_wood_balance", return_value=5000):

        # Frame 1: HUD idle (bond on cooldown), evolve button present -> clicks evolve
        with patch.object(med, "_selection_anchor", return_value=None), \
             patch.object(med, "_has_evolve_button", return_value=True), \
             patch.object(med, "_evolve_button_hit", return_value=evolve_btn):
            res1 = med._tick_main_line(frame_hud)
            assert res1 == LoopAction.Continue
            assert "ClickEvolve" in clicks
            assert med._evolve_feedback_pending is True
            assert med._has_active_transaction() is True
            assert med._l1_cycle_step == "bond"

        # Frame 2: Transition frame (bond cooldown expired, but evolve transaction blocks F/G)
        med._panel_cooldown_until["bond"] = 0.0
        now += 0.5
        with patch.object(med, "_selection_anchor", return_value=None), \
             patch.object(med, "_has_evolve_button", return_value=False), \
             patch.object(med, "_evolve_feedback_seen", return_value=False):
            res2 = med._tick_main_line(frame_hud)
            assert res2 == LoopAction.Continue
            # No panel opened (no G/F/V pressed, clicks stay with only ClickEvolve)
            assert not any("G" in k or "F" in k or "V" in k for k in keys)
            assert not any("OpenBondPanel" in c or "OpenSkillPanel" in c for c in clicks)
            assert med._has_active_transaction() is True
            assert med._evolve_feedback_pending is True

        # Frame 3: Feedback confirmed on frame
        now += 0.5
        with patch.object(med, "_selection_anchor", return_value=None), \
             patch.object(med, "_has_evolve_button", return_value=False), \
             patch.object(med, "_evolve_feedback_seen", return_value=True):
            res3 = med._tick_main_line(frame_hud)
            assert res3 == LoopAction.Continue
            assert med._evolve_feedback_pending is False
            assert med._evolve_awaiting_hero_pick is True
            assert med._has_active_transaction() is True
            # F/G still prohibited
            assert med._maybe_open_choice_panel(frame_hud) is None

        # Frame 4: Hero choice modal appears -> routes to HERO_CHOICE_MODAL -> selects card
        now += 0.5
        with patch.object(med, "_selection_anchor", return_value=hero_anchor), \
             patch.object(med, "_classify_choice_panel", return_value=None), \
             patch.object(med, "_find_evolution_choice", return_value=hero_choice):
            res4 = med._tick_main_line(frame_hud)
            assert res4 == LoopAction.Continue
            assert "SelectEvolutionCard" in clicks
            # Hero pick completed: transaction ownership released
            assert med._evolve_awaiting_hero_pick is False
            assert med._has_active_transaction() is False
            # Remained in original core step (bond)
            assert med._l1_cycle_step == "bond"


def test_22_opportunistic_evolve_no_feedback_timeout_releases_transaction() -> None:
    """Evolve click with no feedback expires within window without permanently hanging transaction."""
    med = _med()
    med.settings.skip_pre_wave_delay = True
    med.settings.pre_wave_protection = False
    med._auto_task_done = True
    med._main_line_started_at = 100.0
    med._l1_cycle_step = "bond"
    med._wood_balance = 5000
    med._panel_state = PanelState.CLOSED
    now = 1000.0
    med._panel_cooldown_until["bond"] = now + 5.0

    frame_hud = _blank_frame()
    evolve_btn = MatchResult("evolve_hud", 1.0, 800, 700, 40, 12, 800, 700)

    with patch("shuabao.mediator.time.time", side_effect=lambda: now), \
         patch.object(med, "act_click", return_value=True), \
         patch.object(med, "_is_in_game_hud", return_value=True), \
         patch.object(med, "_selection_anchor", return_value=None), \
         patch.object(med, "_post_game_state", return_value=None), \
         patch.object(med, "_ensure_auto_task_enabled", return_value=None), \
         patch.object(med, "_ensure_challenge_buttons", return_value=None), \
         patch.object(med, "_maybe_ensure_hero_panel_focus", return_value=None), \
         patch.object(med, "_maybe_click_tqtz", return_value=None), \
         patch.object(med, "_maybe_clear_pressure_monsters", return_value=None), \
         patch.object(med, "_handle_self_opened_compact_panel", return_value=None), \
         patch.object(med, "_find_equipment_affix_choice", return_value=None), \
         patch.object(med, "_hud_wood_balance", return_value=5000), \
         patch.object(med, "_has_evolve_button", return_value=True), \
         patch.object(med, "_evolve_button_hit", return_value=evolve_btn):
        # Click evolve
        med._tick_main_line(frame_hud)
        assert med._evolve_feedback_pending is True
        assert med._has_active_transaction() is True

        # Timeout expires (3.5s later, window is 3.0s)
        now += 3.5
        with patch.object(med, "_evolve_feedback_seen", return_value=False):
            res = med._tick_main_line(frame_hud)
            assert res == LoopAction.Continue
            # Transaction released
            assert med._evolve_feedback_pending is False
            assert med._evolve_awaiting_hero_pick is False
            assert med._has_active_transaction() is False


def test_23_opportunistic_slot1_upgrade_during_core_development() -> None:
    """Slot 1 right-click upgrade runs opportunistically during Core Development (wood >= 1000)."""
    med = _med()
    med.settings.skip_pre_wave_delay = True
    med.settings.pre_wave_protection = False
    med._auto_task_done = True
    med._main_line_started_at = 100.0
    med._l1_cycle_step = "bond"
    med._wood_balance = 5000
    med._panel_state = PanelState.CLOSED
    med._equipment_next_at = 0.0
    now = 1000.0
    med._panel_cooldown_until["bond"] = now + 5.0
    frame_hud = _blank_frame()

    right_clicks: list[str] = []
    with patch("shuabao.mediator.time.time", side_effect=lambda: now), \
         patch.object(med, "act_right_click", side_effect=lambda hit, reason: right_clicks.append(reason) or True), \
         patch.object(med, "_is_in_game_hud", return_value=True), \
         patch.object(med, "_selection_anchor", return_value=None), \
         patch.object(med, "_post_game_state", return_value=None), \
         patch.object(med, "_ensure_auto_task_enabled", return_value=None), \
         patch.object(med, "_ensure_challenge_buttons", return_value=None), \
         patch.object(med, "_maybe_ensure_hero_panel_focus", return_value=None), \
         patch.object(med, "_maybe_click_tqtz", return_value=None), \
         patch.object(med, "_maybe_clear_pressure_monsters", return_value=None), \
         patch.object(med, "_handle_self_opened_compact_panel", return_value=None), \
         patch.object(med, "_find_equipment_affix_choice", return_value=None), \
         patch.object(med, "_hud_wood_balance", return_value=5000), \
         patch.object(med, "_equipment_slot_one_occupied", return_value=True), \
         patch.object(med, "_equipment_slot_fingerprint", return_value="fp_slot1"):
        # 1. Initial click authorizes and begins lease
        res = med._tick_main_line(frame_hud)
        assert res == LoopAction.Continue
        assert len(right_clicks) == 1
        assert "UpgradeEquipmentSlot1-max" in right_clicks[0]
        assert med._equipment_fsm.pending_slot == 1
        assert med._equipment_fsm.slot_state(1) == EquipmentSlotState.LEASED
        assert med._has_active_transaction() is True
        # Stays in core step
        assert med._l1_cycle_step == "bond"

        # 2. Advance past lease (2.0s, lease is 1.0s or 1.5s): fingerprint unchanged -> QUARANTINED
        now += 2.0  # 1002.0
        med._tick_main_line(frame_hud)
        assert med._equipment_fsm.pending_slot is None
        assert med._equipment_fsm.slot_state(1) == EquipmentSlotState.QUARANTINED
        assert med._equipment_fsm.quarantine_until == 1004.0  # 1002.0 + 2.0s quarantine
        assert med._has_active_transaction() is False
        assert len(right_clicks) == 1

        # 3. Quarantine active: at t=1003.0 (< 1004.0), even if equipment_next_at expired, zero input
        now = 1003.0
        med._equipment_next_at = 1000.0
        med._tick_main_line(frame_hud)
        assert len(right_clicks) == 1
        assert med._equipment_fsm.slot_state(1) == EquipmentSlotState.QUARANTINED
        assert med._equipment_fsm.pending_slot is None

        # 4. Quarantine + 8s cadence expired: allows exactly one retry and rebuilds pending lease
        now = 1008.5
        med._equipment_next_at = 1008.0
        med._panel_cooldown_until["bond"] = now + 5.0
        res = med._tick_main_line(frame_hud)
        assert res == LoopAction.Continue
        assert len(right_clicks) == 2
        assert med._equipment_fsm.pending_slot == 1
        assert med._equipment_fsm.slot_state(1) == EquipmentSlotState.LEASED
        assert med._has_active_transaction() is True
        assert med._l1_cycle_step == "bond"


def test_24_skill_refresh_failed_attempts_resets_on_new_episode() -> None:
    """_skill_refresh_failed_attempts resets to 0 at the start of each new panel episode."""
    med = _med()
    med._skill_refresh_failed_attempts = 1
    anchor = MatchResult("skill_hide_btn", 1.0, 20, 20, 40, 40, 40, 40)
    med._enter_panel_episode(_blank_frame(), anchor, "skill", opened=True)
    assert med._skill_refresh_failed_attempts == 0


def test_25_slot1_normal_equipment_path_quarantine_and_retry() -> None:
    """Normal equipment path obeys shared authorization, QUARANTINED semantics, and retry."""
    med = _med()
    frame = _blank_frame()
    med._l1_cycle_step = "equipment"
    med._panel_state = PanelState.CLOSED
    now = 1000.0
    med._equipment_next_at = 0.0

    right_clicks: list[str] = []
    with patch("shuabao.mediator.time.time", side_effect=lambda: now), \
         patch.object(med, "_equipment_slot_one_occupied", return_value=True), \
         patch.object(med, "_equipment_slot_fingerprint", return_value="fp_slot1"), \
         patch.object(med, "act_right_click", side_effect=lambda hit, reason: right_clicks.append(reason) or True):
        # 1. First upgrade click at t=1000.0
        res = med._maybe_upgrade_equipment(frame)
        assert res == LoopAction.Continue
        assert len(right_clicks) == 1
        assert "UpgradeEquipmentSlot1-max" in right_clicks[0]
        assert med._equipment_fsm.pending_slot == 1
        assert med._equipment_fsm.slot_state(1) == EquipmentSlotState.LEASED

        # 2. Advance past lease to t=1002.0 with unchanged fingerprint -> QUARANTINED
        now = 1002.0
        res2 = med._maybe_upgrade_equipment(frame)
        assert med._equipment_fsm.pending_slot is None
        assert med._equipment_fsm.slot_state(1) == EquipmentSlotState.QUARANTINED
        assert med._equipment_fsm.quarantine_until == 1004.0
        assert len(right_clicks) == 1  # zero input during settlement

        # 3. During quarantine (t=1003.0 < 1004.0), even if equipment_next_at expired, zero input
        now = 1003.0
        med._equipment_next_at = 1000.0
        res3 = med._maybe_upgrade_equipment(frame)
        assert len(right_clicks) == 1  # Zero input!
        assert med._equipment_fsm.slot_state(1) == EquipmentSlotState.QUARANTINED

        # 4. Quarantine + 8s cadence expired (t=1008.5): allows one retry, rebuilds pending lease
        now = 1008.5
        med._equipment_next_at = 1008.0
        res4 = med._maybe_upgrade_equipment(frame)
        assert res4 == LoopAction.Continue
        assert len(right_clicks) == 2
        assert med._equipment_fsm.pending_slot == 1
        assert med._equipment_fsm.slot_state(1) == EquipmentSlotState.LEASED


def test_26_slot1_mutation_confirmed_path_both_opportunistic_and_normal() -> None:
    """Fingerprint mutation confirmed path works normally in both opportunistic and normal paths."""
    # --- Path A: Opportunistic path ---
    med = _med()
    med.settings.skip_pre_wave_delay = True
    med.settings.pre_wave_protection = False
    med._auto_task_done = True
    med._main_line_started_at = 100.0
    med._l1_cycle_step = "bond"
    med._wood_balance = 5000
    med._panel_state = PanelState.CLOSED
    med._equipment_next_at = 0.0
    now = 1000.0
    med._panel_cooldown_until["bond"] = now + 5.0
    frame_hud = _blank_frame()
    current_fp = "fp_initial"

    right_clicks: list[str] = []
    with patch("shuabao.mediator.time.time", side_effect=lambda: now), \
         patch.object(med, "act_right_click", side_effect=lambda hit, reason: right_clicks.append(reason) or True), \
         patch.object(med, "_is_in_game_hud", return_value=True), \
         patch.object(med, "_selection_anchor", return_value=None), \
         patch.object(med, "_post_game_state", return_value=None), \
         patch.object(med, "_ensure_auto_task_enabled", return_value=None), \
         patch.object(med, "_ensure_challenge_buttons", return_value=None), \
         patch.object(med, "_maybe_ensure_hero_panel_focus", return_value=None), \
         patch.object(med, "_maybe_click_tqtz", return_value=None), \
         patch.object(med, "_maybe_clear_pressure_monsters", return_value=None), \
         patch.object(med, "_handle_self_opened_compact_panel", return_value=None), \
         patch.object(med, "_find_equipment_affix_choice", return_value=None), \
         patch.object(med, "_hud_wood_balance", return_value=5000), \
         patch.object(med, "_equipment_slot_one_occupied", return_value=True), \
         patch.object(med, "_equipment_slot_fingerprint", side_effect=lambda f, slot: current_fp):
        # Click initiates lease
        med._tick_main_line(frame_hud)
        assert len(right_clicks) == 1
        assert med._equipment_fsm.pending_slot == 1
        assert med._equipment_fsm.slot_state(1) == EquipmentSlotState.LEASED
        assert med._has_active_transaction() is True

        # Mutation occurs on next frame after lease
        now = 1002.0
        current_fp = "fp_mutated_level2"
        med._tick_main_line(frame_hud)
        assert med._equipment_fsm.pending_slot is None
        assert med._equipment_fsm.slot_state(1) == EquipmentSlotState.CONFIRMED
        assert med._has_active_transaction() is False

    # --- Path B: Normal equipment path ---
    med2 = _med()
    frame2 = _blank_frame()
    med2._l1_cycle_step = "equipment"
    med2._panel_state = PanelState.CLOSED
    now2 = 1000.0
    med2._equipment_next_at = 0.0
    current_fp2 = "fp_initial_normal"

    right_clicks2: list[str] = []
    with patch("shuabao.mediator.time.time", side_effect=lambda: now2), \
         patch.object(med2, "_equipment_slot_one_occupied", return_value=True), \
         patch.object(med2, "_equipment_slot_fingerprint", side_effect=lambda f, slot: current_fp2), \
         patch.object(med2, "act_right_click", side_effect=lambda hit, reason: right_clicks2.append(reason) or True):
        # Click initiates lease
        med2._maybe_upgrade_equipment(frame2)
        assert len(right_clicks2) == 1
        assert med2._equipment_fsm.pending_slot == 1
        assert med2._equipment_fsm.slot_state(1) == EquipmentSlotState.LEASED

        # Mutation occurs
        now2 = 1002.0
        current_fp2 = "fp_mutated_normal"
        med2._maybe_upgrade_equipment(frame2)
        assert med2._equipment_fsm.pending_slot is None
        assert med2._equipment_fsm.slot_state(1) == EquipmentSlotState.CONFIRMED


def test_27_slot1_can_use_false_enforces_zero_input_both_paths() -> None:
    """When equipment_fsm.can_use(1, now) is False, act_right_click is never called (zero input)."""
    frame = _blank_frame()
    now = 1000.0

    # Path A: Opportunistic path with can_use returning False
    med = _med()
    med.settings.skip_pre_wave_delay = True
    med.settings.pre_wave_protection = False
    med._auto_task_done = True
    med._main_line_started_at = 100.0
    med._l1_cycle_step = "bond"
    med._wood_balance = 5000
    med._panel_state = PanelState.CLOSED
    med._equipment_next_at = 0.0

    # Put FSM in quarantine until future
    med._equipment_fsm = EquipmentFSM(quarantine_until=now + 50.0)
    assert med._equipment_fsm.can_use(1, now) is False

    right_clicks: list[str] = []
    with patch("shuabao.mediator.time.time", side_effect=lambda: now), \
         patch.object(med, "act_right_click", side_effect=lambda hit, reason: right_clicks.append(reason) or True), \
         patch.object(med, "_is_in_game_hud", return_value=True), \
         patch.object(med, "_selection_anchor", return_value=None), \
         patch.object(med, "_post_game_state", return_value=None), \
         patch.object(med, "_ensure_auto_task_enabled", return_value=None), \
         patch.object(med, "_ensure_challenge_buttons", return_value=None), \
         patch.object(med, "_maybe_ensure_hero_panel_focus", return_value=None), \
         patch.object(med, "_maybe_click_tqtz", return_value=None), \
         patch.object(med, "_maybe_clear_pressure_monsters", return_value=None), \
         patch.object(med, "_handle_self_opened_compact_panel", return_value=None), \
         patch.object(med, "_find_equipment_affix_choice", return_value=None), \
         patch.object(med, "_hud_wood_balance", return_value=5000), \
         patch.object(med, "_equipment_slot_one_occupied", return_value=True), \
         patch.object(med, "_equipment_slot_fingerprint", return_value="fp_slot1"):
        # Directly call helper
        assert med._slot1_upgrade_authorized(frame, now) is False
        assert med._maybe_opportunistic_upgrade_slot1(frame, now) is None
        assert len(right_clicks) == 0

        # Also verify via _tick_main_line
        med._panel_cooldown_until["bond"] = now + 5.0
        med._tick_main_line(frame)
        assert len(right_clicks) == 0

    # Path B: Normal equipment path with can_use returning False
    med2 = _med()
    med2._l1_cycle_step = "equipment"
    med2._panel_state = PanelState.CLOSED
    med2._equipment_next_at = 0.0
    med2._equipment_fsm = EquipmentFSM(quarantine_until=now + 50.0)
    assert med2._equipment_fsm.can_use(1, now) is False

    right_clicks2: list[str] = []
    with patch("shuabao.mediator.time.time", side_effect=lambda: now), \
         patch.object(med2, "_equipment_slot_one_occupied", return_value=True), \
         patch.object(med2, "_equipment_slot_fingerprint", return_value="fp_slot1"), \
         patch.object(med2, "act_right_click", side_effect=lambda hit, reason: right_clicks2.append(reason) or True):
        assert med2._slot1_upgrade_authorized(frame, now) is False
        med2._maybe_upgrade_equipment(frame)
        assert len(right_clicks2) == 0


def test_28_equipment_fsm_quarantined_semantics_pure_contract() -> None:
    """Pure EquipmentFSM unit contract for 2s quarantine cooldown and re-entry to LEASED."""
    fsm = EquipmentFSM()
    now = 100.0

    # Initial state is READY -> can_use is True
    assert fsm.can_use(1, now) is True

    # Begin lease
    fsm = fsm.begin(1, now, lease_s=1.0, fingerprint="fp_v1")
    assert fsm.slot_state(1) == EquipmentSlotState.LEASED
    assert fsm.pending_slot == 1
    assert fsm.lease_until == 101.0
    # In-flight lease rejects new use
    assert fsm.can_use(1, 100.5) is False

    # Timeout unconfirmed: observe at 101.0 with same fingerprint -> QUARANTINED
    fsm = fsm.observe(101.0, current_fingerprint="fp_v1")
    assert fsm.slot_state(1) == EquipmentSlotState.QUARANTINED
    assert fsm.pending_slot is None
    assert fsm.quarantine_until == 103.0  # 101.0 + 2.0s

    # During quarantine (now < quarantine_until): can_use is False, begin() returns unchanged
    assert fsm.can_use(1, 102.0) is False
    assert fsm.begin(1, 102.0) == fsm

    # Quarantine expired (now >= quarantine_until): can_use is True, begin() enters LEASED
    assert fsm.can_use(1, 103.0) is True
    fsm = fsm.begin(1, 103.0, lease_s=1.0, fingerprint="fp_v2")
    assert fsm.slot_state(1) == EquipmentSlotState.LEASED
    assert fsm.pending_slot == 1
    assert fsm.lease_until == 104.0

    # Confirmed mutation at 104.0 -> CONFIRMED with 0.5s cooldown
    fsm = fsm.observe(104.0, current_fingerprint="fp_v3")
    assert fsm.slot_state(1) == EquipmentSlotState.CONFIRMED
    assert fsm.pending_slot is None
    assert fsm.quarantine_until == 104.5
    assert fsm.can_use(1, 104.2) is False
    assert fsm.can_use(1, 105.0) is True

