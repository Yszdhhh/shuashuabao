# -*- coding: utf-8 -*-
"""实机 2026-09-14 放弃选择面板必须点击暂时隐藏并以面板消失为后置条件回归。

- f1020_action_after.png / f1028_state_change.png: 真实帧上选择面板可见（anchor=skill_refresh_btn）。
- f1029_action_before.png / f1030_action_after.png: 面板仍可见（anchor=treasure_lock_btn）。
- f1031_action_before.png: 点击暂时隐藏后面板完全消失（anchor=None），胜利结算继续游戏按钮露出。
- 验收要求：
  - 放弃选择面板时（达到 episode 上限、超时脱困、Fail-Closed 等）必须物理点击「暂时隐藏」；
  - 必须以「面板消失（anchor is None）」为后置确认条件，未消失前严禁放行主线或重回 ACTIVE。
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
FIXTURES = ROOT / "tests" / "fixtures" / "hitch_postgame_20260914b"


def _load_frame(name: str) -> Frame:
    path = FIXTURES / name
    img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert img is not None, f"Failed to load fixture: {path}"
    return Frame(bgr=img, window_title="英雄三国KK", hwnd=10001, role="l1")


def _mediator() -> Mediator:
    med = Mediator(Settings(dry_run=True, ocr_mode="off", mode_id="lobby_hitch"), ROOT)
    med.set_phase(Phase.MAIN_LINE)
    return med


def test_abandon_panel_on_episode_limit_clicks_hide_and_waits_for_disappearance() -> None:
    med = _mediator()
    med.settings.panel_episode_limit_per_kind = 3
    med._panel_episode_count["treasure"] = 3

    f1028 = _load_frame("f1028_state_change.png")
    f1029 = _load_frame("f1029_action_before.png")
    f1031 = _load_frame("f1031_action_before.png")

    anchor1028 = med._selection_anchor(f1028)
    assert anchor1028 is not None
    # 预设候选使第二帧直接通过双帧确认门闩
    med._panel_anchor_candidate = (anchor1028.name, anchor1028.score)

    now = time.time()
    # 达到上限时，必须转 CLOSING 物理关闭，严禁直接 finish 或进 cooldown 遮挡画面
    act1 = med._tick_panel_fsm(f1028, anchor1028, now)
    assert act1 == LoopAction.Continue
    assert med._panel_state == PanelState.CLOSING

    # CLOSING 状态必须物理点击「暂时隐藏」并进 WAIT_MUTATION
    clicks = []
    with patch.object(med, "act_click", side_effect=lambda hit, reason="": clicks.append((hit.name, reason)) or True):
        act2 = med._tick_panel_fsm(f1028, anchor1028, now + 0.1)
        assert act2 == LoopAction.Continue
        assert med._panel_state == PanelState.WAIT_MUTATION
        assert med._panel_pending_choice_action == "close"
        assert len(clicks) == 1
        assert "hide" in clicks[0][0].lower() or "hide" in clicks[0][1].lower()

        # 面板仍可见（f1029），WAIT_MUTATION 绝不能提前结束或重回 ACTIVE
        anchor1029 = med._selection_anchor(f1029)
        assert anchor1029 is not None
        act3 = med._tick_panel_fsm(f1029, anchor1029, now + 0.2)
        assert act3 == LoopAction.Continue
        assert med._panel_state == PanelState.WAIT_MUTATION

        # 面板彻底消失（f1031，anchor is None），此时方可确认关闭并结束 episode
        anchor1031 = med._selection_anchor(f1031)
        assert anchor1031 is None
        act4 = med._tick_panel_fsm(f1031, anchor1031, now + 0.3)
        assert act4 == LoopAction.Continue
        assert med._panel_state == PanelState.CLOSED
        assert med._panel_pending_choice_action is None


def test_abandon_panel_on_timeout_clicks_hide_and_waits_for_disappearance() -> None:
    med = _mediator()
    f1028 = _load_frame("f1028_state_change.png")
    f1031 = _load_frame("f1031_action_before.png")
    anchor1028 = med._selection_anchor(f1028)
    assert anchor1028 is not None

    now = time.time()
    med._panel_state = PanelState.ACTIVE
    med._panel_kind = "treasure"
    med._panel_episode_started = now - 20.0  # 超出 hard_deadline (10s)

    # 超时脱困：画面仍有锚点时必须转 CLOSING 物理隐藏
    act1 = med._tick_panel_fsm(f1028, anchor1028, now)
    assert act1 == LoopAction.Continue
    assert med._panel_state == PanelState.CLOSING

    # CLOSING 状态点击 hide
    clicks = []
    with patch.object(med, "act_click", side_effect=lambda hit, reason="": clicks.append((hit.name, reason)) or True):
        act2 = med._tick_panel_fsm(f1028, anchor1028, now + 0.1)
        assert act2 == LoopAction.Continue
        assert med._panel_state == PanelState.WAIT_MUTATION
        assert med._panel_pending_choice_action == "close"
        assert len(clicks) == 1

        # f1031 面板消失确认
        anchor1031 = med._selection_anchor(f1031)
        assert anchor1031 is None
        act3 = med._tick_panel_fsm(f1031, anchor1031, now + 0.2)
        assert act3 == LoopAction.Continue
        assert med._panel_state == PanelState.CLOSED


def test_main_line_defense_in_depth_no_leak_when_panel_anchor_present() -> None:
    med = _mediator()
    med.settings.panel_episode_limit_per_kind = 3
    med._panel_episode_count["treasure"] = 3

    f1028 = _load_frame("f1028_state_change.png")
    f1029 = _load_frame("f1029_action_before.png")
    f1031 = _load_frame("f1031_action_before.png")

    anchor1028 = med._selection_anchor(f1028)
    assert anchor1028 is not None
    med._panel_anchor_candidate = (anchor1028.name, anchor1028.score)

    clicks = []
    with patch.object(med, "act_click", side_effect=lambda hit, reason="": clicks.append((hit.name, reason)) or True):
        # Tick 1 on f1028: 触发 CLOSING
        act1 = med._tick_main_line(f1028)
        assert act1 == LoopAction.Continue
        assert med._panel_state == PanelState.CLOSING

        # Tick 2 on f1028: 发送 hide 点击
        act2 = med._tick_main_line(f1028)
        assert act2 == LoopAction.Continue
        assert med._panel_state == PanelState.WAIT_MUTATION
        assert len(clicks) == 1
        assert "hide" in clicks[0][0].lower() or "hide" in clicks[0][1].lower()

        # Tick 3 on f1029: 面板仍可见，严禁 HUD 穿透动作
        act3 = med._tick_main_line(f1029)
        assert act3 == LoopAction.Continue
        assert med._panel_state == PanelState.WAIT_MUTATION

        # Tick 4 on f1031: 面板完全消失，胜利继续游戏按钮无遮挡点击
        act4 = med._tick_main_line(f1031)
        assert act4 == LoopAction.Continue
        assert med._panel_state == PanelState.CLOSED
        assert any(c[1] == "ContinueGame" for c in clicks)


def test_hitch_fail_close_requires_wait_mutation_and_panel_disappearance() -> None:
    med = _mediator()
    f1028 = _load_frame("f1028_state_change.png")
    f1031 = _load_frame("f1031_action_before.png")

    now = time.time()
    med._panel_state = PanelState.ACTIVE
    med._panel_kind = "skill"

    clicks = []
    with patch.object(med, "act_click", side_effect=lambda hit, reason="": clicks.append((hit.name, reason)) or True):
        handled = med._hitch_fail_close_choice_panel(f1028, now)
        assert handled is True
        assert len(clicks) == 1
        assert clicks[0][1] == "HitchPanelFailClosed"
        # 必须转 WAIT_MUTATION 等待面板消失证据，严禁直接进入 COOLDOWN
        assert med._panel_state == PanelState.WAIT_MUTATION
        assert med._panel_pending_choice_action == "close"

        # 面板消失后闭环
        act = med._tick_panel_fsm(f1031, None, now + 0.1)
        assert act == LoopAction.Continue
        assert med._panel_state == PanelState.CLOSED
