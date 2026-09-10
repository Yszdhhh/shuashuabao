"""Refresh-gate tests for the 2026-09-08 live harness.

These tests do not send game input and do not claim a live PASS.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

import tools.live_harness_identity as identity
import tools.live_scenario_capture as live_capture
from shuabao.input.emergency_stop import EmergencyStopListener
from shuabao.loop_action import LoopAction
from shuabao.mediator import Mediator, Phase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from tools.live_scenario_capture import (
    LONG_CHAIN_TARGETS,
    TARGETED_PROBE_MENU,
    BundleRecorder,
    HitchLobbyChainObserver,
    SoloIngameChainObserver,
    _initial_phase_for_target,
    _invoke_target_handler,
    _start_surface_preflight,
)


ROOT = Path(__file__).resolve().parents[1]
FROZEN = "dc220e7d0bff85371c663e6320282799146e67f4"
BASE = "dc220e7d0bff85371c663e6320282799146e67f4"
OLD_HARNESS = "144c0c9adc366a35548f6e1c2e52fad8387da090"
OLD_PROD = "b15da05f4fd7313b02b2cc466e319d9683aa979c"


def _blank_frame(**kwargs) -> Frame:
    image = np.full((90, 160, 3), 18, dtype=np.uint8)
    return Frame(image, **kwargs)


def test_identity_uses_current_worktree_not_old_runtime() -> None:
    report = identity.identity_report(repo_root=ROOT)
    assert report["harness_base"] == BASE
    assert report["frozen_production_code_baseline"] == FROZEN
    assert report["production_code_diff"] == "CLEAN"
    assert report["runtime_source_verified"] is True
    assert "Production Candidate SHA" in identity.format_identity_text(report)
    assert report["harness_head"] not in {OLD_HARNESS, OLD_PROD}
    assert "solo-live-harness-20260907" not in str(report["runtime_worktree"]).replace("/", "\\")
    loaded = str(report["runtime_source_path"] or "").replace("\\", "/")
    assert "src/shuabao" in loaded
    assert "solo-live-harness-20260907" not in loaded


def test_production_code_diff_gate_is_clean_on_this_worktree() -> None:
    diff = identity.production_code_diff(ROOT)
    assert diff["status"] == "CLEAN"
    assert diff["files"] == []


def test_source_mismatch_is_not_ready_for_gt(tmp_path: Path) -> None:
    report = identity.identity_report(repo_root=tmp_path)
    assert report["ready_for_gt"] is False
    assert report["match"] == "NO"
    assert report["blocked_reasons"]


def test_old_runtime_sha_is_forbidden(monkeypatch) -> None:
    monkeypatch.setattr(identity, "commit_sha", lambda _repo: OLD_HARNESS)
    monkeypatch.setattr(identity, "is_ancestor", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(identity, "production_code_diff", lambda _repo: {"status": "CLEAN", "files": []})
    monkeypatch.setattr(
        identity,
        "runtime_source_path",
        lambda _repo: {"ok": True, "path": str(ROOT / "src" / "shuabao" / "__init__.py"), "reason": None},
    )
    report = identity.identity_report(repo_root=ROOT)
    assert report["ready_for_gt"] is False
    assert any("forbidden old runtime SHA" in reason for reason in report["blocked_reasons"])


def test_missing_precondition_is_zero_input_blocked() -> None:
    med = SimpleNamespace()
    for target in (
        "choice_bond_skill",
        "treasure",
        "hero_evolve",
        "inventory_devour",
        "archive_challenge",
        "hitch_lobby_chain",
        "solo_ingame_chain",
        "hitch_runtime",
    ):
        result = _start_surface_preflight(med, target, None)
        assert result["status"] == "BLOCKED"
        assert "ZERO INPUT" in str(result.get("reason") or "")


def test_dry_run_prepare_settings_forces_observe_mode() -> None:
    settings = live_capture._prepare_settings(None, "hero_evolve", live_input=False)
    assert settings.dry_run is True
    live = live_capture._prepare_settings(None, "boss_challenge", live_input=True)
    assert live.dry_run is False


def test_fail_bundle_schema_includes_identity_and_window(tmp_path: Path) -> None:
    recorder = BundleRecorder(
        tmp_path / "bundle",
        repo_root=ROOT,
        target="hero_evolve",
        settings=Settings(dry_run=True, ocr_mode="off"),
        initial_phase="MAIN_LINE",
        execution_mode="target_handler",
    )
    recorder.record_preflight({
        "status": "BLOCKED_PRECONDITION",
        "blocked_reasons": ["expected evolve-capable in-game HUD was not confirmed; ZERO INPUT"],
        "window": {"hwnd": 1, "title": "英雄三国", "rect": [0, 0, 1600, 900], "role": "l1"},
    })
    recorder.record_blocked(
        Mediator(Settings(dry_run=True, ocr_mode="off"), ROOT),
        _blank_frame(window_title="英雄三国", hwnd=1, role="l1"),
        status="BLOCKED_PRECONDITION",
        note="start surface missing",
    )
    recorder.finalize()
    payload = json.loads(recorder.manifest_path.read_text(encoding="utf-8"))
    for key in (
        "run_id", "target", "timestamp", "harness_sha", "harness_base_sha",
        "runtime_worktree_sha", "production_baseline_sha", "production_diff_status",
        "final_status", "window",
    ):
        assert key in payload
    assert payload["harness_base_sha"] == BASE
    assert payload["production_baseline_sha"] == FROZEN
    assert payload["production_diff_status"] == "CLEAN"
    assert payload["final_status"] == "BLOCKED_PRECONDITION"
    assert payload["window"]["hwnd"] == 1
    assert (recorder.bundle_dir / "failures").is_dir()


def test_emergency_stop_listener_is_still_wired() -> None:
    source = (ROOT / "tools" / "live_scenario_capture.py").read_text(encoding="utf-8")
    assert "EmergencyStopListener" in source
    assert "Shift+F12" in source
    assert EmergencyStopListener is not None
    launcher = (ROOT / "live_scenario_launcher.ps1").read_text(encoding="utf-8")
    assert "Shift+F12" in launcher


def test_long_chains_still_call_production_tick() -> None:
    assert _initial_phase_for_target("hitch_runtime") is Phase.MAIN_LINE
    assert _initial_phase_for_target("solo_ingame_chain") is Phase.BOOT
    assert _initial_phase_for_target("hitch_lobby_chain") is Phase.LOBBY_ROOM
    med = SimpleNamespace(tick=lambda: "TICK")
    assert _invoke_target_handler(med, "hitch_runtime", _blank_frame()) == "TICK"
    assert _invoke_target_handler(med, "solo_ingame_chain", _blank_frame()) == "TICK"
    assert _invoke_target_handler(med, "hitch_lobby_chain", _blank_frame()) == "TICK"
    assert LONG_CHAIN_TARGETS == ("hitch_runtime", "solo_ingame_chain", "hitch_lobby_chain")


def test_solo_chain_keeps_dashboard_room_creation_and_run_settings(monkeypatch) -> None:
    dashboard = Settings(
        mode_id="lobby_hitch",
        auto_create_room=True,
        cycle_num=5,
        stage_targets=["1-21"],
    )
    monkeypatch.setattr(live_capture, "_load_operator_settings", lambda _path: dashboard)

    settings = live_capture._prepare_settings(None, "solo_ingame_chain", live_input=True)

    assert settings.mode_id == "normal_farm"
    assert settings.auto_create_room is True
    assert settings.cycle_num == 5
    assert settings.stage_targets == ["1-21"]


def test_solo_chain_preflight_accepts_production_l0_start_surface() -> None:
    frame = _blank_frame(window_title="KK官方对战平台", hwnd=1, role="l0")
    med = SimpleNamespace(_startup_state=lambda _frame: "PLATFORM_MAP")

    result = _start_surface_preflight(med, "solo_ingame_chain", frame)

    assert result["status"] == "READY"
    assert result["classifier"] == "_startup_state"


def test_hitch_lobby_chain_does_not_stop_at_first_verified_hud() -> None:
    """首次进入局内只是链路中间证据，不是多局实测的终止条件。"""
    source = (ROOT / "tools" / "live_scenario_capture.py").read_text(encoding="utf-8")
    assert "recorder.solo_observer.is_pass" not in source


def test_chain_13_settings_enable_production_lobby_hitch() -> None:
    settings = live_capture._prepare_settings(None, "hitch_lobby_chain", live_input=False)
    assert settings.mode_id == "lobby_hitch"
    assert settings.auto_create_room is False
    assert settings.never_quick_join is True
    contract = live_capture.TARGET_CONTRACTS["hitch_lobby_chain"]
    assert "Mediator.tick()" in contract["production_entry"]
    assert "_tick_lobby_hitch" in contract["production_entry"]


def test_targeted_probes_call_production_handlers_not_copies() -> None:
    calls: list[str] = []
    frame = _blank_frame()
    med = SimpleNamespace(
        _l1_cycle_step="skill",
        _selection_anchor=lambda _frame: None,
        _tick_panel_fsm=lambda *_args: calls.append("panel") or LoopAction.Continue,
        _maybe_open_choice_panel=lambda *_args, **_kwargs: calls.append("open") or LoopAction.Continue,
        _tick_main_line=lambda _frame: calls.append("main") or LoopAction.Continue,
        _maybe_use_inventory_item=lambda _frame: calls.append("inventory") or LoopAction.Continue,
        _maybe_click_archive_challenge=lambda *_args: calls.append("archive") or LoopAction.Continue,
        _tick_lobby_hitch=lambda *_args, **_kwargs: calls.append("lobby") or LoopAction.Continue,
        _lobby_room_list_evidence=lambda _frame: True,
        _hitch_room_controls_visible=lambda _frame: False,
    )
    _invoke_target_handler(med, "choice_bond_skill", frame)
    _invoke_target_handler(med, "treasure", frame)
    _invoke_target_handler(med, "hero_evolve", frame)
    _invoke_target_handler(med, "inventory_devour", frame)
    _invoke_target_handler(med, "archive_challenge", frame)
    assert calls == ["panel", "panel", "main", "inventory", "archive"]
    assert med._l1_cycle_step == "evolve"
    labels = [item[1] for item in TARGETED_PROBE_MENU]
    assert labels == [
        "choice_bond_skill", "treasure", "hero_evolve", "inventory_devour",
        "inventory_hero_card", "black_merchant", "archive_challenge",
        "heirloom", "secret_realm", "lobby_search",
    ]


def test_harness_source_does_not_reimplement_production_fsms() -> None:
    source = (ROOT / "tools" / "live_scenario_capture.py").read_text(encoding="utf-8")
    launcher = (ROOT / "live_scenario_launcher.ps1").read_text(encoding="utf-8")
    for blob in (source, launcher):
        assert "import pyautogui" not in blob
        assert "keyboard.press" not in blob
        assert "mouse.click" not in blob
        assert "ctypes.windll.user32.SendInput" not in blob
    assert "class HitchSearchFSM" not in source
    assert "def search_rooms" not in source


def test_launcher_keeps_existing_lanes_and_adds_refresh_controls() -> None:
    launcher = (ROOT / "live_scenario_launcher.ps1").read_text(encoding="utf-8")
    for label in (
        "1  启动前检查",
        "11 蹭车局内完整链路",
        "12 单人完整链路",
        "13 大厅蹭车完整链路",
        "单项实机测试",
        "9  打开最新 FAIL bundle",
        "10 Reproduce 最新 FAIL",
        "READY FOR GT",
        "hitch_lobby_chain",
        "solo_ingame_chain",
        "Assert-ReadyForGt",
    ):
        assert label in launcher
    assert "GetFolderPath(\"Desktop\")" not in launcher
    assert "b15da05f4fd7313b02b2cc466e319d9683aa979c" not in launcher
    assert "solo-live-harness-20260907" not in launcher


def test_solo_observer_does_not_pass_on_click_success() -> None:
    observer = SoloIngameChainObserver()
    observer.precheck(True, {"status": "READY"})
    assert observer.is_pass is False
    hitch = HitchLobbyChainObserver()
    hitch.precheck(True, {"status": "READY"})
    assert hitch.is_pass is False


def test_probe_guard_blocks_unrelated_actions() -> None:
    guard = live_capture._capture_input_guard("hero_evolve", "target_handler")
    assert guard("click", "ClickEvolve") is None
    assert guard("click", "HitchJoin") is not None
    devour = live_capture._capture_input_guard("inventory_devour", "target_handler")
    assert devour("click", "UseInventory-hero-card") is not None
    assert devour("click", "UseInventory-swallow_pill") is None
