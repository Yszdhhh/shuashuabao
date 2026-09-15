# -*- coding: utf-8 -*-
"""实机 2026-09-15 单人（solo_ingame_chain_20260915_000229）：前 5 分半只开 F 羁绊，
技能 G 一次没开；木材耗尽后 F 进 60s 冷却，但基础卡 80% 锁仍把目标钉在羁绊，
COOLDOWN 状态占住整个 tick —— 7 分半后整局只剩每 60s 一次 F4，技能 20+ 点没点。

另：_L1_CYCLE_ORDER 里 bond/skill 重复两次，按名字 order.index() 推进永远在
bond↔skill 之间来回，宝物/进化/装备/拾取/黑商/神器从未轮到。

Owner 规则：木材 <500 先处理技能，技能处理完再宝物/进化/物品栏/神器/黑商。
"""
from __future__ import annotations
import contextlib
import io
import json

import time
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
import pytest

from shuabao.mediator import LoopAction, Mediator, PanelState, Phase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult

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


def _frame_from_path(path: Path) -> Frame:
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None, path
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


def test_monster_selected_during_bond_cooldown_gets_f2_hero_focus() -> None:
    """选中小怪时，两个独立 HUD 帧后才以 F2 回归阵地。"""
    med = _med()
    med._round_started_at = time.time() - 900
    med._round_deadline = time.time() + 2700
    med._main_line_started_at = time.time() - 900
    med._auto_task_done = True
    med._panel_kind = "bond"
    med._panel_state = PanelState.COOLDOWN
    med._panel_cooldown_until["bond"] = time.time() + 60
    keys: list[tuple[str, str]] = []
    clock = [time.time()]

    def tick_clock() -> float:  # live ticks are ~1.5s apart; the focus check is 1s-throttled
        return clock[0]

    with patch("shuabao.mediator.time.time", side_effect=tick_clock), \
         patch("shuabao.input.keyboard_mouse.is_current_process_elevated", return_value=True), \
         patch.object(med, "act_key", side_effect=lambda key, reason, *a, **k: keys.append((key, reason)) or True), \
         patch.object(med, "act_click", return_value=True), \
         patch.object(med, "act_right_click", return_value=True), \
         patch.object(med, "_hud_wood_balance", return_value=3346):
        for name in ("monster_selected_f0408.png", "monster_selected_f0412.png",
                     "monster_selected_f0408.png", "monster_selected_f0412.png"):
            med._tick_main_line(_frame(name))
            clock[0] += 1.5
            if ("F2", "HeroFocusFallback") in keys:
                break
    assert ("F2", "HeroFocusFallback") in keys, keys


def test_bond_visit_advances_after_three_confirmed_picks() -> None:
    med = _med()
    med._round_started_at = 0.0
    med._l1_cycle_step = "bond"
    med._l1_cycle_index = 0
    med._l1_cycle_last_advance_at = 100.0
    med._l1_cycle_step_successes = 3
    med._bond_idle_until = 0.0
    clicks: list[str] = []

    with patch("shuabao.mediator.time.time", return_value=110.0), \
         patch.object(med, "_bond_step_blocked", return_value=None), \
         patch.object(med, "_bond_base_progress_pending", return_value=True), \
         patch.object(med, "act_click", side_effect=lambda _hit, reason, *a, **k: clicks.append(reason) or True):
        assert med._maybe_open_choice_panel(_frame("hud_wood_1111_f0200.png")) is LoopAction.Continue

    assert clicks == []
    assert med._l1_cycle_step == "skill"
    assert med._l1_cycle_index == 1
    assert med._l1_cycle_step_successes == 0
    assert med._bond_idle_until == 140.0, "抽干后 30s 内不得被 80% 基础羁绊锁立即拉回 F"


def test_choice_step_advances_after_thirty_seconds_without_a_pick() -> None:
    med = _med()
    med._l1_cycle_step = "skill"
    med._l1_cycle_index = 1
    med._l1_cycle_last_advance_at = 100.0
    med._l1_cycle_step_successes = 0

    with patch("shuabao.mediator.time.time", return_value=130.0), \
         patch.object(med, "_bond_step_blocked", return_value="test backoff"), \
         patch.object(med, "_bond_base_progress_pending", return_value=True), \
         patch.object(med, "act_click") as click:
        assert med._maybe_open_choice_panel(_frame("hud_wood_221_f0300.png")) is LoopAction.Continue

    click.assert_not_called()
    assert med._l1_cycle_step == "bond"
    assert med._l1_cycle_index == 2


def test_open_bond_panel_closes_and_advances_at_pick_cap() -> None:
    med = _med()
    med._round_started_at = 0.0
    med._l1_cycle_step = "bond"
    med._l1_cycle_index = 0
    med._l1_cycle_last_advance_at = 100.0
    med._l1_cycle_step_successes = 3
    med._l1_cycle_owned_panel = True
    med._l1_cycle_selected = True
    med._panel_kind = "bond"
    med._panel_state = PanelState.ACTIVE
    anchor = MatchResult("bond_hide_btn", 0.99, 20, 20, 40, 40, 40, 40)

    with patch.object(med, "_hitch_fail_close_choice_panel", return_value=False):
        assert med._tick_panel_fsm(_frame("hud_wood_1111_f0200.png"), anchor, 110.0) is LoopAction.Continue
    assert med._panel_state is PanelState.CLOSING
    assert med._panel_visit_force_advance is True
    assert med._bond_idle_until == 140.0

    med._finish_panel_episode()
    assert med._panel_state is PanelState.CLOSED
    assert med._panel_visit_force_advance is False
    assert med._l1_cycle_step == "skill"
    assert med._l1_cycle_index == 1


def test_third_run_real_frames_cover_every_l1_step_without_twenty_second_input_gap() -> None:
    """Replay 10 minutes of the third live run through production MAIN_LINE dispatch."""
    timeline = json.loads((ROOT / "tests" / "fixtures" / "solo_round2_b1_20260915" / "timeline.json").read_text(encoding="utf-8"))
    assert timeline["bundle_id"] == "solo_ingame_chain_20260915_000229_642428"
    assert timeline["frames"][-1]["at_s"] - timeline["frames"][0]["at_s"] >= 600.0
    frames = [(entry["at_s"], _frame_from_path(ROOT / entry["file"])) for entry in timeline["frames"]]

    clock = [1000.0]
    simulation_start = clock[0]
    med = _med()
    med.settings.skip_pre_wave_delay = True
    med.settings.pre_wave_protection = False
    med._auto_task_done = True
    med._round_deadline = clock[0] + 3600.0
    med._main_line_started_at = clock[0]
    med._main_line_since = clock[0]
    med._l1_cycle_last_advance_at = clock[0]
    visits: set[str] = set()
    input_times: list[float] = []

    def record_input(*_args, **_kwargs) -> bool:
        input_times.append(clock[0])
        return True

    with contextlib.ExitStack() as stack:
        stack.enter_context(patch("shuabao.mediator.time.time", side_effect=lambda: clock[0]))
        stack.enter_context(patch.object(med, "_post_game_state", return_value=None))
        stack.enter_context(patch.object(med, "_find_equipment_affix_choice", return_value=None))
        stack.enter_context(patch.object(med, "_selection_anchor", return_value=None))
        stack.enter_context(patch.object(med, "_find_stage_page", return_value=False))
        stack.enter_context(patch.object(med, "_ensure_auto_task_enabled", return_value=None))
        stack.enter_context(patch.object(med, "_ensure_challenge_buttons", return_value=None))
        stack.enter_context(patch.object(med, "_maybe_ensure_hero_panel_focus", return_value=None))
        stack.enter_context(patch.object(med, "_maybe_click_tqtz", return_value=None))
        stack.enter_context(patch.object(med, "_maybe_close_main_line_after_5_5", return_value=None))
        stack.enter_context(patch.object(med, "_maybe_clear_pressure_monsters", return_value=None))
        stack.enter_context(patch.object(med, "_handle_self_opened_compact_panel", return_value=None))
        stack.enter_context(patch.object(med, "_hud_wood_balance", return_value=1111))
        stack.enter_context(patch.object(med, "_bond_base_progress_pending", return_value=True))
        stack.enter_context(patch.object(med, "_has_evolve_button", return_value=False))
        stack.enter_context(patch.object(
            med,
            "_maybe_upgrade_equipment",
            side_effect=lambda _f: med._advance_l1_cycle("equipment") or LoopAction.Continue,
        ))
        stack.enter_context(patch.object(med, "_hud_item_bar_overflowed", return_value=False))
        stack.enter_context(patch.object(med, "_maybe_use_inventory_item", return_value=None))
        stack.enter_context(patch.object(med, "_black_merchant_present", return_value=False))
        stack.enter_context(patch.object(med, "_maybe_fire_artifacts", return_value=None))
        stack.enter_context(patch.object(med, "act_click", side_effect=record_input))
        stack.enter_context(patch.object(med, "act_key", side_effect=record_input))
        stack.enter_context(patch.object(med, "act_right_click", side_effect=record_input))
        stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        start_at = frames[0][0]
        for elapsed in np.arange(0.0, 601.5, 1.5):
            current = max((item for item in frames if item[0] - start_at <= elapsed), key=lambda item: item[0])
            visits.add(med._l1_cycle_step)
            med._tick_main_line(current[1])
            clock[0] += 1.5

    expected = {"skill", "treasure", "evolve", "equipment", "pickup", "merchant", "artifact"}
    assert expected <= visits
    assert input_times
    observed = [simulation_start, *input_times, clock[0]]
    gaps = [b - a for a, b in zip(observed, observed[1:])]
    assert max(gaps) <= 20.0
