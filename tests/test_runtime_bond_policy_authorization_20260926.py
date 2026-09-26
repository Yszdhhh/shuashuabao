from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np

from shuabao.choice_policy import SessionState
from shuabao.mediator import Mediator as CoreMediator
from shuabao.runtime_mediator import Mediator as RuntimeMediator
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult

ROOT = Path(__file__).resolve().parents[1]


def _frame() -> Frame:
    return Frame(np.zeros((900, 1600, 3), dtype=np.uint8), window_title="英雄三国KK", hwnd=1)


def _anchor() -> MatchResult:
    return MatchResult("bond_hide_btn", 0.99, 805, 575, 94, 26, 805, 575)


def _run_runtime_bond(
    med: RuntimeMediator,
    slots: list[dict],
    *,
    can_refresh: bool,
    refreshes: int,
) -> tuple[str, MatchResult] | None:
    med._panel_opened_by_us = "bond"
    med._panel_kind = "bond"
    med._choice_session = SessionState(refreshes=refreshes, max_refreshes=3)
    refresh = MatchResult("bond_refresh_btn", 0.99, 1038, 575, 56, 26, 1038, 575)
    with (
        patch.object(med, "_ocr_panel_slots", return_value=slots),
        patch.object(med, "_panel_can_refresh", return_value=can_refresh),
        patch.object(med, "_panel_has_giveup", return_value=False),
        patch.object(med, "_find_panel_refresh", return_value=refresh),
        patch.object(med, "_extract_live_set_progress", return_value=None),
        patch.object(med, "_bond_bar_occupancy", return_value=None),
        patch.object(med, "_bond_refresh_affordable", return_value=(True, 9999, 40)),
    ):
        return med._find_reward_choice(_frame(), _anchor())


def test_runtime_default_settings_allows_mandatory_blessing() -> None:
    med = RuntimeMediator(Settings(), ROOT)
    result = _run_runtime_bond(
        med,
        [
            {"index": 0, "name": "祝福", "confidence": 0.99, "rarity": "green"},
            {"index": 1, "name": "白名单外甲", "confidence": 0.99, "rarity": "red"},
            {"index": 2, "name": "白名单外乙", "confidence": 0.99, "rarity": "orange"},
        ],
        can_refresh=True,
        refreshes=0,
    )
    assert result is not None
    assert result[1].name == "ocr_bond:祝福"


def test_runtime_default_settings_allows_exhausted_off_whitelist_fallback() -> None:
    med = RuntimeMediator(Settings(), ROOT)
    result = _run_runtime_bond(
        med,
        [
            {"index": 0, "name": "白名单外甲", "confidence": 0.99, "rarity": "blue"},
            {"index": 1, "name": "白名单外乙", "confidence": 0.99, "rarity": "red"},
            {"index": 2, "name": "白名单外丙", "confidence": 0.99, "rarity": "orange"},
        ],
        can_refresh=False,
        refreshes=3,
    )
    assert result is not None
    assert result[1].name == "ocr_bond:白名单外乙"


def test_runtime_default_settings_refreshes_before_fallback() -> None:
    med = RuntimeMediator(Settings(), ROOT)
    slots = [
        {"index": 0, "name": "白名单外甲", "confidence": 0.99, "rarity": "blue"},
        {"index": 1, "name": "白名单外乙", "confidence": 0.99, "rarity": "red"},
        {"index": 2, "name": "白名单外丙", "confidence": 0.99, "rarity": "orange"},
    ]
    # OCR 刷新决策要第二帧确认：第一帧零输入，第二帧才点刷新。
    assert _run_runtime_bond(med, slots, can_refresh=True, refreshes=0) is None
    med._choice_policy_idle = False
    result = _run_runtime_bond(med, slots, can_refresh=True, refreshes=0)
    assert result is not None
    assert result[1].name == "bond_refresh_btn"


def test_runtime_blocks_unreadable_policy_selection() -> None:
    med = RuntimeMediator(Settings(), ROOT)
    unreadable = MatchResult("ocr_bond:", 1.0, 560, 330, 1, 1, 560, 330)
    with (
        patch.object(med, "_panel_kind_of", return_value="bond"),
        patch.object(CoreMediator, "_find_reward_choice", return_value=("bond", unreadable)),
    ):
        assert med._find_reward_choice(_frame(), _anchor()) is None
    assert med._choice_policy_idle is True


def test_runtime_jinzifa_only_page_is_zero_input_without_anshen() -> None:
    med = RuntimeMediator(Settings(), ROOT)
    result = _run_runtime_bond(
        med,
        [{"index": 0, "name": "禁字法", "confidence": 0.99, "rarity": "red"}],
        can_refresh=False,
        refreshes=3,
    )
    assert result is None
    assert med._choice_policy_idle is True
