"""选卡决策语义契约（2026-08-12 用户决策）。

这些不是「某次事故的回归」，而是产品语义本身。任何实现（现在的 mediator 临时
逻辑、将来接线的 choice_policy）都必须满足；违反即视为缺陷，不是「行为变更」。

用户在 2026-08-12 明确的三条：

  S1 预设技能按稀有度优先
     「预设技能不是越稀有权重越高吗」——实机里预设里有橙色却选了紫/蓝。
     旧实现按槽位从左到右取第一个命中，稀有度完全没进排序。

  S2 羁绊/卡牌未勾选 = 硬禁用
     「海盗都明确 ban 了还是每次都拿海盗」——UI 勾选框此前只是「偏好」，
     未命中就落到品质色/第一张兜底。现在：未勾选一律不选，三槽全未勾选
     宁可刷新/放弃/隐藏，也不乱拿。硬禁用必须同时封住套装进度与品质降级
     两条旁路，否则 ban 名单形同虚设。

  S3 负面宝物默认不选，勾选后才放行
     形如「获得50万金币，5分钟后不再获得金币」「直接升到25级，之后不再升级」。
     判定依据是**卡面描述原文**而不是卡名黑名单——实机宝物面板的效果描述就在
     卡名下方且可 OCR（已由 tests/performance/fixtures/treasure_panel.png 证实），
     按描述判定可覆盖没见过的新卡。用户在 UI 折叠区打勾的才允许被选。

另有一条防呆：
  S4 品质序必须含 green
     实机宝物面板存在绿边卡（如「双倍神符」）；早期 RARITY_BANDS 缺 green，
     绿边卡在品质逻辑里等于「无颜色」。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.choice_policy import (  # noqa: E402
    DEFAULT_QUALITY_ORDER,
    DEFAULT_TREASURE_MUST_TAKE,
    PANEL_BOND,
    PANEL_SKILL,
    PANEL_TREASURE,
    WHITELIST_HARD,
    PanelCandidates,
    PolicyAction,
    PolicySettings,
    SessionState,
    SlotCandidate,
    assemble_policy_settings,
    choose_action,
    is_negative_treasure,
)

PICK_ACTIONS = {PolicyAction.SELECT_SLOT}
NO_PICK_ACTIONS = {PolicyAction.WAIT, PolicyAction.REFRESH,
                   PolicyAction.GIVEUP, PolicyAction.CLOSE}

# 组装测试用的技能短码 → 中文主技能名（与 config/skill_labels.json 同构）。
SKILL_LABELS = {
    "jq": "剑气", "pg": "普攻", "asj": "奥数箭",
    "asjg": "奥术激光", "hbj": "寒冰箭",
}


def _slot(index, name=None, rarity=None, confidence=0.95, description=""):
    return SlotCandidate(
        index=index, name=name, confidence=confidence,
        rarity=rarity, description=description,
    )


def _panel(kind, slots, **kw):
    return PanelCandidates(panel_kind=kind, slots=tuple(slots), **kw)


class S1SkillRarityPriority(unittest.TestCase):
    """S1：预设技能按稀有度优先，位置只做最后 tie-break。"""

    PRESETS = ["奥数箭", "奥数激光", "奥数射线", "剑气"]

    def test_orange_preset_beats_leftmost_blue_preset(self):
        """实机症状：橙色奥术箭在右、蓝色预设在左，旧实现选了蓝色。"""
        decision = choose_action(_panel(
            PANEL_SKILL,
            [
                _slot(0, "剑气", rarity="blue"),
                _slot(1, "奥数激光", rarity="purple"),
                _slot(2, "奥数箭", rarity="orange"),
            ],
            settings=PolicySettings(skill_presets=tuple(self.PRESETS)),
        ))
        self.assertEqual(decision.action, PolicyAction.SELECT_SLOT)
        self.assertEqual(decision.index, 2, "橙色预设必须胜过更靠左的蓝/紫预设")

    def test_full_rarity_ladder_is_respected(self):
        """红>橙>紫>蓝>白>绿：逐档验证，最高档永远赢。"""
        ladder = ["red", "orange", "purple", "blue", "white", "green"]
        for better in range(len(ladder)):
            for worse in range(better + 1, len(ladder)):
                with self.subTest(better=ladder[better], worse=ladder[worse]):
                    decision = choose_action(_panel(
                        PANEL_SKILL,
                        [
                            # 更差的品质放在更靠左、且配置顺序更靠前的位置，
                            # 确保胜出只可能来自稀有度。
                            _slot(0, "奥数箭", rarity=ladder[worse]),
                            _slot(1, "剑气", rarity=ladder[better]),
                        ],
                        settings=PolicySettings(skill_presets=("奥数箭", "剑气")),
                    ))
                    self.assertEqual(decision.index, 1)

    def test_same_rarity_falls_back_to_config_order(self):
        """同稀有度时用户配置顺序才生效（顺序是用户意图）。"""
        decision = choose_action(_panel(
            PANEL_SKILL,
            [_slot(0, "剑气", rarity="orange"), _slot(1, "奥数箭", rarity="orange")],
            settings=PolicySettings(skill_presets=("奥数箭", "剑气")),
        ))
        self.assertEqual(decision.index, 1, "同品质时配置里更靠前的预设优先")

    def test_non_preset_orange_never_beats_preset(self):
        """稀有度只在预设之间排序，绝不让非预设技能因为品质高被选中。"""
        decision = choose_action(_panel(
            PANEL_SKILL,
            [_slot(0, "陨石", rarity="red"), _slot(1, "剑气", rarity="green")],
            settings=PolicySettings(skill_presets=("剑气",)),
        ))
        self.assertEqual(decision.index, 1, "红色非预设不得胜过绿色预设")


class S2BondWhitelistIsHard(unittest.TestCase):
    """S2：羁绊未勾选 = 硬禁用；必须同时封住套装与品质两条旁路。"""

    def test_unchecked_bond_is_never_selected_even_alone(self):
        """三槽全是未勾选（如海盗）→ 不选，转刷新/等待/放弃。"""
        decision = choose_action(
            _panel(
                PANEL_BOND,
                [
                    _slot(0, "海盗", rarity="red"),
                    _slot(1, "利刃海盗", rarity="orange"),
                    _slot(2, "白赚海盗", rarity="purple"),
                ],
                has_giveup=True,
                settings=PolicySettings(bond_presets=("暴击", "法术")),
            ),
            SessionState(),
        )
        self.assertIn(decision.action, NO_PICK_ACTIONS)
        self.assertIsNone(decision.index)

    def test_hard_ban_blocks_synthesis_bypass(self):
        """套装进度不得把白名单外的羁绊放进来（否则 ban 形同虚设）。"""
        decision = choose_action(_panel(
            PANEL_BOND,
            [_slot(0, "利刃海盗"), _slot(1, "海盗劫掠者")],
            set_progress={
                "海盗": {
                    "have": 1, "need": 2,
                    "members": ["海盗", "利刃海盗", "海盗劫掠者"],
                    "owned": ["海盗"],
                }
            },
            settings=PolicySettings(bond_presets=("暴击",)),
        ))
        self.assertIn(decision.action, NO_PICK_ACTIONS)

    def test_hard_ban_blocks_quality_bypass(self):
        """品质降级不得把白名单外的羁绊放进来。"""
        decision = choose_action(_panel(
            PANEL_BOND,
            [_slot(0, "海盗", rarity="red")],
            settings=PolicySettings(bond_presets=("暴击",)),
        ))
        self.assertIn(decision.action, NO_PICK_ACTIONS)

    def test_whitelisted_bond_is_still_selected(self):
        """硬禁用不是「什么都不拿」：勾选过的照常拿。"""
        decision = choose_action(_panel(
            PANEL_BOND,
            [_slot(0, "海盗", rarity="red"), _slot(1, "暴击", rarity="white")],
            settings=PolicySettings(bond_presets=("暴击",)),
        ))
        self.assertEqual((decision.action, decision.index),
                         (PolicyAction.SELECT_SLOT, 1))

    def test_soft_mode_still_available_for_explicit_opt_out(self):
        """soft 模式仍保留（宝物在用），但必须显式声明才生效。"""
        hard = PolicySettings(bond_presets=())
        self.assertEqual(hard.bond_whitelist_mode, "hard", "默认必须是硬禁用")
        decision = choose_action(_panel(
            PANEL_BOND,
            [_slot(0, "海盗", rarity="red")],
            settings=PolicySettings(bond_presets=(), bond_whitelist_mode="soft"),
        ))
        self.assertEqual(decision.action, PolicyAction.SELECT_SLOT)


class S3NegativeTreasureOptIn(unittest.TestCase):
    """S3：负面宝物默认不选；只有 UI 勾选放行的才可选。"""

    # 用户口述的三类（具体数值以实机截图为准，措辞按卡面描述匹配）
    NEGATIVE_SAMPLES = (
        "立即获得50万金币，5分钟后不再获得金币",
        "立即获得666木材，5分钟后不再获得木材",
        "立即升级到25级，之后不再升级",
    )

    def test_described_negative_is_detected(self):
        settings = PolicySettings()
        for text in self.NEGATIVE_SAMPLES:
            with self.subTest(text=text):
                self.assertTrue(
                    is_negative_treasure(_slot(0, "某宝物", description=text), settings)
                )

    def test_positive_description_is_not_flagged(self):
        """正面卡不得被误判（取自实机 treasure_panel.png 的真实描述）。"""
        settings = PolicySettings()
        for text in (
            "在接下来30秒内：攻击增幅+100%",
            "每次抽卡获得羁绊卡牌，全属性+10",
            "每消耗500金币，获得1点随机属性",
        ):
            with self.subTest(text=text):
                self.assertFalse(
                    is_negative_treasure(_slot(0, "某宝物", description=text), settings)
                )

    def test_negative_treasure_not_selected_even_when_highest_rarity(self):
        decision = choose_action(_panel(
            PANEL_TREASURE,
            [
                _slot(0, "断金币宝物", rarity="red",
                      description="立即获得50万金币，5分钟后不再获得金币"),
                _slot(1, "双倍神符", rarity="green",
                      description="在接下来30秒内：攻击增幅+100%"),
            ],
            settings=PolicySettings(),
        ))
        self.assertEqual((decision.action, decision.index),
                         (PolicyAction.SELECT_SLOT, 1),
                         "红色负面卡不得胜过绿色正面卡")

    def test_all_negative_panel_takes_no_card(self):
        decision = choose_action(
            _panel(
                PANEL_TREASURE,
                [
                    _slot(0, "断金币", rarity="red", description="5分钟后不再获得金币"),
                    _slot(1, "断木材", rarity="orange", description="5分钟后不再获得木材"),
                ],
                has_giveup=True,
                settings=PolicySettings(),
            ),
            SessionState(),
        )
        self.assertIn(decision.action, NO_PICK_ACTIONS)

    def test_opt_in_allows_the_checked_negative_treasure(self):
        """勾选放行后可选——这是「折叠起来打勾才会选」的语义。"""
        decision = choose_action(_panel(
            PANEL_TREASURE,
            [_slot(0, "断金币", rarity="red", description="5分钟后不再获得金币")],
            settings=PolicySettings(treasure_allow_negative=("断金币",)),
        ))
        self.assertEqual((decision.action, decision.index),
                         (PolicyAction.SELECT_SLOT, 0))

    def test_opt_in_is_per_card_not_global(self):
        """放行是逐卡的：勾了断金币不等于放行断木材。"""
        decision = choose_action(_panel(
            PANEL_TREASURE,
            [
                _slot(0, "断木材", rarity="red", description="5分钟后不再获得木材"),
                _slot(1, "断金币", rarity="white", description="5分钟后不再获得金币"),
            ],
            settings=PolicySettings(treasure_allow_negative=("断金币",)),
        ))
        self.assertEqual(decision.index, 1, "只有被勾选的那张负面卡可选")

    def test_missing_description_is_not_guessed_negative(self):
        """未确认的卡在读不到描述时不得凭卡名猜负面（宁可当正面，由白名单/品质把关）。

        注意与已确认名单的区别：用户逐张确认过的 6 张（见 CONFIRMED_NEGATIVE）
        即使描述缺失也照拦；这里测的是名单之外的卡。
        """
        settings = PolicySettings()
        for name in ("命运骰子", "百宝箱", "刷新券"):
            with self.subTest(name=name):
                self.assertNotIn(name, settings.treasure_negative_names)
                self.assertFalse(
                    is_negative_treasure(_slot(0, name, description=""), settings)
                )

    CONFIRMED_NEGATIVE = (
        "透支力量", "贪婪献祭", "金转木", "杀敌梭哈", "伐木契约", "等级优势",
    )

    def test_confirmed_negative_names_blocked_without_description(self):
        """用户 2026-08-12 逐张确认的 6 张：描述 OCR 失败时也必须拦住。"""
        settings = PolicySettings()
        for name in self.CONFIRMED_NEGATIVE:
            with self.subTest(name=name):
                self.assertTrue(
                    is_negative_treasure(_slot(0, name, description=""), settings),
                    f"{name} 已确认为负面宝物，缺描述时仍应拦截",
                )

    def test_confirmed_negative_still_respects_opt_in(self):
        """确认名单不是死锁：勾选放行后照样可选（放行优先级最高）。"""
        settings = PolicySettings(treasure_allow_negative=("贪婪献祭",))
        self.assertFalse(
            is_negative_treasure(_slot(0, "贪婪献祭", description=""), settings)
        )
        self.assertTrue(
            is_negative_treasure(_slot(1, "金转木", description=""), settings),
            "放行是逐卡的，不得连带放行其它负面卡",
        )


class S4QualityOrderIncludesGreen(unittest.TestCase):
    """S4：品质序必须含 green（实机绿边卡存在）。"""

    def test_green_present_and_lowest(self):
        self.assertIn("green", DEFAULT_QUALITY_ORDER)
        self.assertEqual(DEFAULT_QUALITY_ORDER[-1], "green")

    def test_green_ranks_below_white(self):
        decision = choose_action(_panel(
            PANEL_TREASURE,
            [_slot(0, "绿卡", rarity="green"), _slot(1, "白卡", rarity="white")],
            settings=PolicySettings(),
        ))
        self.assertEqual(decision.index, 1, "白必须优于绿")


class S5DeterminismStillHolds(unittest.TestCase):
    """新语义不得破坏纯函数性：同输入恒同输出。"""

    def test_repeated_calls_identical(self):
        panel = _panel(
            PANEL_TREASURE,
            [
                _slot(0, "断金币", rarity="red", description="5分钟后不再获得金币"),
                _slot(1, "双倍神符", rarity="green", description="攻击增幅+100%"),
                _slot(2, None, rarity="orange"),
            ],
            settings=PolicySettings(treasure_presets=("双倍神符",)),
        )
        first = choose_action(panel, SessionState())
        for _ in range(20):
            self.assertEqual(choose_action(panel, SessionState()), first)


class S6SkillModeStrict(unittest.TestCase):
    """S6：技能恒定严格档——仅焦点系/卡（skill_focus_families 展开 ∪ skill_presets），
    未配置 → CLOSE；非焦点卡宁可刷新/隐藏也不拿。"""

    @staticmethod
    def _runtime(skills, **extra):
        return SimpleNamespace(
            skills=list(skills), cards=[], treasure_allow_negative=[], **extra
        )

    def test_assembly_zero_to_four_raw_skills_are_focus_families(self):
        for count in range(5):
            with self.subTest(count=count):
                ps = assemble_policy_settings(
                    settings=self._runtime(list(SKILL_LABELS)[:count]),
                    skill_labels=SKILL_LABELS, fetter_labels={}, policy_doc={},
                )
                self.assertEqual(
                    ps.skill_focus_families,
                    tuple(SKILL_LABELS[c] for c in list(SKILL_LABELS)[:count]),
                )

    def test_assembly_five_or_more_raw_skills_stay_strict(self):
        ps = assemble_policy_settings(
            settings=self._runtime(list(SKILL_LABELS)[:5]),
            skill_labels=SKILL_LABELS, fetter_labels={}, policy_doc={},
        )
        self.assertEqual(
            ps.skill_focus_families, tuple(SKILL_LABELS[c] for c in list(SKILL_LABELS)[:5])
        )
        self.assertFalse(hasattr(ps, "skill_whitelist_mode"))

    def test_hard_mode_rejects_non_focus_card(self):
        """面板出现目录合法但未勾选系的卡 → 宁可刷新也不拿（硬拒绝）。"""
        decision = choose_action(_panel(
            PANEL_SKILL,
            [_slot(0, "箭矢增幅", rarity="red")],
            settings=PolicySettings(skill_focus_families=("剑气",)),
        ), SessionState())
        self.assertIn(decision.action, NO_PICK_ACTIONS)
        self.assertIsNone(decision.index)


class S7VerifiedEvidencePriority(unittest.TestCase):
    """S7：已核实前置/存档只影响优先级，绝不硬拒绝。"""

    def test_owned_prereq_affects_priority(self):
        decision = choose_action(_panel(
            PANEL_SKILL,
            [_slot(0, "剑气增幅", rarity="white"),
             _slot(1, "箭矢增幅", rarity="white")],
            settings=PolicySettings(skill_focus_families=("剑气", "奥数箭")),
        ), SessionState())
        self.assertEqual(decision.index, 0, "无已拥有时两者前置均未确认，取最小 index")
        decision = choose_action(PanelCandidates(
            panel_kind=PANEL_SKILL,
            slots=[_slot(0, "剑气增幅", rarity="white"),
                   _slot(1, "箭矢增幅", rarity="white")],
            settings=PolicySettings(skill_focus_families=("剑气", "奥数箭")),
            owned_skill_cards=("奥术箭",),
        ), SessionState())
        self.assertEqual(decision.index, 1, "已拥有奥术箭 → 箭矢增幅前置确认优先")

    def test_archive_waiver_and_penalty_affect_priority(self):
        # 存档奥术箭36 豁免爆炸箭矢的爆炎箭前置（+owned 奥术箭）→ 前置确认优先。
        decision = choose_action(PanelCandidates(
            panel_kind=PANEL_SKILL,
            slots=[_slot(0, "激光增幅", rarity="white"),
                   _slot(1, "爆炸箭矢", rarity="white")],
            settings=PolicySettings(skill_focus_families=("奥数箭", "奥数激光"),
                                    skill_archive_levels=(("asj", 36),)),
            owned_skill_cards=("奥术箭",),
        ), SessionState())
        self.assertEqual(decision.index, 1)
        # 存档奥术箭10：箭矢齐射「不再降低伤害」已核实 → 优先。
        decision = choose_action(_panel(
            PANEL_SKILL,
            [_slot(0, "激光增幅", rarity="white"),
             _slot(1, "箭矢齐射", rarity="white")],
            settings=PolicySettings(skill_focus_families=("奥数箭", "奥数激光"),
                                    skill_archive_levels=(("asj", 10),)),
        ), SessionState())
        self.assertEqual(decision.index, 1)

    def test_unmet_prereq_is_priority_penalty_not_rejection(self):
        """前置未确认 ≠ 禁止：唯一候选仍选（只排序，不否决）。"""
        decision = choose_action(_panel(
            PANEL_SKILL,
            [_slot(0, "爆炸箭矢", rarity="white")],
            settings=PolicySettings(skill_focus_families=("奥数箭",)),
        ), SessionState())
        self.assertEqual((decision.action, decision.index),
                         (PolicyAction.SELECT_SLOT, 0))

    def test_assembly_deterministic_and_focus_families(self):
        runtime = SimpleNamespace(
            skills=list(SKILL_LABELS)[:5],
            cards=[], treasure_allow_negative=[],
        )
        kwargs = dict(
            settings=runtime,
            skill_labels=SKILL_LABELS, fetter_labels={},
            policy_doc={"min_confidence": 0.65},
        )
        first = assemble_policy_settings(**kwargs)
        self.assertEqual(first.skill_focus_families, tuple(SKILL_LABELS[c] for c in list(SKILL_LABELS)[:5]))
        for _ in range(10):
            self.assertEqual(assemble_policy_settings(**kwargs), first)
        # 4 个原始技能展开后卡名更多，焦点系仍为原始 4 个。
        ps = assemble_policy_settings(
            settings=SimpleNamespace(
                skills=list(SKILL_LABELS)[:4],
                cards=[], treasure_allow_negative=[],
            ),
            skill_labels=SKILL_LABELS, fetter_labels={}, policy_doc={},
        )
        self.assertEqual(ps.skill_focus_families, tuple(SKILL_LABELS[c] for c in list(SKILL_LABELS)[:4]))
        self.assertGreater(len(ps.skill_presets), 4)


class S8TreasureMustTake(unittest.TestCase):
    """S8：必拿宝物名单来自 settings.treasure_must_take（缺省保留旧版特权）。"""

    def test_must_take_comes_from_settings(self):
        """配置名单（如 ONEPIECE）里的卡无视品质直接秒选。"""
        decision = choose_action(_panel(
            PANEL_TREASURE,
            [_slot(0, "双倍神符", rarity="green"), _slot(1, "ONEPIECE")],
            settings=PolicySettings(treasure_must_take=("ONEPIECE",)),
        ), SessionState())
        self.assertEqual((decision.action, decision.index),
                         (PolicyAction.SELECT_SLOT, 1))

    def test_default_must_take_preserves_legacy_privilege(self):
        """缺省名单保留旧版「全都要/卡牌大师」子串特权（默认行为不回归）。"""
        decision = choose_action(_panel(
            PANEL_TREASURE,
            [_slot(0, "我全都要", rarity="white"),
             _slot(1, "双倍神符", rarity="red")],
            settings=PolicySettings(),
        ), SessionState())
        self.assertEqual((decision.action, decision.index),
                         (PolicyAction.SELECT_SLOT, 0),
                         "特权卡必须压过红色非必拿卡")

    def test_must_take_does_not_bypass_negative(self):
        """负面剔除优先于必拿：必拿名单内带负面描述的卡仍不可选。"""
        decision = choose_action(_panel(
            PANEL_TREASURE,
            [_slot(0, "ONEPIECE", description="5分钟后不再获得金币")],
            settings=PolicySettings(treasure_must_take=("ONEPIECE",)),
        ), SessionState())
        self.assertIn(decision.action, NO_PICK_ACTIONS)

    def test_default_must_take_constant(self):
        self.assertEqual(DEFAULT_TREASURE_MUST_TAKE, ("全都要", "卡牌大师"))
        self.assertEqual(WHITELIST_HARD, "hard")


if __name__ == "__main__":
    unittest.main()
