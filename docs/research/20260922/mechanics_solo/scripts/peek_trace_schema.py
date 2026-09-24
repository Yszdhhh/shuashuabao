# -*- coding: utf-8 -*-
"""Peek hitch_lobby_chain trace.jsonl schema and in-game event shapes (read-only)."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

TRACE = Path(r"G:\刷刷宝\captures\hitch_lobby_chain_20260922_004851_422384\trace.jsonl")


def main() -> None:
    phases = Counter()
    contexts = Counter()
    decisions = Counter()
    intents = Counter()
    panel_names = Counter()
    sample_keys = set()
    n = 0
    ingame = []
    for line in TRACE.open(encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        n += 1
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        sample_keys |= set(rec.keys())
        phases[rec.get("phase_after") or rec.get("phase_before")] += 1
        contexts[rec.get("context")] += 1
        dec = rec.get("decision")
        if dec:
            decisions[str(dec)[:80]] += 1
        for a in rec.get("actions") or []:
            intents[str(a.get("intent"))[:60]] += 1
        for p in rec.get("panel") or []:
            panel_names[str(p.get("name"))] += 1
        # detect in-game-ish
        ctx = (rec.get("context") or "") + " " + (rec.get("phase_after") or "")
        if any(k in ctx for k in ("INGAME", "MAIN", "SOLO", "GAME", "IN_GAME", "L1", "PANEL", "BATTLE")):
            if len(ingame) < 3:
                ingame.append(rec)
        # also look for HUD-like fields
    print(f"lines={n}")
    print("phases:", phases.most_common(20))
    print("contexts:", contexts.most_common(20))
    print("top decisions:", decisions.most_common(30))
    print("top intents:", intents.most_common(30))
    print("top panels:", panel_names.most_common(30))
    print("keys:", sorted(sample_keys))
    if ingame:
        print("--- sample ingame rec ---")
        print(json.dumps(ingame[0], ensure_ascii=False)[:2000])
    else:
        # dump one rec with non-lobby phase
        for line in TRACE.open(encoding="utf-8", errors="replace"):
            rec = json.loads(line)
            if (rec.get("phase_after") or "") not in ("LOBBY_ROOM", "LOBBY_SEARCH", None):
                print("--- non-lobby ---")
                print(json.dumps(rec, ensure_ascii=False)[:2500])
                break


if __name__ == "__main__":
    main()
