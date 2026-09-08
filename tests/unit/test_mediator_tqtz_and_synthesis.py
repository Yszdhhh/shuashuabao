"""Unit tests for newly added tqtz early challenge, 5-5 auto close main line, and bond synthesis priority."""

import pytest
from pathlib import Path
from shuabao.choice_policy import (
    choose_action,
    PanelCandidates,
    SlotCandidate,
    SessionState,
    PolicyAction,
    assemble_policy_settings,
    PANEL_BOND,
    PANEL_TREASURE,
)
from shuabao.settings import Settings
from shuabao.mediator import Mediator, LoopAction
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult


def test_bond_synthesis_priority_over_refresh():
    """已持有的羁绊卡（即使不在 bond_must_take 预设中）在面板出现时必须直接秒选合成，严禁刷新。"""
    settings = assemble_policy_settings(
        settings=Settings(bond_must_take=["祝福"], bond_whitelist_mode="soft"),
        skill_labels={},
        fetter_labels={},
        policy_doc={},
    )
    # 模拟手牌已有 1 张修仙（进度 1/3）
    slots = (
        SlotCandidate(index=0, name="修仙", rarity="orange", confidence=0.90),
        SlotCandidate(index=1, name="体术", rarity="green", confidence=0.85),
        SlotCandidate(index=2, name="敏捷", rarity="white", confidence=0.80),
    )
    cands = PanelCandidates(
        panel_kind=PANEL_BOND,
        slots=slots,
        set_progress=None,
        refresh_count=0,
        has_giveup=False,
        can_refresh=True,
        owned_skill_cards=(),
        owned_bond_cards=("修仙",),
        settings=settings,
    )
    session = SessionState()
    dec = choose_action(cands, session)
    assert dec.action == PolicyAction.SELECT_SLOT
    assert dec.index == 0
    assert "羁绊已持有合成优先" in dec.reason


def test_treasure_yazhi_negative_ban_by_default():
    """压制 默认作为负面宝物被 ban，选择时被过滤，除非显式放行。"""
    settings = assemble_policy_settings(
        settings=Settings(),
        skill_labels={},
        fetter_labels={},
        policy_doc={},
    )
    slots = (
        SlotCandidate(index=0, name="压制", rarity="orange", confidence=0.95),
        SlotCandidate(index=1, name="全能神符", rarity="blue", confidence=0.85),
    )
    cands = PanelCandidates(
        panel_kind=PANEL_TREASURE,
        slots=slots,
        set_progress=None,
        refresh_count=0,
        has_giveup=True,
        can_refresh=False,
        owned_skill_cards=(),
        settings=settings,
    )
    session = SessionState()
    dec = choose_action(cands, session)
    # 压制被 ban，降级选 全能神符
    assert dec.action == PolicyAction.SELECT_SLOT
    assert dec.index == 1


def test_global_treasure_must_take_still_outranks_talisman():
    """普通模式保留必拿名单；蹭车的神符限定由 Mediator 单独执行。"""
    settings = assemble_policy_settings(
        settings=Settings(),
        skill_labels={},
        fetter_labels={},
        policy_doc={},
    )
    cands = PanelCandidates(
        panel_kind=PANEL_TREASURE,
        slots=(
            SlotCandidate(index=0, name="卡牌大师", rarity="orange", confidence=0.95),
            SlotCandidate(index=1, name="恢复神符", rarity="green", confidence=0.85),
        ),
        set_progress=None,
        refresh_count=0,
        has_giveup=True,
        can_refresh=False,
        owned_skill_cards=(),
        settings=settings,
    )

    dec = choose_action(cands, SessionState())

    assert dec.action == PolicyAction.SELECT_SLOT
    assert dec.index == 0
    assert "必拿" in dec.reason


def test_non_green_talisman_does_not_get_talisman_priority():
    """“神符”名称缺少绿色品质证据时，不能触发神符优先规则。"""
    settings = assemble_policy_settings(
        settings=Settings(),
        skill_labels={},
        fetter_labels={},
        policy_doc={},
    )
    cands = PanelCandidates(
        panel_kind=PANEL_TREASURE,
        slots=(
            SlotCandidate(index=0, name="奥术神符", rarity="orange", confidence=0.95),
            SlotCandidate(index=1, name="卡牌大师", rarity="blue", confidence=0.85),
        ),
        set_progress=None,
        refresh_count=0,
        has_giveup=True,
        can_refresh=False,
        owned_skill_cards=(),
        settings=settings,
    )

    dec = choose_action(cands, SessionState())

    assert dec.action == PolicyAction.SELECT_SLOT
    assert dec.index == 1


def test_treasure_yazhi_allowed_when_explicitly_checked():
    """压制 在看板中勾选允许后，可以正常作为高品质宝物被选中。"""
    settings = assemble_policy_settings(
        settings=Settings(treasure_allow_negative=["压制"]),
        skill_labels={},
        fetter_labels={},
        policy_doc={},
    )
    slots = (
        SlotCandidate(index=0, name="压制", rarity="orange", confidence=0.95),
        SlotCandidate(index=1, name="全能神符", rarity="blue", confidence=0.85),
    )
    cands = PanelCandidates(
        panel_kind=PANEL_TREASURE,
        slots=slots,
        set_progress=None,
        refresh_count=0,
        has_giveup=True,
        can_refresh=False,
        owned_skill_cards=(),
        settings=settings,
    )
    session = SessionState()
    dec = choose_action(cands, session)
    # 放行后，按品质最高选 压制
    assert dec.action == PolicyAction.SELECT_SLOT
    assert dec.index == 0
