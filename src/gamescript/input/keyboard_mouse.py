"""键鼠执行器（支持窗口校验、前台监控、全局急停取消与剪贴板恢复）。"""

from __future__ import annotations

from dataclasses import dataclass
import time

from gamescript.stop_signal import StopSignal
from gamescript.vision.capture import activate_window, is_window_valid


@dataclass
class ActionResult:
    success: bool
    status: str
    message: str = ""


def get_foreground_window() -> int | None:
    """Return current foreground window HWND."""
    try:
        import ctypes

        hwnd = int(ctypes.windll.user32.GetForegroundWindow())
        return hwnd if hwnd > 0 else None
    except Exception:
        return None


def get_clipboard_text() -> str | None:
    """Retrieve text from Win32 clipboard."""
    try:
        import ctypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        if not user32.OpenClipboard(None):
            return None
        try:
            handle = user32.GetClipboardData(13)  # CF_UNICODETEXT
            if not handle:
                return None
            pointer = kernel32.GlobalLock(handle)
            if not pointer:
                return None
            try:
                text = ctypes.wstring_at(pointer)
                return text
            finally:
                kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()
    except Exception:
        return None


def set_clipboard_text(text: str) -> bool:
    """Set Win32 clipboard text."""
    try:
        import ctypes

        data = (text + "\0").encode("utf-16-le")
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        kernel32.GlobalAlloc.restype = ctypes.c_void_p
        kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
        user32.SetClipboardData.restype = ctypes.c_void_p

        if not user32.OpenClipboard(None):
            return False
        try:
            user32.EmptyClipboard()
            if not text:
                return True
            handle = kernel32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
            if not handle:
                return False
            pointer = kernel32.GlobalLock(handle)
            if not pointer:
                kernel32.GlobalFree(handle)
                return False
            ctypes.memmove(pointer, data, len(data))
            kernel32.GlobalUnlock(handle)
            if not user32.SetClipboardData(13, handle):  # CF_UNICODETEXT
                kernel32.GlobalFree(handle)
                return False
            return True
        finally:
            user32.CloseClipboard()
    except Exception:
        return False


class InputExecutor:
    """Cancellable input executor with target window & foreground verification."""

    def __init__(self, stop_signal: StopSignal | None = None) -> None:
        self.stop_signal = stop_signal or StopSignal()

    def check_can_execute(self, target_hwnd: int | None = None, dry_run: bool = True) -> ActionResult:
        if self.stop_signal.is_set():
            return ActionResult(
                success=False,
                status="CANCELLED_EMERGENCY_STOP",
                message=f"Action cancelled by stop signal: {self.stop_signal.reason}",
            )
        if dry_run:
            return ActionResult(success=True, status="DRY_RUN", message="Dry run mode")

        if target_hwnd is not None:
            if not is_window_valid(target_hwnd):
                return ActionResult(
                    success=False,
                    status="CANCELLED_WINDOW_INVALID",
                    message=f"Target window {target_hwnd} is missing, minimized, or invalid",
                )
            fg = get_foreground_window()
            if fg != target_hwnd:
                activate_window(target_hwnd)
                fg = get_foreground_window()
                if fg != target_hwnd:
                    return ActionResult(
                        success=False,
                        status="CANCELLED_WINDOW_CHANGED",
                        message=f"Target window {target_hwnd} is not foreground (current={fg})",
                    )
        return ActionResult(success=True, status="OK", message="Window verified")

    def click(self, x: int, y: int, target_hwnd: int | None = None, dry_run: bool = True, delay_ms: int = 120) -> ActionResult:
        check = self.check_can_execute(target_hwnd, dry_run=dry_run)
        if not check.success:
            print(f"[input] click ({x}, {y}) CANCELLED: {check.message}")
            return check

        click(x, y, dry_run=dry_run, delay_ms=delay_ms)

        if not dry_run and target_hwnd is not None:
            fg = get_foreground_window()
            if fg != target_hwnd:
                return ActionResult(
                    success=False,
                    status="CANCELLED_WINDOW_CHANGED",
                    message=f"Foreground window changed after click from {target_hwnd} to {fg}",
                )
        return ActionResult(success=True, status="SUCCESS", message=f"Clicked ({x}, {y})")

    def right_click(self, x: int, y: int, target_hwnd: int | None = None, dry_run: bool = True, delay_ms: int = 120) -> ActionResult:
        check = self.check_can_execute(target_hwnd, dry_run=dry_run)
        if not check.success:
            print(f"[input] right_click ({x}, {y}) CANCELLED: {check.message}")
            return check

        right_click(x, y, dry_run=dry_run, delay_ms=delay_ms)
        return ActionResult(success=True, status="SUCCESS", message=f"Right-clicked ({x}, {y})")

    def press_key(self, key: str, target_hwnd: int | None = None, dry_run: bool = True) -> ActionResult:
        check = self.check_can_execute(target_hwnd, dry_run=dry_run)
        if not check.success:
            print(f"[input] press_key {key!r} CANCELLED: {check.message}")
            return check

        press_key(key, dry_run=dry_run)
        return ActionResult(success=True, status="SUCCESS", message=f"Pressed key {key}")

    def hotkey(self, *keys: str, target_hwnd: int | None = None, dry_run: bool = True) -> ActionResult:
        check = self.check_can_execute(target_hwnd, dry_run=dry_run)
        if not check.success:
            print(f"[input] hotkey {keys!r} CANCELLED: {check.message}")
            return check

        hotkey(*keys, dry_run=dry_run)
        return ActionResult(success=True, status="SUCCESS", message=f"Pressed hotkey {keys}")

    def paste_text(self, text: str, target_hwnd: int | None = None, dry_run: bool = True) -> ActionResult:
        check = self.check_can_execute(target_hwnd, dry_run=dry_run)
        if not check.success:
            print(f"[input] paste_text CANCELLED: {check.message}")
            return check

        paste_text(text, dry_run=dry_run)
        return ActionResult(success=True, status="SUCCESS", message="Pasted text with clipboard preservation")

    def scroll(self, x: int, y: int, clicks: int, target_hwnd: int | None = None, dry_run: bool = True) -> ActionResult:
        check = self.check_can_execute(target_hwnd, dry_run=dry_run)
        if not check.success:
            print(f"[input] scroll CANCELLED: {check.message}")
            return check

        scroll(x, y, clicks, dry_run=dry_run)
        return ActionResult(success=True, status="SUCCESS", message=f"Scrolled {clicks} at ({x}, {y})")


# ---------- Standalone functions (Backward Compatible) ----------

def click(x: int, y: int, dry_run: bool = True, delay_ms: int = 120) -> None:
    print(f"[input] click ({x}, {y}) dry_run={dry_run}")
    if dry_run:
        return
    import ctypes
    import pyautogui

    pyautogui.FAILSAFE = False
    pyautogui.moveTo(x, y, duration=0.05)
    user32 = ctypes.windll.user32
    user32.SetCursorPos(x, y)
    time.sleep(0.02)
    user32.mouse_event(0x0002, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTDOWN
    time.sleep(0.05)                        # 50ms press duration for Chromium/game UI
    user32.mouse_event(0x0004, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTUP
    time.sleep(delay_ms / 1000.0)


def right_click(x: int, y: int, dry_run: bool = True, delay_ms: int = 120) -> None:
    print(f"[input] right_click ({x}, {y}) dry_run={dry_run}")
    if dry_run:
        return
    import ctypes
    import pyautogui

    pyautogui.FAILSAFE = False
    pyautogui.moveTo(x, y, duration=0.05)
    user32 = ctypes.windll.user32
    user32.SetCursorPos(x, y)
    time.sleep(0.02)
    user32.mouse_event(0x0008, 0, 0, 0, 0)  # MOUSEEVENTF_RIGHTDOWN
    time.sleep(0.05)                        # 50ms press duration
    user32.mouse_event(0x0010, 0, 0, 0, 0)  # MOUSEEVENTF_RIGHTUP
    time.sleep(delay_ms / 1000.0)


def press_key(key: str, dry_run: bool = True) -> None:
    """key: e.g. 'f4', 'esc', 'z'."""
    print(f"[input] press_key {key!r} dry_run={dry_run}")
    if dry_run:
        return
    import pyautogui

    pyautogui.press(key)


def hotkey(*keys: str, dry_run: bool = True) -> None:
    """Press a key combination, for example ``ctrl+a``."""
    print(f"[input] hotkey {keys!r} dry_run={dry_run}")
    if dry_run:
        return
    import pyautogui

    pyautogui.hotkey(*keys)


def paste_text(text: str, dry_run: bool = True) -> None:
    """Paste text while preserving and restoring prior clipboard content."""
    print(f"[input] paste_text len={len(text)} dry_run={dry_run}")
    if dry_run or not text:
        return
    import pyautogui

    saved_text = get_clipboard_text()
    try:
        if set_clipboard_text(text):
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.05)
        else:
            pyautogui.write(text, interval=0.01)
    finally:
        if saved_text is not None:
            set_clipboard_text(saved_text)


def scroll(x: int, y: int, clicks: int, dry_run: bool = True) -> None:
    """Scroll at a screen point; positive values scroll up."""
    print(f"[input] scroll ({x}, {y}) clicks={clicks} dry_run={dry_run}")
    if dry_run:
        return
    import pyautogui

    pyautogui.moveTo(x, y, duration=0.05)
    pyautogui.scroll(clicks)
