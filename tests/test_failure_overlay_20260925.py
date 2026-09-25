"""Failure modal drawn over the 时光之穴 panel (2026-09-25 hitch round 3).

The host wiped at 4-4; the translucent 失败 modal covered the archive panel,
none of the old strong-fail anchors matched, and the post-game chain clicked
the hidden archive close button 40 times until the 300 s cap.  The 失败
banner is now a strong-fail anchor, so global preemption takes over and the
recovery exits through the top-left 退出游戏.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from shuabao.mediator import Mediator, RecoveryKind
from shuabao.settings import Settings
from shuabao.vision.capture import Frame

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "hitch_failure_overlay_20260925"


def _frame(name: str) -> Frame:
    bgr = cv2.imdecode(np.fromfile(str(FIXTURES / name), dtype=np.uint8), cv2.IMREAD_COLOR)
    return Frame(bgr, window_title="英雄三国KK")


def test_failure_banner_over_time_cave_is_a_strong_fail_anchor() -> None:
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    hit = med.find_scene(_frame("round03_failure_over_timecave.png"), "fail")
    assert hit is not None
    assert "fail_banner" in hit.name


def test_nearest_non_failure_frame_is_not_a_fail_anchor() -> None:
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    assert med.find_scene(_frame("round01_nearest_non_failure.png"), "fail") is None


def test_failure_over_time_cave_recovers_through_the_game_exit() -> None:
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    frame = _frame("round03_failure_over_timecave.png")
    med._begin_recovery(RecoveryKind.FAIL)
    rs = med._recovery_state
    assert med._recovery_anchor(frame, rs) is not None
    action = med._recovery_action(frame, rs)
    assert action is not None
    # Top-left 退出游戏, never the archive panel's close button on the right.
    assert action.center[0] < frame.width * 0.2
    assert action.center[1] < frame.height * 0.1
