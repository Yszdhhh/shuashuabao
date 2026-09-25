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
_CONTENT_HASH_CACHE: dict[Path, str] = {}
# N2.4：灰度模板缓存——模板灰度在加载时一次转换（复用彩色加载），
# 尺度化灰度也缓存，与彩色路径完全对称。
_TEMPLATE_GRAY_CACHE: dict[Path, np.ndarray | None] = {}
_SCALE_GRAY_CACHE: dict[tuple[Path, float], np.ndarray | None] = {}
_CARD_FAMILY_TEMPLATES_CACHE: dict[Path, list[tuple[str, str, np.ndarray]]] = {}
CACHED_SCALES: tuple[float, ...] = (0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15, 1.2)

# N2.4：灰度候选阈值相对彩色阈值的偏移（离线重标，见
# docs/baselines/n2_runs/N2_4_THRESHOLD_RECAL_20260811.md）。灰度分数与彩色分数在
# 同一模板/帧上实测差异中位数 0.000、p90 0.017、最大 0.058（全部在 0.05 内），
# 取 0.05 保守偏移保证召回；精度由命中后的局部彩色复核（原彩色阈值）兜底。
GRAY_THRESHOLD_OFFSET = 0.05

# N2.4：hue 相关模板保持彩色路径（蓝框/品质色语义依赖色相，灰度会丢失判别力）。
# longzhu/longzhu2 是龙珠卡（蓝框为色相判别依据）→ 彩色；closeLongzhu 是关闭
# 按钮（形状/文字）→ 灰度路径。
_COLOR_ONLY_TEMPLATE_STEMS = frozenset({
    # 龙珠卡蓝框
    "longzhu", "longzhu2",
    # 品质/稀有度色
    "r", "sr", "ssr", "ur", "ex", "hc",
    "pinfu", "pingfu1", "pingfu2", "pingfu3", "pingfu4", "pingfu6",
})


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
    _TEMPLATE_GRAY_CACHE.clear()
    _SCALE_GRAY_CACHE.clear()
    _CONTENT_HASH_CACHE.clear()
    _CARD_FAMILY_TEMPLATES_CACHE.clear()


def _template_content_hash(path: Path) -> str | None:
    """模板文件字节 MD5（缓存）。同图多名的场景（kk_start/room_start/… 字节相同）
    按内容去重，避免同一图像按 N 个名字重复全帧扫描。"""
    cached = _CONTENT_HASH_CACHE.get(path)
    if cached is not None:
        return cached
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
        if data.size == 0:
            return None
        import hashlib
        digest = hashlib.md5(data.tobytes()).hexdigest()
        _CONTENT_HASH_CACHE[path] = digest
        return digest
    except Exception:
        return None


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


def _load_template_gray(path: Path) -> np.ndarray | None:
    """灰度模板：加载时一次转换并缓存（复用彩色加载，避免二次解码）。"""
    cached = _TEMPLATE_GRAY_CACHE.get(path)
    if cached is not None or path in _TEMPLATE_GRAY_CACHE:
        return cached
    tmpl = _load_template(path)
    if tmpl is None:
        _TEMPLATE_GRAY_CACHE[path] = None
        return None
    gray = cv2.cvtColor(tmpl, cv2.COLOR_BGR2GRAY)
    _TEMPLATE_GRAY_CACHE[path] = gray
    return gray


def _scale_template_gray(path: Path, scale: float) -> np.ndarray | None:
    """尺度化灰度模板（缓存；与 _scale_template 对称）。"""
    key = (path, scale)
    cached = _SCALE_GRAY_CACHE.get(key)
    if cached is not None or key in _SCALE_GRAY_CACHE:
        return cached
    tgray = _load_template_gray(path)
    if tgray is None:
        _SCALE_GRAY_CACHE[key] = None
        return None
    if scale == 1.0:
        _SCALE_GRAY_CACHE[key] = tgray
        return tgray
    candidate = cv2.resize(
        tgray,
        None,
        fx=scale,
        fy=scale,
        interpolation=cv2.INTER_CUBIC if scale > 1.0 else cv2.INTER_AREA,
    )
    _SCALE_GRAY_CACHE[key] = candidate
    return candidate


def _color_verify(frame_bgr: np.ndarray, color_tpl: np.ndarray, x: int, y: int, threshold: float) -> tuple[bool, float]:
    """命中后的局部彩色复核：在灰度候选位置 ±1px 邻域用彩色 NCC 验证。

    - 与 cv2.TM_CCOEFF_NORMED 同式（减均值归一化互相关），但只用 numpy 在
      候选局部计算，不产生新的 matchTemplate 调用（benchmark match_calls 与
      灰度扫描保持 1:1，见 N2.4 验收「选择 tick matchTemplate ≤20 不倒退」）。
    - 先试精确位置（绝大多数真命中在此通过），失败再试 3×3 邻域。
    - 返回 (是否通过原彩色阈值, 彩色分数)。分数即后续阈值/margin/比较使用的
      权威分数，保证灰度引入后所有阈值语义仍处于彩色刻度。
    """
    th, tw = color_tpl.shape[:2]
    fh, fw = frame_bgr.shape[:2]
    tflat = color_tpl.astype(np.float32).reshape(-1)
    tmean = tflat.mean()
    tdev = tflat - tmean
    tnorm = float(np.sqrt(float((tdev * tdev).sum())))

    def score_at(dx: int, dy: int) -> float:
        x0, y0 = x + dx, y + dy
        if x0 < 0 or y0 < 0 or x0 + tw > fw or y0 + th > fh:
            return -1.0
        crop = frame_bgr[y0 : y0 + th, x0 : x0 + tw].astype(np.float32).reshape(-1)
        cdev = crop - crop.mean()
        denom = tnorm * float(np.sqrt(float((cdev * cdev).sum())))
        if denom <= 0.0:
            return -1.0
        return float((tdev * cdev).sum()) / denom

    best = score_at(0, 0)
    if best >= threshold:
        return True, best
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            s = score_at(dx, dy)
            if s > best:
                best = s
    return best >= threshold, best


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


def _gray_peak_verified(
    frame: Frame,
    result: np.ndarray,
    gray_tpl: np.ndarray,
    color_tpl: np.ndarray,
    threshold: float,
    gray_th: float,
) -> tuple[int, int, float] | None:
    """在单尺度灰度匹配结果上找首个通过『灰度阈值 + 局部彩色复核』的峰。

    命中即返回 (x, y, 彩色分数)；被复核否决的峰整块排除后继续找次峰
    （防灰度假峰压过真峰）。最多试 3 个峰。
    """
    th, tw = gray_tpl.shape[:2]
    res = result
    for _ in range(3):
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if float(max_val) < gray_th:
            return None
        x, y = int(max_loc[0]), int(max_loc[1])
        ok, cscore = _color_verify(frame.bgr, color_tpl, x, y, threshold)
        if ok:
            return x, y, cscore
        # 否决该峰（连同其邻域，避免同一个假峰反复命中）
        x0 = max(0, x - tw)
        y0 = max(0, y - th)
        x1 = min(res.shape[1], x + tw)
        y1 = min(res.shape[0], y + th)
        res[y0:y1, x0:x1] = -2.0
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

    N2.4：形状/文字类模板先灰度候选（灰度阈值 = 彩色阈值 - 0.05，离线重标），
    命中后在候选局部用彩色复核（原彩色阈值）；hue 相关模板（龙珠蓝框/品质色）
    保持纯彩色路径。灰度命中但彩色复核不过 = 假阳性，不产出结果。
    """
    tmpl = _load_template(template_path)
    if tmpl is None:
        return None
    gray_mode = Path(template_path).stem not in _COLOR_ONLY_TEMPLATE_STEMS
    gframe = frame.gray() if gray_mode else None
    if gray_mode and gframe is None:
        gray_mode = False  # 无灰度帧（异常帧）→ 回退彩色语义
    fh, fw = frame.bgr.shape[:2]
    gray_th = max(0.40, threshold - GRAY_THRESHOLD_OFFSET)
    best: MatchResult | None = None
    for scale in scales:
        if gray_mode:
            candidate = _scale_template_gray(template_path, scale)
        else:
            candidate = _scale_template(template_path, scale)
        if candidate is None:
            continue
        th, tw = candidate.shape[:2]
        if th > fh or tw > fw or th < 4 or tw < 4:
            continue
        src = gframe if gray_mode else frame.bgr
        result = cv2.matchTemplate(src, candidate, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if gray_mode:
            hit = _gray_peak_verified(
                frame, result, candidate, _scale_template(template_path, scale), threshold, gray_th
            )
            if hit is None:
                continue
            x, y, score = hit
        else:
            if float(max_val) < threshold:
                continue
            x, y = max_loc
            score = float(max_val)
        if best is not None and score <= best.score:
            continue
        best = MatchResult(
            name=name or template_path.stem,
            score=score,
            x=x,
            y=y,
            w=tw,
            h=th,
            screen_x=frame.left + x + tw // 2,
            screen_y=frame.top + y + th // 2,
        )
        if early_stop_scale:
            return best
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
        scanned: set[Path] = set()
        seen_content: set[str] = set()
        for n in names:
            path = resolve_template(images_dir, n)
            if not path or path in scanned:
                continue
            scanned.add(path)
            digest = _template_content_hash(path)
            if digest is None or digest in seen_content:
                continue  # 与已扫描模板字节相同（同图多名）→ 跳过重复扫描
            seen_content.add(digest)
            hit = match_one(target, path, threshold=threshold, name=path.stem, scales=scales, early_stop_scale=True)
            if hit:
                # 局部比较：未扫描的候选不能充当 second_best / 全局 margin
                return MatchMarginResult(best=hit, second_best=None, margin=hit.score, compared_all=False)
        return MatchMarginResult(best=None, second_best=None, margin=0.0, compared_all=False)

    results: list[MatchResult] = []
    scanned = set()
    seen_content = set()
    for n in names:
        path = resolve_template(images_dir, n)
        if not path or path in scanned:
            continue
        scanned.add(path)
        digest = _template_content_hash(path)
        if digest is None or digest in seen_content:
            continue
        seen_content.add(digest)
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
    seen_paths: set[Path] = set()
    seen_content: set[str] = set()
    for name in names:
        path = resolve_template(images_dir, name)
        if not path or path in seen_paths:
            continue
        seen_paths.add(path)
        digest = _template_content_hash(path)
        if digest is None or digest in seen_content:
            continue  # 同图多名 → 跳过重复扫描
        seen_content.add(digest)
        tmpl = _load_template(path)
        if tmpl is None:
            continue
        gray_mode = path.stem not in _COLOR_ONLY_TEMPLATE_STEMS
        gframe = target.gray() if gray_mode else None
        if gray_mode and gframe is None:
            gray_mode = False
        fh, fw = target.bgr.shape[:2]
        gray_th = max(0.40, threshold - GRAY_THRESHOLD_OFFSET)
        for scale in scales:
            if gray_mode:
                candidate = _scale_template_gray(path, scale)
            else:
                candidate = _scale_template(path, scale)
            if candidate is None:
                continue
            th, tw = candidate.shape[:2]
            if th > fh or tw > fw or th < 4 or tw < 4:
                continue
            src = gframe if gray_mode else target.bgr
            result = cv2.matchTemplate(src, candidate, cv2.TM_CCOEFF_NORMED)
            # 局部非极大抑制：只收集每个局部峰（膨胀后相等处），
            # 避免低阈值+重复纹理时把成千上万个过阈值像素转成 Python 对象
            if result.size > 0:
                kernel = np.ones((3, 3), np.uint8)
                local_max = cv2.dilate(result, kernel)
                peaks = (result == local_max) & (result >= gray_th if gray_mode else result >= threshold)
                ys, xs = np.where(peaks)
            else:
                ys, xs = np.array([], dtype=int), np.array([], dtype=int)
            for y, x in zip(ys.tolist(), xs.tolist()):
                score = float(result[y, x])
                if gray_mode:
                    ok, cscore = _color_verify(target.bgr, _scale_template(path, scale), x, y, threshold)
                    if not ok:
                        continue  # 灰度峰彩色复核不过 → 假阳性，丢弃
                    score = cscore
                candidates.append(MatchResult(
                    name=path.stem,
                    score=score,
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


_CARD_SLOT_ROIS_4: tuple[tuple[float, float, float, float], ...] = (
    (0.185, 0.175, 0.330, 0.255),
    (0.340, 0.175, 0.485, 0.255),
    (0.495, 0.175, 0.640, 0.255),
    (0.650, 0.175, 0.795, 0.255),
)

_CARD_SLOT_ROIS_3: tuple[tuple[float, float, float, float], ...] = (
    (0.250, 0.175, 0.415, 0.255),
    (0.420, 0.175, 0.585, 0.255),
    (0.590, 0.175, 0.755, 0.255),
)


def _get_card_family_templates(
    images_dir: Path, fetter_labels: dict[str, str] | None = None
) -> list[tuple[str, str, np.ndarray]]:
    """Cached list of (stem, label, gray_template) for all card templates."""
    cards_dir = images_dir / "cards" if (images_dir / "cards").is_dir() else images_dir
    cached = _CARD_FAMILY_TEMPLATES_CACHE.get(cards_dir)
    if cached is not None:
        return cached

    labels = fetter_labels or {}
    loaded: list[tuple[str, str, np.ndarray]] = []
    if cards_dir.is_dir():
        for p in sorted(cards_dir.glob("*.png")):
            tgray = _load_template_gray(p)
            if tgray is not None and tgray.size > 0:
                code = p.stem
                label = str(labels.get(code, code)).strip() or code
                loaded.append((code, label, tgray))
    _CARD_FAMILY_TEMPLATES_CACHE[cards_dir] = loaded
    return loaded


def match_card_slots_by_template(
    frame: Frame,
    images_dir: Path,
    kind: str = "bond",
    fetter_labels: dict[str, str] | None = None,
    min_confidence: float = 0.85,
) -> tuple[int, list[dict]] | None:
    """Fast template-based slot recognition for card reward panels.

    Deterministically determines 4-slot vs 3-slot layout based on title template matches
    on fixed slot ROIs. When confident matches exist, returns (slot_count, slots_raw)
    matching the schema expected by _slots_to_candidates. Returns None when templates
    cannot make a confident classification, allowing fallback to OCR shadow.
    """
    if frame is None or getattr(frame, "bgr", None) is None:
        return None

    if kind not in ("bond", "card"):
        return None

    templates = _get_card_family_templates(images_dir, fetter_labels)
    if not templates:
        return None

    gray = (
        frame.gray()
        if callable(getattr(frame, "gray", None))
        else cv2.cvtColor(frame.bgr, cv2.COLOR_BGR2GRAY)
    )
    if gray is None:
        return None
    fh, fw = gray.shape[:2]

    def scan_layout(rois: tuple[tuple[float, float, float, float], ...]) -> tuple[list[dict], int, float]:
        slots: list[dict] = []
        high_conf_count = 0
        sum_conf = 0.0
        for idx, (x0, y0, x1, y1) in enumerate(rois):
            crop = gray[int(y0 * fh) : int(y1 * fh), int(x0 * fw) : int(x1 * fw)]
            if crop.size == 0:
                slots.append({
                    "index": idx,
                    "name": None,
                    "confidence": 0.0,
                    "raw_text": "",
                    "rec_score": 0.0,
                    "status": "MISS",
                    "reason": "empty_crop",
                    "rarity": None,
                    "description": "",
                    "source": "template",
                })
                continue

            best_code, best_label, best_score = "", "", -1.0
            ch, cw = crop.shape[:2]
            for code, label, tpl in templates:
                th, tw = tpl.shape[:2]
                if ch < th or cw < tw:
                    continue
                res = cv2.matchTemplate(crop, tpl, cv2.TM_CCOEFF_NORMED)
                val = float(cv2.minMaxLoc(res)[1])
                if val > best_score:
                    best_score = val
                    best_code = code
                    best_label = label

            is_confident = best_score >= min_confidence
            if is_confident:
                high_conf_count += 1
                sum_conf += best_score

            slots.append({
                "index": idx,
                "name": best_label if is_confident else None,
                "confidence": best_score if is_confident else 0.0,
                "raw_text": best_label if is_confident else "",
                "rec_score": best_score if is_confident else 0.0,
                "status": "SUCCESS" if is_confident else "MISS",
                "reason": f"template:{best_code}:{best_score:.3f}" if is_confident else "template_low_conf",
                "rarity": None,
                "description": "",
                "source": "template",
                "template_code": best_code,
                "template_score": best_score,
            })
        return slots, high_conf_count, sum_conf

    # Evaluate 4-slot layout first (predominant in in-game bond panels)
    slots_4, high_4, sum_4 = scan_layout(_CARD_SLOT_ROIS_4)
    if high_4 >= 2:
        return 4, slots_4

    # Scan 3-slot layout
    slots_3, high_3, sum_3 = scan_layout(_CARD_SLOT_ROIS_3)
    if high_3 >= 2 and high_3 > high_4:
        return 3, slots_3
    if high_3 >= 1 and high_4 == 0:
        return 3, slots_3
    if high_4 >= 1 and high_3 == 0:
        return 4, slots_4
    if high_4 >= 1 and high_3 >= 1:
        return (4, slots_4) if sum_4 >= sum_3 else (3, slots_3)

    return None


