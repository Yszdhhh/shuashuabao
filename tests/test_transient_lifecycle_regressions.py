# -*- coding: utf-8 -*-
"""Stage 1 Task 2 — transient-state episode-boundary leak regressions."""

import time
from pathlib import Path
from unittest.mock import MagicMock

from shuabao.mediator import Mediator, Phase, PendingAction
from shuabao.runtime_mediator import Mediator as LiveMediator
from shuabao.settings import Settings

ROOT = Path(__file__).resolve().parents[1]


def test_pending_action_leaks_across_round_reset():
    """_pending_action / unconfirmed count must not survive into a new episode."""
    med = Mediator(Settings(), ROOT)
    now = time.time()
    med._pending_action = PendingAction(
        kind="WAIT_HERO_CHOICE",
        target_id="hero_card_item",
        deadline=now + 10.0,
        verifier=lambda *args, **kwargs: False,
    )

    med.set_phase(Phase.STAGE_SELECT, "new round started")

    assert med._pending_action is None, "_pending_action must be None on new episode boundary"
    assert med._pending_action_unconfirmed_count == 0, (
        "_pending_action_unconfirmed_count must be 0 on new episode boundary"
    )


def test_hitch_floor_exit_flags_leak_across_lobby_reset():
    """Hitch floor-exit flags must be cleared when returning to lobby search."""
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    med._hitch_floor_exit_pending = True
    med._hitch_floor_exit_confirmed = True
    med._hitch_floor_exit_attempted_at = time.time()

    med._hitch_after_exit(time.time())

    assert med._hitch_floor_exit_pending is False
    assert med._hitch_floor_exit_confirmed is False
    assert med._hitch_floor_exit_attempted_at is None


def test_runtime_watchdog_hud_latch_leaks_across_main_line_reset():
    """Runtime watchdog HUD latch must be re-armed from zero across episodes."""
    med = LiveMediator(Settings(), ROOT)
    med._is_in_game_hud = MagicMock(return_value=True)
    med._post_game_state = MagicMock(return_value=None)

    assert not med._runtime_watchdog_hud_confirmed(MagicMock())
    assert med._runtime_watchdog_hud_confirmed(MagicMock())
    assert med._runtime_watchdog_hud_confirmations >= 2

    med.set_phase(Phase.MAIN_LINE, "re-enter main line")

    assert med._runtime_watchdog_hud_confirmations == 0
    assert med._runtime_watchdog_last_frame_id is None
