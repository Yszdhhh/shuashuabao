# -*- coding: utf-8 -*-
"""单人链路可以从 KK 起跑（契约 start_condition：地图页 / 建房弹窗 / 房间 / 游戏内选关页）。

实机 2026-09-14（以及 09-09）：游戏客户端还没打开时，窗口预检只找「英雄三国」
游戏窗口，每次都 BLOCKED_PRECONDITION。现在单人找不到游戏窗口时退回 KK 窗口，
仍需起始面分类器确认后才允许输入。
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from shuabao.settings import Settings
from shuabao.mediator import Mediator
from shuabao.stop_signal import StopSignal
from shuabao.vision.capture import Frame
from tools import live_scenario_capture as lsc

ROOT = Path(__file__).resolve().parents[1]
KK_ROOM = ROOT / "tests" / "fixtures" / "real_kk_room_window.png"
STAGE_PAGE = ROOT / "tests" / "fixtures" / "hitch_postgame_20260914" / "real_stage_page_f0034.png"


def _kk_frame(title: str = "KK官方对战平台") -> Frame:
    image = cv2.imdecode(np.fromfile(str(KK_ROOM), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    return Frame(image, window_title=title, hwnd=20002, role="l0")


def _missing(error: str = "Target window not found: '英雄三国'"):
    return SimpleNamespace(is_valid=False, bgr=None, error=error, window_title="", hwnd=None,
                           left=0, top=0, width=0, height=0, role="l1")


def _preflight(target: str, first, second):
    calls = []

    def fake_capture(title, role="l1", allow_fallback=False):
        calls.append((title, role))
        return first if len(calls) == 1 else second

    with patch.object(lsc, "capture", side_effect=fake_capture):
        frame, record = lsc._window_preflight(Settings(ocr_mode="off"), target)
    return frame, record, calls


def test_solo_falls_back_to_kk_window_when_game_client_is_absent() -> None:
    frame, record, calls = _preflight("solo_ingame_chain", _missing(), _kk_frame())
    assert calls == [("英雄三国", "l1"), ("", "l0")]
    assert record["status"] == "READY"
    assert record["role"] == "l0"
    assert "KK" in record["title"]
    assert frame is not None and frame.window_title == "KK官方对战平台"


def test_solo_prefers_the_game_window_when_it_exists() -> None:
    game = _kk_frame("英雄三国KK")
    frame, record, calls = _preflight("solo_ingame_chain", game, None)
    assert calls == [("英雄三国", "l1")]
    assert record["status"] == "READY" and frame is game


def test_minimized_game_window_is_not_replaced_by_kk() -> None:
    minimized = _missing("Window is minimized")
    minimized.hwnd = 777
    _, record, calls = _preflight("solo_ingame_chain", minimized, _kk_frame())
    assert calls == [("英雄三国", "l1")]
    assert record["status"] == "BLOCKED"


def test_non_kk_window_is_not_accepted_as_solo_start() -> None:
    _, record, _ = _preflight("solo_ingame_chain", _missing(), _kk_frame("记事本"))
    assert record["status"] == "BLOCKED"


def test_other_in_game_targets_keep_requiring_the_game_window() -> None:
    _, record, calls = _preflight("hitch_runtime", _missing(), _kk_frame())
    assert calls == [("英雄三国", "l1")]
    assert record["status"] == "BLOCKED"


def test_stage_archaeology_button_matches_real_stage_page() -> None:
    image = cv2.imdecode(np.fromfile(str(STAGE_PAGE), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    med = Mediator(Settings(dry_run=True, ocr_mode="off"), ROOT, stop_signal=StopSignal())
    hit = med.find(
        Frame(image, window_title="英雄三国KK", hwnd=20003, role="l1"),
        ["lobby/stage_archaeology_btn"],
        threshold=0.70,
    )
    assert hit is not None
    assert hit.score >= 0.95
    assert hit.center == (1363, 822)
