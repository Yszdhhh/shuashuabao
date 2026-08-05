"""OpenCV 模板匹配（对齐原 OpenCvSharp 找图思路）。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .capture import Frame


@dataclass
class MatchResult:
    name: str
    score: float
    x: int  # 相对截图
    y: int
    w: int
    h: int
    screen_x: int  # 屏幕绝对坐标（中心）
    screen_y: int

    @property
    def center(self) -> tuple[int, int]:
        return self.screen_x, self.screen_y


def _load_template(path: Path) -> np.ndarray | None:
    # Windows + 非 ASCII 路径下 cv2.imread 常失败，改 imdecode
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
        if data.size == 0:
            return None
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception:
        return None


def resolve_template(images_dir: Path, name: str) -> Path | None:
    """name 可为 startGameBtn / startGameBtn.png / skills/jq.png。"""
    n = name if name.lower().endswith(".png") else f"{name}.png"
    candidates = [
        images_dir / n,
        images_dir / Path(n).name,
        images_dir / "lobby" / Path(n).name,
        images_dir / "skills" / Path(n).name,
        images_dir / "cards" / Path(n).name,
        images_dir / "boss" / Path(n).name,
        images_dir / "chuanjiaobao" / Path(n).name,
    ]
    for c in candidates:
        if c.is_file():
            return c
    # fuzzy: stem match under tree
    stem = Path(n).stem
    for f in images_dir.rglob("*.png"):
        if f.stem == stem:
            return f
    return None


def match_one(
    frame: Frame,
    template_path: Path,
    threshold: float = 0.85,
    name: str | None = None,
    scales: tuple[float, ...] = (1.0,),
) -> MatchResult | None:
    tmpl = _load_template(template_path)
    if tmpl is None:
        return None
    fh, fw = frame.bgr.shape[:2]
    best: MatchResult | None = None
    for scale in scales:
        candidate = tmpl if scale == 1.0 else cv2.resize(
            tmpl,
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_CUBIC if scale > 1.0 else cv2.INTER_AREA,
        )
        th, tw = candidate.shape[:2]
        if th > fh or tw > fw or th < 4 or tw < 4:
            continue
        result = cv2.matchTemplate(frame.bgr, candidate, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_val < threshold or (best is not None and max_val <= best.score):
            continue
        x, y = max_loc
        best = MatchResult(
            name=name or template_path.stem,
            score=float(max_val),
            x=x,
            y=y,
            w=tw,
            h=th,
            screen_x=frame.left + x + tw // 2,
            screen_y=frame.top + y + th // 2,
        )
    return best

def find_blue_buttons(
    frame: Frame,
    roi: tuple[float, float, float, float] | None = None,
    min_size: tuple[int, int] = (70, 25),
    max_size: tuple[int, int] = (280, 90),
) -> list[MatchResult]:
    """Return blue button candidates inside one scene-specific ROI.

    This is deliberately not part of :func:`match_any`: blue is a color, not
    a semantic button.  Callers must provide the page/ROI meaning before
    turning a candidate into a click.
    """
    try:
        bgr = frame.bgr
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        # KK 平台蓝色/天蓝色按钮 HSV 范围。
        lower_blue = np.array([90, 80, 70])
        upper_blue = np.array([130, 255, 255])
        mask = cv2.inRange(hsv, lower_blue, upper_blue)
        if roi is not None:
            rx1, ry1, rx2, ry2 = roi
            x1, y1 = int(frame.width * rx1), int(frame.height * ry1)
            x2, y2 = int(frame.width * rx2), int(frame.height * ry2)
            clipped = np.zeros_like(mask)
            clipped[max(0, y1):min(frame.height, y2), max(0, x1):min(frame.width, x2)] = 255
            mask = cv2.bitwise_and(mask, clipped)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        found: list[MatchResult] = []
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            if not (min_size[0] <= w <= max_size[0] and min_size[1] <= h <= max_size[1]):
                continue
            if not 2.0 <= (w / h) <= 5.5:
                continue
            area = float(cv2.contourArea(cnt))
            coverage = area / max(1, w * h)
            if coverage < 0.35:
                continue
            cx = frame.left + x + w // 2
            cy = frame.top + y + h // 2
            found.append(MatchResult(
                name="blue_button_color",
                score=min(0.99, 0.8 + 0.19 * coverage),
                x=x,
                y=y,
                w=w,
                h=h,
                screen_x=cx,
                screen_y=cy,
            ))
        return sorted(found, key=lambda hit: (hit.x, hit.y))
    except Exception:
        return []


def find_blue_button(
    frame: Frame,
    roi: tuple[float, float, float, float],
    side: str = "only",
) -> MatchResult | None:
    """Choose one blue candidate from a narrow, semantic scene ROI."""
    candidates = find_blue_buttons(frame, roi=roi)
    if len(candidates) == 1:
        # A single blue rectangle is not enough evidence on a map page: it
        # may be the equally blue quick-join action.  Accept lone candidates
        # only when the caller explicitly says that the ROI has one semantic
        # action; map-side callers must choose from multiple positioned
        # candidates or provide a template.
        return candidates[0] if side == "only" else None
    if not candidates:
        return None
    if side == "left":
        return candidates[0]
    if side == "right":
        return candidates[-1]
    return None


def find_input_boxes(
    frame: Frame,
    anchor: MatchResult | None = None,
) -> list[MatchResult]:
    """Find two similarly sized dark text boxes above a dialog button."""
    try:
        gray = cv2.cvtColor(frame.bgr, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 60, 160)
        contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        candidates: list[MatchResult] = []
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            if not (240 <= w <= frame.width * 0.55 and 18 <= h <= 75):
                continue
            if not 3.0 <= (w / h) <= 20.0:
                continue
            if y < frame.height * 0.12 or y > frame.height * 0.78:
                continue
            cx, cy = x + w // 2, y + h // 2
            if anchor is not None:
                ax, ay = anchor.x + anchor.w // 2, anchor.y + anchor.h // 2
                if abs(cx - ax) > frame.width * 0.14 or cy >= ay:
                    continue
            fill = float(np.mean(gray[y + 2 : y + h - 2, x + 2 : x + w - 2]))
            if fill > 150:
                continue
            candidates.append(MatchResult(
                name="room_input",
                score=0.8,
                x=x,
                y=y,
                w=w,
                h=h,
                screen_x=frame.left + cx,
                screen_y=frame.top + cy,
            ))
        unique: list[MatchResult] = []
        for hit in sorted(candidates, key=lambda item: (item.y, -item.w)):
            if any(abs(hit.x - old.x) < 8 and abs(hit.y - old.y) < 8 for old in unique):
                continue
            unique.append(hit)
        for i in range(len(unique) - 1):
            first, second = unique[i], unique[i + 1]
            if abs(first.w - second.w) <= max(20, first.w * 0.2) and 10 <= second.y - first.y <= 140:
                return [first, second]
        return []
    except Exception:
        return []


def match_any(
    frame: Frame,
    images_dir: Path,
    names: list[str],
    threshold: float = 0.85,
    scales: tuple[float, ...] = (1.0,),
) -> MatchResult | None:
    best: MatchResult | None = None
    for n in names:
        path = resolve_template(images_dir, n)
        if not path:
            continue
        hit = match_one(frame, path, threshold=threshold, name=path.stem, scales=scales)
        if hit and (best is None or hit.score > best.score):
            best = hit
    
    return best


def match_scenes(
    frame: Frame,
    images_dir: Path,
    scene_name_lists: list[tuple[str, list[str]]],
    threshold: float = 0.85,
) -> tuple[str, MatchResult] | None:
    """Return first priority scene that hits, with best template in that scene."""
    for key, names in scene_name_lists:
        hit = match_any(frame, images_dir, names, threshold=threshold)
        if hit:
            return key, hit
    return None

