"""D 组：负面宝物真机描述夹具契约（2026-08-12 六张 + 2026-09-22 十四张）。

数据源：``fixtures/treasure_negative/DESCRIPTIONS.json`` + ``INDEX.json`` + ``SOURCES.json``。
不修改 ``test_choice_semantics_contract.py``（属主 agent）；本文件独立断言：

1. 全部入库卡（20）均有 ≥1 张真机 panel + 非空描述原文
2. DEFAULT_NEGATIVE_NAMES 卡走名字路径 ``is_negative_treasure`` 为真
3. 名单外卡不得仅凭名字可疑 / 空描述猜负面
4. 口述负面样例仍被 ``DEFAULT_NEGATIVE_PATTERNS`` 覆盖（给新卡兜底）
5. 真机面板端到端：默认不拿槽不被 ``choose_action`` 选中
6. 明确列出当前 patterns 缺口（不改 config；交回 Owner 裁决）
7. 其余仅入库卡断言当前实际命中/未命中（不改期望去迎合）

红线：无合成帧；不改 GATE_BASELINE 糊弄；本轮不改 negative_patterns。
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.choice_policy import (  # noqa: E402
    DEFAULT_NEGATIVE_NAMES,
    DEFAULT_NEGATIVE_PATTERNS,
    PANEL_TREASURE,
    PanelCandidates,
    PolicyAction,
    PolicySettings,
    SessionState,
    SlotCandidate,
    choose_action,
    is_negative_treasure,
)

FIXTURE_DIR = ROOT / "fixtures" / "treasure_negative"
DESCRIPTIONS_PATH = FIXTURE_DIR / "DESCRIPTIONS.json"
INDEX_PATH = FIXTURE_DIR / "INDEX.json"
SOURCES_PATH = FIXTURE_DIR / "SOURCES.json"

# 2026-09-22 批次：Owner 批准默认不拿（进 DEFAULT_NEGATIVE_NAMES）。
# 木材梭哈为 Owner 2026-09-22 晚追加；等级优势同批移出名单（默认拿）。
OWNER_APPROVED_DEFAULT_SKIP = ("诅咒之力", "提高上限", "木材梭哈")
# Owner 2026-09-22 晚批准的描述 pattern：命中即默认不拿（UI 勾选可放行）。
OWNER_APPROVED_PATTERN_SKIP = {
    "恶魔契约": "无法再升级",
    "玻璃大炮": "受到的所有伤害提高",
    "木材梭哈": "木材清0",
    "金币梭哈": "金币清0",
}
# 同批次仅入库、不改默认拿/不拿的 12 张。
FIXTURE_ONLY_20260922 = (
    "力之极",
    "命运骰子",
    "恶魔契约",
    "敏之极",
    "智之极",
    "木材梭哈",
    "混乱转换",
    "玻璃大炮",
    "登神长阶",
    "经验压制",
    "贪婪契约",
    "金币梭哈",
)
# 2026-08-12 已确认名单（DEFAULT_NEGATIVE_NAMES 原六张）。
BASELINE_NEGATIVE = (
    "透支力量",
    "贪婪献祭",
    "金转木",
    "杀敌梭哈",
    "伐木契约",
    "等级优势",
)

NO_PICK = {PolicyAction.WAIT, PolicyAction.REFRESH, PolicyAction.GIVEUP, PolicyAction.CLOSE}


def _load_descriptions() -> dict:
    return json.loads(DESCRIPTIONS_PATH.read_text(encoding="utf-8"))


def _load_index() -> dict:
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


def _slot(index, name=None, rarity=None, confidence=0.95, description=""):
    return SlotCandidate(
        index=index,
        name=name,
        confidence=confidence,
        rarity=rarity,
        description=description,
    )


def _panel(slots, **kw):
    return PanelCandidates(panel_kind=PANEL_TREASURE, slots=tuple(slots), **kw)


def _patterns_hit(text: str, patterns=DEFAULT_NEGATIVE_PATTERNS) -> tuple[str, ...]:
    return tuple(p for p in patterns if p and p in (text or ""))


class TreasureNegativeFixturePresence(unittest.TestCase):
    """夹具包本身必须完整：20 张卡、描述原文、至少一块真机面板、来源可追溯。"""

    def test_descriptions_and_index_exist(self):
        self.assertTrue(DESCRIPTIONS_PATH.is_file(), DESCRIPTIONS_PATH)
        self.assertTrue(INDEX_PATH.is_file(), INDEX_PATH)
        self.assertTrue(SOURCES_PATH.is_file(), SOURCES_PATH)
        self.assertTrue((FIXTURE_DIR / "README.md").is_file())

    def test_all_fixture_cards_present(self):
        desc = _load_descriptions()
        index = _load_index()
        expected = set(BASELINE_NEGATIVE) | set(OWNER_APPROVED_DEFAULT_SKIP) | set(FIXTURE_ONLY_20260922)
        self.assertEqual(set(desc["cards"]), expected)
        self.assertEqual(set(index["names"]), expected)
        for name in expected:
            card_dir = FIXTURE_DIR / name
            self.assertTrue(card_dir.is_dir(), f"missing dir {card_dir}")
            panels = list(card_dir.glob("panel_*.png")) + list(card_dir.glob("panel_*.jpg"))
            self.assertGreaterEqual(len(panels), 1, f"{name} needs ≥1 real panel frame")
            self.assertTrue(str(desc["cards"][name].get("description") or "").strip())

    def test_default_negative_names_subset_of_fixtures(self):
        """默认不拿名单必须有夹具证据（DESCRIPTIONS ⊇ DEFAULT_NEGATIVE_NAMES）。"""
        desc = set(_load_descriptions()["cards"])
        for name in DEFAULT_NEGATIVE_NAMES:
            self.assertIn(name, desc, f"{name} 在 DEFAULT_NEGATIVE_NAMES 但缺夹具描述")

    def test_sources_sha256_present(self):
        sources = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
        images = sources.get("images") or []
        self.assertGreaterEqual(len(images), 26, "2026-09-22 批次 26 张 panel 副本")
        seen = set()
        for img in images:
            key = (img["card"], img["fixture_path"])
            self.assertNotIn(key, seen, f"duplicate source row {key}")
            seen.add(key)
            self.assertTrue(str(img.get("source_sha256") or ""), img)
            self.assertRegex(img["source_sha256"], r"^[0-9a-f]{64}$")
            self.assertTrue(str(img.get("source_path") or ""), img)
            self.assertTrue((ROOT / img["fixture_path"].replace("\\", "/")).is_file(), img)


class TreasureNegativeNameAndDescription(unittest.TestCase):
    """真机描述 + 确认名单：is_negative_treasure 必须拦住。"""

    def test_default_negative_names_blocked_with_real_descriptions(self):
        settings = PolicySettings()
        cards = _load_descriptions()["cards"]
        for name in DEFAULT_NEGATIVE_NAMES:
            with self.subTest(name=name):
                self.assertTrue(
                    is_negative_treasure(
                        _slot(0, name, description=cards[name]["description"]),
                        settings,
                    ),
                    f"{name} + 真机描述应判负面",
                )

    def test_default_negative_names_blocked_even_with_empty_description(self):
        """名字判定与描述判定互为冗余：OCR 失败时仍拦。"""
        settings = PolicySettings()
        for name in DEFAULT_NEGATIVE_NAMES:
            with self.subTest(name=name):
                self.assertTrue(
                    is_negative_treasure(_slot(0, name, description=""), settings)
                )

    def test_owner_approved_default_skip_names_blocked(self):
        """Owner 2026-09-22 批准的两张：名字路径必须拦住（含空描述）。"""
        settings = PolicySettings()
        cards = _load_descriptions()["cards"]
        for name in OWNER_APPROVED_DEFAULT_SKIP:
            with self.subTest(name=name):
                self.assertIn(name, DEFAULT_NEGATIVE_NAMES)
                self.assertTrue(
                    is_negative_treasure(_slot(0, name, description=""), settings),
                    f"{name} Owner 已批准默认不拿，缺描述时仍应拦截",
                )
                self.assertTrue(
                    is_negative_treasure(
                        _slot(0, name, description=cards[name]["description"]),
                        settings,
                    )
                )

    def test_fixture_only_cards_current_actual_behavior(self):
        """其余 12 张：只断言当前实际命中/未命中，不改期望去迎合。

        贪婪契约描述含「将恒定」→ 现有 pattern 命中（即使不在名单）。
        其余 11 张当前既不在名单、描述也无 pattern 命中 → 不得判负面。
        """
        settings = PolicySettings()
        cards = _load_descriptions()["cards"]
        # 当前会被 pattern 命中的仅入库卡（report.md §6 + Owner 09-22 晚批准的 pattern）。
        pattern_hit = {"贪婪契约"} | set(OWNER_APPROVED_PATTERN_SKIP)
        for name in FIXTURE_ONLY_20260922:
            with self.subTest(name=name):
                if name not in OWNER_APPROVED_DEFAULT_SKIP:
                    self.assertNotIn(name, DEFAULT_NEGATIVE_NAMES, f"{name} 未经 Owner 批准不得进默认不拿名单")
                hit = is_negative_treasure(
                    _slot(0, name, description=cards[name]["description"]),
                    settings,
                )
                if name in pattern_hit:
                    self.assertTrue(hit, f"{name} 描述应命中现有 pattern（当前实际）")
                    self.assertTrue(_patterns_hit(cards[name]["description"]))
                else:
                    self.assertFalse(hit, f"{name} 当前不应被默认拦住（待 Owner 裁决）")
                    self.assertFalse(_patterns_hit(cards[name]["description"]))

    def test_greedy_sacrifice_description_looks_positive_but_name_still_blocks(self):
        """贪婪献祭：现有真机帧描述像正面文案，但仍须靠名单拦截。

        描述「每消耗500金币，获得1点随机属性」与 S3 正面对照样例同文；
        不得要求仅靠 negative_patterns 命中；交回说明见 DESCRIPTIONS.json notes。
        """
        meta = _load_descriptions()["cards"]["贪婪献祭"]
        desc = meta["description"]
        self.assertEqual(desc, "每消耗500金币，获得1点随机属性")
        self.assertFalse(
            _patterns_hit(desc),
            "贪婪献祭真机描述不应被现有 DEFAULT_NEGATIVE_PATTERNS 误伤式命中",
        )
        anon = PolicySettings(treasure_negative_names=())
        self.assertFalse(
            is_negative_treasure(_slot(0, "某宝物", description=desc), anon),
            "名单外 + 该描述不得仅凭措辞拉黑",
        )
        self.assertTrue(
            is_negative_treasure(
                _slot(0, "贪婪献祭", description=desc),
                PolicySettings(),
            ),
            "确认名单仍必须拦住贪婪献祭",
        )


class TreasureNegativeFailClosed(unittest.TestCase):
    """名单外：空描述不猜；可疑名字不猜。"""

    def test_off_list_empty_description_not_guessed(self):
        settings = PolicySettings()
        for name in ("命运骰子", "百宝箱", "刷新券", "双倍神符", "卡牌大师"):
            with self.subTest(name=name):
                self.assertNotIn(name, settings.treasure_negative_names)
                self.assertFalse(
                    is_negative_treasure(_slot(0, name, description=""), settings)
                )

    def test_suspicious_off_list_name_without_negative_desc_not_blocked(self):
        """「透支」「献祭」等字样出现在名单外卡名时，不得凭名字拉黑。"""
        settings = PolicySettings()
        for name in ("透支药剂", "献祭图腾", "契约卷轴"):
            with self.subTest(name=name):
                self.assertNotIn(name, settings.treasure_negative_names)
                self.assertFalse(
                    is_negative_treasure(_slot(0, name, description=""), settings)
                )


class TreasureNegativePatternCoverage(unittest.TestCase):
    """核对 DEFAULT_NEGATIVE_PATTERNS 对真机原文 / 口述样例的覆盖。"""

    def test_oral_samples_still_match_default_patterns(self):
        """契约口述三类仍是 patterns 回归基线（覆盖没见过的新卡）。"""
        oral = _load_descriptions()["contract_oral_negative_samples_keep"]
        settings = PolicySettings(treasure_negative_names=())
        for text in oral:
            with self.subTest(text=text):
                self.assertTrue(_patterns_hit(text), f"oral sample not covered: {text}")
                self.assertTrue(
                    is_negative_treasure(_slot(0, "未知新卡", description=text), settings)
                )

    def test_document_real_description_pattern_gaps(self):
        """真机原文相对 DEFAULT_NEGATIVE_PATTERNS 的缺口清单（2026-09-22 批次如实列出）。

        2026-08-12 已追加：消耗全部金币 / 将恒定 / 杀敌数清0 / 宝物效果-。
        本轮不改 patterns；缺口卡不得被假装已覆盖。
        """
        cards = _load_descriptions()["cards"]
        gaps = {
            name: meta["description"]
            for name, meta in cards.items()
            if not _patterns_hit(meta["description"])
        }
        # 当前无 pattern 命中的全部卡（含旧六张中的两张）。
        expected_gaps = {
            "贪婪献祭",
            "等级优势",
            "力之极",
            "命运骰子",
            "敏之极",
            "智之极",
            "混乱转换",
            "登神长阶",
            "经验压制",
            "诅咒之力",
        }
        self.assertEqual(
            set(gaps),
            expected_gaps,
            "pattern 覆盖变化时请同步本断言与 DESCRIPTIONS.json",
        )
        # 已覆盖的卡：description-only 即可拦（无名字也行）
        covered = set(cards) - set(gaps)
        self.assertEqual(
            covered,
            {"透支力量", "金转木", "杀敌梭哈", "伐木契约", "提高上限", "贪婪契约",
             "恶魔契约", "玻璃大炮", "木材梭哈", "金币梭哈"},
        )
        anon = PolicySettings(treasure_negative_names=())
        for name in covered:
            with self.subTest(name=name):
                self.assertTrue(
                    is_negative_treasure(
                        _slot(0, "未知新卡", description=cards[name]["description"]),
                        anon,
                    )
                )

        for name, meta in cards.items():
            for hint in meta.get("pattern_hints") or []:
                with self.subTest(name=name, hint=hint):
                    self.assertTrue(
                        hint in meta["description"]
                        or hint in (_load_descriptions().get("suggested_pattern_appends_for_owner") or [])
                        or hint in (_load_descriptions().get("suggested_pattern_appends_for_main_agent") or []),
                        f"{name} pattern_hint={hint!r} 未落入描述或建议追加列表",
                    )

    def test_current_pattern_gap_notes_for_owner(self):
        """report.md §6 所列缺口：本轮不改 patterns，只如实记录待 Owner 裁决。"""
        # 拟议 pattern | 会命中 | 误伤风险 —— 见交付报告；此处锁缺口卡与关键短语。
        gap_phrases = {
            "恶魔契约": "无法再升级",
            "命运骰子": "增幅-15%",
            "登神长阶": "全属性-35%",
            "玻璃大炮": "受到的所有伤害提高",
            "力之极": "扣除",
            "敏之极": "扣除",
            "智之极": "扣除",
            "木材梭哈": "木材清0",
            "金币梭哈": "金币清0",
            "经验压制": "经验-70%",
            "诅咒之力": "恢复效果-",
        }
        cards = _load_descriptions()["cards"]
        for name, phrase in gap_phrases.items():
            with self.subTest(name=name, phrase=phrase):
                self.assertIn(name, cards)
                self.assertIn(phrase, cards[name]["description"], f"{name} 描述应含缺口短语 {phrase!r}")
                if name in OWNER_APPROVED_PATTERN_SKIP:
                    self.assertEqual(
                        (OWNER_APPROVED_PATTERN_SKIP[name],),
                        _patterns_hit(cards[name]["description"]),
                        f"{name} 应仅由 Owner 批准的 pattern 命中",
                    )
                    continue
                self.assertFalse(
                    _patterns_hit(cards[name]["description"]),
                    f"{name} 当前仍无 DEFAULT_NEGATIVE_PATTERNS 命中（待 Owner 裁决）",
                )
        # 「无法再升级」不得被「无法升级」误判为已覆盖。
        self.assertNotIn("无法升级", cards["恶魔契约"]["description"])


class TreasureNegativeE2EChooseAction(unittest.TestCase):
    """完整面板语义：负面卡不应被选中（纯函数 choose_action，不接线 mediator）。"""

    def test_greedy_sacrifice_panel_picks_non_negative_peer(self):
        """贪婪献祭（slot0，描述像正面） vs 卡牌大师 / 双倍神符 → 不得选 slot0。"""
        meta = _load_descriptions()["cards"]["贪婪献祭"]
        decision = choose_action(
            _panel(
                [
                    _slot(0, "贪婪献祭", rarity="orange", description=meta["description"]),
                    _slot(
                        1,
                        "卡牌大师",
                        rarity="purple",
                        description="每次抽卡获得羁绊卡牌，全属性+10",
                    ),
                    _slot(
                        2,
                        "双倍神符",
                        rarity="green",
                        description="在接下来30秒内：攻击增幅+100%",
                    ),
                ],
                settings=PolicySettings(),
            )
        )
        self.assertEqual(decision.action, PolicyAction.SELECT_SLOT)
        self.assertNotEqual(decision.index, 0, "不得选中贪婪献祭")
        self.assertIn(decision.index, (1, 2))

    def test_overdraft_power_panel_skips_negative_slot(self):
        meta = _load_descriptions()["cards"]["透支力量"]
        decision = choose_action(
            _panel(
                [
                    _slot(0, "物理伤害", rarity="green", description="物理伤害+15%"),
                    _slot(
                        1,
                        "七星球",
                        rarity="blue",
                        description="金币+10000, 木材+100, 集齐七颗龙珠，触发神龙许愿",
                    ),
                    _slot(2, "透支力量", rarity="orange", description=meta["description"]),
                ],
                settings=PolicySettings(),
            )
        )
        self.assertEqual(decision.action, PolicyAction.SELECT_SLOT)
        self.assertNotEqual(decision.index, 2)

    def test_logging_contract_and_level_advantage_panel_skips_both(self):
        cards = _load_descriptions()["cards"]
        decision = choose_action(
            _panel(
                [
                    _slot(0, "四星球", rarity="blue", description="集齐七颗龙珠，触发神龙许愿"),
                    _slot(
                        1,
                        "伐木契约",
                        rarity="red",
                        description=cards["伐木契约"]["description"],
                    ),
                    _slot(
                        2,
                        "等级优势",
                        rarity="blue",
                        description=cards["等级优势"]["description"],
                    ),
                ],
                has_giveup=True,
                settings=PolicySettings(),
            )
        )
        if decision.action == PolicyAction.SELECT_SLOT:
            self.assertEqual(decision.index, 0)
        else:
            self.assertIn(decision.action, NO_PICK)

    def test_gold_to_wood_not_selected(self):
        cards = _load_descriptions()["cards"]
        decision = choose_action(
            _panel(
                [
                    _slot(
                        0,
                        "奥术神符",
                        rarity="green",
                        description="在接下来30秒内：技能急速+200",
                    ),
                    _slot(
                        1,
                        "金转木",
                        rarity="orange",
                        description=cards["金转木"]["description"],
                    ),
                    _slot(
                        2,
                        "赏金神符",
                        rarity="green",
                        description="在接下来45秒内，杀敌金币+100%",
                    ),
                ],
                settings=PolicySettings(),
            )
        )
        self.assertEqual(decision.action, PolicyAction.SELECT_SLOT)
        self.assertNotEqual(decision.index, 1)

    def test_all_in_kills_not_selected(self):
        cards = _load_descriptions()["cards"]
        decision = choose_action(
            _panel(
                [
                    _slot(
                        0,
                        "杀敌梭哈",
                        rarity="purple",
                        description=cards["杀敌梭哈"]["description"],
                    ),
                    _slot(
                        1,
                        "属性神符",
                        rarity="green",
                        description="在接下来45秒内，每击杀1名敌人，获得1点随机属性",
                    ),
                    _slot(
                        2,
                        "赏金神符",
                        rarity="green",
                        description="在接下来45秒内，杀敌金币+100%",
                    ),
                ],
                settings=PolicySettings(),
            )
        )
        self.assertEqual(decision.action, PolicyAction.SELECT_SLOT)
        self.assertNotEqual(decision.index, 0)

    def test_all_six_negative_panel_takes_no_card(self):
        cards = _load_descriptions()["cards"]
        slots = [
            _slot(i, name, rarity="orange", description=cards[name]["description"])
            for i, name in enumerate(DEFAULT_NEGATIVE_NAMES[:3])
        ]
        decision = choose_action(
            _panel(slots, has_giveup=True, settings=PolicySettings()),
            SessionState(),
        )
        self.assertIn(decision.action, NO_PICK)

    def test_owner_approved_default_skip_panel_takes_no_card(self):
        """诅咒之力 + 提高上限 同面板：端到端不得被选中。"""
        cards = _load_descriptions()["cards"]
        decision = choose_action(
            _panel(
                [
                    _slot(
                        0,
                        "诅咒之力",
                        rarity="red",
                        description=cards["诅咒之力"]["description"],
                    ),
                    _slot(
                        1,
                        "提高上限",
                        rarity="orange",
                        description=cards["提高上限"]["description"],
                    ),
                    _slot(
                        2,
                        "赏金神符",
                        rarity="green",
                        description="在接下来45秒内，杀敌金币+100%",
                    ),
                ],
                settings=PolicySettings(),
            )
        )
        if decision.action == PolicyAction.SELECT_SLOT:
            self.assertEqual(decision.index, 2, "只能选非默认不拿的赏金神符")
        else:
            self.assertIn(decision.action, NO_PICK)

    def test_curse_power_real_panel_not_selected(self):
        """真机面板语义：诅咒之力（slot0，对位刷新券/杀敌小）不得被选中。"""
        cards = _load_descriptions()["cards"]
        decision = choose_action(
            _panel(
                [
                    _slot(
                        0,
                        "诅咒之力",
                        rarity="red",
                        description=cards["诅咒之力"]["description"],
                    ),
                    _slot(1, "刷新券", rarity="blue", description="技能免费刷新次数+1"),
                    _slot(2, "杀敌(小)", rarity="green", description="杀敌数+400"),
                ],
                settings=PolicySettings(),
            )
        )
        if decision.action == PolicyAction.SELECT_SLOT:
            self.assertIn(decision.index, (1, 2))
        else:
            self.assertIn(decision.action, NO_PICK)

    def test_raise_cap_real_panel_not_selected(self):
        """真机面板语义：提高上限（攻速-200%）不得被选中。"""
        cards = _load_descriptions()["cards"]
        decision = choose_action(
            _panel(
                [
                    _slot(0, "属性神符", rarity="green", description="每击杀1名敌人，获得1点随机属性"),
                    _slot(
                        1,
                        "提高上限",
                        rarity="orange",
                        description=cards["提高上限"]["description"],
                    ),
                    _slot(2, "金币(中)", rarity="blue", description="金币+10000"),
                ],
                settings=PolicySettings(),
            )
        )
        if decision.action == PolicyAction.SELECT_SLOT:
            self.assertIn(decision.index, (0, 2))
        else:
            self.assertIn(decision.action, NO_PICK)


class TreasureNegativeEvidencePaths(unittest.TestCase):
    """DESCRIPTIONS / INDEX 引用的证据文件必须真实存在（防路径漂移）。"""

    def test_description_evidence_files_exist(self):
        cards = _load_descriptions()["cards"]
        for name, meta in cards.items():
            for rel in meta.get("evidence") or []:
                path = ROOT / rel.replace("\\", "/")
                with self.subTest(name=name, rel=rel):
                    self.assertTrue(path.is_file(), path)

    def test_index_panel_files_exist(self):
        for entry in _load_index()["entries"]:
            for rel in entry.get("panels") or []:
                path = ROOT / rel.replace("\\", "/")
                with self.subTest(name=entry["name"], rel=rel):
                    self.assertTrue(path.is_file(), path)


if __name__ == "__main__":
    unittest.main()
