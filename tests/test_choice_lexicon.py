"""B2-3 词典归一化单测：config/choice_lexicon.json + choice_ocr 纯函数。"""

import json
import unittest
from pathlib import Path

from gamescript.vision.choice_ocr import (
    DEFAULT_MARGIN_THRESHOLD,
    LEXICON_PATH,
    lexicon_errors,
    load_lexicon,
    lookup_lexicon,
    normalize_choice_text,
)

ROOT = Path(__file__).resolve().parents[1]


class LexiconDataTests(unittest.TestCase):
    """词典 JSON 可加载、字段齐全。"""

    def test_lexicon_json_loadable_and_valid(self):
        data = json.loads(LEXICON_PATH.read_text(encoding="utf-8"))
        self.assertEqual(lexicon_errors(data), [])
        self.assertEqual(data["version"], "1.0")

    def test_every_entry_has_all_fields(self):
        data = load_lexicon()
        for canonical, entry in data["entries"].items():
            self.assertIn("aliases", entry)
            self.assertIn("kind", entry)
            self.assertIn("version_seen", entry)
            self.assertIn("confusions", entry)
            self.assertIn("set_membership", entry)
            self.assertIn(entry["kind"], {"skill", "bond", "treasure"})
            self.assertIsInstance(entry["aliases"], list)
            self.assertIsInstance(entry["confusions"], list)
            self.assertTrue(entry["version_seen"])

    def test_required_entries_present(self):
        data = load_lexicon()
        names = set(data["entries"])
        for required in (
            "次级箭", "焦点", "箭矢齐射", "光法", "潮汐猎人",
            "次级增伤", "地震", "射线增幅",
            "三国", "体术", "成长", "修仙", "魔术", "封神",
            "奥术神符", "物理伤害", "攻坚", "四星球", "六星球",
        ):
            self.assertIn(required, names)

    def test_dragon_ball_set_membership(self):
        entries = load_lexicon()["entries"]
        self.assertEqual(entries["四星球"]["set_membership"], "龙珠")
        self.assertEqual(entries["六星球"]["set_membership"], "龙珠")

    def test_documented_confusions(self):
        entries = load_lexicon()["entries"]
        self.assertIn("射线", entries["射线增幅"]["confusions"])
        self.assertIn("射线", entries["奥数射线"]["confusions"])
        self.assertIn("次级增伤", entries["次级箭"]["confusions"])
        self.assertIn("次级箭", entries["次级增伤"]["confusions"])


class NormalizeTests(unittest.TestCase):
    """normalize_choice_text：NFKC → 去装饰符/空白。"""

    def test_nfkc_fullwidth(self):
        self.assertEqual(normalize_choice_text("４星球"), "4星球")
        self.assertEqual(normalize_choice_text("ＡＢＣ"), "ABC")

    def test_strips_new_badge_and_whitespace(self):
        self.assertEqual(normalize_choice_text(" 天雷[NEW] "), "天雷")
        self.assertEqual(normalize_choice_text("剑 气"), "剑气")
        self.assertEqual(normalize_choice_text("射线增幅"), "射线增幅")

    def test_strips_stars(self):
        self.assertEqual(normalize_choice_text("★四星球★"), "四星球")


class LookupExactTests(unittest.TestCase):
    """已知技能精确命中、别名命中。"""

    def test_known_skill_exact(self):
        self.assertEqual(lookup_lexicon("射线增幅").canonical, "射线增幅")
        self.assertEqual(lookup_lexicon("次级箭").canonical, "次级箭")
        self.assertEqual(lookup_lexicon("剑气").canonical, "剑气")

    def test_alias_hit(self):
        self.assertEqual(lookup_lexicon("奥术箭").canonical, "奥数箭")
        self.assertEqual(lookup_lexicon("光法R").canonical, "光法")
        self.assertEqual(lookup_lexicon("潮汐猎人sr").canonical, "潮汐猎人")
        self.assertEqual(lookup_lexicon("4星球").canonical, "四星球")

    def test_normalized_spaces_still_hit(self):
        self.assertEqual(lookup_lexicon(" 剑 气 ").canonical, "剑气")
        self.assertEqual(lookup_lexicon("天雷[NEW]").canonical, "天雷")

    def test_kind_filter(self):
        self.assertEqual(lookup_lexicon("成长", kind="bond").canonical, "成长")
        self.assertIsNone(lookup_lexicon("成长", kind="skill").canonical)
        self.assertEqual(lookup_lexicon("四星球", kind="treasure").canonical, "四星球")
        self.assertIsNone(lookup_lexicon("四星球", kind="skill").canonical)

    def test_invalid_kind_raises(self):
        with self.assertRaises(ValueError):
            lookup_lexicon("剑气", kind="bogus")


class LookupNegativeTests(unittest.TestCase):
    """混淆对负测试：分差不足返回 None，不硬猜。"""

    def test_prefix_shared_confusion_returns_none(self):
        # “射线”既是“射线增幅”前缀，也是“奥数射线”后缀 → 分差不足 → None
        canon, top2, margin = lookup_lexicon("射线")
        self.assertIsNone(canon)
        self.assertEqual(len(top2), 2)
        self.assertLess(margin, DEFAULT_MARGIN_THRESHOLD)

    def test_confusion_pair_explicit(self):
        # “次级”是“次级箭”与“次级增伤”的公共前缀 → 分差不足 → None
        canon, _, margin = lookup_lexicon("次级")
        self.assertIsNone(canon)
        self.assertLess(margin, DEFAULT_MARGIN_THRESHOLD)

    def test_margin_below_threshold_returns_none(self):
        # 截断词“箭矢齐”对“箭矢齐射”分差足够,默认阈值下可接受
        canon_default = lookup_lexicon("箭矢齐").canonical
        self.assertEqual(canon_default, "箭矢齐射")
        # 调高阈值后同一输入被拒绝,证明阈值可参数化且不硬猜
        canon_strict = lookup_lexicon("箭矢齐", margin_threshold=0.9).canonical
        self.assertIsNone(canon_strict)

    def test_unknown_returns_none_without_writeback(self):
        # 使用与词典完全不相交的符号，验证真正未知项无候选且不写回。
        unknown = "☃☄★"
        canon, top2, margin = lookup_lexicon(unknown)
        self.assertIsNone(canon)
        self.assertEqual(top2, ())
        self.assertEqual(margin, 0.0)
        # 词典未被写回
        data = load_lexicon()
        self.assertNotIn(unknown, data["entries"])


if __name__ == "__main__":
    unittest.main()
