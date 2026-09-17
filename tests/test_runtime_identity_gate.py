"""Offline identity boundaries: temporary git worktrees, never real input."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
import shuabao
import tools.live_harness_identity as identity
from shuabao.settings import Settings
from shuabao.shell import live_execute
from shuabao.stop_signal import StopSignal
from shuabao.subscription_permit import DevStartCapability


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True,
        text=True, encoding="utf-8",
    ).stdout.strip()


@pytest.fixture
def candidate_repo(tmp_path, monkeypatch):
    root = tmp_path / "candidate"
    package = root / "src" / "shuabao"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("# offline candidate\n", encoding="utf-8")
    (root / "desktop_app.py").write_text("# source entry\n", encoding="utf-8")
    _git(root, "init")
    _git(root, "add", ".")
    _git(root, "-c", "user.name=Identity Test", "-c", "user.email=identity@example.invalid", "commit", "-m", "candidate")
    anchor = _git(root, "rev-parse", "HEAD")
    (root / "config").mkdir()
    (root / identity.IDENTITY_MANIFEST_PATH).write_text(json.dumps({
        "schema_version": 1, "candidate_sha": anchor,
        "anchored_at": "2026-09-17T00:00:00+00:00",
        "branch": _git(root, "branch", "--show-current"),
        "note": "Offline accepted candidate fixture",
    }), encoding="utf-8")
    monkeypatch.delenv("SHUABAO_CANDIDATE_SHA", raising=False)
    monkeypatch.delenv("SHUABAO_PRODUCTION_SOURCE_ROOT", raising=False)
    monkeypatch.delenv("SHUABAO_PRODUCTION_SOURCE_SHA", raising=False)
    monkeypatch.setattr(sys, "path", sys.path.copy())
    monkeypatch.setattr(shuabao, "__file__", str(package / "__init__.py"))
    return root, anchor


def test_candidate_identity_passes(candidate_repo):
    root, anchor = candidate_repo
    report = live_execute.runtime_identity_preflight(root)
    assert report["ready_for_gt"] is True, report
    assert report["harness_head"] == report["candidate_anchor_sha"] == anchor
    assert report["runtime_source_verified"] is True
    assert report["python_executable"] == sys.executable


def test_wrong_root_blocks(candidate_repo, tmp_path):
    report = live_execute.runtime_identity_preflight(tmp_path / "missing")
    assert report["ready_for_gt"] is False
    assert "Harness HEAD SHA unavailable" in report["blocked_reasons"]


def test_wrong_imported_package_blocks(candidate_repo, monkeypatch):
    root, _ = candidate_repo
    monkeypatch.setattr(identity, "runtime_source_path", lambda _root: {
        "ok": False, "path": str(root.parent / "old" / "shuabao" / "__init__.py"),
        "reason": "imported shuabao is outside the candidate root",
    })
    report = live_execute.runtime_identity_preflight(root)
    assert report["ready_for_gt"] is False
    assert any("imported shuabao" in reason for reason in report["blocked_reasons"])


def test_wrong_sha_override_blocks(candidate_repo, monkeypatch):
    root, _ = candidate_repo
    monkeypatch.setenv("SHUABAO_CANDIDATE_SHA", "f" * 40)
    report = live_execute.runtime_identity_preflight(root)
    assert report["candidate_anchor_sha"] == "f" * 40
    assert report["ready_for_gt"] is False
    assert any("not the candidate anchor" in reason for reason in report["blocked_reasons"])


def test_dirty_source_blocks_even_at_candidate_head(candidate_repo):
    root, anchor = candidate_repo
    (root / "src" / "shuabao" / "__init__.py").write_text("# dirty source\n", encoding="utf-8")
    report = live_execute.runtime_identity_preflight(root)
    assert report["harness_head"] == anchor
    assert report["ready_for_gt"] is False
    assert "src/shuabao/__init__.py" in report["production_code_diff_files"]


def test_identity_failure_precedes_permission_and_mediator(candidate_repo, monkeypatch, tmp_path):
    root, _ = candidate_repo
    monkeypatch.setenv("SHUABAO_CANDIDATE_SHA", "f" * 40)
    monkeypatch.setenv("SHUABAO_SUBSCRIPTION_MODE", "off")
    constructed = []
    fake = ModuleType("shuabao.runtime_mediator")
    fake.Mediator = lambda *_args, **_kwargs: constructed.append(True)
    monkeypatch.setitem(sys.modules, "shuabao.runtime_mediator", fake)

    def unexpected_permission(*_args, **_kwargs):
        pytest.fail("identity must reject before checking permission")

    monkeypatch.setattr(live_execute, "start_permission_allows", unexpected_permission)
    result = live_execute.execute_runtime_mediator(
        settings=Settings(dry_run=True, ocr_mode="off"), root_dir=root,
        incident_dir=tmp_path / "incidents", stop_signal=StopSignal(),
        permission=DevStartCapability.for_off(),
    )
    assert result["phase"] == "ERROR"
    assert result["terminal_reason"].startswith("BLOCKED_PRECONDITION: identity")
    assert result["mediator"] is None
    assert constructed == []
    assert not (tmp_path / "incidents" / "live.log").exists()


def test_failed_bundle_preserves_identity_and_window(candidate_repo, tmp_path, monkeypatch):
    from tools.live_scenario_capture import BundleRecorder

    root, anchor = candidate_repo
    monkeypatch.setenv("SHUABAO_CANDIDATE_SHA", "f" * 40)
    report = live_execute.runtime_identity_preflight(root)
    recorder = BundleRecorder(
        tmp_path / "bundle", repo_root=root, target="hero_evolve",
        settings=Settings(dry_run=True, ocr_mode="off"), initial_phase="MAIN_LINE",
        execution_mode="target_handler",
    )
    window = {"hwnd": None, "title": None, "rect": None, "role": None}
    recorder.record_preflight({
        "status": "BLOCKED_PRECONDITION", "blocked_reasons": report["blocked_reasons"],
        "identity": report, "window": window,
    })
    payload = json.loads(recorder.finalize().read_text(encoding="utf-8"))
    assert payload["final_status"] == "BLOCKED_PRECONDITION"
    assert payload["harness_identity"]["sha"] == anchor
    assert payload["harness_base_sha"] == "f" * 40
    assert payload["window"] == window
    assert payload["live_preflight"]["identity"]["ready_for_gt"] is False


def test_dashboard_uses_imported_runtime_identity(candidate_repo, monkeypatch, tmp_path):
    from shuabao.shell import dashboard_facade as facade
    from shuabao.shell.runner_service import RunnerService

    root, anchor = candidate_repo
    metadata = facade._build_identity_metadata(root)
    assert metadata["source_sha"] == metadata["imported_runtime_sha"] == anchor
    assert metadata["candidate_anchor_sha"] == identity.load_identity_manifest(root)["candidate_sha"]
    runner = RunnerService(tmp_path / "appdata", root)
    ok, detail = facade._build_identity_preflight(root, runner)
    assert ok, detail
    monkeypatch.setenv("SHUABAO_CANDIDATE_SHA", "f" * 40)
    ok, detail = facade._build_identity_preflight(root, runner)
    assert not ok
    assert "BLOCKED_PRECONDITION: identity" in detail
    assert "not the candidate anchor" in detail


def test_clean_descendant_passes_but_changed_source_blocks(candidate_repo):
    root, anchor = candidate_repo
    _git(root, "add", "config")
    _git(root, "-c", "user.name=Identity Test", "-c", "user.email=identity@example.invalid", "commit", "-m", "anchor metadata")
    report = live_execute.runtime_identity_preflight(root)
    assert report["harness_head"] != anchor
    assert report["ready_for_gt"] is True, report
    (root / "src" / "shuabao" / "__init__.py").write_text("# changed candidate\n", encoding="utf-8")
    _git(root, "add", "src")
    _git(root, "-c", "user.name=Identity Test", "-c", "user.email=identity@example.invalid", "commit", "-m", "changed source")
    report = live_execute.runtime_identity_preflight(root)
    assert report["ready_for_gt"] is False
    assert report["production_code_diff_files"] == ["src/shuabao/__init__.py"]


def test_missing_or_invalid_manifest_blocks(candidate_repo):
    root, _ = candidate_repo
    manifest_path = root / identity.IDENTITY_MANIFEST_PATH
    manifest_path.unlink()
    assert live_execute.runtime_identity_preflight(root)["ready_for_gt"] is False
    manifest_path.write_text('{"schema_version": 1, "candidate_sha": "HEAD"}', encoding="utf-8")
    report = live_execute.runtime_identity_preflight(root)
    assert report["ready_for_gt"] is False
    assert any("candidate anchor unavailable" in path for path in report["production_code_diff_files"])
