"""S0 L1 hitch bounds: exhaustion must observe, never ERROR/stop.

Covers four L1 liveness contracts:
1. Pause-resume retry exhaustion keeps the run alive in hitch mode.
2. Unverified post-game archive entry keeps zero-input observation in hitch.
3. Time-cave Boss step has a bounded search budget and falls through to the
   archive panel close instead of hanging or stopping.
4. Archive challenge click rejection cools down, then skips to the next card.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from shuabao.loop_action import LoopAction
from shuabao.mediator import Mediator, Phase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult


def _frame() -> Frame:
    return Frame(np.zeros((900, 1600, 3), dtype=np.uint8), left=185, top=81, hwnd=1184474, window_title="英雄三国KK")


def _hitch_mediator() -> Mediator:
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    med.set_phase(Phase.MAIN_LINE, "hitch l1 bounds setup")
    med._running = True  # 模拟 live run：stop() 必须保持未被调用
    return med

class HitchPauseResumeExhaustionTests(unittest.TestCase):
    def test_hitch_pause_resume_exhausted_does_not_stop(self) -> None:
        med = _hitch_mediator()
        frame = _frame()
        continue_hit = MatchResult("pause_continue_game", 0.98, 700, 400, 200, 50, 980, 480)
        with patch.object(med, "find", return_value=continue_hit), \
                patch.object(med, "act_click", return_value=True) as click, \
                patch.object(med, "stop") as stop:
            for i in range(7):
                action = med._maybe_resume_paused(frame, float(i))
                self.assertIs(action, LoopAction.Continue)
        self.assertEqual(click.call_count, 5)
        self.assertEqual(med._pause_resume_attempts, 5)
        self.assertNotEqual(med.phase, Phase.ERROR)
        self.assertTrue(med._running)
        stop.assert_not_called()


class HitchUnverifiedArchiveTests(unittest.TestCase):
    def test_hitch_unverified_archive_does_not_stop(self) -> None:
        med = _hitch_mediator()
        med._post_game_pending = False
        med._post_game_route = "secret"
        med._victory_continue_attempts = 1  # 局尾检查窗口激活
        frame = _frame()
        archive_hit = MatchResult("archive", 0.95, 800, 300, 100, 60, 850, 330)
        with patch.object(med, "_post_game_state", return_value=None), \
                patch.object(med, "find_scene", return_value=archive_hit) as scene, \
                patch.object(med, "find", return_value=None), \
                patch.object(med, "stop") as stop, \
                patch.object(med, "_maybe_click_hitch_pressure_transfer", return_value=None), \
                patch.object(med, "_hitch_ocr_text", return_value=""), \
                patch.object(med, "_find_failure_gift", return_value=None):
            action = med._tick_main_line(frame)
        self.assertIs(action, LoopAction.Continue)
        self.assertEqual(med.phase, Phase.MAIN_LINE)
        self.assertTrue(med._running)
        stop.assert_not_called()
        scene.assert_called_once_with(frame, "archive")


class HitchMidgameTakeoverTests(unittest.TestCase):
    def test_archive_progress_strip_adopts_an_already_running_round(self) -> None:
        med = _hitch_mediator()
        frame = _frame()
        progress = MatchResult("cundangInfo", 0.95, 20, 45, 96, 20, 68, 55)

        def find(_frame, names, **_kwargs):
            return progress if names == ["cundangInfo"] else None

        with patch.object(med, "_is_in_game_hud", return_value=True), \
                patch.object(med, "_post_game_state", return_value=None), \
                patch.object(med, "find", side_effect=find):
            action = med._maybe_click_hitch_pressure_transfer(frame, 1.0)

        self.assertIs(action, LoopAction.Continue)
        self.assertTrue(med._hitch_pressure_transferred)

    def test_missing_progress_strip_keeps_pressure_gate_closed(self) -> None:
        med = _hitch_mediator()
        frame = _frame()
        with patch.object(med, "_is_in_game_hud", return_value=True), \
                patch.object(med, "_post_game_state", return_value=None), \
                patch.object(med, "find", return_value=None):
            action = med._maybe_click_hitch_pressure_transfer(frame, 1.0)

        self.assertIs(action, LoopAction.Continue)
        self.assertFalse(med._hitch_pressure_transferred)


class HitchTimeCaveBossTests(unittest.TestCase):
    def test_hitch_sgzx_boss_unseen_advances_to_archive_close(self) -> None:
        med = _hitch_mediator()
        med.settings.sgzx_boss = "55吞咽者布鲁"
        med._post_game_pending = True
        med._post_game_route = "archive"
        med._archive_challenge_index = 8  # all eight cards consumed
        med._hitch_postgame_hero_selected = True  # 跳过 F1 选英雄步
        med._time_cave_boss_done = False
        med._boss_challenge_attempts = 0
        med._time_cave_boss_search_attempts = 0
        frame = _frame()
        close_hit = MatchResult("lobby/archive_panel_close", 0.95, 1500, 100, 40, 40, 1520, 120)
        with patch.object(med, "_maybe_click_hitch_pressure_transfer", return_value=None), \
                patch.object(med, "_hitch_ocr_text", return_value=""), \
                patch.object(med, "_maybe_challenge_configured_boss", return_value=None) as boss, \
                patch.object(med, "_find_archive_panel_close", return_value=close_hit), \
                patch.object(med, "act_click", return_value=True) as act, \
                patch.object(med, "stop") as stop:
            results = [med._tick_main_line(frame) for _ in range(6)]
        for action in results:
            self.assertIs(action, LoopAction.Continue)
        self.assertNotEqual(med.phase, Phase.ERROR)
        self.assertTrue(med._running)
        stop.assert_not_called()
        # The boss step gets five observation ticks, then the budget trip
        # marks it done and hands control to the archive panel close.
        self.assertEqual(boss.call_count, 5)
        self.assertTrue(med._time_cave_boss_done)
        self.assertEqual(med._boss_challenge_attempts, 0)
        self.assertEqual(med._time_cave_boss_search_attempts, 0)
        act.assert_called_once()
        self.assertEqual(act.call_args.args[1], "CloseArchivePanel")
        self.assertEqual(med._post_game_route, "heirloom")

class HitchArchiveChallengeRejectionTests(unittest.TestCase):
    def test_hitch_archive_challenge_click_rejection_cooldown_and_skip(self) -> None:
        med = _hitch_mediator()
        med.settings.ui_action_interval_s = 1.0  # 明确冷却时长，时间线可推演
        frame = _frame()
        hit = MatchResult("skill", 0.95, 300, 200, 80, 60, 340, 230)
        with patch.object(med, "_archive_hitch_card_progress_state", return_value="AVAILABLE"), \
                patch.object(med, "_find_archive_challenge_card", return_value=hit), \
                patch.object(med, "act_click", return_value=False) as click:
            # Rejection 1 @ t=1.0: cooldown armed to 2.0, card not advanced.
            self.assertIs(med._maybe_click_archive_challenge(frame, 1.0), LoopAction.Continue)
            self.assertEqual(med._archive_challenge_click_attempts, 1)
            self.assertEqual(med._archive_challenge_index, 0)
            self.assertEqual(med._archive_challenge_next_at, 2.0)
            # t=1.5 inside cooldown: deferred, counter intact.
            self.assertIs(med._maybe_click_archive_challenge(frame, 1.5), LoopAction.Continue)
            self.assertEqual(med._archive_challenge_click_attempts, 1)
            # Rejection 2 @ t=2.1: counter increments, cooldown re-armed to 3.1.
            self.assertIs(med._maybe_click_archive_challenge(frame, 2.1), LoopAction.Continue)
            self.assertEqual(med._archive_challenge_click_attempts, 2)
            # Rejection 3 @ t=3.2: budget trips, card skipped, cursor advances.
            self.assertIs(med._maybe_click_archive_challenge(frame, 3.2), LoopAction.Continue)
            self.assertEqual(med._archive_challenge_click_attempts, 0)
            self.assertEqual(med._archive_challenge_index, 1)
            self.assertEqual(med._archive_challenge_observe_attempts, 0)
            # Next card: attempted at 4.2 (cooldown expired), rejected again.
            self.assertIs(med._maybe_click_archive_challenge(frame, 4.2), LoopAction.Continue)
            self.assertEqual(med._archive_challenge_index, 1)
            self.assertEqual(med._archive_challenge_click_attempts, 1)
        self.assertEqual(click.call_count, 4)


if __name__ == "__main__":
    unittest.main()
