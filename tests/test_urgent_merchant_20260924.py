# -*- coding: utf-8 -*-
"""缺吞噬丹或木材不足时紧急插队去黑商（Owner 2026-09-26）。

- 物品栏没有吞噬丹或木材 < 500：黑商是当前获取支线；
- 插队是绕一趟：黑商一步结束后回到被打断的那一步，装备/拾取不被跳过；
- 蹭车不插队（黑商在蹭车环里本来就是第一步，丹是队伍资产）。
"""
from __future__ import annotations

import contextlib
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
import pytest

from shuabao.mediator import LoopAction, Mediator, PanelState, Phase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame

ROOT = Path(__file__).resolve().parents[1]
HUD = ROOT / "tests" / "fixtures" / "solo_live_20260914" / "hud_wood_1111_f0200.png"


def _hud_frame() -> Frame:
    image = cv2.imdecode(np.fromfile(str(HUD), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    return Frame(image, window_title="英雄三国KK", hwnd=10001, role="l1")


def _med(**kw) -> Mediator:
    med = Mediator(Settings(ocr_mode="off", **kw), ROOT)
    med.set_phase(Phase.MAIN_LINE)
    med._panel_state = PanelState.CLOSED
    return med


@contextlib.contextmanager
def _hud(med: Mediator, *, bond: int | None, pill: bool, wood: int | None):
    med._wood_balance = wood
    with patch.object(med, "_bond_bar_occupancy", return_value=bond), \
         patch.object(med, "_inventory_has_swallow_pill", return_value=pill):
        yield


def test_missing_pill_is_urgent_only_when_bond_bar_is_crowded() -> None:
    med = _med()
    with _hud(med, bond=8, pill=False, wood=2000):
        assert "吞噬丹" in med._urgent_merchant_reason(_hud_frame(), 100.0)
    with _hud(med, bond=8, pill=True, wood=2000):
        assert med._urgent_merchant_reason(_hud_frame(), 100.0) is None
    with _hud(med, bond=7, pill=False, wood=2000):
        assert med._urgent_merchant_reason(_hud_frame(), 100.0) is None


def test_low_wood_uses_normal_merchant_cycle_and_unknown_is_not_urgent() -> None:
    med = _med()
    with _hud(med, bond=2, pill=True, wood=499):
        assert med._urgent_merchant_reason(_hud_frame(), 100.0) is None
    with _hud(med, bond=2, pill=True, wood=500):
        assert med._urgent_merchant_reason(_hud_frame(), 100.0) is None
    with _hud(med, bond=None, pill=True, wood=None):
        assert med._urgent_merchant_reason(_hud_frame(), 100.0) is None


def test_pill_missing_is_urgent_independent_of_bond_occupancy() -> None:
    med = _med()
    with _hud(med, bond=2, pill=False, wood=1500):
        assert med._urgent_merchant_reason(_hud_frame(), 100.0) is None


@pytest.mark.parametrize("blocker", ["passenger", "cooldown", "budget", "already_there", "panel_open", "disabled"])
def test_urgent_merchant_respects_its_gates(blocker: str) -> None:
    med = _med(mode_id="lobby_hitch") if blocker == "passenger" else _med(
        merchant_enabled=blocker != "disabled"
    )
    if blocker == "cooldown":
        med._merchant_urgent_next_at = 200.0
    if blocker == "budget":
        med._merchant_budget_retry_at = 200.0
    if blocker == "already_there":
        med._l1_cycle_step = "merchant"
    if blocker == "panel_open":
        med._panel_state = PanelState.ACTIVE
    with _hud(med, bond=9, pill=False, wood=100):
        assert med._urgent_merchant_reason(_hud_frame(), 100.0) is None


def test_detour_returns_to_the_interrupted_step() -> None:
    med = _med()
    order = med._L1_CYCLE_ORDER
    med._l1_cycle_index = order.index("equipment")
    med._l1_cycle_step = "equipment"
    med._detour_l1_cycle("merchant")
    assert med._l1_cycle_step == "merchant"
    med._advance_l1_cycle("merchant")
    assert (med._l1_cycle_step, med._l1_cycle_index) == ("equipment", order.index("equipment"))
    # 正常轮到黑商时照旧前进到下一步。
    med._l1_cycle_index = order.index("merchant")
    med._l1_cycle_step = "merchant"
    med._advance_l1_cycle("merchant")
    assert med._l1_cycle_step == order[order.index("merchant") + 1]


def test_main_line_tick_detours_to_merchant_when_urgent() -> None:
    med = _med()
    med._l1_cycle_step = "skill"
    med._l1_cycle_index = 1
    with _hud(med, bond=8, pill=False, wood=2000), \
         patch.object(med, "_refresh_solo_signals", return_value=None), \
         patch.object(med, "_maybe_open_choice_panel") as opener:
        for _ in range(5):
            med._tick_main_line(_hud_frame())
            if med._l1_cycle_step == "merchant":
                break
    assert med._l1_cycle_step == "merchant"
    assert med._l1_cycle_resume == (1, "skill")
    assert med._merchant_urgent_next_at > 0
    opener.assert_not_called()


@pytest.mark.parametrize("bond,wood,action", [
    (8, 2000, "OpenBlackMerchantForDevourPill"),
    (2, 300, "OpenBlackMerchantForWood"),
])
def test_merchant_step_opens_the_shop_with_h(bond: int, wood: int, action: str) -> None:
    med = _med()
    med._l1_cycle_step = "merchant"
    med._l1_cycle_index = med._L1_CYCLE_ORDER.index("merchant")
    with _hud(med, bond=bond, pill=False, wood=wood), \
         patch.object(med, "_refresh_solo_signals", return_value=None), \
         patch.object(med, "_black_merchant_present", return_value=False), \
         patch.object(med, "_maybe_open_choice_panel", return_value=None), \
         patch.object(med, "act_key", return_value=True) as key:
        for _ in range(5):
            if med._tick_main_line(_hud_frame()) is LoopAction.Continue and key.called:
                break
    key.assert_any_call("h", action)
