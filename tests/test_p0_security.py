"""Unit tests for P0 security foundation: window identity, client coords, frame health, cancellable executor, Shift+F12 emergency stop, clipboard preservation, and Mediator input chain integration."""

from __future__ import annotations

import argparse
import ctypes
from pathlib import Path
import time
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from shuabao.input.emergency_stop import EmergencyStopListener
from shuabao.input.keyboard_mouse import ActionResult, InputExecutor, get_clipboard_text, paste_text, set_clipboard_text, type_text
from shuabao.loop_action import LoopAction
from shuabao.mediator import AttemptBudget, Mediator, Phase
from shuabao.settings import Settings
from shuabao.stop_signal import StopSignal
from shuabao.vision.matcher import MatchResult
from shuabao.vision.capture import (
    Frame,
    FrameHealthIssue,
    WindowTarget,
    capture,
    capture_target,
    check_frame_health,
    client_to_screen,
    find_window_targets,
    get_client_rect_info,
    get_window_class_name,
    get_window_process_info,
    is_window_minimized,
    is_window_valid,
    screen_to_client,
)
import main


class P0SecurityFoundationTests(unittest.TestCase):
    # ---------- Task 1: Window Identity & Fail-Closed Title Search ----------

    def test_window_target_identity_fields(self) -> None:
        target = WindowTarget(
            hwnd=12345,
            title="英雄三国KK",
            left=100,
            top=100,
            width=1600,
            height=900,
            pid=9999,
            exe="KKGame.exe",
            class_name="KKGameClass",
            role="l1",
            client_left=108,
            client_top=130,
            client_width=1584,
            client_height=860,
        )
        self.assertEqual(target.hwnd, 12345)
        self.assertEqual(target.pid, 9999)
        self.assertEqual(target.exe, "KKGame.exe")
        self.assertEqual(target.class_name, "KKGameClass")
        self.assertEqual(target.role, "l1")
        self.assertEqual(target.client_left, 108)
        self.assertEqual(target.client_top, 130)

    @patch("ctypes.windll.user32.GetClassNameW", side_effect=Exception("mock fail"))
    def test_get_window_class_name_mock(self, _mock_cls) -> None:
        cls_name = get_window_class_name(12345)
        self.assertEqual(cls_name, "")

    @patch("ctypes.windll.user32.GetWindowThreadProcessId", side_effect=Exception("mock fail"))
    def test_get_window_process_info_mock(self, _mock_pid) -> None:
        pid, exe = get_window_process_info(12345)
        self.assertEqual(pid, 0)
        self.assertEqual(exe, "")

    def test_fail_closed_window_keyword_search(self) -> None:
        with patch("shuabao.vision.capture.find_window_targets") as mock_find:
            mock_find.return_value = []
            targets = find_window_targets("NON_EXISTENT_TITLE_99999", allow_fallback=False)
            self.assertEqual(targets, [])

    # ---------- Task 2: Client-to-Screen Coords ----------

    def test_client_to_screen_conversion(self) -> None:
        screen_x, screen_y = client_to_screen(None, 50, 60, client_origin=(108, 130))
        self.assertEqual((screen_x, screen_y), (158, 190))

        client_x, client_y = screen_to_client(None, 158, 190, client_origin=(108, 130))
        self.assertEqual((client_x, client_y), (50, 60))

    def test_get_client_rect_info_fallback(self) -> None:
        c_left, c_top, c_width, c_height = get_client_rect_info(0, 100, 200, 800, 600)
        self.assertEqual((c_left, c_top, c_width, c_height), (100, 200, 800, 600))

    # ---------- Task 3: Frame Health Checks ----------

    def test_check_frame_health_healthy(self) -> None:
        arr = np.random.randint(50, 200, size=(100, 100, 3), dtype=np.uint8)
        frame = Frame(bgr=arr, left=0, top=0, window_title="Game", hwnd=123, is_valid=True)
        res = check_frame_health(frame)
        self.assertTrue(res.is_healthy)
        self.assertEqual(len(res.issues), 0)

    def test_check_frame_health_black_frame(self) -> None:
        black = np.zeros((100, 100, 3), dtype=np.uint8)
        frame = Frame(bgr=black, left=0, top=0, window_title="Game", hwnd=123, is_valid=True)
        res = check_frame_health(frame)
        self.assertFalse(res.is_healthy)
        self.assertIn(FrameHealthIssue.BLACK_FRAME, res.issues)

    def test_check_frame_health_low_entropy(self) -> None:
        white = np.ones((100, 100, 3), dtype=np.uint8) * 200
        frame = Frame(bgr=white, left=0, top=0, window_title="Game", hwnd=123, is_valid=True)
        res = check_frame_health(frame)
        self.assertFalse(res.is_healthy)
        self.assertIn(FrameHealthIssue.LOW_ENTROPY, res.issues)

    def test_check_frame_health_frozen_frame(self) -> None:
        arr = np.random.randint(50, 200, size=(50, 50, 3), dtype=np.uint8)
        t0 = time.time() - 10.0
        t1 = time.time()
        prev = Frame(bgr=arr.copy(), timestamp=t0, is_valid=True)
        curr = Frame(bgr=arr.copy(), timestamp=t1, is_valid=True)
        res = check_frame_health(curr, prev_frame=prev, frozen_threshold_sec=5.0)
        self.assertFalse(res.is_healthy)
        self.assertIn(FrameHealthIssue.FROZEN, res.issues)

    def test_check_frame_health_old_frame(self) -> None:
        arr = np.random.randint(50, 200, size=(50, 50, 3), dtype=np.uint8)
        old_time = time.time() - 20.0
        frame = Frame(bgr=arr, timestamp=old_time, is_valid=True)
        res = check_frame_health(frame, max_age_sec=5.0)
        self.assertFalse(res.is_healthy)
        self.assertIn(FrameHealthIssue.OLD_FRAME, res.issues)

    def test_unhealthy_frame_blocks_decision_and_inputs(self) -> None:
        settings = Settings()
        project_root = Path(__file__).resolve().parents[1]
        mediator = Mediator(settings, project_root)

        black_frame = Frame(bgr=np.zeros((100, 100, 3), dtype=np.uint8), hwnd=123, window_title="KK", is_valid=True)
        with patch.object(mediator, "see", return_value=black_frame), \
             patch.object(mediator, "act_click") as mock_click, \
             patch.object(mediator, "act_key") as mock_key, \
             patch.object(mediator, "find_scene") as mock_find_scene:

            action = mediator.tick()
            self.assertEqual(action, LoopAction.Continue)
            mock_click.assert_not_called()
            mock_key.assert_not_called()
            mock_find_scene.assert_not_called()

    def test_frozen_frame_history_reference_fix(self) -> None:
        settings = Settings()
        project_root = Path(__file__).resolve().parents[1]
        mediator = Mediator(settings, project_root)

        arr = np.random.randint(50, 200, size=(50, 50, 3), dtype=np.uint8)
        f1 = Frame(bgr=arr.copy(), timestamp=time.time() - 10.0, hwnd=100, window_title="KK", is_valid=True)
        f2 = Frame(bgr=arr.copy(), timestamp=time.time(), hwnd=100, window_title="KK", is_valid=True)

        frames = [f1, f1, f2, f2]
        with patch.object(mediator, "_capture_best", side_effect=frames):
            mediator.see("step 1")
            self.assertIs(mediator._last_frame, f1)
            self.assertIsNone(mediator._prev_frame)

            mediator.see("step 2")
            # 内容+位置相同的静态帧复用上一帧对象（场景缓存命中，避免重复模板扫描）
            self.assertIs(mediator._last_frame, f1)
            self.assertIs(mediator._prev_frame, f1)

            health = check_frame_health(mediator._last_frame, prev_frame=mediator._prev_frame)
            self.assertFalse(health.is_healthy)
            # 复用对象保留原时间戳 → 静态帧标记（OLD_FRAME 或 FROZEN）
            self.assertTrue(
                FrameHealthIssue.OLD_FRAME in health.issues or FrameHealthIssue.FROZEN in health.issues,
                f"expected static marker, got {health.issues}",
            )

    # ---------- Task 4: Explicit Capture Failure & Real Input HWND Binding ----------

    def test_capture_target_not_found_explicit_failure(self) -> None:
        with patch("shuabao.vision.capture.find_window_targets", return_value=[]):
            frame = capture(title_contains="NON_EXISTENT_WINDOW_TITLE_12345", allow_fallback=False)
            self.assertFalse(frame.is_valid)
            self.assertIsNotNone(frame.error)
            self.assertIn("Target window not found", frame.error or "")

    def test_capture_minimized_window_explicit_failure(self) -> None:
        target = WindowTarget(hwnd=9999, title="Minimized", left=0, top=0, width=800, height=600)
        with patch("shuabao.vision.capture.is_window_minimized", return_value=True):
            frame = capture_target(target)
            self.assertFalse(frame.is_valid)
            self.assertEqual(frame.error, "Window is minimized")

    def test_real_input_without_hwnd_is_rejected(self) -> None:
        executor = InputExecutor()
        with patch("shuabao.input.keyboard_mouse.is_current_process_elevated", return_value=True), \
             patch("shuabao.input.keyboard_mouse.click") as mock_click, \
             patch("shuabao.input.keyboard_mouse.press_key") as mock_press:
            res_click = executor.click(100, 200, target_hwnd=None, dry_run=False)
            self.assertFalse(res_click.success)
            self.assertEqual(res_click.status, "CANCELLED_NO_TARGET_HWND")
            mock_click.assert_not_called()

            res_press = executor.press_key("f1", target_hwnd=0, dry_run=False)
            self.assertFalse(res_press.success)
            self.assertEqual(res_press.status, "CANCELLED_NO_TARGET_HWND")
            mock_press.assert_not_called()

    def test_search_text_stops_on_first_failed_input_step(self) -> None:
        executor = InputExecutor()
        failed = ActionResult(False, "CANCELLED_SENDINPUT_FAILED", "injected failure")
        with patch.object(executor, "click", return_value=failed) as click:
            result = executor.search_text(10, 20, "4", target_hwnd=123, dry_run=True)

        self.assertIs(result, failed)
        click.assert_called_once()

    def test_win64_keyboard_input_uses_native_input_size(self) -> None:
        sizes: list[int] = []

        def accept_one(_count, _input, input_size):
            sizes.append(int(input_size))
            return 1

        with patch.object(ctypes.windll.user32, "SendInput", side_effect=accept_one), \
             patch("shuabao.input.keyboard_mouse.time.sleep", return_value=None):
            result = type_text("3", dry_run=False)

        self.assertEqual(result, [True])
        self.assertEqual(sizes, [40, 40])

    def test_double_click_rejects_first_injection_failure(self) -> None:
        executor = InputExecutor()
        ok = ActionResult(True, "OK", "")
        with patch.object(executor, "check_can_execute", return_value=ok), \
             patch.object(executor, "_check_point_obscured", return_value=None), \
             patch("shuabao.input.keyboard_mouse.click", side_effect=[False, True]) as click:
            result = executor.double_click(10, 20, target_hwnd=123, dry_run=False)

        self.assertFalse(result.success)
        self.assertEqual(result.status, "CANCELLED_SENDINPUT_FAILED")
        self.assertEqual(click.call_count, 1)

    # ---------- Task 5: Cancellable InputExecutor & Safety Checks ----------

    def test_input_executor_precheck_emergency_stop(self) -> None:
        stop_signal = StopSignal()
        stop_signal.trigger("Emergency test")
        executor = InputExecutor(stop_signal=stop_signal)
        res = executor.click(100, 200, dry_run=True)
        self.assertFalse(res.success)
        self.assertEqual(res.status, "CANCELLED_EMERGENCY_STOP")

    def test_input_executor_not_elevated_cancels_real_input(self) -> None:
        executor = InputExecutor()
        with patch("shuabao.input.keyboard_mouse.is_current_process_elevated", return_value=False), \
             patch("shuabao.input.keyboard_mouse.click") as mock_click:
            res = executor.click(100, 200, target_hwnd=123, dry_run=False)
            self.assertFalse(res.success)
            self.assertEqual(res.status, "CANCELLED_NOT_ELEVATED")
            mock_click.assert_not_called()

    def test_input_executor_window_invalid_cancels(self) -> None:
        executor = InputExecutor()
        with patch("shuabao.input.keyboard_mouse.is_current_process_elevated", return_value=True), \
             patch("shuabao.input.keyboard_mouse.is_window_valid", return_value=False):
            res = executor.click(100, 200, target_hwnd=123, dry_run=False)
            self.assertFalse(res.success)
            self.assertEqual(res.status, "CANCELLED_WINDOW_INVALID")

    def test_input_executor_window_changed_cancels(self) -> None:
        executor = InputExecutor()
        with patch("shuabao.input.keyboard_mouse.is_current_process_elevated", return_value=True), \
             patch("shuabao.input.keyboard_mouse.is_window_valid", return_value=True), \
             patch("shuabao.input.keyboard_mouse.get_foreground_window", return_value=999), \
             patch("shuabao.input.keyboard_mouse.activate_window", return_value=False):
            res = executor.click(100, 200, target_hwnd=123, dry_run=False)
            self.assertFalse(res.success)
            self.assertEqual(res.status, "CANCELLED_WINDOW_CHANGED")

    # ---------- Task 6: Shift+F12 Emergency Stop & Shared Cancel ----------

    def test_shared_stop_signal_across_components(self) -> None:
        signal = StopSignal()
        executor = InputExecutor(stop_signal=signal)
        self.assertFalse(signal.is_set())

        signal.trigger("Shift+F12 emergency stop")
        self.assertTrue(signal.is_set())

        res = executor.press_key("f1", dry_run=True)
        self.assertFalse(res.success)
        self.assertEqual(res.status, "CANCELLED_EMERGENCY_STOP")

    def test_emergency_stop_listener_triggers_signal(self) -> None:
        signal = StopSignal()
        listener = EmergencyStopListener(stop_signal=signal, poll_interval=0.01)

        with patch("shuabao.input.emergency_stop.check_key_pressed_win32", side_effect=lambda vk: vk in (0x10, 0x7B)):
            listener.start()
            time.sleep(0.05)
            listener.stop()

        self.assertTrue(signal.is_set())
        self.assertIn("Shift+F12", signal.reason)

    # ---------- Task 7: Clipboard Save & Restore ----------

    def test_paste_text_preserves_clipboard(self) -> None:
        clipboard_state: list[str] = ["ORIGINAL_CLIPBOARD_TEXT"]
        set_calls: list[str] = []

        def mock_get():
            return clipboard_state[0]

        def mock_set(val: str):
            clipboard_state[0] = val
            set_calls.append(val)
            return True

        with patch("shuabao.input.keyboard_mouse.get_clipboard_text", side_effect=mock_get), \
             patch("shuabao.input.keyboard_mouse.set_clipboard_text", side_effect=mock_set), \
             patch("pyautogui.hotkey") as mock_hotkey:
            paste_text("NEW_PASTE_TEXT", dry_run=False)

        self.assertEqual(set_calls, ["NEW_PASTE_TEXT", "ORIGINAL_CLIPBOARD_TEXT"])
        self.assertEqual(clipboard_state[0], "ORIGINAL_CLIPBOARD_TEXT")
        mock_hotkey.assert_called_with("ctrl", "v")

    # ---------- Task 8: Mediator Input Chain Integration Tests ----------

    def test_mediator_fill_room_dialog_uses_executor(self) -> None:
        settings = Settings()
        settings.room_name = "TestRoom"
        settings.room_password = "123"
        mediator = Mediator(settings, Path(__file__).resolve().parents[1])
        frame = Frame(bgr=np.zeros((100, 100, 3), dtype=np.uint8), hwnd=777, is_valid=True)
        mediator._last_frame = frame
        confirm = MatchResult("confirm", 0.9, 10, 10, 20, 20, 10, 10)

        boxes = [
            MatchResult("box1", 0.9, 5, 5, 10, 10, 5, 5),
            MatchResult("box2", 0.9, 5, 15, 10, 10, 5, 15),
        ]
        with patch("shuabao.mediator.find_input_boxes", return_value=boxes), \
             patch.object(mediator, "act_click", return_value=True), \
             patch.object(mediator.executor, "hotkey", return_value=True) as mock_hk, \
             patch.object(mediator.executor, "paste_text", return_value=True) as mock_paste:

            res = mediator._fill_room_dialog(frame, confirm)
            self.assertTrue(res)
            self.assertEqual(mock_hk.call_count, 2)
            self.assertEqual(mock_paste.call_count, 2)

            # Check that target_hwnd was passed to executor
            for call_args in mock_hk.call_args_list:
                self.assertEqual(call_args.kwargs.get("target_hwnd"), 777)
            for call_args in mock_paste.call_args_list:
                self.assertEqual(call_args.kwargs.get("target_hwnd"), 777)

    def test_mediator_fill_room_dialog_cancels_on_executor_failure(self) -> None:
        settings = Settings()
        settings.room_name = "TestRoom"
        settings.room_password = "123"
        mediator = Mediator(settings, Path(__file__).resolve().parents[1])
        frame = Frame(bgr=np.zeros((100, 100, 3), dtype=np.uint8), hwnd=777, is_valid=True)
        mediator._last_frame = frame
        confirm = MatchResult("confirm", 0.9, 10, 10, 20, 20, 10, 10)
        boxes = [
            MatchResult("box1", 0.9, 5, 5, 10, 10, 5, 5),
            MatchResult("box2", 0.9, 5, 15, 10, 10, 5, 15),
        ]

        # Trigger emergency stop before room dialog fill
        mediator.stop_signal.trigger("Emergency stop inside dialog")

        with patch("shuabao.mediator.find_input_boxes", return_value=boxes), \
             patch.object(mediator, "act_click", return_value=True), \
             patch.object(mediator.executor, "paste_text") as mock_paste:

            res = mediator._fill_room_dialog(frame, confirm)
            self.assertFalse(res)
            mock_paste.assert_not_called()

    def test_mediator_stage_scroll_uses_executor(self) -> None:
        settings = Settings()
        settings.stage_targets = ["2-1"]
        mediator = Mediator(settings, Path(__file__).resolve().parents[1])
        mediator.phase = Phase.STAGE_SELECT
        frame = Frame(bgr=np.zeros((100, 100, 3), dtype=np.uint8), hwnd=888, is_valid=True)
        mediator._last_frame = frame

        with patch.object(mediator, "_detect_context", return_value="STAGE_SELECT"), \
             patch.object(mediator, "_find_stage_page", return_value=True), \
             patch.object(mediator, "_find_stage_target", return_value=None), \
             patch.object(mediator.executor, "scroll", return_value=True) as mock_scroll:

            action = mediator._tick_l0(frame)
            self.assertEqual(action, LoopAction.Continue)
            mock_scroll.assert_called_once()
            self.assertEqual(mock_scroll.call_args.kwargs.get("target_hwnd"), 888)
            self.assertIn(mock_scroll.call_args.args[2], [-1, -2])
            self.assertEqual(mediator._stage_scroll_attempts, 1)

    def test_attempt_budget_bounds_actions_retries_and_deadline(self) -> None:
        budget = AttemptBudget(
            started_at=10.0, hard_deadline=20.0, actions_left=1, retries_left=1
        )

        self.assertTrue(budget.consume_action(15.0))
        self.assertFalse(budget.consume_action(15.0))
        self.assertTrue(budget.consume_retry(15.0))
        self.assertFalse(budget.consume_retry(15.0))
        self.assertTrue(budget.exhausted(20.0))

    def test_stage_budget_deadline_fails_closed_without_reset(self) -> None:
        mediator = Mediator(Settings(), Path(__file__).resolve().parents[1])
        mediator.phase = Phase.STAGE_SELECT
        mediator._stage_attempt_budget = AttemptBudget(
            started_at=0.0, hard_deadline=1.0, actions_left=12, retries_left=2
        )
        frame = Frame(bgr=np.zeros((100, 100, 3), dtype=np.uint8), hwnd=888, is_valid=True)

        with patch("shuabao.mediator.time.time", return_value=1.0):
            self.assertEqual(mediator._tick_l0(frame), LoopAction.Break)

        self.assertIs(mediator.phase, Phase.ERROR)

    def test_challenge_retry_exhaustion_stays_in_same_stage_budget(self) -> None:
        mediator = Mediator(Settings(), Path(__file__).resolve().parents[1])
        mediator._stage_attempt_budget = AttemptBudget(
            started_at=0.0, hard_deadline=100.0, actions_left=12, retries_left=1
        )

        with patch("shuabao.mediator.time.time", return_value=1.0):
            self.assertEqual(mediator._challenge_start_timeout(True), LoopAction.Continue)
            self.assertEqual(mediator._stage_attempt_budget.retries_left, 0)
            self.assertEqual(mediator._stage_budget_guard(1.0), LoopAction.Break)

        self.assertIs(mediator.phase, Phase.ERROR)

    def test_main_line_watchdog_never_injects_global_escape(self) -> None:
        mediator = Mediator(Settings(), Path(__file__).resolve().parents[1])
        mediator.phase = Phase.MAIN_LINE
        mediator._auto_task_done = True
        mediator._l1_cycle_step = "unknown"
        mediator._main_line_since = 0.0
        frame = Frame(bgr=np.zeros((100, 100, 3), dtype=np.uint8), hwnd=888, is_valid=True)

        with patch("shuabao.mediator.time.time", return_value=15.0), \
             patch.object(mediator, "act_key") as key, \
             patch.object(mediator, "_advance_l1_cycle") as advance, \
             patch.object(mediator, "_maybe_ensure_hero_panel_focus", return_value=None):
            self.assertEqual(mediator._tick_main_line(frame), LoopAction.Continue)

        key.assert_not_called()
        advance.assert_called_once()

    def test_legacy_real_mode_prohibited(self) -> None:
        args = argparse.Namespace(config=None, legacy=True, longzhu=False, steps=10)
        ret = main.cmd_run(args)
        self.assertEqual(ret, 1)


if __name__ == "__main__":
    unittest.main()
