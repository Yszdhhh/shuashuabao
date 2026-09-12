"""Post-game plaza, heirloom exit rules and 秘境/团本 (user rules 2026-09-12).

After the heirloom Boss is sent a passenger exits when (1) the right-side
equipment list shows and we are still on the plaza, (2) 60s pass on the
plaza, or (3) the game fails.  Teleported into 秘境 / 团本 it stays until
that run's failure (or victory) page.

Frames: hitch_lobby_chain_20260912_101930_846970.
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
from shuabao.settings import Settings
from shuabao.vision.capture import Frame

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "hitch_live_20260911"

PLAZA = "game_postgame_plaza_npcs.png"
EXIT_DIALOG = "game_plaza_exit_confirm_with_heirloom_loot.png"
HEIRLOOM_GRID = "game_heirloom_boss_grid_open.png"
WAVE = "game_hud_after_pressure_window.png"
FAILURE = "game_failure_page_chat_over_buttons.png"


def _game(name: str) -> Frame:
    image = cv2.imdecode(np.fromfile(str(FIX / name), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None, name
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
    with patch.object(med, "act_click", side_effect=lambda _h, r="": reasons.append(r) or True), \
         patch.object(med, "act_right_click", side_effect=lambda _h, r="": reasons.append(r) or True), \
         patch.object(med, "act_key", side_effect=lambda _k, r="": reasons.append(r) or True), \
         contextlib.redirect_stdout(io.StringIO()):
        med._tick_main_line(frame)
    return reasons


def _heirloom_sent(med: Mediator, seconds_ago: float) -> None:
    med._post_game_route = "boss_active"
    med._post_game_pending = False
    med._hitch_heirloom_exit_since = time.time() - seconds_ago
    med._hitch_instance_seen = False
    med._hitch_instance_frames = 0


def test_top_bar_mode_label_tells_plaza_from_waves() -> None:
    med = _med()
    for name in (PLAZA, EXIT_DIALOG, HEIRLOOM_GRID):
        assert med._top_bar_mode(_game(name)) == "plaza", name
    assert med._top_bar_mode(_game(WAVE)) is None


def test_plaza_with_one_npc_label_in_view_is_the_npc_hub() -> None:
    med = _med()
    med._post_game_pending = True  # after ContinueGame: the hub drives the chain
    assert med._post_game_state(_game(PLAZA)) == "NPC_HUB"
    # A wave HUD never becomes the hub.
    assert med._post_game_state(_game(WAVE)) is None


def test_exit_confirmation_and_failure_page_are_not_the_rift_dialog() -> None:
    med = _med()
    assert med._post_game_state(_game(EXIT_DIALOG)) != "GREAT_RIFT_CONFIRM"
    assert med._post_game_state(_game(FAILURE)) != "GREAT_RIFT_CONFIRM"


def test_players_own_exit_confirmation_is_left_alone() -> None:
    # Live 10:53:58: the script clicked 取消 on it as "CancelGreatRift".
    med = _med()
    reasons = _tick(med, _game(EXIT_DIALOG))
    assert "CancelGreatRift" not in reasons
    assert reasons == []


def test_sixty_seconds_on_the_plaza_after_heirloom_exits() -> None:
    med = _med()
    _heirloom_sent(med, 61.0)
    _tick(med, _game(PLAZA))
    assert med.phase == Phase.QUIT


def test_heirloom_wait_holds_before_sixty_seconds() -> None:
    med = _med()
    _heirloom_sent(med, 30.0)
    _tick(med, _game(PLAZA))
    assert med.phase == Phase.MAIN_LINE


def test_equipment_list_on_the_plaza_exits_at_once() -> None:
    med = _med()
    _heirloom_sent(med, 5.0)
    with patch.object(med, "_heirloom_loot_popup_visible", return_value=True):
        _tick(med, _game(PLAZA))
    assert med.phase == Phase.QUIT


def test_teleport_into_an_instance_holds_the_exit() -> None:
    # The plaza label goes away while our in-game chrome stays, over three
    # distinct frames: 秘境 / 团本.  Neither the loot list nor 60s exits then.
    med = _med()
    _heirloom_sent(med, 61.0)
    for _ in range(3):
        _tick(med, _game(WAVE))
    assert med._hitch_instance_seen is True
    assert med.phase == Phase.MAIN_LINE
    with patch.object(med, "_heirloom_loot_popup_visible", return_value=True):
        _tick(med, _game(WAVE))
    assert med.phase == Phase.MAIN_LINE


def test_unreadable_screen_still_exits_after_a_second_window() -> None:
    med = _med()
    _heirloom_sent(med, 125.0)
    with patch.object(med, "_hitch_left_plaza", return_value=False), \
         patch.object(med, "_top_bar_mode", return_value=None):
        _tick(med, _game(WAVE))
    assert med.phase == Phase.QUIT


def test_one_odd_frame_is_not_a_teleport() -> None:
    med = _med()
    _heirloom_sent(med, 61.0)
    frame = _game(WAVE)
    for _ in range(3):
        # The same frame object again is not new evidence.
        med._hitch_left_plaza(frame)
    assert med._hitch_instance_seen is False


def test_raid_label_is_a_verdict_on_its_own() -> None:
    med = _med()
    _heirloom_sent(med, 61.0)
    with patch.object(med, "_top_bar_mode", return_value="raid"):
        assert med._hitch_left_plaza(_game(PLAZA)) is True
