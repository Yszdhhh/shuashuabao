"""PR-3: Unit and contract tests for Merchant, Bag, and Equipment actions.

Verifies:
1. Merchant 5-slot priority purchasing (skills/bonds, discount, pill, wood, attr route, negative treasure exclusion).
2. Bag devour pill & hero card flow (pill consumption with cooldown, hero card trigger with PendingAction, no infinite loop).
3. Equipment slot 1-6 periodic inspection & upgrades (slot 1 right-click max, slot 2-6 sequential 30s cycle, surface gate).
"""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.mediator import Mediator, PanelState, LoopAction, Phase
from shuabao.merchant_scanner import MerchantScanner, MerchantSlotItem
from shuabao.interaction_surface import InteractionSurface, PendingAction
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult
from shuabao.settings import Settings

def make_test_frame(width: int = 1600, height: int = 900) -> Frame:
    bgr = np.zeros((height, width, 3), dtype=np.uint8)
    return Frame(
        bgr=bgr,
        timestamp=100.0,
        left=0,
        top=0,
    )

class TestMerchantScanner(unittest.TestCase):
    def test_scanner_keeps_hitch_to_swallow_pills(self):
        """蹭车策略只能授权吞噬丹。"""
        scanner = MerchantScanner(
            attr_routes=["intelligence"],
            focus_skills=["奥术箭"],
            focus_bonds=["祝福"],
            auto_refresh=False,
        )

        items = [
            MerchantSlotItem(slot_index=3, center_ratio=(0.88, 0.72), item_type="wood", label="wood"),
            MerchantSlotItem(slot_index=2, center_ratio=(0.78, 0.72), item_type="discount", label="2折"),
            MerchantSlotItem(slot_index=1, center_ratio=(0.74, 0.72), item_type="devour_pill", label="吞噬丹"),
        ]
        ranked = scanner.rank_purchases(items, bond_bar_nonempty=True)
        self.assertEqual([item.item_type for item in ranked], ["devour_pill"])

    def test_scanner_restores_solo_wood_and_verified_discounts(self):
        scanner = MerchantScanner()
        items = [
            MerchantSlotItem(slot_index=3, center_ratio=(0.88, 0.72), item_type="discount", label="5折"),
            MerchantSlotItem(slot_index=2, center_ratio=(0.78, 0.72), item_type="wood", label="merchant_wood"),
            MerchantSlotItem(slot_index=1, center_ratio=(0.74, 0.72), item_type="devour_pill", label="吞噬丹"),
        ]
        ranked = scanner.rank_purchases(items, bond_bar_nonempty=True, solo=True)
        self.assertEqual([item.item_type for item in ranked], ["devour_pill", "wood", "discount"])

    def test_scanner_filters_negative_items(self):
        """Negative treasures must be strictly filtered out."""
        scanner = MerchantScanner()
        items = [
            MerchantSlotItem(slot_index=0, center_ratio=(0.71, 0.72), item_type="treasure", label="破损的诅咒金币", is_negative=True),
            MerchantSlotItem(slot_index=1, center_ratio=(0.74, 0.72), item_type="wood", label="木材礼包"),
        ]
        ranked = scanner.rank_purchases(items, bond_bar_nonempty=False)
        self.assertEqual(ranked, [])

    def test_scanner_skips_pill_when_bond_bar_empty(self):
        """Swallow pill must not be purchased if bond bar is empty."""
        scanner = MerchantScanner()
        items = [
            MerchantSlotItem(slot_index=0, center_ratio=(0.71, 0.72), item_type="devour_pill", label="吞噬丹"),
            MerchantSlotItem(slot_index=1, center_ratio=(0.74, 0.72), item_type="wood", label="木材礼包"),
        ]
        ranked = scanner.rank_purchases(items, bond_bar_nonempty=False)
        self.assertEqual(ranked, [])


class TestBagHeroCardAndDevourPill(unittest.TestCase):
    def setUp(self):
        self.med = Mediator(Settings(), ROOT)
        self.med.settings.ui_action_interval_s = 0.5
        self.med._merchant_kill_balance = lambda _frame: 10_000
        self.frame = make_test_frame()

    @patch("shuabao.mediator.time.time", return_value=100.0)
    def test_devour_pill_fail_closed_with_saved_opt_in_and_visible_pill(self, mock_time):
        # Owner 2026-09-24: solo eats pills from 6/10; Owner 2026-09-25: from 8/10; below that the gate stays closed.
        self.med.settings = Settings(auto_devour_dan=True)
        pill_match = MatchResult("danGif", 0.9, 1100, 750, 20, 20, 1100, 750)
        for occupancy in (4, 5, 6, 7):
            with self.subTest(occupancy=occupancy), \
                 patch.object(self.med, "_bond_bar_occupancy", return_value=occupancy), \
                 patch.object(self.med, "find", return_value=pill_match), \
                 patch.object(self.med, "act_click", return_value=True) as mock_click:
                self.assertFalse(self.med._can_consume_inventory_swallow_pill(self.frame))
                self.assertIsNone(self.med._maybe_use_inventory_item(self.frame))
                mock_click.assert_not_called()
                self.assertIsNone(self.med._pending_action)

    def test_devour_pill_waits_at_three_bonds(self):
        with patch.object(self.med, "_bond_bar_occupancy", return_value=3), \
             patch.object(self.med, "_maybe_opportunistic_yinyue_crystal", return_value=None), \
             patch.object(self.med, "_maybe_use_inventory_slot", return_value=None), \
             patch.object(self.med, "find") as mock_find, \
             patch.object(self.med, "act_click") as mock_click:
            self.assertIsNone(self.med._maybe_use_inventory_item(self.frame))
        mock_find.assert_not_called()
        mock_click.assert_not_called()

    def test_devour_pill_gate_stays_closed_at_four_and_five_bonds(self):
        # Owner 2026-09-24: the gate opened at 6/10; Owner 2026-09-25: opens at 8/10 (test_p0_devour_failclosed_20260917).
        self.med.settings = Settings(auto_devour_dan=True)
        for occupancy in (4, 5, 6, 7):
            with self.subTest(occupancy=occupancy), \
                 patch.object(self.med, "_bond_bar_occupancy", return_value=occupancy):
                self.assertFalse(self.med._can_consume_inventory_swallow_pill(self.frame))

    @patch("shuabao.mediator.time.time", return_value=100.0)
    def test_hero_card_triggers_evolution_flow_with_pending_action(self, mock_time):
        """Hero card click dispatches PendingAction(WAIT_HERO_CHOICE) after evolve 三选一."""
        self.med._evolve_ok_this_cycle = True
        with patch.object(self.med, "_black_merchant_present", return_value=False), \
             patch.object(self.med, "_bond_bar_nonempty", return_value=False), \
             patch.object(self.med, "find") as mock_find, \
             patch.object(self.med, "act_click", return_value=True) as mock_click:
            
            hero_card_match = MatchResult("hero_card_item", 0.9, 1150, 750, 20, 20, 1150, 750)
            mock_find.return_value = hero_card_match

            action = self.med._maybe_use_inventory_item(self.frame)
            self.assertEqual(action, LoopAction.Continue)
            mock_click.assert_called_once_with(hero_card_match, "UseInventory-hero-card")
            self.assertEqual(mock_find.call_args.kwargs["threshold"], 0.65)
            self.assertIsNotNone(self.med._pending_action)
            self.assertEqual(self.med._pending_action.kind, "WAIT_HERO_CHOICE")
            self.assertEqual(self.med._pending_action.target_id, "hero_card_item")


    @patch("shuabao.mediator.time.time", return_value=100.0)
    def test_hero_card_writes_back_inventory_last_pt_for_sticky_protection(self, mock_time):
        """B5 invariant: _maybe_use_hero_card writes back self._inventory_last_pt = pt on first match."""
        self.med._evolve_ok_this_cycle = True
        with patch.object(self.med, "_black_merchant_present", return_value=False), \
             patch.object(self.med, "_bond_bar_nonempty", return_value=False), \
             patch.object(self.med, "find") as mock_find, \
             patch.object(self.med, "act_click", return_value=True):
            
            hero_card_match = MatchResult("hero_card_item", 0.9, 1150, 750, 20, 20, 1150, 750)
            mock_find.return_value = hero_card_match

            self.assertIsNone(self.med._inventory_last_pt)
            action = self.med._maybe_use_inventory_item(self.frame)
            self.assertEqual(action, LoopAction.Continue)
            self.assertEqual(self.med._inventory_last_pt, (1150, 750))
            self.assertEqual(self.med._inventory_same_pt_hits, 1)


    @patch("shuabao.mediator.time.time", return_value=100.0)
    def test_devour_pill_fail_closed_below_episode_limit_and_after_cycle_reset(self, mock_time):
        # P0-2 supersedes mock-open episode clicks: no reliable per-slot identity.
        self.med.settings = Settings(auto_devour_dan=True)
        with patch.object(self.med, "_bond_bar_occupancy", return_value=4), \
             patch.object(self.med, "find") as mock_find, \
             patch.object(self.med, "act_click", return_value=True) as mock_click:
            pill_match = MatchResult("danGif", 0.9, 1100, 750, 20, 20, 1100, 750)
            mock_find.return_value = pill_match
            for consecutive_clicks in (5, 4):
                with self.subTest(consecutive_clicks=consecutive_clicks):
                    self.med._devour_dan_consecutive_clicks = consecutive_clicks
                    self.assertFalse(self.med._can_consume_inventory_swallow_pill(self.frame))
                    self.assertIsNone(self.med._maybe_use_inventory_item(self.frame))
                    mock_click.assert_not_called()
                    self.assertIsNone(self.med._pending_action)

            # Independent cycle reset remains valid; it does not grant click authority.
            self.med._advance_l1_cycle("evolve")
            self.assertEqual(self.med._devour_dan_consecutive_clicks, 0)
            self.assertIsNone(self.med._maybe_use_inventory_item(self.frame))
            mock_click.assert_not_called()
            self.assertIsNone(self.med._pending_action)

    @patch("shuabao.mediator.time.time", return_value=100.0)
    def test_merchant_refreshes_when_kill_count_allows(self, mock_time):
        self.med.settings.auto_gambling_time = 10
        self.med.settings.auto_gambling = False
        with patch.object(self.med, "_black_merchant_present", return_value=True), \
             patch.object(self.med, "_bond_bar_nonempty", return_value=False), \
             patch.object(self.med, "find", return_value=None), \
             patch.object(self.med, "_merchant_refresh_available", return_value=True), \
             patch.object(self.med, "act_click", return_value=True) as mock_click:
            self.assertEqual(self.med._maybe_black_merchant(self.frame), LoopAction.Continue)
            action = self.med._maybe_black_merchant(self.frame)
            self.assertEqual(action, LoopAction.Continue)
            self.assertEqual(mock_click.call_args.args[1], "BlackMerchant-refresh")
class TestEquipmentPeriodicInspection(unittest.TestCase):
    def setUp(self):
        self.med = Mediator(Settings(), ROOT)
        self.med.settings.ui_action_interval_s = 0.5
        self.frame = make_test_frame()

    @patch("shuabao.mediator.time.time", return_value=100.0)
    def test_equipment_slot_1_max_upgrade(self, mock_time):
        """Slot 1 performs right click max upgrade with 8s cooldown."""
        with patch.object(self.med, "_black_merchant_present", return_value=False), \
             patch.object(self.med, "_maybe_use_inventory_item", return_value=None), \
             patch.object(self.med, "_equipment_slot_one_occupied", return_value=True), \
             patch.object(self.med, "act_right_click", return_value=True) as mock_rclick:
            
            self.med._equipment_next_at = 0.0
            action = self.med._maybe_upgrade_equipment(self.frame)
            self.assertEqual(action, LoopAction.Continue)
            self.assertEqual(self.med._equipment_next_at, 108.0)
            mock_rclick.assert_called_once()

    @patch("shuabao.mediator.time.time", return_value=100.0)
    def test_equipment_slots_2_to_6_blind_inspection_disabled(self, mock_time):
        """P0-02 invariant: slots 2 through 6 blind inspection is disabled, producing 0 click input."""
        self.med._equipment_next_at = 200.0  # Slot 1 on cooldown
        self.med._equipment_round_next_at = 0.0
        self.med._equipment_round_current_slot = 2

        with patch.object(self.med, "_black_merchant_present", return_value=False), \
             patch.object(self.med, "_maybe_use_inventory_item", return_value=None), \
             patch.object(self.med, "act_click", return_value=True) as mock_click:
            
            action = self.med._maybe_upgrade_equipment(self.frame)
            self.assertEqual(action, LoopAction.Continue)
            mock_click.assert_not_called()


class TestPendingActionAndSurfaceMediatorIntegration(unittest.TestCase):
    def setUp(self):
        self.med = Mediator(Settings(), ROOT)
        self.frame = make_test_frame()

    def test_pending_action_timeout_lifecycle(self):
        """B2 invariant: pending action timeout clears, applies target cooldown, records unconfirmed metric."""
        self.med.phase = Phase.MAIN_LINE
        self.med._pending_action = PendingAction(
            kind="WAIT_HERO_CHOICE",
            target_id="hero_card_item",
            deadline=50.0,
            verifier=lambda f: False,
        )
        with patch("shuabao.mediator.time.time", return_value=60.0):
            # Action is expired at t=60.0 (deadline was 50.0)
            with patch.object(self.med, "_round_deadline", 1000.0), \
                 patch.object(self.med, "_find_failure_gift", return_value=None), \
                 patch.object(self.med, "_find_equipment_affix_choice", return_value=None), \
                 patch.object(self.med, "_selection_anchor", return_value=None), \
                 patch.object(self.med, "_black_merchant_present", return_value=False):
                self.med._tick_main_line(self.frame)

        self.assertIsNone(self.med._pending_action)
    def test_surface_conflict_bounded_budget_escalation(self):
        """B4 invariant: surface conflict zeroes input and escalates to Phase.ERROR after bounded budget."""
        self.med.phase = Phase.MAIN_LINE
        self.med._pending_action = None
        
        # Simulate conflict (both affix modal and center card modal present -> CONFLICT)
        mock_affix = MatchResult(name="affix", score=0.9, x=10, y=10, w=50, h=50, screen_x=35, screen_y=35)
        with patch.object(self.med, "_find_equipment_affix_choice", return_value=mock_affix), \
             patch.object(self.med, "_selection_anchor", return_value=(100, 100)), \
             patch.object(self.med, "_find_evolution_choice", return_value=None), \
             patch.object(self.med, "_black_merchant_present", return_value=False), \
             patch.object(self.med, "_find_failure_gift", return_value=None), \
             patch.object(self.med, "_round_deadline", 1000.0):
            
            # First conflict at t=100.0 -> zero input, continue
            with patch("shuabao.mediator.time.time", return_value=100.0):
                act1 = self.med._tick_main_line(self.frame)
                self.assertEqual(act1, LoopAction.Continue)
                self.assertEqual(self.med.phase, Phase.MAIN_LINE)
                self.assertEqual(self.med._surface_conflict_since, 100.0)
            
            # Still in conflict at t=101.5 (< deadline) -> continue
            with patch("shuabao.mediator.time.time", return_value=101.5):
                act2 = self.med._tick_main_line(self.frame)
                self.assertEqual(act2, LoopAction.Continue)
                self.assertEqual(self.med.phase, Phase.MAIN_LINE)

            # 20260822（二轮实机 trace 203910）：词缀弹窗是游戏强制模态——
            # 冲突 ≥2.5s 且词缀弹窗在场时降级为 EQUIPMENT_AFFIX_MODAL 处理
            # （点击词缀选择，运行继续），不再停机。
            with patch("shuabao.mediator.time.time", return_value=103.0):
                act3 = self.med._tick_main_line(self.frame)
                self.assertEqual(act3, LoopAction.Continue)
                self.assertEqual(self.med.phase, Phase.MAIN_LINE)

            # 纯未知冲突的 ERROR 兜底：仲裁看到词缀（第一次调用命中 → CONFLICT），
            # 但降级复查时词缀已消失（检测闪变，第二次调用 None）→ 无可降级
            # 目标，panel_hard_deadline_s（默认 15s）后 ERROR。
            self.med._surface_conflict_since = 100.0
            self.med._recovery_step = None
            with patch.object(self.med, "_find_equipment_affix_choice", side_effect=[mock_affix, None]),                  patch("shuabao.mediator.time.time", return_value=115.1):
                act4 = self.med._tick_main_line(self.frame)
                self.assertEqual(act4, LoopAction.Break)
                self.assertEqual(self.med.phase, Phase.ERROR)
                self.assertEqual(self.med._interrupt_reason, "interaction surface conflict timeout (15.10s)")

if __name__ == "__main__":
    unittest.main()
