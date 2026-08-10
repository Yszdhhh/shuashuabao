#!/usr/bin/env python3
"""从素材帧按固定 ROI 裁剪三槽选择面板（卡名 + 套装进度），生成 OCR 数据集。

用法：
  python tools/crop_ocr_choices.py sources.json --out fixtures/ocr_choices

sources.json 是人工/视觉标注输入（一条记录对应一个面板帧或负样本帧），
本工具负责机械部分：

  - 按归一化 ROI 裁剪每个槽位的卡名与套装进度（保持原分辨率原样裁，不缩放）；
  - ROI 硬约束：所有裁剪框下沿 rel_y <= 0.620（按钮区 0.67-0.79，含
    '暂时隐藏/放弃/刷新'；此前 giveUp 模板在 rel_y 0.945 处的误检教训）；
    违规记录直接拒绝，不写任何裁剪图，并计入违规报告；
  - 源帧复制进 fixtures/ocr_choices/frames/<session_id>/（正样本）或
    negatives/<session_id>/（负样本），保证数据集自包含；
  - 汇总写出 fixtures/ocr_choices/manifest.json（含逐条元数据与顶部 stats）。

ROI 规范（1600x900 归一化坐标；任意分辨率按同比例缩放）：

  三槽卡名：Slot0 x=[0.230,0.400] Slot1 x=[0.415,0.585] Slot2 x=[0.600,0.770]
             y=[0.230,0.350]
  套装进度：与卡名同 x 范围，y=[0.360,0.450]
  龙珠卡：  卡名 [0.435,0.565]x[0.250,0.340]，套装进度 [0.435,0.565]x[0.350,0.420]

  roi_mode 取值：three_slot（默认）| dragon_ball | per_slot
  - per_slot 时逐槽位取 slot["roi"] = {"name": [x0,y0,x1,y1], "progress": [...]}
    （归一化坐标），用于混合布局（如三槽面板中间槽是龙珠卡）。

输入条目字段：
  id, frame, kind(skill|bond|treasure|negative|dragonball), session_id, source,
  window_size(可选，缺省读图), game_version, refresh_count, has_giveup,
  has_hide, has_refresh, expected_click_slot, forbidden_area,
  roi_mode(可选), slots(逐槽 {index, canonical_name, raw_text, rarity,
  set_progress, is_valid, is_dragon_ball, roi(可选)}),
  negative_reason(仅 negative), notes(可选)

输出：裁剪图 + manifest.json + 违规报告（stdout + --violations 路径）。
退出码：0=全部通过；2=存在违规 ROI 被拒绝；其他>0=输入/IO 错误。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from PIL import Image

# 归一化 ROI 规范（x0,y0,x1,y1；相对分辨率，与 1600x900 同比例）
SLOT_X = [(0.230, 0.400), (0.415, 0.585), (0.600, 0.770)]
NAME_Y = (0.230, 0.350)
PROGRESS_Y = (0.360, 0.450)
DRAGON_NAME_ROI = (0.435, 0.565, 0.250, 0.340)
DRAGON_PROGRESS_ROI = (0.435, 0.565, 0.350, 0.420)
# 硬约束：任何裁剪框下沿不得超过该归一化 y
MAX_ROI_BOTTOM_Y = 0.620
BUTTON_STRIP_Y = (0.67, 0.79)  # 暂时隐藏/放弃/刷新 按钮区（禁止点击）


def roi_boxes_for_slot(entry: dict, slot: dict, w: int, h: int) -> dict:
    """返回该槽位 (name_roi, progress_roi) 像素框；None 表示该槽不裁该项。"""
    mode = entry.get("roi_mode", "three_slot")
    idx = slot.get("index", 0)
    if not 0 <= idx < 3:
        raise ValueError(f"slot index out of range: {idx}")
    if mode == "per_slot":
        # 显式 ROI 覆盖；未给出的槽位回落到三槽默认 ROI；progress=False 显式跳过
        sr = slot.get("roi") or {}
        name = sr.get("name")
        prog = sr.get("progress")
        if name is None:
            x0, x1 = SLOT_X[idx]
            name = (x0, x1, *NAME_Y)
        if prog is None:
            x0, x1 = SLOT_X[idx]
            prog = (x0, x1, *PROGRESS_Y)
        if prog is False:
            prog = None
    elif mode == "dragon_ball":
        name = DRAGON_NAME_ROI
        prog = DRAGON_PROGRESS_ROI
    else:  # three_slot
        x0, x1 = SLOT_X[idx]
        name = (x0, x1, *NAME_Y)
        prog = (x0, x1, *PROGRESS_Y)

    def to_px(roi):
        # roi 约定为 (x0, x1, y0, y1)（x 范围在前，y 范围在后）；
        # PIL crop 需要 (left, top, right, bottom) = (x0, y0, x1, y1)。
        if not roi:
            return None
        x0, x1, y0, y1 = roi
        return (int(round(x0 * w)), int(round(y0 * h)),
                int(round(x1 * w)), int(round(y1 * h)))

    return {"name": to_px(name), "progress": to_px(prog)}


def validate_roi(box, w, h) -> str | None:
    """返回违规原因；None 表示通过。硬约束：下沿 rel_y <= MAX_ROI_BOTTOM_Y。"""
    if box is None:
        return None
    x0, y0, x1, y1 = box
    if x0 < 0 or y0 < 0 or x1 > w or y1 > h or x1 <= x0 or y1 <= y0:
        return f"box out of frame or degenerate: {box} vs frame {w}x{h}"
    bottom = y1 / h
    if bottom > MAX_ROI_BOTTOM_Y:
        return (f"ROI bottom rel_y={bottom:.3f} > {MAX_ROI_BOTTOM_Y} "
                f"(button strip {BUTTON_STRIP_Y[0]}-{BUTTON_STRIP_Y[1]}, "
                f"giveUp 0.945 misdetection lesson): box={box} frame={w}x{h}")
    return None


def crop_and_save(img, box, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.crop(box).save(dest)


def load_entry_frame(entry: dict) -> tuple[Image.Image, int, int]:
    frame = Path(entry["frame"])
    if not frame.exists():
        raise FileNotFoundError(f"frame not found: {frame}")
    img = Image.open(frame).convert("RGB")
    return img, img.width, img.height


def process_entry(entry: dict, out: Path, violations: list, copies: list) -> dict | None:
    """裁剪 + 复制源帧，返回 manifest 条目；违规返回 None 并记入 violations。"""
    eid = entry["id"]
    kind = entry["kind"]
    session = entry["session_id"]
    stem = Path(entry["frame"]).stem

    if kind == "negative":
        dest_frame = out / "negatives" / session / Path(entry["frame"]).name
        if not dest_frame.exists():
            dest_frame.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(entry["frame"], dest_frame)
        copies.append((entry["frame"], str(dest_frame)))
        with Image.open(dest_frame) as _im:
            _w, _h = _im.size
        return {"id": eid, "panel_kind": "negative", "negative_reason": entry.get("negative_reason", ""),
                "original_frame": str(dest_frame).replace("\\", "/"), "crops": [],
                "window_size": [_w, _h], "game_version": entry.get("game_version", "unknown"),
                "session_id": session, "source": entry.get("source", "unknown"),
                "forbidden_area": None, "slots": [], "notes": entry.get("notes")}

    img, w, h = load_entry_frame(entry)
    crops: list[str] = []
    crop_paths: list[str] = []
    written: list[Path] = []
    slots = []
    for slot in entry.get("slots", []):
        sidx = slot.get("index")
        boxes = roi_boxes_for_slot(entry, slot, w, h)
        slot_crops = []
        ok = True
        for part, box in (("name", boxes["name"]), ("progress", boxes["progress"])):
            if box is None:
                continue
            reason = validate_roi(box, w, h)
            if reason:
                violations.append({"id": eid, "slot": sidx, "part": part, "reason": reason})
                ok = False
                continue
            rel = out / kind / session / f"{stem}_slot{sidx}_{part}.png"
            crop_and_save(img, box, rel)
            written.append(rel)
            slot_crops.append(str(rel).replace("\\", "/"))
            crop_paths.append(str(rel).replace("\\", "/"))
        # 整条记录任一槽位违规则整条拒绝，并清理本条目已写出的裁剪图
        if not ok:
            for rel in written:
                rel.unlink(missing_ok=True)
            return None
        crops.append(slot_crops)
        slots.append({
            "index": slot.get("index"),
            "canonical_name": slot.get("canonical_name"),
            "raw_text": slot.get("raw_text"),
            "rarity": slot.get("rarity"),
            "set_progress": slot.get("set_progress"),
            "is_valid": slot.get("is_valid", False),
            "is_dragon_ball": slot.get("is_dragon_ball", False),
        })

    # 复制源帧到 frames/<session>/
    dest_frame = out / "frames" / session / Path(entry["frame"]).name
    if not dest_frame.exists():
        dest_frame.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(entry["frame"], dest_frame)
    copies.append((entry["frame"], str(dest_frame)))

    return {
        "id": eid,
        "panel_kind": kind,
        "original_frame": str(dest_frame).replace("\\", "/"),
        "crops": crop_paths,
        "window_size": [w, h],
        "game_version": entry.get("game_version", "unknown"),
        "session_id": session,
        "source": entry.get("source", "unknown"),
        "refresh_count": entry.get("refresh_count", 0),
        "has_giveup": entry.get("has_giveup", False),
        "has_hide": entry.get("has_hide", False),
        "has_refresh": entry.get("has_refresh", False),
        "expected_click_slot": entry.get("expected_click_slot"),
        "forbidden_area": entry.get("forbidden_area", {"x": [0.0, 1.0], "y": list(BUTTON_STRIP_Y)}),
        "slots": slots,
        "notes": entry.get("notes"),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("sources", type=Path, help="标注输入 sources.json")
    p.add_argument("--out", type=Path, default=Path("fixtures/ocr_choices"))
    p.add_argument("--violations", type=Path, default=None, help="违规报告输出路径")
    args = p.parse_args()

    if not args.sources.exists():
        print(f"sources not found: {args.sources}")
        return 1
    data = json.loads(args.sources.read_text(encoding="utf-8"))
    entries = data["entries"]
    game_version = data.get("game_version", "unknown")

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    violations: list = []
    copies: list = []
    manifest_entries: list = []

    for entry in entries:
        try:
            m = process_entry(entry, out, violations, copies)
        except Exception as exc:  # noqa: BLE001
            print(f"[error] entry {entry.get('id')}: {exc}")
            return 1
        if m is not None:
            manifest_entries.append(m)

    # stats（龙珠卡面板归类为 treasure，不单独计类）
    kinds = ["skill", "bond", "treasure", "negative"]
    by_kind = {k: [e for e in manifest_entries if e["panel_kind"] == k] for k in kinds}
    dims = {}
    for e in manifest_entries:
        if e["panel_kind"] == "negative":
            img = Image.open(e["original_frame"])
            dims.setdefault(tuple(img.size), []).append(e["id"])
        else:
            dims.setdefault(tuple(e["window_size"]), []).append(e["id"])
    sessions = sorted({e["session_id"] for e in manifest_entries})

    stats = {
        "total_entries": len(manifest_entries),
        "panel_counts": {k: len(by_kind[k]) for k in kinds},
        "dimension_distribution": {f"{w}x{h}": len(ids) for (w, h), ids in sorted(dims.items(), key=lambda kv: (kv[0][0], kv[0][1]))},
        "sessions": sessions,
        "960x540_gap": {
            "present": sum(1 for (w, h) in dims if (w, h) == (960, 540)),
            "requirement": "技能/羁绊/宝物 各至少 10 张 960x540（进入生产候选门槛），当前素材缺口",
            "note": "本阶段现有素材以 1600x900/1586x892 为主，960x540 仅少量；缺口如实记录，后续 shadow 收集补足，不降低门槛。",
        },
        "roi_violations_rejected": len(violations),
    }

    manifest = {
        "schema_version": 1,
        "purpose": "B2-1 OCR 离线数据集（三槽选择面板卡名+套装进度裁剪 + 负样本），蓝图 §8 B2-1",
        "game_version": game_version,
        "roi_spec": {
            "coordinate_system": "normalized to frame resolution (1600x900 reference; any resolution scaled same ratio)",
            "three_slot_card_name": {"slot_x": [[0.230, 0.400], [0.415, 0.585], [0.600, 0.770]], "y": [0.230, 0.350]},
            "set_progress": {"x": "same as card name slot", "y": [0.360, 0.450]},
            "dragon_ball_card_name": {"x": [0.435, 0.565], "y": [0.250, 0.340]},
            "dragon_ball_set_progress": {"x": [0.435, 0.565], "y": [0.350, 0.420]},
            "hard_constraint": f"all crop box bottoms <= rel_y {MAX_ROI_BOTTOM_Y} (button strip {BUTTON_STRIP_Y[0]}-{BUTTON_STRIP_Y[1]}, giveUp 0.945 misdetection lesson)",
        },
        "stats": stats,
        "entries": manifest_entries,
    }

    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"entries: total={len(manifest_entries)} rejected={len(violations)}")
    print("panel_counts: " + json.dumps({k: len(by_kind[k]) for k in kinds}, ensure_ascii=False))
    print("dimensions: " + json.dumps({f"{w}x{h}": len(ids) for (w, h), ids in sorted(dims.items(), key=lambda kv: (kv[0][0], kv[0][1]))}, ensure_ascii=False))
    print("sessions: " + json.dumps(sessions, ensure_ascii=False))
    for v in violations:
        print(f"[violation] {v['id']} slot{v.get('slot')} {v.get('part')}: {v['reason']}")
    if args.violations:
        args.violations.write_text(json.dumps(violations, ensure_ascii=False, indent=2), encoding="utf-8")
    return 2 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
