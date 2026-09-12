"""2026-09-12 live run: a three-card treasure panel read as four slots.

The 3-slot scan read the whole titles 双倍神符 / 提高上限 / 木材梭哈; the 4-slot
scan read ""/申符/上限/梭哈 and fuzzy-matched 梭哈 to 杀敌梭哈.  Both layouts
named one card, the tie went to layout 4, no talisman was visible there, and
the passenger hid the panel on every open.  The OCR responses below are the
recorded live outputs for this exact frame.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.choice_policy import hitch_treasure_pick
from shuabao.mediator import Mediator
from shuabao.settings import Settings
from shuabao.vision.capture import Frame

FRAME = ROOT / "fixtures" / "treasure_layout_20260912" / "double_rune_3card_1600x900.jpg"


class _Candidate:
    def __init__(self, name, confidence):
        self.name = name
        self.confidence = confidence


class _Response:
    def __init__(self, raw_text="", rec_score=0.0, candidates=()):
        self.raw_text = raw_text
        self.rec_score = rec_score
        self.candidates = list(candidates)
        self.status = "ok"
        self.reason = None


LIVE_TITLES_4 = {
    0: _Response("", 0.0),
    1: _Response("申符", 0.83),
    2: _Response("上限", 0.99),
    3: _Response("梭哈", 0.98, [_Candidate("杀敌梭哈", 0.98)]),
}
LIVE_TITLES_3 = {
    0: _Response("双倍神符", 0.98, [_Candidate("双倍神符", 0.98), _Candidate("全能神符", 0.5)]),
    1: _Response("提高上限", 0.99),
    2: _Response("木材梭哈", 0.93),
}


def _live_ocr():
    def shadow_predict(_frame, pid, slot_spec, panel_bbox=None):
        if ":desc:" in pid:
            return _Response()
        table = LIVE_TITLES_4 if pid.endswith(":4s") else LIVE_TITLES_3
        return table[slot_spec["index"]]

    ocr = MagicMock()
    ocr.shadow_predict.side_effect = shadow_predict
    return ocr


class TreasureLayoutTieTest(unittest.TestCase):
    def setUp(self):
        bgr = cv2.imdecode(np.fromfile(str(FRAME), dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertIsNotNone(bgr)
        self.frame = Frame(bgr, window_title="英雄三国KK", hwnd=1)
        self.med = Mediator(Settings(mode_id="lobby_hitch", ocr_mode="live"), ROOT)
        self.med._ocr_client = _live_ocr()

    def test_whole_titles_break_the_tie_toward_three_slots(self):
        slots = self.med._ocr_panel_slots(self.frame, "treasure")

        self.assertEqual(len(slots), 3)
        self.assertEqual(slots[0]["name"], "双倍神符")
        self.assertEqual(slots[0]["rarity"], "green")

    def test_passenger_takes_the_double_rune(self):
        slots_raw = self.med._ocr_panel_slots(self.frame, "treasure")
        candidates = self.med._slots_to_candidates(self.frame, "treasure", slots_raw)

        pick, _reason = hitch_treasure_pick(candidates, self.med._policy_settings())

        self.assertIsNotNone(pick)
        self.assertEqual(pick.index, 0)
        self.assertEqual(pick.name, "双倍神符")


if __name__ == "__main__":
    unittest.main()
