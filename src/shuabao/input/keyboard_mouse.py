"""键鼠执行器（支持窗口校验、前台监控、全局急停取消与剪贴板恢复）。"""

from __future__ import annotations

from dataclasses import dataclass
import time

from shuabao.stop_signal import StopSignal
from shuabao.vision.capture import activate_window, is_window_valid, reacquire_target_window

__all__ = [
    "ActionResult",
    "InputExecutor",
    "activate_window",
    "reacquire_target_window",
    "foreground_matches_target",
    "window_belongs_to_target",
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


GA_ROOT = 2  # GetAncestor flag: walk to the owning top-level window


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


def _window_root(hwnd: int | None) -> int:
    """Top-level window that owns hwnd (GetAncestor GA_ROOT); 0 if unknown.

    KK renders its UI in an embedded CEF/Chromium view, so a point over the
    game surface resolves to a Chrome_RenderWidgetHostHWND child that lives in
    its own renderer process. GA_ROOT walks any such child back to the KK
    top-level HWND, which PID comparison alone cannot do.
    """
    if not hwnd:
        return 0
    try:
        import ctypes

        get_ancestor = ctypes.windll.user32.GetAncestor
        get_ancestor.restype = ctypes.c_void_p
        get_ancestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        root = get_ancestor(ctypes.c_void_p(int(hwnd)), GA_ROOT)
    except Exception:
        return 0
    return int(root or 0)


def _window_class_and_title(hwnd: int | None) -> tuple[str, str]:
    """(class_name, title) for hwnd; empty strings when unavailable."""
    if not hwnd:
        return ("", "")
    try:
        import ctypes

        user32 = ctypes.windll.user32
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(int(hwnd), cls, 256)
        title = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(int(hwnd), title, 256)
        return (cls.value, title.value)
    except Exception:
        return ("", "")


def _describe_window(hwnd: int | None) -> str:
    """hwnd/root/pid/class/title in one line, for input-cancellation messages."""
    cls, title = _window_class_and_title(hwnd)
    return (
        f"hwnd={hwnd} root={_window_root(hwnd)} pid={_window_pid(hwnd)} "
        f"class={cls!r} title={title!r}"
    )


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


def window_belongs_to_target(target_hwnd: int, hwnd: int | None) -> bool:
    """Single authority for "this HWND is part of the target's own surface".

    Accepted, in order:
      1. the exact target HWND;
      2. any window sharing the target's GA_ROOT top-level window - KK's
         embedded CEF renderer children qualify even though their PID differs;
      3. another top-level window of the same process (KK create-room modal).

    Fail-closed: when ancestry cannot be resolved both roots read as 0 and the
    root leg is skipped, so a foreign window is never admitted on class name or
    an unknown ancestry.
    """
    if hwnd is None:
        return False
    if int(hwnd) == int(target_hwnd):
        return True
    target_root = _window_root(target_hwnd)
    other_root = _window_root(hwnd)
    if target_root and other_root and target_root == other_root:
        return True
    return foreground_matches_target(target_hwnd, hwnd)


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


#: Post-injection guard status.  The input WAS sent; only its outcome is
#: unverified.  Callers must not retry it as if nothing had happened.
INPUT_DISPATCHED_UNVERIFIED = "CANCELLED_WINDOW_CHANGED_AFTER_INPUT"


class InputExecutor:
    """Cancellable input executor with target window & foreground verification."""

    def __init__(self, stop_signal: StopSignal | None = None) -> None:
        self.stop_signal = stop_signal or StopSignal()
        self._last_search_steps: list[dict] = []
        self._last_type_text_steps: list[dict] = []

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
            activate_window(target_hwnd)
            fg = get_foreground_window()
            if not foreground_matches_target(target_hwnd, fg):
                return ActionResult(
                    success=False,
                    status="CANCELLED_WINDOW_CHANGED",
                    message=f"Target window {target_hwnd} is not foreground (current={fg})",
                )
        return ActionResult(success=True, status="OK", message="Window verified")

    def _post_check(self, target_hwnd: int | None, dry_run: bool) -> ActionResult | None:
        """Verify the window after injection.

        A failure here is NOT the same as a pre-flight rejection: the input has
        already been sent to the game.  It gets its own status so callers can
        tell "never clicked" from "clicked, result unverified" — retrying the
        latter double-clicks the game (2026-09-09 trace tick 464: the 暴怒神符
        click was injected, reported ok=false, and the panel FSM then hammered
        the same slot until it force-closed the panel).
        """
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
                    status=INPUT_DISPATCHED_UNVERIFIED,
                    message=f"Foreground window changed after action from {target_hwnd} to {fg}",
                )
        return None

    def _check_point_obscured(self, target_hwnd: int, x: int, y: int) -> ActionResult | None:
        """Reject clicks whose screen point is covered by a foreign window.

        Real-machine failure mode: game window partially covered by editor/
        terminal; SendInput lands on the covering window and the game never
        reacts. WindowFromPoint tells us the topmost window at the click point,
        which for KK is normally an embedded CEF renderer child rather than the
        target HWND itself - window_belongs_to_target() resolves that ownership.
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
        if window_belongs_to_target(target_hwnd, top):
            return None
        # Name the covering window in full.  A cancellation here is otherwise
        # indistinguishable between a real foreign overlay and an ownership
        # resolution miss, and re-diagnosing it costs a whole build cycle.
        return ActionResult(
            success=False,
            status="CANCELLED_WINDOW_OBSCURED",
            message=(
                f"Click point ({x},{y}) is covered by another window: "
                f"{_describe_window(top)}; target={_describe_window(target_hwnd)}. "
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

    def double_click(self, x: int, y: int, target_hwnd: int | None = None, dry_run: bool = True, delay_ms: int = 50) -> ActionResult:
        check = self.check_can_execute(target_hwnd, dry_run=dry_run)
        if not check.success:
            print(f"[input] double_click ({x}, {y}) CANCELLED: {check.message}")
            return check
        if not dry_run and target_hwnd:
            obscured = self._check_point_obscured(target_hwnd, x, y)
            if obscured:
                print(f"[input] double_click ({x}, {y}) CANCELLED: {obscured.message}")
                return obscured
        if self.stop_signal and (self.stop_signal.is_set() or self.stop_signal.is_stopped()):
            return ActionResult(
                success=False,
                status="CANCELLED_EMERGENCY_STOP",
                message=f"Action cancelled by stop signal: {self.stop_signal.reason}",
            )
        first_injected = click(x, y, dry_run=dry_run, delay_ms=delay_ms)
        if not dry_run and not first_injected:
            return ActionResult(
                success=False,
                status="CANCELLED_SENDINPUT_FAILED",
                message=f"SendInput did not inject first click at ({x}, {y})",
            )
        time.sleep(0.08)
        second_injected = click(x, y, dry_run=dry_run, delay_ms=delay_ms)
        if not dry_run and not second_injected:
            return ActionResult(
                success=False,
                status="CANCELLED_SENDINPUT_FAILED",
                message=f"SendInput did not inject second click at ({x}, {y})",
            )
        post = self._post_check(target_hwnd, dry_run)
        if post:
            return post
        status = "DRY_RUN" if dry_run else "SUCCESS"
        return ActionResult(success=True, status=status, message=f"Double-clicked ({x}, {y})")

    def search_text(self, x: int, y: int, text: str, target_hwnd: int | None = None, dry_run: bool = True) -> ActionResult:
        self._last_search_steps = []
        check = self.check_can_execute(target_hwnd, dry_run=dry_run)
        if not check.success:
            print(f"[input] search_text ({x}, {y}) CANCELLED: {check.message}")
            return check
        if self.stop_signal and (self.stop_signal.is_set() or self.stop_signal.is_stopped()):
            return ActionResult(
                success=False,
                status="CANCELLED_EMERGENCY_STOP",
                message=f"Action cancelled by stop signal: {self.stop_signal.reason}",
            )
        steps = (
            ("click", lambda: self.click(x, y, target_hwnd=target_hwnd, dry_run=dry_run, delay_ms=80)),
            ("hotkey", lambda: self.hotkey("ctrl", "a", target_hwnd=target_hwnd, dry_run=dry_run)),
            ("press_key", lambda: self.press_key("backspace", target_hwnd=target_hwnd, dry_run=dry_run)),
            ("type_text", lambda: self.type_text(text, target_hwnd=target_hwnd, dry_run=dry_run)),
            ("press_key", lambda: self.press_key("return", target_hwnd=target_hwnd, dry_run=dry_run)),
        )
        for method, action in steps:
            result = action()
            step = {
                "method": method,
                "success": bool(result.success),
                "status": result.status,
                "message": result.message,
            }
            if method == "type_text":
                step["characters"] = list(self._last_type_text_steps)
            self._last_search_steps.append(step)
            if not result.success:
                return result
            time.sleep(0.02)
        status = "DRY_RUN" if dry_run else "SUCCESS"
        return ActionResult(success=True, status=status, message=f"Searched text {text!r} at ({x}, {y})")

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
                return obscured
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
        self._last_type_text_steps = []
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
        try:
            injected = type_text(text, dry_run=dry_run)
        except Exception as exc:
            return ActionResult(
                success=False,
                status="CANCELLED_SENDINPUT_FAILED",
                message=f"Keyboard SendInput exception: {exc}",
            )
        text_value = str(text)
        self._last_type_text_steps = [
            {
                "index": index,
                "char": char,
                "success": bool(ok),
                "status": "DRY_RUN" if dry_run else ("SUCCESS" if ok else "CANCELLED_SENDINPUT_FAILED"),
            }
            for index, (char, ok) in enumerate(zip(text_value, injected))
        ]
        if len(injected) != len(text_value):
            return ActionResult(
                success=False,
                status="CANCELLED_SENDINPUT_FAILED",
                message=(
                    f"Keyboard SendInput reported {len(injected)}/{len(text_value)} "
                    "characters"
                ),
            )
        for step in self._last_type_text_steps:
            if not step["success"]:
                return ActionResult(
                    success=False,
                    status="CANCELLED_SENDINPUT_FAILED",
                    message=f"Keyboard SendInput failed at character index {step['index']}",
                )
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


def type_text(text: str, dry_run: bool = True) -> list[bool]:
    """Type text with native key events, including Unicode without an IME."""
    print(f"[input] type_text len={len(text)} dry_run={dry_run}")
    text_value = str(text)
    if dry_run or not text_value:
        return [True for _ in text_value]
    import ctypes
    from ctypes import wintypes as w

    user32 = ctypes.windll.user32
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_UNICODE = 0x0004

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", w.WORD),
            ("wScan", w.WORD),
            ("dwFlags", w.DWORD),
            ("time", w.DWORD),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    # INPUT's native union is sized by MOUSEINPUT (32 bytes on Win64), not by
    # KEYBDINPUT alone (24 bytes). A keyboard-only union makes INPUT 32 bytes
    # instead of the required 40, so SendInput rejects it with error 87.
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
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", w.DWORD), ("union", INPUT_UNION)]

    def tap(vk: int) -> bool:
        down = INPUT()
        down.type = 1  # INPUT_KEYBOARD
        down.union.ki = KEYBDINPUT(vk, 0, 0, 0, None)
        up = INPUT()
        up.type = 1
        up.union.ki = KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP, 0, None)
        down_ok = int(user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(INPUT))) == 1
        time.sleep(0.02)
        up_ok = int(user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(INPUT))) == 1
        time.sleep(0.03)
        return down_ok and up_ok

    def tap_unicode(codepoint: int) -> bool:
        down = INPUT()
        down.type = 1
        down.union.ki = KEYBDINPUT(0, codepoint, KEYEVENTF_UNICODE, 0, None)
        up = INPUT()
        up.type = 1
        up.union.ki = KEYBDINPUT(0, codepoint, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, None)
        down_ok = int(user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(INPUT))) == 1
        time.sleep(0.02)
        up_ok = int(user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(INPUT))) == 1
        time.sleep(0.03)
        return down_ok and up_ok

    results: list[bool] = []
    for ch in text_value:
        if "0" <= ch <= "9":
            results.append(tap(ord(ch)))  # VK_0..VK_9 == ASCII
        elif "a" <= ch.lower() <= "z":
            results.append(tap(ord(ch.upper())))
        elif ch in (" ", "\t"):
            results.append(tap(0x20 if ch == " " else 0x09))
        elif ord(ch) > 0x7F:
            results.append(tap_unicode(ord(ch)))
        else:
            # fallback scan via VkKeyScanW
            vk_full = int(user32.VkKeyScanW(ord(ch)))
            if vk_full == -1:
                results.append(False)
                continue
            vk = vk_full & 0xFF
            shift = bool(vk_full & 0x100)
            shift_down_ok = True
            if shift:
                tap_shift_down = INPUT()
                tap_shift_down.type = 1
                tap_shift_down.union.ki = KEYBDINPUT(0x10, 0, 0, 0, None)
                shift_down_ok = int(user32.SendInput(1, ctypes.byref(tap_shift_down), ctypes.sizeof(INPUT))) == 1
            key_ok = shift_down_ok and tap(vk)
            shift_up_ok = True
            if shift:
                tap_shift_up = INPUT()
                tap_shift_up.type = 1
                tap_shift_up.union.ki = KEYBDINPUT(0x10, 0, KEYEVENTF_KEYUP, 0, None)
                shift_up_ok = int(user32.SendInput(1, ctypes.byref(tap_shift_up), ctypes.sizeof(INPUT))) == 1
            results.append(key_ok and shift_up_ok)
    return results


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
    positioned = bool(user32.SetCursorPos(int(x), int(y)))
    time.sleep(0.20)
    move_ok = send(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, ax, ay)
    time.sleep(0.02)
    down_ok = send(down_flag)
    time.sleep(0.05)
    up_ok = send(up_flag)
    time.sleep(max(delay_ms, 0) / 1000.0)
    final = w.POINT()
    cursor_read = bool(user32.GetCursorPos(ctypes.byref(final)))
    cursor_at_target = cursor_read and abs(int(final.x) - int(x)) <= 2 and abs(int(final.y) - int(y)) <= 2
    return positioned and bool(move_ok) and bool(down_ok) and bool(up_ok) and cursor_at_target
