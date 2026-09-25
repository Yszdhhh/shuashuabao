#!/usr/bin/env python3
"""汇总 solo_shadow_*.jsonl：只统计，不下结论。

用法::

    python tools/summarize_solo_shadow.py <observe 目录 | solo_shadow_*.jsonl> [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


# Explicit plan families, not substring matching and not executed actions.
_PLAN_TARGETS = {
    "open_skill_panel": "skill",
    "open_treasure_panel": "treasure",
    "bond_draw": "bond",
    "bond_refresh": "bond",
}
_KINDS = {"RECOMMEND", "WAIT_OR_OBSERVE", "CONTINUE_TRANSACTION"}


def _reject_constant(value: str) -> None:
    raise ValueError("non-finite JSON number")


def _unique_object(pairs: list[tuple]) -> dict:
    obj: dict = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("duplicate JSON key")
        obj[key] = value
    return obj


def _validate_record(row: object) -> None:
    """Validate consumed fields, not game facts or successful action evidence."""
    if not isinstance(row, dict):
        raise ValueError("record must be an object")
    if type(row.get("schema")) is not int or row["schema"] not in (1, 2):
        raise ValueError("unsupported log schema")
    if type(row.get("seq")) is not int or row["seq"] < 1:
        raise ValueError("seq must be a positive integer")
    if not isinstance(row.get("round_id"), str) or not row["round_id"].strip():
        raise ValueError("round_id must be a nonempty string")
    dec, actual = row.get("decision"), row.get("actual")
    if not isinstance(dec, dict) or not isinstance(actual, dict):
        raise ValueError("decision and actual must be objects")
    if not isinstance(dec.get("kind"), str) or dec["kind"] not in _KINDS:
        raise ValueError("unsupported decision kind")
    if actual.get("plan_target") is not None and not isinstance(actual["plan_target"], str):
        raise ValueError("plan_target must be a string or null")
    chosen = dec.get("chosen")
    if chosen is not None and not isinstance(chosen, dict):
        raise ValueError("chosen must be an object or null")
    if dec["kind"] == "RECOMMEND" and (
        not chosen or not isinstance(chosen.get("action_id"), str) or not chosen["action_id"]
    ):
        raise ValueError("recommendation must identify a candidate")
    for key in ("review_required", "incomparable"):
        values = dec.get(key, [])
        if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
            raise ValueError(f"{key} must contain strings")
    alternatives = dec.get("alternatives", [])
    if not isinstance(alternatives, list) or any(
        not isinstance(v, (list, tuple)) or len(v) != 2
        or any(not isinstance(part, str) for part in v) for v in alternatives
    ):
        raise ValueError("alternatives must contain action/reason pairs")


def load(paths: list[str]) -> list[dict]:
    """Reject partial/corrupt inputs; a successful summary is still NOT a gate."""
    files: dict[Path, None] = {}
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            matches = sorted(p.glob("solo_shadow_*.jsonl"))
            if not matches:
                raise ValueError(f"{p}: no solo_shadow logs")
        elif p.is_file() and p.name.startswith("solo_shadow") and p.suffix == ".jsonl":
            matches = [p]
        else:
            raise ValueError(f"{p}: missing or unsupported log path")
        for match in matches:
            files[match.resolve()] = None
    rows: list[dict] = []
    for f in files:
        last_seq = 0
        with f.open(encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line, parse_constant=_reject_constant, object_pairs_hook=_unique_object)
                    _validate_record(row)
                    if row["seq"] <= last_seq:
                        raise ValueError("sequence reset/duplicate; session identity requires review")
                    last_seq = row["seq"]
                except ValueError as exc:
                    # Report location, never echo the possibly sensitive raw line.
                    raise ValueError(f"{f}:{line_no}: invalid shadow record ({type(exc).__name__})") from exc
                row["_source_file"] = str(f)
                rows.append(row)
        if last_seq == 0:
            raise ValueError(f"{f}: empty log")
    return rows


def summarize(rows: list[dict]) -> dict:
    by_round: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        _validate_record(r)
        # round_id is only unique inside a recording session. Never merge
        # different files or incompatible schema versions into one episode.
        key = json.dumps([r.get("_source_file", "<memory>"), r["schema"], r["round_id"]], ensure_ascii=False)
        by_round[key].append(r)

    rounds: dict[str, dict] = {}
    for rid, items in by_round.items():
        items.sort(key=lambda x: x.get("seq", 0))
        kinds = Counter((r.get("decision") or {}).get("kind", "?") for r in items)
        agree = disagree = non_recommend = recommend_no_actual = uncomparable = 0
        boundary_kinds = Counter(str(r.get("boundary") or "?") for r in items)
        review = Counter()
        incompar = 0
        rejects = Counter()
        for r in items:
            dec = r.get("decision") or {}
            actual = r.get("actual") or {}
            if dec.get("kind") != "RECOMMEND":
                non_recommend += 1
            else:
                chosen = dec["chosen"]
                family = _PLAN_TARGETS.get(chosen["action_id"])
                target = actual.get("plan_target")
                if not target:
                    recommend_no_actual += 1
                elif (
                    r.get("boundary") != "plan_in_window"
                    or family is None or target not in set(_PLAN_TARGETS.values())
                    or chosen.get("target", family) != family
                ):
                    uncomparable += 1
                elif target == family:
                    agree += 1
                else:
                    disagree += 1
            for reason in dec.get("review_required") or []:
                review[str(reason)] += 1
            if dec.get("incomparable"):
                incompar += 1
            for _aid, reason in dec.get("alternatives") or []:
                if reason and reason not in ("CHOSEN", "NOT_CHOSEN", "CHOSEN_BY_STARVATION", "YIELDED_TO_STARVED", "STARVED_EQUIVALENT", "DOMINATED_IN_FRONT"):
                    rejects[str(reason)] += 1
            snap = r.get("snapshot") or {}
            # reject 也在候选内
        # 再扫一遍 chosen 内 reject 不在 alternatives 时的合法标记
        for r in items:
            dec = r.get("decision") or {}
            ch = dec.get("chosen") or {}
            if ch.get("reject_reason"):
                rejects[str(ch["reject_reason"])] += 1

        total = len(items)
        rounds[rid] = {
            "round_id": items[0]["round_id"],
            "source_file": items[0].get("_source_file"),
            "log_schema": items[0]["schema"],
            "recommend_vs_plan_target_agree": agree,
            "recommend_vs_plan_target_disagree": disagree,
            "recommend_plan_uncomparable": uncomparable,
            # Compatibility aliases only: neither counter attests an action.
            "boundaries": total,
            "decision_counts": dict(kinds),
            "decision_ratio": {
                k: (v / total if total else None) for k, v in kinds.items()
            },
            "recommend_vs_actual_agree": agree,
            "recommend_vs_actual_disagree": disagree,
            "non_recommend": non_recommend,
            "recommend_no_actual_plan": recommend_no_actual,
            "boundary_kinds": dict(boundary_kinds),
            "review_required": review.most_common(),
            "incomparable_boundaries": incompar,
            "incomparable_rate": (incompar / total) if total else None,
            "reject_reasons": rejects.most_common(),
        }

    totals = {
        "rows": len(rows),
        "rounds": len(rounds),
        "boundaries": sum(d["boundaries"] for d in rounds.values()),
    }
    return {
        "report_schema": 2,
        "evidence_scope": "PLAN_TARGET_ONLY",
        "behavior_proof": False,
        "actual_action_evidence": "NOT_AVAILABLE",
        "warning": "NOT_BEHAVIOR_PROOF: logged plan-family comparison only; pairing and execution are not verified",
        "legacy_counter_aliases": "recommend_vs_actual_* are deprecated aliases of recommend_vs_plan_target_*",
        "totals": totals, "rounds": rounds,
    }


def render(s: dict) -> str:
    out: list[str] = [s["warning"], "Evidence scope: PLAN_TARGET_ONLY; actual action evidence: NOT_AVAILABLE"]
    t = s["totals"]
    out.append(f"== solo_shadow 汇总  行 {t['rows']}  局 {t['rounds']}  边界 {t['boundaries']} ==")
    for rid, d in s["rounds"].items():
        out.append(f"== 局 {rid} ==  边界 {d['boundaries']}")
        out.append("  decision: " + "  ".join(f"{k}:{v}" for k, v in d["decision_counts"].items()))
        out.append(f"  RECOMMEND vs 旧逻辑  一致 {d['recommend_vs_actual_agree']}  分歧 {d['recommend_vs_actual_disagree']}  旧逻辑无计划 {d['recommend_no_actual_plan']}  非推荐 {d['non_recommend']}")
        out.append(f"  uncomparable plan records: {d['recommend_plan_uncomparable']}")
        out.append(f"  边界类型 {d['boundary_kinds']}")
        rate = d["incomparable_rate"]
        out.append(f"  不可比边界 {d['incomparable_boundaries']}" + (f"  ({rate*100:.0f}%)" if rate is not None else ""))
        if d["review_required"]:
            out.append("  REVIEW_REQUIRED: " + "  ".join(f"{k}:{v}" for k, v in d["review_required"][:8]))
        if d["reject_reasons"]:
            out.append("  reject_reasons: " + "  ".join(f"{k}:{v}" for k, v in d["reject_reasons"][:12]))
        out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        rows = load(a.paths)
        s = summarize(rows)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"INVALID_SHADOW_EVIDENCE: {exc}", file=sys.stderr)
        return 2
    if not rows:
        print("没有找到 solo_shadow_*.jsonl", file=sys.stderr)
        return 2
    print(json.dumps(s, ensure_ascii=False, indent=2) if a.json else render(s))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
