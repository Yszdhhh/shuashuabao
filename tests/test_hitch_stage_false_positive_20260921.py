# -*- coding: utf-8 -*-
"""实机 2026-09-21 蹭车「进游戏就退出」+ 考古确认假阳性回归。

- hitch_lobby_chain_20260921_230228_111691 f0150：房主开局后的加载图。
  c416ff4 在共用的 ``_classify_glyph`` 里加了「细高=1」捷径（给局内顶栏难度
  统计用），选关行解析被污染，背景细纹读成 ``1-1`` → 选关页 → 误判误开房 →
  QUIT → 找不到退出按钮 → 停机。支线统计不得影响蹭车主线。
- solo_ingame_chain_20260920_202513_573591：点「考古模式」后仍停在选关页的帧
  f0009 上，旧锚点 ``kaogu``（就是那个按钮）命中 0.96，会把"点了没反应"
  判成考古成功；真实考古地图 f0012 顶栏 ``kaoguMode`` 0.925。考古地图背景
  还会杂读出两行（1-17/1-18），同样不得获得选关页 authority。
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from shuabao.mediator import Mediator
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.stage_selector import visible_stage_rows

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "hitch_stage_false_positive_20260921"
REAL_STAGE = ROOT / "tests" / "fixtures" / "hitch_postgame_20260914" / "real_stage_page_f0034.png"
IMAGES = ROOT / "assets" / "Images"


def _frame(path: Path) -> Frame:
    bgr = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert bgr is not None, path
    return Frame(bgr, window_title="英雄三国KK", hwnd=4242)


def _med() -> Mediator:
    return Mediator(Settings(dry_run=True, ocr_mode="off"), ROOT)


def test_loading_screen_streaks_are_not_stage_rows() -> None:
    frame = _frame(FIXTURES / "loading_screen_f0150.png")
    assert visible_stage_rows(frame, IMAGES) == []
    assert _med()._find_stage_page(frame) is False


def test_real_stage_page_keeps_full_row_column() -> None:
    frame = _frame(REAL_STAGE)
    labels = [row.label for row in visible_stage_rows(frame, IMAGES)]
    assert labels == [f"1-{i}" for i in range(1, 13)]
    assert _med()._find_stage_page(frame) is True


def test_archaeology_map_is_not_a_stage_page() -> None:
    frame = _frame(FIXTURES / "archaeology_map_f0012.png")
    assert _med()._find_stage_page(frame) is False


def test_archaeology_anchor_needs_the_map_title_not_the_button() -> None:
    med = _med()
    assert med._archaeology_mode_anchor(_frame(FIXTURES / "stage_page_after_arch_click_f0009.png")) is None
    assert med._archaeology_mode_anchor(_frame(REAL_STAGE)) is None
    hit = med._archaeology_mode_anchor(_frame(FIXTURES / "archaeology_map_f0012.png"))
    assert hit is not None and hit.score >= 0.85
