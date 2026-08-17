"""Settings._from_dict 及其 fallback 机制单测。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gamescript.settings import Settings  # noqa: E402


class SettingsFromDictTests(unittest.TestCase):
    def test_no_fallback_behavior_unchanged(self):
        # 1. 基础转换与默认值
        s = Settings._from_dict({"round_timeout_s": "900", "stage1": "5"})
        self.assertEqual(s.round_timeout_s, 900)
        self.assertEqual(s.stage1, 5)
        self.assertEqual(s.ocr_mode, "off")
        self.assertTrue(s.auto_create_room)

        # 2. 非法容器 / None 的安全默认行为
        s_none = Settings._from_dict(None)
        self.assertEqual(s_none, Settings())

        s_bad_type = Settings._from_dict(["not_a_dict"])
        self.assertEqual(s_bad_type, Settings())

        s_invalid_types = Settings._from_dict({
            "round_timeout_s": [],
            "match_threshold": {},
            "skills": None,
            "skill_archive_levels": [],
            "treasure_allow_negative": "not_a_list",
            "ocr_mode": 12345,
            "auto_create_room": {},
            "stage_targets": "not_a_dict",
        })
        self.assertEqual(s_invalid_types.round_timeout_s, 900)
        self.assertEqual(s_invalid_types.match_threshold, 0.85)
        self.assertEqual(s_invalid_types.skills, [])
        self.assertEqual(s_invalid_types.skill_archive_levels, {})
        self.assertEqual(s_invalid_types.treasure_allow_negative, [])
        self.assertEqual(s_invalid_types.ocr_mode, "off")
        self.assertTrue(s_invalid_types.auto_create_room)
        self.assertEqual(s_invalid_types.stage_targets, "not_a_dict")

    def test_fallback_invalid_bool_retains_base(self):
        base_false = Settings(auto_create_room=False)
        base_true = Settings(auto_create_room=True)
        for invalid in ([], {}, "invalid_bool", None):
            with self.subTest(invalid=invalid):
                out_false = Settings._from_dict({"auto_create_room": invalid}, fallback=base_false)
                self.assertFalse(out_false.auto_create_room)
                out_true = Settings._from_dict({"auto_create_room": invalid}, fallback=base_true)
                self.assertTrue(out_true.auto_create_room)

    def test_fallback_round_timeout_s(self):
        base = Settings(round_timeout_s=123)
        for invalid in ([], {}, "bad", None):
            with self.subTest(invalid=invalid):
                out = Settings._from_dict({"round_timeout_s": invalid}, fallback=base)
                self.assertEqual(out.round_timeout_s, 123)
        # 合法 string / coercion
        self.assertEqual(Settings._from_dict({"round_timeout_s": "900"}, fallback=base).round_timeout_s, 900)
        # clamp 钳制 (min 60)
        self.assertEqual(Settings._from_dict({"round_timeout_s": 1}, fallback=base).round_timeout_s, 60)
        # clamp 钳制 (max 7200)
        self.assertEqual(Settings._from_dict({"round_timeout_s": 99999}, fallback=base).round_timeout_s, 7200)

    def test_fallback_string_retains_base(self):
        base = Settings(room_name="my_room", ocr_mode="live")
        for invalid in ([], {}):
            with self.subTest(invalid=invalid):
                out = Settings._from_dict({"room_name": invalid}, fallback=base)
                self.assertEqual(out.room_name, "my_room")

    def test_fallback_skill_archive_levels(self):
        base = Settings(skill_archive_levels={"asj": 10})
        out_invalid = Settings._from_dict({"skill_archive_levels": []}, fallback=base)
        self.assertEqual(out_invalid.skill_archive_levels, {"asj": 10})

        out_valid = Settings._from_dict(
            {"skill_archive_levels": {"asj": 47, "tl": -5}}, fallback=base
        )
        self.assertEqual(out_valid.skill_archive_levels, {"asj": 47})

    def test_fallback_treasure_allow_negative(self):
        base = Settings(treasure_allow_negative=["card1"])
        # tuple 视为容器清洗，按现有语义变 []
        out_tuple = Settings._from_dict({"treasure_allow_negative": ()}, fallback=base)
        self.assertEqual(out_tuple.treasure_allow_negative, [])

        out_list = Settings._from_dict({"treasure_allow_negative": ["card2"]}, fallback=base)
        self.assertEqual(out_list.treasure_allow_negative, ["card2"])

    def test_fallback_ocr_mode(self):
        base = Settings(ocr_mode="live")
        out_invalid = Settings._from_dict({"ocr_mode": []}, fallback=base)
        self.assertEqual(out_invalid.ocr_mode, "live")

        out_valid = Settings._from_dict({"ocr_mode": "OFF"}, fallback=base)
        self.assertEqual(out_valid.ocr_mode, "off")

    def test_fallback_dataclass_default_value_accepted(self):
        base = Settings(auto_create_room=False)
        out = Settings._from_dict({"auto_create_room": True}, fallback=base)
        self.assertTrue(out.auto_create_room)

    def test_fallback_unrelated_stage1_retained(self):
        base = Settings(stage1=0, round_timeout_s=123)
        out = Settings._from_dict({"round_timeout_s": 900}, fallback=base)
        self.assertEqual(out.stage1, 0)
        self.assertEqual(out.round_timeout_s, 900)


if __name__ == "__main__":
    unittest.main()
