"""Hitch in-game bootstrap and public-bag lease on real 2026-09-11 23:42 frames.

Live failure: the in-game stage lobby a guest sees ("等待玩家1选择难度") was
classified as in-game HUD, so the round "started" early: the opening pressure
gate was never armed and the auto-task UNKNOWN fuse burned before the real
HUD.  Later an item tooltip hid the auto-task checkbox, the fuse froze the
whole main line, and the bag page stayed open over the post-game plaza.
"""
from __future__ import annotations

import contextlib
import io
import time
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from shuabao.mediator import LoopAction, Mediator, Phase
from shuabao.policy.public_bag import PublicBagFSM, PublicBagPhase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "hitch_live_20260911"


def _game(name: str) -> Frame:
    image = cv2.imdecode(np.fromfile(str(FIX / name), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None, name
    return Frame(image, window_title="英雄三国", hwnd=7, role="l1")


WAITING = "game_waiting_player1_difficulty.png"
PRELUDE = "game_prelude_faction_challenge_panel.png"
OPENING = "game_opening_pressure_and_failure_gift.png"
TOOLTIP = "game_bag_item_tooltip_covers_auto_task.png"
POSTGAME_BAG = "game_postgame_plaza_under_open_bag.png"


def _med() -> Mediator:
    return Mediator(Settings(mode_id="lobby_hitch", ocr_mode="off"), ROOT)


def _tick(med: Mediator, handler, frame: Frame) -> tuple[LoopAction, list[str]]:
    reasons: list[str] = []
    with patch.object(med, "act_click", side_effect=lambda _h, r="": reasons.append(r) or True), \
         patch.object(med, "act_right_click", side_effect=lambda _h, r="": reasons.append(r) or True), \
         patch.object(med, "act_key", side_effect=lambda _k, r="": reasons.append(r) or True), \
         contextlib.redirect_stdout(io.StringIO()):
        result = handler(frame)
    return result, reasons


def test_player1_difficulty_banner_is_not_in_game_hud() -> None:
    med = _med()
    frame = _game(WAITING)

    assert med._host_choosing_difficulty(frame) is True
    assert med._is_in_game_hud(frame) is False
    assert med._compute_context(frame, "l1") == "STAGE_SELECT"
    assert med._host_choosing_difficulty(_game(OPENING)) is False


def test_guest_waits_on_player1_difficulty_page_instead_of_quitting() -> None:
    med = _med()
    med.set_phase(Phase.ROOM_WAITING, "test")
    med._hitch_ready_confirmed_at = time.time() - 30

    for name in (WAITING, PRELUDE):
        result, reasons = _tick(med, med._tick_l0, _game(name))
        assert result is LoopAction.Continue
        assert reasons == []
        assert med.phase is Phase.ROOM_WAITING, name


def test_main_line_hands_waiting_page_back_to_room_wait() -> None:
    med = _med()
    med.set_phase(Phase.MAIN_LINE, "test")

    _result, reasons = _tick(med, med._tick_main_line, _game(WAITING))

    assert reasons == []
    assert med.phase is Phase.ROOM_WAITING


def test_natural_round_entry_arms_pressure_and_resets_round_state() -> None:
    med = _med()
    med.set_phase(Phase.ROOM_WAITING, "test")
    med._hitch_ready_confirmed_at = time.time() - 30
    # Leftovers of a previous round must not survive a natural entry.
    med._hitch_pressure_transferred = True
    med._auto_task_done = True

    _tick(med, med._tick_l0, _game(OPENING))

    assert med.phase is Phase.MAIN_LINE
    assert med._hitch_opening_pressure_armed is True
    assert med._hitch_pressure_transferred is False
    assert med._auto_task_done is False

    _result, reasons = _tick(med, med._tick_main_line, _game(OPENING))
    assert reasons == ["HitchPressureTransfer"]


def test_midgame_attach_does_not_arm_opening_pressure() -> None:
    med = _med()
    med.set_phase(Phase.ROOM_WAITING, "test")

    _tick(med, med._tick_l0, _game(OPENING))

    assert med.phase is Phase.MAIN_LINE
    assert med._hitch_opening_pressure_armed is False


def test_hidden_checkbox_never_blocks_once_auto_task_is_on() -> None:
    med = _med()
    med.set_phase(Phase.MAIN_LINE, "test")
    med._auto_task_done = True
    med._auto_task_recheck_at = time.time() + 100
    frame = _game(TOOLTIP)

    assert med._auto_task_state(frame)[0] == "UNKNOWN"
    assert med._ensure_auto_task_enabled(frame) is None
    med._auto_task_recheck_at = time.time() - 1
    assert med._ensure_auto_task_enabled(frame) is None


def test_bag_hop_proceeds_while_tooltip_hides_auto_task() -> None:
    med = _med()
    med.set_phase(Phase.MAIN_LINE, "test")
    med._auto_task_done = True
    med._auto_task_recheck_at = time.time() + 100
    med._challenge_done = set(med._challenge_states)
    med._hitch_pressure_transferred = True
    med._l1_cycle_step = "public_bag"
    med._public_bag_fsm = PublicBagFSM(
        phase=PublicBagPhase.SOURCE_SELECTED, source_id="item_bar_1",
        source_kind="item_bar", source_slot=1, deadline=time.time() + 6, opened_by_us=True,
    )

    _result, reasons = _tick(med, med._tick_main_line, _game(TOOLTIP))

    assert reasons == ["PublicBackpackStash"]


def test_open_bag_is_closed_before_the_post_continue_page() -> None:
    med = _med()
    med.set_phase(Phase.MAIN_LINE, "test")
    med._auto_task_done = True
    med._hitch_pressure_transferred = True
    med._post_game_pending = True
    med._victory_continue_since = time.time() - 3

    _result, reasons = _tick(med, med._tick_main_line, _game(POSTGAME_BAG))

    assert reasons == ["PublicBackpackClose"]


def test_unplaced_right_click_retires_the_source_after_two_timeouts() -> None:
    med = _med()
    frame = _game(TOOLTIP)
    for _ in range(2):
        med._public_bag_fsm = PublicBagFSM(
            phase=PublicBagPhase.SOURCE_SELECTED, source_id="item_bar_1",
            source_kind="item_bar", source_slot=1, deadline=time.time() - 1, opened_by_us=True,
        )
        with patch.object(med, "act_click", return_value=True), \
             patch.object(med, "act_right_click", return_value=True), \
             contextlib.redirect_stdout(io.StringIO()):
            med._maybe_public_backpack_deposit(frame, time.time())
        assert med._public_bag_fsm.phase is PublicBagPhase.ABORTED

    assert med._public_bag_source_exhausted("item_bar_1") is True


def test_manual_bag_close_is_respected() -> None:
    med = _med()
    frame = _game(OPENING)  # no bag page
    now = time.time()
    med._public_bag_fsm = PublicBagFSM(phase=PublicBagPhase.BAG_VISIBLE, opened_by_us=True)

    with contextlib.redirect_stdout(io.StringIO()):
        med._maybe_public_backpack_deposit(frame, now)

    assert med._public_bag_next_at >= now + Mediator._PUBLIC_BAG_USER_CLOSE_COOLDOWN_S - 1


def test_bag_page_open_longer_than_the_lease_is_closed() -> None:
    med = _med()
    frame = _game(TOOLTIP)
    now = time.time()
    med._public_bag_fsm = PublicBagFSM(phase=PublicBagPhase.BAG_VISIBLE, opened_by_us=True)
    med._public_bag_open_since = now - Mediator._PUBLIC_BAG_MAX_OPEN_S - 1
    reasons: list[str] = []

    with patch.object(med, "act_click", side_effect=lambda _h, r="": reasons.append(r) or True), \
         patch.object(med, "act_key", side_effect=lambda _k, r="": reasons.append(r) or True), \
         contextlib.redirect_stdout(io.StringIO()):
        med._maybe_public_backpack_deposit(frame, now)

    assert reasons == ["PublicBackpackClose"]
    assert med._public_bag_fsm.phase is PublicBagPhase.CLOSE_REQUESTED
    assert med._public_bag_next_at >= now + Mediator._PUBLIC_BAG_REOPEN_COOLDOWN_S - 1


def test_hero_focus_fallback_ignores_our_own_bag_page() -> None:
    med = _med()
    med.set_phase(Phase.MAIN_LINE, "test")
    frame = _game(TOOLTIP)

    with patch("shuabao.input.keyboard_mouse.is_current_process_elevated", return_value=True), \
         patch.object(med, "act_key") as key:
        for _ in range(3):
            med._hero_focus_next_check_at = 0.0
            med._hero_focus_last_frame_id = None
            assert med._maybe_ensure_hero_panel_focus(frame, time.time()) is None

    key.assert_not_called()
