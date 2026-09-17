"""P1 multi-round recovery, staged room form, and positive HUD tests."""

from pathlib import Path
import time
from unittest.mock import MagicMock, patch
import numpy as np
import pytest

from shuabao.mediator import LoopAction, PanelState, Phase
from shuabao.runtime_mediator import Mediator as RuntimeMediator
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult


def _make_frame() -> Frame:
    return Frame(bgr=np.zeros((900, 1600, 3), dtype=np.uint8))


def _make_match(name: str = "btn", x: int = 100, y: int = 100) -> MatchResult:
    return MatchResult(name, 0.95, x, y, 20, 20, x, y)


def test_quit_phase_detects_already_in_room() -> None:
    """Phase.QUIT: if room_start is detected, exit is already complete -> Phase.PREPARE."""
    med = RuntimeMediator(Settings(), Path("."))
    med.phase = Phase.QUIT
    frame = _make_frame()

    with patch.object(med, "_find_room_start", return_value=_make_match("room_start", 400, 700)):
        res = med._tick_l1_tail(frame)
        assert res == LoopAction.Continue
        assert med.phase == Phase.PREPARE


def test_next_phase_detects_already_in_room() -> None:
    """Phase.NEXT: if room_start is detected, exit is complete -> Phase.PREPARE."""
    med = RuntimeMediator(Settings(), Path("."))
    med.phase = Phase.NEXT
    frame = _make_frame()

    with patch.object(med, "_find_room_start", return_value=_make_match("room_start", 400, 700)):
        res = med._tick_l1_tail(frame)
        assert res == LoopAction.Continue
        assert med.phase == Phase.PREPARE


def test_next_phase_unknown_timeout_fails_closed_even_in_unattended_mode() -> None:
    """Phase.NEXT: an unclassified surface cannot be re-armed forever."""
    med = RuntimeMediator(Settings(), Path("."))
    med.phase = Phase.NEXT
    med._exit_since = time.time() - 20.0  # Timed out
    med._exit_confirm_attempts = 3
    frame = _make_frame()

    with patch.object(med, "_find_room_start", return_value=None), \
         patch.object(med, "_find_exit_confirm", return_value=None):
        res = med._tick_l1_tail(frame)
        assert res == LoopAction.Break
        assert med.phase == Phase.ERROR


def test_next_phase_confirm_disappeared_on_hud_rearms_quit_with_a_bound() -> None:
    """A positively identified HUD may retry QUIT, but only within a finite budget."""
    med = RuntimeMediator(Settings(), Path("."))
    med.phase = Phase.NEXT
    med._exit_since = time.time() - 20.0
    med._exit_confirm_attempts = 3
    frame = _make_frame()

    with patch.object(med, "_find_room_start", return_value=None), \
         patch.object(med, "_find_exit_confirm", return_value=None), \
         patch.object(med, "_is_in_game_hud", return_value=True):
        res = med._tick_l1_tail(frame)
        assert res == LoopAction.Continue
        assert med.phase == Phase.QUIT
        assert med._exit_rearm_attempts == 1

        med._exit_since = time.time() - 20.0
        med._exit_button_attempts = 3
        med._exit_confirm_attempts = 3
        med._exit_rearm_attempts = med._EXIT_REARM_LIMIT
        res = med._tick_l1_tail(frame)
        assert res == LoopAction.Break
        assert med.phase == Phase.ERROR


def test_next_phase_transition_wait_is_bounded_and_does_not_rearm_timer() -> None:
    """A known game-client transition gets observation time, not a new budget."""
    med = RuntimeMediator(Settings(), Path("."))
    med.phase = Phase.NEXT
    original_since = time.time() - 20.0
    med._exit_since = original_since
    med._exit_confirm_attempts = 3
    frame = _make_frame()

    with patch.object(med, "_find_room_start", return_value=None), \
         patch.object(med, "_find_exit_confirm", return_value=None), \
         patch.object(med, "_is_in_game_hud", return_value=False), \
         patch.object(med, "_is_game_client_frame", return_value=True):
        res = med._tick_l1_tail(frame)

    assert res == LoopAction.Continue
    assert med.phase == Phase.NEXT
    assert med._exit_rearm_attempts == 0
    assert med._exit_since == original_since


def test_next_phase_fails_closed_on_unknown_timeout() -> None:
    """Phase.NEXT: in non-unattended (lab) mode, timeout fails-closed to ERROR."""
    med = RuntimeMediator(Settings(mode_id="lab"), Path("."))
    med.phase = Phase.NEXT
    med._exit_since = time.time() - 40.0  # Expired past timeout
    med._exit_confirm_attempts = 3
    frame = _make_frame()

    with patch.object(med, "_find_room_start", return_value=None), \
         patch.object(med, "_find_exit_confirm", return_value=None):
        res = med._tick_l1_tail(frame)
        assert res == LoopAction.Break
        assert med.phase == Phase.ERROR


def test_room_form_filling_is_a_staged_single_action_transaction() -> None:
    """Each room-form field operation owns one tick; confirm is a later tick."""
    settings = Settings()
    settings.room_name = "Room123"
    settings.room_password = "Pwd456"

    med = RuntimeMediator(settings, Path("."))
    med.phase = Phase.CREATE_ROOM
    frame = _make_frame()
    confirm_hit = _make_match("create_room_confirm", 800, 600)
    boxes = [_make_match("box_name", 600, 400), _make_match("box_pwd", 600, 450)]

    operations: list[str] = []
    pastes: list[str] = []

    med.executor.click = lambda *args, **kw: operations.append("click") or MagicMock(success=True)
    med.executor.hotkey = lambda *args, **kw: operations.append("hotkey") or MagicMock(success=True)
    med.executor.paste_text = lambda text, **kw: operations.append("paste") or pastes.append(text) or MagicMock(success=True)

    with patch("shuabao.mediator.find_input_boxes", return_value=boxes):
        results = [med._fill_room_dialog(frame, confirm_hit) for _ in range(6)]
        res = results[-1]
        assert res is True
        assert operations == ["click", "hotkey", "paste", "click", "hotkey", "paste"]
        assert pastes == ["Room123", "Pwd456"]


def test_positive_hud_evidence_blocks_input_on_unknown_frame() -> None:
    """In MAIN_LINE, a frame without positive HUD evidence produces zero inputs."""
    med = RuntimeMediator(Settings(), Path("."))
    med.phase = Phase.MAIN_LINE
    frame = _make_frame()

    ensure_auto = MagicMock(return_value=LoopAction.Continue)
    med._ensure_auto_task_enabled = ensure_auto

    with patch.object(med, "_is_in_game_hud", return_value=False), \
         patch.object(med, "_find_stage_page", return_value=None), \
         patch.object(med, "_find_equipment_affix_choice", return_value=None), \
         patch.object(med, "_selection_anchor", return_value=None):
        res = med._tick_main_line(frame)
        assert res == LoopAction.Continue
        ensure_auto.assert_not_called()
        assert med._tick_input_executed is False


def test_round1_to_round2_main_line_transition() -> None:
    """Full state machine integration: Round 1 -> Victory -> QUIT -> NEXT -> PREPARE (RoomStart) -> ROOM_STARTING -> STAGE_SELECT -> STAGE_STARTING -> verified Round 2 MAIN_LINE."""
    med = RuntimeMediator(Settings(), Path("."))
    frame = _make_frame()

    # 1. Round 1 in MAIN_LINE with dirty per-round state
    med.phase = Phase.MAIN_LINE
    assert med.phase == Phase.MAIN_LINE
    r1_start = time.time() - 300.0
    med._auto_task_done = True
    med._auto_task_attempts = 2
    med._main_line_closed_done = True
    med._close_main_line_triggered = True
    med._challenge_done = {"coin_challenge", "wood_challenge"}
    med._post_game_route = "archive"
    med._secret_realm_active = True
    med._time_cave_boss_done = True
    med._merchant_next_at = time.time() + 200.0
    med._skill_cards_owned = ["skill_a", "skill_b"]
    med._bond_cards_owned = ["bond_x"]
    med._main_line_started_at = r1_start
    med._round_started_at = r1_start
    med._round_deadline = r1_start + 180.0

    # 2. Victory transition to QUIT
    med.set_phase(Phase.QUIT, "test victory quit")
    assert med.phase == Phase.QUIT

    # 3. In QUIT: exit button clicked -> NEXT
    exit_hit = _make_match("game_exit", 50, 50)
    with patch.object(med, "_find_room_start", return_value=None), \
         patch.object(med, "_find_exit_confirm", return_value=None), \
         patch.object(med, "_find_game_exit", return_value=exit_hit), \
         patch.object(med, "act_click", return_value=True):
        med._tick_l1_tail(frame)
        assert med.phase == Phase.NEXT

    # 4. In NEXT: exit confirmation clicked -> PREPARE
    confirm_hit = _make_match("exit_confirm", 600, 500)
    with patch.object(med, "_find_room_start", return_value=None), \
         patch.object(med, "_find_exit_confirm", return_value=confirm_hit), \
         patch.object(med, "act_click", return_value=True):
        med._tick_l1_tail(frame)
        assert med.phase == Phase.PREPARE

    # 5. In PREPARE: room_start visible -> verifies same room -> ROOM_WAITING
    room_start_hit = _make_match("room_start", 400, 700)
    with patch.object(med, "_find_room_start", return_value=room_start_hit):
        med._tick_l0(frame)
        assert med.phase == Phase.ROOM_WAITING

    # 6. In ROOM_WAITING: room_start clicked -> ROOM_STARTING
    with patch.object(med, "_find_room_start", return_value=room_start_hit), \
         patch.object(med, "act_click", return_value=True):
        med._tick_l0(frame)
        assert med.phase == Phase.ROOM_STARTING

    # 7. In ROOM_STARTING: stage page appears -> STAGE_SELECT
    stage_page_hit = _make_match("stage_page", 200, 200)
    with patch.object(med, "_detect_context", return_value="STAGE_SELECT"), \
         patch.object(med, "_find_stage_page", return_value=stage_page_hit):
        med._tick_l0(_make_frame())
        assert med.phase == Phase.STAGE_SELECT

    # 8. In STAGE_SELECT: stage selected, click stage start -> STAGE_STARTING
    med._stage_selected = True
    med._stage_click_cooldown_until = 0.0
    stage_start_hit = _make_match("stage_start", 800, 700)
    with patch.object(med, "_detect_context", return_value="STAGE_SELECT"), \
         patch.object(med, "_find_stage_page", return_value=stage_page_hit), \
         patch.object(med, "_find_stage_start", return_value=stage_start_hit), \
         patch.object(med, "act_click", return_value=True):
        med._tick_l0(_make_frame())
        assert med.phase == Phase.STAGE_STARTING

    # 9. In STAGE_STARTING: 2 consecutive frames of positive in-game evidence -> verified MAIN_LINE
    with patch.object(med, "_is_in_game_hud", return_value=True):
        # Frame 1: WAIT_TRANSITION -> VERIFY_INGAME (hud_frames=1)
        med._tick_l0(_make_frame())
        assert med.phase == Phase.STAGE_STARTING
        assert med._challenge_start_hud_frames == 1

        # Frame 2: VERIFY_INGAME -> DONE -> MAIN_LINE ("challenge start verified")
        med._tick_l0(_make_frame())
        assert med.phase == Phase.MAIN_LINE

    # 10. Confirm Round 2 receives fresh per-round state
    assert med.phase == Phase.MAIN_LINE
    assert med._auto_task_done is False
    assert med._auto_task_attempts == 0
    assert med._main_line_closed_done is False
    assert med._close_main_line_triggered is False
    assert len(med._challenge_done) == 0
    assert med._post_game_route == "secret"
    assert med._secret_realm_active is False
    assert med._time_cave_boss_done is False
    assert med._merchant_next_at == 0.0
    assert len(med._skill_cards_owned) == 0
    assert len(med._bond_cards_owned) == 0
    assert med._main_line_started_at is not None and med._main_line_started_at > r1_start
    assert med._round_started_at is not None and med._round_started_at > r1_start
    assert med._round_deadline is not None and med._round_deadline > r1_start
    assert med._round_deadline == med._round_started_at + med.settings.round_timeout_s
