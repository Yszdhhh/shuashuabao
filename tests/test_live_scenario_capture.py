"""Offline contract tests for the live-capture adapter.

These tests cover bundle shape and event-driven frame selection only.  They do
not claim a real-machine LIVE PASS; that remains the Natural E2E gate.
"""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
import shutil
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np
import tools.live_scenario_capture as live_capture

from shuabao.input.keyboard_mouse import ActionResult
from shuabao.loop_action import LoopAction
from shuabao.mediator import BUILD_ID, Mediator, Phase
from shuabao.policy.merchant_fsm import MerchantFSM, MerchantPhase
from shuabao.settings import Settings
from shuabao.stop_signal import StopSignal
from shuabao.vision.capture import Frame
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
    _bootstrap_target_probe,
    _build_identity_check,
    _capture_input_guard,
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


def _fixture_frame() -> Frame:
    path = ROOT / "fixtures" / "replay" / "main_line_auto_on.png"
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    return Frame(image, window_title="英雄三国KK", hwnd=10001, role="l1")


def test_live_probe_defaults_to_existing_official_operator_settings() -> None:
    configured = Settings(cjb_boss="54莫阿姆", sgzx_boss="10吞噬者芬鲁斯")
    with patch.object(Settings, "load_official", return_value=configured) as load:
        settings = live_capture._prepare_settings(None, "boss_challenge", live_input=True)
    load.assert_called_once_with()
    assert settings.cjb_boss == "54莫阿姆"
    assert settings.sgzx_boss == "10吞噬者芬鲁斯"
    assert settings.dry_run is False


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
        execution_mode="ground_truth_only",
    )
    recorder.finalize()
    payload = json.loads((tmp_path / "bundle" / "manifest.json").read_text(encoding="utf-8"))
    assert payload["target"] == "heirloom"
    assert payload["production_handler"] is None
    assert payload["execution_mode"] == "ground_truth_only"
    assert payload["production_readiness"] == "BLOCKED"
    assert payload["ground_truth_only"] is True
    assert payload["verification"]["natural_e2e"] == "GROUND_TRUTH_ONLY"
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


def test_all_six_target_contracts_have_a_structural_readiness_result() -> None:
    assert SUPPORTED_TARGETS == (
        "black_merchant",
        "inventory_item",
        "boss_challenge",
        "time_cave",
        "heirloom",
        "secret_realm",
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
    assert by_target["secret_realm"]["production_readiness"] == "CONDITIONAL"
    assert by_target["time_cave"]["production_readiness"] == "BLOCKED"
    assert by_target["heirloom"]["production_readiness"] == "BLOCKED"
    assert by_target["time_cave"]["ground_truth_only"] is True
    assert by_target["heirloom"]["ground_truth_only"] is True
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
    assert med._post_game_pending is True
    assert med._secret_realm_request_pending is True

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
    assert _capture_input_guard("secret_realm", "target_handler")("click", "CloseArchivePanel")
    assert _capture_input_guard("secret_realm", "target_handler")("right_click", "OpenGreatRift") is None
    assert _capture_input_guard("time_cave", "ground_truth_only")("click", "BossConfigured")


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
