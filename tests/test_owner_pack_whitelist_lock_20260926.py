"""Owner 卡组白名单锁（2026-09-26）。

用真实 config/choice_policy.json 和 ui-v2 看板的高级卡组清单走一遍装配 + 决策，
锁住以下 Owner 规则：
- 每个高级卡组的白名单都含卡族名本身（海贼王、异火看到就拿）；
- 刀刀含 8 件装备（旋涡、风之杖、纷争面纱、风神杖、灵匣、绝刃、雷神之锤、希瓦的守护）；
- 修仙含五极山（五座山 + 元禾五极山）；海盗含藏宝图；
- 高级卡组之间的先后由看板优先级（勾选顺序）决定；
- 预设高级组未全部完成时，刷新耗尽兜底只拿非高级卡；
- 预设高级组全部完成后，允许任意高级或基础卡参与兜底。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from shuabao.choice_policy import (
    PANEL_BOND,
    PanelCandidates,
    PolicyAction,
    SessionState,
    SlotCandidate,
    assemble_policy_settings,
    choose_action,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY_DOC = json.loads((ROOT / "config/choice_policy.json").read_text(encoding="utf-8"))

# 看板 pack id → 卡族名（Owner 口径）
PACK_FAMILY = {
    "daodao": "刀刀",
    "yihuo": "异火",
    "dasheng": "大圣",
    "xiuxian": "修仙",
    "fengshen": "封神",
    "haidao": "海盗",
    "wangling": "亡灵",
    "haizeiwang": "海贼王",
}

OWNER_PACK_CARDS = {
    # Owner 2026-09-26：刀刀装备，按游戏实际名字。
    "daodao": ("旋涡", "风之杖", "纷争面纱", "风神杖", "灵匣", "绝刃", "雷神之锤", "希瓦的守护"),
    # Owner 2026-09-26：五极山属修仙，拿满 5 个提高出大乘概率。
    "xiuxian": ("太乙青山", "元磁神山", "阴阳大五行山", "北极元山", "昊阴寒魄山", "元禾五极山"),
    # 海盗靠藏宝图(三)开池。
    "haidao": ("藏宝图",),
}


def _dashboard_packs() -> dict[str, list[str]]:
    """读 ui-v2 看板实际下发的 ADV_PACK_CARDS，保证测的是用户勾选后真实的 cards。"""
    src = (ROOT / "ui-v2/src/main.ts").read_text(encoding="utf-8")
    block = re.search(r"const ADV_PACK_CARDS[^{]*\{(.*?)\n\};", src, re.S)
    assert block, "ui-v2 ADV_PACK_CARDS 不见了"
    packs = {}
    for pack_id, body in re.findall(r"(\w+):\s*\[(.*?)\]", block.group(1)):
        packs[pack_id] = re.findall(r'"([^"]+)"', body)
    return packs


def _policy(pack_ids: list[str], bonds=("成长", "经济", "祝福")):
    packs = _dashboard_packs()
    cards: list[str] = []
    for pack_id in pack_ids:
        for name in packs[pack_id]:
            if name not in cards:
                cards.append(name)
    return assemble_policy_settings(
        settings=SimpleNamespace(skills=[], cards=cards, bonds=list(bonds), treasure_allow_negative=[]),
        skill_labels={},
        fetter_labels={},
        policy_doc=POLICY_DOC,
    )


def _slot(index: int, name: str) -> SlotCandidate:
    return SlotCandidate(index=index, name=name, confidence=0.95, rarity=None, description="")


def _decide(policy, names, *, refreshes=0, can_refresh=False, free_slots=None, completed_advanced_groups=0):
    cands = PanelCandidates(
        panel_kind=PANEL_BOND,
        slots=tuple(_slot(i, n) for i, n in enumerate(names)),
        settings=policy,
        can_refresh=can_refresh,
        free_slots=free_slots,
        completed_advanced_groups=completed_advanced_groups,
    )
    return choose_action(cands, SessionState(refreshes=refreshes))


def test_dashboard_offers_every_owner_pack() -> None:
    assert set(PACK_FAMILY) <= set(_dashboard_packs())


@pytest.mark.parametrize("pack_id", sorted(PACK_FAMILY))
def test_ticked_pack_whitelist_contains_the_family_name(pack_id: str) -> None:
    family = PACK_FAMILY[pack_id]
    policy = _policy([pack_id])
    assert len(policy.bond_advanced_groups) == 1
    assert family in policy.bond_advanced_groups[0]
    assert family in policy.bond_presets
    decision = _decide(policy, ["贪婪", family, "固守"])
    assert (decision.action, decision.index) == (PolicyAction.SELECT_SLOT, 1), decision.reason


@pytest.mark.parametrize(
    "pack_id,card",
    [(pack_id, card) for pack_id, cards in OWNER_PACK_CARDS.items() for card in cards],
)
def test_owner_named_pack_cards_are_taken(pack_id: str, card: str) -> None:
    policy = _policy([pack_id])
    assert card in policy.bond_presets
    decision = _decide(policy, ["贪婪", "固守", card])
    assert (decision.action, decision.index) == (PolicyAction.SELECT_SLOT, 2), decision.reason


def test_treasure_map_template_label_is_taken_for_pirates() -> None:
    """模板/OCR 读出的『藏宝图(三)』同样属于海盗。"""
    decision = _decide(_policy(["haidao"]), ["贪婪", "藏宝图(三)"])
    assert (decision.action, decision.index) == (PolicyAction.SELECT_SLOT, 1), decision.reason


def test_advanced_pack_order_follows_dashboard_priority() -> None:
    """Owner 2026-09-26：高级卡组之间的先后由看板优先级决定。"""
    first = _policy(["yihuo", "daodao"])
    assert [g[0] for g in first.bond_advanced_groups] == ["异火", "刀刀"]
    assert (_decide(first, ["旋涡", "异火"]).index) == 1
    second = _policy(["daodao", "yihuo"])
    assert [g[0] for g in second.bond_advanced_groups] == ["刀刀", "异火"]
    assert (_decide(second, ["旋涡", "异火"]).index) == 0


def test_refresh_fallback_before_all_advanced_complete_only_takes_non_advanced() -> None:
    policy = _policy(["daodao", "yihuo"], bonds=("祝福",))
    decision = _decide(
        policy, ["异火", "见习海贼", "贪婪"],
        refreshes=3, can_refresh=True, completed_advanced_groups=0,
    )
    assert (decision.action, decision.index) == (PolicyAction.SELECT_SLOT, 2), decision.reason


def test_refresh_fallback_after_all_advanced_complete_allows_any_advanced_or_base() -> None:
    policy = _policy(["daodao", "yihuo"], bonds=("祝福",))
    decision = _decide(
        policy, ["见习海贼", "贪婪"],
        refreshes=3, can_refresh=True, completed_advanced_groups=2,
    )
    assert (decision.action, decision.index) == (PolicyAction.SELECT_SLOT, 0), decision.reason


def test_no_advanced_pack_selected_does_not_unlock_unselected_advanced_fallback() -> None:
    policy = _policy([], bonds=("祝福",))
    decision = _decide(
        policy, ["见习海贼", "贪婪"],
        refreshes=3, can_refresh=False, completed_advanced_groups=0,
    )
    assert (decision.action, decision.index) == (PolicyAction.SELECT_SLOT, 1), decision.reason

    only_advanced = _decide(
        policy, ["见习海贼", "异火"],
        refreshes=3, can_refresh=False, completed_advanced_groups=0,
    )
    assert only_advanced.action is not PolicyAction.SELECT_SLOT


def test_refresh_is_used_before_the_fallback() -> None:
    policy = _policy(["daodao"], bonds=("祝福",))
    decision = _decide(policy, ["见习海贼", "贪婪"], refreshes=2, can_refresh=True)
    assert decision.action == PolicyAction.REFRESH, decision.reason
