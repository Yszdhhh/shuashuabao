# -*- coding: utf-8 -*-
"""Scan gameplay videos for skill-card selection frames and OCR card names.

Usage: python tools/scan_card_frames_20260821.py <video> [step_sec]
Writes hits to stdout as JSON lines: {t, name, box}
"""
import json
import sys

import cv2
from rapidocr_onnxruntime import RapidOCR

# Broad fuzzy keys on purpose: OCR misreads (箭/简/剪, 场/坊) happen; every hit
# is visually verified afterwards, and raw ocr_text is kept for disambiguation
# (e.g. 电磁场 vs 电磁网, 奥术箭矢 vs 奥术激光).
FUZZY = {"奥术": "奥术?", "箭矢增": "箭矢增幅", "齐射": "箭矢齐射",
         "连发": "箭矢连发", "爆炸增": "爆炸增伤", "小冰": "小冰箭", "电磁": "电磁?"}


def norm(s):
    return s.replace(" ", "")


def match(text):
    t = norm(text)
    for k, canonical in FUZZY.items():
        if k in t:
            return canonical
    return None


def main():
    video = sys.argv[1]
    step = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
    ocr = RapidOCR()
    cap = cv2.VideoCapture(video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    step_frames = max(1, int(round(fps * step)))
    seen = set()
    idx = 0
    while True:
        ok = cap.grab()
        if not ok:
            break
        if idx % step_frames == 0:
            ok, frame = cap.retrieve()
            if not ok:
                break
            t = idx / fps
            scale = 1280.0 / frame.shape[1]
            small = cv2.resize(frame, (1280, int(frame.shape[0] * scale))) if scale < 1 else frame
            result, _ = ocr(small)
            if result:
                sx = frame.shape[1] / small.shape[1]
                sy = frame.shape[0] / small.shape[0]
                for box, text, conf in result:
                    canon = match(text)
                    if canon and conf > 0.4:
                        key = (canon, text, round(t / 5))
                        if key in seen:
                            continue
                        seen.add(key)
                        xs = [p[0] for p in box]; ys = [p[1] for p in box]
                        print(json.dumps({
                            "video": video, "t": round(t, 2),
                            "mmss": f"{int(t)//60:02d}:{int(t)%60:02d}",
                            "name": canon, "ocr_text": text, "conf": round(conf, 2),
                            "box": [int(min(xs)*sx), int(min(ys)*sy), int(max(xs)*sx), int(max(ys)*sy)],
                        }, ensure_ascii=False), flush=True)
        idx += 1
    cap.release()


if __name__ == "__main__":
    main()
