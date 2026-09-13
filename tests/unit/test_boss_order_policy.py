"""Unit tests for boss order fallback policy and catalog assertions.

Covers:
- T < L: target above visible / below visible / in visible region but not matched
- T > L: at bottom -> CLICK_LAST_NOT_UNLOCKED
- T == L: matched vs missing
- L unknown: no cards visible -> WAIT / FAIL_CLOSED
- Unconfigured target: scroll to bottom, then click last card
- Limits exhausted: locate_attempts or scroll_attempts -> CLICK_LAST_LOCATE_FAILED
- 24 same number: 24戴文戴尔男爵 vs 24瑞文戴尔男爵
- Catalog vs assets assertions (including 18-20, 54莫阿姆 in chuanjiaobao)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from shuabao.policy.boss_order import (
    BossOrderAction,
    BossOrderDecision,
    VisibleCard,
    decide_boss_order_action,
    measure_grid_pitch,
    parse_boss_order_number,
    predict_card_slot,
    LOCATE_FAILURE_FALLBACK_DEFAULT,
)

ROOT = Path(__file__).resolve().parents[2]


def test_parse_boss_order_number():
    assert parse_boss_order_number(1) == 1
    assert parse_boss_order_number("01霍格") == 1
    assert parse_boss_order_number("boss/01霍格") == 1
    assert parse_boss_order_number("18乌索克") == 18
    assert parse_boss_order_number("chuanjiaobao/18乌索克") == 18
    assert parse_boss_order_number("24瑞文戴尔男爵") == 24
    assert parse_boss_order_number("24戴文戴尔男爵") == 24
    assert parse_boss_order_number("54莫阿姆") == 54
    assert parse_boss_order_number("") is None
    assert parse_boss_order_number(None) is None

    catalog = {
        "boss": [{"no": 4, "label": "大范", "template_stem": "04大范"}],
        "chuanjiaobao": [{"no": 18, "label": "乌索克", "template_stem": "18乌索克"}],
    }
    assert parse_boss_order_number("大范", catalog) == 4
    assert parse_boss_order_number("乌索克", catalog) == 18


def test_measure_grid_pitch_and_predict_slot():
    cards = [
        VisibleCard(no=1, name="01", x=100, y=200, w=58, h=58, score=0.9),
        VisibleCard(no=2, name="02", x=180, y=200, w=58, h=58, score=0.9),
        VisibleCard(no=3, name="03", x=260, y=200, w=58, h=58, score=0.9),
        VisibleCard(no=4, name="04", x=340, y=200, w=58, h=58, score=0.9),
        VisibleCard(no=5, name="05", x=100, y=278, w=58, h=58, score=0.9),
    ]
    dx, dy, med_w, med_h = measure_grid_pitch(cards, cols_per_row=4)
    assert 75 <= dx <= 85
    assert 75 <= dy <= 85
    assert med_w == 58
    assert med_h == 58

    # Bilateral interpolation: predict card 2 from card 1 and card 3
    bilateral_cards = [
        VisibleCard(no=1, name="01", x=100, y=200, w=58, h=58, score=0.9),
        VisibleCard(no=3, name="03", x=260, y=200, w=58, h=58, score=0.9),
    ]
    slot = predict_card_slot(2, bilateral_cards, cols_per_row=4)
    assert slot is not None
    assert slot[0] == 180  # (100 + 260) / 2
    assert slot[1] == 200

    # Neighbor projection: predict card 6 (col 1, row 1) from card 5 (col 0, row 1)
    slot6 = predict_card_slot(6, cards, cols_per_row=4)
    assert slot6 is not None
    assert 170 <= slot6[0] <= 190
    assert 270 <= slot6[1] <= 285


def test_target_directly_matched():
    cards = [
        VisibleCard(no=5, name="05克雷什", x=100, y=200, w=58, h=58, score=0.88),
        VisibleCard(no=6, name="06吞噬者穆坦努斯", x=180, y=200, w=58, h=58, score=0.85),
    ]
    dec = decide_boss_order_action(5, cards)
    assert dec.action == BossOrderAction.CLICK_TARGET
    assert dec.target_card.name == "05克雷什"


def test_t_less_than_l_target_above_visible_scrolls_up():
    cards = [
        VisibleCard(no=9, name="09摩拉迪姆", x=100, y=200, w=58, h=58, score=0.88),
        VisibleCard(no=10, name="10吞噬者芬鲁斯", x=180, y=200, w=58, h=58, score=0.85),
    ]
    dec = decide_boss_order_action(
        target_no=4,
        visible_cards=cards,
        at_bottom=False,
        at_top=False,
        can_scroll=True,
    )
    assert dec.action == BossOrderAction.SCROLL_UP


def test_t_less_than_l_target_below_visible_scrolls_down():
    cards = [
        VisibleCard(no=1, name="01霍格", x=100, y=200, w=58, h=58, score=0.88),
        VisibleCard(no=2, name="02耶戈什", x=180, y=200, w=58, h=58, score=0.85),
    ]
    dec = decide_boss_order_action(
        target_no=8,
        visible_cards=cards,
        at_bottom=False,
        at_top=True,
        can_scroll=True,
    )
    assert dec.action == BossOrderAction.SCROLL_DOWN


def test_t_in_visible_range_confirms_predicted_slot():
    cards = [
        VisibleCard(no=1, name="01霍格", x=100, y=200, w=58, h=58, score=0.88),
        VisibleCard(no=3, name="03曲奇", x=260, y=200, w=58, h=58, score=0.85),
    ]
    # Card 2 is missing from visible_cards, but in range [1, 3]
    dec = decide_boss_order_action(
        target_no=2,
        visible_cards=cards,
        locate_attempts=0,
        locate_limit=3,
    )
    assert dec.action == BossOrderAction.CONFIRM_PREDICTED
    assert dec.predicted_box is not None
    assert dec.predicted_box[0] == 180  # interpolated
    assert dec.predicted_box[1] == 200


def test_t_in_visible_range_locate_attempts_exhausted_falls_back():
    cards = [
        VisibleCard(no=1, name="01霍格", x=100, y=200, w=58, h=58, score=0.88),
        VisibleCard(no=3, name="03曲奇", x=260, y=200, w=58, h=58, score=0.85),
    ]
    # If not at bottom: scrolls down to return to bottom
    dec_scroll = decide_boss_order_action(
        target_no=2,
        visible_cards=cards,
        locate_attempts=3,
        locate_limit=3,
        at_bottom=False,
    )
    assert dec_scroll.action == BossOrderAction.SCROLL_DOWN
    assert "回到底部" in dec_scroll.reason

    # If at bottom: selects physical last card if L+1 is verified empty
    dec_bottom = decide_boss_order_action(
        target_no=2,
        visible_cards=cards,
        locate_attempts=3,
        locate_limit=3,
        at_bottom=True,
        slot_empty_checker=lambda b: True,
    )
    assert dec_bottom.action == BossOrderAction.CLICK_LAST_LOCATE_FAILED
    assert dec_bottom.target_card.no == 3  # physical last card

    # If at bottom but L+1 has unverified card: WAIT (never click second-to-last)
    dec_bottom_card = decide_boss_order_action(
        target_no=2,
        visible_cards=cards,
        locate_attempts=3,
        locate_limit=3,
        at_bottom=True,
        slot_empty_checker=lambda b: False,
    )
    assert dec_bottom_card.action == BossOrderAction.WAIT

    # If bottom scroll budget exhausted and still not at bottom: WAIT (never click unproven)
    dec_exhausted = decide_boss_order_action(
        target_no=2,
        visible_cards=cards,
        locate_attempts=3,
        locate_limit=3,
        locate_exhausted=True,
        bottom_scroll_attempts=16,
        bottom_scroll_limit=16,
        at_bottom=False,
    )
    assert dec_exhausted.action == BossOrderAction.WAIT


def test_t_greater_than_l_at_bottom_clicks_last_not_unlocked():
    # Target 18, visible cards max 15 (L=15)
    cards = [
        VisibleCard(no=14, name="14青蛙之神", x=100, y=200, w=58, h=58, score=0.88),
        VisibleCard(no=15, name="15猛虎之神", x=180, y=200, w=58, h=58, score=0.85),
    ]
    viewport = (0, 0, 1000, 1000)

    # 1. When slot 16 is verified empty -> L=15 proven last -> CLICK_LAST_NOT_UNLOCKED
    dec_empty = decide_boss_order_action(
        target_no=18,
        visible_cards=cards,
        at_bottom=True,
        viewport_box=viewport,
        slot_empty_checker=lambda b: True,
    )
    assert dec_empty.action == BossOrderAction.CLICK_LAST_NOT_UNLOCKED
    assert dec_empty.target_card.no == 15

    # 2. When slot 16 has an unverified card and target is 18 (T > 16) -> WAIT (do not click 15!)
    dec_card = decide_boss_order_action(
        target_no=18,
        visible_cards=cards,
        at_bottom=True,
        viewport_box=viewport,
        slot_empty_checker=lambda b: False,
    )
    assert dec_card.action == BossOrderAction.WAIT
    assert "禁止点击倒数第二张" in dec_card.reason

    # 3. When L is already catalog maximum (e.g. 20 for HEIRLOOM) -> CLICK_LAST_NOT_UNLOCKED
    cjb_max_cards = [
        VisibleCard(no=19, name="19玛洛恩", x=100, y=200, w=58, h=58, score=0.88),
        VisibleCard(no=20, name="20鲁克玛", x=180, y=200, w=58, h=58, score=0.85),
    ]
    dec_max = decide_boss_order_action(
        target_no=25,
        visible_cards=cjb_max_cards,
        at_bottom=True,
        page_type="HEIRLOOM_DIALOG",
    )
    assert dec_max.action == BossOrderAction.CLICK_LAST_NOT_UNLOCKED
    assert dec_max.target_card.no == 20


def test_t_equals_l_missing_card():
    # Target is 15, visible cards max 14 (L=14)
    cards = [
        VisibleCard(no=13, name="13蛇王纳什", x=100, y=200, w=58, h=58, score=0.88),
        VisibleCard(no=14, name="14青蛙之神", x=180, y=200, w=58, h=58, score=0.85),
    ]
    viewport = (0, 0, 1000, 1000)

    # If slot 15 has an unverified card, target 15 == L+1 -> CONFIRM_PREDICTED on slot 15
    dec_unverified = decide_boss_order_action(
        target_no=15,
        visible_cards=cards,
        at_bottom=True,
        viewport_box=viewport,
        slot_empty_checker=lambda b: False,
    )
    assert dec_unverified.action == BossOrderAction.CONFIRM_PREDICTED
    assert dec_unverified.predicted_box is not None

    # If slot 15 is verified empty, then target 15 really not unlocked -> CLICK_LAST_NOT_UNLOCKED
    dec_empty = decide_boss_order_action(
        target_no=15,
        visible_cards=cards,
        at_bottom=True,
        viewport_box=viewport,
        slot_empty_checker=lambda b: True,
    )
    assert dec_empty.action == BossOrderAction.CLICK_LAST_NOT_UNLOCKED
    assert dec_empty.target_card.no == 14


def test_unconfigured_target_scrolls_to_bottom_then_selects_last():
    cards = [
        VisibleCard(no=1, name="01霍格", x=100, y=200, w=58, h=58, score=0.88),
        VisibleCard(no=2, name="02耶戈什", x=180, y=200, w=58, h=58, score=0.85),
    ]
    # Not at bottom: scrolls down
    dec_scroll = decide_boss_order_action(
        target_no=None,
        visible_cards=cards,
        at_bottom=False,
        scroll_attempts=0,
        scroll_limit=16,
    )
    assert dec_scroll.action == BossOrderAction.SCROLL_DOWN

    # At bottom with the L+1 slot proven empty: selects last card immediately
    dec_bottom = decide_boss_order_action(
        target_no=None,
        visible_cards=cards,
        at_bottom=True,
        slot_empty_checker=lambda _box: True,
    )
    assert dec_bottom.action == BossOrderAction.CLICK_LAST_NOT_UNLOCKED
    assert dec_bottom.target_card.no == 2


# ---- Path A (P2) + 未决收口回到纯策略 -------------------------------------

_ROW3 = [
    VisibleCard(no=9, name="09摩拉迪姆", x=100, y=360, w=58, h=58, score=0.88),
    VisibleCard(no=10, name="10奥斯里安", x=178, y=360, w=58, h=58, score=0.88),
    VisibleCard(no=11, name="11拉什凡", x=256, y=360, w=58, h=58, score=0.88),
]
_VIEWPORT = (80, 200, 420, 520)


def _decide_unconfigured(attempts: int, checker=lambda _box: False, **kw):
    return decide_boss_order_action(
        target_no=None,
        visible_cards=_ROW3,
        at_bottom=True,
        viewport_box=_VIEWPORT,
        slot_empty_checker=checker,
        unresolved_attempts=attempts,
        unresolved_limit=3,
        **kw,
    )


def test_path_a_unconfigured_unproven_last_card_reobserves_then_falls_back():
    """未配置目标到底、L+1 格位有未识别卡：前 2 次重观察，第 3 次按用户规则点最后已识别卡。"""
    first = _decide_unconfigured(0)
    second = _decide_unconfigured(1)
    third = _decide_unconfigured(2)
    assert first.action == BossOrderAction.WAIT
    assert "未证明" in first.reason
    assert second.action == BossOrderAction.WAIT
    assert third.action == BossOrderAction.CLICK_LAST_VISIBLE_FALLBACK
    assert third.target_card.no == 11
    assert "3/3" in third.reason


def test_path_a_unconfigured_proven_last_card_clicks_without_waiting():
    proven = _decide_unconfigured(0, checker=lambda _box: True)
    assert proven.action == BossOrderAction.CLICK_LAST_NOT_UNLOCKED
    assert proven.target_card.no == 11

    # 已达目录上限的末卡本身就是证明，不需要看 L+1
    catalog_last = decide_boss_order_action(
        target_no=None,
        visible_cards=[VisibleCard(no=20, name="20鲁克玛", x=100, y=360, w=58, h=58, score=0.9)],
        at_bottom=True,
        page_type="HEIRLOOM_DIALOG",
        slot_empty_checker=lambda _box: False,
    )
    assert catalog_last.action == BossOrderAction.CLICK_LAST_NOT_UNLOCKED


def test_path_a_unconfigured_offscreen_next_slot_is_not_proof():
    # 行尾末卡的 L+1 在下一行、超出视野：不算证明，只能有限重观察后兜底
    cards = [VisibleCard(no=12, name="12卡尔加", x=334, y=460, w=58, h=58, score=0.9),
             VisibleCard(no=11, name="11拉什凡", x=256, y=460, w=58, h=58, score=0.9)]
    wait = decide_boss_order_action(
        target_no=None, visible_cards=cards, at_bottom=True, viewport_box=_VIEWPORT,
        slot_empty_checker=lambda _box: True, unresolved_attempts=0,
    )
    assert wait.action == BossOrderAction.WAIT
    assert "超出视野" in wait.reason
    closed = decide_boss_order_action(
        target_no=None, visible_cards=cards, at_bottom=True, viewport_box=_VIEWPORT,
        slot_empty_checker=lambda _box: True, unresolved_attempts=2,
    )
    assert closed.action == BossOrderAction.CLICK_LAST_VISIBLE_FALLBACK
    assert closed.target_card.no == 12


def test_unresolved_closure_applies_to_every_wait_branch():
    """3B：滚动预算耗尽且未到底 -> WAIT；第 3 次未决时策略直接给出最终兜底。"""
    kwargs = dict(
        target_no=55,
        visible_cards=_ROW3,
        at_bottom=False,
        scroll_attempts=16,
        scroll_limit=16,
    )
    assert decide_boss_order_action(**kwargs, unresolved_attempts=1).action == BossOrderAction.WAIT
    closed = decide_boss_order_action(**kwargs, unresolved_attempts=2)
    assert closed.action == BossOrderAction.CLICK_LAST_VISIBLE_FALLBACK
    assert closed.target_card.no == 11


def test_unresolved_closure_without_cards_is_anomaly_not_click():
    kwargs = dict(target_no=18, visible_cards=[], at_bottom=True)
    assert decide_boss_order_action(**kwargs, unresolved_attempts=0).action == BossOrderAction.WAIT
    closed = decide_boss_order_action(**kwargs, unresolved_attempts=2)
    assert closed.action == BossOrderAction.NO_CARD_ANOMALY
    assert closed.target_card is None
    # 超过上限后持续给出异常动作（执行层靠它推进 重试 -> skip）
    assert decide_boss_order_action(**kwargs, unresolved_attempts=5).action == BossOrderAction.NO_CARD_ANOMALY


def test_unresolved_closure_never_overrides_non_wait_decisions():
    """T≤L 预测格位待确认、T>L 已证明末卡：未决计数再高也不改写。"""
    confirm = decide_boss_order_action(
        target_no=10,
        visible_cards=[_ROW3[0], _ROW3[2]],
        at_bottom=True,
        viewport_box=_VIEWPORT,
        unresolved_attempts=9,
    )
    assert confirm.action == BossOrderAction.CONFIRM_PREDICTED
    assert confirm.target_card is None

    not_unlocked = decide_boss_order_action(
        target_no=18,
        visible_cards=_ROW3,
        at_bottom=True,
        viewport_box=_VIEWPORT,
        slot_empty_checker=lambda _box: True,
        unresolved_attempts=9,
    )
    assert not_unlocked.action == BossOrderAction.CLICK_LAST_NOT_UNLOCKED
    assert not_unlocked.target_card.no == 11

    exhausted = decide_boss_order_action(
        target_no=10,
        visible_cards=_ROW3[:1] + _ROW3[2:],
        at_bottom=True,
        locate_exhausted=True,
        viewport_box=_VIEWPORT,
        slot_empty_checker=lambda _box: True,
        unresolved_attempts=9,
    )
    assert exhausted.action == BossOrderAction.CLICK_LAST_LOCATE_FAILED


def test_heirloom_closure_only_targets_orders_1_to_20():
    moam = VisibleCard(no=54, name="54莫阿姆", x=334, y=460, w=58, h=58, score=0.95)
    card3 = VisibleCard(no=3, name="03洛卡纳哈", x=100, y=300, w=58, h=58, score=0.8)
    # 未配置目标、滚动预算耗尽仍未到底 -> WAIT；第 3 次未决收口时 54 不得成为兜底目标
    kwargs = dict(target_no=None, at_bottom=False, scroll_attempts=16, scroll_limit=16,
                  page_type="HEIRLOOM_DIALOG", unresolved_attempts=2)
    mixed = decide_boss_order_action(visible_cards=[card3, moam], **kwargs)
    assert mixed.action == BossOrderAction.CLICK_LAST_VISIBLE_FALLBACK
    assert mixed.target_card.no == 3
    only_moam = decide_boss_order_action(visible_cards=[moam], **kwargs)
    assert only_moam.action == BossOrderAction.NO_CARD_ANOMALY


def test_l_unknown_no_cards_visible():
    # Frame with no cards recognized at all
    dec = decide_boss_order_action(
        target_no=18,
        visible_cards=[],
        at_bottom=True,
    )
    assert dec.action == BossOrderAction.WAIT

    # Scroll limit exceeded with no cards
    dec_fail = decide_boss_order_action(
        target_no=18,
        visible_cards=[],
        at_bottom=False,
        scroll_attempts=16,
        scroll_limit=16,
    )
    assert dec_fail.action == BossOrderAction.WAIT


def test_boss_24_duplicate_numbers():
    # Both 24戴文戴尔男爵 and 24瑞文戴尔男爵 parse to number 24
    assert parse_boss_order_number("24戴文戴尔男爵") == 24
    assert parse_boss_order_number("24瑞文戴尔男爵") == 24

    card = VisibleCard(no=24, name="24戴文戴尔男爵", x=100, y=200, w=58, h=58, score=0.88)
    dec = decide_boss_order_action(24, [card])
    assert dec.action == BossOrderAction.CLICK_TARGET
    assert dec.target_card.no == 24


def test_p0_2_locate_failure_navigation_matrix():
    """P0-2: Verify locate failure navigation across 3 scenarios:

    1. Upward locate failure -> scrolls down to bottom -> clicks real last card.
    2. Downward scroll limit reached without bottom -> WAIT (never click unproven card).
    3. Return-to-bottom scroll budget exhausted -> WAIT.
    """
    cards = [
        VisibleCard(no=5, name="05克雷什", x=100, y=200, w=58, h=58, score=0.88),
        VisibleCard(no=6, name="06穆坦努斯", x=180, y=200, w=58, h=58, score=0.85),
    ]

    # Scenario 1: Upward locate fails at top, not at bottom -> SCROLL_DOWN with 回到底部
    dec1 = decide_boss_order_action(
        target_no=1,
        visible_cards=cards,
        at_top=True,
        at_bottom=False,
        locate_attempts=3,
        locate_limit=3,
    )
    assert dec1.action == BossOrderAction.SCROLL_DOWN
    assert dec1.stage == "return_to_bottom"
    assert "回到底部" in dec1.reason

    # Once at bottom -> clicks true bottom card with CLICK_LAST_LOCATE_FAILED if L+1 empty
    dec1_bottom = decide_boss_order_action(
        target_no=1,
        visible_cards=cards,
        at_top=False,
        at_bottom=True,
        locate_exhausted=True,
        slot_empty_checker=lambda b: True,
    )
    assert dec1_bottom.action == BossOrderAction.CLICK_LAST_LOCATE_FAILED
    assert dec1_bottom.target_card.no == 6

    # If L+1 has card -> WAIT
    dec1_bottom_card = decide_boss_order_action(
        target_no=1,
        visible_cards=cards,
        at_top=False,
        at_bottom=True,
        locate_exhausted=True,
        slot_empty_checker=lambda b: False,
    )
    assert dec1_bottom_card.action == BossOrderAction.WAIT

    # Scenario 2: Downward search limit reached (3B) and not at bottom -> WAIT
    dec2 = decide_boss_order_action(
        target_no=10,
        visible_cards=cards,
        at_bottom=False,
        scroll_attempts=16,
        scroll_limit=16,
    )
    assert dec2.action == BossOrderAction.WAIT
    assert "禁止任意卡兜底" in dec2.reason

    # Scenario 3: Return-to-bottom scroll limit reached -> WAIT
    dec3 = decide_boss_order_action(
        target_no=1,
        visible_cards=cards,
        at_bottom=False,
        locate_exhausted=True,
        bottom_scroll_attempts=16,
        bottom_scroll_limit=16,
    )
    assert dec3.action == BossOrderAction.WAIT
    assert "禁止任意卡兜底" in dec3.reason


def test_p0_3_physical_last_card_proof_empty_slot():
    """P0-3: T > L requires proving slot L+1 is empty.

    If L+1 contains an unverified card, must not click second-to-last card.
    """
    cards = [
        VisibleCard(no=1, name="01", x=100, y=200, w=58, h=58, score=0.88),
        VisibleCard(no=2, name="02", x=180, y=200, w=58, h=58, score=0.85),
    ]
    viewport = (50, 150, 800, 600)

    # 1. Slot 3 is empty -> L=2 is proven last card -> CLICK_LAST_NOT_UNLOCKED
    dec_empty = decide_boss_order_action(
        target_no=5,
        visible_cards=cards,
        at_bottom=True,
        viewport_box=viewport,
        slot_empty_checker=lambda b: True,
    )
    assert dec_empty.action == BossOrderAction.CLICK_LAST_NOT_UNLOCKED
    assert dec_empty.target_card.no == 2

    # 2. Slot 3 has unverified card, target is 3 (T == L+1) -> CONFIRM_PREDICTED on slot 3
    dec_card_target3 = decide_boss_order_action(
        target_no=3,
        visible_cards=cards,
        at_bottom=True,
        viewport_box=viewport,
        slot_empty_checker=lambda b: False,
    )
    assert dec_card_target3.action == BossOrderAction.CONFIRM_PREDICTED
    assert dec_card_target3.predicted_box is not None

    # 3. Slot 3 has unverified card, target is 5 (T > L+1) -> WAIT (never click 2!)
    dec_card_target5 = decide_boss_order_action(
        target_no=5,
        visible_cards=cards,
        at_bottom=True,
        viewport_box=viewport,
        slot_empty_checker=lambda b: False,
    )
    assert dec_card_target5.action == BossOrderAction.WAIT
    assert "禁止点击倒数第二张" in dec_card_target5.reason


def test_p2_7_offscreen_predicted_box_scrolls_instead_of_confirm():
    """P2-7: If predicted slot is outside viewport, scroll instead of confirm."""
    cards = [
        VisibleCard(no=5, name="05", x=100, y=300, w=58, h=58, score=0.88),
        VisibleCard(no=7, name="07", x=260, y=300, w=58, h=58, score=0.85),
    ]

    # Target 6 is in row 1, interpolated at y=300.
    # 1. If viewport is y in [350, 600], predicted slot y=300 is above viewport -> SCROLL_UP
    viewport_clipped_top = (50, 350, 500, 600)
    dec_top = decide_boss_order_action(
        target_no=6,
        visible_cards=cards,
        at_top=False,
        viewport_box=viewport_clipped_top,
    )
    assert dec_top.action == BossOrderAction.SCROLL_UP
    assert "视野上方" in dec_top.reason

    # 2. If viewport is y in [100, 250], predicted slot y=300 is below viewport -> SCROLL_DOWN
    viewport_clipped_bottom = (50, 100, 500, 250)
    dec_bottom = decide_boss_order_action(
        target_no=6,
        visible_cards=cards,
        at_bottom=False,
        viewport_box=viewport_clipped_bottom,
    )
    assert dec_bottom.action == BossOrderAction.SCROLL_DOWN
    assert "视野下方" in dec_bottom.reason

    # 3. If viewport is y in [200, 500], predicted slot y=300 is inside viewport -> CONFIRM_PREDICTED
    dec_in = decide_boss_order_action(
        target_no=6,
        visible_cards=cards,
        viewport_box=(50, 200, 500, 500),
    )
    assert dec_in.action == BossOrderAction.CONFIRM_PREDICTED


def test_catalog_vs_assets_consistency_and_anomalies():
    """Verify challenge_boss_catalog.json consistency against assets directory.

    Explicitly asserts the known domain anomalies:
    1. Chuanjiaobao 18-20 are present in catalog and assets.
    2. Chuanjiaobao 54莫阿姆 is present in both assets and catalog, but excluded from sorting in HEIRLOOM_DIALOG.
    3. Boss 24戴文戴尔男爵 and 24瑞文戴尔男爵 are aliases in assets (same order 24).
    4. Every asset template stem in assets/Images/boss exists in catalog["boss"] (including 54莫阿姆).
    5. Every asset template stem in assets/Images/chuanjiaobao exists in catalog["chuanjiaobao"].
    6. Catalog max order matches assets: 54 for ARCHIVE_PANEL, 20 for HEIRLOOM_DIALOG.
    """
    from shuabao.policy.boss_order import get_catalog_max_order

    catalog_path = ROOT / "config" / "challenge_boss_catalog.json"
    with open(catalog_path, encoding="utf-8") as f:
        catalog = json.load(f)

    cjb_items = {item["no"]: item for item in catalog["chuanjiaobao"]}
    boss_items = {item["no"]: item for item in catalog["boss"]}

    # 1. 18-20 must be present in chuanjiaobao catalog
    assert 18 in cjb_items
    assert cjb_items[18]["template_stem"] == "18乌索克"
    assert 19 in cjb_items
    assert cjb_items[19]["template_stem"] == "19玛洛恩"
    assert 20 in cjb_items
    assert cjb_items[20]["template_stem"] == "20鲁克玛"

    # Corresponding assets must exist
    cjb_assets = {p.stem for p in (ROOT / "assets" / "Images" / "chuanjiaobao").glob("*.png")}
    assert "18乌索克" in cjb_assets
    assert "19玛洛恩" in cjb_assets
    assert "20鲁克玛" in cjb_assets

    # 2. Known anomaly: 54莫阿姆 in chuanjiaobao assets and catalog, but P1-5 excludes it from heirloom ordering
    assert "54莫阿姆" in cjb_assets
    assert 54 in cjb_items

    # 3. Known anomaly: 24戴文戴尔男爵 and 24瑞文戴尔男爵 in boss assets
    boss_assets = {p.stem for p in (ROOT / "assets" / "Images" / "boss").glob("*.png")}
    assert "24戴文戴尔男爵" in boss_assets
    assert "24瑞文戴尔男爵" in boss_assets
    assert 24 in boss_items
    assert boss_items[24]["template_stem"] in {"24瑞文戴尔男爵", "24戴文戴尔男爵"}

    # 4. Consistency: every boss asset must be registered in catalog["boss"]
    for stem in boss_assets:
        no = parse_boss_order_number(stem)
        assert no in boss_items, f"Boss template {stem} missing from challenge_boss_catalog.json"

    # 5. Consistency: every chuanjiaobao asset must be registered in catalog["chuanjiaobao"]
    for stem in cjb_assets:
        no = parse_boss_order_number(stem)
        assert no in cjb_items, f"Chuanjiaobao template {stem} missing from challenge_boss_catalog.json"

    # 6. Upper bounds
    assert get_catalog_max_order("ARCHIVE_PANEL", catalog) == 54
    assert get_catalog_max_order("HEIRLOOM_DIALOG", catalog) == 20


def test_p1_b_target_earlier_than_visible_at_top_confirms_before_fallback():
    """P1-B: When at_top and target < min_no, must attempt CONFIRM_PREDICTED before fallback."""
    cards = [
        VisibleCard(no=2, name="02耶戈什", x=180, y=200, w=58, h=58, score=0.88),
        VisibleCard(no=3, name="03曲奇", x=260, y=200, w=58, h=58, score=0.85),
    ]
    viewport = (0, 0, 1000, 1000)

    # 1. First locate attempt (attempts=0): must return CONFIRM_PREDICTED, not fallback!
    dec0 = decide_boss_order_action(
        target_no=1,
        visible_cards=cards,
        at_top=True,
        locate_attempts=0,
        locate_limit=3,
        viewport_box=viewport,
    )
    assert dec0.action == BossOrderAction.CONFIRM_PREDICTED
    assert dec0.predicted_box is not None

    # 2. Second attempt (attempts=1): still CONFIRM_PREDICTED
    dec1 = decide_boss_order_action(
        target_no=1,
        visible_cards=cards,
        at_top=True,
        locate_attempts=1,
        locate_limit=3,
        viewport_box=viewport,
    )
    assert dec1.action == BossOrderAction.CONFIRM_PREDICTED

    # 3. Third attempt exhausted (attempts=3): now falls back
    dec_exhausted = decide_boss_order_action(
        target_no=1,
        visible_cards=cards,
        at_top=True,
        at_bottom=False,
        locate_attempts=3,
        locate_limit=3,
        viewport_box=viewport,
    )
    assert dec_exhausted.action == BossOrderAction.SCROLL_DOWN
    assert dec_exhausted.stage == "return_to_bottom"


def test_p1_5_heirloom_dialog_excludes_moam_54_from_ordering():
    """P1-5: In HEIRLOOM_DIALOG, 54莫阿姆 is excluded from visible_cards and ordering."""
    from shuabao.mediator import Mediator, MatchResult
    from shuabao.settings import Settings

    med = Mediator(Settings(), ROOT)
    frame = MagicMock()
    frame.bgr = None
    frame.width = 1600
    frame.height = 900

    # Simulate match_all returning cards 1, 2, and 54莫阿姆
    sim_hits = [
        MatchResult("chuanjiaobao/01暴掠龙", 0.85, 100, 200, 58, 58, 129, 229),
        MatchResult("chuanjiaobao/02血腥猛犸", 0.85, 180, 200, 58, 58, 209, 229),
        MatchResult("chuanjiaobao/54莫阿姆", 0.85, 260, 200, 58, 58, 289, 229),
    ]
    with patch("shuabao.mediator.match_all", return_value=sim_hits):
        pairs = med._find_visible_post_game_boss_cards(frame, "HEIRLOOM_DIALOG")
        visible_nos = [vc.no for vc, mr in pairs]
        assert 54 not in visible_nos
        assert visible_nos == [1, 2]

        # In _find_last_recognized_post_game_boss, 54 is also excluded
        last = med._find_last_recognized_post_game_boss(frame, "HEIRLOOM_DIALOG")
        assert last is not None
        assert "54" not in last.name
        assert "02" in last.name

