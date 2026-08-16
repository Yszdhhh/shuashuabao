"""Detect the numbered stage buttons in the game stage list.

The old ``stage.png`` asset is a map card, not a numbered stage button.  This
module reads the small white label rendered on each button instead, so the
configured Stage1/Stage2 values can be applied without adding OCR dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re

import cv2
import numpy as np

from gamescript.vision.capture import Frame
from gamescript.vision.matcher import MatchResult, _load_template, resolve_template


@dataclass(frozen=True)
class StageId:
    """Explicit chapter and index for game stage levels (e.g. 1-10 vs 5-10)."""

    chapter: int
    index: int

    @classmethod
    def parse(cls, label: str) -> StageId | None:
        if not label or not str(label).strip():
            return None
        match = re.fullmatch(r"(\d+)-(\d+)", str(label).strip())
        if not match:
            return None
        return cls(int(match.group(1)), int(match.group(2)))

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, StageId):
            return NotImplemented
        return (self.chapter, self.index) < (other.chapter, other.index)

    def __le__(self, other: object) -> bool:
        if not isinstance(other, StageId):
            return NotImplemented
        return (self.chapter, self.index) <= (other.chapter, other.index)

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, StageId):
            return NotImplemented
        return (self.chapter, self.index) > (other.chapter, other.index)

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, StageId):
            return NotImplemented
        return (self.chapter, self.index) >= (other.chapter, other.index)

    def __str__(self) -> str:
        return f"{self.chapter}-{self.index}"


@dataclass(frozen=True)
class StageRow:
    """A visible numbered stage row and its screen click position."""

    label: str
    stage_id: StageId
    center_x: int
    center_y: int

    @property
    def number(self) -> int:
        return self.stage_id.index


# Existing label assets provide the same font for every digit used by the UI.
_LABEL_ASSETS = {
    "stage1": "1-1",
    "stage2": "2-1",
    "stage3": "3-1",
    "stage4": "4-1",
    "1-23": "1-23",
    "5-10": "5-10",
    "5-6": "5-6",
    "5-7": "5-7",
    "5-8": "5-8",
    "5-9": "5-9",
}


def _runs(values: np.ndarray, minimum: int = 2) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    active = False
    for i, value in enumerate(values):
        if value and not active:
            start = i
            active = True
        if active and (not value or i == len(values) - 1):
            end = i if not value else i + 1
            if end - start >= minimum:
                runs.append((start, end))
            active = False
    return runs


@lru_cache(maxsize=4)
def _glyph_templates(images_dir: Path) -> dict[str, list[np.ndarray]]:
    templates: dict[str, list[np.ndarray]] = {}
    for asset, label in _LABEL_ASSETS.items():
        path = resolve_template(images_dir, asset)
        if path is None:
            continue
        color = _load_template(path)
        if color is None:
            continue
        gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
        mask = (gray > 180).astype(np.uint8)
        columns = _runs(mask.sum(axis=0) > 0)
        if len(columns) != len(label):
            continue
        for char, (x1, x2) in zip(label, columns):
            glyph = mask[:, x1:x2]
            ys, _ = np.where(glyph)
            if len(ys):
                glyph = glyph[ys.min() : ys.max() + 1, :]
                templates.setdefault(char, []).append(glyph)
    return templates


def _classify_glyph(glyph: np.ndarray, templates: dict[str, list[np.ndarray]]) -> str | None:
    ys, _ = np.where(glyph)
    if not len(ys):
        return None
    glyph = glyph[ys.min() : ys.max() + 1, :]
    if glyph.shape[0] < 2 or glyph.shape[1] < 2:
        return None
    best: tuple[float, str] | None = None
    for char, candidates in templates.items():
        for candidate in candidates:
            resized = cv2.resize(
                candidate,
                (glyph.shape[1], glyph.shape[0]),
                interpolation=cv2.INTER_NEAREST,
            )
            score = float(np.mean(resized != glyph))
            if best is None or score < best[0]:
                best = (score, char)
    # A bad crop should not turn into a random stage number.
    return best[1] if best is not None and best[0] <= 0.45 else None


def _read_row(mask: np.ndarray, x_offset: int, y_offset: int, templates: dict[str, list[np.ndarray]]) -> StageRow | None:
    columns = _runs(mask.sum(axis=0) > 0)
    chars: list[str] = []
    for x1, x2 in columns:
        glyph = mask[:, x1:x2]
        char = _classify_glyph(glyph, templates)
        if char is None:
            return None
        chars.append(char)
    label = "".join(chars)
    stage_id = StageId.parse(label)
    if stage_id is None:
        return None
    return StageRow(
        label=label,
        stage_id=stage_id,
        center_x=x_offset + int((columns[0][0] + columns[-1][1]) / 2),
        center_y=y_offset + mask.shape[0] // 2,
    )


def visible_stage_rows(frame: Frame, images_dir: Path) -> list[StageRow]:
    """Return numbered stage rows currently visible in a game stage screen."""
    if frame.width < 600 or frame.height < 400:
        return []
    gray = cv2.cvtColor(frame.bgr, cv2.COLOR_BGR2GRAY)
    # The stage list occupies the middle-right column in the 1600x900 UI.
    x1, x2 = int(frame.width * 0.62), int(frame.width * 0.72)
    y1, y2 = int(frame.height * 0.12), int(frame.height * 0.88)
    mask = (gray[y1:y2, x1:x2] > 180).astype(np.uint8)
    row_runs = _runs(mask.sum(axis=1) > 0, minimum=8)
    templates = _glyph_templates(images_dir)
    rows: list[StageRow] = []
    oversized: list[tuple[int, int]] = []
    for top, bottom in row_runs:
        if bottom - top > 35:
            oversized.append((top, bottom))
            continue
        row = _read_row(mask[top:bottom, :], x1, y1 + top, templates)
        if row is not None:
            rows.append(row)

    # A selected row has a bright border that merges with its label/background.
    # Recover it only when BOTH a same-chapter above and below row prove one
    # unique consecutive gap (below == above + 2). A single neighbor proves
    # nothing, and more than one recoverable block is ambiguous: recover none.
    recovered: list[StageRow] = []
    for top, bottom in oversized:
        above = max(
            (row for row in rows if row.center_y < y1 + top),
            key=lambda row: row.center_y,
            default=None,
        )
        below = min(
            (row for row in rows if row.center_y > y1 + bottom),
            key=lambda row: row.center_y,
            default=None,
        )
        if above is None or below is None:
            continue
        if (
            below.stage_id.chapter != above.stage_id.chapter
            or below.stage_id.index != above.stage_id.index + 2
        ):
            continue
        candidate_id = above.stage_id.index + 1
        candidate_label = f"{above.stage_id.chapter}-{candidate_id}"
        best: tuple[float, int] | None = None
        for center_y in range(y1 + top, y1 + bottom + 1):
            candidate = StageRow(
                label=candidate_label,
                stage_id=StageId(above.stage_id.chapter, candidate_id),
                center_x=above.center_x,
                center_y=center_y,
            )
            ratio = _row_border_bright_ratio(gray, candidate, frame.height / 900.0)
            if best is None or ratio > best[0]:
                best = (ratio, center_y)
        if best is not None and best[0] >= SELECTED_RING_RATIO:
            recovered.append(
                StageRow(
                    label=candidate_label,
                    stage_id=StageId(above.stage_id.chapter, candidate_id),
                    center_x=above.center_x,
                    center_y=best[1],
                )
            )
    if len(recovered) == 1:
        rows.append(recovered[0])
    return sorted(rows, key=lambda row: row.center_y)


def _parse_stage_spec(value: StageId | str | int, default_chapter: int = 1) -> StageId:
    if isinstance(value, StageId):
        return value
    if isinstance(value, int):
        if value <= 0:
            raise ValueError(f"Invalid stage index: {value}")
        return StageId(default_chapter, value)
    val_str = str(value).strip()
    parsed = StageId.parse(val_str)
    if parsed is not None:
        return parsed
    if val_str.isdigit():
        idx = int(val_str)
        if idx <= 0:
            raise ValueError(f"Invalid stage index: {val_str}")
        return StageId(default_chapter, idx)
    raise ValueError(f"Invalid StageId spec: {value!r}")


def find_stage_in_range(
    frame: Frame,
    images_dir: Path,
    start: StageId | str | int,
    end: StageId | str | int,
) -> MatchResult | None:
    """Find a visible stage in the configured inclusive range.

    Prefer the exact start, then end, then any visible stage inside the range.
    Uses StageId(chapter, index) to ensure chapter match when explicit.
    """
    rows = visible_stage_rows(frame, images_dir)
    if not rows:
        return None

    start_parsed = StageId.parse(str(start)) if not isinstance(start, int) else None
    end_parsed = StageId.parse(str(end)) if not isinstance(end, int) else None

    if start_parsed or end_parsed:
        explicit_chapter = start_parsed.chapter if start_parsed else end_parsed.chapter
        eligible_rows = [r for r in rows if r.stage_id.chapter == explicit_chapter]
        low_idx = start_parsed.index if start_parsed else int(start)
        high_idx = end_parsed.index if end_parsed else int(end)
    else:
        try:
            low_idx = int(start)
            high_idx = int(end)
        except ValueError:
            return None
        eligible_rows = rows

    if not eligible_rows:
        return None

    low_idx, high_idx = sorted((low_idx, high_idx))

    chosen = next((r for r in eligible_rows if r.stage_id.index == low_idx), None)
    if chosen is None:
        chosen = next((r for r in eligible_rows if r.stage_id.index == high_idx), None)
    if chosen is None:
        chosen = next((r for r in eligible_rows if low_idx <= r.stage_id.index <= high_idx), None)

    if chosen is None:
        return None

    return MatchResult(
        name=f"stage_target_{chosen.label}",
        score=1.0,
        x=chosen.center_x,
        y=chosen.center_y,
        w=0,
        h=0,
        screen_x=frame.left + chosen.center_x,
        screen_y=frame.top + chosen.center_y,
    )


def find_stage_labels(
    frame: Frame,
    images_dir: Path,
    labels: list[str],
) -> MatchResult | None:
    """Find one exact visible ``chapter-stage`` label matching StageId."""
    wanted_ids: set[StageId | str] = set()
    for label in labels:
        if not label or not str(label).strip():
            continue
        parsed = StageId.parse(label)
        if parsed:
            wanted_ids.add(parsed)
        else:
            wanted_ids.add(str(label).strip())

    if not wanted_ids:
        return None

    rows = visible_stage_rows(frame, images_dir)
    chosen = None
    for row in rows:
        if row.stage_id in wanted_ids or row.label in wanted_ids:
            chosen = row
            break

    if chosen is None:
        return None

    return MatchResult(
        name=f"stage_target_{chosen.label}",
        score=1.0,
        x=chosen.center_x,
        y=chosen.center_y,
        w=0,
        h=0,
        screen_x=frame.left + chosen.center_x,
        screen_y=frame.top + chosen.center_y,
    )


def verify_stage_selection(
    frame: Frame,
    target: StageRow | MatchResult | StageId | str | None = None,
    images_dir: Path | None = None,
) -> bool:
    """Verify that a stage row or target has been selected in the UI.

    Checks for target row selection highlight and contrast against adjacent unselected rows.
    """
    if frame.width < 600 or frame.height < 400:
        return False

    target_cy: int | None = None
    target_cx: int | None = None

    if isinstance(target, StageRow):
        target_cx, target_cy = target.center_x, target.center_y
    elif isinstance(target, MatchResult):
        target_cx = target.x if target.x > 0 else (target.screen_x - frame.left)
        target_cy = target.y if target.y > 0 else (target.screen_y - frame.top)
    elif target is not None and images_dir is not None:
        target_str = str(target)
        rows = visible_stage_rows(frame, images_dir)
        matched = next((r for r in rows if r.label == target_str or str(r.stage_id) == target_str), None)
        if matched:
            target_cx, target_cy = matched.center_x, matched.center_y

    if target_cy is None or target_cx is None:
        if images_dir is not None:
            rows = visible_stage_rows(frame, images_dir)
            for r in rows:
                if verify_stage_selection(frame, target=r):
                    return True
            return False
        target_cx = int(frame.width * 0.67)
        target_cy = int(frame.height * 0.50)

    gray = cv2.cvtColor(frame.bgr, cv2.COLOR_BGR2GRAY)

    y_min = max(0, target_cy - 15)
    y_max = min(frame.height, target_cy + 15)
    x_min = max(0, target_cx - 80)
    x_max = min(frame.width, target_cx + 80)

    target_crop = gray[y_min:y_max, x_min:x_max]
    if target_crop.size == 0:
        return False

    above_ymin = max(0, target_cy - 45)
    above_ymax = max(0, target_cy - 15)
    above_crop = gray[above_ymin:above_ymax, x_min:x_max]

    below_ymin = min(frame.height, target_cy + 15)
    below_ymax = min(frame.height, target_cy + 45)
    below_crop = gray[below_ymin:below_ymax, x_min:x_max]

    target_val = float(np.mean(target_crop))
    bright_pixels = int(np.sum(target_crop > 180))

    if bright_pixels < 10 or target_val < 80.0:
        return False

    adj_vals = []
    if above_crop.size > 0:
        adj_vals.append(float(np.mean(above_crop)))
    if below_crop.size > 0:
        adj_vals.append(float(np.mean(below_crop)))

    if adj_vals:
        adj_avg = sum(adj_vals) / len(adj_vals)
        if (target_val - adj_avg) < 10.0:
            return False

    return True


def _row_border_bright_ratio(gray: np.ndarray, row: StageRow, scale: float) -> float:
    """选中行整圈是奶白亮边（>200）；未选中行只有细灰边。返回边框环亮像素占比。

    实测 20260814_002537 客户端帧：选中的 1-1 占比 0.52，其余 11 行全为 0.000。
    """
    half_h = max(6, int(round(22 * scale)))
    inner_h = max(4, int(round(16 * scale)))
    half_w = max(20, int(round(96 * scale)))
    inner_w = max(16, int(round(90 * scale)))
    cx, cy = row.center_x, row.center_y
    height, width = gray.shape[:2]

    def band(y0: int, y1: int, x0: int, x1: int) -> np.ndarray:
        y0, y1 = max(0, y0), min(height, y1)
        x0, x1 = max(0, x0), min(width, x1)
        if y1 <= y0 or x1 <= x0:
            return np.empty(0, dtype=gray.dtype)
        return gray[y0:y1, x0:x1].ravel()

    ring = np.concatenate([
        band(cy - half_h, cy - inner_h, cx - inner_w, cx + inner_w),
        band(cy + inner_h, cy + half_h, cx - inner_w, cx + inner_w),
        band(cy - half_h, cy + half_h, cx - half_w, cx - inner_w),
        band(cy - half_h, cy + half_h, cx + inner_w, cx + half_w),
    ])
    if ring.size == 0:
        return 0.0
    return float((ring > 200).mean())


SELECTED_RING_RATIO = 0.15
SELECTED_RING_MARGIN = 3.0


def selected_stage_row(frame: Frame, images_dir: Path) -> StageRow | None:
    """返回当前高亮（已选中）的关卡行；判不出唯一一行时返回 None。

    正向证据：只有点中的那一行会整圈变奶白亮边。用它替代「同名 + 相邻 + 有开始按钮」
    这种间接推断——20260814 实机就是高亮还在 1-1、脚本却按间接证据开了 1-1。
    """
    rows = visible_stage_rows(frame, images_dir)
    if not rows:
        return None
    gray = cv2.cvtColor(frame.bgr, cv2.COLOR_BGR2GRAY)
    scale = frame.height / 900.0
    scored = sorted(
        ((_row_border_bright_ratio(gray, row, scale), row) for row in rows),
        key=lambda item: (-item[0], str(item[1].stage_id)),
    )
    best_ratio, best_row = scored[0]
    if best_ratio < SELECTED_RING_RATIO:
        return None
    runner_up = scored[1][0] if len(scored) > 1 else 0.0
    if runner_up > 0 and best_ratio < runner_up * SELECTED_RING_MARGIN:
        return None
    return best_row


def configured_stage_id(
    targets: list[str] | None,
    stage1: int = 1,
    stage2: int = 1,
) -> StageId | None:
    """Best-effort target for scroll direction. Exact ``章-关`` wins."""
    for raw in targets or ():
        parsed = StageId.parse(str(raw))
        if parsed is not None:
            return parsed
    try:
        low = min(int(stage1), int(stage2))
    except (TypeError, ValueError):
        return None
    if low <= 0:
        return None
    return StageId(1, low)


def stage_list_scroll_point(frame: Frame) -> tuple[int, int]:
    """Approximate the center of the numbered-stage list for scrolling."""
    return (
        frame.left + int(frame.width * 0.675),
        frame.top + int(frame.height * 0.52),
    )
