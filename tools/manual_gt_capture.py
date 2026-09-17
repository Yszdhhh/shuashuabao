"""Manual ground-truth frame capture helper.

Captures a limited number of screenshots of an explicit HWND's client area
via stdlib ctypes (Win32) + PIL ImageGrab. No game input is ever sent; this
is a test-only helper.

Capability limitation (documented, not solved here): screen capture captures
the visible desktop. If the target window is occluded by another window,
captured pixels include the occluder; if covered by other apps, frames are
wrong. Caller must keep the window foreground/unobstructed.

Usage:
    python tools/manual_gt_capture.py --hwnd 33950972 --out bundle --count 2 --interval 1

Timestamps do not establish distinct frames: compare PNG SHA-256 hashes.
Capturing frames does not establish that any ground-truth gate passed.
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes
import hashlib
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import NoReturn

from PIL import ImageGrab

MODES = ("MANUAL_GT", "USER_ASSISTED")

_user32 = ctypes.windll.user32

_user32.IsWindow.argtypes = [ctypes.c_void_p]
_user32.IsWindow.restype = ctypes.wintypes.BOOL
_user32.IsIconic.argtypes = [ctypes.c_void_p]
_user32.IsIconic.restype = ctypes.wintypes.BOOL
_user32.GetClientRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.wintypes.RECT)]
_user32.GetClientRect.restype = ctypes.wintypes.BOOL
_user32.ClientToScreen.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.wintypes.POINT)]
_user32.ClientToScreen.restype = ctypes.wintypes.BOOL
_user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
_user32.GetWindowTextW.restype = ctypes.c_int
_user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.wintypes.DWORD)]
_user32.GetWindowThreadProcessId.restype = ctypes.wintypes.DWORD
_user32.GetForegroundWindow.argtypes = []
_user32.GetForegroundWindow.restype = ctypes.c_void_p
_user32.IsChild.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_user32.IsChild.restype = ctypes.wintypes.BOOL
_user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
_user32.SetProcessDpiAwarenessContext.restype = ctypes.wintypes.BOOL


def _fail(msg: str) -> NoReturn:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def _window_title(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(512)
    _user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def _client_rect_screen(hwnd: int):
    rect = ctypes.wintypes.RECT()
    if not _user32.GetClientRect(hwnd, ctypes.byref(rect)):
        _fail("GetClientRect failed")
    w, h = rect.right - rect.left, rect.bottom - rect.top
    if w <= 0 or h <= 0:
        _fail(f"client area has non-positive size {w}x{h}")
    pt = ctypes.wintypes.POINT(rect.left, rect.top)
    if not _user32.ClientToScreen(hwnd, ctypes.byref(pt)):
        _fail("ClientToScreen failed")
    return pt.x, pt.y, pt.x + w, pt.y + h, w, h


def main() -> None:
    ap = argparse.ArgumentParser(description="Manual GT screen-capture helper (test-only, no game input).")
    ap.add_argument("--hwnd", required=True, type=lambda s: int(s, 0), help="target HWND (decimal or 0x hex)")
    ap.add_argument("--out", required=True, type=Path, help="output evidence bundle directory")
    ap.add_argument("--count", type=int, default=1, help="number of frames (1..120)")
    ap.add_argument("--interval", type=float, default=1.0, help="seconds between frames (>= 0)")
    ap.add_argument("--note", default="", help="free-form note recorded in metadata")
    ap.add_argument("--mode", choices=MODES, default="MANUAL_GT")
    args = ap.parse_args()

    hwnd = args.hwnd
    if not (1 <= args.count <= 120):
        _fail("--count must be in 1..120")
    if not math.isfinite(args.interval) or args.interval < 0:
        _fail("--interval must be a finite non-negative number")
    if not 0 < hwnd < (1 << (ctypes.sizeof(ctypes.c_void_p) * 8)):
        _fail("--hwnd must be a positive pointer-sized integer")
    if not _user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
        _fail("cannot establish per-monitor DPI awareness for screen coordinates")
    args.out.mkdir(parents=True, exist_ok=True)
    index_path = args.out / "frames.jsonl"
    for i in range(args.count):
        if not _user32.IsWindow(hwnd):
            _fail(f"HWND {hwnd:#x} is not a valid window")
        if _user32.IsIconic(hwnd):
            _fail(f"HWND {hwnd:#x} is minimized")
        title = _window_title(hwnd)
        pid = ctypes.wintypes.DWORD()
        if not _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)):
            _fail("GetWindowThreadProcessId failed")
        x0, y0, x1, y1, w, h = _client_rect_screen(hwnd)
        fg = _user32.GetForegroundWindow() or 0
        if not (fg == hwnd or _user32.IsChild(hwnd, fg)):
            _fail(f"foreground window {fg:#x} is not target {hwnd:#x} or its child; activate it manually first")
        ts_utc = datetime.now(timezone.utc).isoformat()
        img = ImageGrab.grab(bbox=(x0, y0, x1, y1), all_screens=True)
        if img.size != (w, h):
            _fail(f"grabbed frame size {img.size} != client size {(w, h)}")
        # Only a dark-pixel suspicion, not HUD classification or GT acceptance.
        extrema = img.convert("L").getextrema()
        quality = "suspected_black_frame" if extrema[1] < 16 else "unassessed"
        ts_file = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%f")
        path = args.out / f"frame_{i:03d}_{ts_file}.png"
        with path.open("xb") as png:
            img.save(png, format="PNG")
        sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        rec = {
            "utc_time": ts_utc,
            "index": i,
            "hwnd": hwnd,
            "pid": pid.value,
            "title": title,
            "bbox": [x0, y0, x1, y1],
            "dimensions": [w, h],
            "path": str(path),
            "sha256": sha256,
            "mode": args.mode,
            "note": args.note,
            "game_input_sent": False,
            "source": "live_screen_client_crop",
            "capture_quality": quality,
        }
        with index_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if i + 1 < args.count:
            time.sleep(args.interval)
    print(f"captured {args.count} frame(s); index: {index_path}")


if __name__ == "__main__":
    try:
        main()
    except (Exception, KeyboardInterrupt) as exc:
        _fail(f"{type(exc).__name__}: {exc}")
