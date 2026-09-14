# -*- coding: utf-8 -*-
"""云端审计 2026-09-14 A1：传家宝入口不再只靠模板。

- 阈值 0.58 → 0.70（真实命中 ≥0.83；粗体模板在「存档挑战」上最高 0.573）。
- 模板全 miss 时的受限 OCR 兜底：战后链进行中 + 顶栏=存档广场 + 传家宝 ROI 内
  的白字词框 → OCR 读到「传家宝」且连续两帧稳定，才返回标签。OCR 不单独授权点击。
真实 OCR（本机 .venv-ocr）读 f0707 细体 → '传家宝挑战' 0.996，f0346 粗体 → 0.955。
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from shuabao.mediator import Mediator, Phase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.label_boxes import white_text_word_boxes

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "hitch_postgame_20260914"
THIN = "plaza_thin_heirloom_label_f0707.png"
BOLD = "plaza_bold_heirloom_label_f0346.png"
STAGE = "real_stage_page_f0034.png"
HEIRLOOM_ROI = (0.45, 0.16, 0.80, 0.45)


def _img(name: str) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(str(FIX / name), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None, name
    return image


def _frame(name: str) -> Frame:
    return Frame(_img(name), window_title="英雄三国KK", hwnd=10001, role="l1")


def _near(box, x, y, tol=10) -> bool:
    return abs(box[0] - x) <= tol and abs(box[1] - y) <= tol


def test_word_boxes_find_heirloom_label_in_both_weights() -> None:
    thin = white_text_word_boxes(_img(THIN), HEIRLOOM_ROI)
    bold = white_text_word_boxes(_img(BOLD), HEIRLOOM_ROI)
    assert any(_near(b, 1011, 222) for b in thin), thin
    assert any(_near(b, 1019, 227) for b in bold), bold


def _fake_ocr(calls: list):
    def predict(frame, panel_id, slot):
        x0 = slot["bbox"][0]
        calls.append(slot["bbox"])
        text = "传家宝挑战" if x0 >= 1000 else "存档挑战"
        return SimpleNamespace(status="ok", raw_text=text, rec_score=0.99)

    return SimpleNamespace(is_available=True, shadow_predict=predict)


def _med(pending: bool = True) -> Mediator:
    med = Mediator(Settings(mode_id="normal_farm", ocr_mode="off"), ROOT)
    med.set_phase(Phase.MAIN_LINE)
    med._post_game_pending = pending
    med._post_game_route = "heirloom"
    return med


def test_ocr_fallback_needs_two_stable_frames_then_returns_label() -> None:
    med = _med()
    calls: list = []
    med._ocr_client = _fake_ocr(calls)
    with patch.object(med, "_find_post_game_hub_entry", return_value=None):
        first = med._post_game_hub_entry_click(_frame(THIN), "heirloom")
        med._hub_label_ocr_next_at = 0.0
        second = med._post_game_hub_entry_click(_frame(THIN), "heirloom")
    assert first is None, "one OCR sighting never authorises a click"
    assert second is not None
    assert abs(second.screen_x - 1072) <= 12  # below the 传家宝挑战 label
    assert calls, "OCR was consulted"


def test_ocr_fallback_requires_plaza_and_pending_post_game() -> None:
    calls: list = []
    med = _med(pending=False)
    med._ocr_client = _fake_ocr(calls)
    with patch.object(med, "_find_post_game_hub_entry", return_value=None):
        assert med._post_game_hub_entry_click(_frame(THIN), "heirloom") is None
    assert calls == []

    med = _med()
    med._ocr_client = _fake_ocr(calls)
    with patch.object(med, "_find_post_game_hub_entry", return_value=None):
        assert med._post_game_hub_entry_click(_frame(STAGE), "heirloom") is None
    assert calls == [], "no plaza top bar -> no OCR"


def test_ocr_fallback_ignores_other_words() -> None:
    med = _med()

    def predict(frame, panel_id, slot):
        return SimpleNamespace(status="ok", raw_text="存档挑战", rec_score=0.99)

    med._ocr_client = SimpleNamespace(is_available=True, shadow_predict=predict)
    with patch.object(med, "_find_post_game_hub_entry", return_value=None):
        for _ in range(3):
            med._hub_label_ocr_next_at = 0.0
            assert med._post_game_hub_entry_click(_frame(THIN), "heirloom") is None


def test_ocr_fallback_unavailable_without_ocr_client() -> None:
    med = _med()
    med._ocr_client = None
    with patch.object(med, "_find_post_game_hub_entry", return_value=None):
        assert med._post_game_hub_entry_click(_frame(THIN), "heirloom") is None


def test_template_path_still_first_and_threshold_raised() -> None:
    med = _med()
    seen = {}
    real_find = med.find

    def spy(frame, names, threshold=None, **kw):
        if kw.get("mode") == "post-game-hub:heirloom":
            seen["threshold"] = threshold
        return real_find(frame, names, threshold=threshold, **kw)

    with patch.object(med, "find", side_effect=spy):
        hit = med._find_post_game_hub_entry(_frame(THIN), "heirloom")
    assert seen["threshold"] == 0.70
    assert hit is not None and abs(hit.x - 1015) <= 6
