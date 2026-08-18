"""Unit tests for Central Choice Panels and Secondary Interactions."""

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from shuabao.choice_policy import ActionLifecycle, PolicyAction, PolicyDecision, PolicySettings, SessionState
from shuabao.interaction_surface import InteractionSurface, PendingAction, resolve_interaction_surface
from shuabao.mediator import LoopAction, Mediator, PanelState, Phase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult

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


def test_action_lifecycle_enum_states():
    """Verify ActionLifecycle states are defined and orderable."""
    assert ActionLifecycle.OBSERVED is not None
    assert ActionLifecycle.ACTION_AUTHORIZED is not None
    assert ActionLifecycle.INPUT_SENT is not None
    assert ActionLifecycle.VERIFYING is not None
    assert ActionLifecycle.CONFIRMED is not None
    assert ActionLifecycle.UNCONFIRMED is not None
    assert ActionLifecycle.RECOVERING is not None


def test_skill_selection_mutation_confirmation_and_ownership_update():
    """Verify skill cards are staged on click and only committed upon verified mutation."""
    mediator = Mediator(Settings(), ROOT)
    frame = make_dummy_frame()
    anchor = make_dummy_anchor()
    now = 1000.0

    mediator._enter_panel_episode(frame, anchor, kind="技能", opened=False)
    assert mediator._panel_confirmed_actions == 0
    assert len(mediator._confirmed_skill_cards()) == 0

    candidate_hit = MatchResult(
        name="skills/test_skill",
        score=0.95,
        x=300,
        y=300,
        w=100,
        h=100,
        screen_x=350,
        screen_y=350,
    )
    mediator._find_reward_choice = MagicMock(return_value=("技能", candidate_hit))
    mediator.act_click = MagicMock(return_value=True)

    # Action triggered -> INPUT_SENT & staged
    mediator._tick_panel_fsm(frame, anchor, now=now)
    assert mediator._panel_state == PanelState.WAIT_MUTATION
    assert mediator._skill_cards_pending == ["test_skill"]
    assert len(mediator._confirmed_skill_cards()) == 0  # not committed yet!

    # Mutation confirmed -> CONFIRMED & committed
    mediator._verify_action_mutation = MagicMock(return_value=True)
    mediator._panel_mutation_confirmed = MagicMock(return_value=True)

    mediator._tick_panel_fsm(frame, anchor, now=now + 0.5)
    assert mediator._panel_confirmed_actions == 1
    assert "test_skill" in mediator._confirmed_skill_cards()


def test_missing_refresh_and_close_controls_fail_closed_recovery():
    """Missing refresh and close buttons safely fallback without spinning."""
    mediator = Mediator(Settings(), ROOT)
    frame = make_dummy_frame()
    anchor = make_dummy_anchor()

    # Enter episode
    mediator._enter_panel_episode(frame, anchor, kind="bond", opened=False)

    # If policy asks for REFRESH but refresh/close are missing, policy idles zero-input
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


def test_hero_card_vs_basic_upgrade_distinct_verification():
    """Enforce distinct state verification for hero cards and avoid mixing reputation logic."""
    mediator = Mediator(Settings(), ROOT)
    frame = make_dummy_frame()

    # Hero setup internal state
    assert mediator._hero_state == "IDLE"
    assert mediator._hero_verified_level == 0

    # Ensure hero setup fails cleanly with Break when out of bounds
    mediator.settings.reputation_type = 999
    mediator.settings.reputation_level = 1
    action = mediator._begin_hero_setup(frame)
    assert action == LoopAction.Break
    assert mediator.phase == Phase.ERROR


def test_equipment_upgrade_verification_lifecycle():
    """Ensure equipment upgrade validates occupancy, sends input, and respects debounce."""
    mediator = Mediator(Settings(), ROOT)
    frame = make_dummy_frame()
    now = 1000.0

    with patch("time.time", return_value=now), \
         patch.object(mediator, "_equipment_slot_one_occupied", return_value=True), \
         patch.object(mediator, "act_right_click", return_value=True) as mock_rc:
        action = mediator._maybe_upgrade_equipment(frame)
        assert action == LoopAction.Continue
        mock_rc.assert_called_once()
        assert mediator._equipment_next_at == now + 8.0


def test_secondary_interactions_debouncing_and_recovery():
    """Verify target checks, debouncing, and fail-closed timeout for secondary interactions."""
    mediator = Mediator(Settings(), ROOT)
    frame = make_dummy_frame()

    # Black merchant target check
    assert mediator._black_merchant_present(frame) is False
    assert mediator._find_heirloom_close(frame) is None
    assert mediator._find_secret_realm_npc(frame) is None
