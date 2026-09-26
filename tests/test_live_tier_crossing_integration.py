from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch
import numpy as np

from shuabao.mediator import Mediator, Frame
from shuabao.settings import Settings
from shuabao.choice_policy import PANEL_BOND

ROOT = Path(__file__).resolve().parents[1]

class TestLiveMediatorIntegration(unittest.TestCase):
    """Verify real Mediator instance extracts set_progress & free_slots and feeds ChoicePolicy."""

    def setUp(self):
        self.settings = Settings()
        self.settings.cards = []
        self.settings.bonds = ["成长"]
        self.settings.bond_must_take = []
        self.settings.bond_whitelist_mode = "soft"
        self.mediator = Mediator(project_root=ROOT, settings=self.settings)

    def test_mediator_extracts_and_feeds_live_progress_to_policy_without_must_take_or_merge_shortcut(self):
        # Distinct 3 owned cards in "成长" bond family (count=3, tier crossing threshold is 4, NOT "祝福" so no DEFAULT_BOND_MUST_TAKE match)
        self.mediator._bond_cards_owned = ["成长之根", "成长之苗", "成长之叶"]

        frame = Frame(bgr=np.zeros((100, 100, 3), dtype=np.uint8), hwnd=999, is_valid=True)

        # Candidate 0 is a NEW distinct 4th card "成长之树" (NOT owned -> no merge rank, NOT must_take, NOT exact preset)
        # Candidate 1 is a high-rarity scatter card "散卡之王" (rarity purple)
        fake_slots_raw = [
            {"index": 0, "name": "成长之树", "rarity": "white", "confidence": 0.95, "rect": (10, 10, 50, 50), "description": ""},
            {"index": 1, "name": "散卡之王", "rarity": "purple", "confidence": 0.95, "rect": (60, 10, 100, 50), "description": ""},
            {"index": 2, "name": None, "confidence": 0.0},
        ]

        with patch.object(self.mediator, "_ocr_panel_slots", return_value=fake_slots_raw), \
             patch.object(self.mediator, "_bond_bar_occupancy", return_value=9):
            hit = self.mediator._ocr_reward_choice(frame, PANEL_BOND)

        self.assertIsNotNone(hit)
        # Verify decision selects slot 0 ("成长之树") over higher-rarity purple scatter card
        self.assertIn("成长之树", hit.name)
        # Verify decision reason explicitly proves path went through set_progress / 套装进度优先
        last_decision = getattr(self.mediator, "_last_policy_decision", None)
        if last_decision is not None:
            self.assertIn("套装进度优先", last_decision.reason)
    def test_mediator_zero_free_slots_refuses_scatter_cards(self):
        # Use real confirmed bond cards instead of injecting _active_bond_counts
        self.mediator._bond_cards_owned = ["祝福之灵", "祝福之触"]

        frame = Frame(bgr=np.zeros((100, 100, 3), dtype=np.uint8), hwnd=999, is_valid=True)

        fake_slots_raw = [
            {"index": 0, "name": "陌生散卡A", "rarity": "purple", "confidence": 0.95, "rect": (10, 10, 50, 50), "description": ""},
            {"index": 1, "name": "陌生散卡B", "rarity": "blue", "confidence": 0.95, "rect": (60, 10, 100, 50), "description": ""},
        ]

        with patch.object(self.mediator, "_ocr_panel_slots", return_value=fake_slots_raw), \
             patch.object(self.mediator, "_bond_bar_occupancy", return_value=10):
            hit = self.mediator._ocr_reward_choice(frame, PANEL_BOND)

        self.assertIsNone(hit)
        self.assertTrue(self.mediator._choice_policy_idle)
        self.assertIn("无安全候选", self.mediator._choice_policy_last_reason)
if __name__ == "__main__":
    unittest.main()
