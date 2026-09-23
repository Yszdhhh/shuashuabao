from __future__ import annotations

import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.mediator import Mediator
from shuabao.settings import Settings
from shuabao.vision.capture import Frame


class ChallengeTicketTests(unittest.TestCase):
    def _stage_frame(self) -> np.ndarray:
        path = ROOT / "fixtures" / "live_postgame_20260808" / "live_stage_select.png"
        return cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_COLOR)

    def test_nonzero_challenge_ticket_does_not_switch(self) -> None:
        frame = self._stage_frame()
        med = Mediator(Settings(auto_archaeology=True), ROOT)
        wrapped = Frame(frame, left=0, top=0, window_title="英雄三国KK", hwnd=1)
        self.assertFalse(med._ticket_exhausted(wrapped))

    def test_zero_challenge_ticket_detected_in_remainder_roi(self) -> None:
        frame = self._stage_frame().copy()
        # Model 0/120 by clearing the current-value digits and placing zero
        # left of the slash; the denominator stays untouched.
        zero_path = ROOT / "assets" / "Images" / "lobby" / "ticket_zero.png"
        zero = cv2.imdecode(np.frombuffer(zero_path.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
        self.assertIsNotNone(zero)
        h, w = zero.shape[:2]
        frame[864:884, 1055:1081] = 0
        frame[870 : 870 + h, 1082 : 1082 + w] = zero
        med = Mediator(Settings(auto_archaeology=True), ROOT)
        wrapped = Frame(frame, left=0, top=0, window_title="英雄三国KK", hwnd=1)
        self.assertTrue(med._ticket_exhausted(wrapped))


if __name__ == "__main__":
    unittest.main()
