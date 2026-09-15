from __future__ import annotations

import argparse
import os
import stat
import subprocess
import sys
from pathlib import Path

EXPECTED_CONFIG = {
    "core.hooksPath": ".githooks",
    "pull.ff": "only",
    "fetch.prune": "true",
    "push.default": "simple",
}

REQUIRED_HOOKS = (
    "pre-commit",
    "pre-push",
    "pre-merge-commit",
)


def _git(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )


def _repo_root() -> Path:
    try:
        result = _git("rev-parse", "--show-toplevel")
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("run this command from inside a Git checkout") from exc
    return Path(result.stdout.strip()).resolve()


def _config_value(root: Path, key: str) -> str | None:
    result = _git("config", "--local", "--get", key, cwd=root, check=False)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _make_hooks_executable(root: Path) -> None:
    for hook_name in REQUIRED_HOOKS:
        hook = root / ".githooks" / hook_name
        if not hook.is_file():
            continue
        mode = hook.stat().st_mode
        hook.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def configure(root: Path) -> None:
    for key, value in EXPECTED_CONFIG.items():
        _git("config", "--local", key, value, cwd=root)
    _make_hooks_executable(root)


def check_configuration(root: Path) -> list[str]:
    problems: list[str] = []

    for key, expected in EXPECTED_CONFIG.items():
        actual = _config_value(root, key)
        if actual != expected:
            rendered = "<unset>" if actual is None else repr(actual)
            problems.append(f"{key}: expected {expected!r}, got {rendered}")

    for hook_name in REQUIRED_HOOKS:
        hook = root / ".githooks" / hook_name
        if not hook.is_file():
            problems.append(f"missing hook: .githooks/{hook_name}")
            continue
        if os.name != "nt" and not os.access(hook, os.X_OK):
            problems.append(f"hook is not executable: .githooks/{hook_name}")

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install or verify the repository-local ShuaBao Git guardrails."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify configuration without changing it",
    )
    args = parser.parse_args()

    try:
        root = _repo_root()
    except RuntimeError as exc:
        print(f"[shuashuabao] ERROR: {exc}", file=sys.stderr)
        return 2

    if not args.check:
        configure(root)

    problems = check_configuration(root)
    if problems:
        print("[shuashuabao] Git guardrails are NOT ready:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        if args.check:
            print("Run: python scripts/setup_git_guardrails.py", file=sys.stderr)
        return 1

    mode = "verified" if args.check else "installed and verified"
    print(f"[shuashuabao] Git guardrails {mode} for {root}")
    print("  - tracked hooks: .githooks")
    print("  - pull.ff: only")
    print("  - fetch.prune: true")
    print("  - push.default: simple")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
