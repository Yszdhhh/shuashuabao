"""Unit tests for template-based card slot matcher (match_card_slots_by_template)."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import cv2
import numpy as np

from shuabao.vision.capture import Frame
from shuabao.vision.matcher import (
    clear_template_cache,
    match_card_slots_by_template,
    _CARD_FAMILY_TEMPLATES_CACHE,
)

ROOT = Path(__file__).resolve().parents[1]
IMAGES_DIR = ROOT / "assets" / "Images"
FETTER_LABELS = json.loads((ROOT / "config" / "fetter_labels.json").read_text(encoding="utf-8"))


def _load_frame(path: Path) -> Frame:
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    return Frame(img)


class CardSlotTemplateMatcherTests(unittest.TestCase):
    def setUp(self):
        clear_template_cache()

    def tearDown(self):
        clear_template_cache()

    def test_3_slot_positive_bond_choice(self):
        f = _load_frame(ROOT / "fixtures/card_template_assertions/positives/bond_choice_3.png")
        res = match_card_slots_by_template(f, IMAGES_DIR, kind="bond", fetter_labels=FETTER_LABELS)
        self.assertIsNotNone(res)
        slot_count, slots = res
        self.assertEqual(slot_count, 3)
        self.assertEqual(len(slots), 3)
        for s in slots:
            self.assertEqual(s["name"], "祝福")
            self.assertGreaterEqual(s["confidence"], 0.90)
            self.assertEqual(s["source"], "template")

    def test_3_slot_positive_bond_panel(self):
        f = _load_frame(ROOT / "fixtures/card_template_assertions/positives/bond_panel.png")
        res = match_card_slots_by_template(f, IMAGES_DIR, kind="bond", fetter_labels=FETTER_LABELS)
        self.assertIsNotNone(res)
        slot_count, slots = res
        self.assertEqual(slot_count, 3)
        self.assertEqual(len(slots), 3)
        for s in slots:
            self.assertEqual(s["name"], "祝福")
            self.assertGreaterEqual(s["confidence"], 0.90)

    def test_negative_black_frame(self):
        f = _load_frame(ROOT / "fixtures/card_template_assertions/negatives/black_frame.png")
        res = match_card_slots_by_template(f, IMAGES_DIR, kind="bond", fetter_labels=FETTER_LABELS)
        self.assertIsNone(res)

    def test_negative_idle_hud(self):
        f = _load_frame(ROOT / "fixtures/card_template_assertions/negatives/idle_hud.png")
        res = match_card_slots_by_template(f, IMAGES_DIR, kind="bond", fetter_labels=FETTER_LABELS)
        self.assertIsNone(res)

    def test_treasure_panel_does_not_false_fire_as_bond(self):
        f = _load_frame(ROOT / "fixtures/card_template_assertions/positives/treasure_panel.png")
        res = match_card_slots_by_template(f, IMAGES_DIR, kind="bond", fetter_labels=FETTER_LABELS)
        self.assertIsNone(res)

    def test_non_bond_kind_returns_none(self):
        f = _load_frame(ROOT / "fixtures/card_template_assertions/positives/bond_choice_3.png")
        res = match_card_slots_by_template(f, IMAGES_DIR, kind="treasure", fetter_labels=FETTER_LABELS)
        self.assertIsNone(res)

    def test_none_frame_returns_none(self):
        res = match_card_slots_by_template(None, IMAGES_DIR, kind="bond", fetter_labels=FETTER_LABELS)
        self.assertIsNone(res)

    def test_cache_clearing(self):
        f = _load_frame(ROOT / "fixtures/card_template_assertions/positives/bond_choice_3.png")
        match_card_slots_by_template(f, IMAGES_DIR, kind="bond", fetter_labels=FETTER_LABELS)
        self.assertGreater(len(_CARD_FAMILY_TEMPLATES_CACHE), 0)
        clear_template_cache()
        self.assertEqual(len(_CARD_FAMILY_TEMPLATES_CACHE), 0)


if __name__ == "__main__":
    unittest.main()
