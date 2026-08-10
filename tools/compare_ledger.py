#!/usr/bin/env python3
"""Compare two tick-level action ledgers produced by tools/run_replay.py --ledger.

Equivalence rule (per blueprint B0-2 / invariant #11/#12):
- volatile fields ignored: hwnd, score (report drift separately), status of optional rows
- compared buckets: fixture_id, phase, context, action_name, action_kind, click_point, required
- any difference in compared buckets => DIFF (exit 1); score drift > 0.05 => WARN
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

COMPARED_FIELDS = ("fixture_id", "phase", "context", "action_name", "action_kind", "click_point", "required")


def load_rows(path: Path) -> dict[str, dict]:
    rows = {}
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            rows[row["fixture_id"]] = row
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare two action ledgers (equivalence checker)")
    parser.add_argument("baseline", help="baseline ledger JSONL")
    parser.add_argument("candidate", help="candidate ledger JSONL")
    args = parser.parse_args()

    base = load_rows(Path(args.baseline))
    cand = load_rows(Path(args.candidate))

    diffs: list[str] = []
    warns: list[str] = []
    for fid in sorted(set(base) | set(cand)):
        b = base.get(fid)
        c = cand.get(fid)
        if b is None:
            diffs.append(f"[DIFF] {fid}: only in candidate")
            continue
        if c is None:
            diffs.append(f"[DIFF] {fid}: only in baseline")
            continue
        for field in COMPARED_FIELDS:
            if b.get(field) != c.get(field):
                diffs.append(f"[DIFF] {fid}.{field}: {b.get(field)!r} -> {c.get(field)!r}")
        score_drift = abs(float(b.get("score", 0.0)) - float(c.get("score", 0.0)))
        if score_drift > 0.05:
            warns.append(f"[WARN] {fid}.score drift {b.get('score')} -> {c.get('score')}")

    for w in warns:
        print(w)
    for d in diffs:
        print(d)

    print(f"ledger compare: baseline={len(base)} rows, candidate={len(cand)} rows, "
          f"diffs={len(diffs)}, score-warns={len(warns)}")
    if diffs:
        print("[ERROR] action ledger NOT equivalent to baseline")
        return 1
    print("[OK] action ledger equivalent to baseline (volatile fields ignored)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
