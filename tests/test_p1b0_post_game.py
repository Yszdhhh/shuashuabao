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
        # lab 不属于无人值守模式，仍走 Fail-Closed；normal_farm 的零输入不停机见 test_unattended_recovery_20260914。
        self.settings = Settings(mode_id="lab")
        self.med = Mediator(self.settings, ROOT)
        self.med.set_phase(Phase.MAIN_LINE, "p1b0 setup")
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
        self.assertEqual(npc_hit.name, "damijing_npc")
        # The NPC body under the 大秘境 caption, not the caption text itself.
        self.assertGreater(npc_hit.center[1], 307 + 25)
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
        active_second = load_fixture_frame("fixtures/replay/main_line_auto_on.png")
        verified_at = transition_at + 0.1
        with patch("shuabao.mediator.time.time", return_value=verified_at), \
             patch.object(med, "_post_game_state", return_value=None), \
             patch.object(med, "_is_in_game_hud", return_value=True), \
             patch.object(med, "act_click") as extra_click, \
             patch.object(med, "act_right_click") as extra_right_click:
            action = med._tick_main_line(active)
        self.assertEqual(action, LoopAction.Continue)
        self.assertFalse(med._secret_realm_active)
        self.assertTrue(med._secret_realm_request_pending)
        self.assertTrue(med._post_game_pending)
        self.assertIsNotNone(med._secret_realm_entering_since)
        extra_click.assert_not_called()
        extra_right_click.assert_not_called()

        with patch("shuabao.mediator.time.time", return_value=verified_at + 0.1), \
             patch.object(med, "_post_game_state", return_value=None), \
             patch.object(med, "_is_in_game_hud", return_value=True), \
             patch.object(med, "act_click") as extra_click, \
             patch.object(med, "act_right_click") as extra_right_click:
            action = med._tick_main_line(active_second)
        self.assertEqual(action, LoopAction.Continue)
        self.assertTrue(med._secret_realm_active)
        self.assertFalse(med._secret_realm_request_pending)
        self.assertFalse(med._post_game_pending)
        self.assertIsNone(med._secret_realm_entering_since)
        extra_click.assert_not_called()
        extra_right_click.assert_not_called()

    def test_secret_realm_dialog_timeout_fails_closed_without_guessing(self):
        settings = Settings(auto_secret_realm=True, mode_id="lab")  # lab 不属于无人值守模式，仍走 Fail-Closed；normal_farm 的零输入不停机见 test_unattended_recovery_20260914。
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

    def test_hub_classified_with_dual_challenge_labels_without_damijing(self):
        """damijing score is too low on live plaza frames; the dual hub labels alone classify NPC_HUB."""
        frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), hwnd=10001)

        def fake_find(_frame, names, **_kwargs):
            name = names[0]
            if name == "quit":
                return MatchResult(name, 0.90, 20, 10, 70, 24, 55, 22)
            if name in ("damijing", "HeroChallenge"):
                return None
            return None

        def fake_hub_entry(_frame, route):
            x = 900 if route == "archive" else 1010
            return MatchResult(route, 0.66, x, 200, 90, 24, x + 45, 212)

        with patch.object(self.med, "find", side_effect=fake_find), \
             patch.object(self.med, "_find_post_game_hub_entry", side_effect=fake_hub_entry):
            self.assertEqual(self.med._post_game_state(frame), "NPC_HUB")

    def _hub_frame_state(self, archive_box, heirloom_box):
        """Classify a hub frame whose only page evidence is the two NPC labels."""
        frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), hwnd=10001)

        def fake_find(_frame, names, **_kwargs):
            if names[0] == "quit":
                return MatchResult("quit", 0.89, 39, 12, 75, 24, 76, 24)
            return None

        def fake_hub_entry(_frame, route):
            x, y, w, h = archive_box if route == "archive" else heirloom_box
            return MatchResult(route, 0.66, x, y, w, h, x + w // 2, y + h // 2)

        with patch.object(self.med, "find", side_effect=fake_find), \
             patch.object(self.med, "_find_post_game_hub_entry", side_effect=fake_hub_entry):
            return self.med._post_game_state(frame)

    def test_live_f0133_label_pair_geometry_classifies_the_hub(self):
        """Exact boxes measured on 20260909 f0133_action_after.png (damijing scored 0.597)."""
        self.assertEqual(
            self._hub_frame_state((665, 146, 92, 24), (769, 146, 116, 27)),
            "NPC_HUB",
        )

    def test_labels_on_different_rows_are_not_hub_evidence(self):
        """Two scattered 0.58 hits are template noise, not the plaza's label row."""
        self.assertIsNone(self._hub_frame_state((665, 146, 92, 24), (769, 320, 116, 27)))

    def test_labels_far_apart_are_not_hub_evidence(self):
        """存档挑战 and 传家宝挑战 render nearly touching; a screen-wide gap is noise."""
        self.assertIsNone(self._hub_frame_state((300, 146, 92, 24), (1200, 146, 116, 27)))

    def test_heirloom_label_left_of_archive_is_not_hub_evidence(self):
        self.assertIsNone(self._hub_frame_state((769, 146, 92, 24), (665, 146, 116, 27)))

    def test_centered_live_hub_beats_false_item_panel_anchor(self):
        """The live plaza's central NPC layout must not be hidden by heroRefresh noise."""
        frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), hwnd=10001)

        def fake_find(_frame, names, **_kwargs):
            name = names[0]
            hits = {
                "quit": MatchResult(name, 0.89, 39, 12, 75, 24, 76, 24),
                "damijing": MatchResult(name, 0.91, 925, 231, 72, 25, 961, 243),
                "HeroChallenge": MatchResult(name, 0.95, 310, 77, 84, 23, 352, 88),
            }
            return hits.get(name)

        with patch.object(self.med, "find", side_effect=fake_find), \
             patch.object(self.med, "_selection_anchor", return_value=object()):
            self.assertEqual(self.med._post_game_state(frame), "NPC_HUB")

    def test_archive_panel_visits_archive_cards_before_closing(self):
        """A pending archive page starts the eight-card sequence before close."""
        med = Mediator(Settings(cjb_boss="54莫阿姆", sgzx_boss="55吞咽者布鲁"), ROOT)
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

    def test_archive_walks_all_eight_cards_left_to_right(self):
        """Click every card once, left to right - except a 0/8 card.

        Owner ruling 20260910 clicked every card (a 0/8 cost one wasted
        click); owner rule 2026-09-14 supersedes it: 0/8 and 已挑战 cards are
        never clicked, the rest are swept 1->8 once.
        """
        med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
        frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), hwnd=10001)
        card = MatchResult("archive_card", 0.9, 600, 300, 40, 40, 620, 320)
        clicked_labels: list[str] = []

        def fake_completed(_frame, index):
            return index in med._archive_challenge_clicked  # clicked -> green

        with patch.object(med, "_archive_challenge_completed", side_effect=fake_completed), \
             patch.object(med, "_archive_hitch_card_progress_state",
                          side_effect=lambda f, idx: "UNAVAILABLE" if idx == 2 else "AVAILABLE"), \
             patch.object(med, "_find_archive_challenge_card", return_value=card), \
             patch.object(med, "act_click", return_value=True) as click:
            click.side_effect = lambda _hit, reason: clicked_labels.append(reason) or True
            now = 1.0
            for _ in range(20):
                if med._maybe_click_archive_challenge(frame, now) is None:
                    break
                now = med._archive_challenge_next_at + 0.1
            self.assertIsNone(med._maybe_click_archive_challenge(frame, now))

        self.assertEqual(
            clicked_labels,
            [f"ArchiveChallenge-{name}" for name in med._ARCHIVE_CHALLENGE_NAMES if name != "gem"],
        )

    def test_archive_card_advances_on_the_green_challenged_overlay(self):
        """完成权威是卡面绿色「已挑战」，不是 OCR 计数。"""
        med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
        frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), hwnd=10001)
        done = {0: True}
        with patch.object(med, "_archive_challenge_completed", side_effect=lambda _f, i: done.get(i, False)), \
                patch.object(med, "act_click") as click:
            self.assertEqual(med._maybe_click_archive_challenge(frame, 1.0), LoopAction.Continue)
        self.assertEqual(med._archive_challenge_index, 1)
        click.assert_not_called()

    def test_ocr_completed_alone_no_longer_skips_a_card(self):
        """20260910 实机：宝石/战利品显示 8/8 可点，却被 OCR 判成完成跳过。

        OCR 进度降级为遥测后，没有绿色「已挑战」就不算完成，卡照点。
        """
        med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
        frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), hwnd=10001)
        card = MatchResult("archive_challenge_skill", 0.9, 600, 300, 40, 40, 620, 320)
        with patch.object(med, "_archive_challenge_completed", return_value=False), \
                patch.object(med, "_archive_hitch_card_progress_state", return_value="COMPLETED"), \
                patch.object(med, "_find_archive_challenge_card", return_value=card), \
                patch.object(med, "act_click", return_value=True) as click:
            self.assertEqual(med._maybe_click_archive_challenge(frame, 1.0), LoopAction.Continue)
        click.assert_called_once_with(card, "ArchiveChallenge-skill")

    def test_archive_plan_covers_all_eight_cards_left_to_right(self):
        """Owner ruling 20260910：八张全点一遍，蹭车不再只覆盖四张。"""
        med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
        plan = med._archive_challenge_plan()
        self.assertEqual([label for label, _ in plan], list(med._ARCHIVE_CHALLENGE_NAMES))
        self.assertEqual([index for _, index in plan], list(range(8)))

    def test_unconfirmed_card_is_clicked_once_and_the_sweep_moves_on(self):
        """Owner 2026-09-14：点了没立刻变绿也立即转下一张，绝不在原地重点同一张。"""
        med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
        frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), hwnd=10001)
        card = MatchResult("archive_challenge_skill", 0.9, 600, 300, 40, 40, 620, 320)
        with patch.object(med, "_archive_challenge_completed", return_value=False), \
                patch.object(med, "_archive_hitch_card_progress_state", return_value="AVAILABLE"), \
                patch.object(med, "_find_archive_challenge_card", return_value=card), \
                patch.object(med, "act_click", return_value=True) as click:
            med._maybe_click_archive_challenge(frame, 1.0)
        self.assertEqual(click.call_count, 1)
        self.assertEqual(med._archive_challenge_index, 1, "点一次就转下一张")

    def test_hitch_archive_unknown_is_bounded_and_skips_without_click(self):
        med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
        frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), hwnd=10001)
        with patch.object(med, "_archive_challenge_completed", return_value=False), \
                patch.object(med, "_archive_hitch_card_progress_state", return_value="UNKNOWN"), \
                patch.object(med, "_find_archive_challenge_card", return_value=None), \
                patch.object(med, "act_click") as click:
            now = 1.0
            for _ in range(5):
                self.assertEqual(med._maybe_click_archive_challenge(frame, now), LoopAction.Continue)
                now = med._archive_challenge_next_at + 0.1
        self.assertEqual(med._archive_challenge_index, 1)
        self.assertEqual(med._archive_challenge_observe_attempts, 0)
        click.assert_not_called()

    def test_hitch_victory_retry_exhaustion_rearms_without_stopping(self):
        med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
        med.set_phase(Phase.MAIN_LINE, "hitch victory")
        med._victory_continue_attempts = 3
        med._hitch_pressure_transferred = True  # P0 门禁已通过（8159de8）
        frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), hwnd=10001)
        with patch.object(med, "_post_game_state", return_value="POST_VICTORY"), \
                patch.object(med, "stop") as stop:
            self.assertEqual(med._tick_main_line(frame), LoopAction.Continue)
        self.assertEqual(med._victory_continue_attempts, 0)
        self.assertNotEqual(med.phase, Phase.ERROR)
        stop.assert_not_called()

    def test_hitch_direct_archive_panel_adopts_postgame_chain(self):
        med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
        med._post_game_pending = False
        med._hitch_pressure_transferred = True  # P0 门禁已通过（8159de8）
        frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), hwnd=10001)
        with patch.object(med, "_post_game_state", return_value="ARCHIVE_PANEL"), \
                patch.object(med, "stop") as stop:
            self.assertEqual(med._tick_main_line(frame), LoopAction.Continue)
        self.assertTrue(med._post_game_pending)
        self.assertEqual(med._post_game_route, "archive")
        stop.assert_not_called()

    def test_hitch_unknown_postgame_transition_timeout_keeps_waiting(self):
        med = Mediator(Settings(mode_id="lobby_hitch", query_timeout=3), ROOT)
        med.set_phase(Phase.MAIN_LINE, "hitch postgame loading")
        med._post_game_pending = True
        med._victory_continue_since = 1.0
        frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), hwnd=10001)
        with patch("shuabao.mediator.time.time", return_value=10.0), \
                patch.object(med, "_post_game_state", return_value=None), \
                patch.object(med, "_find_failure_gift", return_value=None), \
                patch.object(med, "stop") as stop:
            self.assertEqual(med._tick_main_line(frame), LoopAction.Continue)
        self.assertNotEqual(med.phase, Phase.ERROR)
        stop.assert_not_called()

    def test_hitch_postgame_uses_f1_before_archive_and_f2_after_time_cave_boss(self):
        """Follow mode owns its hero view before archive and returns to base before heirloom."""
        med = Mediator(Settings(mode_id="lobby_hitch", cjb_boss="54莫阿姆"), ROOT)
        med.set_phase(Phase.MAIN_LINE, "hitch post-game focus")
        med._post_game_pending = True
        med._hitch_pressure_transferred = True  # P0 门禁已通过（8159de8）
        frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), hwnd=10001)

        with patch.object(med, "_post_game_state", return_value="ARCHIVE_PANEL"), \
             patch.object(med, "act_key", return_value=True) as key, \
             patch.object(med, "_maybe_click_archive_challenge") as archive:
            self.assertEqual(med._tick_main_line(frame), LoopAction.Continue)
        key.assert_called_once_with("F1", "HitchPostGameSelectOwnHero")
        archive.assert_not_called()

        med._post_game_route = "boss_postgame"
        med._time_cave_boss_done = True
        with patch.object(med, "_post_game_state", return_value="NPC_HUB"), \
             patch.object(med, "act_key", return_value=True) as key:
            self.assertEqual(med._tick_main_line(frame), LoopAction.Continue)
        key.assert_called_once_with("F2", "HitchPostBossReturnOwnBase")
        self.assertEqual(med._post_game_route, "heirloom")

    def test_pending_archive_panel_beats_skill_panel_false_positive(self):
        """Archive's skill card must not hide the post-game panel classifier."""
        med = Mediator(Settings(), ROOT)
        med._post_game_pending = True
        frame = load_fixture_frame("fixtures/replay/archive_challenge_panel.png")

        with patch.object(med, "_selection_anchor", return_value=object()):
            self.assertEqual(med._post_game_state(frame), "ARCHIVE_PANEL")

    def test_pending_only_archive_panel_requires_two_consecutive_ticks(self):
        """An otherwise generic modal X cannot authorize 4x2 clicks on one frame."""
        med = Mediator(Settings(), ROOT)
        med.set_phase(Phase.MAIN_LINE, "pending-only archive candidate")
        med._post_game_pending = True
        frame = load_fixture_frame("fixtures/replay/archive_challenge_panel.png")
        close = MatchResult("lobby/archive_panel_close", 0.95, 991, 250, 20, 20, 1001, 260)

        def fake_find(_frame, names, **_kwargs):
            if names in (["close"], ["lobby/archive_panel_close"]):
                return close
            return None

        with patch.object(med, "_selection_anchor", return_value=None), \
             patch.object(med, "find", side_effect=fake_find), \
             patch.object(med, "find_scene", return_value=None), \
             patch.object(med, "_archive_challenge_completed", return_value=False), \
             patch.object(med, "_maybe_click_archive_challenge", return_value=LoopAction.Continue) as archive:
            self.assertEqual(med._tick_main_line(frame), LoopAction.Continue)
            archive.assert_not_called()
            self.assertEqual(med._pending_archive_panel_frames, 1)

            self.assertEqual(med._tick_main_line(frame), LoopAction.Continue)
            self.assertEqual(archive.call_count, 1)

    def test_active_archive_route_requires_two_consecutive_hud_frames(self):
        """A one-frame loading/HUD blend keeps the post-game gate closed."""
        med = Mediator(Settings(), ROOT)
        med.set_phase(Phase.MAIN_LINE, "archive destination confirmation")
        med._post_game_pending = True
        med._post_game_route = "archive_active"
        frame = load_fixture_frame("fixtures/replay/main_line_auto_on.png")

        with patch.object(med, "_post_game_state", return_value=None), \
             patch.object(med, "_is_in_game_hud", return_value=True):
            self.assertEqual(med._tick_main_line(frame), LoopAction.Continue)
            self.assertTrue(med._post_game_pending)
            self.assertEqual(med._post_game_hud_confirmations, 1)

            self.assertEqual(med._tick_main_line(frame), LoopAction.Continue)
            self.assertFalse(med._post_game_pending)
            self.assertEqual(med._post_game_hud_confirmations, 0)

    def test_live_archive_title_and_close_anchor_classify_panel(self):
        """The orange live title is valid only together with the modal X."""
        med = Mediator(Settings(), ROOT)
        frame = load_fixture_frame("fixtures/replay/archive_challenge_panel.png")
        title = MatchResult("archiveChallenge", 0.62, 900, 195, 92, 24, 946, 207)
        close = MatchResult("lobby/archive_panel_close", 0.95, 991, 250, 20, 20, 1001, 260)

        def fake_find(_frame, names, **_kwargs):
            if names == ["archiveChallenge"]:
                return title
            if names in (["close"], ["lobby/archive_panel_close"]):
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
        close = MatchResult("lobby/archive_panel_close", 0.95, 991, 250, 20, 20, 1001, 260)

        def fake_find(_frame, names, **_kwargs):
            if names == ["archiveChallenge"]:
                return None
            if names in (["close"], ["lobby/archive_panel_close"]):
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
        med._time_cave_boss_done = True  # isolate the archive-card completion branch
        close = MatchResult("close", 0.9, 990, 230, 20, 20, 1000, 240)

        with patch.object(med, "_post_game_state", return_value="ARCHIVE_PANEL"), \
             patch.object(med, "_find_archive_panel_close", return_value=close), \
             patch.object(med, "act_click", return_value=True) as click:
            self.assertEqual(med._tick_main_line(frame), LoopAction.Continue)

        click.assert_called_once_with(close, "CloseArchivePanel")
        self.assertEqual(med._post_game_route, "heirloom")

    def test_completed_archive_cards_try_time_cave_before_close(self):
        """Eight archive cards must not close before the time-cave handler runs."""
        med = Mediator(Settings(sgzx_boss="55吞咽者布鲁"), ROOT)
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
        def handoff(_frame, _now):
            med._time_cave_boss_done = True
            return LoopAction.Continue

        with patch.object(med, "_post_game_state", return_value="ARCHIVE_PANEL"), \
             patch.object(med, "_maybe_challenge_configured_boss", side_effect=handoff) as boss, \
             patch.object(med, "_find_archive_panel_close") as close:
            self.assertEqual(med._tick_main_line(frame), LoopAction.Continue)

        boss.assert_called_once()
        close.assert_not_called()
        self.assertTrue(med._time_cave_boss_done)

    def test_archive_panel_from_hub_active_triggers_time_cave_when_cards_completed(self):
        """When entering archive panel from hub (route=archive_active), if cards are completed, time cave runs."""
        med = Mediator(Settings(sgzx_boss="55吞咽者布鲁"), ROOT)
        med.set_phase(Phase.MAIN_LINE, "archive from hub")
        med._post_game_pending = True
        med._post_game_route = "archive_active"
        med._boss_challenge_attempts = 0
        frame = load_fixture_frame("fixtures/replay/archive_challenge_panel.png")
        for index in range(8):
            col, row = index % 4, index // 4
            cx = int(frame.width * med._ARCHIVE_CHALLENGE_X[col])
            cy = int(frame.height * med._ARCHIVE_CHALLENGE_Y[row])
            frame.bgr[
                int(cy - frame.height * 0.035):int(cy + frame.height * 0.060),
                int(cx - frame.width * 0.040):int(cx + frame.width * 0.040),
            ] = (0, 255, 0)
        def handoff(_frame, _now):
            med._boss_challenge_attempts = 1
            med._time_cave_boss_done = True
            return LoopAction.Continue

        with patch.object(med, "_post_game_state", return_value="ARCHIVE_PANEL"), \
             patch.object(med, "_maybe_challenge_configured_boss", side_effect=handoff) as boss, \
             patch.object(med, "_find_archive_panel_close") as close:
            self.assertEqual(med._tick_main_line(frame), LoopAction.Continue)

        boss.assert_called_once()
        close.assert_not_called()
        self.assertEqual(med._boss_challenge_attempts, 1)

    def test_eighth_archive_click_does_not_close_same_tick(self):
        med = Mediator(Settings(sgzx_boss="55吞咽者布鲁"), ROOT)
        med._post_game_pending = True
        med._post_game_route = "archive"
        med._archive_challenge_index = 7
        frame = load_fixture_frame("fixtures/replay/archive_challenge_panel.png")

        def eighth_click(_frame, _now):
            med._archive_challenge_index = 8
            med._post_game_route = "archive_active"
            return LoopAction.Continue

        with patch.object(med, "_post_game_state", return_value="ARCHIVE_PANEL"), \
             patch.object(med, "_maybe_click_archive_challenge", side_effect=eighth_click), \
             patch.object(med, "_maybe_challenge_configured_boss") as boss, \
             patch.object(med, "_find_archive_panel_close") as close:
            self.assertEqual(med._tick_main_line(frame), LoopAction.Continue)

        boss.assert_not_called()
        close.assert_not_called()
        self.assertEqual(med._post_game_route, "archive")


    def test_post_game_boss_search_scrolls_before_observing_lower_rows(self):
        """A lower archive-list Boss is searched only after a bounded list scroll."""
        med = Mediator(Settings(sgzx_boss="54莫阿姆"), ROOT)
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

    def test_archive_dialog_uses_only_sgzx_boss_handler(self):
        """The classified archive page must not borrow the heirloom selection."""
        med = Mediator(Settings(cjb_boss="54莫阿姆", sgzx_boss="12卡尔加"), ROOT)
        med._post_game_pending = True
        frame = load_fixture_frame("fixtures/reborn_wow/endgame/archive_challenge_panel.png")

        with patch.object(med, "_post_game_state", return_value="ARCHIVE_PANEL"), \
             patch.object(med, "act_click", return_value=True) as click:
            action = med._maybe_challenge_configured_boss(frame, 10.0, recheck_s=1.0)

        self.assertEqual(action, LoopAction.Continue)
        clicked, reason = click.call_args.args
        self.assertEqual(clicked.name, "12卡尔加")
        self.assertEqual(reason, "BossConfigured")

    def test_classified_boss_search_is_limited_to_its_visible_list_roi(self):
        """Settlement must not spend a full-screen template pass before clicking."""
        med = Mediator(Settings(sgzx_boss="12卡尔加"), ROOT)
        med._post_game_pending = True
        frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), hwnd=1)
        target = MatchResult("boss/12卡尔加", 0.90, 1180, 420, 50, 50, 1180, 420)
        with patch.object(med, "_post_game_state", return_value="ARCHIVE_PANEL"), \
             patch.object(med, "find", return_value=target) as find, \
             patch.object(med, "act_click", return_value=True):
            self.assertEqual(
                med._maybe_challenge_configured_boss(frame, 10.0, recheck_s=1.0),
                LoopAction.Continue,
            )
        self.assertEqual(find.call_count, 1)
        self.assertEqual(find.call_args.kwargs["roi"], med._POST_GAME_BOSS_ROIS["ARCHIVE_PANEL"])
        self.assertEqual(find.call_args.kwargs["mode"], "post-game-boss-grid")

    def test_archive_unavailable_boss_falls_back_to_last_card_only_after_bottom(self):
        """A verified lower boundary, not a fixed scroll count, authorizes fallback."""
        med = Mediator(Settings(sgzx_boss="55吞咽者布鲁"), ROOT)
        med._post_game_pending = True
        med._boss_challenge_scroll_attempts = 1
        frame = load_fixture_frame("fixtures/reborn_wow/endgame/archive_challenge_panel.png")

        with patch.object(med, "_post_game_state", return_value="ARCHIVE_PANEL"), \
             patch.object(med, "_post_game_boss_list_at_bottom", return_value=True), \
             patch.object(med, "act_click", return_value=True) as click:
            action = med._maybe_challenge_configured_boss(frame, 10.0, recheck_s=1.0)

        self.assertEqual(action, LoopAction.Continue)
        clicked, reason = click.call_args.args
        self.assertEqual(clicked.name, "09摩拉迪姆")
        self.assertEqual(reason, "BossNotUnlockedLast")

    def test_heirloom_unavailable_boss_falls_back_to_last_card_only_after_bottom(self):
        """The same production handler reuses heirloom templates after bottom proof."""
        med = Mediator(Settings(cjb_boss="54莫阿姆"), ROOT)
        med._post_game_pending = True
        med._boss_challenge_scroll_attempts = 1
        frame = load_fixture_frame("fixtures/reborn_wow/endgame/heirloom_challenge_bosses.png")

        with patch.object(med, "_post_game_state", return_value="HEIRLOOM_DIALOG"), \
             patch.object(med, "_post_game_boss_list_at_bottom", return_value=True), \
             patch.object(med, "act_click", return_value=True) as click:
            action = med._maybe_challenge_configured_boss(frame, 10.0, recheck_s=1.0)

        self.assertEqual(action, LoopAction.Continue)
        clicked, reason = click.call_args.args
        self.assertEqual(clicked.name, "03洛卡纳哈")
        self.assertEqual(reason, "BossNotUnlockedLast")

    def test_unconfigured_post_game_lists_scroll_to_bottom_then_choose_last_card(self):
        """未设 Boss 时，两类列表都必须到底后才选物理最后卡。"""
        frame = load_fixture_frame("fixtures/reborn_wow/endgame/archive_challenge_panel.png")
        last = MatchResult("12卡尔加", 0.91, 1110, 470, 62, 62, 1110, 470)
        for page, settings in (
            ("ARCHIVE_PANEL", Settings(sgzx_boss="", cjb_boss="")),
            ("HEIRLOOM_DIALOG", Settings(sgzx_boss="", cjb_boss="")),
        ):
            with self.subTest(page=page):
                med = Mediator(settings, ROOT)
                med._post_game_pending = True
                with patch.object(med, "_post_game_state", return_value=page), \
                     patch.object(med, "_find_last_recognized_post_game_boss", return_value=last), \
                     patch.object(med, "_post_game_boss_list_at_bottom", side_effect=[False, False, True]), \
                     patch.object(med, "act_scroll", return_value=True) as scroll, \
                     patch.object(med, "act_click", return_value=True) as click:
                    self.assertEqual(
                        med._maybe_challenge_configured_boss(frame, 10.0, recheck_s=1.0),
                        LoopAction.Continue,
                    )
                    self.assertEqual(
                        med._maybe_challenge_configured_boss(frame, 12.0, recheck_s=1.0),
                        LoopAction.Continue,
                    )
                    self.assertEqual(
                        med._maybe_challenge_configured_boss(frame, 14.0, recheck_s=1.0),
                        LoopAction.Continue,
                    )
                self.assertEqual(scroll.call_count, 2)
                click.assert_called_once_with(last, "BossBottomFallback")

    def test_unavailable_boss_stays_fail_closed_without_fallback_template(self):
        """An exhausted classified list still emits zero click when no card is recognized."""
        med = Mediator(Settings(sgzx_boss="55吞咽者布鲁"), ROOT)
        med._post_game_pending = True
        med._boss_challenge_scroll_attempts = 1
        frame = load_fixture_frame("fixtures/reborn_wow/endgame/archive_challenge_panel.png")

        with patch.object(med, "_post_game_state", return_value="ARCHIVE_PANEL"), \
             patch.object(med, "_post_game_boss_list_at_bottom", return_value=True), \
             patch.object(med, "_find_last_recognized_post_game_boss", return_value=None), \
             patch.object(med, "act_scroll") as scroll, \
             patch.object(med, "act_click") as click:
            action = med._maybe_challenge_configured_boss(frame, 10.0, recheck_s=1.0)

        self.assertEqual(action, LoopAction.Continue)
        scroll.assert_not_called()
        click.assert_not_called()

    def test_bottom_fallback_uses_card_position_not_template_number(self):
        """The fallback chooses the visual lower-right card, never max filename."""
        med = Mediator(Settings(), ROOT)
        frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), hwnd=1)
        top_numbered_high = MatchResult("boss/99顶部", 0.99, 1120, 260, 50, 50, 1120, 260)
        bottom_left = MatchResult("boss/01底部左", 0.90, 1120, 440, 50, 50, 1120, 440)
        bottom_right = MatchResult("boss/02底部右", 0.90, 1220, 440, 50, 50, 1220, 440)
        with patch("shuabao.mediator.match_all", return_value=[top_numbered_high, bottom_left, bottom_right]):
            selected = med._find_last_recognized_post_game_boss(frame, "ARCHIVE_PANEL")
        self.assertIs(selected, bottom_right)

    def test_unclassified_post_game_transition_is_zero_input(self):
        """A pending post-game transition must not search or click an unknown frame."""
        med = Mediator(Settings(sgzx_boss="12卡尔加"), ROOT)
        med._post_game_pending = True
        frame = load_fixture_frame("fixtures/reborn_wow/endgame/archive_challenge_panel.png")

        with patch.object(med, "_post_game_state", return_value=None), \
             patch.object(med, "find") as find, \
             patch.object(med, "act_scroll") as scroll, \
             patch.object(med, "act_click") as click:
            action = med._maybe_challenge_configured_boss(frame, 10.0, recheck_s=1.0)

        self.assertEqual(action, LoopAction.Continue)
        find.assert_not_called()
        scroll.assert_not_called()
        click.assert_not_called()

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
        # The click itself is what proves "already sent" (a time-cave click
        # sharing the counter must not, live 2026-09-12).
        med._heirloom_boss_clicked_at = 9.5
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
        med._heirloom_boss_clicked_at = time.time()
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

    def test_heirloom_boss_tags_before_any_click_do_not_close_the_list(self):
        """2026-09-25 hitch round 2 (f0465): the bottom row's red BOSS tags sit in
        the toast band. Before this round's own Boss click the list must go to
        the Boss handler, never be dismissed as already challenged."""
        med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
        med._post_game_pending = True
        med._post_game_route = "heirloom_active"
        frame = load_fixture_frame("fixtures/hitch_heirloom_20260925/round02_heirloom_list_before_click.png")
        self.assertTrue(med._heirloom_boss_result_visible(frame))  # the false-positive source
        close = MatchResult("close", 0.90, 990, 230, 20, 20, 1000, 240)
        with patch.object(med, "_post_game_state", return_value="HEIRLOOM_DIALOG"), \
             patch.object(med, "_maybe_challenge_configured_boss", return_value=LoopAction.Continue) as choose, \
             patch.object(med, "_find_heirloom_close", return_value=close), \
             patch.object(med, "act_click", return_value=True) as click:
            self.assertEqual(med._tick_main_line(frame), LoopAction.Continue)
        choose.assert_called_once()
        click.assert_not_called()
        self.assertFalse(getattr(med, "_heirloom_boss_result_confirmed", False))

    def test_heirloom_without_config_delegates_to_bottom_fallback(self):
        """An empty cjb_boss must invoke the safe bottom-search handler first."""
        med = Mediator(Settings(), ROOT)
        med._post_game_pending = True
        med._post_game_route = "heirloom_active"
        frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), hwnd=10001)
        close = MatchResult("close", 0.90, 990, 230, 20, 20, 1000, 240)
        with patch.object(med, "_post_game_state", return_value="HEIRLOOM_DIALOG"), \
             patch.object(med, "_maybe_challenge_configured_boss", return_value=LoopAction.Continue) as choose, \
             patch.object(med, "_find_heirloom_close", return_value=close), \
             patch.object(med, "act_click", return_value=True) as click:
            self.assertEqual(med._tick_main_line(frame), LoopAction.Continue)
        choose.assert_called_once()
        click.assert_not_called()

    def test_heirloom_result_ignores_scattered_combat_red_vfx(self):
        """Red attack effects behind the dialog cannot close an unplayed page."""
        med = Mediator(Settings(cjb_boss="08战争雷霆蜥蜴"), ROOT)
        frame_bgr = np.zeros((900, 1600, 3), dtype=np.uint8)
        # Two small red VFX-like components in the exact result-toast ROI.
        frame_bgr[580:584, 790:802] = (0, 0, 255)
        frame_bgr[582:585, 818:829] = (0, 0, 255)
        self.assertFalse(med._heirloom_boss_result_visible(Frame(frame_bgr)))

        # A compact toast-shaped component is accepted as the stronger signal.
        frame_bgr[550:558, 790:860] = (0, 0, 255)
        self.assertTrue(med._heirloom_boss_result_visible(Frame(frame_bgr)))

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

    def test_team_heirloom_boss_chain_requires_postcondition_before_wait_exit(self):
        """A team Boss click cannot bypass the heirloom result and two-leave exit gate."""
        med = Mediator(Settings(mode_id="lobby_hitch", cjb_boss="01暴掠龙"), ROOT)
        med.set_phase(Phase.MAIN_LINE, "team heirloom post-game chain")
        med._hitch_pressure_transferred = True  # P0 门禁已通过（8159de8）
        med._post_game_pending = True
        med._post_game_route = "boss_postgame"
        frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), hwnd=10001)
        heirloom_entry = MatchResult("post_game_heirloom_npc", 0.9, 1000, 340, 100, 30, 1050, 350)
        configured_boss = MatchResult("01暴掠龙", 0.9, 900, 460, 80, 40, 940, 480)
        close = MatchResult("close", 0.9, 990, 230, 20, 20, 1000, 240)
        continue_game = MatchResult("continueGame", 0.9, 800, 500, 80, 40, 840, 520)

        # Boss victory returns to this player's base once, then opens the
        # configured heirloom route rather than quitting the team immediately.
        with patch.object(med, "_post_game_state", return_value="NPC_HUB"), \
             patch.object(med, "act_key", return_value=True) as key:
            self.assertEqual(med._tick_main_line(frame), LoopAction.Continue)
        key.assert_called_once_with("F2", "HitchPostBossReturnOwnBase")
        self.assertEqual(med._post_game_route, "heirloom")

        with patch.object(med, "_post_game_state", return_value="NPC_HUB"), \
             patch.object(med, "_post_game_hub_entry_click", return_value=heirloom_entry), \
             patch.object(med, "act_click", return_value=True) as click:
            self.assertEqual(med._tick_main_line(frame), LoopAction.Continue)
        click.assert_called_once_with(heirloom_entry, "OpenHeirloomChallenges")
        self.assertEqual(med._post_game_route, "heirloom_active")

        # A successful card click only starts observation; it cannot close the
        # panel or enter team_wait_exit before the result postcondition appears.
        with patch.object(med, "_post_game_state", return_value="HEIRLOOM_DIALOG"), \
             patch.object(med, "_heirloom_boss_result_visible", return_value=False), \
             patch.object(med, "find", return_value=configured_boss), \
             patch.object(med, "act_click", return_value=True) as click:
            self.assertEqual(med._tick_main_line(frame), LoopAction.Continue)
        click.assert_called_once_with(configured_boss, "BossConfigured")
        self.assertEqual(med._post_game_route, "heirloom_active")
        self.assertTrue(med._post_game_pending)

        with patch.object(med, "_post_game_state", return_value="HEIRLOOM_DIALOG"), \
             patch.object(med, "_heirloom_boss_result_visible", return_value=False), \
             patch.object(med, "act_click") as click:
            self.assertEqual(med._tick_main_line(frame), LoopAction.Continue)
        click.assert_not_called()
        self.assertEqual(med._post_game_route, "heirloom_active")

        with patch.object(med, "_post_game_state", return_value="HEIRLOOM_DIALOG"), \
             patch.object(med, "_heirloom_boss_result_visible", return_value=True), \
             patch.object(med, "_find_heirloom_close", return_value=close), \
             patch.object(med, "act_click", return_value=True) as click:
            self.assertEqual(med._tick_main_line(frame), LoopAction.Continue)
        click.assert_called_once_with(close, "DismissHeirloomDialog")
        self.assertEqual(med._post_game_route, "boss_active")
        self.assertFalse(med._post_game_pending)
        self.assertIsNotNone(med._hitch_heirloom_exit_since)

        with patch.object(med, "_post_game_state", return_value="POST_VICTORY"), \
             patch.object(med, "_heirloom_loot_popup_visible", return_value=False), \
             patch.object(med, "act_click") as click:
            self.assertEqual(med._tick_main_line(frame), LoopAction.Continue)
        click.assert_not_called()
        self.assertEqual(med.phase, Phase.QUIT)

    def test_live_heirloom_loot_shape_is_three_aligned_green_status_rows(self):
        """The right-side live loot list is accepted; a lone green HUD row is not."""
        med = Mediator(Settings(dry_run=True, ocr_mode="off"), ROOT)
        image = np.zeros((900, 1600, 3), dtype=np.uint8)
        for y in (230, 300, 370):
            for x in (1195, 1208, 1221):
                cv2.rectangle(image, (x, y), (x + 9, y + 7), (0, 220, 0), -1)
        with patch.object(med, "find", return_value=None):
            self.assertTrue(med._heirloom_loot_popup_visible(Frame(image)))

        image[300:] = 0
        with patch.object(med, "find", return_value=None):
            self.assertFalse(med._heirloom_loot_popup_visible(Frame(image)))

    def test_follow_heirloom_victory_exits_without_secret_realm(self):
        med = Mediator(
            Settings(mode_id="follow_team", auto_secret_realm=False, cjb_boss="01暴掠龙"),
            ROOT,
        )
        med.set_phase(Phase.MAIN_LINE, "follow heirloom victory")
        med._post_game_route = "boss_active"
        med._hitch_heirloom_exit_since = time.time()
        frame = load_fixture_frame("fixtures/replay/victory_continue.png")
        with patch.object(med, "_heirloom_loot_popup_visible", return_value=False), \
             patch.object(med, "act_click") as click:
            action = med._tick_main_line(frame)
        self.assertEqual(action, LoopAction.Continue)
        self.assertEqual(med.phase, Phase.QUIT)
        click.assert_not_called()

    def test_follow_heirloom_victory_continues_to_secret_realm(self):
        med = Mediator(
            Settings(mode_id="follow_team", auto_secret_realm=True, cjb_boss="01暴掠龙"),
            ROOT,
        )
        med.set_phase(Phase.MAIN_LINE, "follow heirloom then secret")
        med._post_game_route = "boss_active"
        med._hitch_heirloom_exit_since = time.time()
        frame = load_fixture_frame("fixtures/replay/victory_continue.png")
        with patch.object(med, "_heirloom_loot_popup_visible", return_value=False), \
             patch.object(med, "act_click", return_value=True) as click:
            action = med._tick_main_line(frame)
        self.assertEqual(action, LoopAction.Continue)
        self.assertEqual(med.phase, Phase.MAIN_LINE)
        self.assertTrue(med._post_game_pending)
        self.assertEqual(med._post_game_route, "secret")
        click.assert_called_once()
        self.assertEqual(click.call_args.args[1], "ContinueGame")

    def test_follow_heirloom_loot_waits_for_victory_when_secret_is_enabled(self):
        med = Mediator(Settings(mode_id="follow_team", auto_secret_realm=True), ROOT)
        med.set_phase(Phase.MAIN_LINE, "follow heirloom loot")
        med._hitch_heirloom_exit_since = time.time()
        frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), hwnd=10001)
        with patch.object(med, "_post_game_state", return_value=None), \
             patch.object(med, "_heirloom_loot_popup_visible", return_value=True), \
             patch.object(med, "act_click") as click, \
             patch.object(med, "act_key") as key:
            action = med._tick_main_line(frame)
        self.assertEqual(action, LoopAction.Continue)
        self.assertEqual(med.phase, Phase.MAIN_LINE)
        self.assertTrue(med._passenger_heirloom_for_secret)
        self.assertIsNone(med._hitch_heirloom_exit_since)
        click.assert_not_called()
        key.assert_not_called()

    def test_all_team_modes_route_boss_postgame_to_unified_wait(self):
        frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), hwnd=10001)
        for mode in ("lobby_hitch", "follow_team", "lead_team", "lead"):
            with self.subTest(mode=mode):
                med = Mediator(Settings(mode_id=mode), ROOT)
                med._post_game_route = "boss_postgame"
                med._hitch_pressure_transferred = True  # P0 门禁已通过（8159de8）
                med._post_game_pending = True
                with patch.object(med, "_post_game_state", return_value="NPC_HUB"), \
                     patch.object(med, "act_key", return_value=True) as key:
                    action = med._tick_main_line(frame)
                self.assertEqual(action, LoopAction.Continue)
                key.assert_called_once_with("F2", "HitchPostBossReturnOwnBase")
                self.assertEqual(med._post_game_route, "team_wait_exit")

    def test_team_wait_exit_uses_shadow_predict_and_requires_two_leave_confirmations(self):
        med = Mediator(Settings(mode_id="follow_team"), ROOT)
        frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), hwnd=10001)
        client = MagicMock()
        client.shadow_predict.return_value = MagicMock(status="ok", raw_text="队友退出游戏")
        med._ocr_client = client

        assert med._team_post_game_player_left(frame, 1.0) is False
        assert med._team_post_game_player_left(frame, 2.0) is True

        assert client.shadow_predict.call_count == 2
        client.ocr.assert_not_called()
        slot = client.shadow_predict.call_args.args[2]
        assert slot["kind"] == "text"
        assert slot["bbox"] == client.shadow_predict.call_args.kwargs["panel_bbox"]

    def test_team_wait_exit_holds_zero_input_until_evidence_or_hard_timeout(self):
        med = Mediator(Settings(mode_id="lead_team"), ROOT)
        med.set_phase(Phase.MAIN_LINE, "team post-game")
        med._post_game_pending = True
        med._post_game_route = "team_wait_exit"
        frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), hwnd=10001)

        with patch.object(med, "_post_game_state", return_value="NPC_HUB"), \
             patch.object(med, "_team_post_game_player_left", return_value=False), \
             patch.object(med, "act_click") as click, \
             patch.object(med, "act_key") as key:
            action = med._tick_main_line(frame)

        self.assertEqual(action, LoopAction.Continue)
        self.assertEqual(med.phase, Phase.MAIN_LINE)
        click.assert_not_called()
        key.assert_not_called()

        med._post_game_hub_entered_at = 0.0
        with patch("shuabao.mediator.time.time", return_value=180.0), \
             patch.object(med, "_post_game_state", return_value="NPC_HUB"), \
             patch.object(med, "_team_post_game_player_left", return_value=False):
            action = med._tick_main_line(frame)

        self.assertEqual(action, LoopAction.Continue)
        self.assertEqual(med.phase, Phase.QUIT)

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

    def test_heirloom_route_clicks_the_label_even_if_plaza_is_unclassified(self):
        """H 实机：局内/广场未判成 NPC_HUB 时，仍要点传家宝标签开弹窗。"""
        med = Mediator(Settings(cjb_boss="18乌索克"), ROOT)
        med.set_phase(Phase.MAIN_LINE, "heirloom label")
        med._post_game_pending = True
        med._post_game_route = "heirloom"
        frame = load_fixture_frame("fixtures/replay/main_line_auto_on.png")
        entry = MatchResult("chuanjiabao", 0.80, 1000, 340, 80, 24, 1040, 352)

        with patch.object(med, "_post_game_state", return_value=None), \
             patch.object(med, "_post_game_hub_entry_click", return_value=entry), \
             patch.object(med, "_find_failure_gift", return_value=None), \
             patch.object(med, "_maybe_click_tqtz", return_value=None), \
             patch.object(med, "_tick_early_challenge", return_value=None), \
             patch.object(med, "act_click", return_value=True) as click:
            action = med._tick_main_line(frame)

        self.assertEqual(action, LoopAction.Continue)
        click.assert_called_once_with(entry, "OpenHeirloomChallenges")
        self.assertEqual(med._post_game_route, "heirloom_active")

    def test_hitch_hub_closes_open_bag_before_heirloom_npc(self):
        """广场上背包还开着时先关背包，不点传家宝 NPC。"""
        from shuabao.policy.public_bag import BagLayout, PublicBagPhase

        med = Mediator(Settings(mode_id="lobby_hitch", cjb_boss="54莫阿姆"), ROOT)
        med.set_phase(Phase.MAIN_LINE, "hub bag")
        med._hitch_pressure_transferred = True
        med._post_game_pending = True
        med._post_game_route = "heirloom"
        frame = load_fixture_frame("fixtures/replay/challenge_npc_hub.png")
        layout = BagLayout(670.0, 82.0, 1.0)
        button = MatchResult("bag/bag_toggle_button", 1.0, 1520, 746, 0, 0, 1520, 746)
        entry = MatchResult("post_game_heirloom_npc", 0.64, 1000, 340, 100, 30, 1050, 350)

        with patch.object(med, "_post_game_state", return_value="NPC_HUB"), \
             patch.object(med, "_bag_layout", return_value=layout), \
             patch.object(med, "_hud_hotkey_button", return_value=button), \
             patch.object(med, "_post_game_hub_entry_click", return_value=entry), \
             patch.object(med, "_find_failure_gift", return_value=None), \
             patch.object(med, "_hitch_ocr_text", return_value=""), \
             patch.object(med, "act_click", return_value=True) as click:
            action = med._tick_main_line(frame)

        self.assertEqual(action, LoopAction.Continue)
        click.assert_called_once_with(button, "PublicBackpackClose")
        self.assertEqual(med._post_game_route, "heirloom")
        self.assertIs(med._public_bag_fsm.phase, PublicBagPhase.CLOSE_REQUESTED)

    def test_heirloom_hub_roi_covers_the_in_game_chuanjiabao_label(self):
        """局内传家宝挑战标签 (1016,205) 宽 116，旧 ROI 右缘 0.65 会裁掉。"""
        roi = Mediator._POST_GAME_HUB_ENTRY_ROIS["heirloom"]
        w, h = 1600, 900
        x, y, label_w = 1016, 205, 116
        self.assertLessEqual(w * roi[0], x)
        self.assertGreaterEqual(w * roi[2], x + label_w)
        self.assertLessEqual(h * roi[1], y)
        self.assertGreaterEqual(h * roi[3], y)

    def test_live_hitch_ingame_frame_finds_bag_toggle_and_heirloom_label(self):
        """20260910 18:31 K 起始帧：探针门禁当时把这两个 0.88+ 命中全挡掉了。"""
        path = Path(
            r"C:\Users\10639\AppData\Local\Temp\shuabao-captures"
            r"\public_backpack_deposit_20260910_183126_428426\frames\f0000_state_change.png"
        )
        if not path.is_file():
            self.skipTest("live K start frame not on disk")
        image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertIsNotNone(image)
        frame = Frame(image, left=315, top=59, hwnd=1, window_title="英雄三国KK", role="l1")
        med = Mediator(Settings(mode_id="lobby_hitch", dry_run=True, ocr_mode="off"), ROOT)
        toggle = med._hud_hotkey_button(frame, "bag/bag_toggle_button")
        heirloom = med._find_post_game_hub_entry(frame, "heirloom")
        self.assertIsNotNone(toggle)
        self.assertIsNotNone(heirloom)
        self.assertTrue(med._public_bag_surface_ok(frame))
        self.assertGreaterEqual(heirloom.score, 0.80)

    def test_team_archive_without_heirloom_routes_to_heirloom_fallback(self):
        med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
        med.set_phase(Phase.MAIN_LINE, "team archive route")
        med._hitch_pressure_transferred = True  # P0 门禁已通过（8159de8）
        med._post_game_pending = True
        med._archive_challenge_index = len(med._ARCHIVE_CHALLENGE_NAMES)
        med._time_cave_boss_done = True  # isolate the post-archive route choice
        med._post_game_route = "archive"
        frame = load_fixture_frame("fixtures/replay/archive_challenge_panel.png")
        close = MatchResult("archive_panel_close", 0.99, 976, 197, 43, 31, 997, 212)

        with patch.object(med, "_post_game_state", return_value="ARCHIVE_PANEL"), \
             patch.object(med, "_maybe_click_archive_challenge", return_value=None), \
             patch.object(med, "_find_archive_panel_close", return_value=close), \
             patch.object(med, "act_key", return_value=True), \
             patch.object(med, "act_click", return_value=True):
            med._tick_main_line(frame)
            action = med._tick_main_line(frame)

        self.assertEqual(action, LoopAction.Continue)
        self.assertEqual(med._post_game_route, "heirloom")

    def test_victory_continue_retry_limit_fails_closed(self):
        """3 failed continue attempts must Fail-Closed into ERROR."""
        # lab 不属于无人值守模式，仍走 Fail-Closed；normal_farm 的零输入不停机见 test_unattended_recovery_20260914。
        self.settings = Settings(mode_id="lab")
        self.med = Mediator(self.settings, ROOT)
        self.med.set_phase(Phase.MAIN_LINE, "p1b0 setup")
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


    def test_archive_chain_end_to_end_fallback_flow(self):
        """Verify the complete post-game fallback chain: archive cards -> time-cave boss -> close -> heirloom boss -> close."""
        med = Mediator(Settings(sgzx_boss="55吞咽者布鲁", cjb_boss="55吞咽者布鲁"), ROOT)
        med.set_phase(Phase.MAIN_LINE, "e2e chain")
        med._post_game_pending = True
        med._post_game_route = "archive"

        frame_archive = load_fixture_frame("fixtures/replay/archive_challenge_panel.png")
        for index in range(8):
            col, row = index % 4, index // 4
            cx = int(frame_archive.width * med._ARCHIVE_CHALLENGE_X[col])
            cy = int(frame_archive.height * med._ARCHIVE_CHALLENGE_Y[row])
            frame_archive.bgr[
                int(cy - frame_archive.height * 0.035):int(cy + frame_archive.height * 0.060),
                int(cx - frame_archive.width * 0.040):int(cx + frame_archive.width * 0.040),
            ] = (0, 255, 0)

        boss_target = MatchResult("33玛格曼达", 0.85, 1075, 453, 51, 51, 1075, 453)
        close_target = MatchResult("archive_panel_close", 0.99, 976, 197, 43, 31, 997, 212)

        bottom_calls = {"n": 0}

        def at_bottom(_frame, _post_game=None):
            # Two scrolls, then the list is at bottom for the fallback click and
            # any post-click relocate ticks (time-cave deadlock recovery).
            bottom_calls["n"] += 1
            return bottom_calls["n"] >= 3

        # Production post-confirm requires two *distinct* Frame instances with
        # no Boss cards (convergence only; not challenge acceptance). Reusing
        # one Frame object can never raise _time_cave_boss_clear_frames past 1.
        master_bgr = frame_archive.bgr.copy()

        def next_tick_frame(clicked: bool) -> Frame:
            if clicked:
                # Synthetic zero-card unit input (black frame). Not a loot
                # popup and not live-machine evidence.
                return Frame(
                    np.zeros_like(master_bgr),
                    window_title="英雄三国KK",
                    hwnd=10001,
                )
            return Frame(
                master_bgr.copy(),
                window_title="英雄三国KK",
                hwnd=10001,
            )

        with patch.object(med, "_post_game_state", return_value="ARCHIVE_PANEL"), \
             patch.object(med, "act_scroll", return_value=True) as scroll, \
             patch.object(med, "_post_game_boss_list_at_bottom", side_effect=at_bottom), \
             patch.object(med, "_find_last_recognized_post_game_boss", return_value=boss_target), \
             patch.object(med, "_find_archive_panel_close", return_value=close_target), \
             patch.object(med, "act_click", return_value=True) as click:
            for _ in range(8):
                clicked = getattr(med, "_time_cave_boss_clicked_at", None) is not None
                med._tick_main_line(next_tick_frame(clicked))
                med._boss_challenge_next_at = 0.0
                if med._time_cave_boss_done:
                    break
            self.assertTrue(med._time_cave_boss_done)
            self.assertFalse(med._time_cave_boss_result_confirmed)
            self.assertTrue(med._time_cave_boss_confirm_unconfirmed)
            self.assertIsNone(med._time_cave_boss_clicked_at)
            med._tick_main_line(next_tick_frame(False))
            self.assertEqual(med._post_game_route, "heirloom")

        self.assertEqual(scroll.call_count, 2)
        self.assertGreaterEqual(click.call_count, 1)


if __name__ == "__main__":
    unittest.main()


class PostGameBossRouteTests(unittest.TestCase):
    """时光之穴 Boss 列表滚动 + 传家宝 Boss「已挑战」后置确认。"""

    def _med(self):
        med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
        med.settings.sgzx_boss = "53拉贾克斯将军"
        med.settings.cjb_boss = "18乌索克"
        med._post_game_pending = True
        return med

    @staticmethod
    def _frame():
        return Frame(np.zeros((900, 1600, 3), dtype=np.uint8), hwnd=10001)

    # ---- 时光之穴：ARCHIVE_PANEL 右侧列表 ----------------------------------

    def test_archive_boss_list_scrolls_inside_its_own_roi(self):
        """列表锚点已授权滚动时，滚轮必须落在存档面板右侧列表内。

        本用例验证「已经获得列表卡片锚点」时的滚动 ROI，因此显式授权
        `_post_game_boss_list_alive=True`。无锚点零滚动由
        `tests/test_boss_challenge_20260922.py` 覆盖，此处不重复业务判断。
        """
        med = self._med()
        frame = self._frame()
        roi = med._POST_GAME_BOSS_ROIS["ARCHIVE_PANEL"]
        with patch.object(med, "_post_game_state", return_value="ARCHIVE_PANEL"), \
             patch.object(med, "find", return_value=None), \
             patch.object(med, "_post_game_boss_list_alive", return_value=True), \
             patch.object(med, "_post_game_boss_list_at_bottom", return_value=False), \
             patch.object(med, "_find_last_recognized_post_game_boss", return_value=None), \
             patch.object(med, "act_scroll", return_value=True) as scroll, \
             patch.object(med, "act_click") as click:
            self.assertEqual(
                med._maybe_challenge_configured_boss(frame, 100.0), LoopAction.Continue
            )
        scroll.assert_called_once()
        x, y, clicks, reason = scroll.call_args.args
        self.assertEqual(reason, "BossConfigured-scroll")
        self.assertLess(clicks, 0, "必须向下滚动")
        self.assertTrue(
            frame.width * roi[0] <= x <= frame.width * roi[2], f"滚动点 x={x} 落在列表 ROI 外"
        )
        self.assertTrue(
            frame.height * roi[1] <= y <= frame.height * roi[3], f"滚动点 y={y} 落在列表 ROI 外"
        )
        click.assert_not_called()

    def test_archive_boss_scroll_is_bounded_and_does_not_burn_click_budget(self):
        """列表锚点已授权滚动时，滚动预算独立且有界，滚完还没找到也不许乱点。

        显式授权 `_post_game_boss_list_alive=True`：纯黑无锚点帧上不得期望
        滚动（那是 fail-closed 路径，由 `test_boss_challenge_20260922.py` 覆盖）。
        """
        med = self._med()
        frame = self._frame()
        with patch.object(med, "_post_game_state", return_value="ARCHIVE_PANEL"), \
             patch.object(med, "find", return_value=None), \
             patch.object(med, "_post_game_boss_list_alive", return_value=True), \
             patch.object(med, "_post_game_boss_list_at_bottom", return_value=False), \
             patch.object(med, "_find_last_recognized_post_game_boss", return_value=None), \
             patch.object(med, "act_scroll", return_value=True) as scroll, \
             patch.object(med, "act_click") as click:
            now = 100.0
            for _ in range(med._POST_GAME_BOSS_SCROLL_LIMIT + 2):
                med._maybe_challenge_configured_boss(frame, now)
                now = med._boss_challenge_next_at + 0.1
        self.assertEqual(scroll.call_count, med._POST_GAME_BOSS_SCROLL_LIMIT)
        click.assert_not_called()

    def test_bottom_detection_requires_two_scrollbar_frames_after_a_scroll(self):
        """Only the isolated bottom thumb, never dynamic list pixels, authorizes fallback."""
        med = self._med()
        med._boss_challenge_scroll_attempts = 1
        image = np.zeros((900, 1600, 3), dtype=np.uint8)
        image[430:500, 1347:1353] = 204
        frame = Frame(image, hwnd=10001)
        self.assertFalse(med._post_game_boss_list_at_bottom(frame, "ARCHIVE_PANEL"))
        self.assertTrue(med._post_game_boss_list_at_bottom(frame, "ARCHIVE_PANEL"))

    def test_scroll_limit_ends_after_bounded_unresolved_observations(self):
        med = self._med()
        med._boss_challenge_scroll_attempts = med._POST_GAME_BOSS_SCROLL_LIMIT
        frame = self._frame()
        with patch.object(med, "_post_game_state", return_value="ARCHIVE_PANEL"), \
             patch.object(med, "find", return_value=None), \
             patch.object(med, "_post_game_boss_list_at_bottom", return_value=False), \
             patch.object(med, "act_move", return_value=True):
            for t in range(1, 9):
                self.assertIs(med._maybe_challenge_configured_boss(frame, float(t)), LoopAction.Continue)
        self.assertNotEqual(med.phase, Phase.ERROR)
        self.assertTrue(med._time_cave_boss_done)
        self.assertFalse(med.stop_signal.is_set())

    def test_compact_boss_scales_cover_the_shrunken_cards(self):
        """战后卡片被缩到 58~70px；尺度阶梯必须罩住这一档。"""
        scales = Mediator._POST_GAME_BOSS_SCALES
        self.assertLessEqual(min(scales), 0.40, "缺少足够小的尺度，缩小卡会漏匹配")
        self.assertGreaterEqual(max(scales), 0.80)
        ordered = sorted(scales)
        gaps = [round(b - a, 3) for a, b in zip(ordered, ordered[1:])]
        self.assertLessEqual(max(gaps), 0.10, f"尺度阶梯出现空档：{gaps}")
        self.assertLess(
            Mediator._POST_GAME_BOSS_MATCH_THRESHOLD,
            0.70,
            "缩小卡的匹配度低于常规阈值，战后专用阈值必须更低",
        )

    def test_archive_boss_click_waits_for_time_cave_route_confirmation(self):
        med = self._med()
        frame = self._frame()
        hit = MatchResult("boss/53拉贾克斯将军", 0.9, 1200, 400, 60, 60, 1200, 400)
        with patch.object(med, "_post_game_state", return_value="ARCHIVE_PANEL"), \
             patch.object(med, "find", return_value=hit), \
             patch.object(med, "act_click", return_value=True) as click:
            med._maybe_challenge_configured_boss(frame, 100.0)
        click.assert_called_once_with(hit, "BossConfigured")
        self.assertFalse(med._time_cave_boss_done)
        self.assertEqual(med._time_cave_boss_clicked_at, 100.0)

    # ---- 传家宝：HEIRLOOM_DIALOG 后置确认 ----------------------------------

    def test_heirloom_boss_click_records_the_confirm_window(self):
        med = self._med()
        frame = self._frame()
        hit = MatchResult("chuanjiaobao/18乌索克", 0.9, 700, 400, 60, 60, 700, 400)
        with patch.object(med, "_post_game_state", return_value="HEIRLOOM_DIALOG"), \
             patch.object(med, "find", return_value=hit), \
             patch.object(med, "act_click", return_value=True) as click:
            med._maybe_challenge_configured_boss(frame, 100.0)
        click.assert_called_once_with(hit, "BossConfigured")
        self.assertEqual(med._post_game_route, "heirloom_active")
        self.assertEqual(med._heirloom_boss_clicked_at, 100.0)
        self.assertFalse(med._heirloom_boss_confirm_unconfirmed)

    def test_heirloom_result_toast_is_found_across_the_lower_band(self):
        """旧版只认帧正中 9%x6% 的窄条；飘几个百分点就落空并永久挂起。"""
        med = self._med()
        for cx, cy in ((0.42, 0.56), (0.50, 0.62), (0.60, 0.70)):
            frame = self._frame()
            x = int(frame.width * cx)
            y = int(frame.height * cy)
            frame.bgr[y:y + 18, x:x + 90] = (40, 40, 230)  # red 已挑战 toast
            self.assertTrue(
                med._heirloom_boss_result_visible(frame),
                f"toast at ({cx}, {cy}) 未被识别",
            )

    def test_scattered_combat_red_is_not_a_result_toast(self):
        med = self._med()
        frame = self._frame()
        rng = np.random.default_rng(3)
        for _ in range(400):
            x = int(rng.integers(int(frame.width * 0.35), int(frame.width * 0.65)))
            y = int(rng.integers(int(frame.height * 0.53), int(frame.height * 0.73)))
            frame.bgr[y, x] = (40, 40, 230)
        self.assertFalse(med._heirloom_boss_result_visible(frame))

    def test_heirloom_wait_is_bounded_and_never_claims_success(self):
        """点击已发出但后置一直不出现时，必须有界收敛，且不得记成成功。"""
        med = self._med()
        frame = self._frame()
        med._boss_challenge_attempts = 1
        med._heirloom_boss_clicked_at = 100.0

        with patch.object(med, "_post_game_state", return_value="HEIRLOOM_DIALOG"), \
             patch.object(med, "_heirloom_boss_result_visible", return_value=False), \
             patch.object(med, "act_click") as click:
            inside = med._maybe_challenge_configured_boss(frame, 100.0 + 1.0)
            self.assertEqual(inside, LoopAction.Continue)
            self.assertFalse(med._heirloom_boss_confirm_unconfirmed, "窗口内不得提前放弃")

            expired = med._maybe_challenge_configured_boss(
                frame, 100.0 + med._HEIRLOOM_BOSS_CONFIRM_TIMEOUT_S + 0.1
            )
            self.assertEqual(expired, LoopAction.Continue)
        self.assertTrue(med._heirloom_boss_confirm_unconfirmed, "超时必须记为未确认")
        click.assert_not_called()

    def test_heirloom_confirm_window_survives_more_than_one_tick(self):
        """实测 1.64s/tick：确认窗必须覆盖至少三帧新证据。"""
        self.assertGreaterEqual(Mediator._HEIRLOOM_BOSS_CONFIRM_TIMEOUT_S, 3.0 * 1.64)

    def test_expired_confirm_is_ignored_when_no_click_was_sent(self):
        med = self._med()
        self.assertFalse(med._heirloom_boss_confirm_expired(1.0e9))
        self.assertFalse(med._heirloom_boss_confirm_unconfirmed)
