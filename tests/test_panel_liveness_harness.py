"""Stage 2B0 panel timeout/cooldown/reopen liveness harness.

This harness drives the real panel FSM with the existing FakeClock,
FakeInputExecutor, and ActionProbe.  It deliberately keeps the panel anchor
present in the natural-panel case: a cooldown is only considered safe when the
FSM remains responsible for the still-obscuring UI, not when main-line work is
allowed to continue around it.
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
from shuabao.mediator import Mediator, PanelState, Phase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult
from tests.test_scenario_replay import ActionProbe, FakeClock, FakeInputExecutor


def _frame() -> Frame:
    return Frame(
        np.zeros((900, 1600, 3), dtype=np.uint8),
        window_title="英雄三国KK",
        hwnd=10001,
    )


def _mediator(clock: FakeClock, *, limit: int = 2) -> tuple[Mediator, Frame]:
    settings = Settings(dry_run=True)
    settings.panel_episode_limit_per_kind = limit
    settings.panel_visible_timeout_s = 0.5
    settings.panel_hard_deadline_s = 1.0
    settings.ui_action_interval_s = 0.1
    settings.round_timeout_s = 20
    med = Mediator(settings, ROOT)
    med.executor = FakeInputExecutor(med.stop_signal, clock)
    frame = _frame()
    med._last_frame = frame
    return med, frame


class PanelLivenessHarnessTests(unittest.TestCase):
    def test_invisible_open_timeout_cannot_reopen_same_kind_after_failure_cap(self) -> None:
        """Only the abnormal OPEN_REQUESTED→WAIT_VISIBLE timeout is budgeted."""
        clock = FakeClock(start=100.0)
        med, frame = _mediator(clock)
        med._l1_cycle_step = "skill"
        med._choice_target = "skill"
        probe = ActionProbe(med)

        with clock.install(), patch.object(med, "_selection_anchor", return_value=None), \
                patch.object(med, "_bond_base_progress_pending", return_value=False):
            for expected_count in (1, 2):
                self.assertIs(med._maybe_open_choice_panel(frame), LoopAction.Continue)
                self.assertIs(med._panel_state, PanelState.OPEN_REQUESTED)
                self.assertEqual(med._panel_episode_count.get("skill", 0), expected_count - 1)

                # Advance the real FSM through the visible wait timeout.
                self.assertIs(
                    med._tick_panel_fsm(frame, None, clock.now()),
                    LoopAction.Continue,
                )
                self.assertIs(med._panel_state, PanelState.WAIT_VISIBLE)
                clock.advance(0.6)
                self.assertIs(
                    med._tick_panel_fsm(frame, None, clock.now()),
                    LoopAction.Continue,
                )
                self.assertIs(med._panel_state, PanelState.COOLDOWN)
                self.assertEqual(med._panel_episode_count["skill"], expected_count)

                # The normal short cooldown expires, allowing the next
                # episode to prove that the count survives episode cleanup.
                clock.advance(0.2)
                self.assertIsNone(med._tick_panel_fsm(frame, None, clock.now()))
                self.assertIs(med._panel_state, PanelState.CLOSED)

            # The third open attempt does not click.  Solo (Owner 2026-09-15):
            # the cap is a 60s backoff for this panel only -- the cycle moves on
            # instead of parking the whole main line on it.
            self.assertIs(med._maybe_open_choice_panel(frame), LoopAction.Continue)
            self.assertIs(med._panel_state, PanelState.CLOSED)
            self.assertGreaterEqual(med._panel_cooldown_until["skill"], clock.now() + 59.0)
            self.assertEqual(med._l1_cycle_step, "bond", "skill capped -> next step")

            # No hidden reopen of the capped panel before its backoff expires.
            med._choice_target = "skill"
            clock.advance(1.0)
            self.assertIs(med._maybe_open_choice_panel(frame), LoopAction.Continue)
            self.assertIs(med._panel_state, PanelState.CLOSED)

            # After the backoff the panel is tried again.
            clock.advance(70.0)
            self.assertIs(med._maybe_open_choice_panel(frame), LoopAction.Continue)
            self.assertIs(med._panel_state, PanelState.OPEN_REQUESTED)

        reasons = [record.reason for record in probe._records]
        self.assertEqual(reasons, ["OpenSkillPanel", "OpenSkillPanel", "OpenSkillPanel"])

    def test_persistent_natural_anchor_is_not_ignored_after_episode_cap(self) -> None:
        """A still-visible natural panel cannot be bypassed after quarantine."""
        clock = FakeClock(start=200.0)
        med, frame = _mediator(clock)
        anchor = MatchResult("skill_giveup_btn", 0.95, 800, 600, 20, 20, 800, 600)

        with clock.install(), patch.object(med, "_find_reward_choice", return_value=None), \
                patch.object(med, "_close_current_panel", return_value=None), \
                patch.object(med, "_record_fail_closed_incident"):
            for expected_count in (1, 2):
                # High-confidence anchor enters the natural episode in one
                # frame, then the same panel reaches the hard deadline.
                self.assertIs(
                    med._tick_panel_fsm(frame, anchor, clock.now()),
                    LoopAction.Continue,
                )
                self.assertIs(med._panel_state, PanelState.ACTIVE)
                self.assertEqual(med._panel_episode_count.get("skill", 0), expected_count - 1)

                clock.advance(1.1)
                self.assertIs(
                    med._tick_panel_fsm(frame, anchor, clock.now()),
                    LoopAction.Continue,
                )
                self.assertIs(med._panel_state, PanelState.COOLDOWN)
                self.assertEqual(med._panel_episode_count["skill"], expected_count)
                clock.advance(0.2)
                self.assertIsNone(med._tick_panel_fsm(frame, anchor, clock.now()))
                self.assertIs(med._panel_state, PanelState.CLOSED)

            # The anchor is deliberately still present.  Reaching the cap
            # parks the overlay behind a long bounded cooldown (60s) while
            # the panel FSM stays responsible for the covering UI.
            self.assertIs(
                med._tick_panel_fsm(frame, anchor, clock.now()),
                LoopAction.Continue,
            )
            self.assertIs(med._panel_state, PanelState.COOLDOWN)
            self.assertEqual(med._panel_kind, "skill")
            self.assertEqual(med._panel_episode_count["skill"], 2)
            self.assertGreaterEqual(med._panel_cooldown_until["skill"], clock.now() + 59.0)

            clock.advance(1.0)
            self.assertIs(
                med._tick_panel_fsm(frame, anchor, clock.now()),
                LoopAction.Continue,
            )
            self.assertIs(med._panel_state, PanelState.COOLDOWN)

            # After the bounded cooldown expires the FSM resets instead of
            # freezing forever; the episode-count cap still blocks reentry.
            clock.advance(70.0)
            self.assertIsNone(
                med._tick_panel_fsm(frame, anchor, clock.now()),
            )
            self.assertIs(med._panel_state, PanelState.CLOSED)

    def test_normal_successful_panels_do_not_consume_independent_failure_budgets(self) -> None:
        """Normal skill/bond/treasure episodes stay reusable in one round."""
        clock = FakeClock(start=300.0)
        med, frame = _mediator(clock)
        anchor = MatchResult("skill_hide", 0.95, 800, 600, 20, 20, 800, 600)

        with clock.install(), patch.object(med, "_selection_anchor", return_value=None), \
                patch.object(med, "_bond_base_progress_pending", return_value=False), \
                patch.object(med, "_panel_kind_of", side_effect=("skill", "skill", "bond", "bond", "treasure", "treasure")), \
                patch.object(med, "_find_reward_choice", return_value=None), \
                patch.object(med, "_close_current_panel", return_value=None):
            for kind in ("skill", "bond", "treasure"):
                for _ in range(2):
                    med._l1_cycle_step = kind
                    med._choice_target = kind
                    self.assertIs(med._maybe_open_choice_panel(frame), LoopAction.Continue)
                    self.assertNotIn(kind, med._panel_episode_count)
                    self.assertIs(
                        med._tick_panel_fsm(frame, anchor, clock.now()),
                        LoopAction.Continue,
                    )
                    self.assertIs(med._panel_state, PanelState.WAIT_VISIBLE)
                    self.assertIs(
                        med._tick_panel_fsm(frame, anchor, clock.now()),
                        LoopAction.Continue,
                    )
                    self.assertIs(med._panel_state, PanelState.ACTIVE)
                    med._l1_cycle_selected = True
                    med._finish_panel_episode()
                    self.assertNotIn(kind, med._panel_episode_count)

        self.assertEqual(med._panel_episode_count, {})
        self.assertEqual(med._panel_cooldown_until, {})

        # One failed reopen of each kind produces three independent counters;
        # no kind can spend another kind's budget.
        expected_counts: dict[str, int] = {}
        with clock.install(), patch.object(med, "_selection_anchor", return_value=None), \
                patch.object(med, "_bond_base_progress_pending", return_value=False):
            for kind in ("skill", "bond", "treasure"):
                med._l1_cycle_step = kind
                med._choice_target = kind
                self.assertIs(med._maybe_open_choice_panel(frame), LoopAction.Continue)
                self.assertIs(med._tick_panel_fsm(frame, None, clock.now()), LoopAction.Continue)
                clock.advance(0.6)
                self.assertIs(med._tick_panel_fsm(frame, None, clock.now()), LoopAction.Continue)
                expected_counts[kind] = 1
                self.assertEqual(med._panel_episode_count, expected_counts)
                clock.advance(0.2)
                self.assertIsNone(med._tick_panel_fsm(frame, None, clock.now()))

        self.assertEqual(med._panel_episode_count, {"skill": 1, "bond": 1, "treasure": 1})

    def test_new_round_clears_terminal_panel_quarantine(self) -> None:
        med, _ = _mediator(FakeClock())
        med._panel_episode_count = {"skill": 2, "bond": 1, "treasure": 3}
        med._panel_cooldown_until = {"skill": float("inf"), "bond": 5.0, "treasure": 7.0}
        med._panel_state = PanelState.COOLDOWN
        med._panel_kind = "treasure"
        med._panel_episode_id = "old-episode"
        med._panel_episode_started = 123.0
        med.set_phase(Phase.STAGE_SELECT)
        self.assertEqual(med._panel_episode_count, {})
        self.assertEqual(med._panel_cooldown_until, {})
        self.assertIs(med._panel_state, PanelState.CLOSED)
        self.assertIsNone(med._panel_kind)
        self.assertIsNone(med._panel_episode_id)
        self.assertIsNone(med._panel_episode_started)


if __name__ == "__main__":
    unittest.main()
