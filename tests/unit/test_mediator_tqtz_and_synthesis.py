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
from shuabao.mediator import Mediator, LoopAction, PanelState
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


def test_dashboard_bond_whitelist_accepts_live_ocr_floor():
    """已规范化的看板白名单卡不能因 0.55 级 OCR 被刷新掉。"""
    settings = assemble_policy_settings(
        settings=Settings(cards=["tanlan"]),
        skill_labels={},
        fetter_labels={"tanlan": "贪婪"},
        policy_doc={},
    )
    dec = choose_action(
        PanelCandidates(
            panel_kind=PANEL_BOND,
            slots=(SlotCandidate(index=0, name="贪婪", confidence=0.557),),
            set_progress=None,
            refresh_count=0,
            has_giveup=False,
            can_refresh=True,
            owned_skill_cards=(),
            settings=settings,
        ),
        SessionState(),
    )
    assert (dec.action, dec.index) == (PolicyAction.SELECT_SLOT, 0)


def test_tqtz_always_arms_main_line_close_after_verified_click():
    """提前挑战已点击就是 5-5 后证据，不能被旧看板开关拦住关闭主线。"""
    med = Mediator(Settings(auto_close_main_line=False), Path("."))
    med._round_started_at = 0.0
    hit = MatchResult("tqtz", 0.90, 640, 192, 20, 20, 640, 192)
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(med, "_find_tqtz", lambda _frame: hit)
        monkeypatch.setattr(med, "_auto_task_state", lambda _frame: ("OFF", None))
        monkeypatch.setattr(med, "act_click", lambda *_args, **_kwargs: True)
        assert med._maybe_click_tqtz(Frame(None), 30.0) is LoopAction.Continue
    assert med._close_main_line_triggered is True


def test_tqtz_waits_for_open_choice_panel_instead_of_clicking_through_modal():
    """中央选择面板会吞掉提前挑战输入，必须等面板 FSM 收口再点。"""
    med = Mediator(Settings(), Path("."))
    med._panel_state = PanelState.ACTIVE
    tqtz = MatchResult("tqtz", 0.90, 640, 192, 20, 20, 640, 192)
    panel = MatchResult("skill_hide", 0.90, 700, 500, 20, 20, 700, 500)
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(med, "_selection_anchor", lambda _frame: panel)
        monkeypatch.setattr(med, "_find_tqtz", lambda _frame: tqtz)
        monkeypatch.setattr(med, "act_click", lambda *_args, **_kwargs: pytest.fail("must not click through panel"))
        assert med._maybe_click_tqtz(Frame(None), 30.0) is None


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
