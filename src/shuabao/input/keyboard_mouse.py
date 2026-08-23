"""键鼠执行器（支持窗口校验、前台监控、全局急停取消与剪贴板恢复）。"""

from __future__ import annotations

from dataclasses import dataclass
import time

from shuabao.stop_signal import StopSignal
from shuabao.vision.capture import is_window_valid, reacquire_target_window

__all__ = [
    "ActionResult",
    "InputExecutor",
    "reacquire_target_window",
    "foreground_matches_target",
    "get_clipboard_text",
    "get_foreground_window",
    "is_current_process_elevated",
    "is_window_valid",
]

@dataclass
class ActionResult:
    success: bool
    status: str
    message: str = ""


def _failsafe_action_result(exc: BaseException, action: str) -> ActionResult | None:
    """Map a pyautogui fail-safe to a CANCELLED_FAILSAFE result, else None.

    pyautogui is a LIVE-path-only dependency, imported lazily here so this
    module stays importable without it. Only pyautogui.FailSafeException is
    converted — every other exception is left to propagate untouched.
    """
    try:
        import pyautogui
    except Exception:
        return None
    if isinstance(exc, pyautogui.FailSafeException):
        return ActionResult(
            success=False,
            status="CANCELLED_FAILSAFE",
            message=f"Fail-safe triggered during {action}: {exc}",
        )
    return None


def _clear_clipboard() -> bool:
    opened = False
    user32 = None
    try:
        import ctypes

        user32 = ctypes.windll.user32
        if not user32.OpenClipboard(0):
            return False
        opened = True
        emptied = bool(user32.EmptyClipboard())
        closed = bool(user32.CloseClipboard())
        opened = False
        return emptied and closed
    except Exception:
        return False
    finally:
        if opened and user32 is not None:
            try:
                user32.CloseClipboard()
            except Exception:
                pass


def is_current_process_elevated() -> bool:
    """True when this process has an elevated (admin) token.

    ShuaBao requires requireAdministrator. KK platform is also
    typically elevated; Windows UIPI drops mouse/keyboard injection from a
    medium-IL process into a high-IL target (SendInput returns success, UI
    ignores the click). Real input therefore requires elevation.
    """
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def get_foreground_window() -> int | None:
    """Return current foreground window HWND."""
    try:
        import ctypes

        hwnd = int(ctypes.windll.user32.GetForegroundWindow())
        return hwnd or None
    except Exception:
        return None


def _window_pid(hwnd: int | None) -> int:
    """PID for hwnd; 0 if unknown."""
    if not hwnd:
        return 0
    try:
        import ctypes
        from ctypes import wintypes as w

        pid = w.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(int(hwnd), ctypes.byref(pid))
        return int(pid.value)
    except Exception:
        return 0


def foreground_matches_target(target_hwnd: int, fg: int | None) -> bool:
    """True if fg is target, or another top-level window of the same process.

    KK create-room is a separate Qt HWND in the Platform process; requiring an
    exact HWND match rejects valid clicks after the dialog steals focus.
    """
    if fg is None:
        return False
    if int(fg) == int(target_hwnd):
        return True
    tp = _window_pid(target_hwnd)
    fp = _window_pid(fg)
    return tp > 0 and tp == fp


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
        if self.stop_signal and (self.stop_signal.is_set() or self.stop_signal.is_stopped()):
            return ActionResult(
                success=False,
                status="CANCELLED_EMERGENCY_STOP",
                message=f"Action cancelled by stop signal: {self.stop_signal.reason}",
            )
        if dry_run:
            return ActionResult(success=True, status="DRY_RUN", message="Dry run mode")

        if not is_current_process_elevated():
            return ActionResult(
                success=False,
                status="CANCELLED_NOT_ELEVATED",
                message=(
                    "Real input rejected: process is not elevated. "
                    "KK/ShuaBao run as admin; UIPI drops SendInput from a non-admin script. "
                    "Relaunch ShuaBao with 'Run as administrator'."
                ),
            )

        if not target_hwnd or target_hwnd <= 0:
            return ActionResult(
                success=False,
                status="CANCELLED_NO_TARGET_HWND",
                message="Real input rejected: target_hwnd is required when dry_run=False",
            )

        if not is_window_valid(target_hwnd):
            return ActionResult(
                success=False,
                status="CANCELLED_WINDOW_INVALID",
                message=f"Target window {target_hwnd} is missing, minimized, or invalid",
            )
        fg = get_foreground_window()
        if not foreground_matches_target(target_hwnd, fg):
            return ActionResult(
                success=False,
                status="CANCELLED_WINDOW_CHANGED",
                message=f"Target window {target_hwnd} is not foreground (current={fg}); input paused without activating it",
            )
        return ActionResult(success=True, status="OK", message="Window verified")

    def _post_check(self, target_hwnd: int | None, dry_run: bool) -> ActionResult | None:
        if self.stop_signal and (self.stop_signal.is_set() or self.stop_signal.is_stopped()):
            return ActionResult(
                success=False,
                status="CANCELLED_EMERGENCY_STOP",
                message=f"Emergency stop active after action: {self.stop_signal.reason}",
            )
        if not dry_run and target_hwnd is not None:
            fg = get_foreground_window()
            if not foreground_matches_target(target_hwnd, fg):
                return ActionResult(
                    success=False,
                    status="CANCELLED_WINDOW_CHANGED",
                    message=f"Foreground window changed after action from {target_hwnd} to {fg}",
                )
        return None

    def _check_point_obscured(self, target_hwnd: int, x: int, y: int) -> ActionResult | None:
        """Reject clicks whose screen point is covered by a foreign window.

        Real-machine failure mode: game window partially covered by editor/
        terminal; SendInput lands on the covering window and the game never
        reacts. WindowFromPoint tells us the topmost window at the click point.
        """
        try:
            import ctypes
            from ctypes import wintypes as w

            pt = w.POINT(int(x), int(y))
            top = int(ctypes.windll.user32.WindowFromPoint(pt))
        except Exception:
            return None
        if top == 0:
            return None
        if foreground_matches_target(target_hwnd, top):
            return None
        return ActionResult(
            success=False,
            status="CANCELLED_WINDOW_OBSCURED",
            message=(
                f"Click point ({x},{y}) is covered by another window (hwnd={top}). "
                "Move editors/terminals off the game window or bring the game to front."
            ),
        )

    def click(self, x: int, y: int, target_hwnd: int | None = None, dry_run: bool = True, delay_ms: int = 120) -> ActionResult:
        check = self.check_can_execute(target_hwnd, dry_run=dry_run)
        if not check.success:
            print(f"[input] click ({x}, {y}) CANCELLED: {check.message}")
            return check
        if not dry_run and target_hwnd:
            obscured = self._check_point_obscured(target_hwnd, x, y)
            if obscured:
                print(f"[input] click ({x}, {y}) CANCELLED: {obscured.message}")
                return obscured
        if self.stop_signal and (self.stop_signal.is_set() or self.stop_signal.is_stopped()):
            return ActionResult(
                success=False,
                status="CANCELLED_EMERGENCY_STOP",
                message=f"Action cancelled by stop signal: {self.stop_signal.reason}",
            )
        injected = click(x, y, dry_run=dry_run, delay_ms=delay_ms)
        if not dry_run and not injected:
            return ActionResult(
                success=False,
                status="CANCELLED_SENDINPUT_FAILED",
                message=f"SendInput did not inject click at ({x}, {y})",
            )
        post = self._post_check(target_hwnd, dry_run)
        if post:
            return post
        status = "DRY_RUN" if dry_run else "SUCCESS"
        return ActionResult(success=True, status=status, message=f"Clicked ({x}, {y})")

    def right_click(self, x: int, y: int, target_hwnd: int | None = None, dry_run: bool = True, delay_ms: int = 120) -> ActionResult:
        check = self.check_can_execute(target_hwnd, dry_run=dry_run)
        if not check.success:
            print(f"[input] right_click ({x}, {y}) CANCELLED: {check.message}")
            return check
        if not dry_run and target_hwnd:
            obscured = self._check_point_obscured(target_hwnd, x, y)
            if obscured:
                print(f"[input] right_click ({x}, {y}) CANCELLED: {obscured.message}")
                return obscured
        if self.stop_signal and (self.stop_signal.is_set() or self.stop_signal.is_stopped()):
            return ActionResult(
                success=False,
                status="CANCELLED_EMERGENCY_STOP",
                message=f"Action cancelled by stop signal: {self.stop_signal.reason}",
            )
        injected = right_click(x, y, dry_run=dry_run, delay_ms=delay_ms)
        if not dry_run and not injected:
            return ActionResult(
                success=False,
                status="CANCELLED_SENDINPUT_FAILED",
                message=f"SendInput did not inject right-click at ({x}, {y})",
            )
        post = self._post_check(target_hwnd, dry_run)
        if post:
            return post
        status = "DRY_RUN" if dry_run else "SUCCESS"
        return ActionResult(success=True, status=status, message=f"Right-clicked ({x}, {y})")

    def press_key(self, key: str, target_hwnd: int | None = None, dry_run: bool = True) -> ActionResult:
        check = self.check_can_execute(target_hwnd, dry_run=dry_run)
        if not check.success:
            print(f"[input] press_key {key!r} CANCELLED: {check.message}")
            return check
        if self.stop_signal and (self.stop_signal.is_set() or self.stop_signal.is_stopped()):
            return ActionResult(
                success=False,
                status="CANCELLED_EMERGENCY_STOP",
                message=f"Action cancelled by stop signal: {self.stop_signal.reason}",
            )
        try:
            press_key(key, dry_run=dry_run)
        except Exception as exc:
            result = _failsafe_action_result(exc, f"press_key({key!r})")
            if result is not None:
                return result
            raise
        post = self._post_check(target_hwnd, dry_run)
        if post:
            return post
        status = "DRY_RUN" if dry_run else "SUCCESS"
        return ActionResult(success=True, status=status, message=f"Pressed key {key}")

    def hotkey(self, *keys: str, target_hwnd: int | None = None, dry_run: bool = True) -> ActionResult:
        check = self.check_can_execute(target_hwnd, dry_run=dry_run)
        if not check.success:
            print(f"[input] hotkey {keys!r} CANCELLED: {check.message}")
            return check
        if self.stop_signal and (self.stop_signal.is_set() or self.stop_signal.is_stopped()):
            return ActionResult(
                success=False,
                status="CANCELLED_EMERGENCY_STOP",
                message=f"Action cancelled by stop signal: {self.stop_signal.reason}",
            )
        try:
            hotkey(*keys, dry_run=dry_run)
        except Exception as exc:
            result = _failsafe_action_result(exc, f"hotkey({keys!r})")
            if result is not None:
                return result
            raise
        post = self._post_check(target_hwnd, dry_run)
        if post:
            return post
        status = "DRY_RUN" if dry_run else "SUCCESS"
        return ActionResult(success=True, status=status, message=f"Pressed hotkey {keys}")

    def paste_text(self, text: str, target_hwnd: int | None = None, dry_run: bool = True) -> ActionResult:
        check = self.check_can_execute(target_hwnd, dry_run=dry_run)
        if not check.success:
            print(f"[input] paste_text CANCELLED: {check.message}")
            return check
        if self.stop_signal and (self.stop_signal.is_set() or self.stop_signal.is_stopped()):
            return ActionResult(
                success=False,
                status="CANCELLED_EMERGENCY_STOP",
                message=f"Action cancelled by stop signal: {self.stop_signal.reason}",
            )
        try:
            paste_text(text, dry_run=dry_run)
        except Exception as exc:
            result = _failsafe_action_result(exc, "paste_text")
            if result is not None:
                return result
            raise
        post = self._post_check(target_hwnd, dry_run)
        if post:
            return post
        status = "DRY_RUN" if dry_run else "SUCCESS"
        return ActionResult(success=True, status=status, message="Pasted text with clipboard preservation")

    def scroll(self, x: int, y: int, clicks: int, target_hwnd: int | None = None, dry_run: bool = True) -> ActionResult:
        check = self.check_can_execute(target_hwnd, dry_run=dry_run)
        if not check.success:
            print(f"[input] scroll CANCELLED: {check.message}")
            return check
        if not dry_run and target_hwnd:
            obscured = self._check_point_obscured(target_hwnd, x, y)
            if obscured:
                print(f"[input] scroll ({x}, {y}) CANCELLED: {obscured.message}")
        if self.stop_signal and (self.stop_signal.is_set() or self.stop_signal.is_stopped()):
            return ActionResult(
                success=False,
                status="CANCELLED_EMERGENCY_STOP",
                message=f"Action cancelled by stop signal: {self.stop_signal.reason}",
            )
        try:
            scroll(x, y, clicks, dry_run=dry_run)
        except Exception as exc:
            result = _failsafe_action_result(exc, f"scroll at ({x}, {y})")
            if result is not None:
                return result
            raise
        post = self._post_check(target_hwnd, dry_run)
        if post:
            return post
        status = "DRY_RUN" if dry_run else "SUCCESS"
        return ActionResult(success=True, status=status, message=f"Scrolled {clicks} at ({x}, {y})")

    def type_text(self, text: str, target_hwnd: int | None = None, dry_run: bool = True) -> ActionResult:
        """Type literal characters (digits/ascii) via key events — more reliable than paste in CEF."""
        check = self.check_can_execute(target_hwnd, dry_run=dry_run)
        if not check.success:
            print(f"[input] type_text CANCELLED: {check.message}")
            return check
        if self.stop_signal and (self.stop_signal.is_set() or self.stop_signal.is_stopped()):
            return ActionResult(
                success=False,
                status="CANCELLED_EMERGENCY_STOP",
                message=f"Action cancelled by stop signal: {self.stop_signal.reason}",
            )
        type_text(text, dry_run=dry_run)
        post = self._post_check(target_hwnd, dry_run)
        if post:
            return post
        status = "DRY_RUN" if dry_run else "SUCCESS"
        return ActionResult(success=True, status=status, message=f"Typed text len={len(text)}")


# ---------- Standalone functions (Backward Compatible) ----------

def click(x: int, y: int, dry_run: bool = True, delay_ms: int = 120) -> bool:
    """Left click at screen coords.

    Aligned with original Lan.UIAutomationCore.Input.Mouse path used by 1.3.8/1.3.9:
    SetCursorPos → sleep ~200ms → SendInput left down/up → post delay.
    Returns True only when SendInput actually injected both events.
    """
    print(f"[input] click ({x}, {y}) dry_run={dry_run}")
    if dry_run:
        return True
    return _send_mouse_click(int(x), int(y), right=False, delay_ms=delay_ms)


def right_click(x: int, y: int, dry_run: bool = True, delay_ms: int = 120) -> bool:
    print(f"[input] right_click ({x}, {y}) dry_run={dry_run}")
    if dry_run:
        return True
    return _send_mouse_click(int(x), int(y), right=True, delay_ms=delay_ms)


def press_key(key: str, dry_run: bool = True) -> None:
    """key: e.g. 'f4', 'esc', 'z'.

    Backward Compatible: pyautogui.FailSafeException (and any other exception)
    propagates untouched — no wrapping exception layer.
    """
    print(f"[input] press_key {key!r} dry_run={dry_run}")
    if dry_run:
        return
    import pyautogui

    pyautogui.press(key)


def hotkey(*keys: str, dry_run: bool = True) -> None:
    """Press a key combination, for example ``ctrl+a``.

    Backward Compatible: pyautogui.FailSafeException (and any other exception)
    propagates untouched — no wrapping exception layer.
    """
    print(f"[input] hotkey {keys!r} dry_run={dry_run}")
    if dry_run:
        return
    import pyautogui

    pyautogui.hotkey(*keys)


def paste_text(text: str, dry_run: bool = True) -> None:
    """Paste text while preserving and restoring prior clipboard content.

    Safety: if the previous clipboard cannot be captured (non-text/API
    failure), or the restore of a captured prior content fails, the pasted
    text (e.g. room password) is explicitly cleared afterwards instead of
    being left system-wide.
    """
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
            if not set_clipboard_text(saved_text):
                # 恢复 prior 失败：最终 best-effort 清空，绝不让 secret 留在系统剪贴板
                if not _clear_clipboard():
                    print(
                        "[input] WARNING 无法清空剪贴板，可能残留敏感文本",
                    )
        else:
            # Prior clipboard unavailable: never leave the secret behind
            if not _clear_clipboard():
                print(
                    "[input] WARNING 无法清空剪贴板，可能残留敏感文本",
                )


def type_text(text: str, dry_run: bool = True) -> None:
    """Type ASCII/digits with key events (CEF-friendlier than clipboard paste)."""
    print(f"[input] type_text len={len(text)} dry_run={dry_run}")
    if dry_run or not text:
        return
    import ctypes
    from ctypes import wintypes as w

    user32 = ctypes.windll.user32
    KEYEVENTF_KEYUP = 0x0002

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", w.WORD),
            ("wScan", w.WORD),
            ("dwFlags", w.DWORD),
            ("time", w.DWORD),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class INPUT_UNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", w.DWORD), ("union", INPUT_UNION)]

    def tap(vk: int) -> None:
        down = INPUT()
        down.type = 1  # INPUT_KEYBOARD
        down.union.ki = KEYBDINPUT(vk, 0, 0, 0, None)
        up = INPUT()
        up.type = 1
        up.union.ki = KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP, 0, None)
        user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(INPUT))
        time.sleep(0.02)
        user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(INPUT))
        time.sleep(0.03)

    for ch in str(text):
        if "0" <= ch <= "9":
            tap(ord(ch))  # VK_0..VK_9 == ASCII
        elif "a" <= ch.lower() <= "z":
            tap(ord(ch.upper()))
        elif ch in (" ", "\t"):
            tap(0x20 if ch == " " else 0x09)
        else:
            # fallback scan via VkKeyScanW
            vk_full = int(user32.VkKeyScanW(ord(ch)))
            if vk_full == -1:
                continue
            vk = vk_full & 0xFF
            shift = bool(vk_full & 0x100)
            if shift:
                tap_shift_down = INPUT()
                tap_shift_down.type = 1
                tap_shift_down.union.ki = KEYBDINPUT(0x10, 0, 0, 0, None)
                user32.SendInput(1, ctypes.byref(tap_shift_down), ctypes.sizeof(INPUT))
            tap(vk)
            if shift:
                tap_shift_up = INPUT()
                tap_shift_up.type = 1
                tap_shift_up.union.ki = KEYBDINPUT(0x10, 0, KEYEVENTF_KEYUP, 0, None)
                user32.SendInput(1, ctypes.byref(tap_shift_up), ctypes.sizeof(INPUT))


def scroll(x: int, y: int, clicks: int, dry_run: bool = True) -> None:
    """Scroll at a screen point; positive values scroll up.

    Backward Compatible: pyautogui.FailSafeException (and any other exception)
    propagates untouched — no wrapping exception layer.
    """
    print(f"[input] scroll ({x}, {y}) clicks={clicks} dry_run={dry_run}")
    if dry_run:
        return
    import pyautogui

    pyautogui.moveTo(x, y, duration=0.05)
    pyautogui.scroll(clicks)


def _send_mouse_click(x: int, y: int, *, right: bool, delay_ms: int) -> bool:
    """user32 SetCursorPos + SendInput click (original GameScript path).

    Returns True only when both down and up were successfully injected
    (SendInput reports inserted events). Multi-monitor: absolute MOVE uses the
    virtual desktop origin/size with MOUSEEVENTF_VIRTUALDESK so the pointer
    lands where WindowFromPoint validated.
    """
    import ctypes
    from ctypes import wintypes as w

    user32 = ctypes.windll.user32

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", w.LONG),
            ("dy", w.LONG),
            ("mouseData", w.DWORD),
            ("dwFlags", w.DWORD),
            ("time", w.DWORD),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class INPUT_UNION(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", w.DWORD), ("union", INPUT_UNION)]

    INPUT_MOUSE = 0
    MOUSEEVENTF_MOVE = 0x0001
    MOUSEEVENTF_ABSOLUTE = 0x8000
    MOUSEEVENTF_VIRTUALDESK = 0x4000
    SM_XVIRTUALSCREEN = 76
    SM_YVIRTUALSCREEN = 77
    SM_CXVIRTUALSCREEN = 78
    SM_CYVIRTUALSCREEN = 79
    if right:
        down_flag, up_flag = 0x0008, 0x0010  # RIGHTDOWN / RIGHTUP
    else:
        down_flag, up_flag = 0x0002, 0x0004  # LEFTDOWN / LEFTUP

    # 虚拟桌面坐标：支持多显示器/负坐标（副屏在左侧时 x 可为负）
    vx = int(user32.GetSystemMetrics(SM_XVIRTUALSCREEN))
    vy = int(user32.GetSystemMetrics(SM_YVIRTUALSCREEN))
    vw = max(int(user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)), 1)
    vh = max(int(user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)), 1)
    ax = int((x - vx) * 65535 / max(vw - 1, 1))
    ay = int((y - vy) * 65535 / max(vh - 1, 1))

    def send(flags: int, dx: int = 0, dy: int = 0) -> int:
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.union.mi = MOUSEINPUT(dx, dy, 0, flags, 0, None)
        return int(user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT)))

    # Original: Mouse.set_Position → Sleep(200) → Click → Sleep(500)
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.20)
    move_ok = send(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, ax, ay)
    time.sleep(0.02)
    down_ok = send(down_flag)
    time.sleep(0.05)
    up_ok = send(up_flag)
    time.sleep(max(delay_ms, 0) / 1000.0)
    return bool(down_ok) and bool(up_ok)
