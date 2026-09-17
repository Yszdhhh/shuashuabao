"""P1 scheduler bounded service and F4 disabling tests."""

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


def test_low_wood_scheduler_reaches_all_subsystems() -> None:
    """When wood < 1000, scheduler progresses through all 10 cycle steps."""
    med = RuntimeMediator(Settings(), Path("."))
    med.phase = Phase.MAIN_LINE
    med.wood = 200
    med._wood_balance = 200

    order = med._l1_cycle_order()
    visited: list[str] = []

    med._l1_cycle_step = order[0]
    med._l1_cycle_index = 0
    visited.append(med._l1_cycle_step)

    for _ in range(len(order) * 2):
        med._advance_l1_cycle(med._l1_cycle_step)
        visited.append(med._l1_cycle_step)

    assert "bond" in visited
    assert "skill" in visited
    assert "treasure" in visited
    assert "evolve" in visited
    assert "equipment" in visited
    assert "pickup" in visited
    assert "merchant" in visited
    assert "artifact" in visited


def test_high_wood_scheduler_services_every_step_with_bounded_core_priority() -> None:
    """High wood keeps F/G priority but cannot starve the rest of the cycle."""
    med = RuntimeMediator(Settings(), Path("."))
    med.phase = Phase.MAIN_LINE
    med.wood = 5000
    med._wood_balance = 5000

    order = med._l1_cycle_order()
    visited: list[str] = []

    med._l1_cycle_step = order[0]
    med._l1_cycle_index = 0
    visited.append(med._l1_cycle_step)

    for _ in range(len(order) * 2):
        med._advance_l1_cycle(med._l1_cycle_step)
        visited.append(med._l1_cycle_step)

    assert set(order) <= set(visited)


def test_low_wood_treasure_scheduled_enters_treasure_service() -> None:
    """When scheduled for treasure and wood < 1000, enters treasure service."""
    med = RuntimeMediator(Settings(), Path("."))
    med.phase = Phase.MAIN_LINE
    med.wood = 200
    med._wood_balance = 200
    med._treasure_pending_seen = 11

    frame = _make_frame()
    now = time.time()

    with patch.object(med, "_refresh_solo_signals"), \
         patch.object(med, "_bond_base_progress_pending", return_value=False):
        planned, why = med._solo_plan_panel(frame, now, "treasure")
        assert planned == "treasure", f"Expected treasure service, got {planned} ({why})"


def test_high_wood_urgent_skill_backlog_preempts() -> None:
    """wood >= 1000 and skill backlog >= 8 triggers urgent preemption to clear skills."""
    med = RuntimeMediator(Settings(), Path("."))
    med.phase = Phase.MAIN_LINE
    med.wood = 5000
    med._wood_balance = 5000
    med._skill_points_seen = 12

    frame = _make_frame()
    now = time.time()

    with patch.object(med, "_refresh_solo_signals"), \
         patch.object(med, "_panel_kind_available", return_value=True):
        planned, why = med._solo_plan_panel(frame, now, "bond")
        assert planned == "skill"
        assert "≥ 8" in why


def test_normal_farm_zero_periodic_f4() -> None:
    """In normal_farm mode, automatic F4 is disabled over >60s of simulated execution."""
    med = RuntimeMediator(Settings(), Path("."))
    med.phase = Phase.MAIN_LINE
    med.settings.mode_id = "normal_farm"
    med.settings.auto_pressure = True
    med.settings.pressure_interval_s = 20.0

    frame = _make_frame()
    start_time = 1000.0

    with patch.object(med, "_is_in_game_hud", return_value=True), \
         patch.object(med, "act_key") as mock_key:
        for t in range(0, 120, 5):
            res = med._maybe_clear_pressure_monsters(frame, start_time + t)
            assert res is None
        mock_key.assert_not_called()


def test_f_draw_wait_for_second_frame_does_not_close_legal_candidate() -> None:
    """Runtime must preserve Core's deliberate zero-input confirmation wait."""
    med = RuntimeMediator(Settings(ocr_mode="live"), Path("."))
    med.phase = Phase.MAIN_LINE
    med._panel_state = PanelState.ACTIVE
    med._panel_kind = "bond"
    med._panel_opened_by_us = "bond"
    med._l1_cycle_owned_panel = True
    med._panel_episode_started = time.time()
    med._panel_hard_deadline_s = 60.0
    frame = _make_frame()
    anchor = _make_match("bond_panel", 500, 300)
    close = MagicMock()

    def wait_for_confirmation(_frame, _kind):
        med._choice_policy_idle = True
        med._choice_policy_last_reason = "羁绊决策待第二帧确认：已持有合成优先"
        return None

    with patch.object(med, "_panel_kind_of", return_value="bond"), \
         patch.object(med, "_ocr_reward_choice", side_effect=wait_for_confirmation), \
         patch.object(med, "_close_current_panel", close):
        result = med._tick_panel_fsm(frame, anchor, time.time())

    assert result == LoopAction.Continue
    assert med._choice_policy_idle is False
    close.assert_not_called()


def test_f_draw_same_fingerprint_reopen_has_bounded_backoff() -> None:
    """A stale F draw may reopen twice, then must stop rearming itself."""
    med = RuntimeMediator(Settings(), Path("."))
    med.phase = Phase.MAIN_LINE
    med._wood_balance = 5000
    med._l1_cycle_step = "bond"
    med._panel_physical_fingerprint = lambda _frame: "draw-a"
    frame = _make_frame()
    anchor = _make_match("bond_panel", 500, 300)

    for _ in range(med._F_DRAW_REOPEN_LIMIT + 1):
        med._l1_cycle_owned_panel = True
        med._l1_cycle_selected = False
        med._enter_panel_episode(frame, anchor, "bond", opened=True)
        med._finish_panel_episode()
        med._l1_cycle_step = "bond"

    assert med._f_draw_fingerprint == "draw-a"
    assert med._f_draw_reopen_count == med._F_DRAW_REOPEN_LIMIT
    assert med._f_draw_backoff_until > time.time()
    with patch.object(med, "_refresh_solo_signals"):
        assert med._bond_step_blocked(frame, time.time()) == "同一 F 抽卡无候选，进入有界退避"


def test_f_draw_illegal_candidate_refreshes_when_refresh_budget_exists() -> None:
    """A readable off-whitelist F candidate uses the verified refresh path."""
    settings = Settings(bonds=["经济"], ocr_mode="off")
    med = RuntimeMediator(settings, Path("."))
    frame = _make_frame()
    refresh = _make_match("bond_refresh_btn", 900, 700)
    med._ocr_panel_slots = lambda _frame, _kind: [{
        "index": 0,
        "name": "智力(1/4)",
        "confidence": 0.95,
        "rarity": "white",
        "raw_text": "智力(1/4)",
    }]
    med._find_panel_refresh = lambda _frame, _kind: refresh
    med._panel_has_giveup = lambda _frame, _kind: False
    med._bond_refresh_affordable = lambda _frame: (True, 500, 40)

    result = med._ocr_reward_choice(frame, "bond")

    assert result is not None
    assert result.name == "bond_refresh_btn"
    assert med._choice_policy_last_reason
    assert "刷新" in med._choice_policy_last_reason
