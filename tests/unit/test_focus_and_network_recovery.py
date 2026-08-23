import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from shuabao.input.keyboard_mouse import ActionResult, InputExecutor, foreground_matches_target, get_foreground_window
from shuabao.mediator import LoopAction, Mediator, PanelState, Phase, RecoveryKind, RecoveryState, RecoveryStep, RoundOutcome
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult

ROOT = Path(__file__).resolve().parents[2]


def make_dummy_frame(hwnd: int = 12345) -> Frame:
    bgr = np.zeros((720, 1280, 3), dtype=np.uint8)
    return Frame(
        bgr=bgr,
        left=0,
        top=0,
        hwnd=hwnd,
    )


def make_dummy_hit(name: str = "btn", x: int = 100, y: int = 100) -> MatchResult:
    return MatchResult(
        name=name,
        score=0.95,
        x=x,
        y=y,
        w=50,
        h=30,
        screen_x=x + 25,
        screen_y=y + 15,
    )


def test_foreground_loss_pauses_inputs_without_reactivation():
    """Foreground loss invalidates evidence and leaves the window z-order untouched."""
    settings = Settings(dry_run=False)
    med = Mediator(settings, ROOT)
    med.executor = InputExecutor()
    target_hwnd = 12345
    frame = Frame(
        np.random.default_rng(7).integers(0, 255, (720, 1280, 3), dtype=np.uint8),
        left=0,
        top=0,
        hwnd=target_hwnd,
    )

    # Establish baseline evidence
    ev = med._ensure_evidence(frame)
    med._evidence = ev
    med._tick_evidence = ev
    med._tick_gen = ev.gen
    med._tick_input_seq = med._input_seq
    med._last_frame = frame
    prev_gen = ev.gen

    # 1. Target has foreground: action gate allows action
    with patch("shuabao.mediator.is_window_valid", return_value=True), \
         patch("shuabao.mediator.get_foreground_window", return_value=target_hwnd):
        assert med._action_gate_ok("test ok") is True

    with patch.object(med, "see", return_value=frame), \
         patch("shuabao.mediator.is_window_valid", return_value=True), \
         patch("shuabao.mediator.get_foreground_window", return_value=99999), \
         patch("shuabao.vision.capture.activate_window") as activate:
        assert med.tick() is LoopAction.Continue
        assert med._evidence.gen > prev_gen
        activate.assert_not_called()

def test_stale_coordinate_rejection_on_focus_loss():
    """Act methods must reject execution when window focus is lost or evidence is invalidated."""
    settings = Settings(dry_run=False)
    med = Mediator(settings, ROOT)
    med.executor = InputExecutor()
    target_hwnd = 12345
    frame = make_dummy_frame(hwnd=target_hwnd)

    ev = med._ensure_evidence(frame)
    med._evidence = ev
    med._tick_evidence = ev
    med._tick_gen = ev.gen
    med._tick_input_seq = med._input_seq
    med._last_frame = frame

    hit = make_dummy_hit("some_button")

    # Foreground loss during act_click is rejected by InputExecutor without reactivation.
    with patch("shuabao.input.keyboard_mouse.is_current_process_elevated", return_value=True), \
         patch("shuabao.input.keyboard_mouse.is_window_valid", return_value=True), \
         patch("shuabao.input.keyboard_mouse.get_foreground_window", return_value=99999), \
         patch("shuabao.vision.capture.activate_window") as activate:
        res = med.act_click(hit, "test-stale-focus")
        assert res is False
        activate.assert_not_called()

    # 2. Already-foreground target can execute normally.
    with patch("shuabao.input.keyboard_mouse.get_foreground_window", return_value=target_hwnd), \
         patch.object(med.executor, "click", return_value=ActionResult(success=True, status="SUCCESS")):
        res2 = med.act_click(hit, "test-reacquired-focus")
        assert res2 is True


def test_tick_foreground_check_and_pause():
    """Tick loop checks target foreground and skips business logic when background."""
    settings = Settings(dry_run=False)
    med = Mediator(settings, ROOT)
    med.executor = InputExecutor()
    target_hwnd = 12345
    frame = make_dummy_frame(hwnd=target_hwnd)

    # Mock see to return frame, and get_foreground_window to return foreign hwnd
    with patch.object(med, "see", return_value=frame), \
         patch("shuabao.mediator.is_window_valid", return_value=True), \
         patch("shuabao.mediator.get_foreground_window", return_value=99999):
        action = med.tick()
        assert action == LoopAction.Continue


def test_room_starting_never_retries_platform_start_button():
    med = Mediator(Settings(dry_run=True), ROOT)
    med.set_phase(Phase.ROOM_STARTING)
    med._room_start_deadline = time.time() + 30
    hit = make_dummy_hit("room_start")
    with patch.object(med, "_detect_context", return_value="ROOM_WAITING"), \
         patch.object(med, "_find_stage_page", return_value=False), \
         patch.object(med, "_find_room_start", return_value=hit), \
         patch.object(med, "act_click") as click:
        assert med._tick_l0(make_dummy_frame()) is LoopAction.Continue
    click.assert_not_called()


def test_disconnect_modal_detection_and_recovery_fsm():
    """Disconnect modal triggers bounded recovery FSM."""
    settings = Settings(recovery_timeout_s=60, recovery_action_limit=3)
    med = Mediator(settings, ROOT)
    target_hwnd = 12345
    frame = make_dummy_frame(hwnd=target_hwnd)

    # 1. Begin recovery for DISCONNECT
    med._begin_recovery(RecoveryKind.DISCONNECT)
    assert med.phase == Phase.RECOVER_FAILURE
    assert med._recovery_state is not None
    assert med._recovery_state.kind == RecoveryKind.DISCONNECT
    assert med._recovery_state.step == RecoveryStep.DISCONNECT_RETRY
    assert med._recovery_state.deadline <= time.time() + 120.0

    # 2. Frame has disconnect anchor & retryConnect button
    retry_hit = make_dummy_hit("retryConnect")
    with patch.object(med, "find_scene", return_value=retry_hit), \
         patch.object(med, "act_click", return_value=True):
        action = med._tick_recovery(frame)
        assert action == LoopAction.Continue
        assert med._recovery_state.step == RecoveryStep.DISCONNECT_RETRY
        assert med._recovery_state.waiting_confirm is True


def test_recovery_attempts_and_timeout_termination():
    """Exhausted attempts or timeout safely transitions to recovery failed."""
    settings = Settings(recovery_timeout_s=60, recovery_action_limit=3)
    med = Mediator(settings, ROOT)
    target_hwnd = 12345
    frame = make_dummy_frame(hwnd=target_hwnd)

    med._begin_recovery(RecoveryKind.DISCONNECT)
    rs = med._recovery_state
    now = time.time()

    # Exhausted attempts (> 3)
    rs.attempts[RecoveryStep.DISCONNECT_RETRY] = 3
    action = med._recovery_retry_or_fail(rs, RecoveryStep.DISCONNECT_RETRY, now, "attempts exhausted")
    assert action == LoopAction.Break
    assert med.phase == Phase.ERROR

    # Total duration timeout (> 120s or past deadline)
    med._begin_recovery(RecoveryKind.FAIL)
    rs2 = med._recovery_state
    rs2.deadline = now - 1.0  # Expired
    action2 = med._recovery_retry_or_fail(rs2, RecoveryStep.FAIL_CONFIRM, now, "timeout exceeded")
    assert action2 == LoopAction.Break
    assert med.phase == Phase.ERROR
