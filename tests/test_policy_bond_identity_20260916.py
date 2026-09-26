"""Tests for bond identity membership, completion semantics, and substring isolation (2026-09-16)."""
from dataclasses import replace
from pathlib import Path
import pytest

from shuabao.choice_policy import (
    PANEL_BOND,
    PanelCandidates,
    PolicyAction,
    PolicySettings,
    SessionState,
    SlotCandidate,
    WHITELIST_HARD,
    _active_advanced_presets,
    _is_bond_must_take,
    canonical_bond_identity,
    choose_action,
    same_bond_identity,
)
from shuabao.settings import Settings

ROOT = Path(__file__).resolve().parent.parent


def test_bond_identity_truth_table():
    """规范化羁绊身份严格相等性真值表，防止子串混淆。"""
    assert not same_bond_identity("智力", "智力祝福")
    assert not same_bond_identity("力量", "力量提升")
    assert not same_bond_identity("海盗", "白赚海盗")
    assert not same_bond_identity("封神", "封神榜")
    assert same_bond_identity("成长", "成长之根")
    assert same_bond_identity("智力", "智力")
    assert same_bond_identity("智力(1/3)", "智力")
    assert same_bond_identity("海盗[2/4]", "海盗")


def test_bond_must_take_no_substring_pollution():
    """bond_must_take 严禁通过子串匹配非目标卡牌。"""
    assert not _is_bond_must_take("智力祝福", ("祝福",))
    assert not _is_bond_must_take("白赚海盗", ("海盗",))
    assert _is_bond_must_take("海盗", ("海盗",))
    assert _is_bond_must_take("海盗(1/3)", ("海盗",))

    # choose_action 集成验证：must_take 为海盗，面板出现白赚海盗，不可作为 must_take 选中
    settings = PolicySettings(
        bond_must_take=("海盗",),
        bond_presets=(),
        bond_whitelist_mode=WHITELIST_HARD,
    )
    cands = PanelCandidates(
        panel_kind=PANEL_BOND,
        slots=(
            SlotCandidate(index=0, name="白赚海盗", confidence=0.95),
            SlotCandidate(index=1, name="修仙", confidence=0.95),
        ),
        owned_bond_cards=(),
        can_refresh=False,
        settings=settings,
    )
    # 刷新还有时：白赚海盗不算必拿海盗，本页无目标应刷新。
    dec = choose_action(replace(cands, can_refresh=True), SessionState())
    assert dec.action == PolicyAction.REFRESH
    # 刷新用完：Owner 2026-09-26 03:33 要求兜底拿一张，但理由必须是兜底而非必拿。
    dec = choose_action(cands, SessionState())
    assert dec.action == PolicyAction.SELECT_SLOT
    assert "必拿" not in dec.reason


def test_active_advanced_pack_only_moves_on_after_its_ex():
    """Owner 2026-09-24：换组只看羁绊栏上的 EX 数；持有材料（含子串同名卡）都不换组。"""
    settings = PolicySettings(
        bond_advanced_groups=(("海盗", "探险"), ("封神", "修仙")),
        bond_base_completion_ratio=1.0,
    )
    for owned in (("白赚海盗",), ("海盗", "探险")):
        cands = PanelCandidates(
            panel_kind=PANEL_BOND,
            slots=(),
            owned_bond_cards=owned,
            settings=settings,
        )
        assert _active_advanced_presets(cands, settings) == ("海盗", "探险")
    for done, expected in ((1, ("封神", "修仙")), (5, ("封神", "修仙"))):
        cands = PanelCandidates(
            panel_kind=PANEL_BOND, slots=(), settings=settings, completed_advanced_groups=done,
        )
        assert _active_advanced_presets(cands, settings) == expected


def test_runtime_mediator_stages_policy_authorized_nonpreset_bond_card():
    """点击已由 Core 策略授权；Runtime 不得再用预设卡组过滤确认账本。"""
    from shuabao.runtime_mediator import Mediator as RuntimeMediator

    med = RuntimeMediator(Settings(cards=[]), ROOT)
    med._bond_cards_owned = ["海盗"]
    med._bond_cards_pending.clear()

    # soft 模式可在刷新预算用尽后选择非预设品质回退；点击后必须记账。
    med._stage_bond_card("白赚海盗")
    assert med._bond_cards_pending == ["白赚海盗"]

    # 重复卡仍保留次数，用于升级合并。
    med._stage_bond_card("海盗")
    assert med._bond_cards_pending == ["白赚海盗", "海盗"]
