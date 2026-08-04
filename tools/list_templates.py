#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGES = ROOT / "assets" / "Images"


def main() -> None:
    if not IMAGES.is_dir():
        print("missing", IMAGES)
        return
    by: dict[str, list[str]] = {}
    for f in sorted(IMAGES.rglob("*.png")):
        rel = f.relative_to(IMAGES)
        key = str(rel.parent) if rel.parent != Path(".") else "(root)"
        by.setdefault(key, []).append(rel.name)
    for k, files in by.items():
        print(f"\n## {k} ({len(files)})")
        for name in files:
            print(f"  {name}")
    print(f"\nTOTAL {sum(len(v) for v in by.values())}")


if __name__ == "__main__":
    main()
