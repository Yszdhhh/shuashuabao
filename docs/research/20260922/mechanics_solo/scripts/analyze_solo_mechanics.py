# -*- coding: utf-8 -*-
"""
Analyze hitch_lobby_chain / solo captures for solo in-game mechanics facts.
Read-only. Writes JSON summaries to out/.
Coverage: timeline, resources actions, bonds/OCR, treasure, black merchant.
"""
from __future__ import annotations

import json
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

MAIN = Path(r"G:\刷刷宝\captures\hitch_lobby_chain_20260922_004851_422384")
CTMP = Path(r"C:\tmp\shuabao-captures")
OUT = Path(r"G:\刷刷宝\_facts_20260922\mechanics_solo\out")


def load_trace(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            rec["_line"] = i
            rows.append(rec)
    return rows


def load_events(manifest_path: Path) -> list[dict]:
    data = json.loads(manifest_path.read_text(encoding="utf-8", errors="replace"))
    return data.get("events") or [], data


def pct(vals: list[float], p: float) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    frac = k - lo
    return s[lo] * (1 - frac) + s[hi] * frac


def analyze_bundle(bundle: Path) -> dict:
    trace_p = bundle / "trace.jsonl"
    man_p = bundle / "manifest.json"
    result: dict = {"bundle": str(bundle), "bundle_id": bundle.name}
    if not trace_p.exists():
        result["error"] = "no_trace"
        return result
    rows = load_trace(trace_p)
    result["trace_lines"] = len(rows)

    # --- timeline: MAIN_LINE segments ---
    segments = []  # (start_ts, end_ts, start_tick, end_tick, outcome)
    cur = None
    for r in rows:
        pb, pa = r.get("phase_before"), r.get("phase_after")
        ts = r.get("ts") or 0
        tick = r.get("tick")
        if pb != "MAIN_LINE" and pa == "MAIN_LINE":
            cur = {"start_ts": ts, "start_tick": tick, "start_line": r["_line"]}
        elif cur is not None and pb == "MAIN_LINE" and pa != "MAIN_LINE":
            cur["end_ts"] = ts
            cur["end_tick"] = tick
            cur["end_line"] = r["_line"]
            cur["duration_s"] = ts - cur["start_ts"]
            cur["exit_phase"] = pa
            s0 = r.get("s0") or {}
            cur["outcome"] = s0.get("round_outcome") or s0.get("last_outcome")
            cur["game_count"] = s0.get("game_count")
            segments.append(cur)
            cur = None
    if cur is not None:
        cur["end_ts"] = rows[-1].get("ts")
        cur["end_tick"] = rows[-1].get("tick")
        cur["duration_s"] = (rows[-1].get("ts") or 0) - cur["start_ts"]
        cur["exit_phase"] = "EOF"
        cur["outcome"] = (rows[-1].get("s0") or {}).get("round_outcome")
        segments.append(cur)
    result["ingame_segments"] = segments
    result["ingame_n"] = len(segments)
    durs = [s["duration_s"] for s in segments if s.get("duration_s")]
    if durs:
        result["duration_stats"] = {
            "n": len(durs),
            "min": min(durs),
            "p25": pct(durs, 0.25),
            "median": pct(durs, 0.5),
            "p75": pct(durs, 0.75),
            "max": max(durs),
            "mean": statistics.mean(durs),
            "values": durs,
        }

    # outcomes from s0 transitions
    outcomes = []
    for r in rows:
        s0 = r.get("s0") or {}
        if s0.get("round_outcome") and (
            not outcomes or outcomes[-1]["tick"] != r.get("tick")
        ):
            # record when outcome first set or changes
            if not outcomes or outcomes[-1]["value"] != s0["round_outcome"]:
                outcomes.append(
                    {
                        "tick": r.get("tick"),
                        "ts": r.get("ts"),
                        "value": s0["round_outcome"],
                        "game_count": s0.get("game_count"),
                        "line": r["_line"],
                    }
                )
    result["outcome_changes"] = outcomes

    # --- actions in MAIN_LINE ---
    action_re = Counter()
    decision_re = Counter()
    intents = Counter()
    merchant = []
    treasure_open = 0
    treasure_pick = 0
    treasure_refresh = 0
    bond_related = []
    skill_related = []
    swallow_pill = 0
    merchant_refresh = 0
    merchant_slots = Counter()
    stage_targets = Counter()
    giveup = 0
    f_hidden = 0
    wood_markers = []
    panel_names = Counter()
    for r in rows:
        if r.get("phase_after") != "MAIN_LINE" and r.get("phase_before") != "MAIN_LINE":
            continue
        dec = str(r.get("decision") or "")
        if dec:
            decision_re[dec] += 1
        for a in r.get("actions") or []:
            intent = str(a.get("intent") or "")
            reason = str(a.get("reason") or "")
            intents[f"{intent}|{reason}"] += 1
            action_re[reason] += 1
            if "BlackMerchant" in reason or "black_merchant" in intent:
                merchant.append(
                    {
                        "tick": r.get("tick"),
                        "ts": r.get("ts"),
                        "reason": reason,
                        "intent": intent,
                        "line": r["_line"],
                    }
                )
                if "refresh" in reason.lower():
                    merchant_refresh += 1
                if "swallow" in reason.lower():
                    swallow_pill += 1
                for m in re.finditer(r"slot[_ ]?(\d+)", intent):
                    merchant_slots[m.group(1)] += 1
            if "treasure" in reason.lower() or "Treasure" in reason:
                if "refresh" in reason:
                    treasure_refresh += 1
                elif "选择" in reason or "select" in reason.lower() or "pick" in reason.lower():
                    treasure_pick += 1
            if "OpenTreasurePanel" in reason:
                treasure_open += 1
            if "giveUp" in reason or "giveup" in reason.lower():
                giveup += 1
            if "hidden" in reason.lower() or "hide" in reason.lower():
                f_hidden += 1
        for p in r.get("panel") or []:
            panel_names[str(p.get("name"))] += 1
        # OCR suggestion may hold bond titles
        ocr = r.get("ocr_suggestion")
        if ocr:
            bond_related.append({"tick": r.get("tick"), "ts": r.get("ts"), "ocr": ocr, "line": r["_line"]})

    result["ingame_actions"] = action_re.most_common()
    result["ingame_decisions"] = decision_re.most_common()
    result["ingame_intents"] = intents.most_common()
    result["merchant_events"] = len(merchant)
    result["merchant_refresh"] = merchant_refresh
    result["swallow_pill_clicks"] = swallow_pill
    result["merchant_actions"] = merchant[:80]
    result["merchant_slots"] = dict(merchant_slots)
    result["treasure_open"] = treasure_open
    result["treasure_pick"] = treasure_pick
    result["treasure_refresh_sel"] = treasure_refresh
    result["giveup_actions"] = giveup
    result["hide_actions"] = f_hidden
    result["ingame_panels"] = panel_names.most_common()
    result["ocr_suggestion_samples"] = bond_related[:40]

    # --- events from manifest ---
    if man_p.exists():
        events, man = load_events(man_p)
        result["event_count"] = len(events)
        result["metrics"] = man.get("metrics") or {}
        ocr_kinds = Counter()
        bond_titles = Counter()
        bond_pieces = Counter()
        treasure_cards = Counter()
        treasure_descs = []
        skill_cards = Counter()
        redish = []
        stage_hits = []
        for ev in events:
            ocr = (ev.get("evidence") or {}).get("ocr")
            if not ocr:
                continue
            kind = ocr.get("kind") or "?"
            ocr_kinds[kind] += 1
            slots = ocr.get("slots") or []
            # slots may be dict-like strings or dicts
            for s in slots:
                if isinstance(s, str):
                    try:
                        s = json.loads(s)
                    except Exception:
                        continue
                name = s.get("name") or ""
                raw = s.get("raw_text") or name
                desc = s.get("description") or ""
                rarity = s.get("rarity") or s.get("rarity_letter") or ""
                if kind in ("bond", "fetter", "card"):
                    # title layer often has (x/y)
                    m = re.match(r"(.+?)\((\d+)/(\d+)\)\s*$", raw.strip())
                    if m:
                        bond_titles[m.group(1)] += 1
                        bond_pieces[f"{m.group(1)}({m.group(2)}/{m.group(3)})"] += 1
                    else:
                        bond_titles[raw.strip()] += 1
                elif kind == "treasure":
                    treasure_cards[name or raw] += 1
                    if desc:
                        treasure_descs.append(
                            {
                                "event_id": ev.get("event_id"),
                                "at_s": ev.get("at_s"),
                                "name": name,
                                "desc": desc,
                            }
                        )
                elif kind == "skill":
                    skill_cards[name or raw] += 1
                if desc and any(
                    k in desc
                    for k in (
                        "清0",
                        "清 0",
                        "恒定",
                        "无法",
                        "扣除",
                        "随机",
                        "翻倍",
                        "-35%",
                        "-15%",
                        "-70%",
                        "提高50%",
                        "提高50",
                    )
                ):
                    redish.append(
                        {
                            "event_id": ev.get("event_id"),
                            "at_s": ev.get("at_s"),
                            "kind": kind,
                            "name": name,
                            "desc": desc,
                        }
                    )
            # stage from decision/actions
            for a in (ev.get("action") or {},):
                pass
            fsm = ev.get("fsm_state") or {}
            # skip
        result["ocr_kinds"] = dict(ocr_kinds)
        result["bond_title_counts"] = bond_titles.most_common(50)
        result["bond_progress_tokens"] = bond_pieces.most_common(80)
        result["treasure_card_counts"] = treasure_cards.most_common(50)
        result["treasure_desc_samples"] = treasure_descs[:40]
        result["skill_card_counts"] = skill_cards.most_common(30)
        result["negativeish_desc"] = redish[:40]

        # bond progress timeline
        bond_timeline = []
        for ev in events:
            ocr = (ev.get("evidence") or {}).get("ocr")
            if not ocr or ocr.get("kind") not in ("bond", "fetter", "card"):
                continue
            titles = []
            for s in ocr.get("slots") or []:
                if isinstance(s, str):
                    try:
                        s = json.loads(s)
                    except Exception:
                        continue
                raw = s.get("raw_text") or s.get("name") or ""
                titles.append(raw)
            if titles:
                bond_timeline.append(
                    {"event_id": ev.get("event_id"), "at_s": ev.get("at_s"), "titles": titles}
                )
        result["bond_timeline_n"] = len(bond_timeline)
        result["bond_timeline"] = bond_timeline[:200]

        # MAIN_LINE action timing relative to segment starts
        ml_actions = []
        for ev in events:
            if ev.get("phase_after") != "MAIN_LINE" and ev.get("phase_before") != "MAIN_LINE":
                continue
            act = ev.get("action") or {}
            if not act:
                continue
            ml_actions.append(
                {
                    "event_id": ev.get("event_id"),
                    "at_s": ev.get("at_s"),
                    "reason": act.get("reason"),
                    "kind": act.get("kind"),
                    "target": act.get("target"),
                }
            )
        result["ml_actions_n"] = len(ml_actions)
        # classify per segment
        for seg in segments:
            t0 = seg["start_ts"]
            # events use at_s relative to run start; convert via trace ts
            pass

        # classify merchant / treasure / F / G / V from decisions across all events
        reason_counter = Counter()
        for ev in events:
            act = ev.get("action") or {}
            reason_counter[str(act.get("reason"))] += 1
        result["event_action_reasons"] = reason_counter.most_common(40)

    return result


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    bundles = []
    if (MAIN / "trace.jsonl").exists():
        bundles.append(MAIN)
    if CTMP.exists():
        for d in sorted(CTMP.iterdir()):
            if d.is_dir() and (d / "trace.jsonl").exists():
                bundles.append(d)
    summaries = []
    for b in bundles:
        try:
            s = analyze_bundle(b)
        except Exception as e:
            s = {"bundle": str(b), "error": repr(e)}
        summaries.append(s)
        outp = OUT / f"summary_{b.name}.json"
        outp.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
        n = s.get("ingame_n", 0)
        print(f"{b.name}: lines={s.get('trace_lines')} ingame_n={n} err={s.get('error')}")

    # aggregate across bundles with ingame_n>0
    agg = {"bundles_with_ingame": 0, "total_ingame_segments": 0, "durations": [], "merchant": [], "treasure": []}
    for s in summaries:
        n = s.get("ingame_n") or 0
        if n > 0:
            agg["bundles_with_ingame"] += 1
            agg["total_ingame_segments"] += n
            if s.get("duration_stats"):
                agg["durations"].extend(s["duration_stats"]["values"])
            agg["merchant"].append(
                {
                    "bundle": s["bundle_id"],
                    "events": s.get("merchant_events"),
                    "refresh": s.get("merchant_refresh"),
                    "swallow_pill": s.get("swallow_pill_clicks"),
                    "slots": s.get("merchant_slots"),
                }
            )
            agg["treasure"].append(
                {
                    "bundle": s["bundle_id"],
                    "open": s.get("treasure_open"),
                    "pick": s.get("treasure_pick"),
                    "refresh_sel": s.get("treasure_refresh_sel"),
                }
            )
    d = agg["durations"]
    if d:
        agg["duration_stats"] = {
            "n": len(d),
            "min": min(d),
            "p25": pct(d, 0.25),
            "median": pct(d, 0.5),
            "p75": pct(d, 0.75),
            "max": max(d),
            "mean": statistics.mean(d),
            "values": d,
        }
    (OUT / "aggregate.json").write_text(
        json.dumps(agg, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("aggregate:", json.dumps({k: v for k, v in agg.items() if k != "durations"}, ensure_ascii=False)[:500])


if __name__ == "__main__":
    main()
