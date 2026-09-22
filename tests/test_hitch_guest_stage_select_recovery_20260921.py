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

from shuabao.mediator import Mediator, Phase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult


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

if __name__ == "__main__":
    unittest.main()
