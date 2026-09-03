from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from shuabao.mediator import Mediator, Phase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult


ROOT = Path(__file__).resolve().parents[1]


def _fixture_frame() -> Frame:
    source = ROOT / "fixtures" / "replay" / "main_line_auto_on.png"
    image = cv2.imdecode(np.fromfile(str(source), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    return Frame(image, window_title="KK官方对战平台", hwnd=10001, role="l0")


def _search_anchor() -> MatchResult:
    return MatchResult(
        name="lobby_search_box",
        score=1.0,
        x=1095,
        y=295,
        w=185,
        h=30,
        screen_x=1346,
        screen_y=347,
    )


def test_hitch_rejected_search_input_never_marks_prefix_searched() -> None:
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    anchor = _search_anchor()
    with patch.object(med, "_lobby_room_list_evidence", return_value=True), \
         patch.object(
             med,
             "find_scene",
             side_effect=lambda _frame, key: anchor if key == "lobby_search_box" else None,
         ), \
         patch.object(med, "act_search_box", return_value=False):
        med._tick_lobby_hitch(_fixture_frame(), "LOBBY_ROOM")

    assert med._hitch_search_pending is None
    assert med._hitch_prefix_searched is False


def test_hitch_search_confirmation_defers_room_scan_until_next_tick() -> None:
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    med._hitch_search_pending = ("4", 100.0)
    med._hitch_search_text_override = "4"
    with patch("shuabao.mediator.time.time", return_value=101.0), \
         patch.object(med, "_lobby_room_list_evidence", return_value=True), \
         patch.object(med, "find_scene", return_value=None), \
         patch.object(med, "_find_hitch_joinable_row") as scan:
        med._tick_lobby_hitch(_fixture_frame(), "LOBBY_ROOM")

    scan.assert_not_called()
    assert med._hitch_search_pending is None
    assert med._hitch_prefix_searched is True


def test_hitch_cancel_ready_is_postcondition_not_click_target() -> None:
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    cancel_ready = MatchResult(
        name="room_cancel_ready",
        score=1.0,
        x=800,
        y=600,
        w=100,
        h=30,
        screen_x=850,
        screen_y=615,
    )

    def fake_find(_frame, names, **_kwargs):
        return cancel_ready if "room_cancel_ready" in names else None

    with patch.object(med, "find", side_effect=fake_find), \
         patch.object(med, "find_scene", return_value=None), \
         patch.object(med, "_hitch_room_seat_decision", return_value="ready"), \
         patch.object(med, "act_click") as click:
        med._tick_lobby_hitch(_fixture_frame(), "ROOM_WAITING")

    click.assert_not_called()
    assert med.phase is Phase.ROOM_WAITING
