# -*- coding: utf-8 -*-
"""实机 2026-09-15 单人（solo_ingame_chain_20260915_000229）：前 5 分半只开 F 羁绊，
技能 G 一次没开；木材耗尽后 F 进 60s 冷却，但基础卡 80% 锁仍把目标钉在羁绊，
COOLDOWN 状态占住整个 tick —— 7 分半后整局只剩每 60s 一次 F4，技能 20+ 点没点。

另：_L1_CYCLE_ORDER 里 bond/skill 重复两次，按名字 order.index() 推进永远在
bond↔skill 之间来回，宝物/进化/装备/拾取/黑商/神器从未轮到。

Owner 规则：木材 <500 先处理技能，技能处理完再宝物/进化/物品栏/神器/黑商。
"""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
import pytest

from shuabao.mediator import LoopAction, Mediator, PanelState, Phase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "solo_live_20260914"

OWNER = dict(
    bonds=["成长", "经济", "贪婪", "挑战", "祝福"],
    attributes=["int", "agi", "str"],
    cards=["封神", "封神榜", "打神鞭", "杏黄旗", "斩仙飞刀", "海盗", "白赚海盗", "海盗劫掠者",
           "海盗宝藏", "法术", "急速", "魔能", "暴击", "魔术"],
)


def _frame(name: str) -> Frame:
    image = cv2.imdecode(np.fromfile(str(FIX / name), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None, name
    return Frame(image, window_title="英雄三国KK", hwnd=10001, role="l1")


def _med(**kw) -> Mediator:
    med = Mediator(Settings(ocr_mode="off", **{**OWNER, **kw}), ROOT)
    med.set_phase(Phase.MAIN_LINE)
    return med


def test_cycle_reaches_every_side_step() -> None:
    med = _med()
    seen = [med._l1_cycle_step]
    for _ in range(10):
        med._advance_l1_cycle()
        seen.append(med._l1_cycle_step)
    assert seen == [
        "bond", "skill", "bond", "skill", "treasure", "evolve",
        "equipment", "pickup", "merchant", "artifact", "bond",
    ]


def _open(med: Mediator, frame: Frame, wood: int | None) -> list[str]:
    clicks: list[str] = []
    with patch.object(med, "_hud_wood_balance", return_value=wood), \
         patch.object(med, "act_click", side_effect=lambda hit, reason, *a, **k: clicks.append(reason) or True):
        for _ in range(3):
            if clicks:
                break
            med._maybe_open_choice_panel(frame, anchor=None)
    return clicks


def test_low_wood_releases_the_80_percent_bond_lock_to_skills() -> None:
    med = _med()
    assert med._bond_base_progress_pending(), "fresh round: basic bonds far below 80%"
    assert _open(med, _frame("hud_wood_221_f0300.png"), wood=221) == ["OpenSkillPanel"]


def test_enough_wood_keeps_the_bond_lock() -> None:
    med = _med()
    med._l1_cycle_step = "treasure"
    assert _open(med, _frame("hud_wood_1111_f0200.png"), wood=1111) == ["OpenBondPanel"]


def test_unreadable_wood_falls_back_to_the_idle_backoff() -> None:
    med = _med()
    med._bond_idle_until = time.time() + 20
    assert _open(med, _frame("hud_wood_1111_f0200.png"), wood=None) == ["OpenSkillPanel"]


def test_bond_long_cooldown_releases_the_lock() -> None:
    med = _med()
    med._panel_cooldown_until["bond"] = time.time() + 55
    assert _open(med, _frame("hud_wood_1111_f0200.png"), wood=None) == ["OpenSkillPanel"]


def test_bond_visit_without_a_pick_arms_the_idle_backoff() -> None:
    med = _med()
    med._panel_kind = "bond"
    med._panel_state = PanelState.COOLDOWN
    med._l1_cycle_owned_panel = True
    med._l1_cycle_selected = False
    med._finish_panel_episode()
    assert med._bond_idle_until > time.time() + 20


def test_cooldown_with_no_panel_on_screen_does_not_hold_the_tick() -> None:
    med = _med()
    med._panel_kind = "bond"
    med._panel_state = PanelState.COOLDOWN
    med._panel_cooldown_until["bond"] = time.time() + 60
    assert med._tick_panel_fsm(_frame("hud_wood_221_f0300.png"), None, time.time()) is None
    assert med._panel_state is PanelState.CLOSED
    assert med._panel_cooldown_until["bond"] > time.time() + 50, "the F reopen gate itself stays"


@pytest.mark.parametrize("name, wood", [("hud_wood_1111_f0200.png", 1111), ("hud_wood_221_f0300.png", 221)])
def test_wood_counter_ocr_on_real_frames(name: str, wood: int) -> None:
    med = Mediator(Settings(), ROOT)
    client = med._ocr_client
    if not client.start():
        pytest.skip(f"OCR worker unavailable: {client.ready_reason}")
    try:
        assert med._hud_wood_balance(_frame(name)) == wood
    finally:
        client.close()


def test_monster_selected_during_bond_cooldown_gets_f1_hero_focus() -> None:
    """实机 000229 末段：选中「龙人卫士」，英雄面板标志全无；F 冷却占住 tick，F1 恢复从未执行。"""
    med = _med()
    med._round_started_at = time.time() - 900
    med._round_deadline = time.time() + 2700
    med._main_line_started_at = time.time() - 900
    med._auto_task_done = True
    med._panel_kind = "bond"
    med._panel_state = PanelState.COOLDOWN
    med._panel_cooldown_until["bond"] = time.time() + 60
    keys: list[str] = []
    clock = [time.time()]

    def tick_clock() -> float:  # live ticks are ~1.5s apart; the focus check is 1s-throttled
        return clock[0]

    with patch("shuabao.mediator.time.time", side_effect=tick_clock), \
         patch("shuabao.input.keyboard_mouse.is_current_process_elevated", return_value=True), \
         patch.object(med, "act_key", side_effect=lambda key, reason, *a, **k: keys.append(reason) or True), \
         patch.object(med, "act_click", return_value=True), \
         patch.object(med, "act_right_click", return_value=True), \
         patch.object(med, "_hud_wood_balance", return_value=3346):
        for name in ("monster_selected_f0408.png", "monster_selected_f0412.png",
                     "monster_selected_f0408.png", "monster_selected_f0412.png"):
            med._tick_main_line(_frame(name))
            clock[0] += 1.5
            if "HeroFocusFallback" in keys:
                break
    assert "HeroFocusFallback" in keys, keys
