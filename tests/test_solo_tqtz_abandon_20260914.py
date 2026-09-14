# -*- coding: utf-8 -*-
"""实机 2026-09-14 单人：提前挑战 3 次未确认被标记放弃后，_maybe_click_tqtz 每帧
返回 Continue，把后面所有主线动作（5-5 取消自动任务、羁绊/技能/宝物…）截断，
从第 12 分钟起整局零输入。放弃只表示不再尝试，不能占用 tick。
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
FRAME = ROOT / "tests" / "fixtures" / "solo_live_20260914" / "ingame_tqtz_autotask_on_f0520.png"


def _frame() -> Frame:
    image = cv2.imdecode(np.fromfile(str(FRAME), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    return Frame(image, window_title="英雄三国KK", hwnd=10001, role="l1")


def _med() -> Mediator:
    med = Mediator(Settings(ocr_mode="off", auto_close_main_line=True), ROOT)
    med.set_phase(Phase.MAIN_LINE)
    med._round_started_at = time.time() - 900
    med._round_deadline = time.time() + 2700
    med._tqtz_abandoned = True
    med._tqtz_attempts = 3
    med._close_main_line_triggered = True
    med._auto_task_done = True  # live: EnableAutoTask at minute 1
    return med


def test_abandoned_tqtz_yields_the_tick() -> None:
    med = _med()
    assert med._maybe_click_tqtz(_frame(), time.time()) is None


def test_abandoned_tqtz_lets_5_5_auto_task_close_run_on_real_frame() -> None:
    med = _med()
    clicks: list[str] = []
    with patch.object(med, "act_click", side_effect=lambda hit, reason, *a, **k: clicks.append(reason) or True), \
         patch.object(med, "act_key", return_value=True), \
         patch.object(med, "act_right_click", return_value=True):
        for _ in range(3):
            med._tick_main_line(_frame())
            if "DisableAutoTask" in clicks:
                break
    assert "DisableAutoTask" in clicks, clicks


TQTZ = ROOT / "tests" / "fixtures" / "solo_live_20260914" / "tqtz_button_visible_f0511.png"


def test_tqtz_click_lands_on_the_phoenix_icon_not_the_caption() -> None:
    """实机 f0511：模板是「提前挑战」字样 (480,90)，按钮是上方图标 (444..515, 6..78)。"""
    image = cv2.imdecode(np.fromfile(str(TQTZ), dtype=np.uint8), cv2.IMREAD_COLOR)
    frame = Frame(image, window_title="英雄三国KK", hwnd=10001, role="l1")
    med = Mediator(Settings(ocr_mode="off"), ROOT)
    med.set_phase(Phase.MAIN_LINE)
    med._round_started_at = time.time() - 600
    targets = []
    with patch.object(med, "act_click", side_effect=lambda hit, reason, *a, **k: targets.append((reason, hit.center)) or True):
        med._maybe_click_tqtz(frame, time.time())
    assert targets and targets[0][0] == "ClickTQTZ"
    x, y = targets[0][1]
    assert 444 <= x <= 515 and 6 <= y <= 78, targets


def test_tqtz_is_clicked_as_soon_as_the_icon_shows_even_at_six_minutes() -> None:
    """Owner 2026-09-14：提前挑战开放 10/8/6 分钟不等（时间管理大师 / EX 圣剑），只认图标。"""
    image = cv2.imdecode(np.fromfile(str(TQTZ), dtype=np.uint8), cv2.IMREAD_COLOR)
    frame = Frame(image, window_title="英雄三国KK", hwnd=10001, role="l1")
    med = Mediator(Settings(ocr_mode="off"), ROOT)
    med.set_phase(Phase.MAIN_LINE)
    med._round_started_at = time.time() - 6 * 60
    reasons = []
    with patch.object(med, "act_click", side_effect=lambda hit, reason, *a, **k: reasons.append(reason) or True):
        med._maybe_click_tqtz(frame, time.time())
    assert reasons == ["ClickTQTZ"]
