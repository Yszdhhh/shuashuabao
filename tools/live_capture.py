#!/usr/bin/env python3
"""Live capture watcher: periodically screenshots the KK/game window.

Used during real-machine runs to build the frame-by-frame evidence set for
the post-game flow. Read-only: never sends input, never writes into the repo
(output goes to an out-of-repo capture dir).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gamescript.vision.capture import capture

OUT_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"C:\tmp\captures")
INTERVAL = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0
MAX_SHOTS = int(sys.argv[3]) if len(sys.argv) > 3 else 2000

OUT_DIR.mkdir(parents=True, exist_ok=True)

KEYWORDS = "英雄三国,KK官方,KK对战,KK竞技,对战平台,竞技平台,KK"


def main() -> int:
    shot = 0
    while shot < MAX_SHOTS:
        ts = time.strftime("%Y%m%d_%H%M%S")
        try:
            frame = capture(KEYWORDS, activate=False)
            if frame is not None and frame.bgr is not None and frame.bgr.size > 0:
                path = OUT_DIR / f"{ts}_h{frame.hwnd}.png"
                cv2.imwrite(str(path), frame.bgr)
                print(f"[capture] {path.name} {frame.width}x{frame.height} title={frame.window_title!r}", flush=True)
                shot += 1
        except Exception as e:
            print(f"[capture] error: {e}", flush=True)
        time.sleep(INTERVAL)
    return 0


if __name__ == "__main__":
    sys.exit(main())
