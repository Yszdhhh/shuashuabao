# -*- coding: utf-8 -*-
"""S0 稳定性（去输入化）契约测试。

不变量：
- 窗口权限：仅 "KK" 是 PLATFORM（平台窗），绝不冒充 GAME；游戏标题是 GAME；
  无法识别一律 UNKNOWN（UNKNOWN → 零输入）。
- MAIN_LINE 活性看门狗：停滞 >= 15s 只置位遥测旗标/计数，零物理输入
  （严禁盲发 ESC）；推进完全交由 Core FSM。
- 面板恢复单一所有者：Runtime 侧 fail-forward / 物理面板停滞 / 未知面板
  全部只记 telemetry，不再重复注入 ESC（物理恢复由 Core CLOSING FSM 负责）。
"""

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from shuabao.mediator import Mediator as CoreMediator
from shuabao.mediator import LoopAction, PanelState, Phase
from shuabao.runtime_mediator import Mediator
from shuabao.settings import Settings
from shuabao.vision.capture import Frame, WindowRole, classify_window_role
from shuabao.vision.matcher import MatchResult

ROOT = Path(__file__).resolve().parents[2]


def _frame(title="英雄三国KK", hwnd=1):
    return Frame(np.zeros((900, 1600, 3), dtype=np.uint8), left=185, top=81, hwnd=hwnd, window_title=title)


def _hit(name="skill_hide", x=800, y=500):
    return MatchResult(name, 0.95, x, y, 20, 20, x, y)


def _runtime_med(**kwargs) -> Mediator:
    return Mediator(Settings(ocr_mode="off", **kwargs), ROOT)


def _prime_watchdog(m) -> None:
    """Force the watchdog-eligible stall precondition (telemetry-only)."""
    m.phase = Phase.MAIN_LINE
    m.settings.dry_run = False
    m.settings.pre_wave_protection = False
    m._panel_state = PanelState.CLOSED
    m._post_game_pending = False
    m._pending_action = None
    m._last_runtime_progress_at = 10.0


# ---------------------------------------------------------------------------
# Window authority: KK alone is PLATFORM, never GAME.
# ---------------------------------------------------------------------------


def test_kk_alone_is_platform_not_game():
    assert classify_window_role("KK") is WindowRole.PLATFORM
    assert classify_window_role("KK对战平台") is WindowRole.PLATFORM


def test_game_title_is_game_even_when_it_mentions_kk():
    assert classify_window_role("英雄三国KK") is WindowRole.GAME
    assert classify_window_role("魔兽争霸3") is WindowRole.GAME


def test_unrelated_title_is_unknown():
    assert classify_window_role("记事本") is WindowRole.UNKNOWN
    assert classify_window_role(None) is WindowRole.UNKNOWN
    assert classify_window_role("") is WindowRole.UNKNOWN


# ---------------------------------------------------------------------------
# Watchdog stall: >= 15s inactivity sets telemetry flag, sends ZERO ESC.
# ---------------------------------------------------------------------------


def test_watchdog_stall_after_15s_sets_stalled_flag_and_sends_zero_esc():
    m = _runtime_med()
    _prime_watchdog(m)
    with patch("shuabao.runtime_mediator.time.time", return_value=30.5), patch.object(
        m, "act_key", return_value=True
    ) as key, patch.object(m, "act_click", return_value=True) as click, patch.object(
        CoreMediator, "_tick_main_line", return_value=LoopAction.Continue
    ), patch.object(m, "_post_game_state", return_value=None), patch.object(
        m, "_is_in_game_hud", return_value=True
    ), patch.object(m, "_record_fail_closed_incident") as incident:
        # tick1 primes the two-frame HUD latch (1 < 2, not armed yet);
        # tick2 arms it and observes 20.5s stagnation >= 15s.
        first = m._tick_main_line(_frame())
        second = m._tick_main_line(_frame())

    assert first is LoopAction.Continue
    assert second is LoopAction.Continue
    assert m._runtime_watchdog_stalled is True, "15s+ stagnation must latch the stall flag"
    assert m._runtime_watchdog_stalls == 1
    assert hasattr(m, "_runtime_watchdog_first_stall_at"), "first stall timestamp recorded"
    key.assert_not_called()  # watchdog must never send blind ESC
    click.assert_not_called()
    assert incident.call_count == 1
    assert "runtime_watchdog_stall" in incident.call_args.args[0]


def test_watchdog_single_hud_frame_is_not_enough_to_stall():
    m = _runtime_med()
    _prime_watchdog(m)
    with patch("shuabao.runtime_mediator.time.time", return_value=30.5), patch.object(
        m, "act_key", return_value=True
    ) as key, patch.object(
        CoreMediator, "_tick_main_line", return_value=LoopAction.Continue
    ), patch.object(m, "_post_game_state", return_value=None), patch.object(
        m, "_is_in_game_hud", return_value=True
    ), patch.object(m, "_record_fail_closed_incident") as incident:
        m._tick_main_line(_frame())
    assert m._runtime_watchdog_stalled is False
    assert m._runtime_watchdog_stalls == 0
    key.assert_not_called()
    incident.assert_not_called()


def test_watchdog_prolonged_stall_repeats_telemetry_never_esc():
    """Stall far past the 15s threshold keeps counting telemetry and keeps
    zero physical input; escalation stays with the core fail-closed FSM."""
    m = _runtime_med()
    _prime_watchdog(m)
    with patch("shuabao.runtime_mediator.time.time", return_value=60.5), patch.object(
        m, "act_key", return_value=True
    ) as key, patch.object(m, "act_click", return_value=True) as click, patch.object(
        CoreMediator, "_tick_main_line", return_value=LoopAction.Continue
    ), patch.object(m, "_post_game_state", return_value=None), patch.object(
        m, "_is_in_game_hud", return_value=True
    ), patch.object(m, "_record_fail_closed_incident") as incident:
        for _ in range(4):
            assert m._tick_main_line(_frame()) is LoopAction.Continue
    assert m._runtime_watchdog_stalls == 3  # tick1 primes latch, ticks 2-4 stall
    assert m._runtime_watchdog_stalled is True
    key.assert_not_called()
    click.assert_not_called()
    assert incident.call_count == 3


def test_verified_input_progress_clears_stall_flag():
    m = _runtime_med()
    _prime_watchdog(m)
    m._runtime_watchdog_stalled = True
    with patch("shuabao.runtime_mediator.time.time", return_value=30.5), patch.object(
        CoreMediator, "_tick_main_line", return_value=LoopAction.Continue
    ):
        m._tick_input_executed = True
        m._tick_main_line(_frame())
    assert m._runtime_watchdog_stalled is False


# ---------------------------------------------------------------------------
# Panel recovery: Core CLOSING FSM is the single owner; Runtime sends no ESC.
# ---------------------------------------------------------------------------


def test_panel_fail_forward_is_telemetry_only_zero_input():
    m = _runtime_med()
    with patch.object(m, "act_key", return_value=True) as key, patch.object(
        m, "act_click", return_value=True
    ) as click, patch.object(m, "_record_fail_closed_incident") as incident:
        result = m._panel_fail_forward(_frame(), _hit(), 100.0)
    assert result is LoopAction.Continue
    assert m._panel_fail_forward_events == 1
    key.assert_not_called()  # fail-forward must not inject ESC
    click.assert_not_called()  # ...or close clicks
    assert incident.call_count == 1
    assert "panel_fail_forward_telemetry" in incident.call_args.args[0]


def test_physical_panel_stagnation_records_telemetry_without_recovery_input():
    m = _runtime_med()
    anchor = _hit()
    m._panel_kind = "skill"
    m._physical_panel_signature = ("skill", 1)
    m._physical_panel_first_seen_at = 1.0
    m._physical_panel_last_progress_at = 1.0
    m._physical_panel_deadline_s = 30.0
    with patch.object(m, "act_key", return_value=True) as key, patch.object(
        m, "act_click", return_value=True
    ) as click, patch.object(m, "_panel_fail_forward") as fail_forward, patch.object(
        m, "stop"
    ) as stop, patch.object(m, "_record_fail_closed_incident") as incident:
        result = m._physical_panel_watchdog(_frame(), anchor, 40.0)
    assert result is None, "watchdog must not preempt the core panel FSM"
    fail_forward.assert_not_called()  # recovery is owned by Core CLOSING FSM
    key.assert_not_called()
    click.assert_not_called()
    stop.assert_not_called()
    assert m._physical_panel_recoveries == 1
    assert incident.call_count == 1
    assert "physical_panel_stagnation_observed" in incident.call_args.args[0]


def test_unknown_panel_state_does_not_trigger_runtime_esc_or_fail_forward():
    """UNKNOWN panel far past any fail-forward deadline: zero input from the
    runtime layer; hard-deadline recovery belongs to Core _tick_panel_fsm."""
    m = _runtime_med()
    anchor = _hit()
    m._panel_state = PanelState.ACTIVE
    m._panel_kind = "skill"
    m._runtime_panel_unknown_signature = ("skill", 1)
    m._runtime_panel_unknown_since = 0.0  # armed "100s" before the tick
    with patch("shuabao.runtime_mediator.time.time", return_value=100.0), patch.object(
        m, "act_key", return_value=True
    ) as key, patch.object(m, "act_click", return_value=True) as click, patch.object(
        CoreMediator, "_tick_panel_fsm", return_value=LoopAction.Continue
    ) as core_fsm, patch.object(m, "_record_fail_closed_incident") as incident:
        result = m._tick_panel_fsm(_frame(), anchor, 100.0)
    assert result is LoopAction.Continue
    core_fsm.assert_called_once()  # core FSM stays the single recovery owner
    key.assert_not_called()
    click.assert_not_called()
    assert m._panel_fail_forward_events == 0
    incident.assert_not_called()


def test_runtime_mediator_has_no_panel_fail_forward_dispatch_from_unknown():
    """The duplicated UNKNOWN->fail-forward branch is gone: a stale unknown
    signature alone never calls _panel_fail_forward, even with esc allowed."""
    m = _runtime_med()
    anchor = _hit()
    m._panel_state = PanelState.ACTIVE
    m._panel_kind = "skill"
    m._runtime_panel_unknown_signature = ("skill", 1)
    m._runtime_panel_unknown_since = 0.0
    with patch.object(m, "_panel_fail_forward") as fail_forward, patch.object(
        m, "act_key", return_value=True
    ) as key, patch.object(
        CoreMediator, "_tick_panel_fsm", return_value=LoopAction.Continue
    ):
        m._tick_panel_fsm(_frame(), anchor, 999.0)
    fail_forward.assert_not_called()
    key.assert_not_called()


def test_runtime_watchdog_constants_unchanged():
    assert Mediator._RUNTIME_NO_PROGRESS_MAX_STALL_S == pytest.approx(15.0)
