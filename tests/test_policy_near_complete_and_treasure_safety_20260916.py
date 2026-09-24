"""Tests for near-complete bond gates and unknown treasure slot safety (2026-09-16)."""
import pytest

from shuabao.choice_policy import (
    PANEL_BOND,
    PANEL_TREASURE,
    PanelCandidates,
    PolicyAction,
    PolicySettings,
    SessionState,
    SlotCandidate,
    WHITELIST_HARD,
    choose_action,
)


def test_must_take_outranks_near_complete_and_low_confidence_rejected():
    """must_take 优先于 near_complete，且低置信度（< min_confidence）不放行。"""
    settings = PolicySettings(
        bond_must_take=("海盗",),
        bond_presets=("智力", "海盗"),
        min_confidence=0.80,
    )
    # Slot 0: 智力(3/4) 差一张合成，但置信度仅 0.45 (< 0.80)
    # Slot 1: 海盗 0.99，为 must_take 目标
    cands = PanelCandidates(
        panel_kind=PANEL_BOND,
        slots=(
            SlotCandidate(index=0, name="智力(3/4)", confidence=0.45),
            SlotCandidate(index=1, name="海盗", confidence=0.99),
        ),
        owned_bond_cards=("智力",),
        can_refresh=True,
        settings=settings,
    )
    dec = choose_action(cands, SessionState())
    assert dec.action == PolicyAction.SELECT_SLOT
    assert dec.index == 1
    assert "羁绊系统必拿" in dec.reason


def test_near_complete_respects_capacity_and_owned_merge_when_full():
    """满槽 free_slots == 0：非预设、未持有的 near-complete 禁止拿取；
    已持有同卡合并允许；预设核心卡允许（7751495，满槽后由顶替流程腾位）。"""
    settings = PolicySettings(
        bond_presets=("智力", "力量"),
        min_confidence=0.80,
    )

    # 1. 非预设、未持有的“敏捷(3/4)”：禁止拿取，转为刷新或安全关闭
    cands_unowned = PanelCandidates(
        panel_kind=PANEL_BOND,
        slots=(
            SlotCandidate(index=0, name="敏捷(3/4)", confidence=0.95),
        ),
        owned_bond_cards=("智力",),
        free_slots=0,
        can_refresh=False,
        settings=settings,
    )
    dec_unowned = choose_action(cands_unowned, SessionState())
    assert dec_unowned.action == PolicyAction.CLOSE

    # 2. 已持有的“智力(2/3)”：合法同卡升级合并，允许拿取
    cands_owned = PanelCandidates(
        panel_kind=PANEL_BOND,
        slots=(
            SlotCandidate(index=0, name="智力(2/3)", confidence=0.95),
        ),
        owned_bond_cards=("智力",),
        free_slots=0,
        can_refresh=False,
        settings=settings,
    )
    dec_owned = choose_action(cands_owned, SessionState())
    assert dec_owned.action == PolicyAction.SELECT_SLOT
    assert dec_owned.index == 0

    # 3. 预设核心卡“力量(3/4)”：满槽也允许（Owner 7751495）
    cands_core = PanelCandidates(
        panel_kind=PANEL_BOND,
        slots=(
            SlotCandidate(index=0, name="力量(3/4)", confidence=0.95),
        ),
        owned_bond_cards=("智力",),
        free_slots=0,
        can_refresh=False,
        settings=settings,
    )
    assert choose_action(cands_core, SessionState()).action == PolicyAction.SELECT_SLOT


def test_treasure_unknown_slot_forbidden_even_with_highest_rarity():
    """宝物槽位若 name 与 description 均未知，即使边框为最高品质（red），也严格禁止盲选。"""
    settings = PolicySettings(
        treasure_presets=("双倍神符",),
        quality_order=("red", "orange", "purple", "blue", "green", "white"),
        treasure_refresh_on_no_safe=True,
    )

    # Slot 0: 红色高品质，但 name 和 description 均为 None（全未知）
    # 刷新次数已用完，无安全候选应执行安全关闭，绝不可盲点 slot 0
    state = SessionState(refreshes=2, max_refreshes=2)
    cands = PanelCandidates(
        panel_kind=PANEL_TREASURE,
        slots=(
            SlotCandidate(index=0, name=None, description=None, rarity="red", confidence=0.0),
        ),
        can_refresh=False,
        settings=settings,
    )
    dec = choose_action(cands, state)
    assert dec.action == PolicyAction.CLOSE
    assert "无安全候选" in dec.reason or "卡名未读出" in dec.reason

    # 若还有刷新次数，则执行安全刷新
    state_refreshable = SessionState(refreshes=0, max_refreshes=2)
    cands_refreshable = PanelCandidates(
        panel_kind=PANEL_TREASURE,
        slots=(
            SlotCandidate(index=0, name=None, description=None, rarity="red", confidence=0.0),
        ),
        can_refresh=True,
        settings=settings,
    )
    dec_ref = choose_action(cands_refreshable, state_refreshable)
    assert dec_ref.action == PolicyAction.REFRESH
