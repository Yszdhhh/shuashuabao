"""Offline contract tests for the live-capture adapter.

These tests cover bundle shape and event-driven frame selection only.  They do
not claim a real-machine LIVE PASS; that remains the Natural E2E gate.
"""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
import shutil
import time
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np
import tools.live_scenario_capture as live_capture

from shuabao.input.keyboard_mouse import ActionResult
from shuabao.lobby_hitch import SearchTransaction
from shuabao.loop_action import LoopAction
from shuabao.mediator import BUILD_ID, Mediator, Phase
from shuabao.policy.merchant_fsm import MerchantFSM, MerchantPhase
from shuabao.settings import Settings
from shuabao.stop_signal import StopSignal
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult
from tools.live_scenario_capture import (
    BOOKMARK_STATUSES,
    BookmarkCommandReader,
    FAILURE_VARIANTS,
    FAILURE_TAXONOMY,
    BundleRecorder,
    RecordingInputExecutor,
    SUPPORTED_TARGETS,
    TARGET_CONTRACT_FIELDS,
    TARGET_CONTRACTS,
    TARGET_PRODUCTION_FACTS,
    _append_bookmark_command,
    _bootstrap_direct_boss_postgame_start,
    _bootstrap_target_probe,
    _build_identity_check,
    _capture_input_guard,
    _install_action_reason_bridge,
    _invoke_black_merchant_probe_handlers,
    generate_cases,
    main,
    readiness_report,
    replay_cases,
    reproduce_bundle,
    _resume_after_manual_intervention,
    _state_snapshot,
    _settings_snapshot,
    _timeline,
)


ROOT = Path(__file__).resolve().parents[1]


def _search_icon_anchor() -> MatchResult:
    """The stable search-control anchor as the production template matches it."""
    return MatchResult(
        name="lobby_search_icon",
        score=0.99,
        x=1256,
        y=281,
        w=26,
        h=22,
        screen_x=1256,
        screen_y=281,
    )


def _fixture_frame() -> Frame:
    path = ROOT / "fixtures" / "replay" / "main_line_auto_on.png"
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    return Frame(image, window_title="英雄三国KK", hwnd=10001, role="l1")


def test_live_probe_uses_unavailable_bosses_to_exercise_fallback() -> None:
    configured = Settings(cjb_boss="54莫阿姆", sgzx_boss="10吞噬者芬鲁斯")
    with patch.object(Settings, "load_official", return_value=configured) as load:
        settings = live_capture._prepare_settings(None, "boss_challenge", live_input=True)
    load.assert_called_once_with()
    assert settings.cjb_boss == "55吞咽者布鲁"
    assert settings.sgzx_boss == "55吞咽者布鲁"
    assert settings.auto_secret_realm is False
    assert settings.dry_run is False


def test_non_boss_target_keeps_operator_boss_choices() -> None:
    configured = Settings(cjb_boss="54莫阿姆", sgzx_boss="10吞噬者芬鲁斯")
    with patch.object(Settings, "load_official", return_value=configured):
        settings = live_capture._prepare_settings(None, "heirloom", live_input=True)
    assert settings.cjb_boss == "54莫阿姆"
    assert settings.sgzx_boss == "10吞噬者芬鲁斯"


def test_hitch_lobby_chain_enables_its_full_runtime_route() -> None:
    configured = Settings(merchant_enabled=False, auto_devour_dan=False, auto_treasure=False)
    with patch.object(Settings, "load_official", return_value=configured):
        settings = live_capture._prepare_settings(None, "hitch_lobby_chain", live_input=True)

    assert settings.merchant_enabled is True
    assert settings.auto_devour_dan is True
    assert settings.auto_treasure is True


def test_direct_heirloom_start_enters_existing_selection_handler() -> None:
    med = Mediator(Settings(cjb_boss="01暴掠龙"), ROOT)
    frame = _fixture_frame()
    with patch.object(med, "_post_game_state", return_value="HEIRLOOM_DIALOG"):
        bootstrap = _bootstrap_direct_boss_postgame_start(med, "heirloom", frame)
    assert bootstrap["post_game_route"] == "heirloom_active"
    assert med._post_game_pending is True


def test_bundle_saves_static_pixels_once_and_scrubs_password(tmp_path: Path) -> None:
    recorder = BundleRecorder(
        tmp_path / "bundle",
        repo_root=ROOT,
        target="black_merchant",
        settings={"room_password": "must-not-leak", "dry_run": True},
        initial_phase="MAIN_LINE",
        execution_mode="mediator_tick",
    )
    frame = _fixture_frame()
    first = recorder._save_frame(frame, "state_change", 0.0)
    second = recorder._save_frame(frame, "state_change", 1.0)
    recorder.finalize()

    assert first == second
    assert len(recorder.manifest["frames"]) == 1
    payload = json.loads((tmp_path / "bundle" / "manifest.json").read_text(encoding="utf-8"))
    assert payload["tested_commit_sha"]
    assert "room_password" not in json.dumps(payload, ensure_ascii=False)
    assert payload["verification"]["natural_e2e"] == "REQUIRED_LIVE_PASS"


def test_bookmark_saves_key_frame_trace_and_invalidates_natural_e2e_after_manual(tmp_path: Path) -> None:
    recorder = BundleRecorder(
        tmp_path / "bundle",
        repo_root=ROOT,
        target="black_merchant",
        settings=Settings(dry_run=True, ocr_mode="off"),
        initial_phase="MAIN_LINE",
        execution_mode="mediator_tick",
    )
    med = Mediator(Settings(dry_run=True, ocr_mode="off"), ROOT, stop_signal=StopSignal())
    med.set_phase(Phase.MAIN_LINE, "bookmark unit test")
    frame = _fixture_frame()

    pass_mark = recorder.bookmark("PASS", med, frame, note="target verified")
    fail_mark = recorder.bookmark("FAIL", med, frame, note="production failure")
    manual_mark = recorder.bookmark("MANUAL_INTERVENTION", med, frame, note="user bypassed")
    recorder.finalize()

    assert set(BOOKMARK_STATUSES) == {"PASS", "FAIL", "MANUAL_INTERVENTION"}
    assert pass_mark["counts_as_natural_e2e_pass"] is False
    assert pass_mark["authoritative_live_probe_pass"] is False
    assert fail_mark["frame"] == pass_mark["frame"]
    assert manual_mark["ground_truth_eligible"] is True
    assert manual_mark["counts_as_natural_e2e_pass"] is False
    assert not med.stop_signal.is_set()

    payload = json.loads((tmp_path / "bundle" / "manifest.json").read_text(encoding="utf-8"))
    assert payload["bookmark_summary"] == {"PASS": 1, "FAIL": 1, "MANUAL_INTERVENTION": 1}
    assert payload["verification"]["natural_e2e"] == "DISQUALIFIED_MANUAL_INTERVENTION"
    assert payload["verification"]["natural_e2e_eligible"] is False
    assert payload["verification"]["manual_intervention_seen"] is True
    assert payload["bookmarks"][2]["file"] == "bookmarks/b0002.json"
    manual_sidecar = tmp_path / "bundle" / payload["bookmarks"][2]["file"]
    manual_payload = json.loads(manual_sidecar.read_text(encoding="utf-8"))
    assert manual_payload["bundle_id"] == "bundle"
    assert "recent_trace" in manual_payload
    fail_sidecar = tmp_path / "bundle" / payload["bookmarks"][1]["file"]
    fail_payload = json.loads(fail_sidecar.read_text(encoding="utf-8"))
    assert fail_payload["failure_summary_file"] == "failures/b0001_fail.json"
    failure = json.loads((tmp_path / "bundle" / fail_payload["failure_summary_file"]).read_text(encoding="utf-8"))
    assert failure["target"] == "black_merchant"
    assert failure["bookmark_id"] == "b0001"
    assert failure["replay_command"].endswith('reproduce --bundle "' + str((tmp_path / "bundle").resolve()) + '"')
    assert set(item["layer"] for item in failure["failure_class_hints"]) <= set(FAILURE_TAXONOMY) | {"UNKNOWN"}
    assert (tmp_path / "bundle" / "failures" / "b0001_fail.md").exists()


def test_bookmark_commands_are_non_blocking_and_manual_resume_clears_only_test_stop(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    recorder = BundleRecorder(
        bundle,
        repo_root=ROOT,
        target="inventory_item",
        settings={},
        initial_phase="MAIN_LINE",
        execution_mode="mediator_tick",
    )
    recorder.finalize()
    command_file = _append_bookmark_command(bundle, "FAIL", "first failure")
    command_file.write_text(
        command_file.read_text(encoding="utf-8") + "MANUAL_INTERVENTION|continue ground truth\n",
        encoding="utf-8",
    )
    reader = BookmarkCommandReader(command_file)
    assert reader.poll() == [
        ("FAIL", "first failure"),
        ("MANUAL_INTERVENTION", "continue ground truth"),
    ]
    assert reader.poll() == []
    command_file.write_text(
        command_file.read_text(encoding="utf-8") + "PASS\nUNKNOWN\n",
        encoding="utf-8",
    )
    assert reader.poll() == [("PASS", "")]

    med = Mediator(Settings(), ROOT, stop_signal=StopSignal())
    med.set_phase(Phase.ERROR, "capture failure")
    med.stop_signal.trigger("Mediator.stop()")
    med._running = False
    _resume_after_manual_intervention(med)
    assert med.phase is Phase.MAIN_LINE
    assert med._running is True
    assert not med.stop_signal.is_set()


def test_timeline_reuses_before_frame_for_postcondition_variants(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    (bundle / "frames").mkdir(parents=True)
    source = ROOT / "fixtures" / "replay" / "main_line_auto_on.png"
    shutil.copy2(source, bundle / "frames" / "before.png")
    shutil.copy2(source, bundle / "frames" / "after.png")
    manifest = {
        "capture_schema_version": 1,
        "bundle_id": "sample",
        "target": "black_merchant",
        "initial_phase": "MAIN_LINE",
        "settings": {"dry_run": False},
        "frames": [
            {"id": "before", "file": "frames/before.png", "capture_role": "l1", "hwnd": 10001},
            {"id": "after", "file": "frames/after.png", "capture_role": "l1", "hwnd": 10001},
        ],
        "events": [{
            "event_id": "e0000",
            "at_s": 0.0,
            "frame_before": "before",
            "frame_after": "after",
            "action": {"kind": "click", "reason": "BlackMerchant-refresh"},
            "input": {"method": "click"},
        }],
    }
    (bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    normal = _timeline(bundle, manifest, ROOT, None)
    unchanged = _timeline(bundle, manifest, ROOT, "frame_unchanged")
    missing = _timeline(bundle, manifest, ROOT, "postcondition_missing")
    timeout = _timeline(bundle, manifest, ROOT, "timeout")

    assert len(normal) == len(unchanged) == len(missing) == 2
    assert len(timeout) == 3
    assert timeout[-1].id == "timeout_after_deadline"
    assert timeout[-1].at_s > timeout[-2].at_s
    assert normal[1].file != unchanged[1].file
    assert unchanged[1].file == missing[1].file
    assert set(FAILURE_VARIANTS) == {
        "click_rejected", "postcondition_missing", "frame_unchanged", "timeout"
    }


def test_capture_manifest_declares_supported_target_scope(tmp_path: Path) -> None:
    recorder = BundleRecorder(
        tmp_path / "bundle",
        repo_root=ROOT,
        target="heirloom",
        settings={},
        initial_phase="MAIN_LINE",
        execution_mode="target_handler",
    )
    recorder.finalize()
    payload = json.loads((tmp_path / "bundle" / "manifest.json").read_text(encoding="utf-8"))
    assert payload["target"] == "heirloom"
    # 传家宝整条链（广场→点 NPC→弹窗→选 Boss）都在 production 的战后分发里。
    assert payload["production_handler"] == "_tick_main_line"
    assert payload["execution_mode"] == "target_handler"
    assert payload["production_readiness"] == "CONDITIONAL"
    assert payload["ground_truth_only"] is False
    assert payload["verification"]["natural_e2e"] == "TARGET_PROBE_ONLY"
    assert set(payload["target_contract"]) == set(TARGET_CONTRACT_FIELDS)
    assert _settings_snapshot({"room_password": "secret", "x": 1}) == {"x": 1}


def test_action_postcondition_is_backfilled_by_a_later_state_tick(tmp_path: Path) -> None:
    recorder = BundleRecorder(
        tmp_path / "bundle",
        repo_root=ROOT,
        target="inventory_item",
        settings=Settings(dry_run=True, ocr_mode="off"),
        initial_phase="MAIN_LINE",
        execution_mode="mediator_tick",
    )
    med = Mediator(Settings(dry_run=True, ocr_mode="off"), ROOT, stop_signal=StopSignal())
    med.set_phase(Phase.MAIN_LINE, "capture unit test")
    med._pending_action = SimpleNamespace(kind="WAIT_DEVOUR_DAN", target_id="danGif", deadline=1.0)
    med._trace_actions = [{"intent": "click:test_target", "reason": "UseInventory-swallow_pill", "ok": True}]
    frame = _fixture_frame()

    recorder.begin_tick()
    recorder.record_input("click", (10, 20), {}, ActionResult(True, "SUCCESS", "ok"))
    first = recorder.record_tick(
        med,
        phase_before=Phase.MAIN_LINE.name,
        before_state=_state_snapshot(med),
        before_frame=frame,
        after_frame=frame,
        loop_action=LoopAction.Continue,
        at_s=0.0,
    )
    assert first is not None
    assert first["postcondition"]["observed"] is False
    assert first["input_result"] == {"success": True, "status": "SUCCESS", "message": "ok"}

    med._pending_action = None
    med._trace_actions = []
    recorder.begin_tick()
    recorder.record_tick(
        med,
        phase_before=Phase.MAIN_LINE.name,
        before_state=_state_snapshot(med),
        before_frame=frame,
        after_frame=None,
        loop_action=LoopAction.Continue,
        at_s=0.2,
    )

    assert recorder.manifest["events"][0]["postcondition"]["observed"] is True
    assert recorder.manifest["events"][0]["postcondition"]["confirmed_by_event"] == "e0001"
    assert recorder.manifest["target_result"]["observed"] is True
    assert recorder.manifest["target_result"]["authoritative"] is True


def test_generate_cases_uses_existing_schema_and_creates_all_failure_branches(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    (bundle / "frames").mkdir(parents=True)
    source = ROOT / "fixtures" / "scenarios" / "stage_starting_env_hud" / "frames" / "env_hud_visible.png"
    shutil.copy2(source, bundle / "frames" / "env.png")
    manifest = {
        "capture_schema_version": 1,
        "bundle_id": "sample_capture",
        "target": "inventory_item",
        "initial_phase": "STAGE_STARTING",
        "settings": {"dry_run": True, "ocr_mode": "off"},
        "tested_commit_sha": "test-sha",
        "frames": [{
            "id": "env",
            "file": "frames/env.png",
            "capture_role": "l1",
            "window_title": "英雄三国KK",
            "hwnd": 10001,
            "left": 0,
            "top": 0,
        }],
        "events": [
            {"event_id": "e0", "at_s": 0.0, "frame_before": "env"},
            {"event_id": "e1", "at_s": 1.0, "frame_before": "env"},
        ],
        "generated_cases": [],
        "verification": {"frozen_replay": "PENDING", "natural_e2e": "REQUIRED_LIVE_PASS"},
    }
    (bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    paths = generate_cases(bundle, repo_root=ROOT, variants=FAILURE_VARIANTS)

    assert len(paths) == 1 + len(FAILURE_VARIANTS)
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["schema_version"] == 1
        assert payload["case"] == path.parent.name
        assert len(payload["frames"]) == len(payload["expect_actions"])
        assert payload["settings_overrides"]["dry_run"] is True
        assert payload["settings_overrides"]["ocr_mode"] == "off"
    timeout = next(path for path in paths if "__timeout" in path.parent.name)
    timeout_payload = json.loads(timeout.read_text(encoding="utf-8"))
    assert timeout_payload["frames"][-1]["id"] == "timeout_after_deadline"
    assert replay_cases([path.parent for path in paths], ROOT) == 0
    replayed_manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    assert replayed_manifest["verification"]["frozen_replay"] == "PASS"
    assert len({row["case"] for row in replayed_manifest["generated_cases"]}) == len(paths)

    # Regeneration is safe after a code change: it replaces these case records
    # instead of appending duplicates to the capture manifest.
    generate_cases(bundle, repo_root=ROOT, variants=FAILURE_VARIANTS)
    regenerated_manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    assert len({row["case"] for row in regenerated_manifest["generated_cases"]}) == len(paths)
    assert reproduce_bundle(bundle, repo_root=ROOT) == 0
    assert main(["reproduce", "--bundle", str(bundle), "--repo-root", str(ROOT)]) == 0


def test_generated_click_rejected_branch_reuses_real_mediator_action_path(tmp_path: Path) -> None:
    bundle = tmp_path / "action_bundle"
    (bundle / "frames").mkdir(parents=True)
    source = ROOT / "tests" / "performance" / "fixtures" / "stage_select.png"
    shutil.copy2(source, bundle / "frames" / "stage.png")
    manifest = {
        "capture_schema_version": 1,
        "bundle_id": "action_capture",
        "target": "black_merchant",
        "initial_phase": "STAGE_SELECT",
        "settings": {"dry_run": True, "ocr_mode": "off"},
        "tested_commit_sha": "test-sha",
        "frames": [{
            "id": "stage",
            "file": "frames/stage.png",
            "capture_role": "l0",
            "window_title": "英雄三国KK",
            "hwnd": 10001,
            "left": 0,
            "top": 0,
        }],
        "events": [
            {"event_id": "e0", "at_s": 0.0, "frame_before": "stage", "frame_after": "stage",
             "action": {"kind": "scroll", "reason": "stage scroll"}, "input": {"method": "scroll"}},
            {"event_id": "e1", "at_s": 2.0, "frame_before": "stage", "frame_after": "stage",
             "action": {"kind": "scroll", "reason": "stage scroll"}, "input": {"method": "scroll"}},
        ],
        "generated_cases": [],
        "verification": {"frozen_replay": "PENDING", "natural_e2e": "REQUIRED_LIVE_PASS"},
    }
    (bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    paths = generate_cases(bundle, repo_root=ROOT, variants=("click_rejected",))
    rejected = json.loads(paths[1].read_text(encoding="utf-8"))
    assert rejected["expect_actions"][0]["action_result"]["success"] is False
    assert rejected["expect_actions"][0]["input_injection"] == "SENDINPUT_FAILED"
    assert replay_cases([path.parent for path in paths], ROOT) == 0


def test_all_target_contracts_have_a_structural_readiness_result() -> None:
    assert SUPPORTED_TARGETS == (
        "black_merchant",
        "inventory_item",
        "boss_challenge",
        "time_cave",
        "heirloom",
        "secret_realm",
        "lobby_hitch",
        "lobby_search",
        "s01_lobby_surface_identity",
        "s02_lobby_platform_modal",
        "s03_lobby_room_ready",
        "s04_lobby_single_hwnd_room",
        "s05_lobby_search_join_ready",
        "s06_lobby_recovery_chain",
        "public_backpack_deposit",
        "hitch_runtime",
        "solo_ingame_chain",
        "hitch_lobby_chain",
        "choice_bond_skill",
        "treasure",
        "hero_evolve",
        "inventory_devour",
        "inventory_hero_card",
        "archive_challenge",
    )
    for contract in TARGET_CONTRACTS.values():
        assert all(contract.get(field) for field in TARGET_CONTRACT_FIELDS)
    assert contract["max_probe_time_s"] > 0

    report = readiness_report(repo_root=ROOT, run_replay_self_check=True)
    assert [item["target"] for item in report["targets"]] == list(SUPPORTED_TARGETS)
    assert "status" not in report["targets"][0]
    assert all(item["harness_readiness"] == "READY" for item in report["targets"])
    by_target = {item["target"]: item for item in report["targets"]}
    assert by_target["inventory_item"]["production_readiness"] == "CONDITIONAL"
    assert by_target["black_merchant"]["production_readiness"] == "CONDITIONAL"
    assert by_target["boss_challenge"]["production_readiness"] == "CONDITIONAL"
    assert by_target["time_cave"]["production_readiness"] == "CONDITIONAL"
    assert by_target["heirloom"]["production_readiness"] == "CONDITIONAL"
    assert by_target["secret_realm"]["production_readiness"] == "CONDITIONAL"
    assert by_target["lobby_hitch"]["production_readiness"] == "CONDITIONAL"
    assert by_target["lobby_search"]["production_readiness"] == "CONDITIONAL"
    assert by_target["hitch_runtime"]["production_readiness"] == "CONDITIONAL"
    assert by_target["solo_ingame_chain"]["production_readiness"] == "CONDITIONAL"
    assert by_target["hitch_lobby_chain"]["production_readiness"] == "CONDITIONAL"
    assert by_target["choice_bond_skill"]["production_readiness"] == "CONDITIONAL"
    assert by_target["treasure"]["production_readiness"] == "CONDITIONAL"
    assert by_target["hero_evolve"]["production_readiness"] == "CONDITIONAL"
    assert by_target["inventory_devour"]["production_readiness"] == "CONDITIONAL"
    assert by_target["inventory_hero_card"]["production_readiness"] == "CONDITIONAL"
    assert by_target["archive_challenge"]["production_readiness"] == "CONDITIONAL"
    assert TARGET_CONTRACTS["lobby_search"]["max_probe_time_s"] == 90.0
    assert by_target["time_cave"]["ground_truth_only"] is False
    assert by_target["heirloom"]["ground_truth_only"] is False
    assert by_target["lobby_hitch"]["ground_truth_only"] is False
    assert by_target["lobby_search"]["ground_truth_only"] is False
    assert by_target["hitch_runtime"]["ground_truth_only"] is False
    assert any(
        route["route"] == "black_merchant_wood" and route["readiness"] == "CONDITIONAL"
        for route in by_target["black_merchant"]["production_routes"]
    )
    assert any(
        route["route"] == "tqtz_to_sgzx" and route["readiness"] == "CONDITIONAL"
        for route in by_target["boss_challenge"]["production_routes"]
    )
    assert all(item["capture"] == "READY" for item in report["targets"])
    assert all(item["bookmark"] == "READY" for item in report["targets"])
    assert all(item["failure_summary"] == "READY" for item in report["targets"])
    assert all(item["replay_conversion"] == "READY" for item in report["targets"])
    assert report["replay_self_check"]["status"] == "PASS"
    assert report["live_input_preflight"]["status"] == "REQUIRED"
    assert set(TARGET_PRODUCTION_FACTS) == set(SUPPORTED_TARGETS)


def test_blocked_summary_and_secret_realm_probe_bootstrap_are_evidence_only(tmp_path: Path) -> None:
    recorder = BundleRecorder(
        tmp_path / "bundle",
        repo_root=ROOT,
        target="secret_realm",
        settings=Settings(dry_run=True, ocr_mode="off"),
        initial_phase="MAIN_LINE",
        execution_mode="target_handler",
    )
    med = Mediator(Settings(dry_run=True, ocr_mode="off"), ROOT, stop_signal=StopSignal())
    bootstrap = _bootstrap_target_probe(med, "secret_realm")
    assert bootstrap["post_game_pending"] is True
    assert med._secret_realm_request_pending is False
    assert med._post_game_route == "secret"

    blocked = recorder.record_blocked(med, None, note="synthetic capture unavailable")
    assert blocked is not None
    recorder.finalize()
    payload = json.loads((tmp_path / "bundle" / "manifest.json").read_text(encoding="utf-8"))
    assert payload["verification"]["natural_e2e"] == "BLOCKED"
    assert payload["automatic_failures"][0]["status"] == "BLOCKED"
    summary = json.loads((tmp_path / "bundle" / "failures" / "b0000_blocked.json").read_text(encoding="utf-8"))
    assert summary["failure_class_hints"][0]["layer"] == "L0_CAPTURE_ENV"


def test_black_merchant_probe_bootstrap_records_established_game_time() -> None:
    med = Mediator(Settings(dry_run=True, ocr_mode="off"), ROOT, stop_signal=StopSignal())
    bootstrap = _bootstrap_target_probe(med, "black_merchant")

    assert bootstrap["main_line_started_at"] == "probe_start_minus_30s"
    assert med._main_line_started_at is not None
    assert med._evolve_ok_this_cycle is True


def test_inventory_probe_bootstrap_allows_existing_hero_card_route() -> None:
    med = Mediator(Settings(dry_run=True, ocr_mode="off"), ROOT, stop_signal=StopSignal())
    bootstrap = _bootstrap_target_probe(med, "inventory_item")

    assert bootstrap["evolve_ok_this_cycle"] is True
    assert med._evolve_ok_this_cycle is True
    assert _capture_input_guard("inventory_item", "target_handler")("click", "UseInventory-hero-card") is None


def test_inventory_hero_card_requires_existing_postcondition_for_probe_pass() -> None:
    confirmed = live_capture._target_postcondition_snapshot(
        "inventory_item",
        None,
        None,
        {},
        {"reason": "UseInventory-hero-card"},
        {"observed": True},
    )
    missing = live_capture._target_postcondition_snapshot(
        "inventory_item",
        None,
        None,
        {},
        {"reason": "UseInventory-hero-card"},
        {"observed": False},
    )

    assert confirmed == {"observed": True, "state": "confirmed", "kind": "inventory_hero_card"}
    assert missing["observed"] is False


def test_boss_scroll_is_not_authoritative_destination_pass() -> None:
    base = {"observed": False, "state": "not_observed", "kind": "BossConfigured-scroll"}
    result = live_capture._target_postcondition_snapshot(
        "boss_challenge",
        None,
        _fixture_frame(),
        {},
        {"reason": "BossConfigured-scroll"},
        base,
    )

    assert result == base


def test_failure_summary_uses_recorded_rejection_and_missing_postcondition_evidence(tmp_path: Path) -> None:
    frame = _fixture_frame()
    for label, result, required_layer in (
        ("rejected", ActionResult(False, "CANCELLED_SENDINPUT_FAILED", "fake rejection"), "L4_INPUT_EXECUTION"),
        ("unchanged", ActionResult(True, "SUCCESS", "fake send"), "L5_POSTCONDITION"),
    ):
        recorder = BundleRecorder(
            tmp_path / label,
            repo_root=ROOT,
            target="inventory_item",
            settings=Settings(dry_run=True, ocr_mode="off"),
            initial_phase="MAIN_LINE",
            execution_mode="mediator_tick",
        )
        med = Mediator(Settings(dry_run=True, ocr_mode="off"), ROOT, stop_signal=StopSignal())
        med.set_phase(Phase.MAIN_LINE, "synthetic failure summary")
        med._pending_action = SimpleNamespace(kind="WAIT_TEST", target_id="test", deadline=999.0)
        med._trace_actions = [{"intent": "click:test", "reason": "UseInventory-test", "ok": result.success}]
        recorder.begin_tick()
        recorder.record_input("click", (10, 20), {}, result)
        recorder.record_tick(
            med,
            phase_before="MAIN_LINE",
            before_state=_state_snapshot(med),
            before_frame=frame,
            after_frame=frame,
            loop_action=LoopAction.Continue,
            at_s=0.0,
        )
        failure = recorder.bookmark("FAIL", med, frame, note=f"synthetic {label}")
        payload = json.loads((tmp_path / label / failure["failure_summary_file"]).read_text(encoding="utf-8"))
        assert required_layer in {item["layer"] for item in payload["failure_class_hints"]}
        assert payload["input_sent"] is True
        assert payload["actual_postcondition"]["observed"] is False


def test_human_pass_bookmark_cannot_authorize_a_probe_pass(tmp_path: Path) -> None:
    recorder = BundleRecorder(
        tmp_path / "bundle",
        repo_root=ROOT,
        target="black_merchant",
        settings=Settings(dry_run=True, ocr_mode="off"),
        initial_phase="MAIN_LINE",
        execution_mode="target_handler",
    )
    med = Mediator(Settings(dry_run=True, ocr_mode="off"), ROOT, stop_signal=StopSignal())
    bookmark = recorder.bookmark("PASS", med, _fixture_frame(), note="human evidence only")

    assert bookmark["authoritative_live_probe_pass"] is False
    assert recorder.manifest["target_result"]["observed"] is False
    assert recorder.manifest["verification"]["live_probe"] == "PENDING"


def test_black_merchant_refresh_transition_is_not_an_authoritative_target_pass(tmp_path: Path) -> None:
    recorder = BundleRecorder(
        tmp_path / "bundle",
        repo_root=ROOT,
        target="black_merchant",
        settings=Settings(dry_run=True, ocr_mode="off"),
        initial_phase="MAIN_LINE",
        execution_mode="target_handler",
    )
    med = Mediator(Settings(dry_run=True, ocr_mode="off"), ROOT, stop_signal=StopSignal())
    med.set_phase(Phase.MAIN_LINE, "merchant refresh test")
    med._merchant_fsm = MerchantFSM(
        phase=MerchantPhase.VERIFYING,
        fingerprint="before",
        pending_fingerprint="before",
        deadline=99.0,
    )
    med._trace_actions = [{"intent": "click:refresh", "reason": "BlackMerchant-refresh", "ok": True}]
    frame = _fixture_frame()

    recorder.begin_tick()
    recorder.record_input("click", (10, 20), {}, ActionResult(True, "SUCCESS", "refresh"))
    recorder.record_tick(
        med,
        phase_before="MAIN_LINE",
        before_state=_state_snapshot(med),
        before_frame=frame,
        after_frame=frame,
        loop_action=LoopAction.Continue,
        at_s=0.0,
    )
    med._merchant_fsm = MerchantFSM(phase=MerchantPhase.CONFIRMING, fingerprint="after")
    med._trace_actions = []
    recorder.begin_tick()
    recorder.record_tick(
        med,
        phase_before="MAIN_LINE",
        before_state=_state_snapshot(med),
        before_frame=frame,
        after_frame=None,
        loop_action=LoopAction.Continue,
        at_s=0.2,
    )

    first = recorder.manifest["events"][0]["postcondition"]
    assert first["observed"] is False
    assert first["state"] == "transition_not_target_pass"
    assert recorder.manifest["target_result"]["observed"] is False
    assert recorder.manifest["verification"]["live_probe"] == "PENDING"


def test_build_identity_requires_exact_source_build_and_exe_hash(tmp_path: Path) -> None:
    exe = tmp_path / "ShuaBao.exe"
    exe.write_bytes(b"test packaged executable")
    actual_hash = hashlib.sha256(exe.read_bytes()).hexdigest()
    identity = {
        "schema_version": 1,
        "source_sha": "source-commit",
        "source_tree_clean": True,
        "build_id": BUILD_ID,
        "exe_sha256": actual_hash,
    }
    (tmp_path / "build_identity.json").write_text(json.dumps(identity), encoding="utf-8")

    ready = _build_identity_check(
        repo_root=tmp_path,
        automation_exe=exe,
        source_sha="source-commit",
        source_clean=True,
    )
    assert ready["status"] == "READY"
    assert ready["actual_exe_sha256"] == actual_hash

    identity["source_sha"] = "other-commit"
    (tmp_path / "build_identity.json").write_text(json.dumps(identity), encoding="utf-8")
    blocked = _build_identity_check(
        repo_root=tmp_path,
        automation_exe=exe,
        source_sha="source-commit",
        source_clean=True,
    )
    assert blocked["status"] == "BLOCKED"
    assert any("source/EXE identity mismatch" in reason for reason in blocked["blocked_reasons"])


def test_blocked_precheck_is_evidence_only_and_never_gets_business_taxonomy(tmp_path: Path) -> None:
    recorder = BundleRecorder(
        tmp_path / "bundle",
        repo_root=ROOT,
        target="secret_realm",
        settings=Settings(dry_run=True, ocr_mode="off"),
        initial_phase="MAIN_LINE",
        execution_mode="target_handler",
    )
    recorder.record_preflight({
        "status": "BLOCKED_PRECHECK",
        "tested_source_sha": "test-source",
        "actual_exe": {"status": "BLOCKED"},
        "settings_snapshot": {"dry_run": False},
        "ocr_bootstrap_health": {"healthy": False},
        "window": {"hwnd": 10001, "title": "英雄三国KK", "size": [1600, 900]},
        "single_instance": {"status": "NOT_ACQUIRED"},
        "blocked_reasons": ["source/EXE identity mismatch", "ocr_bootstrap_unhealthy"],
    })
    med = Mediator(Settings(dry_run=True, ocr_mode="off"), ROOT, stop_signal=StopSignal())
    blocked = recorder.record_blocked(
        med,
        _fixture_frame(),
        status="BLOCKED_PRECHECK",
        note="live input refused before target handler",
    )
    assert blocked is not None
    summary = json.loads((tmp_path / "bundle" / blocked["failure_summary_file"]).read_text(encoding="utf-8"))
    assert summary["status"] == "BLOCKED_PRECHECK"
    assert summary["input_sent"] is False
    assert summary["preflight"]["window"]["hwnd"] == 10001
    assert summary["failure_class_hints"] == [{
        "layer": "L8_TEST_EVIDENCE",
        "evidence": "live-input preflight blocked before any business handler: source/EXE identity mismatch; ocr_bootstrap_unhealthy",
    }]


def test_search_action_reason_bridge_keeps_reason_separate_from_text() -> None:
    seen: list[str] = []
    holder: dict[str, object] = {}
    med = SimpleNamespace()

    def act_search_box(*args: object, **kwargs: object) -> bool:
        seen.append(str(holder["provider"]()))
        return True

    med.act_search_box = act_search_box
    holder["provider"] = _install_action_reason_bridge(med)
    med.act_search_box(object(), "4", "HitchSearchBox")

    assert seen == ["HitchSearchBox"]


def test_black_merchant_integrated_routes_and_secret_probe_are_guarded() -> None:
    calls: list[tuple[object, ...]] = []
    results: list[ActionResult] = []
    guards: list[tuple[str, str, str]] = []

    class Delegate:
        stop_signal = StopSignal()

        def click(self, *args, **kwargs):
            calls.append(args)
            return ActionResult(True, "SUCCESS", "delegate should not run")

    integrated = RecordingInputExecutor(
        Delegate(),
        lambda _method, _args, _kwargs, result: results.append(result),
        reason_provider=lambda: "BlackMerchant-wood",
        input_guard=_capture_input_guard("black_merchant", "target_handler"),
        on_guard=lambda method, reason, denial: guards.append((method, reason, denial)),
    )
    result = integrated.click(10, 20, dry_run=False)

    assert result.success is True
    assert result.status == "SUCCESS"
    assert calls == [(10, 20)]
    assert results[0].status == "SUCCESS"
    assert guards == []
    assert _capture_input_guard("black_merchant", "target_handler")("click", "BlackMerchant-discount") is None
    assert _capture_input_guard("black_merchant", "target_handler")("click", "Artifact-Q") is None
    assert _capture_input_guard("boss_challenge", "target_handler")("scroll", "BossConfigured-scroll") is None
    assert _capture_input_guard("secret_realm", "target_handler")("click", "CloseArchivePanel")
    assert _capture_input_guard("time_cave", "target_handler")("click", "BossConfigured") is None


def test_black_merchant_probe_composes_existing_handlers_one_input_per_tick() -> None:
    calls: list[str] = []

    class ProbeMediator:
        def _maybe_black_merchant(self, _frame):
            calls.append("merchant")
            return LoopAction.Continue

        def _maybe_use_inventory_item(self, _frame):
            calls.append("inventory")
            return None

        def _maybe_fire_artifacts(self, _frame):
            calls.append("artifact")
            return LoopAction.Continue

    sent = {"value": False}
    result = _invoke_black_merchant_probe_handlers(
        ProbeMediator(),
        _fixture_frame(),
        input_sent=lambda: sent["value"],
    )
    assert result is LoopAction.Continue
    assert calls == ["merchant", "inventory", "artifact"]

    calls.clear()

    class MerchantInputMediator(ProbeMediator):
        def _maybe_black_merchant(self, _frame):
            calls.append("merchant")
            sent["value"] = True
            return LoopAction.Continue

    sent["value"] = False
    _invoke_black_merchant_probe_handlers(
        MerchantInputMediator(),
        _fixture_frame(),
        input_sent=lambda: sent["value"],
    )
    assert calls == ["merchant"]


def test_harness_capture_kwargs_match_production_signature(monkeypatch) -> None:
    import inspect

    allowed = set(inspect.signature(live_capture.capture).parameters)
    calls: list[dict] = []

    def fake_capture(*_args, **kwargs):
        calls.append(kwargs)
        extra = set(kwargs) - allowed
        assert not extra, extra
        return Frame(bgr=np.zeros((8, 8, 3), dtype=np.uint8), is_valid=False, error="synthetic")

    monkeypatch.setattr(live_capture, "capture", fake_capture)
    live_capture._window_preflight(Settings(), target="hitch_lobby_chain")
    live_capture._capture_after(SimpleNamespace(
        phase=Phase.LOBBY_ROOM,
        _capture_title=lambda: "",
        _last_frame=None,
    ))
    assert calls


def test_minimized_lobby_window_is_explicitly_blocked(monkeypatch) -> None:
    frame = Frame(
        bgr=np.zeros((8, 8, 3), dtype=np.uint8),
        hwnd=101,
        window_title="KK官方对战平台",
        is_valid=False,
        error="Window is minimized",
        role="l0",
    )
    monkeypatch.setattr(live_capture, "capture", lambda *_args, **_kwargs: frame)

    _frame, record = live_capture._window_preflight(Settings(), target="hitch_lobby_chain")

    assert record["status"] == "BLOCKED"
    assert "restore it" in str(record["reason"])


def test_blocked_precondition_bundle_returns_nonzero_exit_code(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps({"live_preflight": {"status": "BLOCKED_PRECONDITION"}}),
        encoding="utf-8",
    )

    assert live_capture._bundle_exit_code(tmp_path) == 3
    persisted = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert persisted["process_exit_code"] == 3


def test_blocked_preflight_does_not_dispatch_any_business_handler(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []
    frame = _fixture_frame()

    def fake_live_mediator(settings, repo_root, stop_signal, incident_dir):
        return Mediator(settings, repo_root, stop_signal=stop_signal, incident_dir=incident_dir), "synthetic runtime blocked"

    def fake_preflight(**_kwargs):
        return ({
            "status": "BLOCKED_PRECHECK",
            "tested_source_sha": "test-source",
            "actual_exe": {"status": "BLOCKED"},
            "settings_snapshot": {"dry_run": False},
            "ocr_bootstrap_health": {"healthy": False},
            "window": {"hwnd": frame.hwnd, "title": frame.window_title, "size": [frame.width, frame.height]},
            "single_instance": {"status": "NOT_ACQUIRED"},
            "blocked_reasons": ["source/EXE identity mismatch"],
        }, None, frame)

    monkeypatch.setattr(live_capture, "_new_live_mediator", fake_live_mediator)
    monkeypatch.setattr(live_capture, "_live_input_preflight", fake_preflight)
    monkeypatch.setattr(live_capture, "_invoke_target_handler", lambda *_args: calls.append("handler"))
    args = SimpleNamespace(
        target="secret_realm",
        repo_root=ROOT,
        settings=None,
        out=tmp_path,
        live_input=True,
        confirm_live_input=True,
        bookmark_file=None,
        duration=1.0,
        interval=0.0,
        max_ticks=1,
        continue_after_failure=False,
        generate=False,
        automation_exe=None,
        build_identity=None,
    )

    bundle = live_capture._run_live_capture(args, probe=True)
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    assert calls == []
    assert manifest["live_preflight"]["status"] == "BLOCKED_PRECHECK"
    assert manifest["automatic_failures"][0]["status"] == "BLOCKED_PRECHECK"
    assert manifest["events"]


def test_live_preflight_uses_window_recovered_during_start_surface_wait(tmp_path: Path) -> None:
    class FakeLane:
        path = tmp_path / "live.lock"
        owner = {"pid": 1}

        def __init__(self, _name: str) -> None:
            pass

        def acquire(self) -> None:
            pass

    args = SimpleNamespace(
        live_input=True,
        allow_dev_source=True,
        automation_exe=None,
        build_identity=None,
        production_source_root=ROOT,
        production_source_sha="candidate",
        target="hitch_lobby_chain",
        start_surface_wait=1.0,
    )
    initial_window = {"status": "BLOCKED", "reason": "target window is minimized"}
    recovered_window = {"status": "READY", "title": "KK官方对战平台"}
    recovered_frame = Frame(np.zeros((100, 100, 3), dtype=np.uint8), role="l0")
    identity = {
        "ready_for_gt": True,
        "blocked_reasons": [],
        "production_source_sha": "candidate",
        "production_source_clean": True,
        "candidate_source_injection": "ACTIVE",
    }
    with patch.object(live_capture, "_scenario_identity", return_value=identity), \
         patch.object(live_capture, "_build_identity_check", return_value={"status": "READY", "blocked_reasons": []}), \
         patch.object(live_capture, "is_current_process_elevated", return_value=True), \
         patch.object(live_capture, "_ocr_bootstrap_preflight", return_value={"healthy": True}), \
         patch.object(live_capture, "_lobby_resource_preflight", return_value=[]), \
         patch.object(live_capture, "_window_preflight", return_value=(None, initial_window)), \
         patch.object(live_capture, "_await_start_surface", return_value=({"status": "READY"}, recovered_frame, recovered_window)), \
         patch.object(live_capture, "LiveLane", FakeLane):
        report, lane, frame = live_capture._live_input_preflight(
            args=args,
            med=SimpleNamespace(),
            settings=Settings(dry_run=False),
            repo_root=ROOT,
            runtime_mediator_error=None,
        )

    assert report["status"] == "READY"
    assert not any("game window unavailable" in reason for reason in report["blocked_reasons"])
    assert lane is not None
    assert frame is recovered_frame


def test_lobby_hitch_settings_and_bootstrap() -> None:
    settings = live_capture._prepare_settings(None, "lobby_hitch", live_input=False)
    assert settings.mode_id == "lobby_hitch"
    assert settings.auto_create_room is False
    assert settings.skip_password_rooms is True
    assert settings.never_quick_join is True

    med = Mediator(settings, ROOT)
    bootstrap = _bootstrap_target_probe(med, "lobby_hitch")
    assert med.phase is Phase.LOBBY_ROOM
    assert med._hitch_re_search is False
    assert bootstrap["mode_id"] == "lobby_hitch"
    assert bootstrap["phase"] == "LOBBY_ROOM"

    search_settings = live_capture._prepare_settings(None, "lobby_search", live_input=False)
    search_med = Mediator(search_settings, ROOT)
    search_bootstrap = _bootstrap_target_probe(search_med, "lobby_search")
    assert search_settings.mode_id == "lobby_hitch"
    assert search_bootstrap["phase"] == "LOBBY_ROOM"
    assert search_bootstrap["continuous_until_ready"] is True
    assert search_med._hitch_sm.continuous is True

    with patch.object(Settings, "load_official", return_value=Settings(auto_secret_realm=True)):
        runtime_settings = live_capture._prepare_settings(None, "hitch_runtime", live_input=False)
    assert runtime_settings.mode_id == "lobby_hitch"
    assert runtime_settings.cycle_num == runtime_settings.hitch_cycle_num
    assert runtime_settings.auto_create_room is False
    assert runtime_settings.auto_secret_realm is False

    with patch.object(
        Settings,
        "load_official",
        return_value=Settings(hitch_cycle_num=2, cycle_num=3, auto_secret_realm=True),
    ):
        chain_settings = live_capture._prepare_settings(None, "hitch_lobby_chain", live_input=True)
    assert chain_settings.mode_id == "lobby_hitch"
    assert chain_settings.cycle_num == 2
    assert chain_settings.hitch_cycle_num == 2


def test_lobby_hitch_allowed_reasons() -> None:
    allowed = live_capture._probe_allowed_reasons("lobby_hitch")
    assert allowed == {
        "HitchRefresh", "HitchJoin", "HitchGoHome", "HitchLeaveRoom",
        "HitchDismissPopup", "HitchSearchBox", "HitchSearchType",
        "HitchSearchEnter", "HitchSelectTab",
    }
    assert live_capture._probe_allowed_reasons("lobby_search") == {
        "HitchSearchBox", "HitchRefresh", "HitchJoin", "HitchReady",
        "HitchDismissPopup", "HitchLeaveFloorOne", "HitchConfirmLeave",
        "HitchSelectTab", "HitchDismissPlatformModalEsc",
        "HitchDismissPlatformModalClose", "HitchLeaveRoom", "HitchGoHome",
        "HitchDismissPlatformPrompt", "HitchDismissPlatformPromptEsc",
        "HitchStallWatchdogEsc",
    }
    assert "OpenArchiveChallenges" in live_capture._probe_allowed_reasons("archive_challenge")
    assert "OpenHeirloomChallenges" in live_capture._probe_allowed_reasons("heirloom")
    assert "PublicBackpackClose" in live_capture._probe_allowed_reasons("heirloom")
    assert "DismissHeirloomDialog" not in live_capture._probe_allowed_reasons("heirloom")
    assert "PublicBackpackStash" in live_capture._probe_allowed_reasons("public_backpack_deposit")
    assert "PublicBackpackClose" in live_capture._probe_allowed_reasons("public_backpack_deposit")


def test_heirloom_probe_bootstrap_uses_classified_open_page() -> None:
    med = Mediator(Settings(cjb_boss="01暴掠龙"), ROOT)
    frame = _fixture_frame()
    with patch.object(med, "_post_game_state", return_value="HEIRLOOM_DIALOG"):
        bootstrap = _bootstrap_target_probe(med, "heirloom", frame)
    assert bootstrap["post_game_route"] == "heirloom_active"
    assert bootstrap["classified_start_surface"] == "HEIRLOOM_DIALOG"
    assert med._post_game_pending is True
    assert med._post_game_route == "heirloom_active"


def test_action_reason_bridge_reads_act_scroll_reason_not_the_y_pixel() -> None:
    med = Mediator(Settings(), ROOT)
    seen: list[str] = []

    def fake_scroll(x, y, clicks, reason=""):
        seen.append(str(getattr(med, "_live_capture_action_reason", "")))
        return True

    med.act_scroll = fake_scroll  # type: ignore[method-assign]
    live_capture._install_action_reason_bridge(med)
    med.act_scroll(1080, 498, -5, "BossConfigured-scroll")
    assert seen == ["BossConfigured-scroll"]


def test_heirloom_probe_bootstrap_keeps_plaza_route_on_npc_hub() -> None:
    med = Mediator(Settings(cjb_boss="01暴掠龙"), ROOT)
    frame = _fixture_frame()
    with patch.object(med, "_post_game_state", return_value="NPC_HUB"):
        bootstrap = _bootstrap_target_probe(med, "heirloom", frame)
    assert bootstrap["post_game_route"] == "heirloom"
    assert bootstrap["classified_start_surface"] == "NPC_HUB"
    assert med._post_game_route == "heirloom"


def test_lobby_search_requires_input_and_room_list_pixel_change() -> None:
    before_pixels = np.zeros((300, 400, 3), dtype=np.uint8)
    after_pixels = before_pixels.copy()
    after_pixels[42:58, 144:176] = 255
    after_pixels[150:170, 80:320] = 255
    before = Frame(before_pixels, left=100, top=200, window_title="KK官方对战平台", hwnd=99, role="l0")
    changed = Frame(after_pixels, left=100, top=200, window_title="KK官方对战平台", hwnd=99, role="l0")
    action = {"reason": "HitchSearchBox", "point": [260, 250], "text": "3"}
    input_record = {"success": True, "status": "SUCCESS"}

    confirmed = live_capture._target_postcondition_snapshot(
        "lobby_search",
        None,
        changed,
        {"phase": "LOBBY_ROOM"},
        action,
        {"observed": False},
        before_frame=before,
        input_record=input_record,
    )
    unchanged = live_capture._target_postcondition_snapshot(
        "lobby_search",
        None,
        before,
        {"phase": "LOBBY_ROOM"},
        action,
        {"observed": False},
        before_frame=before,
        input_record=input_record,
    )

    assert confirmed["observed"] is True
    assert confirmed["authoritative"] is False
    assert confirmed["visual_change"]["search_box"]["changed_pixels"] > 0
    assert confirmed["visual_change"]["room_list"]["changed_pixels"] > 0
    assert unchanged["observed"] is False
    assert unchanged["state"] == "input_not_observed"
    assert unchanged["visual_change"]["search_box"]["changed_pixels"] == 0
    assert unchanged["visual_change"]["room_list"]["changed_pixels"] == 0
    assert live_capture._stage_from_observation(
        "lobby_search", {}, {}, action, confirmed,
    ) == "SEARCH_CONFIRMED"

    field_only_pixels = before_pixels.copy()
    field_only_pixels[42:58, 144:176] = 255
    field_only = Frame(field_only_pixels, left=100, top=200, window_title="KK官方对战平台", hwnd=99, role="l0")
    not_submitted = live_capture._target_postcondition_snapshot(
        "lobby_search",
        None,
        field_only,
        {"phase": "LOBBY_ROOM"},
        action,
        {"observed": False},
        before_frame=before,
        input_record=input_record,
    )
    assert not_submitted["observed"] is False
    assert not_submitted["state"] == "search_results_not_observed"

    existing = live_capture._target_postcondition_snapshot(
        "lobby_search",
        SimpleNamespace(_lobby_room_list_evidence=lambda _frame: True),
        field_only,
        {"phase": "LOBBY_ROOM"},
        action,
        {"observed": False},
        before_frame=before,
        input_record=input_record,
    )
    assert existing["observed"] is True
    assert existing["state"] == "confirmed_existing_results"


def test_lobby_search_refresh_requires_room_list_change() -> None:
    before_pixels = np.zeros((300, 400, 3), dtype=np.uint8)
    after_pixels = before_pixels.copy()
    after_pixels[150:170, 80:320] = 255
    before = Frame(before_pixels, window_title="KK官方对战平台", hwnd=99, role="l0")
    after = Frame(after_pixels, window_title="KK官方对战平台", hwnd=99, role="l0")
    action = {"reason": "HitchRefresh", "point": [320, 90]}
    input_record = {"success": True, "status": "SUCCESS"}

    confirmed = live_capture._target_postcondition_snapshot(
        "lobby_search", None, after, {"hitch_refresh_count": 1}, action, {},
        before_frame=before, input_record=input_record,
    )
    second = live_capture._target_postcondition_snapshot(
        "lobby_search", None, after, {"hitch_refresh_count": 2}, action, {},
        before_frame=before, input_record=input_record,
    )
    unchanged = live_capture._target_postcondition_snapshot(
        "lobby_search", None, before, {}, action, {}, before_frame=before, input_record=input_record,
    )

    assert confirmed["observed"] is True
    assert confirmed["kind"] == "lobby_search_refresh"
    assert confirmed["authoritative"] is False
    assert second["observed"] is True
    assert second["kind"] == "lobby_search_refresh"
    assert second["authoritative"] is False
    assert unchanged["observed"] is False
    assert unchanged["state"] == "refresh_not_observed"
    assert live_capture._stage_from_observation(
        "lobby_search", {}, {}, action, confirmed,
    ) == "REFRESH_CONFIRMED"


def test_lobby_search_join_requires_real_room_waiting_evidence() -> None:
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    frame = _fixture_frame()
    action = {"reason": "HitchJoin", "point": [500, 400]}
    input_record = {"success": True, "status": "SUCCESS"}

    with patch.object(med, "find_scene", return_value=object()):
        confirmed = live_capture._target_postcondition_snapshot(
            "lobby_search", med, frame, {"phase": "ROOM_WAITING"}, action, {},
            before_frame=frame, input_record=input_record,
        )
    with patch.object(med, "find_scene", return_value=None), \
         patch.object(med, "_find_room_start", return_value=None):
        waiting = live_capture._target_postcondition_snapshot(
            "lobby_search", med, frame, {"phase": "LOBBY_ROOM"}, action, {},
            before_frame=frame, input_record=input_record,
        )
    with patch.object(med, "_hitch_room_controls_visible", return_value=True), \
         patch.object(med, "_find_room_start", return_value=None):
        immediate = live_capture._target_postcondition_snapshot(
            "lobby_search", med, frame, {"phase": "LOBBY_ROOM"}, action, {},
            before_frame=frame, input_record=input_record,
        )

    assert confirmed["observed"] is True
    assert confirmed["kind"] == "lobby_hitch_in_room"
    assert waiting["observed"] is False
    assert waiting["state"] == "waiting_room_confirm"
    assert immediate["observed"] is True
    assert immediate["authoritative"] is False


def test_lobby_hitch_pending_join_prefers_separate_room_hwnd() -> None:
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    lobby = Frame(
        np.full((945, 1332, 3), (24, 22, 20), dtype=np.uint8),
        window_title="KK官方对战平台", hwnd=10, role="l0",
    )
    room_image = cv2.imdecode(
        np.fromfile(
            str(ROOT / "tests" / "fixtures" / "real_room_window_frame.png"),
            dtype=np.uint8,
        ),
        cv2.IMREAD_COLOR,
    )
    assert room_image is not None
    room = Frame(
        room_image,
        window_title="KK官方对战平台",
        hwnd=20,
        role="l0",
    )
    med._last_frame = lobby
    med._last_capture_role = "l0"
    med._hitch_sm.note_join_click(1.0)
    targets = [
        SimpleNamespace(hwnd=10, title="KK官方对战平台"),
        SimpleNamespace(hwnd=20, title="KK官方对战平台"),
    ]

    with patch("shuabao.mediator.find_window_targets", return_value=targets), \
         patch("shuabao.mediator.capture_target", side_effect=lambda target: (
             room if target.hwnd == 20 else lobby
         )):
        selected = med._capture_best("KK官方对战平台", "l0")

    assert selected.hwnd == 20


def test_lobby_hitch_pending_join_prefers_new_unconfirmed_popup_window() -> None:
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    lobby = Frame(
        np.full((945, 1332, 3), (24, 22, 20), dtype=np.uint8),
        window_title="KK官方对战平台", hwnd=10, role="l0",
    )
    popup = Frame(
        np.full((720, 960, 3), (18, 18, 18), dtype=np.uint8),
        window_title="KK官方对战平台", hwnd=20, role="l0",
    )
    med._last_frame = lobby
    med._last_capture_role = "l0"
    med._hitch_sm.note_join_click(1.0)
    med._hitch_join_origin_hwnd = lobby.hwnd
    targets = [
        SimpleNamespace(hwnd=10, title="KK官方对战平台"),
        SimpleNamespace(hwnd=20, title="KK官方对战平台"),
    ]

    with patch("shuabao.mediator.find_window_targets", return_value=targets), \
         patch("shuabao.mediator.capture_target", side_effect=lambda target: (
             popup if target.hwnd == 20 else lobby
         )):
        selected = med._capture_best("KK官方对战平台", "l0")

    assert selected.hwnd == 20


def test_lobby_hitch_pending_exit_prefers_confirm_child_without_dialog_template() -> None:
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    lobby = Frame(
        np.full((945, 1332, 3), (24, 22, 20), dtype=np.uint8),
        window_title="KK官方对战平台", hwnd=10, role="l0",
    )
    confirm_image = np.full((260, 440, 3), (24, 22, 20), dtype=np.uint8)
    cv2.rectangle(confirm_image, (44, 172), (211, 195), (200, 130, 20), -1)
    confirm = Frame(
        confirm_image, window_title="KK官方对战平台", hwnd=20, role="l0",
    )
    med._hitch_floor_exit_pending = True
    targets = [
        SimpleNamespace(hwnd=10, title="KK官方对战平台"),
        SimpleNamespace(hwnd=20, title="KK官方对战平台"),
    ]

    with patch("shuabao.mediator.find_window_targets", return_value=targets), \
         patch("shuabao.mediator.capture_target", side_effect=lambda target: (
             confirm if target.hwnd == 20 else lobby
         )), \
         patch.object(med, "find_scene", return_value=None):
        selected = med._capture_best("KK官方对战平台", "l0")

    assert selected.hwnd == 20


def test_lobby_search_ready_requires_button_state_change() -> None:
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    before = Frame(
        cv2.imdecode(
            np.fromfile(
                str(ROOT / "fixtures" / "lobby_hitch_20260814" / "kk_room_ready_btn_t040.png"),
                dtype=np.uint8,
            ),
            cv2.IMREAD_COLOR,
        ),
        window_title="KK官方对战平台", hwnd=99, role="l0",
    )
    after = Frame(
        cv2.imdecode(
            np.fromfile(
                str(ROOT / "fixtures" / "lobby_hitch_20260814" / "kk_room_cancel_ready_t041.png"),
                dtype=np.uint8,
            ),
            cv2.IMREAD_COLOR,
        ),
        window_title="KK官方对战平台", hwnd=99, role="l0",
    )
    assert before.bgr is not None and after.bgr is not None
    action = {"reason": "HitchReady", "point": [862, 614]}
    input_record = {"success": True, "status": "SUCCESS"}

    assert med._find_hitch_ready_button(before) is not None
    assert med._find_hitch_ready_button(after) is None
    assert med._hitch_room_controls_visible(after) is True
    confirmed = live_capture._target_postcondition_snapshot(
        "lobby_search", med, after, {"phase": "ROOM_WAITING"}, action, {},
        before_frame=before, input_record=input_record,
    )

    assert confirmed["observed"] is True
    assert confirmed["kind"] == "lobby_hitch_ready"
    assert live_capture._stage_from_observation(
        "lobby_search", {}, {}, action, confirmed,
    ) == "READY_CONFIRMED"


def _synthetic_hitch_room(
    self_row: int, *, first_floor_empty: bool = False, first_row_host: bool = True,
) -> Frame:
    image = np.full((904, 1224, 3), (24, 22, 20), dtype=np.uint8)
    row_centers = (221, 261, 302, 342)
    cv2.rectangle(image, (299, row_centers[self_row] - 19), (1130, row_centers[self_row] + 19), (139, 71, 1), -1)
    if first_floor_empty:
        cv2.rectangle(image, (308, 207), (341, 234), (40, 32, 24), -1)
        cv2.rectangle(image, (316, 211), (326, 221), (224, 112, 0), -1)
    else:
        cv2.rectangle(image, (308, 207), (341, 234), (68, 68, 68), -1)
    if first_row_host:
        cv2.rectangle(image, (1005, 212), (1045, 230), (30, 50, 230), -1)
    cv2.rectangle(image, (792, 596), (931, 631), (200, 130, 20), -1)
    cv2.rectangle(image, (848, 607), (875, 619), (245, 245, 245), -1)
    cv2.rectangle(image, (1036, 596), (1124, 631), (200, 130, 20), -1)
    cv2.rectangle(image, (1066, 607), (1093, 619), (245, 245, 245), -1)
    return Frame(image, window_title="KK官方对战平台", hwnd=99, role="l0")


def test_lobby_hitch_seat_unknown_never_authorizes_exit() -> None:
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)

    assert med._hitch_room_seat_decision(_synthetic_hitch_room(0)) == "unknown"
    assert med._hitch_room_seat_decision(_synthetic_hitch_room(3)) == "unknown"
    assert med._hitch_room_seat_decision(
        _synthetic_hitch_room(3, first_row_host=False),
    ) == "unknown"


def test_lobby_search_floor_one_exit_requires_visual_room_close() -> None:
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    before = _synthetic_hitch_room(0)
    after = Frame(
        np.full((904, 1224, 3), (24, 22, 20), dtype=np.uint8),
        window_title="KK官方对战平台", hwnd=99, role="l0",
    )
    action = {"reason": "HitchLeaveFloorOne", "point": [1080, 614]}
    post = live_capture._target_postcondition_snapshot(
        "lobby_search", med, after, {"phase": "LOBBY_ROOM"}, action, {},
        before_frame=before, input_record={"success": True, "status": "SUCCESS"},
    )

    assert post["observed"] is True
    assert post["authoritative"] is False
    assert post["kind"] == "lobby_floor_one_rejected"
    assert live_capture._stage_from_observation(
        "lobby_search", {}, {}, action, post,
    ) == "FLOOR_ONE_REJECTED"


def test_lobby_hitch_clicks_two_character_ready_but_not_four_character_action() -> None:
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    image = cv2.imdecode(
        np.fromfile(
            str(ROOT / "fixtures" / "lobby_hitch_20260814" / "kk_room_ready_btn_t040.png"),
            dtype=np.uint8,
        ),
        cv2.IMREAD_COLOR,
    )
    assert image is not None
    frame = Frame(image, window_title="KK官方对战平台", hwnd=99, role="l0")

    # Room identity is established by the real page-level contract.
    med._confirmed_room_hwnd = frame.hwnd
    with patch.object(med, "act_click", return_value=True) as click:
        med._tick_lobby_hitch(frame, "UNKNOWN")

    click.assert_called_once()
    assert click.call_args.args[1] == "HitchReady"
    assert med.phase is Phase.ROOM_WAITING


def test_lobby_hitch_readies_first_even_if_host_not_floor_one() -> None:
    from shuabao.vision.matcher import MatchResult

    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    frame = _synthetic_hitch_room(0, first_row_host=False)
    med._confirmed_room_hwnd = frame.hwnd
    ready_hit = MatchResult("room_ready_btn", 0.95, 860, 614, 792, 596, 931, 631)

    with patch.object(med, "_is_confirmed_room_frame", return_value=True), \
         patch.object(med, "_hitch_room_ready_contract", return_value=("ready", ready_hit)), \
         patch.object(med, "_hitch_room_seat_decision", return_value="reject") as seat_dec, \
         patch.object(med, "act_click", return_value=True) as click:
        med._tick_lobby_hitch(frame, "UNKNOWN")

    click.assert_called_once_with(ready_hit, "HitchReady")
    assert med._hitch_status == "已点击准备"
    assert med.phase is Phase.ROOM_WAITING
    assert med._hitch_floor_exit_pending is False
    seat_dec.assert_not_called()


def test_lobby_hitch_unknown_seat_does_not_leave_or_blacklist() -> None:
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    frame = _synthetic_hitch_room(0, first_row_host=False)
    med._hitch_pending_room_key = "room-763405"

    # Room identity is established by _capture_best -> _is_confirmed_room_frame.
    # This tick is called directly, and the synthetic frame carries no real
    # room_exit_btn template, so seed the authority the capture layer owns.
    med._confirmed_room_hwnd = frame.hwnd
    with patch.object(med, "_is_confirmed_room_frame", return_value=True), \
         patch.object(med, "find_scene", return_value=None), \
         patch.object(med, "act_click", return_value=True) as click:
        med._tick_lobby_hitch(frame, "UNKNOWN")

    click.assert_not_called()
    assert med._hitch_floor_exit_pending is False
    assert "room-763405" not in med._hitch_blacklisted_room_keys


def test_lobby_hitch_confirms_exit_dialog_instead_of_escaping() -> None:
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    image = np.full((904, 1224, 3), (24, 22, 20), dtype=np.uint8)
    cv2.rectangle(image, (120, 350), (330, 410), (200, 130, 20), -1)
    frame = Frame(image, window_title="KK官方对战平台", hwnd=99, role="l0")
    med._hitch_floor_exit_pending = True
    med._hitch_pending_room_key = "room-763405"
    med._confirmed_room_hwnd = frame.hwnd

    with patch.object(med, "_hitch_exit_modal_visible", return_value=True), \
        patch.object(med, "find_scene", return_value=None), \
        patch.object(med, "act_click", return_value=True) as click, \
        patch.object(med, "act_key") as key:
        med._tick_lobby_hitch(frame, "UNKNOWN")

    click.assert_called_once()
    assert click.call_args.args[1] == "HitchConfirmLeave"
    key.assert_not_called()
    assert med._hitch_floor_exit_confirmed is True
    assert "room-763405" in med._hitch_blacklisted_room_keys

def test_lobby_hitch_confirm_leave_zero_input_when_modal_identity_unconfirmed() -> None:
    """Issue B: 仅有蓝色色块几何但无法确认已知退出弹窗身份时，必须零输入等待。"""
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    image = np.full((904, 1224, 3), (24, 22, 20), dtype=np.uint8)
    cv2.rectangle(image, (120, 350), (330, 410), (200, 130, 20), -1)
    frame = Frame(image, window_title="KK官方对战平台", hwnd=99, role="l0")
    med._hitch_floor_exit_pending = True
    med._hitch_pending_room_key = "room-763405"

    with patch.object(med, "_hitch_exit_modal_visible", return_value=False), \
        patch.object(med, "act_click", return_value=True) as click, \
        patch.object(med, "act_key") as key:
        med._tick_lobby_hitch(frame, "UNKNOWN")

    click.assert_not_called()
    key.assert_not_called()
    assert med._hitch_floor_exit_pending is True
    assert getattr(med, "_hitch_floor_exit_confirmed", False) is False


def test_lobby_hitch_generic_popup_without_exit_specific_marker_has_zero_input() -> None:
    """P1: exit_pending + generic popup (lobby_popup_dialog) + blue block + no exit-specific marker => ZERO INPUT。"""
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    image = np.full((904, 1224, 3), (24, 22, 20), dtype=np.uint8)
    # Draw blue confirmation block candidate
    cv2.rectangle(image, (120, 350), (330, 410), (200, 130, 20), -1)
    frame = Frame(image, window_title="KK官方对战平台", hwnd=99, role="l0")
    med._hitch_floor_exit_pending = True
    med._hitch_pending_room_key = "room-763405"

    # Mock generic popup hit (e.g. lobby_popup_dialog) without exit-specific markers
    def mock_find_scene(f: Frame, key: str, **kwargs):
        if key == "lobby_popup_dialog":
            return MatchResult(name="lobby_popup_dialog", score=0.9, x=100, y=100, w=400, h=60, screen_x=120, screen_y=120)
        return None

    with patch.object(med, "find_scene", side_effect=mock_find_scene), \
        patch.object(med, "find", return_value=None), \
        patch.object(med, "act_click", return_value=True) as click, \
        patch.object(med, "act_key") as key:
        med._tick_lobby_hitch(frame, "UNKNOWN")

    # Generic popup alone must NOT grant HitchConfirmLeave input authority
    click.assert_not_called()
    key.assert_not_called()
    assert med._hitch_floor_exit_pending is True
    assert getattr(med, "_hitch_floor_exit_confirmed", False) is False


def test_lobby_hitch_low_information_leave_crop_has_no_exit_authority() -> None:
    """The dark lobby_popup_leave crop must not grant exit-modal authority."""
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    frame = Frame(
        np.full((904, 1224, 3), (24, 22, 20), dtype=np.uint8),
        window_title="KK官方对战平台", hwnd=99, role="l0",
    )
    requested: list[str] = []

    def record_find(_frame: Frame, names, **_kwargs):
        requested.extend(names if isinstance(names, (list, tuple)) else [str(names)])
        return None

    with patch.object(med, "find", side_effect=record_find), \
        patch.object(med, "find_scene", return_value=None), \
        patch.object(med, "_find_hitch_exit_confirm_button", return_value=None):
        assert med._hitch_exit_modal_visible(frame) is False

    assert "lobby/lobby_popup_leave" not in requested


def test_lobby_hitch_exit_deadline_reobserves_without_inferring_exit() -> None:
    """An expired exit budget must recover/reclassify, never finalize or stop."""
    med = Mediator(Settings(dry_run=True, mode_id="lobby_hitch"), ROOT)
    frame = Frame(
        np.full((904, 1224, 3), (24, 22, 20), dtype=np.uint8),
        window_title="KK官方对战平台", hwnd=99, role="l0",
    )
    med._hitch_floor_exit_pending = True
    med._hitch_floor_exit_deadline = 100.0
    med._hitch_floor_exit_input_generation = 1
    med._capture_generation = 2

    with patch("shuabao.mediator.time.time", return_value=101.0), \
        patch.object(med, "_lobby_room_list_evidence", return_value=False), \
        patch.object(med, "_hitch_exit_modal_visible", return_value=False), \
        patch.object(med, "_record_lobby_observation_incident") as incident, \
        patch.object(med, "act_click") as click, \
        patch.object(med, "act_key") as key, \
        patch.object(med, "stop") as stop:
        action = med._tick_lobby_hitch(frame, "UNKNOWN")

    assert action is LoopAction.Continue
    incident.assert_called_once()
    click.assert_not_called()
    key.assert_not_called()
    stop.assert_not_called()
    assert med._hitch_floor_exit_pending is True
    assert med._hitch_floor_exit_deadline == 109.0
    assert med._hitch_floor_exit_reobserve_until == 103.0


def test_lobby_hitch_confirm_leave_clicks_when_exit_specific_marker_present() -> None:
    """P1: 存在明确 exit-specific marker 且定位到确认按钮时，允许发起 HitchConfirmLeave 点击。"""
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    image = np.full((904, 1224, 3), (24, 22, 20), dtype=np.uint8)
    cv2.rectangle(image, (120, 350), (330, 410), (200, 130, 20), -1)
    frame = Frame(image, window_title="KK官方对战平台", hwnd=99, role="l0")
    med._hitch_floor_exit_pending = True
    med._hitch_pending_room_key = "room-763405"
    med._confirmed_room_hwnd = frame.hwnd

    with patch.object(med, "_hitch_exit_modal_visible", return_value=True), \
        patch.object(med, "act_click", return_value=True) as click, \
        patch.object(med, "act_key") as key:
        med._tick_lobby_hitch(frame, "UNKNOWN")

    click.assert_called_once()
    assert click.call_args.args[1] == "HitchConfirmLeave"
    key.assert_not_called()
def test_lobby_hitch_exit_confirm_rejection_recovers_when_modal_dismissed() -> None:
    """act_click 拒绝后弹窗在下一帧消失：必须收尾退出回大厅，不能永久挂起。"""
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    modal = np.full((904, 1224, 3), (24, 22, 20), dtype=np.uint8)
    cv2.rectangle(modal, (120, 350), (330, 410), (200, 130, 20), -1)
    modal_frame = Frame(modal, window_title="KK官方对战平台", hwnd=99, role="l0")
    lobby_frame = Frame(
        np.full((904, 1224, 3), (24, 22, 20), dtype=np.uint8),
        window_title="KK官方对战平台", hwnd=99, role="l0",
    )
    med._hitch_floor_exit_pending = True
    med._hitch_floor_exit_confirmed = False
    med._hitch_floor_exit_attempted_at = 100.0
    med._hitch_pending_room_key = "room-763405"
    med._confirmed_room_hwnd = 99

    def modal_visible(frame: Frame) -> bool:
        return frame is modal_frame

    with patch("shuabao.mediator.time.time", return_value=101.0), \
        patch.object(med, "_hitch_exit_modal_visible", side_effect=modal_visible), \
        patch.object(med, "find_scene", return_value=None), \
        patch.object(med, "_lobby_room_list_evidence", return_value=True), \
        patch.object(med, "_find_hitch_ready_button", return_value=None), \
        patch.object(med, "_hitch_room_controls_visible", return_value=False), \
        patch.object(med, "act_click", return_value=False) as click:
        med._tick_lobby_hitch(modal_frame, "UNKNOWN")
        assert click.call_args.args[1] == "HitchConfirmLeave"
        assert med._hitch_floor_exit_pending is True
        assert med._hitch_floor_exit_confirmed is False

        med._tick_lobby_hitch(lobby_frame, "UNKNOWN")

    assert med.phase is Phase.LOBBY_ROOM
    assert med._hitch_floor_exit_pending is False
    assert med._hitch_floor_exit_confirmed is False
    assert med._hitch_floor_exit_attempted_at is None
    assert "room-763405" in med._hitch_blacklisted_room_keys
    assert med._hitch_pending_room_key is None


def test_lobby_hitch_stale_room_waiting_context_does_not_block_exit_return_to_lobby() -> None:
    """场景 A: 陈旧 context=='ROOM_WAITING' + tangible_room=False + lobby_visible=True -> finalize 到 LOBBY_ROOM。"""
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    frame = Frame(
        np.full((904, 1224, 3), (24, 22, 20), dtype=np.uint8),
        window_title="KK官方对战平台", hwnd=99, role="l0",
    )
    med._hitch_floor_exit_pending = True
    med._hitch_floor_exit_confirmed = True
    med._hitch_floor_exit_attempted_at = 100.0
    med._hitch_pending_room_key = "room-763405"

    with patch("shuabao.mediator.time.time", return_value=101.0), \
        patch.object(med, "find_scene", return_value=None), \
        patch.object(med, "_lobby_room_list_evidence", return_value=True), \
        patch.object(med, "_find_hitch_ready_button", return_value=None), \
        patch.object(med, "_hitch_room_controls_visible", return_value=False), \
        patch.object(med, "act_click", return_value=False) as click:
        med._tick_lobby_hitch(frame, "ROOM_WAITING")

    click.assert_not_called()
    assert med.phase is Phase.LOBBY_ROOM
    assert med._hitch_floor_exit_pending is False
    assert "room-763405" in med._hitch_blacklisted_room_keys


def test_lobby_hitch_tangible_room_with_timeout_still_zero_input_and_no_lobby() -> None:
    """场景 B: tangible_room=True + elapsed > 3s + lobby_visible=False -> 绝不进入 LOBBY_ROOM，零输入等待。"""
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    frame = Frame(
        np.full((904, 1224, 3), (24, 22, 20), dtype=np.uint8),
        window_title="KK官方对战平台", hwnd=99, role="l0",
    )
    med._hitch_floor_exit_pending = True
    med._hitch_floor_exit_attempted_at = 100.0

    with patch("shuabao.mediator.time.time", return_value=110.0), \
        patch.object(med, "find_scene", return_value=None), \
        patch.object(med, "_lobby_room_list_evidence", return_value=False), \
        patch.object(med, "_find_hitch_ready_button", return_value=None), \
        patch.object(med, "_hitch_room_controls_visible", return_value=True), \
        patch.object(med, "act_click", return_value=False) as click:
        med._tick_lobby_hitch(frame, "UNKNOWN")

    click.assert_not_called()
    assert med._hitch_floor_exit_pending is True
    assert med.phase is not Phase.LOBBY_ROOM


def test_lobby_hitch_no_room_no_lobby_holds_pending_zero_input() -> None:
    """场景 C: tangible_room=False + lobby_visible=False -> 缺少大厅依据，保持 pending 零输入。"""
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    frame = Frame(
        np.full((904, 1224, 3), (24, 22, 20), dtype=np.uint8),
        window_title="KK官方对战平台", hwnd=99, role="l0",
    )
    med._hitch_floor_exit_pending = True
    med._hitch_floor_exit_attempted_at = 100.0

    with patch("shuabao.mediator.time.time", return_value=105.0), \
        patch.object(med, "find_scene", return_value=None), \
        patch.object(med, "_lobby_room_list_evidence", return_value=False), \
        patch.object(med, "_find_hitch_ready_button", return_value=None), \
        patch.object(med, "_hitch_room_controls_visible", return_value=False), \
        patch.object(med, "act_click", return_value=False) as click:
        med._tick_lobby_hitch(frame, "UNKNOWN")

    click.assert_not_called()
    assert med._hitch_floor_exit_pending is True
    assert med.phase is not Phase.LOBBY_ROOM


def test_lobby_hitch_conflicting_room_and_lobby_holds_pending_zero_input() -> None:
    """场景 D: tangible_room=True + lobby_visible=True -> 证据冲突/歧义，保持 pending 零输入。"""
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    frame = Frame(
        np.full((904, 1224, 3), (24, 22, 20), dtype=np.uint8),
        window_title="KK官方对战平台", hwnd=99, role="l0",
    )
    med._hitch_floor_exit_pending = True
    med._hitch_floor_exit_attempted_at = 100.0

    # Room identity is established by _capture_best -> _is_confirmed_room_frame.
    # This tick is called directly, and the synthetic frame carries no real
    # room_exit_btn template, so seed the authority the capture layer owns.
    med._confirmed_room_hwnd = frame.hwnd
    with patch("shuabao.mediator.time.time", return_value=101.0), \
        patch.object(med, "find_scene", return_value=None), \
        patch.object(med, "_lobby_room_list_evidence", return_value=True), \
        patch.object(med, "_find_hitch_ready_button", return_value=None), \
        patch.object(med, "_hitch_room_controls_visible", return_value=True), \
        patch.object(med, "_is_confirmed_room_frame", return_value=True), \
        patch.object(med, "act_click", return_value=False) as click:
        med._tick_lobby_hitch(frame, "UNKNOWN")

    click.assert_not_called()
    assert med._hitch_floor_exit_pending is True
    assert med.phase is not Phase.LOBBY_ROOM

def test_tick_l0_exit_pending_does_not_clobber_room_start_and_stays_zero_input() -> None:
    """Issue A: 当 _hitch_floor_exit_pending=True 时，必须经过 _tick_l0()，
    禁止 ROOM_WAITING + lobby evidence 把 room_start 清成 None；
    冲突 room_start=True + lobby=True 到达 _tick_lobby_hitch() 后仍判 ambiguous / pending / 零输入。
    """
    from shuabao.vision.matcher import MatchResult

    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    med._hitch_floor_exit_pending = True
    med._hitch_pending_room_key = "room-763405"
    med.phase = Phase.LOBBY_ROOM

    frame = Frame(np.full((904, 1224, 3), 100, dtype=np.uint8), window_title="KK官方对战平台", hwnd=99, role="l0")
    fake_room_start = MatchResult(name="room_start", score=0.9, x=100, y=100, w=50, h=50, screen_x=125, screen_y=125)

    # Room identity is established by _capture_best -> _is_confirmed_room_frame.
    # This tick is called directly, and the synthetic frame carries no real
    # room_exit_btn template, so seed the authority the capture layer owns.
    med._confirmed_room_hwnd = frame.hwnd
    with patch.object(med, "_is_confirmed_room_frame", return_value=True), \
         patch.object(med, "_detect_context", return_value="ROOM_WAITING"), \
         patch.object(med, "_lobby_room_list_evidence", return_value=True), \
         patch.object(med, "_find_room_start", return_value=fake_room_start), \
         patch.object(med, "act_click") as click, \
         patch.object(med, "act_key") as key:
        action = med._tick_l0(frame)

    # 校验：零输入，保持 pending，绝不转回 Phase.LOBBY_ROOM 成功态
    click.assert_not_called()
    key.assert_not_called()
    assert med._hitch_floor_exit_pending is True
    assert action == LoopAction.Continue

def test_lobby_hitch_unknown_page_without_room_list_anchor_has_zero_input() -> None:
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    frame = _fixture_frame()

    with patch.object(med, "_lobby_room_list_evidence", return_value=False), \
        patch.object(med, "find_scene", return_value=None), \
        patch.object(med, "act_click", return_value=True) as click:
        med._tick_lobby_hitch(frame, "UNKNOWN")

    click.assert_not_called()


def test_lobby_hitch_black_frame_has_zero_input_even_with_stale_template() -> None:
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    frame = Frame(np.zeros((945, 1332, 3), dtype=np.uint8), role="l0")

    with patch.object(med, "find_scene", return_value=object()), \
         patch.object(med, "act_click") as click, \
         patch.object(med, "act_search_box") as search:
        med._tick_lobby_hitch(frame, "UNKNOWN")

    click.assert_not_called()
    search.assert_not_called()

def test_lobby_hitch_exit_pending_black_frame_holds_zero_input() -> None:
    """场景 E: 退出 pending 状态下收到全黑帧，必须保持 pending 且零输入（不回归）。"""
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    frame = Frame(np.zeros((945, 1332, 3), dtype=np.uint8), role="l0")
    med._hitch_floor_exit_pending = True

    with patch.object(med, "act_click") as click, \
         patch.object(med, "act_key") as key:
        med._tick_lobby_hitch(frame, "UNKNOWN")

    click.assert_not_called()
    key.assert_not_called()
    assert med._hitch_floor_exit_pending is True
    assert med.phase is not Phase.LOBBY_ROOM


def test_lobby_room_list_evidence_rejects_wrong_tab_template_hit() -> None:
    """模板命中（find_scene right_tab MatchResult）本身不再是房间列表证据：
    ea9776c 安全修复后灰模板权威被移除，仅蓝色高亮像素或刷新控件才是真权威，
    因此 wrong_tab 与 right_tab 的 template-only 命中都必须拒绝（False）。"""
    from shuabao.vision.matcher import MatchResult

    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    frame = Frame(np.zeros((945, 1332, 3), dtype=np.uint8), role="l0")
    wrong_tab = MatchResult("lobby_room_list_selected", 1.0, 230, 247, 75, 25, 230, 247)
    right_tab = MatchResult("lobby_room_list_selected", 1.0, 311, 247, 75, 25, 311, 247)

    with patch.object(
        med, "find_scene", side_effect=lambda _frame, key: wrong_tab
        if key == "lobby_room_list_selected" else None,
    ):
        assert med._lobby_room_list_evidence(frame) is False
    with patch.object(
        med, "find_scene", side_effect=lambda _frame, key: right_tab
        if key == "lobby_room_list_selected" else None,
    ):
        assert med._lobby_room_list_evidence(frame) is False


def test_lobby_room_list_evidence_rejects_selected_tab_highlight_without_surface() -> None:
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    image = np.zeros((945, 1332, 3), dtype=np.uint8)
    cv2.rectangle(image, (311, 254), (400, 260), (200, 130, 20), -1)
    frame = Frame(image, role="l0")

    with patch.object(med, "find_scene", return_value=None):
        assert med._lobby_room_list_evidence(frame) is False


def test_hitch_start_preflight_accepts_a_selectable_room_list_tab() -> None:
    frame = _fixture_frame()
    med = SimpleNamespace(
        _lobby_room_list_evidence=lambda _frame: False,
        _find_hitch_room_list_tab=lambda _frame: object(),
    )

    result = live_capture._start_surface_preflight(med, "hitch_lobby_chain", frame)

    assert result["status"] == "READY"
    assert result["classifier"] == "_lobby_room_list_evidence/_find_hitch_room_list_tab"
    assert "will acquire the list" in result["reason"]


def test_lobby_hitch_postcondition_and_stage() -> None:
    med = Mediator(Settings(), ROOT)
    frame = _fixture_frame()

    # Confirmed in room
    with patch.object(med, "find_scene", return_value=object()):
        post = live_capture._target_postcondition_snapshot(
            "lobby_hitch",
            med,
            frame,
            {"phase": "ROOM_WAITING"},
            {"reason": "HitchJoin"},
            {"observed": False},
        )
    assert post["observed"] is True
    assert post["kind"] == "lobby_hitch_in_room"

    stage = live_capture._stage_from_observation(
        "lobby_hitch",
        {"phase": "ROOM_WAITING"},
        {},
        {"reason": "HitchJoin"},
        post,
    )
    assert stage == "ROOM_WAITING_CONFIRMED"

    # Waiting confirm after join click
    with patch.object(med, "find_scene", return_value=None):
        post_join = live_capture._target_postcondition_snapshot(
            "lobby_hitch",
            med,
            frame,
            {"phase": "LOBBY_ROOM"},
            {"reason": "HitchJoin"},
            {"observed": False},
        )
    assert post_join["observed"] is False
    assert post_join["state"] == "waiting_room_confirm"
    stage_join = live_capture._stage_from_observation(
        "lobby_hitch",
        {"phase": "LOBBY_ROOM"},
        {},
        {"reason": "HitchJoin"},
        post_join,
    )
    assert stage_join == "JOIN"


def test_lobby_hitch_invoke_target_handler() -> None:
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    calls = []

    def mock_tick_lobby_hitch(frame, context, room_start=None, stage_page=False):
        calls.append((context, room_start, stage_page))
        return LoopAction.Continue

    med._tick_lobby_hitch = mock_tick_lobby_hitch
    frame = _fixture_frame()
    result = live_capture._invoke_target_handler(med, "lobby_hitch", frame)
    assert result is LoopAction.Continue
    assert len(calls) == 1

    result = live_capture._invoke_target_handler(med, "lobby_search", frame)
    assert result is LoopAction.Continue
    assert len(calls) == 2

def test_lobby_hitch_overrides_generic_room_context_when_list_is_visible() -> None:
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    calls: list[tuple[str, object, bool]] = []
    med._startup_state = lambda _frame: "UNKNOWN"
    med._detect_context = lambda _frame, _role: "ROOM_WAITING"
    med._lobby_room_list_evidence = lambda _frame: True
    med._tick_lobby_hitch = lambda frame, context, room_start=None, stage_page=False: (
        calls.append((context, room_start, stage_page)) or LoopAction.Continue
    )

    result = med._tick_l0(_fixture_frame())

    assert result is LoopAction.Continue
    assert calls == [("LOBBY_ROOM", None, False)]


def test_probe_entry_also_overrides_generic_room_context() -> None:
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    calls: list[tuple[str, object, bool]] = []
    med._detect_context = lambda _frame, _role: "ROOM_WAITING"
    med._find_room_start = lambda _frame: object()
    med._lobby_room_list_evidence = lambda _frame: True
    med._tick_lobby_hitch = lambda frame, context, room_start=None, stage_page=False: (
        calls.append((context, room_start, stage_page)) or LoopAction.Continue
    )

    result = live_capture._invoke_target_handler(med, "lobby_hitch", _fixture_frame())

    assert result is LoopAction.Continue
    assert calls == [("LOBBY_ROOM", None, False)]
def test_lobby_hitch_uses_default_and_custom_search_text() -> None:
    assert Settings().hitch_stage_prefix == "4,3"
    assert Settings._from_dict({"hitch_stage_prefix": "4-8"}).hitch_stage_prefix == "4-8"
    assert Settings._from_dict({"hitch_stage_prefix": "   "}).hitch_stage_prefix == "4,3"


def test_lobby_hitch_clicks_text_area_left_of_search_icon() -> None:
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    anchor = _search_icon_anchor()
    with patch.object(med, "_lobby_room_list_evidence", return_value=True), \
         patch.object(
             med,
             "find_scene",
             side_effect=lambda _frame, key: anchor if key == "lobby_search_icon" else None,
         ), \
         patch.object(med, "act_search_box", return_value=True) as search:
        med._tick_lobby_hitch(_fixture_frame(), "LOBBY_ROOM")

    click_hit, text, reason = search.call_args.args
    # Middle of the text area: inside the edit box, clear of the magnifier.
    assert (click_hit.screen_x, click_hit.screen_y) == (1180, 292)
    assert (text, reason) == ("4", "HitchSearchBox")
    tx = med._hitch_search
    assert tx is not None and tx.prefix == "4"
    assert tx.awaiting_confirm is True
    assert tx.confirmed is False


def test_lobby_hitch_waits_for_search_box_postcondition_before_scanning_rows() -> None:
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    med._hitch_sm.prefix = "3"
    med._hitch_search = SearchTransaction(prefix="3", opened_at=100.0, typed_at=100.0)
    frame = _fixture_frame()

    with patch("shuabao.mediator.time.time", return_value=101.0), \
         patch.object(med, "_lobby_room_list_evidence", return_value=True), \
         patch.object(med, "find_scene", return_value=None), \
         patch.object(med, "_hitch_search_prefix_confirmed", return_value=False), \
         patch.object(med, "_find_hitch_joinable_row") as scan, \
         patch.object(med, "act_click") as click:
        med._tick_lobby_hitch(frame, "LOBBY_ROOM")

    scan.assert_not_called()
    click.assert_not_called()
    assert med._hitch_prefix_ok() is False


def test_lobby_hitch_confirms_search_text_before_rows_are_eligible() -> None:
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    med._hitch_sm.prefix = "3"
    med._hitch_search = SearchTransaction(prefix="3", opened_at=100.0, typed_at=100.0)
    med._hitch_search_text_override = "3"
    frame = _fixture_frame()

    with patch("shuabao.mediator.time.time", return_value=101.0), \
         patch.object(med, "_lobby_room_list_evidence", return_value=True), \
         patch.object(med, "find_scene", return_value=None), \
         patch.object(med, "_find_hitch_joinable_row") as scan:
        med._tick_lobby_hitch(frame, "LOBBY_ROOM")

    scan.assert_not_called()
    assert med._hitch_search is not None
    assert med._hitch_search.confirmed is True
    assert med._hitch_prefix_ok() is True


def test_lobby_hitch_refresh_clicks_above_anchor_center() -> None:
    from shuabao.lobby_hitch import HitchAction
    from shuabao.vision.matcher import MatchResult

    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    anchor = MatchResult(
        name="lobby_refresh",
        score=1.0,
        x=1045,
        y=295,
        w=40,
        h=30,
        screen_x=1255,
        screen_y=339,
    )
    with patch.object(med, "_lobby_room_list_evidence", return_value=True), \
         patch.object(med, "find_scene", return_value=anchor):
        hit = med._hitch_action_hit(_fixture_frame(), HitchAction.REFRESH)

    assert hit.screen_x == 1255
    assert hit.screen_y == 324


def test_lobby_hitch_row_templates_are_rooted_at_repo() -> None:
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    with patch.object(med, "_lobby_room_list_evidence", return_value=True), \
         patch.object(med, "find_scene", return_value=_search_icon_anchor()), \
         patch("shuabao.mediator._load_template", return_value=None) as load:
        med._find_hitch_joinable_row(_fixture_frame())
    assert [call.args[0] for call in load.call_args_list] == [
        med.images / "lobby" / "lobby_room_lock.png",
        med.images / "lobby" / "lobby_4_4.png",
        med.images / "lobby" / "lobby_in_game.png",
    ]


def test_lobby_hitch_skips_full_and_active_rows_before_available_row() -> None:
    width, height = 1332, 945
    image = np.full((height, width, 3), (24, 22, 20), dtype=np.uint8)
    first_y, row_step, count_x, status_x = 385, 48, 920, 1150

    def draw_row(index: int, count: str, status: str) -> None:
        y = first_y + index * row_step
        cv2.putText(image, count, (count_x, y + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.36,
                    (190, 190, 190), 1, cv2.LINE_AA)
        cv2.putText(image, status, (status_x, y + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.36,
                    (190, 190, 190), 1, cv2.LINE_AA)

    draw_row(0, "4/4", "-")
    draw_row(1, "3/4", "GAME")
    draw_row(2, "2/4", "-")
    draw_row(3, "2/4", "-")
    full_template = image[first_y - 12:first_y + 12, count_x - 2:count_x + 35].copy()
    lock_template = np.zeros((8, 8, 3), dtype=np.uint8)
    lock_template[::2, ::2] = 255
    lock_template[1::2, 1::2] = 255

    def load_template(path: Path):
        if path.name == "lobby_room_lock.png":
            return lock_template
        if path.name == "lobby_4_4.png":
            return full_template
        return None

    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    med._hitch_rejected_row_ys.add(first_y + 2 * row_step)
    with patch.object(med, "_lobby_room_list_evidence", return_value=True), \
         patch.object(med, "find_scene", return_value=_search_icon_anchor()), \
         patch("shuabao.mediator._load_template", side_effect=load_template):
        hit = med._find_hitch_joinable_row(Frame(image))

    assert hit is not None
    assert hit.y == first_y + 3 * row_step


def test_lobby_hitch_skips_gray_lock_without_badge_dependency() -> None:
    width, height = 1332, 945
    image = np.full((height, width, 3), (24, 22, 20), dtype=np.uint8)
    first_y, row_step, count_x = 385, 48, 920

    for index in range(2):
        y = first_y + index * row_step
        cv2.putText(image, "1/4", (count_x, y + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.36,
                    (190, 190, 190), 1, cv2.LINE_AA)
    # First row has a gray lock and deliberately has no yellow V badge.
    lock_x, lock_y = 440, first_y - 6
    cv2.rectangle(image, (lock_x + 2, lock_y), (lock_x + 7, lock_y + 5), (180, 180, 180), 2)
    cv2.rectangle(image, (lock_x, lock_y + 5), (lock_x + 9, lock_y + 11), (180, 180, 180), -1)

    full_template = np.zeros((12, 24, 3), dtype=np.uint8)
    full_template[::2, ::2] = 255
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    with patch.object(med, "_lobby_room_list_evidence", return_value=True), \
         patch.object(med, "find_scene", return_value=_search_icon_anchor()), \
         patch("shuabao.mediator._load_template", side_effect=lambda path: (
             full_template if path.name == "lobby_4_4.png" else None
         )):
        hit = med._find_hitch_joinable_row(Frame(image))

    assert hit is not None
    assert hit.y == first_y + row_step


def test_lobby_hitch_refresh_cd_is_five_seconds() -> None:
    from shuabao.lobby_hitch import HitchAction, HitchSearchSM

    sm = HitchSearchSM()
    sm.note_refresh(100.0)

    assert sm.refresh_s_min == 5.0
    assert sm.refresh_s_max == 5.0
    assert sm.tick(now=104.9, matched=False, prefix_ok=True).action is HitchAction.NONE
    assert sm.tick(now=105.0, matched=False, prefix_ok=True).action is HitchAction.REFRESH


def test_lobby_hitch_default_multi_prefix_budget_rotates_each_prefix_before_exhaustion() -> None:
    from shuabao.lobby_hitch import HitchAction

    med = Mediator(Settings(mode_id="lobby_hitch", hitch_stage_prefix="4,3"), ROOT)
    sm = med._hitch_sm

    assert sm.join_limit == 20
    for refresh in range(10):
        sm.note_refresh(float(refresh))
    assert sm.prefix == "3"
    assert sm.tick(now=14.0, matched=False, prefix_ok=True).action is HitchAction.REFRESH
    for refresh in range(10, 20):
        sm.note_refresh(float(refresh))
    assert sm.prefix == "4"
    assert sm.refresh_cycles_on_prefix == 0


def test_lobby_hitch_recreated_state_machine_preserves_current_prefix_and_limits() -> None:
    med = Mediator(Settings(mode_id="lobby_hitch", hitch_stage_prefix="4,3"), ROOT)
    med._hitch_sm.rotate_prefix()
    med._hitch_sm.search_timeout_s = 321.0
    med._hitch_sm.sleep_s = 45.0

    replacement = med._new_hitch_sm()

    assert replacement.prefix == "3"
    assert replacement.prefix_idx == 1
    assert replacement.join_limit == 20
    assert replacement.search_timeout_s == 321.0
    assert replacement.sleep_s == 45.0


def test_lobby_hitch_after_exit_clears_search_and_row_transients() -> None:
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    med._hitch_search = SearchTransaction(
        prefix="3", opened_at=1.0, typed_at=1.0, confirmed=True,
    )
    med._hitch_pending_row_y = 385
    med._hitch_pending_room_key = "room"
    med._hitch_refresh_required = False
    med._hitch_rejected_row_ys.add(385)

    med._hitch_after_exit(10.0)

    assert med._hitch_search is None
    assert med._hitch_prefix_ok() is False
    assert med._hitch_pending_row_y is None
    assert med._hitch_pending_room_key is None
    assert med._hitch_refresh_required is True
    assert med._hitch_rejected_row_ys == set()


def test_main_line_entry_clears_post_game_active_wait_timestamp() -> None:
    med = Mediator(Settings(), ROOT)
    med._post_game_active_wait_since = 12.0

    med.set_phase(Phase.MAIN_LINE, "new round")

    assert med._post_game_active_wait_since is None


def test_hitch_rotate_interval_is_integer_and_clamped(tmp_path: Path) -> None:
    assert Settings._from_dict({"hitch_rotate_interval": 10}).hitch_rotate_interval == 10
    parsed = Settings._from_dict({"hitch_rotate_interval": "10"})
    assert parsed.hitch_rotate_interval == 10
    assert isinstance(parsed.hitch_rotate_interval, int)
    path = tmp_path / "settings.json"
    parsed.save(path)
    assert Settings.load(path).hitch_rotate_interval == 10
    assert Settings._from_dict({"hitch_rotate_interval": 0}).hitch_rotate_interval == 1
    assert Settings._from_dict({"hitch_rotate_interval": 999}).hitch_rotate_interval == 100
    assert Settings._from_dict({"hitch_rotate_interval": "bad"}).hitch_rotate_interval == 10


def test_lobby_search_continuous_cycle_never_exhausts_to_go_home() -> None:
    from shuabao.lobby_hitch import HitchAction, HitchSearchSM

    sm = HitchSearchSM(continuous=True)
    sm.search_started_at = 0.0
    sm.attempts = sm.join_limit
    sm.next_allowed_at = 20.0

    decision = sm.tick(now=20.0, matched=False, prefix_ok=True)

    assert decision.action is HitchAction.REFRESH
    assert decision.attempts == 0
    assert sm.search_started_at == 20.0


def test_lobby_search_recreated_state_machine_stays_continuous() -> None:
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    med._hitch_sm.continuous = True

    replacement = med._new_hitch_sm()

    assert replacement.continuous is True


def test_until_success_cli_is_explicit_lobby_search_mode() -> None:
    args = live_capture.build_parser().parse_args([
        "probe", "--target", "lobby_search", "--out", "capture-out",
        "--live-input", "--confirm-live-input", "--until-success",
    ])

    assert args.until_success is True

def test_lobby_hitch_does_not_treat_lobby_as_room_waiting() -> None:
    from shuabao.vision.matcher import MatchResult

    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    room_cancel = object()
    search_box = _search_icon_anchor()
    with patch.object(med, "_hitch_ocr_text", return_value=""), \
         patch.object(med, "_lobby_room_list_evidence", return_value=True), \
         patch.object(
             med,
             "find_scene",
             side_effect=lambda _frame, key: (
                 room_cancel if key == "room_cancel_ready"
                 else search_box if key == "lobby_search_icon"
                 else None
             ),
         ), \
         patch.object(med, "act_search_box", return_value=True) as search:
        med._tick_lobby_hitch(_fixture_frame(), "UNKNOWN")
    assert med.phase is not Phase.ROOM_WAITING
    search.assert_called_once()


def test_lobby_hitch_failed_join_does_not_arm_pending_join() -> None:
    from shuabao.lobby_hitch import HitchAction, HitchDecision, HitchPhase
    from shuabao.vision.matcher import MatchResult

    med = Mediator(Settings(mode_id="lobby_hitch", hitch_stage_prefix="4"), ROOT)
    med._hitch_search = SearchTransaction(
        prefix="4", opened_at=0.0, typed_at=0.0, confirmed=True,
    )
    frame = _fixture_frame()
    hit = MatchResult("room_list_row", 1.0, 100, 100, 100, 40, 100, 100)
    decision = HitchDecision(HitchAction.JOIN, HitchPhase.SEARCH, "match", 0, 0.0)
    with patch.object(med, "_hitch_ocr_text", return_value=""), \
         patch.object(med, "_hitch_room_matched", return_value=True), \
         patch.object(med, "_hitch_prefix_ok", return_value=True), \
         patch.object(med._hitch_sm, "tick", return_value=decision), \
         patch.object(med, "_hitch_action_hit", return_value=hit), \
         patch.object(med, "act_double_click", return_value=False):
        med._tick_lobby_hitch(frame, "UNKNOWN")
    assert med._hitch_sm.pending_join is False


def test_lobby_hitch_join_timeout_closes_popup_and_skips_failed_row() -> None:
    med = Mediator(Settings(mode_id="lobby_hitch", hitch_stage_prefix="4"), ROOT)
    med._hitch_search = SearchTransaction(
        prefix="4", opened_at=0.0, typed_at=0.0, confirmed=True,
    )
    med._hitch_pending_row_y = 385
    med._hitch_sm.note_join_click(97.0)
    frame = _fixture_frame()

    with patch("shuabao.mediator.time.time", return_value=100.0), \
         patch.object(med, "_hitch_ocr_text", return_value=""), \
         patch.object(med, "find_scene", return_value=None), \
         patch.object(med, "_hitch_room_controls_visible", return_value=False), \
         patch.object(med, "act_key", return_value=True) as key, \
         patch.object(med, "act_click", return_value=True) as click:
        med._tick_lobby_hitch(frame, "LOBBY_ROOM")

    # 20260908 新契约：无可信已知弹窗 authority 时，join 超时绝不盲 Esc。
    # 只拒绝本次进房并回大厅（零输入）。
    key.assert_not_called()
    click.assert_not_called()
    assert med._hitch_sm.pending_join is False
    assert med._hitch_pending_row_y is None
    assert med._hitch_rejected_row_ys == {385}
    assert med._hitch_refresh_required is True
    assert med._hitch_search_actions == ["reject"]
    assert med._hitch_sm.next_allowed_at == 100.0


def test_lobby_hitch_failed_join_forces_refresh_before_next_room() -> None:
    from shuabao.lobby_hitch import HitchAction

    med = Mediator(Settings(mode_id="lobby_hitch", hitch_stage_prefix="4"), ROOT)
    med._hitch_search = SearchTransaction(
        prefix="4", opened_at=0.0, typed_at=0.0, confirmed=True,
    )
    med._hitch_refresh_required = True
    frame = _fixture_frame()
    refresh_hit = type("Hit", (), {
        "name": "lobby_refresh", "screen_x": 1546, "screen_y": 330,
    })()

    with patch.object(med, "_lobby_room_list_evidence", return_value=True), \
         patch.object(med, "_hitch_action_hit", side_effect=lambda _frame, action: (
             refresh_hit if action is HitchAction.REFRESH else None
         )), \
         patch.object(med, "_hitch_room_matched") as scan, \
         patch.object(med, "act_click", return_value=True) as click, \
         patch.object(med, "act_double_click") as join:
        med._tick_lobby_hitch(frame, "UNKNOWN")

    scan.assert_not_called()
    join.assert_not_called()
    click.assert_called_once_with(refresh_hit, "HitchRefresh")
    assert med._hitch_refresh_required is False


def test_lobby_hitch_never_falls_back_to_quick_join() -> None:
    from shuabao.lobby_hitch import HitchAction

    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    frame = _fixture_frame()
    with patch.object(med, "_find_hitch_joinable_row", return_value=None), \
         patch.object(med, "find_scene") as find_scene:
        find_scene.return_value = None
        assert med._hitch_action_hit(frame, HitchAction.JOIN) is None


def test_lobby_hitch_popup_is_dismissed_before_search_action() -> None:
    """已知 KK 平台提示 shell 才允许中性关闭；拒绝等 fresh 帧证明后才回大厅。"""
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    med._hitch_pending_row_y = 385
    med._hitch_sm.note_join_click(10.0)
    modal_path = ROOT / "tests" / "fixtures" / "gt_kk_platform_modal_kicked_child.png"
    modal_image = cv2.imdecode(np.fromfile(str(modal_path), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert modal_image is not None
    modal_frame = Frame(modal_image, window_title="KK官方对战平台", hwnd=10002, role="l0")
    lobby_frame = Frame(
        np.full((904, 1224, 3), (24, 22, 20), dtype=np.uint8),
        window_title="KK官方对战平台", hwnd=10002, role="l0",
    )
    # 场景锚点：实机被踢提示必须命中共享 shell，否则测试失去意义。
    assert med._kk_platform_modal_shell(modal_frame) is not None
    with (
        patch.object(med, "act_key", return_value=True) as key,
        patch.object(med, "act_click", return_value=True) as click,
    ):
        med._tick_lobby_hitch(modal_frame, "UNKNOWN")
        key.assert_called_once_with("esc", "HitchDismissPlatformModalEsc")
        assert med._hitch_sm.pending_join is True

        med._tick_lobby_hitch(lobby_frame, "UNKNOWN")

    click.assert_not_called()
    assert med._hitch_sm.pending_join is False
    assert "reject" in med._hitch_search_actions
    assert med.phase is Phase.LOBBY_ROOM


def test_lobby_hitch_shared_modal_shell_escs_without_rejecting_row() -> None:
    """共享 KK modal shell 允许中性 Esc，但不读取正文或立即拒绝进房。"""
    med = Mediator(Settings(dry_run=True, mode_id="lobby_hitch"), ROOT)
    med._hitch_pending_row_y = 385
    med._hitch_sm.note_join_click(10.0)
    image = cv2.imdecode(
        np.fromfile(
            str(ROOT / "tests" / "fixtures" / "gt_kk_platform_modal_level_insufficient_overlay.png"),
            dtype=np.uint8,
        ),
        cv2.IMREAD_COLOR,
    )
    assert image is not None
    frame = Frame(image, window_title="KK官方对战平台", hwnd=99, role="l0")
    with (
        patch.object(med, "act_key", return_value=True) as key,
        patch.object(med, "_hitch_room_list_row_count", return_value=3),
        patch.object(med, "find_scene", return_value=None),
    ):
        med._tick_lobby_hitch(frame, "UNKNOWN")
    key.assert_called_once_with("esc", "HitchDismissPlatformModalEsc")
    assert med._hitch_rejected_row_ys == set()
    assert med._hitch_sm.pending_join is True


def test_lobby_search_popup_dismiss_accepts_rejected_row_state_evidence() -> None:
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    frame = _fixture_frame()
    post = live_capture._target_postcondition_snapshot(
        "lobby_search",
        med,
        frame,
        {"hitch_rejected_rows": [385]},
        {"reason": "HitchDismissPopup"},
        {},
        before_frame=frame,
        input_record={"success": True, "status": "SUCCESS"},
    )

    assert post["observed"] is True
    assert post["authoritative"] is False
    assert post["visual_change"]["rejected_rows"] == [385]


def test_lobby_resource_preflight_reports_missing_templates(tmp_path: Path) -> None:
    med = SimpleNamespace(images=tmp_path)
    missing = live_capture._lobby_resource_preflight(med, "lobby_hitch")

    assert len(missing) == 4
    assert len(live_capture._lobby_resource_preflight(med, "lobby_search")) == 3
    assert live_capture._lobby_resource_preflight(med, "black_merchant") == []


def test_lobby_resource_preflight_rejects_blank_templates(tmp_path: Path) -> None:
    lobby = tmp_path / "lobby"
    lobby.mkdir()
    for name in (
        "lobby_search_icon.png",
        "lobby_refresh.png",
        "lobby_room_list_tab.png",
        "lobby_room_list_selected.png",
    ):
        cv2.imwrite(str(lobby / name), np.zeros((24, 32, 3), dtype=np.uint8))

    missing = live_capture._lobby_resource_preflight(SimpleNamespace(images=tmp_path), "lobby_hitch")

    assert len(missing) == 4
    assert all("blank or low-contrast" in item for item in missing)
