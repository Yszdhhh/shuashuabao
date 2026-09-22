#!/usr/bin/env python3
"""Compare offline pytest results with solo shadow disabled/enabled.

Equal successful summaries are not proof that _tick_main_line was exercised
or that action sequences, state, and timing were unchanged. Those require
separate integration evidence; this tool must never label them as proven.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
TARGETS = [
    "tests/test_solo_scheduler_contract.py",
    "tests/test_solo_shadow_adapter.py",
    "tests/contract",
    "tests/test_choice_policy.py",
    "tests/test_p1_choice_fsm_contracts.py",
]


def run(env_flag: str) -> str:
    env = os.environ.copy()
    env["SHUABAO_SOLO_SHADOW"] = env_flag
    cmd = [PY, "-m", "pytest", *TARGETS, "-q", "--tb=line"]
    proc = subprocess.run(
        cmd, cwd=str(ROOT), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=1800,
    )
    tail = ((proc.stdout or "") + (proc.stderr or ""))[-8000:]
    return f"exit={proc.returncode}\n{tail}"


def _successful_counts(text: str) -> dict[str, int] | None:
    lines = text.splitlines()
    if not lines or lines[0] != "exit=0":
        return None
    for line in reversed(lines[1:]):
        clean = re.sub(r"\x1b\[[0-9;]*m", "", line)
        if " in " not in clean:
            continue
        counts = {
            label: int(number)
            for number, label in re.findall(
                r"\b(\d+) (passed|failed|errors?|skipped|xfailed|xpassed|deselected)\b",
                clean,
            )
        }
        if not counts:
            continue
        if counts.get("passed", 0) <= 0 or any(
            counts.get(label, 0) for label in ("failed", "error", "errors", "xpassed")
        ):
            return None
        return counts
    return None


def main() -> int:
    try:
        a, b = run("0"), run("1")
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"RESULT: RUN_FAILED ({type(exc).__name__})", file=sys.stderr)
        return 1
    print("=== SHUABAO_SOLO_SHADOW=0 ===")
    print(a)
    print("=== SHUABAO_SOLO_SHADOW=1 ===")
    print(b)
    ca, cb = _successful_counts(a), _successful_counts(b)
    ok = ca is not None and cb is not None and ca == cb
    print("RESULT:", "IDENTICAL_SUCCESSFUL_STATS" if ok else "FAILED_OR_DIFFERENT_STATS")
    print("NOT_BEHAVIOR_PROOF: requires _tick_main_line hook coverage and action-sequence comparison.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
