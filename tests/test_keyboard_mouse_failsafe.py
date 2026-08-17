"""LIVE pyautogui 路径的 fail-safe 语义化测试。

背景：pyautogui 0.9.54 的 press/hotkey/write/moveTo 内部会调用
failSafeCheck()——鼠标进入屏幕角落时抛 pyautogui.FailSafeException。
要求（Backward Compatible）：
- standalone press_key/hotkey/paste_text/scroll 一律原样抛
  pyautogui.FailSafeException，不包任何自定义异常层；其他异常也原样抛。
  （13685ae 引入的 InputFailSafeError 第二套异常层已被移除。）
- 只在 InputExecutor 的 press_key/hotkey/paste_text/scroll 四个方法边界
  捕获 pyautogui.FailSafeException，收敛为
  ActionResult(success=False, status='CANCELLED_FAILSAFE')。
- paste_text 在 FailSafeException 传播前仍执行剪贴板恢复/清空：
  saved_text 存在 → set_clipboard_text 调用顺序 [secret, prior]；
  saved_text=None → 清空剪贴板，绝不留密。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pyautogui  # noqa: E402

from shuabao.input import keyboard_mouse as kb  # noqa: E402
from shuabao.input.keyboard_mouse import ActionResult  # noqa: E402
from shuabao.stop_signal import StopSignal  # noqa: E402


class StandaloneFailSafePropagationTests(unittest.TestCase):
    """独立函数：FailSafeException 原样抛出（类型精确不变），其他异常原样抛出。"""

    def test_press_key_live_raises_exact_failsafe_exception(self):
        with patch.object(pyautogui, "press", side_effect=pyautogui.FailSafeException("corner")):
            with self.assertRaises(pyautogui.FailSafeException) as cm:
                kb.press_key("f4", dry_run=False)
        self.assertIs(
            type(cm.exception), pyautogui.FailSafeException,
            "standalone 必须原样抛 pyautogui.FailSafeException，不得包装",
        )

    def test_press_key_live_propagates_other_exceptions(self):
        with patch.object(pyautogui, "press", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError) as cm:
                kb.press_key("f4", dry_run=False)
        self.assertIs(type(cm.exception), RuntimeError, "其他异常必须原样抛出")

    def test_hotkey_live_raises_exact_failsafe_exception(self):
        with patch.object(pyautogui, "hotkey", side_effect=pyautogui.FailSafeException("corner")):
            with self.assertRaises(pyautogui.FailSafeException) as cm:
                kb.hotkey("ctrl", "a", dry_run=False)
        self.assertIs(type(cm.exception), pyautogui.FailSafeException)

    def test_hotkey_live_propagates_other_exceptions(self):
        with patch.object(pyautogui, "hotkey", side_effect=ValueError("bad key")):
            with self.assertRaises(ValueError) as cm:
                kb.hotkey("ctrl", "a", dry_run=False)
        self.assertIs(type(cm.exception), ValueError)

    def test_paste_text_live_raises_exact_failsafe_exception(self):
        with patch.object(kb, "get_clipboard_text", return_value="prior"), \
             patch.object(kb, "set_clipboard_text", return_value=True), \
             patch.object(pyautogui, "hotkey", side_effect=pyautogui.FailSafeException("corner")):
            with self.assertRaises(pyautogui.FailSafeException) as cm:
                kb.paste_text("secret", dry_run=False)
        self.assertIs(type(cm.exception), pyautogui.FailSafeException)

    def test_paste_text_live_propagates_other_exceptions(self):
        with patch.object(kb, "get_clipboard_text", return_value="prior"), \
             patch.object(kb, "set_clipboard_text", return_value=True), \
             patch.object(pyautogui, "hotkey", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError) as cm:
                kb.paste_text("secret", dry_run=False)
        self.assertIs(type(cm.exception), RuntimeError)

    def test_scroll_live_raises_exact_failsafe_exception(self):
        with patch.object(pyautogui, "moveTo", side_effect=pyautogui.FailSafeException("corner")):
            with self.assertRaises(pyautogui.FailSafeException) as cm:
                kb.scroll(100, 200, 3, dry_run=False)
        self.assertIs(type(cm.exception), pyautogui.FailSafeException)

    def test_scroll_live_propagates_other_exceptions(self):
        with patch.object(pyautogui, "moveTo", side_effect=OSError("bad")):
            with self.assertRaises(OSError) as cm:
                kb.scroll(100, 200, 3, dry_run=False)
        self.assertIs(type(cm.exception), OSError)

    def test_dry_run_never_touches_pyautogui(self):
        with patch.object(pyautogui, "press", side_effect=AssertionError("must not call")):
            kb.press_key("f4", dry_run=True)
        with patch.object(pyautogui, "hotkey", side_effect=AssertionError("must not call")):
            kb.hotkey("ctrl", "a", dry_run=True)
        with patch.object(pyautogui, "moveTo", side_effect=AssertionError("must not call")):
            kb.scroll(1, 2, 3, dry_run=True)
        kb.paste_text("", dry_run=False)  # 空文本不触碰 pyautogui


class PasteTextClipboardRestoreTests(unittest.TestCase):
    """paste_text 的 FailSafeException 传播前必须完成剪贴板恢复/清空。"""

    def test_failsafe_with_prior_clipboard_restores_in_secret_then_prior_order(self):
        calls: list[str] = []

        def fake_set(text: str) -> bool:
            calls.append(text)
            return True

        with patch.object(kb, "get_clipboard_text", return_value="prior"), \
             patch.object(kb, "set_clipboard_text", side_effect=fake_set), \
             patch.object(pyautogui, "hotkey", side_effect=pyautogui.FailSafeException("corner")):
            with self.assertRaises(pyautogui.FailSafeException):
                kb.paste_text("secret", dry_run=False)
        self.assertEqual(["secret", "prior"], calls, "必须先写入 secret，再在 finally 恢复 prior")

    def test_failsafe_without_prior_clipboard_clears_clipboard(self):
        with patch.object(kb, "get_clipboard_text", return_value=None), \
             patch.object(kb, "set_clipboard_text", return_value=True), \
             patch.object(kb, "_clear_clipboard") as clear_mock, \
             patch.object(pyautogui, "hotkey", side_effect=pyautogui.FailSafeException("corner")):
            with self.assertRaises(pyautogui.FailSafeException):
                kb.paste_text("secret", dry_run=False)
        clear_mock.assert_called_once_with()

    def test_write_fallback_failsafe_also_clears_clipboard(self):
        # set_clipboard_text 失败 → pyautogui.write 路径同样受 FailSafe 保护
        with patch.object(kb, "get_clipboard_text", return_value=None), \
             patch.object(kb, "set_clipboard_text", return_value=False), \
             patch.object(kb, "_clear_clipboard") as clear_mock, \
             patch.object(pyautogui, "write", side_effect=pyautogui.FailSafeException("corner")):
            with self.assertRaises(pyautogui.FailSafeException):
                kb.paste_text("secret", dry_run=False)
        clear_mock.assert_called_once_with()

    def test_restore_failure_after_failsafe_clears_clipboard(self):
        # Major confidentiality：secret 已写入剪贴板，pyautogui FailSafe 退出后
        # 恢复 prior 失败（set_clipboard_text 返回 False）→ 必须 _clear_clipboard 兜底，
        # 绝不让 secret 留在系统剪贴板。
        def fake_set(text: str) -> bool:
            return text == "secret"  # secret 写入成功，prior 恢复失败

        with patch.object(kb, "get_clipboard_text", return_value="prior"), \
             patch.object(kb, "set_clipboard_text", side_effect=fake_set), \
             patch.object(kb, "_clear_clipboard") as clear_mock, \
             patch.object(pyautogui, "hotkey", side_effect=pyautogui.FailSafeException("corner")):
            with self.assertRaises(pyautogui.FailSafeException):
                kb.paste_text("secret", dry_run=False)
        clear_mock.assert_called_once_with()

    def test_restore_failure_after_normal_paste_clears_clipboard(self):
        # 正常退出（hotkey 成功）后恢复 prior 失败同样必须清空
        def fake_set(text: str) -> bool:
            return text == "secret"

        with patch.object(kb, "get_clipboard_text", return_value="prior"), \
             patch.object(kb, "set_clipboard_text", side_effect=fake_set), \
             patch.object(kb, "_clear_clipboard") as clear_mock, \
             patch.object(pyautogui, "hotkey"):
            kb.paste_text("secret", dry_run=False)
        clear_mock.assert_called_once_with()

    def test_restore_failure_after_other_exception_clears_clipboard(self):
        # 非 FailSafe 异常退出同样先清空剪贴板，再原样传播异常
        def fake_set(text: str) -> bool:
            return text == "secret"

        with patch.object(kb, "get_clipboard_text", return_value="prior"), \
             patch.object(kb, "set_clipboard_text", side_effect=fake_set), \
             patch.object(kb, "_clear_clipboard") as clear_mock, \
             patch.object(pyautogui, "hotkey", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                kb.paste_text("secret", dry_run=False)
        clear_mock.assert_called_once_with()

    def test_restore_success_does_not_clear_clipboard(self):
        # 恢复成功 → 不额外清空（prior 内容保留，且不误伤其他剪贴板内容）
        with patch.object(kb, "get_clipboard_text", return_value="prior"), \
             patch.object(kb, "set_clipboard_text", return_value=True), \
             patch.object(kb, "_clear_clipboard") as clear_mock, \
             patch.object(pyautogui, "hotkey"):
            kb.paste_text("secret", dry_run=False)
        clear_mock.assert_not_called()


class ClearClipboardResultTests(unittest.TestCase):
    """_clear_clipboard 只在 Open+Empty+Close 全成功时返回 True。"""

    def _user32(self, open_ok=True, empty_ok=True, close_ok=True):
        user32 = MagicMock()
        user32.OpenClipboard.return_value = open_ok
        user32.EmptyClipboard.return_value = empty_ok
        user32.CloseClipboard.return_value = close_ok
        return user32

    def test_clear_returns_true_when_open_empty_close_succeed(self):
        user32 = self._user32()
        with patch("ctypes.windll.user32", user32):
            self.assertTrue(kb._clear_clipboard())
        user32.OpenClipboard.assert_called_once()
        user32.EmptyClipboard.assert_called_once()
        user32.CloseClipboard.assert_called()

    def test_clear_returns_false_when_open_fails(self):
        user32 = self._user32(open_ok=False)
        with patch("ctypes.windll.user32", user32):
            self.assertFalse(kb._clear_clipboard())
        user32.EmptyClipboard.assert_not_called()
        user32.CloseClipboard.assert_not_called()

    def test_clear_returns_false_when_empty_fails_and_still_closes(self):
        user32 = self._user32(empty_ok=False)
        with patch("ctypes.windll.user32", user32):
            self.assertFalse(kb._clear_clipboard())
        user32.CloseClipboard.assert_called()

    def test_clear_returns_false_on_exception_and_closes_if_opened(self):
        user32 = self._user32()
        user32.EmptyClipboard.side_effect = OSError("boom")
        with patch("ctypes.windll.user32", user32):
            self.assertFalse(kb._clear_clipboard())
        user32.CloseClipboard.assert_called()


class PasteTextClearWarningTests(unittest.TestCase):
    """prior 未知或 restore 失败时，clear 失败必须打出 [input] WARNING。"""

    def test_restore_failure_and_clear_failure_prints_input_warning(self):
        def fake_set(text: str) -> bool:
            return text == "secret"

        with patch.object(kb, "get_clipboard_text", return_value="prior"), \
             patch.object(kb, "set_clipboard_text", side_effect=fake_set), \
             patch.object(kb, "_clear_clipboard", return_value=False), \
             patch.object(pyautogui, "hotkey"), \
             patch("builtins.print") as printed:
            kb.paste_text("secret", dry_run=False)
        joined = " ".join(str(call) for call in printed.call_args_list)
        self.assertIn("[input] WARNING", joined)
        self.assertIn("无法清空", joined)
        self.assertIn("敏感", joined)

    def test_prior_none_and_clear_failure_prints_input_warning(self):
        with patch.object(kb, "get_clipboard_text", return_value=None), \
             patch.object(kb, "set_clipboard_text", return_value=True), \
             patch.object(kb, "_clear_clipboard", return_value=False), \
             patch.object(pyautogui, "hotkey"), \
             patch("builtins.print") as printed:
            kb.paste_text("secret", dry_run=False)
        joined = " ".join(str(call) for call in printed.call_args_list)
        self.assertIn("[input] WARNING", joined)
        self.assertIn("无法清空", joined)
        self.assertIn("敏感", joined)

    def test_restore_success_does_not_print_clear_warning(self):
        with patch.object(kb, "get_clipboard_text", return_value="prior"), \
             patch.object(kb, "set_clipboard_text", return_value=True), \
             patch.object(kb, "_clear_clipboard", return_value=False), \
             patch.object(pyautogui, "hotkey"), \
             patch("builtins.print") as printed:
            kb.paste_text("secret", dry_run=False)
        joined = " ".join(str(call) for call in printed.call_args_list)
        self.assertNotIn("[input] WARNING", joined)


class ExecutorFailSafeActionTests(unittest.TestCase):
    """InputExecutor 四方法边界：FailSafeException → CANCELLED_FAILSAFE。"""

    def setUp(self):
        self.executor = kb.InputExecutor(StopSignal())

    def _ok_check(self, target_hwnd=None, dry_run=True):
        return ActionResult(success=True, status="OK", message="ok")

    def test_press_key_returns_failsafe_failure(self):
        with patch.object(kb.InputExecutor, "check_can_execute", return_value=self._ok_check()), \
             patch.object(kb, "press_key", side_effect=pyautogui.FailSafeException("corner")):
            result = self.executor.press_key("f4", target_hwnd=1, dry_run=False)
        self.assertFalse(result.success)
        self.assertEqual("CANCELLED_FAILSAFE", result.status)
        self.assertIn("f4", result.message)

    def test_hotkey_returns_failsafe_failure(self):
        with patch.object(kb.InputExecutor, "check_can_execute", return_value=self._ok_check()), \
             patch.object(kb, "hotkey", side_effect=pyautogui.FailSafeException("corner")):
            result = self.executor.hotkey("ctrl", "a", target_hwnd=1, dry_run=False)
        self.assertFalse(result.success)
        self.assertEqual("CANCELLED_FAILSAFE", result.status)

    def test_paste_text_returns_failsafe_failure(self):
        with patch.object(kb.InputExecutor, "check_can_execute", return_value=self._ok_check()), \
             patch.object(kb, "paste_text", side_effect=pyautogui.FailSafeException("corner")):
            result = self.executor.paste_text("secret", target_hwnd=1, dry_run=False)
        self.assertFalse(result.success)
        self.assertEqual("CANCELLED_FAILSAFE", result.status)

    def test_scroll_returns_failsafe_failure(self):
        with patch.object(kb.InputExecutor, "check_can_execute", return_value=self._ok_check()), \
             patch.object(kb.InputExecutor, "_check_point_obscured", return_value=None), \
             patch.object(kb, "scroll", side_effect=pyautogui.FailSafeException("corner")):
            result = self.executor.scroll(100, 200, 3, target_hwnd=1, dry_run=False)
        self.assertFalse(result.success)
        self.assertEqual("CANCELLED_FAILSAFE", result.status)

    def test_other_exceptions_still_propagate_from_executor(self):
        with patch.object(kb.InputExecutor, "check_can_execute", return_value=self._ok_check()), \
             patch.object(kb, "press_key", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.executor.press_key("f4", target_hwnd=1, dry_run=False)

    def test_paste_text_end_to_end_failsafe_converges_and_restores_clipboard(self):
        # 真实 standalone paste_text 链路：FailSafeException 从 pyautogui 一路
        # 传到 executor 边界，收敛为 CANCELLED_FAILSAFE，且剪贴板已按序恢复。
        calls: list[str] = []

        def fake_set(text: str) -> bool:
            calls.append(text)
            return True

        with patch.object(kb.InputExecutor, "check_can_execute", return_value=self._ok_check()), \
             patch.object(kb, "get_clipboard_text", return_value="prior"), \
             patch.object(kb, "set_clipboard_text", side_effect=fake_set), \
             patch.object(pyautogui, "hotkey", side_effect=pyautogui.FailSafeException("corner")):
            result = self.executor.paste_text("secret", target_hwnd=1, dry_run=False)
        self.assertFalse(result.success)
        self.assertEqual("CANCELLED_FAILSAFE", result.status)
        self.assertEqual(["secret", "prior"], calls)


if __name__ == "__main__":
    unittest.main()
