# -*- coding: utf-8 -*-
"""首个正式版卡组范围收敛（Owner 2026-09-26）。

拿满即出 EX 型（异火/大圣/封神/海贼王）：“按需求拿满就能出 EX”，优先进初版。
锁的是纯函数 `choose_action` 行为：
- 看板勾选某组 pack cards 后，整组可拿成员都在白名单里；
- 给定面板序列从首卡走到末卡，路人卡不拿；
- 帝炎/法天象地/圣人靠合成得到，面板出现也不拿；海贼王与系列同名，按 Owner 2026-09-26 规则看到就拿；
- 前一组未合成出 EX（海盗为 UR）之前，下一组不开；看到 EX 计数后解锁下一组。

慢卡组（刀刀/修仙/海盗/亡灵）的同类锁定见
`tests/test_slow_pack_pickup_lock_20260924.py`，这里不重复。
修仙只删错误成员「元神出窍」（不补境界链）；亡灵标实验不默认（见末尾两条）。
"""
from __future__ import annotations

import json
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
from shuabao.vision.choice_ocr import lookup_lexicon

ROOT = Path(__file__).resolve().parents[1]

OWNER_BONDS = ["成长", "经济", "贪婪", "挑战", "祝福"]
FAST_PACKS = ("yihuo", "dasheng", "fengshen", "haizeiwang")
EX_FINAL = {
    "yihuo": "帝炎",
    "dasheng": "法天象地",
    "fengshen": "圣人",
    "haizeiwang": "海贼王",
}
# 大圣组内唯一的单卡前置：禁字法必须先有安身法（choice_policy 既有门禁）。
WALK_SEED_OWNED = {"dasheng": ("安身法",)}
STRANGER = "神兽"  # 看板没有入口、不在任何白名单组里的系列


def _dashboard_pack_cards() -> dict[str, list[str]]:
    source = (ROOT / "ui-v2" / "src" / "main.ts").read_text(encoding="utf-8")
    block = re.search(r"const ADV_PACK_CARDS[^=]*=\s*\{(.*?)\n\};", source, re.S)
    assert block, "ui-v2/src/main.ts 里找不到 ADV_PACK_CARDS"
    return {
        key: re.findall(r'"([^"]+)"', body)
        for key, body in re.findall(r"(\w+):\s*\[([^\]]*)\]", block.group(1))
    }


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


def _group_of(policy, pack: str) -> tuple[str, ...]:
    for group in policy.bond_advanced_groups:
        if PACK_CARDS[pack][0] in group:
            return tuple(group)
    raise AssertionError(f"{pack} 没有装配出推进组")


@pytest.mark.parametrize("pack", FAST_PACKS)
def test_fast_pack_group_covers_dashboard_cards_and_ex_scope(pack: str) -> None:
    policy = _policy(pack)
    group = _group_of(policy, pack)
    final = EX_FINAL[pack]
    assert set(PACK_CARDS[pack]) <= set(group)
    for name in group:
        if name != final:
            assert name in policy.bond_presets, (pack, name)
    if pack == "haizeiwang":
        assert final in policy.bond_advanced_presets
        assert final in policy.bond_presets
    else:
        assert final not in policy.bond_presets
        assert final not in policy.bond_advanced_presets
        assert final not in policy.bond_base_presets


@pytest.mark.parametrize("pack", FAST_PACKS)
def test_fast_pack_is_walked_from_first_to_last_pickable_card(pack: str) -> None:
    policy = _policy(pack)
    group = _group_of(policy, pack)
    final = EX_FINAL[pack]
    owned: list[str] = list(WALK_SEED_OWNED.get(pack, ()))
    for step, card in enumerate([name for name in group if name != final]):
        decision = _decide(policy, [STRANGER, card], owned=owned)
        assert (decision.action, decision.index) == (PolicyAction.SELECT_SLOT, 1), (step, card, decision.reason)
        decision_blessing = _decide(policy, [card, "祝福"], owned=owned)
        assert (decision_blessing.action, decision_blessing.index) == (PolicyAction.SELECT_SLOT, 1), (step, card, decision_blessing.reason)
        # Owner 2026-09-26：祝福 > 成长/经济 > 当前高级组，经济同页先拿。
        decision_econ = _decide(policy, [card, "经济"], owned=owned)
        assert (decision_econ.action, decision_econ.index) == (PolicyAction.SELECT_SLOT, 1), (step, card, decision_econ.reason)
        owned.append(card)
    # EX 终卡通常靠合成；海贼王与系列同名，按 Owner 2026-09-26 口径拿。
    decision = _decide(policy, [EX_FINAL[pack]], owned=owned)
    if pack == "haizeiwang":
        assert (decision.action, decision.index) == (PolicyAction.SELECT_SLOT, 0), decision.reason
    else:
        assert decision.action != PolicyAction.SELECT_SLOT, decision.reason


@pytest.mark.parametrize(
    "first,second",
    [("yihuo", "dasheng"), ("dasheng", "fengshen"), ("fengshen", "haizeiwang")],
)
def test_second_pack_starts_only_after_the_first_pack_ex(first: str, second: str) -> None:
    policy = _policy(first, second)
    owned = [name for name in _group_of(policy, first) if name != EX_FINAL[first]]
    opener = PACK_CARDS[second][0]
    decision = _decide(policy, [STRANGER, opener], owned=owned)
    assert decision.action == PolicyAction.REFRESH, decision.reason
    decision = _decide(policy, [STRANGER, opener], owned=owned, completed=1)
    assert (decision.action, decision.index) == (PolicyAction.SELECT_SLOT, 1), decision.reason


def test_xiuxian_yuanshenchuqiao_removed_everywhere() -> None:
    policy_doc = json.loads((ROOT / "config" / "choice_policy.json").read_text(encoding="utf-8"))
    assert "元神出窍" not in policy_doc["bond"]["advanced_names"]
    assert all("元神出窍" not in group for group in policy_doc["bond"]["advanced_groups"])
    defaults = json.loads((ROOT / "config" / "official_strategy_defaults.json").read_text(encoding="utf-8"))
    assert "元神出窍" not in defaults["card_packs"]["advanced"]["xiuxian"]["cards"]
    assert "元神出窍" not in PACK_CARDS["xiuxian"]
    policy = _policy("xiuxian")
    assert "元神出窍" not in policy.bond_presets
    # 剩下 5 张照拿：面板出现不再 CLOSE。
    owned: list[str] = []
    for card in PACK_CARDS["xiuxian"]:
        decision = _decide(policy, [STRANGER, card], owned=owned)
        assert (decision.action, decision.index) == (PolicyAction.SELECT_SLOT, 1), (card, decision.reason)
        owned.append(card)


def test_wangling_marked_experimental_and_off_by_default() -> None:
    defaults = json.loads((ROOT / "config" / "official_strategy_defaults.json").read_text(encoding="utf-8"))
    assert defaults["card_packs"]["advanced"]["wangling"].get("experimental") is True
    html = (ROOT / "ui-v2" / "index.html").read_text(encoding="utf-8")
    m = re.search(r"const ADV_EXPERIMENTAL\s*=\s*\[(.*?)\];", html, re.S)
    assert m and '"wangling"' in m.group(1).replace("'", '"')
    for adv_list in re.findall(r"adv:\[([^\]]*)\]", html):
        assert "wangling" not in adv_list
    # 未勾选时零影响：不带亡灵卡装配就没有推进组，基础卡照拿。
    policy = _policy("haidao")
    assert policy.bond_advanced_groups != ()
    assert all("亡灵" not in group for group in policy.bond_advanced_groups)
    decision = _decide(policy, ["经济"], owned=())
    assert (decision.action, decision.index) == (PolicyAction.SELECT_SLOT, 0), decision.reason


def test_new_lexicon_entries_resolve_as_bond() -> None:
    entries = json.loads((ROOT / "config" / "choice_lexicon.json").read_text(encoding="utf-8"))["entries"]
    expected_sets = {
        "见习海贼": "海贼王", "超新星": "海贼王", "七武海": "海贼王",
        "凯多": "海贼王", "红发": "海贼王", "白胡子": "海贼王", "大妈": "海贼王",
        "打神鞭": "封神", "杏黄旗": "封神",
        "海盗宝藏": "海盗",
    }
    for name, set_name in expected_sets.items():
        assert lookup_lexicon(name, kind="bond").canonical == name
        assert entries[name]["kind"] == "bond"
        assert entries[name]["set_membership"] == set_name
