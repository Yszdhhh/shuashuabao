#!/usr/bin/env python3
"""录屏拆解工具：抽帧 → 场景变化检测 → 关键帧 + 时间线 JSON。

用法：
  python tools/video_breakdown.py <video.mp4> [--out DIR] [--fps 2] [--min-diff 12]
  python tools/video_breakdown.py --batch-dir "C:\\Users\\...\\录屏素材" --glob "2026081*.mp4" --out C:\\tmp\\frame_candidates_20260812

产物：
  <out>/<video_stem>/frames/    每场景关键帧 PNG
  <out>/<video_stem>/timeline.json
  <out>/<video_stem>/contact_sheet.png
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np


def breakdown_one(video: Path, out_root: Path, fps_sample: float, min_diff: float) -> int:
    if not video.exists():
        print(f"video not found: {video}")
        return 2

    out = out_root / video.stem
    frames = out / "frames"
    frames.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        print(f"cannot open video: {video}")
        return 3

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    step = max(1, int(fps / fps_sample))
    print(f"[{video.name}] fps={fps:.2f} total={total} step={step} ({fps_sample:.1f} fps sampling)")

    timeline: list[dict] = []
    prev_gray: np.ndarray | None = None
    scene = 0
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % step != 0:
            idx += 1
            continue
        t = idx / fps
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        diff = 0.0
        if prev_gray is not None and prev_gray.shape == gray.shape:
            diff = float(np.abs(cv2.absdiff(prev_gray, gray)).mean())
        new_scene = prev_gray is None or diff >= min_diff
        if new_scene:
            scene += 1
            fname = f"s{scene:03d}_t{t:07.2f}_d{diff:05.1f}.png"
            ok, buf = cv2.imencode(".png", frame)
            if ok:
                (frames / fname).write_bytes(buf.tobytes())
            timeline.append({
                "scene": scene,
                "t": round(t, 2),
                "frame": fname,
                "diff": round(diff, 1),
                "shape": [int(frame.shape[1]), int(frame.shape[0])],
            })
            print(f"  scene {scene} t={t:.2f}s diff={diff:.1f} -> {fname}")
        prev_gray = gray
        idx += 1
    cap.release()

    (out / "timeline.json").write_text(
        json.dumps(
            {
                "video": str(video),
                "fps": fps,
                "total_frames": total,
                "scenes": timeline,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"  timeline: {len(timeline)} scenes -> {out / 'timeline.json'}")

    files = sorted(frames.glob("*.png"))
    if files:
        thumbs = []
        for f in files:
            im = cv2.imdecode(np.frombuffer(f.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
            if im is None:
                continue
            im = cv2.resize(im, (320, 180))
            thumbs.append(im)
        cols = 4
        rows = (len(thumbs) + cols - 1) // cols
        sheet = np.full(
            (rows * 180 + (rows + 1) * 10, cols * 320 + (cols + 1) * 10, 3), 30, np.uint8
        )
        for i, im in enumerate(thumbs):
            r, c = divmod(i, cols)
            y0, x0 = r * 190 + 10, c * 330 + 10
            sheet[y0 : y0 + 180, x0 : x0 + 320] = im
        cv2.imwrite(str(out / "contact_sheet.png"), sheet)
        print(f"  contact sheet: {len(files)} thumbs -> {out / 'contact_sheet.png'}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("video", type=Path, nargs="?", default=None)
    p.add_argument("--batch-dir", type=Path, default=None)
    p.add_argument("--glob", default="*.mp4")
    p.add_argument("--out", type=Path, default=Path(r"C:\tmp\video_breakdown"))
    p.add_argument("--fps", type=float, default=2.0)
    p.add_argument("--min-diff", type=float, default=12.0)
    args = p.parse_args()

    if args.batch_dir is not None:
        videos = sorted(args.batch_dir.glob(args.glob))
        if not videos:
            print(f"no videos match {args.batch_dir / args.glob}")
            return 2
        rc = 0
        for video in videos:
            code = breakdown_one(video, args.out, args.fps, args.min_diff)
            rc = rc or code
        return rc

    if args.video is None:
        p.error("provide video path or --batch-dir")
    return breakdown_one(args.video, args.out, args.fps, args.min_diff)


if __name__ == "__main__":
    sys.exit(main())
