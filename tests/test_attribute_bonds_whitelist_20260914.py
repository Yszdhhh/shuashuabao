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


def test_owner_attribute_lines_are_whitelisted_outside_the_80_percent_gate() -> None:
    """2026-09-15：属性线整条（含门卡）都可拿，但不计入基础卡 80% 分母。

    实机 000229：门卡进分母后 13 个基础家族需碰到 11 个，只到 10，门槛再没解开。
    """
    policy = _policy()
    for name in ("智力", "力量", "敏捷"):
        assert name in policy.bond_presets, name
        assert name in policy.bond_chain_presets, name
        assert name not in policy.bond_base_presets, name
        assert name not in policy.bond_advanced_presets, name
    assert len(policy.bond_base_presets) == 10


def test_whitelist_order_economy_by_payback_then_basic_then_attribute_lines() -> None:
    """KB 卡面：祝福净赚木材、经济~10 分钟回本、贪婪钥匙+150 木、挑战间接、成长~22 分钟。"""
    presets = list(_policy().bond_presets)
    assert presets[:5] == ["祝福", "经济", "贪婪", "挑战", "成长"]
    assert presets.index("魔术") < presets.index("智力") < presets.index("封神")


def test_no_attributes_selected_means_no_attribute_presets() -> None:
    policy = _policy(attributes=[])
    for name in ("智力", "力量", "敏捷"):
        assert name not in policy.bond_presets


def test_real_frame_selects_agility_with_owner_attributes() -> None:
    """真实帧夹具测试：槽位 [箭术, 藏宝图(三), 体术, 敏捷]。

    交接提示词提及 f0062（槽位 箭术/藏宝图/体术/敏捷），经 trace 与抓帧校验，
    包含 [箭术, 藏宝图(三), 体术, 敏捷] 的真实帧为 f0121_action_before.png。
    带 Owner 当前 attributes (int/agi/str) 时断言选中【敏捷】；
    无 attributes 时断言不选敏捷（触发刷新）。
    在 20752af 修复前因 attributes 未入白名单，两者均会选刷新。
    """
    import cv2
    import numpy as np
    import pytest
    from shuabao.vision.capture import Frame

    fixture_path = ROOT / "tests" / "fixtures" / "solo_live_20260914" / "f0121_action_before.png"
    if not fixture_path.exists():
        fixture_path = ROOT / "tests" / "fixtures" / "solo_live_20260914" / "f0062_action_before.png"
    if not fixture_path.exists():
        pytest.skip(f"Fixture {fixture_path} not found")

    frame_bgr = cv2.imdecode(np.fromfile(str(fixture_path), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert frame_bgr is not None, "Failed to load fixture"
    frame = Frame(frame_bgr)

    # 1. 带 Owner 当前 attributes (int/agi/str) 策略：选中敏捷
    med = Mediator(Settings(ocr_mode="live", **OWNER), ROOT)
    choice = med._find_reward_choice(frame)
    assert choice is not None, "Expected choice on bond selection panel"
    kind, hit = choice
    assert kind == "bond", f"Expected bond selection, got {kind}"
    assert "敏捷" in hit.name, f"Expected 敏捷 in {hit.name}"

    # 2. 不带 attributes 策略：不选敏捷，触发刷新
    med_no_attr = Mediator(Settings(ocr_mode="live", **{**OWNER, "attributes": []}), ROOT)
    choice_no_attr = med_no_attr._find_reward_choice(frame)
    assert choice_no_attr is not None, "Expected refresh on bond selection panel"
    kind_no_attr, hit_no_attr = choice_no_attr
    assert kind_no_attr == "bond刷新", f"Expected bond刷新, got {kind_no_attr}"


def test_attribute_line_is_walked_from_gate_card_to_ur() -> None:
    """Owner 2026-09-14：属性线 = 开启卡组到 UR；门卡之后的整条链都要拿。"""
    policy = _policy()
    for chain in (("智力", "秘法师", "法神", "湮灭者"),
                  ("力量", "野蛮人", "战神", "屠戮者"),
                  ("敏捷", "猎魔人", "弓神", "收割者")):
        for name in chain:
            assert name in policy.bond_presets, name
        for name in chain[1:]:
            assert name in policy.bond_chain_presets, name
            assert name not in policy.bond_base_presets, name
            assert name not in policy.bond_advanced_presets, name


def test_only_selected_attribute_lines_are_expanded() -> None:
    policy = _policy(attributes=["int"])
    assert "法神" in policy.bond_presets
    for name in ("力量", "野蛮人", "屠戮者", "敏捷", "猎魔人", "收割者"):
        assert name not in policy.bond_presets, name


def test_intelligence_support_cards_are_not_part_of_the_attribute_line() -> None:
    """魔法师/元素师偏智力，但属于看板基础卡组选项，不随属性线自动拿。"""
    policy = _policy(attributes=["int"])
    for name in ("魔法师", "元素师"):
        assert name not in policy.bond_presets, name
    picked = _policy(attributes=["int"], cards=[*OWNER["cards"], "魔法师", "元素师"])
    for name in ("魔法师", "元素师"):
        assert name in picked.bond_base_presets, name


def test_chain_constants_match_the_kb_attr_routes() -> None:
    import json

    from shuabao.choice_policy import _ATTRIBUTE_CHAINS

    doc = json.loads((ROOT / "config" / "official_strategy_defaults.json").read_text(encoding="utf-8"))
    routes = doc["attr_routes"]
    assert _ATTRIBUTE_CHAINS["int"] == tuple(routes["intelligence"]["chain"])
    assert _ATTRIBUTE_CHAINS["str"] == tuple(routes["strength"]["chain"])
    assert _ATTRIBUTE_CHAINS["agi"] == tuple(routes["agility"]["chain"])


def test_chain_card_is_selectable_before_basic_bonds_reach_80_percent() -> None:
    from shuabao.choice_policy import (
        PANEL_BOND, PanelCandidates, PolicyAction, SessionState, SlotCandidate, choose_action,
    )

    policy = _policy()
    cands = PanelCandidates(
        panel_kind=PANEL_BOND,
        slots=(
            SlotCandidate(index=0, name="白赚海盗", confidence=0.99),
            SlotCandidate(index=1, name="秘法师", confidence=0.99),
        ),
        owned_bond_cards=("智力",),
        can_refresh=True,
        settings=policy,
    )
    decision = choose_action(cands, SessionState())
    assert decision.action == PolicyAction.SELECT_SLOT, decision.reason
    assert decision.index == 1

