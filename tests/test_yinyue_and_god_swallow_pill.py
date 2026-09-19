# -*- coding: utf-8 -*-
"""Unit tests for 银月之晶 (yinyue_crystal) and 神赐吞噬丹 (god_swallow_pill).

Verifies:
1. 银月之晶确认弹窗：匹配【是】按钮直接点击，或依据标题相对坐标点击【是】。
2. 银月之晶直接使用：快捷栏或背包出现立即左键消费，绝不暂存背包。
3. 神赐吞噬丹门禁：无 EX 羁绊卡时严格阻断使用（Fail-Closed）；持有 EX 卡时左键使用吞噬。
4. 神赐吞噬丹背包流转：无 EX 卡且快捷栏满溢时右键暂存背包；在背包中保护不作为装备误取出；有 EX 卡时激活使用。
"""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from shuabao.mediator import LoopAction, Mediator, PanelState
from shuabao.policy.public_bag import BagLayout
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult

ROOT = Path(__file__).resolve().parents[1]


def test_yinyue_confirm_dialog_clicks_yes_button():
    """银月之晶弹窗出现时，直接匹配并点击【是】按钮。"""
    med = Mediator(Settings(), ROOT)
    frame = Frame(bgr=np.zeros((900, 1600, 3), dtype=np.uint8))

    yes_hit = MatchResult("yinyue_confirm_yes", 0.95, 800, 500, 45, 30, 800, 500)
    med.find = lambda f, cands, **kwargs: yes_hit if "yinyue_confirm_yes" in cands else None

    clicked = []
    med.act_click = lambda hit, reason: (clicked.append((hit, reason)), True)[1]

    res = med._handle_yinyue_confirm_dialog(frame)
    assert res == LoopAction.Continue
    assert len(clicked) == 1
    assert clicked[0][1] == "YinyueConfirm-Yes"
    assert clicked[0][0].center == (800, 500)


def test_yinyue_confirm_dialog_clicks_from_title():
    """若【是】按钮暂时被遮挡但识别到标题，按相对几何偏移 (-78, +71) 点击【是】。"""
    med = Mediator(Settings(), ROOT)
    frame = Frame(bgr=np.zeros((900, 1600, 3), dtype=np.uint8))

    title_hit = MatchResult("yinyue_confirm_title", 0.95, 800, 450, 260, 25, 800, 450)
    med.find = lambda f, cands, **kwargs: title_hit if "yinyue_confirm_title" in cands else None

    clicked = []
    med.act_click = lambda hit, reason: (clicked.append((hit, reason)), True)[1]

    res = med._handle_yinyue_confirm_dialog(frame)
    assert res == LoopAction.Continue
    assert len(clicked) == 1
    assert clicked[0][1] == "YinyueConfirm-Yes-FromTitle"
    # 800 - 78 = 722, 450 + 71 = 521
    assert clicked[0][0].center == (722, 521)


def test_yinyue_crystal_direct_consumption():
    """快捷栏中存在银月之晶时，直接左键使用并进入 WAIT_YINYUE_CONFIRM。"""
    med = Mediator(Settings(), ROOT)
    frame = Frame(bgr=np.zeros((900, 1600, 3), dtype=np.uint8))

    crystal_hit = MatchResult("yinyue_crystal", 0.90, 1100, 800, 40, 40, 1100, 800)
    med.find = lambda f, cands, **kwargs: crystal_hit if "yinyue_crystal" in cands else None

    clicked = []
    med.act_click = lambda hit, reason: (clicked.append((hit, reason)), True)[1]

    res = med._maybe_use_inventory_item(frame)
    assert res == LoopAction.Continue
    assert len(clicked) == 1
    assert clicked[0][1] == "UseInventory-yinyue_crystal"
    assert med._pending_action is not None
    assert med._pending_action.kind == "WAIT_YINYUE_CONFIRM"


def test_god_swallow_pill_blocked_without_ex_card():
    """卡牌栏中不存在 EX 羁绊卡时，严禁使用神赐吞噬丹。"""
    med = Mediator(Settings(bonds=["haidao", "zhufu"]), ROOT)
    frame = Frame(bgr=np.zeros((900, 1600, 3), dtype=np.uint8))

    # 持有非 EX 卡（海盗、力量之球）
    med._bond_cards_owned = ["haidao_n_green", "力量之球", "SSR重拳先生"]
    assert not med._can_consume_god_swallow_pill(frame)

    god_pill_hit = MatchResult("god_swallow_pill", 0.92, 1100, 800, 30, 30, 1100, 800)
    med.find = lambda f, cands, **kwargs: god_pill_hit if "god_swallow_pill" in cands else None

    clicked = []
    med.act_click = lambda hit, reason: (clicked.append((hit, reason)), True)[1]

    med._maybe_use_inventory_item(frame)
    # 没有左键点击消费
    assert not any("god_swallow_pill" in reason for _, reason in clicked)


def test_god_swallow_pill_not_consumed_even_with_ex_card():
    """有 EX 羁绊卡也不再自动使用神赐吞噬丹（2026-09-19 收紧）。

    "栏里存在一张 EX 卡"只说明可能存在一个合法目标，说明不了这次会吃哪张，
    也没有可验证的消费后置——丹药图标消失、羁绊格数少一都可能只是识别丢失。
    在目标身份、消费规则与后置验证补齐前，这条路径保持关闭；恢复它需要独立
    的消费授权（见 runtime_core.contracts），而不是把这里改回 True。

    断言保持"零输入"口径：不是点了没生效，是压根没点。
    """
    med = Mediator(Settings(bonds=["haidao", "wangling"]), ROOT)
    frame = Frame(bgr=np.zeros((900, 1600, 3), dtype=np.uint8))

    # 持有 EX 兵主
    med._bond_cards_owned = ["haidao_n_green", "EX兵主"]
    med._hud_item_bar_state = lambda f: "occupied"
    assert med._can_consume_god_swallow_pill(frame) is False

    god_pill_hit = MatchResult("god_swallow_pill", 0.92, 1100, 800, 30, 30, 1100, 800)
    med.find = lambda f, cands, **kwargs: god_pill_hit if "god_swallow_pill" in cands else None

    clicked = []
    med.act_click = lambda hit, reason: (clicked.append((hit, reason)), True)[1]

    med._maybe_use_inventory_item(frame)
    assert not any("god_swallow_pill" in reason for _, reason in clicked)


def test_god_swallow_pill_stashed_when_no_ex_and_hud_overflowed():
    """快捷栏有神赐吞噬丹且无 EX 卡，当快捷栏满溢且背包打开时，右键暂存入个人背包格。"""
    med = Mediator(Settings(bonds=["haidao"]), ROOT)
    frame = Frame(bgr=np.zeros((900, 1600, 3), dtype=np.uint8))

    layout = BagLayout(origin_x=100.0, origin_y=100.0, scale=1.0)
    med._bag_layout = lambda f: layout
    med._solo_boss_is_alive = lambda f: False
    med._hud_item_bar_state = lambda f: "full"
    med._hud_item_bar_overflowed = lambda f: True
    med._bond_cards_owned = ["haidao_n_green"]  # 无 EX 卡

    center = layout.item_bar_slot_center(1)
    god_pill_hit = MatchResult("god_swallow_pill", 0.92, center[0], center[1], 30, 30, center[0], center[1])
    med.find = lambda f, cands, **kwargs: god_pill_hit if "god_swallow_pill" in cands else None

    right_clicked = []
    med.act_right_click = lambda hit, reason: (right_clicked.append((hit, reason)), True)[1]

    res = med._maybe_use_inventory_item(frame)
    assert res == LoopAction.Continue
    assert len(right_clicked) == 1
    assert "god_swallow_pill" in right_clicked[0][1]
    assert med._bag_has_god_swallow_pill is True
    assert med._solo_stash_held_source is not None
    assert med._solo_stash_held_source["action"] == "stash"


def test_god_swallow_pill_preserved_in_personal_bag():
    """个人背包内的神赐吞噬丹被妥善保留，绝不当作待穿戴装备误右键取出。"""
    med = Mediator(Settings(bonds=["haidao"]), ROOT)
    frame = Frame(bgr=np.zeros((900, 1600, 3), dtype=np.uint8))

    layout = BagLayout(origin_x=100.0, origin_y=100.0, scale=1.0)
    med._bag_layout = lambda f: layout
    med._solo_boss_is_alive = lambda f: False
    med._hud_item_bar_state = lambda f: "empty"
    med._bond_cards_owned = ["haidao_n_green"]  # 无 EX 卡

    center = layout.personal_slot_center(0, 0)
    god_pill_hit = MatchResult("god_swallow_pill", 0.92, center[0], center[1], 30, 30, center[0], center[1])
    med.find = lambda f, cands, **kwargs: god_pill_hit if "god_swallow_pill" in cands else None

    # 模拟仅 (0, 0) 格为占用，且为神赐吞噬丹
    target_rect = layout.personal_slot_rect(0, 0)
    med._bag_slot_occupied = lambda f, rect: bool(rect == target_rect)
    med._item_bar_slot_occupied = lambda f, lay, idx: False

    right_clicked = []
    med.act_right_click = lambda hit, reason: (right_clicked.append((hit, reason)), True)[1]

    med._maybe_use_inventory_item(frame)
    # 绝不能当作装备右键拿起 (EquipBagItem-0-0)
    assert not any("EquipBagItem" in reason for _, reason in right_clicked)


def test_yinyue_crystal_in_bag_direct_consumption():
    """若个人背包打开且包含银月之晶，左键直接使用消费，绝不占用背包格子。"""
    med = Mediator(Settings(), ROOT)
    frame = Frame(bgr=np.zeros((900, 1600, 3), dtype=np.uint8))

    layout = BagLayout(origin_x=100.0, origin_y=100.0, scale=1.0)
    med._bag_layout = lambda f: layout
    med._solo_boss_is_alive = lambda f: False
    med._hud_item_bar_state = lambda f: "empty"

    center = layout.personal_slot_center(1, 1)
    crystal_hit = MatchResult("yinyue_crystal", 0.95, center[0], center[1], 40, 40, center[0], center[1])
    med.find = lambda f, cands, **kwargs: crystal_hit if "yinyue_crystal" in cands and "roi" in kwargs else None

    clicked = []
    med.act_click = lambda hit, reason: (clicked.append((hit, reason)), True)[1]

    res = med._maybe_use_inventory_item(frame)
    assert res == LoopAction.Continue
    assert len(clicked) == 1
    assert clicked[0][1] == "UseInventory-yinyue_crystal"
    assert med._pending_action is not None
    assert med._pending_action.kind == "WAIT_YINYUE_CONFIRM"

