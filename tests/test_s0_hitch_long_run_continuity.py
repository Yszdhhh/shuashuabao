# -*- coding: utf-8 -*-
"""Long-run hitch continuity: outcome wins, optional steps skip, no blind lobby."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.loop_action import LoopAction
from shuabao.mediator import Mediator, Phase, RecoveryKind
from shuabao.run_exit import RunExitReason, is_legal_hitch_terminal
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult


def _hitch() -> Mediator:
    return Mediator(Settings(mode_id="lobby_hitch", dry_run=True, ocr_mode="off"), ROOT)


def _game_frame(hwnd: int = 20) -> Frame:
    return Frame(
        np.full((900, 1600, 3), 40, dtype=np.uint8),
        window_title="英雄三国KK",
        hwnd=hwnd,
        role="l1",
    )


def _platform_frame(hwnd: int = 7, width: int = 1280, height: int = 800) -> Frame:
    return Frame(
        np.full((height, width, 3), 30, dtype=np.uint8),
        window_title="KK官方对战平台",
        hwnd=hwnd,
        role="l0",
    )


def _hit(name: str, x: int = 800, y: int = 500) -> MatchResult:
    return MatchResult(name, 0.95, x, y, 40, 24, x, y)


def test_optional_pressure_cannot_block_victory_observation() -> None:
    med = _hitch()
    med.set_phase(Phase.MAIN_LINE)
    frame = _game_frame()
    continue_hit = _hit("continueGame", 820, 560)
    pressure_called = {"n": 0}

    def blocked_pressure(frame_arg, now):
        pressure_called["n"] += 1
        return LoopAction.Continue

    with patch.object(med, "_hitch_ocr_text", return_value=""), \
            patch.object(med, "_post_game_state", return_value="POST_VICTORY"), \
            patch.object(med, "_maybe_click_hitch_pressure_transfer", side_effect=blocked_pressure), \
            patch.object(med, "find", return_value=continue_hit), \
            patch.object(med, "act_click", return_value=True) as click, \
            patch.object(med, "stop") as stop:
        action = med._tick_main_line(frame)
    assert action is LoopAction.Continue
    assert pressure_called["n"] == 0
    click.assert_called()
    assert click.call_args.args[1] == "continueGame" or click.call_args.args[0] is continue_hit
    stop.assert_not_called()
    assert med._run_exit_reason is None


def test_pressure_unconfirmed_is_not_success_and_budget_skip_keeps_run() -> None:
    med = _hitch()
    frame = _game_frame()
    button = _hit("yalizhuanyi", 1200, 700)
    with patch.object(med, "_is_in_game_hud", return_value=True), \
            patch.object(med, "find", return_value=button), \
            patch.object(med, "act_click", return_value=True):
        assert med._maybe_click_hitch_pressure_transfer(frame, 10.0) is LoopAction.Continue
    assert med._hitch_pressure_transferred is False
    assert med._hitch_pressure_click_at == 10.0

    with patch.object(med, "_is_in_game_hud", return_value=True), \
            patch.object(med, "find", return_value=button):
        assert med._maybe_click_hitch_pressure_transfer(frame, 16.0) is LoopAction.Continue
    assert med._hitch_pressure_transferred is False

    med._hitch_pressure_retry_count = med._HITCH_PRESSURE_ATTEMPT_LIMIT
    with patch.object(med, "_is_in_game_hud", return_value=True), \
            patch.object(med, "find", return_value=button), \
            patch.object(med, "act_click", return_value=True) as click, \
            patch.object(med, "stop") as stop:
        assert med._maybe_click_hitch_pressure_transfer(frame, 40.0) is None
    assert med._hitch_pressure_transferred is False
    assert med._hitch_pressure_skipped is True
    click.assert_not_called()
    stop.assert_not_called()
    assert med._run_exit_reason is None


def test_unknown_page_does_not_permanent_continue() -> None:
    med = _hitch()
    med.set_phase(Phase.LOBBY_ROOM)
    frame = _platform_frame()
    dialog = _hit("lobby_popup_dialog", 400, 300)
    with patch.object(med, "find_scene", return_value=dialog), \
            patch.object(med, "act_key") as key, \
            patch.object(med, "act_click") as click:
        first = med._tick_lobby_hitch(frame, "LOBBY_ROOM")
    assert first is LoopAction.Continue
    key.assert_not_called()
    click.assert_not_called()
    assert med._hitch_surface_phase == "reobserve"
    assert med._hitch_unknown_since is not None

    with patch.object(med, "find_scene", return_value=dialog), \
            patch.object(med, "act_key") as key2, \
            patch("shuabao.mediator.time.time", return_value=float(med._hitch_surface_since) + 5.0):
        second = med._tick_lobby_hitch(frame, "LOBBY_ROOM")
    assert second is LoopAction.Continue
    key2.assert_not_called()
    assert med._hitch_surface_phase == "reacquire"
    assert med.phase is not Phase.ERROR
    assert med._run_exit_reason is None


def test_unhealthy_game_window_reacquires_without_blind_lobby() -> None:
    med = _hitch()
    med.phase = Phase.MAIN_LINE
    med._hitch_last_game_hwnd = 20
    frame = Frame(
        np.zeros((900, 1600, 3), dtype=np.uint8),
        window_title="英雄三国KK",
        hwnd=20,
        role="l1",
    )
    med.see = lambda reason="": frame
    with patch.object(med, "stop") as stop, \
            patch.object(med, "_hitch_try_reacquire_same_hwnd", return_value=False) as reacquire:
        assert med.tick() is LoopAction.Continue
    assert med.phase is Phase.MAIN_LINE
    stop.assert_not_called()
    reacquire.assert_not_called()  # first cycle is reobserve, zero business input
    assert med._hitch_surface_phase == "reobserve"

    with patch.object(med, "_hitch_lobby_handoff_authorized", return_value=False), \
            patch.object(med, "_hitch_try_reacquire_same_hwnd", return_value=True) as reacquire2:
        assert med._hitch_advance_surface_recovery(frame, med._hitch_surface_since + 5.0, med._hitch_surface_reason) is LoopAction.Continue
    assert med.phase is Phase.MAIN_LINE
    reacquire2.assert_called()
    assert med._hitch_surface_phase == "reacquire"


def test_lobby_handoff_requires_fresh_game_absent_and_platform() -> None:
    med = _hitch()
    med.set_phase(Phase.MAIN_LINE)
    platform = _platform_frame()
    with patch.object(med, "_hitch_after_exit") as after_exit:
        assert med._hitch_advance_surface_recovery(platform, 10.0, "unhealthy") is LoopAction.Continue
    after_exit.assert_not_called()
    assert med.phase is Phase.MAIN_LINE

    med._hitch_last_game_hwnd = 20
    med._hitch_surface_coarse = "GAME"
    with patch.object(med, "_hitch_game_absent_proven", return_value=True), \
            patch.object(med, "_hitch_after_exit", wraps=med._hitch_after_exit) as after_exit:
        action = med._hitch_advance_surface_recovery(platform, 12.0, "unhealthy")
    assert action is LoopAction.Continue
    after_exit.assert_called_once()
    assert med.phase is Phase.LOBBY_ROOM
    assert med._run_exit_reason is None


def test_recovery_failed_hitch_has_no_illegal_stop_and_no_cleanup_first() -> None:
    med = _hitch()
    med._begin_recovery(RecoveryKind.FAIL)
    rs = med._recovery_state
    with patch.object(med, "_hitch_after_exit") as after_exit, \
            patch.object(med, "stop") as stop, \
            patch.object(med, "_hitch_lobby_handoff_authorized", return_value=False):
        action = med._recovery_failed(rs, "anchor missing")
    assert action is LoopAction.Continue
    after_exit.assert_not_called()
    stop.assert_not_called()
    assert med.phase is Phase.RECOVER_FAILURE
    assert not is_legal_hitch_terminal(med._run_exit_reason)
    assert med._run_exit_reason is None


def test_popup_esc_dispatch_is_not_dismiss_and_exhaustion_is_not_permanent_wait() -> None:
    med = _hitch()
    med.set_phase(Phase.ROOM_WAITING)
    med._hitch_popup_esc_attempts = med._HITCH_POPUP_ESC_LIMIT
    frame = Frame(
        np.full((260, 440, 3), 18, dtype=np.uint8),
        window_title="KK官方对战平台",
        hwnd=106758834,
        role="l0",
    )
    with patch.object(med, "act_key") as key, \
            patch.object(med, "act_click") as click, \
            patch.object(med, "stop") as stop:
        action = med._tick_lobby_hitch(frame, "UNKNOWN")
    key.assert_not_called()
    click.assert_not_called()
    assert action is LoopAction.Continue
    assert med._hitch_popup_esc_pending_kind is None
    assert med._hitch_re_search is False
    assert med._hitch_surface_phase == "reobserve"
    stop.assert_not_called()
    assert med.phase is Phase.ROOM_WAITING


def test_hitch_stop_paths_in_this_module_carry_run_exit_reason() -> None:
    med = _hitch()
    med.settings.cycle_num = 1
    with patch.object(med, "_hitch_after_exit"):
        assert med._finish_hitch_round(1.0, "verified") is LoopAction.Break
    assert med.phase is Phase.COMPLETE
    assert med._run_exit_reason is RunExitReason.CONFIGURED_CYCLE_COMPLETE
    assert is_legal_hitch_terminal(med._run_exit_reason)

    med2 = _hitch()
    med2.stop_signal.trigger("Shift+F12 emergency stop")
    assert med2._attribute_active_stop() is RunExitReason.EMERGENCY_STOP

    med3 = _hitch()
    med3.note_external_stop(RunExitReason.USER_STOP)
    med3.stop()
    assert med3._run_exit_reason is RunExitReason.USER_STOP
    assert is_legal_hitch_terminal(med3._run_exit_reason)

    med4 = _hitch()
    med4.stop(RunExitReason.UIPI_FATAL)
    assert med4._run_exit_reason is RunExitReason.UIPI_FATAL

    med5 = _hitch()
    med5.note_external_stop(RunExitReason.UNRECOVERABLE_CRASH)
    assert med5._run_exit_reason is RunExitReason.UNRECOVERABLE_CRASH


def test_victory_continue_budget_does_not_reset_or_stop() -> None:
    med = _hitch()
    med.set_phase(Phase.MAIN_LINE)
    med._victory_continue_attempts = 3
    frame = _game_frame()
    with patch.object(med, "_hitch_ocr_text", return_value=""), \
            patch.object(med, "_post_game_state", return_value="POST_VICTORY"), \
            patch.object(med, "find", return_value=_hit("continueGame")), \
            patch.object(med, "act_click") as click, \
            patch.object(med, "stop") as stop:
        action = med._tick_main_line(frame)
    assert action is LoopAction.Continue
    assert med._victory_continue_attempts == 3
    assert med._running is not False or med._run_exit_reason is None
    click.assert_not_called()
    stop.assert_not_called()
    assert med.phase is Phase.MAIN_LINE


def test_secret_realm_timeout_does_not_stop_hitch() -> None:
    med = _hitch()
    med.set_phase(Phase.MAIN_LINE)
    med.settings.auto_secret_realm = True
    med._secret_realm_entering_since = 1.0
    frame = _game_frame()
    with patch.object(med, "_hitch_ocr_text", return_value=""), \
            patch.object(med, "_post_game_state", return_value=None), \
            patch.object(med, "stop") as stop:
        action = med._observe_secret_realm_entry(frame, 30.0, None)
    assert action is LoopAction.Continue
    assert med._secret_realm_entering_since is None
    stop.assert_not_called()
    assert med._run_exit_reason is None
