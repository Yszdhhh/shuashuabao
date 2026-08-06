from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from gamescript.loop_action import LoopAction
from gamescript.mediator import Mediator, Phase
from gamescript.settings import Settings
from gamescript.vision.capture import Frame
from gamescript.vision.matcher import MatchResult, _load_template
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
        hit = find_stage_labels(self._frame_with_labels(), IMAGES, ["1-10"])
        self.assertIsNone(hit)

        hit5 = find_stage_labels(self._frame_with_labels(), IMAGES, ["5-10"])
        self.assertIsNotNone(hit5)
        self.assertEqual(hit5.name, "stage_target_5-10")

    def test_verify_stage_selection_empty(self):
        empty = Frame(np.zeros((939, 1616, 3), dtype=np.uint8))
        self.assertFalse(verify_stage_selection(empty))

    def test_verify_stage_selection_bright_but_unselected(self):
        # Bright text on target row but no selection highlight over adjacent background
        img = np.zeros((939, 1616, 3), dtype=np.uint8)
        # Put bright white text everywhere in stage list region
        img[100:800, 900:1300] = 220
        frame = Frame(img)
        # Because adjacent rows are also bright (contrast diff < 10), verify returns False
        self.assertFalse(verify_stage_selection(frame, target="5-6"))

    def test_verify_stage_selection_selected_target_row(self):
        # Target row has bright selection highlight background while adjacent rows are dark
        img = np.zeros((939, 1616, 3), dtype=np.uint8)
        # Target row center at (1080, 200)
        img[185:215, 1000:1160] = 230
        frame = Frame(img)
        target_hit = MatchResult("stage_target_5-6", 1.0, 1080, 200, 40, 20, 1080, 200)
        self.assertTrue(verify_stage_selection(frame, target=target_hit))

    def test_verify_stage_selection_state_disappears(self):
        img_selected = np.zeros((939, 1616, 3), dtype=np.uint8)
        img_selected[185:215, 1000:1160] = 230
        frame_selected = Frame(img_selected)

        img_unselected = np.zeros((939, 1616, 3), dtype=np.uint8)
        frame_unselected = Frame(img_unselected)

        target_hit = MatchResult("stage_target_5-6", 1.0, 1080, 200, 40, 20, 1080, 200)
        self.assertTrue(verify_stage_selection(frame_selected, target=target_hit))
        self.assertFalse(verify_stage_selection(frame_unselected, target=target_hit))

    def test_mediator_verification_failure_no_start_click(self):
        settings = Settings()
        med = Mediator(settings, ROOT)
        med.set_phase(Phase.STAGE_SELECT)

        # Mock frame and stage target
        img = np.zeros((939, 1616, 3), dtype=np.uint8)
        frame = Frame(img, window_title="KK", hwnd=1000)

        hit = MatchResult("stage_target_5-6", 1.0, 1080, 200, 40, 20, 1080, 200)
        med._stage_selected = True
        med._stage_click_cooldown_until = 0.0

        with patch("gamescript.mediator.verify_stage_selection", return_value=False):
            with patch.object(med, "act_click") as mock_click:
                action = med._tick_l0(frame)
                self.assertEqual(action, LoopAction.Continue)
                mock_click.assert_not_called()

    def test_stage_id_cross_chapter_comparison(self):
        s1_10 = StageId(1, 10)
        s2_1 = StageId(2, 1)
        self.assertTrue(s1_10 < s2_1)
        self.assertTrue(s1_10 <= s2_1)
        self.assertFalse(s1_10 > s2_1)
        self.assertFalse(s1_10 >= s2_1)

    def test_stage_id_invalid_input(self):
        self.assertIsNone(StageId.parse(""))
        self.assertIsNone(StageId.parse("invalid"))
        self.assertIsNone(StageId.parse("-1"))
        self.assertIsNone(StageId.parse("1-"))


if __name__ == "__main__":
    unittest.main()
