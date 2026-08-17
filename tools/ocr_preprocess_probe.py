#!/usr/bin/env python3
"""B2-2 快速预处理探针：PP-OCRv5 mobile rec 对游戏艺术字的 6 种预处理变体对比。

仅用于离线实验（不接运行时）；变体若显著改善再并入正式评测。
用法：.venv-ocr\\Scripts\\python.exe tools/ocr_preprocess_probe.py
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.vision.choice_ocr import normalize_choice_text  # noqa: E402

MODEL_DIR = ROOT / "models" / "ocr" / "PP-OCRv5_mobile_rec_infer"
STAGE_DIR = Path.home() / "AppData" / "Local" / "Temp" / "gamescript_ocr_stage" / "PP-OCRv5_mobile_rec_infer"
MANIFEST = ROOT / "fixtures" / "ocr_choices" / "manifest.json"


def stage_model() -> Path:
    if not STAGE_DIR.exists():
        STAGE_DIR.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(MODEL_DIR, STAGE_DIR)
    return STAGE_DIR


def make_variants(p: Path) -> dict[str, np.ndarray]:
    img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)
    bgr = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = bgr.shape
    big = cv2.resize(bgr, (w * 3, h * 3), interpolation=cv2.INTER_LANCZOS4)
    variants: dict[str, np.ndarray] = {"raw": img}
    # v1 灰度 3x + 自适应对比度
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    variants["gray3x_clahe"] = cv2.cvtColor(clahe.apply(big), cv2.COLOR_GRAY2BGR)
    # v2 Otsu 二值化（黑字白底）
    _, otsu = cv2.threshold(big, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants["gray3x_otsu"] = cv2.cvtColor(otsu, cv2.COLOR_GRAY2BGR)
    # v3 Otsu 反色（白字黑底）
    variants["gray3x_otsu_inv"] = cv2.cvtColor(255 - otsu, cv2.COLOR_GRAY2BGR)
    # v4 锐化
    blur = cv2.GaussianBlur(big, (0, 0), 2.0)
    sharp = cv2.addWeighted(big, 1.6, blur, -0.6, 0)
    variants["gray3x_sharpen"] = cv2.cvtColor(sharp, cv2.COLOR_GRAY2BGR)
    # v5 中值去噪 + 锐化
    den = cv2.medianBlur(big, 3)
    blur2 = cv2.GaussianBlur(den, (0, 0), 1.5)
    variants["gray3x_denoise_sharpen"] = cv2.cvtColor(cv2.addWeighted(den, 1.5, blur2, -0.5, 0), cv2.COLOR_GRAY2BGR)
    return variants


def main() -> int:
    import os
    from paddleocr import PaddleOCR

    os.environ.setdefault("PADDLE_PDX_MODEL_OFFLINE", "1")
    st = stage_model()
    print(f"[probe] staged model at {st}")
    from paddleocr._models.text_recognition import TextRecognition

    t0 = time.perf_counter()
    rec = TextRecognition(model_name="PP-OCRv5_mobile_rec", model_dir=str(st),
                          device="cpu", cpu_threads=10)
    print(f"[probe] model load {time.perf_counter() - t0:.2f}s")

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    samples: list[tuple[str, str]] = []  # (crop_path, canonical)
    for entry in manifest["entries"]:
        for slot in entry.get("slots", []):
            if not slot.get("is_valid"):
                continue
            name = slot.get("canonical_name")
            if not name:
                continue
            crop = next((c for c in entry.get("crops", [])
                         if c.endswith(f"_slot{slot['index']}_name.png")), None)
            if crop:
                samples.append((str(ROOT / crop), name))
    print(f"[probe] {len(samples)} valid name slots")

    results: dict[str, dict] = {}
    for vidx, vname in enumerate(("raw", "gray3x_clahe", "gray3x_otsu", "gray3x_otsu_inv", "gray3x_sharpen", "gray3x_denoise_sharpen")):
        hits = 0
        exact = 0
        total = 0
        lat = []
        for crop_path, truth in samples:
            variants = make_variants(Path(crop_path))
            tmp = ROOT / f"_probe_{vidx}.png"
            cv2.imencode(".png", variants[vname])[1].tofile(str(tmp))
            t1 = time.perf_counter()
            out = rec.predict(str(tmp))
            dt = (time.perf_counter() - t1) * 1000
            lat.append(dt)
            text = str(out[0].get("rec_text") or "") if out else ""
            total += 1
            n = normalize_choice_text(text)
            if n == normalize_choice_text(truth):
                exact += 1
            if n and truth in n:
                hits += 1
            tmp.unlink(missing_ok=True)
        lat = sorted(lat)
        results[vname] = {
            "exact": exact, "contains": hits, "total": total,
            "p50_ms": round(lat[len(lat) // 2], 1), "p95_ms": round(lat[int(len(lat) * 0.95)], 1),
        }
        print(f"[probe] {vname:<24} exact={exact}/{total} ({exact / total:.1%}) "
              f"contains={hits} p50={results[vname]['p50_ms']}ms p95={results[vname]['p95_ms']}ms")

    print(json.dumps(results, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
