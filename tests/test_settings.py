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

        # 2. 32633f4 真实 bool 行为：None/[]/{} 以及数值 0/1 的 bool(v) 转换
        s_bool_dict = Settings._from_dict({"auto_create_room": {}})
        self.assertFalse(s_bool_dict.auto_create_room)

        s_bool_list = Settings._from_dict({"auto_create_room": []})
        self.assertFalse(s_bool_list.auto_create_room)

        s_bool_none = Settings._from_dict({"auto_create_room": None})
        self.assertFalse(s_bool_none.auto_create_room)

        s_bool_zero = Settings._from_dict({"auto_create_room": 0})
        self.assertFalse(s_bool_zero.auto_create_room)

        s_bool_one = Settings._from_dict({"auto_create_room": 1})
        self.assertTrue(s_bool_one.auto_create_room)

        # 未知字符串回落 dataclass default (auto_create_room default=True)
        s_bool_unknown_str = Settings._from_dict({"auto_create_room": "invalid_string"})
        self.assertTrue(s_bool_unknown_str.auto_create_room)

        # 3. 32633f4 真实 string / 未在已知清洗列表中的字段行为，无兼容漂移
        s_legacy_passthrough = Settings._from_dict({
            "room_name": 123,
            "images_dir": None,
            "skills": None,
            "stage_targets": "not_a_dict",
            "skill_archive_levels": [],
            "treasure_allow_negative": "not_a_list",
            "ocr_mode": 12345,
        })
        self.assertEqual(s_legacy_passthrough.room_name, 123)
        self.assertIsNone(s_legacy_passthrough.images_dir)
        self.assertEqual(s_legacy_passthrough.skills, [])
        self.assertEqual(s_legacy_passthrough.stage_targets, "not_a_dict")
        self.assertEqual(s_legacy_passthrough.skill_archive_levels, {})
        self.assertEqual(s_legacy_passthrough.treasure_allow_negative, [])
        self.assertEqual(s_legacy_passthrough.ocr_mode, "off")

    def test_from_dict_truncates_skills_to_four(self):
        """解析边界集中截断：5+ 技能只保留前 4 个（保序）。"""
        s = Settings._from_dict({"skills": ["a", "b", "c", "d", "e", "f"]})
        self.assertEqual(["a", "b", "c", "d"], s.skills)

    def test_from_dict_skills_empty_none_and_fallback(self):
        """空/None 技能回落空列表；fallback 模式 overlay 同样截断且不污染 base。"""
        self.assertEqual([], Settings._from_dict({"skills": []}).skills)
        self.assertEqual([], Settings._from_dict({"skills": None}).skills)
        base = Settings(skills=["x"])
        out = Settings._from_dict(
            {"skills": ["a", "b", "c", "d", "e"]}, fallback=base
        )
        self.assertEqual(["a", "b", "c", "d"], out.skills)
        self.assertEqual(["x"], base.skills)

    def test_non_dict_input_is_safe(self):
        # 无 fallback：非 dict 输入返回安全的默认 Settings()
        self.assertEqual(Settings._from_dict(None), Settings())
        self.assertEqual(Settings._from_dict(["not_a_dict"]), Settings())
        self.assertEqual(Settings._from_dict(12345), Settings())

        # 有 fallback：非 dict 输入返回 fallback 的副本，对象独立且值相等
        base = Settings(round_timeout_s=123, room_name="base_room")
        out_none = Settings._from_dict(None, fallback=base)
        self.assertIsNot(out_none, base)
        self.assertEqual(out_none, base)

        out_list = Settings._from_dict(["not_a_dict"], fallback=base)
        self.assertIsNot(out_list, base)
        self.assertEqual(out_list, base)

    def test_fallback_invalid_bool_retains_base(self):
        base_false = Settings(auto_create_room=False)
        base_true = Settings(auto_create_room=True)
        for invalid in ([], {}, "invalid_bool", None):
            with self.subTest(invalid=invalid):
                out_false = Settings._from_dict({"auto_create_room": invalid}, fallback=base_false)
                self.assertFalse(out_false.auto_create_room)
                out_true = Settings._from_dict({"auto_create_room": invalid}, fallback=base_true)
                self.assertTrue(out_true.auto_create_room)

    def test_fallback_all_none_treated_as_missing_retains_base(self):
        # fallback 模式下所有 None 视为缺损 pop 保留 base，显式清空必须传合法 '' 或 []
        base = Settings(
            room_name="my_room",
            skills=["skill_a"],
            cards=["card_a"],
            stage_targets={"st": 1},
            treasure_allow_negative=["neg_card"],
            ocr_mode="live",
            auto_create_room=False,
        )
        out_none = Settings._from_dict({
            "room_name": None,
            "skills": None,
            "cards": None,
            "stage_targets": None,
            "treasure_allow_negative": None,
            "ocr_mode": None,
            "auto_create_room": None,
        }, fallback=base)
        self.assertEqual(out_none.room_name, "my_room")
        self.assertEqual(out_none.skills, ["skill_a"])
        self.assertEqual(out_none.cards, ["card_a"])
        self.assertEqual(out_none.stage_targets, {"st": 1})
        self.assertEqual(out_none.treasure_allow_negative, ["neg_card"])
        self.assertEqual(out_none.ocr_mode, "live")
        self.assertFalse(out_none.auto_create_room)

        # 显式清空验证
        out_empty = Settings._from_dict({
            "room_name": "",
            "skills": [],
            "cards": [],
            "treasure_allow_negative": [],
        }, fallback=base)
        self.assertEqual(out_empty.room_name, "")
        self.assertEqual(out_empty.skills, [])
        self.assertEqual(out_empty.cards, [])
        self.assertEqual(out_empty.treasure_allow_negative, [])

    def test_fallback_str_fields_protection(self):
        base = Settings(room_name="my_room", images_dir="assets/Images", ocr_repo_root="my_root")
        for invalid in ([], {}, 123, None):
            with self.subTest(invalid=invalid):
                out = Settings._from_dict({
                    "room_name": invalid,
                    "images_dir": invalid,
                    "ocr_repo_root": invalid,
                }, fallback=base)
                self.assertEqual(out.room_name, "my_room")
                self.assertEqual(out.images_dir, "assets/Images")
                self.assertEqual(out.ocr_repo_root, "my_root")

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

    def test_fallback_skill_archive_levels(self):
        base = Settings(skill_archive_levels={"asj": 10})
        for invalid in ([], "not_a_dict", 123, None):
            with self.subTest(invalid=invalid):
                out_invalid = Settings._from_dict({"skill_archive_levels": invalid}, fallback=base)
                self.assertEqual(out_invalid.skill_archive_levels, {"asj": 10})

        out_valid = Settings._from_dict(
            {"skill_archive_levels": {"asj": 47, "tl": -5}}, fallback=base
        )
        self.assertEqual(out_valid.skill_archive_levels, {"asj": 47})

    def test_fallback_treasure_allow_negative(self):
        base = Settings(treasure_allow_negative=["card1"])
        # tuple 视为容器清洗，按现有语义保留转为 list
        out_empty_tuple = Settings._from_dict({"treasure_allow_negative": ()}, fallback=base)
        self.assertEqual(out_empty_tuple.treasure_allow_negative, [])

        out_tuple = Settings._from_dict({"treasure_allow_negative": ("card2", "card3")}, fallback=base)
        self.assertEqual(out_tuple.treasure_allow_negative, ["card2", "card3"])

        out_list = Settings._from_dict({"treasure_allow_negative": ["card4"]}, fallback=base)
        self.assertEqual(out_list.treasure_allow_negative, ["card4"])

        for invalid in ("not_a_list", 123, {}, None):
            with self.subTest(invalid=invalid):
                out_invalid = Settings._from_dict({"treasure_allow_negative": invalid}, fallback=base)
                self.assertEqual(out_invalid.treasure_allow_negative, ["card1"])

    def test_fallback_window_size(self):
        base = Settings(window_size=[1920, 1080])
        for invalid in ([], [1600], [1600, -900], ["1600", "900"], "bad", None):
            with self.subTest(invalid=invalid):
                out = Settings._from_dict({"window_size": invalid}, fallback=base)
                self.assertEqual(out.window_size, [1920, 1080])

        out_valid = Settings._from_dict({"window_size": [1280, 720]}, fallback=base)
        self.assertEqual(out_valid.window_size, [1280, 720])

    def test_fallback_ocr_mode(self):
        base = Settings(ocr_mode="live")
        for invalid in ([], {}, 12345, "invalid_mode", None):
            with self.subTest(invalid=invalid):
                out_invalid = Settings._from_dict({"ocr_mode": invalid}, fallback=base)
                self.assertEqual(out_invalid.ocr_mode, "live")

        out_valid = Settings._from_dict({"ocr_mode": "OFF"}, fallback=base)
        self.assertEqual(out_valid.ocr_mode, "off")

        out_shadow = Settings._from_dict({"ocr_mode": "shadow"}, fallback=base)
        self.assertEqual(out_shadow.ocr_mode, "shadow")

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
