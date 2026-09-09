# -*- coding: utf-8 -*-
"""
Merchant Refresh 3-State GT Verifier & Evaluator Tool.
Enforces strict 3-state evaluation:
  1. MERCHANT_REFRESH_MUTATED
  2. MERCHANT_REFRESH_UNCHANGED
  3. MERCHANT_REFRESH_SAMPLE_FAILED (NEVER coerced to UNCHANGED)
"""

import os
import json
import argparse
import cv2
import numpy as np

def calculate_roi_mutation(before_img: np.ndarray, after_img: np.ndarray, roi_rect=None, threshold: float = 0.05):
    """
    Compute pixel difference ratio in merchant goods ROI.
    Returns: (state_label, diff_ratio, details)
    """
    if before_img is None or after_img is None:
        return "MERCHANT_REFRESH_SAMPLE_FAILED", 1.0, {"error": "frame_none"}
        
    if before_img.shape != after_img.shape:
        # Resolution or geometry mismatch
        return "MERCHANT_REFRESH_SAMPLE_FAILED", 1.0, {"error": "shape_mismatch"}
        
    b_gray = cv2.cvtColor(before_img, cv2.COLOR_BGR2GRAY) if len(before_img.shape) == 3 else before_img
    a_gray = cv2.cvtColor(after_img, cv2.COLOR_BGR2GRAY) if len(after_img.shape) == 3 else after_img
    
    if roi_rect is not None:
        x, y, w, h = roi_rect
        b_crop = b_gray[y:y+h, x:x+w]
        a_crop = a_gray[y:y+h, x:x+w]
    else:
        b_crop = b_gray
        a_crop = a_gray
        
    if b_crop.size == 0 or a_crop.size == 0:
        return "MERCHANT_REFRESH_SAMPLE_FAILED", 1.0, {"error": "empty_roi"}
        
    # Check for capture quality failure (black frame, low entropy, or corrupted read)
    if b_crop.mean() < 2.0 or a_crop.mean() < 2.0 or b_crop.std() < 1.0 or a_crop.std() < 1.0:
        return "MERCHANT_REFRESH_SAMPLE_FAILED", 1.0, {"error": "unhealthy_frame"}
        
    diff = cv2.absdiff(b_crop, a_crop)
    changed_pixels = np.count_nonzero(diff > 15)
    total_pixels = b_crop.size
    diff_ratio = changed_pixels / float(total_pixels)
    
    if diff_ratio >= threshold:
        return "MERCHANT_REFRESH_MUTATED", diff_ratio, {"changed": changed_pixels, "total": total_pixels}
    else:
        return "MERCHANT_REFRESH_UNCHANGED", diff_ratio, {"changed": changed_pixels, "total": total_pixels}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Merchant Refresh GT Verifier")
    parser.add_argument("--before", required=True, help="Path to pre-refresh image")
    parser.add_argument("--after", required=True, help="Path to post-refresh image")
    parser.add_argument("--threshold", type=float, default=0.05, help="Pixel difference threshold")
    args = parser.parse_args()
    
    b_data = np.fromfile(args.before, dtype=np.uint8)
    b_img = cv2.imdecode(b_data, cv2.IMREAD_UNCHANGED)
    a_data = np.fromfile(args.after, dtype=np.uint8)
    a_img = cv2.imdecode(a_data, cv2.IMREAD_UNCHANGED)
    
    state, ratio, meta = calculate_roi_mutation(b_img, a_img, threshold=args.threshold)
    print(json.dumps({
        "state": state,
        "mutation_ratio": round(ratio, 4),
        "threshold": args.threshold,
        "meta": meta
    }, indent=2, ensure_ascii=False))
