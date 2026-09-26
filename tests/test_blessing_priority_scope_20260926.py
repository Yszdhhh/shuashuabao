# -*- coding: utf-8 -*-
"""祝福优先的范围与节流（Owner 2026-09-26 04:59）。

原话：前期先把祝福拿完，再做点击进化、英雄选择、神器。
- 祝福没拿完时只压过进化、英雄选择、神器；拾取、装备、黑商、背包清理照常轮换。
- 为祝福开 F 守羁绊冷却，两次之间至少隔 _BLESSING_OPEN_MIN_INTERVAL_S。
- 临时口径（待 Owner 规则问题 1）：连续 _BLESSING_PRIORITY_MAX_DRY_OPENS 次开 F
  没多拿到祝福，本局不再让祝福抢占，防止三张合成后计数凑不满 3 时整局饿死。
"""
from __future__ import annotations

import contextlib
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
import pytest

from shuabao.mediator import LoopAction, Mediator, Phase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult

ROOT = Path(__file__).resolve().parents[1]
HUD = ROOT / "tests" / "fixtures" / "solo_live_20260914" / "hud_wood_1111_f0200.png"
NOW = 200.0


def _med() -> Mediator:
    med = Mediator(Settings(ocr_mode="off", bonds=["成长", "经济", "祝福"]), ROOT)
    med.set_phase(Phase.MAIN_LINE)
    med.settings.auto_artifact = True
    med._main_line_started_at = 100.0
    med._auto_task_done = True
    return med


def _tick(med: Mediator) -> list[str]:
    image = cv2.imdecode(np.fromfile(str(HUD), dtype=np.uint8), cv2.IMREAD_COLOR)
    frame = Frame(image, window_title="英雄三国KK", hwnd=10001, role="l1")
    fired: list[str] = []
    hit = MatchResult("hud_btn", 1.0, 100, 100, 10, 10, 100, 100)
    with contextlib.ExitStack() as stack:
        for name, value in (
            ("_post_game_state", None), ("_find_stage_page", False), ("_selection_anchor", None),
            ("_ensure_auto_task_enabled", None), ("_ensure_challenge_buttons", None),
            ("_maybe_ensure_hero_panel_focus", None), ("_maybe_click_tqtz", None),
            ("_maybe_clear_pressure_monsters", None), ("_handle_self_opened_compact_panel", None),
            ("_maybe_open_choice_panel", None), ("_is_in_game_hud", True),
            ("_black_merchant_present", False), ("_slot_has_artifact", True),
            ("_urgent_merchant_reason", None), ("_hud_button_hit", hit),
        ):
            stack.enter_context(patch.object(med, name, return_value=value))
        stack.enter_context(patch("time.time", return_value=NOW))
        stack.enter_context(patch.object(
            med, "act_click", side_effect=lambda _hit, reason, *a, **k: fired.append(reason) or True,
        ))
        assert med._tick_main_line(frame) == LoopAction.Continue
    return fired


def test_blessing_pending_opens_bond_before_artifact() -> None:
    med = _med()
    med._l1_cycle_step = "skill"
    assert _tick(med) == ["OpenBondPanel-BlessingPriority"]


@pytest.mark.parametrize("step", ["pickup", "equipment", "merchant", "backpack_clean"])
def test_blessing_does_not_preempt_pickup_equipment_merchant(step: str) -> None:
    med = _med()
    med._l1_cycle_step = step
    assert "OpenBondPanel-BlessingPriority" not in _tick(med)


def test_blessing_pending_still_holds_artifact_while_bond_cools_down() -> None:
    med = _med()
    med._l1_cycle_step = "skill"
    med._panel_cooldown_until["bond"] = NOW + 30.0
    fired = _tick(med)
    assert "OpenBondPanel-BlessingPriority" not in fired
    assert not any(reason.startswith("Artifact") for reason in fired)


def test_blessing_open_is_throttled_when_panel_did_not_open() -> None:
    med = _med()
    med._l1_cycle_step = "skill"
    med._last_bond_attempt = NOW - 1.0
    assert "OpenBondPanel-BlessingPriority" not in _tick(med)


def test_blessing_priority_releases_after_dry_opens_and_rearms_on_gain() -> None:
    med = _med()
    assert med._blessing_priority_active() is True
    med._blessing_dry_opens = Mediator._BLESSING_PRIORITY_MAX_DRY_OPENS
    assert med._blessing_priority_active() is False
    med._bond_cards_owned = ["祝福"]
    assert med._blessing_priority_active() is True
    med._bond_cards_owned = ["祝福", "祝福", "祝福"]
    assert med._blessing_priority_active() is False


def test_artifact_fires_once_blessings_are_done() -> None:
    med = _med()
    med._l1_cycle_step = "skill"
    med._bond_cards_owned = ["祝福", "祝福", "祝福"]
    assert "Artifact-Q" in _tick(med)
