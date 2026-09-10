from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.loop_action import LoopAction
from shuabao.mediator import Mediator, PanelState, Phase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.stage_selector import StageId, StageRow


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
            # 本文件验证观察模式契约（OBSERVE incident 只记录不终止）；
            # 1d8f101 把 dry_run 默认翻成 False，显式钉回测试出生时的模式。
            dry_run=True,
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
        # 本用例验证“退出后回同房并开第二局”，不重复覆盖已经由专项测试
        # 验证的 8 张存档挑战卡。将游标置尾，保留正式关闭面板→NPC hub 链。
        self.med._archive_challenge_index = len(self.med._ARCHIVE_CHALLENGE_NAMES)
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
        self.assertEqual(1, self.med.game_count)
        self.assertFalse(self.med._awaiting_room_return)
        # G0 contract #7：同房返回证明完成后进入 LeaveOldRoom episode，
        # 等待既有语义控件请求离房，fresh room-list authority 才进 PLATFORM_MAP。
        self.assertTrue(self.med._room_leave_pending)
        self.assertEqual(Phase.PREPARE, self.med.phase)

        # 同房 room 帧无可信 room-list 权威：episode 保持零输入观察。
        # （room_start 仍可见 → GO_HOME 语义控件命中时仅发一次 request）
        self._assert_one_input_at_most(lambda: self.med._tick_l0(room))
        self.assertTrue(self.med._room_leave_pending)
        self.assertEqual(Phase.PREPARE, self.med.phase)

        self.assertEqual(
            [
                "ContinueGame",
                "CloseArchivePanel",
                "QuitGame-open-confirm",
                "QuitGame-confirm",
                "LeaveOldRoom",
            ],
            [reason for reason, _ in self.actions],
        )
        self.assertNotIn("CreateRoom-open", [reason for reason, _ in self.actions])
        self.assertNotIn("RoomStart", [reason for reason, _ in self.actions])

    def test_unknown_choice_panel_is_bounded_instead_of_waiting_forever(self):
        # 57d40ce 后语义：未知选择面板保持零输入等待，超过 10s 才 Fail-Closed
        # ERROR（不再盲点隐藏按钮）。用假时钟推进验证 10s 上界与零输入。
        # P0-3：自然面板需同类型锚点连续 2 帧才进入面板处理——首帧只建立候选
        # （零输入），第二帧才进入 ACTIVE 起算 unknown 计时。
        # R8-REVIEW：本场景用 skill 面板 fixture（card_hide 不命中、无自然关闭
        # 权）——bond 面板（card_hide 0.85 命中）现走安全关闭而非超时（另测）。
        from tests.test_scenario_replay import FakeClock

        clock = FakeClock(start=100.0)
        self.med.set_phase(Phase.MAIN_LINE, "unknown choice replay")
        frame = load_frame("fixtures/replay/skill_choice_3.png")

        with clock.install(), \
                patch.object(self.med, "_post_game_state", return_value=None), \
                patch.object(self.med, "find_scene", return_value=None), \
                patch.object(self.med, "_find_reward_choice", return_value=None):
            for i in range(4):
                clock.set(100.0 + float(i + 1) * 4.0)  # 104（候选）/ 108（确认→ACTIVE）/ 112 / 116（<10s）
                action = self.med._tick_main_line(frame)
                self.assertEqual(LoopAction.Continue, action)
                self.assertEqual(Phase.MAIN_LINE, self.med.phase)

            clock.set(124.0)  # 确认后 elapsed = 124 - 108 = 16s >= 15s（panel_hard_deadline_s）
            action = self.med._tick_main_line(frame)

        # 20260822 语义：未知面板不再盲选、也不再 ERROR 停机——由面板
        # episode hard deadline（panel_hard_deadline_s，默认 15s）强制 COOLDOWN
        # 脱困，运行继续。
        self.assertEqual(LoopAction.Continue, action)
        self.assertEqual(Phase.MAIN_LINE, self.med.phase)
        self.assertEqual(PanelState.COOLDOWN, self.med._panel_state)
        # 全程零输入：未知面板绝不盲点（旧行为是 3 次 HideUnknownSelection
        # 点击，2026-08-20 一度回归为 3s 品质盲选，均已封死）
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
            # 36s：since=1004，elapsed=32s 超过容忍窗 30s。dry-run 是观察
            # 模式：记录 incident，但不得自行终止或丢失当前 phase。
            clock.set(1036.0)
            action = self.med.tick()
            self.assertEqual(action, LoopAction.Continue)
            self.assertEqual(self.med.phase, Phase.CREATE_ROOM)
            self.assertEqual(self.med._interrupt_reason, "unhealthy frame timeout")


class _EmptyFrameSource:
    def capture_best(self, *a, **k) -> Frame:
        return Frame(bgr=None, left=0, top=0, window_title="", hwnd=None, is_valid=False)


if __name__ == "__main__":
    unittest.main()
