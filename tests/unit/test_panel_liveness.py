import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from shuabao.mediator import LoopAction, Mediator as CoreMediator, PanelState, Phase
from shuabao.runtime_mediator import Mediator as RuntimeMediator
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult
from shuabao.settings import Settings

ROOT = Path(__file__).resolve().parents[2]
def make_dummy_frame() -> Frame:
    bgr = np.zeros((720, 1280, 3), dtype=np.uint8)
    return Frame(
        bgr=bgr,
        left=0,
        top=0,
    )


def make_dummy_anchor(name: str = "card_panel_anchor", score: float = 0.95) -> MatchResult:
    return MatchResult(
        name=name,
        score=score,
        x=100,
        y=100,
        w=100,
        h=100,
        screen_x=150,
        screen_y=150,
    )


def test_episode_id_creation_and_diagnostics():
    """Verify episode_id creation, fields and diagnostics propagation."""
    mediator = RuntimeMediator(Settings(), ROOT)
    assert mediator._panel_state == PanelState.CLOSED
    assert mediator._panel_episode_id is None

    diag = mediator.panel_episode_diagnostics()
    assert diag["panel_state"] == "CLOSED"
    assert diag["episode_id"] is None
    assert diag["executed_actions"] == 0

    frame = make_dummy_frame()
    anchor = make_dummy_anchor()
    now = 1000.0

    # Entering panel episode
    mediator._enter_panel_episode(frame, anchor, kind="bond", opened=False)

    assert mediator._panel_state == PanelState.ACTIVE
    assert mediator._panel_kind == "bond"
    assert mediator._panel_episode_id is not None
    assert mediator._panel_episode_id.startswith("ep_")
    assert mediator._panel_first_seen_at is not None
    assert mediator._panel_last_progress_at is not None
    assert mediator._panel_hard_deadline_s == 15.0

    diag = mediator.panel_episode_diagnostics()
    assert diag["panel_state"] == "ACTIVE"
    assert diag["episode_id"] == mediator._panel_episode_id
    assert diag["kind"] == "bond"
    assert diag["hard_deadline_s"] == 15.0


def test_episode_hard_deadline_expiration_under_stagnant_panel():
    """Stagnant panel exceeding hard deadline forces cooldown and breaks infinite loop."""
    mediator = CoreMediator(Settings(panel_hard_deadline_s=10.0), ROOT)
    frame = make_dummy_frame()
    anchor = make_dummy_anchor()

    # Enter episode at t = 100.0 with 10.0s hard deadline
    mediator.settings.panel_hard_deadline_s = 10.0
    mediator._panel_hard_deadline_s = 10.0
    with patch("time.time", return_value=100.0):
        mediator._enter_panel_episode(frame, anchor, kind="bond", opened=False)
    assert mediator._panel_state == PanelState.ACTIVE
    assert mediator._panel_episode_started == 100.0

    # At t = 105.0 (< 10.0s elapsed), within deadline
    action = mediator._tick_panel_fsm(frame, anchor, now=105.0)
    assert action is not None
    assert mediator._panel_state in (PanelState.ACTIVE, PanelState.WAIT_MUTATION, PanelState.CLOSING)

    # At t = 111.0 (11.0s elapsed >= 10.0s hard deadline), must trigger cooldown and log incident
    incidents = []
    mediator._record_fail_closed_incident = lambda note: incidents.append(note)

    action = mediator._tick_panel_fsm(frame, anchor, now=111.0)
    assert action == LoopAction.Continue
    assert mediator._panel_state == PanelState.COOLDOWN
    assert len(incidents) == 1
    assert "panel_episode_timeout" in incidents[0]


def test_closing_state_when_close_button_missing_bounds_livelock():
    """CLOSING state without close buttons transitions to COOLDOWN after 3 attempts or timeout."""
    mediator = CoreMediator(Settings(), ROOT)
    frame = make_dummy_frame()
    anchor = make_dummy_anchor()

    now = 500.0
    mediator._enter_panel_episode(frame, anchor, kind="bond", opened=False)
    mediator._panel_state = PanelState.CLOSING
    mediator._close_current_panel = MagicMock(return_value=None)

    # Attempt 1
    res1 = mediator._tick_panel_fsm(frame, anchor, now=now)
    assert mediator._panel_state == PanelState.CLOSING
    assert mediator._panel_closing_attempts == 1

    # Attempt 2
    res2 = mediator._tick_panel_fsm(frame, anchor, now=now + 0.5)
    assert mediator._panel_state == PanelState.CLOSING
    assert mediator._panel_closing_attempts == 2

    # Attempt 3 (>= 3 attempts) forces COOLDOWN, never spinning infinitely
    res3 = mediator._tick_panel_fsm(frame, anchor, now=now + 1.0)
    assert mediator._panel_state == PanelState.COOLDOWN
    assert res3 == LoopAction.Continue


def test_unexecutable_refresh_giveup_policy_rejection_no_spinning():
    """Unexecutable REFRESH / GIVEUP falls back safely to close or idle zero-input without spin."""
    mediator = CoreMediator(Settings(), ROOT)
    frame = make_dummy_frame()

    # Mock policy returning REFRESH but physical refresh button is missing
    with patch.object(mediator, "_find_panel_refresh", return_value=None), \
         patch.object(mediator, "_close_current_panel", return_value=None):
        hit = mediator._policy_decision_to_hit(
            frame=frame,
            kind="bond",
            decision=MagicMock(action="REFRESH", reason="need refresh"),
            slots=[],
        )
        assert hit is None
        assert mediator._choice_policy_idle is True

    # When close button exists, REFRESH falls back to closing
    dummy_close = MatchResult(name="close_btn", score=0.9, x=1, y=1, w=10, h=10, screen_x=5, screen_y=5)
    with patch.object(mediator, "_find_panel_refresh", return_value=None), \
         patch.object(mediator, "_close_current_panel", return_value=dummy_close):
        label, hit_res = mediator._policy_decision_to_hit(
            frame=frame,
            kind="bond",
            decision=MagicMock(action="REFRESH", reason="need refresh"),
            slots=[],
        )
        assert label == "bond"
        assert hit_res.name == "close_btn"


def test_multiple_unconfirmed_clicks_trigger_closing_cooldown():
    mediator = CoreMediator(Settings(panel_action_limit_per_fingerprint=2), ROOT)
    frame = make_dummy_frame()
    anchor = make_dummy_anchor()
    now = 200.0

    mediator._enter_panel_episode(frame, anchor, kind="bond", opened=False)

    candidate_hit = MatchResult(
        name="cards/test_card",
        score=0.95,
        x=300,
        y=300,
        w=100,
        h=100,
        screen_x=350,
        screen_y=350,
    )
    mediator._find_reward_choice = MagicMock(return_value=("bond", candidate_hit))
    mediator.act_click = MagicMock(return_value=True)

    # Click 1
    mediator._tick_panel_fsm(frame, anchor, now=now)
    assert mediator._panel_fingerprint_attempts == 1
    assert mediator._panel_state == PanelState.WAIT_MUTATION

    # Advance time past confirm_window (16.0s >= 15.0s, advance episode_started as well to stay < hard_deadline)
    mediator._panel_last_input_at = now
    mediator._panel_mutation_baseline = np.zeros((10, 10, 3), dtype=np.uint8)
    mediator._panel_mutation_confirmed = MagicMock(return_value=False)
    mediator._panel_episode_started = now + 10.0

    mediator._tick_panel_fsm(frame, anchor, now=now + 16.0)
    assert mediator._panel_state == PanelState.CLOSING  # select mutation failed -> CLOSING
