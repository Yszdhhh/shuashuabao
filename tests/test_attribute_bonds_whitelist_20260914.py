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

