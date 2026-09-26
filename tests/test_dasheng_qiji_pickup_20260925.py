# -*- coding: utf-8 -*-
"""大圣「奇技」命名回归锁（2026-09-25）。

实机证据：`solo_ingame_chain_20260925_230841_870781` trace 第 186/187/195 行，
卡顶标题 OCR 为「奇技(0/3)」（0.92/0.92/0.70），但仓库大圣卡组成员写的是「奇迹」，
`matches_bond_preset` 只做原文精确/子串匹配，白名单里没有「奇技」导致面板上的
奇技从不被拿（单独出现时直接 CLOSE）。

锁：看板勾选大圣卡组（`ui-v2/src/main.ts` ADV_PACK_CARDS `dasheng` 五首卡）时，
OCR 名为「奇技」的槽位必须被选中；旧写法「奇迹/骑技」仍经词典归一到同一身份，
合成张数保持 3。
"""
from __future__ import annotations

from pathlib import Path

from shuabao.bond_capacity import stack_need
from shuabao.choice_policy import (
    PANEL_BOND,
    PanelCandidates,
    PolicyAction,
    SessionState,
    SlotCandidate,
    choose_action,
    same_bond_identity,
)
from shuabao.mediator import Mediator
from shuabao.settings import Settings
from shuabao.vision.choice_ocr import lookup_lexicon

ROOT = Path(__file__).resolve().parents[1]

DASHENG_PACK_CARDS = ["齐天大圣", "大圣", "天命人", "大圣残躯", "大圣套装"]


def _policy():
    settings = Settings(ocr_mode="off", bonds=["祝福"], attributes=[], cards=list(DASHENG_PACK_CARDS))
    return Mediator(settings, ROOT)._policy_settings()


def _decide(policy, names, *, owned=()):
    cands = PanelCandidates(
        panel_kind=PANEL_BOND,
        slots=tuple(SlotCandidate(index=i, name=name, confidence=0.92) for i, name in enumerate(names)),
        owned_bond_cards=tuple(owned),
        can_refresh=False,
        settings=policy,
        round_elapsed_s=10.0,
    )
    return choose_action(cands, SessionState())


def test_qiji_selected_when_dasheng_pack_checked() -> None:
    policy = _policy()
    assert "奇技" in tuple(policy.bond_presets)
    decision = _decide(policy, ["神兽", "奇技"], owned=("祝福",))
    assert (decision.action, decision.index) == (PolicyAction.SELECT_SLOT, 1), decision.reason
    assert "奇技" in decision.reason


def test_qiji_trace_panel_shape_shenfa_first_qiji_eligible() -> None:
    """trace tick 186 面板形状：身法按组内顺序先拿，奇技必须合法（不再 CLOSE）。"""
    policy = _policy()
    decision = _decide(policy, ["身法", "术法", "箭术", "奇技"], owned=("祝福",))
    assert decision.action == PolicyAction.SELECT_SLOT, decision.reason
    assert decision.index == 0, decision.reason


def test_qiji_legacy_spellings_share_identity_and_need() -> None:
    assert lookup_lexicon("奇技", kind="bond").canonical == "奇技"
    assert lookup_lexicon("奇迹", kind="bond").canonical == "奇技"
    assert lookup_lexicon("骑技", kind="bond").canonical == "奇技"
    assert lookup_lexicon("奇技大成", kind="bond").canonical == "奇技大成"
    assert lookup_lexicon("奇迹大成", kind="bond").canonical == "奇技大成"
    assert lookup_lexicon("骑技大成", kind="bond").canonical == "奇技大成"
    assert same_bond_identity("奇技", "奇迹")
    assert same_bond_identity("奇技大成", "奇迹大成")
    assert stack_need("奇技") == 3
    assert stack_need("奇迹") == 3
