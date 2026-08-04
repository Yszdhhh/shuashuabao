#!/usr/bin/env python3
"""Validate scenes.json templates exist under assets/Images."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGES = ROOT / "assets" / "Images"
SCENES = ROOT / "config" / "scenes.json"


def resolve(name: str) -> Path | None:
    n = name if name.lower().endswith(".png") else f"{name}.png"
    for c in [
        IMAGES / n,
        IMAGES / Path(n).name,
        IMAGES / "skills" / Path(n).name,
        IMAGES / "cards" / Path(n).name,
        IMAGES / "boss" / Path(n).name,
        IMAGES / "chuanjiaobao" / Path(n).name,
    ]:
        if c.is_file():
            return c
    stem = Path(n).stem
    for f in IMAGES.rglob("*.png"):
        if f.stem == stem:
            return f
    return None


def main() -> int:
    doc = json.loads(SCENES.read_text(encoding="utf-8"))
    missing: list[str] = []
    ok = 0
    for key, sc in doc.get("scenes", {}).items():
        for t in sc.get("templates") or []:
            if resolve(t):
                ok += 1
            else:
                missing.append(f"{key}: {t}")
    print(f"ok={ok} missing={len(missing)}")
    for m in missing:
        print(" MISSING", m)
    # list root pngs not referenced
    referenced = set()
    for sc in doc.get("scenes", {}).values():
        for t in sc.get("templates") or []:
            referenced.add(Path(t).stem)
    for name in doc.get("combat_templates_root_unclassified") or []:
        referenced.add(name)
    unref = []
    for f in IMAGES.glob("*.png"):
        if f.stem not in referenced:
            unref.append(f.name)
    print(f"root_unreferenced={len(unref)}")
    for u in sorted(unref)[:40]:
        print(" UNREF", u)
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
