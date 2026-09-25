"""Regression tests for guest stage select recovery in hitch mode.

Reproducing three issues observed on live 2026-09-21:
1. Revocation of false-positive team-archaeology room detection on the normal
   stage select page.
2. Preventing in-game startGameBtn from falsely fulfilling Phase.QUIT room return.
3. Bounded timeout and real exit chain for host difficulty selection.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.loop_action import LoopAction
from shuabao.mediator import Mediator, Phase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult
from shuabao.vision.stage_selector import StageId, StageRow


def _game_frame() -> Frame:
    return Frame(
        np.zeros((900, 1600, 3), dtype=np.uint8),
        window_title="英雄三国KK",
        hwnd=12976826,
    )


def _platform_frame() -> Frame:
    return Frame(
        np.zeros((945, 1332, 3), dtype=np.uint8),
        window_title="KK官方对战平台",
        hwnd=658066,
    )


def _med() -> Mediator:
    return Mediator(Settings(mode_id="lobby_hitch", dry_run=True), ROOT)


class GuestStageSelectRecoveryTests(unittest.TestCase):
    def test_hitch_guest_records_confirmed_room_stage_not_hud_wave(self) -> None:
        med = _med()
        med.phase = Phase.ROOM_WAITING
        frame = _game_frame()
        selected = StageRow("2-7", StageId(2, 7), 1077, 420)

        with patch.object(med, "_host_choosing_difficulty", return_value=True), \
                patch("shuabao.mediator.selected_stage_row", return_value=selected):
            med._tick_lobby_hitch(frame, context="STAGE_SELECT", stage_page=True)

        self.assertEqual(med._hitch_pending_selected_stage, "2-7")
        self.assertEqual(med._hitch_stats_stages, {}, "选关未开局前不记为已完成关卡")
        self.assertEqual(med.game_count, 0)

    def test_verified_hitch_room_return_emits_round_brief_and_spends_two_tickets(self) -> None:
        med = _med()
        med.phase = Phase.PREPARE
        med._awaiting_room_return = True
        med._hitch_stats_started = 1
        med._hitch_stats_current_stage = "2-7"
        med._hitch_stats_stages = {"2-7": 1}
        med._ticket_balance = 130
        frame = _platform_frame()

        with patch.object(med, "_observe_ticket_balance"), \
                patch.object(med, "_detect_context", return_value="LOBBY_ROOM"), \
                patch.object(med, "_lobby_room_list_evidence", return_value=True), \
                patch.object(med, "_find_room_start", return_value=None), \
                patch("builtins.print") as printed:
            med._tick_l0(frame)

        self.assertEqual(med.game_count, 1)
        self.assertEqual(med._ticket_rounds_since_read, 1)
        self.assertEqual(med._ticket_projected_remaining(), 128)
        self.assertFalse(med._awaiting_room_return)
        self.assertEqual(med.phase, Phase.LOBBY_ROOM)
        self.assertTrue(any("本局蹭车简报：关卡 2-7" in str(call) for call in printed.call_args_list))

    def test_normal_stage_select_is_not_flagged_as_team_archaeology(self) -> None:
        """Issue 1: The '考古模式' button on the normal stage select page must not

        trigger team-archaeology room reset or blacklist the room.
        """
        med = _med()
        med.phase = Phase.ROOM_WAITING
        med._hitch_pending_room_key = "test-room-1"
        frame = _game_frame()

        kaogu_btn = MatchResult("kaogu", 0.86, 1309, 796, 114, 51, 1366, 821)
        with patch.object(med, "_archaeology_mode_anchor", return_value=kaogu_btn), \
                patch.object(med, "_host_choosing_difficulty", return_value=True):
            med._tick_lobby_hitch(frame, context="STAGE_SELECT", stage_page=True)

        # Must not have been blacklisted or reset as a team archaeology room
        self.assertNotIn("test-room-1", med._hitch_blacklisted_room_keys)
        self.assertNotEqual(med._hitch_status, "大厅主页")
        self.assertEqual(med._hitch_status, "host_choosing_difficulty")

    def test_game_client_frame_cannot_fulfill_phase_quit_room_return(self) -> None:
        """Issue 2: In Phase.QUIT, an in-game frame with startGameBtn must NOT be

        treated as having returned to the platform room.
        """
        med = _med()
        med.phase = Phase.QUIT
        frame = _game_frame()

        # In the game client, startGameBtn matches the in-game '开始游戏' button
        start_btn = MatchResult("startGameBtn", 0.994, 1035, 799, 90, 26, 1080, 812)
        quit_btn = MatchResult("quit", 0.88, 1463, 21, 75, 24, 1500, 33)

        with patch.object(med, "_find_room_start", return_value=start_btn), \
                patch.object(med, "_find_exit_confirm", return_value=None), \
                patch.object(med, "_find_game_exit", return_value=quit_btn), \
                patch.object(med, "act_click", return_value=True):
            med._tick_l1_tail(frame)

        # Must NOT switch to PREPARE (already back in room) while still in game client
        self.assertNotEqual(med.phase, Phase.PREPARE)
        # It should proceed to NEXT via quit button click
        self.assertEqual(med.phase, Phase.NEXT)

    def test_host_difficulty_selection_timeout_triggers_exit_and_blacklist(self) -> None:
        """Issue 3: When host hangs on difficulty selection past the timeout,

        guest must blacklist the room, physically exit, and wait for fresh room
        evidence without counting the aborted room as a completed round.
        """
        med = _med()
        med.phase = Phase.ROOM_WAITING
        med._hitch_pending_room_key = "afk-host-room"
        med._ticket_balance = 10
        frame = _game_frame()

        with patch.object(med, "_host_choosing_difficulty", return_value=True):
            # First tick at t=100.0: records timestamp
            med._tick_lobby_hitch(frame, context="STAGE_SELECT", stage_page=True)
            self.assertEqual(med.phase, Phase.ROOM_WAITING)
            self.assertNotIn("afk-host-room", med._hitch_blacklisted_room_keys)

            # Advance time past _HITCH_HOST_DIFFICULTY_TIMEOUT_S
            timeout = getattr(med, "_HITCH_HOST_DIFFICULTY_TIMEOUT_S", 60.0)
            now = (med._hitch_host_difficulty_since or 100.0) + timeout + 1.0
            with patch("time.time", return_value=now):
                med._tick_lobby_hitch(frame, context="STAGE_SELECT", stage_page=True)

        # Must have blacklisted the room
        self.assertIn("afk-host-room", med._hitch_blacklisted_room_keys)
        # Must transition to Phase.QUIT for real physical exit
        self.assertEqual(med.phase, Phase.QUIT)

        quit_btn = MatchResult("quit", 0.88, 1463, 21, 75, 24, 1500, 33)
        confirm_btn = MatchResult("exit_confirm_btn", 0.91, 690, 490, 100, 60, 740, 520)
        room_start = MatchResult("startGameBtn", 0.95, 980, 760, 140, 50, 1050, 785)

        # QUIT must send the physical exit-button click.
        with patch.object(med, "_find_room_start", return_value=None), \
                patch.object(med, "_find_exit_confirm", return_value=None), \
                patch.object(med, "_find_game_exit", return_value=quit_btn), \
                patch.object(med, "act_click", return_value=True) as click:
            med._tick_l1_tail(frame)
        click.assert_called_once_with(quit_btn, "QuitGame-open-confirm")
        self.assertEqual(med.phase, Phase.NEXT)

        # Confirmation is another physical click, but it is not yet proof that
        # the client actually returned to the room.
        with patch.object(med, "_find_room_start", return_value=None), \
                patch.object(med, "_find_exit_confirm", return_value=confirm_btn), \
                patch.object(med, "act_click", return_value=True) as click:
            med._tick_l1_tail(frame)
        click.assert_called_once_with(confirm_btn, "QuitGame-confirm")
        self.assertEqual(med.phase, Phase.NEXT)
        self.assertEqual(med.game_count, 0)
        self.assertEqual(med._ticket_rounds_since_read, 0)

        # Only a later platform-room frame completes the abort transaction.
        with patch.object(med, "_find_room_start", return_value=room_start):
            med._tick_l1_tail(_platform_frame())
        self.assertEqual(med.phase, Phase.LOBBY_ROOM)
        self.assertFalse(med._hitch_unstarted_exit_pending)
        self.assertEqual(med.game_count, 0)
        self.assertEqual(med._ticket_rounds_since_read, 0)

    def test_host_difficulty_without_exit_button_uses_semantic_escape(self) -> None:
        """The known guest waiting page must not fall through to UNKNOWN timeout."""
        med = _med()
        med._hitch_unstarted_exit_pending = True
        med.set_phase(Phase.QUIT, "hitch host difficulty timeout")
        with patch.object(med, "_find_exit_confirm", return_value=None), \
                patch.object(med, "_find_game_exit", return_value=None), \
                patch.object(med, "_find_stage_page", return_value=False), \
                patch.object(med, "_host_choosing_difficulty", return_value=True), \
                patch.object(med, "act_key", return_value=True) as key:
            med._tick_l1_tail(_game_frame())

        key.assert_called_once_with("esc", "HitchLeaveHostDifficulty")
        self.assertEqual(med.phase, Phase.NEXT)

    def test_hitch_quit_landing_on_difficulty_page_escapes_once_and_returns(self) -> None:
        """QUIT 阶段看到选难度页（非未开局退房）也发一次 Esc，回到房间后 LOBBY_ROOM。"""
        med = _med()
        self.assertFalse(med._hitch_unstarted_exit_pending)
        med.set_phase(Phase.QUIT, "hitch round finished")
        with patch.object(med, "_find_exit_confirm", return_value=None), \
                patch.object(med, "_find_game_exit", return_value=None), \
                patch.object(med, "_find_stage_page", return_value=False), \
                patch.object(med, "_host_choosing_difficulty", return_value=True), \
                patch.object(med, "act_key", return_value=True) as key:
            med._tick_l1_tail(_game_frame())
            med._tick_l1_tail(_game_frame())

        key.assert_called_once_with("esc", "HitchLeaveHostDifficulty")
        self.assertEqual(med.phase, Phase.NEXT)

        room_start = MatchResult("room_start", 0.95, 980, 760, 140, 50, 1050, 785)
        with patch.object(med, "_find_room_start", return_value=room_start):
            med._tick_l1_tail(_platform_frame())
        self.assertEqual(med.phase, Phase.LOBBY_ROOM)

    def test_host_chooser_loading_transition_times_out_and_recovers(self) -> None:
        """A chooser that moved to a stuck load frame stays bounded and re-searches."""
        med = _med()
        med.phase = Phase.ROOM_WAITING
        med._hitch_pending_room_key = "stuck-load-room"
        med._hitch_host_difficulty_since = 100.0
        frame = _game_frame()
        timeout = med._HITCH_PREGAME_TRANSITION_TIMEOUT_S

        with patch.object(med, "_host_choosing_difficulty", return_value=False), \
                patch.object(med, "_is_in_game_hud", return_value=False), \
                patch.object(med, "_find_stage_page", return_value=False), \
                patch("time.time", return_value=110.0):
            med._tick_lobby_hitch(frame, context="UNKNOWN")
        self.assertEqual(med._hitch_pregame_transition_since, 110.0)
        self.assertEqual(med.phase, Phase.ROOM_WAITING)
        with patch.object(med, "act_key") as key:
            self.assertIsNone(med._tick_hitch_stall_watchdog(frame, "UNKNOWN", 200.0))
        key.assert_not_called()
        med._hitch_soft_reset(120.0)
        self.assertIsNone(med._hitch_host_difficulty_since)
        self.assertEqual(med._hitch_pregame_transition_since, 110.0)

        with patch.object(med, "_host_choosing_difficulty", return_value=False), \
                patch.object(med, "_is_in_game_hud", return_value=False), \
                patch.object(med, "_find_stage_page", return_value=False), \
                patch("time.time", return_value=111.0 + timeout):
            med._tick_lobby_hitch(frame, context="UNKNOWN")

        self.assertEqual(med.phase, Phase.QUIT)
        self.assertTrue(med._hitch_unstarted_exit_pending)
        self.assertIn("stuck-load-room", med._hitch_blacklisted_room_keys)

        with patch.object(med, "_find_room_start", return_value=None), \
                patch.object(med, "_find_exit_confirm", return_value=None), \
                patch.object(med, "_find_game_exit", return_value=None), \
                patch.object(med, "_find_stage_page", return_value=False), \
                patch.object(med, "_host_choosing_difficulty", return_value=False), \
                patch.object(med, "act_key", return_value=True) as key, \
                patch("time.time", return_value=112.0 + timeout):
            med._tick_l1_tail(frame)
        key.assert_called_once_with("esc", "HitchLeavePreGameTransition")
        self.assertEqual(med.phase, Phase.NEXT)

        room_start = MatchResult("room_start", 0.95, 980, 760, 140, 50, 1050, 785)
        with patch.object(med, "_find_room_start", return_value=room_start):
            med._tick_l1_tail(_platform_frame())
        self.assertEqual(med.phase, Phase.LOBBY_ROOM)
        self.assertFalse(med._hitch_unstarted_exit_pending)
        self.assertEqual(med.game_count, 0)
        self.assertEqual(med._ticket_rounds_since_read, 0)

    def test_host_difficulty_abort_re_searches_even_when_arch_configured(self) -> None:
        """An aborted pre-game room is not counted and does not end the hitch cycle.

        Owner 2026-09-22: one slow host must not cut a 30-round run short;
        archaeology stays reserved for cycle_num / ticket budget endings.
        """
        med = Mediator(
            Settings(mode_id="lobby_hitch", hitch_after_goal="arch", dry_run=True), ROOT
        )
        med._hitch_unstarted_exit_pending = True
        med.set_phase(Phase.NEXT, "host difficulty exit requested")

        room_start = MatchResult("room_start", 0.95, 980, 760, 140, 50, 1050, 785)
        with patch.object(med, "_find_room_start", return_value=room_start):
            med._tick_l1_tail(_platform_frame())

        self.assertEqual(med.game_count, 0)
        self.assertEqual(med.settings.mode_id, "lobby_hitch")
        self.assertFalse(getattr(med, "_archaeology_handoff_pending", False))
        self.assertEqual(med.phase, Phase.LOBBY_ROOM)

    def test_team_archaeology_before_goal_is_rejected_without_counting_round(self) -> None:
        """Joining archaeology early must leave this room and keep hitching."""
        med = Mediator(
            Settings(mode_id="lobby_hitch", hitch_after_goal="arch", cycle_num=20, dry_run=True), ROOT
        )
        med.phase = Phase.ROOM_WAITING
        med._hitch_pending_room_key = "team-archaeology-room"
        med.game_count = 3
        frame = _game_frame()
        anchor = MatchResult("kaoguMode", 0.922, 755, 6, 100, 30, 805, 21)

        with patch.object(med, "_is_game_client_frame", return_value=True), \
                patch.object(med, "_archaeology_mode_anchor", return_value=anchor):
            med._tick_lobby_hitch(frame, context="UNKNOWN")

        self.assertEqual(med.phase, Phase.QUIT)
        self.assertIn("team-archaeology-room", med._hitch_blacklisted_room_keys)
        self.assertTrue(med._hitch_archaeology_room_pending)
        self.assertTrue(med._hitch_unstarted_exit_pending)
        self.assertEqual(med.game_count, 3)
        self.assertEqual(med._ticket_rounds_since_read, 0)
        self.assertEqual(med.settings.mode_id, "lobby_hitch")
        self.assertFalse(med._archaeology_handoff_pending)

    def test_team_archaeology_at_goal_is_not_treated_as_an_early_room(self) -> None:
        med = Mediator(
            Settings(mode_id="lobby_hitch", hitch_after_goal="arch", cycle_num=20, dry_run=True), ROOT
        )
        med.phase = Phase.ROOM_WAITING
        med.game_count = 20
        anchor = MatchResult("kaoguMode", 0.922, 755, 6, 100, 30, 805, 21)

        with patch.object(med, "_is_game_client_frame", return_value=True), \
                patch.object(med, "_is_in_game_hud", return_value=True), \
                patch.object(med, "_archaeology_mode_anchor", return_value=anchor) as detect:
            med._tick_lobby_hitch(_game_frame(), context="UNKNOWN")

        detect.assert_not_called()
        self.assertEqual(med.phase, Phase.ROOM_WAITING)
        self.assertFalse(med._hitch_archaeology_room_pending)

    def test_late_archaeology_detection_rolls_back_hitch_only_stats(self) -> None:
        """An archaeology HUD cannot remain in the hitch summary if first seen late."""
        med = _med()
        med.phase = Phase.MAIN_LINE
        med._hitch_round_started_counted = True
        med._hitch_stats_started = 4
        med._hitch_stats_stages = {"2-7": 2, "3-9": 1}
        med._hitch_stats_current_stage = "3-9"
        med._hitch_stats_stage_recorded_this_round = True
        anchor = MatchResult("kaoguMode", 0.922, 755, 6, 100, 30, 805, 21)

        with patch.object(med, "_is_game_client_frame", return_value=True), \
                patch.object(med, "_archaeology_mode_anchor", return_value=anchor):
            med._tick_main_line(_game_frame())

        self.assertEqual(med.phase, Phase.QUIT)
        self.assertEqual(med._hitch_stats_started, 3)
        self.assertEqual(med._hitch_stats_stages, {"2-7": 2})
        self.assertFalse(med._hitch_round_started_counted)
        self.assertFalse(med._hitch_stats_stage_recorded_this_round)
        self.assertEqual(med.game_count, 0)
        self.assertEqual(med._ticket_rounds_since_read, 0)

    def test_archaeology_room_without_exit_button_escapes_and_researches(self) -> None:
        """The known archaeology room uses semantic Esc, then waits for room proof."""
        med = Mediator(
            Settings(mode_id="lobby_hitch", hitch_after_goal="arch", cycle_num=20, dry_run=True), ROOT
        )
        med.phase = Phase.QUIT
        med._hitch_archaeology_room_pending = True
        med._hitch_unstarted_exit_pending = True
        med._hitch_pending_room_key = "team-archaeology-room"
        med.set_phase(Phase.QUIT, "hitch reject team archaeology before goal")
        frame = _game_frame()

        with patch.object(med, "_find_exit_confirm", return_value=None), \
                patch.object(med, "_find_game_exit", return_value=None), \
                patch.object(med, "_find_stage_page", return_value=False), \
                patch.object(med, "_host_choosing_difficulty", return_value=False), \
                patch.object(med, "_is_game_client_frame", return_value=True), \
                patch.object(med, "act_key", return_value=True) as key:
            med._tick_l1_tail(frame)

        key.assert_called_once_with("esc", "HitchLeaveUnrequestedArchaeology")
        self.assertEqual(med.phase, Phase.NEXT)

        room_start = MatchResult("room_start", 0.95, 980, 760, 140, 50, 1050, 785)
        with patch.object(med, "_find_room_start", return_value=room_start):
            med._tick_l1_tail(_platform_frame())

        self.assertEqual(med.phase, Phase.LOBBY_ROOM)
        self.assertEqual(med.settings.mode_id, "lobby_hitch")
        self.assertEqual(med.game_count, 0)
        self.assertEqual(med._ticket_rounds_since_read, 0)
        self.assertFalse(med._hitch_unstarted_exit_pending)
        self.assertFalse(med._hitch_archaeology_room_pending)
        self.assertFalse(med._archaeology_handoff_pending)

    def test_hitch_unstarted_exit_budget_exhausted_gives_up_without_stop(self) -> None:
        """Early-archaeology exit budget spent: abandon room, keep hitch mission."""
        import time as _time

        med = Mediator(
            Settings(mode_id="lobby_hitch", hitch_after_goal="arch", cycle_num=20, dry_run=True), ROOT
        )
        med.phase = Phase.QUIT
        med._hitch_archaeology_room_pending = True
        med._hitch_unstarted_exit_pending = True
        med._hitch_pending_room_key = "team-archaeology-room"
        med._hitch_unstarted_exit_esc_attempts = 1
        med._exit_rearm_attempts = med._EXIT_REARM_LIMIT
        med._exit_button_attempts = 3
        med._exit_since = _time.time() - 60.0
        med.game_count = 3
        med._hitch_stats_started = 4
        frame = _game_frame()

        with patch.object(med, "_find_exit_confirm", return_value=None), \
                patch.object(med, "_find_game_exit", return_value=None), \
                patch.object(med, "_find_stage_page", return_value=False), \
                patch.object(med, "_host_choosing_difficulty", return_value=False), \
                patch.object(med, "_is_game_client_frame", return_value=True), \
                patch.object(med, "_classify_exit_surface", return_value="unknown"), \
                patch.object(med, "stop") as stop:
            result = med._tick_l1_tail(frame)

        self.assertIsNot(result, LoopAction.Break)
        self.assertEqual(med.phase, Phase.LOBBY_ROOM)
        stop.assert_not_called()
        self.assertEqual(med.game_count, 3)
        self.assertEqual(med._ticket_rounds_since_read, 0)
        self.assertEqual(med.settings.mode_id, "lobby_hitch")
        self.assertFalse(med._archaeology_handoff_pending)
        self.assertFalse(med._hitch_archaeology_room_pending)
        self.assertIn("team-archaeology-room", med._hitch_blacklisted_room_keys)

    def test_goal_reached_arch_handoff_only_at_cycle_num(self) -> None:
        """after-goal=arch fires only when cycle_num is reached."""
        med = Mediator(
            Settings(mode_id="lobby_hitch", hitch_after_goal="arch", cycle_num=2, dry_run=True), ROOT
        )
        med.set_phase(Phase.MAIN_LINE, "test")
        med._hitch_stats_started = 1
        med.game_count = 1
        with patch.object(med, "_observe_ticket_balance"), \
                patch.object(med, "_ticket_budget_allows_another_round", return_value=True):
            med._finish_hitch_round(1000.0, "one of two", already_counted=True)
        self.assertEqual(med.game_count, 1)
        self.assertEqual(med.phase, Phase.LOBBY_ROOM)
        self.assertFalse(med._archaeology_handoff_pending)

        med.game_count = 2
        med.set_phase(Phase.MAIN_LINE, "test")
        with patch.object(med, "_observe_ticket_balance"), \
                patch.object(med, "_ticket_budget_allows_another_round", return_value=True):
            med._finish_hitch_round(2000.0, "goal", already_counted=True)
        self.assertTrue(med._archaeology_handoff_pending)
        self.assertEqual(med.settings.mode_id, "normal_farm")


if __name__ == "__main__":
    unittest.main()
