#!/usr/bin/env python3
"""O4 off/shadow action-ledger equivalence check.

Runs the full fixture replay twice with ocr_mode=off and ocr_mode=shadow,
writes both tick-level ledgers, and applies compare_ledger's equivalence
rule (fixture_id/phase/context/action_name/action_kind/click_point/required;
hwnd/score/status are volatile).  Any difference exits 1.

ocr_mode is not yet consumed by the mediator (integration wave), so shadow
must not change a single compared field — this proves shadow holds zero input
action authority.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from compare_ledger import COMPARED_FIELDS, load_rows  # noqa: E402
from gamescript.mediator import Mediator  # noqa: E402
from gamescript.settings import Settings  # noqa: E402
from run_replay import run_replay_fixture  # noqa: E402

MANIFEST = ROOT / "fixtures" / "manifest.json"


def run_mode(mode: str, ledger_path: Path) -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    settings = Settings()
    settings.ocr_mode = mode
    med = Mediator(settings, ROOT)
    total = 0
    rows = 0
    with ledger_path.open("w", encoding="utf-8") as fh:
        for fixture in manifest.get("fixtures", []):
            res = run_replay_fixture(fixture, med, ROOT)
            total += 1
            if res.status == "PASS":
                rows += 1
            row = {
                "fixture_id": res.fixture_id,
                "phase": res.detected_scene,
                "context": res.actual_state,
                "action_name": res.action_name,
                "action_kind": res.action_kind,
                "click_point": res.click_point,
                "hwnd": res.target_hwnd,
                "score": round(res.best_score, 3),
                "margin": round(res.score_margin, 3),
                "status": res.status,
                "required": res.required,
                "dry_run": True,
            }
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"[{mode}] replay total={total} pass={rows} ledger={ledger_path}")
    return total


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "baselines" / "O4_LEDGER_20260811")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    off_ledger = args.out / "off.jsonl"
    shadow_ledger = args.out / "shadow.jsonl"
    run_mode("off", off_ledger)
    run_mode("shadow", shadow_ledger)

    base = load_rows(off_ledger)
    cand = load_rows(shadow_ledger)
    diffs: list[str] = []
    for fid in sorted(set(base) | set(cand)):
        b = base.get(fid)
        c = cand.get(fid)
        if b is None:
            diffs.append(f"[DIFF] {fid}: only in shadow")
            continue
        if c is None:
            diffs.append(f"[DIFF] {fid}: only in off")
            continue
        for field in COMPARED_FIELDS:
            if b.get(field) != c.get(field):
                diffs.append(f"[DIFF] {fid}.{field}: {b.get(field)!r} -> {c.get(field)!r}")
    for d in diffs:
        print(d)
    print(f"ledger compare: off={len(base)} rows, shadow={len(cand)} rows, diffs={len(diffs)}")
    if diffs:
        print("[ERROR] off/shadow action ledger NOT equivalent")
        return 1
    print("[OK] off/shadow action ledger equivalent (shadow has no input action authority)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
