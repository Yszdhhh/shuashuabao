"""A 组选卡策略 mediator 接线契约（2026-08-12）。

不改 test_choice_semantics_contract.py；本文件只锁 mediator 接线行为：
- 技能预设稀有度优先理由可见
- 羁绊硬禁用切断品质色/第一张旁路
- 宝物负面名单拦截（名字即可，描述可空）
- RARITY_BANDS 含 green
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.choice_policy import PolicyAction, choose_action  # noqa: E402
from shuabao.mediator import Mediator  # noqa: E402
from shuabao.settings import Settings  # noqa: E402
from shuabao.vision.capture import Frame  # noqa: E402
import numpy as np  # noqa: E402


def _frame(w=1600, h=900) -> Frame:
    return Frame(np.zeros((h, w, 3), dtype=np.uint8))


class A1RarityGreen(unittest.TestCase):
    def test_rarity_bands_include_green_as_lowest(self):
        bands = [b for b, _ in Mediator.RARITY_BANDS]
        self.assertIn("green", bands)
        scores = dict(Mediator.RARITY_BANDS)
        self.assertEqual(scores["green"], min(scores.values()))


class A2SkillRarityReason(unittest.TestCase):
    def test_ocr_skill_select_logs_rarity_first_reason(self):
        med = Mediator(Settings(skills=["asj", "jq"]), ROOT)
        slots = [
            {"index": 0, "name": "剑气", "confidence": 0.99, "raw_text": "剑气", "rarity": "blue", "family_source": "badge"},
            {"index": 1, "name": "奥数箭", "confidence": 0.99, "raw_text": "奥数箭", "rarity": "orange", "family_source": "badge"},
            {"index": 2, "name": "陨石", "confidence": 0.99, "raw_text": "陨石", "rarity": "red", "family_source": "badge"},
        ]
        with patch.object(med, "_ocr_panel_slots", return_value=slots), \
                patch.object(med, "_slot_rarity_band", side_effect=lambda *_a, **_k: None):
            hit = med._ocr_reward_choice(_frame(), "skill")
        self.assertIsNotNone(hit)
        self.assertEqual(hit.name, "asj")
        self.assertIn("稀有度优先", med._choice_policy_last_reason)


class A3BondHardDisableCutsBypass(unittest.TestCase):
    def test_unlisted_bond_never_uses_rarity_or_fallback(self):
        med = Mediator(Settings(ocr_mode="live", cards=[]), ROOT)
        slots = [
            {"index": 0, "name": "海盗", "confidence": 0.99, "raw_text": "海盗"},
            {"index": 1, "name": "亡灵", "confidence": 0.99, "raw_text": "亡灵"},
            {"index": 2, "name": "军团", "confidence": 0.99, "raw_text": "军团"},
        ]
        with patch.object(med, "_ocr_panel_slots", return_value=slots), \
                patch.object(med, "_find_panel_refresh", return_value=None), \
                patch.object(med, "_find_panel_giveup", return_value=None), \
                patch.object(med, "_close_current_panel", return_value=None), \
                patch.object(med, "_rarity_choice") as rarity, \
                patch.object(med, "_fallback_choice") as fallback:
            hit = med._ocr_reward_choice(_frame(), "bond")
        self.assertIsNone(hit)
        rarity.assert_not_called()
        fallback.assert_not_called()
        self.assertTrue(med._choice_policy_idle)


class A3TreasureNegativeByName(unittest.TestCase):
    def test_named_negative_treasure_not_selected_even_without_description(self):
        med = Mediator(Settings(ocr_mode="live"), ROOT)
        # 贪婪献祭在负面名单；描述留空也必须拦。
        slots = [
            {
                "index": 0,
                "name": "贪婪献祭",
                "confidence": 0.99,
                "raw_text": "贪婪献祭",
                "rarity": "orange",
                "description": "",
            },
            {
                "index": 1,
                "name": "卡牌大师",
                "confidence": 0.99,
                "raw_text": "卡牌大师",
                "rarity": "purple",
                "description": "",
            },
            {
                "index": 2,
                "name": "双倍神符",
                "confidence": 0.99,
                "raw_text": "双倍神符",
                "rarity": "green",
                "description": "",
            },
        ]
        with patch.object(med, "_ocr_panel_slots", return_value=slots), \
                patch.object(med, "_slot_rarity_band", side_effect=lambda *_a, **_k: None):
            hit = med._ocr_reward_choice(_frame(), "treasure")
        self.assertIsNotNone(hit)
        self.assertNotIn("贪婪献祭", hit.name)
        self.assertTrue(
            "卡牌大师" in hit.name or "双倍神符" in hit.name,
            f"应选非负面候选，实际 {hit.name}",
        )

    def test_desc_roi_constants_cover_desc2_calibration(self):
        spec = Mediator._OCR_DESC_ROIS["treasure"]
        # desc2 回投：y0≈0.275 / y1≈0.416 / half_w≈0.086（1609x931 面板）
        self.assertLessEqual(spec["y0"], 0.280)
        self.assertGreaterEqual(spec["y1"], 0.415)
        self.assertGreaterEqual(spec["half_w"], 0.085)
        self.assertEqual(spec["centers_x"], (0.348, 0.497, 0.646))

    def test_descriptions_json_names_match_policy_defaults(self):
        import json
        from shuabao.choice_policy import DEFAULT_NEGATIVE_NAMES

        data = json.loads((ROOT / "fixtures/treasure_negative/DESCRIPTIONS.json").read_text(encoding="utf-8"))
        names = set(data["cards"])
        self.assertTrue(set(DEFAULT_NEGATIVE_NAMES) <= names)


class A3FallbackDisabled(unittest.TestCase):
    def test_fallback_choice_returns_none(self):
        med = Mediator(Settings(), ROOT)
        self.assertIsNone(med._fallback_choice(_frame(), "treasure"))
        self.assertIsNone(med._fallback_choice(_frame(), "bond"))
        self.assertIsNone(med._rarity_choice(_frame(), "bond"))


if __name__ == "__main__":
    unittest.main()
