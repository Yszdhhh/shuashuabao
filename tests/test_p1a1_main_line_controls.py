import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import gamescript.loop_action
from gamescript.input.keyboard_mouse import ActionResult
from gamescript.mediator import Mediator, Phase
from gamescript.settings import Settings
from gamescript.stop_signal import StopSignal
from gamescript.vision.capture import Frame
from gamescript.vision.matcher import MatchResult
from run_replay import run_replay_fixture


def load_fixture_frame(rel_path: str, title: str = "英雄三国KK") -> Frame:
    path = ROOT / rel_path
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    return Frame(img, window_title=title, hwnd=10001)


class P1A1MainLineControlsTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings()
        self.med = Mediator(self.settings, ROOT)

    # 1. 独立回归测试：未验证战后入口最高优先 (Section I)
    def test_simultaneous_archive_and_auto_task_hits_error_first(self):
        f = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), window_title="英雄三国KK", hwnd=10001)
        self.med._last_frame = f
        self.med.phase = Phase.MAIN_LINE

        archive_hit = MatchResult(name="archive", score=0.9, x=100, y=100, w=50, h=50, screen_x=100, screen_y=100)
        toggle_hit = MatchResult(name="auto_task_toggle", score=0.9, x=1400, y=500, w=30, h=30, screen_x=1400, screen_y=500)

        with patch.object(self.med, "find_scene", side_effect=lambda frame, scene, **kw: archive_hit if scene == "archive" else None), \
             patch.object(self.med, "_find_auto_task_toggle", return_value=toggle_hit), \
             patch.object(self.med, "act_click") as mock_act_click, \
             patch.object(self.med, "act_right_click") as mock_act_right_click, \
             patch.object(self.med, "act_key") as mock_act_key, \
             patch.object(self.med, "click_scene") as mock_click_scene, \
             patch.object(self.med.executor, "click") as mock_click, \
             patch.object(self.med.executor, "right_click") as mock_right_click, \
             patch.object(self.med.executor, "press_key") as mock_press_key:

            action = self.med._tick_main_line(f)
            self.assertEqual(action, gamescript.loop_action.LoopAction.Break)
            self.assertEqual(self.med.phase, Phase.ERROR)

            mock_act_click.assert_not_called()
            mock_act_right_click.assert_not_called()
            mock_act_key.assert_not_called()
            mock_click_scene.assert_not_called()
            mock_click.assert_not_called()
            mock_right_click.assert_not_called()
            mock_press_key.assert_not_called()

    def test_all_unverified_post_game_scenes_halt_before_any_input(self):
        for scene_key in ["archive", "boss_entry", "longzhu"]:
            med = Mediator(self.settings, ROOT)
            f = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), window_title="英雄三国KK", hwnd=10001)
            med._last_frame = f
            med.phase = Phase.MAIN_LINE

            scene_hit = MatchResult(name=scene_key, score=0.9, x=100, y=100, w=50, h=50, screen_x=100, screen_y=100)
            toggle_hit = MatchResult(name="auto_task_toggle", score=0.9, x=1400, y=500, w=30, h=30, screen_x=1400, screen_y=500)

            with patch.object(med, "find_scene", side_effect=lambda frame, scene, **kw: scene_hit if scene == scene_key else None), \
                 patch.object(med, "_find_auto_task_toggle", return_value=toggle_hit), \
                 patch.object(med.executor, "click") as mock_click, \
                 patch.object(med.executor, "right_click") as mock_right_click:

                action = med._tick_main_line(f)
                self.assertEqual(action, gamescript.loop_action.LoopAction.Break)
                self.assertEqual(med.phase, Phase.ERROR)
                mock_click.assert_not_called()
                mock_right_click.assert_not_called()

    # 2. 自动任务真实素材与识别测试 (Section II & III)
    def test_auto_task_off_triggers_left_click_in_right_roi(self):
        f_off = load_fixture_frame("fixtures/replay/main_line_auto_off.png")
        f_off.hwnd = 12345
        self.med._last_frame = f_off
        self.med.phase = Phase.MAIN_LINE
        self.settings.dry_run = True

        with patch.object(self.med.executor, "click", return_value=ActionResult(success=True, status="DRY_RUN")) as mock_click, \
             patch.object(self.med.executor, "right_click", return_value=ActionResult(success=True, status="DRY_RUN")) as mock_right_click:

            action = self.med._tick_main_line(f_off)
            self.assertEqual(action, gamescript.loop_action.LoopAction.Continue)

            mock_click.assert_called_once()
            mock_right_click.assert_not_called()

            x_arg, y_arg = mock_click.call_args[0]
            kwargs = mock_click.call_args[1]

            self.assertGreaterEqual(x_arg, int(0.85 * f_off.width))
            self.assertLessEqual(x_arg, int(0.95 * f_off.width))
            self.assertGreaterEqual(y_arg, int(0.50 * f_off.height))
            self.assertLessEqual(y_arg, int(0.65 * f_off.height))

            self.assertEqual(kwargs.get("target_hwnd"), 12345)
            self.assertTrue(kwargs.get("dry_run"))

    def test_auto_task_on_yields_zero_clicks_and_none_replay_action(self):
        f_on = load_fixture_frame("fixtures/replay/main_line_auto_on.png")
        f_on.hwnd = 10001
        self.med._last_frame = f_on
        self.med.phase = Phase.MAIN_LINE

        with patch.object(self.med.executor, "click", return_value=ActionResult(success=True, status="DRY_RUN")) as mock_click, \
             patch.object(self.med.executor, "right_click", return_value=ActionResult(success=True, status="DRY_RUN")) as mock_right_click:

            res = self.med._ensure_auto_task_enabled(f_on)
            self.assertIsNone(res)
            mock_click.assert_not_called()
            mock_right_click.assert_not_called()

        fix_on = {
            "fixture_id": "main_line_auto_on",
            "file_path": "fixtures/replay/main_line_auto_on.png",
            "resolution": [1609, 932],
            "window_title": "英雄三国KK",
            "page": "MAIN_LINE",
            "expected_state": "MAIN_LINE",
            "expected_action": "none",
            "expected_input_kind": "none",
            "required": True,
        }
        res = run_replay_fixture(fix_on, self.med, ROOT)
        self.assertEqual(res.status, "PASS")
        self.assertEqual(res.action_name, "none")
        self.assertEqual(res.action_kind, "none")
        self.assertIsNone(res.click_point)

    # 3. 失败、有限重试与状态流转测试 (Section III)
    def test_auto_task_retry_limit_and_state_resets(self):
        f_off = load_fixture_frame("fixtures/replay/main_line_auto_off.png")
        f_off.hwnd = 10001
        self.med._last_frame = f_off

        self.med._auto_task_attempts = 3
        with patch.object(self.med.executor, "click") as mock_click:
            res = self.med._ensure_auto_task_enabled(f_off)
            self.assertEqual(res, gamescript.loop_action.LoopAction.Break)
            self.assertEqual(self.med.phase, Phase.ERROR)
            mock_click.assert_not_called()

        self.med.set_phase(Phase.MAIN_LINE, "reset test")
        self.assertEqual(self.med._auto_task_attempts, 0)
        self.assertFalse(self.med._auto_task_done)

        f_on = load_fixture_frame("fixtures/replay/main_line_auto_on.png")
        res_on = self.med._ensure_auto_task_enabled(f_on)
        self.assertIsNone(res_on)
        self.assertTrue(self.med._auto_task_done)

    def test_auto_task_off_executor_failure_retry_count_and_no_right_click(self):
        f_off = load_fixture_frame("fixtures/replay/main_line_auto_off.png")
        f_off.hwnd = 10001
        self.med._last_frame = f_off
        self.med.phase = Phase.MAIN_LINE

        with patch.object(self.med.executor, "click", return_value=ActionResult(success=False, status="CANCELLED", message="Failed")), \
             patch.object(self.med.executor, "right_click") as mock_right_click:

            action1 = self.med._tick_main_line(f_off)
            self.assertEqual(action1, gamescript.loop_action.LoopAction.Continue)
            self.assertEqual(self.med._auto_task_attempts, 1)
            mock_right_click.assert_not_called()

            action2 = self.med._tick_main_line(f_off)
            self.assertEqual(action2, gamescript.loop_action.LoopAction.Continue)
            self.assertEqual(self.med._auto_task_attempts, 2)
            mock_right_click.assert_not_called()

            action3 = self.med._tick_main_line(f_off)
            self.assertEqual(action3, gamescript.loop_action.LoopAction.Break)
            self.assertEqual(self.med._auto_task_attempts, 3)
            self.assertEqual(self.med.phase, Phase.ERROR)
            mock_right_click.assert_not_called()

    def test_stop_signal_or_hwnd_change_aborts_subsequent_input(self):
        f_off = load_fixture_frame("fixtures/replay/main_line_auto_off.png")
        f_off.hwnd = 10001
        self.med._last_frame = f_off

        self.med.stop_signal.trigger("Emergency stop test")
        self.assertEqual(self.med.tick(), gamescript.loop_action.LoopAction.Break)

    # 4. 回放严格性与动作类型校验 (Section IV)
    def test_replay_strictness_input_kind_mismatch_fails(self):
        fix_off = {
            "fixture_id": "main_line_auto_off",
            "file_path": "fixtures/replay/main_line_auto_off.png",
            "resolution": [1599, 933],
            "window_title": "英雄三国KK",
            "page": "MAIN_LINE",
            "expected_state": "MAIN_LINE",
            "expected_action": "EnableAutoTask",
            "expected_input_kind": "left_click",
            "required": True,
        }
        res_pass = run_replay_fixture(fix_off, self.med, ROOT)
        self.assertEqual(res_pass.status, "PASS")
        self.assertEqual(res_pass.action_name, "EnableAutoTask")
        self.assertEqual(res_pass.action_kind, "left_click")

        fix_mismatch_kind = dict(fix_off, expected_input_kind="right_click")
        res_fail_kind = run_replay_fixture(fix_mismatch_kind, self.med, ROOT)
        self.assertEqual(res_fail_kind.status, "FAIL")

        fix_mismatch_action = dict(fix_off, expected_action="EnableAutoChallenges")
        res_fail_action = run_replay_fixture(fix_mismatch_action, self.med, ROOT)
        self.assertEqual(res_fail_action.status, "FAIL")

    def test_challenge_right_click_does_not_pass_auto_task_fixture(self):
        fix_auto_off = {
            "fixture_id": "main_line_auto_off",
            "file_path": "fixtures/replay/main_line_auto_off.png",
            "resolution": [1599, 933],
            "window_title": "英雄三国KK",
            "page": "MAIN_LINE",
            "expected_state": "MAIN_LINE",
            "expected_action": "EnableAutoTask",
            "expected_input_kind": "left_click",
            "required": True,
        }
        with patch.object(self.med, "_find_auto_task_toggle", return_value=None):
            res = run_replay_fixture(fix_auto_off, self.med, ROOT)
            self.assertEqual(res.status, "FAIL")
            self.assertIn("Action mismatch", res.notes)

    # 5. 技能选择测试（3选一/4选一/多配置优先级/空配置/非技能卡片隔离）
    def test_skill_choice_3_real_screenshot(self):
        f3 = load_fixture_frame("fixtures/replay/skill_choice_3.png")
        self.settings.skills = ["asj", "dz"]
        choice = self.med._find_reward_choice(f3)
        self.assertIsNotNone(choice)
        kind, hit = choice
        self.assertEqual(kind, "技能")
        self.assertEqual(hit.name, "asj")

    def test_skill_choice_4_real_screenshot(self):
        f4 = load_fixture_frame("fixtures/replay/skill_choice_4.jpg")
        self.settings.skills = ["dcw", "byj"]
        choice = self.med._find_reward_choice(f4)
        self.assertIsNotNone(choice)
        kind, hit = choice
        self.assertEqual(kind, "技能")
        self.assertEqual(hit.name, "dcw")

    def test_skill_choice_multiple_configured_skills_respects_priority(self):
        f4 = load_fixture_frame("fixtures/replay/skill_choice_4.jpg")
        self.settings.skills = ["byj", "dcw"]
        choice1 = self.med._find_reward_choice(f4)
        self.assertIsNotNone(choice1)
        self.assertEqual(choice1[1].name, "byj")

        self.settings.skills = ["dcw", "byj"]
        choice2 = self.med._find_reward_choice(f4)
        self.assertIsNotNone(choice2)
        self.assertEqual(choice2[1].name, "dcw")

    def test_skill_choice_unconfigured_or_empty_skills_yields_zero_action(self):
        f4 = load_fixture_frame("fixtures/replay/skill_choice_4.jpg")
        self.settings.skills = ["asj", "jq"]
        self.assertIsNone(self.med._find_reward_choice(f4))

        self.settings.skills = []
        self.assertIsNone(self.med._find_reward_choice(f4))

    def test_skill_choice_invalid_candidate_count_yields_zero_action(self):
        f3 = load_fixture_frame("fixtures/replay/skill_choice_3.png")
        self.settings.skills = ["asj", "ys", "dz"]

        mock_candidates_2 = [
            MatchResult(name="skills/asj", score=0.9, x=752, y=260, w=98, h=97, screen_x=752, screen_y=260),
            MatchResult(name="skills/ys", score=0.9, x=519, y=260, w=98, h=97, screen_x=519, screen_y=260),
        ]
        with patch("gamescript.mediator.match_all", return_value=mock_candidates_2):
            self.assertIsNone(self.med._find_reward_choice(f3))

        mock_candidates_5 = [
            MatchResult(name="skills/asj", score=0.9, x=500, y=260, w=98, h=97, screen_x=500, screen_y=260),
            MatchResult(name="skills/ys", score=0.9, x=600, y=260, w=98, h=97, screen_x=600, screen_y=260),
            MatchResult(name="skills/dz", score=0.9, x=700, y=260, w=98, h=97, screen_x=700, screen_y=260),
            MatchResult(name="skills/byj", score=0.9, x=800, y=260, w=98, h=97, screen_x=800, screen_y=260),
            MatchResult(name="skills/dcw", score=0.9, x=900, y=260, w=98, h=97, screen_x=900, screen_y=260),
        ]
        with patch("gamescript.mediator.match_all", return_value=mock_candidates_5):
            self.assertIsNone(self.med._find_reward_choice(f3))

    def test_non_skill_real_choice_materials_yield_zero_action(self):
        self.settings.skills = ["asj", "dz", "byj", "dcw"]

        f_bond = load_fixture_frame("fixtures/replay/bond_choice_3.png")
        self.assertIsNone(self.med._find_reward_choice(f_bond))

        f_treasure = load_fixture_frame("fixtures/replay/treasure_choice_3.png")
        self.assertIsNone(self.med._find_reward_choice(f_treasure))

        f_black = load_fixture_frame("fixtures/replay/black_merchant_card_strip.png")
        self.assertIsNone(self.med._find_reward_choice(f_black))


if __name__ == "__main__":
    unittest.main()
