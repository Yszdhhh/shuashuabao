# -*- coding: utf-8 -*-
"""云端审计 2026-09-14 B0/B1：恢复能力不再绑定 _passenger_mode()。

normal_farm 以前在暂停、胜利页、战后面板、退出链、秘境等可恢复 UI 异常上
Phase.ERROR + stop() 整个运行；蹭车早已改为重新武装、由监督器/战后预算/整局
截止兜底。这里逐点钉住单人（normal_farm）的新行为，并保证乘客业务规则不外溢。
另含用户 2026-09-14 定的单人传家宝收口：已获取装备或 120s；开自动秘境则进秘境。
"""
from __future__ import annotations

import contextlib
import io
import time
from pathlib import Path
from unittest.mock import patch

import numpy as np

from shuabao.mediator import LoopAction, Mediator, Phase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult

ROOT = Path(__file__).resolve().parents[1]


def _med(mode: str = "normal_farm", **kw) -> Mediator:
    med = Mediator(Settings(mode_id=mode, ocr_mode="off", **kw), ROOT)
    med.set_phase(Phase.MAIN_LINE)
    return med


def _frame() -> Frame:
    return Frame(np.zeros((900, 1600, 3), dtype=np.uint8), window_title="英雄三国KK", hwnd=10001, role="l1")


def _quiet(fn, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)


def _tick_post_game(med: Mediator, page: str | None, **patches) -> LoopAction:
    with patch.object(med, "_post_game_state", return_value=page), \
         patch.object(med, "_is_in_game_hud", return_value=False), \
         patch.object(med, "_find_stage_page", return_value=False), \
         patch.object(med, "_bag_layout", return_value=None), \
         patch.object(med, "act_click", return_value=True), \
         patch.object(med, "act_key", return_value=True), \
         patch.object(med, "act_right_click", return_value=True), \
         patch.object(med, "stop") as stop, \
         contextlib.ExitStack() as stack:
        for name, value in patches.items():
            stack.enter_context(patch.object(med, name, return_value=value))
        res = _quiet(med._tick_main_line, _frame())
    assert not stop.called, "normal_farm must not stop the whole run"
    return res


def test_recovery_predicate_covers_desktop_live_modes_only() -> None:
    for mode in ("normal_farm", "lobby_hitch", "follow_team"):
        assert _med(mode)._unattended_recovery_enabled()
    for mode in ("lab", "gambling_wood", "raid_wait"):
        assert not _med(mode)._unattended_recovery_enabled()


def test_solo_is_not_a_passenger() -> None:
    med = _med()
    assert med._unattended_recovery_enabled() and not med._passenger_mode()


def test_solo_victory_continue_budget_rearms() -> None:
    med = _med()
    med._victory_continue_attempts = 3
    assert _tick_post_game(med, "POST_VICTORY") is LoopAction.Continue
    assert med._victory_continue_attempts == 0
    assert med.phase is Phase.MAIN_LINE


def test_solo_victory_page_not_closing_rearms() -> None:
    med = _med()
    med._post_game_pending = True
    med._victory_continue_since = time.time() - 120.0
    assert _tick_post_game(med, "POST_VICTORY") is LoopAction.Continue
    assert med._post_game_pending is False
    assert med.phase is Phase.MAIN_LINE


def test_solo_archive_panel_without_victory_takes_over_post_game_chain() -> None:
    med = _med()
    assert _tick_post_game(med, "ARCHIVE_PANEL") is LoopAction.Continue
    assert med._post_game_pending is True
    assert med._post_game_route == "archive"


def test_solo_npc_hub_without_victory_takes_over_post_game_chain() -> None:
    med = _med()
    assert _tick_post_game(med, "NPC_HUB") is LoopAction.Continue
    assert med._post_game_pending is True
    assert med._post_game_route == "archive"


def test_solo_archive_close_budget_rearms() -> None:
    med = _med()
    med._post_game_pending = True
    med._post_game_route = "archive"
    med._archive_challenge_index = 99
    med._time_cave_boss_done = True
    med._post_game_close_attempts = 3
    _tick_post_game(med, "ARCHIVE_PANEL", _maybe_click_archive_challenge=None)
    assert med._post_game_close_attempts == 0
    assert med.phase is Phase.MAIN_LINE


def test_solo_heirloom_dialog_close_budget_rearms() -> None:
    med = _med()
    med._post_game_pending = True
    med._post_game_route = "archive"
    med._aux_dialog_attempts["HEIRLOOM_DIALOG"] = 3
    _tick_post_game(med, "HEIRLOOM_DIALOG")
    assert med._aux_dialog_attempts["HEIRLOOM_DIALOG"] == 0
    assert med.phase is Phase.MAIN_LINE


def test_solo_unimplemented_post_game_page_is_zero_input() -> None:
    med = _med()
    with patch.object(med, "act_click") as click:
        _tick_post_game(med, "SOME_NEW_PAGE")
    click.assert_not_called()
    assert med.phase is Phase.MAIN_LINE


def test_solo_post_game_transition_timeout_keeps_waiting() -> None:
    med = _med()
    med._post_game_pending = True
    med._post_game_route = "archive_active"
    med._victory_continue_since = time.time() - 60.0
    assert _tick_post_game(med, None) is LoopAction.Continue
    assert med.phase is Phase.MAIN_LINE


def test_solo_post_game_hard_cap_ends_round_not_run() -> None:
    med = _med()
    med._post_game_pending = True
    med._hitch_postgame_started_at = time.time() - med._HITCH_POSTGAME_HARD_CAP_S - 1
    _tick_post_game(med, "ARCHIVE_PANEL")
    assert med.phase is Phase.QUIT


def test_solo_secret_realm_npc_timeout_abandons_rift_and_quits() -> None:
    med = _med(auto_secret_realm=True)
    med._post_game_pending = True
    med._post_game_route = "secret"
    med._secret_realm_request_attempts = 3
    med._secret_realm_request_since = time.time()
    _tick_post_game(med, "NPC_HUB")
    assert med.phase is Phase.QUIT
    assert med._post_game_pending is False
    assert med._secret_realm_request_pending is False


def test_solo_exit_chain_timeouts_rearm() -> None:
    med = _med()
    med.set_phase(Phase.QUIT)
    med._exit_button_attempts = 3
    med._exit_since = time.time() - 60.0
    with patch.object(med, "stop") as stop, patch.object(med, "_find_exit_confirm", return_value=None):
        assert _quiet(med._tick_l1_tail, _frame()) is LoopAction.Continue
    stop.assert_not_called()
    assert med._exit_button_attempts == 0 and med.phase is Phase.QUIT

    med.set_phase(Phase.NEXT)
    med._exit_confirm_attempts = 3
    med._exit_since = time.time() - 60.0
    with patch.object(med, "stop") as stop:
        assert _quiet(med._tick_l1_tail, _frame()) is LoopAction.Continue
    stop.assert_not_called()
    assert med._exit_confirm_attempts == 0 and med.phase is Phase.NEXT


def test_solo_unverified_archive_entry_is_zero_input_observation() -> None:
    med = _med()
    med._post_game_pending = False
    med._round_deadline = time.time() + 5  # 局尾窗口
    archive = MatchResult("archive", 0.95, 100, 100, 50, 50, 100, 100)
    with patch.object(med, "find_scene", side_effect=lambda f, sk, **kw: archive if sk == "archive" else None), \
         patch.object(med, "act_click") as click, \
         patch.object(med, "act_key") as key, \
         patch.object(med, "act_right_click") as rclick, \
         patch.object(med, "stop") as stop:
        assert _quiet(med._tick_main_line, _frame()) is LoopAction.Continue
    click.assert_not_called(); key.assert_not_called(); rclick.assert_not_called()
    stop.assert_not_called()
    assert med.phase is Phase.MAIN_LINE


def test_lab_mode_keeps_fail_closed() -> None:
    med = _med("lab")
    med._victory_continue_attempts = 3
    with patch.object(med, "_post_game_state", return_value="POST_VICTORY"), \
         patch.object(med, "_is_in_game_hud", return_value=False), \
         patch.object(med, "stop") as stop:
        assert _quiet(med._tick_main_line, _frame()) is LoopAction.Break
    stop.assert_called_once()
    assert med.phase is Phase.ERROR


# ---- 单人传家宝收口（用户 2026-09-14）----

def _heirloom_wait(med: Mediator, waited: float) -> None:
    med._post_game_route = "boss_active"
    med._post_game_pending = False
    med._hitch_heirloom_exit_since = time.time() - waited


def test_solo_heirloom_loot_without_secret_quits_as_victory() -> None:
    med = _med()
    _heirloom_wait(med, 10.0)
    _tick_post_game(med, None, _top_bar_mode="plaza", _heirloom_loot_popup_visible=True)
    assert med.phase is Phase.QUIT
    assert med._hitch_heirloom_exit_since is None


def test_solo_heirloom_window_is_120s() -> None:
    med = _med()
    _heirloom_wait(med, 70.0)
    _tick_post_game(med, None, _top_bar_mode="plaza", _heirloom_loot_popup_visible=False)
    assert med.phase is Phase.MAIN_LINE, "60s is the passenger window, solo waits 120s"
    _heirloom_wait(med, 121.0)
    _tick_post_game(med, None, _top_bar_mode="plaza", _heirloom_loot_popup_visible=False)
    assert med.phase is Phase.QUIT


def test_solo_heirloom_loot_with_secret_arms_rift_and_waits_for_victory() -> None:
    med = _med(auto_secret_realm=True)
    _heirloom_wait(med, 10.0)
    _tick_post_game(med, None, _top_bar_mode="plaza", _heirloom_loot_popup_visible=True)
    assert med.phase is Phase.MAIN_LINE
    assert med._passenger_heirloom_for_secret is True
    assert med._hitch_heirloom_exit_since is not None


def test_solo_heirloom_timer_with_secret_arms_rift() -> None:
    med = _med(auto_secret_realm=True)
    _heirloom_wait(med, 121.0)
    _tick_post_game(med, None, _top_bar_mode="plaza", _heirloom_loot_popup_visible=False)
    assert med.phase is Phase.MAIN_LINE
    assert med._passenger_heirloom_for_secret is True


def test_solo_heirloom_secret_wait_is_bounded() -> None:
    med = _med(auto_secret_realm=True)
    _heirloom_wait(med, 241.0)
    med._passenger_heirloom_for_secret = True
    _tick_post_game(med, None, _top_bar_mode="plaza", _heirloom_loot_popup_visible=False)
    assert med.phase is Phase.QUIT
    assert med._passenger_heirloom_for_secret is False


def test_solo_heirloom_victory_continues_into_rift_with_fresh_budget() -> None:
    med = _med(auto_secret_realm=True)
    _heirloom_wait(med, 150.0)
    # First Victory was long ago: the heirloom Victory must not hit the cap.
    med._hitch_postgame_started_at = time.time() - 1000.0
    hit = MatchResult("continueGame", 0.95, 760, 560, 80, 30, 800, 575)
    with patch.object(med, "find", return_value=hit):
        _tick_post_game(med, "POST_VICTORY")
    assert med.phase is Phase.MAIN_LINE
    assert med._post_game_route == "secret"
    assert med._hitch_heirloom_exit_since is None


def test_hitch_heirloom_window_stays_60s() -> None:
    med = _med("lobby_hitch")
    assert med._heirloom_exit_window_s() == 60.0
    assert _med()._heirloom_exit_window_s() == 120.0


# ---- 无进展监督：单人只监督局内阶段 ----

def _stall(med: Mediator, phase: Phase, seconds: float, world: str) -> None:
    if med.phase != phase:
        med.set_phase(phase, "test")
    med._tick_input_executed = False
    med._liveness_last_progress_at = time.time() - seconds
    med._liveness_level_at = None
    with patch.object(med, "_hitch_observe_world", return_value=world):
        _quiet(med._hitch_liveness_supervise)


def test_solo_supervisor_soft_resets_then_leaves_stalled_post_game() -> None:
    med = _med()
    _stall(med, Phase.MAIN_LINE, 200.0, "game_postgame")
    assert med.phase is Phase.MAIN_LINE and med._liveness_level == 1
    assert med._l1_cycle_step == "bond"
    med._tick_input_executed = False
    med._liveness_level_at = time.time() - 1000.0
    with patch.object(med, "_hitch_observe_world", return_value="game_postgame"):
        _quiet(med._hitch_liveness_supervise)
    assert med.phase is Phase.QUIT


def test_solo_supervisor_ignores_lobby_phases() -> None:
    med = _med()
    _stall(med, Phase.PREPARE, 10_000.0, "kk_other")
    assert med.phase is Phase.PREPARE
    assert med._liveness_level == 0


def test_solo_supervisor_blocks_when_game_window_is_gone() -> None:
    med = _med()
    _stall(med, Phase.QUIT, 100.0, "kk_lobby")
    assert med.phase is Phase.QUIT and med._liveness_level == 1
    med._tick_input_executed = False
    med._liveness_level_at = time.time() - 1000.0
    with patch.object(med, "_hitch_observe_world", return_value="kk_lobby"), \
         patch.object(med, "stop") as stop:
        _quiet(med._hitch_liveness_supervise)
    assert med.phase is Phase.ERROR
    stop.assert_called_once()
