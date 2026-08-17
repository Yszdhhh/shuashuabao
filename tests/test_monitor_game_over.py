from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.monitor_game_over import GameActivityMonitor


def bgr(value: int, height: int = 30, width: int = 30) -> np.ndarray:
    return np.full((height, width, 3), value, dtype=np.uint8)


class GameActivityMonitorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.monitor = GameActivityMonitor()

    def test_static_frames_become_candidate_after_two_seconds(self) -> None:
        frame = np.full((30, 30), 80, dtype=np.uint8)

        first = self.monitor.update(frame, 0.0)
        started = self.monitor.update(frame, 0.5)
        early = self.monitor.update(frame, 2.49)
        candidate = self.monitor.update(frame, 2.5)

        self.assertTrue(first.valid)
        self.assertIsNone(first.is_still)
        self.assertTrue(started.is_still)
        self.assertEqual(0.0, started.still_for)
        self.assertFalse(early.stillness_candidate)
        self.assertTrue(candidate.stillness_candidate)
        self.assertEqual(2.0, candidate.still_for)

    def test_motion_resets_stillness_timer(self) -> None:
        still = bgr(20, 40, 40)
        moved = bgr(220, 40, 40)
        self.monitor.update(still, 0.0)
        self.monitor.update(still, 0.5)
        self.assertTrue(self.monitor.update(still, 2.5).stillness_candidate)

        motion = self.monitor.update(moved, 3.0)
        restarted = self.monitor.update(moved, 3.5)
        early = self.monitor.update(moved, 5.49)
        candidate = self.monitor.update(moved, 5.5)

        self.assertFalse(motion.is_still)
        self.assertEqual(1600, motion.changed_pixels)
        self.assertFalse(motion.stillness_candidate)
        self.assertEqual(0.0, restarted.still_for)
        self.assertFalse(early.stillness_candidate)
        self.assertTrue(candidate.stillness_candidate)

    def test_intensity_and_changed_pixel_boundaries(self) -> None:
        self.monitor.update(bgr(0, 20, 25), 0.0)
        difference_15 = self.monitor.update(bgr(15, 20, 25), 0.5)
        self.assertEqual(0, difference_15.changed_pixels)
        self.assertTrue(difference_15.is_still)

        self.monitor.reset()
        self.monitor.update(bgr(0, 20, 25), 0.0)
        exactly_500 = self.monitor.update(bgr(16, 20, 25), 0.5)
        self.assertEqual(500, exactly_500.changed_pixels)
        self.assertTrue(exactly_500.is_still)

        self.monitor.reset()
        self.monitor.update(bgr(0, 3, 167), 0.0)
        over_limit = self.monitor.update(bgr(16, 3, 167), 0.5)
        self.assertEqual(501, over_limit.changed_pixels)
        self.assertFalse(over_limit.is_still)

    def test_time_rollback_resets_without_reusing_candidate(self) -> None:
        frame = bgr(90)
        self.monitor.update(frame, 10.0)
        self.monitor.update(frame, 10.5)
        self.assertTrue(self.monitor.update(frame, 12.5).stillness_candidate)

        rolled_back = self.monitor.update(frame, 11.0)
        restarted = self.monitor.update(frame, 11.5)

        self.assertTrue(rolled_back.valid)
        self.assertIsNone(rolled_back.changed_pixels)
        self.assertIsNone(rolled_back.is_still)
        self.assertFalse(rolled_back.stillness_candidate)
        self.assertTrue(restarted.is_still)
        self.assertEqual(0.0, restarted.still_for)

    def test_invalid_inputs_fail_safe_and_clear_history(self) -> None:
        frame = bgr(70)
        self.monitor.update(frame, 0.0)
        self.monitor.update(frame, 0.5)
        self.assertTrue(self.monitor.update(frame, 2.5).stillness_candidate)

        invalid_inputs = (
            (None, 3.0),
            (np.empty((0, 0, 3), dtype=np.uint8), 3.0),
            (np.zeros((4,), dtype=np.uint8), 3.0),
            (np.zeros((4, 4, 2), dtype=np.uint8), 3.0),
            (np.zeros((4, 4, 3), dtype=np.float32), 3.0),
            (frame, float("nan")),
        )
        for roi, timestamp in invalid_inputs:
            with self.subTest(shape=getattr(roi, "shape", None), timestamp=timestamp):
                result = self.monitor.update(roi, timestamp)
                self.assertFalse(result.valid)
                self.assertFalse(result.stillness_candidate)

        baseline = self.monitor.update(frame, 4.0)
        self.assertTrue(baseline.valid)
        self.assertIsNone(baseline.changed_pixels)
        self.assertFalse(baseline.stillness_candidate)


if __name__ == "__main__":
    unittest.main()
