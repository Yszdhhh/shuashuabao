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

    def test_a_three_slot_ocr_and_click_legacy_centers(self):
        med = self.med
        frame = self.frame_1600
        hit0 = med._choice_slot_hit(frame, "bond", 0, "卡1", slot_count=3)
        hit1 = med._choice_slot_hit(frame, "bond", 1, "卡2", slot_count=3)
        hit2 = med._choice_slot_hit(frame, "bond", 2, "卡3", slot_count=3)
        self.assertEqual(hit0.x, int(1600 * 0.331))
        self.assertEqual(hit1.x, int(1600 * 0.503))
        self.assertEqual(hit2.x, int(1600 * 0.676))

    def test_b_four_slot_ocr_recognizes_fourth_card(self):
        med = self.med
        frame = self.frame_1600
        mock_ocr = MagicMock()
        def shadow_predict(f, pid, slot_spec, panel_bbox=None):
            idx = slot_spec["index"]
            names = ["成长之苗", "成长之根", "成长之叶", "成长之芽"]
            return DummyResponse(candidates=[DummyCandidate(names[idx])], raw_text=names[idx])
        mock_ocr.shadow_predict.side_effect = shadow_predict
        med._ocr_client = mock_ocr
        slots = med._ocr_panel_slots(frame, "bond")
        self.assertEqual(len(slots), 4)
        self.assertEqual(slots[3]["name"], "成长之芽")
        self.assertEqual(slots[3]["index"], 3)

    def test_c_four_slot_clicks_all_hit_four_slot_centers(self):
        med = self.med
        frame = self.frame_1600
        hit0 = med._choice_slot_hit(frame, "bond", 0, "卡0", slot_count=4)
        hit1 = med._choice_slot_hit(frame, "bond", 1, "卡1", slot_count=4)
        hit2 = med._choice_slot_hit(frame, "bond", 2, "卡2", slot_count=4)
        hit3 = med._choice_slot_hit(frame, "bond", 3, "卡3", slot_count=4)
        self.assertEqual(hit0.x, int(1600 * 0.255))
        self.assertEqual(hit1.x, int(1600 * 0.410))
        self.assertEqual(hit2.x, int(1600 * 0.565))
        self.assertEqual(hit3.x, int(1600 * 0.720))

    def test_d_four_slot_treasure_slot3_rarity_and_description_reading(self):
        med = self.med
        frame = self.frame_1600
        mock_ocr = MagicMock()
        def shadow_predict(f, pid, slot_spec, panel_bbox=None):
            idx = slot_spec["index"]
            if slot_spec.get("kind") == "treasure_desc":
                desc = ["增伤", "增加暴击", "增加攻速", "降低攻速"][idx]
                return DummyResponse(candidates=[DummyCandidate(desc)], raw_text=desc)
            names = ["宝物A", "宝物B", "宝物C", "魔王之瞳"]
            return DummyResponse(candidates=[DummyCandidate(names[idx])], raw_text=names[idx])
        def read_description(f, bbox):
            return DummyResponse(text="降低攻速", raw_text="降低攻速")
        mock_ocr.shadow_predict.side_effect = shadow_predict
        mock_ocr.read_description.side_effect = read_description
        med._ocr_client = mock_ocr
        slots = med._ocr_panel_slots(frame, "treasure")
        self.assertEqual(len(slots), 4)
        self.assertIn("降低攻速", slots[3]["description"])
        self.assertEqual(slots[3]["index"], 3)

    def test_e_bond_bar_occupancy_returns_real_count_and_drives_free_slots(self):
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