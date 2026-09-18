"""Offline GT test-candidate identity. Temp git repos only; no live input."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import shuabao
import tools.gt_test_identity as gt
import tools.live_harness_identity as identity

ROOT = Path(__file__).resolve().parents[1]


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True,
        text=True, encoding="utf-8",
    ).stdout.strip()


def _write(path: Path, text: str = "# x\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _declared_delta_repo(tmp_path: Path, monkeypatch):
    root = tmp_path / "gt"
    package = root / "src" / "shuabao" / "shell"
    package.mkdir(parents=True)
    _write(root / "src" / "shuabao" / "__init__.py")
    _write(root / "src" / "shuabao" / "mediator.py")
    _write(root / "src" / "shuabao" / "runtime_mediator.py")
    _write(root / "src" / "shuabao" / "vision" / "capture.py")
    _write(root / "src" / "shuabao" / "shell" / "live_execute.py")
    _write(root / "src" / "shuabao" / "shell" / "dashboard_facade.py")
    _write(root / "tools" / "live_harness_identity.py")
    _write(root / "config" / "runtime_identity_manifest.json", "{}")
    _git(root, "init")
    _git(root, "add", ".")
    _git(root, "-c", "user.name=Identity Test", "-c", "user.email=identity@example.invalid", "commit", "-m", "production")
    parent = _git(root, "rev-parse", "HEAD")
    for rel in sorted(gt.DECLARED_TEST_ONLY_DELTA):
        _write(root / rel, f"# declared {rel}\n")
    _git(root, "add", ".")
    _git(root, "-c", "user.name=Identity Test", "-c", "user.email=identity@example.invalid", "commit", "-m", "test-only")
    monkeypatch.setattr(gt, "PRODUCTION_SHA", parent)
    monkeypatch.setattr(shuabao, "__file__", str(root / "src" / "shuabao" / "__init__.py"))
    monkeypatch.setattr(sys, "path", [str(root / "src"), *sys.path])
    return root, parent, _git(root, "rev-parse", "HEAD")


def test_production_fixture_identity_ready(tmp_path, monkeypatch):
    root = tmp_path / "candidate"
    package = root / "src" / "shuabao"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("# offline candidate\n", encoding="utf-8")
    _git(root, "init")
    _git(root, "add", ".")
    _git(root, "-c", "user.name=Identity Test", "-c", "user.email=identity@example.invalid", "commit", "-m", "candidate")
    anchor = _git(root, "rev-parse", "HEAD")
    (root / "config").mkdir()
    (root / identity.IDENTITY_MANIFEST_PATH).write_text(json.dumps({
        "schema_version": 1, "candidate_sha": anchor,
        "anchored_at": "2026-09-17T00:00:00+00:00",
        "branch": "candidate",
        "note": "Offline accepted candidate fixture",
    }), encoding="utf-8")
    monkeypatch.delenv("SHUABAO_CANDIDATE_SHA", raising=False)
    monkeypatch.setattr(shuabao, "__file__", str(package / "__init__.py"))
    report = identity.identity_report(repo_root=root)
    assert report["ready_for_gt"] is True, report
    assert report["production_code_diff"] == "CLEAN"


def test_real_root_production_not_clean_and_test_candidate(monkeypatch):
    monkeypatch.delenv("SHUABAO_CANDIDATE_SHA", raising=False)
    prod = identity.identity_report(repo_root=ROOT)
    assert prod["production_code_diff"] == "NOT_CLEAN"
    assert any(str(path).startswith("src/shuabao/") for path in prod["production_code_diff_files"])
    head = _git(ROOT, "rev-parse", "HEAD")
    report = gt.evaluate_test_candidate(ROOT)
    assert report["production_sha"] == gt.PRODUCTION_SHA
    assert report["test_sha"] == head
    assert report["production_is_ancestor"] is True
    imported = Path(report["imported_shuabao"]).resolve()
    expected_pkg = (ROOT / "src" / "shuabao").resolve()
    assert imported == expected_pkg / "__init__.py" or expected_pkg in imported.parents
    assert report["src_clean"] is True
    assert report["config_clean"] is True
    assert report["tools_clean"] is True
    assert report["code_paths_clean"] is True
    delta_paths = {item["path"] for item in report["TEST_ONLY_DELTA"]}
    assert delta_paths == set(gt.DECLARED_TEST_ONLY_DELTA)
    assert report["status"] == "READY", report["blocked_reasons"]


def test_wrong_production_sha_blocked(tmp_path, monkeypatch):
    root, _parent, _head = _declared_delta_repo(tmp_path, monkeypatch)
    report = gt.evaluate_test_candidate(root, production_sha="0" * 40)
    assert report["status"] == "BLOCKED"
    assert any("wrong production SHA" in reason for reason in report["blocked_reasons"])


def test_production_not_ancestor_blocked(tmp_path, monkeypatch):
    root, _parent, _head = _declared_delta_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(gt, "PRODUCTION_SHA", "b52c69e2aa1f74b59506439cceba06535bc6234c")
    report = gt.evaluate_test_candidate(root)
    assert report["status"] == "BLOCKED"
    assert report["production_is_ancestor"] is False
    assert any("not an ancestor" in reason for reason in report["blocked_reasons"])


def test_wrong_test_sha_blocked(tmp_path, monkeypatch):
    root, _parent, _head = _declared_delta_repo(tmp_path, monkeypatch)
    report = gt.evaluate_test_candidate(root, expected_test_sha="f" * 40)
    assert report["status"] == "BLOCKED"
    assert any("wrong Test SHA" in reason for reason in report["blocked_reasons"])


def test_dirty_src_blocked(tmp_path, monkeypatch):
    root, _parent, _head = _declared_delta_repo(tmp_path, monkeypatch)
    (root / "src" / "shuabao" / "choice_policy.py").write_text("# dirty\n", encoding="utf-8")
    report = gt.evaluate_test_candidate(root)
    assert report["status"] == "BLOCKED"
    assert any("dirty src" in reason for reason in report["blocked_reasons"])


@pytest.mark.parametrize(
    ("relative", "reason"),
    [
        ("src/shuabao/choice_policy.py", "dirty src"),
        ("config/dashboard_test_profiles.json", "dirty config"),
        ("tools/gt_test_identity.py", "dirty tools"),
    ],
)
def test_dirty_code_path_roots_block_candidate(tmp_path, monkeypatch, relative, reason):
    root, _parent, _head = _declared_delta_repo(tmp_path, monkeypatch)
    path = root / relative
    path.write_text(path.read_text(encoding="utf-8") + "# dirty\n", encoding="utf-8")

    report = gt.evaluate_test_candidate(root)

    assert report["status"] == "BLOCKED", report
    assert report["ready"] is False
    assert report["code_paths_clean"] is False
    assert reason in report["blocked_reasons"]


@pytest.mark.parametrize("relative", ["src/untracked.py", "config/untracked.json", "tools/untracked.py"])
def test_untracked_code_path_roots_block_candidate(tmp_path, monkeypatch, relative):
    root, _parent, _head = _declared_delta_repo(tmp_path, monkeypatch)
    _write(root / relative)

    report = gt.evaluate_test_candidate(root)

    assert report["status"] == "BLOCKED", report
    assert report["ready"] is False
    assert report["code_paths_clean"] is False
    assert any(reason in report["blocked_reasons"] for reason in ("dirty src", "dirty config", "dirty tools"))


def test_undeclared_src_file_blocked(tmp_path, monkeypatch):
    root, _parent, _head = _declared_delta_repo(tmp_path, monkeypatch)
    (root / "src" / "shuabao" / "zz_undeclared.py").write_text("# extra\n", encoding="utf-8")
    report = gt.evaluate_test_candidate(root)
    assert report["status"] == "BLOCKED"
    assert any("undeclared new src/shuabao file" in reason for reason in report["blocked_reasons"])


def test_wrong_imported_package_blocked(tmp_path, monkeypatch):
    root, _parent, _head = _declared_delta_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(shuabao, "__file__", str(tmp_path / "old" / "shuabao" / "__init__.py"))
    report = gt.evaluate_test_candidate(root)
    assert report["status"] == "BLOCKED"
    assert any("imported shuabao" in reason for reason in report["blocked_reasons"])


def test_missing_operator_and_ocr_cannot_start(tmp_path, monkeypatch):
    root, _parent, _head = _declared_delta_repo(tmp_path, monkeypatch)
    evidence = gt.build_session_evidence(
        repo_root=root,
        python_executable=sys.executable,
        settings_path=tmp_path / "missing-settings.json",
        operator_settings_source=tmp_path / "missing-operator.json",
        profile_name="海盗+亡灵机制GT",
        profile_config_path=root / "config" / "dashboard_test_profiles.json",
        ocr_python=None,
        ocr_model_dir=None,
    )
    assert evidence["cannot_start_gt"] is True
    assert evidence["status"] == "BLOCKED"
    joined = " ".join(evidence["blocked_reasons"])
    assert "operator settings source missing" in joined
    assert "missing OCR evidence" in joined
