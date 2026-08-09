from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gamescript.loop_action import LoopAction
from gamescript.mediator import Mediator, Phase
from gamescript.settings import Settings
from gamescript.vision.capture import Frame


def load_frame(relative_path: str, title: str = "英雄三国") -> Frame:
    path = ROOT / relative_path
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(path)
    return Frame(image, window_title=title, hwnd=10001)


class TemporalSameRoomLoopTests(unittest.TestCase):
    def setUp(self):
        settings = Settings(
            stage_targets=["1-12"],
            auto_create_room=True,
            new_room_every_times=False,
            query_timeout=30,
        )
        self.med = Mediator(settings, ROOT)
        self.actions: list[tuple[str, tuple[int, int]]] = []
        self.med.act_click = lambda hit, reason="": self.actions.append(
            (reason, hit.center)
        ) or True

    def _assert_one_input_at_most(self, callback):
        before = len(self.actions)
        action = callback()
        self.assertLessEqual(len(self.actions) - before, 1)
        return action

    def test_victory_returns_to_same_room_and_enters_second_main_line(self):
        self.med.set_phase(Phase.MAIN_LINE, "temporal replay start")
        victory = load_frame("fixtures/replay/victory_continue.png")
        archive = load_frame("fixtures/replay/archive_challenge_panel.png")
        hub = load_frame("fixtures/replay/challenge_npc_hub.png")
        exit_page = load_frame("fixtures/live_postgame_20260808/live_exit_button.png")
        exit_confirm = load_frame("fixtures/live_postgame_20260808/live_exit_confirm.png")
        room = load_frame("fixtures/replay/room_waiting_host.png", "KK官方对战平台")
        stage = load_frame("fixtures/live_postgame_20260808/live_stage_select.png")
        main_line = load_frame("fixtures/replay/main_line_auto_on.png")

        self._assert_one_input_at_most(lambda: self.med._tick_main_line(victory))
        self._assert_one_input_at_most(lambda: self.med._tick_main_line(archive))
        self._assert_one_input_at_most(lambda: self.med._tick_main_line(hub))
        self.assertEqual(Phase.QUIT, self.med.phase)

        self._assert_one_input_at_most(lambda: self.med._tick_l1_tail(exit_page))
        self.assertEqual(Phase.NEXT, self.med.phase)
        self._assert_one_input_at_most(lambda: self.med._tick_l1_tail(exit_confirm))
        self.assertEqual(Phase.PREPARE, self.med.phase)
        self.assertTrue(self.med._awaiting_room_return)
        self.assertEqual(0, self.med.game_count)

        self._assert_one_input_at_most(lambda: self.med._tick_l0(room))
        self.assertEqual(Phase.ROOM_WAITING, self.med.phase)
        self.assertEqual(1, self.med.game_count)
        self.assertFalse(self.med._awaiting_room_return)

        self._assert_one_input_at_most(lambda: self.med._tick_l0(room))
        self.assertEqual(Phase.ROOM_STARTING, self.med.phase)
        self._assert_one_input_at_most(lambda: self.med._tick_l0(stage))
        self.assertEqual(Phase.STAGE_SELECT, self.med.phase)
        self._assert_one_input_at_most(lambda: self.med._tick_l0(stage))
        self.med._stage_click_cooldown_until = 0
        with patch("gamescript.mediator.verify_stage_selection", return_value=True):
            self._assert_one_input_at_most(lambda: self.med._tick_l0(stage))
        self.assertEqual(Phase.STAGE_STARTING, self.med.phase)
        # startChallenge 子状态机：局内锚点需连续 2 帧确认，
        # 首帧仅进入 VERIFY_INGAME（phase 保持 STAGE_STARTING），第二帧推进 MAIN_LINE
        self._assert_one_input_at_most(lambda: self.med._tick_l0(main_line))
        self.assertEqual(Phase.STAGE_STARTING, self.med.phase)
        self._assert_one_input_at_most(lambda: self.med._tick_l0(main_line))
        self.assertEqual(Phase.MAIN_LINE, self.med.phase)

        self.assertEqual(
            [
                "ContinueGame",
                "CloseArchivePanel",
                "QuitGame-open-confirm",
                "QuitGame-confirm",
                "RoomStart",
                "SelectStage-target",
                "StageStart",
            ],
            [reason for reason, _ in self.actions],
        )
        self.assertNotIn("CreateRoom-open", [reason for reason, _ in self.actions])

    def test_unknown_choice_panel_is_bounded_instead_of_waiting_forever(self):
        # 57d40ce 后语义：未知选择面板保持零输入等待，超过 10s 才 Fail-Closed
        # ERROR（不再盲点隐藏按钮）。用假时钟推进验证 10s 上界与零输入。
        from tests.test_scenario_replay import FakeClock

        clock = FakeClock(start=100.0)
        self.med.set_phase(Phase.MAIN_LINE, "unknown choice replay")
        frame = load_frame("fixtures/replay/bond_choice_3.png")

        with clock.install(), \
                patch.object(self.med, "_post_game_state", return_value=None), \
                patch.object(self.med, "find_scene", return_value=None), \
                patch.object(self.med, "_find_reward_choice", return_value=None):
            for i in range(3):
                clock.set(100.0 + float(i + 1) * 4.0)  # 104 / 108（<10s）
                action = self.med._tick_main_line(frame)
                self.assertEqual(LoopAction.Continue, action)
                self.assertEqual(Phase.MAIN_LINE, self.med.phase)

            clock.set(116.0)  # elapsed = 116 - 104 = 12s >= 10s
            action = self.med._tick_main_line(frame)

        self.assertEqual(LoopAction.Break, action)
        self.assertEqual(Phase.ERROR, self.med.phase)
        # 全程零输入：未知面板绝不盲点（旧行为是 3 次 HideUnknownSelection 点击）
        self.assertEqual([], self.actions)


    def test_create_room_window_blip_does_not_error_early(self):
        # 实机 2026-08-09：dry-run 观察模式下建房弹窗被手动关闭后窗口短暂不可见，
        # 15s 即 ERROR 太激进。CREATE_ROOM 无窗口容忍应 ≥30s（与 BOOT 同窗）。
        from tests.test_scenario_replay import FakeClock

        clock = FakeClock(start=1000.0)
        self.med.settings.query_timeout = 30  # 容忍窗 = max(30, min(30,60)) = 30s
        self.med.set_phase(Phase.CREATE_ROOM, "window blip test")
        src = _EmptyFrameSource()
        self.med._capture_best = src.capture_best
        with clock.install():
            # 20s：仍在容忍窗内 → 不 ERROR
            for i in range(5):
                clock.set(1000.0 + float(i + 1) * 4.0)
                action = self.med.tick()
                self.assertEqual(LoopAction.Continue, action)
                self.assertNotEqual(self.med.phase, Phase.ERROR, f"tick {i+1} 不应提前 ERROR")
            # 36s：since=1004，elapsed=32s 超过容忍窗 30s → Fail-Closed ERROR
            clock.set(1036.0)
            action = self.med.tick()
            self.assertEqual(self.med.phase, Phase.ERROR)


class _EmptyFrameSource:
    def capture_best(self, *a, **k) -> Frame:
        return Frame(bgr=None, left=0, top=0, window_title="", hwnd=None, is_valid=False)


if __name__ == "__main__":
    unittest.main()
