import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.mediator import LoopAction, Mediator, Phase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult


def _frame() -> Frame:
    return Frame(np.zeros((900, 1600, 3), dtype=np.uint8), window_title="KK", hwnd=123)


def _hit(name: str, x: int = 700, y: int = 800) -> MatchResult:
    return MatchResult(name, 0.93, x, y, 120, 40, x + 60, y + 20)


class P0ACreateRoomGateTests(unittest.TestCase):
    def setUp(self):
        # 真机创房门闩用 dry_run=False；学习模式有独立用例。
        self.med = Mediator(Settings(auto_create_room=True, dry_run=False), ROOT)
        self.med.set_phase(Phase.PLATFORM_MAP, "test")

    def _patch_map(self, *, confirm=None, candidate=None):
        return (
            patch.object(self.med, "_detect_context", return_value="PLATFORM_MAP"),
            patch.object(self.med, "_find_room_start", return_value=None),
            patch.object(self.med, "_find_create_confirm", return_value=confirm),
            patch.object(self.med, "_find_map_create_room", return_value=candidate),
        )

    def test_click_is_only_open_request_until_dialog_anchor(self):
        candidate = _hit("create_room")
        click = MagicMock(return_value=True)
        p = self._patch_map(candidate=candidate)
        with p[0], p[1], p[2], p[3], patch.object(self.med, "act_click", click):
            self.assertEqual(self.med._tick_l0(_frame()), LoopAction.Continue)
            self.assertEqual(self.med.phase, Phase.PLATFORM_MAP)
            self.assertEqual(self.med._create_room_attempts, 1)
            self.assertIsNotNone(self.med._create_room_pending_since)
            click.assert_called_once_with(candidate, "CreateRoom-open")
            self.assertEqual(self.med._trace_controls[-1]["state"], "OPEN_REQUESTED")
            self.assertEqual(self.med._trace_controls[-1]["candidate"]["name"], "create_room")

        # The settle window is observe-only; a second candidate cannot cause
        # another input before the dedicated dialog confirmation deadline.
        candidate_lookup = MagicMock(return_value=candidate)
        p = self._patch_map(candidate=candidate_lookup)
        with p[0], p[1], p[2], p[3], patch.object(self.med, "act_click", click):
            self.med._tick_l0(_frame())
        candidate_lookup.assert_not_called()
        self.assertEqual(click.call_count, 1)

    def test_learning_mode_records_intent_without_pending_dialog_wait(self):
        """学习模式：记录创建房间意图，不进入等弹窗 / 不烧 attempts。"""
        self.med.settings.dry_run = True
        candidate = _hit("create_room")
        click = MagicMock(return_value=True)
        p = self._patch_map(candidate=candidate)
        with (
            p[0],
            p[1],
            p[2],
            p[3],
            patch.object(self.med, "act_click", click),
            patch("shuabao.mediator.append_learning_observation") as obs,
        ):
            self.assertEqual(self.med._tick_l0(_frame()), LoopAction.Continue)
        self.assertEqual(self.med.phase, Phase.PLATFORM_MAP)
        self.assertEqual(self.med._create_room_attempts, 0)
        self.assertIsNone(self.med._create_room_pending_since)
        self.assertIsNone(self.med._create_room_flow_deadline)
        self.assertIsNotNone(self.med._create_room_next_observe_at)
        self.assertEqual(self.med._trace_controls[-1]["state"], "LEARN_OBSERVE")
        click.assert_called_once_with(candidate, "CreateRoom-open")
        obs.assert_called_once()
        payload = obs.call_args.args[0]
        self.assertEqual(payload["event"], "create_room_intent")
        self.assertEqual(payload["decision"]["action"], "WOULD_CLICK")

    def test_dialog_anchor_confirms_and_preserves_candidate_trace(self):
        self.med._create_room_pending_since = 100.0
        self.med._create_room_next_observe_at = 104.0
        self.med._create_room_flow_deadline = 115.0
        self.med._create_room_attempts = 1
        self.med._create_room_last_candidate = self.med._create_room_candidate_payload(_hit("create_room"))
        confirm = _hit("create_room_confirm", 800, 700)
        p = self._patch_map(confirm=confirm)
        with p[0], p[1], p[2], p[3], patch("shuabao.mediator.time.time", return_value=105.0):
            self.med._tick_l0(_frame())

        self.assertEqual(self.med.phase, Phase.CREATE_ROOM)
        event = self.med._trace_controls[-1]
        self.assertEqual(event["state"], "CONFIRMED")
        self.assertTrue(event["post_confirm"])
        self.assertEqual(event["candidate"]["name"], "create_room")

    def test_existing_room_anchor_cannot_bypass_pending_dialog_gate(self):
        self.med._create_room_pending_since = time.time()
        self.med._create_room_next_observe_at = time.time() + 4.0
        p = (
            patch.object(self.med, "_detect_context", return_value="PLATFORM_MAP"),
            patch.object(self.med, "_find_room_start", return_value=_hit("kk_start")),
            patch.object(self.med, "_find_create_confirm", return_value=None),
            patch.object(self.med, "_find_map_create_room", return_value=None),
        )
        with p[0], p[1], p[2], p[3]:
            self.med._tick_l0(_frame())

        self.assertEqual(self.med.phase, Phase.PLATFORM_MAP)

    def test_missing_dialog_fails_closed_after_bounded_budget(self):
        self.med._create_room_pending_since = 100.0
        self.med._create_room_next_observe_at = 104.0
        self.med._create_room_flow_deadline = 115.0
        self.med._create_room_attempts = 3
        p = self._patch_map()
        with p[0], p[1], p[2], p[3], patch("shuabao.mediator.time.time", return_value=116.0):
            self.assertEqual(self.med._tick_l0(_frame()), LoopAction.Break)

        self.assertEqual(self.med.phase, Phase.ERROR)
        self.assertEqual(self.med._trace_controls[-1]["state"], "TIMEOUT")

    def test_create_room_retries_after_confirm_window_without_dialog(self):
        candidate = _hit("create_room")
        click = MagicMock(return_value=True)
        t0 = 1000.0
        p = self._patch_map(candidate=candidate)
        with p[0], p[1], p[2], p[3], patch.object(self.med, "act_click", click), patch(
            "shuabao.mediator.time.time", return_value=t0
        ):
            self.assertEqual(self.med._tick_l0(_frame()), LoopAction.Continue)
        self.assertEqual(click.call_count, 1)
        self.assertFalse(self.med._create_room_opened_ok)
        self.assertGreaterEqual(
            self.med._create_room_flow_deadline or 0,
            t0 + 30.0,
        )

        later = t0 + Mediator._CREATE_ROOM_CONFIRM_WINDOW_S + 0.1
        p = self._patch_map(candidate=candidate)
        with p[0], p[1], p[2], p[3], patch.object(self.med, "act_click", click), patch(
            "shuabao.mediator.time.time", return_value=later
        ):
            self.assertEqual(self.med._tick_l0(_frame()), LoopAction.Continue)
        self.assertEqual(click.call_count, 2)
        self.assertEqual(self.med.phase, Phase.PLATFORM_MAP)
        self.assertEqual(self.med._create_room_attempts, 2)

    def test_create_room_retry_count_is_telemetry_not_terminal(self):
        self.med._create_room_flow_deadline = time.time() + 100.0
        self.med._create_room_attempts = 3
        candidate = _hit("create_room")
        p = self._patch_map(candidate=candidate)
        with p[0], p[1], p[2], p[3], patch.object(
            self.med, "act_click", return_value=True
        ) as click:
            self.assertEqual(self.med._tick_l0(_frame()), LoopAction.Continue)
        click.assert_called_once_with(candidate, "CreateRoom-open")
        self.assertEqual(self.med._create_room_attempts, 4)

    def test_create_confirm_blue_fallback_never_fires_on_large_window(self):
        # P1-3/P4（LOBBY_AUDIT §3 #2）：建房弹窗确认的蓝色兜底只在小窗
        # （≤800×700）授权；1600×900 / 1328×945 大窗即使含蓝色按钮也零蓝色点击
        # （负向断言，防止大窗上颜色兜底复活）。
        import cv2

        for w, h in ((1600, 900), (1328, 945)):
            image = np.zeros((h, w, 3), dtype=np.uint8)
            cv2.rectangle(
                image,
                (int(w * 0.45), int(h * 0.80)),
                (int(w * 0.55), int(h * 0.86)),
                (230, 150, 20),
                -1,
            )
            with patch.object(self.med, "find_scene", return_value=None):
                self.assertIsNone(
                    self.med._find_create_confirm(Frame(image)),
                    f"大窗 {w}x{h} 不得走蓝色兜底",
                )

    def test_create_confirm_never_uses_blue_fallback_on_small_or_large_windows(self):
        # P0-3: 无论大窗还是小窗，即便含 2 个蓝色按钮 + 2 个输入框，未匹配到场景模板均不得授权点击。
        import cv2

        # 1. 小窗负样本 (584x488)
        small_image = np.zeros((488, 584, 3), dtype=np.uint8)
        for y in (98, 194):
            cv2.rectangle(small_image, (203, y), (485, y + 32), (60, 60, 60), -1)
            cv2.rectangle(small_image, (203, y), (485, y + 32), (180, 180, 180), 2)
        cv2.rectangle(small_image, (262, 418), (373, 458), (230, 150, 20), -1)
        cv2.rectangle(small_image, (390, 420), (506, 456), (230, 150, 20), -1)
        with patch.object(self.med, "find_scene", return_value=None):
            self.assertIsNone(self.med._find_create_confirm(Frame(small_image)))

        # 2. 内嵌大窗负样本 (1328x945)
        large_image = np.zeros((945, 1328, 3), dtype=np.uint8)
        for y in (325, 421):
            cv2.rectangle(large_image, (574, y), (856, y + 32), (60, 60, 60), -1)
            cv2.rectangle(large_image, (574, y), (856, y + 32), (180, 180, 180), 2)
        cv2.rectangle(large_image, (633, 645), (745, 685), (230, 150, 20), -1)
        cv2.rectangle(large_image, (761, 647), (877, 683), (230, 150, 20), -1)
        with patch.object(self.med, "find_scene", return_value=None):
            self.assertIsNone(self.med._find_create_confirm(Frame(large_image)))
    def test_embedded_single_blue_button_is_not_create_dialog_authority(self):
        import cv2

        image = np.zeros((945, 1328, 3), dtype=np.uint8)
        for y in (325, 421):
            cv2.rectangle(image, (574, y), (856, y + 32), (60, 60, 60), -1)
            cv2.rectangle(image, (574, y), (856, y + 32), (180, 180, 180), 2)
        cv2.rectangle(image, (633, 645), (745, 685), (230, 150, 20), -1)

        with patch.object(self.med, "find_scene", return_value=None):
            self.assertIsNone(self.med._find_create_confirm(Frame(image)))

    def test_pending_create_request_prefers_separate_dialog_hwnd(self):
        """A healthy sticky parent must not starve KK's separate dialog HWND."""
        from shuabao.vision.capture import WindowTarget

        parent = WindowTarget(
            hwnd=123,
            title="KK",
            left=0,
            top=0,
            width=1328,
            height=945,
            client_left=0,
            client_top=0,
            client_width=1328,
            client_height=945,
            role="l0",
        )
        dialog = WindowTarget(
            hwnd=456,
            title="KK",
            left=300,
            top=200,
            width=584,
            height=488,
            client_left=300,
            client_top=200,
            client_width=584,
            client_height=488,
            role="l0",
        )
        self.med._create_room_pending_since = time.time()
        sticky = _frame()
        form = Frame(np.zeros((488, 584, 3), dtype=np.uint8), window_title="KK", hwnd=456)
        self.med._last_frame = sticky
        self.med._last_capture_role = "l0"

        def capture_one(target):
            return form if target.hwnd == 456 else sticky

        def find_confirm(frame):
            return _hit("create_room_confirm") if frame.hwnd == 456 else None

        with patch("shuabao.mediator.find_window_targets", return_value=[parent, dialog]), \
                patch("shuabao.mediator.capture_target", side_effect=capture_one) as capture_call, \
                patch.object(self.med, "_find_create_confirm", side_effect=find_confirm):
            self.assertIs(self.med._capture_best("KK", "l0"), form)
        self.assertEqual([call.args[0].hwnd for call in capture_call.call_args_list], [123, 456])


    def test_create_room_phase_does_not_starve_room_window_after_dialog_closes(self):
        """After Create, room HWND is smaller than the map; max(size) must not win.

        r10 live regression: create_dialog_probe fell back to largest window
        (1328x945 map) and never saw room_start on 1224x904, hanging until
        create dialog confirmation timeout.
        """
        from shuabao.vision.capture import WindowTarget

        parent = WindowTarget(
            hwnd=123,
            title="KK",
            left=0,
            top=0,
            width=1328,
            height=945,
            client_left=0,
            client_top=0,
            client_width=1328,
            client_height=945,
            role="l0",
        )
        room = WindowTarget(
            hwnd=789,
            title="KK",
            left=50,
            top=50,
            width=1224,
            height=904,
            client_left=50,
            client_top=50,
            client_width=1224,
            client_height=904,
            role="l0",
        )
        self.med.phase = Phase.CREATE_ROOM
        map_frame = Frame(
            np.zeros((945, 1328, 3), dtype=np.uint8),
            window_title="KK",
            hwnd=123,
        )
        room_frame = Frame(
            np.zeros((904, 1224, 3), dtype=np.uint8),
            window_title="KK",
            hwnd=789,
        )
        # Last capture was the dialog; it is gone now.
        self.med._last_frame = Frame(
            np.zeros((488, 584, 3), dtype=np.uint8),
            window_title="KK",
            hwnd=456,
        )
        self.med._last_capture_role = "l0"

        def capture_one(target):
            return room_frame if target.hwnd == 789 else map_frame

        def find_room_start(frame):
            return _hit("kk_start") if frame.hwnd == 789 else None

        with patch("shuabao.mediator.find_window_targets", return_value=[parent, room]), \
                patch("shuabao.mediator.capture_target", side_effect=capture_one), \
                patch.object(self.med, "_find_create_confirm", return_value=None), \
                patch.object(self.med, "_find_room_start", side_effect=find_room_start):
            chosen = self.med._capture_best("KK", "l0")
        self.assertIs(chosen, room_frame)
        self.assertEqual(chosen.hwnd, 789)



if __name__ == "__main__":
    unittest.main()
