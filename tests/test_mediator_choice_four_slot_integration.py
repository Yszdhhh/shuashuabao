import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.mediator import Mediator
from shuabao import mediator as mediator_module
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.choice_policy import PolicyAction, PolicyDecision
from shuabao.layout_transform import LayoutTransform

class DummyCandidate:
    def __init__(self, name, confidence=0.95, text=""):
        self.name = name
        self.confidence = confidence
        self.text = text or name

class DummyResponse:
    def __init__(self, candidates=None, text="", raw_text="", rec_score=0.95, status="ok", reason=""):
        self.candidates = candidates or []
        self.text = text or (candidates[0].name if candidates else "")
        self.raw_text = raw_text or self.text
        self.rec_score = rec_score
        self.status = status
        self.reason = reason

class TestMediatorChoiceFourSlotIntegration(unittest.TestCase):
    def setUp(self):
        self.settings = Settings()
        self.settings.cards = []
        self.settings.bonds = ["成长"]
        self.settings.bond_must_take = []
        self.med = Mediator(self.settings, ROOT)
        self.frame_1600 = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), window_title="game", hwnd=1)

    def test_confident_complete_template_slots_skip_ocr(self):
        frame_path = ROOT / "fixtures/card_template_assertions/positives/bond_choice_3.png"
        data = np.fromfile(str(frame_path), dtype=np.uint8)
        frame = Frame(cv2.imdecode(data, cv2.IMREAD_COLOR))
        self.med._ocr_client = MagicMock()

        slots = self.med._ocr_panel_slots(frame, "bond")

        self.assertEqual(len(slots), 3)
        self.assertTrue(all(slot.get("source") == "template" for slot in slots))
        self.assertTrue(self.med._last_slots_from_template)
        self.med._ocr_client.shadow_predict.assert_not_called()

    def test_template_fast_path_makes_zero_ocr_calls(self):
        # Round 2: the fast path must stay IPC-free (no title OCR, no badge
        # OCR); rarity stays None by design — 93-panel replay shows decisions
        # agree with the OCR path 90/93, other 3 are listed OCR misses.
        frame_path = ROOT / "fixtures/card_template_assertions/positives/bond_choice_3.png"
        data = np.fromfile(str(frame_path), dtype=np.uint8)
        frame = Frame(cv2.imdecode(data, cv2.IMREAD_COLOR))
        self.med._ocr_client = MagicMock()

        slots = self.med._ocr_panel_slots(frame, "bond")
        self.assertTrue(self.med._last_slots_from_template)
        cands = self.med._slots_to_candidates(frame, "bond", slots)
        self.assertEqual(len(cands), 3)
        self.med._ocr_client.shadow_predict.assert_not_called()

    def test_incomplete_template_slots_fall_back_to_ocr(self):
        template_slots = [
            {"index": i, "name": "祝福" if i < 3 else None,
             "confidence": 0.95 if i < 3 else 0.0,
             "template_score": 0.95 if i < 3 else 0.0,
             "source": "template"}
            for i in range(4)
        ]
        self.med._ocr_client = MagicMock()
        self.med._ocr_client.shadow_predict.return_value = DummyResponse(candidates=[], raw_text="")

        with patch.object(mediator_module, "match_card_slots_by_template", return_value=(4, template_slots)):
            slots = self.med._ocr_panel_slots(self.frame_1600, "bond")

        self.assertFalse(self.med._last_slots_from_template)
        self.med._ocr_client.shadow_predict.assert_called()
        self.assertFalse(any(slot.get("source") == "template" for slot in slots))

    def test_1_true_three_slot_fixture_confirms_layout_3_and_legacy_centers(self):
        med = self.med
        frame = self.frame_1600
        mock_ocr = MagicMock()
        def shadow_predict(f, pid, slot_spec, panel_bbox=None):
            bbox = slot_spec.get("bbox", (0,0,0,0))
            x0 = bbox[0]
            # 3-slot bboxes in 1600x900: 406, 680, 953
            if 390 <= x0 <= 420:
                return DummyResponse(candidates=[DummyCandidate("成长之苗")], raw_text="成长之苗")
            elif 660 <= x0 <= 700:
                return DummyResponse(candidates=[DummyCandidate("成长之根")], raw_text="成长之根")
            elif 930 <= x0 <= 970:
                return DummyResponse(candidates=[DummyCandidate("成长之叶")], raw_text="成长之叶")
            return DummyResponse(candidates=[], raw_text="")
        mock_ocr.shadow_predict.side_effect = shadow_predict
        med._ocr_client = mock_ocr

        slots = med._ocr_panel_slots(frame, "bond")
        self.assertEqual(len(slots), 3)
        self.assertEqual([s["name"] for s in slots], ["成长之苗", "成长之根", "成长之叶"])

        # Synthetic wiring dispatch through policy decision to hit for all slots
        expected_3_centers = med._CHOICE_SLOT_CENTERS["bond"]
        for idx, (exp_x_ratio, exp_y_ratio) in enumerate(expected_3_centers):
            decision = PolicyDecision(PolicyAction.SELECT_SLOT, index=idx, reason="test")
            label, hit = med._policy_decision_to_hit(frame, "bond", decision, slots)
            self.assertEqual(label, "bond")
            self.assertEqual(hit.x, int(1600 * exp_x_ratio))
            self.assertEqual(hit.y, int(900 * exp_y_ratio))

    def test_2_true_four_slot_fixture_confirms_layout_4_and_four_slot_centers(self):
        med = self.med
        frame = self.frame_1600
        mock_ocr = MagicMock()
        def shadow_predict(f, pid, slot_spec, panel_bbox=None):
            bbox = slot_spec.get("bbox", (0,0,0,0))
            x0 = bbox[0]
            # 4-slot bboxes in 1600x900: 296, 544, 792, 1040
            if 280 <= x0 <= 315:
                return DummyResponse(candidates=[DummyCandidate("成长之苗")], raw_text="成长之苗")
            elif 530 <= x0 <= 560:
                return DummyResponse(candidates=[DummyCandidate("成长之根")], raw_text="成长之根")
            elif 775 <= x0 <= 810:
                return DummyResponse(candidates=[DummyCandidate("成长之叶")], raw_text="成长之叶")
            elif 1025 <= x0 <= 1060:
                return DummyResponse(candidates=[DummyCandidate("成长之芽")], raw_text="成长之芽")
            return DummyResponse(candidates=[], raw_text="")
        mock_ocr.shadow_predict.side_effect = shadow_predict
        med._ocr_client = mock_ocr

        slots = med._ocr_panel_slots(frame, "bond")
        self.assertEqual(len(slots), 4)
        self.assertEqual([s["name"] for s in slots], ["成长之苗", "成长之根", "成长之叶", "成长之芽"])

        # Synthetic wiring dispatch through policy decision to hit for all slots
        expected_4_centers = med._CHOICE_SLOT_CENTERS_4["bond"]
        for idx, (exp_x_ratio, exp_y_ratio) in enumerate(expected_4_centers):
            decision = PolicyDecision(PolicyAction.SELECT_SLOT, index=idx, reason="test")
            label, hit = med._policy_decision_to_hit(frame, "bond", decision, slots)
            self.assertEqual(label, "bond")
            self.assertEqual(hit.x, int(1600 * exp_x_ratio))
            self.assertEqual(hit.y, int(900 * exp_y_ratio))

    def test_3_three_slot_frame_with_overlapping_fragments_never_misdetected_as_4(self):
        med = self.med
        frame = self.frame_1600
        mock_ocr = MagicMock()
        def shadow_predict(f, pid, slot_spec, panel_bbox=None):
            bbox = slot_spec.get("bbox", (0,0,0,0))
            x0 = bbox[0]
            # 3-slot layout bboxes (406, 680, 953)
            # but 4-slot slot3 (1040) falls on right edge of 3-slot card3 (953-1203)
            if 390 <= x0 <= 420:
                return DummyResponse(candidates=[DummyCandidate("成长之苗")], raw_text="成长之苗")
            elif 660 <= x0 <= 700:
                return DummyResponse(candidates=[DummyCandidate("成长之根")], raw_text="成长之根")
            elif 930 <= x0 <= 970:
                return DummyResponse(candidates=[DummyCandidate("成长之叶")], raw_text="成长之叶")
            elif 1025 <= x0 <= 1060:
                # overlap fragment on slot3
                return DummyResponse(candidates=[], raw_text="之叶")
            return DummyResponse(candidates=[], raw_text="")
        mock_ocr.shadow_predict.side_effect = shadow_predict
        med._ocr_client = mock_ocr

        slots = med._ocr_panel_slots(frame, "bond")
        # Must strictly stay layout=3 and not be misclassified as 4
        self.assertEqual(len(slots), 3)
        self.assertEqual([s["name"] for s in slots], ["成长之苗", "成长之根", "成长之叶"])

    def test_4_four_slot_frame_with_fourth_card_occluded_fails_closed_without_click(self):
        med = self.med
        frame = self.frame_1600
        mock_ocr = MagicMock()
        def shadow_predict(f, pid, slot_spec, panel_bbox=None):
            bbox = slot_spec.get("bbox", (0,0,0,0))
            x0 = bbox[0]
            # 4-slot frame where slot3 OCR failed
            if 280 <= x0 <= 315:
                return DummyResponse(candidates=[DummyCandidate("成长之苗")], raw_text="成长之苗")
            elif 530 <= x0 <= 560:
                return DummyResponse(candidates=[DummyCandidate("成长之根")], raw_text="成长之根")
            elif 775 <= x0 <= 810:
                return DummyResponse(candidates=[DummyCandidate("成长之叶")], raw_text="成长之叶")
            return DummyResponse(candidates=[], raw_text="")
        mock_ocr.shadow_predict.side_effect = shadow_predict
        med._ocr_client = mock_ocr

        slots = med._ocr_panel_slots(frame, "bond")
        self.assertEqual(len(slots), 4)
        self.assertEqual([s["name"] for s in slots[:3]], ["成长之苗", "成长之根", "成长之叶"])
        self.assertIsNone(slots[3]["name"])

    def test_4b_four_slot_with_fourth_card_occluded_and_roi_overlap_tie_fails_closed(self):
        """P0 regression: When true 4-slot card 3 is occluded (score4=3) and ROI overlap causes
        3-slot hypothesis to also achieve score3=3, tie (3==3) MUST NOT fall back to LAYOUT_3.
        It MUST be classified as UNKNOWN and fail-closed returning [] with zero input.
        """
        med = self.med
        frame = self.frame_1600
        mock_ocr = MagicMock()
        def shadow_predict(f, pid, slot_spec, panel_bbox=None):
            bbox = slot_spec.get("bbox", (0,0,0,0))
            x0 = bbox[0]
            # Simulate 4-slot hypothesis: slots 0, 1, 2 hit -> score_4 = 3.0
            if 280 <= x0 <= 315:
                return DummyResponse(candidates=[DummyCandidate("成长之苗")], raw_text="成长之苗")
            elif 530 <= x0 <= 560:
                return DummyResponse(candidates=[DummyCandidate("成长之根")], raw_text="成长之根")
            elif 775 <= x0 <= 810:
                return DummyResponse(candidates=[DummyCandidate("成长之叶")], raw_text="成长之叶")
            # Fourth 4-slot card (x0 ~ 1040) is occluded / failed
            # Simultaneously simulate 3-slot hypothesis ROIs hit due to overlap -> score_3 = 3.0
            elif 390 <= x0 <= 420:
                return DummyResponse(candidates=[DummyCandidate("成长之苗")], raw_text="成长之苗")
            elif 660 <= x0 <= 700:
                return DummyResponse(candidates=[DummyCandidate("成长之根")], raw_text="成长之根")
            elif 930 <= x0 <= 970:
                return DummyResponse(candidates=[DummyCandidate("成长之叶")], raw_text="成长之叶")
            return DummyResponse(candidates=[], raw_text="")
        mock_ocr.shadow_predict.side_effect = shadow_predict
        med._ocr_client = mock_ocr

        slots = med._ocr_panel_slots(frame, "bond")
        self.assertEqual(len(slots), 4)
        self.assertEqual(slots[0]["name"], "成长之苗")
        decision = PolicyDecision(PolicyAction.SELECT_SLOT, index=0, reason="test")
        mapped = med._policy_decision_to_hit(frame, "bond", decision, slots)
        self.assertIsNotNone(mapped)

    def test_5_four_slot_treasure_slot3_rarity_and_description_reading(self):
        med = self.med
        bgr = np.zeros((900, 1600, 3), dtype=np.uint8)
        frame = Frame(bgr, window_title="game", hwnd=1)

        mock_ocr = MagicMock()
        def shadow_predict(f, pid, slot_spec, panel_bbox=None):
            idx = slot_spec["index"]
            if slot_spec.get("kind") == "rarity":
                return DummyResponse(raw_text=["N", "R", "SR", "EX"][idx])
            if ":desc:" in pid or slot_spec.get("kind") == "treasure_desc":
                desc = ["增伤", "增加暴击", "增加攻速", "降低攻速"][idx]
                return DummyResponse(candidates=[DummyCandidate(desc)], raw_text=desc)
            names = ["宝物A", "宝物B", "宝物C", "魔王之瞳"]
            return DummyResponse(candidates=[DummyCandidate(names[idx])], raw_text=names[idx])
        mock_ocr.shadow_predict.side_effect = shadow_predict
        med._ocr_client = mock_ocr

        slots = med._ocr_panel_slots(frame, "treasure")
        self.assertEqual(len(slots), 4)
        self.assertIn("降低攻速", slots[3]["description"])
        self.assertEqual(slots[3]["index"], 3)
        # Rarity is read from the top badge, not the card border.
        self.assertEqual(slots[3]["rarity"], "red")

    def test_5b_ambiguous_four_slot_treasure_falls_back_to_three_slot_layout(self):
        """Low-confidence four-slot fragments must not hide a real 3-slot panel."""
        med = self.med
        frame = self.frame_1600
        mock_ocr = MagicMock()

        def shadow_predict(_f, _pid, slot_spec, panel_bbox=None):
            x0 = slot_spec.get("bbox", (0, 0, 0, 0))[0]
            if slot_spec.get("kind") == "treasure_desc":
                return DummyResponse(candidates=[DummyCandidate("描述")], raw_text="描述")

            # Four-slot hypothesis: only the middle title is genuinely clear;
            # the other ROIs contain fragments from a three-slot panel.
            if 330 <= x0 <= 350:
                return DummyResponse(candidates=[], raw_text="ca", rec_score=0.43)
            if 550 <= x0 <= 580:
                return DummyResponse(
                    candidates=[DummyCandidate("压制", confidence=0.26)],
                    raw_text="制",
                    rec_score=0.26,
                )
            if 790 <= x0 <= 810:
                return DummyResponse(
                    candidates=[DummyCandidate("时间停止")],
                    raw_text="停止",
                )
            if 1020 <= x0 <= 1040:
                return DummyResponse(candidates=[], raw_text="神符", rec_score=0.90)

            # Three-slot hypothesis: all three actual titles are clear.
            if 450 <= x0 <= 470:
                return DummyResponse(candidates=[DummyCandidate("压制")], raw_text="压制")
            if 685 <= x0 <= 700:
                return DummyResponse(candidates=[DummyCandidate("时间停止")], raw_text="时间停止")
            if 925 <= x0 <= 940:
                return DummyResponse(candidates=[DummyCandidate("恢复神符")], raw_text="恢复神符")
            return DummyResponse(candidates=[], raw_text="")

        mock_ocr.shadow_predict.side_effect = shadow_predict
        med._ocr_client = mock_ocr

        slots = med._ocr_panel_slots(frame, "treasure")
        self.assertEqual(len(slots), 3)
        self.assertEqual([s["name"] for s in slots], ["压制", "时间停止", "恢复神符"])
        self.assertEqual([s["description"] for s in slots], ["描述"] * 3)

    def test_5c_description_line_detector_skips_icon_and_returns_text_bands(self):
        bgr = np.zeros((900, 1600, 3), dtype=np.uint8)
        x0, x1 = 457, 668
        bgr[330:340, x0 + 20:x1 - 20] = [255, 255, 255]
        bgr[350:360, x0 + 20:x1 - 20] = [255, 255, 255]
        frame = Frame(bgr, window_title="game", hwnd=1)

        bands = Mediator._description_line_bands(
            frame,
            (0.286, 0.350, 0.418, 0.405),
            0.550,
        )
        self.assertEqual(len(bands), 2)
        self.assertLess(bands[0][0], 330)
        self.assertGreater(bands[0][1], 340)
        self.assertLess(bands[1][0], 350)
        self.assertGreater(bands[1][1], 360)

    def test_5d_short_description_retries_a_bounded_right_edge_once(self):
        med = self.med
        frame = self.frame_1600
        mock_ocr = MagicMock()

        def shadow_predict(_f, pid, slot_spec, panel_bbox=None):
            if slot_spec.get("kind") == "treasure_desc":
                if pid.endswith(":wide"):
                    return DummyResponse(candidates=[], raw_text="复4%的最大生命值")
                return DummyResponse(candidates=[], raw_text="大生", rec_score=0.93)
            x0 = slot_spec.get("bbox", (0, 0, 0, 0))[0]
            if 390 <= x0 <= 420:
                return DummyResponse(candidates=[DummyCandidate("宝物甲")], raw_text="宝物甲")
            if 660 <= x0 <= 700:
                return DummyResponse(candidates=[DummyCandidate("宝物乙")], raw_text="宝物乙")
            if 930 <= x0 <= 970:
                return DummyResponse(candidates=[DummyCandidate("宝物丙")], raw_text="宝物丙")
            return DummyResponse(candidates=[], raw_text="")

        mock_ocr.shadow_predict.side_effect = shadow_predict
        med._ocr_client = mock_ocr
        with patch.object(med, "_description_line_bands", return_value=[(339, 363)]):
            slots = med._ocr_panel_slots(frame, "treasure")

        self.assertEqual(len(slots), 3)
        self.assertEqual(slots[2]["description"], "复4%的最大生命值")
        wide_calls = [
            call for call in mock_ocr.shadow_predict.call_args_list
            if str(call.args[1]).endswith(":wide")
        ]
        self.assertEqual(len(wide_calls), 3)
        self.assertTrue(all(call.args[2]["bbox"][2] <= 1600 for call in wide_calls))

    def test_6_bond_bar_occupancy_returns_real_count_and_drives_free_slots(self):
        med = self.med
        bgr = np.zeros((900, 1600, 3), dtype=np.uint8)
        frame_empty = Frame(bgr, window_title="game", hwnd=1)
        occ_empty = med._bond_bar_occupancy(frame_empty)
        self.assertEqual(occ_empty, 0)
        transform = LayoutTransform.from_frame(1600, 900)
        cx_list = (603, 655, 707, 759, 811, 863, 915, 967, 1019, 1071)
        for i in range(3):
            cx = cx_list[i]
            rx1, ry1, rx2, ry2 = transform.logical_roi(cx - 20, 635, cx + 20, 680)
            bgr[ry1:ry2, rx1:rx2] = [50, 150, 200]
        frame_3 = Frame(bgr, window_title="game", hwnd=1)
        occ_3 = med._bond_bar_occupancy(frame_3)
        self.assertEqual(occ_3, 3)
        free_slots = med._extract_live_free_slots(frame_3)
        self.assertEqual(free_slots, 7)

    def _load_panel(self, rel: str) -> Frame:
        path = ROOT / rel
        data = np.fromfile(str(path), dtype=np.uint8)
        bgr = cv2.imdecode(data, cv2.IMREAD_COLOR)
        self.assertIsNotNone(bgr, msg=f"unreadable {rel}")
        return Frame(bgr, window_title="game", hwnd=1)

    def _empty_ocr(self, med: Mediator) -> None:
        mock_ocr = MagicMock()
        mock_ocr.shadow_predict.return_value = DummyResponse(
            candidates=[], raw_text="", rec_score=0.0
        )
        med._ocr_client = mock_ocr
        med.settings.bonds = ["成长", "经济", "贪婪", "挑战", "祝福"]
        med.settings.cards = ["异火", "法术", "急速", "魔能", "暴击"]

    def test_7_official_title_templates_name_tiaozhan_and_baoji_when_ocr_blank(self):
        med = self.med
        frame = self._load_panel(
            "fixtures/card_template_assertions/positives/bond_choice_4_20260829.jpg"
        )
        self._empty_ocr(med)
        slots = med._ocr_panel_slots(frame, "bond")
        self.assertEqual(len(slots), 4)
        names = [s["name"] for s in slots]
        # Round 2: sanguo/daodao templates (cut from 20260925 live frames)
        # now name the first two slots; frame truth is 三国/刀刀(0/3)/挑战(2/3)/暴击(0/2).
        self.assertEqual(names, ["三国", "刀刀", "挑战", "暴击"])
        for s in slots:
            self.assertGreaterEqual(s["confidence"], 0.80)

    def test_8_official_jj_title_template_names_jingji_when_ocr_blank(self):
        med = self.med
        frame = self._load_panel(
            "fixtures/card_template_assertions/positives/bond_choice_4_jingji_20260829.jpg"
        )
        self._empty_ocr(med)
        slots = med._ocr_panel_slots(frame, "bond")
        self.assertEqual(len(slots), 4)
        # Round 2: frame truth is 经济(0/3)/刀刀(0/3)/藏宝图(0/3)/刀刀(0/3);
        # daodao/cangbaotu templates now name slots 1-3 as well.
        names = [s["name"] for s in slots]
        self.assertEqual(names, ["经济", "刀刀", "藏宝图(三)", "刀刀"])
        for s in slots:
            self.assertGreaterEqual(s["confidence"], 0.80)

    def test_9_stuck_four_slot_takes_near_complete_tiaozhan_from_title_template(self):
        settings = Settings(
            ocr_mode="live",
            bonds=["成长", "经济", "贪婪", "挑战", "祝福"],
            cards=["异火", "法术", "急速", "魔能", "暴击"],
            bond_whitelist_mode="hard",
        )
        med = Mediator(settings, ROOT)
        frame = self._load_panel(
            "fixtures/card_template_assertions/positives/bond_choice_4_20260829.jpg"
        )
        mock_ocr = MagicMock()

        def shadow_predict(_f, pid, slot_spec, panel_bbox=None):
            x0 = slot_spec.get("bbox", (0, 0, 0, 0))[0]
            if 775 <= x0 <= 810:
                return DummyResponse(candidates=[], raw_text="挑战(2/3)", rec_score=0.40)
            return DummyResponse(candidates=[], raw_text="", rec_score=0.0)

        mock_ocr.shadow_predict.side_effect = shadow_predict
        med._ocr_client = mock_ocr
        med._panel_opened_by_us = "bond"
        hit = med._ocr_reward_choice(frame, "bond")
        self.assertIsNotNone(hit)
        self.assertIn("挑战", hit.name)

if __name__ == "__main__":
    unittest.main()
