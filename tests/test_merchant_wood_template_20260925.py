# -*- coding: utf-8 -*-
"""黑商木材模板真实帧回归（solo 第四轮第一局 P2）。

真实帧夹具（tests/fixtures/，1600x900 实机截图，未合成）：
- solo_merchant_wood_f0249.png：黑商 slot 2 为 8 折真木材，slot 0 为拳套
  （旧 merchant_wood.png 实为拳套图，在此帧以 0.982 误命中 slot 0）。
- solo_merchant_wood_f0296.png：黑商 slot 3 为 8 折真木材。

新模板 assets/Images/merchant_wood.png 裁自 f0249 slot 2 木材图标核心区
（44x22，避开顶部 8折角标与底部价格条），阈值保持 0.95 不动。
"""
from __future__ import annotations

import copy
from pathlib import Path

import cv2
import numpy as np

from shuabao.mediator import Mediator
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import match_any_with_margin

ROOT = Path(__file__).resolve().parents[1]
IMAGES = ROOT / "assets" / "Images"
FIXTURES = {
    # (fixture, 木材期望槽位)
    "solo_merchant_wood_f0249.png": 2,
    "solo_merchant_wood_f0296.png": 3,
}

# 与 mediator._maybe_black_merchant 内木材 find 调用逐字一致的参数。
WOOD_THRESHOLD = 0.95
WOOD_SCALES = (0.9, 1.0, 1.1)
WOOD_ROI = (0.70, 0.66, 0.90, 0.76)


def _load_gray(path: Path):
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    assert image is not None, f"template missing: {path}"
    return image


def _load_frame(name: str) -> Frame:
    path = ROOT / "tests" / "fixtures" / name
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None, f"fixture missing: {path}"
    return Frame(bgr=image, timestamp=100.0, left=0, top=0)


def _frame_hit_slot(frame: Frame, name: str):
    """复刻 mediator.find 的 ROI 回映 + _merchant_slot_index 槽位映射。"""
    res = match_any_with_margin(
        frame,
        IMAGES,
        ["merchant_wood"],
        threshold=WOOD_THRESHOLD,
        scales=WOOD_SCALES,
        roi=WOOD_ROI,
    )
    hit = res.best
    assert hit is not None, f"{name}: 木材模板在真实帧上无命中"
    assert hit.score >= WOOD_THRESHOLD, f"{name}: 木材命中分数 {hit.score} 低于阈值"
    roi_x0 = int(frame.bgr.shape[1] * WOOD_ROI[0])
    framed = copy.copy(hit)
    framed.x = hit.x + roi_x0
    slot = Mediator._merchant_slot_index(frame, framed)
    return hit, slot


def test_wood_found_in_correct_slot_on_live_frames():
    for name, expected_slot in FIXTURES.items():
        hit, slot = _frame_hit_slot(_load_frame(name), name)
        assert slot == expected_slot, f"{name}: 木材命中 slot {slot}，期望 {expected_slot}"


def test_wood_template_does_not_match_fist_slot():
    """旧模板在 f0249 以 0.982 误命中 slot 0 拳套；新模板在拳套槽位不得成峰。"""
    template = _load_gray(IMAGES / "merchant_wood.png")
    for name in FIXTURES:
        frame = _load_frame(name)
        gray = cv2.cvtColor(frame.bgr, cv2.COLOR_BGR2GRAY)
        h, w = frame.bgr.shape[:2]
        x0, y0, x1, y1 = int(w * WOOD_ROI[0]), int(h * WOOD_ROI[1]), int(w * WOOD_ROI[2]), int(h * WOOD_ROI[3])
        roi_gray = gray[y0:y1, x0:x1]
        result = cv2.matchTemplate(roi_gray, template, cv2.TM_CCOEFF_NORMED)
        tw = template.shape[1]
        # slot 0 在 ROI 内 x 范围 [0, 64)。
        slot0_peak = float(result[:, : max(1, 64 - tw + 1)].max())
        assert slot0_peak < WOOD_THRESHOLD - 0.05, f"{name}: 拳套槽位灰度峰 {slot0_peak} 过高"
        _, slot = _frame_hit_slot(frame, name)
        assert slot != 0, f"{name}: 木材命中落入拳套槽位"
