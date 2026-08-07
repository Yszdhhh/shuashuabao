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

    # 1. 自动任务关闭图测试
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
            
            # 必须且只调用一次 executor.click
            mock_click.assert_called_once()
            mock_right_click.assert_not_called()
            
            # 点击坐标必须落在右侧自动任务复选框 ROI 范围内 (x: 0.85*w .. 0.95*w, y: 0.52*h .. 0.62*h)
            x_arg, y_arg = mock_click.call_args[0]
            kwargs = mock_click.call_args[1]
            
            self.assertGreaterEqual(x_arg, int(0.85 * f_off.width))
            self.assertLessEqual(x_arg, int(0.95 * f_off.width))
            self.assertGreaterEqual(y_arg, int(0.52 * f_off.height))
            self.assertLessEqual(y_arg, int(0.62 * f_off.height))
            
            # 必须传递 target_hwnd 与 dry_run
            self.assertEqual(kwargs.get("target_hwnd"), 12345)
            self.assertTrue(kwargs.get("dry_run"))

    # 2. 自动任务开启图测试
    def test_auto_task_on_yields_zero_clicks_and_none_replay_action(self):
        f_on = load_fixture_frame("fixtures/replay/main_line_auto_on.png")
        f_on.hwnd = 10001
        self.med._last_frame = f_on
        self.med.phase = Phase.MAIN_LINE

        with patch.object(self.med.executor, "click", return_value=ActionResult(success=True, status="DRY_RUN")) as mock_click, \
             patch.object(self.med.executor, "right_click", return_value=ActionResult(success=True, status="DRY_RUN")) as mock_right_click:
            
            # _ensure_auto_task_enabled 应该识别已开启，返回 False，不发出点击
            self.assertFalse(self.med._ensure_auto_task_enabled(f_on))
            mock_click.assert_not_called()
            mock_right_click.assert_not_called()

        # 回放结果检查
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

    # 3. 同一关闭帧重试保护与状态重置测试
    def test_auto_task_retry_limit_and_state_resets(self):
        f_off = load_fixture_frame("fixtures/replay/main_line_auto_off.png")
        f_off.hwnd = 10001
        self.med._last_frame = f_off

        # 模拟点击 3 次后触上限
        self.med._auto_task_attempts = 3
        with patch.object(self.med.executor, "click") as mock_click:
            self.assertFalse(self.med._ensure_auto_task_enabled(f_off))
            mock_click.assert_not_called()

        # 切换进 Phase.MAIN_LINE 应重置重试状态
        self.med.set_phase(Phase.MAIN_LINE, "reset test")
        self.assertEqual(self.med._auto_task_attempts, 0)
        self.assertFalse(self.med._auto_task_done)

        # 只有在后续帧中识别到已开启时才标记完成
        f_on = load_fixture_frame("fixtures/replay/main_line_auto_on.png")
        self.assertFalse(self.med._ensure_auto_task_enabled(f_on))
        self.assertTrue(self.med._auto_task_done)

    def test_executor_failure_or_stop_signal_aborts_auto_task_input(self):
        f_off = load_fixture_frame("fixtures/replay/main_line_auto_off.png")
        f_off.hwnd = 10001
        self.med._last_frame = f_off

        # 点击失败 (如窗口变更/失效) 中断后续处理
        with patch.object(self.med.executor, "click", return_value=ActionResult(success=False, status="CANCELLED_WINDOW_CHANGED", message="Window changed")):
            acted = self.med._ensure_auto_task_enabled(f_off)
            self.assertFalse(acted)
            self.assertFalse(self.med._auto_task_done)

        # StopSignal 激活时终止循环
        self.med.stop_signal.trigger("Emergency stop test")
        self.assertEqual(self.med.tick(), gamescript.loop_action.LoopAction.Break)

    # 4. 回放严格性与动作类型校验
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

        # 模拟产生 right_click 或错误的 action 导致预期匹配失败
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
        # 如果自动任务识别被 mock 为 None，导致回退到产生金币挑战的 right_click
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
        
        # 羁绊 3选一
        f_bond = load_fixture_frame("fixtures/replay/bond_choice_3.png")
        self.assertIsNone(self.med._find_reward_choice(f_bond))

        # 宝物 3选一
        f_treasure = load_fixture_frame("fixtures/replay/treasure_choice_3.png")
        self.assertIsNone(self.med._find_reward_choice(f_treasure))

        # 黑商
        f_black = load_fixture_frame("fixtures/replay/black_merchant_card_strip.png")
        self.assertIsNone(self.med._find_reward_choice(f_black))


if __name__ == "__main__":
    unittest.main()
