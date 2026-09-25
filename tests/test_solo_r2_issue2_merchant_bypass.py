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


def test_solo_does_not_want_merchant_when_wood_is_abundant_and_bonds_not_full():
    med = _make_mediator()
    frame = Frame(None)
    med._wood_balance = 2347

    with patch.object(med, "_bond_bar_occupancy", return_value=6), \
         patch.object(med, "_inventory_has_swallow_pill", return_value=False), \
         patch.object(med, "_devour_hold_reason", return_value=None):
        # 6/10 bonds with wood 2347 does not want merchant when occupancy threshold is 8
        # (and even with 6, if occupancy < threshold it's False)
        med._DEVOUR_BOND_OCCUPANCY = 8
        assert not med._solo_wants_merchant(frame)


def test_solo_wants_merchant_only_when_wood_low_or_pill_needed():
    med = _make_mediator()
    frame = Frame(None)

    # 1. Wood < 500 -> wants merchant
    med._wood_balance = 450
    with patch.object(med, "_bond_bar_occupancy", return_value=3), \
         patch.object(med, "_inventory_has_swallow_pill", return_value=False):
        assert med._solo_wants_merchant(frame)

    # 2. Wood >= 500 and bond >= 8 without pill -> wants merchant
    med._wood_balance = 1500
    med._DEVOUR_BOND_OCCUPANCY = 8
    with patch.object(med, "_bond_bar_occupancy", return_value=8), \
         patch.object(med, "_inventory_has_swallow_pill", return_value=False), \
         patch.object(med, "_devour_hold_reason", return_value=None):
        assert med._solo_wants_merchant(frame)

    # 3. Wood >= 500 and bond >= 8 BUT already has pill -> does not want merchant
    with patch.object(med, "_bond_bar_occupancy", return_value=8), \
         patch.object(med, "_inventory_has_swallow_pill", return_value=True), \
         patch.object(med, "_devour_hold_reason", return_value=None):
        assert not med._solo_wants_merchant(frame)


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
