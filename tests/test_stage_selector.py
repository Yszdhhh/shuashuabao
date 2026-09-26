from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from shuabao.loop_action import LoopAction
from shuabao.mediator import Mediator, Phase
from shuabao.runtime_mediator import Mediator as RuntimeMediator
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult, _load_template
from shuabao.vision.stage_selector import (
    StageId,
    StageRow,
    _truncated_last_row_fallback,
    _classify_glyph,
    _classify_topbar_one,
    find_stage_in_range,
    find_stage_labels,
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

    def test_selected_stage_row_reads_the_highlighted_row(self):
        frame = self._live_20260814_frame()
        row = selected_stage_row(frame, IMAGES)
        self.assertIsNotNone(row)
        self.assertEqual(str(row.stage_id), "1-1")

    def test_selected_stage_row_none_when_nothing_highlighted(self):
        frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), window_title="英雄三国KK", hwnd=1000)
        self.assertIsNone(selected_stage_row(frame, IMAGES))

    def _live_20260926_truncated_frame(self, name: str) -> Frame:
        path = ROOT / "fixtures/stage_select_1_23_truncated_20260926" / name
        img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
        return Frame(img, window_title="英雄三国KK", hwnd=1000)

    def test_selected_stage_row_reads_truncated_last_row(self):
        """20260926 solo：1-23 在列表底部只露上半截但已金边选中，必须读出。"""
        frame = self._live_20260926_truncated_frame(
            "selected_1_23_bottom_truncated_client_1600x900.png"
        )
        row = selected_stage_row(frame, IMAGES)
        self.assertIsNotNone(row)
        self.assertEqual(str(row.stage_id), "1-23")

    def test_selected_stage_row_keeps_true_highlight_before_truncated_click(self):
        """点选前高亮在 1-18：截断兜底不得提前宣布 1-23，也不得盖掉真高亮。"""
        frame = self._live_20260926_truncated_frame(
            "highlight_on_1_18_before_click_client_1600x900.png"
        )
        row = selected_stage_row(frame, IMAGES)
        self.assertIsNotNone(row)
        self.assertEqual(str(row.stage_id), "1-18")


    def test_truncated_fallback_rejects_unselected_last_row(self):
        frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8))
        gray = cv2.cvtColor(frame.bgr, cv2.COLOR_BGR2GRAY)
        rows = [
            StageRow("1-22", StageId(1, 22), 1080, 735),
            StageRow("1-23", StageId(1, 23), 1080, 785),
        ]
        self.assertIsNone(_truncated_last_row_fallback(frame, rows, gray, 1.0))

    def test_truncated_fallback_rejects_last_row_whose_ring_is_not_clipped(self):
        frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8))
        gray = cv2.cvtColor(frame.bgr, cv2.COLOR_BGR2GRAY)
        rows = [
            StageRow("1-21", StageId(1, 21), 1080, 680),
            StageRow("1-22", StageId(1, 22), 1080, 735),
        ]
        # Even if side evidence were bright, center 735 + ring half-height 22
        # stays inside the 0.88h ROI (792), so this is not a truncated row.
        with patch(
            "shuabao.vision.stage_selector._row_border_bright_ratio",
            return_value=0.5,
        ):
            self.assertIsNone(_truncated_last_row_fallback(frame, rows, gray, 1.0))

    def test_two_full_ring_highlights_fail_closed_without_truncated_fallback(self):
        frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8))
        rows = [
            StageRow("1-22", StageId(1, 22), 1080, 735),
            StageRow("1-23", StageId(1, 23), 1080, 785),
        ]
        with patch(
            "shuabao.vision.stage_selector.visible_stage_rows",
            return_value=rows,
        ), patch(
            "shuabao.vision.stage_selector._row_border_bright_ratio",
            side_effect=[0.42, 0.31],
        ), patch(
            "shuabao.vision.stage_selector._truncated_last_row_fallback",
        ) as fallback:
            self.assertIsNone(selected_stage_row(frame, IMAGES))
        fallback.assert_not_called()

    def test_selected_truncated_stage_scales_to_1280x720(self):
        source = self._live_20260926_truncated_frame(
            "selected_1_23_bottom_truncated_client_1600x900.png"
        )
        resized = cv2.resize(source.bgr, (1280, 720), interpolation=cv2.INTER_AREA)
        row = selected_stage_row(Frame(resized, window_title="英雄三国KK", hwnd=1000), IMAGES)
        self.assertIsNotNone(row)
        self.assertEqual(str(row.stage_id), "1-23")

    def test_unselected_truncated_last_row_stays_unselected_at_1280x720(self):
        source = self._live_20260926_truncated_frame(
            "highlight_on_1_18_before_click_client_1600x900.png"
        )
        resized = cv2.resize(source.bgr, (1280, 720), interpolation=cv2.INTER_AREA)
        row = selected_stage_row(Frame(resized, window_title="英雄三国KK", hwnd=1000), IMAGES)
        self.assertIsNotNone(row)
        self.assertEqual(str(row.stage_id), "1-18")

    def test_runtime_mediator_starts_when_truncated_target_highlighted(self):
        """20260926 回归：_stage_selected 已立、高亮在截断的 1-23，必须点开始游戏。

        旧逻辑里 selected_stage_row() 返回 None，LIVE 覆写判定“缺少正向高亮确认”
        而重置 _stage_selected，于是 tick 48/51/54 反复重点击 1-23 直到预算耗尽。
        """
        med = RuntimeMediator(Settings(stage_targets=["1-23"], auto_reputation=False), ROOT)
        med.set_phase(Phase.STAGE_SELECT)
        frame = self._live_20260926_truncated_frame(
            "selected_1_23_bottom_truncated_client_1600x900.png"
        )
        med._last_frame = frame
        med._stage_selected = True
        med._stage_target_name = "stage_target_1-23"
        med._stage_click_cooldown_until = 0.0
        with patch.object(med, "_detect_context", return_value="STAGE_SELECT"), \
             patch.object(med, "_maybe_switch_to_archaeology", return_value=None), \
             patch.object(med, "act_click", return_value=True) as click:
            action = med._tick_l0(frame)
        self.assertEqual(action, LoopAction.Continue)
        self.assertTrue(med._stage_selected)
        self.assertEqual(click.call_args.args[1], "StageStart")

    def test_runtime_mediator_still_resets_when_highlight_is_on_another_stage(self):
        """截断兜底不得把错位高亮当选中：目标 1-8、高亮 1-23 时仍必须重点。"""
        med = RuntimeMediator(Settings(stage_targets=["1-8"], auto_reputation=False), ROOT)
        med.set_phase(Phase.STAGE_SELECT)
        frame = self._live_20260926_truncated_frame(
            "selected_1_23_bottom_truncated_client_1600x900.png"
        )
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

    @staticmethod
    def _thin_one_glyph() -> np.ndarray:
        # 高>=12、宽/高<0.38 的细长竖笔，旧共享分类会直接当成 "1"。
        return np.ones((16, 5), dtype=np.uint8)

    def test_topbar_thin_stroke_still_reads_as_one(self):
        self.assertEqual(_classify_topbar_one(self._thin_one_glyph()), "1")

    def test_shared_glyph_classifier_does_not_promote_thin_noise_to_one(self):
        self.assertIsNone(_classify_glyph(self._thin_one_glyph(), {}))


if __name__ == "__main__":
    unittest.main()
