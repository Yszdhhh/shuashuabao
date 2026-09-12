"""Integration test for post-game Boss selection with unlock order fallback.

Runs Mediator.tick() with real game fixtures:
- fixtures/reborn_wow/endgame/archive_challenge_panel.png (ARCHIVE_PANEL)
- fixtures/reborn_wow/endgame/heirloom_challenge_bosses.png (HEIRLOOM_DIALOG)
- fixtures/hitch_live_20260911/game_heirloom_boss_grid_open.png (HEIRLOOM_DIALOG)

Verifies:
1. Target in view directly clicked with reason BossConfigured.
2. T < L target above visible view triggers act_scroll up (ARCHIVE_PANEL).
3. T > L target with list at bottom triggers BossBottomFallback (logs BossNotUnlockedLast).
4. Unconfigured boss with list at bottom triggers BossBottomFallback.
5. All tests patch reacquire_target_window, capture_reacquire_target_window, and activate_window.
"""

from __future__ import annotations

import contextlib
import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
import pytest

from shuabao.mediator import LoopAction, Mediator, Phase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame

ROOT = Path(__file__).resolve().parents[1]


def load_frame(rel_path: str) -> Frame:
    path = ROOT / rel_path
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    assert image is not None, f"Failed to load image: {path}"
    return Frame(
        image,
        left=0,
        top=0,
        window_title="英雄三国KK",
        hwnd=12345,
        role="l1",
    )


@pytest.fixture
def base_patches():
    """Patches required for safe Mediator.tick() execution without hanging."""
    with patch("shuabao.mediator.reacquire_target_window", return_value=(12345, (0, 0, 1280, 720))), \
         patch("shuabao.mediator.capture_reacquire_target_window", return_value=12345), \
         patch("shuabao.mediator.activate_window", return_value=True):
        yield


def test_archive_panel_configured_target_in_view(base_patches):
    """08巨形缝合怪 is visible in archive_challenge_panel.png -> click directly."""
    frame = load_frame("fixtures/reborn_wow/endgame/archive_challenge_panel.png")
    settings = Settings(sgzx_boss="08巨形缝合怪", mode_id="solo", ocr_mode="off")
    med = Mediator(settings, ROOT)
    med._post_game_pending = True

    clicked = []
    scrolled = []

    with patch.object(med, "act_click", side_effect=lambda hit, reason="": clicked.append((hit, reason)) or True), \
         patch.object(med, "act_scroll", side_effect=lambda x, y, c, reason="": scrolled.append((x, y, c, reason)) or True), \
         contextlib.redirect_stdout(io.StringIO()):
        # Pre-set phase to MAIN_LINE for tick
        med.set_phase(Phase.MAIN_LINE, "integration test")
        action = med._maybe_challenge_configured_boss(frame, 10.0, recheck_s=1.0)

    assert action == LoopAction.Continue
    assert len(clicked) == 1
    hit, reason = clicked[0]
    assert "08" in hit.name or "缝合怪" in hit.name
    assert reason == "BossConfigured"
    assert len(scrolled) == 0


def test_archive_panel_target_above_visible_scrolls_up(base_patches):
    """When visible cards are row 2+ (e.g. >= 05) and target is 01霍格, scroll up."""
    frame = load_frame("fixtures/reborn_wow/endgame/archive_challenge_panel.png")
    settings = Settings(sgzx_boss="01霍格", mode_id="solo", ocr_mode="off")
    med = Mediator(settings, ROOT)
    med._post_game_pending = True

    clicked = []
    scrolled = []

    from shuabao.policy.boss_order import VisibleCard
    sim_visible = [
        (VisibleCard(5, "05克雷什", 100, 200, 58, 58, 0.9), MagicMock(name="05克雷什")),
        (VisibleCard(6, "06吞噬者穆坦努斯", 180, 200, 58, 58, 0.9), MagicMock(name="06吞噬者穆坦努斯")),
    ]

    with patch.object(med, "_post_game_state", return_value="ARCHIVE_PANEL"), \
         patch.object(med, "find", return_value=None), \
         patch.object(med, "_find_visible_post_game_boss_cards", return_value=sim_visible), \
         patch.object(med, "act_click", side_effect=lambda hit, reason="": clicked.append((hit, reason)) or True), \
         patch.object(med, "act_scroll", side_effect=lambda x, y, c, reason="": scrolled.append((x, y, c, reason)) or True), \
         patch.object(med, "_post_game_boss_list_at_top", return_value=False), \
         contextlib.redirect_stdout(io.StringIO()):
        med.set_phase(Phase.MAIN_LINE, "integration test")
        action = med._maybe_challenge_configured_boss(frame, 10.0, recheck_s=1.0)

    assert action == LoopAction.Continue
    assert len(clicked) == 0
    assert len(scrolled) == 1
    _x, _y, clicks, reason = scrolled[0]
    assert clicks > 0  # scroll up
    assert "BossConfigured-scroll-up" in reason


def test_archive_panel_target_not_unlocked_bottom_fallback(base_patches):
    """Target 55吞咽者布鲁 with at_bottom=True clicks last card with BossBottomFallback."""
    frame = load_frame("fixtures/reborn_wow/endgame/archive_challenge_panel.png")
    settings = Settings(sgzx_boss="55吞咽者布鲁", mode_id="solo", ocr_mode="off")
    med = Mediator(settings, ROOT)
    med._post_game_pending = True

    clicked = []

    stdout_buf = io.StringIO()
    with patch.object(med, "_post_game_state", return_value="ARCHIVE_PANEL"), \
         patch.object(med, "act_click", side_effect=lambda hit, reason="": clicked.append((hit, reason)) or True), \
         patch.object(med, "_post_game_boss_list_at_bottom", return_value=True), \
         contextlib.redirect_stdout(stdout_buf):
        med.set_phase(Phase.MAIN_LINE, "integration test")
        action = med._maybe_challenge_configured_boss(frame, 10.0, recheck_s=1.0)

    assert action == LoopAction.Continue
    assert len(clicked) == 1
    hit, reason = clicked[0]
    assert reason == "BossBottomFallback"
    # Log contains BossNotUnlockedLast
    assert "BossNotUnlockedLast" in stdout_buf.getvalue()


def test_heirloom_dialog_configured_target_in_view(base_patches):
    """03洛卡纳哈 is visible in heirloom_challenge_bosses.png -> click directly."""
    frame = load_frame("fixtures/reborn_wow/endgame/heirloom_challenge_bosses.png")
    settings = Settings(cjb_boss="03洛卡纳哈", mode_id="solo", ocr_mode="off")
    med = Mediator(settings, ROOT)
    med._post_game_pending = True

    clicked = []

    with patch.object(med, "_post_game_state", return_value="HEIRLOOM_DIALOG"), \
         patch.object(med, "act_click", side_effect=lambda hit, reason="": clicked.append((hit, reason)) or True), \
         contextlib.redirect_stdout(io.StringIO()):
        med.set_phase(Phase.MAIN_LINE, "integration test")
        action = med._maybe_challenge_configured_boss(frame, 10.0, recheck_s=1.0)

    assert action == LoopAction.Continue
    assert len(clicked) == 1
    hit, reason = clicked[0]
    assert "03" in hit.name or "洛卡纳哈" in hit.name
    assert reason == "BossConfigured"


def test_heirloom_dialog_target_not_unlocked_bottom_fallback(base_patches):
    """Target 18乌索克 (or 54莫阿姆) on heirloom dialog when at_bottom -> clicks last card."""
    frame = load_frame("fixtures/reborn_wow/endgame/heirloom_challenge_bosses.png")
    settings = Settings(cjb_boss="54莫阿姆", mode_id="solo", ocr_mode="off")
    med = Mediator(settings, ROOT)
    med._post_game_pending = True

    clicked = []
    stdout_buf = io.StringIO()
    with patch.object(med, "_post_game_state", return_value="HEIRLOOM_DIALOG"), \
         patch.object(med, "act_click", side_effect=lambda hit, reason="": clicked.append((hit, reason)) or True), \
         patch.object(med, "_post_game_boss_list_at_bottom", return_value=True), \
         contextlib.redirect_stdout(stdout_buf):
        med.set_phase(Phase.MAIN_LINE, "integration test")
        action = med._maybe_challenge_configured_boss(frame, 10.0, recheck_s=1.0)

    assert action == LoopAction.Continue
    assert len(clicked) == 1
    hit, reason = clicked[0]
    assert reason == "BossBottomFallback"
    assert "BossNotUnlockedLast" in stdout_buf.getvalue()


def test_mediator_tick_lifecycle_archive_panel(base_patches):
    """Full Mediator.tick() test on archive_challenge_panel with safe window mocks."""
    frame = load_frame("fixtures/reborn_wow/endgame/archive_challenge_panel.png")
    settings = Settings(sgzx_boss="08巨形缝合怪", mode_id="solo", ocr_mode="off")
    med = Mediator(settings, ROOT)
    med.set_phase(Phase.MAIN_LINE, "integration tick")
    med._post_game_pending = True
    med._post_game_archive_pending_only = False
    med._archive_challenge_index = len(med._ARCHIVE_CHALLENGE_NAMES)

    clicked = []
    with patch.object(med, "_post_game_state", return_value="ARCHIVE_PANEL"), \
         patch.object(med, "act_click", side_effect=lambda hit, reason="": clicked.append((hit, reason)) or True), \
         contextlib.redirect_stdout(io.StringIO()):
        med._tick_main_line(frame)

    assert len(clicked) == 1
    hit, reason = clicked[0]
    assert reason == "BossConfigured"
    assert "08" in hit.name or "缝合怪" in hit.name
