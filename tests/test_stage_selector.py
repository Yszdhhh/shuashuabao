from pathlib import Path
import unittest

import cv2
import numpy as np

from gamescript.vision.capture import Frame
from gamescript.vision.matcher import _load_template
from gamescript.vision.stage_selector import (
    StageId,
    find_stage_in_range,
    find_stage_labels,
    verify_stage_selection,
    visible_stage_rows,
)


ROOT = Path(__file__).resolve().parents[1]
IMAGES = ROOT / "assets" / "Images"


class StageSelectorTests(unittest.TestCase):
    def _frame_with_labels(self) -> Frame:
        frame = np.zeros((939, 1616, 3), dtype=np.uint8)
        x = int(frame.shape[1] * 0.62) + 50
        for y, name in ((160, "5-6"), (215, "5-10")):
            label = _load_template(IMAGES / f"{name}.png")
            self.assertIsNotNone(label)
            h, w = label.shape[:2]
            frame[y:y + h, x:x + w] = label
        return Frame(frame)

    def test_reads_numbered_rows_without_ocr_dependency(self):
        rows = visible_stage_rows(self._frame_with_labels(), IMAGES)
        self.assertEqual([row.number for row in rows], [6, 10])
        self.assertEqual([str(row.stage_id) for row in rows], ["5-6", "5-10"])

    def test_prefers_configured_end_when_start_is_scrolled_out(self):
        hit = find_stage_in_range(self._frame_with_labels(), IMAGES, 1, 10)
        self.assertIsNotNone(hit)
        self.assertEqual(hit.name, "stage_target_5-10")

    def test_stage_id_chapter_distinction(self):
        s1 = StageId.parse("1-10")
        s2 = StageId.parse("5-10")
        self.assertIsNotNone(s1)
        self.assertIsNotNone(s2)
        self.assertNotEqual(s1, s2)
        self.assertEqual(s1.chapter, 1)
        self.assertEqual(s2.chapter, 5)

    def test_does_not_match_different_chapter_exact_target(self):
        # 5-10 is visible, but user requested exact 1-10
        hit = find_stage_labels(self._frame_with_labels(), IMAGES, ["1-10"])
        self.assertIsNone(hit)

        # Exact 5-10 request hits 5-10
        hit5 = find_stage_labels(self._frame_with_labels(), IMAGES, ["5-10"])
        self.assertIsNotNone(hit5)
        self.assertEqual(hit5.name, "stage_target_5-10")

    def test_verify_stage_selection(self):
        empty = Frame(np.zeros((939, 1616, 3), dtype=np.uint8))
        self.assertFalse(verify_stage_selection(empty))


if __name__ == "__main__":
    unittest.main()

