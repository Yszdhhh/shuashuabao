#!/usr/bin/env python3
"""Summarize treasure name/description OCR shadow telemetry.

The trace records OCR availability, not whether a particular OCR result
changed a business decision.  The report therefore separates observed signal
from causal claims and keeps treasure semantics enabled.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRACE = Path(r"C:\Users\10639\AppData\Local\ShuaBao\incidents\ocr_shadow.jsonl")
DEFAULT_POLICY = ROOT / "config" / "choice_policy.json"
DEFAULT_OUTPUT = ROOT / "docs" / "distillation" / "TREASURE_OCR_AUDIT.json"


def _kind(row: dict[str, Any]) -> str | None:
    panel_id = str(row.get("panel_id") or "")
    if not panel_id.startswith("treasure:"):
        return None
    return "description" if panel_id.endswith(":desc") else "name"


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((len(ordered) - 1) * percentile))
    return round(float(ordered[index]), 3)


def _policy_summary(path: Path) -> dict[str, Any]:
    policy = json.loads(path.read_text(encoding="utf-8"))
    treasure = policy.get("treasure") or {}
    return {
        "negative_names": len(treasure.get("negative_names") or []),
        "negative_patterns": len(treasure.get("negative_patterns") or []),
        "must_take_names": len(treasure.get("must_take_names") or []),
        "allow_negative_names": len(treasure.get("allow_negative") or []),
        "refresh_on_no_safe": bool(treasure.get("refresh_on_no_safe")),
    }


def audit(trace_path: Path, policy_path: Path, output: Path) -> dict[str, Any]:
    if not trace_path.is_file():
        report = {"status": "not_available", "trace": str(trace_path), "reason": "trace file missing"}
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return report

    rows: list[dict[str, Any]] = []
    with trace_path.open(encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, 1):
            if not raw.strip():
                continue
            item = json.loads(raw)
            if not isinstance(item, dict):
                raise ValueError(f"{trace_path}:{line_no}: row is not an object")
            rows.append(item)

    treasure_rows = [row for row in rows if _kind(row) is not None]
    by_kind: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in treasure_rows:
        by_kind[_kind(row)].append(row)  # type: ignore[arg-type]

    metrics: dict[str, Any] = {}
    for kind in ("name", "description"):
        items = by_kind[kind]
        statuses = Counter(str(row.get("status") or "missing") for row in items)
        reasons = Counter(str(row.get("reason") or "") for row in items if row.get("reason"))
        elapsed = [float(row["elapsed_ms"]) for row in items if row.get("elapsed_ms") is not None]
        raw_nonempty = sum(bool(str(row.get("raw_text") or "").strip()) for row in items)
        candidate_nonempty = sum(bool(row.get("candidates")) for row in items)
        metrics[kind] = {
            "calls": len(items),
            "status": dict(statuses),
            "reasons": dict(reasons),
            "raw_nonempty": raw_nonempty,
            "candidate_nonempty": candidate_nonempty,
            "elapsed_ms": {
                "count": len(elapsed),
                "p50": _percentile(elapsed, 0.50),
                "p95": _percentile(elapsed, 0.95),
            },
        }

    panel_calls = Counter(
        str(row.get("panel_id"))[:-5] if str(row.get("panel_id", "")).endswith(":desc") else str(row.get("panel_id"))
        for row in treasure_rows
    )
    report = {
        "schema_version": 1,
        "status": "COMPLETED",
        "trace": str(trace_path),
        "total_trace_rows": len(rows),
        "treasure_trace_rows": len(treasure_rows),
        "treasure_panels": {
            "distinct_name_description_panel_ids": len(panel_calls),
            "max_ocr_calls_per_panel": max(panel_calls.values(), default=0),
        },
        "by_kind": metrics,
        "policy": _policy_summary(policy_path),
        "interpretation": {
            "full_treasure_ocr_removal": "REJECT",
            "semantic_policy": "retain name and description OCR; continue fail-closed when unavailable",
            "causal_business_value": "not_proven by this shadow trace because it has no selected-action/outcome label",
            "description_signal": "availability and inference behavior only; do not infer zero business value from low lexicon hits",
            "next_evidence": "label safe/negative/must-take outcomes on a held-out trace before changing OCR scope",
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", type=Path, default=DEFAULT_TRACE)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--json-out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    report = audit(args.trace, args.policy, args.json_out)
    print(json.dumps({"status": report["status"], "json": str(args.json_out.resolve()), "treasure_rows": report.get("treasure_trace_rows", 0)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
