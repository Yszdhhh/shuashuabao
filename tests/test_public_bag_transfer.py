"""Public-bag deposit chain: geometry, FSM, input-safety and mediator wiring.

Ground truth spec: ``docs/gt_lab/PUBLIC_BAG_GT_SPEC_20260909.md``.
Geometry is asserted against the 2026-09-09 live capture measurements
(``_public_bag_gt_20260909/keyframes/t12_0.png``, KK client 1600x900).  The
frames themselves live outside the repo, so the numbers they produced are
pinned here instead of the images: the deposited pill sat in public slot (3, 0)
and the panel origin measured (670, 82).

These are unit tests.  They do not claim a live deposit PASS — the spec forbids
that until multiplayer hitch footage exists.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.loop_action import LoopAction
from shuabao.mediator import Mediator
from shuabao.policy.public_bag import (
    GRID_COLS,
    GRID_ROWS,
    ITEM_BAR_SLOTS,
    BagLayout,
    PublicBagFSM,
    PublicBagPhase,
)
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult


#: Panel origin measured on the GT keyframe, in 1600x900 client pixels.
GT_PANEL_ORIGIN = (670.0, 82.0)
GT_TITLE_ORIGIN = (1131.0, 93.0)
GT_SELL_ORIGIN = (899.0, 479.0)
#: The pill the operator deposited landed here.
GT_DEPOSIT_SLOT = (3, 0)
GT_DEPOSIT_RECT_CENTER = (1036, 274)


def _frame(width: int = 1600, height: int = 900) -> Frame:
    return Frame(bgr=np.zeros((height, width, 3), dtype=np.uint8), timestamp=0.0, left=0, top=0, hwnd=7)


def _gt_layout() -> BagLayout:
    return BagLayout(GT_PANEL_ORIGIN[0], GT_PANEL_ORIGIN[1], 1.0)


class BagLayoutGeometryTests(unittest.TestCase):
    def test_title_anchor_reproduces_the_measured_panel_origin(self):
        layout = BagLayout.from_anchor("bag/public_bag_title", *GT_TITLE_ORIGIN, 1.0)
        self.assertIsNotNone(layout)
        self.assertAlmostEqual(layout.origin_x, GT_PANEL_ORIGIN[0], places=3)
        self.assertAlmostEqual(layout.origin_y, GT_PANEL_ORIGIN[1], places=3)

    def test_second_anchor_cross_check_agrees_on_the_same_panel(self):
        layout = BagLayout.from_anchor("bag/public_bag_title", *GT_TITLE_ORIGIN, 1.0)
        self.assertTrue(layout.anchor_matches("bag/bag_sell_equipment", *GT_SELL_ORIGIN))

    def test_second_anchor_cross_check_rejects_a_stray_hit(self):
        layout = BagLayout.from_anchor("bag/public_bag_title", *GT_TITLE_ORIGIN, 1.0)
        self.assertFalse(
            layout.anchor_matches("bag/bag_sell_equipment", GT_SELL_ORIGIN[0] + 60, GT_SELL_ORIGIN[1])
        )

    def test_deposited_pill_slot_matches_the_measured_grid_cell(self):
        layout = _gt_layout()
        row, col = GT_DEPOSIT_SLOT
        self.assertEqual(layout.public_slot_center(row, col), GT_DEPOSIT_RECT_CENTER)

    def test_grid_is_seven_by_eight_and_bounded(self):
        layout = _gt_layout()
        self.assertEqual(len(list(layout.public_slots())), GRID_ROWS * GRID_COLS)
        self.assertIsNone(layout.public_slot_rect(GRID_ROWS, 0))
        self.assertIsNone(layout.public_slot_rect(0, GRID_COLS))
        self.assertIsNone(layout.item_bar_slot_rect(ITEM_BAR_SLOTS))

    def test_public_and_personal_grids_do_not_overlap(self):
        layout = _gt_layout()
        for row, col in layout.public_slots():
            px0, _, px1, _ = layout.personal_slot_rect(row, col)
            qx0, _, qx1, _ = layout.public_slot_rect(row, col)
            self.assertLess(px1, qx0, f"personal ({row},{col}) leaks into the public grid")
            self.assertLess(px0, qx1)

    def test_item_bar_slot_lookup_round_trips(self):
        layout = _gt_layout()
        for index in range(ITEM_BAR_SLOTS):
            x, y = layout.item_bar_slot_center(index)
            self.assertEqual(layout.item_bar_slot_index(x, y), index)

    def test_geometry_scales_with_the_frame(self):
        scaled = BagLayout(GT_PANEL_ORIGIN[0] * 1.2, GT_PANEL_ORIGIN[1] * 1.2, 1.2)
        base = _gt_layout()
        bx0, by0, bx1, by1 = base.public_slot_rect(*GT_DEPOSIT_SLOT)
        sx0, sy0, sx1, sy1 = scaled.public_slot_rect(*GT_DEPOSIT_SLOT)
        self.assertAlmostEqual((sx1 - sx0) / (bx1 - bx0), 1.2, delta=0.08)
        self.assertAlmostEqual((sy1 - sy0) / (by1 - by0), 1.2, delta=0.08)

    def test_personal_surface_covers_grid_and_item_bar(self):
        layout = _gt_layout()
        self.assertTrue(layout.inside_personal_surface(*layout.personal_slot_center(0, 0)))
        self.assertTrue(layout.inside_personal_surface(*layout.item_bar_slot_center(1)))
        self.assertFalse(layout.inside_personal_surface(*layout.public_slot_center(0, 0)))
        self.assertTrue(layout.inside_public_grid(*layout.public_slot_center(4, 4)))


class PublicBagFSMTests(unittest.TestCase):
    def test_happy_path_follows_the_spec_step_order(self):
        fsm = PublicBagFSM()
        self.assertTrue(fsm.can_start(0.0))
        fsm = fsm.request_bag_open(0.0)
        self.assertIs(fsm.phase, PublicBagPhase.BAG_OPEN_REQUESTED)
        fsm = fsm.observe(0.1, bag_visible=True)
        self.assertIs(fsm.phase, PublicBagPhase.BAG_VISIBLE)
        fsm = fsm.select_source("swallow_pill", 1, 0.2)
        self.assertIs(fsm.phase, PublicBagPhase.SOURCE_SELECTED)
        fsm = fsm.request_deposit(3, 0, 0.3)
        self.assertIs(fsm.phase, PublicBagPhase.DEPOSIT_REQUESTED)
        fsm = fsm.observe(0.4, bag_visible=True, deposit_confirmed=True)
        self.assertIs(fsm.phase, PublicBagPhase.CLOSE_REQUESTED)
        self.assertEqual(fsm.deposits, 1)
        fsm = fsm.observe(0.5, bag_visible=False)
        self.assertIs(fsm.phase, PublicBagPhase.IDLE)

    def test_left_click_is_only_authorised_while_carrying_the_source(self):
        fsm = PublicBagFSM()
        for phase in PublicBagPhase:
            candidate = PublicBagFSM(phase=phase)
            self.assertEqual(
                candidate.can_left_click(),
                phase is PublicBagPhase.SOURCE_SELECTED,
                f"{phase} must not authorise a left click",
            )
        self.assertFalse(fsm.can_left_click())

    def test_bag_page_disappearing_aborts_instead_of_clicking_blind(self):
        fsm = PublicBagFSM().request_bag_open(0.0).observe(0.1, bag_visible=True)
        fsm = fsm.select_source("swallow_pill", 1, 0.2)
        fsm = fsm.observe(0.3, bag_visible=False)
        self.assertIs(fsm.phase, PublicBagPhase.ABORTED)
        self.assertEqual(fsm.abort_reason, "bag_page_lost")

    def test_bag_never_opening_aborts_on_its_deadline(self):
        fsm = PublicBagFSM().request_bag_open(0.0, timeout_s=3.0)
        self.assertIs(fsm.observe(2.9, bag_visible=False).phase, PublicBagPhase.BAG_OPEN_REQUESTED)
        aborted = fsm.observe(3.1, bag_visible=False)
        self.assertIs(aborted.phase, PublicBagPhase.ABORTED)
        self.assertEqual(aborted.abort_reason, "bag_page_not_visible")

    def test_unconfirmed_deposit_aborts_and_never_reclicks(self):
        fsm = (
            PublicBagFSM()
            .request_bag_open(0.0)
            .observe(0.1, bag_visible=True)
            .select_source("swallow_pill", 1, 0.2)
            .request_deposit(3, 0, 0.3, timeout_s=4.0)
        )
        waiting = fsm.observe(1.0, bag_visible=True, deposit_confirmed=None)
        self.assertIs(waiting.phase, PublicBagPhase.DEPOSIT_REQUESTED)
        expired = fsm.observe(5.0, bag_visible=True, deposit_confirmed=None)
        self.assertIs(expired.phase, PublicBagPhase.ABORTED)
        self.assertEqual(expired.deposits, 0)
        self.assertFalse(expired.can_left_click())

    def test_failed_postcondition_aborts_immediately(self):
        fsm = (
            PublicBagFSM()
            .request_bag_open(0.0)
            .observe(0.1, bag_visible=True)
            .select_source("swallow_pill", 1, 0.2)
            .request_deposit(3, 0, 0.3)
        )
        aborted = fsm.observe(0.4, bag_visible=True, deposit_confirmed=False)
        self.assertIs(aborted.phase, PublicBagPhase.ABORTED)
        self.assertEqual(aborted.abort_reason, "deposit_postcondition_failed")

    def test_abort_holds_a_cooldown_before_the_next_attempt(self):
        fsm = PublicBagFSM().abort("no_deposit_source", 100.0, cooldown_s=30.0)
        self.assertFalse(PublicBagFSM(cooldown_until=fsm.cooldown_until).can_start(120.0))
        self.assertTrue(PublicBagFSM(cooldown_until=fsm.cooldown_until).can_start(131.0))

    def test_out_of_order_transitions_are_refused(self):
        idle = PublicBagFSM()
        self.assertIs(idle.select_source("swallow_pill", 0, 0.0).phase, PublicBagPhase.IDLE)
        self.assertIs(idle.request_deposit(0, 0, 0.0).phase, PublicBagPhase.IDLE)
        self.assertIs(idle.confirm_deposit(0.0).phase, PublicBagPhase.IDLE)
        self.assertEqual(idle.confirm_deposit(0.0).deposits, 0)


class MediatorPublicBagTests(unittest.TestCase):
    def setUp(self):
        self.med = Mediator(Settings(dry_run=True, ocr_mode="off", mode_id="lobby_hitch"), ROOT)
        self.frame = _frame()
        self.layout = _gt_layout()

    def _patch_layout(self, layout: BagLayout | None):
        return patch.object(self.med, "_bag_layout", return_value=layout)

    def test_zero_input_when_the_bag_page_is_not_confirmed(self):
        with self._patch_layout(None), \
             patch.object(self.med, "_is_in_game_hud", return_value=False), \
             patch.object(self.med, "act_key") as key, \
             patch.object(self.med, "act_click") as click, \
             patch.object(self.med, "act_right_click") as right:
            self.assertIsNone(self.med._maybe_public_backpack_deposit(self.frame, 100.0))
        key.assert_not_called()
        click.assert_not_called()
        right.assert_not_called()

    def test_operation_is_scoped_to_lobby_hitch(self):
        self.med.settings.mode_id = "normal_farm"
        with patch.object(self.med, "_bag_layout") as layout:
            self.assertIsNone(self.med._maybe_public_backpack_deposit(self.frame, 100.0))
        layout.assert_not_called()

    def test_presses_b_only_on_a_confirmed_in_game_hud(self):
        with self._patch_layout(None), \
             patch.object(self.med, "_is_in_game_hud", return_value=True), \
             patch.object(self.med, "act_key", return_value=True) as key:
            self.assertEqual(self.med._maybe_public_backpack_deposit(self.frame, 100.0), LoopAction.Continue)
        key.assert_called_once_with("b", "PublicBackpackDepositB")
        self.assertIs(self.med._public_bag_fsm.phase, PublicBagPhase.BAG_OPEN_REQUESTED)

    def test_source_item_is_right_clicked_never_left_clicked(self):
        self.med._public_bag_fsm = PublicBagFSM(phase=PublicBagPhase.BAG_VISIBLE, deadline=200.0)
        source_hit = MatchResult("item_bar_slot_1", 0.9, *self.layout.item_bar_slot_center(1), 0, 0, 0, 0)
        with self._patch_layout(self.layout), \
             patch.object(self.med, "_public_bag_source", return_value=("swallow_pill", 1, source_hit)), \
             patch.object(self.med, "act_right_click", return_value=True) as right, \
             patch.object(self.med, "act_click") as click:
            self.assertEqual(self.med._maybe_public_backpack_deposit(self.frame, 100.0), LoopAction.Continue)
        right.assert_called_once_with(source_hit, "PublicBackpackDepositRightClick")
        click.assert_not_called()
        self.assertIs(self.med._public_bag_fsm.phase, PublicBagPhase.SOURCE_SELECTED)
        self.assertEqual(self.med._public_bag_fsm.source_slot, 1)

    def test_deposit_left_clicks_the_first_verified_empty_public_slot(self):
        self.med._public_bag_fsm = PublicBagFSM(
            phase=PublicBagPhase.SOURCE_SELECTED, source_id="swallow_pill", source_slot=1, deadline=200.0
        )
        x, y = self.layout.public_slot_center(*GT_DEPOSIT_SLOT)
        slot_hit = MatchResult("public_bag_slot_3_0", 1.0, x, y, 0, 0, x, y)
        with self._patch_layout(self.layout), \
             patch.object(self.med, "_public_bag_empty_slot", return_value=(3, 0, slot_hit)), \
             patch.object(self.med, "act_click", return_value=True) as click:
            self.assertEqual(self.med._maybe_public_backpack_deposit(self.frame, 100.0), LoopAction.Continue)
        click.assert_called_once_with(slot_hit, "PublicBackpackDeposit")
        self.assertIs(self.med._public_bag_fsm.phase, PublicBagPhase.DEPOSIT_REQUESTED)
        self.assertEqual(self.med._public_bag_fsm.target_slot, (3, 0))

    def test_a_deposit_target_inside_the_personal_bag_is_refused(self):
        """铁律：左键绝不落在个人背包/物品栏，哪怕定位层给出了这样的目标。"""
        self.med._public_bag_fsm = PublicBagFSM(
            phase=PublicBagPhase.SOURCE_SELECTED, source_id="swallow_pill", source_slot=1, deadline=200.0
        )
        x, y = self.layout.personal_slot_center(3, 0)
        bad_hit = MatchResult("personal_slot", 1.0, x, y, 0, 0, x, y)
        with self._patch_layout(self.layout), \
             patch.object(self.med, "_public_bag_empty_slot", return_value=(3, 0, bad_hit)), \
             patch.object(self.med, "act_click") as click:
            self.med._maybe_public_backpack_deposit(self.frame, 100.0)
        click.assert_not_called()
        self.assertIs(self.med._public_bag_fsm.phase, PublicBagPhase.ABORTED)
        self.assertEqual(self.med._public_bag_fsm.abort_reason, "deposit_target_outside_public_bag")

    def test_item_bar_hit_is_refused_as_a_deposit_target(self):
        layout = self.layout
        x, y = layout.item_bar_slot_center(2)
        self.assertFalse(
            self.med._public_bag_left_click_allowed(layout, MatchResult("x", 1.0, x, y, 0, 0, x, y))
        )

    def test_full_public_bag_aborts_without_input(self):
        self.med._public_bag_fsm = PublicBagFSM(
            phase=PublicBagPhase.SOURCE_SELECTED, source_id="swallow_pill", source_slot=1, deadline=200.0
        )
        with self._patch_layout(self.layout), \
             patch.object(self.med, "_public_bag_empty_slot", return_value=None), \
             patch.object(self.med, "act_click") as click:
            self.med._maybe_public_backpack_deposit(self.frame, 100.0)
        click.assert_not_called()
        self.assertEqual(self.med._public_bag_fsm.abort_reason, "public_bag_full_or_unverified")

    def test_deposit_waits_zero_input_until_the_postcondition_lands(self):
        self.med._public_bag_fsm = PublicBagFSM(
            phase=PublicBagPhase.DEPOSIT_REQUESTED,
            source_id="swallow_pill",
            source_slot=1,
            target_slot=(3, 0),
            deadline=200.0,
        )
        with self._patch_layout(self.layout), \
             patch.object(self.med, "_public_bag_deposit_confirmed", return_value=None), \
             patch.object(self.med, "act_click") as click, \
             patch.object(self.med, "act_right_click") as right, \
             patch.object(self.med, "act_key") as key:
            self.assertEqual(self.med._maybe_public_backpack_deposit(self.frame, 100.0), LoopAction.Continue)
        for spy in (click, right, key):
            spy.assert_not_called()
        self.assertIsNone(self.med._trace_post_confirm())

    def test_confirmed_deposit_reports_post_confirm_true(self):
        self.med._public_bag_fsm = PublicBagFSM(
            phase=PublicBagPhase.DEPOSIT_REQUESTED,
            source_id="swallow_pill",
            source_slot=1,
            target_slot=(3, 0),
            deadline=200.0,
            opened_by_us=True,
        )
        with self._patch_layout(self.layout), \
             patch.object(self.med, "_public_bag_deposit_confirmed", return_value=True), \
             patch.object(self.med, "act_key", return_value=True):
            self.med._maybe_public_backpack_deposit(self.frame, 100.0)
        self.assertEqual(self.med._public_bag_fsm.deposits, 1)
        self.assertIs(self.med._trace_post_confirm(), True)

    def test_failed_deposit_reports_post_confirm_false(self):
        self.med._public_bag_fsm = PublicBagFSM(
            phase=PublicBagPhase.DEPOSIT_REQUESTED,
            source_id="swallow_pill",
            source_slot=1,
            target_slot=(3, 0),
            deadline=200.0,
        )
        with self._patch_layout(self.layout), \
             patch.object(self.med, "_public_bag_deposit_confirmed", return_value=False):
            self.med._maybe_public_backpack_deposit(self.frame, 100.0)
        self.assertIs(self.med._trace_post_confirm(), False)

    def test_postcondition_is_not_observed_without_a_public_bag_surface(self):
        with self._patch_layout(None):
            result = self.med._public_backpack_deposit_postcondition(self.frame, self.frame)
        self.assertFalse(result["observed"])
        self.assertEqual(result["state"], "public_bag_surface_not_confirmed")

    def test_postcondition_requires_the_target_slot_to_stop_being_empty(self):
        self.med._public_bag_fsm = PublicBagFSM(
            phase=PublicBagPhase.DEPOSIT_REQUESTED, source_slot=1, target_slot=(3, 0)
        )
        with self._patch_layout(self.layout), \
             patch.object(self.med, "_bag_slot_empty", return_value=True):
            result = self.med._public_backpack_deposit_postcondition(self.frame, self.frame)
        self.assertFalse(result["observed"])
        self.assertEqual(result["state"], "target_slot_still_empty")

    def test_postcondition_confirms_a_real_transfer(self):
        self.med._public_bag_fsm = PublicBagFSM(
            phase=PublicBagPhase.DEPOSIT_REQUESTED, source_slot=1, target_slot=(3, 0), deposits=0
        )
        empties = {"before": True, "after": False}

        def fake_empty(frame, _rect):
            return empties["before"] if frame is before else empties["after"]

        before = _frame()
        with self._patch_layout(self.layout), patch.object(self.med, "_bag_slot_empty", side_effect=fake_empty):
            result = self.med._public_backpack_deposit_postcondition(before, self.frame)
        self.assertTrue(result["observed"])
        self.assertEqual(result["state"], "confirmed")
        self.assertEqual(result["target_slot"], [3, 0])

    #: Everything the hitch main line checks before reaching its parking step.
    _MAIN_LINE_GATES = (
        "_maybe_click_hitch_pressure_transfer",
        "_tick_early_challenge",
        "_ensure_auto_task_enabled",
        "_ensure_challenge_buttons",
        "_maybe_ensure_hero_panel_focus",
        "_maybe_click_tqtz",
        "_maybe_close_main_line_after_5_5",
        "_handle_self_opened_compact_panel",
        "_maybe_open_choice_panel",
    )

    def test_hitch_idle_step_drives_the_deposit_operation(self):
        self.med._l1_cycle_step = "hitch_idle"
        self.med._hitch_pressure_transferred = True
        with ExitStack() as stack:
            for name in self._MAIN_LINE_GATES:
                stack.enter_context(patch.object(self.med, name, return_value=None))
            op = stack.enter_context(
                patch.object(
                    self.med, "_maybe_public_backpack_deposit", return_value=LoopAction.Continue
                )
            )
            self.assertEqual(self.med._tick_main_line(self.frame), LoopAction.Continue)
        op.assert_called_once()

    def test_devour_pill_is_never_consumed_while_a_transfer_is_in_flight(self):
        self.med._public_bag_fsm = PublicBagFSM(phase=PublicBagPhase.SOURCE_SELECTED)
        with patch.object(self.med, "find") as find, patch.object(self.med, "act_click") as click:
            self.assertIsNone(self.med._maybe_use_inventory_item(self.frame))
        find.assert_not_called()
        click.assert_not_called()

    def test_bag_page_pill_is_not_consumed_under_lobby_hitch(self):
        with patch.object(self.med, "_bag_layout") as layout:
            self.assertIsNone(self.med._bag_page_swallow_pill(self.frame))
        layout.assert_not_called()

    def test_bag_page_pill_is_reachable_in_solo(self):
        self.med.settings.mode_id = "normal_farm"
        hit = MatchResult("item_bar_slot_1", 0.9, 100, 100, 0, 0, 100, 100)
        with patch.object(self.med, "_bag_layout", return_value=self.layout), \
             patch.object(self.med, "_public_bag_source", return_value=("swallow_pill", 1, hit)):
            self.assertIs(self.med._bag_page_swallow_pill(self.frame), hit)


class BagSlotOccupancyTests(unittest.TestCase):
    """Occupancy thresholds calibrated on the GT keyframes."""

    def setUp(self):
        self.med = Mediator(Settings(dry_run=True, ocr_mode="off", mode_id="lobby_hitch"), ROOT)

    def _slot_frame(self, fill) -> Frame:
        bgr = np.zeros((900, 1600, 3), dtype=np.uint8)
        bgr[:, :] = (32, 34, 36)  # panel interior grey, like the real empty grid
        fill(bgr)
        return Frame(bgr=bgr, timestamp=0.0, left=0, top=0, hwnd=7)

    def test_flat_dark_cell_reads_empty(self):
        layout = _gt_layout()
        frame = self._slot_frame(lambda _bgr: None)
        self.assertTrue(self.med._bag_slot_empty(frame, layout.public_slot_rect(0, 0)))

    def test_saturated_icon_reads_occupied(self):
        layout = _gt_layout()
        x0, y0, x1, y1 = layout.public_slot_rect(*GT_DEPOSIT_SLOT)

        def fill(bgr):
            bgr[y0:y1, x0:x1] = (220, 40, 200)  # the pill's magenta orb

        frame = self._slot_frame(fill)
        self.assertFalse(self.med._bag_slot_empty(frame, layout.public_slot_rect(*GT_DEPOSIT_SLOT)))

    def test_high_contrast_cursor_is_not_reported_empty(self):
        """A cursor-occluded cell is unknown, not empty — never a deposit target."""
        layout = _gt_layout()
        x0, y0, x1, y1 = layout.public_slot_rect(5, 1)

        def fill(bgr):
            bgr[y0:y0 + 20, x0:x0 + 20] = (255, 255, 255)
            bgr[y0 + 4:y0 + 16, x0 + 4:x0 + 16] = (0, 0, 0)

        frame = self._slot_frame(fill)
        self.assertFalse(self.med._bag_slot_empty(frame, layout.public_slot_rect(5, 1)))

    def test_empty_slot_scan_returns_the_first_cell_in_fill_order(self):
        layout = _gt_layout()
        frame = self._slot_frame(lambda _bgr: None)
        found = self.med._public_bag_empty_slot(frame, layout)
        self.assertIsNotNone(found)
        row, col, hit = found
        self.assertEqual((row, col), (0, 0))
        self.assertEqual((hit.x, hit.y), layout.public_slot_center(0, 0))

    def test_out_of_bounds_rect_is_never_empty(self):
        frame = self._slot_frame(lambda _bgr: None)
        self.assertFalse(self.med._bag_slot_empty(frame, None))
        self.assertFalse(self.med._bag_slot_empty(frame, (1598, 898, 1599, 899)))


if __name__ == "__main__":
    unittest.main()
