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


_TEMPLATE_CACHE: dict[Path, np.ndarray | None] = {}
_RESOLVE_CACHE: dict[tuple[Path, str], Path | None] = {}
_SCALE_CACHE: dict[tuple[Path, float], np.ndarray | None] = {}
CACHED_SCALES: tuple[float, ...] = (0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15, 1.2)


@dataclass(frozen=True)
class MatchSearch:
    """一次场景级搜索的完整配置（N2.1 热路径）。

    早停是显式模式：只有 ``early_stop=True`` 且 ``min_margin == 0`` 时才按
    ``names`` 顺序返回首个达到 threshold 的命中；``min_margin > 0`` 自动转全扫描
    以保留歧义检测。``roi`` 是 (x1, y1, x2, y2) 比例坐标。
    """

    names: tuple[str, ...]
    threshold: float = 0.85
    primary_scale: float = 1.0
    neighbor_scale: float | None = None
    roi: tuple[float, float, float, float] | None = None
    early_stop: bool = False
    min_margin: float = 0.0


def preferred_scales(primary_scale: float, neighbor_scale: float | None = None) -> tuple[float, ...]:
    """主尺度 + 一个邻域的最终尺度元组：去重、保序、夹在支持区间。

    邻域缺省时取主尺度的 1.06 倍（与 mediator ``_adapt_scales`` 的邻域约定一致）；
    支持区间以 CACHED_SCALES 为基准，但允许低于 0.85 的主尺度（如 960x540 窗口
    的 0.6）不被夹掉。
    """
    neighbor = neighbor_scale if neighbor_scale is not None else round(primary_scale * 1.06, 3)
    lo = min(min(CACHED_SCALES), float(primary_scale))
    hi = max(max(CACHED_SCALES), float(primary_scale))
    out: list[float] = []
    for s in (float(primary_scale), float(neighbor)):
        clamped = round(max(lo, min(hi, s)), 3)
        if not any(abs(clamped - x) < 1e-6 for x in out):
            out.append(clamped)
    return tuple(sorted(out))


def clear_template_cache() -> None:
    """Clear all cached templates/resolutions (tests or asset hot-reload)."""
    _TEMPLATE_CACHE.clear()
    _RESOLVE_CACHE.clear()
    _SCALE_CACHE.clear()


def _load_template(path: Path) -> np.ndarray | None:
    cached = _TEMPLATE_CACHE.get(path)
    if cached is not None or path in _TEMPLATE_CACHE:
        return cached
    # Windows + 非 ASCII 路径下 cv2.imread 常失败，改 imdecode
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
        if data.size == 0:
            _TEMPLATE_CACHE[path] = None
            return None
        arr = cv2.imdecode(data, cv2.IMREAD_COLOR)
        _TEMPLATE_CACHE[path] = arr
        return arr
    except Exception:
        _TEMPLATE_CACHE[path] = None
        return None


def _scale_template(path: Path, scale: float) -> np.ndarray | None:
    key = (path, scale)
    cached = _SCALE_CACHE.get(key)
    if cached is not None or key in _SCALE_CACHE:
        return cached
    tmpl = _load_template(path)
    if tmpl is None:
        _SCALE_CACHE[key] = None
        return None
    if scale == 1.0:
        _SCALE_CACHE[key] = tmpl
        return tmpl
    candidate = cv2.resize(
        tmpl,
        None,
        fx=scale,
        fy=scale,
        interpolation=cv2.INTER_CUBIC if scale > 1.0 else cv2.INTER_AREA,
    )
    _SCALE_CACHE[key] = candidate
    return candidate


def resolve_template(images_dir: Path, name: str) -> Path | None:
    """name 可为 startGameBtn / startGameBtn.png / skills/jq.png。"""
    key = (images_dir, name)
    if key in _RESOLVE_CACHE:
        return _RESOLVE_CACHE[key]
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
            _RESOLVE_CACHE[key] = c
            return c
    # fuzzy: stem match under tree
    stem = Path(n).stem
    for f in images_dir.rglob("*.png"):
        if f.stem == stem:
            _RESOLVE_CACHE[key] = f
            return f
    _RESOLVE_CACHE[key] = None
    return None


def match_one(
    frame: Frame,
    template_path: Path,
    threshold: float = 0.85,
    name: str | None = None,
    scales: tuple[float, ...] = (1.0,),
    *,
    early_stop_scale: bool = False,
) -> MatchResult | None:
    """单模板匹配。

    ``early_stop_scale=True``：按尺度顺序在第一个达到 threshold 的 scale 返回；
    否则保留既有“全 scales 取最高分”语义。热路径只试主尺度与一个邻域时使用
    早停模式，宽尺度（5-8 档）保持全扫描。
    """
    tmpl = _load_template(template_path)
    if tmpl is None:
        return None
    fh, fw = frame.bgr.shape[:2]
    best: MatchResult | None = None
    for scale in scales:
        candidate = _scale_template(template_path, scale)
        if candidate is None:
            continue
        th, tw = candidate.shape[:2]
        if th > fh or tw > fw or th < 4 or tw < 4:
            continue
        result = cv2.matchTemplate(frame.bgr, candidate, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if early_stop_scale and max_val >= threshold:
            x, y = max_loc
            return MatchResult(
                name=name or template_path.stem,
                score=float(max_val),
                x=x,
                y=y,
                w=tw,
                h=th,
                screen_x=frame.left + x + tw // 2,
                screen_y=frame.top + y + th // 2,
            )
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
        # N2.1：先裁 ROI 再做 cvtColor/inRange/形态学，contour 坐标回映原帧。
        # roi=None 才允许全图；空/退化 ROI 直接返回 []。
        if roi is not None:
            rx1, ry1, rx2, ry2 = roi
            x1 = max(0, min(frame.width, int(frame.width * rx1)))
            y1 = max(0, min(frame.height, int(frame.height * ry1)))
            x2 = max(x1, min(frame.width, int(frame.width * rx2)))
            y2 = max(y1, min(frame.height, int(frame.height * ry2)))
            if x2 - x1 < 1 or y2 - y1 < 1:
                return []
            bgr = frame.bgr[y1:y2, x1:x2]
            if bgr is None or bgr.size == 0:
                return []
            ox, oy = x1, y1
        else:
            bgr = frame.bgr
            ox, oy = 0, 0
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        # KK 平台蓝色/天蓝色按钮 HSV 范围。
        lower_blue = np.array([90, 80, 70])
        upper_blue = np.array([130, 255, 255])
        mask = cv2.inRange(hsv, lower_blue, upper_blue)
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
            gx, gy = x + ox, y + oy  # 回映到原帧坐标
            cx = frame.left + gx + w // 2
            cy = frame.top + gy + h // 2
            found.append(MatchResult(
                name="blue_button_color",
                score=min(0.99, 0.8 + 0.19 * coverage),
                x=gx,
                y=gy,
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


@dataclass
class MatchMarginResult:
    best: MatchResult | None
    second_best: MatchResult | None
    margin: float
    compared_all: bool = True  # False 仅当 early_stop 在 names 耗尽前返回（局部比较）


def match_any(
    frame: Frame,
    images_dir: Path,
    names: list[str],
    threshold: float = 0.85,
    scales: tuple[float, ...] = (1.0,),
    roi: tuple[float, float, float, float] | None = None,
    *,
    early_stop: bool = False,
) -> MatchResult | None:
    res = match_any_with_margin(
        frame, images_dir, names, threshold=threshold, scales=scales, roi=roi, early_stop=early_stop
    )
    return res.best


def _crop_for_roi(frame: Frame, roi: tuple[float, float, float, float]) -> tuple[Frame, int, int]:
    """按比例 ROI 裁出匹配目标帧，返回 (crop, x1, y1) 供坐标回映。"""
    rx1, ry1, rx2, ry2 = roi
    x1 = max(0, min(frame.width, int(frame.width * rx1)))
    y1 = max(0, min(frame.height, int(frame.height * ry1)))
    x2 = max(x1, min(frame.width, int(frame.width * rx2)))
    y2 = max(y1, min(frame.height, int(frame.height * ry2)))
    target = Frame(
        frame.bgr[y1:y2, x1:x2],
        left=frame.left + x1,
        top=frame.top + y1,
        window_title=frame.window_title,
        hwnd=frame.hwnd,
    )
    return target, x1, y1


def match_any_with_margin(
    frame: Frame,
    images_dir: Path,
    names: list[str],
    threshold: float = 0.85,
    scales: tuple[float, ...] = (1.0,),
    min_margin: float = 0.0,
    roi: tuple[float, float, float, float] | None = None,
    *,
    early_stop: bool = False,
) -> MatchMarginResult:
    """多模板匹配（可早停）。

    - ``early_stop=False``（默认）：全 names × scales 扫描取全局最高分，
      ``compared_all=True``，与 N0 语义完全一致。
    - ``early_stop=True, min_margin == 0``：按 names 顺序返回首个达到 threshold
      的命中；``compared_all=False``、``second_best=None``，margin 仅为诊断值。
    - ``early_stop=True, min_margin > 0``：禁止早停，自动转全扫描，保留歧义检测。
    """
    if not names:
        return MatchMarginResult(best=None, second_best=None, margin=0.0, compared_all=True)
    if early_stop and min_margin > 0.0:
        early_stop = False  # min_margin>0 自动全扫描

    target = frame
    if roi is not None:
        target, _x1, _y1 = _crop_for_roi(frame, roi)

    if early_stop:
        for n in names:
            path = resolve_template(images_dir, n)
            if not path:
                continue
            hit = match_one(target, path, threshold=threshold, name=path.stem, scales=scales, early_stop_scale=True)
            if hit:
                # 局部比较：未扫描的候选不能充当 second_best / 全局 margin
                return MatchMarginResult(best=hit, second_best=None, margin=hit.score, compared_all=False)
        return MatchMarginResult(best=None, second_best=None, margin=0.0, compared_all=False)

    results: list[MatchResult] = []
    for n in names:
        path = resolve_template(images_dir, n)
        if not path:
            continue
        hit = match_one(target, path, threshold=threshold, name=path.stem, scales=scales)
        if hit:
            results.append(hit)

    results.sort(key=lambda m: m.score, reverse=True)
    if not results:
        return MatchMarginResult(best=None, second_best=None, margin=0.0, compared_all=True)

    best = results[0]
    second = results[1] if len(results) > 1 else None
    margin = (best.score - second.score) if second else best.score

    if min_margin > 0.0 and margin < min_margin:
        return MatchMarginResult(best=None, second_best=second, margin=margin, compared_all=True)

    return MatchMarginResult(best=best, second_best=second, margin=margin, compared_all=True)


def match_all(
    frame: Frame,
    images_dir: Path,
    names: list[str],
    threshold: float = 0.85,
    scales: tuple[float, ...] = (1.0,),
    roi: tuple[float, float, float, float] | None = None,
    max_results: int = 32,
) -> list[MatchResult]:
    """Return non-overlapping template hits, optionally limited to an ROI.

    ``match_any`` is correct for a single button, but reward panels contain
    several selectable cards.  This keeps that case explicit instead of
    making every existing caller pay for a full multi-hit scan.
    """
    if not names or max_results <= 0:
        return []

    target = frame
    if roi is not None:
        rx1, ry1, rx2, ry2 = roi
        x1 = max(0, min(frame.width, int(frame.width * rx1)))
        y1 = max(0, min(frame.height, int(frame.height * ry1)))
        x2 = max(x1, min(frame.width, int(frame.width * rx2)))
        y2 = max(y1, min(frame.height, int(frame.height * ry2)))
        target = Frame(
            frame.bgr[y1:y2, x1:x2],
            left=frame.left + x1,
            top=frame.top + y1,
            window_title=frame.window_title,
            hwnd=frame.hwnd,
        )

    candidates: list[MatchResult] = []
    for name in names:
        path = resolve_template(images_dir, name)
        if not path:
            continue
        tmpl = _load_template(path)
        if tmpl is None:
            continue
        fh, fw = target.bgr.shape[:2]
        for scale in scales:
            candidate = _scale_template(path, scale)
            if candidate is None:
                continue
            th, tw = candidate.shape[:2]
            if th > fh or tw > fw or th < 4 or tw < 4:
                continue
            result = cv2.matchTemplate(target.bgr, candidate, cv2.TM_CCOEFF_NORMED)
            # 局部非极大抑制：只收集每个局部峰（膨胀后相等处），
            # 避免低阈值+重复纹理时把成千上万个过阈值像素转成 Python 对象
            if result.size > 0:
                kernel = np.ones((3, 3), np.uint8)
                local_max = cv2.dilate(result, kernel)
                peaks = (result == local_max) & (result >= threshold)
                ys, xs = np.where(peaks)
            else:
                ys, xs = np.array([], dtype=int), np.array([], dtype=int)
            for y, x in zip(ys.tolist(), xs.tolist()):
                candidates.append(MatchResult(
                    name=path.stem,
                    score=float(result[y, x]),
                    x=x + (target.left - frame.left),
                    y=y + (target.top - frame.top),
                    w=tw,
                    h=th,
                    screen_x=target.left + x + tw // 2,
                    screen_y=target.top + y + th // 2,
                ))

    def iou(first: MatchResult, second: MatchResult) -> float:
        left = max(first.x, second.x)
        top = max(first.y, second.y)
        right = min(first.x + first.w, second.x + second.w)
        bottom = min(first.y + first.h, second.y + second.h)
        overlap = max(0, right - left) * max(0, bottom - top)
        union = first.w * first.h + second.w * second.h - overlap
        return overlap / union if union else 0.0

    kept: list[MatchResult] = []
    for hit in sorted(candidates, key=lambda item: item.score, reverse=True):
        if any(
            iou(hit, old) >= 0.25
            or (
                abs(hit.screen_x - old.screen_x) < max(8, min(hit.w, old.w) * 0.45)
                and abs(hit.screen_y - old.screen_y) < max(8, min(hit.h, old.h) * 0.45)
            )
            for old in kept
        ):
            continue
        kept.append(hit)
        if len(kept) >= max_results:
            break
    return kept


def match_scenes(
    frame: Frame,
    images_dir: Path,
    scene_searches: list[tuple[str, MatchSearch]],
) -> tuple[str, MatchResult] | None:
    """按场景优先级顺序搜索，命中即停（N2.1 场景级 API）。

    每个场景携带自己的 threshold / ROI / 主-邻尺度 / 早停策略；只给
    ``_post_game_state``、退出、挑战、stage 等已知候选集合的热路径使用。
    """
    for key, search in scene_searches:
        res = match_any_with_margin(
            frame,
            images_dir,
            list(search.names),
            threshold=search.threshold,
            scales=preferred_scales(search.primary_scale, search.neighbor_scale),
            roi=search.roi,
            min_margin=search.min_margin,
            early_stop=search.early_stop,
        )
        if res.best:
            return key, res.best
    return None

