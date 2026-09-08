from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.loop_action import LoopAction
from shuabao.mediator import Mediator as CoreMediator
from shuabao.mediator import PanelState, Phase
from shuabao.runtime_mediator import Mediator
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult


def frame() -> Frame:
    return Frame(
        np.zeros((900, 1600, 3), dtype=np.uint8),
        window_title="英雄三国KK",
        hwnd=1,
    )


def hit(name: str, x: int = 800, y: int = 500) -> MatchResult:
    return MatchResult(name, 0.95, x, y, 20, 20, x, y)


def med(**kwargs) -> Mediator:
    settings = Settings(ocr_mode="off", **kwargs)
    return Mediator(settings, ROOT)


def test_l1_cycle_traverses_duplicate_steps_by_position_and_wraps():
    m = med()
    m._l1_cycle_step = "bond"
    m._l1_cycle_index = 0
    seen = [m._l1_cycle_step]
    for _ in range(len(m._L1_CYCLE_ORDER)):
        m._advance_l1_cycle()
        seen.append(m._l1_cycle_step)
    # 20260822：evolve 提前到 equipment 之前——装备右键会异步弹十级词缀
    # 弹窗，旧顺序在弹窗渲染前点进化造成双模态冲突停机（trace 203910）。
    assert seen == [
        "bond",
        "skill",
        "bond",
        "skill",
        "treasure",
        "evolve",
        "equipment",
        "pickup",
        "merchant",
        "artifact",
        "bond",
    ]


def test_inventory_no_action_returns_none_so_equipment_can_continue():
    m = med()
    m._panel_state = PanelState.CLOSED
    m._evolve_ok_this_cycle = True
    with patch.object(m, "_black_merchant_present", return_value=False), patch.object(
        m, "_bond_bar_nonempty", return_value=False
    ), patch.object(m, "find", return_value=None):
        assert m._maybe_use_inventory_item(frame()) is None


def test_live_disables_unverified_fixed_coordinate_panel_close():
    m = med()
    assert m._hide_fallback_hit(frame(), "skill") is None


def test_evolution_refresh_is_never_reported_as_completed_pick():
    m = med()
    refresh = hit("evolution_refresh_btn", 946, 542)
    card = hit("rarity_card_orange", 933, 300)
    with patch.object(CoreMediator, "_find_evolution_choice", return_value=refresh):
        m._evolve_awaiting_hero_pick = False
        assert m._find_evolution_choice(frame()) is None
        m._evolve_awaiting_hero_pick = True
        with patch.object(m, "_rarity_choice", return_value=card):
            assert m._find_evolution_choice(frame()) is card


def test_stage_start_requires_positive_highlight_and_rearms_selection():
    m = med(stage_targets=["1-21"])
    m._stage_selected = True
    start = hit("stage_start_fallback", 1090, 817)
    with patch.object(CoreMediator, "_find_stage_start", return_value=start), patch(
        "shuabao.runtime_mediator.selected_stage_row", return_value=None
    ):
        assert m._find_stage_start(frame()) is None
    assert m._stage_selected is False


def test_inventory_uses_swallow_pill_while_merchant_strip_is_visible():
    m = med(auto_devour_dan=True)
    pill = hit("danGif", 1100, 780)
    with patch.object(m, "_black_merchant_present", return_value=True), patch.object(
        m, "_can_consume_inventory_swallow_pill", return_value=True
    ), patch.object(m, "find", return_value=pill), patch.object(
        m, "act_click", return_value=True
    ) as click:
        assert m._maybe_use_inventory_item(frame()) is LoopAction.Continue
    click.assert_called_once_with(pill, "UseInventory-swallow_pill")


def test_merchant_disabled_does_not_implicitly_refresh_or_buy_other_items():
    m = med(auto_gambling_time=0, auto_devour_dan=False)
    m._merchant_next_at = 0.0
    with patch.object(m, "_black_merchant_present", return_value=True), patch.object(
        m, "act_click", return_value=True
    ) as click:
        assert m._maybe_black_merchant(frame()) is None
    click.assert_not_called()


def test_runtime_merchant_uses_integrated_core_handler():
    m = med()
    merchant_frame = frame()
    with patch.object(CoreMediator, "_maybe_black_merchant", return_value=LoopAction.Continue) as core_merchant:
        assert m._maybe_black_merchant(merchant_frame) is LoopAction.Continue
    core_merchant.assert_called_once_with(merchant_frame)


def test_physical_panel_deadline_is_telemetry_only_never_recovers_by_input():
    """S0 收敛：物理面板停滞只做 telemetry，不派发 Fail-Forward、不发输入、不停机。"""
    m = med()
    anchor = hit("skill_refresh_btn", 850, 550)
    m._panel_kind = "skill"
    m._physical_panel_signature = ("skill", 1)
    m._physical_panel_first_seen_at = 1.0
    m._physical_panel_last_progress_at = 1.0
    m._physical_panel_deadline_s = 30.0
    with patch.object(
        m, "act_key"
    ) as key, patch.object(m, "act_click") as click, patch.object(
        m, "stop"
    ) as stop, patch.object(m, "_record_fail_closed_incident") as incident:
        result = m._physical_panel_watchdog(frame(), anchor, 40.0)
    assert result is None
    key.assert_not_called()
    click.assert_not_called()
    stop.assert_not_called()
    incident.assert_called_once()
    assert m._physical_panel_recoveries == 1
    assert m._physical_panel_last_progress_at == 40.0


def test_runtime_watchdog_is_independent_from_core_main_line_since():
    m = med()
    m.phase = Phase.MAIN_LINE
    m.settings.pre_wave_protection = False
    m.settings.dry_run = False
    m._panel_state = PanelState.CLOSED
    m._post_game_pending = False
    m._pending_action = None
    m._last_runtime_progress_at = 10.0
    m._main_line_since = 99.0
    with patch("shuabao.runtime_mediator.time.time", return_value=30.5), patch.object(
        m, "act_key", return_value=True
    ) as key, patch.object(m, "_advance_l1_cycle") as advance, patch.object(
        CoreMediator, "_tick_main_line", return_value=LoopAction.Continue
    ) as core, patch.object(m, "_post_game_state", return_value=None):
        result = m._tick_main_line(frame())
    assert result is LoopAction.Continue
    # A black/UNKNOWN frame is not HUD evidence: core arbitration still runs,
    # and the watchdog must not send a key or advance the L1 cycle.
    key.assert_not_called()
    advance.assert_not_called()
    core.assert_called_once()


def test_runtime_watchdog_requires_two_stable_hud_frames_and_never_sends_input():
    """S0 去输入化：双帧 HUD 确认 + 停滞达标只记录 telemetry，绝不发任何输入。"""
    m = med()
    m.phase = Phase.MAIN_LINE
    m.settings.pre_wave_protection = False
    m.settings.dry_run = False
    m._panel_state = PanelState.CLOSED
    m._post_game_pending = False
    m._pending_action = None
    m._last_runtime_progress_at = 10.0
    with patch("shuabao.runtime_mediator.time.time", return_value=30.5), patch.object(
        m, "act_key"
    ) as key, patch.object(m, "act_click") as click, patch.object(
        m, "_advance_l1_cycle"
    ) as advance, patch.object(
        CoreMediator, "_tick_main_line", return_value=LoopAction.Continue
    ) as core, patch.object(m, "_post_game_state", return_value=None), patch.object(
        m, "_is_in_game_hud", return_value=True
    ), patch.object(m, "_record_fail_closed_incident") as incident:
        first = m._tick_main_line(frame())
        second = m._tick_main_line(frame())

    assert first is LoopAction.Continue
    assert second is LoopAction.Continue
    key.assert_not_called()
    click.assert_not_called()
    advance.assert_not_called()
    assert core.call_count == 2
    # 30.5 - 10.0 >= 15s：停滞事件被记录为 telemetry（计数+旗标），零输入。
    assert m._runtime_watchdog_stall_episodes_total == 1
    incident.assert_called_once()


def test_runtime_watchdog_hud_latch_resets_after_interruption():
    m = med()
    m.phase = Phase.MAIN_LINE
    m.settings.pre_wave_protection = False
    m.settings.dry_run = False
    m._panel_state = PanelState.CLOSED
    m._post_game_pending = False
    m._pending_action = None
    m._last_runtime_progress_at = 10.0
    with patch("shuabao.runtime_mediator.time.time", return_value=30.5), patch.object(
        m, "act_key", return_value=True
    ) as key, patch.object(
        CoreMediator, "_tick_main_line", return_value=LoopAction.Continue
    ), patch.object(m, "_post_game_state", return_value=None), patch.object(
        m, "_is_in_game_hud", side_effect=[True, False, True]
    ):
        m._tick_main_line(frame())
        m._tick_main_line(frame())
        m._tick_main_line(frame())

    # Only one HUD frame follows the interruption, so no watchdog input.
    key.assert_not_called()
