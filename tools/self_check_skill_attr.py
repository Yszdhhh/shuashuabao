"""Standalone self-check: 16 core skills and their primary attribute tags.

Stdlib only (json + pathlib), no shuabao imports. Mirrors the physical/magical
partition in src/shuabao/smart_route.py RouteEvaluator._fallback_routes:
magical -> intelligence (智力), physical -> agility (敏捷); strength (力量) is
a bond route with no dedicated skill preset (official_strategy_defaults.json
attr_routes._comment).
"""
from __future__ import annotations

import json
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / "config"

# Ground truth: smart_route.py _fallback_routes
MAGICAL_INTELLIGENCE = {"asj", "asjg", "assx", "tl", "sdl", "dcw", "hq", "byj", "hbj", "bsxx"}
PHYSICAL_AGILITY = {"jq", "pg", "ys", "dz", "ljf", "jf"}

labels = json.loads((CONFIG / "skill_labels.json").read_text(encoding="utf-8"))
labels = {k: v for k, v in labels.items() if not k.startswith("_")}
meta = json.loads((CONFIG / "skill_meta.json").read_text(encoding="utf-8"))["skills"]

tagged = MAGICAL_INTELLIGENCE | PHYSICAL_AGILITY
assert len(MAGICAL_INTELLIGENCE) == 10, "magical set must have 10 skills"
assert len(PHYSICAL_AGILITY) == 6, "physical set must have 6 skills"
assert not (MAGICAL_INTELLIGENCE & PHYSICAL_AGILITY), "attribute tags must not overlap"
assert tagged == set(labels), f"tagged codes != skill_labels codes: {tagged ^ set(labels)}"
assert tagged == set(meta), f"tagged codes != skill_meta codes: {tagged ^ set(meta)}"

for code in sorted(tagged):
    attr = "intelligence/智力" if code in MAGICAL_INTELLIGENCE else "agility/敏捷"
    print(f"{code:5s} {labels[code]:6s} -> {attr}")

print(f"\nPASS: {len(tagged)} core skills, all tagged, labels/meta consistent.")
