"""Live 2026-09-12 12:03 (hitch_lobby_chain_20260912_120333_103843).

1. The victory page was never continued: its 胜利 banner animates in over the
   archive panel before 继续游戏 is drawn.  That frame classified as
   ARCHIVE_PANEL, the passenger took over the archive chain (pending flag),
   and the finished victory page then read as "Continue already clicked"
   with no click time - a wait that never timed out.
2. No devour pill was bought: after every [Z]/[B]/[V]/challenge click the
   pointer rested on that control and its tooltip covered the merchant strip
   (pill 0.99 when uncovered, never at the merchant step).  The fix is
   general: a click on the bottom HUD / right edge marks the pointer, and the
   next HUD read first parks it on open ground (move, no click).
"""

from __future__ import annotations

import contextlib
import io
import time
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from shuabao.input.keyboard_mouse import InputExecutor, move_cursor
from shuabao.mediator import MatchResult, Mediator, PanelState, Phase
from shuabao.policy.public_bag import PublicBagFSM, PublicBagPhase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "hitch_live_20260911"

VICTORY_ANIMATING = FIX / "game_archive_victory_animating.png"
VICTORY_CONTINUE = ROOT / "fixtures" / "reborn_wow" / "endgame" / "victory_continue.png"
STRIP_COVERED = FIX / "game_hud_merchant_strip_under_tooltip.png"
PILL_VISIBLE = FIX / "game_hud_merchant_devour_pill_visible.png"


def _frame(path: Path) -> Frame:
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None, path
    return Frame(image, window_title="英雄三国", hwnd=7, role="l1")


def _med() -> Mediator:
    med = Mediator(Settings(mode_id="lobby_hitch", ocr_mode="off"), ROOT)
    with contextlib.redirect_stdout(io.StringIO()):
        med.set_phase(Phase.MAIN_LINE, "hitch natural round entry")
    med._auto_task_done = True
    med._challenge_done = set(med._challenge_states)
    med._hitch_pressure_transferred = True
    return med


def _tick(med: Mediator, frame: Frame) -> list[str]:
    reasons: list[str] = []
    med._last_frame = frame
    with patch.object(med, "act_click", side_effect=lambda _h, r="": reasons.append(r) or True), \
         patch.object(med, "act_right_click", side_effect=lambda _h, r="": reasons.append(r) or True), \
         patch.object(med, "act_key", side_effect=lambda _k, r="": reasons.append(r) or True), \
         patch.object(med, "act_move", side_effect=lambda _x, _y, r="": reasons.append(r) or True), \
         contextlib.redirect_stdout(io.StringIO()):
        med._tick_main_line(frame)
    return reasons


# ---------- victory ----------

def test_animating_victory_banner_is_the_victory_page_not_the_archive() -> None:
    med = _med()
    assert med._post_game_state(_frame(VICTORY_ANIMATING)) == "POST_VICTORY"


def test_victory_waits_for_the_button_then_continues() -> None:
    med = _med()
    for _ in range(3):
        # Banner only: no archive chain, no F1, no clicks under the modal.
        assert _tick(med, _frame(VICTORY_ANIMATING)) == []
    assert med._post_game_pending is False
    assert _tick(med, _frame(VICTORY_CONTINUE)) == ["ContinueGame"]
    assert med._victory_continue_since is not None


def test_pending_chain_without_our_click_still_continues() -> None:
    # The live state: pending set by an archive takeover, no click on record.
    med = _med()
    med._post_game_pending = True
    med._post_game_route = "archive"
    med._victory_continue_since = None
    assert _tick(med, _frame(VICTORY_CONTINUE)) == ["ContinueGame"]


def test_after_our_continue_click_the_victory_page_is_awaited() -> None:
    med = _med()
    med._post_game_pending = True
    med._victory_continue_since = time.time()
    assert _tick(med, _frame(VICTORY_CONTINUE)) == []


# ---------- pointer tooltip / merchant ----------

def test_tooltip_hides_the_pill_and_open_ground_shows_it() -> None:
    med = _med()
    covered, clear = _frame(STRIP_COVERED), _frame(PILL_VISIBLE)
    roi = (0.70, 0.66, 0.90, 0.76)
    scales = (0.5, 0.6, 0.75, 0.9, 1.0, 1.1, 1.25, 1.5)
    assert med.find(covered, ["danGif"], threshold=0.90, scales=scales, roi=roi) is None
    hit = med.find(clear, ["danGif"], threshold=0.90, scales=scales, roi=roi)
    assert hit is not None and hit.score >= 0.95


def test_bottom_hud_click_marks_the_pointer_and_the_next_read_parks_it() -> None:
    med = _med()
    frame = _frame(STRIP_COVERED)
    med._last_frame = frame
    z_button = MatchResult("bag/hud_pickup_button", 1.0, 1533, 710, 0, 0, 1533, 710)
    med._note_pointer_on_hud(z_button)
    assert med._pointer_needs_park is True

    reasons = _tick(med, frame)
    assert reasons == ["ParkPointer"]


def test_park_is_a_move_and_clears_the_mark() -> None:
    med = _med()
    frame = _frame(STRIP_COVERED)
    med._last_frame = frame
    med._pointer_needs_park = True
    moves: list[tuple[int, int]] = []

    class _Exec:
        def move(self, x, y, target_hwnd=None, dry_run=True):
            moves.append((x, y))
            from shuabao.input.keyboard_mouse import ActionResult
            return ActionResult(True, "SUCCESS", "moved")

    med.executor = _Exec()
    with contextlib.redirect_stdout(io.StringIO()):
        action = med._maybe_park_pointer(frame)
    assert action is not None
    assert moves == [(int(1600 * 0.62), int(900 * 0.30))]
    assert med._pointer_needs_park is False


def test_merchant_buys_the_pill_once_the_strip_is_clear() -> None:
    med = _med()
    med._l1_cycle_step = "merchant"
    reasons = _tick(med, _frame(PILL_VISIBLE))
    assert "BlackMerchant-swallow_pill" in reasons


def test_no_park_in_the_middle_of_a_bag_hop_or_panel() -> None:
    med = _med()
    frame = _frame(STRIP_COVERED)
    med._pointer_needs_park = True
    med._public_bag_fsm = PublicBagFSM(phase=PublicBagPhase.SOURCE_SELECTED, opened_by_us=True)
    assert med._maybe_park_pointer(frame) is None
    med._public_bag_fsm = PublicBagFSM()
    med._panel_state = PanelState.ACTIVE
    assert med._maybe_park_pointer(frame) is None


def test_top_of_screen_click_does_not_mark_the_pointer() -> None:
    med = _med()
    med._last_frame = _frame(STRIP_COVERED)
    quit_button = MatchResult("quit", 1.0, 60, 20, 0, 0, 60, 20)
    med._note_pointer_on_hud(quit_button)
    assert med._pointer_needs_park is False


def test_input_layer_move_is_pointer_only() -> None:
    assert move_cursor(10, 10, dry_run=True) is True
    with contextlib.redirect_stdout(io.StringIO()):
        result = InputExecutor().move(10, 10, dry_run=True)
    assert result.success is True
    assert result.status == "DRY_RUN"
