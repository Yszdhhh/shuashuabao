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


def test_next_phase_unattended_rearms_on_timeout() -> None:
    """Phase.NEXT: in unattended mode (default), timeout rearms attempts and stays in NEXT."""
    med = RuntimeMediator(Settings(), Path("."))
    med.phase = Phase.NEXT
    med._exit_since = time.time() - 20.0  # Timed out
    med._exit_confirm_attempts = 3
    frame = _make_frame()

    with patch.object(med, "_find_room_start", return_value=None), \
         patch.object(med, "_find_exit_confirm", return_value=None):
        res = med._tick_l1_tail(frame)
        assert res == LoopAction.Continue
        assert med.phase == Phase.NEXT
        assert med._exit_confirm_attempts == 0


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


def test_room_form_filling_uses_executor() -> None:
    """_fill_room_dialog fills name and pwd using executor without livelock."""
    settings = Settings()
    settings.room_name = "Room123"
    settings.room_password = "Pwd456"

    med = RuntimeMediator(settings, Path("."))
    med.phase = Phase.CREATE_ROOM
    frame = _make_frame()
    confirm_hit = _make_match("create_room_confirm", 800, 600)
    boxes = [_make_match("box_name", 600, 400), _make_match("box_pwd", 600, 450)]

    clicked_reasons: list[str] = []
    pastes: list[str] = []

    def mock_click(hit: MatchResult, reason: str = "") -> bool:
        clicked_reasons.append(reason)
        return True

    med.act_click = mock_click
    med.executor.hotkey = MagicMock(return_value=MagicMock(success=True))
    med.executor.paste_text = lambda text, **kw: pastes.append(text) or MagicMock(success=True)

    with patch("shuabao.mediator.find_input_boxes", return_value=boxes):
        res = med._fill_room_dialog(frame, confirm_hit)
        assert res is True
        assert "CreateRoom-focus-name" in clicked_reasons
        assert "CreateRoom-focus-pwd" in clicked_reasons
        assert pastes == ["Room123", "Pwd456"]


def test_positive_hud_evidence_blocks_input_on_unknown_frame() -> None:
    """In MAIN_LINE, a frame without positive HUD evidence produces zero inputs."""
    med = RuntimeMediator(Settings(), Path("."))
    med.phase = Phase.MAIN_LINE
    frame = _make_frame()

    clicks: list[str] = []
    keys: list[str] = []
    med.act_click = lambda hit, reason="": clicks.append(reason) or True
    med.act_key = lambda key, reason="": keys.append(reason) or True

    with patch.object(med, "_is_in_game_hud", return_value=False), \
         patch.object(med, "_find_stage_page", return_value=None), \
         patch.object(med, "_find_equipment_affix_choice", return_value=None), \
         patch.object(med, "_selection_anchor", return_value=None):
        res = med._tick_main_line(frame)
        assert res == LoopAction.Continue
        assert len(clicks) == 0
        assert len(keys) == 0


def test_round1_to_round2_main_line_transition() -> None:
    """Full state machine integration: Round 1 -> Victory -> QUIT -> NEXT -> PREPARE (RoomStart) -> Round 2 MAIN_LINE."""
    med = RuntimeMediator(Settings(), Path("."))
    frame = _make_frame()

    # 1. Round 1 in MAIN_LINE
    med.phase = Phase.MAIN_LINE
    assert med.phase == Phase.MAIN_LINE

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

    # 7. In ROOM_STARTING: game launches -> transitions into Round 2 MAIN_LINE
    with patch.object(med, "_detect_context", return_value="MAIN_LINE"), \
         patch.object(med, "_is_in_game_hud", return_value=True):
        med._tick_l0(frame)
        assert med.phase == Phase.MAIN_LINE
        # Successfully reached Round 2 MAIN_LINE!
