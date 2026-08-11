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

    def test_o2_entries_present(self):
        """O2 补录：误归一修复 + D0 复核转 canonical 的词条必须存在。"""
        data = load_lexicon()
        names = set(data["entries"])
        for required in (
            "金币(中)", "吕岳", "恢复神符", "三星球", "二星球", "一星球",
            "白赚海盗", "射手姿态", "海盗劫掠者", "力量之源", "元素之力",
            "利刃", "利刃海盗", "爆炸箭矢", "致残剑气", "杀敌加成", "龙族",
            "亡灵天灾", "末日使者", "金转木", "木材(中)", "杀敌(小)",
        ):
            self.assertIn(required, names)
        self.assertEqual(data["entries"]["金币(中)"]["kind"], "treasure")
        self.assertEqual(data["entries"]["吕岳"]["kind"], "bond")
        self.assertEqual(data["entries"]["二星球"]["set_membership"], "龙珠")

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

    def test_strips_plain_new_token(self):
        """O2-1：无方括号的纯文本 NEW 徽章也要剥离（亮绿角标被 OCR 直接拼进卡名）。"""
        self.assertEqual(normalize_choice_text("风 NEW"), "风")
        self.assertEqual(normalize_choice_text("石NEW"), "石")
        self.assertEqual(normalize_choice_text("NEW 次级箭"), "次级箭")
        self.assertEqual(normalize_choice_text("W风NEW"), "W风")
        # 词典名不含 NEW，剥离不误伤
        self.assertEqual(normalize_choice_text("魔法权杖"), "魔法权杖")

    def test_progress_ratio_preserved_in_normalize(self):
        """套装进度方括号数字串必须保留（extract_progress 依赖），仅在 lookup 输入侧剥离。"""
        self.assertEqual(normalize_choice_text("套装[0/7]"), "套装[0/7]")
        self.assertEqual(normalize_choice_text("厕术(0/2)"), "厕术(0/2)")


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

    def test_o2_misnorm_fixes(self):
        """O2-1：误归一修复 —— 金币(中) 精确命中、吕岳 不再被 三国 覆盖。"""
        self.assertEqual(lookup_lexicon("金币(中)").canonical, "金币(中)")
        self.assertEqual(lookup_lexicon("金币（中）").canonical, "金币(中)")
        self.assertEqual(lookup_lexicon("吕岳", kind="bond").canonical, "吕岳")

    def test_o2_vision_confirmed_aliases(self):
        """O2-1：视觉复核确认 crop 完整后，金边艺术字 OCR 误读别名。"""
        self.assertEqual(lookup_lexicon("箭失卉射").canonical, "箭矢齐射")
        self.assertEqual(lookup_lexicon("世三图", kind="bond").canonical, "乱世三国")
        self.assertEqual(lookup_lexicon("厕术(0/2)", kind="bond").canonical, "魔术")
        self.assertEqual(lookup_lexicon("失速发").canonical, "箭矢连发")
        self.assertEqual(lookup_lexicon("希故多", kind="bond").canonical, "杀敌多多")
        self.assertEqual(lookup_lexicon("焦点慢破").canonical, "焦点爆破")
        self.assertEqual(lookup_lexicon("风风").canonical, "飓风")
        self.assertEqual(lookup_lexicon("体", kind="bond").canonical, "体魄")
        self.assertEqual(lookup_lexicon("福", kind="bond").canonical, "敏捷祝福")
        # 二星球 数字前缀丢失：'星球' 别名已撤销（会给 星球 系列截断文本引入竞争候选压低 margin）
        self.assertIsNone(lookup_lexicon("星球", kind="treasure").canonical)

    def test_traditional_char_equivalence(self):
        """O2：繁简同形字（金边艺术字常用繁体异体）在 lookup 输入侧等价。"""
        self.assertEqual(lookup_lexicon("奧能扫射", kind="skill").canonical, "奥能扫射")
        self.assertEqual(lookup_lexicon("風舞者", kind="bond").canonical, "风舞者")

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
