"""L0 state-alignment regressions for the 20260818 transition incident."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from shuabao.loop_action import LoopAction
from shuabao.mediator import Mediator, Phase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame

ROOT = Path(__file__).resolve().parents[1]


class TestL0TransitionAlignment(unittest.TestCase):
    @staticmethod
    def invalid_frame() -> Frame:
        return Frame(
            np.empty((0, 0, 3), dtype=np.uint8),
            is_valid=False,
            error="game window is still launching",
        )

    def test_room_starting_can_wait_beyond_legacy_15_seconds(self):
        med = Mediator(Settings(query_timeout=60, dry_run=False), ROOT)
        med.phase = Phase.ROOM_STARTING
        med._room_start_deadline = 160.0
        with patch.object(med, "see", return_value=self.invalid_frame()), patch(
            "shuabao.mediator.time.time", return_value=116.0
        ):
            action = med._tick_impl()
        self.assertEqual(action, LoopAction.Continue)
        self.assertIs(med.phase, Phase.ROOM_STARTING)

    def test_room_starting_macro_deadline_still_bounds_recovery(self):
        med = Mediator(Settings(query_timeout=60, dry_run=False), ROOT)
        med.phase = Phase.ROOM_STARTING
        med._room_start_deadline = 160.0
        with patch.object(med, "see", return_value=self.invalid_frame()), patch(
            "shuabao.mediator.time.time", return_value=160.1
        ):
            action = med._tick_impl()
        self.assertEqual(action, LoopAction.Continue)
        self.assertIs(med.phase, Phase.ROOM_WAITING)

    def test_room_starting_inspects_platform_when_game_hwnd_absent(self):
        med = Mediator(Settings(query_timeout=60), ROOT)
        med.phase = Phase.ROOM_STARTING
        missing = self.invalid_frame()
        platform = Frame(
            np.random.default_rng(7).integers(0, 255, (720, 1040, 3), dtype=np.uint8),
            window_title="KK官方对战平台",
            hwnd=42,
        )
        with patch.object(med, "_capture_best", side_effect=[missing, platform]), patch.object(
            med, "_frame_signal", return_value=1
        ) as signal:
            seen = med.see("tick")
        signal.assert_called_once_with(platform, "l0")
        self.assertIs(seen, platform)


if __name__ == "__main__":
    unittest.main()
