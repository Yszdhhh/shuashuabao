"""Hitch liveness supervisor (2026-09-12).

Every hitch phase has a no-input budget.  When it runs out the supervisor
observes the real screen and escalates: reconcile / soft reset -> leave ->
BLOCKED.  A running round's legitimate idle only gets the soft reset.
"""

from __future__ import annotations

import contextlib
import io
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from shuabao.mediator import LoopAction, Mediator, PanelState, Phase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "hitch_live_20260911"


def _img(name: str) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(str(FIX / name), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None, name
    return image


def _game(name: str) -> Frame:
    return Frame(_img(name), window_title="英雄三国", hwnd=7, role="l1")


def _med() -> Mediator:
    return Mediator(Settings(mode_id="lobby_hitch", ocr_mode="off"), ROOT)


def _stall(med: Mediator, phase: Phase, seconds: float, world: str) -> None:
    """Put ``med`` in ``phase`` with ``seconds`` of no input, then supervise."""
    if med.phase != phase:
        med.set_phase(phase, "test")
    med._tick_input_executed = False
    med._liveness_last_progress_at = time.time() - seconds
    med._liveness_level_at = None
    with patch.object(med, "_hitch_observe_world", return_value=world), \
         contextlib.redirect_stdout(io.StringIO()):
        med._hitch_liveness_supervise()


def _escalate(med: Mediator, world: str) -> None:
    """One more budget without input at the current level."""
    med._tick_input_executed = False
    med._liveness_level_at = time.time() - 1000.0
    with patch.object(med, "_hitch_observe_world", return_value=world), \
         contextlib.redirect_stdout(io.StringIO()):
        med._hitch_liveness_supervise()


def test_lobby_phase_stuck_on_game_failure_page_is_handed_to_quit_chain() -> None:
    med = _med()
    _stall(med, Phase.LOBBY_ROOM, 100.0, "game_failure")

    assert med.phase == Phase.QUIT
    assert med._recovery_step == "DONE"
    assert med._liveness_level == 1


def test_budget_not_spent_does_nothing() -> None:
    med = _med()
    _stall(med, Phase.LOBBY_ROOM, 30.0, "game_failure")

    assert med.phase == Phase.LOBBY_ROOM
    assert med._liveness_level == 0


def test_designed_search_sleep_extends_the_lobby_budget() -> None:
    from shuabao.lobby_hitch import HitchPhase

    med = _med()
    med.set_phase(Phase.LOBBY_ROOM, "test")
    med._hitch_sm.phase = HitchPhase.SLEEP_RETRY
    med._hitch_sm.sleep_until = time.time() + 20.0
    _stall(med, Phase.LOBBY_ROOM, 120.0, "kk_lobby")
    assert med._liveness_level == 0

    med._hitch_sm.sleep_until = time.time() - 100.0
    _stall(med, Phase.LOBBY_ROOM, 220.0, "kk_lobby")
    assert med._liveness_level == 1


def test_successful_input_resets_the_ladder() -> None:
    med = _med()
    _stall(med, Phase.ROOM_WAITING, 200.0, "kk_room")
    assert med._liveness_level == 1

    med._tick_input_executed = True
    med.last_business_action = "HitchReady"
    med._hitch_liveness_supervise()

    assert med._liveness_level == 0
    assert time.time() - med._liveness_last_progress_at < 1.0


def test_blind_watchdog_esc_is_not_progress() -> None:
    med = _med()
    med.set_phase(Phase.LOBBY_ROOM, "test")
    med._liveness_last_progress_at = time.time() - 100.0
    med._tick_input_executed = True
    med.last_business_action = "HitchStallWatchdogEsc"
    with patch.object(med, "_hitch_observe_world", return_value="kk_other"), \
         contextlib.redirect_stdout(io.StringIO()):
        med._hitch_liveness_supervise()

    assert med._liveness_level == 1


def test_running_round_idle_only_gets_a_soft_reset() -> None:
    med = _med()
    med.set_phase(Phase.MAIN_LINE, "startup found existing game")
    med._round_deadline = None
    med._panel_state = PanelState.ACTIVE
    med._pending_action = object()
    med._l1_cycle_step = "pickup"

    for _ in range(4):
        _stall(med, Phase.MAIN_LINE, 400.0, "game_round")

    assert med.phase == Phase.MAIN_LINE
    assert med._liveness_level == 0
    assert med._panel_state == PanelState.CLOSED
    assert med._pending_action is None
    assert med._l1_cycle_step == "merchant"
    # An attached round still owns a hard deadline.
    assert med._round_deadline is not None


def test_room_ladder_soft_reset_then_leave_then_blocked() -> None:
    med = _med()
    _stall(med, Phase.ROOM_WAITING, 200.0, "kk_room")
    assert med.phase == Phase.ROOM_WAITING
    assert med._liveness_level == 1
    assert med._hitch_ready_timeout_pending is False

    _escalate(med, "kk_room")
    assert med.phase == Phase.ROOM_WAITING
    assert med._liveness_level == 2
    assert med._hitch_ready_timeout_pending is True

    _escalate(med, "kk_room")
    assert med.phase == Phase.ERROR
    assert med.stop_signal.is_set()


def test_stalled_game_is_left_through_the_quit_chain() -> None:
    med = _med()
    med.set_phase(Phase.MAIN_LINE, "startup found existing game")
    _stall(med, Phase.MAIN_LINE, 200.0, "game_unknown")
    assert med.phase == Phase.MAIN_LINE
    assert med._liveness_level == 1

    _escalate(med, "game_unknown")
    assert med.phase == Phase.QUIT
    assert med._recovery_step == "DONE"


def test_swallowed_exit_confirmation_goes_back_to_the_exit_button() -> None:
    med = _med()
    med.set_phase(Phase.NEXT, "exit button clicked")
    _stall(med, Phase.NEXT, 70.0, "game_round")

    assert med.phase == Phase.QUIT


def test_game_gone_during_quit_resets_to_the_lobby_without_counting() -> None:
    med = _med()
    med.set_phase(Phase.QUIT, "round deadline expired")
    med._hitch_opening_pressure_armed = True
    count = med.game_count
    _stall(med, Phase.QUIT, 70.0, "kk_lobby")

    assert med.phase == Phase.LOBBY_ROOM
    assert med.game_count == count
    assert med._hitch_opening_pressure_armed is False


def test_lobby_stuck_on_running_round_enters_main_line() -> None:
    med = _med()
    _stall(med, Phase.LOBBY_ROOM, 100.0, "game_round")

    assert med.phase == Phase.MAIN_LINE


def test_world_observation_reads_the_game_window_first() -> None:
    med = _med()
    cases = {
        "game_failure_page_chat_over_buttons.png": "game_failure",
        "game_waiting_player1_difficulty.png": "game_waiting",
        "game_opening_pressure_and_failure_gift.png": "game_round",
    }
    for name, world in cases.items():
        with patch.object(med, "_probe_l1_game_frame", return_value=_game(name)), \
             contextlib.redirect_stdout(io.StringIO()):
            assert med._hitch_observe_world() == world, name


def test_world_observation_falls_back_to_kk_windows() -> None:
    med = _med()
    room = Frame(_img("room_ready_self_row3_host_row1.png"), window_title="英雄三国KK", hwnd=9, role="l0")
    lobby = Frame(_img("lobby_room_list_812.png"), window_title="英雄三国KK", hwnd=8, role="l0")
    for frame, world in ((room, "kk_room"), (lobby, "kk_lobby")):
        with patch.object(med, "_probe_l1_game_frame", return_value=None), \
             patch.object(med, "_capture_best", return_value=frame), \
             contextlib.redirect_stdout(io.StringIO()):
            assert med._hitch_observe_world() == world


def test_closing_game_window_is_not_readopted_right_after_exit() -> None:
    med = _med()
    med.set_phase(Phase.QUIT, "test")
    with contextlib.redirect_stdout(io.StringIO()):
        med._finish_hitch_round(time.time(), "exit confirmed; hitch re-search")
    assert med.phase == Phase.LOBBY_ROOM

    kk = Frame(_img("lobby_room_list_812.png"), window_title="英雄三国KK", hwnd=8, role="l0")
    probe = MagicMock(return_value=_game("game_postgame_plaza_under_open_bag.png"))
    with patch.object(med, "_probe_l1_game_frame", probe), \
         patch.object(med, "_capture_best", return_value=kk), \
         contextlib.redirect_stdout(io.StringIO()):
        frame = med.see("test")
    assert probe.call_count == 0
    assert frame.hwnd == 8

    med._hitch_game_exit_at = time.time() - med._HITCH_GAME_CLOSE_GRACE_S - 1.0
    with patch.object(med, "_probe_l1_game_frame", probe), \
         patch.object(med, "_capture_best", return_value=kk), \
         contextlib.redirect_stdout(io.StringIO()):
        med.see("test")
    assert probe.call_count == 1


def test_tick_breaks_when_the_supervisor_blocks(tmp_path) -> None:
    med = _med()
    med.set_trace(str(tmp_path / "trace.jsonl"))
    med.set_phase(Phase.LOBBY_ROOM, "test")
    med._liveness_last_progress_at = time.time() - 1000.0
    med._liveness_level = 2
    med._liveness_level_at = time.time() - 1000.0

    def _impl() -> LoopAction:
        med._tick_input_executed = False
        return LoopAction.Continue

    with patch.object(med, "_tick_impl", side_effect=_impl), \
         patch.object(med, "_hitch_observe_world", return_value="none"), \
         contextlib.redirect_stdout(io.StringIO()):
        action = med.tick()

    assert action is LoopAction.Break
    assert med.phase == Phase.ERROR
    # Each tick row is flushed as it is written (live trace reading).
    text = (tmp_path / "trace.jsonl").read_text(encoding="utf-8")
    assert '"stall_level": 3' in text
    med.set_trace(None)


def _dwell(med: Mediator, seconds: float, world: str) -> None:
    """Keep clicking (progress every tick) while ``seconds`` of dwell pass."""
    med._tick_input_executed = True
    med.last_business_action = "QuitGame-open-confirm"
    med._liveness_family_since = time.time() - seconds
    with patch.object(med, "_hitch_observe_world", return_value=world), \
         contextlib.redirect_stdout(io.StringIO()):
        med._hitch_liveness_supervise()


def test_exit_chain_that_keeps_clicking_is_capped() -> None:
    med = _med()
    med.set_phase(Phase.QUIT, "round deadline expired")
    _dwell(med, 0.0, "game_round")  # enters the exit family
    med.set_phase(Phase.NEXT, "exit button clicked")
    _dwell(med, 100.0, "game_round")
    assert med.phase == Phase.NEXT

    _dwell(med, 250.0, "game_round")
    assert med.phase == Phase.ERROR
    assert med.stop_signal.is_set()


def test_room_dwell_cap_leaves_once_then_blocks() -> None:
    med = _med()
    med.set_phase(Phase.ROOM_WAITING, "test")
    _dwell(med, 0.0, "kk_room")
    _dwell(med, 610.0, "kk_room")
    assert med.phase == Phase.ROOM_WAITING
    assert med._hitch_ready_timeout_pending is True

    _dwell(med, 610.0, "kk_room")
    assert med.phase == Phase.ERROR


def test_lobby_search_and_running_round_have_no_dwell_cap() -> None:
    med = _med()
    for phase, world in ((Phase.LOBBY_ROOM, "kk_lobby"), (Phase.MAIN_LINE, "game_round")):
        med.set_phase(phase, "startup found existing game")
        _dwell(med, 0.0, world)
        _dwell(med, 10_000.0, world)
        assert med.phase == phase


def test_supervisor_is_off_outside_unattended_modes_and_in_dry_run() -> None:
    # Cloud audit 2026-09-14 B0: solo now shares the ladder inside a game
    # (tests/test_unattended_recovery_20260914.py); lab and solo lobby
    # phases stay unsupervised.
    lab = Mediator(Settings(mode_id="lab", ocr_mode="off"), ROOT)
    lab.set_phase(Phase.MAIN_LINE, "test")
    lab._liveness_last_progress_at = time.time() - 10_000.0
    lab._tick_input_executed = False
    with patch.object(lab, "_hitch_observe_world") as observe:
        lab._hitch_liveness_supervise()
    assert observe.call_count == 0

    solo = Mediator(Settings(ocr_mode="off"), ROOT)
    solo.set_phase(Phase.PREPARE, "test")
    solo._liveness_last_progress_at = time.time() - 10_000.0
    solo._tick_input_executed = False
    with patch.object(solo, "_hitch_observe_world") as observe:
        solo._hitch_liveness_supervise()
    assert observe.call_count == 0

    dry = Mediator(Settings(mode_id="lobby_hitch", ocr_mode="off", dry_run=True), ROOT)
    dry.set_phase(Phase.LOBBY_ROOM, "test")
    dry._liveness_last_progress_at = time.time() - 10_000.0
    dry._tick_input_executed = False
    with patch.object(dry, "_hitch_observe_world") as observe:
        dry._hitch_liveness_supervise()
    assert observe.call_count == 0
