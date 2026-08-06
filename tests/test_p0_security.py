"""Unit tests for P0 security foundation: window identity, client coords, frame health, cancellable executor, Shift+F12 emergency stop, and clipboard preservation."""

from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from gamescript.input.emergency_stop import EmergencyStopListener
from gamescript.input.keyboard_mouse import InputExecutor, get_clipboard_text, paste_text, set_clipboard_text
from gamescript.stop_signal import StopSignal
from gamescript.vision.capture import (
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


class P0SecurityFoundationTests(unittest.TestCase):
    # ---------- Task 1: Window Identity ----------

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

    # ---------- Task 2: Client-to-Screen Coords ----------

    def test_client_to_screen_conversion(self) -> None:
        # Given client top-left at screen (108, 130)
        screen_x, screen_y = client_to_screen(None, 50, 60, client_origin=(108, 130))
        self.assertEqual((screen_x, screen_y), (158, 190))

        client_x, client_y = screen_to_client(None, 158, 190, client_origin=(108, 130))
        self.assertEqual((client_x, client_y), (50, 60))

    def test_get_client_rect_info_fallback(self) -> None:
        c_left, c_top, c_width, c_height = get_client_rect_info(0, 100, 200, 800, 600)
        self.assertEqual((c_left, c_top, c_width, c_height), (100, 200, 800, 600))

    # ---------- Task 3: Frame Health Checks ----------

    def test_check_frame_health_healthy(self) -> None:
        # Create a varied image frame
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
        # Uniform solid white frame -> std is 0 (< 1.0)
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

    # ---------- Task 4: Explicit Capture Failure ----------

    def test_capture_target_not_found_explicit_failure(self) -> None:
        # Calling capture with a non-existent title must return is_valid=False
        frame = capture(title_contains="NON_EXISTENT_WINDOW_TITLE_12345")
        self.assertFalse(frame.is_valid)
        self.assertIsNotNone(frame.error)
        self.assertIn("Target window not found", frame.error or "")

    def test_capture_minimized_window_explicit_failure(self) -> None:
        target = WindowTarget(hwnd=9999, title="Minimized", left=0, top=0, width=800, height=600)
        with patch("gamescript.vision.capture.is_window_minimized", return_value=True):
            frame = capture_target(target)
            self.assertFalse(frame.is_valid)
            self.assertEqual(frame.error, "Window is minimized")

    # ---------- Task 5: Cancellable InputExecutor ----------

    def test_input_executor_precheck_emergency_stop(self) -> None:
        stop_signal = StopSignal()
        stop_signal.trigger("Emergency test")
        executor = InputExecutor(stop_signal=stop_signal)
        res = executor.click(100, 200, dry_run=True)
        self.assertFalse(res.success)
        self.assertEqual(res.status, "CANCELLED_EMERGENCY_STOP")

    def test_input_executor_window_invalid_cancels(self) -> None:
        executor = InputExecutor()
        with patch("gamescript.input.keyboard_mouse.is_window_valid", return_value=False):
            res = executor.click(100, 200, target_hwnd=123, dry_run=False)
            self.assertFalse(res.success)
            self.assertEqual(res.status, "CANCELLED_WINDOW_INVALID")

    def test_input_executor_window_changed_cancels(self) -> None:
        executor = InputExecutor()
        with patch("gamescript.input.keyboard_mouse.is_window_valid", return_value=True), \
             patch("gamescript.input.keyboard_mouse.get_foreground_window", return_value=999), \
             patch("gamescript.input.keyboard_mouse.activate_window", return_value=False):
            res = executor.click(100, 200, target_hwnd=123, dry_run=False)
            self.assertFalse(res.success)
            self.assertEqual(res.status, "CANCELLED_WINDOW_CHANGED")

    # ---------- Task 6: Shift+F12 Emergency Stop & Shared Cancel ----------

    def test_shared_stop_signal_across_components(self) -> None:
        signal = StopSignal()
        executor = InputExecutor(stop_signal=signal)
        self.assertFalse(signal.is_set())

        # Trigger emergency stop
        signal.trigger("Shift+F12 emergency stop")
        self.assertTrue(signal.is_set())

        # Executor must cancel action
        res = executor.press_key("f1", dry_run=True)
        self.assertFalse(res.success)
        self.assertEqual(res.status, "CANCELLED_EMERGENCY_STOP")

    def test_emergency_stop_listener_triggers_signal(self) -> None:
        signal = StopSignal()
        listener = EmergencyStopListener(stop_signal=signal, poll_interval=0.01)

        # Mock check_key_pressed_win32 to simulate Shift+F12 pressed
        with patch("gamescript.input.emergency_stop.check_key_pressed_win32", side_effect=lambda vk: vk in (0x10, 0x7B)):
            listener.start()
            time.sleep(0.05)
            listener.stop()

        self.assertTrue(signal.is_set())
        self.assertIn("Shift+F12", signal.reason)

    # ---------- Task 7: Clipboard Save & Restore ----------

    def test_paste_text_preserves_clipboard(self) -> None:
        # Mock get_clipboard_text and set_clipboard_text
        clipboard_state: list[str] = ["ORIGINAL_CLIPBOARD_TEXT"]
        set_calls: list[str] = []

        def mock_get():
            return clipboard_state[0]

        def mock_set(val: str):
            clipboard_state[0] = val
            set_calls.append(val)
            return True

        with patch("gamescript.input.keyboard_mouse.get_clipboard_text", side_effect=mock_get), \
             patch("gamescript.input.keyboard_mouse.set_clipboard_text", side_effect=mock_set), \
             patch("pyautogui.hotkey") as mock_hotkey:
            paste_text("NEW_PASTE_TEXT", dry_run=False)

        # Set should be called first with NEW_PASTE_TEXT, then restored with ORIGINAL_CLIPBOARD_TEXT
        self.assertEqual(set_calls, ["NEW_PASTE_TEXT", "ORIGINAL_CLIPBOARD_TEXT"])
        self.assertEqual(clipboard_state[0], "ORIGINAL_CLIPBOARD_TEXT")
        mock_hotkey.assert_called_with("ctrl", "v")


if __name__ == "__main__":
    unittest.main()
