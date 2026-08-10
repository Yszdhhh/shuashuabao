import unittest
import time
from pathlib import Path

import cv2
import numpy as np

from gamescript.vision.capture import Frame, _window_title_score, is_local_helper_title
from gamescript.vision.matcher import MatchResult, _load_template, find_blue_button, find_input_boxes, match_all, match_any
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
        # LIVE remains Fail-Closed; dry_run/OBSERVE is covered separately and
        # records this timeout without terminating.
        med = Mediator(Settings(query_timeout=10, dry_run=False), root)
        med.see = lambda reason="": Frame(np.zeros((720, 1280, 3), dtype=np.uint8))
        med._missing_window_since = time.time() - 20
        self.assertEqual(med.tick(), LoopAction.Break)
        self.assertEqual(med.phase, Phase.ERROR)

    def test_phase_transition_to_main_line_is_not_ignored(self):
        med = Mediator(Settings(), Path(__file__).resolve().parents[1])
        med.set_phase(Phase.STAGE_STARTING)
        med.set_phase(Phase.MAIN_LINE, "stage start verified")
        self.assertEqual(med.phase, Phase.MAIN_LINE)

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

    def test_match_all_keeps_two_reward_choices(self):
        template = _load_template(self.images_dir() / "skills" / "asj.png")
        self.assertIsNotNone(template)
        frame = np.zeros((500, 900, 3), dtype=np.uint8)
        frame[100:100 + template.shape[0], 260:260 + template.shape[1]] = template
        frame[100:100 + template.shape[0], 520:520 + template.shape[1]] = template
        hits = match_all(
            Frame(frame),
            self.images_dir(),
            ["skills/asj"],
            threshold=0.99,
            roi=(0.20, 0.10, 0.90, 0.70),
        )
        self.assertEqual(len(hits), 2)
        self.assertEqual([hit.x for hit in hits], [260, 520])

    def test_reward_choice_prefers_configured_skill_in_center_roi(self):
        root = Path(__file__).resolve().parents[1]
        frame = np.zeros((939, 1616, 3), dtype=np.uint8)
        # 用新版面板按钮模板作 anchor（hide.png 为旧版 UI 模板，会与新按钮
        # 模板交叉误匹配导致分类漂移）
        anchor_btn = _load_template(root / "assets" / "Images" / "skill_giveup_btn.png")
        first = _load_template(root / "assets" / "Images" / "skills" / "asj.png")
        preferred = _load_template(root / "assets" / "Images" / "skills" / "assx.png")
        third = _load_template(root / "assets" / "Images" / "skills" / "dz.png")
        self.assertIsNotNone(anchor_btn)
        self.assertIsNotNone(first)
        self.assertIsNotNone(preferred)
        self.assertIsNotNone(third)
        frame[595:595 + anchor_btn.shape[0], 542:542 + anchor_btn.shape[1]] = anchor_btn
        frame[261:261 + first.shape[0], 526:526 + first.shape[1]] = first
        frame[261:261 + preferred.shape[0], 759:759 + preferred.shape[1]] = preferred
        frame[261:261 + third.shape[0], 992:992 + third.shape[1]] = third
        med = Mediator(Settings(skills=["assx"], match_threshold=0.85), root)
        kind, hit = med._find_reward_choice(Frame(frame))
        self.assertEqual(kind, "技能")
        self.assertEqual(hit.name, "assx")

    def test_challenge_label_maps_to_icon_click_and_detects_auto(self):
        root = Path(__file__).resolve().parents[1]
        frame = np.zeros((900, 800, 3), dtype=np.uint8)
        label = _load_template(root / "assets" / "Images" / "challenges" / "coin_challenge.png")
        self.assertIsNotNone(label)
        frame[698:698 + label.shape[0], 150:150 + label.shape[1]] = label
        frame[624:656, 138:237] = (0, 220, 0)
        med = Mediator(Settings(), root)
        found = med._find_challenge_button(Frame(frame), "coin_challenge")
        self.assertIsNotNone(found)
        label_hit, click_hit = found
        self.assertEqual(click_hit.screen_y, label_hit.screen_y - 42)
        self.assertTrue(med._challenge_is_auto(Frame(frame), label_hit))

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
