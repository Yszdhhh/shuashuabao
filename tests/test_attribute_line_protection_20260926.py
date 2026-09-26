# -*- coding: utf-8 -*-
"""已勾选属性线的链上卡：满栏顶替保护；吞噬丹照常吃（2026-09-26）。

- 顶替：_is_target_synthetic_bond 对已勾选线的链上卡（含 UR 散件）返回 True，
  未勾选线的链上卡与散卡仍为 False（可顶替）。
- 吞噬丹：Owner 2026-09-26 06:57 定，只有专心做亡灵时停丹，属性链照常吃丹。
  链上卡未完成、UR 散件持有都不得触发 _devour_hold_reason。

零真实输入：只调纯查询方法与 mock 执行器。
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from shuabao.mediator import Mediator as CoreMediator
from shuabao.runtime_mediator import Mediator as RuntimeMediator
from shuabao.settings import Settings

ROOT = Path(__file__).resolve().parents[1]


def _med(cls=CoreMediator, **kw):
    med = cls(Settings(ocr_mode="off", **kw), ROOT)
    med.executor = MagicMock(name="executor")
    return med


def test_selected_line_chain_cards_are_protected_from_replacement() -> None:
    med = _med(attributes=["int"], bonds=[], cards=[])
    for name in ("智力", "秘法师", "法神", "湮灭者", "聚能之虹", "洞察之眼", "奥法之辉"):
        assert med._is_target_synthetic_bond(name) is True, name


def test_unselected_lines_stay_replaceable() -> None:
    med = _med(attributes=["int"], bonds=[], cards=[])
    for name in ("野蛮人", "战神", "屠戮者", "猎魔人", "弓神", "收割者",
                 "战斗咆哮", "亡者之轮", "体术"):
        assert med._is_target_synthetic_bond(name) is False, name


def test_all_three_lines_selected_protects_all_chains() -> None:
    med = _med(attributes=["int", "str", "agi"], bonds=[], cards=[])
    for name in ("秘法师", "湮灭者", "野蛮人", "战神", "屠戮者",
                 "猎魔人", "弓神", "收割者", "聚能之虹", "战斗咆哮", "亡者之轮"):
        assert med._is_target_synthetic_bond(name) is True, name
    assert med._is_target_synthetic_bond("体术") is False


def test_no_attributes_selected_changes_nothing() -> None:
    med = _med(attributes=[], bonds=[], cards=[])
    assert med._is_target_synthetic_bond("屠戮者") is False
    assert med._is_target_synthetic_bond("秘法师") is False


@pytest.mark.parametrize("cls", [CoreMediator, RuntimeMediator])
def test_devour_is_not_held_by_attribute_chains(cls) -> None:
    """Owner 2026-09-26 06:57：属性跟吞噬丹没有冲突，链上卡未完成、UR 散件都照常吃丹。"""
    med = _med(cls, attributes=["int", "agi"], bonds=[], cards=[])
    for owned in ([], ["智力", "智力"], ["智力"] * 4, ["野蛮人", "野蛮人"], ["亡者之轮"]):
        med._bond_cards_owned = list(owned)
        assert med._devour_hold_reason() is None, owned


@pytest.mark.parametrize("cls", [CoreMediator, RuntimeMediator])
def test_unfinished_chain_does_not_block_the_pill_gate_at_8_occupancy(cls) -> None:
    import numpy as np

    from shuabao.vision.capture import Frame

    med = _med(cls, attributes=["int"], bonds=[], cards=[])
    med._bond_cards_owned = ["智力", "智力"]
    bgr = np.zeros((900, 1600, 3), dtype=np.uint8)
    for cx in (603, 655, 707, 759, 811, 863, 915, 967)[:8]:
        bgr[635:680, cx - 20:cx + 20] = (255, 0, 0)
    frame = Frame(bgr, window_title="英雄三国KK", hwnd=10001, role="l1")
    assert med._bond_bar_occupancy(frame) == 8
    assert med._can_consume_inventory_swallow_pill(frame) is True
    assert med.executor.mock_calls == []
