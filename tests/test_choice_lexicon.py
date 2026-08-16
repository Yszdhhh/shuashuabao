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

    def test_ex_guide_names_live_first(self):
        entries = load_lexicon()["entries"]
        self.assertEqual(entries["亡灵天灾"]["set_membership"], "亡灵")
        self.assertEqual(entries["异兽蛋"]["version_seen"], "live-20260814")
        self.assertIn("克尔苏加德", entries)
        self.assertNotIn("巫妖", entries["克尔苏加德"]["aliases"])
        self.assertEqual(entries["巫妖"]["set_membership"], None)
        self.assertEqual(lookup_lexicon("巫妖").canonical, "巫妖")
        self.assertEqual(lookup_lexicon("焚决").canonical, "焚诀·黄阶")
        self.assertEqual(entries["斩仙飞刀"]["set_membership"], "法宝")
        self.assertEqual(entries["小鱼人"]["set_membership"], "神兽")
        self.assertEqual(entries["燃烧的远征"]["set_membership"], "军团")
        self.assertEqual(entries["巨龙军团"]["set_membership"], "龙族")
        self.assertEqual(entries["神秘戒指"]["kind"], "bond")
        self.assertEqual(entries["神秘戒指"]["set_membership"], "修仙")
        self.assertEqual(entries["小绿瓶"]["kind"], "treasure")
        self.assertEqual(lookup_lexicon("迦拉客隆").canonical, "迦拉克隆")
        self.assertEqual(lookup_lexicon("练气期").canonical, "练气期")
        self.assertEqual(entries["藏宝图(三)"]["set_membership"], "海盗")
        self.assertEqual(entries["贪婪"]["kind"], "bond")
        self.assertIsNone(entries["贪婪"]["set_membership"])
        self.assertEqual(entries["黄金猿"]["kind"], "treasure")
        self.assertEqual(lookup_lexicon("黄金元").canonical, "黄金猿")
        self.assertEqual(lookup_lexicon("开剑码头").canonical, "开进码头")
        self.assertEqual(lookup_lexicon("重拳").canonical, "重拳先生")


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
        self.assertEqual(lookup_lexicon("齐天大圣", kind="bond").canonical, "齐天大圣")
        self.assertEqual(lookup_lexicon("天命人", kind="bond").canonical, "天命人")
        self.assertEqual(lookup_lexicon("幽灵系带", kind="bond").canonical, "幽灵系带")
        entries = json.loads((ROOT / "config" / "choice_lexicon.json").read_text(encoding="utf-8"))["entries"]
        self.assertEqual(entries["敏捷祝福"]["set_membership"], "祝福")
        self.assertEqual(entries["力量祝福"]["set_membership"], "祝福")
        self.assertEqual(entries["幽灵系带"]["set_membership"], "刀刀")
        self.assertEqual(lookup_lexicon("焚诀·黄阶", kind="bond").canonical, "焚诀·黄阶")
        self.assertEqual(lookup_lexicon("焚诀", kind="bond").canonical, "焚诀·黄阶")
        self.assertEqual(lookup_lexicon("刀刀萌新", kind="bond").canonical, "刀刀萌新")
        self.assertEqual(lookup_lexicon("刀刀大成", kind="bond").canonical, "刀刀大成")
        self.assertEqual(lookup_lexicon("阴阳双炎", kind="bond").canonical, "阴阳双炎")
        self.assertEqual(entries["护腕"]["set_membership"], "刀刀")
        self.assertEqual(entries["空灵挂坠"]["set_membership"], "刀刀")
        self.assertEqual(entries["焚诀·黄阶"]["set_membership"], "异火")
        self.assertEqual(entries["阴阳双炎"]["set_membership"], "异火")
        self.assertEqual(lookup_lexicon("帝炎", kind="bond").canonical, "帝炎")
        self.assertEqual(lookup_lexicon("陀舍古帝", kind="bond").canonical, "帝炎")
        self.assertEqual(lookup_lexicon("焚诀·天阶", kind="bond").canonical, "焚诀·天阶")
        self.assertEqual(lookup_lexicon("焚诀", kind="bond").canonical, "焚诀·黄阶")
        self.assertEqual(entries["帝炎"]["version_seen"], "live-20260814")
        self.assertIn("EX", entries["帝炎"]["_note"])
        self.assertEqual(lookup_lexicon("解放的圣剑", kind="bond").canonical, "解放的圣剑")
        self.assertEqual(lookup_lexicon("圣剑", kind="bond").canonical, "圣剑")
        self.assertEqual(lookup_lexicon("三元重疾", kind="bond").canonical, "三元重戟")
        self.assertEqual(entries["点金手"]["set_membership"], "刀刀")
        self.assertEqual(entries["天命人"]["set_membership"], "大圣")
        self.assertNotIn("天命人", entries["齐天大圣"]["aliases"])
        self.assertEqual(lookup_lexicon("毁灭战舰", kind="bond").canonical, "毁灭战舰")
        self.assertEqual(entries["法天象地"]["set_membership"], "神通")
        self.assertEqual(entries["阴阳双炎"]["version_seen"], "live-20260814")
        self.assertIn("火系", entries["风怒龙炎"]["_note"])
        self.assertEqual(entries["陨落心炎"]["version_seen"], "catalog-20260814")
        self.assertEqual(lookup_lexicon("恐鳌", kind="bond").canonical, "恐鳌戒指")
        self.assertEqual(entries["生命之球"]["set_membership"], "恐鳌戒指")
        self.assertEqual(lookup_lexicon("时间停止", kind="treasure").canonical, "时间停止")
        catalog = json.loads((ROOT / "config" / "bond_stack_catalog.json").read_text(encoding="utf-8"))
        self.assertEqual(catalog["needs"]["刀刀"]["need"], 3)
        self.assertNotIn("刀刀", catalog["unknown"])
        self.assertNotIn("异火", catalog["needs"])
        self.assertNotIn("大圣残躯", catalog["needs"])
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
