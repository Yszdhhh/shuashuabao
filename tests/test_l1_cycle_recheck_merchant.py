import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gamescript.loop_action import LoopAction
from gamescript.mediator import ChallengeState, Mediator
from gamescript.settings import Settings
from gamescript.vision.capture import Frame
from gamescript.vision.matcher import MatchResult


def hit(name: str, x: int = 100, y: int = 100) -> MatchResult:
    return MatchResult(name, 0.95, x, y, 30, 30, x, y)


class L1CycleRecheckMerchantTests(unittest.TestCase):
    def setUp(self):
        self.med = Mediator(Settings(), ROOT)
        self.frame = Frame(
            np.zeros((900, 1600, 3), dtype=np.uint8),
            window_title="game",
            hwnd=1,
        )

    def test_panel_cycle_advances_only_after_an_empty_owned_episode(self):
        self.med._l1_cycle_step = "skill"
        self.med._panel_kind = "skill"
        self.med._l1_cycle_owned_panel = True
        self.med._l1_cycle_selected = True
        self.med._finish_panel_episode()
        self.assertEqual(self.med._l1_cycle_step, "skill")

        self.med._panel_kind = "skill"
        self.med._l1_cycle_owned_panel = True
        self.med._l1_cycle_selected = False
        self.med._finish_panel_episode()
        self.assertEqual(self.med._l1_cycle_step, "bond")

    def test_background_cycle_uses_inventory_pickup_merchant_then_artifact(self):
        self.assertEqual(
            self.med._L1_CYCLE_ORDER,
            ("skill", "bond", "treasure", "evolve", "equipment", "pickup", "merchant", "artifact"),
        )

        self.med._l1_cycle_step = "pickup"
        self.med._auto_task_done = True
        self.med._main_line_started_at = 1.0
        with patch.object(self.med, "_post_game_state", return_value=None), \
                patch.object(self.med, "find", return_value=None), \
                patch.object(self.med, "_find_equipment_affix_choice", return_value=None), \
                patch.object(self.med, "_selection_anchor", return_value=None), \
                patch.object(self.med, "_ensure_auto_task_enabled", return_value=None), \
                patch.object(self.med, "_ensure_challenge_buttons", return_value=None), \
                patch.object(self.med, "_find_stage_page", return_value=False), \
                patch.object(self.med, "_handle_self_opened_compact_panel", return_value=None), \
                patch.object(self.med, "_maybe_open_choice_panel", return_value=None), \
                patch.object(self.med, "act_key", return_value=True) as key:
            self.assertIs(self.med._tick_main_line(self.frame), LoopAction.Continue)
        key.assert_called_once_with("z", "Pickup-Z")
        self.assertEqual(self.med._l1_cycle_step, "merchant")

    def test_legacy_five_episode_cap_no_longer_starves_rest_of_game(self):
        self.med._l1_cycle_step = "skill"
        self.med._panel_episode_count["skill"] = 5
        with patch.object(self.med, "act_click") as click:
            result = self.med._maybe_open_choice_panel(self.frame, anchor=None)
        self.assertEqual(result, LoopAction.Continue)
        self.assertEqual(self.med._panel_episode_count["skill"], 0)
        self.assertEqual(self.med._l1_cycle_step, "bond")
        click.assert_not_called()

        self.med._l1_cycle_step = "skill"
        with patch.object(self.med, "act_click", return_value=True) as click:
            result = self.med._maybe_open_choice_panel(self.frame, anchor=None)
        self.assertEqual(result, LoopAction.Continue)
        click.assert_called_once()

    def test_periodic_auto_task_off_starts_fresh_repair_episode(self):
        toggle = hit("auto_task_toggle", 1450, 530)
        self.med._auto_task_done = True
        self.med._auto_task_recheck_at = time.time() - 1.0
        with patch.object(
            self.med,
            "_auto_task_state_detail",
            return_value=("OFF", toggle, 0.1, 0.95),
        ), patch.object(
            self.med, "_auto_task_state", return_value=("OFF", toggle)
        ), patch.object(
            self.med, "_find_auto_task_toggle", return_value=toggle
        ), patch.object(
            self.med, "act_click", return_value=True
        ) as click:
            result = self.med._ensure_auto_task_enabled(self.frame)
        self.assertEqual(result, LoopAction.Continue)
        self.assertFalse(self.med._auto_task_done)
        self.assertEqual(self.med._auto_task_attempts, 1)
        self.assertIsNotNone(self.med._auto_task_pending_since)
        click.assert_called_once()

    def test_periodic_challenge_off_rearms_only_that_toggle(self):
        keys = (
            "coin_challenge",
            "wood_challenge",
            "experience_challenge",
            "treasure_challenge",
        )
        self.med._challenge_done.update(keys)
        future = time.time() + 1000
        self.med._challenge_recheck_at = {key: future for key in keys}
        self.med._challenge_recheck_at["coin_challenge"] = time.time() - 1.0
        label = hit("coin_challenge", 150, 650)
        click_hit = hit("coin_challenge", 150, 650)
        with patch.object(
            self.med, "_find_challenge_button", return_value=(label, click_hit)
        ), patch.object(
            self.med, "_resolve_challenge_state", return_value=ChallengeState.OFF
        ), patch.object(
            self.med, "_challenge_green_count", return_value=0
        ), patch.object(
            self.med, "act_right_click", return_value=True
        ) as right_click:
            result = self.med._ensure_challenge_buttons(self.frame)
        self.assertEqual(result, LoopAction.Continue)
        self.assertNotIn("coin_challenge", self.med._challenge_done)
        self.assertEqual(self.med._challenge_attempts["coin_challenge"], 1)
        self.assertIsNotNone(self.med._challenge_pending_since["coin_challenge"])
        right_click.assert_called_once()

    def test_real_strip_fixture_is_a_merchant_anchor(self):
        path = ROOT / "fixtures" / "replay" / "black_merchant_card_strip.png"
        strip = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        canvas = np.zeros((900, 1600, 3), dtype=np.uint8)
        canvas[603 : 603 + strip.shape[0], 1120 : 1120 + strip.shape[1]] = strip
        frame = Frame(canvas, window_title="game", hwnd=1)
        self.assertTrue(self.med._black_merchant_present(frame))
        self.assertTrue(self.med._merchant_refresh_available(frame))
        wood = self.med.find(
            frame,
            ["merchant_wood", "woodgift"],
            threshold=0.72,
            scales=(0.75, 0.9, 1.0, 1.1, 1.25),
            roi=(0.70, 0.67, 0.90, 0.79),
        )
        self.assertIsNotNone(wood)
        self.assertEqual(wood.name, "merchant_wood")

    def test_merchant_prefers_pill_then_wood_and_refreshes_when_neither_exists(self):
        pill = hit("danGif", 1160, 640)
        wood = hit("woodgift", 1280, 650)

        def find_known(_frame, names, **_kwargs):
            return pill if names == ["danGif"] else wood

        with patch.object(self.med, "_black_merchant_present", return_value=True), patch.object(
            self.med, "_bond_bar_nonempty", return_value=True
        ), patch.object(self.med, "find", side_effect=find_known), patch.object(
            self.med, "act_click", return_value=True
        ) as click:
            result = self.med._maybe_black_merchant(self.frame)
        self.assertEqual(result, LoopAction.Continue)
        self.assertEqual(click.call_args.args[1], "BlackMerchant-swallow_pill")

        self.med._merchant_next_at = 0.0
        with patch.object(self.med, "_black_merchant_present", return_value=True), patch.object(
            self.med, "_bond_bar_nonempty", return_value=False
        ), patch.object(self.med, "find", return_value=None), patch.object(
            self.med, "_merchant_refresh_available", return_value=True
        ), patch.object(self.med, "act_click", return_value=True) as click:
            result = self.med._maybe_black_merchant(self.frame)
        self.assertEqual(result, LoopAction.Continue)
        self.assertEqual(click.call_args.args[1], "BlackMerchant-refresh")


if __name__ == "__main__":
    unittest.main()
