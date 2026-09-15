# -*- coding: utf-8 -*-
"""B2 拿卡提速回归：

1. 免二次确认只在「预设命中 + OCR>=0.95 + 四槽无重名」时生效（其余仍两帧）。
   （单卡场景的直接回归见 test_live_run_205044_regressions.py 的三条
   test_owned_bond_select_* 用例；这里补跨面板类型 + 刷新动作不受影响的覆盖。）
2. F4 压力清怪绝不插在一次面板会话（OPEN_REQUESTED→…→CLOSED）中间：
   panel_state != CLOSED 时 _tick_main_line 不得派发 act_key("f4", ...)。
3. 单卡周期改前/改后 tick 数对比（离线，基于真实 _ocr_reward_choice 调用序列，
   不是手工估算）。
"""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import numpy as np

from shuabao.mediator import LoopAction, Mediator, PanelState, Phase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult

ROOT = Path(__file__).resolve().parents[1]


def _frame() -> Frame:
    return Frame(np.zeros((900, 1600, 3), dtype=np.uint8), window_title="英雄三国KK", hwnd=10001)


def _med(**overrides) -> Mediator:
    med = Mediator(Settings(ocr_mode="live", cards=["祝福"], **overrides), ROOT)
    med._panel_opened_by_us = "bond"
    med._panel_kind = "bond"
    return med


UNAMBIGUOUS_SLOTS = [
    {"index": 0, "name": "祝福", "confidence": 0.99, "raw_text": "祝福"},
    {"index": 1, "name": "体术", "confidence": 0.99, "raw_text": "体术"},
    {"index": 2, "name": "亡灵", "confidence": 0.99, "raw_text": "亡灵"},
    {"index": 3, "name": "刀刀", "confidence": 0.99, "raw_text": "刀刀"},
]


def test_refresh_action_still_waits_two_frames_even_when_confident() -> None:
    """免二次确认只覆盖 SELECT_SLOT；REFRESH 决策继续两帧确认。"""
    med = _med()
    slots = [
        {"index": 0, "name": "体术", "confidence": 0.99, "raw_text": "体术"},
        {"index": 1, "name": "亡灵", "confidence": 0.99, "raw_text": "亡灵"},
        {"index": 2, "name": "刀刀", "confidence": 0.99, "raw_text": "刀刀"},
        {"index": 3, "name": "海盗", "confidence": 0.99, "raw_text": "海盗"},
    ]
    with patch.object(med, "_ocr_panel_slots", return_value=slots), \
            patch.object(med, "_panel_can_refresh", return_value=True), \
            patch.object(med, "_bond_refresh_affordable", return_value=(True, 1000, 40)):
        first = med._ocr_reward_choice(_frame(), "bond")
        assert first is None, "无预设命中槽位时刷新决策必须仍走两帧确认"
        second = med._ocr_reward_choice(_frame(), "bond")
    assert second is not None, "刷新决策仍应在第二帧确认后落定"


def test_pressure_clear_never_fires_while_a_panel_session_is_open() -> None:
    """B2：F4 不取消，但不得插在一次面板会话（非 CLOSED 状态）中间。"""
    med = Mediator(Settings(), ROOT)
    med.set_phase(Phase.MAIN_LINE, "test")
    med._auto_task_done = True
    med._post_game_pending = False
    med._pressure_next_at = 0.0  # 压力转移计时已到期，正常 tick 会立刻按 F4
    med._panel_state = PanelState.ACTIVE
    med._panel_kind = "bond"
    med._panel_opened_by_us = "bond"
    med._panel_episode_started = time.time()
    med._panel_first_seen_at = time.time()
    med._panel_last_progress_at = time.time()
    med._panel_hard_deadline_s = 15.0
    anchor = MatchResult("bond_hide_btn", 0.85, 805, 575, 94, 26, 805, 575)

    with patch.object(med, "_hitch_ocr_text", return_value=""), \
            patch.object(med, "_find_failure_gift", return_value=None), \
            patch.object(med, "_post_game_state", return_value=None), \
            patch.object(med, "_selection_anchor", return_value=anchor), \
            patch.object(med, "_find_reward_choice", return_value=None), \
            patch.object(med, "act_click", return_value=False), \
            patch.object(med, "act_key", return_value=True) as key:
        res = med._tick_main_line(_frame())

    assert res == LoopAction.Continue
    key.assert_not_called()
    assert med._panel_state != PanelState.CLOSED


def test_offline_tick_count_for_one_card_pick_drops_by_one_ocr_confirm_tick() -> None:
    """离线 tick 序列对比：预设命中 + 高置信 + 无歧义时，
    _ocr_reward_choice 从「2 次调用才出结果」降到「1 次调用出结果」。
    这一次调用对应主循环一整个 tick（cadence 见 _cadence_for_current_state），
    因此每张这样的卡少走 1 个 tick。
    """
    med = _med()
    with patch.object(med, "_ocr_panel_slots", return_value=UNAMBIGUOUS_SLOTS):
        ticks_after = 0
        hit = None
        while hit is None and ticks_after < 5:
            ticks_after += 1
            hit = med._ocr_reward_choice(_frame(), "bond")
    assert hit is not None
    assert ticks_after == 1, "B2 改后：预设命中+高置信+无歧义应在第 1 次调用（同 tick）出结果"

    # 改前基线（未打 B2 补丁时的行为）：人为关闭快速路径，复现旧的两帧确认，
    # 验证「改前」确实要多打一次 _ocr_panel_slots 调用（多 1 个 tick）。
    med2 = _med()
    with patch.object(med2, "_ocr_panel_slots", return_value=UNAMBIGUOUS_SLOTS), \
            patch.object(Mediator, "_is_unambiguous_high_confidence_pick", return_value=False), \
            patch.object(Mediator, "_SINGLE_FRAME_PICK_CONFIDENCE", 1.01):
        ticks_before = 0
        hit2 = None
        while hit2 is None and ticks_before < 5:
            ticks_before += 1
            hit2 = med2._ocr_reward_choice(_frame(), "bond")
    assert hit2 is not None
    assert ticks_before == 2, "B2 改前基线：同一无歧义高置信命中需要 2 次调用（两帧确认）"
    assert ticks_after == ticks_before - 1
