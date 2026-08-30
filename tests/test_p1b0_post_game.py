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

from shuabao.loop_action import LoopAction
from shuabao.mediator import Mediator, Phase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult
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
        with patch("shuabao.mediator.time.time", return_value=transition_at), \
             patch.object(med, "act_click") as transition_click, \
             patch.object(med, "act_right_click") as transition_right_click:
            action = med._tick_main_line(hub)
        self.assertEqual(action, LoopAction.Continue)
        self.assertIsNotNone(med._secret_realm_entering_since)
        transition_click.assert_not_called()
        transition_right_click.assert_not_called()

        active = load_fixture_frame("fixtures/replay/main_line_auto_on.png")
        verified_at = transition_at + 0.1
        with patch("shuabao.mediator.time.time", return_value=verified_at), \
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

    def test_new_hub_layout_without_hero_indicator_is_classified(self):
        """Real 1600x900 hub frames use the two challenge labels instead of HeroChallenge."""
        frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), hwnd=10001)

        def fake_find(_frame, names, **_kwargs):
            name = names[0]
            if name == "quit":
                return MatchResult(name, 0.90, 20, 10, 70, 24, 55, 22)
            if name == "damijing":
                return MatchResult(name, 0.97, 1140, 195, 72, 25, 1176, 207)
            if name == "HeroChallenge":
                return None
            if name == "close":
                return None
            return None

        def fake_hub_entry(_frame, route):
            x = 900 if route == "archive" else 1010
            return MatchResult(route, 0.64, x, 200, 90, 24, x + 45, 212)

        with patch.object(self.med, "find", side_effect=fake_find), \
             patch.object(self.med, "_find_post_game_hub_entry", side_effect=fake_hub_entry):
            self.assertEqual(self.med._post_game_state(frame), "NPC_HUB")

    def test_archive_panel_visits_archive_cards_before_closing(self):
        """A pending archive page starts the eight-card sequence before close."""
        med = Mediator(Settings(cjb_boss="54莫阿姆"), ROOT)
        med.set_phase(Phase.MAIN_LINE, "archive order")
        med._post_game_pending = True
        med._post_game_route = "archive"
        frame = load_fixture_frame("fixtures/replay/archive_challenge_panel.png")

        with patch.object(med, "_post_game_state", return_value="ARCHIVE_PANEL"), \
             patch.object(med, "_maybe_click_archive_challenge", return_value=LoopAction.Continue) as archive, \
             patch.object(med, "_find_archive_panel_close") as close:
            action = med._tick_main_line(frame)

        self.assertEqual(action, LoopAction.Continue)
        archive.assert_called_once()
        close.assert_not_called()

    def test_archive_card_sequence_uses_all_eight_fixture_slots(self):
        """The classified panel exposes eight stable card hitboxes in order."""
        med = Mediator(Settings(), ROOT)
        frame = load_fixture_frame("fixtures/reborn_wow/endgame/archive_challenge_panel.png")
        points = []
        for index in range(8):
            hit = med._find_archive_challenge_card(frame, index)
            self.assertIsNotNone(hit)
            points.append(hit.center)
        self.assertEqual([p[0] for p in points[:4]], sorted(p[0] for p in points[:4]))
        self.assertLess(points[0][1], points[4][1])

    def test_pending_archive_panel_beats_skill_panel_false_positive(self):
        """Archive's skill card must not hide the post-game panel classifier."""
        med = Mediator(Settings(), ROOT)
        med._post_game_pending = True
        frame = load_fixture_frame("fixtures/replay/archive_challenge_panel.png")

        with patch.object(med, "_selection_anchor", return_value=object()):
            self.assertEqual(med._post_game_state(frame), "ARCHIVE_PANEL")

    def test_live_archive_title_and_close_anchor_classify_panel(self):
        """The orange live title is valid only together with the modal X."""
        med = Mediator(Settings(), ROOT)
        frame = load_fixture_frame("fixtures/replay/archive_challenge_panel.png")
        title = MatchResult("archiveChallenge", 0.62, 900, 195, 92, 24, 946, 207)
        close = MatchResult("close", 0.47, 991, 250, 20, 20, 1001, 260)

        def fake_find(_frame, names, **_kwargs):
            if names == ["archiveChallenge"]:
                return title
            if names == ["close"]:
                return close
            if names == ["damijing"]:
                return MatchResult("damijing", 0.97, 1147, 201, 72, 25, 1183, 213)
            return None

        with patch.object(med, "_selection_anchor", return_value=None), \
             patch.object(med, "_archive_challenge_completed", return_value=True), \
             patch.object(med, "find", side_effect=fake_find):
            self.assertEqual(med._post_game_state(frame), "ARCHIVE_PANEL")

    def test_completed_archive_panel_does_not_require_archive_title_anchor(self):
        """The current completed page may expose only cundangInfo plus modal evidence."""
        med = Mediator(Settings(), ROOT)
        frame = load_fixture_frame("fixtures/replay/archive_challenge_panel.png")
        close = MatchResult("close", 0.47, 991, 250, 20, 20, 1001, 260)

        def fake_find(_frame, names, **_kwargs):
            if names == ["archiveChallenge"]:
                return None
            if names == ["close"]:
                return close
            return None

        with patch.object(med, "_selection_anchor", return_value=None), \
             patch.object(med, "_archive_challenge_completed", return_value=True), \
             patch.object(med, "find", side_effect=fake_find):
            self.assertEqual(med._post_game_state(frame), "ARCHIVE_PANEL")

    def test_completed_archive_cards_close_without_reclicking(self):
        """All eight green 已挑战 overlays advance directly to heirloom."""
        med = Mediator(Settings(cjb_boss="54莫阿姆"), ROOT)
        med.set_phase(Phase.MAIN_LINE, "archive completed")
        med._post_game_pending = True
        med._post_game_route = "archive"
        frame = load_fixture_frame("fixtures/replay/archive_challenge_panel.png")
        for index in range(8):
            col, row = index % 4, index // 4
            cx = int(frame.width * med._ARCHIVE_CHALLENGE_X[col])
            cy = int(frame.height * med._ARCHIVE_CHALLENGE_Y[row])
            frame.bgr[
                int(cy - frame.height * 0.035):int(cy + frame.height * 0.060),
                int(cx - frame.width * 0.040):int(cx + frame.width * 0.040),
            ] = (0, 255, 0)
            self.assertTrue(med._archive_challenge_completed(frame, index))
        close = MatchResult("close", 0.9, 990, 230, 20, 20, 1000, 240)

        with patch.object(med, "_post_game_state", return_value="ARCHIVE_PANEL"), \
             patch.object(med, "_find_archive_panel_close", return_value=close), \
             patch.object(med, "act_click", return_value=True) as click:
            self.assertEqual(med._tick_main_line(frame), LoopAction.Continue)

        click.assert_called_once_with(close, "CloseArchivePanel")
        self.assertEqual(med._post_game_route, "heirloom")

    def test_post_game_boss_search_scrolls_before_observing_lower_rows(self):
        """A lower archive-list Boss is searched only after a bounded list scroll."""
        med = Mediator(Settings(cjb_boss="54莫阿姆"), ROOT)
        med.set_phase(Phase.MAIN_LINE, "archive list scroll")
        med._post_game_pending = True
        med._post_game_route = "archive_active"
        frame = load_fixture_frame("fixtures/replay/archive_challenge_panel.png")
        target = MatchResult("54莫阿姆", 0.91, 1110, 470, 62, 62, 1110, 470)
        visible_after_scroll = {"value": False}

        def fake_find(_frame, _names, **kwargs):
            if visible_after_scroll["value"] and kwargs.get("mode") == "post-game-boss-grid":
                return target
            return None

        def fake_scroll(_x, _y, _clicks, _reason):
            visible_after_scroll["value"] = True
            return True

        with patch.object(med, "_post_game_state", return_value="ARCHIVE_PANEL"), \
             patch.object(med, "find", side_effect=fake_find), \
             patch.object(med, "act_scroll", side_effect=fake_scroll) as scroll, \
             patch.object(med, "act_click", return_value=True) as click:
            first = med._maybe_challenge_configured_boss(frame, 10.0, recheck_s=1.0)
            second = med._maybe_challenge_configured_boss(frame, 12.0, recheck_s=1.0)

        self.assertEqual(first, LoopAction.Continue)
        self.assertEqual(second, LoopAction.Continue)
        scroll.assert_called_once()
        sx, sy, clicks, reason = scroll.call_args.args
        self.assertEqual(reason, "BossConfigured-scroll")
        self.assertLess(clicks, 0)
        self.assertGreaterEqual(sx, frame.left + int(frame.width * 0.64))
        self.assertLessEqual(sx, frame.left + int(frame.width * 0.86))
        self.assertGreaterEqual(sy, frame.top + int(frame.height * 0.24))
        self.assertLessEqual(sy, frame.top + int(frame.height * 0.60))
        click.assert_called_once_with(target, "BossConfigured")
        self.assertEqual(med._boss_challenge_scroll_attempts, 1)
        self.assertEqual(med._boss_challenge_attempts, 1)

    def test_heirloom_dialog_uses_cjb_boss_handler(self):
        """A classified heirloom page selects cjb_boss through the existing handler."""
        med = Mediator(Settings(cjb_boss="01暴掠龙", sgzx_boss="24瑞文戴尔男爵"), ROOT)
        med._post_game_pending = True
        med._post_game_route = "heirloom_active"
        frame = load_fixture_frame("fixtures/reborn_wow/endgame/heirloom_challenge_bosses.png")
        with patch.object(med, "_post_game_state", return_value="HEIRLOOM_DIALOG"), \
             patch.object(med, "act_click", return_value=True) as click:
            action = med._maybe_challenge_configured_boss(frame, 10.0, recheck_s=1.0)
        self.assertEqual(action, LoopAction.Continue)
        click.assert_called_once()
        self.assertEqual(click.call_args.args[1], "BossConfigured")
        self.assertEqual(med._post_game_route, "heirloom_active")

    def test_heirloom_boss_waits_for_result_instead_of_reclicking(self):
        """After one heirloom click, the same card is not clicked again while settling."""
        med = Mediator(Settings(cjb_boss="01暴掠龙"), ROOT)
        med._post_game_pending = True
        med._post_game_route = "heirloom_active"
        med._boss_challenge_attempts = 1
        frame = load_fixture_frame("fixtures/reborn_wow/endgame/heirloom_challenge_bosses.png")
        with patch.object(med, "_post_game_state", return_value="HEIRLOOM_DIALOG"), \
             patch.object(med, "_heirloom_boss_result_visible", return_value=False), \
             patch.object(med, "act_click") as click:
            action = med._maybe_challenge_configured_boss(frame, 10.0, recheck_s=1.0)
        self.assertEqual(action, LoopAction.Continue)
        click.assert_not_called()

    def test_heirloom_result_closes_only_after_postcondition(self):
        """A confirmed live result toast is the only path to dismiss the panel."""
        med = Mediator(Settings(cjb_boss="01暴掠龙"), ROOT)
        med._post_game_pending = True
        med._post_game_route = "heirloom_active"
        med._boss_challenge_attempts = 1
        frame = load_fixture_frame("fixtures/reborn_wow/endgame/heirloom_challenge_bosses.png")
        close = MatchResult("close", 0.90, 990, 230, 20, 20, 1000, 240)
        with patch.object(med, "_post_game_state", return_value="HEIRLOOM_DIALOG"), \
             patch.object(med, "_heirloom_boss_result_visible", return_value=True), \
             patch.object(med, "_find_heirloom_close", return_value=close), \
             patch.object(med, "act_click", return_value=True) as click:
            action = med._tick_main_line(frame)
        self.assertEqual(action, LoopAction.Continue)
        click.assert_called_once_with(close, "DismissHeirloomDialog")
        self.assertEqual(med._post_game_route, "boss_active")
        self.assertFalse(med._post_game_pending)

    def test_active_boss_route_never_looks_like_npc_hub(self):
        """Live-map NPC labels cannot authorize exit during an active Boss."""
        med = Mediator(Settings(cjb_boss="08战争雷霆蜥蜴"), ROOT)
        med._post_game_route = "boss_active"
        med._post_game_pending = False
        frame = load_fixture_frame("fixtures/replay/challenge_npc_hub.png")
        self.assertIsNone(med._post_game_state(frame))

    def test_active_boss_route_does_not_reenter_configured_boss_probe(self):
        """The active challenge route suppresses both proactive Boss entry probes."""
        med = Mediator(Settings(cjb_boss="08战争雷霆蜥蜴"), ROOT)
        med._post_game_route = "boss_active"
        med._post_game_pending = False
        med._boss_challenge_attempts = 1
        frame = load_fixture_frame("fixtures/replay/challenge_npc_hub.png")
        with patch.object(med, "_post_game_state", return_value=None), \
             patch.object(med, "find_scene", return_value=True), \
             patch.object(med, "_maybe_challenge_configured_boss") as probe:
            med._round_tail_checks_active = lambda: True
            med._tick_main_line(frame)
        probe.assert_not_called()

    def test_boss_victory_continue_keeps_boss_postgame_route(self):
        """Only after Victory is observed may the Boss route proceed to exit/rift."""
        med = Mediator(Settings(cjb_boss="08战争雷霆蜥蜴"), ROOT)
        med.set_phase(Phase.MAIN_LINE, "boss victory route")
        med._post_game_route = "boss_active"
        frame = load_fixture_frame("fixtures/replay/victory_continue.png")
        with patch.object(med, "act_click", return_value=True) as click:
            action = med._tick_main_line(frame)
        self.assertEqual(action, LoopAction.Continue)
        self.assertEqual(click.call_count, 1)
        self.assertEqual(click.call_args.args[1], "ContinueGame")
        self.assertTrue(med._post_game_pending)
        self.assertEqual(med._post_game_route, "boss_postgame")

    def test_hub_route_opens_heirloom_after_archive_close(self):
        """After archive handling, the next hub action is the heirloom NPC, not rift."""
        med = Mediator(Settings(cjb_boss="54莫阿姆"), ROOT)
        med.set_phase(Phase.MAIN_LINE, "heirloom route")
        med._post_game_pending = True
        med._post_game_route = "heirloom"
        frame = load_fixture_frame("fixtures/replay/challenge_npc_hub.png")
        entry = MatchResult("post_game_heirloom_npc", 0.64, 1000, 340, 100, 30, 1050, 350)

        with patch.object(med, "_post_game_state", return_value="NPC_HUB"), \
             patch.object(med, "_post_game_hub_entry_click", return_value=entry), \
             patch.object(med, "act_click", return_value=True) as click:
            action = med._tick_main_line(frame)

        self.assertEqual(action, LoopAction.Continue)
        click.assert_called_once_with(entry, "OpenHeirloomChallenges")
        self.assertEqual(med._post_game_route, "heirloom_active")

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
             patch("shuabao.mediator.time") as mock_time:
            mock_time.time.return_value = 1000.0
            mock_time.sleep.return_value = None
            action = med.tick()
            self.assertEqual(action, LoopAction.Continue)
            mock_tick.assert_not_called()
            self.assertIsNotNone(med._missing_window_since)


if __name__ == "__main__":
    unittest.main()
