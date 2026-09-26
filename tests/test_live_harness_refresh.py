"""Refresh-gate tests for the 2026-09-08 live harness.

These tests do not send game input and do not claim a live PASS.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

import tools.live_harness_identity as identity
import tools.live_scenario_capture as live_capture
from shuabao.input.emergency_stop import EmergencyStopListener
from shuabao.loop_action import LoopAction
from shuabao.mediator import Mediator, Phase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult
from tests.test_scenario_replay import FakeClock
from tools.live_scenario_capture import (
    LONG_CHAIN_TARGETS,
    TARGETED_PROBE_MENU,
    BundleRecorder,
    HitchLobbyChainObserver,
    SoloIngameChainObserver,
    _initial_phase_for_target,
    _arm_direct_archaeology_after_stage_select,
    _invoke_target_handler,
    _start_surface_preflight,
)


ROOT = Path(__file__).resolve().parents[1]
FROZEN = "7a6c36bbbdc39064ceed1aebd9ffc301bfeea342"
BASE = identity.load_identity_manifest(ROOT)["candidate_sha"]
OLD_HARNESS = "144c0c9adc366a35548f6e1c2e52fad8387da090"
OLD_PROD = "b15da05f4fd7313b02b2cc466e319d9683aa979c"


def _blank_frame(**kwargs) -> Frame:
    image = np.full((90, 160, 3), 18, dtype=np.uint8)
    return Frame(image, **kwargs)


def test_identity_uses_current_worktree_not_old_runtime() -> None:
    report = identity.identity_report(repo_root=ROOT)
    assert report["harness_base"] == BASE
    assert report["candidate_anchor_sha"] == identity.load_identity_manifest(ROOT)["candidate_sha"]
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
    assert diff["candidate_anchor_sha"] == BASE


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
    assert payload["harness_base_sha"] == identity.candidate_anchor_sha(ROOT)
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
        bonds=["chengzhang", "jingji"],
        cards=["dasheng", "fengshen"],
        auto_bond=False,
        auto_treasure=False,
        auto_devour_dan=False,
    )
    monkeypatch.setattr(live_capture, "_load_operator_settings", lambda _path: dashboard)

    settings = live_capture._prepare_settings(None, "solo_ingame_chain", live_input=True)

    assert settings.mode_id == "normal_farm"
    assert settings.auto_create_room is True
    assert settings.cycle_num == 5
    assert settings.stage_targets == ["1-21"]
    assert settings.bonds == dashboard.bonds
    assert settings.cards == dashboard.cards
    assert settings.auto_bond is False
    assert settings.auto_treasure is False
    assert settings.auto_devour_dan is False


def test_12_launcher_requires_current_dashboard_settings_by_default() -> None:
    script = (ROOT / "live_scenario_launcher.ps1").read_text(encoding="utf-8")
    assert "SHUABAO_SOLO_CLEAN_BACKPACK" not in script
    start = script.index("function Invoke-SoloIngameChainCapture")
    end = script.index("function Invoke-SoloDirectArchaeologyCapture", start)
    case_12 = script[start:end]
    assert "New-DashboardSettingsSnapshot -RequireDashboard" in case_12
    assert '"--settings", $settingsPath' in case_12
    assert "$script:HarnessSettingsPath = $null" in case_12
    assert "Resolve-OperatorSettingsPath" in script
    assert "user_settings.json" in script


def test_backpack_buttons_use_isolated_settings_and_live_gate() -> None:
    script = (ROOT / "live_scenario_launcher.ps1").read_text(encoding="utf-8")
    capture = script.split("function Invoke-BackpackCleanCapture {", 1)[1].split("\nfunction ", 1)[0]
    for expected in (
        "Assert-ReadyForGt", "New-DashboardSettingsSnapshot", "Get-LiveRuntimeArgs",
        '"--target", "backpack_clean"', '"--backpack-entry", $Entry',
        "auto_clean_backpack", "clean_backpack_every_rounds",
    ):
        assert expected in capture
    assert "B1 局内清理背包（蹭车/局内）" in script
    assert "B2 选关页清理背包（单人）" in script
    assert "Invoke-BackpackCleanCapture -Entry ingame" in script
    assert "Invoke-BackpackCleanCapture -Entry stage" in script


def test_solo_chain_loads_saved_dashboard_snapshot_without_replacing_policy(tmp_path: Path) -> None:
    saved = Settings(
        mode_id="lobby_hitch", auto_create_room=True, cycle_num=3,
        stage_targets=["1-22"], bonds=["成长", "经济"],
        cards=["齐天大圣", "封神"], auto_devour_dan=True,
        auto_bond=True, auto_treasure=False,
    )
    path = tmp_path / "user_settings.json"
    saved.save(path)

    actual = live_capture._prepare_settings(path, "solo_ingame_chain", live_input=True)

    assert actual.mode_id == "normal_farm"
    for field in ("auto_create_room", "cycle_num", "stage_targets", "bonds", "cards", "auto_devour_dan", "auto_bond", "auto_treasure"):
        assert getattr(actual, field) == getattr(saved, field)


def test_direct_archaeology_arms_only_after_production_stage_select() -> None:
    med = SimpleNamespace(phase=Phase.ROOM_WAITING)

    assert _arm_direct_archaeology_after_stage_select(med, enabled=True) is False
    assert not hasattr(med, "_archaeology_handoff_pending")

    med.phase = Phase.STAGE_SELECT
    assert _arm_direct_archaeology_after_stage_select(med, enabled=True) is True
    assert med._archaeology_handoff_pending is True
    assert _arm_direct_archaeology_after_stage_select(med, enabled=True) is False


def test_solo_chain_preflight_accepts_production_l0_start_surface() -> None:
    frame = _blank_frame(window_title="KK官方对战平台", hwnd=1, role="l0")
    med = SimpleNamespace(_startup_state=lambda _frame: "PLATFORM_MAP")

    result = _start_surface_preflight(med, "solo_ingame_chain", frame)

    assert result["status"] == "READY"
    assert result["classifier"] == "_startup_state"


def test_hitch_lobby_chain_does_not_stop_at_first_verified_hud() -> None:
    """首次进入局内只是链路中间证据，不是多局实测的终止条件。"""
    source = (ROOT / "tools" / "live_scenario_capture.py").read_text(encoding="utf-8")
    break_handler = source.split("if loop_action is LoopAction.Break:", 1)[1].split("process_bookmarks()", 1)[0]
    assert 'target == "solo_ingame_chain"' in break_handler
    assert 'target == "hitch_lobby_chain"' not in break_handler


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
    # archive_challenge 走 production 的战后分发（_tick_main_line），由它自己
    # 点广场 NPC 打开存档面板；直接调面板内的打卡 handler 等于要求操作者先手
    # 动开好面板，那既不是被测的业务链，也让 preflight 只能死等 ARCHIVE_PANEL。
    assert calls == ["panel", "panel", "main", "inventory", "main"]
    assert med._l1_cycle_step == "evolve"
    labels = [item[1] for item in TARGETED_PROBE_MENU]
    assert labels == [
        "choice_bond_skill", "treasure", "hero_evolve", "inventory_devour",
        "inventory_hero_card", "black_merchant", "archive_challenge",
        "heirloom", "secret_realm", "lobby_search", "public_backpack_deposit",
    ]


def test_evolve_click_routes_real_two_card_panel_before_shared_skill_buttons() -> None:
    fixture = ROOT / "tests" / "fixtures" / "evolve_deadlock_20260926" / "hero_evolve_two_choice_f0030.png"
    bgr = cv2.imdecode(np.fromfile(str(fixture), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert bgr is not None
    frame = Frame(bgr, window_title="英雄三国KK", hwnd=10001, role="l1")
    med = Mediator(Settings(dry_run=True, ocr_mode="off"), ROOT)
    med.set_phase(Phase.MAIN_LINE)
    med._l1_cycle_step = "bond"
    med._panel_cooldown_until["bond"] = 200.0
    med._auto_task_done = True
    med._main_line_started_at = 100.0
    clock = FakeClock(start=100.0)
    clicks: list[tuple[str, tuple[int, int]]] = []
    evolve_btn = MatchResult("evolve_hud", 1.0, 800, 700, 40, 12, 800, 700)

    with clock.install(), \
         patch.object(med, "act_click", side_effect=lambda hit, reason, *a, **k: clicks.append((reason, hit.center)) or True), \
         patch.object(med, "_has_evolve_button", return_value=True), \
         patch.object(med, "_evolve_button_hit", return_value=evolve_btn):
        assert med._maybe_opportunistic_evolve(_blank_frame(), clock.now()) == LoopAction.Continue
        assert med._evolve_feedback_pending is True
        clock.advance(0.5)
        with patch.object(med, "_is_in_game_hud", return_value=True), \
             patch.object(med, "_post_game_state", return_value=None), \
             patch.object(med, "_ensure_auto_task_enabled", return_value=None), \
             patch.object(med, "_ensure_challenge_buttons", return_value=None), \
             patch.object(med, "_maybe_ensure_hero_panel_focus", return_value=None), \
             patch.object(med, "_maybe_click_tqtz", return_value=None), \
             patch.object(med, "_maybe_clear_pressure_monsters", return_value=None), \
             patch.object(med, "_handle_self_opened_compact_panel", return_value=None), \
             patch.object(med, "_find_equipment_affix_choice", return_value=None), \
             patch.object(med, "_hud_wood_balance", return_value=5000):
            assert med._selection_anchor(frame).name == "skill_refresh_btn"
            assert med._classify_choice_panel(frame) is None
            choice = med._find_reward_choice(frame)
            assert choice is not None
            assert choice[1].name == "evolution_card_1_rank_6"
            assert med._tick_main_line(frame) == LoopAction.Continue

    assert clicks == [
        ("ClickEvolve", (800, 700)),
        ("SelectEvolutionCard", (933, 300)),
    ]
    assert med._evolve_feedback_pending is False
    assert med._evolve_awaiting_hero_pick is False
    assert med._evolve_ok_this_cycle is True


def test_unresolved_evolve_panel_wait_fails_closed_after_bounded_wait() -> None:
    med = Mediator(Settings(dry_run=True, ocr_mode="off"), ROOT)
    med.set_phase(Phase.MAIN_LINE)
    med._evolve_awaiting_hero_pick = True
    med._evolve_awaiting_hero_pick_at = 100.0
    clock = FakeClock(start=100.0)
    incidents: list[str] = []

    with clock.install(), \
         patch.object(med, "_selection_anchor", return_value=None), \
         patch.object(med, "_find_equipment_affix_choice", return_value=None), \
         patch.object(med, "_post_game_state", return_value=None), \
         patch.object(med, "_record_fail_closed_incident", side_effect=incidents.append), \
         patch.object(med, "stop") as stop:
        clock.advance(15.1)
        result = med._tick_main_line(_blank_frame())

    assert result == LoopAction.Break
    assert med.phase == Phase.ERROR
    assert med._evolve_awaiting_hero_pick is False
    assert incidents == ["evolve hero-choice panel unresolved"]
    stop.assert_called_once()


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
        "13 PRIMARY HITCH_FULL_NATURAL_E2E",
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


def test_solo_observer_waits_for_secret_realm_terminal_surface(monkeypatch) -> None:
    observer = SoloIngameChainObserver(require_secret_realm=True)
    observer._postgame_seen = True
    for name in observer.checkpoints:
        if name != "POSTGAME_ROUTE_PROGRESS":
            observer.checkpoints[name] = {"status": "PASS", "evidence": {}}
    med = SimpleNamespace()
    state = {"phase": "MAIN_LINE", "secret_realm_active": False}
    surfaces = {
        "room": False, "platform": False, "stage": False, "stage_target": False,
        "hero": False, "hud": False, "game_hwnd": False, "boss_entry": False,
        "lobby": False, "postgame": "POST_VICTORY",
    }
    monkeypatch.setattr(live_capture, "_physical_surfaces", lambda *_args: surfaces)

    observer.observe(med, state, _blank_frame(), {}, None)
    assert observer.is_pass is False

    observer.route_observations["SECRET_REALM_ROUTE"].update({
        "request_status": "PASS",
        "confirmation_status": "PASS",
        "status": "PASS",
    })
    observer.observe(med, state, _blank_frame(), {}, None)
    assert observer.is_pass is True


def test_probe_guard_blocks_unrelated_actions() -> None:
    guard = live_capture._capture_input_guard("hero_evolve", "target_handler")
    assert guard("click", "ClickEvolve") is None
    assert guard("click", "HitchJoin") is not None
    devour = live_capture._capture_input_guard("inventory_devour", "target_handler")
    assert devour("click", "UseInventory-hero-card") is not None
    assert devour("click", "UseInventory-swallow_pill") is None
