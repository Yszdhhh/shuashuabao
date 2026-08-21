"""Collectible no-safe-candidate physical-close regressions."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from shuabao.choice_policy import (
    PANEL_BOND,
    PANEL_TREASURE,
    PanelCandidates,
    PolicyAction,
    PolicySettings,
    SessionState,
    SlotCandidate,
    choose_action,
)
from shuabao.mediator import Mediator
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult

ROOT = Path(__file__).resolve().parents[1]


class TestCollectiblePhysicalClose(unittest.TestCase):
    def test_bond_and_treasure_no_safe_candidate_close_immediately(self):
        for kind in (PANEL_BOND, PANEL_TREASURE):
            with self.subTest(kind=kind):
                decision = choose_action(
                    PanelCandidates(
                        panel_kind=kind,
                        slots=(SlotCandidate(0, None, 0.0),),
                        settings=PolicySettings(),
                    ),
                    SessionState(waits=3, max_waits=3),
                )
                self.assertEqual(decision.action, PolicyAction.CLOSE)

    def test_treasure_close_accepts_card_hide_physical_template(self):
        med = Mediator(Settings(), ROOT)
        frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8))
        card_hide = MatchResult("card_hide", 0.99, 800, 560, 20, 20, 800, 560)

        def find(_frame, names, **_kwargs):
            return card_hide if "card_hide" in names else None

        with patch.object(med, "find", side_effect=find):
            hit = med._close_current_panel(frame, "treasure")
        self.assertIsNotNone(hit)
        self.assertEqual(hit.name, "card_hide")

    def test_skill_close_accepts_card_hide_when_skill_hide_variant_is_absent(self):
        med = Mediator(Settings(), ROOT)
        frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8))
        card_hide = MatchResult("card_hide", 0.99, 800, 560, 20, 20, 800, 560)

        def find(_frame, names, **_kwargs):
            self.assertIn("skill_hide", names)
            self.assertIn("card_hide", names)
            return card_hide

        with patch.object(med, "find", side_effect=find):
            hit = med._close_current_panel(frame, "skill")
        self.assertEqual(hit.name, "card_hide")


if __name__ == "__main__":
    unittest.main()
