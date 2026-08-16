from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from gamescript.loop_action import LoopAction
from gamescript.mediator import Mediator, Phase
from gamescript.settings import Settings
from gamescript.vision.capture import Frame
from gamescript.vision.matcher import MatchResult, _load_template
from gamescript.vision.stage_selector import (
    StageId,
    find_stage_in_range,
    find_stage_labels,
    find_unselected_old_world_tab,
    selected_stage_row,
    verify_stage_selection,
    visible_stage_rows,
)


ROOT = Path(__file__).resolve().parents[1]
IMAGES = ROOT / "assets" / "Images"


class StageSelectorTests(unittest.TestCase):
    def _frame_with_labels(self) -> Frame:
        frame = np.zeros((939, 1616, 3), dtype=np.uint8)
        x = int(frame.shape[1] * 0.62) + 50
        for y, name in ((160, "5-6"), (215, "5-10")):
            label = _load_template(IMAGES / f"{name}.png")
            self.assertIsNotNone(label)
            h, w = label.shape[:2]
            frame[y:y + h, x:x + w] = label
        return Frame(frame)

    def test_reads_numbered_rows_without_ocr_dependency(self):
        rows = visible_stage_rows(self._frame_with_labels(), IMAGES)
        self.assertEqual([row.number for row in rows], [6, 10])
        self.assertEqual([str(row.stage_id) for row in rows], ["5-6", "5-10"])

    def test_prefers_configured_end_when_start_is_scrolled_out(self):
        hit = find_stage_in_range(self._frame_with_labels(), IMAGES, 1, 10)
        self.assertIsNotNone(hit)
        self.assertEqual(hit.name, "stage_target_5-10")

    def test_stage_id_chapter_distinction(self):
        s1 = StageId.parse("1-10")
        s2 = StageId.parse("5-10")
        self.assertIsNotNone(s1)
        self.assertIsNotNone(s2)
        self.assertNotEqual(s1, s2)
        self.assertEqual(s1.chapter, 1)
        self.assertEqual(s2.chapter, 5)

    def test_does_not_match_different_chapter_exact_target(self):
        hit = find_stage_labels(self._frame_with_labels(), IMAGES, ["1-10"])
        self.assertIsNone(hit)

        hit5 = find_stage_labels(self._frame_with_labels(), IMAGES, ["5-10"])
        self.assertIsNotNone(hit5)
        self.assertEqual(hit5.name, "stage_target_5-10")

    def test_verify_stage_selection_empty(self):
        empty = Frame(np.zeros((939, 1616, 3), dtype=np.uint8))
        self.assertFalse(verify_stage_selection(empty))

    def test_verify_stage_selection_bright_but_unselected(self):
        # Bright text on target row but no selection highlight over adjacent background
        img = np.zeros((939, 1616, 3), dtype=np.uint8)
        # Put bright white text everywhere in stage list region
        img[100:800, 900:1300] = 220
        frame = Frame(img)
        # Because adjacent rows are also bright (contrast diff < 10), verify returns False
        self.assertFalse(verify_stage_selection(frame, target="5-6"))

    def test_verify_stage_selection_selected_target_row(self):
        # Target row has bright selection highlight background while adjacent rows are dark
        img = np.zeros((939, 1616, 3), dtype=np.uint8)
        # Target row center at (1080, 200)
        img[185:215, 1000:1160] = 230
        frame = Frame(img)
        target_hit = MatchResult("stage_target_5-6", 1.0, 1080, 200, 40, 20, 1080, 200)
        self.assertTrue(verify_stage_selection(frame, target=target_hit))

    def test_verify_stage_selection_state_disappears(self):
        img_selected = np.zeros((939, 1616, 3), dtype=np.uint8)
        img_selected[185:215, 1000:1160] = 230
        frame_selected = Frame(img_selected)

        img_unselected = np.zeros((939, 1616, 3), dtype=np.uint8)
        frame_unselected = Frame(img_unselected)

        target_hit = MatchResult("stage_target_5-6", 1.0, 1080, 200, 40, 20, 1080, 200)
        self.assertTrue(verify_stage_selection(frame_selected, target=target_hit))
        self.assertFalse(verify_stage_selection(frame_unselected, target=target_hit))

    def test_mediator_verification_failure_no_start_click(self):
        settings = Settings()
        med = Mediator(settings, ROOT)
        med.set_phase(Phase.STAGE_SELECT)
        img = np.zeros((939, 1616, 3), dtype=np.uint8)
        frame = Frame(img, window_title="KK", hwnd=1000)
        med._stage_selected = True
        med._stage_click_cooldown_until = 0.0

        with patch.object(med, "act_click") as mock_click:
            action = med._tick_l0(frame)
            self.assertEqual(action, LoopAction.Continue)
            mock_click.assert_not_called()

    def _live_20260814_frame(self) -> Frame:
        path = ROOT / "fixtures/stage_select_20260814/highlight_on_1_1_client_1600x900.png"
        img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
        return Frame(img, window_title="英雄三国KK", hwnd=1000, left=203, top=84)

    def _lab13_stage_frame(self) -> Frame:
        path = ROOT / "fixtures/lab13_200601_stage_card/02_q2_stage_select_click2_t1567.0s.jpg"
        full = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertIsNotNone(full)
        return Frame(full[84:984, 203:1803].copy(), window_title="英雄三国KK", hwnd=1000, left=203, top=84)

    def test_selected_stage_row_recovers_lab13_highlighted_1_12(self):
        row = selected_stage_row(self._lab13_stage_frame(), IMAGES)
        self.assertIsNotNone(row)
        self.assertEqual(str(row.stage_id), "1-12")

    def _recovery_frame(
        self,
        labels: list[tuple[int, str]],
        blocks: list[tuple[int, int]],
    ) -> Frame:
        """Synthetic stage list: readable label rows plus oversized bright blocks.

        The wide block (200px) mimics a selected row whose bright border merges
        with its label; the narrow one (24px) never reaches SELECTED_RING_RATIO.
        """
        img = np.zeros((939, 1616, 3), dtype=np.uint8)
        x0 = int(img.shape[1] * 0.62) + 50
        for y, name in labels:
            label = _load_template(IMAGES / f"{name}.png")
            self.assertIsNotNone(label)
            h, w = label.shape[:2]
            img[y:y + h, x0:x0 + w] = label
        for top, width in blocks:
            cx = x0 + 20
            img[top:top + 44, cx - width // 2:cx + width // 2] = 255
        return Frame(img)

    def test_recovers_middle_row_when_both_neighbors_and_ring_confirm(self):
        frame = self._recovery_frame([(160, "5-6"), (480, "5-8")], [(300, 200)])
        rows = visible_stage_rows(frame, IMAGES)
        self.assertEqual([str(r.stage_id) for r in rows], ["5-6", "5-7", "5-8"])

    def test_recovery_negative_without_below_neighbor(self):
        frame = self._recovery_frame([(160, "5-6")], [(300, 200)])
        rows = visible_stage_rows(frame, IMAGES)
        self.assertEqual([str(r.stage_id) for r in rows], ["5-6"])

    def test_recovery_negative_without_above_neighbor(self):
        frame = self._recovery_frame([(480, "5-8")], [(300, 200)])
        rows = visible_stage_rows(frame, IMAGES)
        self.assertEqual([str(r.stage_id) for r in rows], ["5-8"])

    def test_recovery_negative_across_chapters(self):
        frame = self._recovery_frame([(160, "5-6"), (480, "1-23")], [(300, 200)])
        rows = visible_stage_rows(frame, IMAGES)
        self.assertEqual([str(r.stage_id) for r in rows], ["5-6", "1-23"])

    def test_recovery_negative_when_neighbors_not_two_apart(self):
        frame = self._recovery_frame([(160, "5-6"), (480, "5-9")], [(300, 200)])
        rows = visible_stage_rows(frame, IMAGES)
        self.assertEqual([str(r.stage_id) for r in rows], ["5-6", "5-9"])

    def test_recovery_negative_when_ring_too_dim(self):
        frame = self._recovery_frame([(160, "5-6"), (480, "5-8")], [(300, 24)])
        rows = visible_stage_rows(frame, IMAGES)
        self.assertEqual([str(r.stage_id) for r in rows], ["5-6", "5-8"])

    def test_recovery_negative_when_two_blocks_qualify(self):
        frame = self._recovery_frame(
            [(160, "5-6"), (480, "5-8"), (760, "5-10")],
            [(300, 200), (620, 200)],
        )
        rows = visible_stage_rows(frame, IMAGES)
        self.assertEqual([str(r.stage_id) for r in rows], ["5-6", "5-8", "5-10"])

    def test_selected_stage_row_reads_the_highlighted_row(self):
        frame = self._live_20260814_frame()
        row = selected_stage_row(frame, IMAGES)
        self.assertIsNotNone(row)
        self.assertEqual(str(row.stage_id), "1-1")

    def test_selected_stage_row_none_when_nothing_highlighted(self):
        frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), window_title="英雄三国KK", hwnd=1000)
        self.assertIsNone(selected_stage_row(frame, IMAGES))

    def test_mediator_reclicks_target_when_highlight_sits_on_another_stage(self):
        """20260814：高亮在 1-1、目标是 1-8，不得点开始游戏。"""
        med = Mediator(Settings(stage_targets=["1-8"], auto_reputation=False), ROOT)
        med.set_phase(Phase.STAGE_SELECT)
        frame = self._live_20260814_frame()
        med._last_frame = frame
        med._stage_selected = True
        med._stage_target_name = "stage_target_1-8"
        med._stage_click_cooldown_until = 0.0
        with patch.object(med, "_detect_context", return_value="STAGE_SELECT"), \
             patch.object(med, "_maybe_switch_to_archaeology", return_value=None), \
             patch.object(med, "act_click", return_value=True) as click:
            action = med._tick_l0(frame)
        self.assertEqual(action, LoopAction.Continue)
        click.assert_not_called()
        self.assertFalse(med._stage_selected)

    def test_mediator_starts_when_highlight_is_on_the_target(self):
        med = Mediator(Settings(stage_targets=["1-1"], auto_reputation=False), ROOT)
        med.set_phase(Phase.STAGE_SELECT)
        frame = self._live_20260814_frame()
        med._last_frame = frame
        med._stage_selected = True
        med._stage_target_name = "stage_target_1-1"
        med._stage_click_cooldown_until = 0.0
        start = MatchResult("roomStart", 0.99, 1080, 812, 120, 40, 1283, 896)
        with patch.object(med, "_detect_context", return_value="STAGE_SELECT"), \
             patch.object(med, "_maybe_switch_to_archaeology", return_value=None), \
             patch.object(med, "_find_stage_start", return_value=start), \
             patch.object(med, "act_click", return_value=True) as click:
            med._tick_l0(frame)
        self.assertEqual(click.call_args.args[1], "StageStart")
        self.assertEqual(click.call_args.args[0].name, "roomStart")

    def test_mediator_stops_after_three_failed_target_clicks(self):
        med = Mediator(Settings(stage_targets=["1-8"], auto_reputation=False), ROOT)
        med.set_phase(Phase.STAGE_SELECT)
        frame = self._live_20260814_frame()
        med._last_frame = frame
        med._stage_selected = True
        med._stage_target_name = "stage_target_1-8"
        med._stage_click_cooldown_until = 0.0
        med._stage_select_attempts = 3
        with patch.object(med, "_detect_context", return_value="STAGE_SELECT"), \
             patch.object(med, "_maybe_switch_to_archaeology", return_value=None), \
             patch.object(med, "act_click", return_value=True) as click:
            action = med._tick_l0(frame)
        self.assertEqual(action, LoopAction.Break)
        self.assertIs(med.phase, Phase.ERROR)
        click.assert_not_called()

    def test_stage_settle_window_does_not_click_again(self):
        settings = Settings()
        med = Mediator(settings, ROOT)
        med.set_phase(Phase.STAGE_SELECT)
        frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), window_title="KK", hwnd=1000)
        med._stage_selected = True
        med._stage_click_cooldown_until = 9999999999.0

        with patch.object(med, "_detect_context", return_value="STAGE_SELECT"), \
             patch.object(med, "_maybe_switch_to_archaeology", return_value=None), \
             patch.object(med, "act_click") as click:
            action = med._tick_l0(frame)

        self.assertEqual(action, LoopAction.Continue)
        click.assert_not_called()

    def test_stage_id_cross_chapter_comparison(self):
        s1_10 = StageId(1, 10)
        s2_1 = StageId(2, 1)
        self.assertTrue(s1_10 < s2_1)
        self.assertTrue(s1_10 <= s2_1)
        self.assertFalse(s1_10 > s2_1)
        self.assertFalse(s1_10 >= s2_1)
    def test_stage_id_invalid_input(self):
        self.assertIsNone(StageId.parse(""))
        self.assertIsNone(StageId.parse("invalid"))
        self.assertIsNone(StageId.parse("-1"))
        self.assertIsNone(StageId.parse("1-"))

    # ---------- 旧世大陆大区页签自动切换（CORE02-L0-STAGE-REGION-TAB-AUTO-RECOVERY） ----------

    def _reborn_stage_frame(self, name: str) -> Frame:
        path = ROOT / "fixtures/reborn_wow/stage" / name
        img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertIsNotNone(img)
        return Frame(img, window_title="英雄三国KK", hwnd=1000, left=203, top=84)

    def _raid_region_frame(self) -> Frame:
        """团本分页（熔火之心）：右侧列表是 2-x 行，旧世大陆页签未选中。"""
        return self._reborn_stage_frame("stage_select_molten_core_2.png")

    def test_finds_old_world_tab_on_raid_region_page(self):
        frame = self._raid_region_frame()
        hit = find_unselected_old_world_tab(frame, IMAGES)
        self.assertIsNotNone(hit)
        # 点击目标必须落在实测页签带内（窗口相对坐标，含窗口偏移）
        rx = (hit.screen_x - frame.left) / frame.width
        ry = (hit.screen_y - frame.top) / frame.height
        self.assertGreaterEqual(rx, 0.44)
        self.assertLessEqual(rx, 0.64)
        self.assertGreaterEqual(ry, 0.05)
        self.assertLessEqual(ry, 0.30)

    def test_old_world_tab_none_when_already_on_old_world(self):
        # 已在旧世大陆：可见行是 1-x，页签状态不构成点击理由
        for frame in (self._live_20260814_frame(),
                      self._reborn_stage_frame("stage_select_old_world_1.png")):
            self.assertIsNone(find_unselected_old_world_tab(frame, IMAGES))

    def test_mediator_switches_old_world_tab_before_scanning_stage_list(self):
        """缺陷 20260816_204613：团本分页进入 STAGE_SELECT 时必须先切页签，
        不得在未切页前扫描/滚动关卡列表。"""
        med = Mediator(Settings(stage_targets=["1-12"], auto_reputation=False), ROOT)
        med.set_phase(Phase.STAGE_SELECT)
        frame = self._raid_region_frame()
        med._last_frame = frame
        # 模拟缺陷现场：滚动预算耗尽、误在团本分页选中了关卡
        med._stage_selected = True
        med._stage_target_name = "stage_target_2-1"
        med._stage_scroll_attempts = 8
        with patch.object(med, "_detect_context", return_value="STAGE_SELECT"), \
             patch.object(med, "_maybe_switch_to_archaeology", return_value=None), \
             patch.object(med, "act_click", return_value=True) as click, \
             patch.object(med, "_find_stage_target") as find_target:
            action = med._tick_l0(frame)
        self.assertEqual(action, LoopAction.Continue)
        click.assert_called_once()
        self.assertEqual(click.call_args.args[1], "SwitchOldWorldTab")
        hit = click.call_args.args[0]
        rx = (hit.screen_x - frame.left) / frame.width
        ry = (hit.screen_y - frame.top) / frame.height
        self.assertGreaterEqual(rx, 0.44)
        self.assertLessEqual(rx, 0.64)
        self.assertGreaterEqual(ry, 0.05)
        self.assertLessEqual(ry, 0.30)
        find_target.assert_not_called()
        self.assertFalse(med._stage_selected)
        self.assertIsNone(med._stage_target_name)
        self.assertEqual(med._stage_scroll_attempts, 0)
        self.assertGreater(med._stage_scroll_cooldown_until, 0.0)


if __name__ == "__main__":
    unittest.main()
