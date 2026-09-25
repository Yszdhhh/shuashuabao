import sys
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.choice_policy import PolicyDecision, SlotCandidate
from shuabao.mediator import Mediator
from shuabao.settings import Settings
from shuabao.vision.capture import Frame


def panel_frame(name: str) -> Frame:
    path = ROOT / "fixtures" / "solo_round4_20260925" / f"{name}.png"
    bgr = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert bgr is not None
    return Frame(bgr, window_title="game", hwnd=1)


def test_filtered_four_slot_choice_clicks_physical_slot_three(capsys) -> None:
    med = Mediator(Settings(), ROOT)
    frame = panel_frame("f0307")
    assert med._selection_anchor(frame) is not None
    # Stall filtering leaves only 力量 at original index 3; the panel still has four slots.
    filtered = (SlotCandidate(index=3, name="力量", confidence=0.99),)
    mapped = med._policy_decision_to_hit(
        frame, "bond", PolicyDecision.select(3, "停滞选力量"), filtered, slot_count=4
    )
    assert mapped is not None
    assert mapped[1].center == (
        int(frame.width * med._CHOICE_SLOT_CENTERS_4["bond"][3][0]),
        int(frame.height * med._CHOICE_SLOT_CENTERS_4["bond"][3][1]),
    )
    assert med._policy_decision_to_hit(
        frame, "bond", PolicyDecision.select(4, "越界"), filtered, slot_count=4
    ) is None
    assert "槽位越界，零输入" in capsys.readouterr().out


def test_selected_bond_panel_cannot_be_equipment_affix() -> None:
    med = Mediator(Settings(), ROOT)
    for name in ("f0307", "f0308", "f0350"):
        frame = panel_frame(name)
        assert med._selection_anchor(frame) is not None
        assert med._find_equipment_affix_choice(frame) is None
    # f0308/f0350 really satisfy the old affix color heuristic without the panel anchor.
    with patch.object(med, "_selection_anchor", return_value=None):
        assert med._find_equipment_affix_choice(panel_frame("f0308")) is not None
        assert med._find_equipment_affix_choice(panel_frame("f0350")) is not None
