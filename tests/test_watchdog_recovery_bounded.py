# -*- coding: utf-8 -*-
"""S0 stability — runtime watchdog de-inputization (telemetry only).

Invariants enforced here:
- A stalled MAIN_LINE with two confirmed HUD frames NEVER sends any physical
  input (no ESC): the watchdog only accumulates telemetry and sets a flag.
- Business advancement stays with the core FSM (_advance_l1_cycle / panel
  CLOSING); a true input deadlock is bounded by existing core deadlines.
- Only a real core input (_tick_input_executed) clears the stalled flag and
  refreshes the progress clock.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.loop_action import LoopAction
from shuabao.mediator import Mediator as CoreMediator
from shuabao.mediator import PanelState, Phase
from shuabao.runtime_mediator import Mediator
from shuabao.settings import Settings
from shuabao.vision.capture import Frame


def frame() -> Frame:
    return Frame(
        np.zeros((900, 1600, 3), dtype=np.uint8),
        window_title="英雄三国KK",
        hwnd=1,
    )


def med(**kwargs) -> Mediator:
    settings = Settings(ocr_mode="off", **kwargs)
    return Mediator(settings, ROOT)


def _prime_stalled(m) -> None:
    """Force the watchdog-eligible stall precondition."""
    m.phase = Phase.MAIN_LINE
    m.settings.pre_wave_protection = False
    m.settings.dry_run = False
    m._panel_state = PanelState.CLOSED
    m._post_game_pending = False
    m._pending_action = None
    m._last_runtime_progress_at = 10.0


def test_stalled_watchdog_never_sends_any_input_and_records_telemetry():
    """S0 去输入化：即使 act_key 可用，停滞看门狗也绝不发送任何物理输入；
    停滞只累计 telemetry（stalls 计数 + stalled 旗标 + incident 归档）。"""
    m = med()
    _prime_stalled(m)
    m._RUNTIME_NO_PROGRESS_MAX_STALL_S = 5.0
    with patch("shuabao.runtime_mediator.time.time", return_value=30.5), patch.object(
        m, "act_key", return_value=True
    ) as key, patch.object(
        m, "act_click", return_value=True
    ) as click, patch.object(
        m, "_post_game_state", return_value=None
    ), patch.object(
        m, "_is_in_game_hud", return_value=True
    ), patch.object(
        CoreMediator, "_tick_main_line", return_value=LoopAction.Continue
    ), patch.object(
        m, "set_phase"
    ) as set_phase, patch.object(
        m, "_record_fail_closed_incident"
    ) as incident:
        # tick1 primes the HUD latch (no telemetry yet), tick2+ accumulate.
        m._tick_main_line(frame())
        m._tick_main_line(frame())
        m._tick_main_line(frame())
        m._tick_main_line(frame())

    key.assert_not_called()
    click.assert_not_called()
    set_phase.assert_not_called()
    assert m._runtime_watchdog_stall_episodes_total == 1  # one episode, not per-tick
    assert m._runtime_watchdog_stalled is True
    assert m.phase == Phase.MAIN_LINE, "telemetry-only watchdog must not fail the run"
    assert incident.call_count == 1


def test_verified_progress_clears_stalled_flag_and_marks_progress():
    """A fresh frame proving progress (real core input) resets the stalled
    flag and refreshes the progress clock so normal play continues."""
    m = med()
    _prime_stalled(m)
    m._runtime_watchdog_stall_episodes_total = 2
    m._runtime_watchdog_stalled = True
    # Simulate: core input executed this tick -> progress verified by marker.
    with patch("shuabao.runtime_mediator.time.time", return_value=30.5), patch.object(
        CoreMediator, "_tick_main_line", return_value=LoopAction.Continue
    ):
        m._tick_input_executed = True
        m._tick_main_line(frame())
    assert m._runtime_watchdog_stalled is False, (
        "verified input progress must clear the watchdog stalled flag"
    )
    assert m._last_runtime_progress_at == 30.5
