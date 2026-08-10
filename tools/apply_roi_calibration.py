#!/usr/bin/env python3
"""把 designer 校准结果（C:/tmp/ocr_audit/batch_*.json）合并进 sources.json。

- 为每个正样本条目设置 roi_mode="per_slot" 与 slot["roi"]（name/progress 紧裁 bbox）；
- 不改动 truth 字段（truth 纠正/unknown 由 crop_ocr_choices.py 按词典自动处理）；
- 输出合并后的 sources.json 与覆盖报告（未覆盖面板/槽位清单）。

用法：
  python tools/apply_roi_calibration.py batch_0.json batch_1.json ... [--sources fixtures/ocr_choices/sources.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

VALID_SLOTS_BY_PANEL = {}


def load_batch(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "panels" not in data:
        raise ValueError(f"bad batch file {path}: missing 'panels'")
    return data


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("batches", nargs="+", type=Path)
    p.add_argument("--sources", type=Path, default=REPO_ROOT / "fixtures" / "ocr_choices" / "sources.json")
    p.add_argument("--out", type=Path, default=None, help="输出路径（默认覆盖 sources）")
    args = p.parse_args()

    sources_path = args.sources
    if not sources_path.exists():
        print(f"sources not found: {sources_path}")
        return 1
    sources = json.loads(sources_path.read_text(encoding="utf-8"))
    entries_by_id = {e["id"]: e for e in sources["entries"]}

    # 合并各 batch
    merged_panels: dict[str, dict] = {}
    for bpath in args.batches:
        batch = load_batch(bpath)
        for panel in batch["panels"]:
            pid = panel["id"]
            if pid in merged_panels:
                print(f"[warn] duplicate panel {pid} across batches; last wins")
            merged_panels[pid] = panel

    missing_entries = []
    covered_slots = 0
    total_slots = 0
    unverified_panels = []
    for pid, panel in sorted(merged_panels.items()):
        if pid not in entries_by_id:
            missing_entries.append(pid)
            continue
        entry = entries_by_id[pid]
        if entry["kind"] == "negative":
            continue
        entry["roi_mode"] = "per_slot"
        slots_by_idx = {s["index"]: s for s in entry.get("slots", [])}
        for ps in panel.get("slots", []):
            idx = ps["slot_index"]
            slot = slots_by_idx.get(idx)
            if slot is None:
                print(f"[warn] {pid}: slot {idx} not in sources")
                continue
            total_slots += 1
            if ps.get("verified") and ps.get("name_bbox"):
                roi = {"name": [round(float(v), 4) for v in ps["name_bbox"]]}
                if ps.get("progress_bbox"):
                    roi["progress"] = [round(float(v), 4) for v in ps["progress_bbox"]]
                else:
                    roi["progress"] = False
                slot["roi"] = roi
                covered_slots += 1
            else:
                slot.pop("roi", None)
                print(f"[unverified] {pid} slot {idx}: {ps.get('notes', 'no bbox')}")
        if any(s.get("roi") is None for s in entry.get("slots", [])):
            unverified_panels.append(pid)

    print(f"panels: merged={len(merged_panels)} missing_from_sources={len(missing_entries)}")
    print(f"slots: covered={covered_slots}/{total_slots}")
    print(f"unverified_panels={len(unverified_panels)}")

    out_path = args.out or sources_path
    out_path.write_text(json.dumps(sources, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"written: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
