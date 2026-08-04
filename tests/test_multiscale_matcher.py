from pathlib import Path
import unittest

import cv2
import numpy as np

from gamescript.vision.capture import Frame
from gamescript.vision.matcher import match_any, _load_template


ROOT = Path(__file__).resolve().parents[1]
SCALES = (0.9, 1.0, 1.1, 1.15, 1.2)


class MultiScaleMatcherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.images = ROOT / "assets" / "Images"

    def _scaled_fixture(self, name: str, scale: float = 1.15) -> Frame:
        path = self.images / f"{name}.png"
        template = _load_template(path)
        self.assertIsNotNone(template)
        scaled = cv2.resize(template, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        frame = np.zeros((max(320, scaled.shape[0] + 80), max(480, scaled.shape[1] + 120), 3), dtype=np.uint8)
        y, x = 40, 60
        frame[y:y + scaled.shape[0], x:x + scaled.shape[1]] = scaled
        return Frame(frame)

    def test_start_button_survives_window_scaling(self):
        hit = match_any(self._scaled_fixture("startGameBtn"), self.images, ["startGameBtn"], scales=SCALES)
        self.assertIsNotNone(hit)
        self.assertGreaterEqual(hit.score, 0.95)

    def test_stage_marker_survives_window_scaling(self):
        hit = match_any(self._scaled_fixture("stage"), self.images, ["stage"], scales=SCALES)
        self.assertIsNotNone(hit)
        self.assertGreaterEqual(hit.score, 0.95)


if __name__ == "__main__":
    unittest.main()
