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


def fixture(name: str) -> Frame:
    path = ROOT / "fixtures" / "live_postgame_20260808" / name
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise AssertionError(f"cannot load {path}")
    return Frame(image, window_title="英雄三国KK", hwnd=10001)


class HeroModeTemporalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(
            stage_targets=["1-15"],
            auto_reputation=True,
            reputation_type=3,
            reputation_level=2,
            dry_run=True,
            query_timeout=30,
        )
        self.med = Mediator(self.settings, ROOT)

    @staticmethod
    def _selected_level_one(modal: Frame) -> Frame:
        image = modal.bgr.copy()
        image[118:286, 662:815] = 255 - image[118:286, 662:815]
        image[314:342, 724:752] = 255 - image[314:342, 724:752]
        return Frame(image, window_title=modal.window_title, hwnd=modal.hwnd)

    @staticmethod
    def _selected_level_two(level_one: Frame) -> Frame:
        image = level_one.bgr.copy()
        image[314:342, 724:752] = (0, 255, 0)
        return Frame(image, window_title=level_one.window_title, hwnd=level_one.hwnd)

    def test_recorded_kenrito_path_is_one_input_per_confirmed_step(self) -> None:
        stage = fixture("live_stage_select.png")
        modal = fixture("live_archive_start_panel.png")
        in_game = fixture("live_hero_challenge.png")

        self.med.set_phase(Phase.STAGE_SELECT)
        target = self.med._find_stage_target(stage)
        self.assertIsNotNone(target)
        self.med._stage_selected = True
        self.med._stage_target_name = target.name
        self.med._stage_target_position = (target.x, target.y)
        self.med._stage_click_cooldown_until = 0.0

        with patch("gamescript.mediator.verify_stage_selection", return_value=False), patch.object(
            self.med, "act_click", return_value=True
        ) as click:
            before = click.call_count
            self.assertEqual(LoopAction.Continue, self.med._tick_l0(stage))
            self.assertEqual(1, click.call_count - before)
            self.assertEqual("OpenHeroModeModal", click.call_args.args[1])
            self.assertEqual(Phase.HERO_SETUP, self.med.phase)

            before = click.call_count
            self.assertEqual(LoopAction.Continue, self.med._tick_l0(modal))
            self.assertEqual(1, click.call_count - before)
            self.assertEqual("HeroKenritoPlus-1", click.call_args.args[1])

            level_one = self._selected_level_one(modal)
            before = click.call_count
            self.med._tick_l0(level_one)
            self.assertEqual(0, click.call_count - before)
            before = click.call_count
            self.med._tick_l0(level_one)
            self.assertEqual(1, click.call_count - before)
            self.assertEqual("HeroKenritoPlus-2", click.call_args.args[1])

            level_two = self._selected_level_two(level_one)
            before = click.call_count
            self.med._tick_l0(level_two)
            self.assertEqual(0, click.call_count - before)
            before = click.call_count
            self.med._tick_l0(level_two)
            self.assertEqual(1, click.call_count - before)
            self.assertEqual("StartHeroModeChallenge", click.call_args.args[1])
            self.assertEqual("WAIT_MODAL_CLOSE", self.med._hero_state)

            # A persistent modal never causes a duplicate Start click.
            before = click.call_count
            self.med._tick_l0(modal)
            self.assertEqual(0, click.call_count - before)

            loading = Frame(
                np.zeros((900, 1600, 3), dtype=np.uint8),
                window_title="英雄三国KK",
                hwnd=10001,
            )
            self.med._tick_l0(loading)
            self.assertEqual("WAIT_MODAL_CLOSE", self.med._hero_state)
            self.med._tick_l0(loading)
            self.assertEqual("WAIT_INGAME", self.med._hero_state)
            before = click.call_count
            self.med._tick_l0(in_game)
            self.assertEqual(0, click.call_count - before)
            self.assertEqual(Phase.MAIN_LINE, self.med.phase)

    def test_unverified_faction_fails_before_any_click(self) -> None:
        self.settings.reputation_type = 1
        stage = fixture("live_stage_select.png")
        with patch.object(self.med, "act_click") as click:
            action = self.med._begin_hero_setup(stage)
        self.assertEqual(LoopAction.Break, action)
        self.assertEqual(Phase.ERROR, self.med.phase)
        click.assert_not_called()

    def test_hero_step_deadline_allows_slow_capture_between_plus_steps(self) -> None:
        modal = fixture("live_archive_start_panel.png")
        level_one = self._selected_level_one(modal)
        level_two = self._selected_level_two(level_one)

        self.med.set_phase(Phase.HERO_SETUP)
        self.med._hero_state = "WAIT_MODAL"
        # Simulate a prior frame at t=100s.  The next real capture arrives
        # nine seconds later; the old 3s deadline failed before reading it.
        self.med._hero_step_deadline = 120.0

        with patch.object(self.med, "act_click", return_value=True) as click:
            with patch("gamescript.mediator.time.time", return_value=109.0):
                self.med._tick_hero_setup(modal)
            self.assertEqual("WAIT_LEVEL_CHANGE", self.med._hero_state)
            self.assertEqual("HeroKenritoPlus-1", click.call_args.args[1])

            with patch("gamescript.mediator.time.time", return_value=118.0):
                self.med._tick_hero_setup(level_one)
            self.assertEqual("WAIT_LEVEL_STABLE", self.med._hero_state)

            with patch("gamescript.mediator.time.time", return_value=127.0):
                self.med._tick_hero_setup(level_one)
            self.assertEqual("WAIT_LEVEL_CHANGE", self.med._hero_state)
            self.assertEqual("HeroKenritoPlus-2", click.call_args.args[1])

            with patch("gamescript.mediator.time.time", return_value=136.0):
                self.med._tick_hero_setup(level_two)
            self.assertEqual("WAIT_LEVEL_STABLE", self.med._hero_state)

            with patch("gamescript.mediator.time.time", return_value=145.0):
                self.med._tick_hero_setup(level_two)
            self.assertEqual("WAIT_MODAL_CLOSE", self.med._hero_state)
            self.assertEqual("StartHeroModeChallenge", click.call_args.args[1])

    def test_modal_close_allows_two_slow_frames_after_start(self) -> None:
        loading = Frame(
            np.zeros((900, 1600, 3), dtype=np.uint8),
            window_title="英雄三国KK",
            hwnd=10001,
        )
        self.med.set_phase(Phase.HERO_SETUP)
        self.med._hero_state = "WAIT_MODAL_CLOSE"
        self.med._hero_step_deadline = 160.0

        with patch("gamescript.mediator.time.time", return_value=109.0):
            self.med._tick_hero_setup(loading)
        self.assertEqual("WAIT_MODAL_CLOSE", self.med._hero_state)

        with patch("gamescript.mediator.time.time", return_value=118.0):
            self.med._tick_hero_setup(loading)
        self.assertEqual("WAIT_INGAME", self.med._hero_state)
        self.assertGreaterEqual(self.med._hero_step_deadline, 138.0)

    def test_stage_confirmation_rejects_target_after_row_moves(self) -> None:
        stage = fixture("live_stage_select.png")
        self.med.set_phase(Phase.STAGE_SELECT)
        target = self.med._find_stage_target(stage)
        self.assertIsNotNone(target)
        self.med._stage_selected = True
        self.med._stage_target_name = target.name
        self.med._stage_target_position = (target.x, target.y + 80)
        self.med._stage_click_cooldown_until = 0.0

        with patch("gamescript.mediator.verify_stage_selection", return_value=False), patch.object(
            self.med, "act_click", return_value=True
        ) as click:
            self.med._tick_l0(stage)

        self.assertEqual(Phase.STAGE_SELECT, self.med.phase)
        self.assertFalse(self.med._stage_selected)
        click.assert_not_called()

    def test_stage_target_requires_two_stable_frames_before_click(self) -> None:
        stage = fixture("live_stage_select.png")
        self.med.set_phase(Phase.STAGE_SELECT)

        with patch.object(self.med, "act_click", return_value=True) as click:
            self.med._tick_l0(stage)
            click.assert_not_called()

            self.med._tick_l0(stage)
            self.assertEqual(1, click.call_count)
            self.assertEqual("SelectStage-target", click.call_args.args[1])
            self.assertTrue(self.med._stage_selected)

    def test_ordinary_mode_uses_exact_target_and_start_when_row_has_no_highlight(self) -> None:
        self.settings.auto_reputation = False
        stage = fixture("live_stage_select.png")
        self.med.set_phase(Phase.STAGE_SELECT)
        target = self.med._find_stage_target(stage)
        self.assertIsNotNone(target)
        self.med._stage_selected = True
        self.med._stage_target_name = target.name
        self.med._stage_target_position = (target.x, target.y)
        self.med._stage_click_cooldown_until = 0.0

        with patch("gamescript.mediator.verify_stage_selection", return_value=False), patch.object(
            self.med, "act_click", return_value=True
        ) as click:
            action = self.med._tick_l0(stage)

        self.assertEqual(LoopAction.Continue, action)
        self.assertEqual(Phase.STAGE_STARTING, self.med.phase)
        self.assertEqual(1, click.call_count)
        self.assertEqual("StageStart", click.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
