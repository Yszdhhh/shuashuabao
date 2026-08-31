import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.loop_action import LoopAction
from shuabao.mediator import Mediator, Phase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult


def create_dummy_frame() -> Frame:
    img = np.zeros((900, 1600, 3), dtype=np.uint8)
    return Frame(img, window_title="英雄三国KK", hwnd=10001)


class P0C1FixesTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings()
        self.med = Mediator(self.settings, ROOT)

    def test_default_settings_auto_secret_realm_is_false(self):
        default_json_path = ROOT / "config" / "default_settings.json"
        with open(default_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertFalse(data.get("auto_secret_realm"))
        self.assertFalse(self.settings.auto_secret_realm)

    def test_default_settings_enable_the_packaged_ocr_worker(self):
        default_json_path = ROOT / "config" / "default_settings.json"
        with open(default_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual("live", data.get("ocr_mode"))
        self.assertEqual("live", self.settings.ocr_mode)

    def test_find_longzhu_in_game_config_key_is_wired(self):
        # 1.4 借鉴项 ②：配置门闩落地（默认 False，零行为改动；LONGZHU 重建后启用）
        default_json_path = ROOT / "config" / "default_settings.json"
        with open(default_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertFalse(data.get("find_longzhu_in_game"))
        self.assertFalse(self.settings.find_longzhu_in_game)
        # 官方映射与 bool 解析
        from shuabao.settings import _OFFICIAL_MAP

        self.assertEqual(_OFFICIAL_MAP["FindLongzhuInGame"], "find_longzhu_in_game")
        # 加载/保存往返：True 可写回并重新加载
        self.settings.find_longzhu_in_game = True
        self.assertTrue(self.settings.find_longzhu_in_game)

    def test_quit_next_use_only_dedicated_anchors(self):
        self.settings.auto_secret_realm = True
        frame = create_dummy_frame()

        with patch.object(self.med, "click_scene") as mock_click_scene, \
             patch.object(self.med, "act_click") as mock_act_click, \
             patch.object(self.med.executor, "click") as mock_exec_click:

            for phase in (Phase.QUIT, Phase.NEXT):
                self.med.set_phase(phase)
                action = self.med._tick_l1_tail(frame)

                self.assertEqual(action, LoopAction.Continue)
                self.assertEqual(self.med.game_count, 0)
                mock_click_scene.assert_not_called()
                mock_act_click.assert_not_called()
                mock_exec_click.assert_not_called()

    def test_main_line_unverified_entries_fail_closed(self):
        """S0 ⑧ 阶段门控后：archive 只在局尾窗口检查（Fail-Closed 保留）；
        boss_entry 20260822 起是 Boss 提前挑战入口——未配置挑战 Boss 时零输入
        等待（不停机、零输入），配置后点击；longzhu 色相检查移至 LONGZHU 阶段。"""
        frame = create_dummy_frame()

        for scene_key in ("archive",):
            self.med = Mediator(self.settings, ROOT)
            self.med.set_phase(Phase.MAIN_LINE)
            self.med._post_game_pending = True  # 局尾窗口（战后流程进行中）

            def mock_find_scene(f, sk, threshold=None):
                if sk == scene_key:
                    return MatchResult(name=scene_key, score=0.95, x=100, y=100, w=50, h=50, screen_x=100, screen_y=100)
                return None

            with patch.object(self.med, "find_scene", side_effect=mock_find_scene), \
                 patch.object(self.med, "_selection_anchor", return_value=None), \
                 patch.object(self.med, "_ensure_challenge_buttons", return_value=False), \
                 patch.object(self.med, "act_click") as mock_act_click, \
                 patch.object(self.med, "click_scene") as mock_click_scene, \
                 patch.object(self.med, "act_right_click") as mock_act_right_click, \
                 patch.object(self.med, "act_key") as mock_act_key, \
                 patch.object(self.med.executor, "click") as mock_exec_click:

                action = self.med._tick_main_line(frame)

                self.assertEqual(self.med.phase, Phase.ERROR)
                self.assertTrue(self.med.stop_signal.is_set())
                mock_act_click.assert_not_called()
                mock_click_scene.assert_not_called()
                mock_act_right_click.assert_not_called()
                mock_act_key.assert_not_called()
                mock_exec_click.assert_not_called()

        # boss_entry：未配置挑战 Boss → 零输入等待（不 ERROR、零输入）
        self.med = Mediator(self.settings, ROOT)
        self.med.set_phase(Phase.MAIN_LINE)
        self.med._post_game_pending = True

        def mock_find_scene_boss(f, sk, threshold=None):
            if sk == "boss_entry":
                return MatchResult(name="boss_entry", score=0.95, x=100, y=100, w=50, h=50, screen_x=100, screen_y=100)
            return None

        with patch.object(self.med, "find_scene", side_effect=mock_find_scene_boss), \
             patch.object(self.med, "_selection_anchor", return_value=None), \
             patch.object(self.med, "_ensure_challenge_buttons", return_value=False), \
             patch.object(self.med, "act_click") as mock_act_click, \
             patch.object(self.med.executor, "click") as mock_exec_click:
            action = self.med._tick_main_line(frame)
            self.assertEqual(action, LoopAction.Continue)
            self.assertEqual(self.med.phase, Phase.MAIN_LINE)
            mock_act_click.assert_not_called()
            mock_exec_click.assert_not_called()

        # boss_entry：已配置挑战 Boss → 点击配置 Boss 模板（BossConfigured）
        self.med = Mediator(replace(self.settings, cjb_boss="04克雷什之父"), ROOT)
        self.med.set_phase(Phase.MAIN_LINE)
        self.med._post_game_pending = True
        boss_hit = MatchResult(name="04克雷什之父", score=0.95, x=800, y=400, w=60, h=60, screen_x=800, screen_y=400)

        def find_boss_only(f, names, **kw):
            for n in names or ():
                if "克雷什之父" in str(n):
                    return boss_hit
            return None

        with patch.object(self.med, "find_scene", side_effect=mock_find_scene_boss), \
             patch.object(self.med, "_selection_anchor", return_value=None), \
             patch.object(self.med, "_ensure_challenge_buttons", return_value=False), \
             patch.object(self.med, "find", side_effect=find_boss_only), \
             patch.object(self.med, "act_click", return_value=True) as mock_act_click:
            action = self.med._tick_main_line(frame)
            self.assertEqual(action, LoopAction.Continue)
            self.assertEqual(self.med.phase, Phase.MAIN_LINE)
            mock_act_click.assert_called_once()
            self.assertEqual(mock_act_click.call_args[0][1], "BossConfigured")

    def test_missing_configured_boss_uses_last_visible_template_fallback(self):
        self.med = Mediator(replace(self.settings, cjb_boss="不存在的 Boss"), ROOT)
        frame = create_dummy_frame()
        fallback = MatchResult(name="20鲁克玛", score=0.95, x=800, y=400, w=60, h=60, screen_x=800, screen_y=400)
        self.med._boss_challenge_attempts = 2
        with patch.object(self.med, "find", return_value=None), \
             patch.object(self.med, "_last_visible_boss_hit", return_value=fallback), \
             patch.object(self.med, "act_click", return_value=True) as click:
            self.assertEqual(self.med._maybe_challenge_configured_boss(frame, 100.0), LoopAction.Continue)
        self.assertEqual(click.call_args.args[1], "BossLastVisibleFallback")

        # longzhu：仅在 LONGZHU 阶段检查并 Fail-Closed（MAIN_LINE 不再每 tick 扫）
        self.med = Mediator(self.settings, ROOT)
        self.med.set_phase(Phase.LONGZHU)

        def mock_find_scene_lz(f, sk, threshold=None):
            if sk == "longzhu":
                return MatchResult(name="longzhu", score=0.95, x=700, y=250, w=50, h=50, screen_x=700, screen_y=250)
            return None

        with patch.object(self.med, "find_scene", side_effect=mock_find_scene_lz), \
             patch.object(self.med, "act_click") as mock_act_click, \
             patch.object(self.med.executor, "click") as mock_exec_click:
            action = self.med._tick_l1_tail(frame)

        self.assertEqual(action, LoopAction.Break)
        self.assertEqual(self.med.phase, Phase.ERROR)
        self.assertTrue(self.med.stop_signal.is_set())
        mock_act_click.assert_not_called()
        mock_exec_click.assert_not_called()

    def test_l1_tail_legacy_phases_fail_closed(self):
        frame = create_dummy_frame()

        for phase in (Phase.EARLY_CHALLENGE, Phase.ANCHOR_BOSS, Phase.LONGZHU):
            self.med = Mediator(self.settings, ROOT)
            self.med.set_phase(phase)

            with patch.object(self.med, "act_click") as mock_act_click, \
                 patch.object(self.med, "click_scene") as mock_click_scene, \
                 patch.object(self.med, "act_right_click") as mock_act_right_click, \
                 patch.object(self.med, "act_key") as mock_act_key, \
                 patch.object(self.med.executor, "click") as mock_exec_click:

                action = self.med._tick_l1_tail(frame)

                self.assertEqual(self.med.phase, Phase.ERROR)
                self.assertTrue(self.med.stop_signal.is_set())
                mock_act_click.assert_not_called()
                mock_click_scene.assert_not_called()
                mock_act_right_click.assert_not_called()
                mock_act_key.assert_not_called()
                mock_exec_click.assert_not_called()


if __name__ == "__main__":
    unittest.main()
