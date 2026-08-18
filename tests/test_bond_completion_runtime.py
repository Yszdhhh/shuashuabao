"""Regression tests for the round-local bond preset completion latch."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from shuabao.choice_policy import PolicySettings
from shuabao.loop_action import LoopAction
from shuabao.mediator import PanelState
from shuabao.runtime_mediator import Mediator
from shuabao.settings import Settings
from shuabao.vision.capture import Frame


class TestBondCompletionRuntime(unittest.TestCase):
    def new_mediator(self) -> Mediator:
        med = Mediator(
            Settings(
                cards=["三国", "体术"],
                auto_bond=True,
                dry_run=True,
                ocr_mode="off",
            ),
            ROOT,
        )
        med._fetter_labels = {"三国": "三国", "体术": "体术"}
        med._cached_policy_settings = PolicySettings(
            bond_presets=("三国", "体术"),
        )
        return med

    def test_unconfirmed_click_never_counts_as_owned(self):
        med = self.new_mediator()
        med._stage_bond_card("ocr_bond:三国")
        self.assertEqual(med._confirmed_bond_cards(), ())
        self.assertEqual(med._remaining_bond_presets(), ("三国", "体术"))
        med._clear_pending_skill_cards()
        self.assertEqual(med._confirmed_bond_cards(), ())

    def test_confirmed_cards_are_removed_from_remaining_whitelist(self):
        med = self.new_mediator()
        med._stage_bond_card("ocr_bond:三国")
        med._commit_pending_skill_cards()
        self.assertEqual(med._confirmed_bond_cards(), ("三国",))
        self.assertEqual(med._remaining_bond_presets(), ("体术",))
        self.assertEqual(med._policy_settings().bond_presets, ("体术",))
        self.assertFalse(med._bond_presets_complete())

    def test_all_confirmed_presets_complete_the_round_latch(self):
        med = self.new_mediator()
        for name in ("三国", "体术"):
            med._stage_bond_card(f"ocr_bond:{name}")
            med._commit_pending_skill_cards()
        self.assertTrue(med._bond_presets_complete())
        self.assertEqual(med._remaining_bond_presets(), ())
        self.assertEqual(med._policy_settings().bond_presets, ())

    def test_completed_presets_skip_proactive_f_and_advance_to_treasure(self):
        med = self.new_mediator()
        med._bond_cards_owned[:] = ["三国", "体术"]
        med._l1_cycle_step = "bond"
        med._panel_state = PanelState.CLOSED
        frame = Frame(
            np.zeros((900, 1600, 3), dtype=np.uint8),
            window_title="英雄三国",
            hwnd=1,
        )
        with patch.object(
            med,
            "act_click",
            side_effect=AssertionError("completed bond presets must not click F"),
        ):
            result = med._maybe_open_choice_panel(frame, anchor=None)
        self.assertEqual(result, LoopAction.Continue)
        self.assertEqual(med._l1_cycle_step, "treasure")
        self.assertEqual(med._panel_state, PanelState.CLOSED)

    def test_partial_presets_keep_bond_step_available(self):
        med = self.new_mediator()
        med._bond_cards_owned[:] = ["三国"]
        med._l1_cycle_step = "bond"
        med._panel_state = PanelState.CLOSED
        frame = Frame(
            np.zeros((900, 1600, 3), dtype=np.uint8),
            window_title="英雄三国",
            hwnd=1,
        )
        with patch.object(med, "_selection_anchor", return_value=None), patch.object(
            med, "act_click", return_value=True
        ) as click:
            result = med._maybe_open_choice_panel(frame, anchor=None)
        self.assertEqual(result, LoopAction.Continue)
        click.assert_called_once()
        self.assertEqual(med._panel_kind, "bond")
        self.assertEqual(med._panel_state, PanelState.OPEN_REQUESTED)

    def test_empty_bond_configuration_skips_bond_entirely(self):
        med = self.new_mediator()
        med._cached_policy_settings = PolicySettings(bond_presets=())
        self.assertTrue(med._bond_presets_complete())


if __name__ == "__main__":
    unittest.main()
