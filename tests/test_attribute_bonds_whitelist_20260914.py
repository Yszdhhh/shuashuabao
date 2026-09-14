# -*- coding: utf-8 -*-
"""看板基础卡组的三条属性线（智力/力量/敏捷）必须进入羁绊白名单。

Owner 看板（2026-09-14）：基础卡组 = 智力 力量 敏捷 祝福 成长 经济 贪婪 挑战 法术 急速 魔能
魔术 暴击；user_settings.json 把属性存成 attributes=['int','agi','str']。策略装配只读
bonds / cards，属性线从未进白名单——第一局 35 次羁绊选择里这三张 0 次。
"""
from __future__ import annotations

from pathlib import Path

from shuabao.mediator import Mediator
from shuabao.settings import Settings

ROOT = Path(__file__).resolve().parents[1]

OWNER = dict(
    bonds=["成长", "经济", "贪婪", "挑战", "祝福"],
    attributes=["int", "agi", "str"],
    cards=["封神", "封神榜", "打神鞭", "杏黄旗", "斩仙飞刀", "海盗", "白赚海盗", "海盗劫掠者",
           "海盗宝藏", "法术", "急速", "魔能", "暴击", "魔术"],
)


def _policy(**overrides):
    med = Mediator(Settings(ocr_mode="off", **{**OWNER, **overrides}), ROOT)
    return med._policy_settings()


def test_owner_attribute_lines_are_basic_bond_presets() -> None:
    policy = _policy()
    for name in ("智力", "力量", "敏捷"):
        assert name in policy.bond_presets, name
        assert name in policy.bond_base_presets, name
        assert name not in policy.bond_advanced_presets, name


def test_existing_bond_order_is_kept_ahead_of_attributes() -> None:
    presets = list(_policy().bond_presets)
    assert presets[:5] == OWNER["bonds"]
    assert presets.index("智力") > presets.index("祝福")


def test_no_attributes_selected_means_no_attribute_presets() -> None:
    policy = _policy(attributes=[])
    for name in ("智力", "力量", "敏捷"):
        assert name not in policy.bond_presets
