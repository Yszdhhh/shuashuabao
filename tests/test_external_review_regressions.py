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
from gamescript.vision.matcher import MatchResult


def load_frame(relative_path: str) -> Frame:
    path = ROOT / relative_path
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(path)
    return Frame(image, window_title="英雄三国KK", hwnd=10001)


def hit(name: str = "hit") -> MatchResult:
    return MatchResult(name=name, score=0.95, x=100, y=100, w=20, h=20, screen_x=100, screen_y=100)


class ExternalReviewRegressionTests(unittest.TestCase):
    def test_main_line_stage_glyph_has_no_click_authority(self) -> None:
        med = Mediator(Settings(), ROOT)
        frame = Frame(np.zeros((900, 1600, 3), np.uint8), window_title="英雄三国KK", hwnd=10001)
        med.phase = Phase.MAIN_LINE
        med._last_frame = frame

        with patch.object(med, "_post_game_state", return_value=None), \
                patch.object(med, "find_scene", return_value=None), \
                patch.object(med, "_selection_anchor", return_value=None), \
                patch.object(med, "_ensure_auto_task_enabled", return_value=None), \
                patch.object(med, "_ensure_challenge_buttons", return_value=None), \
                patch.object(med, "_find_stage_page", return_value=True), \
                patch.object(med, "_is_in_game_hud", return_value=True), \
                patch.object(med, "_maybe_fire_artifacts", return_value=None), \
                patch.object(med, "_maybe_open_choice_panel", return_value=None), \
                patch.object(med, "act_click") as click:
            action = med._tick_main_line(frame)

        self.assertIs(action, LoopAction.Continue)
        self.assertIs(med.phase, Phase.MAIN_LINE)
        click.assert_not_called()

    def test_real_stage_page_is_handed_to_guarded_l0_state(self) -> None:
        med = Mediator(Settings(), ROOT)
        frame = Frame(np.zeros((900, 1600, 3), np.uint8), window_title="英雄三国KK", hwnd=10001)
        med.phase = Phase.MAIN_LINE
        med._last_frame = frame
        med._auto_task_done = True
        with patch.object(med, "_post_game_state", return_value=None), \
                patch.object(med, "find_scene", return_value=None), \
                patch.object(med, "_selection_anchor", return_value=None), \
                patch.object(med, "_ensure_auto_task_enabled", return_value=None), \
                patch.object(med, "_ensure_challenge_buttons", return_value=None), \
                patch.object(med, "_find_stage_page", return_value=True), \
                patch.object(med, "_is_in_game_hud", return_value=False):
            action = med._tick_main_line(frame)
        self.assertIs(action, LoopAction.Continue)
        self.assertIs(med.phase, Phase.STAGE_SELECT)

    def test_fail_requires_two_frames_and_recovery_owns_followup(self) -> None:
        med = Mediator(Settings(), ROOT)
        image = np.random.default_rng(42).integers(0, 255, (900, 1600, 3), dtype=np.uint8)
        frame = Frame(image, window_title="英雄三国KK", hwnd=10001)
        med.set_phase(Phase.MAIN_LINE, "test")
        med._capture_best = lambda *args, **kwargs: frame
        clicked: list[str] = []

        def find_scene(_frame, scene, **_kwargs):
            return hit("fail") if scene == "fail" else None

        with patch.object(med, "find_scene", side_effect=find_scene), \
                patch.object(med, "_selection_anchor", return_value=None), \
                patch.object(med, "click_scene", side_effect=lambda _f, _s, reason="", **_k: clicked.append(reason) or True):
            self.assertIs(med.tick(), LoopAction.Continue)
            self.assertIs(med.phase, Phase.MAIN_LINE)
            self.assertEqual(clicked, [])

            self.assertIs(med.tick(), LoopAction.Continue)
            self.assertIs(med.phase, Phase.QUIT)
            self.assertEqual(clicked, [])

            self.assertIs(med.tick(), LoopAction.Continue)
            self.assertEqual(clicked, ["recover"])
            self.assertEqual(med._recovery_step, "WAIT_OK")

    def test_verified_main_line_resets_cross_game_retry_budget(self) -> None:
        med = Mediator(Settings(), ROOT)
        med._challenge_start_attempts = 1
        med._recovery_step = "DONE"
        med._failure_candidate_frames = 1
        med.set_phase(Phase.MAIN_LINE, "verified next game")
        self.assertEqual(med._challenge_start_attempts, 0)
        self.assertIsNone(med._recovery_step)
        self.assertEqual(med._failure_candidate_frames, 0)

    def test_dry_run_records_error_but_does_not_stop_observation(self) -> None:
        med = Mediator(Settings(dry_run=True), ROOT)
        med.phase = Phase.MAIN_LINE

        def uncertain_tick() -> LoopAction:
            med.set_phase(Phase.ERROR, "unknown selection panel timeout")
            med.stop()
            return LoopAction.Break

        with patch.object(med, "_tick_impl", side_effect=uncertain_tick):
            self.assertIs(med.tick(), LoopAction.Continue)
        self.assertIs(med.phase, Phase.MAIN_LINE)
        self.assertEqual(med._interrupt_reason, "unknown selection panel timeout")

    def test_960_postgame_and_auto_task_roi_are_enabled(self) -> None:
        med = Mediator(Settings(), ROOT)
        image = load_frame("fixtures/replay/victory_continue.png").bgr
        small = cv2.resize(image, (960, 540))
        frame = Frame(small, window_title="英雄三国KK", hwnd=10001)
        med._ui_scale = 0.6
        self.assertEqual(med._post_game_state(frame), "POST_VICTORY")
        self.assertIsNotNone(med._auto_task_roi_frame(frame))

    def test_exit_confirm_fixture_never_selects_cancel(self) -> None:
        med = Mediator(Settings(), ROOT)
        frame = load_frame("fixtures/live_postgame_20260808/live_exit_confirm.png")
        confirm = med._find_exit_confirm(frame)
        cancel = med.find(frame, ["lobby/exit_cancel_btn"], threshold=0.78, scales=(0.9, 1.0, 1.1))
        self.assertIsNotNone(confirm)
        self.assertIsNotNone(cancel)
        self.assertLess(confirm.screen_x, cancel.screen_x)
        self.assertLessEqual(confirm.x, frame.width * 0.50)
        self.assertGreaterEqual(cancel.x, frame.width * 0.50)

    def test_artifacts_use_game_start_time_and_click_one_slot_per_tick(self) -> None:
        med = Mediator(Settings(artifact_slots=3), ROOT)
        med._main_line_started_at = 1.0
        # The idle watchdog is refreshed by frequent UI work; it must not
        # postpone artifact warm-up.
        med._main_line_since = 99.0
        med._last_frame = Frame(np.zeros((900, 1600, 3), np.uint8), hwnd=10001)
        with patch("gamescript.mediator.time.time", return_value=100.0), \
                patch.object(med, "_slot_has_artifact", return_value=True), \
                patch.object(med, "act_click", return_value=True) as click, \
                patch.object(med.executor, "press_key") as press:
            self.assertIs(med._maybe_fire_artifacts(med._last_frame), LoopAction.Continue)
        click.assert_called_once()
        self.assertEqual(click.call_args.args[1], "Artifact-Q")
        press.assert_not_called()

    def test_pause_overlay_precedes_generic_confirm_classifier(self) -> None:
        med = Mediator(Settings(), ROOT)
        frame = Frame(np.zeros((900, 1600, 3), np.uint8), hwnd=10001)

        def matched(_frame, names, **_kwargs):
            name = names[0]
            if name == "pauseGame":
                return MatchResult(name, 0.85, 755, 386, 90, 29, 755, 386)
            if name == "mijingOk":
                return MatchResult(name, 0.79, 752, 526, 26, 30, 752, 526)
            return None

        with patch.object(med, "find", side_effect=matched):
            self.assertEqual(med._post_game_state(frame), "PAUSED")

    def test_pause_overlay_is_zero_action_wait(self) -> None:
        med = Mediator(Settings(), ROOT)
        med.phase = Phase.MAIN_LINE
        med._main_line_since = 1.0
        frame = Frame(np.zeros((900, 1600, 3), np.uint8), hwnd=10001)
        with patch.object(med, "_post_game_state", return_value="PAUSED"), \
                patch.object(med, "act_click") as click:
            self.assertIs(med._tick_main_line(frame), LoopAction.Continue)
        self.assertIs(med.phase, Phase.MAIN_LINE)
        click.assert_not_called()

    def test_choice_panels_use_hud_mouse_buttons_not_keyboard(self) -> None:
        frame = Frame(np.zeros((900, 1600, 3), np.uint8), hwnd=10001)
        cases = (
            ("skill", 0.0, 0.0, (1444, 780), "OpenSkillPanel"),
            ("bond", 200.0, 0.0, (1382, 780), "OpenBondPanel"),
            ("treasure", 200.0, 200.0, (1377, 729), "OpenTreasurePanel"),
        )
        for kind, last_skill, last_bond, expected, reason in cases:
            with self.subTest(kind=kind):
                med = Mediator(Settings(), ROOT)
                med._last_skill_panel = last_skill
                med._last_bond_attempt = last_bond
                with patch("gamescript.mediator.time.time", return_value=200.0), \
                        patch.object(med, "_selection_anchor", return_value=None), \
                        patch.object(med, "act_click", return_value=True) as click, \
                        patch.object(med.executor, "press_key") as press:
                    self.assertIs(med._maybe_open_choice_panel(frame), LoopAction.Continue)
                click.assert_called_once()
                opened_hit = click.call_args.args[0]
                self.assertEqual((opened_hit.screen_x, opened_hit.screen_y), expected)
                self.assertEqual(click.call_args.args[1], reason)
                press.assert_not_called()

    def test_auto_task_uses_relative_scores_from_live_compressed_frames(self) -> None:
        med = Mediator(Settings(), ROOT)
        frame = Frame(np.zeros((900, 1600, 3), np.uint8), hwnd=10001)

        def scored(_frame, template, **_kwargs):
            score = 0.589 if template.stem == "auto_task_on" else 0.754
            return MatchResult(template.stem, score, 10, 10, 20, 20, 10, 10)

        with patch("gamescript.mediator.match_one", side_effect=scored):
            state, toggle = med._auto_task_state(frame)
        self.assertEqual(state, "OFF")
        self.assertIsNotNone(toggle)

    def test_auto_task_unknown_blocks_challenges(self) -> None:
        med = Mediator(Settings(), ROOT)
        frame = Frame(np.zeros((900, 1600, 3), np.uint8), window_title="英雄三国KK", hwnd=10001)
        med.phase = Phase.MAIN_LINE
        med._last_frame = frame
        with patch.object(med, "_post_game_state", return_value=None), \
                patch.object(med, "find_scene", return_value=None), \
                patch.object(med, "_selection_anchor", return_value=None), \
                patch.object(med, "_ensure_auto_task_enabled", return_value=None), \
                patch.object(med, "_ensure_challenge_buttons") as challenges:
            action = med._tick_main_line(frame)
        self.assertIs(action, LoopAction.Continue)
        challenges.assert_not_called()

    def test_choice_shortcuts_precede_repeating_evolve_button(self) -> None:
        med = Mediator(Settings(), ROOT)
        frame = Frame(np.zeros((900, 1600, 3), np.uint8), window_title="英雄三国KK", hwnd=10001)
        med.phase = Phase.MAIN_LINE
        med._last_frame = frame
        med._auto_task_done = True
        with patch.object(med, "_post_game_state", return_value=None), \
                patch.object(med, "find_scene", return_value=None), \
                patch.object(med, "_selection_anchor", return_value=None), \
                patch.object(med, "_ensure_auto_task_enabled", return_value=None), \
                patch.object(med, "_ensure_challenge_buttons", return_value=None), \
                patch.object(med, "_find_stage_page", return_value=False), \
                patch.object(med, "_handle_self_opened_compact_panel", return_value=None), \
                patch.object(med, "_maybe_open_choice_panel", return_value=LoopAction.Continue) as panels, \
                patch.object(med, "find") as find:
            action = med._tick_main_line(frame)
        self.assertIs(action, LoopAction.Continue)
        panels.assert_called_once()
        # N2.4：_is_in_game_hud 会先调用 find（环境锚点 ROI 检查）；契约是
        # 「选择快捷键先于重复进化按钮」——进化按钮（click_evolve）不得被扫描。
        evolve_calls = [
            c for c in find.call_args_list
            if c.args and isinstance(c.args[1], list) and "click_evolve" in c.args[1]
        ]
        self.assertEqual(evolve_calls, [], "选择快捷键存在时不得扫描进化按钮")

    def test_compact_skill_panel_respects_configured_priority(self) -> None:
        med = Mediator(Settings(skills=["asj", "asjg", "jq"]), ROOT)
        frame = Frame(np.zeros((900, 1600, 3), np.uint8), hwnd=10001)
        hits = [
            MatchResult("jq", 0.95, 20, 20, 40, 40, 1200, 650),
            MatchResult("asj", 0.80, 10, 10, 40, 40, 1100, 650),
        ]
        with patch("gamescript.mediator.match_all", return_value=hits):
            chosen = med._find_compact_skill_choice(frame)
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.name, "asj")


if __name__ == "__main__":
    unittest.main()
