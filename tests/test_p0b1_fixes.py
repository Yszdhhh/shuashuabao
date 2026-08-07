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

from gamescript.input.keyboard_mouse import ActionResult, InputExecutor
from gamescript.mediator import LoopAction, Mediator, Phase
from gamescript.settings import Settings
from gamescript.stop_signal import StopSignal
from gamescript.vision.capture import Frame
from run_replay import main as replay_main, run_replay_fixture


def load_fixture_frame(rel_path: str, title: str = "英雄三国KK") -> Frame:
    path = ROOT / rel_path
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    return Frame(img, window_title=title, hwnd=10001)


class P0B1FixesTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings()
        self.med = Mediator(self.settings, ROOT)

    def test_room_waiting_host_detection_and_candidate(self):
        frame = load_fixture_frame("fixtures/replay/room_waiting_host.png", title="KK")
        ctx = self.med._detect_context(frame, role="l0")
        self.assertEqual(ctx, "ROOM_WAITING")

        room_start = self.med._find_room_start(frame)
        self.assertIsNotNone(room_start)
        self.assertGreater(room_start.score, 0.90)

        fixture = {
            "fixture_id": "room_waiting_host",
            "file_path": "fixtures/replay/room_waiting_host.png",
            "resolution": [1040, 719],
            "window_title": "KK",
            "page": "ROOM_WAITING",
            "expected_state": "ROOM_WAITING",
            "expected_action": "RoomStart",
            "required": True,
        }
        res = run_replay_fixture(fixture, self.med, ROOT)
        self.assertEqual(res.status, "PASS")
        self.assertEqual(res.actual_state, "ROOM_WAITING")
        self.assertIsNotNone(res.click_point)
        self.assertEqual(res.forbidden_click_count, 0)

    def test_main_line_images_not_stage_select(self):
        f_off = load_fixture_frame("fixtures/replay/main_line_auto_off.png")
        f_on = load_fixture_frame("fixtures/replay/main_line_auto_on.png")

        self.assertNotEqual(self.med._detect_context(f_off), "STAGE_SELECT")
        self.assertNotEqual(self.med._detect_context(f_on), "STAGE_SELECT")

        self.assertEqual(self.med._detect_context(f_off), "MAIN_LINE")
        self.assertEqual(self.med._detect_context(f_on), "MAIN_LINE")

    def test_challenge_is_auto_evaluations(self):
        f_off = load_fixture_frame("fixtures/replay/main_line_auto_off.png")
        f_on = load_fixture_frame("fixtures/replay/main_line_auto_on.png")

        for sc in ("coin_challenge", "wood_challenge", "experience_challenge", "treasure_challenge"):
            found_off = self.med._find_challenge_button(f_off, sc)
            self.assertIsNotNone(found_off, f"Failed to find {sc} on auto_off")
            lbl_off, _ = found_off
            self.assertFalse(self.med._challenge_is_auto(f_off, lbl_off), f"{sc} should be False on auto_off")

            found_on = self.med._find_challenge_button(f_on, sc)
            self.assertIsNotNone(found_on, f"Failed to find {sc} on auto_on")
            lbl_on, _ = found_on
            self.assertTrue(self.med._challenge_is_auto(f_on, lbl_on), f"{sc} should be True on auto_on")

    def test_auto_off_right_click_candidate_and_auto_on_no_action(self):
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
        res_off = run_replay_fixture(fix_off, self.med, ROOT)
        self.assertEqual(res_off.status, "PASS")
        self.assertEqual(res_off.actual_state, "MAIN_LINE")
        self.assertIsNotNone(res_off.click_point)

        fix_on = {
            "fixture_id": "main_line_auto_on",
            "file_path": "fixtures/replay/main_line_auto_on.png",
            "resolution": [1609, 932],
            "window_title": "英雄三国KK",
            "page": "MAIN_LINE",
            "expected_state": "MAIN_LINE",
            "expected_action": "none",
            "required": True,
        }
        res_on = run_replay_fixture(fix_on, self.med, ROOT)
        self.assertEqual(res_on.status, "PASS")
        self.assertEqual(res_on.actual_state, "MAIN_LINE")
        self.assertIsNone(res_on.click_point)

    def test_ensure_challenge_buttons_uses_right_click_wrapper(self):
        f_off = load_fixture_frame("fixtures/replay/main_line_auto_off.png")
        f_off.hwnd = 12345

        with patch.object(self.med.executor, "right_click", return_value=ActionResult(success=True, status="DRY_RUN")) as mock_rc:
            self.med._last_frame = f_off
            acted = self.med._ensure_challenge_buttons(f_off)
            self.assertEqual(acted, LoopAction.Continue)
            mock_rc.assert_called_once()
            _, kwargs = mock_rc.call_args
            self.assertEqual(kwargs.get("target_hwnd"), 12345)
            self.assertEqual(kwargs.get("dry_run"), self.settings.dry_run)

    def test_executor_failure_aborts_further_actions(self):
        f_off = load_fixture_frame("fixtures/replay/main_line_auto_off.png")
        f_off.hwnd = 12345

        # Fail executor right_click
        with patch.object(self.med.executor, "right_click", return_value=ActionResult(success=False, status="CANCELLED_WINDOW_CHANGED", message="Window changed")) as mock_rc:
            self.med._last_frame = f_off
            acted = self.med._ensure_challenge_buttons(f_off)
            self.assertEqual(acted, LoopAction.Continue)
            # scene_key should NOT be marked done
            self.assertEqual(len(self.med._challenge_done), 0)

    def test_existing_stage_select_positive_fixtures_pass(self):
        fix1 = {
            "fixture_id": "stage_select_1616x939",
            "file_path": "docs/agent_shared_logs/official_raw/20260803_CaptureWindow_20260803154629.png",
            "resolution": [1616, 939],
            "page": "STAGE_SELECT",
            "expected_state": "STAGE_SELECT",
            "expected_action": "SelectStage-target",
            "expected_stage": "4-4",
            "required": True,
        }
        res1 = run_replay_fixture(fix1, self.med, ROOT)
        self.assertEqual(res1.status, "PASS")

        fix2 = {
            "fixture_id": "stage_select_1936x1066",
            "file_path": "docs/agent_shared_logs/official_raw/20260803_CaptureWindow_20260803141607.png",
            "resolution": [1936, 1066],
            "page": "STAGE_SELECT",
            "expected_state": "STAGE_SELECT",
            "expected_action": "SelectStage-target",
            "expected_stage": "1-10",
            "required": True,
        }
        res2 = run_replay_fixture(fix2, self.med, ROOT)
        self.assertEqual(res2.status, "PASS")

    def test_no_action_fixture_fails_if_click_candidate_produced(self):
        fix_bad = {
            "fixture_id": "bad_no_action",
            "file_path": "fixtures/replay/main_line_auto_off.png",
            "resolution": [1599, 933],
            "window_title": "英雄三国KK",
            "page": "MAIN_LINE",
            "expected_state": "MAIN_LINE",
            "expected_action": "none",
            "is_negative": False,
        }
        res = run_replay_fixture(fix_bad, self.med, ROOT)
        self.assertEqual(res.status, "FAIL")
        self.assertIn("Unauthorized click candidate produced", res.notes)

    def test_missing_disconnect_modal_causes_replay_main_exit_code_1(self):
        exit_code = replay_main()
        self.assertEqual(exit_code, 1)

    def test_main_line_bootstrap_and_signal(self):
        f_off = load_fixture_frame("fixtures/replay/main_line_auto_off.png")
        self.assertEqual(self.med._detect_context(f_off, role="l1"), "MAIN_LINE")
        self.assertGreater(self.med._frame_signal(f_off, role="l1"), 0)

        self.med.phase = Phase.BOOT
        with patch.object(self.med.executor, "click") as mock_click, patch.object(self.med.executor, "right_click") as mock_rc:
            action = self.med._tick_l0(f_off)
            self.assertEqual(self.med.phase, Phase.MAIN_LINE)
            mock_click.assert_not_called()
            mock_rc.assert_not_called()

    def test_challenge_retry_reset_on_main_line_phase(self):
        for key in ("coin_challenge", "wood_challenge", "experience_challenge", "treasure_challenge"):
            self.med._challenge_attempts[key] = 3

        self.med.set_phase(Phase.MAIN_LINE, "new game started")
        self.assertEqual(len(self.med._challenge_attempts), 0)

        f_off = load_fixture_frame("fixtures/replay/main_line_auto_off.png")
        f_off.hwnd = 12345
        with patch.object(self.med.executor, "right_click", return_value=ActionResult(success=True, status="DRY_RUN")) as mock_rc:
            self.med._last_frame = f_off
            acted = self.med._ensure_challenge_buttons(f_off)
            self.assertEqual(acted, LoopAction.Continue)
            mock_rc.assert_called_once()
            _, kwargs = mock_rc.call_args
            self.assertEqual(kwargs.get("target_hwnd"), 12345)
            self.assertEqual(kwargs.get("dry_run"), self.settings.dry_run)

    def test_stage_id_generic_parsing_unbounded(self):
        from gamescript.vision.stage_selector import StageId
        self.assertEqual(StageId.parse("6-1"), StageId(6, 1))
        self.assertEqual(StageId.parse("1-31"), StageId(1, 31))


if __name__ == "__main__":
    unittest.main()
