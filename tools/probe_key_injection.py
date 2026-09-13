# -*- coding: utf-8 -*-
"""Find out which keyboard-injection method this game actually accepts.

20260910: the PUBLIC_BACKPACK_DEPOSIT probe pressed B five times, every press
reported SUCCESS, and the bag never opened (bundle
public_backpack_deposit_20260910_122808_521256, frames f0001/f0003/... all show
plain HUD).  The game's own hint strip says "B 打开背包", so the key is right and
the delivery is wrong.

This tool answers the question with evidence instead of a guess: it presses B
through each candidate injection path and asks the production bag detector
whether the panel appeared.  It sends nothing else, stops at the first method
that works, and closes the panel again between attempts.

Run it elevated (KK runs as admin; UIPI drops input from a medium-IL process),
with the game in the foreground and NOT already showing the bag:

    python tools/probe_key_injection.py --production-source-root <candidate>
"""

from __future__ import annotations

import argparse
import ctypes
import sys
import time
from ctypes import wintypes as w
from pathlib import Path

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
MAPVK_VK_TO_VSC = 0


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", w.WORD),
        ("wScan", w.WORD),
        ("dwFlags", w.DWORD),
        ("time", w.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _MOUSEINPUT(ctypes.Structure):
    # INPUT's native union is sized by MOUSEINPUT, not KEYBDINPUT; a
    # keyboard-only union makes INPUT too small and SendInput fails with 87.
    _fields_ = [
        ("dx", w.LONG),
        ("dy", w.LONG),
        ("mouseData", w.DWORD),
        ("dwFlags", w.DWORD),
        ("time", w.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", w.DWORD), ("union", _INPUT_UNION)]


def _send(ki_down: _KEYBDINPUT, ki_up: _KEYBDINPUT) -> bool:
    user32 = ctypes.windll.user32
    down = _INPUT()
    down.type = 1  # INPUT_KEYBOARD
    down.union.ki = ki_down
    up = _INPUT()
    up.type = 1
    up.union.ki = ki_up
    ok_down = int(user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(_INPUT))) == 1
    time.sleep(0.04)
    ok_up = int(user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(_INPUT))) == 1
    return ok_down and ok_up


def press_pyautogui(vk: int) -> bool:
    import pyautogui

    pyautogui.press(chr(vk).lower())
    return True


def press_sendinput_vk(vk: int) -> bool:
    return _send(
        _KEYBDINPUT(vk, 0, 0, 0, None),
        _KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP, 0, None),
    )


def press_sendinput_scancode(vk: int) -> bool:
    scan = int(ctypes.windll.user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC))
    return _send(
        _KEYBDINPUT(0, scan, KEYEVENTF_SCANCODE, 0, None),
        _KEYBDINPUT(0, scan, KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP, 0, None),
    )


def press_sendinput_vk_and_scancode(vk: int) -> bool:
    scan = int(ctypes.windll.user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC))
    return _send(
        _KEYBDINPUT(vk, scan, 0, 0, None),
        _KEYBDINPUT(vk, scan, KEYEVENTF_KEYUP, 0, None),
    )


METHODS = (
    ("pyautogui.press           (current production path)", press_pyautogui),
    ("SendInput vk only         (same as type_text)", press_sendinput_vk),
    ("SendInput scancode        (games usually need this)", press_sendinput_scancode),
    ("SendInput vk + scancode", press_sendinput_vk_and_scancode),
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Which key injection does KK accept?")
    parser.add_argument("--production-source-root", required=True)
    parser.add_argument("--key", default="B", help="single letter, default B (打开背包)")
    parser.add_argument("--settle", type=float, default=1.5, help="seconds to wait after a press")
    args = parser.parse_args()

    root = Path(args.production_source_root).resolve()
    sys.path.insert(0, str(root / "src"))
    from shuabao.mediator import Mediator  # noqa: E402
    from shuabao.settings import Settings  # noqa: E402
    from shuabao.vision.capture import capture  # noqa: E402

    if not ctypes.windll.shell32.IsUserAnAdmin():
        print("[probe] BLOCKED: 需要管理员权限，否则 UIPI 会丢弃发给 KK 的输入")
        return 2

    settings = Settings(dry_run=True, ocr_mode="off")
    settings.mode_id = "lobby_hitch"
    med = Mediator(settings, root)
    vk = ord(args.key.upper()[0])

    def bag_open() -> bool:
        frame = capture("英雄三国")
        return med._bag_layout(frame) is not None

    if bag_open():
        print("[probe] BLOCKED: 背包已经是打开的。请先手动关掉再跑，否则分不清是谁开的。")
        return 2
    print(f"[probe] 起始状态确认：背包未打开。开始逐个方法按 {args.key.upper()} 键。\n")

    winner = None
    for label, method in METHODS:
        print(f"[probe] 尝试 {label} ...", flush=True)
        try:
            injected = method(vk)
        except Exception as exc:  # noqa: BLE001 - report, do not crash the probe
            print(f"           注入抛异常：{type(exc).__name__}: {exc}")
            continue
        time.sleep(args.settle)
        opened = bag_open()
        print(f"           injected={injected}  背包打开={opened}")
        if opened:
            winner = label
            method(vk)  # close it again so the next state is clean
            time.sleep(args.settle)
            print(f"           已再按一次关闭，关闭确认={not bag_open()}")
            break

    print()
    if winner:
        print(f"[probe] RESULT: 有效方法 = {winner}")
        return 0
    print("[probe] RESULT: 四种注入方式都没能打开背包。")
    print("        这说明问题不在注入方式，检查：游戏是否前台、是否有 IME 占用按键、")
    print("        B 是否被游戏内改键、以及本进程是否真的和 KK 同权限等级。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
