# -*- coding: utf-8 -*-
"""勾一条属性线后从门卡到 UR 的纯函数序列测试（2026-09-26）。

覆盖 grok 核查 attribute_lines_ur_check.md 的断点修复：
- UR 散件名单槽出现时视同该线 UR 去拿（不再刷新）；
- 门卡凑满后同页让路给下一环；
- 与祝福同页时祝福无条件最高优先；
- 当前高级卡组先于未入手属性链卡（Owner 2026-09-26：成长/经济除外）。

全部走 choose_action / assemble_policy_settings 纯函数，零真实输入。
"""
from __future__ import annotations

import json
from pathlib import Path

from shuabao.choice_policy import (
    _ATTRIBUTE_CHAINS,
    _ATTRIBUTE_PIECES,
    PANEL_BOND,
    PanelCandidates,
    PolicyAction,
    SessionState,
    SlotCandidate,
    choose_action,
)
from shuabao.mediator import Mediator
from shuabao.settings import Settings

ROOT = Path(__file__).resolve().parents[1]

HAIDAO = ("海盗", "白赚海盗", "海盗劫掠者", "海盗宝藏")


def _policy(**overrides):
    med = Mediator(Settings(ocr_mode="off", **{**overrides}), ROOT)
    return med._policy_settings()


def _decide(*, slots, owned=(), attributes=("int",), bonds=(), cards=(), refreshes=0):
    policy = _policy(attributes=list(attributes), bonds=list(bonds), cards=list(cards))
    cands = PanelCandidates(
        panel_kind=PANEL_BOND,
        slots=tuple(
            SlotCandidate(index=i, name=name, confidence=0.99)
            if isinstance(name, str)
            else SlotCandidate(index=i, **name)
            for i, name in enumerate(slots)
        ),
        owned_bond_cards=tuple(owned),
        can_refresh=True,
        settings=policy,
    )
    return choose_action(cands, SessionState(refreshes=refreshes, max_refreshes=2))


def test_pieces_constants_match_the_kb_attr_routes() -> None:
    doc = json.loads((ROOT / "config" / "official_strategy_defaults.json").read_text(encoding="utf-8"))
    routes = doc["attr_routes"]
    assert _ATTRIBUTE_PIECES["int"] == tuple(routes["intelligence"]["pieces"])
    assert _ATTRIBUTE_PIECES["str"] == tuple(routes["strength"]["pieces"])
    assert _ATTRIBUTE_PIECES["agi"] == tuple(routes["agility"]["pieces"])


def test_pieces_are_whitelisted_as_chain_cards() -> None:
    policy = _policy(attributes=["int"], bonds=[], cards=[])
    for name in ("聚能之虹", "洞察之眼", "奥法之辉"):
        assert name in policy.bond_presets, name
        assert name in policy.bond_chain_presets, name
        assert name not in policy.bond_base_presets, name
        assert name not in policy.bond_advanced_presets, name
    # 未勾选的线不展开
    for name in ("战斗咆哮", "亡者之轮"):
        assert name not in policy.bond_presets, name


def test_single_piece_slot_is_selected_not_refreshed() -> None:
    decision = _decide(slots=["聚能之虹"])
    assert decision.action == PolicyAction.SELECT_SLOT, decision.reason
    assert decision.index == 0

    decision = _decide(slots=["亡者之轮"], attributes=("agi",))
    assert decision.action == PolicyAction.SELECT_SLOT, decision.reason
    assert decision.index == 0

    decision = _decide(slots=["战斗咆哮"], attributes=("str",))
    assert decision.action == PolicyAction.SELECT_SLOT, decision.reason
    assert decision.index == 0


def test_piece_and_set_name_on_the_same_page_prefers_the_line_order() -> None:
    # 散件排在该线套名之后：同页只看得到散件就拿散件，不刷新。
    decision = _decide(slots=["亡者之轮", "收割者"], attributes=("agi",))
    assert decision.action == PolicyAction.SELECT_SLOT, decision.reason
    assert decision.index == 1


def test_completed_gate_card_yields_to_the_next_ring() -> None:
    owned = ("智力", "智力", "智力", "智力")
    slots = [
        {"name": "智力", "confidence": 0.99, "evidence": "智力(4/4)"},
        {"name": "秘法师", "confidence": 0.99},
    ]
    decision = _decide(slots=slots, owned=owned)
    assert decision.action == PolicyAction.SELECT_SLOT, decision.reason
    assert decision.index == 1, decision.reason

    # 无进度后缀时靠已持有计数同样让路
    decision = _decide(slots=["智力", "秘法师"], owned=owned)
    assert decision.action == PolicyAction.SELECT_SLOT, decision.reason
    assert decision.index == 1, decision.reason


def test_next_ring_is_still_taken_with_empty_hands() -> None:
    """游戏若提前刷出后环，脚本本来就会点（现状锁定，非新增行为）。"""
    decision = _decide(slots=["秘法师"])
    assert decision.action == PolicyAction.SELECT_SLOT, decision.reason
    assert decision.index == 0


def test_gate_to_ur_walk_for_one_selected_line() -> None:
    """智力线：门卡→中环→次环→UR→散件，随持有进度逐环选中。"""
    decision = _decide(slots=["智力"])
    assert (decision.action, decision.index) == (PolicyAction.SELECT_SLOT, 0), decision.reason

    decision = _decide(slots=["秘法师"], owned=("智力",) * 4)
    assert (decision.action, decision.index) == (PolicyAction.SELECT_SLOT, 0), decision.reason

    decision = _decide(slots=["法神"], owned=("智力",) * 4 + ("秘法师",) * 4)
    assert (decision.action, decision.index) == (PolicyAction.SELECT_SLOT, 0), decision.reason

    decision = _decide(slots=["湮灭者"], owned=("智力",) * 4 + ("秘法师",) * 4 + ("法神",) * 3)
    assert (decision.action, decision.index) == (PolicyAction.SELECT_SLOT, 0), decision.reason

    decision = _decide(slots=["聚能之虹"], owned=("智力",) * 4 + ("秘法师",) * 4 + ("法神",) * 3)
    assert (decision.action, decision.index) == (PolicyAction.SELECT_SLOT, 0), decision.reason


def test_blessing_still_beats_the_chain_on_the_same_page() -> None:
    """Owner 2026-09-26：祝福无条件必拿且高于其它候选。"""
    decision = _decide(slots=["秘法师", "智力祝福"])
    assert decision.action == PolicyAction.SELECT_SLOT, decision.reason
    assert decision.index == 1, decision.reason

    decision = _decide(slots=["智力", "祝福"], bonds=("祝福",))
    assert decision.action == PolicyAction.SELECT_SLOT, decision.reason
    assert decision.index == 1, decision.reason


def test_current_advanced_pack_still_beats_unowned_chain_card() -> None:
    """Owner 2026-09-26：当前高级卡组高于其它白名单（属性线属于其它白名单）。"""
    decision = _decide(slots=["智力", "白赚海盗"], cards=list(HAIDAO))
    assert decision.action == PolicyAction.SELECT_SLOT, decision.reason
    assert decision.index == 1, decision.reason

    decision = _decide(slots=["智力", "白赚海盗"], owned=("智力",), cards=list(HAIDAO))
    assert decision.action == PolicyAction.SELECT_SLOT, decision.reason
    assert decision.index == 1, decision.reason


def test_skill_routes_ur_links_use_the_live_ur_names() -> None:
    """dashboard_mechanics.json 已把 skill_routes 的「不动尊」标成旧错：
    力量线 UR 是屠戮者（lab 152022 + 散件静帧）。"""
    doc = json.loads((ROOT / "config" / "skill_routes.json").read_text(encoding="utf-8"))
    links = doc["ur_links"]
    assert "湮灭者" in links["zhili"]
    assert "收割者" in links["mingjie"]
    assert "屠戮者" in links["liliang"]
    assert "不动尊" not in links["liliang"]


def test_chain_constants_still_match_the_kb_attr_routes() -> None:
    doc = json.loads((ROOT / "config" / "official_strategy_defaults.json").read_text(encoding="utf-8"))
    routes = doc["attr_routes"]
    assert _ATTRIBUTE_CHAINS["int"] == tuple(routes["intelligence"]["chain"])
    assert _ATTRIBUTE_CHAINS["str"] == tuple(routes["strength"]["chain"])
    assert _ATTRIBUTE_CHAINS["agi"] == tuple(routes["agility"]["chain"])
