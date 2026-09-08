from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from shuabao.lobby_hitch import SearchTransaction
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
    """The stable search-control anchor as the production template matches it."""
    return MatchResult(
        name="lobby_search_icon",
        score=0.99,
        x=1256,
        y=281,
        w=26,
        h=22,
        screen_x=1256,
        screen_y=281,
    )


def test_hitch_rejected_search_input_never_marks_prefix_searched() -> None:
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    anchor = _search_anchor()
    with patch.object(med, "_lobby_room_list_evidence", return_value=True), \
         patch.object(
             med,
             "find_scene",
             side_effect=lambda _frame, key: anchor if key == "lobby_search_icon" else None,
         ), \
         patch.object(med, "act_search_box", return_value=False):
        med._tick_lobby_hitch(_fixture_frame(), "LOBBY_ROOM")

    tx = med._hitch_search
    assert tx is None or tx.awaiting_confirm is False
    assert med._hitch_prefix_ok() is False


def test_hitch_search_confirmation_defers_room_scan_until_next_tick() -> None:
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    med._hitch_search = SearchTransaction(prefix="4", opened_at=100.0, typed_at=100.0)
    med._hitch_search_text_override = "4"
    with patch("shuabao.mediator.time.time", return_value=101.0), \
         patch.object(med, "_lobby_room_list_evidence", return_value=True), \
         patch.object(med, "find_scene", return_value=None), \
         patch.object(med, "_find_hitch_joinable_row") as scan:
        med._tick_lobby_hitch(_fixture_frame(), "LOBBY_ROOM")

    scan.assert_not_called()
    assert med._hitch_search is not None
    assert med._hitch_search.confirmed is True
    assert med._hitch_prefix_ok() is True


def test_comment_tab_is_not_room_list_and_switches_to_room_list() -> None:
    """评论页的蓝色活动标签不能越界伪装成房间列表。"""
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    image = np.full((945, 1332, 3), 12, dtype=np.uint8)
    # 房间列表的灰色文字仍在固定槽位；评论页才是当前蓝色活动标签。
    image[235:255, 325:405] = (180, 180, 180)
    image[235:255, 438:466] = (210, 160, 10)
    frame = Frame(image, window_title="KK官方对战平台", hwnd=10001, role="l0")

    with patch.object(med, "find_scene", return_value=None), \
         patch.object(med, "act_click", return_value=True) as click:
        assert med._lobby_room_list_evidence(frame) is False
        assert med._find_hitch_room_list_tab(frame) is not None
        med._tick_lobby_hitch(frame, "PLATFORM_MAP")

    assert click.call_args.args[1] == "HitchSelectTab"


def test_hitch_cancel_ready_is_postcondition_not_click_target() -> None:
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    frame = _fixture_frame()
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
    exit_btn = MatchResult(
        name="room_exit_btn",
        score=1.0,
        x=1100,
        y=60,
        w=60,
        h=28,
        screen_x=1150,
        screen_y=75,
    )

    def fake_find(_frame, names, **_kwargs):
        if "room_exit_btn" in names:
            return exit_btn
        return cancel_ready if "room_cancel_ready" in names else None

    # Room identity is owned by the confirmed-room HWND authority
    # (_capture_best -> _is_confirmed_room_frame), not by a lone template
    # hit, so seed it to put this tick genuinely inside the room.
    med._confirmed_room_hwnd = frame.hwnd

    with patch.object(med, "find", side_effect=fake_find), \
         patch.object(med, "find_scene", return_value=None), \
         patch.object(med, "_hitch_room_seat_decision", return_value="ready"), \
         patch.object(med, "act_click") as click:
        med._tick_lobby_hitch(frame, "ROOM_WAITING")

    click.assert_not_called()
    assert med.phase is Phase.ROOM_WAITING
