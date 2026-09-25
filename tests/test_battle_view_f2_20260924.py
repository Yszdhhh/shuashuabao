"""Owner 2026-09-24: the battle/plaza view flew away -> F2 (返回阵地).

The camera box on the minimap is the evidence.  Home comes from real solo
frames (2026-09-14); "away" uses real hitch frames (2026-09-11) whose camera
sits on another quadrant, which is what a flown-away view looks like.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from shuabao.mediator import LoopAction, Mediator, PanelState
from shuabao.settings import Settings
from shuabao.vision.capture import Frame

ROOT = Path(__file__).resolve().parents[1]
HOME = ROOT / "tests/fixtures/solo_live_20260914/hud_wood_1111_f0200.png"
HOME_2 = ROOT / "tests/fixtures/solo_live_20260914/monster_selected_f0408.png"
AWAY = ROOT / "tests/fixtures/hitch_live_20260911/game_hud_item_bar_empty.png"
DIMMED = ROOT / "tests/performance/fixtures/bond_panel.png"


def _load(path: Path) -> np.ndarray:
    img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert img is not None, path
    return img


def _frame(path: Path) -> Frame:
    return Frame(_load(path), window_title="英雄三国KK", hwnd=1, role="l1")


def _med() -> tuple[Mediator, list[tuple[str, str]]]:
    med = Mediator(Settings(ocr_mode="off"), ROOT)
    keys: list[tuple[str, str]] = []
    med.act_key = lambda key, reason, *a, **k: keys.append((key, reason)) or True  # type: ignore[method-assign]
    med._is_in_game_hud = lambda frame: True  # type: ignore[method-assign]
    med._has_active_transaction = lambda frame: False  # type: ignore[method-assign]
    med._top_bar_mode = lambda frame: None  # type: ignore[method-assign]
    return med, keys


def _learn_home(med: Mediator) -> None:
    for t in (100.0, 101.5, 103.0):
        assert med._maybe_recover_battle_view(_frame(HOME if t != 101.5 else HOME_2), t) is None
    assert med._battle_view_home is not None


def test_minimap_box_reads_on_real_frames() -> None:
    med, _ = _med()
    home = med._minimap_viewport_center(_frame(HOME))
    away = med._minimap_viewport_center(_frame(AWAY))
    assert home == pytest.approx((0.23, 0.31), abs=0.03)
    assert away == pytest.approx((0.72, 0.25), abs=0.03)
    # A selection panel dims the minimap: no evidence, not "away".
    assert med._minimap_viewport_center(_frame(DIMMED)) is None


def test_home_needs_three_frames_over_three_seconds() -> None:
    med, keys = _med()
    med._maybe_recover_battle_view(_frame(HOME), 100.0)
    med._maybe_recover_battle_view(_frame(HOME), 100.5)
    med._maybe_recover_battle_view(_frame(HOME), 101.0)
    assert med._battle_view_home is None  # 3 frames but only 1s
    med._maybe_recover_battle_view(_frame(HOME), 103.0)
    assert med._battle_view_home == pytest.approx((0.23, 0.31), abs=0.03)
    assert keys == []


def test_away_two_frames_two_seconds_then_one_f2() -> None:
    med, keys = _med()
    _learn_home(med)
    assert med._maybe_recover_battle_view(_frame(AWAY), 110.0) is None
    assert med._maybe_recover_battle_view(_frame(AWAY), 111.0) is None  # < 2s
    assert med._maybe_recover_battle_view(_frame(AWAY), 112.5) is LoopAction.Continue
    assert keys == [("F2", "BattleViewReturnHome")]


def test_f2_is_rate_limited_and_bounded_until_home_again() -> None:
    med, keys = _med()
    _learn_home(med)
    for t in np.arange(110.0, 200.0, 1.5):
        med._maybe_recover_battle_view(_frame(AWAY), float(t))
    assert len(keys) == Mediator._BATTLE_VIEW_F2_MAX
    med._maybe_recover_battle_view(_frame(HOME), 201.0)
    assert med._battle_view_f2_count == 0


def test_no_home_no_input() -> None:
    med, keys = _med()
    for t in (100.0, 102.5, 105.0):
        med._maybe_recover_battle_view(_frame(AWAY), t)
    # An away-looking first view simply becomes home; never an F2 before home.
    assert keys == []


def test_open_panel_or_challenge_route_blocks_f2() -> None:
    med, keys = _med()
    _learn_home(med)
    med._panel_state = PanelState.ACTIVE
    for t in (110.0, 113.0, 116.0):
        med._maybe_recover_battle_view(_frame(AWAY), t)
    med._panel_state = PanelState.CLOSED
    med._post_game_route = "heirloom_active"
    for t in (120.0, 123.0, 126.0):
        med._maybe_recover_battle_view(_frame(AWAY), t)
    assert keys == []


def test_main_line_tick_reaches_the_battle_view_check() -> None:
    """Real combat HUD frames through _tick_main_line: home, then a flown view -> F2."""
    from unittest.mock import patch

    from shuabao.mediator import Phase

    med = Mediator(Settings(ocr_mode="off"), ROOT)
    med.set_phase(Phase.MAIN_LINE)
    med._auto_task_done = True
    keys: list[tuple[str, str]] = []
    clock = [1000.0]
    with patch("shuabao.mediator.time.time", side_effect=lambda: clock[0]), \
         patch("shuabao.input.keyboard_mouse.is_current_process_elevated", return_value=True), \
         patch.object(med, "act_key", side_effect=lambda key, reason, *a, **k: keys.append((key, reason)) or True), \
         patch.object(med, "act_click", return_value=True), \
         patch.object(med, "act_right_click", return_value=True), \
         patch.object(med, "_minimap_viewport_center", side_effect=lambda f: (0.23, 0.31) if f.meta_home else (0.72, 0.25)):
        for i in range(12):
            frame = _frame(HOME if i % 2 else HOME_2)
            frame.meta_home = i < 4  # type: ignore[attr-defined]
            med._tick_main_line(frame)
            clock[0] += 1.5
            if ("F2", "BattleViewReturnHome") in keys:
                break
    assert ("F2", "BattleViewReturnHome") in keys, keys
