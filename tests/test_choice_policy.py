"""P0 确定性选择策略单测（蓝图 §12，纯函数）。

覆盖：预设命中 / 预设缺失刷新 / 刷新耗尽放弃 / unknown 不点击 /
品质降级顺序 / 套装进度优先（龙珠可验证字段）/ 并列 tie-break /
WAIT 上限 / 技能永不非预设 / 确定性（同输入同输出）/ 动作枚举合法性 /
panel_priority / 无面板 NONE / 期限与尝试上限抢占。

运行：PYTHONPATH=src python -m unittest tests.test_choice_policy -v
"""

from __future__ import annotations

import itertools
import unittest
from types import SimpleNamespace

from shuabao.card_fact import CardFact
from shuabao.choice_policy import (
    DEFAULT_QUALITY_ORDER,
    DEFAULT_TREASURE_MUST_TAKE,
    PANEL_BOND,
    PANEL_SKILL,
    PANEL_TREASURE,
    WHITELIST_HARD,
    PanelCandidates,
    PolicyAction,
    PolicyDecision,
    PolicySettings,
    SessionState,
    SlotCandidate,
    assemble_policy_settings,
    choose_action,
    panel_priority,
    slot_fingerprint,
    _rank_skill_candidates,
)

# 便捷构造 -----------------------------------------------------------------


def slot(index, name=None, confidence=0.95, rarity=None, description=""):
    return SlotCandidate(
        index=index,
        name=name,
        confidence=confidence,
        rarity=rarity,
        description=description,
    )


def skill_cands(slots=(), **kw):
    return PanelCandidates(panel_kind=PANEL_SKILL, slots=tuple(slots), **kw)


def bond_cands(slots=(), **kw):
    return PanelCandidates(panel_kind=PANEL_BOND, slots=tuple(slots), **kw)


def treasure_cands(slots=(), **kw):
    return PanelCandidates(panel_kind=PANEL_TREASURE, slots=tuple(slots), **kw)


def settings(**kw):
    return PolicySettings.from_mapping(kw)


class TestSkillPolicy(unittest.TestCase):
    """技能：仅预设；预设缺失刷新；刷新耗尽放弃；永不非预设。"""

    def test_preset_hit_selects_lowest_index(self):
        d = choose_action(
            skill_cands(
                [slot(0, "地震"), slot(1, "剑气"), slot(2, "寒冰箭")],
                settings=settings(skill_presets=["剑气"]),
            )
        )
        self.assertEqual(d.action, PolicyAction.SELECT_SLOT)
        self.assertEqual(d.index, 1)

    def test_preset_respects_config_order_not_visual_order(self):
        # 配置顺序优先：预设 [寒冰箭, 剑气] 命中寒冰箭（即使剑气 index 更小）。
        d = choose_action(
            skill_cands(
                [slot(0, "剑气"), slot(1, "寒冰箭")],
                settings=settings(skill_presets=["寒冰箭", "剑气"]),
            )
        )
        self.assertEqual(d.action, PolicyAction.SELECT_SLOT)
        self.assertEqual(d.index, 1)

    def test_same_preset_multiple_slots_tie_break_lowest_index(self):
        # 同预设出现在多槽（理论上不该，但并列规则要求确定性）。
        d = choose_action(
            skill_cands(
                [slot(2, "剑气"), slot(0, "剑气"), slot(1, "地震")],
                settings=settings(skill_presets=["剑气"]),
            )
        )
        self.assertEqual((d.action, d.index), (PolicyAction.SELECT_SLOT, 0))

    def test_preset_missing_refresh(self):
        d = choose_action(
            skill_cands(
                [slot(0, "地震"), slot(1, "剑气")],
                settings=settings(skill_presets=["寒冰箭"]),
            ),
            SessionState(),
        )
        self.assertEqual(d.action, PolicyAction.CLOSE)
        self.assertIsNone(d.index)

    def test_refresh_exhausted_giveup(self):
        d = choose_action(
            skill_cands(
                [slot(0, "地震")], has_giveup=True,
                settings=settings(skill_presets=["寒冰箭"]),
            ),
            SessionState(refreshes=3, max_refreshes=3),
        )
        self.assertEqual(d.action, PolicyAction.CLOSE)
        self.assertIsNone(d.index)
        d = choose_action(
            skill_cands(
                [slot(0, "地震")], has_giveup=True,
                settings=settings(skill_presets=["寒冰箭"], allow_skill_giveup=True),
            ),
            SessionState(refreshes=3, max_refreshes=3),
        )
        # 技能 panel 恒定严格：即使 allow_skill_giveup=True，Focus-Miss 也恒定 CLOSE，永不 GIVEUP
        self.assertEqual(d.action, PolicyAction.CLOSE)
        self.assertIsNone(d.index)

    def test_refresh_exhausted_no_giveup_close(self):
        d = choose_action(
            skill_cands(
                [slot(0, "地震")], has_giveup=False,
                settings=settings(skill_presets=["寒冰箭"]),
            ),
            SessionState(refreshes=3, max_refreshes=3),
        )
        self.assertEqual(d.action, PolicyAction.CLOSE)
        self.assertIsNone(d.index)

    def test_never_select_high_confidence_non_preset_skill(self):
        # 候选含高置信非预设技能：未命中预设恒定 CLOSE（宁可不选也不乱拿，不刷新）。
        d = choose_action(
            skill_cands(
                [slot(0, "剑气", confidence=0.99), slot(1, "地震", confidence=0.98)],
                settings=settings(skill_presets=["寒冰箭"]),
            ),
            SessionState(),
        )
        self.assertNotEqual(d.action, PolicyAction.SELECT_SLOT)
        self.assertEqual(d.action, PolicyAction.CLOSE)
        d = choose_action(
            skill_cands(
                [slot(0, "剑气", confidence=0.99)],
                settings=settings(skill_presets=[]),
            ),
            SessionState(),
        )
        self.assertNotEqual(d.action, PolicyAction.SELECT_SLOT)

    def test_unknown_skill_slots_never_select(self):
        d = choose_action(
            skill_cands(
                [slot(0, None), slot(1, None)],
                settings=settings(skill_presets=["剑气"]),
            ),
            SessionState(),
        )
        self.assertNotEqual(d.action, PolicyAction.SELECT_SLOT)
        self.assertEqual(d.action, PolicyAction.WAIT)

    def test_empty_names_never_giveup_even_with_button(self):
        d = choose_action(
            skill_cands(
                [slot(0, None), slot(1, None), slot(2, None)],
                has_giveup=True,
                settings=settings(skill_presets=["asj", "爆炸箭矢", "箭矢齐射"]),
            ),
            SessionState(waits=5, max_waits=5, refreshes=3, max_refreshes=3),
        )
        self.assertNotEqual(d.action, PolicyAction.GIVEUP)
        self.assertIn(d.action, {PolicyAction.CLOSE, PolicyAction.WAIT, PolicyAction.NONE})

    def test_trace_231455_preset_names_select(self):
        d = choose_action(
            skill_cands(
                [
                    slot(0, "爆炸箭矢", rarity="purple"),
                    slot(1, "闪电链", rarity="blue"),
                    slot(2, "箭矢齐射", rarity="purple"),
                ],
                settings=settings(
                    skill_presets=["爆炸箭矢", "闪电链", "箭矢齐射", "奥术箭矢", "剑气"]
                ),
            )
        )
        self.assertEqual(d.action, PolicyAction.SELECT_SLOT)
        self.assertIn(d.index, (0, 1, 2))

    def test_unchanged_refresh_fingerprint_no_loop_no_giveup(self):
        slots = [
            slot(0, "陨石", rarity="red"),
            slot(1, "地震", rarity="purple"),
            slot(2, "火球", rarity="blue"),
        ]
        fp = slot_fingerprint(tuple(slots))
        d = choose_action(
            skill_cands(
                slots,
                has_giveup=True,
                settings=settings(skill_presets=["寒冰箭"]),
            ),
            SessionState(
                refreshes=1,
                max_refreshes=3,
                waits=5,
                max_waits=5,
                last_slot_fingerprint=fp,
            ),
        )
        self.assertNotEqual(d.action, PolicyAction.REFRESH)
        self.assertNotEqual(d.action, PolicyAction.GIVEUP)


class TestSkillEmptyConfig(unittest.TestCase):
    """skill_presets / skill_focus_families 均空（用户零勾选）→ 直接 CLOSE。

    零配置不是"读不到卡名"：不 WAIT 不 REFRESH，立即隐藏/关闭技能面板；
    也不受 allow_skill_giveup 影响（零勾选绝不花技能点）。非空配置 + OCR
    不可读的行为不变。
    """

    def test_empty_config_unreadable_slots_close_directly(self):
        d = choose_action(
            skill_cands(
                [slot(0, None), slot(1, None), slot(2, None)],
                settings=settings(),
            ),
            SessionState(),
        )
        self.assertEqual(d.action, PolicyAction.CLOSE)

    def test_empty_config_readable_non_preset_close_directly(self):
        # 卡名可读但没有配置任何焦点系/卡：同样直接 CLOSE，不得走 REFRESH。
        d = choose_action(
            skill_cands(
                [slot(0, "剑气", confidence=0.99)],
                settings=settings(),
            ),
            SessionState(),
        )
        self.assertEqual(d.action, PolicyAction.CLOSE)

    def test_empty_config_never_giveup_even_when_allowed(self):
        d = choose_action(
            skill_cands(
                [slot(0, None), slot(1, None)],
                has_giveup=True,
                settings=settings(allow_skill_giveup=True),
            ),
            SessionState(),
        )
        self.assertEqual(d.action, PolicyAction.CLOSE)

    def test_empty_config_waits_refreshes_exhausted_still_close(self):
        d = choose_action(
            skill_cands(
                [slot(0, None)],
                settings=settings(),
            ),
            SessionState(waits=5, max_waits=5, refreshes=3, max_refreshes=3),
        )
        self.assertEqual(d.action, PolicyAction.CLOSE)

    def test_empty_config_attempts_cap_never_giveup(self):
        # 空配置裁决必须先于 attempts last-resort：attempts=max + has_giveup
        # 也必须 CLOSE，绝不 GIVEUP/REFRESH/SELECT（零配置绝不花技能点）。
        d = choose_action(
            skill_cands(
                [slot(0, "剑气", confidence=0.99)],
                has_giveup=True,
                settings=settings(),
            ),
            SessionState(attempts=12, max_attempts=12),
        )
        self.assertEqual(d.action, PolicyAction.CLOSE)
        self.assertIsNone(d.index)

    def test_empty_config_deadline_exceeded_never_giveup(self):
        # 空配置裁决必须先于 deadline last-resort：deadline_exceeded +
        # has_giveup 也必须 CLOSE，绝不 GIVEUP。
        d = choose_action(
            skill_cands(
                [slot(0, "剑气", confidence=0.99)],
                has_giveup=True,
                settings=settings(),
            ),
            SessionState(deadline_exceeded=True),
        )
        self.assertEqual(d.action, PolicyAction.CLOSE)
        self.assertIsNone(d.index)

    def test_empty_config_never_selects_even_with_remaining_attempts(self):
        # 空配置在任何会话状态下都只 CLOSE：即使 attempts 未耗尽也不 SELECT。
        d = choose_action(
            skill_cands(
                [slot(0, "剑气", confidence=0.99)],
                settings=settings(),
            ),
            SessionState(attempts=3),
        )
        self.assertEqual(d.action, PolicyAction.CLOSE)

    def test_nonempty_attempts_cap_still_giveup(self):
        # 技能 panel attempts=max 时恒 CLOSE（不放弃技能点）。
        d = choose_action(
            skill_cands(
                [slot(0, "剑气", confidence=0.99)],
                has_giveup=True,
                settings=settings(skill_presets=["剑气"]),
            ),
            SessionState(attempts=12, max_attempts=12),
        )
        self.assertEqual(d.action, PolicyAction.CLOSE)
    def test_nonempty_config_unreadable_unchanged_waits(self):
        # 非空配置 + OCR 不可读：保持旧行为（WAIT → 耗尽后 CLOSE）。
        d = choose_action(
            skill_cands(
                [slot(0, None), slot(1, None)],
                settings=settings(skill_presets=["剑气"]),
            ),
            SessionState(),
        )
        self.assertEqual(d.action, PolicyAction.WAIT)

    def test_nonempty_focus_families_unreadable_unchanged_waits(self):
        d = choose_action(
            skill_cands(
                [slot(0, None)],
                settings=settings(skill_focus_families=["箭术"]),
            ),
            SessionState(),
        )
        self.assertEqual(d.action, PolicyAction.WAIT)


class TestBondTreasureUnknown(unittest.TestCase):
    """羁绊/宝物：unknown 绝不点击，阻塞面板直接关闭。"""

    def test_near_complete_bond_takes_immediately(self):
        policy = settings(
            bond_presets=["成长", "经济", "贪婪", "挑战", "暴击"],
            bond_base_presets=["成长", "经济", "贪婪", "挑战", "暴击"],
            bond_advanced_presets=["封神"],
        )
        d = choose_action(
            bond_cands(
                [
                    SlotCandidate(index=0, name="三国", confidence=0.90),
                    SlotCandidate(index=1, name="刀刀", confidence=0.90),
                    SlotCandidate(index=2, name="挑战", confidence=0.52, evidence="挑战(2/3)"),
                    SlotCandidate(index=3, name="暴击", confidence=0.70, evidence="暴击(0/2)"),
                ],
                settings=policy,
            ),
            SessionState(),
        )
        self.assertEqual((d.action, d.index), (PolicyAction.SELECT_SLOT, 2))
        self.assertIn("差一张合成", d.reason)

    def test_advanced_bond_waits_for_eighty_percent_base_progress(self):
        policy = settings(
            bond_presets=["成长", "经济", "贪婪", "挑战", "封神"],
            bond_base_presets=["成长", "经济", "贪婪", "挑战"],
            bond_advanced_presets=["封神"],
        )
        d = choose_action(
            bond_cands(
                [slot(0, "封神")], can_refresh=True, settings=policy,
                owned_bond_cards=("成长", "经济"),
            ),
            SessionState(),
        )
        self.assertEqual(d.action, PolicyAction.REFRESH)

    def test_advanced_bond_unlocks_after_eighty_percent_base_progress(self):
        policy = settings(
            bond_presets=["成长", "经济", "贪婪", "挑战", "封神"],
            bond_base_presets=["成长", "经济", "贪婪", "挑战"],
            bond_advanced_presets=["封神"],
        )
        d = choose_action(
            bond_cands(
                [slot(0, "封神")], settings=policy,
                owned_bond_cards=("成长", "经济", "贪婪", "挑战"),
            ),
            SessionState(),
        )
        self.assertEqual((d.action, d.index), (PolicyAction.SELECT_SLOT, 0))

    def test_second_advanced_pack_waits_for_active_pack(self):
        policy = settings(
            bond_presets=["成长", "经济", "贪婪", "挑战", "海盗", "白赚海盗", "海盗劫掠者", "海盗宝藏", "封神"],
            bond_base_presets=["成长", "经济", "贪婪", "挑战"],
            bond_advanced_presets=["海盗", "白赚海盗", "海盗劫掠者", "海盗宝藏", "封神"],
            bond_advanced_groups=(
                ("海盗", "白赚海盗", "海盗劫掠者", "海盗宝藏"),
                ("封神",),
            ),
        )
        d = choose_action(
            bond_cands(
                [slot(0, "封神")], can_refresh=True, settings=policy,
                owned_bond_cards=("成长", "经济", "贪婪", "挑战", "海盗"),
            ),
            SessionState(),
        )
        self.assertEqual(d.action, PolicyAction.REFRESH)

    def test_second_advanced_pack_unlocks_after_active_pack(self):
        policy = settings(
            bond_presets=["成长", "经济", "贪婪", "挑战", "海盗", "白赚海盗", "海盗劫掠者", "海盗宝藏", "封神"],
            bond_base_presets=["成长", "经济", "贪婪", "挑战"],
            bond_advanced_presets=["海盗", "白赚海盗", "海盗劫掠者", "海盗宝藏", "封神"],
            bond_advanced_groups=(
                ("海盗", "白赚海盗", "海盗劫掠者", "海盗宝藏"),
                ("封神",),
            ),
        )
        d = choose_action(
            bond_cands(
                [slot(0, "封神")], settings=policy,
                owned_bond_cards=("成长", "经济", "贪婪", "挑战", "海盗", "白赚海盗", "海盗劫掠者", "海盗宝藏"),
            ),
            SessionState(),
        )
        self.assertEqual((d.action, d.index), (PolicyAction.SELECT_SLOT, 0))

    def test_bond_unknown_only_slot_no_click(self):
        d = choose_action(
            bond_cands([slot(0, None)], settings=settings(bond_presets=["三国"])),
            SessionState(),
        )
        self.assertNotEqual(d.action, PolicyAction.SELECT_SLOT)
        self.assertEqual(d.action, PolicyAction.CLOSE)

    def test_bond_unknown_closes_independent_of_micro_counters(self):
        cands = bond_cands(
            [slot(0, None), slot(1, None)],
            has_giveup=True,
            settings=settings(bond_presets=["三国"]),
        )
        for state in (
            SessionState(),
            SessionState(waits=2, max_waits=2),
            SessionState(waits=9, refreshes=9),
        ):
            with self.subTest(state=state):
                self.assertEqual(choose_action(cands, state).action, PolicyAction.CLOSE)

    def test_bond_unknown_no_giveup_close(self):
        cands = bond_cands(
            [slot(0, None)], has_giveup=False,
            settings=settings(bond_presets=["三国"]),
        )
        d = choose_action(
            cands, SessionState(waits=2, max_waits=2, refreshes=3, max_refreshes=3)
        )
        self.assertEqual(d.action, PolicyAction.CLOSE)

    def test_bond_unknown_never_masquerade_known_bond(self):
        # 构造：unknown 槽位（品质最高）+ 词典内 bond（未命中预设）。
        # unknown 槽位（index 0）绝不能被点；只能由词典内规范名经品质降级选中。
        cands = bond_cands(
            [slot(0, None, confidence=0.99, rarity="red"),
             slot(1, "三国", confidence=0.99, rarity="white")],
            # 词典内但非预设；本用例测的是「unknown 不得冒充已知」，
            # 走 soft 品质阶梯才能观察到「被选中的是已知名槽位」。
            settings=settings(bond_presets=["封神"], bond_whitelist_mode="soft"),
        )
        d = choose_action(cands, SessionState())
        self.assertEqual(d.action, PolicyAction.SELECT_SLOT)
        self.assertEqual(d.index, 1)  # 只可能是已知名槽位，绝不 index 0

    def test_treasure_unknown_no_click(self):
        d = choose_action(
            treasure_cands([slot(0, None)], settings=settings()),
            SessionState(),
        )
        self.assertNotEqual(d.action, PolicyAction.SELECT_SLOT)
        self.assertEqual(d.action, PolicyAction.CLOSE)

    def test_collectible_no_safe_candidate_has_single_close_decision(self):
        cands = bond_cands(
            [slot(0, None)], has_giveup=True,
            settings=settings(bond_presets=["三国"]),
        )
        for state in (
            SessionState(waits=0, max_waits=3, max_refreshes=3),
            SessionState(waits=3, refreshes=2, max_refreshes=3),
            SessionState(waits=99, refreshes=99),
        ):
            with self.subTest(state=state):
                self.assertEqual(choose_action(cands, state).action, PolicyAction.CLOSE)

    def _bonds(self, **kw):
        return bond_cands(
            [
                slot(0, "乱世三国", rarity="white"),
                slot(1, "体术", rarity="red"),
                slot(2, "三国", rarity="blue"),
            ],
            set_progress={
                "三国": {
                    "have": 1, "need": 2,
                    "members": ["三国", "乱世三国"],
                    "owned": ["三国"],  # 缺乱世三国 → 合成候选
                }
            },
            **kw,
        )

    def test_preset_beats_synthesis_and_quality(self):
        d = choose_action(
            bond_cands(
                [slot(0, "乱世三国"), slot(1, "体术"), slot(2, "三国")],
                set_progress={
                    "三国": {"have": 1, "need": 2, "members": ["三国", "乱世三国"]}
                },
                settings=settings(bond_presets=["体术"]),
            )
        )
        self.assertEqual((d.action, d.index), (PolicyAction.SELECT_SLOT, 1))

    def test_synthesis_beats_quality(self):
        # 无预设：接近合成（三国 1/2，缺乱世三国）优先于红色品质卡。
        d = choose_action(self._bonds(settings=settings(bond_presets=[], bond_whitelist_mode='soft')))
        self.assertEqual((d.action, d.index), (PolicyAction.SELECT_SLOT, 0))

    def test_synthesis_smaller_gap_wins(self):
        # 1 格之差的套装严格优先于 2 格之差。
        cands = bond_cands(
            [slot(0, "乱世三国"), slot(1, "吕岳")],
            set_progress={
                "三国": {
                    "have": 1, "need": 2,
                    "members": ["三国", "乱世三国"],
                    "owned": ["三国"],
                },
                "封神": {
                    "have": 0, "need": 2,
                    "members": ["吕岳", "姜子牙"],
                    "owned": [],
                },
            },
            settings=settings(bond_presets=[], bond_whitelist_mode='soft'),
        )
        d = choose_action(cands)
        self.assertEqual((d.action, d.index), (PolicyAction.SELECT_SLOT, 0))

    def test_gap_beyond_limit_not_synthesis(self):
        # need-have > MAX_SYNTHESIS_GAP（2）不进入合成优先 → 品质降级。
        cands = bond_cands(
            [slot(0, "姜子牙", rarity="purple"), slot(1, "吕岳", rarity="white")],
            set_progress={
                "封神": {
                    "have": 0, "need": 3,
                    "members": ["吕岳", "姜子牙"],
                    "owned": [],
                }
            },
            settings=settings(bond_presets=[], bond_whitelist_mode='soft'),
        )
        d = choose_action(cands)
        self.assertEqual((d.action, d.index), (PolicyAction.SELECT_SLOT, 0))

    def test_complete_set_not_synthesis(self):
        # have == need（已合成完成）不再被当作合成候选。
        cands = bond_cands(
            [slot(0, "乱世三国", rarity="white"), slot(1, "体术", rarity="red")],
            set_progress={
                "三国": {
                    "have": 2, "need": 2,
                    "members": ["三国", "乱世三国"],
                    "owned": ["三国", "乱世三国"],
                }
            },
            settings=settings(bond_presets=[], bond_whitelist_mode='soft'),
        )
        d = choose_action(cands)
        self.assertEqual((d.action, d.index), (PolicyAction.SELECT_SLOT, 1))

    def test_unverifiable_set_progress_skipped(self):
        # 缺 members / 缺 owned / 字段不可解析的套装绝不参与（绝不猜测）。
        cands = bond_cands(
            [slot(0, "乱世三国", rarity="purple"), slot(1, "三国", rarity="white")],
            set_progress={
                "三国": {"have": 1, "need": 2, "owned": ["三国"]},  # 缺 members
                "封神": {"have": 1, "need": 2, "members": ["吕岳"],
                         "owned": "?"},  # owned 不可解析
                "体术": {"have": "?", "need": 2, "members": ["体术"],
                         "owned": []},  # have 解析失败
            },
            settings=settings(bond_presets=[], bond_whitelist_mode='soft'),
        )
        d = choose_action(cands)
        # 三个套装均不可验证 → 落品质降级（purple 槽 0）。
        self.assertEqual((d.action, d.index), (PolicyAction.SELECT_SLOT, 0))

    def test_synthesis_never_picks_owned_member(self):
        # owned 成员即使出现在面板里也不得被合成路径选中（已是重复卡）。
        cands = bond_cands(
            [slot(0, "三国", rarity="red"), slot(1, "乱世三国", rarity="white")],
            set_progress={
                "三国": {
                    "have": 1, "need": 2,
                    "members": ["三国", "乱世三国"],
                    "owned": ["三国"],
                }
            },
            settings=settings(bond_presets=[], bond_whitelist_mode='soft'),
        )
        d = choose_action(cands)
        self.assertEqual((d.action, d.index), (PolicyAction.SELECT_SLOT, 1))

    def test_quality_degradation_order(self):
        cands = bond_cands(
            [
                slot(0, "体术", rarity="white"),
                slot(1, "三国", rarity="purple"),
                slot(2, "乱世三国", rarity="red"),
            ],
            settings=settings(bond_whitelist_mode="soft"),
        )
        d = choose_action(cands)
        self.assertEqual((d.action, d.index), (PolicyAction.SELECT_SLOT, 2))

    def test_quality_unknown_rarity_last(self):
        cands = bond_cands(
            [slot(0, "体术", rarity=None), slot(1, "三国", rarity="white")],
            settings=settings(bond_whitelist_mode="soft"),
        )
        d = choose_action(cands)
        self.assertEqual((d.action, d.index), (PolicyAction.SELECT_SLOT, 1))

    def test_quality_tie_break_lowest_index(self):
        cands = bond_cands(
            [slot(2, "体术", rarity="blue"), slot(0, "三国", rarity="blue")],
            settings=settings(bond_whitelist_mode="soft"),
        )
        d = choose_action(cands)
        self.assertEqual((d.action, d.index), (PolicyAction.SELECT_SLOT, 0))

    def test_quality_unknown_name_never_selected(self):
        # 品质最高但 name 为 None 的槽位不得被品质路径选中。
        cands = bond_cands(
            [slot(0, None, rarity="red", confidence=0.99), slot(1, "体术", rarity="white")],
            settings=settings(bond_whitelist_mode="soft"),
        )
        d = choose_action(cands)
        self.assertEqual((d.action, d.index), (PolicyAction.SELECT_SLOT, 1))


class TestTreasurePriority(unittest.TestCase):
    """宝物：品质优先（2026-09 裁决）；同品质带内 预设 > 合成 > 默认。"""

    def test_quality_beats_lower_quality_synthesis(self):
        # 2026-09 产品裁决：红卡品质优先；白色七星球合成进度不再压过更高品质。
        cands = treasure_cands(
            [slot(0, "四星球", rarity="red"), slot(1, "七星球", rarity="white")],
            set_progress={
                "龙珠": {
                    "have": 6,
                    "need": 7,
                    "members": ["一星球", "二星球", "三星球", "四星球",
                                "五星球", "六星球", "七星球"],
                    "owned": ["一星球", "二星球", "三星球", "四星球",
                              "五星球", "六星球"],
                }
            },
            settings=settings(),
        )
        d = choose_action(cands)
        self.assertEqual((d.action, d.index), (PolicyAction.SELECT_SLOT, 0))

    def test_dragonball_progress_without_owned_no_synthesis_guess(self):
        # 只有 have/need、没有 owned → 无法证明缺哪颗 → 不合成优先（落品质）。
        cands = treasure_cands(
            [slot(0, "四星球", rarity="red"), slot(1, "七星球", rarity="white")],
            set_progress={
                "龙珠": {
                    "have": 6, "need": 7,
                    "members": ["一星球", "二星球", "三星球", "四星球",
                                "五星球", "六星球", "七星球"],
                }
            },
            settings=settings(),
        )
        d = choose_action(cands)
        self.assertEqual((d.action, d.index), (PolicyAction.SELECT_SLOT, 0))

    def test_treasure_preset_beats_set_progress(self):
        cands = treasure_cands(
            [slot(0, "四星球"), slot(1, "七星球")],
            set_progress={
                "龙珠": {"have": 6, "need": 7, "members": ["七星球"], "owned": []}
            },
            settings=settings(treasure_presets=["四星球"]),
        )
        d = choose_action(cands)
        self.assertEqual((d.action, d.index), (PolicyAction.SELECT_SLOT, 0))

    def test_treasure_quality_degradation(self):
        cands = treasure_cands(
            [slot(0, "奥术神符", rarity="white"), slot(1, "物理伤害", rarity="orange")],
            settings=settings(),
        )
        d = choose_action(cands)
        self.assertEqual((d.action, d.index), (PolicyAction.SELECT_SLOT, 1))

    def test_treasure_no_safe_candidate_closes(self):
        cands = treasure_cands(
            [slot(0, None), slot(1, None)],
            has_giveup=True,
            settings=settings(),
        )
        d = choose_action(cands, SessionState(waits=2, max_waits=2))
        self.assertEqual(d.action, PolicyAction.CLOSE)

    def test_deterministic_same_input_twice(self):
        cands = skill_cands(
            [slot(0, "剑气"), slot(1, "地震")],
            settings=settings(skill_presets=["地震", "剑气"]),
        )
        a = choose_action(cands, SessionState())
        b = choose_action(cands, SessionState())
        self.assertEqual(a, b)
        self.assertEqual((a.action, a.index, a.reason), (b.action, b.index, b.reason))

    def test_deterministic_slot_order_invariance(self):
        # 槽位传入乱序 → 结果一致（模块内部按 index 归一）。
        cands_a = skill_cands(
            [slot(1, "地震"), slot(0, "剑气"), slot(2, "寒冰箭")],
            settings=settings(skill_presets=["剑气"]),
        )
        cands_b = skill_cands(
            [slot(2, "寒冰箭"), slot(0, "剑气"), slot(1, "地震")],
            settings=settings(skill_presets=["剑气"]),
        )
        self.assertEqual(
            choose_action(cands_a), choose_action(cands_b)
        )

    def test_deterministic_set_progress_dict_order_invariance(self):
        base = {
            "龙珠": {"have": 6, "need": 7, "members": ["七星球", "四星球"]},
            "三国": {"have": 1, "need": 2, "members": ["三国", "乱世三国"]},
        }
        cands_a = treasure_cands(
            [slot(0, "七星球"), slot(1, "三国")], set_progress=base,
            settings=settings(),
        )
        cands_b = treasure_cands(
            [slot(0, "七星球"), slot(1, "三国")],
            set_progress=dict(reversed(list(base.items()))),
            settings=settings(),
        )
        self.assertEqual(
            choose_action(cands_a), choose_action(cands_b)
        )

    def test_determinism_across_settings_mapping_forms(self):
        # dict 配置与 PolicySettings 配置等价。
        cands = bond_cands(
            [slot(0, "体术", rarity="red"), slot(1, "三国", rarity="white")],
            settings={"bond_presets": [], "quality_order": list(DEFAULT_QUALITY_ORDER)},
        )
        d1 = choose_action(cands)
        cands2 = PanelCandidates(
            panel_kind=PANEL_BOND,
            slots=[slot(0, "体术", rarity="red"), slot(1, "三国", rarity="white")],
            settings=settings(),
        )
        d2 = choose_action(cands2)
        self.assertEqual(d1, d2)

    def test_dict_shaped_contract_input_equivalent(self):
        # 契约文档形态（全 dict：candidates/slots/settings/session）与 dataclass 等价。
        dict_form = {
            "panel_kind": PANEL_SKILL,
            "slots": [
                {"index": 1, "name": "剑气", "confidence": 0.9, "evidence": "roi-a"},
                {"index": 0, "name": "地震", "confidence": 0.95, "evidence": "roi-b"},
            ],
            "set_progress": None,
            "refresh_count": 0,
            "has_giveup": True,
            "settings": {"skill_presets": ["剑气"]},
        }
        d1 = choose_action(dict_form, {"refreshes": 0})
        d2 = choose_action(
            skill_cands(
                [slot(0, "地震", confidence=0.95), slot(1, "剑气", confidence=0.9)],
                has_giveup=True,
                settings=settings(skill_presets=["剑气"]),
            ),
            SessionState(),
        )
        self.assertEqual(d1, d2)
        self.assertEqual((d1.action, d1.index), (PolicyAction.SELECT_SLOT, 1))


class TestBudgetAndPreemption(unittest.TestCase):
    """尝试上限 / 总期限（外部时钟）抢占；无面板 NONE。"""

    def test_attempts_cap_giveup(self):
        d = choose_action(
            skill_cands(
                [slot(0, "剑气")], has_giveup=True,
                settings=settings(skill_presets=["剑气"]),
            ),
            SessionState(attempts=12, max_attempts=12),
        )
        # 技能 panel attempts 耗尽恒 CLOSE（绝不 GIVEUP）
        self.assertEqual(d.action, PolicyAction.CLOSE)
        self.assertIsNone(d.index)
    def test_attempts_cap_no_giveup_close(self):
        d = choose_action(
            skill_cands(
                [slot(0, "剑气")], has_giveup=False,
                settings=settings(skill_presets=["剑气"]),
            ),
            SessionState(attempts=12, max_attempts=12),
        )
        self.assertEqual(d.action, PolicyAction.CLOSE)

    def test_deadline_exceeded_preempts_even_good_preset(self):
        # 总期限过期优先于任何正常动作（技能恒 CLOSE）。
        d = choose_action(
            skill_cands(
                [slot(0, "剑气")], has_giveup=True,
                settings=settings(skill_presets=["剑气"]),
            ),
            SessionState(deadline_exceeded=True),
        )
        self.assertEqual(d.action, PolicyAction.CLOSE)
    def test_no_panel_none(self):
        d = choose_action(PanelCandidates(panel_kind=None))
        self.assertEqual(d.action, PolicyAction.NONE)
        self.assertIsNone(d.index)

    def test_invalid_panel_kind_raises(self):
        with self.assertRaises(ValueError):
            PanelCandidates(panel_kind="card")

    def test_session_refresh_fallback_from_candidates(self):
        # session 缺省时 refresh_count 作为已刷新次数（刷新耗尽 → 放弃）。
        cands = skill_cands(
            [slot(0, "地震")], refresh_count=3, has_giveup=True,
            settings=settings(skill_presets=["寒冰箭"]),
        )
        d = choose_action(cands)
        self.assertEqual(d.action, PolicyAction.CLOSE)

    def test_min_confidence_gate(self):
        # 预设命中但置信度低于 min_confidence → 不可选；技能面板宁可不拿也不乱拿，直接关闭面板。
        cands = skill_cands(
            [slot(0, "剑气", confidence=0.5)],
            settings=settings(skill_presets=["剑气"], min_confidence=0.8),
        )
        d = choose_action(cands, SessionState())
        self.assertNotEqual(d.action, PolicyAction.SELECT_SLOT)
        self.assertEqual(d.action, PolicyAction.CLOSE)

class TestPanelPriority(unittest.TestCase):
    def test_skill_first(self):
        self.assertEqual(
            panel_priority([PANEL_TREASURE, PANEL_SKILL, PANEL_BOND]), PANEL_SKILL
        )

    def test_bond_before_treasure(self):
        self.assertEqual(panel_priority([PANEL_TREASURE, PANEL_BOND]), PANEL_BOND)

    def test_empty_and_none(self):
        self.assertIsNone(panel_priority([]))
        self.assertIsNone(panel_priority(None))


class TestSafetySweep(unittest.TestCase):
    """穷举安全不变量：技能非预设点击数=0；unknown 直接点击=0。"""

    NAMES = ["剑气", "地震", "寒冰箭", "三国", "乱世三国", "体术", "四星球",
             "七星球", None]
    RARITIES = [None, "red", "orange", "purple", "blue", "white"]
    PRESETS = {
        PANEL_SKILL: ["剑气"],
        PANEL_BOND: ["三国"],
        PANEL_TREASURE: ["四星球"],
    }
    SET_PROGRESS = {
        "龙珠": {"have": 6, "need": 7, "members": ["七星球", "四星球"]},
    }

    def test_skill_non_preset_clicks_zero(self):
        # 全部 2 槽组合 × 预设组合：技能面板 SELECT 的槽位必须 ∈ skill_presets。
        for names in itertools.product(self.NAMES, repeat=2):
            for preset_list in ([], ["剑气"], ["地震", "剑气"]):
                cands = skill_cands(
                    [
                        slot(0, names[0], confidence=0.99),
                        slot(1, names[1], confidence=0.99),
                    ],
                    settings=settings(skill_presets=preset_list),
                )
                for refreshes in (0, 1, 3):
                    d = choose_action(
                        cands, SessionState(refreshes=refreshes, max_refreshes=3)
                    )
                    if d.action == PolicyAction.SELECT_SLOT:
                        self.assertIsNotNone(d.index)
                        picked = names[d.index]
                        self.assertIn(
                            picked, preset_list,
                            f"技能 SELECT 了非预设 {picked!r}（预设 {preset_list}）",
                        )

    def test_unknown_clicks_zero(self):
        # 全部 2 槽组合 × 预设 × 面板种类：SELECT 的槽位 name 必须非空。
        for kind, presets in self.PRESETS.items():
            for names in itertools.product(self.NAMES, repeat=2):
                cands = PanelCandidates(
                    panel_kind=kind,
                    slots=[
                        slot(0, names[0], confidence=0.99),
                        slot(1, names[1], confidence=0.99),
                    ],
                    set_progress=self.SET_PROGRESS,
                    settings=settings(**{f"{kind}_presets": presets}),
                )
                for refreshes in (0, 1, 3):
                    d = choose_action(
                        cands, SessionState(refreshes=refreshes, max_refreshes=3)
                    )
                    if d.action == PolicyAction.SELECT_SLOT:
                        self.assertIsNotNone(d.index)
                        self.assertIsNotNone(
                            names[d.index],
                            f"{kind} SELECT 了 unknown 槽位（{names}）",
                        )

    def test_all_returns_are_enum_plus_index(self):
        # 返回值仅 PolicyAction 枚举 + index：穷举组合断言。
        for kind, presets in self.PRESETS.items():
            for names in itertools.product(self.NAMES, repeat=2):
                for rarities in itertools.product(self.RARITIES, repeat=2):
                    cands = PanelCandidates(
                        panel_kind=kind,
                        slots=[
                            slot(0, names[0], confidence=0.8, rarity=rarities[0]),
                            slot(1, names[1], confidence=0.8, rarity=rarities[1]),
                        ],
                        set_progress=self.SET_PROGRESS,
                        settings=settings(**{f"{kind}_presets": presets}),
                    )
                    d = choose_action(cands, SessionState())
                    self.assertIsInstance(d, PolicyDecision)
                    self.assertIsInstance(d.action, PolicyAction)
                    if d.action == PolicyAction.SELECT_SLOT:
                        self.assertIsInstance(d.index, int)
                    else:
                        self.assertIsNone(d.index)


class TestSkillModeStrict(unittest.TestCase):
    """技能恒定严格档：仅焦点系/卡（skill_focus_families 展开 ∪ skill_presets）。"""

    def test_hard_mode_rejects_non_focus_card(self):
        # 目录合法但未勾选系的卡 → 技能恒定严格，直接 CLOSE。
        d = choose_action(
            skill_cands(
                [slot(0, "箭矢增幅", confidence=0.99)],
                settings=settings(skill_focus_families=["剑气"]),
            ),
            SessionState(),
        )
        self.assertNotEqual(d.action, PolicyAction.SELECT_SLOT)
        self.assertEqual(d.action, PolicyAction.CLOSE)
        self.assertIsNone(d.index)
    def test_hard_mode_rejects_non_focus_even_highest_rarity(self):
        # 非焦点卡品质再高也不选（宁可不拿也不乱拿）。
        d = choose_action(
            skill_cands(
                [slot(0, "箭矢增幅", rarity="red", confidence=0.99)],
                settings=settings(skill_focus_families=["剑气"]),
            ),
            SessionState(),
        )
        self.assertNotEqual(d.action, PolicyAction.SELECT_SLOT)
        self.assertIsNone(d.index)

    def test_hard_mode_selects_focus_family_card(self):
        # 焦点系展开内的卡照常选。
        d = choose_action(
            skill_cands(
                [slot(0, "剑气增幅", rarity="white", confidence=0.99)],
                settings=settings(skill_focus_families=["剑气"]),
            ),
            SessionState(),
        )
        self.assertEqual((d.action, d.index), (PolicyAction.SELECT_SLOT, 0))

    def test_hard_mode_legacy_presets_still_work(self):
        # 旧式直接构造（skill_presets，无焦点系）行为不变：仅预设可点。
        d = choose_action(
            skill_cands(
                [slot(0, "箭矢增幅", rarity="red"), slot(1, "剑气", rarity="white")],
                settings=settings(skill_presets=["剑气"]),
            ),
            SessionState(),
        )
        self.assertEqual((d.action, d.index), (PolicyAction.SELECT_SLOT, 1))

    def test_hard_mode_low_confidence_focus_no_click(self):
        d = choose_action(
            skill_cands(
                [slot(0, "剑气增幅", confidence=0.5)],
                settings=settings(skill_focus_families=["剑气"],
                                  min_confidence=0.8),
            ),
            SessionState(),
        )
        self.assertNotEqual(d.action, PolicyAction.SELECT_SLOT)


class TestOwnedBranchAndRarityPriority(unittest.TestCase):
    """Owned branches beat new branches; within same branch rarity sorts first."""

    def test_owned_branch_priority_over_new_branch(self):
        # 玩家已拥有「剑气」系卡 → 剑气系候选 is_owned_branch=0 优先于奥术箭系 is_owned_branch=1。
        cands = skill_cands(
            [slot(0, "箭矢增幅", rarity="purple", confidence=0.99),
             slot(1, "剑气增幅", rarity="white", confidence=0.99)],
            settings=settings(skill_focus_families=["剑气", "奥术箭"]),
            owned_skill_cards=("剑气",),
        )
        d = choose_action(cands, SessionState())
        self.assertEqual((d.action, d.index), (PolicyAction.SELECT_SLOT, 1))

    def test_same_branch_rarity_sorting(self):
        # 同属剑气系：碎冰（紫，rank=2）优先于剑气爆发（蓝，rank=3），即使蓝 index 更小。
        cands = skill_cands(
            [slot(0, "剑气爆发", confidence=0.99),
             slot(1, "碎冰", confidence=0.99)],
            settings=settings(skill_focus_families=["剑气"]),
        )
        d = choose_action(cands, SessionState())
        self.assertEqual((d.action, d.index), (PolicyAction.SELECT_SLOT, 1))
    def test_zero_preset_match_close(self):
        # 0 预设命中（Focus-Miss）→ 恒定 CLOSE（不消耗刷新预算，永不 REFRESH/GIVEUP）。
        cands = skill_cands(
            [slot(0, "地震", confidence=0.99)],
            settings=settings(skill_presets=["寒冰箭"]),
        )
        d = choose_action(cands, SessionState(refreshes=0, max_refreshes=3))
        self.assertEqual(d.action, PolicyAction.CLOSE)

        # 刷新耗尽且 allow_skill_giveup=False → CLOSE（不 GIVEUP）。
        d2 = choose_action(
            cands,
            SessionState(refreshes=3, max_refreshes=3),
        )
        self.assertEqual(d2.action, PolicyAction.CLOSE)

        # 即使 allow_skill_giveup=True 且 has_giveup=True → 技能面板 Focus-Miss 依然恒定 CLOSE（永不 GIVEUP）。
        cands_giveup = skill_cands(
            [slot(0, "地震", confidence=0.99)], has_giveup=True,
            settings=settings(skill_presets=["寒冰箭"], allow_skill_giveup=True),
        )
        d3 = choose_action(cands_giveup, SessionState(refreshes=3, max_refreshes=3))
        self.assertEqual(d3.action, PolicyAction.CLOSE)
class TestSkillPriorityVerifiedEvidence(unittest.TestCase):
    """已核实前置/存档影响优先级，但不构成硬拒绝（唯一候选仍可选）。"""

    def test_owned_prereq_met_beats_unconfirmed(self):
        cands = skill_cands(
            [slot(0, "剑气增幅", rarity="white"), slot(1, "箭矢增幅", rarity="white")],
            settings=settings(skill_focus_families=["剑气", "奥术箭"]),
        )
        d0 = choose_action(cands, SessionState())
        # 无已拥有：两者前置均未确认 → 同组 → 最小 index。
        self.assertEqual((d0.action, d0.index), (PolicyAction.SELECT_SLOT, 0))
        owned = PanelCandidates(
            panel_kind=PANEL_SKILL,
            slots=[slot(0, "剑气增幅", rarity="white"),
                   slot(1, "箭矢增幅", rarity="white")],
            settings=settings(skill_focus_families=["剑气", "奥术箭"]),
            owned_skill_cards=("奥术箭",),
        )
        d1 = choose_action(owned, SessionState())
        # 箭矢增幅前置（奥术箭）已拥有 → 前置确认 → 优先。
        self.assertEqual((d1.action, d1.index), (PolicyAction.SELECT_SLOT, 1))

    def test_owned_skill_cards_preserve_duplicate_learns(self):
        cands = PanelCandidates(
            panel_kind=PANEL_SKILL,
            slots=[slot(0, "箭矢增幅", rarity="white")],
            settings=settings(skill_focus_families=["奥术箭"]),
            owned_skill_cards=("奥术箭", "奥术箭", ""),
        )
        self.assertEqual(cands.owned_skill_cards, ("奥术箭", "奥术箭"))

    def test_two_copy_prerequisite_uses_duplicate_learn_history(self):
        cands = PanelCandidates(
            panel_kind=PANEL_SKILL,
            slots=[
                slot(0, "激光增幅", rarity="white"),
                slot(1, "强力箭矢", rarity="white"),
            ],
            settings=settings(skill_focus_families=["奥术箭", "奥术激光"]),
            owned_skill_cards=("箭矢增幅", "箭矢增幅"),
        )
        decision = choose_action(cands, SessionState())
        self.assertEqual(
            (decision.action, decision.index),
            (PolicyAction.SELECT_SLOT, 1),
        )

    def test_archive_waiver_prioritizes_prereq(self):
        # 存档奥术箭36 豁免爆炸箭矢的爆炎箭前置 + owned 奥术箭 → 前置确认。
        cands = PanelCandidates(
            panel_kind=PANEL_SKILL,
            slots=[slot(0, "激光增幅", rarity="white"),
                   slot(1, "爆炸箭矢", rarity="white")],
            settings=settings(skill_focus_families=["奥术箭", "奥术激光"],
                              skill_archive_levels=[("asj", 36)]),
            owned_skill_cards=("奥术箭",),
        )
        d = choose_action(cands, SessionState())
        self.assertEqual((d.action, d.index), (PolicyAction.SELECT_SLOT, 1))

    def test_archive_penalty_removed_prioritizes(self):
        # 存档奥术箭10：箭矢齐射「不再降低伤害」已核实 → 优先于未核实卡。
        cands = skill_cands(
            [slot(0, "激光增幅", rarity="white"), slot(1, "箭矢齐射", rarity="white")],
            settings=settings(skill_focus_families=["奥术箭", "奥术激光"],
                              skill_archive_levels=[("asj", 10)]),
        )
        d = choose_action(cands, SessionState())
        self.assertEqual((d.action, d.index), (PolicyAction.SELECT_SLOT, 1))

    def test_archive_unlock_threshold_met_prioritizes(self):
        # 同属白卡时：强化飞箭（奥术箭43 进池，存档达标）优先于未达标的奥术穿透（奥术射线50）。
        cands = skill_cands(
            [slot(0, "奥术穿透", rarity="white"), slot(1, "强化飞箭", rarity="white")],
            settings=settings(skill_focus_families=["奥术箭", "奥术射线"],
                              skill_archive_levels=[("asj", 43)]),
        )
        d = choose_action(cands, SessionState())
        self.assertEqual((d.action, d.index), (PolicyAction.SELECT_SLOT, 1))
    def test_archive_levels_normalized_sorted(self):
        ps = settings(skill_archive_levels=[("jq", 13), ("asj", 47)])
        self.assertEqual(ps.skill_archive_levels, (("asj", 47), ("jq", 13)))

    def test_unmet_prereq_not_hard_rejection(self):
        # 前置未确认只是排序靠后：唯一候选仍可选。
        d = choose_action(
            skill_cands(
                [slot(0, "爆炸箭矢", rarity="white", confidence=0.99)],
                settings=settings(skill_focus_families=["奥术箭"]),
            ),
            SessionState(),
        )
        self.assertEqual((d.action, d.index), (PolicyAction.SELECT_SLOT, 0))


class TestTreasureMustTake(unittest.TestCase):
    """宝物必拿名单来自 settings.treasure_must_take；Owner 2026-09-15：EX 出现就拿，不看品质。"""

    def test_must_take_comes_from_settings(self):
        # Owner 2026-09-15：EX 本身就是最高品质，出现即拿（推翻 09-09 的「只在最高品质带内」）。
        d = choose_action(
            treasure_cands(
                [slot(0, "双倍神符", rarity="green"),
                 slot(1, "ONEPIECE", confidence=0.99)],
                settings=settings(treasure_must_take=["ONEPIECE"]),
            ),
            SessionState(),
        )
        self.assertEqual((d.action, d.index), (PolicyAction.SELECT_SLOT, 1))

    def test_must_take_case_insensitive_substring(self):
        # 子串 + 大小写不敏感：onepiece 命中 ONEPIECE；EX 跨品质必拿。
        d = choose_action(
            treasure_cands(
                [slot(0, "双倍神符", rarity="red", confidence=0.99),
                 slot(1, "onepiece黄金船", rarity="white", confidence=0.99)],
                settings=settings(treasure_must_take=["ONEPIECE"]),
            ),
            SessionState(),
        )
        self.assertEqual((d.action, d.index), (PolicyAction.SELECT_SLOT, 1))

    def test_legacy_substring_privilege_ignores_quality(self):
        # Owner 2026-09-15：缺省名单（全都要/卡牌大师）出现即拿，边框品质不压过它。
        for name in ("我全都要", "卡牌大师"):
            with self.subTest(name=name):
                d = choose_action(
                    treasure_cands(
                        [slot(0, name, rarity="white", confidence=0.99),
                         slot(1, "双倍神符", rarity="red", confidence=0.99)],
                    ),
                    SessionState(),
                )
                self.assertEqual((d.action, d.index), (PolicyAction.SELECT_SLOT, 0))

    def test_must_take_does_not_bypass_negative(self):
        # 负面剔除优先：必拿名单内的卡带负面描述仍不可选。
        d = choose_action(
            treasure_cands(
                [slot(0, "ONEPIECE", description="5分钟后不再获得金币")],
                settings=settings(treasure_must_take=["ONEPIECE"]),
            ),
            SessionState(),
        )
        self.assertNotEqual(d.action, PolicyAction.SELECT_SLOT)

    def test_must_take_still_requires_minimum_confidence(self):
        d = choose_action(
            treasure_cands(
                [slot(0, "ONEPIECE", confidence=0.59)],
                settings=settings(
                    treasure_must_take=["ONEPIECE"],
                    min_confidence=0.60,
                ),
            ),
            SessionState(),
        )
        self.assertNotEqual(d.action, PolicyAction.SELECT_SLOT)

    def test_must_take_explicit_empty_disables_privilege(self):
        # 配置显式空名单 → 特权关闭：走回品质降级（选高品质卡，不再秒选）。
        d = choose_action(
            treasure_cands(
                [slot(0, "我全都要", rarity="white", confidence=0.99),
                 slot(1, "双倍神符", rarity="red", confidence=0.99)],
                settings=settings(treasure_must_take=[]),
            ),
            SessionState(),
        )
        self.assertEqual((d.action, d.index), (PolicyAction.SELECT_SLOT, 1))
        # 对照：缺省名单含「全都要」→ EX 出现即拿（Owner 2026-09-15）。
        d_default = choose_action(
            treasure_cands(
                [slot(0, "我全都要", rarity="white", confidence=0.99),
                 slot(1, "双倍神符", rarity="red", confidence=0.99)],
                settings=settings(),
            ),
            SessionState(),
        )
        self.assertEqual((d_default.action, d_default.index),
                         (PolicyAction.SELECT_SLOT, 0))


class TestAssemblePolicySettings(unittest.TestCase):
    """assemble_policy_settings：纯函数、焦点系派生、字段解析。"""

    LABELS = {
        "jq": "剑气", "pg": "普攻", "asj": "奥术箭",
        "asjg": "奥术激光", "hbj": "寒冰箭", "byj": "爆炎箭",
    }

    @staticmethod
    def fake_settings(skills, cards=(), bonds=(), allow_neg=(), archive=None):
        return SimpleNamespace(
            skills=list(skills),
            cards=list(cards),
            bonds=list(bonds),
            treasure_allow_negative=list(allow_neg),
            skill_archive_levels=dict(archive or {}),
        )

    def test_five_raw_skills_keep_strict_no_mode_field(self):
        """5+ 原始勾选不再产生 all_round：无模式字段，焦点系=全部勾选系，非焦点卡硬拒。"""
        ps = assemble_policy_settings(
            settings=self.fake_settings(["jq", "pg", "asjg", "hbj", "byj"]),
            skill_labels=self.LABELS, fetter_labels={}, policy_doc={},
        )
        self.assertFalse(hasattr(ps, "skill_whitelist_mode"))
        self.assertEqual(
            ("剑气", "普攻", "奥术激光", "寒冰箭", "爆炎箭"),
            ps.skill_focus_families,
        )
        d = choose_action(
            skill_cands(
                [slot(0, "箭矢增幅", confidence=0.99)],
                settings=settings(
                    skill_focus_families=["剑气", "普攻", "奥术激光", "寒冰箭", "爆炎箭"]
                ),
            ),
            SessionState(),
        )
        self.assertNotEqual(d.action, PolicyAction.SELECT_SLOT)
        self.assertEqual(d.action, PolicyAction.CLOSE)

    def test_four_raw_skills_strict_rejects_non_focus(self):
        """4 个原始技能：严格路径不变，非焦点卡硬拒（直接 CLOSE 面板）。"""
        ps = assemble_policy_settings(
            settings=self.fake_settings(["jq", "pg", "asjg", "hbj"]),
            skill_labels=self.LABELS, fetter_labels={}, policy_doc={},
        )
        self.assertEqual(("剑气", "普攻", "奥术激光", "寒冰箭"), ps.skill_focus_families)
        d = choose_action(
            skill_cands(
                [slot(0, "箭矢增幅", rarity="red", confidence=0.99)],
                settings=settings(skill_focus_families=["剑气", "普攻", "奥术激光", "寒冰箭"]),
            ),
            SessionState(),
        )
        self.assertNotEqual(d.action, PolicyAction.SELECT_SLOT)
        self.assertEqual(d.action, PolicyAction.CLOSE)
        self.assertIsNone(d.index)
    def test_zero_to_four_raw_skills_become_focus_families(self):
        for count in range(5):
            with self.subTest(count=count):
                ps = assemble_policy_settings(
                    settings=self.fake_settings(list(self.LABELS)[:count]),
                    skill_labels=self.LABELS, fetter_labels={}, policy_doc={},
                )
                self.assertEqual(
                    ps.skill_focus_families,
                    tuple(self.LABELS[c] for c in list(self.LABELS)[:count]),
                )

    def test_five_raw_skills_are_strict_focus_families(self):
        ps = assemble_policy_settings(
            settings=self.fake_settings(list(self.LABELS)[:5]),
            skill_labels=self.LABELS, fetter_labels={}, policy_doc={},
        )
        self.assertEqual(
            ps.skill_focus_families,
            tuple(self.LABELS[c] for c in list(self.LABELS)[:5]),
        )

    def test_four_raw_skills_expand_beyond_raw_count(self):
        # 4 个原始技能展开后卡名数远超 4；严格档只过滤焦点集，不改变档位。
        ps = assemble_policy_settings(
            settings=self.fake_settings(list(self.LABELS)[:4]),
            skill_labels=self.LABELS, fetter_labels={}, policy_doc={},
        )
        self.assertGreater(len(ps.skill_presets), 4)
        self.assertIn("剑气", ps.skill_presets)
        self.assertIn("剑气增幅", ps.skill_presets)
        self.assertIn("箭矢增幅", ps.skill_presets)

    def test_focus_families_config_order_deduped(self):
        ps = assemble_policy_settings(
            settings=self.fake_settings(["jq", "asj", "jq"]),
            skill_labels=self.LABELS, fetter_labels={}, policy_doc={},
        )
        self.assertEqual(ps.skill_focus_families, ("剑气", "奥术箭"))

    def test_parses_policy_doc_fields(self):
        ps = assemble_policy_settings(
            settings=self.fake_settings(["jq"]),
            skill_labels=self.LABELS, fetter_labels={},
            policy_doc={
                "min_confidence": 0.8,
                "quality_order": ["orange", "white"],
                "allow_skill_giveup": True,
                "bond": {"whitelist_mode": "soft"},
                "treasure": {
                    "must_take_names": ["ONEPIECE"],
                    "negative_patterns": ["不再获得"],
                    "negative_names": ["透支力量"],
                },
            },
        )
        self.assertEqual(ps.min_confidence, 0.8)
        self.assertEqual(ps.quality_order, ("orange", "white"))
        self.assertTrue(ps.allow_skill_giveup)
        self.assertEqual(ps.bond_whitelist_mode, "soft")
        self.assertEqual(ps.treasure_must_take, ("ONEPIECE",))
        self.assertEqual(ps.treasure_negative_patterns, ("不再获得",))
        self.assertEqual(ps.treasure_negative_names, ("透支力量",))

    def test_omitted_policy_doc_uses_safe_defaults(self):
        ps = assemble_policy_settings(
            settings=self.fake_settings(["jq"]),
            skill_labels=self.LABELS, fetter_labels={}, policy_doc={},
        )
        self.assertEqual(ps.min_confidence, 0.60)
        self.assertEqual(ps.quality_order, DEFAULT_QUALITY_ORDER)
        self.assertEqual(ps.bond_whitelist_mode, "hard")
        self.assertEqual(ps.treasure_must_take, DEFAULT_TREASURE_MUST_TAKE)
        self.assertFalse(ps.allow_skill_giveup)
        self.assertEqual(ps.treasure_presets, ())

    def test_carries_archive_levels_as_sorted_tuple_pairs(self):
        ps = assemble_policy_settings(
            settings=self.fake_settings(["jq"], archive={"jq": 13, "asj": 47}),
            skill_labels=self.LABELS, fetter_labels={}, policy_doc={},
        )
        self.assertEqual(ps.skill_archive_levels, (("asj", 47), ("jq", 13)))

    def test_cards_resolve_through_fetter_labels(self):
        ps = assemble_policy_settings(
            settings=self.fake_settings(["jq"], cards=["三国.png", "unknown_stem"]),
            skill_labels=self.LABELS,
            fetter_labels={"三国": "乱世三国"},
            policy_doc={},
        )
        self.assertEqual(ps.bond_presets, ("乱世三国", "unknown_stem"))

    def test_bonds_remain_base_when_cards_are_all_advanced(self):
        ps = assemble_policy_settings(
            settings=self.fake_settings(
                ["jq"],
                cards=["封神", "封神榜", "海盗"],
                bonds=["成长", "经济", "贪婪", "挑战", "祝福"],
            ),
            skill_labels=self.LABELS,
            fetter_labels={},
            policy_doc={
                "bond": {
                    "base_completion_ratio": 0.8,
                    "advanced_names": ["封神", "封神榜", "海盗"],
                    "advanced_groups": [["封神", "封神榜"], ["海盗"]],
                }
            },
        )
        self.assertEqual(ps.bond_base_presets, ("祝福", "成长", "经济", "贪婪", "挑战"))
        self.assertEqual(ps.bond_advanced_presets, ("封神", "封神榜", "海盗"))
        self.assertEqual(ps.bond_advanced_groups[0][0], "封神")
        self.assertEqual(ps.bond_advanced_groups[1][0], "海盗")

    def test_treasure_allow_negative_from_settings(self):
        ps = assemble_policy_settings(
            settings=self.fake_settings(["jq"], allow_neg=["贪婪献祭"]),
            skill_labels=self.LABELS, fetter_labels={}, policy_doc={},
        )
        self.assertEqual(ps.treasure_allow_negative, ("贪婪献祭",))

    def test_habit_scores_pass_through(self):
        ps = assemble_policy_settings(
            settings=self.fake_settings(["jq"]),
            skill_labels=self.LABELS, fetter_labels={},
            policy_doc={}, habit_name_scores=(("剑气增幅", 2.0),),
        )
        self.assertEqual(ps.habit_name_scores, (("剑气增幅", 2.0),))

    def test_deterministic_same_input(self):
        kwargs = dict(
            settings=self.fake_settings(
                ["jq", "pg", "asj", "hbj", "byj"],
                cards=["三国.png"], allow_neg=["贪婪献祭"], archive={"asj": 47},
            ),
            skill_labels=self.LABELS, fetter_labels={"三国": "乱世三国"},
            policy_doc={"min_confidence": 0.7,
                        "treasure": {"must_take_names": ["ONEPIECE"]}},
        )
        a = assemble_policy_settings(**kwargs)
        b = assemble_policy_settings(**kwargs)
        self.assertEqual(a, b)
        self.assertEqual(
            a.skill_focus_families, ("剑气", "普攻", "奥术箭", "寒冰箭", "爆炎箭")
        )


class TestCardFactAndBadgeFirstSelection(unittest.TestCase):
    """Phase 2 Badge-first 选卡与 CardFact 结构测试。"""

    def test_card_fact_creation_and_to_slot(self):
        cf = CardFact(
            slot=0,
            family="奥术箭",
            rarity="red",
            prereq_marker=True,
            is_new=True,
            exact_name="奥术散射",
        )
        self.assertEqual(cf.slot, 0)
        self.assertEqual(cf.family, "奥术箭")
        self.assertEqual(cf.rarity, "red")
        self.assertTrue(cf.prereq_marker)
        self.assertTrue(cf.is_new)
        self.assertEqual(cf.exact_name, "奥术散射")

        slot_cand = cf.to_slot_candidate()
        self.assertEqual(slot_cand.index, 0)
        self.assertEqual(slot_cand.name, "奥术散射")
        self.assertEqual(slot_cand.family, "奥术箭")
        self.assertEqual(slot_cand.rarity, "red")
        self.assertTrue(slot_cand.prereq_marker)
        self.assertTrue(slot_cand.is_new)
        self.assertEqual(slot_cand.card_fact, cf)

    def test_card_fact_from_slot_candidate(self):
        slot_cand = SlotCandidate(
            index=1,
            name="寒冰箭·极",
            confidence=0.9,
            rarity="orange",
            family="寒冰箭",
            prereq_marker=False,
            is_new=True,
            skill_level=3,
        )
        cf = CardFact.from_slot(slot_cand)
        self.assertEqual(cf.slot, 1)
        self.assertEqual(cf.family, "寒冰箭")
        self.assertEqual(cf.rarity, "orange")
        self.assertFalse(cf.prereq_marker)
        self.assertTrue(cf.is_new)
        self.assertEqual(cf.exact_name, "寒冰箭·极")
        self.assertEqual(cf.skill_level, 3)

    def test_card_fact_badge_first_sorting_rule(self):
        """Badge-first 排序严格不变量：
        1. family 必须在 focus 集合中（否则淘汰）；
        2. prereq_marker 最高；
        3. rarity 稀有度排序 (red > orange > purple > blue > white > green)；
        4. skill_level；
        5. is_new；
        6. user focus family preference order；
        7. slot 确定性 tie-break。
        """
        ps = PolicySettings(
            skill_focus_families=("奥术箭", "冰霜"),
            skill_presets=(),
        )
        # 槽0: 奥术箭 蓝色 prereq_marker=True
        # 槽1: 冰霜 红色 prereq_marker=False
        # 槽2: 雷电 红色 (不在 focus 集合中 -> 淘汰)
        cands = [
            CardFact(slot=0, family="奥术箭", rarity="blue", prereq_marker=True),
            CardFact(slot=1, family="冰霜", rarity="red", prereq_marker=False),
            CardFact(slot=2, family="雷电", rarity="red", prereq_marker=True),
        ]
        panel = PanelCandidates(panel_kind=PANEL_SKILL, slots=tuple(cands), settings=ps)
        dec = choose_action(panel)
        self.assertEqual(dec.action, PolicyAction.SELECT_SLOT)
        # 前置卡 (槽0) 胜过无前置红卡 (槽1)
        self.assertEqual(dec.target_slot, 0)

    def test_card_fact_rarity_ranking(self):
        ps = PolicySettings(
            skill_focus_families=("奥术箭",),
            skill_presets=(),
        )
        # 槽0: 紫卡
        # 槽1: 橙卡
        # 槽2: 红卡
        cands = [
            CardFact(slot=0, family="奥术箭", rarity="purple"),
            CardFact(slot=1, family="奥术箭", rarity="orange"),
            CardFact(slot=2, family="奥术箭", rarity="red"),
        ]
        panel = PanelCandidates(panel_kind=PANEL_SKILL, slots=tuple(cands), settings=ps)
        dec = choose_action(panel)
        self.assertEqual(dec.action, PolicyAction.SELECT_SLOT)
        # 红卡胜出 (槽2)
        self.assertEqual(dec.target_slot, 2)

    def test_card_fact_ocr_degraded_idempotent_decision(self):
        """即使 exact_name 为 None 或乱码，只要 badge/family 和 quality 存在，选择 100% 确定。"""
        ps = PolicySettings(
            skill_focus_families=("奥术箭",),
            skill_presets=(),
        )
        cands = [
            CardFact(slot=0, family="奥术箭", rarity="blue", exact_name=None),
            CardFact(slot=1, family="奥术箭", rarity="orange", exact_name="??乱码"),
        ]
        panel = PanelCandidates(panel_kind=PANEL_SKILL, slots=tuple(cands), settings=ps)
        dec = choose_action(panel)
        self.assertEqual(dec.action, PolicyAction.SELECT_SLOT)
        self.assertEqual(dec.target_slot, 1)

    def test_card_fact_all_focus_miss_closes(self):
        ps = PolicySettings(
            skill_focus_families=("奥术箭",),
            skill_presets=(),
        )
        cands = [
            CardFact(slot=0, family="毒素", rarity="red"),
            CardFact(slot=1, family="火焰", rarity="red"),
        ]
        panel = PanelCandidates(panel_kind=PANEL_SKILL, slots=tuple(cands), settings=ps)
        dec = choose_action(panel, session=SessionState(refreshes=3, max_refreshes=3))
        self.assertEqual(dec.action, PolicyAction.CLOSE)

    def test_unknown_garbage_ocr_name_not_treated_as_prereq(self):
        """Defect 1 fix: Unknown/garbage OCR names must not be treated as prereqs."""
        ps = PolicySettings(
            skill_focus_families=("奥术箭",),
            skill_presets=(),
        )
        # 槽0: 识别出垃圾卡名，但无 catalog prereq / prereq_marker -> 不能当 prereq
        # 槽1: 正常红卡，无 prereq
        # 橙卡 (槽0) 虽有垃圾名但不是 prereq，应输给红卡 (槽1)
        cands = [
            CardFact(slot=0, family="奥术箭", rarity="orange", exact_name="垃圾乱码卡名"),
            CardFact(slot=1, family="奥术箭", rarity="red", exact_name=None),
        ]
        panel = PanelCandidates(panel_kind=PANEL_SKILL, slots=tuple(cands), settings=ps)
        dec = choose_action(panel)
        self.assertEqual(dec.action, PolicyAction.SELECT_SLOT)
        self.assertEqual(dec.target_slot, 1)

    def test_legacy_preset_mode_filters_off_preset_nameless_family_cards(self):
        """Defect 2 fix: Legacy preset mode checks family against presets to avoid off-preset nameless cards."""
        ps = PolicySettings(
            skill_focus_families=(),
            skill_presets=("奥术箭",),
        )
        # 槽0: 暴风雪族（无名卡），不在 preset 里 -> 必须过滤
        # 槽1: 奥术箭族（无名卡），在 preset 里 -> 应当选中
        cands = [
            CardFact(slot=0, family="暴风雪", rarity="red", exact_name=None),
            CardFact(slot=1, family="奥术箭", rarity="blue", exact_name=None),
        ]
        panel = PanelCandidates(panel_kind=PANEL_SKILL, slots=tuple(cands), settings=ps)
        dec = choose_action(panel)
        self.assertEqual(dec.action, PolicyAction.SELECT_SLOT)
        self.assertEqual(dec.target_slot, 1)

    def test_slot_fingerprint_includes_family(self):
        """Defect 3 fix: Slot fingerprint includes family so empty-name different-family panels differ."""
        cands_a = [
            CardFact(slot=0, family="奥术箭", rarity="blue", exact_name=None),
        ]
        cands_b = [
            CardFact(slot=0, family="冰霜", rarity="blue", exact_name=None),
        ]
        fp_a = slot_fingerprint(cands_a)
        fp_b = slot_fingerprint(cands_b)
        self.assertNotEqual(fp_a, fp_b)
        self.assertIn("奥术箭", fp_a)
        self.assertIn("冰霜", fp_b)

    def test_card_fact_family_source_property_and_defaults(self):
        """D1 invariant: CardFact family_source defaults to 'unknown' ("badge" | "legacy_name" | "unknown")."""
        cf_default = CardFact(slot=0, family="奥术箭")
        self.assertEqual(cf_default.family_source, "unknown")

        cf_badge = CardFact(slot=0, family="奥术箭", family_source="badge")
        self.assertEqual(cf_badge.family_source, "badge")

        cf_legacy = CardFact(slot=1, family="冰霜", family_source="legacy_name")
        self.assertEqual(cf_legacy.family_source, "legacy_name")

        cand = cf_legacy.to_slot_candidate()
        self.assertEqual(cand.card_fact.family_source, "legacy_name")
        self.assertEqual(cand.to_card_fact().family_source, "legacy_name")

class TestSkillInvariantsA1toA6(unittest.TestCase):
    """Skill invariant tests A1-A6 covering P0-1 and P1-2."""

    def test_a1_fresh_session_focus_miss_closes_no_refresh_no_giveup(self):
        """A1: fresh session (refreshes=0) + readable focus miss => CLOSE (refreshes=0, giveup=0)."""
        cands = skill_cands(
            [slot(0, "毒素增幅", confidence=0.99), slot(1, "烈焰风暴", confidence=0.99)],
            settings=settings(skill_focus_families=["剑气"]),
        )
        state = SessionState(refreshes=0, max_refreshes=3)
        dec = choose_action(cands, state)
        self.assertEqual(dec.action, PolicyAction.CLOSE)
        self.assertIsNone(dec.index)
        self.assertIsNone(dec.target_slot)
        self.assertEqual(state.refreshes, 0)
        self.assertIn("关闭面板", dec.reason)

    def test_a2_allow_skill_giveup_focus_miss_closes_never_giveup(self):
        """A2: allow_skill_giveup=True + focus miss => CLOSE (never GIVEUP)."""
        cands = skill_cands(
            [slot(0, "地震", confidence=0.99), slot(1, "火球术", confidence=0.99)],
            has_giveup=True,
            settings=settings(skill_presets=["寒冰箭"], allow_skill_giveup=True),
        )
        state = SessionState(refreshes=0, max_refreshes=3)
        dec = choose_action(cands, state)
        self.assertEqual(dec.action, PolicyAction.CLOSE)
        self.assertNotEqual(dec.action, PolicyAction.GIVEUP)
        self.assertNotEqual(dec.action, PolicyAction.REFRESH)

    def test_a3_arbitrary_refreshes_focus_miss_closes(self):
        """A3: refreshes arbitrary value => CLOSE."""
        for r in (0, 1, 2, 5, 99):
            with self.subTest(refreshes=r):
                cands = skill_cands(
                    [slot(0, "毒云", confidence=0.99)],
                    has_giveup=True,
                    settings=settings(skill_focus_families=["剑气"], allow_skill_giveup=True),
                )
                state = SessionState(refreshes=r, max_refreshes=3)
                dec = choose_action(cands, state)
                self.assertEqual(dec.action, PolicyAction.CLOSE)
                self.assertEqual(state.refreshes, r)

    def test_a4_exact_sorting_tuple_verification(self):
        """A4: exact sorting tuple verification (prereq > rarity > -level > new > fam_pref > slot)."""
        ps = PolicySettings(
            skill_focus_families=("剑气", "奥术箭"),
            skill_presets=(),
        )
        # 槽0: 剑气, 红品质(rank=0), level=1, new=1, fam_pref=0
        # 槽1: 剑气, 红品质(rank=0), level=5, new=1, fam_pref=0 -> -level 更小，优先
        s0 = SlotCandidate(index=0, name="剑气A", rarity="red", confidence=0.99, skill_level=1, family="剑气")
        s1 = SlotCandidate(index=1, name="剑气B", rarity="red", confidence=0.99, skill_level=5, family="剑气")
        ranked = _rank_skill_candidates((s0, s1), ps, ())
        self.assertEqual(ranked[0], s1.index)
        self.assertEqual(ranked[1], s0.index)

        # 槽0: 剑气(fam_pref=0), 槽1: 奥术箭(fam_pref=1), 同品质同level -> fam_pref 优先
        s0 = SlotCandidate(index=0, name="奥术箭1", rarity="red", confidence=0.99, skill_level=1, family="奥术箭")
        s1 = SlotCandidate(index=1, name="剑气1", rarity="red", confidence=0.99, skill_level=1, family="剑气")
        ranked = _rank_skill_candidates((s0, s1), ps, ())
        self.assertEqual(ranked[0], s1.index)  # 剑气 rank 0 < 奥术箭 rank 1

        # unknown rarity 必须排在所有已知品质之后
        s_unknown = SlotCandidate(index=0, name="剑气X", rarity="unknown", confidence=0.99, skill_level=10, family="剑气")
        s_white = SlotCandidate(index=1, name="剑气Y", rarity="white", confidence=0.99, skill_level=1, family="剑气")
        ranked = _rank_skill_candidates((s_unknown, s_white), ps, ())
        self.assertEqual(ranked[0], s_white.index)  # white (rank=5) < unknown (rank=6)

    def test_a5_prereq_beats_higher_rarity(self):
        """A5: prereq_rank beats higher rarity."""
        ps = PolicySettings(
            skill_focus_families=("剑气",),
            skill_presets=(),
        )
        # s0: red rarity, no prereq (prereq_rank=1)
        # s1: blue rarity, prereq met (prereq_rank=0)
        s0 = SlotCandidate(index=0, name="剑气红", rarity="red", confidence=0.99, skill_level=1, family="剑气", prereq_marker=False)
        s1 = SlotCandidate(index=1, name="剑气蓝", rarity="blue", confidence=0.99, skill_level=1, family="剑气", prereq_marker=True)
        ranked = _rank_skill_candidates((s0, s1), ps, ())
        self.assertEqual(ranked[0], s1.index)

    def test_a6_card_fact_focus_miss_closes_without_refresh(self):
        """A6: CardFact badge-first focus miss closes immediately without refresh."""
        ps = PolicySettings(
            skill_focus_families=("奥术箭",),
            skill_presets=(),
        )
        cands = [
            CardFact(slot=0, family="毒素", rarity="red"),
            CardFact(slot=1, family="火焰", rarity="gold"),
        ]
        panel = PanelCandidates(panel_kind=PANEL_SKILL, slots=tuple(cands), settings=ps)
        state = SessionState(refreshes=0, max_refreshes=3)
        dec = choose_action(panel, session=state)
        self.assertEqual(dec.action, PolicyAction.CLOSE)
        self.assertEqual(state.refreshes, 0)


class TestLiveRegressions20260822(unittest.TestCase):
    """20260822 实机回归（trace 181735）：羁绊刷新与技能主技能优先。"""

    def test_bond_soft_mode_refreshes_before_quality_fallback(self):
        """软模式（推荐方案）预设未命中且有刷新预算 → REFRESH 而非品质降级。

        实机现象：整局 0 次刷新、羁绊只拿 4 张（can_refresh 从未接线 +
        软模式无刷新分支的双重根因）。
        """
        cands = bond_cands(
            [slot(0, "修仙", rarity="purple"), slot(1, "战术", rarity="blue")],
            can_refresh=True,
            settings=settings(bond_presets=["祝福", "成长"], bond_whitelist_mode="soft"),
        )
        state = SessionState(refreshes=0, max_refreshes=3)
        d = choose_action(cands, session=state)
        self.assertEqual(d.action, PolicyAction.REFRESH)

    def test_bond_soft_mode_quality_fallback_after_refresh_budget(self):
        """软模式刷新耗尽后仍回落品质降级（保持原 soft 语义）。"""
        cands = bond_cands(
            [slot(0, "修仙", rarity="purple"), slot(1, "战术", rarity="blue")],
            can_refresh=True,
            settings=settings(bond_presets=["祝福", "成长"], bond_whitelist_mode="soft"),
        )
        state = SessionState(refreshes=3, max_refreshes=3)
        d = choose_action(cands, session=state)
        self.assertEqual(d.action, PolicyAction.SELECT_SLOT)
        self.assertEqual(d.index, 0)

    def test_bond_hard_mode_refresh_then_close(self):
        """硬模式：预算内 REFRESH，耗尽后 CLOSE（语义不变）。"""
        ps = PolicySettings(bond_presets=("祝福",), bond_whitelist_mode=WHITELIST_HARD)
        cands = bond_cands(
            [slot(0, "修仙", rarity="red")],
            can_refresh=True,
            settings=ps,
        )
        d = choose_action(cands, session=SessionState(refreshes=0, max_refreshes=3))
        self.assertEqual(d.action, PolicyAction.REFRESH)
        d2 = choose_action(cands, session=SessionState(refreshes=3, max_refreshes=3))
        self.assertEqual(d2.action, PolicyAction.CLOSE)

    def test_unowned_preset_main_skill_beats_owned_family_stack(self):
        """trace 181735 tick42 复现：面板有红色预设主技能「剑气」，
        已拥有族（奥术箭）的紫色堆叠卡不得再压过它。"""
        ps = PolicySettings(
            skill_focus_families=("奥术箭", "奥术激光", "剑气", "奥术射线"),
            skill_presets=("奥术箭", "奥术激光", "剑气", "奥术射线"),
        )
        stack = slot(2, "箭矢齐射", rarity="purple")
        main = slot(0, "剑气", rarity="red")
        ranked = _rank_skill_candidates((main, stack), ps, ("箭矢连发",))
        self.assertEqual(ranked[0], main.index)

    def test_owned_main_no_longer_starves_stacking(self):
        """主技能集齐后（4 族全拥有），排序回到原堆叠语义。"""
        ps = PolicySettings(
            skill_focus_families=("奥术箭", "奥术激光", "剑气", "奥术射线"),
        )
        stack = slot(2, "箭矢齐射", rarity="purple")
        main = slot(0, "剑气", rarity="red")
        owned = ("奥术箭", "奥术激光", "剑气", "奥术射线")
        ranked = _rank_skill_candidates((main, stack), ps, owned)
        self.assertEqual(ranked[0], stack.index)

    # ---- 20260822 第二轮实机回归（trace 203910）----

    def test_skill_focus_miss_closes_without_refresh(self):
        """可读但未命中预设/焦点 → CLOSE，不刷新、不放弃、不补位。"""
        ps = PolicySettings(
            skill_focus_families=("奥术箭", "奥术激光", "剑气", "奥术射线"),
            skill_presets=("奥术箭", "奥术激光", "剑气", "奥术射线"),
        )
        cands = PanelCandidates(
            panel_kind=PANEL_SKILL,
            slots=(slot(0, "天雷", rarity="purple"), slot(1, "地震", rarity="purple")),
            can_refresh=True,
            settings=ps,
        )
        self.assertEqual(
            choose_action(cands, session=SessionState(refreshes=0, max_refreshes=3)).action,
            PolicyAction.CLOSE,
        )

    def test_treasure_unnamed_high_rarity_beats_readable_green(self):
        """Pre-GT 2026-09-16 安全收口：宝物卡若卡名与描述均未知，即使边框为高品质（orange），
        亦禁止盲选以免绕过负面宝物门禁，优先选择已知安全的有效槽位。"""
        ps = PolicySettings(treasure_presets=())
        cands = treasure_cands(
            [slot(0, "属性神符", confidence=0.84, rarity="green"),
             slot(1, None, confidence=0.0, rarity="orange"),
             slot(2, "暴怒神符", confidence=0.8, rarity="green")],
            settings=ps,
        )
        d = choose_action(cands, session=SessionState())
        self.assertEqual(d.action, PolicyAction.SELECT_SLOT)
        self.assertEqual(d.index, 0)

    def test_bond_unnamed_still_not_clickable(self):
        """羁绊未读名槽位保持不可选（安全语义不随宝物放宽）。"""
        cands = bond_cands(
            [slot(0, "修仙", rarity="purple"), slot(1, None, confidence=0.0, rarity="red")],
            settings=settings(bond_presets=["祝福"], bond_whitelist_mode="soft"),
        )
        d = choose_action(cands, session=SessionState(refreshes=3, max_refreshes=3))
        self.assertEqual(d.action, PolicyAction.SELECT_SLOT)
        self.assertEqual(d.index, 0)

    def test_dynamic_four_slot_bond_and_treasure_selection(self):
        """验证 4 选 1（4-Slot）布局下策略正确评分并选取最佳槽位。"""
        ps = settings(bond_presets=["成长之芽"], bond_whitelist_mode="soft")
        cands_4 = bond_cands(
            [
                slot(0, "散卡A", rarity="green"),
                slot(1, "散卡B", rarity="blue"),
                slot(2, "成长之芽", rarity="green"),
                slot(3, "散卡C", rarity="green"),
            ],
            settings=ps,
        )
        d = choose_action(cands_4, session=SessionState())
        self.assertEqual(d.action, PolicyAction.SELECT_SLOT)
        self.assertEqual(d.index, 2)
    def test_dynamic_four_slot_skill_strict_rejection(self):
        """验证 4 选 1（4-Slot）技能在无 focus 技能时严格返回 CLOSE。"""
        ps = PolicySettings(skill_presets=("剑气",), skill_fill_empty_slots=False)
        cands_4 = skill_cands(
            [
                slot(0, "地震", rarity="purple"),
                slot(1, "火球", rarity="blue"),
                slot(2, "冰锥", rarity="green"),
                slot(3, "旋风", rarity="blue"),
            ],
            settings=ps,
        )
        d = choose_action(cands_4, session=SessionState())
        self.assertEqual(d.action, PolicyAction.CLOSE)


if __name__ == "__main__":
    unittest.main()
