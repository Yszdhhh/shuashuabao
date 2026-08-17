"""图鉴投影一致性：只 join 权威 JSON，不写第四份卡名表。"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from gamescript.atlas_view import (
    CATEGORY_SKILL_CARD,
    CATEGORY_SKILL_FAMILY,
    PENDING_TEXT,
    apply_to_run,
    load_atlas_view,
)
from gamescript.settings import Settings
from gamescript.vision.choice_ocr import load_lexicon, lookup_lexicon

ROOT = Path(__file__).resolve().parents[1]


def _load(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


class AtlasViewJoinTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        load_atlas_view.cache_clear()
        cls.view = load_atlas_view()
        cls.lexicon = load_lexicon()["entries"]
        cls.catalog = _load("config/skill_card_catalog.json")
        cls.policy = _load("config/choice_policy.json")
        cls.strategy = _load("config/official_strategy_defaults.json")

    def test_no_fourth_name_table(self):
        self.assertFalse((ROOT / "config" / "atlas.json").exists())
        self.assertFalse((ROOT / "src" / "gamescript" / "atlas.json").exists())

    def test_projected_skill_names_subset_of_lexicon_or_catalog(self):
        catalog_names = {
            str(card.get("name") or "").strip()
            for card in (self.catalog.get("cards") or [])
            if isinstance(card, dict) and card.get("name")
        }
        families = set(self.catalog.get("family_to_code") or {})
        allowed = set(self.lexicon) | catalog_names | families
        for entry in self.view.entries:
            if entry.category not in {CATEGORY_SKILL_FAMILY, CATEGORY_SKILL_CARD}:
                continue
            self.assertIn(
                entry.name,
                allowed,
                f"投影技能名 {entry.name!r} 不在 lexicon∪catalog",
            )

    def test_negative_treasure_names_equal_policy(self):
        expected = [str(n) for n in (self.policy.get("treasure") or {}).get("negative_names") or []]
        projected = [e.name for e in self.view.entries if "negative" in e.flags]
        self.assertEqual(sorted(expected), sorted(projected))
        self.assertTrue(expected, "policy 负面名单不应为空")

    def test_attr_route_names_resolve_in_lexicon(self):
        for key, meta in (self.strategy.get("attr_routes") or {}).items():
            if str(key).startswith("_") or not isinstance(meta, dict):
                continue
            names = list(meta.get("chain") or []) + list(meta.get("support") or [])
            if meta.get("set_name"):
                names.append(meta["set_name"])
            for name in names:
                text = str(name).strip()
                if not text:
                    continue
                hit = lookup_lexicon(text, kind="bond")
                self.assertEqual(
                    hit.canonical,
                    text,
                    f"羁绊链 {key} 的 {text!r} 不能在词典解析",
                )
                self.assertIsNotNone(self.view.get(text), text)

    def test_search_jisu_lands_on_jisu_bond(self):
        self.assertEqual(lookup_lexicon("极速", kind="bond").canonical, "急速")
        hits = self.view.search("极速")
        names = [e.name for e in hits]
        self.assertIn("急速", names)
        self.assertEqual(hits[0].name, "急速")
        self.assertEqual(self.view.get("极速").name, "急速")

    def test_yanmiezhe_has_intel_chain_and_ur_fixtures(self):
        hits = self.view.search("湮灭者")
        self.assertTrue(hits)
        entry = hits[0]
        self.assertEqual(entry.name, "湮灭者")
        self.assertIsNotNone(entry.route)
        self.assertEqual(entry.route.attr, "智力")
        self.assertEqual(entry.route.chain, ("智力", "秘法师", "法神", "湮灭者"))
        piece_names = [p.name for p in entry.route.pieces]
        self.assertEqual(piece_names, ["聚能之虹", "洞察之眼", "奥法之辉"])
        for piece in entry.route.pieces:
            self.assertTrue(piece.icon_path, piece.name)
            self.assertTrue((ROOT / piece.icon_path).is_file(), piece.icon_path)

    def test_empty_family_description_is_pending_not_invented(self):
        asj = self.view.get("奥数箭")
        self.assertIsNotNone(asj)
        self.assertEqual(asj.effect, "")
        self.assertEqual(asj.display_effect(), PENDING_TEXT)
        self.assertNotIn("%", asj.display_effect())
        self.assertEqual(asj.evidence, "待补")

    def test_live_family_keeps_source_text(self):
        tl = self.view.get("天雷")
        self.assertIsNotNone(tl)
        self.assertIn("麻痹", tl.effect)
        self.assertEqual(tl.evidence, "实机")

    def test_archive_tier_uses_json_text(self):
        asj = self.view.get("奥数箭")
        texts = [row.display() for row in asj.archive_tiers]
        self.assertTrue(any("Lv36" in text and "爆炸箭矢" in text for text in texts), texts)

    def test_bond_columns_split_by_short_code(self):
        jisu = self.view.get("急速")
        self.assertIsNotNone(jisu)
        self.assertFalse(jisu.whitelist_ok)
        self.assertIn("knowledge_only", jisu.flags)
        yanmie = self.view.get("湮灭者")
        self.assertTrue(yanmie.whitelist_ok)
        self.assertEqual(yanmie.short_code, "yanmiezhe")
        dasheng = self.view.get("大圣")
        self.assertIsNotNone(dasheng)
        self.assertTrue(dasheng.whitelist_ok)
        self.assertEqual(dasheng.short_code, "dasheng")

    def test_merchant_page_is_empty_state(self):
        page = self.view.merchant_page()
        self.assertEqual(page.entries, ())
        self.assertEqual(self.view.by_category("merchant"), ())
        self.assertTrue(page.pending)
        self.assertTrue(any("merchant" in item for item in page.pending))
        self.assertFalse(any("建议购买" in item for item in page.pending))
        kinds = {row.get("kind") for row in self.lexicon.values()}
        self.assertNotIn("merchant", kinds)

    def test_yihuo_set_joined_from_lexicon(self):
        live = self.view.get("阴阳双炎")
        self.assertIsNotNone(live)
        self.assertEqual(live.category, "bond")
        self.assertEqual(live.evidence, "实机")
        self.assertIn("4%", live.effect)
        self.assertIn("knowledge_only", live.flags)
        catalog = self.view.get("虚无吞炎")
        self.assertIsNotNone(catalog)
        self.assertEqual(catalog.evidence, "攻略")
        self.assertIn("吞天噬地", catalog.effect)
        self.assertEqual(self.view.get("陀舍古帝").name, "帝炎")
        self.assertEqual(self.view.get("帝炎").evidence, "实机")
        yihuo = self.view.get("异火")
        self.assertIsNotNone(yihuo)
        self.assertEqual(yihuo.evidence, "实机")

    def test_daodao_set_joined_from_lexicon(self):
        belt = self.view.get("幽灵系带")
        self.assertIsNotNone(belt)
        self.assertEqual(belt.evidence, "实机")
        self.assertEqual(belt.family_or_need, "刀刀")
        self.assertIn("30", belt.effect)
        ur = self.view.get("刀刀大成")
        self.assertIsNotNone(ur)
        self.assertEqual(ur.evidence, "实机")
        self.assertIn("500", ur.effect)
        self.assertIn("多段", ur.effect)
        self.assertIn("knowledge_only", ur.flags)
        set_entry = self.view.get("刀刀")
        self.assertIsNotNone(set_entry)
        self.assertEqual(set_entry.family_or_need, "3张")
        self.assertEqual(set_entry.evidence, "实机")

    def test_ex_capstones_joined(self):
        saint = self.view.get("圣人")
        self.assertIsNotNone(saint)
        self.assertEqual(saint.family_or_need, "封神")
        self.assertIn("无法吞噬", saint.effect)
        diyan = self.view.get("帝炎")
        self.assertEqual(diyan.evidence, "实机")
        self.assertIn("EX", diyan.effect)
        ship = self.view.get("毁灭战舰")
        self.assertIsNotNone(ship)
        self.assertEqual(ship.family_or_need, "海盗")
        self.assertEqual(self.view.get("法天象地").family_or_need, "神通")
        tianming = self.view.get("天命人")
        self.assertIsNotNone(tianming)
        self.assertEqual(tianming.family_or_need, "大圣")

    def test_ex_capstone_icons_and_cannot_devour(self):
        for name in ("帝炎", "解放的圣剑", "圣人"):
            entry = self.view.get(name)
            self.assertIsNotNone(entry, name)
            self.assertIn("cannot_devour", entry.flags, name)
            self.assertTrue(entry.icon_path, name)
            self.assertTrue((ROOT / entry.icon_path).is_file(), entry.icon_path)
            self.assertTrue(entry.rarity, name)

    def test_daodao_route_from_kb(self):
        entry = self.view.get("刀刀")
        self.assertIsNotNone(entry.route)
        self.assertEqual(
            entry.route.chain,
            ("幽灵系带", "护腕", "空灵挂坠", "刀刀萌新", "刀刀大成", "解放的圣剑"),
        )
        self.assertEqual(
            [piece.name for piece in entry.route.pieces],
            ["幽灵系带", "护腕", "空灵挂坠"],
        )
        self.assertEqual(self.view.get("刀刀萌新").route.chain, entry.route.chain)
        self.assertEqual(self.view.get("点金手").route.chain, entry.route.chain)

    def test_fengshen_wangling_shenshou_routes_from_kb(self):
        feng = self.view.get("封神")
        self.assertIsNotNone(feng.route)
        self.assertEqual(feng.route.chain, ("姜子牙", "圣人"))
        self.assertEqual(self.view.get("斩仙飞刀").route.chain, feng.route.chain)
        wang = self.view.get("亡灵")
        self.assertEqual(wang.route.chain, ("亡灵天灾", "兵主"))
        self.assertEqual(self.view.get("克尔苏加德").route.chain, wang.route.chain)
        self.assertIsNone(self.view.get("巫妖"))
        self.assertEqual(self.view.get("巫妖王").name, "巫妖王")
        shen = self.view.get("神兽")
        self.assertEqual(shen.route.chain, ("异兽蛋", "祖龙"))
        self.assertEqual(self.view.get("小鱼人").route.chain, shen.route.chain)

    def test_juntuan_longzu_sanguo_xiuxian_routes_from_kb(self):
        jun = self.view.get("军团")
        self.assertEqual(jun.route.chain, ("燃烧的远征", "萨格拉斯"))
        self.assertEqual(self.view.get("扭曲虚空").route.chain, jun.route.chain)
        longzu = self.view.get("龙族")
        self.assertEqual(longzu.route.chain, ("巨龙军团", "世界末日迦拉克隆"))
        self.assertEqual(self.view.get("克罗斯龙提").route.chain, longzu.route.chain)
        san = self.view.get("三国")
        self.assertEqual(san.route.chain, ("乱世三国", "吞食天地"))
        self.assertEqual(self.view.get("司马懿").route.chain, san.route.chain)
        xiu = self.view.get("修仙")
        self.assertEqual(xiu.route.chain, ("神秘戒指", "练气期", "大乘期"))
        self.assertEqual(self.view.get("流星泪").route.chain, xiu.route.chain)
        bottle = self.view.get("小绿瓶")
        self.assertIsNotNone(bottle)
        self.assertTrue(bottle.route is None or bottle.route.chain != xiu.route.chain)

    def test_haidao_and_baozang_routes_from_kb(self):
        pirate = self.view.get("海盗")
        self.assertEqual(pirate.route.chain, ("藏宝图(三)", "毁灭战舰"))
        self.assertEqual(self.view.get("罗杰斯上将").route.chain, pirate.route.chain)
        greedy = self.view.get("贪婪")
        self.assertTrue(greedy.route is None or greedy.route.chain != pirate.route.chain)
        ape = self.view.get("黄金猿")
        self.assertIsNotNone(ape)
        self.assertEqual(ape.route.chain, ("黄金猿", "宝藏"))
        self.assertEqual(self.view.get("黄金元").name, "黄金猿")

    def test_yihuo_route_from_kb(self):
        entry = self.view.get("焚诀·黄阶")
        self.assertIsNotNone(entry.route)
        self.assertEqual(entry.route.chain, ("焚诀·黄阶", "焚诀·玄阶", "帝炎"))
        self.assertEqual(
            [piece.name for piece in entry.route.pieces],
            ["阴阳双炎", "风怒龙炎", "幽冥毒火", "玄黄炎"],
        )
        self.assertEqual(self.view.get("阴阳双炎").route.chain, entry.route.chain)
        self.assertEqual(self.view.get("虚无吞炎").route.chain, entry.route.chain)

    def test_catalog_yihuo_stays_guide_not_live_flavor(self):
        entry = self.view.get("陨落心炎")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.evidence, "攻略")
        self.assertNotIn("护甲穿透", entry.effect)
        self.assertIsNone(entry.route)

    def test_live_yihuo_stats_follow_ocr_not_old_phys_magic(self):
        wind = self.view.get("风怒龙炎")
        self.assertIsNotNone(wind)
        self.assertEqual(wind.evidence, "实机")
        self.assertIn("火系", wind.effect)
        self.assertNotIn("物伤+4%", wind.effect)
        poison = self.view.get("幽冥毒火")
        self.assertIn("燃烧", poison.effect)
        xuan = self.view.get("玄黄炎")
        self.assertIn("100", xuan.effect)

    def test_kongao_ring_joined_from_kb(self):
        ring = self.view.get("恐鳌戒指")
        self.assertIsNotNone(ring)
        self.assertEqual(ring.evidence, "实机")
        self.assertEqual(
            [piece.name for piece in ring.route.pieces],
            ["生命之球", "守护指环"],
        )
        ball = self.view.get("生命之球")
        self.assertIn("250", ball.effect)
        self.assertIn("knowledge_only", ball.flags)

    def test_must_take_joined_from_policy(self):
        names = [e.name for e in self.view.entries if "must_take" in e.flags]
        self.assertEqual(
            sorted(names),
            sorted((self.policy.get("treasure") or {}).get("must_take_names") or []),
        )


class AtlasApplyOneWayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        load_atlas_view.cache_clear()
        cls.view = load_atlas_view()

    def test_upgrade_cards_never_enter_skills(self):
        settings = Settings(skills=["asj", "jq"])
        before = list(settings.skills)
        cards = [e.name for e in self.view.by_category(CATEGORY_SKILL_CARD)]
        self.assertGreaterEqual(len(cards), 200)
        diff = apply_to_run(cards, view=self.view)
        self.assertEqual(diff.skills, ())
        self.assertEqual(settings.skills, before)
        self.assertTrue(diff.rejected)

    def test_family_and_bond_and_negative_apply(self):
        diff = apply_to_run(["奥数箭", "湮灭者", "金转木", "箭矢增幅"], view=self.view)
        self.assertEqual(diff.skills, ("asj",))
        self.assertEqual(diff.cards, ("yanmiezhe",))
        self.assertEqual(diff.treasure_allow_negative, ("金转木",))
        self.assertIn("箭矢增幅", diff.rejected)

    def test_running_rejects_all(self):
        diff = apply_to_run(["奥数箭"], running=True, view=self.view)
        self.assertEqual(diff.skills, ())
        self.assertEqual(diff.cards, ())
        self.assertIn("奥数箭", diff.rejected)

    def test_knowledge_bond_cannot_apply(self):
        diff = apply_to_run(["急速"], view=self.view)
        self.assertEqual(diff.cards, ())
        self.assertIn("急速", diff.rejected)

    def test_family_apply_caps_at_four(self):
        """图鉴应用技能系上限=4（与 Settings 解析边界同一常量）。"""
        diff = apply_to_run(
            ["奥数箭", "奥数激光", "奥数射线", "剑气", "爆炎箭"], view=self.view
        )
        self.assertEqual(("asj", "asjg", "assx", "jq"), diff.skills)
        self.assertIn("爆炎箭", diff.rejected)

    def test_family_cap_reuses_settings_constant(self):
        from gamescript import atlas_view as atlas
        from gamescript.settings import MAX_SELECTED_SKILLS

        self.assertEqual(atlas.MAX_APPLY_SKILLS, MAX_SELECTED_SKILLS)


if __name__ == "__main__":
    unittest.main()
