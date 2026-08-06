import unittest
import time
from pathlib import Path

import cv2
import numpy as np

from gamescript.vision.capture import Frame, _window_title_score, is_local_helper_title
from gamescript.vision.matcher import MatchResult, find_blue_button, find_input_boxes, match_any
from gamescript.loop_action import LoopAction
from gamescript.mediator import Mediator, Phase
from gamescript.settings import Settings


class LobbyDetectorTests(unittest.TestCase):
    def test_blue_detection_is_roi_bound(self):
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        cv2.rectangle(frame, (180, 540), (380, 590), (230, 150, 20), -1)
        cv2.rectangle(frame, (600, 540), (800, 590), (230, 150, 20), -1)
        hit = find_blue_button(Frame(frame), (0.10, 0.70, 0.60, 0.99), side="left")
        self.assertIsNotNone(hit)
        self.assertEqual((hit.x, hit.y), (180, 540))

    def test_map_blue_fallback_rejects_one_ambiguous_candidate(self):
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        cv2.rectangle(frame, (760, 540), (960, 590), (230, 150, 20), -1)
        self.assertIsNone(find_blue_button(frame=Frame(frame), roi=(0.10, 0.70, 0.99, 0.99), side="left"))

    def test_match_any_has_no_global_blue_fallback(self):
        frame = np.zeros((200, 300, 3), dtype=np.uint8)
        cv2.rectangle(frame, (20, 120), (220, 165), (230, 150, 20), -1)
        self.assertIsNone(match_any(Frame(frame), self.images_dir(), ["missing_start"]))

    def test_window_role_separates_platform_and_game(self):
        platform = "KK官方对战平台"
        game = "英雄三国KK"
        self.assertGreater(_window_title_score(platform, "l0"), 0)
        self.assertLess(_window_title_score(platform, "l1"), 0)
        self.assertGreater(_window_title_score(game, "l1"), 0)
        self.assertLess(_window_title_score(game, "l0"), 0)

    def test_local_control_panel_is_not_a_game_window(self):
        helper = "英雄三国挂机助手 (懒人系列之魔兽世界刷刷刷) · 1.3.3.3 本地版"
        self.assertTrue(is_local_helper_title(helper))
        self.assertFalse(is_local_helper_title("英雄三国KK"))

    def test_missing_window_fails_closed(self):
        root = Path(__file__).resolve().parents[1]
        med = Mediator(Settings(query_timeout=10), root)
        med.see = lambda reason="": Frame(np.zeros((720, 1280, 3), dtype=np.uint8))
        med._missing_window_since = time.time() - 20
        self.assertEqual(med.tick(), LoopAction.Break)
        self.assertEqual(med.phase, Phase.ERROR)

    def test_dialog_fields_need_two_similar_boxes(self):
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        for y in (300, 360):
            cv2.rectangle(frame, (480, y), (800, y + 35), (60, 60, 60), -1)
            cv2.rectangle(frame, (480, y), (800, y + 35), (180, 180, 180), 2)
        anchor = MatchResult("confirm", 0.9, 690, 440, 160, 50, 770, 465)
        boxes = find_input_boxes(Frame(frame), anchor=anchor)
        self.assertEqual(len(boxes), 2)

    def test_create_dialog_button_is_found_in_bottom_roi(self):
        frame = np.zeros((488, 584, 3), dtype=np.uint8)
        for y in (98, 194):
            cv2.rectangle(frame, (203, y), (485, y + 32), (60, 60, 60), -1)
            cv2.rectangle(frame, (203, y), (485, y + 32), (180, 180, 180), 2)
        # Current KK create dialog: Create is left of Cancel at the bottom.
        cv2.rectangle(frame, (262, 418), (373, 458), (230, 150, 20), -1)
        cv2.rectangle(frame, (390, 420), (506, 456), (230, 150, 20), -1)
        root = Path(__file__).resolve().parents[1]
        med = Mediator(Settings(auto_create_room=True), root)
        hit = med._find_create_confirm(Frame(frame))
        self.assertIsNotNone(hit)
        self.assertLess(hit.x, 350)
        self.assertEqual(med._detect_context(Frame(frame)), "CREATE_ROOM")

    def test_map_create_template_is_preferred_over_quick_join(self):
        root = Path(__file__).resolve().parents[1]
        template = cv2.imdecode(
            np.fromfile(str(root / "assets" / "Images" / "lobby" / "create_room.png"), dtype=np.uint8),
            cv2.IMREAD_COLOR,
        )
        self.assertIsNotNone(template)
        frame = np.zeros((932, 1328, 3), dtype=np.uint8)
        y, x = 862, 723
        h, w = template.shape[:2]
        frame[y:y + h, x:x + w] = template
        med = Mediator(Settings(auto_create_room=True), root)
        hit = med._find_map_create_room(Frame(frame))
        self.assertIsNotNone(hit)
        self.assertEqual(hit.name, "create_room")
        self.assertEqual((hit.x, hit.y), (x, y))

    @staticmethod
    def images_dir():
        from pathlib import Path

        return Path(__file__).resolve().parents[1] / "assets" / "Images"


if __name__ == "__main__":
    unittest.main()
