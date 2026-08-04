from pathlib import Path
import unittest

import cv2
import numpy as np

from gamescript.vision.capture import Frame
from gamescript.vision.matcher import match_any


ROOT = Path(__file__).resolve().parents[1]
SCALES = (0.9, 1.0, 1.1, 1.15, 1.2)


class MultiScaleMatcherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sample = ROOT / "docs" / "agent_shared_logs" / "exports" / "CaptureWindow_20260803141607.png"
        image = cv2.imdecode(np.fromfile(str(sample), dtype=np.uint8), cv2.IMREAD_COLOR)
        cls.frame = Frame(image)
        cls.images = ROOT / "assets" / "Images"

    def test_start_button_survives_window_scaling(self):
        hit = match_any(self.frame, self.images, ["startGameBtn"], scales=SCALES)
        self.assertIsNotNone(hit)
        self.assertGreaterEqual(hit.score, 0.85)

    def test_stage_marker_survives_window_scaling(self):
        hit = match_any(self.frame, self.images, ["stage"], scales=SCALES)
        self.assertIsNotNone(hit)
        self.assertGreaterEqual(hit.score, 0.85)


if __name__ == "__main__":
    unittest.main()
