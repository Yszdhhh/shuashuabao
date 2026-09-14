# -*- coding: utf-8 -*-
"""单人传家宝 → 大秘境（真实帧，solo_ingame_chain_20260914_212509）。

实机：传家宝 Boss 在广场上被打死后没有胜利页，37s 后大秘境确认框弹出，脚本按
"非自己请求"点了「否」。现在：出装备或满 120s → 走 NPC_HUB 秘境路由右键大秘境
NPC；秘境路由上 / 传家宝等待中弹出的确认框视为本次请求并点「是」。
"""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from shuabao.mediator import Mediator, Phase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "solo_live_20260914"


def _frame(name: str) -> Frame:
    image = cv2.imdecode(np.fromfile(str(FIX / name), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    return Frame(image, window_title="英雄三国KK", hwnd=10001, role="l1")


def _med(secret: bool = True) -> Mediator:
    med = Mediator(Settings(ocr_mode="off", auto_secret_realm=secret), ROOT)
    med.set_phase(Phase.MAIN_LINE)
    med._post_game_route = "boss_active"
    return med


def _tick(med: Mediator, frame: Frame) -> list[str]:
    clicks: list[str] = []
    rec = lambda hit, reason, *a, **k: clicks.append(reason) or True  # noqa: E731
    with patch.object(med, "act_click", side_effect=rec), \
         patch.object(med, "act_right_click", side_effect=rec), \
         patch.object(med, "act_key", return_value=True):
        med._tick_main_line(frame)
    return clicks


def test_heirloom_window_then_rift_npc_right_click_on_real_plaza() -> None:
    med = _med()
    med._hitch_heirloom_exit_since = time.time() - 121
    frame = _frame("plaza_after_heirloom_boss_f0578.png")
    assert _tick(med, frame) == []
    assert med._post_game_route == "secret" and med._post_game_pending
    assert _tick(med, frame) == ["OpenGreatRift"]


def test_rift_dialog_during_heirloom_wait_is_accepted() -> None:
    med = _med()
    med._hitch_heirloom_exit_since = time.time() - 37
    assert _tick(med, _frame("great_rift_confirm_f0584.png")) == ["ConfirmGreatRift"]


def test_rift_dialog_without_auto_secret_is_still_cancelled() -> None:
    med = _med(secret=False)
    med._hitch_heirloom_exit_since = time.time() - 37
    assert _tick(med, _frame("great_rift_confirm_f0584.png")) == ["CancelGreatRift"]


def test_rift_right_click_hits_the_npc_body_under_the_caption() -> None:
    """实机 225835：三次右键都点在「大秘境」文字 (1183,213) 上，确认框没开。"""
    med = _med()
    med._hitch_heirloom_exit_since = time.time() - 121
    frame = _frame("plaza_after_heirloom_boss_f0578.png")
    _tick(med, frame)
    targets = []
    rec = lambda hit, reason, *a, **k: targets.append((reason, hit.center)) or True  # noqa: E731
    with patch.object(med, "act_click", side_effect=rec), \
         patch.object(med, "act_right_click", side_effect=rec), \
         patch.object(med, "act_key", return_value=True):
        med._tick_main_line(frame)
    assert targets and targets[0][0] == "OpenGreatRift"
    x, y = targets[0][1]
    assert 1145 <= x <= 1180 and 245 <= y <= 290, targets


def test_third_rift_click_still_gets_its_walk_window_before_giving_up() -> None:
    med = _med()
    med._post_game_pending = True
    med._post_game_route = "secret"
    frame = _frame("plaza_after_heirloom_boss_f0578.png")
    t0 = 1_000_000.0
    reasons = []
    rec = lambda hit, reason, *a, **k: reasons.append(reason) or True  # noqa: E731
    with patch.object(med, "act_click", side_effect=rec), \
         patch.object(med, "act_right_click", side_effect=rec), \
         patch.object(med, "act_key", return_value=True):
        for step in range(0, 16):
            with patch("shuabao.mediator.time.time", return_value=t0 + step):
                med._tick_main_line(frame)
            if step == 11:
                assert reasons.count("OpenGreatRift") == 3
                assert med._post_game_route == "secret", "must still be waiting for the third walk"
    assert reasons.count("OpenGreatRift") == 3, reasons
