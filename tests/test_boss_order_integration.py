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

from shuabao.mediator import LoopAction, MatchResult, Mediator, Phase
from shuabao.policy.boss_order import VisibleCard
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


def test_archive_panel_partially_visible_predicted_target_clicks_directly(base_patches):
    """A toast-covered next-row target is clicked from its verified predicted slot."""
    frame = load_frame("fixtures/reborn_wow/endgame/archive_challenge_panel.png")
    settings = Settings(sgzx_boss="15莫格莱尼", mode_id="solo", ocr_mode="off")
    med = Mediator(settings, ROOT)
    med._post_game_pending = True

    visible = []
    for no in range(1, 13):
        row, col = divmod(no - 1, 4)
        x, y = 100 + col * 80, 200 + row * 75
        card = VisibleCard(no, f"{no:02d}", x, y, 58, 58, 0.9)
        hit = MatchResult(f"boss/{no:02d}", 0.9, x, y, 58, 58, x + 29, y + 29)
        visible.append((card, hit))
    predicted = MatchResult("boss/15莫格莱尼", 0.524, 1200, 425, 58, 58, 1229, 454)
    clicked = []

    with patch.object(med, "_post_game_state", return_value="ARCHIVE_PANEL"), \
         patch.object(med, "find", return_value=None), \
         patch.object(med, "_find_visible_post_game_boss_cards", return_value=visible), \
         patch.object(med, "_verify_boss_predicted_slot", return_value=predicted) as verify, \
         patch.object(med, "act_click", side_effect=lambda hit, reason="": clicked.append((hit, reason)) or True), \
         contextlib.redirect_stdout(io.StringIO()):
        action = med._maybe_challenge_configured_boss(frame, 10.0, recheck_s=1.0)

    assert action == LoopAction.Continue
    verify.assert_called_once()
    assert clicked == [(predicted, "BossConfigured")]


def test_archive_panel_target_not_unlocked_bottom_fallback(base_patches):
    """Target 55吞咽者布鲁 with at_bottom=True clicks last card with BossBottomFallback."""
    frame = load_frame("fixtures/reborn_wow/endgame/archive_challenge_panel.png")
    settings = Settings(sgzx_boss="55吞咽者布鲁", mode_id="solo", ocr_mode="off")
    med = Mediator(settings, ROOT)
    med._post_game_pending = True

    clicked = []
    from shuabao.policy.boss_order import VisibleCard
    sim_bottom_cards = [
        (VisibleCard(52, "52维希度斯", 100, 300, 58, 58, 0.9), MagicMock(name="boss/52维希度斯", center=(129, 329))),
        (VisibleCard(53, "53拉贾克斯将军", 180, 300, 58, 58, 0.9), MagicMock(name="boss/53拉贾克斯将军", center=(209, 329))),
    ]

    stdout_buf = io.StringIO()
    with patch.object(med, "_post_game_state", return_value="ARCHIVE_PANEL"), \
         patch.object(med, "find", return_value=None), \
         patch.object(med, "_find_visible_post_game_boss_cards", return_value=sim_bottom_cards), \
         patch.object(med, "_find_last_recognized_post_game_boss", return_value=sim_bottom_cards[1][1]), \
         patch.object(med, "act_click", side_effect=lambda hit, reason="": clicked.append((hit, reason)) or True), \
         patch.object(med, "_post_game_boss_list_at_bottom", return_value=True), \
         contextlib.redirect_stdout(stdout_buf):
        med.set_phase(Phase.MAIN_LINE, "integration test")
        action = med._maybe_challenge_configured_boss(frame, 10.0, recheck_s=1.0)

    assert action == LoopAction.Continue
    assert len(clicked) == 1
    hit, reason = clicked[0]
    assert reason == "BossNotUnlockedLast"
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
    """P0-A: Target 18乌索克 on 3-card heirloom dialog (no scrollbar) without patches.

    Verifies:
    1. Does not patch at_bottom, at_top, or find.
    2. Takes 2 frames to establish stability on the no-scrollbar list.
    3. Triggers BossBottomFallback clicking 03洛卡纳哈.
    4. Log contains BossNotUnlockedLast.
    """
    frame = load_frame("fixtures/reborn_wow/endgame/heirloom_challenge_bosses.png")
    settings = Settings(cjb_boss="18乌索克", mode_id="solo", ocr_mode="off")
    med = Mediator(settings, ROOT)
    med._post_game_pending = True

    clicked = []
    stdout_buf = io.StringIO()
    with patch.object(med, "act_click", side_effect=lambda hit, reason="": clicked.append((hit, reason)) or True), \
         contextlib.redirect_stdout(stdout_buf):
        med.set_phase(Phase.MAIN_LINE, "integration test")
        # Frame 1: establishes stable frame count = 1, can_scroll=False -> waits
        action1 = med._maybe_challenge_configured_boss(frame, 10.0, recheck_s=1.0)
        assert action1 == LoopAction.Continue
        assert len(clicked) == 0

        # Frame 2: stable frame count = 2 -> confirmed at bottom, clicks 03洛卡纳哈
        action2 = med._maybe_challenge_configured_boss(frame, 15.0, recheck_s=1.0)
        assert action2 == LoopAction.Continue

    assert len(clicked) == 1
    hit, reason = clicked[0]
    assert reason == "BossNotUnlockedLast"
    assert "03" in hit.name or "洛卡纳哈" in hit.name
    assert "BossNotUnlockedLast" in stdout_buf.getvalue()


def test_heirloom_dialog_target_02_clicks_directly(base_patches):
    """P0-A: Target 02血腥猛犸 on 3-card heirloom dialog without patches clicks directly on frame 1."""
    frame = load_frame("fixtures/reborn_wow/endgame/heirloom_challenge_bosses.png")
    settings = Settings(cjb_boss="02血腥猛犸", mode_id="solo", ocr_mode="off")
    med = Mediator(settings, ROOT)
    med._post_game_pending = True

    clicked = []
    with patch.object(med, "act_click", side_effect=lambda hit, reason="": clicked.append((hit, reason)) or True), \
         contextlib.redirect_stdout(io.StringIO()):
        med.set_phase(Phase.MAIN_LINE, "integration test")
        action = med._maybe_challenge_configured_boss(frame, 10.0, recheck_s=1.0)

    assert action == LoopAction.Continue
    assert len(clicked) == 1
    hit, reason = clicked[0]
    assert reason == "BossConfigured"
    assert "02" in hit.name or "血腥猛犸" in hit.name


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


def test_p0_1_verify_boss_predicted_slot_ocr_signature(base_patches):
    """P0-1: ShadowClient.shadow_predict signature and error resilience.

    Uses create_autospec(ShadowClient, instance=True) to guarantee strict signature validation.
    Verifies that status=='ok' and rec_score>=0.75 returns MatchResult,
    and any exception inside shadow_predict is caught and returns None without crashing tick.
    """
    from unittest.mock import create_autospec
    from shuabao.vision.ocr_shadow.client import ShadowClient, ShadowResponse

    med = Mediator(Settings(), ROOT)
    frame = load_frame("fixtures/reborn_wow/endgame/archive_challenge_panel.png")

    mock_ocr = create_autospec(ShadowClient, instance=True)
    mock_ocr.is_available = True
    med._ocr_client = mock_ocr

    # Case A: OCR successfully recognizes target boss name with score >= 0.75
    mock_resp = ShadowResponse(
        seq=1,
        status="ok",
        candidates=[],
        elapsed_ms=10.0,
        reason="",
        cache_hit=False,
        raw_text="53拉贾克斯将军",
        rec_score=0.85,
        model_name="test_model",
        model_hash="abc",
        model_validated=True,
    )
    mock_ocr.shadow_predict.return_value = mock_resp

    with patch.object(med, "find", return_value=None):
        result = med._verify_boss_predicted_slot(
            frame, "ARCHIVE_PANEL", "53拉贾克斯将军", (100, 200, 58, 58)
        )
    assert result is not None
    assert "ocr_boss" in result.name
    assert result.score == 0.85

    # Case B: ShadowClient raises Exception -> caught safely, returns None
    mock_ocr.shadow_predict.side_effect = RuntimeError("Simulated OCR worker crash")
    with patch.object(med, "find", return_value=None), \
         contextlib.redirect_stdout(io.StringIO()):
        result_err = med._verify_boss_predicted_slot(
            frame, "ARCHIVE_PANEL", "53拉贾克斯将军", (100, 200, 58, 58)
        )
    assert result_err is None


def test_p0_3_heirloom_missing_last_card_does_not_click_second_to_last(base_patches):
    """P0-3: On bottomed fixture, if last card is unverified, do not click second-to-last card.

    Uses heirloom_challenge_bosses.png where cards 1, 2, 3 are present.
    If card 3 is omitted from visible cards (simulating unverified card 3),
    target 3 must NOT click card 2.
    """
    frame = load_frame("fixtures/reborn_wow/endgame/heirloom_challenge_bosses.png")
    settings = Settings(cjb_boss="03洛卡纳哈", mode_id="solo", ocr_mode="off")
    med = Mediator(settings, ROOT)
    med._post_game_pending = True

    clicked = []
    # Mock visible cards to only show cards 1 and 2 (card 3 missing from recognized cards)
    from shuabao.policy.boss_order import VisibleCard
    sim_visible = [
        (VisibleCard(1, "01暴掠龙", 607, 279, 58, 58, 0.8), MagicMock(name="01暴掠龙")),
        (VisibleCard(2, "02血腥猛犸", 686, 278, 58, 58, 0.8), MagicMock(name="02血腥猛犸")),
    ]

    with patch.object(med, "_post_game_state", return_value="HEIRLOOM_DIALOG"), \
         patch.object(med, "find", return_value=None), \
         patch.object(med, "_find_visible_post_game_boss_cards", return_value=sim_visible), \
         patch.object(med, "_post_game_boss_list_at_bottom", return_value=True), \
         patch.object(med, "act_click", side_effect=lambda hit, reason="": clicked.append((hit, reason)) or True), \
         contextlib.redirect_stdout(io.StringIO()):
        med.set_phase(Phase.MAIN_LINE, "integration test")
        action = med._maybe_challenge_configured_boss(frame, 10.0, recheck_s=1.0)

    # In heirloom_challenge_bosses.png, slot 3 (765, 281) actually has card 03, so slot 3 is NOT empty.
    # Therefore, L=2 is NOT proven to be last card!
    # Target is 3 (T == L+1), so it seeks confirmation on slot 3 (CONFIRM_PREDICTED),
    # and NEVER clicks card 2!
    assert action == LoopAction.Continue
    assert len(clicked) == 0  # Does NOT click second-to-last card 2!


def test_p1_4_heirloom_dialog_scrollbar_at_top_requires_two_stable_frames():
    """P1-4: Verify HEIRLOOM_DIALOG scrollbar detection on real fixture and 2-frame stability."""
    frame = load_frame("tests/fixtures/hitch_live_20260911/game_heirloom_boss_grid_open.png")
    med = Mediator(Settings(), ROOT)

    # First observation: stable frames count becomes 1 (< 2) -> at_top is False
    top_1 = med._post_game_boss_list_at_top(frame, "HEIRLOOM_DIALOG")
    assert top_1 is False
    assert getattr(med, "_boss_challenge_scroll_top_stable_frames", 0) == 1

    # Second observation: stable frames count becomes 2 (>= 2) -> at_top is True
    top_2 = med._post_game_boss_list_at_top(frame, "HEIRLOOM_DIALOG")
    assert top_2 is True

    # At bottom must be False because thumb is at the top
    assert med._post_game_boss_list_at_bottom(frame, "HEIRLOOM_DIALOG") is False


def test_boss_order_locate_failed_fallback_clicks_last_card(base_patches):
    """When target locate attempts are exhausted, clicks last card with BossOrderLocateFailed."""
    frame = load_frame("fixtures/reborn_wow/endgame/heirloom_challenge_bosses.png")
    settings = Settings(cjb_boss="18乌索克", mode_id="solo", ocr_mode="off")
    med = Mediator(settings, ROOT)
    med.set_phase(Phase.MAIN_LINE, "integration test")
    med._post_game_pending = True
    med._boss_challenge_locate_attempts = 3
    med._boss_challenge_locate_exhausted = True

    clicked = []
    with patch.object(med, "_post_game_state", return_value="HEIRLOOM_DIALOG"), \
         patch.object(med, "find", return_value=None), \
         patch.object(med, "act_click", side_effect=lambda hit, reason="": clicked.append((hit, reason)) or True), \
         contextlib.redirect_stdout(io.StringIO()):
        # Frame 1: stable count 1
        med._maybe_challenge_configured_boss(frame, 10.0, recheck_s=1.0)
        # Frame 2: stable count 2 -> bottom confirmed, locate exhausted -> fallback
        action = med._maybe_challenge_configured_boss(frame, 12.0, recheck_s=1.0)

    assert action == LoopAction.Continue
    assert len(clicked) == 1
    hit, reason = clicked[0]
    assert reason == "BossOrderLocateFailed"
    assert "03" in hit.name or "洛卡纳哈" in hit.name


def test_boss_last_visible_fallback_when_unresolved_limit_exceeded(base_patches):
    """When list is not at bottom and unresolved limit exceeded, falls back to physically last card."""
    frame = load_frame("fixtures/reborn_wow/endgame/archive_challenge_panel.png")
    settings = Settings(sgzx_boss="55吞咽者布鲁", mode_id="solo", ocr_mode="off")
    med = Mediator(settings, ROOT)
    med.set_phase(Phase.MAIN_LINE, "integration test")
    med._post_game_pending = True
    med._boss_challenge_scroll_attempts = med._POST_GAME_BOSS_SCROLL_LIMIT

    clicked = []
    with patch.object(med, "_post_game_state", return_value="ARCHIVE_PANEL"), \
         patch.object(med, "find", return_value=None), \
         patch.object(med, "_post_game_boss_list_at_bottom", return_value=False), \
         patch.object(med, "act_click", side_effect=lambda hit, reason="": clicked.append((hit, reason)) or True), \
         contextlib.redirect_stdout(io.StringIO()):
        # Ticks 1 and 2: unresolved attempts 1, 2
        med._maybe_challenge_configured_boss(frame, 10.0, recheck_s=0.1)
        med._maybe_challenge_configured_boss(frame, 11.0, recheck_s=0.1)
        # Tick 3: unresolved limit (3) exceeded -> falls back to physically last visible card
        action = med._maybe_challenge_configured_boss(frame, 12.0, recheck_s=0.1)

    assert action == LoopAction.Continue
    assert len(clicked) == 1
    hit, reason = clicked[0]
    assert reason == "BossLastVisibleFallback"
    assert "09" in hit.name or "摩拉迪姆" in hit.name
    assert med.phase != Phase.ERROR
    assert not med.stop_signal.is_set()


def test_boss_challenge_skipped_on_all_black_frame(base_patches):
    """When no boss card is recognized on all-black frame, retries with pointer park then skips."""
    black_frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), hwnd=1)
    settings = Settings(sgzx_boss="01霍格", mode_id="solo", ocr_mode="off")
    med = Mediator(settings, ROOT)
    med.set_phase(Phase.MAIN_LINE, "integration test")
    med._post_game_pending = True
    med._boss_challenge_scroll_attempts = med._POST_GAME_BOSS_SCROLL_LIMIT

    moved = []
    clicked = []
    with patch.object(med, "_post_game_state", return_value="ARCHIVE_PANEL"), \
         patch.object(med, "_post_game_boss_list_at_bottom", return_value=False), \
         patch.object(med, "act_move", side_effect=lambda x, y, reason="": moved.append((x, y, reason)) or True), \
         patch.object(med, "act_click", side_effect=lambda hit, reason="": clicked.append((hit, reason)) or True), \
         contextlib.redirect_stdout(io.StringIO()):
        # 2 unresolved ticks + 6 anomaly retry ticks = 8 ticks
        for t in range(1, 9):
            action = med._maybe_challenge_configured_boss(black_frame, float(t), recheck_s=0.1)
            assert action == LoopAction.Continue

    # Pointer park occurred during anomaly retries
    assert len(moved) >= 1
    assert any("BossAnomalyParkPointer" in reason for _, _, reason in moved)
    # Never clicked any card
    assert len(clicked) == 0
    # Did NOT enter ERROR, did NOT stop
    assert med.phase != Phase.ERROR
    assert not med.stop_signal.is_set()
    # Advanced to close path
    assert med._time_cave_boss_done is True
    assert med._post_game_route == "archive"


def test_boss_challenge_skipped_consecutive_warn_log(base_patches):
    """When anomaly skip happens for 2 consecutive rounds, a warn-level log is emitted."""
    black_frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), hwnd=1)
    settings = Settings(sgzx_boss="01霍格", mode_id="solo", ocr_mode="off")
    med = Mediator(settings, ROOT)
    med.set_phase(Phase.MAIN_LINE, "integration test")
    med._post_game_pending = True
    med._boss_challenge_scroll_attempts = med._POST_GAME_BOSS_SCROLL_LIMIT

    stdout_buf = io.StringIO()
    with patch.object(med, "_post_game_state", return_value="ARCHIVE_PANEL"), \
         patch.object(med, "_post_game_boss_list_at_bottom", return_value=False), \
         patch.object(med, "act_move", return_value=True), \
         contextlib.redirect_stdout(stdout_buf):
        # Round 1: complete 8 ticks to skip
        for t in range(1, 9):
            med._maybe_challenge_configured_boss(black_frame, float(t), recheck_s=0.1)
        assert getattr(med, "_boss_anomaly_skip_counts", {}).get("ARCHIVE_PANEL") == 1
        assert "警告：时光之穴连续 2 局没有认出任何卡" not in stdout_buf.getvalue()

        # Arm round 2
        med._time_cave_boss_done = False
        med._boss_challenge_scroll_attempts = med._POST_GAME_BOSS_SCROLL_LIMIT
        for t in range(9, 17):
            med._maybe_challenge_configured_boss(black_frame, float(t), recheck_s=0.1)
        assert getattr(med, "_boss_anomaly_skip_counts", {}).get("ARCHIVE_PANEL") == 2
        assert "警告：时光之穴连续 2 局没有认出任何卡" in stdout_buf.getvalue()
        assert med.phase != Phase.ERROR
        assert not med.stop_signal.is_set()


def test_grid_partial_row_proves_last_boss_only_after_two_frames():
    """A full row followed by 37 and an empty 38 is a fast, safe bottom witness."""
    med = Mediator(Settings(sgzx_boss="53拉贾克斯将军", ocr_mode="off"), ROOT)
    frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), hwnd=1)
    pairs = []
    for no in range(33, 38):
        col, row = divmod(no - 1, 4)
        x, y = 100 + row * 80, 220 + col * 80
        card = VisibleCard(no, f"{no:02d}", x, y, 58, 58, 0.95)
        hit = MatchResult(f"boss/{no:02d}", 0.95, x, y, 58, 58, x + 29, y + 29)
        pairs.append((card, hit))

    first, candidate = med._post_game_boss_grid_end_card(
        frame, "ARCHIVE_PANEL", pairs, lambda _box: True
    )
    assert candidate is True
    assert first is None
    second, confirmed = med._post_game_boss_grid_end_card(
        frame, "ARCHIVE_PANEL", pairs, lambda _box: True
    )
    assert confirmed is True
    assert second is not None
    assert second.name == "boss/37"


def test_heirloom_dialog_keeps_boss_attempt_when_pending_flag_was_lost():
    """A classified heirloom dialog must not close before its configured Boss is attempted."""
    med = Mediator(Settings(cjb_boss="18乌索克", ocr_mode="off"), ROOT)
    med.set_phase(Phase.MAIN_LINE, "heirloom regression")
    med._post_game_pending = False
    med._post_game_route = "heirloom_active"
    frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), hwnd=1)

    with patch.object(med, "_post_game_state", return_value="HEIRLOOM_DIALOG"), \
         patch.object(med, "_maybe_challenge_configured_boss", return_value=LoopAction.Continue) as boss, \
         patch.object(med, "_find_heirloom_close") as close:
        action = med._tick_main_line(frame)

    assert action == LoopAction.Continue
    boss.assert_called_once()
    close.assert_not_called()


def test_heirloom_dialog_pending_configured_boss_overrides_stale_archive_route():
    """A newly classified heirloom dialog must not inherit Archive's stale route."""
    med = Mediator(Settings(cjb_boss="07古龙龟", ocr_mode="off"), ROOT)
    med.set_phase(Phase.MAIN_LINE, "heirloom stale route regression")
    med._post_game_pending = True
    med._post_game_route = "archive"
    frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), hwnd=1)

    with patch.object(med, "_post_game_state", return_value="HEIRLOOM_DIALOG"), \
         patch.object(med, "_maybe_challenge_configured_boss", return_value=LoopAction.Continue) as boss, \
         patch.object(med, "_find_heirloom_close") as close:
        action = med._tick_main_line(frame)

    assert action == LoopAction.Continue
    boss.assert_called_once()
    close.assert_not_called()


def test_archive_completion_ignores_green_chat_sized_components():
    """Green text crossing a 5/8 key card is not its green completion overlay."""
    med = Mediator(Settings(ocr_mode="off"), ROOT)
    image = np.zeros((900, 1600, 3), dtype=np.uint8)
    frame = Frame(image, hwnd=1)
    index = 4
    col, row = index % 4, index // 4
    cx = int(frame.width * med._ARCHIVE_CHALLENGE_X[col])
    cy = int(frame.height * med._ARCHIVE_CHALLENGE_Y[row])
    x0 = int(cx - frame.width * 0.040)
    y0 = int(cy - frame.height * 0.035)
    for offset in (0, 27, 54):
        image[y0 + 8:y0 + 22, x0 + 6 + offset:x0 + 26 + offset] = (0, 255, 0)
    assert med._archive_challenge_completed(frame, index) is False

    for offset in (0, 27, 54):
        image[y0 + 8:y0 + 26, x0 + 6 + offset:x0 + 26 + offset] = (0, 255, 0)
    assert med._archive_challenge_completed(frame, index) is True



