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
13. Fake/old skill_refresh_btn never gains click authority
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


def test_09_burst_cap_with_high_wood_stays_in_core_dev() -> None:
    """9. F burst reaches cap with wood >= 1000 -> strictly F <-> G, no side branches."""
    med = _med()
    med._wood_balance = 3000
    med._l1_cycle_step = "bond"
    med._advance_l1_cycle("bond")
    assert med._l1_cycle_step == "skill"
    med._advance_l1_cycle("skill")
    assert med._l1_cycle_step == "bond"
    # Never enters treasure / evolve / equipment when wood >= 1000
    assert med._l1_cycle_step not in ("treasure", "evolve", "equipment", "pickup", "merchant", "artifact")


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


def test_13_fake_skill_refresh_btn_never_gains_click_authority() -> None:
    """13. Fake/old skill_refresh_btn is excluded from refresh button candidates."""
    med = _med()
    frame = _blank_frame()
    searched: list[str] = []

    def mock_find(_frame, names, *a, **kw):
        searched.extend(names)
        if "skill_refresh_btn" in names:
            return MatchResult("skill_refresh_btn", 0.95, 500, 500, 50, 50, 500, 500)
        return None

    with patch.object(med, "find", side_effect=mock_find):
        res = med._find_panel_refresh(frame, "skill")
    assert res is None
    assert "skill_refresh_btn" not in searched


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
    # Check if frame exists in fixtures or captures
    capture_path = Path(r"C:\Users\10639\AppData\Local\Temp\shuabao-captures\solo_ingame_chain_20260915_232202_461360\frames\f0085_action_after.png")
    if not capture_path.exists():
        pytest.skip("Replay capture frames not present locally")
    bgr = cv2.imread(str(capture_path))
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


def test_21_opportunistic_evolve_fires_during_core_development() -> None:
    """Opportunistic evolve triggers on HUD during core development (wood >= 1000) without advancing cycle."""
    med = _med()
    frame = _blank_frame()
    med._l1_cycle_step = "bond"
    med._wood_balance = 5000
    med._panel_state = PanelState.CLOSED
    now = time.time()

    clicked: list[str] = []
    evolve_btn = MatchResult("evolve_hud", 1.0, 800, 700, 40, 12, 800, 700)
    with patch.object(med, "_has_evolve_button", return_value=True), \
         patch.object(med, "_evolve_button_hit", return_value=evolve_btn), \
         patch.object(med, "act_click", side_effect=lambda hit, reason: clicked.append(reason) or True):
        res = med._maybe_opportunistic_evolve(frame, now)

    assert res == LoopAction.Continue
    assert "ClickEvolve" in clicked
    assert med._evolve_feedback_pending is True
    # Cycle step remains bond (core development not disrupted)
    assert med._l1_cycle_step == "bond"

