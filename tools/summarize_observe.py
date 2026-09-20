#!/usr/bin/env python3
"""把局内观测 JSONL 归约成四个优化指标。纯离线只读，不碰游戏。

用法::

    python tools/summarize_observe.py <observe 目录 | tick_*.jsonl> [--json]

输出
====

1. **木材**：净囤积、峰值、消耗总量、高位滞留时长占比
2. **转化率**：花掉的木材 ÷ 进账木材
3. **决策机会分配**：编排把机会给了谁（羁绊 / 技能抢占 / 其它）
4. **每次开 F 的产出**：面板决策的动作分布、刷新被降级成隐藏的次数

刻意不做
========

不建议任何阈值。读不出的值一律排除在统计外，**不当成 0**；
被排除的样本数会如实报出来。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path


def load(paths: list[str], prefix: str) -> list[dict]:
    files: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            files.extend(sorted(p.glob(f"{prefix}_*.jsonl")))
        elif p.exists() and p.name.startswith(prefix):
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


def _num(v: object) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


# 编排理由 -> 归类。依据 mediator._solo_plan_panel 的实际措辞。
def classify(reason: str) -> str:
    if not reason:
        return "未记录"
    if "紧急强抢占" in reason:
        return "技能抢占(>=8)"
    if "木材不足抽羁绊" in reason:
        return "技能优先(木材不足)"
    if "羁绊优先" in reason or "木材充足" in reason:
        return "羁绊优先"
    if "按轮换" in reason:
        return "普通轮换"
    return reason[:18]


def summarize(ticks: list[dict], choices: list[dict]) -> dict:
    by_round: dict[str, list[dict]] = {}
    for t in ticks:
        by_round.setdefault(str(t.get("round_id", "?")), []).append(t)

    rounds = {}
    for rid, rows in by_round.items():
        rows.sort(key=lambda r: r.get("seq", 0))
        woods = [(r, _num(r.get("wood"))) for r in rows]
        series = [(r, w) for r, w in woods if w is not None]
        unreadable = len(woods) - len(series)

        gained = spent = 0.0
        drops = 0
        for (_, a), (_, b) in zip(series, series[1:]):
            if b > a:
                gained += b - a
            elif b < a:
                spent += a - b
                drops += 1
        vals = [w for _, w in series]
        peak = max(vals) if vals else None
        # 高位滞留：木材 >= 峰值 80% 的采样占比
        high = (sum(1 for v in vals if peak and v >= peak * 0.8) / len(vals)) if vals else None

        skills = [s for s in (_num(r.get("skill_points")) for r in rows) if s is not None]
        plans = Counter(classify(str(r.get("plan_reason") or "")) for r in rows
                        if r.get("plan_reason"))

        rounds[rid] = {
            "samples": len(rows),
            "wood_unreadable_samples": unreadable,
            "wood_first": vals[0] if vals else None,
            "wood_last": vals[-1] if vals else None,
            "wood_peak": peak,
            "wood_gained": gained,
            "wood_spent": spent,
            "wood_net": gained - spent,
            "wood_drop_samples": drops,
            # 指标 2
            "conversion_rate": (spent / gained) if gained else None,
            # 指标 1
            "high_water_share": high,
            "skill_min": min(skills) if skills else None,
            "skill_max": max(skills) if skills else None,
            # 指标 3
            "plan_allocation": plans.most_common(),
        }

    # 指标 4
    ch = {
        "total": len(choices),
        "by_panel": Counter(c.get("panel_kind") for c in choices).most_common(),
        "by_action": Counter(str(c.get("decision_action") or "").rsplit(".", 1)[-1]
                             for c in choices).most_common(),
        "refresh_downgraded_to_hide": sum(1 for c in choices if c.get("downgraded_from")),
        "wood_unreadable": sum(1 for c in choices if c.get("wood") is None),
    }
    return {"rounds": rounds, "choices": ch}


def render(s: dict) -> str:
    out: list[str] = []
    for rid, d in s["rounds"].items():
        out.append(f"== 局 {rid} ==  采样 {d['samples']}（木材读不出 {d['wood_unreadable_samples']}）")
        out.append(f"  [1] 木材  {d['wood_first']} → {d['wood_last']}   峰值 {d['wood_peak']}"
                   f"   净 {d['wood_net']:+.0f}")
        if d["high_water_share"] is not None:
            out.append(f"      高位滞留（≥峰值80%）占采样 {d['high_water_share']*100:.0f}%")
        cr = d["conversion_rate"]
        out.append(f"  [2] 转化率  消耗 {d['wood_spent']:.0f} ÷ 进账 {d['wood_gained']:.0f}"
                   f" = {f'{cr*100:.0f}%' if cr is not None else '无法计算'}"
                   f"   （{d['wood_drop_samples']} 个采样出现下降）")
        out.append(f"      技能积压 min={d['skill_min']} max={d['skill_max']}")
        out.append("  [3] 决策机会分配：")
        total = sum(n for _, n in d["plan_allocation"]) or 1
        for name, n in d["plan_allocation"]:
            out.append(f"        {name:<22} {n:>4}  ({n*100//total}%)")
        out.append("")

    c = s["choices"]
    out.append(f"== [4] 面板决策  共 {c['total']} 次（木材读不出 {c['wood_unreadable']}）==")
    out.append("  按面板: " + "  ".join(f"{k}:{v}" for k, v in c["by_panel"]))
    out.append("  按动作: " + "  ".join(f"{k}:{v}" for k, v in c["by_action"]))
    out.append(f"  刷新因木材不足被降级成隐藏: {c['refresh_downgraded_to_hide']} 次")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    ticks = load(a.paths, "tick")
    choices = load(a.paths, "choice")
    if not ticks and not choices:
        print("没有找到 tick_*.jsonl / choice_*.jsonl", file=sys.stderr)
        return 2
    s = summarize(ticks, choices)
    print(json.dumps(s, ensure_ascii=False, indent=2) if a.json else render(s))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
