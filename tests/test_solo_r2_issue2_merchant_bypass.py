from pathlib import Path
from unittest.mock import patch
import pytest

from shuabao.mediator import Mediator, Frame, Settings, PanelState, Phase, LoopAction

ROOT = Path(__file__).resolve().parents[1]


def _make_mediator(**kwargs) -> Mediator:
    settings = Settings(ocr_mode="off", dry_run=True, **kwargs)
    med = Mediator(settings, ROOT)
    med.set_phase(Phase.MAIN_LINE)
    med._panel_state = PanelState.CLOSED
    return med


def test_solo_does_not_want_merchant_when_pill_and_wood_are_available():
    med = _make_mediator()
    frame = Frame(None)
    med._wood_balance = 2347

    with patch.object(med, "_bond_bar_occupancy", return_value=6), \
         patch.object(med, "_inventory_has_swallow_pill", return_value=True), \
         patch.object(med, "_devour_hold_reason", return_value=None):
        # 6/10 bonds are irrelevant when the bag has a pill and wood is abundant.
        med._DEVOUR_BOND_OCCUPANCY = 8
        assert not med._solo_wants_merchant(frame)


def test_solo_wants_merchant_when_wood_is_not_overflowing_or_emergency_pill_needed():
    med = _make_mediator()
    frame = Frame(None)

    # Low wood is a fallback even when the bag already has a pill.
    med._wood_balance = 450
    with patch.object(med, "_bond_bar_occupancy", return_value=3), \
         patch.object(med, "_inventory_has_swallow_pill", return_value=True):
        assert med._solo_wants_merchant(frame)

    # At overflow wood, missing pill is urgent only when the bond bar is crowded.
    med._wood_balance = 1500
    med._DEVOUR_BOND_OCCUPANCY = 8
    with patch.object(med, "_bond_bar_occupancy", return_value=3), \
         patch.object(med, "_inventory_has_swallow_pill", return_value=False), \
         patch.object(med, "_devour_hold_reason", return_value=None):
        assert not med._solo_wants_merchant(frame)

    # Both needs satisfied means no merchant detour.
    with patch.object(med, "_bond_bar_occupancy", return_value=8), \
         patch.object(med, "_inventory_has_swallow_pill", return_value=True), \
         patch.object(med, "_devour_hold_reason", return_value=None):
        assert not med._solo_wants_merchant(frame)

    # Unknown wood does not imply overflow or trigger a normal merchant visit.
    med._wood_balance = None
    with patch.object(med, "_bond_bar_occupancy", return_value=3), \
         patch.object(med, "_inventory_has_swallow_pill", return_value=True):
        assert not med._solo_wants_merchant(frame)

    # Emergency pill visit remains at overflow wood when occupancy reaches 8.
    med._wood_balance = None
    with patch.object(med, "_bond_bar_occupancy", return_value=8), \
         patch.object(med, "_inventory_has_swallow_pill", return_value=False), \
         patch.object(med, "_devour_hold_reason", return_value=None):
        assert med._solo_wants_merchant(frame)


HUD = ROOT / "tests" / "fixtures" / "solo_live_20260914" / "hud_wood_1111_f0200.png"


def _hud_frame() -> Frame:
    import numpy as np
    import cv2
    image = cv2.imdecode(np.fromfile(str(HUD), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    return Frame(image, window_title="英雄三国KK", hwnd=10001, role="l1")


def test_solo_cycle_skips_merchant_when_unneeded():
    med = _make_mediator()
    frame = _hud_frame()
    med._l1_cycle_step = "merchant"
    med._l1_cycle_index = med._L1_CYCLE_ORDER.index("merchant")

    with patch.object(med, "_refresh_solo_signals", return_value=None), \
         patch.object(med, "_evolve_button_hit", return_value=None), \
         patch.object(med, "_solo_wants_merchant", return_value=False), \
         patch.object(med, "_maybe_black_merchant") as mock_merchant:
        res = med._tick_main_line(frame)
        assert res == LoopAction.Continue
        # Step advanced away from merchant
        assert med._l1_cycle_step != "merchant"
        mock_merchant.assert_not_called()
