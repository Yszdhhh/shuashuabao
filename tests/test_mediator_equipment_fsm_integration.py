import sys
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.mediator import Mediator
from shuabao.policy.equipment_fsm import EquipmentSlotState
from shuabao.settings import Settings
from shuabao.vision.capture import Frame


class TestMediatorEquipmentFSMIntegration(unittest.TestCase):
    def setUp(self):
        self.med = Mediator(Settings(), ROOT)
        frame_bgr = np.full((900, 1600, 3), 100, dtype=np.uint8)
        self.frame = Frame(frame_bgr, window_title="game", hwnd=1)

    def test_upgrade_equipment_click_success_transitions_and_visual_confirm(self):
        self.med._equipment_next_at = 0.0
        with patch.object(self.med, "_equipment_slot_one_occupied", return_value=True), \
             patch.object(self.med, "act_right_click", return_value=True):
            self.med._maybe_upgrade_equipment(self.frame)
            self.assertEqual(self.med._equipment_fsm.slot_state(1), EquipmentSlotState.LEASED)
            self.assertNotEqual(self.med._equipment_fsm.last_fingerprint, "")

            changed_bgr = np.full((900, 1600, 3), 200, dtype=np.uint8)
            changed_frame = Frame(changed_bgr, window_title="game", hwnd=1)
            self.med._equipment_pending_until = 0.0
            self.med._maybe_upgrade_equipment(changed_frame)
            self.assertEqual(self.med._equipment_fsm.slot_state(1), EquipmentSlotState.CONFIRMED)

    def test_upgrade_equipment_no_visual_change_quarantines_after_timeout(self):
        self.med._equipment_next_at = 0.0
        with patch.object(self.med, "_equipment_slot_one_occupied", return_value=True), \
             patch.object(self.med, "act_right_click", return_value=True):
            self.med._maybe_upgrade_equipment(self.frame)
            self.assertEqual(self.med._equipment_fsm.slot_state(1), EquipmentSlotState.LEASED)

            now = self.med._equipment_fsm.lease_until + 1.0
            with patch("shuabao.mediator.time.time", return_value=now):
                self.med._equipment_pending_until = 0.0
                self.med._maybe_upgrade_equipment(self.frame)
                self.assertEqual(self.med._equipment_fsm.slot_state(1), EquipmentSlotState.QUARANTINED)


if __name__ == "__main__":
    unittest.main()
