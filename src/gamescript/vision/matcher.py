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

def find_kk_blue_button(frame: Frame) -> MatchResult | None:
    """KK对战平台房间'开始游戏'蓝底按钮 HSV/RGB 色彩特征识别算法兜底。"""
    try:
        bgr = frame.bgr
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        # KK 平台蓝色/天蓝色按钮 HSV 范围 (H: 90~130, S: 100~255, V: 100~255)
        lower_blue = np.array([90, 100, 100])
        upper_blue = np.array([130, 255, 255])
        mask = cv2.inRange(hsv, lower_blue, upper_blue)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        best_rect = None
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            # 按钮尺寸约束：宽 80..220，高 25..70，长宽比 2.0..4.5
            if 70 <= w <= 250 and 25 <= h <= 80 and 2.0 <= (w / h) <= 5.0:
                # KK 房间开始按钮位于窗口中下部 (y > 0.4 * frame_height)
                if y > frame.height * 0.3:
                    best_rect = (x, y, w, h)
                    break
        if best_rect:
            x, y, w, h = best_rect
            cx = frame.left + x + w // 2
            cy = frame.top + y + h // 2
            return MatchResult(
                name="kk_start_blue_button_color",
                score=0.99,
                x=x,
                y=y,
                w=w,
                h=h,
                screen_x=cx,
                screen_y=cy,
            )
    except Exception:
        pass
    return None


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
    
    # 若模板未能匹配，且包含 kk_start/start 关键字，调用色域轮廓识别兜底
    if best is None and any("start" in n.lower() or "kk" in n.lower() for n in names):
        color_hit = find_kk_blue_button(frame)
        if color_hit:
            return color_hit

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

