#!/usr/bin/env python3
"""B2-2 打包可行性最小 CLI：加载 rec 模型 → 对单张裁剪图推理 → 打印 JSON。

仅用于 PyInstaller 冷启动/离线/体积评测（B2-2 验收项），不接入游戏、无任何输入动作权。
用法：ocr_cli_min.py <model_dir_ascii> <image_path>
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 3:
        print(json.dumps({"error": "usage: ocr_cli_min.py <model_dir> <image_path>"}))
        return 2
    model_dir, image_path = sys.argv[1], sys.argv[2]
    t0 = time.perf_counter()
    from paddleocr._models.text_recognition import TextRecognition
    rec = TextRecognition(model_name="PP-OCRv5_mobile_rec", model_dir=model_dir,
                          device="cpu", cpu_threads=4)
    load_s = time.perf_counter() - t0
    t1 = time.perf_counter()
    out = rec.predict(image_path)
    dt = (time.perf_counter() - t1) * 1000
    text = str(out[0].get("rec_text") or "") if out else ""
    score = float(out[0].get("rec_score") or 0.0) if out else 0.0
    print(json.dumps({
        "text": text, "score": round(score, 4),
        "load_s": round(load_s, 3), "infer_ms": round(dt, 1),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
