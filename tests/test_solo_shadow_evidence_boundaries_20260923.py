"""W2 shadow must not re-perceive and must not forge action agreement."""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from shuabao.mediator import Mediator
from shuabao.settings import Settings

ROOT = Path(__file__).resolve().parents[1]


def _med() -> Mediator:
    return Mediator(Settings(dry_run=True, ocr_mode="off"), ROOT)


class SoloShadowEvidenceTests(unittest.TestCase):
    def test_shadow_tick_does_not_call_refresh_solo_signals(self) -> None:
        med = _med()
        med.phase = SimpleNamespace(name="MAIN_LINE")
        med._passenger_mode = lambda: False  # type: ignore[method-assign]
        calls: list[tuple] = []

        def _refresh(frame, now):
            calls.append((frame, now))

        med._refresh_solo_signals = _refresh  # type: ignore[method-assign]
        log = MagicMock()
        med._solo_shadow_log = lambda: log  # type: ignore[method-assign]
        frame = object()

        with patch("shuabao.solo_shadow.build_snapshot", return_value=MagicMock()), patch(
            "shuabao.solo_shadow.decide", return_value=MagicMock()
        ):
            med._solo_shadow_tick(frame)

        self.assertEqual(calls, [], "shadow must consume shared signals, not refresh")

    def test_actual_act_is_never_plan_target(self) -> None:
        med = _med()
        med.phase = SimpleNamespace(name="MAIN_LINE")
        med._passenger_mode = lambda: False  # type: ignore[method-assign]
        log = MagicMock()
        med._solo_shadow_log = lambda: log  # type: ignore[method-assign]
        snap = MagicMock()
        decision = MagicMock()
        med._solo_shadow_pending = {
            "snapshot": snap,
            "decision": decision,
            "plan_before": (None, ""),
            "cycle_step": "bond",
        }
        med._observe_plan = ("F", "按轮换")

        with patch("shuabao.solo_shadow.build_snapshot", return_value=MagicMock()), patch(
            "shuabao.solo_shadow.decide", return_value=MagicMock()
        ):
            med._solo_shadow_tick(None)

        self.assertTrue(log.note_boundary.called)
        kwargs = log.note_boundary.call_args.kwargs
        self.assertEqual(kwargs["actual_act"], "")
        self.assertEqual(kwargs["actual_plan_target"], "F")
        self.assertEqual(kwargs["boundary"], "plan_observed_unpaired")

    def test_phase_exit_pending_is_unpaired_without_act(self) -> None:
        med = _med()
        med.phase = SimpleNamespace(name="POST_GAME")
        med._passenger_mode = lambda: False  # type: ignore[method-assign]
        log = MagicMock()
        med._solo_shadow_log = lambda: log  # type: ignore[method-assign]
        med._solo_shadow_pending = {
            "snapshot": MagicMock(),
            "decision": MagicMock(),
            "plan_before": (None, ""),
            "cycle_step": "skill",
        }

        med._solo_shadow_tick(None)

        kwargs = log.note_boundary.call_args.kwargs
        self.assertEqual(kwargs["actual_act"], "")
        self.assertEqual(kwargs["boundary"], "phase_exit_unpaired")


if __name__ == "__main__":
    unittest.main()
