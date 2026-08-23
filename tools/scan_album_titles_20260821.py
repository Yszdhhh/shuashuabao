# -*- coding: utf-8 -*-
"""Dense scan of the card-album region for card titles.

Usage: python tools/scan_album_titles_20260821.py <video> <t0> <t1> [step]
OCR only the album card grid (x150-1340, y120-720) every `step` seconds;
emit short title-like texts with timestamps.
"""
import json
import sys

import cv2
from rapidocr_onnxruntime import RapidOCR

NOISE = ("前置", "排斥", "伤害", "解锁", "级", "+", "系统", "点击", "战斗", "选择",
         "卡牌", "刷新", "放弃", "免费", "进入", "攻击", "冷却", "数量", "范围",
         "穿透", "持续", "命中", "目标", "分裂", "附魔", "射出", "发射", "召唤",
         "获得", "不再", "造成", "提高", "降低", "额外", "概率", "触发", "秒",
         "%，", "%，", "（", "(", "]", "】")


def title_like(t):
    if not (2 <= len(t) <= 8):
        return False
    return not any(k in t for k in NOISE)


def main():
    video, t0, t1 = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
    step = float(sys.argv[4]) if len(sys.argv) > 4 else 0.5
    ocr = RapidOCR()
    cap = cv2.VideoCapture(video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    seen = set()
    t = t0
    while t <= t1:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            break
        crop = frame[120:720, 150:1340]
        result, _ = ocr(crop)
        if result:
            for box, text, conf in result:
                text = text.replace(" ", "")
                if conf < 0.6 or not title_like(text):
                    continue
                key = (text, round(t / 3))
                if key in seen:
                    continue
                seen.add(key)
                xs = [p[0] for p in box]; ys = [p[1] for p in box]
                print(json.dumps({
                    "t": round(t, 1), "mmss": f"{int(t)//60:02d}:{int(t)%60:02d}",
                    "text": text, "conf": round(conf, 2),
                    "box": [int(min(xs)) + 150, int(min(ys)) + 120,
                            int(max(xs)) + 150, int(max(ys)) + 120],
                }, ensure_ascii=False), flush=True)
        t += step
    cap.release()


if __name__ == "__main__":
    main()
