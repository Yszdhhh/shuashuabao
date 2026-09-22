"""时光之穴 Boss 点击后置确认（2026-09-22 真机回归）。

Bundle: C:\\tmp\\shuabao-captures\\hitch_lobby_chain_20260922_002105_993691
tick 320–351：点击「18瑟莱德丝公主」后列表被掉落弹窗替换（f0310），
旧逻辑 1.0s 盲等后继续在空列表上滚动 4 次 → BossAnomalyParkPointer ×3
→ boss_challenge_skipped。

夹具帧全部来自该 bundle 的 frames/，非合成图。
"""

from __future__ import annotations

import contextlib
import io
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
import pytest

from shuabao.mediator import LoopAction, Mediator, Phase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "boss_challenge_20260922"


def load_frame(name: str) -> Frame:
    path = FIXTURES / name
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    assert image is not None, f"missing fixture: {path}"
    return Frame(image, left=0, top=0, window_title="英雄三国KK", hwnd=12345, role="l1")


@pytest.fixture
def base_patches():
    with patch("shuabao.mediator.reacquire_target_window", return_value=(12345, (0, 0, 1600, 900))), \
         patch("shuabao.mediator.capture_reacquire_target_window", return_value=12345), \
         patch("shuabao.mediator.activate_window", return_value=True):
        yield


def make_med(sgzx_boss: str = "18瑟莱德丝公主", cjb_boss: str = "17年兽") -> Mediator:
    settings = Settings(sgzx_boss=sgzx_boss, cjb_boss=cjb_boss, mode_id="solo", ocr_mode="off")
    med = Mediator(settings, ROOT)
    med._post_game_pending = True
    med.set_phase(Phase.MAIN_LINE, "boss_challenge_20260922")
    return med


def test_fixture_frames_exist():
    for name in (
        "f0309_before_click_18.png",
        "f0310_after_click_18.png",
        "f0311_before_scroll1.png",
        "f0318_after_scroll4.png",
        "f0326_before_click_17.png",
        "f0327_after_click_17.png",
    ):
        assert (FIXTURES / name).is_file(), name


def test_time_cave_list_alive_on_open_panel(base_patches):
    """f0309：时光之穴列表仍打开 → 锚点存在，允许有界滚动。"""
    frame = load_frame("f0309_before_click_18.png")
    med = make_med()
    pairs = med._find_visible_post_game_boss_cards(frame, "ARCHIVE_PANEL")
    assert med._post_game_boss_list_alive(frame, "ARCHIVE_PANEL", pairs) is True


def test_time_cave_list_not_alive_after_click(base_patches):
    """f0310/f0311/f0318：列表被掉落弹窗/地图替换 → 无锚点，禁止滚动。"""
    med = make_med()
    for name in ("f0310_after_click_18.png", "f0311_before_scroll1.png", "f0318_after_scroll4.png"):
        frame = load_frame(name)
        pairs = med._find_visible_post_game_boss_cards(frame, "ARCHIVE_PANEL")
        assert pairs == [], name
        assert med._post_game_boss_list_alive(frame, "ARCHIVE_PANEL", pairs) is False, name


def test_time_cave_result_visible_after_click(base_patches):
    """点击后列表关闭即挑战受理后置，双帧稳定后为 True。"""
    med = make_med()
    med._time_cave_boss_clicked_at = 100.0
    f1 = load_frame("f0310_after_click_18.png")
    f2 = load_frame("f0311_before_scroll1.png")
    assert med._time_cave_boss_result_visible(f1) is False  # 首帧只累计
    assert med._time_cave_boss_result_visible(f2) is True
    assert med._time_cave_boss_clear_frames >= 2


def test_no_scroll_after_click_on_replaced_list(base_patches):
    """核心回归：点击后在 f0310/f0311（列表已关）上绝不 act_scroll。"""
    med = make_med()
    med._boss_challenge_attempts = 1
    med._time_cave_boss_clicked_at = 100.0
    med._boss_challenge_next_at = 0.0
    scrolled = []
    clicked = []

    f1 = load_frame("f0310_after_click_18.png")
    f2 = load_frame("f0311_before_scroll1.png")

    with patch.object(med, "act_scroll", side_effect=lambda x, y, c, reason="": scrolled.append(reason) or True), \
         patch.object(med, "act_click", side_effect=lambda hit, reason="": clicked.append(reason) or True), \
         patch.object(med, "act_move", return_value=True), \
         contextlib.redirect_stdout(io.StringIO()):
        # 双帧稳定：第一帧累计，第二帧确认列表关闭
        a1 = med._maybe_challenge_configured_boss(f1, 101.0, recheck_s=0.35)
        a2 = med._maybe_challenge_configured_boss(f2, 102.0, recheck_s=0.35)

    assert a1 == LoopAction.Continue
    assert a2 == LoopAction.Continue
    assert scrolled == [], f"点击后不得滚动，实际: {scrolled}"
    assert clicked == [], f"点击后不得重复点击，实际: {clicked}"
    assert med._time_cave_boss_done is True
    assert med._time_cave_boss_result_confirmed is True


def test_no_scroll_when_no_anchor_without_click(base_patches):
    """未点击且看不到卡片/滑块 → 零输入，不滚动。"""
    frame = load_frame("f0318_after_scroll4.png")
    med = make_med()
    med._boss_challenge_next_at = 0.0
    scrolled = []

    with patch.object(med, "act_scroll", side_effect=lambda x, y, c, reason="": scrolled.append(reason) or True), \
         patch.object(med, "act_click", return_value=True), \
         patch.object(med, "act_move", return_value=True), \
         contextlib.redirect_stdout(io.StringIO()):
        action = med._maybe_challenge_configured_boss(frame, 10.0, recheck_s=0.35)

    assert action == LoopAction.Continue
    assert scrolled == [], f"无锚点不得滚动，实际: {scrolled}"


def test_unconfirmed_timeout_skips_with_evidence(base_patches):
    """后置超时：安全跳过并留证据，不滚动、不计成功。"""
    frame = load_frame("f0311_before_scroll1.png")
    med = make_med()
    med._boss_challenge_attempts = 1
    med._time_cave_boss_clicked_at = 100.0
    med._boss_challenge_next_at = 0.0
    # 强制 result 不可见（clear_frames 已满但再喂一帧可见卡），走超时分支
    med._time_cave_boss_clear_frames = 0
    med._time_cave_boss_clear_last_frame = frame
    incidents = []
    scrolled = []

    with patch.object(med, "_time_cave_boss_result_visible", return_value=False), \
         patch.object(med, "_record_boss_challenge_skipped_incident",
                      side_effect=lambda page, reason="anomaly": incidents.append((page, reason))), \
         patch.object(med, "act_scroll", side_effect=lambda x, y, c, reason="": scrolled.append(reason) or True), \
         patch.object(med, "act_move", return_value=True), \
         contextlib.redirect_stdout(io.StringIO()):
        action = med._maybe_challenge_configured_boss(frame, 100.0 + med._TIME_CAVE_BOSS_CONFIRM_TIMEOUT_S + 0.1, recheck_s=0.35)

    assert action == LoopAction.Continue
    assert scrolled == []
    assert med._time_cave_boss_done is True
    assert med._time_cave_boss_confirm_unconfirmed is True
    assert incidents == [("ARCHIVE_PANEL", "post_click_unconfirmed")]


def test_post_click_wait_is_zero_action(base_patches):
    """后置窗口内（未确认未超时）必须零动作。"""
    frame = load_frame("f0311_before_scroll1.png")
    med = make_med()
    med._boss_challenge_attempts = 1
    med._time_cave_boss_clicked_at = 100.0
    med._boss_challenge_next_at = 0.0
    scrolled, clicked, moved = [], [], []

    with patch.object(med, "_time_cave_boss_result_visible", return_value=False), \
         patch.object(med, "act_scroll", side_effect=lambda x, y, c, reason="": scrolled.append(reason) or True), \
         patch.object(med, "act_click", side_effect=lambda hit, reason="": clicked.append(reason) or True), \
         patch.object(med, "act_move", side_effect=lambda x, y, reason="": moved.append(reason) or True), \
         contextlib.redirect_stdout(io.StringIO()):
        action = med._maybe_challenge_configured_boss(frame, 102.0, recheck_s=0.35)

    assert action == LoopAction.Continue
    assert scrolled == [] and clicked == [] and moved == []
    assert med._time_cave_boss_done is False
    assert med._time_cave_boss_clicked_at == 100.0


def test_click_target_on_open_list_still_works(base_patches):
    """f0309 列表打开时仍应命中配置 Boss（不因修复而丢点击）。"""
    frame = load_frame("f0309_before_click_18.png")
    med = make_med(sgzx_boss="18瑟莱德丝公主")
    med._post_game_pending = True
    clicked, scrolled = [], []

    with patch.object(med, "_post_game_state", return_value="ARCHIVE_PANEL"), \
         patch.object(med, "act_click", side_effect=lambda hit, reason="": clicked.append((hit.name, reason)) or True), \
         patch.object(med, "act_scroll", side_effect=lambda x, y, c, reason="": scrolled.append(reason) or True), \
         contextlib.redirect_stdout(io.StringIO()):
        action = med._maybe_challenge_configured_boss(frame, 10.0, recheck_s=1.0)

    assert action == LoopAction.Continue
    assert clicked, "配置 Boss 在视野内必须点击"
    _name, reason = clicked[0]
    assert reason == "BossConfigured"
    assert med._time_cave_boss_clicked_at == 10.0
    assert scrolled == []


def test_heirloom_click_on_real_frame(base_patches):
    """f0326 传家宝列表：17年兽 仍走 BossConfigured（问题现场后半段正常）。"""
    frame = load_frame("f0326_before_click_17.png")
    med = make_med(cjb_boss="17年兽")
    med._post_game_pending = True
    clicked = []

    with patch.object(med, "_post_game_state", return_value="HEIRLOOM_DIALOG"), \
         patch.object(med, "act_click", side_effect=lambda hit, reason="": clicked.append((hit.name, reason)) or True), \
         patch.object(med, "act_scroll", return_value=True), \
         contextlib.redirect_stdout(io.StringIO()):
        action = med._maybe_challenge_configured_boss(frame, 10.0, recheck_s=1.0)

    assert action == LoopAction.Continue
    assert clicked, "17年兽 应被识别"
    name, reason = clicked[0]
    assert "17" in name or "年兽" in name
    assert reason == "BossConfigured"
