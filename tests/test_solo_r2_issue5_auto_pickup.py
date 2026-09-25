# -*- coding: utf-8 -*-
"""Regression tests for Issue 5: Connecting auto pickup [Z] to solo L1 cycle.

Owner observed:
- In solo round 2 (solo_ingame_chain_20260925_190942_836832), pickup step never
  performed range pickup because _hud_item_bar_overflowed required all 5 item slots
  to be full.
- Fix: Solo mode performs range pickup [Z] on cooldown when the cycle reaches pickup,
  without gating on full inventory overflow. Passenger/hitch mode retains overflow gate.
"""
from __future__ import annotations

import contextlib
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from shuabao.loop_action import LoopAction
from shuabao.mediator import Mediator, PanelState, Phase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult

ROOT = Path(__file__).resolve().parents[1]


def _make_frame() -> Frame:
    return Frame(np.zeros((900, 1600, 3), dtype=np.uint8), window_title="英雄三国KK", hwnd=10001, role="l1")


def _setup_solo_med(**kwargs) -> Mediator:
    med = Mediator(Settings(ocr_mode="off", mode_id="normal_farm", **kwargs), ROOT)
    med.set_phase(Phase.MAIN_LINE)
    med._panel_state = PanelState.CLOSED
    med._l1_cycle_step = "pickup"
    med._l1_cycle_index = med._L1_CYCLE_ORDER.index("pickup")
    med._auto_task_done = True
    med._main_line_started_at = 1.0
    med._wood_balance = 2000
    return med


@contextlib.contextmanager
def _mock_hud_env(med: Mediator):
    with patch.object(med, "_post_game_state", return_value=None), \
         patch.object(med, "find", return_value=None), \
         patch.object(med, "_find_equipment_affix_choice", return_value=None), \
         patch.object(med, "_selection_anchor", return_value=None), \
         patch.object(med, "_ensure_auto_task_enabled", return_value=None), \
         patch.object(med, "_ensure_challenge_buttons", return_value=None), \
         patch.object(med, "_find_stage_page", return_value=False), \
         patch.object(med, "_handle_self_opened_compact_panel", return_value=None), \
         patch.object(med, "_maybe_open_choice_panel", return_value=None), \
         patch.object(med, "_maybe_ensure_hero_panel_focus", return_value=None), \
         patch.object(med, "_maybe_fire_artifacts", return_value=None), \
         patch.object(med, "_maybe_opportunistic_evolve", return_value=None), \
         patch.object(med, "_is_in_game_hud", return_value=True), \
         patch.object(med, "_urgent_merchant_reason", return_value=None):
        yield


def test_solo_cycle_picks_up_when_cooldown_ready_even_without_overflow() -> None:
    med = _setup_solo_med()
    frame = _make_frame()
    now = 100.0
    med._pickup_next_at = now - 1.0

    with _mock_hud_env(med), \
         patch("time.time", return_value=now), \
         patch.object(med, "_hud_item_bar_overflowed", return_value=False), \
         patch.object(med, "_hud_item_bar_occupied_count", return_value=1), \
         patch.object(med, "_hud_hotkey_button", return_value=None), \
         patch.object(med, "act_key", return_value=True) as mock_key:
        res = med._tick_main_line(frame)

    assert res == LoopAction.Continue
    mock_key.assert_called_once_with("z", "Pickup-Z")
    assert med._pickup_next_at == now + 10.0
    assert med._l1_cycle_step == "merchant"


def test_solo_cycle_clicks_hud_pickup_button_when_available() -> None:
    med = _setup_solo_med()
    frame = _make_frame()
    now = 100.0
    med._pickup_next_at = now - 1.0
    button = MatchResult("bag/hud_pickup_button", 0.95, 1500, 700, 30, 30, 1500, 700)

    with _mock_hud_env(med), \
         patch("time.time", return_value=now), \
         patch.object(med, "_hud_item_bar_overflowed", return_value=False), \
         patch.object(med, "_hud_hotkey_button", return_value=button), \
         patch.object(med, "act_click", return_value=True) as mock_click, \
         patch.object(med, "act_key") as mock_key:
        res = med._tick_main_line(frame)

    assert res == LoopAction.Continue
    mock_click.assert_called_once_with(button, "Pickup-Z")
    mock_key.assert_not_called()
    assert med._pickup_next_at == now + 10.0
    assert med._l1_cycle_step == "merchant"


def test_solo_cycle_respects_pickup_cooldown() -> None:
    med = _setup_solo_med()
    frame = _make_frame()
    now = 100.0
    med._pickup_next_at = now + 5.0  # Cooldown not reached

    with _mock_hud_env(med), \
         patch("time.time", return_value=now), \
         patch.object(med, "_hud_item_bar_overflowed", return_value=False), \
         patch.object(med, "act_key") as mock_key, \
         patch.object(med, "act_click") as mock_click:
        res = med._tick_main_line(frame)

    assert res == LoopAction.Continue
    mock_key.assert_not_called()
    mock_click.assert_not_called()
    assert med._l1_cycle_step == "merchant"


def test_hitch_cycle_still_requires_overflow() -> None:
    med = Mediator(Settings(ocr_mode="off", mode_id="lobby_hitch"), ROOT)
    med.set_phase(Phase.MAIN_LINE)
    med._panel_state = PanelState.CLOSED
    med._l1_cycle_step = "pickup"
    med._auto_task_done = True
    med._main_line_started_at = 1.0
    frame = _make_frame()
    now = 100.0
    med._pickup_next_at = now - 1.0

    with _mock_hud_env(med), \
         patch("time.time", return_value=now), \
         patch.object(med, "_hud_item_bar_overflowed", return_value=False), \
         patch.object(med, "_pickup_bag_has_space", return_value=True), \
         patch.object(med, "act_key") as mock_key, \
         patch.object(med, "act_click") as mock_click:
        res = med._tick_main_line(frame)

    assert res == LoopAction.Continue
    mock_key.assert_not_called()
    mock_click.assert_not_called()
    assert med._l1_cycle_step != "pickup"
