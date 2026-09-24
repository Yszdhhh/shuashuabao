"""Owner 2026-09-24: post-game view drifted away from the plaza -> F2."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np

from shuabao.mediator import LoopAction, Mediator
from shuabao.settings import Settings
from shuabao.vision.capture import Frame

ROOT = Path(__file__).resolve().parents[1]


def _frame() -> Frame:
    return Frame(np.zeros((900, 1600, 3), dtype=np.uint8), window_title="英雄三国KK", hwnd=1, role="l1")


def _med(top_bar: str | None = "plaza") -> tuple[Mediator, list[tuple[str, str]]]:
    med = Mediator(Settings(ocr_mode="off"), ROOT)
    med._post_game_pending = True
    med._post_game_route = "heirloom"
    keys: list[tuple[str, str]] = []
    med.act_key = lambda key, reason, *a, **k: keys.append((key, reason)) or True  # type: ignore[method-assign]
    med._top_bar_mode = lambda frame: top_bar  # type: ignore[method-assign]
    med._has_active_transaction = lambda frame: False  # type: ignore[method-assign]
    return med, keys


def test_two_distinct_unclassified_plaza_frames_press_f2_once() -> None:
    med, keys = _med()
    assert med._maybe_recover_post_game_view(_frame(), None, 100.0) is None
    assert med._maybe_recover_post_game_view(_frame(), None, 101.0) is None  # < 2s
    assert med._maybe_recover_post_game_view(_frame(), None, 102.5) is LoopAction.Continue
    assert keys == [("F2", "PostGameViewReturnPlaza")]


def test_same_frame_object_never_confirms() -> None:
    med, keys = _med()
    frame = _frame()
    med._maybe_recover_post_game_view(frame, None, 100.0)
    assert med._maybe_recover_post_game_view(frame, None, 105.0) is None
    assert keys == []


def test_loading_or_instance_frames_stay_zero_input() -> None:
    med, keys = _med(top_bar=None)
    for t in (100.0, 103.0, 106.0):
        assert med._maybe_recover_post_game_view(_frame(), None, t) is None
    assert keys == []


def test_recognised_page_or_active_challenge_is_not_drift() -> None:
    med, keys = _med()
    for t in (100.0, 103.0):
        assert med._maybe_recover_post_game_view(_frame(), "NPC_HUB", t) is None
    med._post_game_route = "boss_active"
    for t in (110.0, 113.0):
        assert med._maybe_recover_post_game_view(_frame(), None, t) is None
    assert keys == []


def test_f2_is_bounded_per_post_game_transaction() -> None:
    med, keys = _med()
    t = 100.0
    for _ in range(20):
        med._maybe_recover_post_game_view(_frame(), None, t)
        t += 3.0
    assert len(keys) == Mediator._POST_GAME_VIEW_F2_MAX
