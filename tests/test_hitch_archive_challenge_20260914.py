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


def test_archive_challenge_insufficient_notice_is_detected_on_real_toast() -> None:
    """第二证据检测本身保留；扫卡规则（Owner 2026-09-14）下不再有原地重试可"停止"。"""
    frame_toast = _load_frame(FRAME_1705)
    ocr_client = ProductionShadowClient(repo_root=ROOT)
    try:
        med = _mediator(ocr_client)
        assert med._archive_challenge_insufficient_notice(frame_toast) is True
    finally:
        ocr_client.close()


def test_available_slow_to_green_card_is_swept_not_retried_in_place() -> None:
    """变绿慢的卡不漏点：扫卡轮点一次并立即转下一张，复查轮最多补一次，绝不原地重试。"""
    frame = _load_frame(FRAME_1700)
    med = _mediator()
    clicked: list[str] = []
    with patch.object(med, "_archive_hitch_card_progress_state", return_value="UNKNOWN"), \
         patch.object(med, "_archive_challenge_completed", return_value=False), \
         patch.object(med, "act_click", side_effect=lambda hit, reason, *a, **k: clicked.append(reason) or True):
        med._archive_challenge_next_at = 0.0
        med._maybe_click_archive_challenge(frame, now=100.0)
        assert clicked == ["ArchiveChallenge-skill"]
        assert med._archive_challenge_index == 1, "点完立即去下一张，不在原地等变绿"
        now = 100.0
        for _ in range(30):
            now += 2.0
            if med._maybe_click_archive_challenge(frame, now=now) is None:
                break
    assert clicked.count("ArchiveChallenge-skill") == 1
    assert clicked.count("ArchiveChallenge-skill-verify") <= 1
