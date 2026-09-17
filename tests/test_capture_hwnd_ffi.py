"""Regression: a real 64-bit HWND must survive the Win32 FFI boundary.

Live evidence 2026-09-17: ``find_window_targets`` died with OverflowError
inside EnumWindows because ``ctypes.windll.user32`` had no argtypes, so a
pointer-sized handle was pushed through the default ``c_int`` argument.  The
fix declares the real signatures; handles are never clamped or truncated.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

import pytest

from shuabao.vision import capture

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Win32 FFI boundary")

# A plausible x64 user-mode handle. Above 2**31, which is exactly what the
# default c_int argument cannot represent.
HIGH_HWND = 0x00007FFE12345678


def test_untyped_user32_overflows_on_64bit_handle():
    """Pin the root cause: a fresh, untyped user32 still rejects the handle."""
    untyped = ctypes.WinDLL("user32")
    with pytest.raises(ctypes.ArgumentError) as excinfo:
        untyped.IsWindowVisible(HIGH_HWND)
    assert "OverflowError" in str(excinfo.value)


def test_typed_user32_passes_64bit_handle_to_win32():
    user32 = capture._typed_user32()
    # Reaches Win32 and answers "not a window" instead of raising.
    assert user32.IsWindowVisible(HIGH_HWND) == 0
    assert user32.IsWindow(HIGH_HWND) == 0
    # Idempotent: a second call must not re-declare into a broken state.
    assert capture._typed_user32().IsIconic(HIGH_HWND) == 0


def test_enum_windows_callback_visits_real_handles():
    """Live: a BOOL callback keeps enumerating; a c_bool one stops early."""
    user32 = capture._typed_user32()
    seen: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def enum_proc(hwnd, _lparam):
        seen.append(int(hwnd))
        return True

    assert user32.EnumWindows(enum_proc, 0)
    assert len(seen) >= 2
    assert all(hwnd > 0 for hwnd in seen)


def test_find_window_targets_reports_the_full_handle(monkeypatch):
    """The enumerated handle reaches WindowTarget without losing its high bits."""

    class FakeUser32:
        def IsWindowVisible(self, hwnd):
            return 1

        def IsIconic(self, hwnd):
            return 0

        def GetWindowTextLengthW(self, hwnd):
            return len("英雄三国")

        def GetWindowTextW(self, hwnd, buf, size):
            buf.value = "英雄三国"
            return len(buf.value)

        def GetWindowRect(self, hwnd, ref):
            rect = ref._obj
            rect.left, rect.top, rect.right, rect.bottom = 0, 0, 1600, 900
            return 1

        def EnumWindows(self, callback, lparam):
            callback(HIGH_HWND, lparam)
            return 1

        def GetForegroundWindow(self):
            return 0

    monkeypatch.setattr(capture, "_user32", FakeUser32())
    targets = capture.find_window_targets("英雄三国")
    assert [target.hwnd for target in targets] == [HIGH_HWND]
    assert targets[0].width == 1600 and targets[0].height == 900
