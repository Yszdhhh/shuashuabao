"""Window-ownership authority for the input obscured gate.

Regression target: KK renders its UI in an embedded CEF/Chromium view, so
WindowFromPoint over the game surface returns a Chrome_RenderWidgetHostHWND
child whose PID differs from the KK top-level window. The obscured gate used to
compare only exact HWND / PID and cancelled every real click with
CANCELLED_WINDOW_OBSCURED.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes as w
import unittest
from unittest.mock import patch

from shuabao.input import keyboard_mouse as km
from shuabao.input.keyboard_mouse import InputExecutor, window_belongs_to_target

KK_ROOT = 31985540          # KK 官方对战平台 top-level HWND (real-machine value)
KK_CEF_CHILD = 37164458     # Chrome_RenderWidgetHostHWND child of KK_ROOT
KK_MODAL = 44556677         # create-room modal: own root, same process as KK
EXTERNAL_CHROME = 99001122  # a genuinely foreign top-level window

KK_PID = 4242
CEF_RENDERER_PID = 5353     # CEF renderer lives in its own process
CHROME_PID = 7777


def _fake_root(hwnd: int | None) -> int:
    return {
        KK_ROOT: KK_ROOT,
        KK_CEF_CHILD: KK_ROOT,
        KK_MODAL: KK_MODAL,
        EXTERNAL_CHROME: EXTERNAL_CHROME,
    }.get(int(hwnd or 0), 0)


def _fake_pid(hwnd: int | None) -> int:
    return {
        KK_ROOT: KK_PID,
        KK_CEF_CHILD: CEF_RENDERER_PID,
        KK_MODAL: KK_PID,
        EXTERNAL_CHROME: CHROME_PID,
    }.get(int(hwnd or 0), 0)


class WindowOwnershipTests(unittest.TestCase):
    """window_belongs_to_target(): the single ownership authority."""

    def setUp(self) -> None:
        root = patch.object(km, "_window_root", side_effect=_fake_root)
        pid = patch.object(km, "_window_pid", side_effect=_fake_pid)
        root.start()
        pid.start()
        self.addCleanup(root.stop)
        self.addCleanup(pid.stop)

    def test_cef_renderer_child_belongs_to_target_despite_foreign_pid(self) -> None:
        self.assertTrue(window_belongs_to_target(KK_ROOT, KK_CEF_CHILD))

    def test_exact_target_belongs(self) -> None:
        self.assertTrue(window_belongs_to_target(KK_ROOT, KK_ROOT))

    def test_same_process_modal_still_belongs(self) -> None:
        self.assertTrue(window_belongs_to_target(KK_ROOT, KK_MODAL))

    def test_external_window_does_not_belong(self) -> None:
        self.assertFalse(window_belongs_to_target(KK_ROOT, EXTERNAL_CHROME))

    def test_none_does_not_belong(self) -> None:
        self.assertFalse(window_belongs_to_target(KK_ROOT, None))

    def test_unresolvable_ancestry_fails_closed(self) -> None:
        """Both roots unknown (0) must not read as 'same tree'."""
        with patch.object(km, "_window_root", return_value=0), \
             patch.object(km, "_window_pid", return_value=0):
            self.assertFalse(window_belongs_to_target(KK_ROOT, KK_CEF_CHILD))


class CheckPointObscuredTests(unittest.TestCase):
    """_check_point_obscured(): what actually gates SendInput."""

    def setUp(self) -> None:
        self.executor = InputExecutor()
        root = patch.object(km, "_window_root", side_effect=_fake_root)
        pid = patch.object(km, "_window_pid", side_effect=_fake_pid)
        root.start()
        pid.start()
        self.addCleanup(root.stop)
        self.addCleanup(pid.stop)

    def _obscured_at(self, hit_hwnd: int):
        with patch.object(ctypes.windll.user32, "WindowFromPoint", return_value=hit_hwnd):
            return self.executor._check_point_obscured(KK_ROOT, 1746, 331)

    def test_case1_kk_cef_child_is_not_obscuring(self) -> None:
        self.assertIsNone(self._obscured_at(KK_CEF_CHILD))

    def test_case2_external_chrome_is_obscuring(self) -> None:
        result = self._obscured_at(EXTERNAL_CHROME)
        self.assertIsNotNone(result)
        self.assertFalse(result.success)
        self.assertEqual(result.status, "CANCELLED_WINDOW_OBSCURED")

    def test_case3_exact_target_is_not_obscuring(self) -> None:
        self.assertIsNone(self._obscured_at(KK_ROOT))

    def test_case4_same_process_modal_is_not_obscuring(self) -> None:
        self.assertIsNone(self._obscured_at(KK_MODAL))

    def test_null_hit_is_not_obscuring(self) -> None:
        self.assertIsNone(self._obscured_at(0))


def _find_visible_top_level_with_child() -> tuple[int, int] | None:
    """First visible top-level HWND that owns a child HWND, or None."""
    user32 = ctypes.windll.user32
    found: list[tuple[int, int]] = []
    GW_CHILD = 5
    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)

    def _visit(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        child = int(user32.GetWindow(hwnd, GW_CHILD) or 0)
        if child:
            found.append((int(hwnd), child))
            return False
        return True

    user32.EnumWindows(enum_proc(_visit), 0)
    return found[0] if found else None


class WindowRootWin32Tests(unittest.TestCase):
    """_window_root() against the real Win32 API (ctypes signature guard)."""

    def test_zero_and_none(self) -> None:
        self.assertEqual(km._window_root(0), 0)
        self.assertEqual(km._window_root(None), 0)

    def test_desktop_window_has_no_root(self) -> None:
        """GetAncestor(GA_ROOT) returns NULL for the desktop window by design."""
        desktop = int(ctypes.windll.user32.GetDesktopWindow())
        self.assertEqual(km._window_root(desktop), 0)

    def test_real_child_hwnd_resolves_to_its_top_level_root(self) -> None:
        """The exact shape of the KK bug: child HWND -> owning top-level HWND."""
        pair = _find_visible_top_level_with_child()
        if pair is None:
            self.skipTest("no visible top-level window with a child HWND on this desktop")
        top, child = pair
        self.assertNotEqual(child, top)
        self.assertEqual(km._window_root(child), top)

    def test_real_top_level_hwnd_is_its_own_root(self) -> None:
        pair = _find_visible_top_level_with_child()
        if pair is None:
            self.skipTest("no visible top-level window on this desktop")
        top, _child = pair
        self.assertEqual(km._window_root(top), top)


if __name__ == "__main__":
    unittest.main()
