# -*- coding: utf-8 -*-
"""P0 回归：hitch 模式下"已验证退出"后的阶段交接。

修复前缺陷：
  1. `_finish_direct_failure_exit`（RECOVER_FAILURE 路径）调用
     `_hitch_after_exit` 清空 `_recovery_state` 后不 set_phase —— 阶段停在
     RECOVER_FAILURE，下一 tick `_tick_recovery` 命中防御分支
     （"recovery state missing"）→ ERROR + stop。
  2. `_tick_l1_tail` NEXT 分支（QUIT 退出确认点击后）同样只清状态不交接 ——
     阶段停在 NEXT，确认框已消失，等待至 elapsed >= timeout →
     ERROR "exit confirmation timeout" + stop。

修复：两条路径在 `_hitch_after_exit` 之后 set_phase(Phase.LOBBY_ROOM)，
移交既有 evidence-gated 的 `_tick_lobby_hitch` L0 流程（黑帧/无证据 = 零输入）。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from shuabao.loop_action import LoopAction
from shuabao.mediator import Mediator, Phase, RecoveryKind
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult


def _hitch_mediator() -> Mediator:
    return Mediator(Settings(dry_run=True, ocr_mode="off", mode_id="lobby_hitch"), ROOT)


def _lobby_frame(seed: int = 7) -> Frame:
    """健康（非黑帧）且无可信大厅证据的合成帧：所有模板匹配均不命中。"""
    rng = np.random.default_rng(seed)
    return Frame(
        rng.integers(0, 255, (900, 1600, 3), dtype=np.uint8),
        window_title="KK官方对战平台",
        hwnd=10,
        role="l0",
    )


def _hit(name: str = "hit", x: int = 100, y: int = 100) -> MatchResult:
    return MatchResult(name=name, score=0.95, x=x, y=y, w=20, h=20, screen_x=x, screen_y=y)


def _verified_failure_exit(med: Mediator) -> None:
    """驱动生产函数走完一次已验证失败退出的 hitch 交接。"""
    med._begin_recovery(RecoveryKind.FAIL)
    assert med.phase == Phase.RECOVER_FAILURE
    rs = med._recovery_state
    assert rs is not None
    action = med._finish_direct_failure_exit(rs, 100.0)
    assert action == LoopAction.Continue


def test_hitch_verified_failure_exit_does_not_error_next_tick() -> None:
    """修复核心：验证失败退出后阶段必须离开 RECOVER_FAILURE，
    下一真实 tick 走 LOBBY_ROOM 派发，绝不进入恢复处理器的防御 ERROR/stop。"""
    med = _hitch_mediator()
    _verified_failure_exit(med)
    assert med._recovery_state is None
    assert med.phase == Phase.LOBBY_ROOM
    assert med._hitch_re_search is True

    # 真实下一 tick：LOBBY_ROOM → _tick_l0 → _tick_lobby_hitch。
    # 无大厅证据（全部 locator 桩为 None）→ 零输入 Continue，零停止。
    clicks: list[str] = []
    keys: list[str] = []
    med.see = lambda reason="": _lobby_frame()
    with patch.object(med, "stop") as stop, \
         patch.object(med, "find_scene", return_value=None), \
         patch.object(med, "find", return_value=None), \
         patch.object(med, "_lobby_room_list_evidence", return_value=False), \
         patch.object(med, "_find_hitch_room_list_tab", return_value=None), \
         patch.object(med, "act_click", side_effect=lambda hit, reason="": clicks.append(reason) or True), \
         patch.object(med, "act_key", side_effect=lambda key, reason="": keys.append(reason) or True), \
         patch.object(med, "act_search_box", side_effect=lambda hit, text, reason="": clicks.append(reason) or True):
        action = med.tick()
    assert action == LoopAction.Continue
    assert med.phase != Phase.ERROR
    stop.assert_not_called()
    assert clicks == [] and keys == []

    # 防御分支本身仍是 fail-closed 契约：RECOVER_FAILURE + 无状态 = ERROR+stop。
    # 修复前，上面那次真实退出后每一 tick 都会走到这里。
    med2 = _hitch_mediator()
    med2.phase = Phase.RECOVER_FAILURE
    med2._recovery_state = None
    with patch.object(med2, "stop") as stop2:
        assert med2._tick_recovery(_lobby_frame()) == LoopAction.Break
        assert med2.phase == Phase.ERROR
        stop2.assert_called_once()


def test_hitch_after_verified_exit_requires_fresh_lobby_evidence_before_input() -> None:
    """交接后必须先有 fresh 大厅证据才允许输入：无证据 tick 零点击零按键，
    有证据 tick 才允许搜房输入链推进。"""
    med = _hitch_mediator()
    _verified_failure_exit(med)
    frame = _lobby_frame()
    clicks: list[str] = []
    keys: list[str] = []
    boxes: list[tuple[str, str]] = []

    def rec_click(hit, reason="", *args, **kwargs):
        clicks.append(reason)
        return True

    def rec_key(key, reason="", *args, **kwargs):
        keys.append(reason)
        return True

    def rec_search(hit, text, reason="", *args, **kwargs):
        boxes.append((text, reason))
        return True

    with patch.object(med, "_lobby_room_list_evidence", return_value=False), \
         patch.object(med, "_hitch_lobby_home_visible", return_value=False), \
         patch.object(med, "find_scene", return_value=None), \
         patch.object(med, "find", return_value=None), \
         patch.object(med, "_find_hitch_room_list_tab", return_value=None), \
         patch.object(med, "_hitch_action_hit", return_value=None), \
         patch.object(med, "act_click", side_effect=rec_click), \
         patch.object(med, "act_key", side_effect=rec_key), \
         patch.object(med, "act_search_box", side_effect=rec_search):
        assert med._tick_lobby_hitch(frame, context="UNKNOWN") == LoopAction.Continue
        assert clicks == [], "无大厅证据时绝不允许点击"
        assert keys == [], "无大厅证据时绝不允许按键"
        assert boxes == [], "无大厅证据时绝不允许搜索框输入"
    cooldown_until = med._hitch_sm.next_allowed_at
    observed_at = max(cooldown_until - 5.0, 0.0)  # tick1 的真实 now

    # fresh 可信大厅列表证据出现：搜房输入链允许推进（至少发出搜索框输入）。
    def scene_only_search_icon(f, name, **kwargs):
        return _hit("lobby_search_icon", 500, 300) if name == "lobby_search_icon" else None

    with patch.object(med, "_lobby_room_list_evidence", return_value=True), \
         patch.object(med, "_hitch_lobby_home_visible", return_value=True), \
         patch.object(med, "find_scene", side_effect=scene_only_search_icon), \
         patch.object(med, "find", return_value=None), \
         patch.object(med, "_hitch_action_hit", return_value=None), \
         patch.object(med, "act_click", side_effect=rec_click), \
         patch.object(med, "act_key", side_effect=rec_key), \
         patch.object(med, "act_search_box", side_effect=rec_search), \
         patch("shuabao.mediator.time.time", return_value=observed_at + 6.0):
        assert med._tick_lobby_hitch(frame, context="UNKNOWN") == LoopAction.Continue
    assert boxes, "fresh 大厅证据出现后必须允许搜房输入（搜索框输入链推进）"
    text, reason = boxes[0]
    assert reason == "HitchSearchBox"
    assert text == med._hitch_sm.prefix
    assert med._hitch_search is not None
    assert med._hitch_search.typed_at is not None


def test_hitch_after_exit_cleanup_semantics_preserved() -> None:
    """`_hitch_after_exit` 既有清理语义不得被交接修复改变。"""
    from shuabao.lobby_hitch import SearchTransaction

    med = _hitch_mediator()
    med._hitch_re_search = False
    med._hitch_search = SearchTransaction(prefix="4", opened_at=1.0)
    med._hitch_refresh_required = False
    med._hitch_pending_row_y = 123.0
    med._hitch_floor_exit_pending = True
    med._hitch_ready_confirmed_at = 1.0
    med._hitch_ready_timeout_attempts = 3
    med._hitch_ready_timeout_deadline = 99.0
    med._round_started_at = 1.0
    med._round_deadline = 99.0
    med._outcome_recorded = True
    med._awaiting_room_return = True

    med._hitch_after_exit(100.0)

    assert med._hitch_re_search is True
    assert med._hitch_search is None
    assert med._hitch_refresh_required is True
    assert med._hitch_pending_row_y is None
    assert med._hitch_floor_exit_pending is False
    assert med._hitch_ready_confirmed_at is None
    assert med._hitch_ready_timeout_attempts == 0
    assert med._hitch_ready_timeout_deadline is None
    assert med._round_started_at is None
    assert med._round_deadline is None
    assert med._outcome_recorded is False
    assert med._awaiting_room_return is False


def test_solo_verified_failure_exit_still_goes_prepare() -> None:
    """非 hitch（独狼）路径不受影响：仍走 PREPARE + 等待回房验证。"""
    med = Mediator(Settings(dry_run=True, ocr_mode="off"), ROOT)
    assert med._hitch_enabled() is False
    _verified_failure_exit(med)
    assert med.phase == Phase.PREPARE
    assert med._awaiting_room_return is True
    assert med._recovery_state is None


def test_hitch_exit_confirm_in_next_leaves_phase_for_lobby_hitch_flow() -> None:
    """QUIT 路径修复：NEXT 阶段点击退出确认 + hitch 启用时，
    `_hitch_after_exit` 之后必须 set_phase(LOBBY_ROOM)。
    修复前阶段停在 NEXT，确认框消失 → 15s 后 "exit confirmation timeout" ERROR+stop。"""
    med = _hitch_mediator()
    med.set_phase(Phase.NEXT, "exit confirm visible")
    confirm = _hit("exit_confirm", 800, 500)
    with patch.object(med, "_find_exit_confirm", return_value=confirm), \
         patch.object(med, "act_click", return_value=True) as click, \
         patch.object(med, "stop") as stop:
        action = med._tick_l1_tail(_lobby_frame())
    assert action == LoopAction.Continue
    click.assert_called_once_with(confirm, "QuitGame-confirm") if click.call_args else click.assert_called_once()
    assert med._hitch_re_search is True
    assert med._hitch_search is None
    assert med.game_count == 1
    assert med.phase == Phase.LOBBY_ROOM
    stop.assert_not_called()


def test_hitch_misopened_stage_page_clicks_top_right_exit_before_escape() -> None:
    """A false one-floor start uses the dedicated top-right exit, then NEXT confirms."""
    med = _hitch_mediator()
    med.set_phase(Phase.QUIT, "misopened one-floor game")
    top_right_exit = _hit("quit", 1464, 52)
    with patch.object(med, "_find_exit_confirm", return_value=None), \
         patch.object(med, "_find_game_exit", return_value=top_right_exit), \
         patch.object(med, "_find_stage_page", return_value=True), \
         patch.object(med, "act_click", return_value=True) as click, \
         patch.object(med, "act_key") as key:
        action = med._tick_l1_tail(_lobby_frame())
    assert action == LoopAction.Continue
    click.assert_called_once_with(top_right_exit, "QuitGame-open-confirm")
    key.assert_not_called()
    assert med.phase == Phase.NEXT


def test_hitch_failure_exit_counts_round_and_rearms_next_round_deadline() -> None:
    med = _hitch_mediator()
    med._round_started_at = 1.0
    med._round_deadline = 2.0
    _verified_failure_exit(med)
    assert med.game_count == 1
    assert med._round_started_at is None
    assert med._round_deadline is None
    assert med._outcome_recorded is False

    with patch("shuabao.mediator.time.time", return_value=200.0):
        med.set_phase(Phase.MAIN_LINE, "next hitch round skipped stage page")
    assert med._round_started_at == 200.0
    assert med._round_deadline == 200.0 + med.settings.round_timeout_s


def test_hitch_cycle_target_stops_only_after_verified_exit() -> None:
    med = Mediator(
        Settings(dry_run=True, ocr_mode="off", mode_id="lobby_hitch", cycle_num=1, hitch_after_goal="end"),
        ROOT,
    )
    med._begin_recovery(RecoveryKind.FAIL)
    rs = med._recovery_state
    assert rs is not None
    assert med._finish_direct_failure_exit(rs, 100.0) == LoopAction.Break
    assert med.game_count == 1
    assert med.phase == Phase.COMPLETE
    assert med.stop_signal.is_set()


def test_hitch_cycle_target_solo_handoff_leaves_guest_room_before_create() -> None:
    med = Mediator(
        Settings(
            dry_run=True,
            ocr_mode="off",
            mode_id="lobby_hitch",
            cycle_num=1,
            hitch_after_goal="solo",
            auto_create_room=False,
        ),
        ROOT,
    )

    assert med._finish_hitch_round(100.0, "verified hitch exit") == LoopAction.Continue
    assert med.game_count == 1
    assert med.settings.mode_id == "normal_farm"
    assert med.settings.auto_create_room is True
    assert med.phase == Phase.ROOM_WAITING
    assert med._room_leave_pending is True
    assert not med.stop_signal.is_set()


def test_hitch_cycle_target_arch_handoff_leaves_guest_room_before_existing_archaeology_route() -> None:
    med = Mediator(
        Settings(
            dry_run=True,
            ocr_mode="off",
            mode_id="lobby_hitch",
            cycle_num=5,
            hitch_after_goal="arch",
            auto_archaeology=False,
        ),
        ROOT,
    )
    med.game_count = 4

    assert med._finish_hitch_round(100.0, "verified fifth hitch exit") == LoopAction.Continue
    assert med.game_count == 5
    assert med.settings.mode_id == "normal_farm"
    assert med.settings.auto_create_room is True
    assert med.phase == Phase.ROOM_WAITING
    assert med._room_leave_pending is True
    assert med._archaeology_handoff_pending is True
    assert med._hitch_goal_archaeology_handoff is True
    assert not med.stop_signal.is_set()

    # An explicit "结束后去考古" route is allowed even when the separate
    # ticket-exhaustion automation switch is off; the existing fresh-anchor
    # confirmation remains mandatory.
    frame = _lobby_frame()
    with patch.object(med, "find", return_value=_hit("lobby/stage_archaeology_btn")), \
         patch.object(med, "act_click", return_value=True) as click:
        assert med._maybe_switch_to_archaeology(frame) == LoopAction.Continue
    click.assert_called_once()


def test_hitch_cycle_target_reached_through_room_return_arms_archaeology() -> None:
    """The disappear-first exit path must use the same final-round handoff."""
    med = Mediator(
        Settings(
            dry_run=True,
            ocr_mode="off",
            mode_id="lobby_hitch",
            cycle_num=5,
            hitch_after_goal="arch",
        ),
        ROOT,
    )
    # The disappear-first exit path has already recorded this round before
    # the room window is reacquired.
    med.game_count = 5
    med._awaiting_room_return = True
    med.set_phase(Phase.PREPARE, "exit confirmed; verify same room")

    with patch.object(med, "_startup_state", return_value="UNKNOWN"), \
         patch.object(med, "_detect_context", return_value="ROOM_WAITING"), \
         patch.object(med, "_lobby_room_list_evidence", return_value=False), \
         patch.object(med, "_find_hitch_room_list_tab", return_value=None), \
         patch.object(med, "_find_room_start", return_value=_hit("room_start")):
        assert med._tick_l0(_lobby_frame()) == LoopAction.Continue

    assert med.game_count == 5
    assert med._room_leave_pending is True
    assert med._archaeology_handoff_pending is True
    assert med._hitch_goal_archaeology_handoff is True
    assert med.phase is Phase.ROOM_WAITING


def test_hitch_lobby_reset_does_not_count_as_completed_round() -> None:
    med = _hitch_mediator()
    assert med._hitch_reset_lobby("home", 100.0) == LoopAction.Continue
    assert med.game_count == 0


def test_hitch_kick_reset_blacklists_recorded_room() -> None:
    med = _hitch_mediator()
    med._hitch_pending_room_key = "room-kicked"
    assert med._hitch_reset_lobby("kicked", 100.0) == LoopAction.Continue
    assert "room-kicked" in med._hitch_blacklisted_room_keys
    assert med._hitch_pending_room_key is None


def test_hitch_exit_timeout_with_unknown_surface_fails_closed() -> None:
    med = _hitch_mediator()
    med.set_phase(Phase.QUIT, "timeout exit")
    med._exit_button_attempts = 3
    with patch.object(med, "_find_exit_confirm", return_value=None), \
            patch.object(med, "stop") as stop:
        assert med._tick_l1_tail(_lobby_frame()) == LoopAction.Break
    assert med.phase == Phase.ERROR
    stop.assert_called_once()


def test_hitch_unhealthy_frame_never_ends_long_running_loop() -> None:
    med = _hitch_mediator()
    med.phase = Phase.MAIN_LINE
    med.see = lambda reason="": Frame(
        np.zeros((900, 1600, 3), dtype=np.uint8),
        window_title="英雄三国KK",
        hwnd=20,
        role="l1",
    )
    with patch.object(med, "stop") as stop:
        assert med.tick() == LoopAction.Continue
    assert med.phase == Phase.MAIN_LINE
    stop.assert_not_called()
