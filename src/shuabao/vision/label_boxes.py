"""White on-screen label text -> word boxes (no OCR, no input authority).

The project's OCR (``vision.ocr_shadow``) only recognises a caller-given box;
it has no text detector.  The post-game plaza NPC labels (存档挑战 /
传家宝挑战) are white text that renders bold when hovered and thin
otherwise, so a single template misses one of the two states (live
2026-09-14).  This finds candidate word boxes from the white glyphs so a
caller can ask OCR what each box says.  It never decides a click.
"""

from __future__ import annotations

import cv2
import numpy as np

# Measured on the 1600x900 plaza (tests/fixtures/hitch_postgame_20260914):
# labels are 22-23 px tall and 98-122 px wide; neighbouring labels sit
# ~15 px apart, glyphs inside one word 2-8 px apart.
_BASE_HEIGHT = 900.0
_MIN_H, _MAX_H = 14, 40
_MIN_W, _MAX_W = 50, 220
_MIN_ASPECT = 2.5
_GLYPH_JOIN_W, _GLYPH_JOIN_H = 10, 3
_WHITE_V_MIN = 200
_WHITE_S_MAX = 60


def white_text_word_boxes(
    bgr: np.ndarray,
    roi: tuple[float, float, float, float],
) -> list[tuple[int, int, int, int]]:
    """Return (x, y, w, h) frame-pixel boxes of white words inside ``roi``.

    ``roi`` is (x0, y0, x1, y1) as fractions of the frame.  Sizes scale with
    the frame height so a scaled client keeps the same geometry.
    """
    if bgr is None or bgr.ndim != 3 or bgr.size == 0:
        return []
    h, w = bgr.shape[:2]
    x0, y0 = int(w * roi[0]), int(h * roi[1])
    x1, y1 = int(w * roi[2]), int(h * roi[3])
    if x1 <= x0 or y1 <= y0:
        return []
    scale = h / _BASE_HEIGHT
    hsv = cv2.cvtColor(bgr[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    mask = ((hsv[..., 2] >= _WHITE_V_MIN) & (hsv[..., 1] <= _WHITE_S_MAX)).astype(np.uint8) * 255
    kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (max(3, round(_GLYPH_JOIN_W * scale)), max(1, round(_GLYPH_JOIN_H * scale))),
    )
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(cv2.dilate(mask, kernel))
    boxes: list[tuple[int, int, int, int]] = []
    for i in range(1, count):
        bx, by, bw, bh = (int(v) for v in stats[i][:4])
        if not (_MIN_H * scale <= bh <= _MAX_H * scale):
            continue
        if not (_MIN_W * scale <= bw <= _MAX_W * scale) or bw < _MIN_ASPECT * bh:
            continue
        boxes.append((x0 + bx, y0 + by, bw, bh))
    return sorted(boxes, key=lambda b: (b[1], b[0]))
