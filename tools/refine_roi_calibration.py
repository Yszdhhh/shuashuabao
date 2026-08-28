#!/usr/bin/env python3
"""OCR 引导的 ROI 精修 v2：会话-类别几何先验 + 带内搜索。

v1 教训：
1. designer 视觉校准对 y 不可靠（同 session 结果互相矛盾）→ 全范围 y 搜索；
2. 全范围搜索会把卡面描述文字（y≈0.37-0.45，可能包含卡名字符）误判为卡名
   （如 '剑气' ⊂ '道剑气' 描述行）→ 必须用 会话+面板类别 的先验 y 带约束；
3. 2 字符卡名（剑气/魔术）相似度天然偏低 → 先验带内搜索 + 适度放宽。

流程：
- 第一遍：读取输入 batch（designer 校准）做全范围 y 搜索（v1 逻辑），得到初步 bbox；
- 计算每个 (session, panel_kind) 的卡名 y 带中位数（稳健几何）；
- 第二遍：全部槽位在 [med_y0-0.03, med_y0+0.03] 带内重新搜索（x 为 designer x±0.04），
  卡名分数下限 0.45；失败槽位标 unverified_layout，由 contact sheet 人工复核。
- 进度计数器（x/y）同样带内搜索（先验带 = 该槽位已确认卡名带下方 0.08-0.16）。

用法（.venv-ocr）：
  python tools/refine_roi_calibration.py C:/tmp/ocr_audit/batch_0.json ... \
      --out C:/tmp/ocr_audit/refined3 --manifest fixtures/ocr_choices/manifest.json

输出：refined3/<batch>.json（与输入同构，bbox 替换为精修值，新增 refiner 字段）。
"""
from __future__ import annotations

import argparse
import collections
import json
import shutil
import statistics
import sys
import tempfile
from difflib import SequenceMatcher
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shuabao.vision.choice_ocr import normalize_choice_text  # noqa: E402

NAME_HEIGHT_NORM = 0.056   # ~50px @900
PROG_HEIGHT_NORM = 0.036   # ~32px @900
NAME_SCORE_FLOOR = 0.45
PROG_SCORE_FLOOR = 0.45
BAND_HALF = 0.030
X_PAD = 0.04


def _load_frame_bgr(path: Path):
    import cv2
    import numpy as np

    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"cannot decode frame: {path}")
    return img


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


class Refiner:
    def __init__(self, cpu_threads: int = 10):
        stage = Path(tempfile.mkdtemp()) / "m"
        shutil.copytree(REPO_ROOT / "models" / "ocr" / "PP-OCRv5_mobile_rec_infer", stage)
        from paddleocr._models.text_recognition import TextRecognition

        self._stage = stage
        self._rec = TextRecognition(
            model_name="PP-OCRv5_mobile_rec", model_dir=str(stage), device="cpu", cpu_threads=cpu_threads
        )
        self._tmpdir = Path(tempfile.mkdtemp())

    def close(self) -> None:
        self._rec.close()
        shutil.rmtree(self._stage, ignore_errors=True)

    def _ocr(self, frame, box) -> str:
        import cv2
        from PIL import Image, ImageEnhance

        x0, y0, x1, y1 = box
        crop = frame[y0:y1, x0:x1]
        if crop.size == 0:
            return ""
        pil = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
        pil = pil.resize((pil.width * 2, pil.height * 2), Image.LANCZOS)
        pil = ImageEnhance.Contrast(pil).enhance(1.5)
        tmp = self._tmpdir / "c.png"
        pil.save(tmp)
        r = self._rec.predict(str(tmp))[0]
        return str(r.get("rec_text") or "")

    def refine_name_band(self, frame, w, h, designer_box, truth_raw: str,
                         band_y0: float | None, x_pad: float = X_PAD,
                         name_floor: float = NAME_SCORE_FLOOR) -> dict:
        """在 (session,kind) 先验 y 带内找卡名。band_y0=None → 全范围兜底。"""
        x0 = max(0.12, designer_box[0] - x_pad)
        x1 = min(0.88, designer_box[2] + x_pad)
        hh = NAME_HEIGHT_NORM
        if band_y0 is not None:
            y_top = max(0.10, band_y0 - BAND_HALF)
            # 窗口起点范围 = 带 ± BAND_HALF（窗口可高出带顶，保证能完整罩住文字）
            y_bot = min(0.52, band_y0 + BAND_HALF)
        else:
            y_top, y_bot = 0.12, 0.50
        best = None
        y0 = y_top
        while y0 + hh <= y_bot + hh + 1e-6:
            box = (int(x0 * w), int(y0 * h), int(x1 * w), int((y0 + hh) * h))
            txt = normalize_choice_text(self._ocr(frame, box))
            truth = normalize_choice_text(truth_raw)
            score = _similarity(txt, truth)
            if best is None or score > best["score"]:
                best = {"y0": y0, "score": score, "ocr": txt}
            y0 += 0.004
        if best is None or best["score"] < name_floor:
            return {"verified": False,
                    "reason": f"band search best {best['score'] if best else 0:.2f} < {name_floor}"}
        y0 = best["y0"]
        y1 = y0 + hh
        # 保守 x 紧裁：阈值放低、且不得小于搜索范围 55%（防字符间隙截断文字）
        xext = self._tight_x(frame, w, h, x0, x1, y0, y1)
        if xext[1] - xext[0] < 0.55 * (x1 - x0):
            xext = (x0, x1)
        return {
            "verified": True,
            "bbox": [round(xext[0], 4), round(y0, 4), round(xext[1], 4), round(y1, 4)],
            "ocr": best["ocr"],
            "score": round(best["score"], 3),
            "method": "band_ocr_y_sweep+tight_x(conservative)",
        }

    def refine_progress_band(self, frame, w, h, designer_box, truth: str, name_y0: float) -> dict:
        """进度计数器：在卡名带下方 0.07-0.18 区域搜索（x 用 designer 进度 x 范围）。"""
        if designer_box is not None:
            x0 = max(0.12, designer_box[0] - X_PAD)
            x1 = min(0.88, designer_box[2] + X_PAD)
        else:
            x0, x1 = 0.22, 0.78
        y_top = max(0.12, name_y0 + 0.07)
        y_bot = min(0.55, name_y0 + 0.20)
        best = None
        y0 = y_top
        hh = PROG_HEIGHT_NORM
        while y0 + hh <= y_bot + hh + 1e-6:
            box = (int(x0 * w), int(y0 * h), int(x1 * w), int((y0 + hh) * h))
            txt = self._ocr(frame, box)
            norm = normalize_choice_text(txt)
            truth_norm = normalize_choice_text(truth)
            if truth_norm and truth_norm in norm:
                score = 1.0
            else:
                score = _similarity(norm, truth_norm) * 0.6
            if best is None or score > best["score"]:
                best = {"y0": y0, "score": score, "ocr": norm}
            y0 += 0.004
        if best is None or best["score"] < PROG_SCORE_FLOOR:
            return {"verified": False, "reason": f"progress band search best {best['score'] if best else 0:.2f}"}
        y0 = best["y0"]
        y1 = y0 + hh
        xext = self._tight_x(frame, w, h, x0, x1, y0, y1)
        return {
            "verified": True,
            "bbox": [round(xext[0], 4), round(y0, 4), round(xext[1], 4), round(y1, 4)],
            "ocr": best["ocr"],
            "score": round(best["score"], 3),
            "method": "progress_band_ocr_y_sweep+tight_x",
        }

    @staticmethod
    def _tight_x(frame, w, h, x0, x1, y0, y1) -> tuple[float, float]:
        import numpy as np

        band = frame[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
        gray = band.mean(axis=2) if band.ndim == 3 else band
        bright = (gray > 110).sum(axis=0)
        cols = np.where(bright > 0)[0]
        if len(cols) < 3:
            return (x0, x1)
        pad = 6 / w
        return (max(0.0, x0 + cols.min() / w - pad), min(1.0, x0 + cols.max() / w + pad))


def _compute_band_priors(batches: list[dict], entries_by_id: dict, exclude: set[str] | None = None) -> dict:
    """(session, kind) -> median name y0（来自已 verified 槽位；排除指定面板）。"""
    exclude = exclude or set()
    rows = collections.defaultdict(list)
    for batch in batches:
        for panel in batch["panels"]:
            if panel["id"] in exclude:
                continue
            e = entries_by_id[panel["id"]]
            for ps in panel["slots"]:
                nb = ps.get("refiner", {}).get("name") or {}
                if nb.get("verified") and nb.get("bbox"):
                    rows[(e["session_id"], e["panel_kind"])].append(nb["bbox"][1])
    return {k: statistics.median(v) for k, v in rows.items() if v}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("batches", nargs="+", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--manifest", type=Path, default=REPO_ROOT / "fixtures" / "ocr_choices" / "manifest.json")
    p.add_argument("--cpu-threads", type=int, default=10)
    p.add_argument("--priors-from", type=Path, default=None,
                   help="从已有精修 batch 目录计算先验带，跳过第一遍全范围搜索（加速）")
    p.add_argument("--name-floor", type=float, default=NAME_SCORE_FLOOR,
                   help="卡名相似度下限（默认 0.45；带内搜索可适度放低）")
    p.add_argument("--exclude-panels", nargs="*", default=[],
                   help="跳过这些面板（已由模板匹配复核定标，不参与精修/先验）")
    args = p.parse_args()
    NAME_FLOOR = args.name_floor
    exclude = set(args.exclude_panels)

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    entries_by_id = {e["id"]: e for e in manifest["entries"]}
    args.out.mkdir(parents=True, exist_ok=True)

    refiner = Refiner(args.cpu_threads)
    try:
        if args.priors_from:
            # 从 priors-from 目录读取精修结果计算先验带；输入 batch 仍从 args.batches 读
            prior_batches = []
            for f in sorted(args.priors_from.glob("batch_*.json")):
                prior_batches.append(json.loads(f.read_text(encoding="utf-8")))
            priors = _compute_band_priors(prior_batches, entries_by_id, exclude)
            prelim = []
            for bpath in args.batches:
                batch = json.loads(bpath.read_text(encoding="utf-8"))
                for panel in batch["panels"]:
                    if panel["id"] in exclude:
                        continue
                    e = entries_by_id[panel["id"]]
                    prior = priors.get((e["session_id"], e["panel_kind"]))
                    frame = _load_frame_bgr(REPO_ROOT / e["original_frame"])
                    h, w = frame.shape[:2]
                    truth_by_idx = {s["index"]: s for s in e["slots"]}
                    for ps in panel["slots"]:
                        slot = truth_by_idx.get(ps["slot_index"])
                        if slot is None or not ps.get("verified") or not ps.get("name_bbox"):
                            continue
                        ps.setdefault("_orig_name_bbox", list(ps["name_bbox"]))
                        # 直接用先验带搜索（带内），不再全范围
                        nb = refiner.refine_name_band(frame, w, h, ps["name_bbox"], slot.get("raw_text") or "", prior, name_floor=NAME_FLOOR)
                        if nb.get("verified"):
                            ps["name_bbox"] = nb["bbox"]
                            ps["refiner"] = {"name": nb}
                        else:
                            ps["verified"] = False
                            ps.pop("name_bbox", None)
                            ps["notes"] = (ps.get("notes", "") + " | " + nb["reason"]).strip()
                        if ps.get("progress_bbox") and slot.get("set_progress") and nb.get("verified"):
                            pb = refiner.refine_progress_band(frame, w, h, ps["progress_bbox"], slot["set_progress"], nb["bbox"][1])
                            if pb.get("verified"):
                                ps["progress_bbox"] = pb["bbox"]
                                ps["refiner"]["progress"] = pb
                            else:
                                ps["progress_bbox"] = None
                                ps["notes"] = (ps.get("notes", "") + " | progress: " + pb["reason"]).strip()
                prelim.append(batch)
            print("band priors (from --priors-from):")
            for k, v in sorted(priors.items()):
                print(f"  {k[0][:22]:24s} {k[1]:8s} y0={v:.3f}")
        else:
            # 第一遍：全范围搜索初步 bbox（旧逻辑）
            for bpath in args.batches:
                batch = json.loads(bpath.read_text(encoding="utf-8"))
                for panel in batch["panels"]:
                    e = entries_by_id[panel["id"]]
                    frame = _load_frame_bgr(REPO_ROOT / e["original_frame"])
                    h, w = frame.shape[:2]
                    truth_by_idx = {s["index"]: s for s in e["slots"]}
                    for ps in panel["slots"]:
                        slot = truth_by_idx.get(ps["slot_index"])
                        if slot is None or not ps.get("verified") or not ps.get("name_bbox"):
                            continue
                        ps.setdefault("_orig_name_bbox", list(ps["name_bbox"]))
                        nb = refiner.refine_name_band(frame, w, h, ps["name_bbox"], slot.get("raw_text") or "", None, x_pad=0.02)
                        if nb.get("verified"):
                            ps["name_bbox"] = nb["bbox"]
                            ps["refiner"] = {"name": nb}
                        else:
                            ps["verified"] = False
                            ps.pop("name_bbox", None)
                            ps["notes"] = (ps.get("notes", "") + " | " + nb["reason"]).strip()
                        if ps.get("progress_bbox") and slot.get("set_progress") and nb.get("verified"):
                            pb = refiner.refine_progress_band(frame, w, h, ps["progress_bbox"], slot["set_progress"], nb["bbox"][1])
                            if pb.get("verified"):
                                ps["progress_bbox"] = pb["bbox"]
                                ps["refiner"]["progress"] = pb
                            else:
                                ps["progress_bbox"] = None
                                ps["notes"] = (ps.get("notes", "") + " | progress: " + pb["reason"]).strip()
                prelim.append(batch)

            # 先验带
            priors = _compute_band_priors(prelim, entries_by_id, exclude)
            print("band priors (session,kind)->name_y0 median:")
            for k, v in sorted(priors.items()):
                print(f"  {k[0][:22]:24s} {k[1]:8s} y0={v:.3f}")

        # 第二遍：全部槽位带内重搜
        final = []
        for batch in prelim:
            n_ok = n_bad = 0
            for panel in batch["panels"]:
                e = entries_by_id[panel["id"]]
                frame = _load_frame_bgr(REPO_ROOT / e["original_frame"])
                h, w = frame.shape[:2]
                truth_by_idx = {s["index"]: s for s in e["slots"]}
                for ps in panel["slots"]:
                    slot = truth_by_idx.get(ps["slot_index"])
                    if slot is None:
                        continue
                    prior = priors.get((e["session_id"], e["panel_kind"]))
                    cur = ps.get("refiner", {}).get("name") or {}
                    needs_research = (not cur.get("verified")) or (
                        prior is not None and abs(cur["bbox"][1] - prior) > BAND_HALF
                    )
                    if needs_research and prior is not None:
                        # 未验证或离群（描述文字陷阱）→ 带内重搜
                        search_box = (
                            ps.get("name_bbox")
                            or ps.get("_orig_name_bbox")
                            or [0.20, 0.15, 0.44, 0.35]
                        )
                        nb = refiner.refine_name_band(frame, w, h, search_box, slot.get("raw_text") or "", prior, name_floor=NAME_FLOOR)
                        if nb.get("verified"):
                            ps["verified"] = True
                            ps["name_bbox"] = nb["bbox"]
                            ps["refiner"] = {"name": nb}
                            if slot.get("set_progress"):
                                pb = refiner.refine_progress_band(frame, w, h, ps.get("progress_bbox"), slot["set_progress"], nb["bbox"][1])
                                if pb.get("verified"):
                                    ps["progress_bbox"] = pb["bbox"]
                                    ps["refiner"]["progress"] = pb
                                else:
                                    ps["progress_bbox"] = None
                                    ps["notes"] = (ps.get("notes", "") + " | progress: " + pb["reason"]).strip()
                        else:
                            ps["verified"] = False
                            ps["notes"] = (ps.get("notes", "") + " | band re-search failed: " + nb["reason"]).strip()
                    if ps.get("verified"):
                        n_ok += 1
                    else:
                        n_bad += 1
            final.append(batch)
        for idx, batch in enumerate(final):
            out_path = args.out / f"batch_{idx}.json"
            out_path.write_text(json.dumps(batch, ensure_ascii=False, indent=1), encoding="utf-8")
            n_ok = sum(1 for panel in batch["panels"] for ps in panel["slots"] if ps.get("verified"))
            n_tot = sum(1 for panel in batch["panels"] for ps in panel["slots"])
            print(f"batch_{idx}.json: verified={n_ok}/{n_tot} -> {out_path}")
    finally:
        refiner.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
