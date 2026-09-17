"""P0-1 regression: Non-reputation challenge start verified round boundary resets."""

from pathlib import Path
import time

from shuabao.mediator import ChallengeState, Phase
from shuabao.runtime_mediator import Mediator as RuntimeMediator
from shuabao.settings import Settings


def test_non_reputation_new_round_resets_dirty_per_round_state() -> None:
    """Requirement 1: Normal STAGE_STARTING -> MAIN_LINE ('challenge start verified') executes full round reset."""
    settings = Settings(auto_reputation=False)
    med = RuntimeMediator(settings, Path("."))

    # Construct dirty state left over from previous round
    med.phase = Phase.STAGE_STARTING
    med._auto_task_done = True
    med._auto_task_attempts = 3
    med._main_line_closed_done = True
    med._close_main_line_triggered = True
    med._challenge_done = {"coin_challenge", "wood_challenge"}
    med._challenge_states = {"coin_challenge": ChallengeState.ON}
    med._post_game_route = "archive"
    med._secret_realm_active = True
    med._time_cave_boss_done = True
    med._merchant_next_at = time.time() + 300.0
    med._skill_cards_owned = ["skill_1", "skill_2"]
    med._bond_cards_owned = ["bond_1"]
    old_time = time.time() - 500.0
    med._main_line_started_at = old_time
    med._round_started_at = old_time
    med._round_deadline = old_time + 180.0
    med._tqtz_clicked = True
    med._tqtz_abandoned = True
    med._stage_attempt_budget = 5

    # Simulate transition: STAGE_STARTING -> MAIN_LINE ("challenge start verified")
    before_transition = time.time()
    med.set_phase(Phase.MAIN_LINE, "challenge start verified")
    after_transition = time.time()

    # Verify true new round resets
    assert med.phase == Phase.MAIN_LINE
    # Auto task re-armed
    assert med._auto_task_done is False
    assert med._auto_task_attempts == 0
    # Main-line closed flags cleared
    assert med._main_line_closed_done is False
    assert med._close_main_line_triggered is False
    # Challenge state cleared
    assert len(med._challenge_done) == 0
    assert med._challenge_states["coin_challenge"] == ChallengeState.PENDING
    # Postgame route back to default ("secret")
    assert med._post_game_route == "secret"
    # Secret realm state cleared
    assert med._secret_realm_active is False
    # Time cave boss done cleared
    assert med._time_cave_boss_done is False
    # Merchant timing cleared
    assert med._merchant_next_at == 0.0
    # Cards owned cleared
    assert len(med._skill_cards_owned) == 0
    assert len(med._bond_cards_owned) == 0
    # TQTZ cleared
    assert med._tqtz_clicked is False
    assert med._tqtz_abandoned is False
    # Timestamps properly established for new round
    assert med._main_line_started_at is not None
    assert before_transition <= med._main_line_started_at <= after_transition
    assert med._round_started_at is not None
    assert before_transition <= med._round_started_at <= after_transition
    assert med._round_deadline is not None
    assert med._round_deadline == med._round_started_at + med.settings.round_timeout_s


def test_non_reputation_new_round_resets_with_none_timestamps() -> None:
    """Requirement 1 variant: STAGE_STARTING -> MAIN_LINE when timestamps were None (e.g. from STAGE_SELECT)."""
    settings = Settings(auto_reputation=False)
    med = RuntimeMediator(settings, Path("."))

    med.phase = Phase.STAGE_STARTING
    med._auto_task_done = True
    med._main_line_closed_done = True
    med._close_main_line_triggered = True
    med._challenge_done = {"coin_challenge"}
    med._post_game_route = "archive"
    med._secret_realm_active = True
    med._time_cave_boss_done = True
    med._merchant_next_at = 12345.0
    med._skill_cards_owned = ["skill_1"]
    med._bond_cards_owned = ["bond_1"]
    med._main_line_started_at = None
    med._round_started_at = None
    med._round_deadline = None

    before_transition = time.time()
    med.set_phase(Phase.MAIN_LINE, "challenge start verified (DONE)")
    after_transition = time.time()

    assert med.phase == Phase.MAIN_LINE
    assert med._auto_task_done is False
    assert med._main_line_closed_done is False
    assert med._close_main_line_triggered is False
    assert len(med._challenge_done) == 0
    assert med._post_game_route == "secret"
    assert med._secret_realm_active is False
    assert med._time_cave_boss_done is False
    assert med._merchant_next_at == 0.0
    assert len(med._skill_cards_owned) == 0
    assert len(med._bond_cards_owned) == 0
    assert med._main_line_started_at is not None
    assert before_transition <= med._main_line_started_at <= after_transition
    assert med._round_started_at is not None
    assert before_transition <= med._round_started_at <= after_transition
    assert med._round_deadline is not None
    assert med._round_deadline == med._round_started_at + med.settings.round_timeout_s


def test_reentry_does_not_reset_in_game_state() -> None:
    """Requirement 2: Re-entry / reconcile paths must NOT reset in-game state."""
    settings = Settings()
    med = RuntimeMediator(settings, Path("."))

    # Scenario A: MAIN_LINE -> MAIN_LINE ("challenge return")
    med.phase = Phase.MAIN_LINE
    med._auto_task_done = True
    med._skill_cards_owned = ["skill_keep_1", "skill_keep_2"]
    med._bond_cards_owned = ["bond_keep_1"]
    med._challenge_done = {"coin_challenge"}
    med._post_game_route = "heirloom"
    med._merchant_next_at = 9999.0
    fixed_start = 123456.0
    fixed_deadline = fixed_start + 180.0
    med._main_line_started_at = fixed_start
    med._round_started_at = fixed_start
    med._round_deadline = fixed_deadline

    med.set_phase(Phase.MAIN_LINE, "challenge return")

    assert med.phase == Phase.MAIN_LINE
    assert med._auto_task_done is True
    assert med._skill_cards_owned == ["skill_keep_1", "skill_keep_2"]
    assert med._bond_cards_owned == ["bond_keep_1"]
    assert med._challenge_done == {"coin_challenge"}
    assert med._post_game_route == "heirloom"
    assert med._merchant_next_at == 9999.0
    assert med._main_line_started_at == fixed_start
    assert med._round_started_at == fixed_start
    assert med._round_deadline == fixed_deadline

    # Scenario B: RECOVER_FAILURE -> MAIN_LINE ("challenge return")
    med.phase = Phase.RECOVER_FAILURE
    med._auto_task_done = True
    med._skill_cards_owned = ["skill_keep_1"]
    med._challenge_done = {"wood_challenge"}
    med._merchant_next_at = 8888.0

    med.set_phase(Phase.MAIN_LINE, "challenge return")

    assert med.phase == Phase.MAIN_LINE
    assert med._auto_task_done is True
    assert med._skill_cards_owned == ["skill_keep_1"]
    assert med._challenge_done == {"wood_challenge"}
    assert med._merchant_next_at == 8888.0
    assert med._main_line_started_at == fixed_start
    assert med._round_started_at == fixed_start
    assert med._round_deadline == fixed_deadline

    # Scenario C: RECOVER_FAILURE -> MAIN_LINE ("already in game" / "startup reconcile")
    med.phase = Phase.RECOVER_FAILURE
    med.set_phase(Phase.MAIN_LINE, "already in game")
    assert med.phase == Phase.MAIN_LINE
    assert med._auto_task_done is True
    assert med._skill_cards_owned == ["skill_keep_1"]
    assert med._challenge_done == {"wood_challenge"}
    assert med._merchant_next_at == 8888.0

    med.phase = Phase.RECOVER_FAILURE
    med.set_phase(Phase.MAIN_LINE, "startup reconcile to live")
    assert med.phase == Phase.MAIN_LINE
    assert med._auto_task_done is True
    assert med._skill_cards_owned == ["skill_keep_1"]
    assert med._challenge_done == {"wood_challenge"}
    assert med._merchant_next_at == 8888.0
