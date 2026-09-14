# -*- coding: utf-8 -*-
"""实机 2026-09-14 单人第二局（solo_ingame_chain_20260914_225835）：点提前挑战图标后弹出
「是否确认提前挑战？」，是/否按钮与大秘境确认框同款（mijingOk 0.91），被分类成
GREAT_RIFT_CONFIRM；不在秘境路由上 → 找「否」找不到 → 零输入，直到 Owner 手动点「是」。
局内这个框属于我们自己的提前挑战：点「是」，Boss 直接召唤，没有 Boss 选择面板要等。
"""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from shuabao.mediator import Mediator, PanelState, Phase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "solo_live_20260914"
DIALOG = "tqtz_confirm_dialog_f0582.png"


def _frame(name: str) -> Frame:
    image = cv2.imdecode(np.fromfile(str(FIX / name), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None, name
    return Frame(image, window_title="英雄三国KK", hwnd=10001, role="l1")


def _med() -> Mediator:
    med = Mediator(Settings(ocr_mode="off", auto_close_main_line=True, auto_secret_realm=True), ROOT)
    med.set_phase(Phase.MAIN_LINE)
    med._round_started_at = time.time() - 700
    med._round_deadline = time.time() + 2700
    med._auto_task_done = True
    return med


def _tick(med: Mediator, frame: Frame) -> list[tuple[str, tuple[int, int]]]:
    clicks: list[tuple[str, tuple[int, int]]] = []
    rec = lambda hit, reason, *a, **k: clicks.append((reason, hit.center)) or True  # noqa: E731
    with patch.object(med, "act_click", side_effect=rec), \
         patch.object(med, "act_right_click", side_effect=rec), \
         patch.object(med, "act_key", return_value=True):
        med._tick_main_line(frame)
    return clicks


def test_real_dialog_is_the_one_misread_as_great_rift() -> None:
    assert _med()._post_game_state(_frame(DIALOG)) == "GREAT_RIFT_CONFIRM"


def test_dialog_after_our_icon_click_is_confirmed_with_yes() -> None:
    med = _med()
    now = time.time()
    # Live state: the skill panel was still in WAIT_MUTATION when the icon was clicked.
    med._panel_state = PanelState.WAIT_MUTATION
    med._tqtz_attempts = 1
    med._tqtz_pending = True
    med._tqtz_pending_since = now - 1
    med._tqtz_dialog_expected_until = now + 29
    med._early_challenge_pending = True
    med._early_challenge_started_at = now - 1
    clicks = _tick(med, _frame(DIALOG))
    assert [c[0] for c in clicks] == ["ConfirmTQTZ"], clicks
    x, y = clicks[0][1]
    assert 690 <= x <= 735 and 370 <= y <= 405, clicks  # 是 (712,387); 否 is (883,387)
    assert med._tqtz_clicked and not med._tqtz_pending
    assert not med._early_challenge_pending, "no Boss picker follows 是; do not hold the loop 15s"


def test_dialog_without_our_click_but_with_tqtz_caption_is_still_ours() -> None:
    med = _med()
    clicks = _tick(med, _frame(DIALOG))
    assert [c[0] for c in clicks] == ["ConfirmTQTZ"], clicks


def test_confirm_is_bounded_and_not_repeated_within_cooldown() -> None:
    med = _med()
    frame = _frame(DIALOG)
    assert [c[0] for c in _tick(med, frame)] == ["ConfirmTQTZ"]
    assert _tick(med, frame) == [], "second click only after the 1.5s cooldown"


def test_post_game_rift_route_still_owns_the_rift_dialog() -> None:
    med = _med()
    med._hitch_heirloom_exit_since = time.time() - 37
    clicks = _tick(med, _frame("great_rift_confirm_f0584.png"))
    assert [c[0] for c in clicks] == ["ConfirmGreatRift"], clicks
