"""Review regressions: real captures, full tick, no window/input calls.

These cases began as strict xfails in the architecture review and now lock in
the fixes on both the core and production runtime mediators.
"""
from __future__ import annotations

import contextlib
import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np
import pytest

from shuabao.input.keyboard_mouse import ActionResult
from shuabao.mediator import Mediator as CoreMediator, PanelState, Phase
from shuabao.runtime_mediator import Mediator as RuntimeMediator
from shuabao.settings import Settings
from shuabao.vision.capture import Frame

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests/fixtures/hitch_live_20260911"
VICTORY = ROOT / "fixtures/reborn_wow/endgame/victory_continue.png"
OPENING = FIX / "game_opening_pressure_and_failure_gift.png"
HUD = FIX / "game_hud_merchant_devour_pill_visible.png"
ANIMATING = FIX / "game_archive_victory_animating.png"


def frame(path):
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    return Frame(image, hwnd=7, window_title="英雄三国", role="l1")


class OfflineExecutor:
    def ok(self, *args, **kwargs):
        return ActionResult(True, "SUCCESS", "offline fake input")

    click = double_click = right_click = press_key = move = scroll = ok


@contextlib.contextmanager
def replay(cls):
    clock = SimpleNamespace(now=1_000_000.0, path=VICTORY)
    med = cls(Settings(mode_id="lobby_hitch", ocr_mode="off", dry_run=False), ROOT)
    med.executor = OfflineExecutor()
    with patch("shuabao.mediator.time.time", side_effect=lambda: clock.now), \
         patch.object(med, "_capture_best", side_effect=lambda *a, **k: frame(clock.path)), \
         patch("shuabao.mediator.activate_window", side_effect=AssertionError("real window access")), \
         patch("shuabao.mediator.find_window_targets", side_effect=AssertionError("real window enumeration")), \
         contextlib.redirect_stdout(io.StringIO()):
        med.set_phase(Phase.MAIN_LINE, "hitch natural round entry")
        yield med, clock


@pytest.mark.parametrize("cls", [CoreMediator, RuntimeMediator])
def test_real_victory_animation_then_button_through_tick(cls):
    with replay(cls) as (med, clock):
        clock.path = ANIMATING
        med.tick()
        assert med._trace_actions == []
        assert not med._post_game_pending
        clock.now += 1
        clock.path = VICTORY
        med.tick()
        assert [a["reason"] for a in med._trace_actions] == ["ContinueGame"]
        assert med._victory_continue_since == clock.now


@pytest.mark.parametrize("cls", [CoreMediator, RuntimeMediator])
def test_swallowed_victory_clicks_leave_before_whole_round_deadline(cls):
    with replay(cls) as (med, clock):
        reasons = []
        for _ in range(28):
            med.tick()
            reasons.extend(a["reason"] for a in med._trace_actions)
            clock.now += 16
            if med.phase != Phase.MAIN_LINE:
                break
        assert reasons.count("ContinueGame") >= 3
        assert med.phase in {Phase.QUIT, Phase.NEXT, Phase.ERROR}


@pytest.mark.parametrize("cls", [CoreMediator, RuntimeMediator])
def test_isolated_postgame_candidate_does_not_age_the_next_episode(cls):
    with replay(cls) as (med, clock):
        clock.path = ANIMATING
        med.tick()
        assert med._hitch_postgame_started_at == clock.now

        clock.now += 1
        clock.path = HUD
        med._auto_task_done = True
        med._challenge_done = set(med._challenge_states)
        med.tick()
        assert med._hitch_postgame_started_at is None

        clock.now += med._HITCH_POSTGAME_HARD_CAP_S + 1
        clock.path = VICTORY
        med.tick()
        assert med.phase == Phase.MAIN_LINE
        assert "ContinueGame" in [a["reason"] for a in med._trace_actions]


@pytest.mark.parametrize("cls", [CoreMediator, RuntimeMediator])
def test_expired_round_deadline_preempts_persistent_pressure_button(cls):
    with replay(cls) as (med, clock):
        clock.path = OPENING
        med._round_deadline = clock.now - 1
        reasons = []
        for _ in range(3):
            med.tick()
            reasons.extend(a["reason"] for a in med._trace_actions)
            clock.now += 4
        assert med.phase in {Phase.QUIT, Phase.NEXT}
        assert "HitchPressureTransfer" not in reasons


@pytest.mark.parametrize("cls", [CoreMediator, RuntimeMediator])
def test_hitch_new_round_clears_pending_input_authority(cls):
    with replay(cls) as (med, clock):
        med._pending_action = object()
        med._pending_action_unconfirmed_count = 7
        med._hitch_after_exit(clock.now)
        med.set_phase(Phase.ROOM_WAITING, "new room")
        med.set_phase(Phase.MAIN_LINE, "hitch natural round entry")
        assert med._pending_action is None
        assert med._pending_action_unconfirmed_count == 0


def test_instance_evidence_requires_consecutive_eligible_frames():
    # This is a classifier-counter test, not evidence of a real secret realm.
    med = RuntimeMediator(Settings(mode_id="lobby_hitch", ocr_mode="off"), ROOT)
    assert med._top_bar_mode(frame(HUD)) is None
    assert not med._hitch_left_plaza(frame(HUD))
    assert not med._hitch_left_plaza(frame(VICTORY))
    assert med._hitch_instance_frames == 0


@pytest.mark.parametrize("cls", [CoreMediator, RuntimeMediator])
def test_heirloom_resets_exhausted_archive_budget_before_dispatch(cls):
    with replay(cls) as (med, clock):
        clock.path = FIX / "game_heirloom_boss_grid_open.png"
        med.settings.cjb_boss = "18乌索克"
        med._post_game_pending = True
        med._post_game_route = "heirloom_active"
        med._boss_challenge_page = "ARCHIVE_PANEL"
        med._boss_challenge_attempts = 3
        med._time_cave_boss_done = True
        med.tick()
        assert med._boss_challenge_page == "HEIRLOOM_DIALOG"
        assert "DismissHeirloomDialog" not in [a["reason"] for a in med._trace_actions]


@pytest.mark.parametrize("cls", [CoreMediator, RuntimeMediator])
def test_new_round_treasure_does_not_inherit_previous_panel_timer(cls):
    with replay(cls) as (med, clock):
        med._panel_episode_started = clock.now - 120
        med._panel_state = PanelState.ACTIVE
        med._panel_kind = "treasure"
        med._hitch_after_exit(clock.now)
        med.set_phase(Phase.ROOM_WAITING, "new room")
        med.set_phase(Phase.MAIN_LINE, "hitch natural round entry")
        med._auto_task_done = True
        med._challenge_done = set(med._challenge_states)
        med._hitch_pressure_transferred = True
        med._l1_cycle_step = "treasure"
        clock.path = HUD
        med.tick()
        assert "OpenTreasurePanel" in [a["reason"] for a in med._trace_actions]
        clock.now += 1
        med.tick()
        assert med._panel_state != PanelState.COOLDOWN


@pytest.mark.parametrize("name", ["d0_a_000224.png", "d0_a_000442.png"])
def test_matrix_room_hud_overlap_is_owned_by_game_tick(name):
    with replay(RuntimeMediator) as (med, clock):
        clock.path = ROOT / "fixtures/ocr_choices/frames/rec9_mijing_20260810" / name
        image = frame(clock.path)
        # Raw classifiers overlap, but dispatch must prefer game ownership.
        assert med._hitch_room_surface_evidence(image) is not None
        assert med._is_in_game_hud(image)
        med.tick()
        assert med._context_cache_value == "MAIN_LINE"
        assert med.phase == Phase.MAIN_LINE
        assert not any(a["reason"] in {"HitchJoin", "HitchReady", "HitchSelectTab"} for a in med._trace_actions)


@pytest.mark.parametrize("cls", [CoreMediator, RuntimeMediator])
def test_pointer_parks_then_merchant_buys_on_next_real_frame(cls):
    with replay(cls) as (med, clock):
        med._auto_task_done = True
        med._challenge_done = set(med._challenge_states)
        med._hitch_pressure_transferred = True
        med._pointer_needs_park = True
        med._l1_cycle_step = "treasure"
        clock.path = FIX / "game_hud_merchant_strip_under_tooltip.png"
        med.tick()
        assert [a["reason"] for a in med._trace_actions] == ["ParkPointer"]
        assert not med._pointer_needs_park
        clock.now += 1
        clock.path = HUD
        med._l1_cycle_step = "merchant"
        med.tick()
        assert "BlackMerchant-swallow_pill" in [a["reason"] for a in med._trace_actions]
