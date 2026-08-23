"""Auto-task UNKNOWN fuse: drive the shipped gate, patch state + monotonic only."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from shuabao.loop_action import LoopAction
from shuabao.mediator import Mediator, Phase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame

ROOT = Path(__file__).resolve().parents[2]


class _Clock:
    def __init__(self, start: float = 1000.0) -> None:
        self.t = start

    def monotonic(self) -> float:
        return self.t


def _frame() -> Frame:
    return Frame(np.zeros((720, 1280, 3), dtype=np.uint8), hwnd=10001)


def _mediator(**kwargs) -> Mediator:
    settings = Settings(dry_run=False, auto_create_room=True, **kwargs)
    return Mediator(settings, ROOT)


def _patch_state(med: Mediator, state: str):
    scores = {
        "ON": (0.95, 0.10),
        "OFF": (0.10, 0.95),
        "UNKNOWN": (0.40, 0.41),
    }
    on_score, off_score = scores.get(state, (0.0, 0.0))
    return (
        patch.object(med, "_auto_task_state", return_value=(state, None)),
        patch.object(
            med,
            "_auto_task_state_detail",
            return_value=(state, None, on_score, off_score),
        ),
        patch.object(med, "_find_auto_task_toggle", return_value=None),
    )


def test_first_unknown_records_monotonic_timestamp():
    med = _mediator()
    clock = _Clock(1234.5)
    assert med._auto_task_unknown_since is None
    state_p, detail_p, toggle_p = _patch_state(med, "UNKNOWN")
    with state_p, detail_p, toggle_p, patch("shuabao.mediator.time.monotonic", clock.monotonic):
        result = med._ensure_auto_task_enabled(_frame())
    assert result is None
    assert med._auto_task_unknown_since == pytest.approx(1234.5)
    assert med.phase != Phase.ERROR


def test_on_and_off_immediately_clear_unknown_timer():
    med = _mediator()
    clock = _Clock(10.0)
    state_p, detail_p, toggle_p = _patch_state(med, "UNKNOWN")
    with state_p, detail_p, toggle_p, patch("shuabao.mediator.time.monotonic", clock.monotonic):
        med._ensure_auto_task_enabled(_frame())
    assert med._auto_task_unknown_since == pytest.approx(10.0)

    on_state, on_detail, on_toggle = _patch_state(med, "ON")
    with on_state, on_detail, on_toggle, patch("shuabao.mediator.time.monotonic", clock.monotonic):
        med._ensure_auto_task_enabled(_frame())
    assert med._auto_task_unknown_since is None

    unk_state, unk_detail, unk_toggle = _patch_state(med, "UNKNOWN")
    with unk_state, unk_detail, unk_toggle, patch("shuabao.mediator.time.monotonic", clock.monotonic):
        med._ensure_auto_task_enabled(_frame())
    assert med._auto_task_unknown_since == pytest.approx(10.0)

    off_state, off_detail, off_toggle = _patch_state(med, "OFF")
    with off_state, off_detail, off_toggle, patch("shuabao.mediator.time.monotonic", clock.monotonic):
        med._ensure_auto_task_enabled(_frame())
    assert med._auto_task_unknown_since is None


def test_unknown_beyond_default_45s_restarts_observation_without_stopping():
    med = _mediator()
    clock = _Clock(100.0)
    state_p, detail_p, toggle_p = _patch_state(med, "UNKNOWN")
    with state_p, detail_p, toggle_p, patch("shuabao.mediator.time.monotonic", clock.monotonic):
        first = med._ensure_auto_task_enabled(_frame())
        assert first is None
        clock.t += 44.9
        still_waiting = med._ensure_auto_task_enabled(_frame())
        assert still_waiting is None
        assert med.phase != Phase.ERROR
        clock.t += 0.2
        reobserved = med._ensure_auto_task_enabled(_frame())
    assert reobserved is None
    assert med.phase is not Phase.ERROR
    assert not med.stop_signal.is_set()
    assert med._auto_task_unknown_since == pytest.approx(clock.t)


def test_timeout_clamp_30_and_60_controls_reobservation_cadence(monkeypatch):
    med = _mediator()
    clock = _Clock(0.0)
    state_p, detail_p, toggle_p = _patch_state(med, "UNKNOWN")
    with state_p, detail_p, toggle_p, patch("shuabao.mediator.time.monotonic", clock.monotonic):
        med.settings.auto_task_unknown_timeout_s = 10.0
        assert med._auto_task_unknown_timeout_s() == pytest.approx(30.0)
        med._ensure_auto_task_enabled(_frame())
        clock.t = 29.9
        assert med._ensure_auto_task_enabled(_frame()) is None
        clock.t = 30.0
        assert med._ensure_auto_task_enabled(_frame()) is None
        assert med.phase is not Phase.ERROR

    med2 = _mediator()
    clock2 = _Clock(0.0)
    med2.settings.auto_task_unknown_timeout_s = 90.0
    assert med2._auto_task_unknown_timeout_s() == pytest.approx(60.0)
    state_p2, detail_p2, toggle_p2 = _patch_state(med2, "UNKNOWN")
    with state_p2, detail_p2, toggle_p2, patch("shuabao.mediator.time.monotonic", clock2.monotonic):
        med2._ensure_auto_task_enabled(_frame())
        clock2.t = 59.9
        assert med2._ensure_auto_task_enabled(_frame()) is None
        clock2.t = 60.0
        result = med2._ensure_auto_task_enabled(_frame())
    assert result is None
    assert med2.phase is not Phase.ERROR


def test_refreshing_main_line_since_does_not_postpone_reobservation():
    med = _mediator()
    clock = _Clock(500.0)
    med.set_phase(Phase.MAIN_LINE, "test")
    state_p, detail_p, toggle_p = _patch_state(med, "UNKNOWN")
    with state_p, detail_p, toggle_p, patch("shuabao.mediator.time.monotonic", clock.monotonic):
        med._ensure_auto_task_enabled(_frame())
        assert med._auto_task_unknown_since == pytest.approx(500.0)
        med._main_line_since = 10**12
        clock.t = 500.0 + 45.0
        result = med._ensure_auto_task_enabled(_frame())
    assert result is None
    assert med.phase is not Phase.ERROR
    assert not med.stop_signal.is_set()
    assert med._auto_task_unknown_since == pytest.approx(clock.t)
