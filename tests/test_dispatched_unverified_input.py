"""A click that reached the game must never be replayed as if it had not.

2026-09-09 live trace (``hitch_lobby_chain_20260909_215849_052314``):
tick 175 selected 极速神符 and logged ``ok=true``; tick 464 selected 暴怒神符,
the log shows ``[input] click (723, 480) dry_run=False`` — the input WAS
injected — yet the action recorded ``ok=false`` because the operator's desktop
took the foreground straight afterwards.  The panel FSM read that as "never
clicked", kept the same fingerprint, and hammered the slot until it force-closed
the treasure panel.  These tests pin the separation between "never sent" and
"sent, outcome unverified".
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.input.keyboard_mouse import INPUT_DISPATCHED_UNVERIFIED, ActionResult, InputExecutor
from shuabao.mediator import Mediator, PanelState
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult


def _frame() -> Frame:
    return Frame(bgr=np.zeros((900, 1600, 3), dtype=np.uint8), timestamp=0.0, left=0, top=0, hwnd=10001)


class ExecutorPostCheckTests(unittest.TestCase):
    def test_pre_flight_foreground_mismatch_keeps_the_original_status(self):
        executor = InputExecutor()
        with patch("shuabao.input.keyboard_mouse.is_current_process_elevated", return_value=True), \
             patch("shuabao.input.keyboard_mouse.is_window_valid", return_value=True), \
             patch("shuabao.input.keyboard_mouse.get_foreground_window", return_value=999), \
             patch("shuabao.input.keyboard_mouse.activate_window", return_value=False):
            res = executor.click(100, 200, target_hwnd=123, dry_run=False)
        self.assertFalse(res.success)
        self.assertEqual(res.status, "CANCELLED_WINDOW_CHANGED")

    def test_foreground_lost_after_injection_gets_its_own_status(self):
        executor = InputExecutor()
        with patch("shuabao.input.keyboard_mouse.is_current_process_elevated", return_value=True), \
             patch("shuabao.input.keyboard_mouse.is_window_valid", return_value=True), \
             patch("shuabao.input.keyboard_mouse.get_foreground_window", side_effect=[123, 999]), \
             patch("shuabao.input.keyboard_mouse.foreground_matches_target", side_effect=[True, False]), \
             patch.object(InputExecutor, "_check_point_obscured", return_value=None), \
             patch("shuabao.input.keyboard_mouse.click", return_value=True):
            res = executor.click(100, 200, target_hwnd=123, dry_run=False)
        self.assertFalse(res.success)
        self.assertEqual(res.status, INPUT_DISPATCHED_UNVERIFIED)
        self.assertNotEqual(res.status, "CANCELLED_WINDOW_CHANGED")


class MediatorDispatchAccountingTests(unittest.TestCase):
    def setUp(self):
        self.med = Mediator(Settings(dry_run=True, ocr_mode="off"), ROOT)
        self.hit = MatchResult("ocr_treasure:暴怒神符", 1.0, 723, 480, 40, 20, 723, 480)

    def _click_with_status(self, status: str, success: bool = False) -> bool:
        result = ActionResult(success=success, status=status, message="")
        with patch.object(self.med.executor, "click", return_value=result):
            return self.med.act_click(self.hit, "treasure选择")

    def test_never_sent_input_does_not_consume_the_tick_budget(self):
        self.assertFalse(self._click_with_status("CANCELLED_WINDOW_CHANGED"))
        self.assertFalse(self.med._last_input_dispatched_unverified())
        self.assertEqual(self.med._input_seq, 0)

    def test_dispatched_unverified_input_consumes_the_tick_budget(self):
        self.assertFalse(self._click_with_status(INPUT_DISPATCHED_UNVERIFIED))
        self.assertTrue(self.med._last_input_dispatched_unverified())
        self.assertEqual(self.med._input_seq, 1, "已注入的输入必须推进输入序号，本 tick 不得再发第二次")
        self.assertTrue(self.med._tick_input_executed)

    def test_successful_input_is_not_flagged_as_unverified(self):
        self.assertTrue(self._click_with_status("SUCCESS", success=True))
        self.assertFalse(self.med._last_input_dispatched_unverified())


class ChoicePanelPostConfirmTests(unittest.TestCase):
    def setUp(self):
        self.med = Mediator(Settings(dry_run=True, ocr_mode="off"), ROOT)
        self.med._panel_state = PanelState.ACTIVE
        self.med._panel_kind = "treasure"
        self.med._panel_episode_started = None
        self.frame = _frame()
        self.anchor = MatchResult("panel_anchor", 1.0, 800, 300, 10, 10, 800, 300)
        self.hit = MatchResult("ocr_treasure:暴怒神符", 1.0, 723, 480, 40, 20, 723, 480)

    def _run_choice(self, clicked: bool, dispatched_unverified: bool):
        with patch.object(self.med, "_find_reward_choice", return_value=("treasure", self.hit)), \
             patch.object(self.med, "_hitch_fail_close_choice_panel", return_value=False), \
             patch.object(self.med, "act_click", return_value=clicked), \
             patch.object(self.med, "_last_input_dispatched_unverified", return_value=dispatched_unverified):
            return self.med._tick_panel_fsm(self.frame, self.anchor, 100.0)

    def test_dispatched_unverified_select_waits_for_mutation_instead_of_reclicking(self):
        self._run_choice(clicked=False, dispatched_unverified=True)
        self.assertIs(self.med._panel_state, PanelState.WAIT_MUTATION)
        self.assertEqual(self.med._panel_pending_choice_action, "select")
        self.assertGreater(self.med._selection_click_cooldown_until, 100.0)

    def test_genuinely_rejected_select_leaves_the_panel_active(self):
        self._run_choice(clicked=False, dispatched_unverified=False)
        self.assertIs(self.med._panel_state, PanelState.ACTIVE)

    def test_confirmed_mutation_reports_post_confirm_true(self):
        self._run_choice(clicked=True, dispatched_unverified=False)
        self.assertIs(self.med._panel_state, PanelState.WAIT_MUTATION)
        self.med._tick_post_confirm = None
        with patch.object(self.med, "_panel_mutation_confirmed", return_value=True):
            self.med._tick_panel_fsm(self.frame, self.anchor, 100.5)
        self.assertIs(self.med._trace_post_confirm(), True)

    def test_expired_confirm_window_reports_post_confirm_false(self):
        self._run_choice(clicked=True, dispatched_unverified=False)
        self.med._tick_post_confirm = None
        with patch.object(self.med, "_panel_mutation_confirmed", return_value=False):
            self.med._tick_panel_fsm(self.frame, self.anchor, 100.0 + self.med._panel_confirm_window + 1.0)
        self.assertIs(self.med._trace_post_confirm(), False)

    def test_post_confirm_is_null_while_the_window_is_still_open(self):
        self._run_choice(clicked=True, dispatched_unverified=False)
        self.med._tick_post_confirm = None
        with patch.object(self.med, "_panel_mutation_confirmed", return_value=False):
            self.med._tick_panel_fsm(self.frame, self.anchor, 100.5)
        self.assertIsNone(self.med._trace_post_confirm())


if __name__ == "__main__":
    unittest.main()
