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
        self.settings.cards = ["祝福"]
        self.settings.bonds = ["祝福"]
        self.settings.bond_must_take = []
        self.mediator = Mediator(project_root=ROOT, settings=self.settings)

    def test_mediator_extracts_and_feeds_live_progress_to_policy(self):
        # Use real confirmed bond cards instead of injecting _active_bond_counts
        self.mediator._bond_cards_owned = ["祝福之灵", "祝福之触", "祝福之光"]

        frame = Frame(bgr=np.zeros((100, 100, 3), dtype=np.uint8), hwnd=999, is_valid=True)

        fake_slots_raw = [
            {"index": 0, "name": "祝福之灵", "rarity": "white", "confidence": 0.95, "rect": (10, 10, 50, 50), "description": ""},
            {"index": 1, "name": "陌生散卡", "rarity": "purple", "confidence": 0.95, "rect": (60, 10, 100, 50), "description": ""},
        ]

        with patch.object(self.mediator, "_ocr_panel_slots", return_value=fake_slots_raw), \
             patch.object(self.mediator, "_bond_bar_occupancy", return_value=9):
            hit = self.mediator._ocr_reward_choice(frame, PANEL_BOND)

        self.assertIsNotNone(hit)
        self.assertIn("祝福之灵", hit.name)

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

        # In slot-capped zero free slots with only scatter cards, policy issues CLOSE (hide_fallback hit) rather than selecting a slot
        self.assertIsNotNone(hit)
        self.assertEqual(hit.name, "hide_fallback")
if __name__ == "__main__":
    unittest.main()
