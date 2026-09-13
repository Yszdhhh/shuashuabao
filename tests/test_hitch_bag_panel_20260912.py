"""Live 2026-09-12 10:19 run (hitch_lobby_chain_20260912_101930_846970).

- The bag opened and closed empty after every pickup: opening was not gated
  on anything being in 物品栏 2-6.
- The hero card in slot 2 was never handed over: on the bag page it measured
  135 saturated pixels against the 140 floor, so it was skipped as unsure.
- From 10:28 the capped treasure step parked the panel FSM in COOLDOWN and
  never left the step; the cap then carried into round 2 (hitch rounds never
  pass STAGE_SELECT), so round 2 had no pickup, bag or merchant at all.
"""

from __future__ import annotations

import contextlib
import io
import time
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from shuabao.mediator import LoopAction, Mediator, PanelState, Phase
from shuabao.policy.public_bag import PublicBagPhase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "hitch_live_20260911"

HUD_EMPTY = "game_hud_item_bar_empty.png"
HUD_CARD = "game_hud_card_in_slot2_chat_bar.png"
BAG_EMPTY = "game_bag_open_item_bar_empty.png"
BAG_CARD = "game_bag_open_faint_hero_card.png"


def _game(name: str) -> Frame:
    image = cv2.imdecode(np.fromfile(str(FIX / name), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None, name
    return Frame(image, window_title="英雄三国", hwnd=7, role="l1")


def _med(limit: int = 5) -> Mediator:
    med = Mediator(Settings(mode_id="lobby_hitch", ocr_mode="off"), ROOT)
    med.settings.panel_episode_limit_per_kind = limit
    return med


def _acts(med: Mediator, fn, *args) -> tuple[object, list[str]]:
    reasons: list[str] = []
    with patch.object(med, "act_click", side_effect=lambda _h, r="": reasons.append(r) or True), \
         patch.object(med, "act_right_click", side_effect=lambda _h, r="": reasons.append(r) or True), \
         patch.object(med, "act_key", side_effect=lambda _k, r="": reasons.append(r) or True), \
         contextlib.redirect_stdout(io.StringIO()):
        result = fn(*args)
    return result, reasons


def test_hud_item_bar_reads_slots_two_to_six() -> None:
    med = _med()
    assert med._hud_item_bar_state(_game(HUD_EMPTY)) == "empty"
    assert med._hud_item_bar_state(_game(HUD_CARD)) == "items"
    # The bag page leaves the HUD copy visible.
    assert med._hud_item_bar_state(_game(BAG_EMPTY)) == "empty"


def test_bag_is_not_opened_when_item_bar_is_empty() -> None:
    med = _med()
    med.set_phase(Phase.MAIN_LINE, "test")

    result, reasons = _acts(med, med._maybe_public_backpack_deposit, _game(HUD_EMPTY), time.time())

    assert result is None
    assert reasons == []
    assert med._public_bag_fsm.phase is PublicBagPhase.IDLE


def test_bag_is_opened_for_an_item_in_the_item_bar() -> None:
    med = _med()
    med.set_phase(Phase.MAIN_LINE, "test")

    result, reasons = _acts(med, med._maybe_public_backpack_deposit, _game(HUD_CARD), time.time())

    assert result is LoopAction.Continue
    assert reasons == ["PublicBackpackDepositB"]


def test_items_left_in_the_personal_grid_justify_the_next_open() -> None:
    med = _med()
    med.set_phase(Phase.MAIN_LINE, "test")
    med._public_bag_personal_leftover = True

    _result, reasons = _acts(med, med._maybe_public_backpack_deposit, _game(HUD_EMPTY), time.time())

    assert reasons == ["PublicBackpackDepositB"]


def test_faint_hero_card_on_the_bag_page_is_a_source() -> None:
    med = _med()
    frame = _game(BAG_CARD)
    with contextlib.redirect_stdout(io.StringIO()):
        layout = med._bag_layout(frame)
    assert layout is not None
    # The page alone can't call it (135 < 140) ...
    assert med._bag_slot_occupied(frame, layout.item_bar_slot_probe_rect(1)) is False
    # ... the HUD copy settles it.
    source = med._public_bag_source(frame, layout)
    assert source is not None
    assert source["source_id"] == "item_bar_1"


def test_empty_bag_page_still_has_no_source() -> None:
    med = _med()
    frame = _game(BAG_EMPTY)
    with contextlib.redirect_stdout(io.StringIO()):
        layout = med._bag_layout(frame)
    assert layout is not None
    assert med._public_bag_source(frame, layout) is None


def test_capped_treasure_step_is_skipped_not_parked() -> None:
    med = _med(limit=5)
    med.set_phase(Phase.MAIN_LINE, "test")
    med._l1_cycle_step = "treasure"
    med._panel_episode_count["treasure"] = 5
    before = time.time()

    result, reasons = _acts(med, med._maybe_open_choice_panel, _game(HUD_EMPTY), None)

    assert result is LoopAction.Continue
    assert reasons == []
    assert med._panel_state is PanelState.CLOSED
    assert med._l1_cycle_step == "pickup"
    assert med._hitch_treasure_retry_at > before


def test_capped_treasure_step_reopens_after_its_retry_window() -> None:
    """A V cap is a bounded episode, never a rest-of-round disable switch."""
    med = _med(limit=5)
    med.set_phase(Phase.MAIN_LINE, "test")
    med._l1_cycle_step = "treasure"
    med._panel_episode_count["treasure"] = 5
    med._hitch_treasure_retry_at = time.time() - 0.1

    result, reasons = _acts(med, med._maybe_open_choice_panel, _game(HUD_EMPTY), None)

    assert result is LoopAction.Continue
    assert reasons == ["OpenTreasurePanel"]
    assert med._panel_episode_count.get("treasure", 0) == 0
    assert med._hitch_treasure_retry_at == 0.0


def test_no_treasure_choices_is_not_a_failure_and_retries_later() -> None:
    med = _med(limit=5)
    med.set_phase(Phase.MAIN_LINE, "test")
    med._l1_cycle_step = "treasure"
    frame = _game(HUD_EMPTY)

    _result, reasons = _acts(med, med._maybe_open_choice_panel, frame, None)
    assert reasons == ["OpenTreasurePanel"]
    now = time.time()
    med._panel_state = PanelState.WAIT_VISIBLE
    med._panel_visible_deadline = now - 0.1
    with contextlib.redirect_stdout(io.StringIO()):
        med._tick_panel_fsm(frame, None, now)

    assert med._panel_episode_count.get("treasure", 0) == 0
    assert med._hitch_treasure_retry_at > now

    # Within the retry window the step is skipped without input.
    med._panel_state = PanelState.CLOSED
    med._l1_cycle_step = "treasure"
    _result, reasons = _acts(med, med._maybe_open_choice_panel, frame, None)
    assert reasons == []
    assert med._l1_cycle_step == "pickup"


def test_heirloom_grid_is_not_blocked_by_the_time_cave_boss_click() -> None:
    # Live 10:44:55: the heirloom grid opened right after the time-cave Boss
    # click; the shared attempt counter made it wait for a result it never
    # asked for.
    med = _med()
    med.settings.cjb_boss = "18乌索克"  # the live run's configured heirloom Boss
    med.set_phase(Phase.MAIN_LINE, "hitch natural round entry")
    med._auto_task_done = True
    med._challenge_done = set(med._challenge_states)
    med._hitch_pressure_transferred = True
    med._post_game_pending = True
    med._post_game_route = "heirloom_active"
    med._time_cave_boss_done = True
    med._boss_challenge_page = "ARCHIVE_PANEL"
    med._boss_challenge_attempts = 1
    med._boss_challenge_scroll_attempts = 3
    med._heirloom_boss_clicked_at = None
    frame = _game("game_heirloom_boss_grid_open.png")
    assert med._post_game_state(frame) == "HEIRLOOM_DIALOG"

    reasons: list[str] = []
    with patch.object(med, "act_click", side_effect=lambda _h, r="": reasons.append(r) or True), \
         patch.object(med, "act_key", side_effect=lambda _k, r="": reasons.append(r) or True), \
         patch.object(med, "act_scroll", side_effect=lambda *_a, **_k: reasons.append("scroll") or True), \
         patch.object(med, "_post_game_boss_list_at_bottom", side_effect=[False, False, True, True, True]), \
         patch("shuabao.mediator.is_slot_empty", return_value=True), \
         contextlib.redirect_stdout(io.StringIO()):
        for _ in range(5):
            med._boss_challenge_next_at = 0.0
            med._tick_main_line(frame)

    assert reasons, "heirloom grid must get input"
    # The configured 18乌索克 is absent from this real grid; the new policy
    # must still reach the physical bottom before using its fallback.
    assert "BossBottomFallback" in reasons
    assert med._heirloom_boss_clicked_at is not None


def test_new_hitch_round_resets_panel_caps() -> None:
    med = _med()
    med.set_phase(Phase.MAIN_LINE, "test")
    med._panel_episode_count["treasure"] = 5
    med._panel_cooldown_until["treasure"] = time.time() + 999
    med._public_bag_personal_leftover = True
    with contextlib.redirect_stdout(io.StringIO()):
        med._finish_hitch_round(time.time(), "exit confirmed; hitch re-search")
        med.set_phase(Phase.ROOM_WAITING, "test")
        med.set_phase(Phase.MAIN_LINE, "hitch natural round entry")

    assert med._panel_episode_count == {}
    assert med._panel_cooldown_until == {}
    assert med._public_bag_personal_leftover is False
