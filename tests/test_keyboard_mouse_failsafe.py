"""LIVE pyautogui 路径的 fail-safe 语义化测试。

背景：pyautogui 0.9.54 的 press/hotkey/write/moveTo 内部会调用
failSafeCheck()——鼠标进入屏幕角落时抛 pyautogui.FailSafeException。
此前该异常一路炸穿 InputExecutor，调用方拿不到任何失败信号。
要求：LIVE press_key/hotkey/paste_text/scroll 捕获 FailSafeException，
经 InputExecutor 沿用 ActionResult 返回明确失败；其他异常继续抛出。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pyautogui  # noqa: E402

from gamescript.input import keyboard_mouse as kb  # noqa: E402
from gamescript.input.keyboard_mouse import ActionResult, InputFailSafeError  # noqa: E402
from gamescript.stop_signal import StopSignal  # noqa: E402


class StandaloneFailSafeConversionTests(unittest.TestCase):
    """独立函数：FailSafeException → InputFailSafeError；其他异常原样抛出。"""

    def test_press_key_live_converts_failsafe(self):
        with patch.object(pyautogui, "press", side_effect=pyautogui.FailSafeException("corner")):
            with self.assertRaises(InputFailSafeError):
                kb.press_key("f4", dry_run=False)

    def test_press_key_live_propagates_other_exceptions(self):
        with patch.object(pyautogui, "press", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                kb.press_key("f4", dry_run=False)

    def test_hotkey_live_converts_failsafe(self):
        with patch.object(pyautogui, "hotkey", side_effect=pyautogui.FailSafeException("corner")):
            with self.assertRaises(InputFailSafeError):
                kb.hotkey("ctrl", "a", dry_run=False)

    def test_hotkey_live_propagates_other_exceptions(self):
        with patch.object(pyautogui, "hotkey", side_effect=ValueError("bad key")):
            with self.assertRaises(ValueError):
                kb.hotkey("ctrl", "a", dry_run=False)

    def test_paste_text_live_converts_failsafe(self):
        with patch.object(kb, "get_clipboard_text", return_value="prior"), \
             patch.object(kb, "set_clipboard_text", return_value=True), \
             patch.object(pyautogui, "hotkey", side_effect=pyautogui.FailSafeException("corner")):
            with self.assertRaises(InputFailSafeError):
                kb.paste_text("secret", dry_run=False)

    def test_paste_text_live_propagates_other_exceptions(self):
        with patch.object(kb, "get_clipboard_text", return_value="prior"), \
             patch.object(kb, "set_clipboard_text", return_value=True), \
             patch.object(pyautogui, "hotkey", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                kb.paste_text("secret", dry_run=False)

    def test_scroll_live_converts_failsafe(self):
        with patch.object(pyautogui, "moveTo", side_effect=pyautogui.FailSafeException("corner")):
            with self.assertRaises(InputFailSafeError):
                kb.scroll(100, 200, 3, dry_run=False)

    def test_scroll_live_propagates_other_exceptions(self):
        with patch.object(pyautogui, "moveTo", side_effect=OSError("bad")):
            with self.assertRaises(OSError):
                kb.scroll(100, 200, 3, dry_run=False)

    def test_dry_run_never_touches_pyautogui(self):
        with patch.object(pyautogui, "press", side_effect=AssertionError("must not call")):
            kb.press_key("f4", dry_run=True)
        with patch.object(pyautogui, "hotkey", side_effect=AssertionError("must not call")):
            kb.hotkey("ctrl", "a", dry_run=True)
        with patch.object(pyautogui, "moveTo", side_effect=AssertionError("must not call")):
            kb.scroll(1, 2, 3, dry_run=True)
        kb.paste_text("", dry_run=False)  # 空文本不触碰 pyautogui


class ExecutorFailSafeActionTests(unittest.TestCase):
    """InputExecutor：FailSafeException 必须变成 ActionResult 明确失败。"""

    def setUp(self):
        self.executor = kb.InputExecutor(StopSignal())

    def _ok_check(self, target_hwnd=None, dry_run=True):
        return ActionResult(success=True, status="OK", message="ok")

    def test_press_key_returns_failsafe_failure(self):
        with patch.object(kb.InputExecutor, "check_can_execute", return_value=self._ok_check()), \
             patch.object(kb, "press_key", side_effect=InputFailSafeError("corner")):
            result = self.executor.press_key("f4", target_hwnd=1, dry_run=False)
        self.assertFalse(result.success)
        self.assertEqual("CANCELLED_FAILSAFE", result.status)
        self.assertIn("f4", result.message)

    def test_hotkey_returns_failsafe_failure(self):
        with patch.object(kb.InputExecutor, "check_can_execute", return_value=self._ok_check()), \
             patch.object(kb, "hotkey", side_effect=InputFailSafeError("corner")):
            result = self.executor.hotkey("ctrl", "a", target_hwnd=1, dry_run=False)
        self.assertFalse(result.success)
        self.assertEqual("CANCELLED_FAILSAFE", result.status)

    def test_paste_text_returns_failsafe_failure(self):
        with patch.object(kb.InputExecutor, "check_can_execute", return_value=self._ok_check()), \
             patch.object(kb, "paste_text", side_effect=InputFailSafeError("corner")):
            result = self.executor.paste_text("secret", target_hwnd=1, dry_run=False)
        self.assertFalse(result.success)
        self.assertEqual("CANCELLED_FAILSAFE", result.status)

    def test_scroll_returns_failsafe_failure(self):
        with patch.object(kb.InputExecutor, "check_can_execute", return_value=self._ok_check()), \
             patch.object(kb.InputExecutor, "_check_point_obscured", return_value=None), \
             patch.object(kb, "scroll", side_effect=InputFailSafeError("corner")):
            result = self.executor.scroll(100, 200, 3, target_hwnd=1, dry_run=False)
        self.assertFalse(result.success)
        self.assertEqual("CANCELLED_FAILSAFE", result.status)

    def test_other_exceptions_still_propagate_from_executor(self):
        with patch.object(kb.InputExecutor, "check_can_execute", return_value=self._ok_check()), \
             patch.object(kb, "press_key", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.executor.press_key("f4", target_hwnd=1, dry_run=False)


if __name__ == "__main__":
    unittest.main()
