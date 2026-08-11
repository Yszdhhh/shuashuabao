"""P1-B0 read-only post-game evidence tests.

Defends the P1-B0 invariant: verified post-game pages use only their dedicated
safe action. Optional heirloom/rift dialogs are dismissed with X/“否”; pages
without an authorized transition still fail closed.

Anchor evidence levels (from tools/analyze_post_game.py, legacy 1.3.8
templates matched against current-version full screenshots):
  victory_continue      -> continueGame  (continue button)
  archive_challenge_panel -> archiveChallenge (archive tab)
  challenge_npc_hub     -> damijing + HeroChallenge (rift NPC + hero indicator)
  heirloom_challenge_bosses -> cjbtiaozhan (heirloom dialog header)
  great_rift_confirm    -> mijingOk + ok (confirm dialog "yes" region)
"""

import json
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from gamescript.loop_action import LoopAction
from gamescript.mediator import Mediator, Phase
from gamescript.settings import Settings
from gamescript.vision.capture import Frame
from run_replay import run_replay_fixture

ENDGAME = ROOT / "fixtures" / "reborn_wow" / "endgame"


def load_fixture_frame(rel_path: str, title: str = "英雄三国KK") -> Frame:
    path = ROOT / rel_path
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    return Frame(img, window_title=title, hwnd=10001)


class P1B0PostGameTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings()
        self.med = Mediator(self.settings, ROOT)
        self.med.set_phase(Phase.MAIN_LINE, "p1b0 setup")

    # ---------- 1. Fail-Closed: no post-game page may produce input ----------

    def test_post_game_pages_fail_closed_with_zero_input(self):
        """Archive/hub/heirloom/rift pages must cause Fail-Closed stop with zero executor calls."""
        fail_closed_ids = {"archive_challenge_panel", "challenge_npc_hub"}
        for shot in sorted(ENDGAME.glob("*.png")) + sorted(ENDGAME.glob("*.jpg")):
            if shot.stem not in fail_closed_ids:
                continue
            frame = load_fixture_frame(f"fixtures/reborn_wow/endgame/{shot.name}")
            with patch.object(self.med.executor, "click") as mock_click, \
                 patch.object(self.med.executor, "right_click") as mock_right_click, \
                 patch.object(self.med.executor, "press_key") as mock_key, \
                 patch.object(self.med, "act_click") as mock_act, \
                 patch.object(self.med, "act_right_click") as mock_act_rc:
                action = self.med._tick_main_line(frame)
                self.assertEqual(action, LoopAction.Break, f"{shot.name} must Fail-Closed")
                self.assertEqual(self.med.phase, Phase.ERROR, f"{shot.name} must enter ERROR")
                self.assertFalse(self.med._running)
            mock_click.assert_not_called()
            mock_right_click.assert_not_called()
            mock_key.assert_not_called()
            mock_act.assert_not_called()
            mock_act_rc.assert_not_called()

    def test_optional_dialogs_are_safely_dismissed(self):
        cases = {
            "heirloom_challenge_bosses": "DismissHeirloomDialog",
            "great_rift_confirm": "CancelGreatRift",
        }
        for name, expected_reason in cases.items():
            with self.subTest(name=name):
                med = Mediator(Settings(), ROOT)
                med.set_phase(Phase.MAIN_LINE, "optional dialog")
                frame = load_fixture_frame(f"fixtures/replay/{name}.png")
                with patch.object(med, "act_click", return_value=True) as click:
                    action = med._tick_main_line(frame)
                self.assertEqual(action, LoopAction.Continue)
                self.assertEqual(med.phase, Phase.MAIN_LINE)
                click.assert_called_once()
                hit, reason = click.call_args.args
                self.assertEqual(reason, expected_reason)
                if name == "great_rift_confirm":
                    self.assertEqual(hit.name, "great_rift_cancel")
                    self.assertGreaterEqual(hit.x, frame.width * 0.50)
                    self.assertLessEqual(hit.x, frame.width * 0.65)

    def test_enabled_secret_realm_uses_npc_then_yes_and_verifies_hud(self):
        settings = Settings(auto_secret_realm=True)
        med = Mediator(settings, ROOT)
        med.set_phase(Phase.MAIN_LINE, "secret realm setup")
        med._post_game_pending = True
        med._victory_continue_since = time.time()

        hub = load_fixture_frame("fixtures/replay/challenge_npc_hub.png")
        with patch.object(med, "act_right_click", return_value=True) as right_click:
            action = med._tick_main_line(hub)
        self.assertEqual(action, LoopAction.Continue)
        right_click.assert_called_once()
        npc_hit, reason = right_click.call_args.args
        self.assertEqual(reason, "OpenGreatRift")
        self.assertEqual(npc_hit.name, "damijing")
        self.assertTrue(med._secret_realm_request_pending)
        self.assertTrue(med._post_game_pending)

        confirm = load_fixture_frame("fixtures/replay/great_rift_confirm.png")
        with patch.object(med, "act_click", return_value=True) as click:
            action = med._tick_main_line(confirm)
        self.assertEqual(action, LoopAction.Continue)
        click.assert_called_once()
        yes_hit, reason = click.call_args.args
        self.assertEqual(reason, "ConfirmGreatRift")
        self.assertIn(yes_hit.name, {"mijingOk", "ok"})
        self.assertIsNotNone(med._secret_realm_entering_since)
        self.assertTrue(med._post_game_pending)

        # Real 1.4.1 footage briefly shows the NPC hub again after “yes”.  It is
        # a loading transition, not authority to right-click the rift NPC twice.
        transition_at = med._secret_realm_entering_since + settings.ui_action_interval_s + 0.05
        with patch("gamescript.mediator.time.time", return_value=transition_at), \
             patch.object(med, "act_click") as transition_click, \
             patch.object(med, "act_right_click") as transition_right_click:
            action = med._tick_main_line(hub)
        self.assertEqual(action, LoopAction.Continue)
        self.assertIsNotNone(med._secret_realm_entering_since)
        transition_click.assert_not_called()
        transition_right_click.assert_not_called()

        active = load_fixture_frame("fixtures/replay/main_line_auto_on.png")
        verified_at = transition_at + 0.1
        with patch("gamescript.mediator.time.time", return_value=verified_at), \
             patch.object(med, "_post_game_state", return_value=None), \
             patch.object(med, "_is_in_game_hud", return_value=True), \
             patch.object(med, "act_click") as extra_click, \
             patch.object(med, "act_right_click") as extra_right_click:
            action = med._tick_main_line(active)
        self.assertEqual(action, LoopAction.Continue)
        self.assertTrue(med._secret_realm_active)
        self.assertFalse(med._secret_realm_request_pending)
        self.assertFalse(med._post_game_pending)
        self.assertIsNone(med._secret_realm_entering_since)
        extra_click.assert_not_called()
        extra_right_click.assert_not_called()

    def test_secret_realm_dialog_timeout_fails_closed_without_guessing(self):
        settings = Settings(auto_secret_realm=True)
        med = Mediator(settings, ROOT)
        med.set_phase(Phase.MAIN_LINE, "secret realm timeout")
        med._post_game_pending = True
        med._secret_realm_request_pending = True
        med._secret_realm_request_since = time.time() - 16.0
        frame = load_fixture_frame("fixtures/replay/main_line_auto_on.png")

        with patch.object(med, "_post_game_state", return_value=None), \
             patch.object(med, "act_click") as click, \
             patch.object(med, "act_right_click") as right_click:
            action = med._tick_main_line(frame)
        self.assertEqual(action, LoopAction.Break)
        self.assertEqual(med.phase, Phase.ERROR)
        click.assert_not_called()
        right_click.assert_not_called()

    def test_victory_page_clicks_continue_game(self):
        """The victory modal drives a ContinueGame left click (owner-authorized), not a stop."""
        frame = load_fixture_frame("fixtures/replay/victory_continue.png")
        with patch.object(self.med, "act_click", return_value=True) as mock_act, \
             patch.object(self.med.executor, "right_click") as mock_right_click:
            action = self.med._tick_main_line(frame)
            self.assertEqual(action, LoopAction.Continue)
            mock_act.assert_called_once()
            hit_arg, reason = mock_act.call_args[0]
            self.assertEqual(reason, "ContinueGame")
            self.assertIn("continueGame", hit_arg.name)
            self.assertTrue(self.med._post_game_pending)
            self.assertEqual(self.med._victory_continue_attempts, 1)
            mock_right_click.assert_not_called()

    def test_victory_continue_retry_limit_fails_closed(self):
        """3 failed continue attempts must Fail-Closed into ERROR."""
        frame = load_fixture_frame("fixtures/replay/victory_continue.png")
        self.med._victory_continue_attempts = 3
        with patch.object(self.med, "act_click") as mock_act:
            action = self.med._tick_main_line(frame)
            self.assertEqual(action, LoopAction.Break)
            self.assertEqual(self.med.phase, Phase.ERROR)
            mock_act.assert_not_called()

    def test_post_game_pending_gate_blocks_main_line_actions(self):
        """After a continue click, unrecognized frames must yield zero input (no auto-task/challenge/stage)."""
        frame = load_fixture_frame("fixtures/replay/main_line_auto_off.png")
        self.med._post_game_pending = True
        self.med._victory_continue_since = 0.0
        with patch.object(self.med.executor, "click") as mock_click, \
             patch.object(self.med.executor, "right_click") as mock_right_click, \
             patch.object(self.med, "act_click") as mock_act:
            action = self.med._tick_main_line(frame)
            self.assertEqual(action, LoopAction.Continue)
            mock_click.assert_not_called()
            mock_right_click.assert_not_called()
            mock_act.assert_not_called()

    # ---------- 2. Multi-anchor classifier ----------

    def test_classifier_maps_all_endgame_pages(self):
        cases = {
            "victory_continue": "POST_VICTORY",
            "archive_challenge_panel": "ARCHIVE_PANEL",
            "challenge_npc_hub": "NPC_HUB",
            "heirloom_challenge_bosses": "HEIRLOOM_DIALOG",
            "great_rift_confirm": "GREAT_RIFT_CONFIRM",
        }
        for name, expected in cases.items():
            frame = load_fixture_frame(f"fixtures/replay/{name}.png")
            self.assertEqual(self.med._post_game_state(frame), expected, f"{name} classifier")

    def test_classifier_no_false_positive_on_in_game_pages(self):
        """In-game pages (main line, choices, room, stage) must classify as None."""
        negatives = [
            "fixtures/replay/main_line_auto_off.png",
            "fixtures/replay/main_line_auto_on.png",
            "fixtures/replay/skill_choice_3.png",
            "fixtures/replay/skill_choice_4.jpg",
            "fixtures/replay/bond_choice_3.png",
            "fixtures/replay/treasure_choice_3.png",
            "fixtures/replay/room_waiting_host.png",
        ]
        for rel in negatives:
            frame = load_fixture_frame(rel)
            self.assertIsNone(self.med._post_game_state(frame), f"false positive on {rel}")

    # ---------- 3. Observe-only root Replay entries ----------

    def test_post_game_manifest_entries(self):
        """Root replay entries preserve their explicitly authorized actions."""
        manifest = json.loads((ROOT / "fixtures" / "manifest.json").read_text(encoding="utf-8"))
        ids = {
            "post_game_victory_continue",
            "post_game_archive_panel",
            "post_game_npc_hub",
            "post_game_heirloom_bosses",
            "post_game_great_rift_confirm",
        }
        entries = [f for f in manifest["fixtures"] if f["fixture_id"] in ids]
        self.assertEqual(len(entries), 5, "all 5 P1-B0 entries must exist in the root manifest")

        for fixture in entries:
            res = run_replay_fixture(fixture, self.med, ROOT)
            self.assertEqual(res.status, "PASS", f"{fixture['fixture_id']}: {res.notes}")
            self.assertEqual(res.forbidden_click_count, 0)
            if fixture["fixture_id"] == "post_game_victory_continue":
                self.assertEqual(res.action_name, "ContinueGame")
                self.assertEqual(res.action_kind, "left_click")
                self.assertIsNotNone(res.click_point)
            elif fixture["fixture_id"] in {"post_game_archive_panel", "post_game_npc_hub"}:
                self.assertEqual(res.action_name, "none")
                self.assertIsNone(res.click_point, f"{fixture['fixture_id']} must not produce a click")
            else:
                self.assertIn(res.action_name, {"DismissHeirloomDialog", "CancelGreatRift"})
                self.assertEqual(res.action_kind, "left_click")
                self.assertIsNotNone(res.click_point)

    # ---------- 3. Page-discriminating anchor evidence ----------

    def test_victory_page_continue_game_anchor(self):
        """The victory modal's continue button matches the legacy continueGame template.

        NOTE: scene "start" (startGameBtn+continueGame+jihuo) is ambiguous on this
        page (jihuo wins at >=0.80), so the direct template is asserted instead.
        """
        frame = load_fixture_frame("fixtures/replay/victory_continue.png")
        hit = self.med.find(frame, ["continueGame"], threshold=0.80, scales=(0.9, 1.0, 1.1))
        self.assertIsNotNone(hit, "continueGame anchor must match on victory page")
        self.assertGreaterEqual(hit.score, 0.85)

    def test_archive_panel_anchor(self):
        frame = load_fixture_frame("fixtures/replay/archive_challenge_panel.png")
        hit = self.med.find_scene(frame, "archive", threshold=0.85)
        self.assertIsNotNone(hit)
        self.assertGreaterEqual(hit.score, 0.90)

    def test_npc_hub_secret_and_hero_indicators(self):
        """The NPC hub shows the secret-realm NPC and the Hero Challenge indicator."""
        frame = load_fixture_frame("fixtures/replay/challenge_npc_hub.png")
        hit = self.med.find_scene(frame, "secret", threshold=0.85)
        self.assertIsNotNone(hit, "damijing anchor must match on NPC hub")
        self.assertGreaterEqual(hit.score, 0.90)
        hero = self.med.find(frame, ["HeroChallenge"], threshold=0.85)
        self.assertIsNotNone(hero, "HeroChallenge indicator must be visible on NPC hub")
        self.assertGreaterEqual(hero.score, 0.90)

    def test_heirloom_dialog_anchor(self):
        frame = load_fixture_frame("fixtures/replay/heirloom_challenge_bosses.png")
        hit = self.med.find_scene(frame, "boss_entry", threshold=0.85)
        self.assertIsNotNone(hit, "cjbtiaozhan anchor must match on heirloom dialog")
        self.assertGreaterEqual(hit.score, 0.95)

    def test_great_rift_confirm_ok_anchor(self):
        """The great-rift confirm dialog matches mijingOk / ok in the dialog center."""
        frame = load_fixture_frame("fixtures/replay/great_rift_confirm.png")
        hit = self.med.find_scene(frame, "ok", threshold=0.85)
        self.assertIsNotNone(hit, "ok anchor must match on great-rift confirm")
        self.assertGreaterEqual(hit.score, 0.90)
        # The confirm button sits in the dialog body, not the top-left exit area
        self.assertGreater(hit.x, frame.width * 0.30)
        self.assertGreater(hit.y, frame.height * 0.40)


    # ---------- 4. Static-frame (frozen/old) must not kill the flow ----------

    def test_static_frame_allows_recognition_and_no_timeout_kill(self):
        """A frozen/old frame (static dialog) must continue recognition instead of ERROR-stopping."""
        arr = np.random.randint(40, 200, size=(300, 500, 3), dtype=np.uint8)
        t0 = time.time() - 10.0  # old timestamps -> OLD_FRAME
        f_prev = Frame(bgr=arr.copy(), timestamp=t0, hwnd=10001, window_title="KK", is_valid=True)
        f_curr = Frame(bgr=arr.copy(), timestamp=time.time(), hwnd=10001, window_title="KK", is_valid=True)
        # identical content + >=5s gap -> FROZEN; curr timestamp fresh so not OLD
        med = Mediator(self.settings, ROOT)
        med._prev_frame = f_prev
        med.phase = Phase.BOOT
        with patch.object(med, "_tick_l0", return_value=LoopAction.Continue) as mock_tick:
            with patch.object(med, "see", return_value=f_curr):
                action = med.tick()
                self.assertEqual(action, LoopAction.Continue)
                mock_tick.assert_called_once()  # recognition ran despite frozen frame
                self.assertNotEqual(med.phase, Phase.ERROR)

    def test_black_frame_still_blocks_and_accumulates_timeout(self):
        """Real anomalies (black frame) must still skip decision and count toward the stop timeout."""
        black = Frame(bgr=np.zeros((300, 500, 3), dtype=np.uint8), timestamp=time.time(), hwnd=10001,
                      window_title="KK", is_valid=True)
        med = Mediator(self.settings, ROOT)
        med.phase = Phase.BOOT
        with patch.object(med, "see", return_value=black), \
             patch.object(med, "_tick_l0") as mock_tick, \
             patch("gamescript.mediator.time") as mock_time:
            mock_time.time.return_value = 1000.0
            mock_time.sleep.return_value = None
            action = med.tick()
            self.assertEqual(action, LoopAction.Continue)
            mock_tick.assert_not_called()
            self.assertIsNotNone(med._missing_window_since)


if __name__ == "__main__":
    unittest.main()
