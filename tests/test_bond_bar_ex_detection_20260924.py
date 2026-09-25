# -*- coding: utf-8 -*-
"""羁绊栏蓝色 EX 卡计数（Owner 2026-09-24：合成出 EX 才解锁下一组高级卡组）。

模板取自 Owner 的卡面截图 fixtures/ex_finals_20260814（不是羁绊栏实拍）。这里的"贴图"
用例是合成帧，只测计数逻辑，不代表真机识别已通过（AGENTS.md 第 4 条）；真机帧只用来
锁"非 EX 卡不误认"。
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from shuabao.mediator import Mediator
from shuabao.settings import Settings
from shuabao.vision.capture import Frame

ROOT = Path(__file__).resolve().parents[1]
# 真机 2026-09-23：羁绊栏 7 张（经济/弓神/野蛮人，蓝/橙/紫框），后 3 格空。
LIVE_BAR = ROOT / "tests/fixtures/evolve_false_positive_20260923.jpg"
DAODAO_TOOLTIP = ROOT / "fixtures/ex_finals_20260814/06_刀刀_解放的圣剑.png"


def _read(path: Path) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None, path
    return image


def _live_frame(image: np.ndarray | None = None) -> Frame:
    return Frame(_read(LIVE_BAR) if image is None else image, window_title="英雄三国KK", hwnd=10001, role="l1")


def test_missing_templates_mean_unknown_not_zero(tmp_path: Path) -> None:
    med = Mediator(Settings(ocr_mode="off"), ROOT)
    med.images = tmp_path
    assert med._bond_bar_ex_count(_live_frame()) is None


def test_live_bond_bar_without_ex_counts_zero() -> None:
    med = Mediator(Settings(ocr_mode="off"), ROOT)
    assert med._bond_bar_occupancy(_live_frame()) == 7
    assert med._bond_bar_ex_count(_live_frame()) == 0


def test_ex_icon_placed_in_an_empty_cell_is_counted() -> None:
    """合成：把卡面截图里的解放的圣剑卡图缩到 50px 贴进真机帧的第 9 格空位。"""
    icon = cv2.resize(_read(DAODAO_TOOLTIP)[76:141, 13:78], (50, 50), interpolation=cv2.INTER_AREA)
    image = _read(LIVE_BAR).copy()
    cx = Mediator._BOND_BAR_CELL_XS[8]
    image[632:682, cx - 25:cx + 25] = icon
    med = Mediator(Settings(ocr_mode="off"), ROOT)
    assert med._bond_bar_ex_count(_live_frame(image)) == 1
