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

from gamescript.choice_policy import (
    DEFAULT_QUALITY_ORDER,
    PANEL_BOND,
    PANEL_SKILL,
    PANEL_TREASURE,
    PanelCandidates,
    PolicyAction,
    PolicyDecision,
    PolicySettings,
    SessionState,
    SlotCandidate,
    choose_action,
    panel_priority,
)

# 便捷构造 -----------------------------------------------------------------


def slot(index, name=None, confidence=0.95, rarity=None):
    return SlotCandidate(
        index=index, name=name, confidence=confidence, rarity=rarity
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
        self.assertEqual(d.action, PolicyAction.REFRESH)
        self.assertIsNone(d.index)

    def test_refresh_exhausted_giveup(self):
        d = choose_action(
            skill_cands(
                [slot(0, "地震")], has_giveup=True,
                settings=settings(skill_presets=["寒冰箭"]),
            ),
            SessionState(refreshes=3, max_refreshes=3),
        )
        self.assertEqual(d.action, PolicyAction.GIVEUP)
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
        # 候选含高置信非预设技能：必须返回非 SELECT（刷新）。
        d = choose_action(
            skill_cands(
                [slot(0, "剑气", confidence=0.99), slot(1, "地震", confidence=0.98)],
                settings=settings(skill_presets=["寒冰箭"]),
            ),
            SessionState(),
        )
        self.assertNotEqual(d.action, PolicyAction.SELECT_SLOT)
        self.assertEqual(d.action, PolicyAction.REFRESH)

    def test_never_select_non_preset_even_when_presets_empty(self):
        d = choose_action(
            skill_cands(
                [slot(0, "剑气", confidence=0.99)],
                settings=settings(skill_presets=[]),
            ),
            SessionState(),
        )
        self.assertNotEqual(d.action, PolicyAction.SELECT_SLOT)

    def test_unknown_skill_slots_never_select(self):
        # 全部槽位 unknown：技能路径不允许 WAIT，直接刷新。
        d = choose_action(
            skill_cands(
                [slot(0, None), slot(1, None)],
                settings=settings(skill_presets=["剑气"]),
            ),
            SessionState(),
        )
        self.assertNotEqual(d.action, PolicyAction.SELECT_SLOT)
        self.assertEqual(d.action, PolicyAction.REFRESH)

    def test_skill_no_wait_path(self):
        # 技能面板永不返回 WAIT（预设缺失即刷新/退出）。
        for refresh_count in range(4):
            d = choose_action(
                skill_cands(
                    [slot(0, None)],
                    settings=settings(skill_presets=["剑气"]),
                ),
                SessionState(refreshes=refresh_count, max_refreshes=3),
            )
            self.assertNotEqual(d.action, PolicyAction.WAIT)


class TestBondTreasureUnknown(unittest.TestCase):
    """羁绊/宝物：unknown 绝不冒充词典内名称；只能 WAIT/REFRESH。"""

    def test_bond_unknown_only_slot_no_click(self):
        d = choose_action(
            bond_cands([slot(0, None)], settings=settings(bond_presets=["三国"])),
            SessionState(),
        )
        self.assertNotEqual(d.action, PolicyAction.SELECT_SLOT)
        self.assertEqual(d.action, PolicyAction.WAIT)

    def test_bond_unknown_wait_then_refresh_then_giveup(self):
        # WAIT 有上限：waits 耗尽 → REFRESH；刷新耗尽 → GIVEUP/CLOSE。
        cands = bond_cands(
            [slot(0, None), slot(1, None)],
            has_giveup=True,
            settings=settings(bond_presets=["三国"]),
        )
        d = choose_action(cands, SessionState(waits=2, max_waits=2))
        self.assertEqual(d.action, PolicyAction.REFRESH)
        d = choose_action(
            cands, SessionState(waits=2, max_waits=2, refreshes=3, max_refreshes=3)
        )
        self.assertEqual(d.action, PolicyAction.GIVEUP)

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
        self.assertEqual(d.action, PolicyAction.WAIT)

    def test_wait_cap_prevents_infinite_wait(self):
        # 任意 waits 计数下，决策序列必在有限步内离开 WAIT。
        cands = bond_cands(
            [slot(0, None)], has_giveup=True,
            settings=settings(bond_presets=["三国"]),
        )
        state = SessionState(waits=0, max_waits=3, max_refreshes=3)
        seq = []
        for _ in range(10):  # 超过理论上限的轮数
            d = choose_action(cands, state)
            seq.append(d.action)
            if d.action == PolicyAction.WAIT:
                state = SessionState(
                    waits=state.waits + 1, max_waits=3, max_refreshes=3
                )
            elif d.action == PolicyAction.REFRESH:
                state = SessionState(
                    refreshes=state.refreshes + 1, max_waits=3, max_refreshes=3,
                    waits=3,
                )
            else:
                break
        self.assertIn(PolicyAction.REFRESH, seq)
        self.assertEqual(seq[-1], PolicyAction.GIVEUP)
        self.assertLessEqual(seq.count(PolicyAction.WAIT), 3)


class TestBondPriority(unittest.TestCase):
    """羁绊：预设 > 接近合成 > 品质降级。"""

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
    """宝物：预设 + 套装进度优先（龙珠可验证字段）→ 品质序降级。"""

    def test_dragonball_set_progress_priority(self):
        # 龙珠 6/7，owned 可验证缺七星球：选中缺失的七星球（非已拥有的四星球）。
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
        self.assertEqual((d.action, d.index), (PolicyAction.SELECT_SLOT, 1))

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

    def test_treasure_no_safe_candidate_refresh(self):
        cands = treasure_cands(
            [slot(0, None), slot(1, None)],
            has_giveup=True,
            settings=settings(),
        )
        d = choose_action(
            cands, SessionState(waits=2, max_waits=2)
        )
        self.assertEqual(d.action, PolicyAction.REFRESH)


class TestTieBreakAndDeterminism(unittest.TestCase):
    """并列优先级固定 tie-break；同输入同输出。"""

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
        self.assertEqual(d.action, PolicyAction.GIVEUP)
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
        # 总期限过期优先于任何正常动作（包括技能预设命中）。
        d = choose_action(
            skill_cands(
                [slot(0, "剑气")], has_giveup=True,
                settings=settings(skill_presets=["剑气"]),
            ),
            SessionState(deadline_exceeded=True),
        )
        self.assertEqual(d.action, PolicyAction.GIVEUP)

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
        self.assertEqual(d.action, PolicyAction.GIVEUP)

    def test_min_confidence_gate(self):
        # 预设命中但置信度低于 min_confidence → 不可选（刷新）。
        cands = skill_cands(
            [slot(0, "剑气", confidence=0.5)],
            settings=settings(skill_presets=["剑气"], min_confidence=0.8),
        )
        d = choose_action(cands, SessionState())
        self.assertNotEqual(d.action, PolicyAction.SELECT_SLOT)
        self.assertEqual(d.action, PolicyAction.REFRESH)


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


if __name__ == "__main__":
    unittest.main()
