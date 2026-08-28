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
        # Background frame with slot 1 at (1087, 737)
        self.base_bgr = np.full((900, 1600, 3), 100, dtype=np.uint8)
        # Seed slot 1 with a known pattern
        cx, cy = 1087, 737
        self.base_bgr[cy - 10 : cy + 10, cx - 10 : cx + 10] = 50
        self.frame = Frame(self.base_bgr.copy(), window_title="game", hwnd=1)

    def test_upgrade_equipment_slot_change_confirms(self):
        self.med._equipment_next_at = 0.0
        with patch.object(self.med, "_equipment_slot_one_occupied", return_value=True), \
             patch.object(self.med, "act_right_click", return_value=True):
            self.med._maybe_upgrade_equipment(self.frame)
            self.assertEqual(self.med._equipment_fsm.slot_state(1), EquipmentSlotState.LEASED)
            fp_before = self.med._equipment_fsm.last_fingerprint
            self.assertNotEqual(fp_before, "")

            # Case 1: Slot ROI changes significantly -> CONFIRMED
            changed_bgr = self.base_bgr.copy()
            changed_bgr[727:747, 1077:1097] = 220
            changed_frame = Frame(changed_bgr, window_title="game", hwnd=1)
            self.med._equipment_pending_until = 0.0
            self.med._maybe_upgrade_equipment(changed_frame)
            self.assertEqual(self.med._equipment_fsm.slot_state(1), EquipmentSlotState.CONFIRMED)

    def test_upgrade_equipment_only_outside_roi_change_does_not_confirm(self):
        self.med._equipment_next_at = 0.0
        with patch.object(self.med, "_equipment_slot_one_occupied", return_value=True), \
             patch.object(self.med, "act_right_click", return_value=True):
            self.med._maybe_upgrade_equipment(self.frame)
            self.assertEqual(self.med._equipment_fsm.slot_state(1), EquipmentSlotState.LEASED)

            # Case 2: Only outside region changes (e.g. at (200, 200)), slot ROI untouched
            outside_bgr = self.base_bgr.copy()
            outside_bgr[100:300, 100:300] = 255
            outside_frame = Frame(outside_bgr, window_title="game", hwnd=1)
            self.med._equipment_pending_until = 0.0
            self.med._maybe_upgrade_equipment(outside_frame)
            # Slot remains LEASED because slot 1 ROI did not change
            self.assertEqual(self.med._equipment_fsm.slot_state(1), EquipmentSlotState.LEASED)

    def test_upgrade_equipment_minor_sensor_noise_does_not_false_confirm(self):
        self.med._equipment_next_at = 0.0
        with patch.object(self.med, "_equipment_slot_one_occupied", return_value=True), \
             patch.object(self.med, "act_right_click", return_value=True):
            self.med._maybe_upgrade_equipment(self.frame)
            self.assertEqual(self.med._equipment_fsm.slot_state(1), EquipmentSlotState.LEASED)

            # Case 3: Minor 1-2px noise on slot ROI (+1 intensity) -> same perceptual hash
            noisy_bgr = self.base_bgr.copy().astype(np.int16)
            noisy_bgr[727:747, 1077:1097] += 1
            noisy_frame = Frame(np.clip(noisy_bgr, 0, 255).astype(np.uint8), window_title="game", hwnd=1)
            self.med._equipment_pending_until = 0.0
            self.med._maybe_upgrade_equipment(noisy_frame)
            # Fingerprint stays identical, remains LEASED
            self.assertEqual(self.med._equipment_fsm.slot_state(1), EquipmentSlotState.LEASED)

    def test_upgrade_equipment_no_visual_change_quarantines_after_timeout(self):
        self.med._equipment_next_at = 0.0
        with patch.object(self.med, "_equipment_slot_one_occupied", return_value=True), \
             patch.object(self.med, "act_right_click", return_value=True):
            self.med._maybe_upgrade_equipment(self.frame)
            self.assertEqual(self.med._equipment_fsm.slot_state(1), EquipmentSlotState.LEASED)

            # Case 4: Zero change and timeout expires -> QUARANTINED
            now = self.med._equipment_fsm.lease_until + 1.0
            with patch("shuabao.mediator.time.time", return_value=now):
                self.med._equipment_pending_until = 0.0
                self.med._maybe_upgrade_equipment(self.frame)
                self.assertEqual(self.med._equipment_fsm.slot_state(1), EquipmentSlotState.QUARANTINED)


if __name__ == "__main__":
    unittest.main()
