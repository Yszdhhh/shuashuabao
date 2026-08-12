"""D 组：负面宝物真机描述夹具契约（2026-08-12）。

数据源：``fixtures/treasure_negative/DESCRIPTIONS.json`` + ``INDEX.json``。
不修改 ``test_choice_semantics_contract.py``（属主 agent）；本文件独立断言：

1. 已确认 6 张卡名 + 真机描述 → ``is_negative_treasure`` 为真（名字路径）
2. 名单外卡不得仅凭名字可疑 / 空描述猜负面
3. 口述负面样例仍被 ``DEFAULT_NEGATIVE_PATTERNS`` 覆盖（给新卡兜底）
4. 真机面板端到端：负面槽不被 ``choose_action`` 选中
5. 明确列出当前 patterns 缺口（不改 config；交回主 agent 只补不删）

红线：无合成帧；不改 GATE_BASELINE 糊弄。
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from gamescript.choice_policy import (  # noqa: E402
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
    """夹具包本身必须完整：6 张卡、描述原文、至少一块真机面板。"""

    def test_descriptions_and_index_exist(self):
        self.assertTrue(DESCRIPTIONS_PATH.is_file(), DESCRIPTIONS_PATH)
        self.assertTrue(INDEX_PATH.is_file(), INDEX_PATH)
        self.assertTrue((FIXTURE_DIR / "README.md").is_file())

    def test_six_confirmed_names_present(self):
        desc = _load_descriptions()
        index = _load_index()
        expected = set(DEFAULT_NEGATIVE_NAMES)
        self.assertEqual(set(desc["cards"]), expected)
        self.assertEqual(set(index["names"]), expected)
        for name in expected:
            card_dir = FIXTURE_DIR / name
            self.assertTrue(card_dir.is_dir(), f"missing dir {card_dir}")
            panels = list(card_dir.glob("panel_*.png")) + list(card_dir.glob("panel_*.jpg"))
            self.assertGreaterEqual(len(panels), 1, f"{name} needs ≥1 real panel frame")
            self.assertTrue(str(desc["cards"][name].get("description") or "").strip())


class TreasureNegativeNameAndDescription(unittest.TestCase):
    """真机描述 + 确认名单：is_negative_treasure 必须拦住。"""

    def test_fixture_cards_blocked_with_real_descriptions(self):
        settings = PolicySettings()
        cards = _load_descriptions()["cards"]
        for name, meta in cards.items():
            with self.subTest(name=name):
                self.assertIn(name, settings.treasure_negative_names)
                self.assertTrue(
                    is_negative_treasure(
                        _slot(0, name, description=meta["description"]),
                        settings,
                    ),
                    f"{name} + 真机描述应判负面",
                )

    def test_fixture_cards_blocked_even_with_empty_description(self):
        """名字判定与描述判定互为冗余：OCR 失败时仍拦。"""
        settings = PolicySettings()
        for name in _load_descriptions()["cards"]:
            with self.subTest(name=name):
                self.assertTrue(
                    is_negative_treasure(_slot(0, name, description=""), settings)
                )

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
        """真机原文相对 DEFAULT_NEGATIVE_PATTERNS 的缺口清单（只文档化，不改 config）。

        缺口详情与建议追加串见 DESCRIPTIONS.json::suggested_pattern_appends_for_main_agent。
        本测试锁定「哪些卡目前无法仅靠 patterns 拦」，避免 silent drift。
        """
        cards = _load_descriptions()["cards"]
        gaps = {
            name: meta["description"]
            for name, meta in cards.items()
            if not _patterns_hit(meta["description"])
        }
        # 六张真机原文目前均不能仅靠现有 patterns 兜底（贪婪/等级等甚至无可用 hint）。
        self.assertEqual(
            set(gaps),
            set(DEFAULT_NEGATIVE_NAMES),
            "若主 agent 已补 patterns 使某卡 description-only 可拦，请同步收紧本断言",
        )
        suggested = _load_descriptions()["suggested_pattern_appends_for_main_agent"]
        for token in ("消耗全部金币", "将恒定", "杀敌数清0"):
            self.assertIn(token, suggested)

        # 带 pattern_hints 的卡：hints 本身应出现在建议列表或描述中，便于主 agent 追加。
        for name, meta in cards.items():
            for hint in meta.get("pattern_hints") or []:
                with self.subTest(name=name, hint=hint):
                    self.assertTrue(
                        hint in meta["description"] or hint in suggested,
                        f"{name} pattern_hint={hint!r} 未落入描述或建议追加列表",
                    )


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
