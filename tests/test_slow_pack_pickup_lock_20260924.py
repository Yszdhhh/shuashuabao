# -*- coding: utf-8 -*-
"""慢卡组（刀刀/修仙/海盗/亡灵）端到端拿取锁定（2026-09-24）。

`docs/handoff_20260924/CARD_FAMILY_PICKUP_AUDIT_20260924.md` 第二节第 1 条：大圣/异火/封神
和三条属性线都有"从首卡拿到终卡"的锁定测试，这四组没有，拿取逻辑被收敛删掉也不会变红。

每组都按看板方式装配：从 `ui-v2/src/main.ts` 的 `ADV_PACK_CARDS` 读出勾选后下发的卡名，
加上 Owner 看板的 5 个经济羁绊，经 `Mediator._policy_settings()` 读真实 `config/`。
锁的是当前行为：
- 开局基础羁绊未达 80% 且未到 480s：本组卡不拿，同页有基础卡时拿基础卡；
- 解锁后（480s 时间兜底，或基础 80%）：从首卡逐张拿到白名单末卡，路人卡不拿；
- 同页有缺的基础羁绊时先拿基础（规则锁 8）。本组起步后也一样：慢卡组不走 EX 直通组的
  "已选 EX 卡组持续推进"，按白名单顺序基础在前。例外是修仙萌新/修仙大成：`choice_lexicon`
  把它们归一成「修仙」，持有修仙后按"已持有合成"压过基础卡（`LEXICON_MERGE_STAGES`）；
- EX 终卡（解放的圣剑/大乘期/毁灭战舰/兵主）当前不拿，待 Owner 定（审计第二节第 3 条）。
  Owner 定了要拿，就改 `EX_FINALS_NOT_TAKEN_PENDING_OWNER` 和对应断言，并写明原话日期。

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
EX_FINALS_NOT_TAKEN_PENDING_OWNER = {
    "daodao": "解放的圣剑",
    "xiuxian": "大乘期",
    "haidao": "毁灭战舰",
    "wangling": "兵主",
}
# choice_lexicon 把这些阶段卡归一到本组首卡，持有首卡后它们走"已持有合成"（第 3 步），
# 排在基础羁绊之前。阶段卡能否单独持有、卡顶标题是什么都未经实机确认。
LEXICON_MERGE_STAGES = {"xiuxian": {"修仙萌新", "修仙大成"}}
STRANGER = "神兽"  # 看板没有入口、不在任何白名单组里的系列
UNLOCK_S = 480


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


def _policy(pack: str):
    settings = Settings(ocr_mode="off", bonds=list(OWNER_BONDS), attributes=[], cards=list(PACK_CARDS[pack]))
    return Mediator(settings, ROOT)._policy_settings()


def _decide(policy, names, *, owned=(), elapsed=60.0):
    cands = PanelCandidates(
        panel_kind=PANEL_BOND,
        slots=tuple(SlotCandidate(index=i, name=name, confidence=0.95) for i, name in enumerate(names)),
        owned_bond_cards=tuple(owned),
        can_refresh=True,
        settings=policy,
        round_elapsed_s=elapsed,
    )
    return choose_action(cands, SessionState())


def _unlocks():
    # 时间兜底：一张基础卡都没有，开局 480s；基础 80%：5 个经济羁绊持有 4 个，缺成长。
    return {
        "time": dict(owned=(), elapsed=float(UNLOCK_S), missing_base="经济"),
        "base80": dict(owned=("经济", "祝福", "贪婪", "挑战"), elapsed=60.0, missing_base="成长"),
    }


@pytest.mark.parametrize("pack", SLOW_PACKS)
def test_dashboard_pack_is_one_whole_advanced_group(pack: str) -> None:
    policy = _policy(pack)
    cards = tuple(PACK_CARDS[pack])
    assert policy.bond_advanced_groups == (cards,)
    assert policy.bond_advanced_presets == cards
    assert policy.bond_base_presets == ("经济", "祝福", "贪婪", "挑战", "成长")
    assert policy.bond_whitelist_mode == "hard"
    assert policy.bond_advanced_unlock_s == UNLOCK_S


@pytest.mark.parametrize("pack", SLOW_PACKS)
def test_slow_pack_waits_for_basic_gate(pack: str) -> None:
    policy = _policy(pack)
    first = PACK_CARDS[pack][0]
    decision = _decide(policy, [STRANGER, first], elapsed=UNLOCK_S - 1)
    assert decision.action == PolicyAction.REFRESH, decision.reason
    decision = _decide(policy, [first, "经济"], elapsed=UNLOCK_S - 1)
    assert (decision.action, decision.index) == (PolicyAction.SELECT_SLOT, 1), decision.reason


@pytest.mark.parametrize("unlock", ("time", "base80"))
@pytest.mark.parametrize("pack", SLOW_PACKS)
def test_slow_pack_is_walked_from_first_to_last_card(pack: str, unlock: str) -> None:
    policy = _policy(pack)
    ctx = _unlocks()[unlock]
    owned = list(ctx["owned"])
    for step, card in enumerate(PACK_CARDS[pack]):
        decision = _decide(policy, [STRANGER, card], owned=owned, elapsed=ctx["elapsed"])
        assert (decision.action, decision.index) == (PolicyAction.SELECT_SLOT, 1), (step, card, decision.reason)
        # 规则锁 8：缺的基础羁绊同页出现时先拿基础，起步前后都一样（词典归一的阶段卡除外）。
        decision = _decide(policy, [card, ctx["missing_base"]], owned=owned, elapsed=ctx["elapsed"])
        expected = 0 if card in LEXICON_MERGE_STAGES.get(pack, ()) else 1
        assert (decision.action, decision.index) == (PolicyAction.SELECT_SLOT, expected), (step, card, decision.reason)
        owned.append(card)

    decision = _decide(policy, [STRANGER], owned=owned, elapsed=ctx["elapsed"])
    assert decision.action == PolicyAction.REFRESH, decision.reason


@pytest.mark.parametrize("pack", SLOW_PACKS)
def test_slow_pack_ex_final_is_not_taken_pending_owner_decision(pack: str) -> None:
    policy = _policy(pack)
    final = EX_FINALS_NOT_TAKEN_PENDING_OWNER[pack]
    assert final not in policy.bond_presets
    owned = [*_unlocks()["base80"]["owned"], *PACK_CARDS[pack]]
    decision = _decide(policy, [final], owned=owned, elapsed=float(UNLOCK_S))
    assert decision.action == PolicyAction.REFRESH, decision.reason
