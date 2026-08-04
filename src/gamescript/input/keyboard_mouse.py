"""键鼠执行（对齐 H.InputSimulator / PressKey 思路）。"""

from __future__ import annotations

import time


def click(x: int, y: int, dry_run: bool = True, delay_ms: int = 120) -> None:
    print(f"[input] click ({x}, {y}) dry_run={dry_run}")
    if dry_run:
        return
    import pyautogui

    pyautogui.moveTo(x, y, duration=0.05)
    pyautogui.click()
    time.sleep(delay_ms / 1000.0)


def press_key(key: str, dry_run: bool = True) -> None:
    """key: 如 'f4', 'esc', 'z'。"""
    print(f"[input] press_key {key!r} dry_run={dry_run}")
    if dry_run:
        return
    import pyautogui

    pyautogui.press(key)
