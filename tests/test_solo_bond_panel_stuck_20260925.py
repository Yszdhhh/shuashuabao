# -*- coding: utf-8 -*-
"""实机 2026-09-25 局内单人模式羁绊面板刷新耗尽/超时卡死回归测试。

真实事故场景（solo_ingame_chain_20260925_230841_870781）：
- tick 289 刷新 2/2 耗尽；
- tick 290 突变确认回到 ACTIVE；
- tick 291 因 episode 累计耗时 15.5s 触发 hard deadline 超时脱困，但 solo 模式未转 CLOSING，进入 COOLDOWN；
- tick 294 达到 episode limit，solo 模式再次仅进 COOLDOWN 60s；
- tick 295–424 连续约 130 ticks 在 COOLDOWN 中因画面 anchor 存在每 tick 返回 Continue，画面上面板一直开着零动作；
- 修复要求：
  1) 刷新用完且无目标卡时，必须选择"暂时隐藏"关闭面板（PolicyAction.CLOSE）；
  2) 超时脱困或达到 episode limit 时，只要画面仍有 anchor，必须转 CLOSING 物理隐藏面板，严禁留在画面上进 COOLDOWN；
  3) COOLDOWN 状态若检测到画面仍有物理 anchor，必须立即纠偏转 CLOSING 物理关闭，绝不能连续 60s 零动作；
  4) 活跃交互中（突变、点击）以最后进展时间计算活跃度，避免合法多轮刷新被误判为死锁超时。
"""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
import pytest

from shuabao.mediator import LoopAction, Mediator, PanelState, Phase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "solo_bond_stuck_20260925" / "f0357_state_change.png"


def _load_f0357() -> Frame:
    assert FIXTURE_PATH.is_file(), f"Fixture missing: {FIXTURE_PATH}"
    img = cv2.imdecode(np.fromfile(str(FIXTURE_PATH), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert img is not None, f"Failed to load fixture: {FIXTURE_PATH}"
    return Frame(bgr=img, window_title="英雄三国KK", hwnd=10001, role="l1")


def _solo_mediator() -> Mediator:
    med = Mediator(Settings(dry_run=True, ocr_mode="live", mode_id="solo"), ROOT)
    med.set_phase(Phase.MAIN_LINE)
    med.settings.bond_target_names = ["祝福", "大圣", "海贼王"]
    return med


def test_solo_bond_exhausted_refreshes_selects_card_hide_to_close() -> None:
    """f0357 真实帧：4 张非目标卡（箭术/三国/体术/法术），刷新已达上限 2/2，必须选择暂时隐藏按钮关闭面板。"""
    med = _solo_mediator()
    frame = _load_f0357()

    anchor = med._selection_anchor(frame)
    assert anchor is not None
    assert "bond" in anchor.name or "hide" in anchor.name

    now = time.time()
    med._enter_panel_episode(frame, anchor, "bond", opened=True)
    med._skill_refresh_attempts = 2  # 刷新次数已用尽2/2
    med._sync_choice_session_refreshes()

    clicks = []
    with patch.object(med, "act_click", side_effect=lambda hit, reason="": clicks.append((hit.name, reason)) or True):
        act = med._tick_panel_fsm(frame, anchor, now)
        assert act == LoopAction.Continue
        assert len(clicks) == 1
        clicked_name, clicked_reason = clicks[0]
        # 必须点击暂时隐藏按钮（card_hide 或 bond_hide_btn），严禁盲点卡片或刷新
        assert "hide" in clicked_name.lower() or "close" in clicked_reason.lower()
        # 动作派发后必须转入 WAIT_MUTATION 等待关闭生效
        assert med._panel_state == PanelState.WAIT_MUTATION
        assert med._panel_pending_choice_action == "close"


def test_solo_bond_episode_limit_with_physical_panel_transitions_to_closing() -> None:
    """达到 episode limit 时，若画面仍有物理面板，单人模式也必须转 CLOSING 点击暂时隐藏，绝不可留屏进 COOLDOWN。"""
    med = _solo_mediator()
    med.settings.panel_episode_limit_per_kind = 1
    med._panel_episode_count["bond"] = 1

    frame = _load_f0357()
    anchor = med._selection_anchor(frame)
    assert anchor is not None
    # 模拟双帧确认门闩通过
    med._panel_anchor_candidate = (anchor.name, anchor.score)

    now = time.time()
    med._panel_state = PanelState.CLOSED

    clicks = []
    with patch.object(med, "act_click", side_effect=lambda hit, reason="": clicks.append((hit.name, reason)) or True):
        # Tick 1: 触发上限检测，因画面有 anchor 必须转 CLOSING
        act1 = med._tick_panel_fsm(frame, anchor, now)
        assert act1 == LoopAction.Continue
        assert med._panel_state == PanelState.CLOSING

        # Tick 2: CLOSING 状态派发 hide 点击，转 WAIT_MUTATION
        act2 = med._tick_panel_fsm(frame, anchor, now + 0.1)
        assert act2 == LoopAction.Continue
        assert med._panel_state == PanelState.WAIT_MUTATION
        assert len(clicks) == 1
        assert "hide" in clicks[0][0].lower() or "close" in clicks[0][1].lower()


def test_solo_cooldown_with_physical_panel_resyncs_and_closes_immediately() -> None:
    """面板状态机为 COOLDOWN 但画面上仍有物理面板（脱节），必须立即转 CLOSING 物理隐藏，严禁长达 60s 零动作。"""
    med = _solo_mediator()
    frame = _load_f0357()
    anchor = med._selection_anchor(frame)
    assert anchor is not None

    now = time.time()
    med._panel_state = PanelState.COOLDOWN
    med._panel_kind = "bond"
    med._panel_cooldown_until["bond"] = now + 60.0  # 仍在 60s 冷却中

    clicks = []
    with patch.object(med, "act_click", side_effect=lambda hit, reason="": clicks.append((hit.name, reason)) or True):
        # 必须检测到画面与状态脱节，立即转 CLOSING
        act1 = med._tick_panel_fsm(frame, anchor, now)
        assert act1 == LoopAction.Continue
        assert med._panel_state == PanelState.CLOSING

        # 下一 tick 点击 hide 物理隐藏
        act2 = med._tick_panel_fsm(frame, anchor, now + 0.1)
        assert act2 == LoopAction.Continue
        assert med._panel_state == PanelState.WAIT_MUTATION
        assert len(clicks) == 1


def test_solo_episode_timeout_with_physical_panel_transitions_to_closing() -> None:
    """硬超时（如连续 15s 无有效进展）脱困时，画面仍有物理 anchor 必须转 CLOSING 隐藏面板。"""
    med = _solo_mediator()
    frame = _load_f0357()
    anchor = med._selection_anchor(frame)
    assert anchor is not None

    now = time.time()
    med._panel_state = PanelState.ACTIVE
    med._panel_kind = "bond"
    med._panel_episode_started = now - 20.0
    med._panel_last_progress_at = now - 20.0
    med._panel_last_input_at = now - 20.0

    act = med._tick_panel_fsm(frame, anchor, now)
    assert act == LoopAction.Continue
    assert med._panel_state == PanelState.CLOSING
