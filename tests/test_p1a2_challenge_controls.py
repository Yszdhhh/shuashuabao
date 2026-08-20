"""P1-A2 Unit Tests for 4 Challenge Controls Automation & Safety.

Tests cover:
- Detection of 4 challenge templates on real main_line_auto_off.png / main_line_auto_on.png
- Icon click point validity & forbidden ROI avoidance
- Strict fixed ordering (coin -> wood -> experience -> treasure) and 1 right-click per tick
- Post-verification on subsequent frames
- Retry limit (3) and Fail-Closed stop in Phase.ERROR
- Safety cancellation (StopSignal, HWND mismatch, dry_run=False without target_hwnd)
- Regression protections for P0 Fail-Closed archive/boss_entry/longzhu and skill selection
- Explicit 4-State resolution (ON, OFF, UNKNOWN, PENDING) and zero-leakage of downstream inputs on UNKNOWN/failures
"""

import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from shuabao.input.keyboard_mouse import ActionResult
from shuabao.mediator import ChallengeState, LoopAction, Mediator, Phase
from shuabao.settings import Settings
from shuabao.stop_signal import StopSignal
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult
from run_replay import load_image
from tests.test_scenario_replay import FakeClock, FakeInputExecutor


class TestP1A2ChallengeControls(unittest.TestCase):
    def setUp(self):
        self.root = ROOT
        self.settings = Settings()
        self.stop_signal = StopSignal()
        self.med = Mediator(self.settings, self.root, stop_signal=self.stop_signal)
        self.med.set_phase(Phase.MAIN_LINE, "test setup")

        off_img_path = self.root / "fixtures" / "replay" / "main_line_auto_off.png"
        on_img_path = self.root / "fixtures" / "replay" / "main_line_auto_on.png"

        img_off = load_image(off_img_path)
        img_on = load_image(on_img_path)

        self.assertIsNotNone(img_off, f"Failed to load {off_img_path}")
        self.assertIsNotNone(img_on, f"Failed to load {on_img_path}")

        self.frame_off = Frame(img_off, window_title="英雄三国KK", hwnd=10001)
        self.frame_on = Frame(img_on, window_title="英雄三国KK", hwnd=10001)

    def test_find_all_challenge_templates_on_main_line_auto_off(self):
        """1. Check that all 4 challenge templates are found on main_line_auto_off.png and click points land in icon area."""
        keys = ["coin_challenge", "wood_challenge", "experience_challenge", "treasure_challenge"]
        labels = ["金币", "木材", "经验", "宝物"]

        auto_task_roi_box = (1400, 500, 150, 100)

        for key, label_name in zip(keys, labels):
            found = self.med._find_challenge_button(self.frame_off, key)
            self.assertIsNotNone(found, f"Challenge template {key} not found on main_line_auto_off.png")
            label_hit, click_hit = found
            cx, cy = click_hit.center

            # Click point must land in icon area (above text label)
            self.assertLess(click_hit.y, label_hit.y, f"{key} click_hit should be above label")

            # Must NOT land inside right-side auto task checkbox ROI
            bx, by, bw, bh = auto_task_roi_box
            is_in_auto_task_roi = (bx <= cx <= bx + bw) and (by <= cy <= by + bh)
            self.assertFalse(is_in_auto_task_roi, f"{key} click point {click_hit.center} fell into auto_task ROI")

            # Check explicit state resolution on main_line_auto_off.png (should be OFF)
            state = self.med._resolve_challenge_state(self.frame_off, label_hit)
            self.assertEqual(state, ChallengeState.OFF, f"{key} should be resolved as OFF on main_line_auto_off.png")

    def test_all_challenges_on_main_line_auto_on(self):
        """2. Check that on main_line_auto_on.png, all 4 challenges are confirmed ON and produce zero right click."""
        keys = ["coin_challenge", "wood_challenge", "experience_challenge", "treasure_challenge"]

        for key in keys:
            found = self.med._find_challenge_button(self.frame_on, key)
            self.assertIsNotNone(found, f"Challenge button {key} not found on main_line_auto_on.png")
            label_hit, _ = found
            state = self.med._resolve_challenge_state(self.frame_on, label_hit)
            self.assertEqual(state, ChallengeState.ON, f"{key} should be detected as ON (green auto) on main_line_auto_on.png")

        # When all 4 challenges are ON, _ensure_challenge_buttons returns None
        self.med._auto_task_done = True
        res = self.med._ensure_challenge_buttons(self.frame_on)
        self.assertIsNone(res, "Should return None when all 4 challenges are ON (allowing downstream non-input logic)")
        for key in keys:
            self.assertEqual(self.med._challenge_states.get(key), ChallengeState.ON)
            self.assertIn(key, self.med._challenge_done)

    def test_strict_four_challenge_ordering_and_one_input_per_tick(self):
        """3. Check strict order (coin -> wood -> experience -> treasure) and max 1 right click per tick."""
        self.med._auto_task_done = True  # bypass right-side auto task for this test

        # Mock act_right_click to record calls
        recorded_calls = []

        def mock_act_right_click(hit, name):
            recorded_calls.append(name)
            return True

        self.med.act_right_click = mock_act_right_click

        # Tick 1: Should trigger coin_challenge only
        res1 = self.med._ensure_challenge_buttons(self.frame_off)
        self.assertEqual(res1, LoopAction.Continue)
        self.assertEqual(len(recorded_calls), 1)
        self.assertEqual(recorded_calls[0], "金币Challenge-right_click")
        self.assertEqual(self.med._challenge_attempts.get("coin_challenge"), 1)
        self.assertEqual(self.med._challenge_states.get("coin_challenge"), ChallengeState.PENDING)
        self.assertNotIn("coin_challenge", self.med._challenge_done, "Right click success must NOT mark done immediately")

        # If on tick 2 coin_challenge is now ON (simulate via _challenge_done)
        self.med._challenge_done.add("coin_challenge")
        res2 = self.med._ensure_challenge_buttons(self.frame_off)
        self.assertEqual(res2, LoopAction.Continue)
        self.assertEqual(len(recorded_calls), 2)
        self.assertEqual(recorded_calls[1], "木材Challenge-right_click")

        # Tick 3: wood_challenge now ON
        self.med._challenge_done.add("wood_challenge")
        res3 = self.med._ensure_challenge_buttons(self.frame_off)
        self.assertEqual(res3, LoopAction.Continue)
        self.assertEqual(len(recorded_calls), 3)
        self.assertEqual(recorded_calls[2], "经验Challenge-right_click")

        # Tick 4: experience_challenge now ON
        self.med._challenge_done.add("experience_challenge")
        res4 = self.med._ensure_challenge_buttons(self.frame_off)
        self.assertEqual(res4, LoopAction.Continue)
        self.assertEqual(len(recorded_calls), 4)
        self.assertEqual(recorded_calls[3], "宝物Challenge-right_click")

        # Tick 5: treasure_challenge now ON -> all done -> returns None
        self.med._challenge_done.add("treasure_challenge")
        res5 = self.med._ensure_challenge_buttons(self.frame_off)
        self.assertIsNone(res5)

    def test_post_verification_requires_green_auto_on_subsequent_frame(self):
        """4. Check post-verification: right-click does NOT mark challenge ON immediately."""
        self.med._auto_task_done = True
        self.med.act_right_click = MagicMock(return_value=True)

        # First tick: right-clicks coin_challenge
        res = self.med._ensure_challenge_buttons(self.frame_off)
        self.assertEqual(res, LoopAction.Continue)
        self.assertNotIn("coin_challenge", self.med._challenge_done)
        self.assertEqual(self.med._challenge_states.get("coin_challenge"), ChallengeState.PENDING)

        # Second tick with frame_on (green auto visible): now marks ON
        res_on = self.med._ensure_challenge_buttons(self.frame_on)
        self.assertIsNone(res_on)  # frame_on marks all ON -> returns None
        self.assertIn("coin_challenge", self.med._challenge_done)
        self.assertEqual(self.med._challenge_states.get("coin_challenge"), ChallengeState.ON)

    def test_retry_limit_enters_phase_error_and_stops(self):
        """Three unconfirmed retries still Fail-Closed, with 1.5s observation spacing."""
        self.med._auto_task_done = True
        self.med.act_right_click = MagicMock(return_value=True)
        clock = FakeClock(start=100.0)

        with clock.install():
            # Attempt 1
            res1 = self.med._ensure_challenge_buttons(self.frame_off)
            self.assertEqual(res1, LoopAction.Continue)
            self.assertEqual(self.med._challenge_attempts.get("coin_challenge"), 1)

            # The observation window suppresses a second right-click.
            clock.advance(self.settings.ui_action_interval_s - 0.1)
            res_wait = self.med._ensure_challenge_buttons(self.frame_off)
            self.assertEqual(res_wait, LoopAction.Continue)
            self.assertEqual(self.med._challenge_attempts.get("coin_challenge"), 1)

            # Attempts 2 and 3 are only consumed after each window expires.
            clock.advance(0.1)
            res2 = self.med._ensure_challenge_buttons(self.frame_off)
            self.assertEqual(res2, LoopAction.Continue)
            self.assertEqual(self.med._challenge_attempts.get("coin_challenge"), 2)

            clock.advance(self.settings.ui_action_interval_s)
            res3 = self.med._ensure_challenge_buttons(self.frame_off)
            self.assertEqual(res3, LoopAction.Continue)
            self.assertEqual(self.med._challenge_attempts.get("coin_challenge"), 3)

            clock.advance(self.settings.ui_action_interval_s)
            res4 = self.med._ensure_challenge_buttons(self.frame_off)
        self.assertEqual(res4, LoopAction.Break)
        self.assertEqual(self.med.phase, Phase.ERROR)
        self.assertFalse(self.med._running)

    def test_auto_task_observation_window_suppresses_second_click(self):
        """Auto-task ON confirmation is observed for 1.5s before retrying."""
        toggle = MatchResult("auto_task_toggle", 0.9, 1400, 500, 30, 30, 1400, 500)
        clock = FakeClock(start=100.0)
        self.med._last_frame = self.frame_off

        with clock.install(), \
             patch.object(self.med, "_auto_task_state",
                          side_effect=[("OFF", toggle), ("OFF", toggle), ("ON", toggle)]), \
             patch.object(self.med, "_find_auto_task_toggle", return_value=toggle), \
             patch.object(self.med, "act_click", return_value=True) as click:
            first = self.med._ensure_auto_task_enabled(self.frame_off)
            self.assertEqual(first, LoopAction.Continue)
            self.assertEqual(click.call_count, 1)

            clock.advance(self.settings.ui_action_interval_s - 0.1)
            waiting = self.med._ensure_auto_task_enabled(self.frame_off)
            self.assertEqual(waiting, LoopAction.Continue)
            self.assertEqual(click.call_count, 1)

            clock.advance(0.1)
            done = self.med._ensure_auto_task_enabled(self.frame_off)
        self.assertIsNone(done)
        self.assertTrue(self.med._auto_task_done)
        self.assertEqual(click.call_count, 1)

    def test_control_trace_jsonl_records_ordered_observation_schema(self):
        """Challenge trace controls remain independently parseable JSON objects."""
        dummy_label = MatchResult("coin_challenge", 0.9, 100, 500, 50, 20, 100, 500)
        clock = FakeClock(start=100.0)

        with tempfile.TemporaryDirectory() as tmp, clock.install():
            trace_path = Path(tmp) / "trace.jsonl"
            self.med.set_trace(str(trace_path))
            self.med._last_frame = self.frame_off
            self.med._auto_task_done = True
            with patch.object(self.med, "_find_challenge_button", return_value=(dummy_label, dummy_label)), \
                 patch.object(self.med, "_resolve_challenge_state", return_value=ChallengeState.OFF), \
                 patch.object(self.med, "act_right_click", return_value=True):
                self.assertEqual(self.med._ensure_challenge_buttons(self.frame_off), LoopAction.Continue)
            self.med._trace_tick("MAIN_LINE", 0.0)
            self.med.set_trace(None)

            row = json.loads(trace_path.read_text(encoding="utf-8").strip())
        self.assertIsInstance(row["controls"], list)
        entry = row["controls"][0]
        self.assertEqual(
            list(entry),
            ["control", "state", "green_count", "label_bbox", "click_point", "pending_age"],
        )
        self.assertEqual(entry["control"], "coin_challenge")
        self.assertEqual(entry["state"], "OFF")
    def test_safety_stop_signal_and_hwnd_cancellation(self):
        """6. Check safety cancellation under StopSignal, HWND invalidation, or missing target_hwnd."""
        self.med._auto_task_done = True

        # StopSignal active
        self.stop_signal.trigger("test stop")
        res_stop = self.med._ensure_challenge_buttons(self.frame_off)
        self.assertEqual(res_stop, LoopAction.Break)

        # Reset stop signal & mediator
        self.stop_signal.reset()
        self.med.set_phase(Phase.MAIN_LINE, "reset")
        self.med._auto_task_done = True

        # dry_run=False without target_hwnd (hwnd=None or 0)
        invalid_frame = Frame(self.frame_off.bgr, window_title="英雄三国KK", hwnd=None)
        self.med._last_frame = invalid_frame
        self.med.settings.dry_run = False
        self.med.executor.dry_run = False
        res_no_hwnd = self.med.act_right_click(
            MatchResult("test", 0.9, 100, 100, 10, 10, 100, 100),
            "test_right_click"
        )
        self.assertFalse(res_no_hwnd, "dry_run=False without target_hwnd should be rejected")
        self.med.settings.dry_run = True
        self.med.executor.dry_run = True

    def test_regressions_post_game_archive_boss_longzhu_priority(self):
        """7. Check regression: archive/boss_entry/longzhu Fail-Closed 保留（S0 ⑧ 阶段门控）。"""
        self.med._auto_task_done = True
        self.med._post_game_pending = True  # 局尾窗口（战后流程进行中）才检查

        # Create dummy frame with 'archive' template matched
        with patch.object(self.med, "find_scene", side_effect=lambda f, name, **kw: MatchResult("archive", 0.9, 100, 100, 50, 50, 100, 100) if name == "archive" else None):
            res = self.med._tick_main_line(self.frame_off)
            self.assertEqual(res, LoopAction.Break)
            self.assertEqual(self.med.phase, Phase.ERROR)

    def test_reset_challenge_state_on_entering_new_main_line(self):
        """8. Check that set_phase(Phase.MAIN_LINE) resets challenge done/attempts and initializes states to PENDING."""
        self.med._challenge_done.add("coin_challenge")
        self.med._challenge_attempts["coin_challenge"] = 2
        self.med._challenge_unknown_since["coin_challenge"] = 123.0
        self.med._challenge_states["coin_challenge"] = ChallengeState.ON

        self.med.set_phase(Phase.MAIN_LINE, "new game")

        self.assertEqual(len(self.med._challenge_done), 0)
        self.assertEqual(len(self.med._challenge_attempts), 0)
        self.assertEqual(len(self.med._challenge_unknown_since), 0)
        for key in ("coin_challenge", "wood_challenge", "experience_challenge", "treasure_challenge"):
            self.assertEqual(self.med._challenge_states.get(key), ChallengeState.PENDING)

    def test_pending_lifecycle_and_transitions(self):
        """Check PENDING lifecycle: initialized at PENDING, transitions to PENDING on right-click, ON when confirmed."""
        self.med._auto_task_done = True
        dummy_label = MatchResult("coin_challenge", 0.9, 100, 500, 50, 20, 100, 500)

        # 1. Initially PENDING
        self.assertEqual(self.med._challenge_states.get("coin_challenge"), ChallengeState.PENDING)

        # 2. Right-click sent -> state transitions to PENDING waiting for confirmation
        with patch.object(self.med, "_find_challenge_button", return_value=(dummy_label, dummy_label)), \
             patch.object(self.med, "_resolve_challenge_state", return_value=ChallengeState.OFF), \
             patch.object(self.med.executor, "right_click", return_value=ActionResult(success=True, status="DRY_RUN")) as mock_rc:
            res = self.med._ensure_challenge_buttons(self.frame_off)
            self.assertEqual(res, LoopAction.Continue)
            mock_rc.assert_called_once()
            self.assertEqual(self.med._challenge_states.get("coin_challenge"), ChallengeState.PENDING)

        # 3. Subsequent frame confirms green auto text -> transitions PENDING -> ON
        with patch.object(self.med, "_find_challenge_button", return_value=(dummy_label, dummy_label)), \
             patch.object(self.med, "_resolve_challenge_state", return_value=ChallengeState.ON):
            res_on = self.med._ensure_challenge_buttons(self.frame_on)
            self.assertIn("coin_challenge", self.med._challenge_done)
            self.assertEqual(self.med._challenge_states.get("coin_challenge"), ChallengeState.ON)

    # --- New Required Refactoring Regression Tests ---

    def test_unknown_state_blocks_input_and_blocks_stage_select(self):
        """Regression 1: UNKNOWN state due to blurry/gray/obstructed ROI produces 0 clicks, 0 attempts, and blocks stage select."""
        self.med._auto_task_done = True
        dummy_label = MatchResult("coin_challenge", 0.8, 100, 500, 50, 20, 100, 500)

        with patch.object(self.med, "_find_challenge_button", return_value=(dummy_label, dummy_label)), \
             patch.object(self.med, "_resolve_challenge_state", return_value=ChallengeState.UNKNOWN), \
             patch.object(self.med.executor, "right_click") as mock_rc, \
             patch("shuabao.mediator.find_stage_labels") as mock_stage_find:

            res = self.med._tick_main_line(self.frame_off)
            self.assertEqual(res, LoopAction.Continue)
            mock_rc.assert_not_called()
            mock_stage_find.assert_not_called()
            self.assertEqual(self.med._challenge_attempts.get("coin_challenge", 0), 0)
            self.assertEqual(self.med._challenge_states.get("coin_challenge"), ChallengeState.UNKNOWN)

    def test_unknown_state_has_bounded_zero_input_timeout(self):
        """Persistent UNKNOWN: zero input while bounded, then the challenge is SKIPPED (no full stop)."""
        self.med._auto_task_done = True
        self.med.settings.query_timeout = 3
        dummy_label = MatchResult("coin_challenge", 0.8, 100, 500, 50, 20, 100, 500)

        with patch.object(self.med, "_find_challenge_button", return_value=(dummy_label, dummy_label)), \
             patch.object(self.med, "_resolve_challenge_state", return_value=ChallengeState.UNKNOWN), \
             patch.object(self.med.executor, "right_click") as mock_rc, \
             patch("shuabao.mediator.time.time", side_effect=[100.0, 103.0, 103.0, 103.0, 103.0, 103.0, 103.0, 103.0]):
            # 第一 tick：UNKNOWN → 零输入等待（Continue）
            self.assertEqual(self.med._ensure_challenge_buttons(self.frame_off), LoopAction.Continue)
            self.assertEqual(self.med._challenge_states.get("coin_challenge"), ChallengeState.UNKNOWN)
            # 超时后：跳过该挑战继续（Continue），不再整机停机
            self.assertEqual(self.med._ensure_challenge_buttons(self.frame_off), LoopAction.Continue)
            self.assertIn("coin_challenge", self.med._challenge_done)

        mock_rc.assert_not_called()
        self.assertNotEqual(self.med.phase, Phase.ERROR)
        self.assertFalse(self.stop_signal.is_set())

    def test_right_click_failure_attempt_1_blocks_stage_select(self):
        """Regression 2: Right click failure on attempt 1 increments attempt, returns Continue, and blocks stage select."""
        self.med._auto_task_done = True

        with patch.object(self.med.executor, "right_click", return_value=ActionResult(success=False, status="FAILED")) as mock_rc, \
             patch("shuabao.mediator.find_stage_labels") as mock_stage_find:

            res = self.med._tick_main_line(self.frame_off)
            self.assertEqual(res, LoopAction.Continue)
            mock_rc.assert_called_once()
            mock_stage_find.assert_not_called()
            self.assertEqual(self.med._challenge_attempts.get("coin_challenge"), 1)

    def test_right_click_failure_attempt_3_enters_phase_error(self):
        """Regression 3: Consecutive 3rd failed attempt sets Phase.ERROR, stops mediator, and returns Break."""
        self.med._auto_task_done = True
        self.med._challenge_attempts["coin_challenge"] = 2

        with patch.object(self.med.executor, "right_click", return_value=ActionResult(success=False, status="FAILED")) as mock_rc, \
             patch("shuabao.mediator.find_stage_labels") as mock_stage_find:

            res = self.med._tick_main_line(self.frame_off)
            self.assertEqual(res, LoopAction.Break)
            self.assertEqual(self.med.phase, Phase.ERROR)
            self.assertFalse(self.med._running)
            mock_stage_find.assert_not_called()

    def test_explicit_on_state_produces_zero_click(self):
        """Regression 4: Explicit ON state (green auto text >= 30) produces zero clicks."""
        dummy_label = MatchResult("coin_challenge", 0.9, 100, 500, 50, 20, 100, 500)

        with patch.object(self.med, "_find_challenge_button", return_value=(dummy_label, dummy_label)), \
             patch.object(self.med, "_resolve_challenge_state", return_value=ChallengeState.ON), \
             patch.object(self.med.executor, "right_click") as mock_rc:

            acted = self.med._ensure_challenge_buttons(self.frame_on)
            self.assertIsNone(acted)  # all ON -> returns None
            mock_rc.assert_not_called()
            self.assertEqual(self.med._challenge_states.get("coin_challenge"), ChallengeState.ON)

    def test_explicit_off_state_only_triggers_right_click(self):
        """Regression 5: Right click is only triggered when state is explicitly OFF."""
        dummy_label = MatchResult("coin_challenge", 0.9, 100, 500, 50, 20, 100, 500)

        with patch.object(self.med, "_find_challenge_button", return_value=(dummy_label, dummy_label)), \
             patch.object(self.med, "_resolve_challenge_state", return_value=ChallengeState.OFF), \
             patch.object(self.med.executor, "right_click", return_value=ActionResult(success=True, status="DRY_RUN")) as mock_rc:

            acted = self.med._ensure_challenge_buttons(self.frame_off)
            self.assertEqual(acted, LoopAction.Continue)
            mock_rc.assert_called_once()
            self.assertEqual(self.med._challenge_states.get("coin_challenge"), ChallengeState.PENDING)

    # --- Periodic ON re-observation (configured cadence, not permanent done) ---

    def test_anchored_on_schedules_periodic_recheck_not_permanent_done(self):
        """Regression: anchored ON schedules periodic re-observation (30s) and clicks nothing."""
        self.med._auto_task_done = True
        self.med.settings.challenge_recheck_interval_s = 30.0
        dummy_label = MatchResult("coin_challenge", 0.9, 100, 500, 50, 20, 100, 500)
        clock = FakeClock(start=100.0)
        with clock.install():
            with patch.object(self.med, "_find_challenge_button", return_value=(dummy_label, dummy_label)), \
                 patch.object(self.med, "_resolve_challenge_state", return_value=ChallengeState.ON), \
                 patch.object(self.med.executor, "right_click") as mock_rc:
                acted = self.med._ensure_challenge_buttons(self.frame_on)
        self.assertIsNone(acted)
        mock_rc.assert_not_called()
        self.assertIn("coin_challenge", self.med._challenge_done)
        # 复查时间按配置 cadence 排程，而非永久 done
        self.assertAlmostEqual(
            self.med._challenge_recheck_at["coin_challenge"],
            clock.now() + 30.0,
            delta=0.01,
        )

    def test_on_recheck_due_still_on_is_zero_click_and_reschedules(self):
        """周期复查到期且仍 ON：零点击，并按配置 cadence 重排下一次复查。"""
        self.med._auto_task_done = True
        self.med.settings.challenge_recheck_interval_s = 30.0
        dummy_label = MatchResult("coin_challenge", 0.9, 100, 500, 50, 20, 100, 500)
        clock = FakeClock(start=100.0)
        self.med._challenge_done.add("coin_challenge")
        self.med._challenge_recheck_at["coin_challenge"] = clock.now() - 1.0  # 到期
        with clock.install():
            with patch.object(self.med, "_find_challenge_button", return_value=(dummy_label, dummy_label)), \
                 patch.object(self.med, "_resolve_challenge_state", return_value=ChallengeState.ON), \
                 patch.object(self.med.executor, "right_click") as mock_rc:
                acted = self.med._ensure_challenge_buttons(self.frame_on)
        self.assertIsNone(acted)
        mock_rc.assert_not_called()
        self.assertIn("coin_challenge", self.med._challenge_done)
        self.assertGreater(self.med._challenge_recheck_at["coin_challenge"], clock.now() + 25.0)

    def test_later_anchored_off_toggle_clicked_once_within_cadence(self):
        """周期复查发现锚定的 OFF → 在配置 cadence 内点一次恢复（不永久 done）。"""
        self.med._auto_task_done = True
        self.med.settings.challenge_recheck_interval_s = 30.0
        dummy_label = MatchResult("coin_challenge", 0.9, 100, 500, 50, 20, 100, 500)
        clock = FakeClock(start=100.0)
        self.med._challenge_done.add("coin_challenge")
        self.med._challenge_recheck_at["coin_challenge"] = clock.now() - 1.0  # 到期复查
        with clock.install():
            with patch.object(self.med, "_find_challenge_button", return_value=(dummy_label, dummy_label)), \
                 patch.object(self.med, "_resolve_challenge_state", return_value=ChallengeState.OFF), \
                 patch.object(self.med.executor, "right_click", return_value=ActionResult(success=True, status="DRY_RUN")) as mock_rc:
                acted = self.med._ensure_challenge_buttons(self.frame_off)
        self.assertEqual(acted, LoopAction.Continue)
        mock_rc.assert_called_once()
        self.assertNotIn("coin_challenge", self.med._challenge_done)
        self.assertEqual(self.med._challenge_states.get("coin_challenge"), ChallengeState.PENDING)


if __name__ == "__main__":
    unittest.main()
