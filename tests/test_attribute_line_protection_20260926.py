# -*- coding: utf-8 -*-
"""已勾选属性线的链上卡：满栏顶替保护 + 吞噬丹暂停（2026-09-26）。

- 顶替：_is_target_synthetic_bond 对已勾选线的链上卡（含 UR 散件）返回 True，
  未勾选线的链上卡与散卡仍为 False（可顶替）。
- 吞噬丹：占格阈值 8 不变；链上卡 0 < 已持有 < stack_need 时 _devour_hold_reason
  返回暂停原因（套用亡灵结构）；UR 散件无目录张数，持有即保守暂停——吞噬目标
  由游戏侧决定，脚本选不了受害者，只能整段不吃。

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
def test_devour_holds_while_chain_card_is_unfinished(cls) -> None:
    med = _med(cls, attributes=["int"], bonds=[], cards=[])
    med._bond_cards_owned = ["智力", "智力"]
    assert med._devour_hold_reason() is not None


@pytest.mark.parametrize("cls", [CoreMediator, RuntimeMediator])
def test_devour_resumes_when_chain_ring_is_complete_or_empty(cls) -> None:
    med = _med(cls, attributes=["int"], bonds=[], cards=[])
    med._bond_cards_owned = []
    assert med._devour_hold_reason() is None

    med._bond_cards_owned = ["智力", "智力", "智力", "智力"]
    assert med._devour_hold_reason() is None


@pytest.mark.parametrize("cls", [CoreMediator, RuntimeMediator])
def test_devour_ignores_unselected_lines(cls) -> None:
    med = _med(cls, attributes=["int"], bonds=[], cards=[])
    med._bond_cards_owned = ["野蛮人", "野蛮人"]
    assert med._devour_hold_reason() is None


@pytest.mark.parametrize("cls", [CoreMediator, RuntimeMediator])
def test_devour_holds_conservatively_for_pieces_without_catalog_need(cls) -> None:
    """UR 散件无 bond_stack_catalog 张数条目：持有即暂停，不赌进度。"""
    med = _med(cls, attributes=["agi"], bonds=[], cards=[])
    med._bond_cards_owned = ["亡者之轮"]
    reason = med._devour_hold_reason()
    assert reason is not None
    assert "亡者之轮" in reason


@pytest.mark.parametrize("cls", [CoreMediator, RuntimeMediator])
def test_devour_hold_blocks_the_pill_gate_at_8_occupancy(cls) -> None:
    import numpy as np

    from shuabao.vision.capture import Frame
    from shuabao.vision.matcher import MatchResult

    med = _med(cls, attributes=["int"], bonds=[], cards=[])
    med._bond_cards_owned = ["智力", "智力"]
    pill = MatchResult("danGif", 0.95, 1100, 780, 20, 20, 1100, 780)
    bgr = np.zeros((900, 1600, 3), dtype=np.uint8)
    for cx in (603, 655, 707, 759, 811, 863, 915, 967)[:8]:
        bgr[635:680, cx - 20:cx + 20] = (255, 0, 0)
    frame = Frame(bgr, window_title="英雄三国KK", hwnd=10001, role="l1")
    assert med._bond_bar_occupancy(frame) == 8
    assert med._can_consume_inventory_swallow_pill(frame) is False
    assert med.executor.mock_calls == []
