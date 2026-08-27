import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.mediator import Mediator
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
        # Ambiguous / UNKNOWN -> fail-closed returns []
        self.assertEqual(slots, [])

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
        # Strict tie (score_4=3.0, score_3=3.0): margin check fails both -> UNKNOWN -> returns []
        self.assertEqual(slots, [])
        # Ensure downstream choice policy to hit produces zero input (None)
        decision = PolicyDecision(PolicyAction.SELECT_SLOT, index=0, reason="test")
        mapped = med._policy_decision_to_hit(frame, "bond", decision, slots)
        self.assertIsNone(mapped)

    def test_5_four_slot_treasure_slot3_rarity_and_description_reading(self):
        med = self.med
        # 4-slot treasure x center for slot3 = 1600 * 0.705 = 1128, cy for treasure sample in 900 = 0.300*900 = 270
        # Card bbox width in 1600x900 is ~204x162
        bgr = np.zeros((900, 1600, 3), dtype=np.uint8)
        w, h = int(1600 * 0.128), int(900 * 0.180) # 204 x 162
        cx3, cy3 = int(1600 * 0.705), int(900 * 0.300)
        x0, y0 = cx3 - w // 2, cy3 - h // 2
        # Fill border ring with bright red/orange pixels to trigger 'red' rarity band
        bgr[y0:y0+5, x0:x0+w] = [0, 0, 255] # Red BGR
        bgr[y0+h-5:y0+h, x0:x0+w] = [0, 0, 255]
        bgr[y0:y0+h, x0:x0+5] = [0, 0, 255]
        bgr[y0:y0+h, x0+w-5:x0+w] = [0, 0, 255]
        frame = Frame(bgr, window_title="game", hwnd=1)

        mock_ocr = MagicMock()
        def shadow_predict(f, pid, slot_spec, panel_bbox=None):
            idx = slot_spec["index"]
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
        # Assert rarity is extracted and matches red
        self.assertEqual(slots[3]["rarity"], "red")

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

if __name__ == "__main__":
    unittest.main()
