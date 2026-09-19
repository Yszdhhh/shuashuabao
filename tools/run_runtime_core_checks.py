#!/usr/bin/env python3
"""Run only the portable runtime-core unit suite. Never invoke a LIVE entrypoint."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    started = time.monotonic()
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests" / "runtime_core"))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    try:
        process = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                                 capture_output=True, text=True, check=True, timeout=5)
        sha = process.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        sha = None
    paths = sorted((ROOT / "src" / "shuabao" / "runtime_core").glob("*.py"))
    paths += sorted((ROOT / "tests" / "runtime_core").glob("*.py"))
    paths += [Path(__file__).resolve(), ROOT / "tools" / "prepare_runtime_core_integration.py"]
    passed = result.wasSuccessful() and result.testsRun >= 78 and not result.skipped
    hashes = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    report = {
        "schema_version": 1, "evidence_kind": "OFFLINE_UNIT",
        "candidate_sha": sha, "status": "PASS" if passed else "FAIL",
        "tests_run": result.testsRun, "failures": len(result.failures),
        "errors": len(result.errors), "skipped": len(result.skipped),
        "seconds": round(time.monotonic() - started, 3), "files_sha256": hashes,
        "runtime_wiring": "NOT_VALIDATED", "release_gate": "NOT_RUN",
        "frozen_replay": "NOT_RUN", "live": "NOT_RUN", "real_input": False,
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "files_sha256"}, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
