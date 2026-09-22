"""SHUABAO_SOURCE_QUICK_TEST: source-only relaxed identity, never GT, never frozen."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
import tools.live_harness_identity as identity
from shuabao.settings import Settings
from shuabao.shell import live_execute
from shuabao.stop_signal import StopSignal
from shuabao.subscription_permit import DevStartCapability
from tests.test_runtime_identity_gate import _git, candidate_repo  # noqa: F401  (fixture)


def _commit_changed_source(root: Path) -> None:
    (root / "src" / "shuabao" / "__init__.py").write_text("# changed after candidate\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "-c", "user.name=Identity Test", "-c", "user.email=identity@example.invalid",
         "commit", "-m", "post-candidate source change")


def test_profile_off_keeps_gt_gate(candidate_repo, monkeypatch):
    root, _ = candidate_repo
    monkeypatch.delenv(live_execute.SOURCE_QUICK_TEST_ENV, raising=False)
    _commit_changed_source(root)
    report = live_execute.runtime_identity_preflight(root)
    assert report["ready_for_gt"] is False
    assert "evidence_class" not in report
    assert "ready_for_source_test" not in report
    assert live_execute.identity_allows_live(report) is False


def test_profile_allows_head_plus_dirty_without_rewriting_gt(candidate_repo, monkeypatch):
    root, anchor = candidate_repo
    monkeypatch.setenv(live_execute.SOURCE_QUICK_TEST_ENV, "1")
    _commit_changed_source(root)
    (root / "src" / "shuabao" / "__init__.py").write_text("# unstaged\n", encoding="utf-8")
    (root / "staged.txt").write_text("staged\n", encoding="utf-8")
    _git(root, "add", "staged.txt")
    (root / "untracked.txt").write_text("untracked\n", encoding="utf-8")
    report = live_execute.runtime_identity_preflight(root)
    assert report["ready_for_gt"] is False  # GT verdict is never rewritten
    assert report["ready_for_source_test"] is True, report
    assert report["evidence_class"] == "SOURCE_QUICK_TEST"
    assert report["worktree_dirty"] is True
    assert {"src/shuabao/__init__.py", "staged.txt", "untracked.txt"} <= set(report["worktree_dirty_files"])
    assert any("production code diff" in item for item in report["advisories"])
    assert report["source_test_blocked_reasons"] == []
    assert live_execute.identity_allows_live(report) is True
    line = live_execute.identity_evidence_line(report)
    assert "evidence_class=SOURCE_QUICK_TEST" in line and "ready_for_gt=False" in line
    assert report["harness_head"] != anchor


def test_profile_non_descendant_is_advisory(candidate_repo, monkeypatch):
    root, _ = candidate_repo
    monkeypatch.setenv(live_execute.SOURCE_QUICK_TEST_ENV, "1")
    monkeypatch.setenv("SHUABAO_CANDIDATE_SHA", "f" * 40)
    report = live_execute.runtime_identity_preflight(root)
    assert report["ready_for_gt"] is False
    assert report["ready_for_source_test"] is True, report
    assert any("not the candidate anchor" in item for item in report["advisories"])


def test_profile_still_blocks_wrong_import_and_forbidden_head(candidate_repo, monkeypatch):
    root, _ = candidate_repo
    monkeypatch.setenv(live_execute.SOURCE_QUICK_TEST_ENV, "1")
    monkeypatch.setattr(identity, "runtime_source_path", lambda _root: {
        "ok": False, "path": str(root.parent / "old" / "shuabao" / "__init__.py"),
        "reason": "imported shuabao is outside the candidate root",
    })
    report = live_execute.runtime_identity_preflight(root)
    assert report["ready_for_source_test"] is False
    assert live_execute.identity_allows_live(report) is False
    assert live_execute.identity_block_reasons(report)

    monkeypatch.undo()
    monkeypatch.setenv(live_execute.SOURCE_QUICK_TEST_ENV, "1")
    head = _git(root, "rev-parse", "HEAD")
    monkeypatch.setattr(identity, "FORBIDDEN_RUNTIME_SHAS", (head,))
    report = live_execute.runtime_identity_preflight(root)
    assert report["ready_for_source_test"] is False
    assert any("forbidden old runtime" in r for r in report["source_test_blocked_reasons"])


def test_profile_blocks_unresolvable_head(tmp_path, monkeypatch):
    monkeypatch.setenv(live_execute.SOURCE_QUICK_TEST_ENV, "1")
    report = live_execute.runtime_identity_preflight(tmp_path / "missing")
    assert live_execute.identity_allows_live(report) is False


def test_forged_report_without_profile_is_rejected(monkeypatch):
    monkeypatch.delenv(live_execute.SOURCE_QUICK_TEST_ENV, raising=False)
    forged = {"evidence_class": "SOURCE_QUICK_TEST", "ready_for_source_test": True, "ready_for_gt": False}
    assert live_execute.identity_allows_live(forged) is False


@pytest.mark.parametrize("value", ["", "0", "true", "yes", " 2 "])
def test_only_exact_one_enables(value):
    assert live_execute.source_quick_test_enabled({"SHUABAO_SOURCE_QUICK_TEST": value}) is False
    assert live_execute.source_quick_test_enabled({"SHUABAO_SOURCE_QUICK_TEST": "1"}) is True


def test_frozen_ignores_profile_completely(tmp_path, monkeypatch):
    monkeypatch.setenv(live_execute.SOURCE_QUICK_TEST_ENV, "1")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert live_execute.source_quick_test_enabled() is False
    monkeypatch.setattr(live_execute, "_live_identity", lambda _root: live_execute._LiveIdentity("", "", "", True))
    report = live_execute.runtime_identity_preflight(tmp_path)
    assert report["ready_for_gt"] is False
    assert "evidence_class" not in report and "ready_for_source_test" not in report
    forged = {"evidence_class": "SOURCE_QUICK_TEST", "ready_for_source_test": True, "ready_for_gt": False}
    assert live_execute.identity_allows_live(forged) is False


def test_quick_test_logs_evidence_class_before_mediator(candidate_repo, monkeypatch, tmp_path):
    root, _ = candidate_repo
    monkeypatch.setenv(live_execute.SOURCE_QUICK_TEST_ENV, "1")
    monkeypatch.setenv("SHUABAO_SUBSCRIPTION_MODE", "off")
    _commit_changed_source(root)
    fake = ModuleType("shuabao.runtime_mediator")

    class _NoInputMediator:
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError("offline test: no mediator, no input")

    fake.Mediator = _NoInputMediator
    monkeypatch.setitem(sys.modules, "shuabao.runtime_mediator", fake)
    monkeypatch.setattr(live_execute, "start_permission_allows", lambda *_a, **_k: True)
    incidents = tmp_path / "incidents"
    result = live_execute.execute_runtime_mediator(
        settings=Settings(dry_run=True, ocr_mode="off"), root_dir=root,
        incident_dir=incidents, stop_signal=StopSignal(),
        permission=DevStartCapability.for_off(),
    )
    assert not result["terminal_reason"].startswith("BLOCKED_PRECONDITION")
    assert result["identity"]["evidence_class"] == "SOURCE_QUICK_TEST"
    evidence = json.loads((incidents / "source_quick_test_identity.json").read_text(encoding="utf-8"))
    assert evidence["evidence_class"] == "SOURCE_QUICK_TEST"
    assert evidence["ready_for_gt"] is False
    assert evidence["harness_head"] == _git(root, "rev-parse", "HEAD")
    assert "evidence_class=SOURCE_QUICK_TEST" in (incidents / "live.log").read_text(encoding="utf-8")


def test_dashboard_preflight_uses_same_helper(candidate_repo, monkeypatch, tmp_path):
    from shuabao.shell import dashboard_facade as facade
    from shuabao.shell.runner_service import RunnerService

    root, _ = candidate_repo
    _commit_changed_source(root)
    runner = RunnerService(tmp_path / "appdata", root)
    monkeypatch.delenv(live_execute.SOURCE_QUICK_TEST_ENV, raising=False)
    ok, detail = facade._build_identity_preflight(root, runner)
    assert not ok and "BLOCKED_PRECONDITION: identity" in detail
    monkeypatch.setenv(live_execute.SOURCE_QUICK_TEST_ENV, "1")
    ok, detail = facade._build_identity_preflight(root, runner)
    assert ok, detail
    assert "SOURCE_QUICK_TEST" in detail and "非 GT" in detail


def test_window_title_self_identifies_only_in_source_profile(monkeypatch):
    monkeypatch.delenv(live_execute.SOURCE_QUICK_TEST_ENV, raising=False)
    assert live_execute.source_quick_test_window_title("刷刷宝") == "刷刷宝"
    monkeypatch.setenv(live_execute.SOURCE_QUICK_TEST_ENV, "1")
    assert live_execute.source_quick_test_window_title("刷刷宝") == "刷刷宝 · 源码快速测试 · 不做卡密验收"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert live_execute.source_quick_test_window_title("刷刷宝") == "刷刷宝"


def test_web_shell_uses_title_helper():
    source = (Path(__file__).resolve().parents[1] / "src" / "shuabao" / "shell" / "web_config_shell.py").read_text(
        encoding="utf-8")
    assert "self.setWindowTitle(source_quick_test_window_title(APP_TITLE))" in source


def test_quick_test_script_contract():
    raw = (Path(__file__).resolve().parents[1] / "tools" / "quick_test.ps1").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "Windows PowerShell 5.1 needs a UTF-8 BOM for the Chinese text"
    text = raw.decode("utf-8-sig")
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    # env is only set after the RunAs relaunch (env vars do not cross elevation)
    relaunch = code.index("-Verb RunAs")
    for assignment in ("$env:SHUABAO_SOURCE_QUICK_TEST = \"1\"", "$env:SHUABAO_APP_DATA =",
                       "$env:SHUABAO_LIVE_LOCK_DIR =", "$env:SHUABAO_SUBSCRIPTION_MODE = \"off\""):
        assert code.index(assignment) > relaunch, assignment
    assert 'Join-Path $env:LOCALAPPDATA "ShuaBao-dev"' in code
    assert 'Join-Path $env:LOCALAPPDATA "ShuaBao"' in code
    for pattern in ('"SHUABAO_SUBSCRIPTION_*"', '"SHUABAO_*LICENSE*"', '"SHUABAO_CANDIDATE_SHA"'):
        assert pattern in code
    assert code.index("Remove-Item -LiteralPath \"Env:$name\"") < code.index("$env:SHUABAO_SUBSCRIPTION_MODE = \"off\"")
    assert "源码快速测试 · 不做卡密验收" in code
    assert "run_desktop_dev.ps1" in code and "$code -ne 0" in code
    lowered = code.lower()
    for forbidden in ("git pull", "git checkout", "git switch", "git reset", "git fetch", "ui-v2\\dist\\index.html"):
        assert forbidden not in lowered, forbidden
