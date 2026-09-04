# -*- coding: utf-8 -*-
"""Stage 1 Task 3 — bounded mechanical recovery (RuntimeWatchdog-EscUnstuck).

Invariants enforced here:
- ESC success (act_key True) is NOT business success; a fresh frame must
  prove page mutation (progress re-arm) before the watchdog re-fires.
- Same-target attempts are bounded; budget exhaustion escalates to the
  existing fail-closed ERROR phase, never an UNKNOWN→ESC fallback.
- UNKNOWN frame = zero input at all times.
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
    m._runtime_watchdog_esc_attempts = 0


def test_esc_unstuck_click_success_without_page_mutation_consumes_budget_and_fails_closed():
    """act_key True but stale progress (no mutation) must consume attempt budget;
    exceeding the bounded cap must fail closed into the existing ERROR phase,
    never loop ESC forever and never claim success."""
    m = med()
    _prime_stalled(m)
    m._RUNTIME_STALL_TIMEOUT_S = 5.0
    # act_key succeeds physically each time, but _mark_runtime_progress is
    # stubbed to a no-op: page mutation never verified.
    with patch("shuabao.runtime_mediator.time.time", return_value=30.5), patch.object(
        m, "act_key", return_value=True
    ) as key, patch.object(
        m, "_mark_runtime_progress"
    ), patch.object(
        m, "_post_game_state", return_value=None
    ), patch.object(
        m, "_is_in_game_hud", return_value=True
    ), patch.object(
        CoreMediator, "_tick_main_line", return_value=LoopAction.Continue
    ) as core, patch.object(
        m, "set_phase"
    ) as set_phase:
        # HUD latch needs two distinct frames before the watchdog is armed:
        # tick1 primes the latch (no send), tick2 send(=1), tick3 send(=2),
        # tick4 entry gate sees 2>=2 -> fail-closed, no further ESC.
        first = m._tick_main_line(frame())
        second = m._tick_main_line(frame())
        third = m._tick_main_line(frame())
        fourth = m._tick_main_line(frame())

    assert first is LoopAction.Continue
    assert second is LoopAction.Continue
    assert third is LoopAction.Continue
    assert fourth is LoopAction.Continue
    set_phase.assert_called_once()
    assert set_phase.call_args[0][0] is Phase.ERROR
    assert key.call_count == 2, "budget cap must stop further ESC after 2 sends"
    assert m._runtime_watchdog_esc_attempts >= m._RUNTIME_WATCHDOG_MAX_ESC_ATTEMPTS


def test_unverified_progress_does_not_rearm_watchdog_budget():
    """After ESC, only verified progress (fresh-frame mutation) resets the
    attempt counter; an act_key success with no observed progress must keep
    the counter accumulating toward the bounded cap."""
    m = med()
    _prime_stalled(m)
    m._RUNTIME_STALL_TIMEOUT_S = 5.0
    with patch("shuabao.runtime_mediator.time.time", return_value=30.5), patch.object(
        m, "act_key", return_value=True
    ), patch.object(m, "_mark_runtime_progress"), patch.object(
        m, "_post_game_state", return_value=None
    ), patch.object(
        m, "_is_in_game_hud", return_value=True
    ), patch.object(
        CoreMediator, "_tick_main_line", return_value=LoopAction.Continue
    ), patch.object(
        m, "set_phase"
    ):
        # tick1 primes the HUD latch (no send), tick2 send(=1), tick3
        # send(=2): the counter accumulates because no fresh-frame verified
        # progress occurs (all progress markers stubbed out).
        m._tick_main_line(frame())
        first = m._runtime_watchdog_esc_attempts
        m._tick_main_line(frame())
        second = m._runtime_watchdog_esc_attempts
        m._tick_main_line(frame())
        third = m._runtime_watchdog_esc_attempts
    assert first == 0
    assert second == 1
    assert third == 2, "unverified progress must not re-arm the watchdog budget"


def test_verified_progress_rearms_watchdog_budget():
    """A fresh frame proving progress (via real _mark_runtime_progress call
    path) resets the same-target attempt counter so normal play continues."""
    m = med()
    _prime_stalled(m)
    m._RUNTIME_STALL_TIMEOUT_S = 5.0
    m._runtime_watchdog_esc_attempts = 2  # one below cap
    # Simulate: core input executed this tick -> progress verified by marker.
    with patch("shuabao.runtime_mediator.time.time", return_value=30.5), patch.object(
        CoreMediator, "_tick_main_line", return_value=LoopAction.Continue
    ) as core:
        m._tick_input_executed = True
        m._tick_main_line(frame())
    assert m._runtime_watchdog_esc_attempts == 0, (
        "verified input progress must re-arm the bounded watchdog budget"
    )
