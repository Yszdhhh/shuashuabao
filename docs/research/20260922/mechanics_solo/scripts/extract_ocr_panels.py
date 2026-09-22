# -*- coding: utf-8 -*-
"""Extract bond/stage/merchant price signals from panels + ocr_shadow + event reasons."""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

MAIN = Path(r"G:\刷刷宝\captures\hitch_lobby_chain_20260922_004851_422384")
CTMP = Path(r"C:\tmp\shuabao-captures")
OUT = Path(r"G:\刷刷宝\_facts_20260922\mechanics_solo\out")

STAGE_RE = re.compile(r"(\d+)-(\d+)")
BOND_TITLE_RE = re.compile(r"(.+?)\((\d+)/(\d+)\)")


def scan_ocr_shadow(path: Path, out: dict) -> None:
    if not path.exists():
        return
    kinds = Counter()
    panel_ids = Counter()
    bond_titles = Counter()
    bond_names = Counter()
    stage_hits = Counter()
    price_hits = Counter()
    samples = []
    n = 0
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            n += 1
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            pid = str(rec.get("panel_id") or rec.get("session") or "")
            panel_ids[pid] += 1
            raw = str(rec.get("raw_text") or "")
            name = str(rec.get("name") or "")
            cands = rec.get("candidates") or []
            text = raw or name
            if not text and cands:
                text = str(cands[0].get("name") if isinstance(cands[0], dict) else cands[0])
            # classify
            if any(k in pid for k in ("bond", "fetter", "card")):
                kinds["bond"] += 1
                m = BOND_TITLE_RE.search(text)
                if m:
                    bond_titles[m.group(1)] += 1
                else:
                    bond_titles[text] += 1
            elif "treasure" in pid:
                kinds["treasure"] += 1
            elif "skill" in pid:
                kinds["skill"] += 1
            elif "merchant" in pid or "black" in pid:
                kinds["merchant"] += 1
            else:
                kinds[pid or "?"] += 1
            for m in STAGE_RE.finditer(text):
                stage_hits[f"{m.group(1)}-{m.group(2)}"] += 1
            for pat in (r"木材\s*(\d+)", r"花费木材[^\d]*(\d+)", r"刷新\s*(\d+)", r"杀敌\s*(\d+)", r"\+(\d+(?:\.\d+)?)/?s?"):
                for m in re.finditer(pat, text):
                    price_hits[f"{pat}|{m.group(1)}"] += 1
            if len(samples) < 30 and text:
                samples.append({"panel_id": pid, "text": text[:80], "ts": rec.get("ts")})
    out["ocr_shadow_lines"] = n
    out["ocr_shadow_panel_ids"] = panel_ids.most_common(40)
    out["ocr_shadow_kinds"] = dict(kinds)
    out["ocr_shadow_bond_titles"] = bond_titles.most_common(40)
    out["ocr_shadow_stages"] = stage_hits.most_common(30)
    out["ocr_shadow_price_hits"] = price_hits.most_common(40)
    out["ocr_shadow_samples"] = samples


def scan_panels(bundle: Path, out: dict) -> None:
    panels = list(bundle.glob("incidents/**/panels/*.jpg")) + list(bundle.glob("incidents/**/panels/*.png"))
    out["panel_frames"] = len(panels)
    # inventory of panel meta if any json sidecars
    metas = list(bundle.glob("incidents/**/panels/*.json"))
    out["panel_meta_json"] = len(metas)


def scan_events_stages(man_path: Path, out: dict) -> None:
    if not man_path.exists():
        return
    man = json.loads(man_path.read_text(encoding="utf-8", errors="replace"))
    events = man.get("events") or []
    stage_first = {}
    stage_last = {}
    boss_reasons = Counter()
    giveup = 0
    hide = 0
    f_clicks = 0
    g_clicks = 0
    v_clicks = 0
    for ev in events:
        at = ev.get("at_s")
        act = ev.get("action") or {}
        reason = str(act.get("reason") or "")
        target = str(act.get("target") or "")
        blob = f"{reason} {target} {json.dumps(ev.get('evidence') or {}, ensure_ascii=False)[:200]}"
        for m in STAGE_RE.finditer(blob):
            key = f"{m.group(1)}-{m.group(2)}"
            if key not in stage_first:
                stage_first[key] = {"at_s": at, "event_id": ev.get("event_id")}
            stage_last[key] = {"at_s": at, "event_id": ev.get("event_id")}
        if "Boss" in reason or "boss" in reason:
            boss_reasons[reason] += 1
        if "giveUp" in reason or "giveup" in reason.lower():
            giveup += 1
        if "hide" in reason.lower() or "Hide" in reason:
            hide += 1
        if "bond" in reason.lower() or "fetter" in reason.lower() or "F:" in reason:
            f_clicks += 1
        if "skill" in reason.lower() and ("G" in reason or "skill" in reason.lower()):
            g_clicks += 1
        if "treasure" in reason.lower():
            v_clicks += 1
    out["stage_first"] = stage_first
    out["stage_last"] = stage_last
    out["boss_reasons"] = boss_reasons.most_common()
    out["giveup"] = giveup
    out["hide"] = hide
    out["bondish_actions"] = f_clicks
    out["skillish_actions"] = g_clicks
    out["treasureish_actions"] = v_clicks
    out["metrics"] = man.get("metrics") or {}
    # settings
    cps = (man.get("hitch_lobby_chain") or {}).get("checkpoints") or {}
    pre = (cps.get("PRECHECK_OK") or {}).get("evidence") or {}
    out["settings_snapshot"] = pre.get("settings_snapshot")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    bundles = [MAIN] + [d for d in sorted(CTMP.iterdir()) if d.is_dir() and (d / "trace.jsonl").exists()]
    for b in bundles:
        out = {"bundle": b.name}
        scan_ocr_shadow(b / "incidents" / "ocr_shadow.jsonl", out)
        if not out.get("ocr_shadow_lines"):
            scan_ocr_shadow(b / "ocr_shadow.jsonl", out)
        scan_panels(b, out)
        scan_events_stages(b / "manifest.json", out)
        (OUT / f"ocrpanels_{b.name}.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            b.name,
            "shadow",
            out.get("ocr_shadow_lines"),
            "panels",
            out.get("panel_frames"),
            "stages",
            list(out.get("stage_first", {}))[:12],
            "bonds",
            (out.get("ocr_shadow_bond_titles") or [None])[0],
        )


if __name__ == "__main__":
    main()
