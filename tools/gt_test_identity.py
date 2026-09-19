#!/usr/bin/env python3
"""Narrow Test-candidate identity/evidence adapter. No FSM, Mediator, or input."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

PRODUCTION_BRANCH = "fix/solo-live-regression-20260915"
PRODUCTION_SHA = "b52c69e2aa1f74b59506439cceba06535bc6234c"
TEST_BRANCH_NAME = "test/pirate-necromancy-gt-20260917"

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

DECLARED_TEST_ONLY_DELTA = frozenset({
    "config/bond_stack_catalog.json",
    "config/choice_lexicon.json",
    "config/choice_policy.json",
    "config/dashboard_test_profiles.json",
    "config/fetter_labels.json",
    "config/game_mechanics_kb.json",
    "config/runtime_asset_manifest.json",
    "src/shuabao/bond_capacity.py",
    "src/shuabao/choice_policy.py",
    "src/shuabao/mediator.py",
    "src/shuabao/settings.py",
    "src/shuabao/shell/main_window.py",
    "src/shuabao/shell/test_profiles.py",
    "src/shuabao/vision/ocr_shadow/worker.py",
    "tools/check_pirate_necromancy_profile.py",
    "tools/gt_test_identity.py",
    "tools/live_scenario_capture.py",
    "tools/manual_gt_capture.py",
    "tools/one_click_test.ps1",
    "tools/test_dashboard.py",
})

PRODUCTION_CRITICAL_PATHS = (
    "tools/live_harness_identity.py",
    "config/runtime_identity_manifest.json",
    "src/shuabao/shell/live_execute.py",
    "src/shuabao/shell/dashboard_facade.py",
    "src/shuabao/runtime_mediator.py",
    "src/shuabao/vision/capture.py",
)

_CODE_PATHSPECS = ("src", "config", "tools")
_STABLE_DIFF = (
    "-c", "core.quotepath=false", "diff",
    "--no-ext-diff", "--no-color", "--no-textconv",
    "--src-prefix=a/", "--dst-prefix=b/",
)
_IGNORED_TOP = ("captures/", "docs/")


def _git(repo_root: Path, *args: str) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return 1, "", str(exc)
    return result.returncode, result.stdout.rstrip("\r\n"), result.stderr.strip()


def _git_bytes(repo_root: Path, *args: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            capture_output=True,
            check=False,
        )
    except OSError:
        return b""
    return result.stdout or b""


def _posix(path: str) -> str:
    return path.strip().replace("\\", "/")


def _ignored(path: str) -> bool:
    return path.startswith(_IGNORED_TOP)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str | None:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError:
        return None


def _parse_name_status(out: str) -> list[tuple[str, str]]:
    records: list[tuple[str, str]] = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        status = parts[0].strip()
        path = _posix(parts[-1] if parts else "")
        if not path or _ignored(path):
            continue
        records.append((status, path))
    return records


def _parse_porcelain(out: str) -> list[tuple[str, str]]:
    records: list[tuple[str, str]] = []
    for line in out.splitlines():
        if not line:
            continue
        if len(line) >= 4 and line[2] == " ":
            status, rest = line[:2], line[3:]
        else:
            parts = line.strip().split(maxsplit=1)
            if len(parts) != 2:
                continue
            status, rest = parts[0], parts[1]
        rest = rest.strip().strip('"')
        if " -> " in rest:
            rest = rest.split(" -> ", 1)[1]
        path = _posix(rest)
        if not path or _ignored(path):
            continue
        records.append((status, path))
    return records


def _delta_records(repo_root: Path, production_sha: str) -> list[dict[str, str]]:
    by_path: dict[str, str] = {}
    _code, committed, _err = _git(
        repo_root, *_STABLE_DIFF, "--name-status",
        f"{production_sha}..HEAD", "--", *_CODE_PATHSPECS,
    )
    _code, worktree, _err = _git(
        repo_root, *_STABLE_DIFF, "--name-status",
        production_sha, "--", *_CODE_PATHSPECS,
    )
    _code, porcelain, _err = _git(
        repo_root, "status", "--porcelain", "--untracked-files=all", "--", *_CODE_PATHSPECS,
    )
    for status, path in _parse_name_status(committed) + _parse_name_status(worktree):
        by_path[path] = status
    for status, path in _parse_porcelain(porcelain):
        by_path.setdefault(path, status.strip() or status)
    return [{"status": by_path[path], "path": path} for path in sorted(by_path)]


def _fingerprints(repo_root: Path, production_sha: str) -> tuple[str, str, bool]:
    committed = _git_bytes(
        repo_root, *_STABLE_DIFF, production_sha, "HEAD", "--", *_CODE_PATHSPECS,
    )
    worktree = _git_bytes(
        repo_root, *_STABLE_DIFF, production_sha, "--", *_CODE_PATHSPECS,
    )
    _code, porcelain, _err = _git(
        repo_root, "status", "--porcelain", "--untracked-files=all", "--", *_CODE_PATHSPECS,
    )
    code_paths_clean = not porcelain
    committed_fp = _sha256_bytes(committed)
    evidence_fp = committed_fp if code_paths_clean else _sha256_bytes(worktree)
    return committed_fp, evidence_fp, code_paths_clean


def _path_clean(repo_root: Path, pathspec: str) -> bool:
    code, porcelain, _err = _git(
        repo_root,
        "status",
        "--porcelain",
        "--untracked-files=all",
        "--",
        pathspec,
    )
    return code == 0 and not porcelain


def _imported_shuabao(repo_root: Path) -> tuple[str | None, str | None]:
    src = (Path(repo_root) / "src").resolve()
    src_s = str(src)
    if src_s not in sys.path:
        sys.path.insert(0, src_s)
    loaded = sys.modules.get("shuabao")
    if loaded is not None:
        path = Path(getattr(loaded, "__file__", "") or "").resolve()
    else:
        try:
            import shuabao  # noqa: WPS433

            path = Path(shuabao.__file__).resolve()
        except Exception as exc:
            return None, f"cannot import shuabao from {src}: {exc}"
    expected = (src / "shuabao").resolve()
    ok = path == expected / "__init__.py" or expected in path.parents
    if not ok:
        return str(path), f"imported shuabao is {path}, not {expected}"
    return str(path), None


def evaluate_test_candidate(
    repo_root: Path | str,
    production_sha: str | None = None,
    expected_test_sha: str | None = None,
) -> dict[str, Any]:
    """Fail-closed Test-candidate identity. Never infer production SHA from merge-base."""
    if not production_sha:
        production_sha = PRODUCTION_SHA
    repo_root = Path(repo_root).resolve()
    reasons: list[str] = []
    if production_sha != PRODUCTION_SHA:
        reasons.append(f"wrong production SHA: {production_sha}")

    code, test_sha, _err = _git(repo_root, "rev-parse", "HEAD")
    if code != 0 or not test_sha:
        test_sha = "unknown"
        reasons.append("test SHA unavailable")
    if expected_test_sha and expected_test_sha != test_sha:
        reasons.append(f"wrong Test SHA: expected={expected_test_sha} actual={test_sha}")

    ancestor_code, _out, _err = _git(
        repo_root, "merge-base", "--is-ancestor", production_sha, "HEAD",
    )
    production_is_ancestor = ancestor_code == 0
    if not production_is_ancestor:
        reasons.append("production is not an ancestor of HEAD")

    _code, test_branch, _err = _git(repo_root, "rev-parse", "--abbrev-ref", "HEAD")
    if not test_branch:
        test_branch = "unknown"

    imported, import_reason = _imported_shuabao(repo_root)
    if import_reason:
        reasons.append(import_reason)

    src_clean = _path_clean(repo_root, "src")
    config_clean = _path_clean(repo_root, "config")
    tools_clean = _path_clean(repo_root, "tools")
    if not src_clean:
        reasons.append("dirty src")
    if not config_clean:
        reasons.append("dirty config")
    if not tools_clean:
        reasons.append("dirty tools")
    code_paths_clean = src_clean and config_clean and tools_clean

    production_critical_clean = True
    for rel in PRODUCTION_CRITICAL_PATHS:
        committed_code, _out, _err = _git(
            repo_root, *_STABLE_DIFF, "--exit-code", production_sha, "HEAD", "--", rel,
        )
        dirty_code, _out, _err = _git(repo_root, "diff", "--exit-code", "HEAD", "--", rel)
        _code, dirty_porc, _err = _git(
            repo_root, "status", "--porcelain", "--untracked-files=all", "--", rel,
        )
        if committed_code != 0 or dirty_code != 0 or dirty_porc:
            production_critical_clean = False
            reasons.append(f"production-critical path mismatch: {rel}")

    from live_harness_identity import identity_report

    canonical = identity_report(repo_root=repo_root)
    delta = _delta_records(repo_root, production_sha)
    delta_paths = {item["path"] for item in delta}
    extra = sorted(delta_paths - DECLARED_TEST_ONLY_DELTA)
    missing = sorted(DECLARED_TEST_ONLY_DELTA - delta_paths)
    if extra or missing:
        reasons.append(
            "TEST_ONLY_DELTA mismatch"
            + (f" extra={extra}" if extra else "")
            + (f" missing={missing}" if missing else "")
        )
    undeclared_src = sorted(
        path for path in extra
        if path.startswith("src/shuabao/")
    )
    if undeclared_src:
        reasons.append(f"undeclared new src/shuabao file: {undeclared_src}")

    committed_fp, evidence_fp, fingerprint_code_paths_clean = _fingerprints(repo_root, production_sha)
    code_paths_clean = code_paths_clean and fingerprint_code_paths_clean
    _code, all_porc, _err = _git(repo_root, "status", "--porcelain", "--untracked-files=all")
    leftover = [path for _status, path in _parse_porcelain(all_porc) if not _ignored(path)]
    worktree_fully_clean = not leftover
    ready = not reasons
    return {
        "status": "READY" if ready else "BLOCKED",
        "ready": ready,
        "blocked_reasons": reasons,
        "production_branch": PRODUCTION_BRANCH,
        "production_sha": production_sha,
        "test_sha": test_sha,
        "production_is_ancestor": production_is_ancestor,
        "test_branch": test_branch,
        "test_root": str(repo_root),
        "imported_shuabao": imported,
        "python_executable": sys.executable,
        "TEST_ONLY_DELTA": delta,
        "delta_fingerprint": evidence_fp,
        "committed_fingerprint": committed_fp,
        "canonical_production_identity": {
            "match": canonical.get("match"),
            "ready_for_gt": canonical.get("ready_for_gt"),
            "production_code_diff": canonical.get("production_code_diff"),
            "files": canonical.get("production_code_diff_files"),
        },
        "src_clean": src_clean,
        "config_clean": config_clean,
        "tools_clean": tools_clean,
        "code_paths_clean": code_paths_clean,
        "worktree_fully_clean": worktree_fully_clean,
        "production_critical_clean": production_critical_clean,
        "production_source_clean": src_clean,
    }


def build_session_evidence(
    *,
    repo_root: Path | str,
    python_executable: str,
    settings_path: Path | str | None,
    operator_settings_source: Path | str | None,
    profile_name: str,
    profile_config_path: Path | str | None,
    ocr_python: str | None,
    ocr_model_dir: str | Path | None,
    expected_test_sha: str | None = None,
) -> dict[str, Any]:
    repo_root = Path(repo_root).resolve()
    evaluation = evaluate_test_candidate(repo_root, expected_test_sha=expected_test_sha)
    reasons = list(evaluation.get("blocked_reasons") or [])
    cannot_start = False

    settings_path_s = str(settings_path) if settings_path else None
    settings_sha = _sha256_file(Path(settings_path)) if settings_path and Path(settings_path).is_file() else None

    operator_path = Path(operator_settings_source) if operator_settings_source else None
    operator_s = str(operator_path) if operator_path else None
    operator_sha = _sha256_file(operator_path) if operator_path and operator_path.is_file() else None
    if operator_sha is None:
        cannot_start = True
        reasons.append("operator settings source missing")

    profile_path = Path(profile_config_path) if profile_config_path else repo_root / "config" / "dashboard_test_profiles.json"
    profile_sha = _sha256_file(profile_path)

    ocr_python_path = str(ocr_python) if ocr_python else None
    model_dir = Path(ocr_model_dir).resolve() if ocr_model_dir else None
    ocr_model_path = str(model_dir) if model_dir else None
    manifest_fp = None
    model_fp = None
    if model_dir is not None:
        manifest = model_dir / "MODEL_MANIFEST.json"
        if not manifest.is_file():
            nested = model_dir / "PP-OCRv5_mobile_rec_infer"
            if (nested / "MODEL_MANIFEST.json").is_file():
                manifest = nested / "MODEL_MANIFEST.json"
        if manifest.is_file():
            manifest_fp = _sha256_file(manifest)
        inference = model_dir / "PP-OCRv5_mobile_rec_infer" / "inference.json"
        if not inference.is_file():
            inference = model_dir / "inference.json"
        if inference.is_file():
            model_fp = _sha256_file(inference)
    if not ocr_python_path or not model_dir or not (manifest_fp or model_fp):
        cannot_start = True
        reasons.append("missing OCR evidence")

    if cannot_start:
        evaluation = dict(evaluation)
        evaluation["blocked_reasons"] = reasons
        evaluation["status"] = "BLOCKED"
        evaluation["ready"] = False

    return {
        "production_branch": PRODUCTION_BRANCH,
        "production_sha": evaluation["production_sha"],
        "test_sha": evaluation["test_sha"],
        "production_is_ancestor": evaluation["production_is_ancestor"],
        "test_branch": evaluation["test_branch"],
        "test_root": evaluation["test_root"],
        "imported_shuabao": evaluation["imported_shuabao"],
        "python_executable": python_executable or sys.executable,
        "TEST_ONLY_DELTA": evaluation["TEST_ONLY_DELTA"],
        "delta_fingerprint": evaluation["delta_fingerprint"],
        "settings_path": settings_path_s,
        "settings_sha256": settings_sha,
        "operator_settings_source": operator_s,
        "operator_settings_source_sha256": operator_sha,
        "profile_name": profile_name,
        "profile_config_sha256": profile_sha,
        "ocr_python_path": ocr_python_path,
        "ocr_model_path": ocr_model_path,
        "ocr_model_fingerprint": model_fp,
        "ocr_model_manifest_fingerprint": manifest_fp,
        "canonical_production_identity": evaluation["canonical_production_identity"],
        "test_candidate_identity": evaluation,
        "cannot_start_gt": cannot_start,
        "blocked_reasons": reasons,
        "status": "BLOCKED" if (cannot_start or evaluation["status"] != "READY") else "READY",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GT test-candidate identity")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--expected-test-sha", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = evaluate_test_candidate(args.repo_root, expected_test_sha=args.expected_test_sha)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"status={report['status']} production={report['production_sha']} test={report['test_sha']}")
        for reason in report.get("blocked_reasons") or []:
            print(f"BLOCKED: {reason}")
    cannot = bool(report.get("cannot_start_gt"))
    return 0 if report["status"] == "READY" and not cannot else 1


if __name__ == "__main__":
    raise SystemExit(main())
