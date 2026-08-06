"""键鼠执行（对齐 H.InputSimulator / PressKey 思路）。"""

from __future__ import annotations

import time


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
    """key: 如 'f4', 'esc', 'z'。"""
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
    """Paste Unicode text without adding a clipboard dependency."""
    print(f"[input] paste_text len={len(text)} dry_run={dry_run}")
    if dry_run or not text:
        return
    import ctypes
    import pyautogui

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
        pyautogui.write(text, interval=0.01)
        return
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
        if not handle:
            pyautogui.write(text, interval=0.01)
            return
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            kernel32.GlobalFree(handle)
            pyautogui.write(text, interval=0.01)
            return
        ctypes.memmove(pointer, data, len(data))
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(13, handle):  # CF_UNICODETEXT
            kernel32.GlobalFree(handle)
            pyautogui.write(text, interval=0.01)
            return
    finally:
        user32.CloseClipboard()
    pyautogui.hotkey("ctrl", "v")


def scroll(x: int, y: int, clicks: int, dry_run: bool = True) -> None:
    """Scroll at a screen point; positive values scroll up."""
    print(f"[input] scroll ({x}, {y}) clicks={clicks} dry_run={dry_run}")
    if dry_run:
        return
    import pyautogui

    pyautogui.moveTo(x, y, duration=0.05)
    pyautogui.scroll(clicks)
