from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

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
from shuabao.vision.capture import Frame


def load_fixture_f0118() -> Frame:
    path = ROOT / "fixtures" / "solo_round4_20260925" / "f0118.png"
    bgr = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert bgr is not None, f"Failed to load fixture {path}"
    return Frame(bgr, window_title="英雄三国KK", hwnd=1)


def test_f0118_dasheng_chosen_over_greed_under_20260926_rule() -> None:
    """真实帧 f0118（单人第四轮第一局 02:15 Tick 108）：

    【面板四槽与识别】：
      - Slot 0: 齐天大圣（当前高级卡组首卡，品质绿/N，置信度 0.978）
      - Slot 1: 体术（非预设/不在当前推进卡组，品质蓝/R，置信度 0.651）
      - Slot 2: 贪婪（基础卡组，品质蓝/R，置信度 0.945）
      - Slot 3: 亡灵（第二组高级卡组，当前未解锁，品质绿/N，置信度 0.959）

    【已有羁绊】：
      已持有 [祝福, 经济, 成长]，贪婪尚未持有。

    【Owner 2026-09-26 新规则下贪婪仍低于当前高级组】：
      1. 画面中无未入手「祝福」或「成长/经济」卡；
      2. 画面中无已持有卡需要合成：已持有祝福/经济/成长，4 槽均未持有，Step 3 不触发；
      3. 贪婪与普通卡组同级，排在当前高级卡组之后；
      4. 当前推进的高级卡组为第一组「齐天大圣」（active_adv），
         Slot 0 的「齐天大圣」在 Step 4（当前高级卡组持续推进）中被优先命中；
      5. 因此决策明确选取 Slot 0「齐天大圣」，理由为“当前高级卡组持续推进：齐天大圣 @ slot 0”。
    """
    settings = Settings(
        ocr_mode="off",
        bonds=["祝福", "成长", "经济", "贪婪"],
        cards=["齐天大圣", "大圣", "亡灵"],
    )
    med = Mediator(settings, ROOT)
    policy = med._policy_settings()

    # 1. 纯候选结构断言（与真实帧 OCR 结果逐字段对齐）
    slots = (
        SlotCandidate(index=0, name="齐天大圣", confidence=0.978, rarity="green"),
        SlotCandidate(index=1, name="体术", confidence=0.651, rarity="blue"),
        SlotCandidate(index=2, name="贪婪", confidence=0.945, rarity="blue"),
        SlotCandidate(index=3, name="亡灵", confidence=0.959, rarity="green"),
    )
    cands = PanelCandidates(
        panel_kind=PANEL_BOND,
        slots=slots,
        owned_bond_cards=("祝福", "经济", "成长"),
        can_refresh=True,
        settings=policy,
    )

    decision = choose_action(cands, SessionState())
    assert decision.action == PolicyAction.SELECT_SLOT
    assert decision.index == 0
    assert "当前高级卡组持续推进" in decision.reason
    assert "齐天大圣" in decision.reason

    # 2. 对比测试：如果画面中出现未持有的「祝福」，祝福依然享有最高优先特权
    slots_with_blessing = (
        SlotCandidate(index=0, name="齐天大圣", confidence=0.978, rarity="green"),
        SlotCandidate(index=1, name="祝福", confidence=0.950, rarity="green"),
        SlotCandidate(index=2, name="贪婪", confidence=0.945, rarity="blue"),
        SlotCandidate(index=3, name="亡灵", confidence=0.959, rarity="green"),
    )
    cands_with_blessing = PanelCandidates(
        panel_kind=PANEL_BOND,
        slots=slots_with_blessing,
        owned_bond_cards=("经济", "成长"),  # 尚未持有祝福
        can_refresh=True,
        settings=policy,
    )
    # 2a. 默认配置下（含 DEFAULT_BOND_MUST_TAKE），祝福命中必拿
    decision_blessing = choose_action(cands_with_blessing, SessionState())
    assert decision_blessing.action == PolicyAction.SELECT_SLOT
    assert decision_blessing.index == 1
    assert "祝福" in decision_blessing.reason

    # 2b. 显式去除 must_take，断言 Step 2.5 纯规则（祝福羁绊优先）触发
    from dataclasses import replace
    cands_step25 = PanelCandidates(
        panel_kind=PANEL_BOND,
        slots=slots_with_blessing,
        owned_bond_cards=("经济", "成长"),
        can_refresh=True,
        settings=replace(policy, bond_must_take=()),
    )
    decision_step25 = choose_action(cands_step25, SessionState())
    assert decision_step25.action == PolicyAction.SELECT_SLOT
    assert decision_step25.index == 1
    assert "羁绊系统必拿" in decision_step25.reason

    # 3. 真实帧 anchor 验证
    frame = load_fixture_f0118()
    anchor = med._selection_anchor(frame)
    assert anchor is not None
    assert anchor.name == "bond_hide_btn"
