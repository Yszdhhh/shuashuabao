import json
import sys
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import shuabao.loop_action
from shuabao.input.keyboard_mouse import ActionResult
from shuabao.mediator import Mediator, Phase
from shuabao.settings import Settings
from shuabao.stop_signal import StopSignal
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult
from run_replay import run_replay_fixture


def load_fixture_frame(rel_path: str, title: str = "英雄三国KK") -> Frame:
    path = ROOT / rel_path
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    return Frame(img, window_title=title, hwnd=10001)


class P1A1MainLineControlsTests(unittest.TestCase):
    def setUp(self):
        # These fixtures exercise the deterministic template path.  Live OCR has
        # separate contract/integration coverage and must be opted into explicitly.
        self.settings = Settings(ocr_mode="off")
        self.med = Mediator(self.settings, ROOT)

    def test_simultaneous_archive_and_auto_task_hits_error_first(self):
        """20260831 实机复盘：未验证 archive 守卫只对"无战后上下文"的帧
        Fail-Closed；`_post_game_pending=True` 属于战后链过渡窗，必须豁免
        （Continue 零输入），否则过渡帧误杀停机。见 mediator 未验证入口分支。"""
        # lab 不属于无人值守模式，仍走 Fail-Closed；normal_farm 的零输入不停机见 test_unattended_recovery_20260914。
        self.settings = Settings(ocr_mode="off", mode_id="lab")
        self.med = Mediator(self.settings, ROOT)
        f = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), window_title="英雄三国KK", hwnd=10001)
        self.med._last_frame = f
        self.med.phase = Phase.MAIN_LINE
        self.med._post_game_pending = False
        self.med._round_deadline = time.time() + 5  # 局尾窗口内

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
            self.assertEqual(action, shuabao.loop_action.LoopAction.Break)
            self.assertEqual(self.med.phase, Phase.ERROR)

            mock_act_click.assert_not_called()
            mock_act_right_click.assert_not_called()
            mock_act_key.assert_not_called()
            mock_click_scene.assert_not_called()
            mock_click.assert_not_called()
            mock_right_click.assert_not_called()
            mock_press_key.assert_not_called()

        # 战后过渡窗（pending=True）同帧出现 archive 顶栏 → 豁免、零输入 Continue
        self.med._post_game_pending = True
        with patch.object(self.med, "find_scene", side_effect=lambda frame, scene, **kw: archive_hit if scene == "archive" else None), \
             patch.object(self.med, "_find_auto_task_toggle", return_value=toggle_hit), \
             patch.object(self.med, "act_click") as mock_act_click, \
             patch.object(self.med, "click_scene") as mock_click_scene:
            action = self.med._tick_main_line(f)
            self.assertEqual(action, shuabao.loop_action.LoopAction.Continue)
            mock_act_click.assert_not_called()
            mock_click_scene.assert_not_called()


    def test_all_unverified_post_game_scenes_halt_before_any_input(self):
        # lab 不属于无人值守模式，仍走 Fail-Closed；normal_farm 的零输入不停机见 test_unattended_recovery_20260914。
        self.settings = Settings(ocr_mode="off", mode_id="lab")
        # 20260831 实机复盘：未验证 archive 守卫只对"无战后上下文"的帧
        # Fail-Closed（pending=False + 局尾窗口）；`_post_game_pending=True`
        # 属于战后链过渡窗 → 豁免、零输入 Continue。
        # boss_entry 20260822 起是 Boss 提前挑战入口：未配置挑战 Boss 时零输入
        # 等待（不 ERROR、零输入）；longzhu 色相检查移至 LONGZHU 阶段。
        med = Mediator(self.settings, ROOT)
        f = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), window_title="英雄三国KK", hwnd=10001)
        med._last_frame = f
        med.phase = Phase.MAIN_LINE
        med._post_game_pending = False
        med._round_deadline = time.time() + 5  # 局尾窗口内

        scene_hit = MatchResult(name="archive", score=0.9, x=100, y=100, w=50, h=50, screen_x=100, screen_y=100)
        toggle_hit = MatchResult(name="auto_task_toggle", score=0.9, x=1400, y=500, w=30, h=30, screen_x=1400, screen_y=500)

        with patch.object(med, "find_scene", side_effect=lambda frame, scene, **kw: scene_hit if scene == "archive" else None), \
             patch.object(med, "_find_auto_task_toggle", return_value=toggle_hit), \
             patch.object(med.executor, "click") as mock_click, \
             patch.object(med.executor, "right_click") as mock_right_click:

            action = med._tick_main_line(f)
            self.assertEqual(action, shuabao.loop_action.LoopAction.Break)
            self.assertEqual(med.phase, Phase.ERROR)
            mock_click.assert_not_called()
            mock_right_click.assert_not_called()

        # 战后过渡窗（pending=True）：archive 顶栏豁免 → 零输入 Continue、不进 ERROR
        med = Mediator(self.settings, ROOT)
        med._last_frame = f
        med.phase = Phase.MAIN_LINE
        med._post_game_pending = True
        with patch.object(med, "find_scene", side_effect=lambda frame, scene, **kw: scene_hit if scene == "archive" else None), \
             patch.object(med, "_find_auto_task_toggle", return_value=toggle_hit), \
             patch.object(med.executor, "click") as mock_click, \
             patch.object(med.executor, "right_click") as mock_right_click:
            action = med._tick_main_line(f)
            self.assertEqual(action, shuabao.loop_action.LoopAction.Continue)
            self.assertEqual(med.phase, Phase.MAIN_LINE)
            mock_click.assert_not_called()
            mock_right_click.assert_not_called()

        # boss_entry 未配置挑战 Boss：零输入 Continue、不进 ERROR
        med = Mediator(self.settings, ROOT)
        f = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), window_title="英雄三国KK", hwnd=10001)
        med._last_frame = f
        med.phase = Phase.MAIN_LINE
        med._post_game_pending = True
        boss_scene_hit = MatchResult(name="boss_entry", score=0.9, x=100, y=100, w=50, h=50, screen_x=100, screen_y=100)
        toggle_hit = MatchResult(name="auto_task_toggle", score=0.9, x=1400, y=500, w=30, h=30, screen_x=1400, screen_y=500)
        with patch.object(med, "find_scene", side_effect=lambda frame, scene, **kw: boss_scene_hit if scene == "boss_entry" else None), \
             patch.object(med, "_find_auto_task_toggle", return_value=toggle_hit), \
             patch.object(med.executor, "click") as mock_click, \
             patch.object(med.executor, "right_click") as mock_right_click:
            action = med._tick_main_line(f)
            self.assertEqual(action, shuabao.loop_action.LoopAction.Continue)
            self.assertEqual(med.phase, Phase.MAIN_LINE)
            mock_click.assert_not_called()
            mock_right_click.assert_not_called()

        # longzhu：LONGZHU 阶段才检查并 Fail-Closed
        med = Mediator(self.settings, ROOT)
        f = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), window_title="英雄三国KK", hwnd=10001)
        med.set_phase(Phase.LONGZHU)
        scene_hit = MatchResult(name="longzhu", score=0.9, x=700, y=250, w=50, h=50, screen_x=700, screen_y=250)
        with patch.object(med, "find_scene", side_effect=lambda frame, scene, **kw: scene_hit if scene == "longzhu" else None), \
             patch.object(med.executor, "click") as mock_click, \
             patch.object(med.executor, "right_click") as mock_right_click:
            action = med._tick_l1_tail(f)
            self.assertEqual(action, shuabao.loop_action.LoopAction.Break)
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
            self.assertEqual(action, shuabao.loop_action.LoopAction.Continue)

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
            self.assertEqual(res, shuabao.loop_action.LoopAction.Break)
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
            self.assertEqual(action1, shuabao.loop_action.LoopAction.Continue)
            self.assertEqual(self.med._auto_task_attempts, 1)
            mock_right_click.assert_not_called()

            action2 = self.med._tick_main_line(f_off)
            self.assertEqual(action2, shuabao.loop_action.LoopAction.Continue)
            self.assertEqual(self.med._auto_task_attempts, 2)
            mock_right_click.assert_not_called()

            action3 = self.med._tick_main_line(f_off)
            self.assertEqual(action3, shuabao.loop_action.LoopAction.Break)
            self.assertEqual(self.med._auto_task_attempts, 3)
            self.assertEqual(self.med.phase, Phase.ERROR)
            mock_right_click.assert_not_called()

    def test_stop_signal_or_hwnd_change_aborts_subsequent_input(self):
        f_off = load_fixture_frame("fixtures/replay/main_line_auto_off.png")
        f_off.hwnd = 10001
        self.med._last_frame = f_off

        self.med.stop_signal.trigger("Emergency stop test")
        self.assertEqual(self.med.tick(), shuabao.loop_action.LoopAction.Break)

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

    def test_skill_choice_no_preferred_hit_refreshes_then_blocks_giveup(self):
        # 技能只允许用户配置项：焦点技能未命中时先走已验证刷新钮；
        # 刷新预算耗尽后仅在有隐藏模板时收口，否则零输入；绝不点配置外技能或放弃。
        f4 = load_fixture_frame("fixtures/replay/skill_choice_4.jpg")
        self.settings.skills = ["asj", "jq"]  # 不在该面板上的技能
        choice = self.med._find_reward_choice(f4)
        self.assertIsNotNone(choice)
        self.assertEqual(choice[0], "技能刷新")
        self.assertEqual(choice[1].name, "refresh")

        self.med._choice_session = replace(
            self.med._choice_session,
            refreshes=self.med._choice_session.max_refreshes,
        )
        exhausted = self.med._find_reward_choice(f4)
        self.assertIsNone(exhausted, "刷新预算耗尽且无隐藏模板时必须零输入，不得点放弃")
    def test_skill_choice_candidate_count_is_not_a_hard_gate(self):
        # 57d40ce 移除 3/4 数量门：少识别/多误识别不阻塞，只选配置内的候选
        # （按 settings.skills 配置顺序，不按视觉分数）。
        f3 = load_fixture_frame("fixtures/replay/skill_choice_3.png")
        self.settings.skills = ["asj", "ys", "dz"]

        mock_candidates_2 = [
            MatchResult(name="skills/asj", score=0.9, x=752, y=260, w=98, h=97, screen_x=752, screen_y=260),
            MatchResult(name="skills/ys", score=0.9, x=519, y=260, w=98, h=97, screen_x=519, screen_y=260),
        ]
        with patch("shuabao.mediator.match_all", return_value=mock_candidates_2):
            choice = self.med._find_reward_choice(f3)
            self.assertIsNotNone(choice)
            self.assertEqual(Path(choice[1].name).stem, "asj")

        mock_candidates_5 = [
            MatchResult(name="skills/asj", score=0.9, x=500, y=260, w=98, h=97, screen_x=500, screen_y=260),
            MatchResult(name="skills/ys", score=0.9, x=600, y=260, w=98, h=97, screen_x=600, screen_y=260),
            MatchResult(name="skills/dz", score=0.9, x=700, y=260, w=98, h=97, screen_x=700, screen_y=260),
            MatchResult(name="skills/byj", score=0.9, x=800, y=260, w=98, h=97, screen_x=800, screen_y=260),
            MatchResult(name="skills/dcw", score=0.9, x=900, y=260, w=98, h=97, screen_x=900, screen_y=260),
        ]
        with patch("shuabao.mediator.match_all", return_value=mock_candidates_5):
            choice = self.med._find_reward_choice(f3)
            self.assertIsNotNone(choice)
            self.assertEqual(Path(choice[1].name).stem, "asj")  # 配置序第一，忽略配置外候选

        # 候选全在配置外 → 绝不返回配置外的卡；有刷新预算时只点刷新。
        mock_outside = [
            MatchResult(name="skills/zzz", score=0.95, x=600, y=260, w=98, h=97, screen_x=600, screen_y=260),
        ]
        with patch("shuabao.mediator.match_all", return_value=mock_outside):
            choice = self.med._find_reward_choice(f3)
            self.assertIsNotNone(choice)
            self.assertEqual(choice[0], "技能刷新")
            self.assertIn(choice[1].name, ("refresh", "skill_refresh_btn"))
    def test_treasure_fixture_uses_real_card_centers_and_not_skill_layout(self):
        # A3：禁止无脑第一张；无 cards 偏好时宝物可走品质色（负面剔除后），
        # 坐标仍必须是宝物布局而非技能布局。
        # 2026-08-16 L1 裁决：新判别纪律下自然宝物面板（lock 0.785 弱命中 +
        # 共用刷新图 0.916）不再单凭模板定类为 treasure；按 V 键打开的
        # 面板走「主动打开键位优先」路径，kind=treasure 由键位保证。
        frame = load_fixture_frame("fixtures/replay/treasure_choice_3.png")
        self.settings.cards = []
        self.med._panel_opened_by_us = "treasure"
        choice = self.med._find_reward_choice(frame)
        self.assertIsNotNone(choice)
        kind, hit = choice
        self.assertEqual(kind, "treasure")
        self.assertTrue(
            hit.name.startswith("rarity_") or "hide" in hit.name.lower() or "giveup" in hit.name.lower(),
            f"无偏好时应收口到品质色或关闭/放弃，实际 {hit.name}",
        )
        if hit.name.startswith("rarity_"):
            self.assertAlmostEqual(hit.x / frame.width, 0.348, delta=0.05)
            self.assertAlmostEqual(hit.y / frame.height, 0.300, delta=0.05)
            # 技能左槽中心约 0.354/0.42；品质色采样中心 y=0.300，不得落到技能点击中心
            self.assertLess(abs(hit.y / frame.height - 0.300), abs(hit.y / frame.height - 0.42))

    def test_choice_panel_giveup_not_treated_as_fail(self):
        # S0 ①：实机 2026-08-09 局内选择面板"放弃"按钮与 giveUp 模板同源（0.945 命中）
        # → 旧版经 fail 场景误判失败。S0 把 giveUp 移出 STRONG_FAIL、独立为 giveup 场景：
        # giveUp+面板锚点 → AMBIGUOUS_GIVEUP，非失败，继续 panel FSM。
        f3 = load_fixture_frame("fixtures/replay/skill_choice_3.png")
        f3.hwnd = 10001
        self.med.set_phase(Phase.MAIN_LINE, "choice panel fail guard")
        self.assertIsNotNone(self.med._selection_anchor(f3))
        self.assertIsNone(self.med.find_scene(f3, "fail"), "S0：giveUp 已移出 STRONG_FAIL（fail）模板集")
        self.assertIsNotNone(self.med.find_scene(f3, "giveup"), "giveUp 作为独立 giveup 场景仍可加载")
        with patch.object(self.med, "_capture_best", return_value=f3), \
             patch.object(self.med, "_post_game_state", return_value=None), \
             patch.object(self.med.executor, "click") as mock_click, \
             patch.object(self.med.executor, "right_click") as mock_rc:
            action = self.med.tick()
            self.assertEqual(action, shuabao.loop_action.LoopAction.Continue)
            self.assertEqual(self.med.phase, Phase.MAIN_LINE, "giveUp+面板锚点不得进入 fail/QUIT 流程")
            self.assertNotEqual(self.med.phase, Phase.QUIT)
            self.assertIsNone(self.med._recovery_state, "giveUp+面板锚点不得触发恢复")
            # 允许技能选择点击，但绝不允许 fail 恢复链的 giveUp 点击（reason='recover'）
            for call in mock_click.call_args_list:
                args = call.args
                self.assertNotIn("recover", str(args))
            mock_rc.assert_not_called()

    def test_treasure_panel_precedes_generic_longzhu_stop(self):
        frame = load_fixture_frame("fixtures/replay/treasure_choice_3.png")
        frame.hwnd = 10001
        self.med.set_phase(Phase.MAIN_LINE, "treasure longzhu guard")
        # 2026-08-16 L1 裁决：同上——按 V 打开的宝物面板，kind 由键位优先保证；
        # 本测试核心是「面板处理优先于龙珠停手」，不是模板定类本身。
        self.med._panel_opened_by_us = "treasure"
        false_longzhu = MatchResult("longzhu", 0.95, 700, 250, 80, 80, 700, 250)
        with patch.object(self.med, "_post_game_state", return_value=None), \
             patch.object(self.med, "find_scene", return_value=false_longzhu) as scene, \
             patch.object(self.med, "act_click", return_value=True) as click:
            action = self.med._tick_main_line(frame)
        self.assertEqual(action, shuabao.loop_action.LoopAction.Continue)
        self.assertEqual(self.med.phase, Phase.MAIN_LINE)
        scene.assert_not_called()
        click.assert_called_once()
        self.assertTrue(click.call_args.args[1].startswith("treasure"))

    def test_non_skill_choice_materials_never_click_configured_skill(self):
        # A3：bond 硬禁用后无 cards 偏好 → 关闭/隐藏，绝不再品质色乱点；
        # 无论分类如何，绝不点击用户配置的具名技能模板。
        self.settings.skills = ["asj", "dz", "byj", "dcw"]

        f_bond = load_fixture_frame("fixtures/replay/bond_choice_3.png")
        choice = self.med._find_reward_choice(f_bond)
        self.assertIsNotNone(choice)
        kind, hit = choice
        self.assertEqual(kind, "bond", "bond 面板必须分类为 bond，不得当作技能")
        self.assertFalse(hit.name.startswith("rarity_"), f"硬禁用后不得品质色旁路，实际 {hit.name}")
        self.assertNotIn(Path(hit.name).stem, self.settings.skills)

        f_treasure = load_fixture_frame("fixtures/replay/treasure_choice_3.png")
        choice = self.med._find_reward_choice(f_treasure)
        if choice is not None:
            self.assertNotIn(choice[1].name, self.settings.skills)

        f_black = load_fixture_frame("fixtures/replay/black_merchant_card_strip.png")
        choice = self.med._find_reward_choice(f_black)
        if choice is not None:
            self.assertNotIn(choice[1].name, self.settings.skills)


if __name__ == "__main__":
    unittest.main()
