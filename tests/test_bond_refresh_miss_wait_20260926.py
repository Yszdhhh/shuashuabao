"""刷新钮单帧漏检不得直接兜底（2026-09-26 审查）。

本页无目标、刷新次数没用完、木材够时，这一帧没找到刷新钮只零输入等下一帧；
连续 3 帧看不到才兜底。木材确认不够或刷新次数已用完时照旧直接兜底。
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np

from shuabao.choice_policy import SessionState
from shuabao.runtime_mediator import Mediator as RuntimeMediator
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult

ROOT = Path(__file__).resolve().parents[1]

SLOTS = [
    {"index": 0, "name": "白名单外甲", "confidence": 0.99, "rarity": "blue"},
    {"index": 1, "name": "白名单外乙", "confidence": 0.99, "rarity": "red"},
    {"index": 2, "name": "白名单外丙", "confidence": 0.99, "rarity": "orange"},
]


def _frame() -> Frame:
    return Frame(np.zeros((900, 1600, 3), dtype=np.uint8), window_title="英雄三国KK", hwnd=1)


def _anchor() -> MatchResult:
    return MatchResult("bond_hide_btn", 0.99, 805, 575, 94, 26, 805, 575)


def _med(refreshes: int) -> RuntimeMediator:
    med = RuntimeMediator(Settings(), ROOT)
    med._panel_opened_by_us = "bond"
    med._panel_kind = "bond"
    med._choice_session = SessionState(refreshes=refreshes, max_refreshes=3)
    return med


def _tick(med: RuntimeMediator, *, wood: int = 9999):
    med._choice_policy_idle = False
    with (
        patch.object(med, "_ocr_panel_slots", return_value=SLOTS),
        patch.object(med, "_find_panel_refresh", return_value=None),
        patch.object(med, "_panel_has_giveup", return_value=False),
        patch.object(med, "_extract_live_set_progress", return_value=None),
        patch.object(med, "_bond_bar_occupancy", return_value=None),
        patch.object(med, "_bond_refresh_affordable", return_value=(wood >= 100, wood, 100)),
    ):
        return med._find_reward_choice(_frame(), _anchor())


def _picked(result) -> str | None:
    return None if result is None else result[1].name


def test_single_missing_refresh_frame_waits_instead_of_fallback() -> None:
    med = _med(refreshes=0)
    assert _tick(med) is None
    assert med._choice_policy_idle is True
    assert _tick(med) is None
    # 连续第 3 帧仍看不到刷新钮才兜底。
    assert _picked(_tick(med)) == "ocr_bond:白名单外乙"


def test_insufficient_wood_falls_back_without_waiting() -> None:
    med = _med(refreshes=0)
    assert _picked(_tick(med, wood=50)) == "ocr_bond:白名单外乙"
    assert med._bond_refresh_miss_frames == 0


def test_exhausted_refreshes_fall_back_without_waiting() -> None:
    med = _med(refreshes=3)
    assert _picked(_tick(med)) == "ocr_bond:白名单外乙"
    assert med._bond_refresh_miss_frames == 0
