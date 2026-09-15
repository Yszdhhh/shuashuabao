# -*- coding: utf-8 -*-
"""单人编排用的 HUD 信号（实机 solo_ingame_chain_20260915_000229）。

- 顶栏木材（骷髅左侧）。
- G 技能按钮角标 = 未点的技能次数（该局从 4 涨到 32，一次没点）。
- V 宝物按钮角标 = 待拿宝物次数（涨到 14）。
按钮本身不在（选中小怪）→ None；按钮在但无角标 → 0；面板打开时 HUD 变暗也要读出。
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from shuabao.mediator import Mediator
from shuabao.settings import Settings
from shuabao.vision.capture import Frame

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "solo_live_20260914"


def _frame(name: str) -> Frame:
    image = cv2.imdecode(np.fromfile(str(FIX / name), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None, name
    return Frame(image, window_title="英雄三国KK", hwnd=10001, role="l1")


def test_badges_are_unknown_when_a_monster_replaces_the_command_card() -> None:
    med = Mediator(Settings(ocr_mode="off"), ROOT)
    frame = _frame("monster_selected_f0412.png")
    assert med._hud_skill_points(frame) is None
    assert med._hud_treasure_pending(frame) is None


@pytest.fixture()
def ocr_med():
    med = Mediator(Settings(), ROOT)
    if not med._ocr_client.start():
        pytest.skip(f"OCR worker unavailable: {med._ocr_client.ready_reason}")
    yield med
    med._ocr_client.close()


def test_skill_and_treasure_badges_on_a_real_hero_frame(ocr_med) -> None:
    frame = _frame("hud_wood_1111_f0200.png")
    assert ocr_med._hud_skill_points(frame) == 13
    assert ocr_med._hud_treasure_pending(frame) == 2
    assert ocr_med._hud_wood_balance(frame) == 1111
