#!/usr/bin/env python3
"""O1 从素材帧按 显式 per-slot bbox 裁剪三槽选择面板（卡名 + 套装进度），生成 OCR 数据集。

用法：
  python tools/crop_ocr_choices.py sources.json --out fixtures/ocr_choices \
      --contact-sheet docs/baselines/O1_contact_sheet

sources.json 是人工/视觉标注输入（一条记录对应一个面板帧或负样本帧），
本工具负责机械部分：

O1 相比 B2 版的关键变化：
  1. 显式布局 bbox：每个正样本面板必须给出 面板级 layout + 逐槽位
     slot["roi"] = {"name": [x0,y0,x1,y1], "progress": [..] 或 None/False}
     （归一化坐标，紧裁卡名与套装进度文字）。禁止对未知布局静默使用全局
     fallback ROI；无显式 bbox 的槽位标 layout_status="unverified_layout"，
     不裁该项，也不进入准确率分母（evaluator 侧校验）。
  2. manifest 记录每槽最终生效 bbox（归一化 + 像素）、来源帧、分辨率、session、
     truth 规范名（与 config/choice_lexicon.json 对齐：别名纠正为规范名，
     词典外标 truth_status=unknown 且 canonical_name=null）。
  3. ROI 硬约束保留：所有裁剪框下沿 rel_y <= 0.620（按钮区 0.67-0.79）。
  4. 生成 100% 覆盖 contact sheet：每面板 原图缩略 + 各 name/progress crop +
     truth 标签（图片集合 + HTML/JSON 汇总索引），供 designer 人工审核。

输入条目字段：
  id, frame, kind(skill|bond|treasure|negative|dragonball), session_id, source,
  window_size(可选，缺省读图), game_version, refresh_count, has_giveup,
  has_hide, has_refresh, expected_click_slot, forbidden_area,
  roi_mode(可选；O1 要求 per_slot 或显式 layout), slots(逐槽 {index,
  canonical_name, raw_text, rarity, set_progress, is_valid, is_dragon_ball,
  roi(可选, {"name": [...], "progress": [...]|None|False})}),
  negative_reason(仅 negative), notes(可选)

输出：裁剪图 + manifest.json(schema_version 2) + contact sheet + 违规报告。
退出码：0=全部通过；2=存在违规 ROI 被拒绝；其他>0=输入/IO 错误。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from gamescript.vision.choice_ocr import (  # noqa: E402
    load_lexicon,
    normalize_choice_text,
)

# 归一化 ROI 规范（x0,y0,x1,y1；相对分辨率，与 1600x900 同比例）——B2 遗留默认值，
# 仅用于 roi_mode=three_slot/dragon_ball 的旧输入；O1 新输入一律 per_slot 显式 bbox。
SLOT_X = [(0.230, 0.400), (0.415, 0.585), (0.600, 0.770)]
NAME_Y = (0.230, 0.350)
PROGRESS_Y = (0.360, 0.450)
DRAGON_NAME_ROI = (0.435, 0.565, 0.250, 0.340)
DRAGON_PROGRESS_ROI = (0.435, 0.565, 0.350, 0.420)
# 硬约束：任何裁剪框下沿不得超过该归一化 y
MAX_ROI_BOTTOM_Y = 0.620
BUTTON_STRIP_Y = (0.67, 0.79)  # 暂时隐藏/放弃/刷新 按钮区（禁止点击）
# Frozen blind-test layout prior (O3 correction, 1600x900 only).  These
# bands are deliberately wider than the O1 per-sample bboxes and are never
# adjusted from the truth label or OCR result.
FROZEN_NAME_Y_BANDS = {
    "skill": (0.160, 0.250),    # O1 cross-session median y0 ~= 0.174
    "bond": (0.250, 0.350),     # O1 cross-session median y0 ~= 0.270
    "treasure": (0.170, 0.270), # O1 cross-session median y0 ~= 0.186
}


def frozen_roi_for_slot(kind: str, slot_index: int, field: str = "name") -> tuple[float, float, float, float]:
    """Return the immutable blind-test ROI for one 1600x900 slot.

    ``kind`` and ``slot_index`` select only the frozen layout prior.  No
    manifest bbox, truth label, or detection result is consulted.
    """
    if kind not in FROZEN_NAME_Y_BANDS:
        raise ValueError(f"unsupported blind-test kind: {kind!r}")
    if slot_index not in range(len(SLOT_X)):
        raise ValueError(f"slot index must be 0..{len(SLOT_X) - 1}: {slot_index!r}")
    if field == "name":
        y0, y1 = FROZEN_NAME_Y_BANDS[kind]
    elif field == "progress":
        y0, y1 = PROGRESS_Y
    else:
        raise ValueError(f"unsupported blind-test field: {field!r}")
    x0, x1 = SLOT_X[slot_index]
    return (x0, y0, x1, y1)




def truth_status_of(canonical: str | None, lexicon: dict) -> str:
    """truth 归类（与 evaluator 一致）：in_lexicon / alias_covered / unknown。"""
    if not canonical:
        return "unknown"
    entries = lexicon["entries"]
    if canonical in entries:
        return "in_lexicon"
    for canon, entry in entries.items():
        if canonical in entry.get("aliases", []):
            return "alias_covered"
    return "unknown"


def canonical_for(canonical: str | None, lexicon: dict) -> str | None:
    """纠正别名 → 词典规范名；词典外返回 None（标 unknown）。"""
    if not canonical:
        return None
    entries = lexicon["entries"]
    if canonical in entries:
        return canonical
    for canon, entry in entries.items():
        if canonical in entry.get("aliases", []):
            return canon
    return None


def roi_boxes_for_slot(entry: dict, slot: dict, w: int, h: int) -> dict:
    """返回该槽位 (name_roi, progress_roi, status) 归一化 ROI 与布局状态。

    - per_slot：显式 slot["roi"]；缺失的部件不回落全局默认 → status=unverified_layout；
    - three_slot / dragon_ball：B2 遗留全局 ROI（旧输入兼容；O1 不再新增此类）。
    """
    mode = entry.get("roi_mode", "per_slot")
    idx = slot.get("index", 0)
    if not 0 <= idx < 3:
        raise ValueError(f"slot index out of range: {idx}")
    if mode == "per_slot":
        sr = slot.get("roi") or {}
        name = sr.get("name")
        prog = sr.get("progress")
        if name is None or not _valid_roi_tuple(name):
            return {"name": None, "progress": None, "status": "unverified_layout"}
        if prog is False:
            prog = None
        if prog is not None and not _valid_roi_tuple(prog):
            return {"name": None, "progress": None, "status": "unverified_layout"}
        return {"name": tuple(name), "progress": tuple(prog) if prog else None,
                "status": "verified"}
    if mode == "dragon_ball":
        return {"name": DRAGON_NAME_ROI, "progress": DRAGON_PROGRESS_ROI,
                "status": "verified"}
    # three_slot（遗留）
    x0, x1 = SLOT_X[idx]
    return {"name": (x0, x1, *NAME_Y), "progress": (x0, x1, *PROGRESS_Y),
            "status": "verified"}


def _valid_roi_tuple(roi) -> bool:
    if not isinstance(roi, (list, tuple)) or len(roi) != 4:
        return False
    try:
        x0, y0, x1, y1 = (float(v) for v in roi)
    except (TypeError, ValueError):
        return False
    return 0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0


def to_px(roi, w, h):
    """归一化 (x0,y0,x1,y1) → 像素 (left, top, right, bottom)。"""
    if not roi:
        return None
    x0, y0, x1, y1 = roi
    return (int(round(x0 * w)), int(round(y0 * h)),
            int(round(x1 * w)), int(round(y1 * h)))


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


def process_entry(entry: dict, out: Path, violations: list, copies: list, lexicon: dict) -> dict | None:
    """裁剪 + 复制源帧，返回 manifest 条目（schema 2）；违规返回 None。"""
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
        status = boxes["status"]
        slot_crops = []
        ok = True
        bbox_record = {}
        for part, box in (("name", boxes["name"]), ("progress", boxes["progress"])):
            if box is None:
                bbox_record[part] = None
                continue
            reason = validate_roi(to_px(box, w, h), w, h)
            if reason:
                violations.append({"id": eid, "slot": sidx, "part": part, "reason": reason})
                ok = False
                continue
            rel = out / kind / session / f"{stem}_slot{sidx}_{part}.png"
            crop_and_save(img, to_px(box, w, h), rel)
            written.append(rel)
            slot_crops.append(str(rel).replace("\\", "/"))
            crop_paths.append(str(rel).replace("\\", "/"))
            bbox_record[part] = {
                "normalized": [round(float(v), 4) for v in box],
                "pixels": list(to_px(box, w, h)),
            }
        if not ok:
            for rel in written:
                rel.unlink(missing_ok=True)
            return None

        truth_raw = slot.get("canonical_name")
        tstatus = truth_status_of(truth_raw, lexicon)
        canon_out = canonical_for(truth_raw, lexicon)
        slot_crop_map = {"name": None, "progress": None}
        # slot_crops 按 part 顺序记录（name, progress）
        for part, box in (("name", boxes["name"]), ("progress", boxes["progress"])):
            if box is None:
                continue
            rel = out / kind / session / f"{stem}_slot{sidx}_{part}.png"
            slot_crop_map[part] = str(rel).replace("\\", "/")
        slots.append({
            "index": sidx,
            "canonical_name": canon_out,
            "canonical_corrected_from": truth_raw if (tstatus == "alias_covered" and canon_out != truth_raw) else None,
            "raw_text": slot.get("raw_text"),
            "rarity": slot.get("rarity"),
            "set_progress": slot.get("set_progress"),
            "is_valid": slot.get("is_valid", False),
            "is_dragon_ball": slot.get("is_dragon_ball", False),
            "truth_status": tstatus,
            "layout_status": status,
            "crops": slot_crop_map,
            "roi": {
                "name": [round(float(v), 4) for v in boxes["name"]] if boxes["name"] else None,
                "progress": [round(float(v), 4) for v in boxes["progress"]] if boxes["progress"] else None,
            },
            "roi_px": bbox_record or None,
            "bbox_source_frame": str(Path(entry["frame"])).replace("\\", "/"),
        })
        crops.append(slot_crops)

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


# ---------------------------------------------------------------------------
# contact sheet（O1-12：52 面板 100% 覆盖人工审核材料）
# ---------------------------------------------------------------------------
def _load_font(size: int):
    for cand in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(cand, size)
        except Exception:  # noqa: BLE001
            continue
    return ImageFont.load_default()


def render_panel_sheet(entry: dict, frame_img: Image.Image, out_path: Path) -> None:
    """每面板一张审核图：原图缩略 + 各 name/progress crop + truth 标签。"""
    font = _load_font(14)
    font_sm = _load_font(11)
    w, h = entry["window_size"]
    thumb_w = 420
    thumb_h = int(h * thumb_w / w)
    thumb = frame_img.resize((thumb_w, thumb_h), Image.LANCZOS)
    # 收集各槽 crop
    rows = []
    for slot in entry["slots"]:
        if not slot.get("is_valid"):
            continue
        label = f"slot{slot['index']}: {slot.get('canonical_name') or 'UNKNOWN'} | {slot.get('truth_status')} | {slot.get('layout_status')}"
        if slot.get("set_progress"):
            label += f" | progress={slot['set_progress']}"
        if slot.get("is_dragon_ball"):
            label += " | DB"
        rows.append((label, slot))
    # 组合画布：上方缩略图，下方每槽一行（name crop + progress crop + 标签）
    crop_max_w = 340
    line_h = 64
    sheet_h = thumb_h + 26 + max(1, len(rows)) * line_h + 16
    sheet = Image.new("RGB", (thumb_w + 360, sheet_h), (30, 30, 30))
    d = ImageDraw.Draw(sheet)
    sheet.paste(thumb, (4, 4))
    d.text((4, 4), f"{entry['id']}  {entry['panel_kind']}  {w}x{h}  {entry['session_id']}",
           fill=(255, 255, 120), font=font)
    y = thumb_h + 30
    for label, slot in rows:
        d.text((4, y), label, fill=(255, 255, 255), font=font_sm)
        x = 4
        s_crops = slot.get("crops") if isinstance(slot.get("crops"), dict) else {}
        name_crop = s_crops.get("name")
        prog_crop = s_crops.get("progress")
        if name_crop is None and slot.get("roi", {}).get("name") is not None:
            i = slot["index"]
            if len(entry["crops"]) == 2 * len(entry["slots"]):
                name_crop = entry["crops"][2 * i]
                prog_crop = entry["crops"][2 * i + 1]
            elif len(entry["crops"]) == len(entry["slots"]):
                name_crop = entry["crops"][i]
        if name_crop and Path(name_crop).exists():
            c = Image.open(name_crop).convert("RGB")
            if c.width > crop_max_w:
                c = c.resize((crop_max_w, max(1, int(c.height * crop_max_w / c.width))), Image.LANCZOS)
            sheet.paste(c, (x, y + 16))
            x += c.width + 8
        if prog_crop and Path(prog_crop).exists():
            c = Image.open(prog_crop).convert("RGB")
            if c.width > crop_max_w:
                c = c.resize((crop_max_w, max(1, int(c.height * crop_max_w / c.width))), Image.LANCZOS)
            sheet.paste(c, (x, y + 16))
        y += line_h
    sheet.save(out_path)


def build_contact_sheet(manifest: dict, out_dir: Path, frame_root: Path) -> dict:
    """为全部正样本面板生成单面板审核图 + HTML/JSON 汇总索引。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    index_rows = []
    for e in manifest["entries"]:
        if e["panel_kind"] == "negative":
            continue
        fpath = frame_root / e["original_frame"]
        img = Image.open(fpath).convert("RGB")
        dest = out_dir / f"{e['id']}.png"
        render_panel_sheet(e, img, dest)
        unverified = any(s.get("layout_status") == "unverified_layout" for s in e["slots"])
        index_rows.append(
            {
                "id": e["id"], "kind": e["panel_kind"], "session": e["session_id"],
                "resolution": e["window_size"], "sheet": str(dest.relative_to(out_dir.parent.parent)).replace("\\", "/"),
                "slots": [
                    {
                        "index": s["index"], "canonical": s.get("canonical_name"),
                        "truth_status": s.get("truth_status"), "layout_status": s.get("layout_status"),
                        "roi": s.get("roi"),
                    }
                    for s in e["slots"]
                ],
                "unverified_layout": unverified,
            }
        )
    # HTML 索引
    html_lines = [
        "<!doctype html><html><head><meta charset='utf-8'><title>O1 OCR crop contact sheet</title></head><body>",
        f"<h1>O1 OCR crop contact sheet（{len(index_rows)} 面板）</h1>",
        "<p>每面板：原图缩略 + 逐槽 name/progress 紧裁 crop + truth 标签。红字=unverified_layout。</p>",
    ]
    for row in index_rows:
        badge = " style='color:red'" if row["unverified_layout"] else ""
        slots_txt = "; ".join(
            f"s{s['index']}={s['canonical'] or 'UNKNOWN'}({s['truth_status']})" for s in row["slots"]
        )
        html_lines.append(
            f"<h2 id='{row['id']}'><span{badge}>{row['id']}</span> — {row['kind']} {row['resolution'][0]}x{row['resolution'][1]} {row['session']}</h2>"
            f"<p>{slots_txt}</p>"
            f"<img src='{row['sheet']}' loading='lazy' alt='{row['id']}' style='max-width:1200px'/><hr/>"
        )
    html_lines.append("</body></html>")
    (out_dir / "index.html").write_text("\n".join(html_lines), encoding="utf-8")
    (out_dir / "index.json").write_text(
        json.dumps(index_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "sheets": len(index_rows),
        "html": str(out_dir / "index.html"),
        "json": str(out_dir / "index.json"),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("sources", type=Path, help="标注输入 sources.json")
    p.add_argument("--out", type=Path, default=Path("fixtures/ocr_choices"))
    p.add_argument("--violations", type=Path, default=None, help="违规报告输出路径")
    p.add_argument("--contact-sheet", type=Path, default=None,
                   help="contact sheet 输出目录（默认不生成）")
    p.add_argument("--lexicon", type=Path, default=None, help="词典路径（默认 config/choice_lexicon.json）")
    args = p.parse_args()

    if not args.sources.exists():
        print(f"sources not found: {args.sources}")
        return 1
    data = json.loads(args.sources.read_text(encoding="utf-8"))
    entries = data["entries"]
    game_version = data.get("game_version", "unknown")
    lexicon = load_lexicon(args.lexicon) if args.lexicon else load_lexicon()

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    violations: list = []
    copies: list = []
    manifest_entries: list = []

    for entry in entries:
        try:
            m = process_entry(entry, out, violations, copies, lexicon)
        except Exception as exc:  # noqa: BLE001
            print(f"[error] entry {entry.get('id')}: {exc}")
            return 1
        if m is not None:
            manifest_entries.append(m)

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

    # O1 统计：truth/layout 状态
    truth_dist: dict[str, int] = {}
    layout_dist: dict[str, int] = {}
    slot_roi_covered = 0
    slot_total = 0
    for e in manifest_entries:
        if e["panel_kind"] == "negative":
            continue
        for s in e["slots"]:
            if not s.get("is_valid"):
                continue
            slot_total += 1
            truth_dist[s.get("truth_status", "unknown")] = truth_dist.get(s.get("truth_status", "unknown"), 0) + 1
            layout_dist[s.get("layout_status", "unverified_layout")] = layout_dist.get(s.get("layout_status", "unverified_layout"), 0) + 1
            if s.get("roi", {}).get("name") is not None:
                slot_roi_covered += 1

    stats = {
        "total_entries": len(manifest_entries),
        "panel_counts": {k: len(by_kind[k]) for k in kinds},
        "dimension_distribution": {f"{w}x{h}": len(ids) for (w, h), ids in sorted(dims.items(), key=lambda kv: (kv[0][0], kv[0][1]))},
        "sessions": sessions,
        "slot_stats": {
            "valid_slots": slot_total,
            "slots_with_explicit_roi": slot_roi_covered,
            "truth_status_distribution": truth_dist,
            "layout_status_distribution": layout_dist,
        },
        "960x540_gap": {
            "present": sum(1 for (w, h) in dims if (w, h) == (960, 540)),
            "requirement": "技能/羁绊/宝物 各至少 10 张 960x540（进入生产候选门槛），当前素材缺口",
            "note": "本阶段现有素材以 1600x900/1586x892 为主，960x540 仅少量；缺口如实记录，后续 shadow 收集补足，不降低门槛。",
        },
        "roi_violations_rejected": len(violations),
    }

    manifest = {
        "schema_version": 2,
        "purpose": "O1 OCR 离线数据集：显式 per-slot bbox 紧裁（卡名+套装进度）+ 负样本；蓝图 §9 O1",
        "game_version": game_version,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "roi_spec": {
            "coordinate_system": "normalized to frame resolution (x0,y0,x1,y1; 0..1)",
            "per_slot_bbox": "slot.roi = {name: [x0,y0,x1,y1], progress: [x0,y0,x1,y1]|null|false} — 每个有效槽必须显式给出（O1），紧裁卡名/计数器文字",
            "legacy_three_slot": {"slot_x": [[0.230, 0.400], [0.415, 0.585], [0.600, 0.770]], "name_y": [0.230, 0.350], "progress_y": [0.360, 0.450]},
            "hard_constraint": f"all crop box bottoms <= rel_y {MAX_ROI_BOTTOM_Y} (button strip {BUTTON_STRIP_Y[0]}-{BUTTON_STRIP_Y[1]}, giveUp 0.945 misdetection lesson)",
            "unverified_layout": "无显式 bbox 的槽位标 unverified_layout、不裁剪、不进准确率分母（evaluator 校验）",
        },
        "stats": stats,
        "entries": manifest_entries,
    }

    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"entries: total={len(manifest_entries)} rejected={len(violations)}")
    print("panel_counts: " + json.dumps({k: len(by_kind[k]) for k in kinds}, ensure_ascii=False))
    print("slot_stats: " + json.dumps(stats["slot_stats"], ensure_ascii=False))
    print("dimensions: " + json.dumps({f"{w}x{h}": len(ids) for (w, h), ids in sorted(dims.items(), key=lambda kv: (kv[0][0], kv[0][1]))}, ensure_ascii=False))
    print("sessions: " + json.dumps(sessions, ensure_ascii=False))
    for v in violations:
        print(f"[violation] {v['id']} slot{v.get('slot')} {v.get('part')}: {v['reason']}")
    if args.violations:
        args.violations.write_text(json.dumps(violations, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.contact_sheet:
        cs = build_contact_sheet(manifest, args.contact_sheet, out)
        print(f"contact sheet: {cs['sheets']} panels -> {cs['html']} + {cs['json']}")
    return 2 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
