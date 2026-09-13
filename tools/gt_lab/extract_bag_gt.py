# -*- coding: utf-8 -*-
"""
Public Bag GT Video Slicer & Frame Metadata Generator.
Designed for offline GT Lab data extraction from gameplay videos.
"""

import os
import sys
import json
import argparse
import cv2
import numpy as np

def extract_bag_gt_frames(video_path: str, output_dir: str, interval_sec: float = 1.0):
    if not os.path.exists(video_path):
        print(f"[ERROR] Video file not found: {video_path}")
        return False
        
    os.makedirs(output_dir, exist_ok=True)
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        fps = 30.0
    step = max(1, int(fps * interval_sec))
    
    frame_idx = 0
    saved_count = 0
    records = []
    
    print(f"[INFO] Processing {video_path} (step={step}, fps={fps:.2f})...")
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx % step == 0:
            ts = frame_idx / fps
            fname = f"frame_{saved_count:04d}_t{ts:.2f}s.png"
            out_file = os.path.join(output_dir, fname)
            # Unicode safe write
            is_success, buf = cv2.imencode(".png", frame)
            if is_success:
                buf.tofile(out_file)
                records.append({
                    "file": fname,
                    "timestamp_sec": round(ts, 2),
                    "source_frame_idx": frame_idx,
                    "resolution": [frame.shape[1], frame.shape[0]],
                    "labels": []
                })
                saved_count += 1
        frame_idx += 1
        
    cap.release()
    
    manifest_file = os.path.join(output_dir, "manifest.json")
    with open(manifest_file, "w", encoding="utf-8") as f:
        json.dump({
            "schema_version": "1.0",
            "contract": "PUBLIC_BAG_LAYOUT_GT",
            "source_video": video_path,
            "extracted_count": saved_count,
            "labels_schema": [
                "PERSONAL_BAG",
                "PUBLIC_BAG",
                "PUBLIC_BAG_EMPTY_SLOT",
                "PUBLIC_BAG_OCCUPIED_SLOT",
                "SOURCE_DEVOUR_PILL",
                "SOURCE_TALISMAN",
                "SOURCE_SELECTED",
                "DEPOSIT_REQUESTED",
                "DEPOSIT_CONFIRMED",
                "PUBLIC_BAG_FULL"
            ],
            "hard_negatives": [
                "PERSONAL_BAG_EMPTY_SLOT",
                "PERSONAL_BAG_OCCUPIED_SLOT",
                "PUBLIC_BAG_OCCUPIED_SLOT",
                "DARK_UNUSABLE_SLOT",
                "SELECTED_HIGHLIGHTED_SLOT",
                "PANEL_BORDER",
                "TOOLTIP",
                "ANIMATION_FRAME"
            ],
            "records": records
        }, f, indent=2, ensure_ascii=False)
        
    print(f"[SUCCESS] Extracted {saved_count} frames to {output_dir}")
    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Public Bag GT Extractor")
    parser.add_argument("--video", required=True, help="Path to video file")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--interval", type=float, default=1.0, help="Interval in seconds")
    args = parser.parse_args()
    
    extract_bag_gt_frames(args.video, args.out, args.interval)
