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


def test_high_wood_scheduler_reaches_all_subsystems() -> None:
    """Continuous wood >= 1000 must visit all 10 cycle steps without starving V, evolve, equipment, etc."""
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

    assert "bond" in visited
    assert "skill" in visited
    assert "treasure" in visited
    assert "evolve" in visited
    assert "equipment" in visited
    assert "pickup" in visited
    assert "merchant" in visited
    assert "artifact" in visited


def test_high_wood_treasure_backlog_enters_treasure_service() -> None:
    """wood >= 1000 and treasure badge = 11 must enter treasure service when scheduled, not hijacked by F."""
    med = RuntimeMediator(Settings(), Path("."))
    med.phase = Phase.MAIN_LINE
    med.wood = 5000
    med._wood_balance = 5000
    med._treasure_pending_seen = 11

    frame = _make_frame()
    now = time.time()

    with patch.object(med, "_refresh_solo_signals"), \
         patch.object(med, "_bond_step_blocked", return_value=None):
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
