# -*- coding: utf-8 -*-
"""实机 2026-09-14 战后传家宝滚动条双向校准与滚动网格指纹停机回归。

- f1750_action_before.png：真实帧上仅解锁 15 个 Boss，无滚动条（has_no_scrollbar=True）。
- game_heirloom_boss_grid_open.png：真实夹具上解锁 >15 个 Boss，有滚动条（has_no_scrollbar=False）。
- 滚动后网格指纹不变 = 到底（通用证据，避免无谓空滚）。
- 滚动步长作为可选项。
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
import pytest

from shuabao.mediator import LoopAction, Mediator, Phase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame

ROOT = Path(__file__).resolve().parents[1]
FIXTURES_B = ROOT / "tests" / "fixtures" / "hitch_postgame_20260914b"
FIXTURES_OPEN = ROOT / "tests" / "fixtures" / "hitch_live_20260911"
FRAME_1750 = "f1750_action_before.png"
FRAME_OPEN = "game_heirloom_boss_grid_open.png"


def _load_frame(path: Path) -> Frame:
    img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert img is not None, f"Failed to load fixture: {path}"
    return Frame(bgr=img, window_title="英雄三国KK", hwnd=10001, role="l1")


def _mediator(scroll_clicks: int | None = None) -> Mediator:
    settings = Settings(dry_run=True, ocr_mode="off", mode_id="lobby_hitch")
    if scroll_clicks is not None:
        settings.post_game_boss_scroll_clicks = scroll_clicks
    med = Mediator(settings, ROOT)
    med.set_phase(Phase.MAIN_LINE)
    return med


def test_post_game_boss_has_no_scrollbar_bidirectional_calibration() -> None:
    med = _mediator()
    frame_no_scroll = _load_frame(FIXTURES_B / FRAME_1750)
    frame_with_scroll = _load_frame(FIXTURES_OPEN / FRAME_OPEN)

    # f1750 确无滚动条，必须判为 True
    assert med._post_game_boss_has_no_scrollbar(frame_no_scroll, "HEIRLOOM_DIALOG") is True

    # game_heirloom_boss_grid_open 有滚动条，必须判为 False
    assert med._post_game_boss_has_no_scrollbar(frame_with_scroll, "HEIRLOOM_DIALOG") is False


def test_post_game_boss_scroll_unchanged_fingerprint_proves_bottom() -> None:
    med = _mediator()
    frame = _load_frame(FIXTURES_B / FRAME_1750)

    # 计算网格指纹
    fp = med._post_game_boss_grid_fingerprint(frame, "HEIRLOOM_DIALOG")
    assert fp is not None

    # 模拟发生过向下滚动，且记录的滚动前指纹与当前指纹一致（网格未移动）
    med._boss_challenge_scroll_attempts = 1
    med._boss_challenge_scroll_grid_fp = fp

    # 网格指纹不变证明已到底
    assert med._post_game_boss_list_at_bottom(frame, "HEIRLOOM_DIALOG") is True


def test_scroll_step_configurable() -> None:
    med_default = _mediator()
    assert med_default._post_game_boss_scroll_step == -5

    med_custom = _mediator(scroll_clicks=-8)
    assert med_custom._post_game_boss_scroll_step == -8
