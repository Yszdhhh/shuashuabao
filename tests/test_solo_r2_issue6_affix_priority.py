# -*- coding: utf-8 -*-
"""Regression tests for Issue 6: Equipment affix color priority.

Owner 2026-09-25 rule:
- Equipment upgrade affixes must follow strict color priority:
  橙/红 > 紫 > 蓝 > 绿 > 白
- In solo round 2 (f0357_action_before.png), Row 0 was Blue and Row 1 was Green,
  but old logic had Green as Rank 6 (top priority) so it selected Green over Blue.
- With the fix, Blue (Rank 3) beats Green (Rank 2), selecting equipment_affix_0.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from shuabao.mediator import Mediator
from shuabao.settings import Settings
from shuabao.vision.capture import Frame

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests/fixtures/solo_r2_20260925/equipment_affix_f0357.png"


def test_f0357_real_fixture_prefers_blue_over_green() -> None:
    """Real frame fixture f0357: Row 0 is Blue, Row 1 is Green -> must choose equipment_affix_0."""
    assert FIXTURE_PATH.is_file(), f"Fixture missing: {FIXTURE_PATH}"
    img = cv2.imdecode(np.fromfile(str(FIXTURE_PATH), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert img is not None

    med = Mediator(Settings(), ROOT)
    hit = med._find_equipment_affix_choice(Frame(img, hwnd=1, window_title="英雄三国KK"))
    assert hit is not None
    assert hit.name == "equipment_affix_0"


@pytest.mark.parametrize("higher_color,lower_color,higher_row,lower_row,expected_name", [
    # 橙/红 (BGR: 40, 40, 220) vs 紫 (BGR: 200, 40, 160)
    ((40, 40, 220), (200, 40, 160), 1, 0, "equipment_affix_1"),
    # 紫 (BGR: 200, 40, 160) vs 蓝 (BGR: 220, 100, 40)
    ((200, 40, 160), (220, 100, 40), 2, 1, "equipment_affix_2"),
    # 蓝 (BGR: 220, 100, 40) vs 绿 (BGR: 40, 200, 40)
    ((220, 100, 40), (40, 200, 40), 3, 0, "equipment_affix_3"),
    # 绿 (BGR: 40, 200, 40) vs 白 (BGR: 230, 230, 230)
    ((40, 200, 40), (230, 230, 230), 1, 0, "equipment_affix_1"),
])
def test_equipment_affix_color_hierarchy(
    higher_color: tuple[int, int, int],
    lower_color: tuple[int, int, int],
    higher_row: int,
    lower_row: int,
    expected_name: str,
) -> None:
    """Verify 橙/红 > 紫 > 蓝 > 绿 > 白 regardless of row index."""
    med = Mediator(Settings(), ROOT)
    image = np.zeros((900, 1600, 3), dtype=np.uint8)
    # Outer gold borders
    cv2.rectangle(image, (560, 215), (1039, 219), (0, 170, 230), -1)
    cv2.rectangle(image, (560, 430), (1039, 434), (0, 170, 230), -1)
    rows = (240, 285, 330, 375)
    for y in rows:
        cv2.rectangle(image, (735, y + 10), (865, y + 18), (230, 230, 230), -1)

    # Place colored blocks
    cv2.rectangle(image, (700, rows[lower_row] + 10), (760, rows[lower_row] + 28), lower_color, -1)
    cv2.rectangle(image, (700, rows[higher_row] + 10), (760, rows[higher_row] + 28), higher_color, -1)

    hit = med._find_equipment_affix_choice(Frame(image, hwnd=1, window_title="英雄三国KK"))
    assert hit is not None
    assert hit.name == expected_name


def test_equipment_affix_does_not_trigger_false_evolution_detection() -> None:
    """Real fixture f0357: affix modal must NOT be recognized as hero evolution choice or evolve button."""
    assert FIXTURE_PATH.is_file(), f"Fixture missing: {FIXTURE_PATH}"
    img = cv2.imdecode(np.fromfile(str(FIXTURE_PATH), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert img is not None
    frame = Frame(img, hwnd=1, window_title="英雄三国KK")

    med = Mediator(Settings(dry_run=True), ROOT)

    # 1. Evolve button detection must NOT hit on affix modal
    assert med._evolve_gold_center(frame) is None
    assert med._has_evolve_button(frame) is False

    # 2. Hero evolution choice detection must NOT hit on affix modal
    assert med._find_evolution_choice(frame) is None

    # 3. Affix choice is correctly detected
    hit = med._find_equipment_affix_choice(frame)
    assert hit is not None
    assert hit.name == "equipment_affix_0"
