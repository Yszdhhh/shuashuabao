"""Offline contracts for the primary Tier-0 Lobby natural-E2E lane.

These tests verify routing, candidate-source identity, and evidence contracts
only.  They never claim a real KK LIVE PASS and never fabricate recognition
matches or production postconditions.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from tools.live_scenario_capture import (
    PRIMARY_LIVE_SCENARIO,
    PRIMARY_LIVE_TARGET,
    PRODUCTION_TEST_CANDIDATE_SHA,
    TARGET_CONTRACTS,
    TARGET_PRODUCTION_FACTS,
    TIER0_LOBBY_TARGETS,
    HitchLobbyChainObserver,
)


ROOT = Path(__file__).resolve().parents[1]
_LOCAL_CANDIDATE = Path(r"G:\刷刷宝\Worktrees\lobby-hitch-surface-test")
CANDIDATE_ROOT = _LOCAL_CANDIDATE if _LOCAL_CANDIDATE.is_dir() else ROOT
_UTF8_ENV = dict(os.environ, PYTHONIOENCODING="utf-8")


def _candidate_sha() -> str:
    return subprocess.check_output(
        ["git", "-C", str(CANDIDATE_ROOT), "rev-parse", "HEAD"],
        text=True,
        encoding="utf-8",
        errors="replace",
    ).strip()


def test_primary_lane_is_the_full_chain_not_the_s01_to_s06_diagnostics() -> None:
    assert PRIMARY_LIVE_SCENARIO == "HITCH_FULL_NATURAL_E2E"
    assert PRIMARY_LIVE_TARGET == "hitch_lobby_chain"
    assert PRIMARY_LIVE_TARGET not in TIER0_LOBBY_TARGETS
    assert len(TIER0_LOBBY_TARGETS) == 6

    contract = TARGET_CONTRACTS[PRIMARY_LIVE_TARGET]
    assert "Mediator.tick()" in contract["production_entry"]
    assert "至少 3 个完整 hitch round" in contract["success_postcondition"]
    assert "公共背包" in contract["success_postcondition"]
    assert contract["expected_steps"][:4] == (
        "ROOM_LIST", "SEARCH_CONFIRMED", "JOIN", "MODAL_RECOVERY",
    )
    assert contract["expected_steps"][-3:] == (
        "REAL_EXIT", "LOBBY_RETURN", "NEXT_ROUND",
    )


def test_primary_ledger_exposes_required_metrics_and_does_not_pass_empty() -> None:
    observer = HitchLobbyChainObserver()
    required_metrics = {
        "rounds_started",
        "rooms_joined",
        "ready_confirmed",
        "pressure_confirmed",
        "pressure_core_failure",
        "modals_dismissed",
        "merchant_devour_acquired",
        "talisman_acquired",
        "public_bag_deposit_attempts",
        "public_bag_deposit_confirmed",
        "public_bag_deposit_failed",
        "victory_count",
        "failure_count",
        "lobby_returns",
        "longest_stall_s",
        "silent_stop_count",
        "manual_intervention_count",
    }
    assert required_metrics <= set(observer.metrics)
    assert observer.is_pass is False

    observer.precheck(False, {"status": "BLOCKED_PRECHECK", "reason": "no KK window"})
    payload = observer.payload()
    assert payload["natural_e2e"] == "BLOCKED"
    assert payload["metrics"] == observer.metrics
    assert observer.is_pass is False


def test_candidate_source_identity_is_explicit_and_clean() -> None:
    candidate_sha = _candidate_sha()
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "live_scenario_capture.py"),
            "identity",
            "--repo-root",
            str(ROOT),
            "--production-source-root",
            str(CANDIDATE_ROOT),
            "--production-source-sha",
            candidate_sha,
            "--json",
        ],
        cwd=ROOT,
        env=_UTF8_ENV,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    report = json.loads(completed.stdout)

    assert report["production_source_sha"] == candidate_sha
    assert report["runtime_worktree_sha"] == candidate_sha
    assert report["production_source_clean"] is True
    assert report["candidate_source_injection"] == "ACTIVE"
    assert report["runtime_source_verified"] is True
    assert str(CANDIDATE_ROOT).lower() in str(report["runtime_source_path"]).lower()
    assert report["ready_for_gt"] is True


def test_identity_blocks_when_production_source_sha_missing() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "live_scenario_capture.py"),
            "identity",
            "--repo-root",
            str(ROOT),
            "--production-source-root",
            str(CANDIDATE_ROOT),
            "--json",
        ],
        cwd=ROOT,
        env=_UTF8_ENV,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert completed.returncode == 1
    report = json.loads(completed.stdout)
    assert report["ready_for_gt"] is False
    assert any("production candidate SHA is not specified" in r for r in report["blocked_reasons"])


def test_readiness_keeps_public_backpack_blocked_until_production_gt() -> None:
    candidate_sha = _candidate_sha()
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "live_scenario_capture.py"),
            "readiness",
            "--repo-root",
            str(ROOT),
            "--production-source-root",
            str(CANDIDATE_ROOT),
            "--production-source-sha",
            candidate_sha,
            "--quick",
            "--json",
        ],
        cwd=ROOT,
        env=_UTF8_ENV,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    report = json.loads(completed.stdout)
    by_target = {item["target"]: item for item in report["targets"]}
    public = by_target["public_backpack_deposit"]

    assert report["primary_live_scenario"] == PRIMARY_LIVE_SCENARIO
    assert report["production_source_sha"] == candidate_sha
    assert public["production_entry_status"] == "MISSING"
    assert public["production_readiness"] == "BLOCKED"
    assert public["production_missing"] == [
        "production entry unavailable: _maybe_public_backpack_deposit",
    ]
    assert TARGET_PRODUCTION_FACTS["public_backpack_deposit"]["production_readiness"] == "CONDITIONAL"


def test_public_backpack_contract_is_stash_then_public_then_close() -> None:
    contract = TARGET_CONTRACTS["public_backpack_deposit"]
    fact = TARGET_PRODUCTION_FACTS["public_backpack_deposit"]

    assert contract["handler"] == "_maybe_public_backpack_deposit"
    assert "ITEM_BAR_STASH" in contract["expected_steps"]
    assert "PUBLIC_DEPOSIT" in contract["expected_steps"]
    assert "BAG_CLOSE" in contract["expected_steps"]
    assert "物品栏" in contract["start_condition"]
    assert fact["production_readiness"] == "CONDITIONAL"


def test_capture_observes_every_tick_even_when_no_event_frame_is_saved() -> None:
    source = (ROOT / "tools" / "live_scenario_capture.py").read_text(encoding="utf-8")
    start = source.index("        if not should_save:")
    end = source.index("        before_id =", start)
    no_event_path = source[start:end]
    assert "self.solo_observer.observe(" in no_event_path
    assert "after_frame or before_frame" in no_event_path


def test_harness_and_launcher_do_not_contain_a_second_lobby_fsm() -> None:
    source = (ROOT / "tools" / "live_scenario_capture.py").read_text(encoding="utf-8")
    launcher = (ROOT / "live_scenario_launcher.ps1").read_text(encoding="utf-8")
    assert "class HitchSearchFSM" not in source
    assert "def search_rooms" not in source
    assert "HITCH_FULL_NATURAL_E2E" in source
    assert "HITCH_FULL_NATURAL_E2E" in launcher
    assert "ProductionSourceSha" in launcher
    assert "production-source-root" in launcher
    assert "public_backpack_deposit" in launcher
    assert "Mediator.tick()" in source

