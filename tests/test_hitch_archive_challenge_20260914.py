# -*- coding: utf-8 -*-
"""实机 2026-09-14 战后存档挑战 0/8 识别与跳过回归。

- f1700_action_before.png：真实帧上卡位 2(gem)、3(loot)、4(key)、6(blessing) 均为 0/8。
  历史代码因 card_index 限制及正则缺少对 018 的解析，未判定为 UNAVAILABLE。
- f1705_action_after.png：点击后弹出「今日挑战次数不足」toast，作为第二证据。
- 严禁对可挑战但变绿慢的卡少点。
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import cv2
import pytest

from shuabao.mediator import LoopAction, Mediator, Phase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.ocr_shadow.production import ProductionShadowClient

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "hitch_postgame_20260914b"
FRAME_1700 = "f1700_action_before.png"
FRAME_1705 = "f1705_action_after.png"


import numpy as np

def _load_frame(name: str) -> Frame:
    path = FIXTURES / name
    img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert img is not None, f"Failed to load fixture: {path}"
    return Frame(bgr=img, window_title="英雄三国KK", hwnd=10001, role="l1")


def _mediator(ocr_client: ProductionShadowClient | None = None) -> Mediator:
    med = Mediator(Settings(dry_run=True, ocr_mode="live", mode_id="lobby_hitch"), ROOT)
    if ocr_client is not None:
        ocr_client.start()
        med._ocr_client = ocr_client
    med.set_phase(Phase.MAIN_LINE)
    return med


def test_archive_card_progress_state_identifies_unavailable_cards() -> None:
    frame = _load_frame(FRAME_1700)
    ocr_client = ProductionShadowClient(repo_root=ROOT)
    try:
        med = _mediator(ocr_client)
        # 卡位 2(gem), 3(loot), 4(key), 6(blessing) 真实画面上均为红色 0/8
        # 必须明确解析为 UNAVAILABLE，绝不能判为 UNKNOWN 或 AVAILABLE
        for card_idx, name in [(2, "gem"), (3, "loot"), (4, "key"), (6, "blessing")]:
            state = med._archive_hitch_card_progress_state(frame, card_idx)
            assert state == "UNAVAILABLE", f"Card {card_idx} ({name}) expected UNAVAILABLE, got {state}"
    finally:
        ocr_client.close()


def test_archive_challenge_skips_unavailable_cards_without_clicks() -> None:
    frame = _load_frame(FRAME_1700)
    ocr_client = ProductionShadowClient(repo_root=ROOT)
    try:
        med = _mediator(ocr_client)
        # 初始化在卡位 2 (gem，0/8)
        med._archive_challenge_index = 2
        med._archive_challenge_next_at = 0.0

        clicked_targets: list[str] = []
        with patch.object(med, "act_click", side_effect=lambda hit, reason, *a, **k: clicked_targets.append(reason) or True):
            action = med._maybe_click_archive_challenge(frame, now=100.0)

        # 0/8 的卡应该直接被跳过，而不是被点击
        assert not any("gem" in t for t in clicked_targets), f"Unavailable gem should not be clicked: {clicked_targets}"
        assert not any("loot" in t for t in clicked_targets), f"Unavailable loot should not be clicked: {clicked_targets}"
    finally:
        ocr_client.close()


def test_archive_challenge_second_evidence_stops_retry() -> None:
    frame_toast = _load_frame(FRAME_1705)
    ocr_client = ProductionShadowClient(repo_root=ROOT)
    try:
        med = _mediator(ocr_client)
        # 验证第二证据：检测「今日挑战次数不足」
        assert med._archive_challenge_insufficient_notice(frame_toast) is True

        # 当处于某卡点击确认阶段，若下一帧出现次数不足提示，应立即推进到下一张卡，不重试满 3 次
        med._archive_challenge_index = 2
        med._archive_challenge_confirm_attempts = 1
        med._archive_challenge_next_at = 0.0

        with patch.object(med, "act_click", return_value=True):
            med._maybe_click_archive_challenge(frame_toast, now=100.0)

        assert med._archive_challenge_index > 2, "Should advance to next card upon insufficient notice"
        assert med._archive_challenge_confirm_attempts == 0
    finally:
        ocr_client.close()


def test_available_slow_to_green_card_is_not_skipped() -> None:
    # 验证约束：严禁对「可挑战但变绿慢」的卡少点
    frame = _load_frame(FRAME_1700)
    med = _mediator()
    # 模拟某卡处于 UNKNOWN 状态（无法断定 0/8）且无「次数不足」提示
    with patch.object(med, "_archive_hitch_card_progress_state", return_value="UNKNOWN"), \
         patch.object(med, "_archive_challenge_insufficient_notice", return_value=False), \
         patch.object(med, "_archive_challenge_completed", return_value=False):
        med._archive_challenge_index = 0  # skill 卡
        med._archive_challenge_next_at = 0.0
        med._archive_challenge_confirm_attempts = 0

        # 第 1 次点击
        clicked: list[str] = []
        with patch.object(med, "act_click", side_effect=lambda hit, reason, *a, **k: clicked.append(reason) or True):
            med._maybe_click_archive_challenge(frame, now=100.0)
        assert len(clicked) == 1
        assert med._archive_challenge_index == 0  # 留在当前卡等待变绿
        assert med._archive_challenge_confirm_attempts == 1

        # 第 2 次点击（仍未变绿，必须允许重试确认，绝不能提前跳过）
        med._archive_challenge_next_at = 0.0
        with patch.object(med, "act_click", side_effect=lambda hit, reason, *a, **k: clicked.append(reason) or True):
            med._maybe_click_archive_challenge(frame, now=105.0)
        assert len(clicked) == 2
        assert med._archive_challenge_index == 0
        assert med._archive_challenge_confirm_attempts == 2

