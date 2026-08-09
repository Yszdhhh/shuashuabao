import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gamescript.loop_action import LoopAction
from gamescript.mediator import Mediator, Phase
from gamescript.settings import Settings
from gamescript.vision.capture import Frame
from gamescript.vision.matcher import MatchResult


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

    def test_find_longzhu_in_game_config_key_is_wired(self):
        # 1.4 借鉴项 ②：配置门闩落地（默认 False，零行为改动；LONGZHU 重建后启用）
        default_json_path = ROOT / "config" / "default_settings.json"
        with open(default_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertFalse(data.get("find_longzhu_in_game"))
        self.assertFalse(self.settings.find_longzhu_in_game)
        # 官方映射与 bool 解析
        from gamescript.settings import _OFFICIAL_MAP

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
        frame = create_dummy_frame()

        for scene_key in ("archive", "boss_entry", "longzhu"):
            self.med = Mediator(self.settings, ROOT)
            self.med.set_phase(Phase.MAIN_LINE)

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
