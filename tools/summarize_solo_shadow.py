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


def load(paths: list[str]) -> list[dict]:
    files: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            files.extend(sorted(p.glob("solo_shadow_*.jsonl")))
        elif p.exists() and p.name.startswith("solo_shadow"):
            files.append(p)
    rows: list[dict] = []
    for f in files:
        with f.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    return rows


def summarize(rows: list[dict]) -> dict:
    by_round: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_round[str(r.get("round_id", "?"))].append(r)

    rounds: dict[str, dict] = {}
    for rid, items in by_round.items():
        items.sort(key=lambda x: x.get("seq", 0))
        kinds = Counter((r.get("decision") or {}).get("kind", "?") for r in items)
        agree = disagree = non_recommend = 0
        review = Counter()
        incompar = 0
        rejects = Counter()
        for r in items:
            dec = r.get("decision") or {}
            actual = r.get("actual") or {}
            if dec.get("kind") != "RECOMMEND":
                non_recommend += 1
            else:
                chosen = (dec.get("chosen") or {}).get("action_id") or ""
                target = str(actual.get("plan_target") or "")
                # 旧逻辑 plan_target 是 skill/bond/treasure；影子 action_id 形如 open_*_panel / bond_*
                norm = chosen.replace("open_", "").replace("_panel", "")
                if target and (target in chosen or target == norm or target == (dec.get("chosen") or {}).get("target")):
                    agree += 1
                elif chosen and target:
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
        rec = kinds.get("RECOMMEND", 0)
        rounds[rid] = {
            "boundaries": total,
            "decision_counts": dict(kinds),
            "decision_ratio": {
                k: (v / total if total else None) for k, v in kinds.items()
            },
            "recommend_vs_actual_agree": agree,
            "recommend_vs_actual_disagree": disagree,
            "non_recommend": non_recommend,
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
    return {"totals": totals, "rounds": rounds}


def render(s: dict) -> str:
    out: list[str] = []
    t = s["totals"]
    out.append(f"== solo_shadow 汇总  行 {t['rows']}  局 {t['rounds']}  边界 {t['boundaries']} ==")
    for rid, d in s["rounds"].items():
        out.append(f"== 局 {rid} ==  边界 {d['boundaries']}")
        out.append("  decision: " + "  ".join(f"{k}:{v}" for k, v in d["decision_counts"].items()))
        out.append(f"  RECOMMEND vs 旧逻辑  一致 {d['recommend_vs_actual_agree']}  分歧 {d['recommend_vs_actual_disagree']}  非推荐 {d['non_recommend']}")
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
    rows = load(a.paths)
    if not rows:
        print("没有找到 solo_shadow_*.jsonl", file=sys.stderr)
        return 2
    s = summarize(rows)
    print(json.dumps(s, ensure_ascii=False, indent=2) if a.json else render(s))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
