import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gamescript.mediator import LoopAction, Mediator, Phase
from gamescript.settings import Settings
from gamescript.vision.capture import Frame
from gamescript.vision.matcher import MatchResult


def _frame() -> Frame:
    return Frame(np.zeros((900, 1600, 3), dtype=np.uint8), window_title="KK", hwnd=123)


def _hit(name: str, x: int = 700, y: int = 800) -> MatchResult:
    return MatchResult(name, 0.93, x, y, 120, 40, x + 60, y + 20)


class P0ACreateRoomGateTests(unittest.TestCase):
    def setUp(self):
        self.med = Mediator(Settings(auto_create_room=True, dry_run=True), ROOT)
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

    def test_dialog_anchor_confirms_and_preserves_candidate_trace(self):
        self.med._create_room_pending_since = 100.0
        self.med._create_room_next_observe_at = 104.0
        self.med._create_room_flow_deadline = 115.0
        self.med._create_room_attempts = 1
        self.med._create_room_last_candidate = self.med._create_room_candidate_payload(_hit("create_room"))
        confirm = _hit("create_room_confirm", 800, 700)
        p = self._patch_map(confirm=confirm)
        with p[0], p[1], p[2], p[3], patch("gamescript.mediator.time.time", return_value=105.0):
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
        with p[0], p[1], p[2], p[3], patch("gamescript.mediator.time.time", return_value=116.0):
            self.assertEqual(self.med._tick_l0(_frame()), LoopAction.Break)

        self.assertEqual(self.med.phase, Phase.ERROR)
        self.assertEqual(self.med._trace_controls[-1]["state"], "TIMEOUT")

    def test_retry_cap_prevents_fourth_click(self):
        self.med._create_room_flow_deadline = time.time() + 100.0
        self.med._create_room_attempts = 3
        candidate_lookup = MagicMock(return_value=_hit("create_room"))
        p = self._patch_map(candidate=candidate_lookup)
        with p[0], p[1], p[2], p[3], patch.object(self.med, "act_click") as click:
            self.assertEqual(self.med._tick_l0(_frame()), LoopAction.Continue)
        candidate_lookup.assert_not_called()
        click.assert_not_called()

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

    def test_create_confirm_blue_fallback_still_works_on_small_dialog(self):
        # P1-3 正向控制：小窗（584×488）含蓝色确认按钮 + 上方 ≥2 输入框 → 兜底命中。
        import cv2

        image = np.zeros((488, 584, 3), dtype=np.uint8)
        for y in (98, 194):
            cv2.rectangle(image, (203, y), (485, y + 32), (60, 60, 60), -1)
            cv2.rectangle(image, (203, y), (485, y + 32), (180, 180, 180), 2)
        cv2.rectangle(image, (262, 418), (373, 458), (230, 150, 20), -1)
        cv2.rectangle(image, (390, 420), (506, 456), (230, 150, 20), -1)
        with patch.object(self.med, "find_scene", return_value=None):
            hit = self.med._find_create_confirm(Frame(image))
        self.assertIsNotNone(hit)
        self.assertLess(hit.x, 350)


if __name__ == "__main__":
    unittest.main()
