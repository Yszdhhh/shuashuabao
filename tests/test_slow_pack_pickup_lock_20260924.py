# -*- coding: utf-8 -*-
"""慢卡组（刀刀/修仙/海盗/亡灵）端到端拿取锁定（2026-09-24）。

`docs/handoff_20260924/CARD_FAMILY_PICKUP_AUDIT_20260924.md` 第二节第 1 条：大圣/异火/封神
和三条属性线都有"从首卡拿到终卡"的锁定测试，这四组没有，拿取逻辑被收敛删掉也不会变红。

每组都按看板方式装配：从 `ui-v2/src/main.ts` 的 `ADV_PACK_CARDS` 读出勾选后下发的卡名，
加上 Owner 看板的 5 个经济羁绊，经 `Mediator._policy_settings()` 读真实 `config/`。
锁的是 Owner 2026-09-24 的规则：
- 高级卡组不设硬门槛：开局一张基础羁绊都没有，本组卡单独出现也照拿；
- 从首卡逐张拿到白名单末卡，路人卡不拿；
- 同页有还没拿到的勾选基础羁绊时先拿基础，本组起步前后都一样（"差一张合成"除外）；
- 同一时刻只推进一组：前一组合成出 EX（海盗为 UR）之前，后一组的卡不拿；
- EX 终卡（解放的圣剑/大乘期/毁灭战舰/兵主）靠合成得到，不从面板拿。

海盗藏宝图、修仙练气期等成员的卡顶标题未经实机确认（审计第二节第 2 条），这里不锁。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from shuabao.choice_policy import (
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

OWNER_BONDS = ["成长", "经济", "贪婪", "挑战", "祝福"]
SLOW_PACKS = ("daodao", "xiuxian", "haidao", "wangling")
EX_FINALS_BY_SYNTHESIS = {
    "daodao": "解放的圣剑",
    "xiuxian": "大乘期",
    "haidao": "毁灭战舰",
    "wangling": "兵主",
}
# choice_lexicon 把修仙萌新/修仙大成归一成「修仙」（stack_need=3）：持有修仙和修仙萌新后，
# 修仙大成是"差一张合成"，这一步排在基础优先之前。卡顶标题未经实机确认。
NEAR_COMPLETE_BY_LEXICON = {"xiuxian": {"修仙大成"}}
STRANGER = "神兽"  # 看板没有入口、不在任何白名单组里的系列


def _dashboard_pack_cards() -> dict[str, list[str]]:
    source = (ROOT / "ui-v2" / "src" / "main.ts").read_text(encoding="utf-8")
    block = re.search(r"const ADV_PACK_CARDS[^=]*=\s*\{(.*?)\n\};", source, re.S)
    assert block, "ui-v2/src/main.ts 里找不到 ADV_PACK_CARDS"
    packs = {
        key: re.findall(r'"([^"]+)"', body)
        for key, body in re.findall(r"(\w+):\s*\[([^\]]*)\]", block.group(1))
    }
    assert set(SLOW_PACKS) <= set(packs), sorted(packs)
    return packs


PACK_CARDS = _dashboard_pack_cards()


def _policy(*packs: str):
    cards = [card for pack in packs for card in PACK_CARDS[pack]]
    settings = Settings(ocr_mode="off", bonds=list(OWNER_BONDS), attributes=[], cards=cards)
    return Mediator(settings, ROOT)._policy_settings()


def _decide(policy, names, *, owned=(), completed=0):
    cands = PanelCandidates(
        panel_kind=PANEL_BOND,
        slots=tuple(SlotCandidate(index=i, name=name, confidence=0.95) for i, name in enumerate(names)),
        owned_bond_cards=tuple(owned),
        can_refresh=True,
        settings=policy,
        round_elapsed_s=10.0,
        completed_advanced_groups=completed,
    )
    return choose_action(cands, SessionState())


@pytest.mark.parametrize("pack", SLOW_PACKS)
def test_dashboard_pack_is_one_whole_advanced_group(pack: str) -> None:
    policy = _policy(pack)
    cards = tuple(PACK_CARDS[pack])
    assert policy.bond_advanced_groups == (cards,)
    assert policy.bond_advanced_presets == cards
    assert policy.bond_base_presets == ("祝福", "成长", "经济", "挑战", "贪婪")
    assert policy.bond_whitelist_mode == "hard"


@pytest.mark.parametrize("pack", SLOW_PACKS)
def test_slow_pack_is_walked_from_first_to_last_card(pack: str) -> None:
    policy = _policy(pack)
    owned: list[str] = []
    for step, card in enumerate(PACK_CARDS[pack]):
        # 没有硬门槛：开局 10s、一张基础羁绊都没有，本组卡单独出现照拿。
        decision = _decide(policy, [STRANGER, card], owned=owned)
        assert (decision.action, decision.index) == (PolicyAction.SELECT_SLOT, 1), (step, card, decision.reason)
        # 规则锁 8：还没拿到的勾选基础羁绊同页出现时先拿基础，本组起步前后都一样；
        # 只有"差一张合成"排在它前面。
        decision = _decide(policy, [card, "经济"], owned=owned)
        expected = 0 if card in NEAR_COMPLETE_BY_LEXICON.get(pack, ()) else 1
        assert (decision.action, decision.index) == (PolicyAction.SELECT_SLOT, expected), (step, card, decision.reason)
        owned.append(card)

    decision = _decide(policy, [STRANGER], owned=owned)
    assert decision.action == PolicyAction.REFRESH, decision.reason


@pytest.mark.parametrize("first,second", [("daodao", "haidao"), ("wangling", "xiuxian")])
def test_second_pack_starts_only_after_the_first_pack_ex(first: str, second: str) -> None:
    policy = _policy(first, second)
    owned = list(PACK_CARDS[first])  # 材料拿齐也不算，要看到 EX
    opener = PACK_CARDS[second][0]
    decision = _decide(policy, [STRANGER, opener], owned=owned)
    assert decision.action == PolicyAction.REFRESH, decision.reason
    decision = _decide(policy, [STRANGER, opener], owned=owned, completed=1)
    assert (decision.action, decision.index) == (PolicyAction.SELECT_SLOT, 1), decision.reason


@pytest.mark.parametrize("pack", SLOW_PACKS)
def test_slow_pack_ex_final_is_never_picked_from_the_panel(pack: str) -> None:
    """Owner 2026-09-24：EX（海盗为 UR）靠合成链得到，不是从面板拿的。"""
    policy = _policy(pack)
    final = EX_FINALS_BY_SYNTHESIS[pack]
    assert final not in policy.bond_presets
    decision = _decide(policy, [final], owned=[*OWNER_BONDS, *PACK_CARDS[pack]])
    assert decision.action == PolicyAction.REFRESH, decision.reason
