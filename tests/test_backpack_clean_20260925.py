# -*- coding: utf-8 -*-
"""Tests for hitch passenger in-game auto backpack clean (2026-09-25).

Covers:
1. Full 6-tick transaction on live captured frames (hud -> archive -> equip tab -> decompose -> quality yes -> return game -> hud).
2. Legend checked on quality dialog: clicks "否", never "是".
3. Unreadable checkbox count (4-19 pixels): clicks "否", never "是".
4. Disabled (auto_clean_backpack=False): zero input, advances cycle.
5. Not due (game_count - last_round < clean_backpack_every_rounds): zero input, advances cycle.
6. Non-passenger mode (e.g. normal_farm): zero input, advances cycle.
7. 45s hard cap convergence: timeout terminates transaction, records last_round = game_count, no retry in current round.
8. Step timeout fallback: clicks return_game if visible on unexpected screen/timeout.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
import time

import cv2
import numpy as np
import pytest

from shuabao.mediator import LoopAction, Mediator, Phase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult
from tools.live_scenario_capture import BundleRecorder, _invoke_target_handler, _start_surface_preflight, build_parser

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "backpack_clean_20260925"


def test_capture_target_uses_production_handler_with_fake_input() -> None:
    class FakeInput:
        def __init__(self) -> None:
            self.reasons: list[str] = []

        def click(self, target: MatchResult, reason: str = "") -> bool:
            self.reasons.append(reason)
            return True

    args = build_parser().parse_args(["capture", "--target", "backpack_clean", "--backpack-entry", "ingame", "--out", str(ROOT)])
    assert args.backpack_entry == "ingame"
    med = _make_mediator()
    fake = FakeInput()
    med.act_click = fake.click
    med._backpack_clean_solo = False
    med._backpack_clean_phase = "wait_cundang"
    med._backpack_clean_phase_since = time.time()
    med._backpack_clean_deadline = time.time() + 45
    frames = [_load_frame(name) for name in (
        "01_hud.png", "02_page_items_tab.png", "03_page_equip_tab.png",
        "04_quality_dialog.png", "05_dialog_closed.png", "06_hud_returned.png",
    )]
    assert _start_surface_preflight(med, "backpack_clean", frames[0])["status"] == "READY"
    for frame in frames:
        assert _invoke_target_handler(med, "backpack_clean", frame) == LoopAction.Continue
    assert med._backpack_clean_phase == "idle"
    assert med._backpack_clean_abort_reason is None
    assert fake.reasons == [
        "backpack_clean:hud_cundang", "backpack_clean:zhuangbei",
        "backpack_clean:decompose", "backpack_clean:quality_yes",
        "backpack_clean:return_game",
    ]


def test_capture_target_stage_requires_stage_entry() -> None:
    med = _make_mediator(Settings(dry_run=True, mode_id="normal_farm"))
    med._backpack_clean_solo = True
    assert _start_surface_preflight(med, "backpack_clean", _load_frame("01_hud.png"))["status"] == "BLOCKED"


@pytest.mark.parametrize("status,reason", [("cleaned", "return_verified"), ("aborted", "quality_check_failed")])
def test_capture_manifest_reports_transaction_result(tmp_path: Path, status: str, reason: str) -> None:
    recorder = BundleRecorder(
        tmp_path / "bundle", repo_root=ROOT, target="backpack_clean",
        settings=Settings(dry_run=True), initial_phase="MAIN_LINE", execution_mode="target_handler",
    )
    recorder.manifest["backpack_result"] = {"status": status, "reason": reason}
    assert recorder._compute_final_status() == (status, reason)


def _load_frame(filename: str) -> Frame:
    path = FIXTURES / filename
    img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert img is not None, f"Failed to load fixture frame: {path}"
    return Frame(bgr=img, window_title="英雄三国KK", hwnd=10001, role="l1")


def _make_mediator(settings: Settings | None = None) -> Mediator:
    if settings is None:
        settings = Settings(
            dry_run=True,
            mode_id="lobby_hitch",
            auto_clean_backpack=True,
            clean_backpack_every_rounds=10,
            cycle_num=10,
        )
    med = Mediator(settings, ROOT)
    med.set_phase(Phase.MAIN_LINE)
    med.game_count = 10
    med._auto_task_done = True
    med._skip_auto_task_gate = True
    med._l1_cycle_step = "backpack_clean"
    return med


def test_full_backpack_clean_transaction() -> None:
    """Live 6-frame end-to-end transaction: 存档 -> 装备 -> 一键分解 -> 是 -> 返回游戏 -> HUD恢复."""
    med = _make_mediator()
    clicks: list[tuple[str, str, tuple[int, int]]] = []

    def fake_click(target: MatchResult, reason: str = "") -> bool:
        name = target.name if hasattr(target, "name") else str(target)
        center = (target.screen_x, target.screen_y) if hasattr(target, "screen_x") else (0, 0)
        clicks.append((name, reason, center))
        return True

    med.act_click = fake_click

    f1 = _load_frame("01_hud.png")
    f2 = _load_frame("02_page_items_tab.png")
    f3 = _load_frame("03_page_equip_tab.png")
    f4 = _load_frame("04_quality_dialog.png")
    f5 = _load_frame("05_dialog_closed.png")
    f6 = _load_frame("06_hud_returned.png")

    # Tick 1: HUD -> click hud_cundang -> wait_archive
    res1 = med._tick_main_line(f1)
    assert res1 == LoopAction.Continue
    assert med._backpack_clean_phase == "wait_archive"
    assert len(clicks) == 1
    assert clicks[0][1] == "backpack_clean:hud_cundang"

    # Tick 2: Archive open (items tab) -> click zhuangbei -> wait_decompose
    res2 = med._tick_main_line(f2)
    assert res2 == LoopAction.Continue
    assert med._backpack_clean_phase == "wait_decompose"
    assert len(clicks) == 2
    assert clicks[1][1] == "backpack_clean:zhuangbei"

    # Tick 3: Equip tab active -> click decompose -> wait_quality_dialog
    res3 = med._tick_main_line(f3)
    assert res3 == LoopAction.Continue
    assert med._backpack_clean_phase == "wait_quality_dialog"
    assert len(clicks) == 3
    assert clicks[2][1] == "backpack_clean:decompose"

    # Tick 4: Quality dialog -> checkboxes: jingliang=True, shishi=True, chuanshuo=False -> click quality_yes -> wait_quality_disappear
    res4 = med._tick_main_line(f4)
    assert res4 == LoopAction.Continue
    assert med._backpack_clean_phase == "wait_quality_disappear"
    assert len(clicks) == 4
    assert clicks[3][1] == "backpack_clean:quality_yes"

    # Tick 5: Dialog dismissed -> click return_game -> wait_hud_return
    res5 = med._tick_main_line(f5)
    assert res5 == LoopAction.Continue
    assert med._backpack_clean_phase == "wait_hud_return"
    assert len(clicks) == 5
    assert clicks[4][1] == "backpack_clean:return_game"

    # Tick 6: Returned to HUD -> detects hud_cundang -> finish
    res6 = med._tick_main_line(f6)
    assert res6 == LoopAction.Continue
    assert med._backpack_clean_phase == "idle"
    assert med._backpack_clean_last_round == 10
    assert med._l1_cycle_step == "merchant"
    assert len(clicks) == 5


def test_solo_stage_page_clean_returns_to_lobby_tab() -> None:
    settings = Settings(
        dry_run=True,
        mode_id="normal_farm",
        auto_clean_backpack=True,
        clean_backpack_every_rounds=10,
    )
    med = _make_mediator(settings)
    med.set_phase(Phase.STAGE_SELECT)
    med._observe_ticket_balance = lambda frame: None
    clicks: list[str] = []
    med.act_click = lambda target, reason="": clicks.append(reason) or True
    stage_path = ROOT / "fixtures" / "stage_select_20260814" / "highlight_on_1_1_client_1600x900.png"
    stage_img = cv2.imdecode(np.fromfile(str(stage_path), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert stage_img is not None
    stage = Frame(bgr=stage_img, window_title="英雄三国KK", hwnd=10001, role="l1")
    stage_returned = Frame(bgr=stage_img.copy(), window_title="英雄三国KK", hwnd=10001, role="l1")

    frames = [
        stage,
        _load_frame("02_page_items_tab.png"),
        _load_frame("03_page_equip_tab.png"),
        _load_frame("04_quality_dialog.png"),
        _load_frame("05_dialog_closed.png"),
        stage_returned,
    ]
    for frame in frames:
        assert med._tick_l0(frame) == LoopAction.Continue

    assert clicks == [
        "backpack_clean:tab_cundang",
        "backpack_clean:zhuangbei",
        "backpack_clean:decompose",
        "backpack_clean:quality_yes",
        "backpack_clean:tab_lobby",
    ]
    assert med._backpack_clean_phase == "idle"
    assert med._backpack_clean_last_round == 10
    assert med.phase == Phase.STAGE_SELECT


@pytest.mark.parametrize(
    ("mode_id", "enabled", "last_round"),
    [
        ("normal_farm", False, 0),
        ("normal_farm", True, 5),
        ("lobby_hitch", True, 0),
    ],
)
def test_stage_page_clean_skips_disabled_not_due_and_passenger_mode(
    mode_id: str, enabled: bool, last_round: int
) -> None:
    settings = Settings(
        dry_run=True,
        mode_id=mode_id,
        auto_clean_backpack=enabled,
        clean_backpack_every_rounds=10,
    )
    med = _make_mediator(settings)
    med.set_phase(Phase.STAGE_SELECT)
    med._backpack_clean_last_round = last_round
    med._observe_ticket_balance = lambda frame: None
    med._stage_budget_guard = lambda now: LoopAction.Continue
    clicks: list[str] = []
    med.act_click = lambda target, reason="": clicks.append(reason) or True
    stage_path = ROOT / "fixtures" / "stage_select_20260814" / "highlight_on_1_1_client_1600x900.png"
    stage_img = cv2.imdecode(np.fromfile(str(stage_path), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert stage_img is not None
    frame = Frame(bgr=stage_img, window_title="英雄三国KK", hwnd=10001, role="l1")

    assert med._tick_l0(frame) == LoopAction.Continue
    assert med._backpack_clean_phase == "idle"
    assert clicks == []


def test_backpack_clean_legend_checked_clicks_no() -> None:
    """When chuanshuo (legend) checkbox is checked, must click 「否」, never 「是」."""
    med = _make_mediator()
    clicks: list[tuple[str, str, tuple[int, int]]] = []

    def fake_click(target: MatchResult, reason: str = "") -> bool:
        name = target.name if hasattr(target, "name") else str(target)
        center = (target.screen_x, target.screen_y) if hasattr(target, "screen_x") else (0, 0)
        clicks.append((name, reason, center))
        return True

    med.act_click = fake_click

    f4 = _load_frame("04_quality_dialog.png")
    # Synthetic modification: draw green pixels in chuanshuo checkbox
    # Title is at (630, 332). Chuanshuo box is x in [890, 909), y in [376, 396)
    synth_bgr = f4.bgr.copy()
    # Draw green pixels (HSV H~60, S=255, V=255)
    synth_bgr[380:392, 895:905] = (0, 255, 0)
    synth_frame = Frame(bgr=synth_bgr, window_title=f4.window_title, hwnd=f4.hwnd, role=f4.role)

    # Put state machine in wait_quality_dialog
    med._backpack_clean_phase = "wait_quality_dialog"
    med._backpack_clean_started_at = time.time()
    med._backpack_clean_deadline = time.time() + 45.0
    med._backpack_clean_phase_since = time.time()

    res = med._tick_main_line(synth_frame)
    assert res == LoopAction.Continue
    assert len(clicks) == 1
    hit_name, reason, center = clicks[0]
    assert reason == "backpack_clean:quality_no"
    assert "quality_yes" not in reason
    # "否" comes from its own real-frame template, centered at (885, 471).
    assert center == (885, 471)
    assert med._backpack_clean_phase == "wait_quality_disappear"


def test_backpack_clean_unreadable_clicks_no() -> None:
    """When a checkbox has ambiguous green pixel count (between 4 and 19), must click 「否」."""
    med = _make_mediator()
    clicks: list[tuple[str, str, tuple[int, int]]] = []

    def fake_click(target: MatchResult, reason: str = "") -> bool:
        name = target.name if hasattr(target, "name") else str(target)
        clicks.append((name, reason, (target.screen_x, target.screen_y)))
        return True

    med.act_click = fake_click

    f4 = _load_frame("04_quality_dialog.png")
    synth_bgr = f4.bgr.copy()
    # Draw exactly 10 green pixels in chuanshuo box
    synth_bgr[380:382, 895:900] = (0, 255, 0)
    synth_frame = Frame(bgr=synth_bgr, window_title=f4.window_title, hwnd=f4.hwnd, role=f4.role)

    med._backpack_clean_phase = "wait_quality_dialog"
    med._backpack_clean_started_at = time.time()
    med._backpack_clean_deadline = time.time() + 45.0
    med._backpack_clean_phase_since = time.time()

    res = med._tick_main_line(synth_frame)
    assert res == LoopAction.Continue
    assert len(clicks) == 1
    assert clicks[0][1] == "backpack_clean:quality_no"


def test_backpack_clean_disabled_zero_input() -> None:
    """When auto_clean_backpack is False, zero clicks and cycle advances."""
    settings = Settings(
        dry_run=True,
        mode_id="lobby_hitch",
        auto_clean_backpack=False,
        clean_backpack_every_rounds=10,
        cycle_num=10,
    )
    med = _make_mediator(settings)
    clicks: list[str] = []
    med.act_click = lambda target, reason="": clicks.append(reason) or True

    f1 = _load_frame("01_hud.png")
    res = med._tick_main_line(f1)
    assert res == LoopAction.Continue
    assert len(clicks) == 0
    assert med._l1_cycle_step == "merchant"
    assert med._backpack_clean_phase == "idle"


def test_backpack_clean_not_due_zero_input() -> None:
    """When game_count - last_round < clean_backpack_every_rounds, zero clicks and cycle advances."""
    med = _make_mediator()
    med.game_count = 10
    med._backpack_clean_last_round = 5  # 10 - 5 = 5 < 10
    clicks: list[str] = []
    med.act_click = lambda target, reason="": clicks.append(reason) or True

    f1 = _load_frame("01_hud.png")
    res = med._tick_main_line(f1)
    assert res == LoopAction.Continue
    assert len(clicks) == 0
    assert med._l1_cycle_step == "merchant"
    assert med._backpack_clean_phase == "idle"


def test_backpack_clean_non_passenger_mode_zero_input() -> None:
    """In non-passenger mode (e.g. normal_farm), zero clicks and cycle advances."""
    settings = Settings(
        dry_run=True,
        mode_id="normal_farm",
        auto_clean_backpack=True,
        clean_backpack_every_rounds=10,
        merchant_enabled=False,
    )
    med = _make_mediator(settings)
    clicks: list[str] = []
    med.act_click = lambda target, reason="": clicks.append(reason) or True

    f1 = _load_frame("01_hud.png")
    res = med._tick_main_line(f1)
    assert res == LoopAction.Continue
    assert len(clicks) == 0
    assert med._l1_cycle_step != "backpack_clean"
    assert med._backpack_clean_phase == "idle"


def test_backpack_clean_45s_hard_cap_converges_and_no_retry() -> None:
    """An unverified page after 45s stops the run without another click."""
    med = _make_mediator()
    clicks: list[str] = []
    med.act_click = lambda target, reason="": clicks.append(reason) or True

    f1 = _load_frame("01_hud.png")
    # Start transaction on f1
    med._tick_main_line(f1)
    assert med._backpack_clean_phase == "wait_archive"
    assert len(clicks) == 1

    # Simulate unknown frame stuck past 45s hard cap
    black_frame = Frame(bgr=np.zeros((900, 1600, 3), dtype=np.uint8), window_title="英雄三国KK", hwnd=10001, role="l1")

    # Fast forward deadline past 45s
    med._backpack_clean_deadline = time.time() - 1.0

    res = med._tick_main_line(black_frame)
    assert res == LoopAction.Break
    assert med.phase == Phase.ERROR
    assert med._backpack_clean_phase == "idle"
    assert med._backpack_clean_last_round == 10  # Marked current round done
    assert med._backpack_clean_abort_reason is not None
    assert len(clicks) == 1  # No new clicks


def test_backpack_clean_step_timeout_fallback_return_game() -> None:
    """On step timeout (e.g. decompose not found for 10s), if return_game is visible, click it to exit."""
    med = _make_mediator()
    clicks: list[tuple[str, str]] = []

    def fake_click(target: MatchResult, reason: str = "") -> bool:
        name = target.name if hasattr(target, "name") else str(target)
        clicks.append((name, reason))
        return True

    med.act_click = fake_click

    # Start in wait_decompose
    med._backpack_clean_phase = "wait_decompose"
    med._backpack_clean_started_at = time.time()
    med._backpack_clean_deadline = time.time() + 45.0
    # Simulate step timeout
    med._backpack_clean_phase_since = time.time() - 11.0

    # Frame 02 has return_game visible, but decompose is missing
    f2 = _load_frame("02_page_items_tab.png")
    f6 = _load_frame("06_hud_returned.png")

    orig_find = med.find

    def patched_find(frame, targets, **kwargs):
        if "decompose" in targets or targets == ["decompose"]:
            return None
        if "zhuangbei" in targets:
            return None
        return orig_find(frame, targets, **kwargs)

    with patch.object(med, "find", side_effect=patched_find):
        res = med._tick_main_line(f2)

    assert res == LoopAction.Continue
    assert len(clicks) == 1
    assert clicks[0][0] == "return_game"
    assert "return_game" in clicks[0][1] or "abort" in clicks[0][1]
    assert med._backpack_clean_phase == "wait_hud_return"
    assert med._backpack_clean_last_round == 10

    # Next tick: HUD returns -> phase idle
    res2 = med._tick_main_line(f6)
    assert res2 == LoopAction.Continue
    assert med._backpack_clean_phase == "idle"
