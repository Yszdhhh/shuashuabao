# -*- coding: utf-8 -*-
"""S0 政策边界回归：蹭车（lobby_hitch）面板策略不可被非 live OCR 旁路。

1. 蹭车 + ocr_mode != "live"：宝物面板绝不走 _rarity_choice 品质兜底，
   只能关闭（或无关闭按钮时 None）。
2. 蹭车宝物 OCR live：只拿绿色神符；非绿/非神符只刷新或关闭。
3. 普通模式（normal_farm）保留既有品质兜底行为。
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from shuabao.choice_policy import PolicyAction, SessionState, SlotCandidate
from shuabao.mediator import Mediator
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult


def _frame() -> Frame:
    return Frame(bgr=np.zeros((900, 1600, 3), dtype=np.uint8), left=0, top=0)


def _mediator(mode_id: str, ocr_mode: str = "off") -> Mediator:
    return Mediator(
        Settings(dry_run=True, ocr_mode=ocr_mode, mode_id=mode_id),
        ROOT,
    )


def _hit(name: str = "card_hide") -> MatchResult:
    return MatchResult(name, 0.99, 100, 100, 10, 10, 1100, 700)


def _slot(index: int, name: str, rarity: str, confidence: float = 0.95) -> SlotCandidate:
    return SlotCandidate(index=index, name=name, confidence=confidence, rarity=rarity)


# ---------------------------------------------------------------------------
# 1. 蹭车 + 非 live OCR：宝物禁止品质兜底
# ---------------------------------------------------------------------------


def test_hitch_treasure_no_rarity_fallback_when_ocr_off() -> None:
    """蹭车 + ocr_mode=off：宝物面板不调用 _rarity_choice，直接关闭。"""
    med = _mediator("lobby_hitch", ocr_mode="off")
    med.settings.cards = []  # 排除模板偏好路径
    close = _hit()
    frame = _frame()
    with patch.object(med, "_panel_kind_of", return_value="treasure"), \
            patch.object(med, "_rarity_choice") as rarity, \
            patch.object(med, "_close_current_panel", return_value=close) as closer:
        result = med._find_reward_choice(frame, anchor=_hit("anchor_treasure"))
    rarity.assert_not_called()
    closer.assert_called_once()
    assert result == ("treasure", close)


def test_hitch_treasure_no_rarity_fallback_returns_none_without_close() -> None:
    """蹭车 + ocr_mode=shadow：无关闭按钮时返回 None，绝不品质兜底。"""
    med = _mediator("lobby_hitch", ocr_mode="shadow")
    med.settings.cards = []
    with patch.object(med, "_panel_kind_of", return_value="treasure"), \
            patch.object(med, "_rarity_choice") as rarity, \
            patch.object(med, "_close_current_panel", return_value=None):
        result = med._find_reward_choice(_frame(), anchor=_hit("anchor_treasure"))
    rarity.assert_not_called()
    assert result is None


def test_normal_treasure_keeps_rarity_fallback_when_ocr_off() -> None:
    """普通模式（非蹭车）+ ocr_mode=off：保留品质兜底行为。"""
    med = _mediator("normal_farm", ocr_mode="off")
    med.settings.cards = []
    rarity_hit = _hit("rarity_orange")
    frame = _frame()
    with patch.object(med, "_panel_kind_of", return_value="treasure"), \
            patch.object(med, "_rarity_choice", return_value=rarity_hit) as rarity:
        result = med._find_reward_choice(frame, anchor=_hit("anchor_treasure"))
    rarity.assert_called_once()
    assert result == ("treasure", rarity_hit)


# ---------------------------------------------------------------------------
# 2. 蹭车宝物 OCR live：绿色神符严格裁决
# ---------------------------------------------------------------------------


def _talisman_stacks(mode_id: str, slots, can_refresh: bool = False):
    """返回 (med, ctxmanager)；进入后 slots 直通，close/refresh 命中可观察。"""
    med = _mediator(mode_id, ocr_mode="live")
    close = _hit()

    @contextmanager
    def patched():
        with patch.object(med, "_ocr_panel_slots", return_value=[{"index": s.index} for s in slots]), \
                patch.object(med, "_slots_to_candidates", return_value=slots), \
                patch.object(med, "_extract_live_set_progress", return_value=None), \
                patch.object(med, "_bond_bar_occupancy", return_value=None), \
                patch.object(med, "_panel_can_refresh", return_value=can_refresh), \
                patch.object(med, "_panel_has_giveup", return_value=False), \
                patch.object(med, "_close_current_panel", return_value=close) as closer, \
                patch.object(med, "_find_panel_refresh", return_value=None):
            yield med, closer, close

    return med, patched


def test_hitch_treasure_selects_green_talisman() -> None:
    """蹭车宝物：绿色神符被选中，同面板的高品质非神符不选。"""
    slots = (
        _slot(0, "红色宝物", "red"),
        _slot(1, "绿色神符", "green"),
    )
    med, patched = _talisman_stacks("lobby_hitch", slots)
    with patched() as (_, closer, _):
        result = med._ocr_reward_choice(_frame(), "treasure")
    closer.assert_not_called()
    assert result is not None
    assert result.name == "ocr_treasure:绿色神符"


def test_hitch_treasure_without_shareable_item_only_refreshes_or_closes() -> None:
    """蹭车宝物：没有可共享道具时不选；预算内刷新（无钮降级关闭）/预算尽关闭。

    20260910 Owner ruling 之后「可共享」= 神符/吞噬丹/英雄卡/最高品质，所以
    这条边界要用真正的自用宝物来构造，蓝色神符已经属于该拿的了。
    """
    slots = (
        _slot(0, "橙色宝物", "orange"),
        _slot(1, "蓝色护腕", "blue"),
    )
    med, patched = _talisman_stacks("lobby_hitch", slots, can_refresh=True)
    with patched() as (m, closer, close):
        m._choice_session = SessionState(max_refreshes=3)
        result = m._ocr_reward_choice(_frame(), "treasure")
    assert result == close
    closer.assert_called_once()

    med2, patched2 = _talisman_stacks("lobby_hitch", slots, can_refresh=True)
    with patched2() as (m2, closer2, close2):
        m2._choice_session = SessionState(refreshes=99, max_refreshes=3)
        result2 = m2._ocr_reward_choice(_frame(), "treasure")
    assert result2 == close2
    closer2.assert_called_once()


def test_hitch_treasure_close_when_refresh_unavailable() -> None:
    """蹭车宝物：无绿色神符且不可刷新 → 直接关闭，不回落品质链。"""
    slots = (_slot(0, "橙色宝物", "orange"),)
    med, patched = _talisman_stacks("lobby_hitch", slots, can_refresh=False)
    with patched() as (m, closer, close):
        result = m._ocr_reward_choice(_frame(), "treasure")
    assert result == ("treasure", close)
    closer.assert_called_once()

def test_hitch_treasure_close_when_refresh_unavailable() -> None:
    """蹭车宝物：无绿色神符且不可刷新 → 直接关闭，不回落品质链。"""
    slots = (_slot(0, "橙色宝物", "orange"),)
    med, patched = _talisman_stacks("lobby_hitch", slots, can_refresh=False)
    with patched() as (m, closer, close):
        result = m._ocr_reward_choice(_frame(), "treasure")
    assert result == close
    closer.assert_called_once()


def test_normal_treasure_live_ignores_green_talisman_rule() -> None:
    """普通模式 live OCR：不受蹭车绿神符规则约束（走通用品质策略）。"""
    slots = (_slot(0, "橙色宝物", "orange"), _slot(1, "绿色神符", "green"))
    med, patched = _talisman_stacks("normal_farm", slots, can_refresh=False)
    with patched() as (m, closer, _), \
            patch.object(m, "_policy_decision_to_hit", return_value=None) as mapped:
        result = m._ocr_reward_choice(_frame(), "treasure")
    mapped.assert_called_once()
    decision = mapped.call_args[0][2]
    assert decision.action in {PolicyAction.SELECT_SLOT, PolicyAction.CLOSE, PolicyAction.REFRESH}
    closer.assert_not_called()


