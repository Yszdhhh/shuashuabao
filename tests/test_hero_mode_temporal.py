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
from shuabao.mediator import FACTION_SPECS, Mediator, Phase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import _load_template, resolve_template


def fixture(name: str) -> Frame:
    path = ROOT / "fixtures" / "live_postgame_20260808" / name
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise AssertionError(f"cannot load {path}")
    return Frame(image, window_title="英雄三国KK", hwnd=10001)


def hero_modal_180825(name: str = "client_1600x900.png") -> Frame:
    path = ROOT / "fixtures" / "hero_modal_20260812_180825" / name
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

        with patch("shuabao.mediator.selected_stage_row", return_value=None), patch.object(
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

    def test_multi_faction_allocation_switches_cards_before_start(self) -> None:
        """alloc {3:2, 4:1}：肯瑞托加到 2 后必须先点选探险者卡再继续加点。"""
        modal = fixture("live_archive_start_panel.png")
        self.med.settings.reputation_allocations = {"3": 2, "4": 1}
        self.med.set_phase(Phase.HERO_SETUP)
        self.med._hero_plan = [(3, 2), (4, 1)]
        self.med._hero_plan_index = 0
        self.med._hero_state = "WAIT_MODAL"
        self.med._hero_level_baseline = None
        self.med._hero_level_candidate = None
        self.med._hero_card_baseline = None
        self.med._hero_modal_missing_frames = 0
        self.med._hero_step_deadline = float("inf")

        def inverted(frame: Frame, roi: tuple[int, int, int, int]) -> Frame:
            image = frame.bgr.copy()
            x1, y1, x2, y2 = roi
            image[y1:y2, x1:x2] = 255 - image[y1:y2, x1:x2]
            return Frame(image, window_title=frame.window_title, hwnd=frame.hwnd)

        tx_card = FACTION_SPECS[4].card_roi
        tx_level = FACTION_SPECS[4].level_roi

        with patch.object(self.med, "act_click", return_value=True) as click:
            self.assertEqual(LoopAction.Continue, self.med._tick_hero_setup(modal))
            self.assertEqual("HeroKenritoPlus-1", click.call_args.args[1])

            level_one = self._selected_level_one(modal)
            self.med._tick_hero_setup(level_one)
            self.med._tick_hero_setup(level_one)
            level_two = self._selected_level_two(level_one)
            self.med._tick_hero_setup(level_two)
            self.med._tick_hero_setup(level_two)

            self.assertEqual("WAIT_FACTION_SELECTED", self.med._hero_state)
            self.assertIn("Tanxian", click.call_args.args[1])

            frame_tx = inverted(level_two, tx_card)
            self.med._tick_hero_setup(frame_tx)
            self.assertEqual("HeroTanxianPlus-1", click.call_args.args[1])

            image = frame_tx.bgr.copy()
            x1, y1, x2, y2 = tx_level
            image[y1:y2, x1:x2] = (0, 255, 0)
            frame_tx_level1 = Frame(
                image, window_title=frame_tx.window_title, hwnd=frame_tx.hwnd
            )
            self.med._tick_hero_setup(frame_tx_level1)
            self.med._tick_hero_setup(frame_tx_level1)
            self.assertEqual("StartHeroModeChallenge", click.call_args.args[1])

    def test_unknown_faction_type_fails_before_any_click(self) -> None:
        """type=0 is not in FACTION_SPECS at all: must fail-closed regardless of

        how many factions currently have a verified template (renamed from
        test_unverified_faction_fails_before_any_click, which pinned type=1;
        once all 6 unselected templates exist, type=1 alone stops being a
        reliable "unverified" probe).
        """
        self.settings.reputation_type = 0
        stage = fixture("live_stage_select.png")
        with patch.object(self.med, "act_click") as click:
            action = self.med._begin_hero_setup(stage)
        self.assertEqual(LoopAction.Break, action)
        self.assertEqual(Phase.ERROR, self.med.phase)
        click.assert_not_called()

    def test_out_of_range_level_fails_before_any_click(self) -> None:
        """level outside 1..10 must fail-closed (6..10 now legal)."""
        stage = fixture("live_stage_select.png")
        for level in (0, 11):
            with self.subTest(level=level):
                med = Mediator(self.settings, ROOT)
                med.settings.reputation_type = 3
                med.settings.reputation_level = level
                with patch.object(med, "act_click") as click:
                    action = med._begin_hero_setup(stage)
                self.assertEqual(LoopAction.Break, action)
                self.assertEqual(Phase.ERROR, med.phase)
                click.assert_not_called()

    def test_all_six_factions_are_verified_with_templates(self) -> None:
        """六阵营均已从 20260812_180825 裁出未选中卡面；未知 type 仍走 fail-closed。"""
        for rep_type in range(1, 7):
            spec = FACTION_SPECS[rep_type]
            self.assertTrue(spec.verified, spec.name)
            self.assertIsNotNone(spec.unselected_template, spec.name)

    def test_verified_non_kenrito_faction_does_not_use_kenrito_only_message(self) -> None:
        """If a faction's unselected template is verified, the gate must not

        reject it with the old Kenrito-only message; it should be allowed to
        proceed past _begin_hero_setup's static gate (it may still block on
        finding the hero entry, which is a legitimate zero-input wait, not a
        Fail-Closed).
        """
        verified_non_kenrito = [t for t, spec in FACTION_SPECS.items() if spec.verified and t != 3]
        self.assertTrue(verified_non_kenrito, "expected at least one verified non-Kenrito faction")
        stage = fixture("live_stage_select.png")
        for rep_type in verified_non_kenrito:
            with self.subTest(rep_type=rep_type):
                med = Mediator(self.settings, ROOT)
                med.settings.reputation_type = rep_type
                med.settings.reputation_level = 2
                with patch.object(med, "act_click", return_value=True):
                    action = med._begin_hero_setup(stage)
                # Not a Fail-Closed: either it clicked the entry (Continue,
                # phase advanced to HERO_SETUP) or it is zero-input waiting
                # for the entry to appear (Continue, phase unchanged).
                self.assertEqual(LoopAction.Continue, action)
                self.assertNotEqual(Phase.ERROR, med.phase)

    def test_verified_faction_unselected_templates_match_fixture_offline(self) -> None:
        """六阵营未选中模板必须在 180825 客户区夹具上自匹配 ≥0.90。

        旧夹具 live_archive_start_panel 上黑锋为选中态，不能再拿它做全阵营自匹配。
        肯瑞托仍须在旧夹具上保持高匹配（既有证据不被新裁切破坏）。
        """
        modal = hero_modal_180825()
        verified_count = 0
        for rep_type, spec in FACTION_SPECS.items():
            self.assertTrue(spec.verified, f"faction {rep_type} ({spec.name}) should be verified")
            verified_count += 1
            template_path = resolve_template(self.med.images, spec.unselected_template)
            self.assertIsNotNone(template_path, f"missing template for {spec.name}")
            template = _load_template(template_path)
            self.assertIsNotNone(template, f"unreadable template for {spec.name}")
            x1, y1, x2, y2 = spec.card_roi
            region = modal.bgr[y1:y2, x1:x2]
            self.assertEqual(
                region.shape, template.shape,
                f"{spec.name} card_roi size does not match its template",
            )
            score = float(cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)[0, 0])
            self.assertGreaterEqual(score, 0.90, f"{spec.name} self-match score too low: {score}")
        self.assertEqual(6, verified_count)

        kenrito = FACTION_SPECS[3]
        old = fixture("live_archive_start_panel.png")
        template = _load_template(resolve_template(self.med.images, kenrito.unselected_template))
        x1, y1, x2, y2 = kenrito.card_roi
        score = float(cv2.matchTemplate(old.bgr[y1:y2, x1:x2], template, cv2.TM_CCOEFF_NORMED)[0, 0])
        self.assertGreaterEqual(score, 0.90, f"Kenrito regression on old fixture: {score}")

    def test_calibrated_level_rois_match_zero_on_180825(self) -> None:
        """校准后的 level_roi 在开局零级帧上应对 hero_level_zero ≥0.95。"""
        modal = hero_modal_180825()
        zero_path = resolve_template(self.med.images, "lobby/hero_level_zero")
        self.assertIsNotNone(zero_path)
        zero = _load_template(zero_path)
        self.assertIsNotNone(zero)
        for spec in FACTION_SPECS.values():
            x1, y1, x2, y2 = spec.level_roi
            roi = modal.bgr[y1:y2, x1:x2]
            self.assertEqual(roi.shape[:2], zero.shape[:2], spec.name)
            score = float(cv2.matchTemplate(roi, zero, cv2.TM_CCOEFF_NORMED)[0, 0])
            self.assertGreaterEqual(score, 0.95, f"{spec.name} zero score {score}")

    def test_recorded_plus_clicks_mutate_non_kenrito_level_rois(self) -> None:
        """180825 上人工点加号时，五阵营 level_roi 相对开局帧有显著像素差。

        这是离线旁证，不是完整确认闭环；阈值与 mediator._hero_changed_pixels 同量级。
        """
        baseline = hero_modal_180825().bgr
        peaks = {
            1: "frame_heifeng_peak.png",
            2: "frame_yinse_peak.png",
            4: "frame_tanxian_peak.png",
            5: "frame_yuansu_peak.png",
            6: "frame_shouhu_peak.png",
        }
        for rep_type, frame_name in peaks.items():
            with self.subTest(rep_type=rep_type):
                spec = FACTION_SPECS[rep_type]
                peak = hero_modal_180825(frame_name).bgr
                x1, y1, x2, y2 = spec.level_roi
                a = baseline[y1:y2, x1:x2].astype(np.int16)
                b = peak[y1:y2, x1:x2].astype(np.int16)
                changed = int((np.abs(a - b).sum(axis=2) > 18).sum())
                self.assertGreaterEqual(changed, 200, f"{spec.name} changed_px={changed}")

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
            with patch("shuabao.mediator.time.time", return_value=109.0):
                self.med._tick_hero_setup(modal)
            self.assertEqual("WAIT_LEVEL_CHANGE", self.med._hero_state)
            self.assertEqual("HeroKenritoPlus-1", click.call_args.args[1])

            with patch("shuabao.mediator.time.time", return_value=118.0):
                self.med._tick_hero_setup(level_one)
            self.assertEqual("WAIT_LEVEL_STABLE", self.med._hero_state)

            with patch("shuabao.mediator.time.time", return_value=127.0):
                self.med._tick_hero_setup(level_one)
            self.assertEqual("WAIT_LEVEL_CHANGE", self.med._hero_state)
            self.assertEqual("HeroKenritoPlus-2", click.call_args.args[1])

            with patch("shuabao.mediator.time.time", return_value=136.0):
                self.med._tick_hero_setup(level_two)
            self.assertEqual("WAIT_LEVEL_STABLE", self.med._hero_state)

            with patch("shuabao.mediator.time.time", return_value=145.0):
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

        with patch("shuabao.mediator.time.time", return_value=109.0):
            self.med._tick_hero_setup(loading)
        self.assertEqual("WAIT_MODAL_CLOSE", self.med._hero_state)

        with patch("shuabao.mediator.time.time", return_value=118.0):
            self.med._tick_hero_setup(loading)
        self.assertEqual("WAIT_INGAME", self.med._hero_state)
        self.assertGreaterEqual(self.med._hero_step_deadline, 138.0)

    def test_stage_confirmation_allows_target_after_row_moves_with_semantics(self) -> None:
        """Normal list movement is allowed when target, neighbors, and hero entry remain valid.

        Rejection of changed labels, broken neighbors, and missing entries is covered by
        StageSelectorTests.test_mediator_rejects_changed_stage_semantics_without_input.
        """
        stage = fixture("live_stage_select.png")
        self.med.set_phase(Phase.STAGE_SELECT)
        target = self.med._find_stage_target(stage)
        self.assertIsNotNone(target)
        self.med._stage_selected = True
        self.med._stage_target_name = target.name
        # Simulate a post-click list displacement greater than the old 6px gate.
        self.med._stage_target_position = (target.x, target.y + 80)
        self.med._stage_click_cooldown_until = 0.0

        with patch("shuabao.mediator.selected_stage_row", return_value=None), patch.object(
            self.med, "act_click", return_value=True
        ) as click:
            self.med._tick_l0(stage)

        self.assertEqual(Phase.HERO_SETUP, self.med.phase)
        self.assertTrue(self.med._stage_selected)
        click.assert_called_once()
        self.assertEqual("OpenHeroModeModal", click.call_args.args[1])

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

        with patch("shuabao.mediator.selected_stage_row", return_value=None), patch.object(
            self.med, "act_click", return_value=True
        ) as click:
            action = self.med._tick_l0(stage)

        self.assertEqual(LoopAction.Continue, action)
        self.assertEqual(Phase.STAGE_STARTING, self.med.phase)
        self.assertEqual(1, click.call_count)
        self.assertEqual("StageStart", click.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
