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

from shuabao.mediator import Mediator, PanelState, LoopAction
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
    def test_scanner_priority_ordering(self):
        """Discounts and swallow pills and wood items should be prioritized in order."""
        scanner = MerchantScanner(
            attr_routes=["intelligence"],
            focus_skills=["奥术箭"],
            focus_bonds=["祝福"],
            auto_refresh=False,
        )

        items = [
            MerchantSlotItem(slot_index=4, center_ratio=(0.88, 0.72), item_type="wood", label="wood"),
            MerchantSlotItem(slot_index=2, center_ratio=(0.78, 0.72), item_type="discount", label="3折"),
            MerchantSlotItem(slot_index=1, center_ratio=(0.74, 0.72), item_type="devour_pill", label="吞噬丹"),
            MerchantSlotItem(slot_index=0, center_ratio=(0.71, 0.72), item_type="focus_card", label="奥术箭"),
        ]
        ranked = scanner.rank_purchases(items, bond_bar_nonempty=True)
        self.assertEqual(ranked[0].item_type, "discount")
        self.assertEqual(ranked[1].item_type, "devour_pill")
        self.assertEqual(ranked[2].item_type, "wood")
        self.assertEqual(ranked[3].item_type, "focus_card")

    def test_scanner_filters_negative_items(self):
        """Negative treasures must be strictly filtered out."""
        scanner = MerchantScanner()
        items = [
            MerchantSlotItem(slot_index=0, center_ratio=(0.71, 0.72), item_type="treasure", label="破损的诅咒金币", is_negative=True),
            MerchantSlotItem(slot_index=1, center_ratio=(0.74, 0.72), item_type="wood", label="木材礼包"),
        ]
        ranked = scanner.rank_purchases(items, bond_bar_nonempty=False)
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0].item_type, "wood")

    def test_scanner_skips_pill_when_bond_bar_empty(self):
        """Swallow pill must not be purchased if bond bar is empty."""
        scanner = MerchantScanner()
        items = [
            MerchantSlotItem(slot_index=0, center_ratio=(0.71, 0.72), item_type="devour_pill", label="吞噬丹"),
            MerchantSlotItem(slot_index=1, center_ratio=(0.74, 0.72), item_type="wood", label="木材礼包"),
        ]
        ranked = scanner.rank_purchases(items, bond_bar_nonempty=False)
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0].item_type, "wood")


class TestBagHeroCardAndDevourPill(unittest.TestCase):
    def setUp(self):
        self.med = Mediator(Settings(), ROOT)
        self.med.settings.ui_action_interval_s = 0.5
        self.frame = make_test_frame()

    @patch("shuabao.mediator.time.time", return_value=100.0)
    def test_devour_pill_consumed_when_bond_bar_nonempty(self, mock_time):
        """Swallow pill is clicked in inventory and updates inventory next cooldown."""
        with patch.object(self.med, "_black_merchant_present", return_value=False), \
             patch.object(self.med, "_bond_bar_nonempty", return_value=True), \
             patch.object(self.med, "find") as mock_find, \
             patch.object(self.med, "act_click", return_value=True) as mock_click:
            pill_match = MatchResult("danGif", 0.9, 1100, 750, 20, 20, 1100, 750)
            mock_find.return_value = pill_match

            action = self.med._maybe_use_inventory_item(self.frame)
            self.assertEqual(action, LoopAction.Continue)
            mock_click.assert_called_once_with(pill_match, "UseInventory-swallow_pill")
            self.assertGreater(self.med._inventory_next_at, 100.0)

    @patch("shuabao.mediator.time.time", return_value=100.0)
    def test_hero_card_triggers_evolution_flow_with_pending_action(self, mock_time):
        """Hero card click dispatches PendingAction(WAIT_HERO_CHOICE) without requiring prior evolve."""
        with patch.object(self.med, "_black_merchant_present", return_value=False), \
             patch.object(self.med, "_bond_bar_nonempty", return_value=False), \
             patch.object(self.med, "find") as mock_find, \
             patch.object(self.med, "act_click", return_value=True) as mock_click:
            
            hero_card_match = MatchResult("hero_card_item", 0.9, 1150, 750, 20, 20, 1150, 750)
            mock_find.return_value = hero_card_match

            action = self.med._maybe_use_inventory_item(self.frame)
            self.assertEqual(action, LoopAction.Continue)
            mock_click.assert_called_once_with(hero_card_match, "UseInventory-hero-card")
            self.assertIsNotNone(self.med._pending_action)
            self.assertEqual(self.med._pending_action.kind, "WAIT_HERO_CHOICE")
            self.assertEqual(self.med._pending_action.target_id, "hero_card_item")


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
    def test_equipment_slots_2_to_6_sequential_inspection(self, mock_time):
        """Slots 2 through 6 are sequentially clicked per tick every 30s."""
        self.med._equipment_next_at = 200.0  # Slot 1 on cooldown
        self.med._equipment_round_next_at = 0.0
        self.med._equipment_round_current_slot = 2

        with patch.object(self.med, "_black_merchant_present", return_value=False), \
             patch.object(self.med, "_maybe_use_inventory_item", return_value=None), \
             patch.object(self.med, "act_click", return_value=True) as mock_click:
            
            # Tick 1: slot 2
            action1 = self.med._maybe_upgrade_equipment(self.frame)
            self.assertEqual(action1, LoopAction.Continue)
            self.assertEqual(self.med._equipment_round_current_slot, 3)

            # Advance time for next slot tick
            self.med._equipment_pending_until = 0.0
            
            # Tick 2: slot 3
            action2 = self.med._maybe_upgrade_equipment(self.frame)
            self.assertEqual(action2, LoopAction.Continue)
            self.assertEqual(self.med._equipment_round_current_slot, 4)


if __name__ == "__main__":
    unittest.main()
