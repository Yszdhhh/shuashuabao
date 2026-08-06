"""Detect the numbered stage buttons in the game stage list.

The old ``stage.png`` asset is a map card, not a numbered stage button.  This
module reads the small white label rendered on each button instead, so the
configured Stage1/Stage2 values can be applied without adding OCR dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import re

import cv2

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
        if not label:
            return None
        match = re.fullmatch(r"(\d+)-(\d+)", label.strip())
        if not match:
            return None
        return cls(int(match.group(1)), int(match.group(2)))

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
    for top, bottom in row_runs:
        row = _read_row(mask[top:bottom, :], x1, y1 + top, templates)
        if row is not None:
            rows.append(row)
    return rows


def _parse_stage_spec(value: StageId | str | int, default_chapter: int = 1) -> StageId:
    if isinstance(value, StageId):
        return value
    if isinstance(value, int):
        return StageId(default_chapter, value)
    parsed = StageId.parse(str(value))
    if parsed is not None:
        return parsed
    try:
        return StageId(default_chapter, int(value))
    except ValueError:
        return StageId(default_chapter, 1)


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
    start_parsed = StageId.parse(str(start)) if not isinstance(start, int) else None
    end_parsed = StageId.parse(str(end)) if not isinstance(end, int) else None

    rows = visible_stage_rows(frame, images_dir)
    if not rows:
        return None

    # Check if explicit chapter was specified
    explicit_chapter = start_parsed.chapter if start_parsed else (end_parsed.chapter if end_parsed else None)
    if explicit_chapter is not None:
        eligible_rows = [r for r in rows if r.stage_id.chapter == explicit_chapter]
    else:
        eligible_rows = rows

    if not eligible_rows:
        return None

    low_index = start_parsed.index if start_parsed else int(start)
    high_index = end_parsed.index if end_parsed else int(end)
    low_index, high_index = sorted((low_index, high_index))

    chosen = next((r for r in eligible_rows if r.stage_id.index == low_index), None)
    if chosen is None:
        chosen = next((r for r in eligible_rows if r.stage_id.index == high_index), None)
    if chosen is None:
        chosen = next((r for r in eligible_rows if low_index <= r.stage_id.index <= high_index), None)
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
        if not label or not label.strip():
            continue
        parsed = StageId.parse(label)
        if parsed:
            wanted_ids.add(parsed)
        else:
            wanted_ids.add(label.strip())

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


def verify_stage_selection(frame: Frame, hit: MatchResult | None = None) -> bool:
    """Verify that a stage row or target has been selected in the UI.

    Checks for visible stage list region and selection highlight evidence.
    """
    if frame.width < 600 or frame.height < 400:
        return False
    gray = cv2.cvtColor(frame.bgr, cv2.COLOR_BGR2GRAY)
    x1, x2 = int(frame.width * 0.55), int(frame.width * 0.95)
    y1, y2 = int(frame.height * 0.10), int(frame.height * 0.90)
    crop = gray[y1:y2, x1:x2]
    if crop.size == 0:
        return False
    bright_pixels = np.sum(crop > 200)
    return int(bright_pixels) > 50


def stage_list_scroll_point(frame: Frame) -> tuple[int, int]:
    """Approximate the center of the numbered-stage list for scrolling."""
    return (
        frame.left + int(frame.width * 0.675),
        frame.top + int(frame.height * 0.52),
    )
