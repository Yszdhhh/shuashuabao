#!/usr/bin/env python3
"""Fail-closed identity for the live harness.

This module does not implement game logic.  It only answers: is the current
process about to exercise the frozen production source, or an old worktree /
dist / EXE?
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

HARNESS_BASE_SHA = "bf1d247eefd30d84ef5f88ffb2f13a334e2b9b4d"
FROZEN_PRODUCTION_CODE_BASELINE = "bf1d247eefd30d84ef5f88ffb2f13a334e2b9b4d"
FORBIDDEN_RUNTIME_SHAS = (
    "144c0c9adc366a35548f6e1c2e52fad8387da090",
    "b15da05f4fd7313b02b2cc466e319d9683aa979c",
)
FORBIDDEN_WORKTREE_MARKERS = (
    "solo-live-harness-20260907",
)
PRODUCTION_PATHSPECS = ("src/shuabao",)
BUILD_IDENTITY_FILENAME = "build_identity.json"


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
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def commit_sha(repo_root: Path) -> str:
    code, out, _err = _git(repo_root, "rev-parse", "HEAD")
    return out if code == 0 and out else "unknown"


def git_branch(repo_root: Path) -> str:
    code, out, _err = _git(repo_root, "rev-parse", "--abbrev-ref", "HEAD")
    return out if code == 0 and out else "unknown"


def is_ancestor(repo_root: Path, ancestor: str, descendant: str = "HEAD") -> bool:
    code, _out, _err = _git(repo_root, "merge-base", "--is-ancestor", ancestor, descendant)
    return code == 0


def _name_only_diff(repo_root: Path, baseline: str, pathspec: str) -> list[str]:
    code, out, _err = _git(repo_root, "diff", "--name-only", f"{baseline}...HEAD", "--", pathspec)
    if code != 0:
        code, out, _err = _git(repo_root, "diff", "--name-only", baseline, "HEAD", "--", pathspec)
    if code != 0:
        return [f"<git diff failed for {pathspec} vs {baseline[:12]}>"]
    return [line.strip().replace("\\", "/") for line in out.splitlines() if line.strip()]


def _dirty_production_paths(repo_root: Path) -> list[str]:
    code, out, _err = _git(repo_root, "status", "--porcelain", "--untracked-files=all", "--", *PRODUCTION_PATHSPECS)
    if code != 0:
        return ["<git status failed for production paths>"]
    dirty: list[str] = []
    for line in out.splitlines():
        path = line[3:].strip().replace("\\", "/")
        if path:
            dirty.append(path)
    return dirty


def production_code_diff(repo_root: Path) -> dict[str, Any]:
    """Compare production source against the frozen code freeze and harness base."""
    files: list[str] = []
    for baseline in (FROZEN_PRODUCTION_CODE_BASELINE, HARNESS_BASE_SHA):
        for pathspec in PRODUCTION_PATHSPECS:
            files.extend(_name_only_diff(repo_root, baseline, pathspec))
    files.extend(_dirty_production_paths(repo_root))
    unique = sorted(set(files))
    return {
        "status": "CLEAN" if not unique else "NOT_CLEAN",
        "files": unique,
        "frozen_production_code_baseline": FROZEN_PRODUCTION_CODE_BASELINE,
        "harness_base_sha": HARNESS_BASE_SHA,
    }


def runtime_source_path(repo_root: Path) -> dict[str, Any]:
    """Resolve the shuabao package this process would actually import."""
    src = (Path(repo_root).resolve() / "src")
    src_s = str(src)
    if src_s not in sys.path:
        sys.path.insert(0, src_s)
    loaded = sys.modules.get("shuabao")
    if loaded is not None:
        loaded_path = Path(getattr(loaded, "__file__", "") or "").resolve()
    else:
        try:
            import shuabao  # noqa: WPS433

            loaded_path = Path(shuabao.__file__).resolve()
        except Exception as exc:
            return {
                "ok": False,
                "path": None,
                "reason": f"cannot import shuabao from {src}: {exc}",
            }
    expected = (src / "shuabao").resolve()
    ok = loaded_path == expected / "__init__.py" or expected in loaded_path.parents
    return {
        "ok": ok,
        "path": str(loaded_path) if loaded_path else None,
        "expected_package_dir": str(expected),
        "reason": None if ok else f"imported shuabao is {loaded_path}, not {expected}",
    }


def _forbidden_worktree(repo_root: Path, runtime_path: str | None) -> list[str]:
    reasons: list[str] = []
    haystacks = [str(Path(repo_root).resolve())]
    if runtime_path:
        haystacks.append(runtime_path)
    for marker in FORBIDDEN_WORKTREE_MARKERS:
        if any(marker.lower() in text.replace("/", "\\").lower() for text in haystacks):
            reasons.append(f"runtime path still points at old harness worktree marker {marker}")
    return reasons


def _exe_identity(automation_exe: Path | None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "path": None,
        "source_sha": None,
        "status": "NOT_PROVIDED",
        "blocked_reasons": [],
    }
    if automation_exe is None:
        return record
    exe_path = Path(automation_exe).resolve()
    record["path"] = str(exe_path)
    if not exe_path.is_file():
        record["status"] = "MISSING"
        record["blocked_reasons"].append(f"automation EXE not found: {exe_path}")
        return record
    sidecar = exe_path.parent / BUILD_IDENTITY_FILENAME
    record["build_identity_path"] = str(sidecar)
    if not sidecar.is_file():
        record["status"] = "NO_SIDECAR"
        record["blocked_reasons"].append(f"build identity sidecar missing: {sidecar}")
        return record
    try:
        identity = json.loads(sidecar.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError) as exc:
        record["status"] = "UNREADABLE"
        record["blocked_reasons"].append(f"build identity sidecar unreadable: {exc}")
        return record
    if not isinstance(identity, dict):
        record["status"] = "INVALID"
        record["blocked_reasons"].append("build identity sidecar is not a JSON object")
        return record
    source_sha = str(identity.get("source_sha") or identity.get("tested_source_sha") or "")
    record["source_sha"] = source_sha or None
    record["identity"] = {
        "source_sha": source_sha,
        "build_id": identity.get("build_id"),
        "source_tree_clean": identity.get("source_tree_clean"),
    }
    record["status"] = "PRESENT"
    return record


def identity_report(
    *,
    repo_root: Path,
    automation_exe: Path | None = None,
    require_exe: bool = False,
) -> dict[str, Any]:
    repo_root = Path(repo_root).resolve()
    harness_head = commit_sha(repo_root)
    derived = is_ancestor(repo_root, HARNESS_BASE_SHA, "HEAD") if harness_head != "unknown" else False
    prod_diff = production_code_diff(repo_root)
    runtime = runtime_source_path(repo_root)
    exe = _exe_identity(automation_exe)
    reasons: list[str] = []

    if harness_head == "unknown":
        reasons.append("Harness HEAD SHA unavailable")
    if harness_head in FORBIDDEN_RUNTIME_SHAS:
        reasons.append(f"Harness HEAD is a forbidden old runtime SHA: {harness_head}")
    if not derived:
        reasons.append(f"Harness HEAD is not a descendant of harness base {HARNESS_BASE_SHA[:12]}")
    if prod_diff["status"] != "CLEAN":
        reasons.append(
            "production code diff is NOT_CLEAN: " + ", ".join(prod_diff["files"][:12])
        )
    if not runtime.get("ok"):
        reasons.append(str(runtime.get("reason") or "runtime source is not this worktree"))
    reasons.extend(_forbidden_worktree(repo_root, runtime.get("path")))

    exe_sha = str(exe.get("source_sha") or "")
    if exe_sha in FORBIDDEN_RUNTIME_SHAS:
        reasons.append(f"automation EXE source SHA is a forbidden old runtime: {exe_sha}")
    if exe["status"] in {"MISSING", "UNREADABLE", "INVALID"}:
        reasons.extend(exe.get("blocked_reasons") or [])
    if require_exe and exe["status"] != "PRESENT":
        reasons.append("automation EXE identity is required for this live-input mode")
    if exe["status"] == "PRESENT" and exe_sha and exe_sha != harness_head:
        # Packaged EXE may lag the harness-only commit.  It must still be a
        # descendant of the frozen production baseline and not an old runtime.
        if not is_ancestor(repo_root, FROZEN_PRODUCTION_CODE_BASELINE, exe_sha):
            reasons.append(
                f"automation EXE source {exe_sha[:12]} is not derived from frozen production "
                f"{FROZEN_PRODUCTION_CODE_BASELINE[:12]}"
            )

    ready = not reasons
    return {
        "harness_head": harness_head,
        "harness_branch": git_branch(repo_root),
        "harness_base": HARNESS_BASE_SHA,
        "runtime_worktree": str(repo_root),
        "runtime_worktree_sha": harness_head,
        "runtime_source_path": runtime.get("path"),
        "runtime_source_verified": bool(runtime.get("ok")) and not _forbidden_worktree(repo_root, runtime.get("path")),
        "frozen_production_code_baseline": FROZEN_PRODUCTION_CODE_BASELINE,
        "production_code_diff": prod_diff["status"],
        "production_code_diff_files": prod_diff["files"],
        "automation_exe": exe,
        "ready_for_gt": ready,
        "match": "READY" if ready else "NO",
        "blocked_reasons": reasons,
    }


def format_identity_text(report: dict[str, Any]) -> str:
    ready = "YES" if report.get("ready_for_gt") else "NO"
    lines = [
        f"Harness HEAD: {report.get('harness_head')}",
        f"Harness Base: {report.get('harness_base')}",
        f"Production Candidate SHA: {report.get('frozen_production_code_baseline')}",
        f"Runtime Worktree: {report.get('runtime_worktree')}",
        f"Frozen Production Code Baseline: {report.get('frozen_production_code_baseline')}",
        f"Production Code Diff: {report.get('production_code_diff')}",
        f"MATCH / READY: {report.get('match')}",
        f"READY FOR GT: {ready}",
    ]
    exe = report.get("automation_exe") or {}
    if exe.get("path"):
        lines.append(f"Automation EXE: {exe.get('path')} ({exe.get('status')})")
        if exe.get("source_sha"):
            lines.append(f"Automation EXE source SHA: {exe.get('source_sha')}")
    if report.get("runtime_source_path"):
        lines.append(f"Runtime source: {report.get('runtime_source_path')}")
    for reason in report.get("blocked_reasons") or []:
        lines.append(f"BLOCKED: {reason}")
    return "\r\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Live harness production-identity gate")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--automation-exe", type=Path, default=None)
    parser.add_argument("--require-exe", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = identity_report(
        repo_root=args.repo_root,
        automation_exe=args.automation_exe,
        require_exe=bool(args.require_exe),
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_identity_text(report))
    return 0 if report["ready_for_gt"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
