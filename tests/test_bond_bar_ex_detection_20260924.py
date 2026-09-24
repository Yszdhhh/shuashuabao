# -*- coding: utf-8 -*-
"""羁绊栏蓝色 EX 卡计数（Owner 2026-09-24：合成出 EX 才解锁下一组高级卡组）。

真机模板还没截（放 assets/Images/bond_bar/ex_card.png，海盗 UR 放 ur_card_haidao.png）。
这里用合成模板只测计数与 fail-closed 逻辑，不代表真机识别已通过（AGENTS.md 第 4 条）。
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from shuabao.mediator import Mediator
from shuabao.settings import Settings
from shuabao.vision.capture import Frame

ROOT = Path(__file__).resolve().parents[1]


def _frame_with_cards(patch: np.ndarray | None, cells: tuple[int, ...]) -> Frame:
    image = np.zeros((900, 1600, 3), dtype=np.uint8)
    if patch is not None:
        h, w = patch.shape[:2]
        for cell in cells:
            cx = Mediator._BOND_BAR_CELL_XS[cell]
            image[658 - h // 2:658 - h // 2 + h, cx - w // 2:cx - w // 2 + w] = patch
    return Frame(image)


def _synthetic_card() -> np.ndarray:
    rng = np.random.default_rng(20260924)
    return rng.integers(0, 255, size=(44, 40, 3), dtype=np.uint8)


def test_missing_template_means_unknown_not_zero() -> None:
    med = Mediator(Settings(ocr_mode="off"), ROOT)
    assert med._bond_bar_ex_count(_frame_with_cards(_synthetic_card(), (0,))) is None


def test_counts_each_bond_bar_cell_holding_an_ex_card(tmp_path: Path) -> None:
    card = _synthetic_card()
    (tmp_path / "bond_bar").mkdir()
    ok, buf = cv2.imencode(".png", card)
    assert ok
    (tmp_path / "bond_bar" / "ex_card.png").write_bytes(buf.tobytes())

    med = Mediator(Settings(ocr_mode="off"), ROOT)
    med.images = tmp_path
    assert med._bond_bar_ex_count(_frame_with_cards(None, ())) == 0
    assert med._bond_bar_ex_count(_frame_with_cards(card, (2, 7))) == 2
