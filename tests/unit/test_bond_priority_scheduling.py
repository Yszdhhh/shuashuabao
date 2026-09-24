# -*- coding: utf-8 -*-
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np

from shuabao.mediator import Mediator, Settings, PanelState
from shuabao.runtime_mediator import Mediator as RuntimeMediator
from shuabao.vision.capture import Frame
from shuabao.choice_policy import PolicySettings

ROOT = Path(__file__).resolve().parents[2]


class TestBondPriorityScheduling(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(
            ocr_mode="off",
            mode_id="normal_farm",
            cards=["大圣", "封神"],
            bonds=["经济", "祝福"],
            skills=["asj", "asjg"],
        )
        self.med = Mediator(self.settings, ROOT)
        self.frame = Frame(
            np.zeros((900, 1600, 3), dtype=np.uint8),
            window_title="英雄三国KK",
            hwnd=10001,
            role="l1",
        )

    def test_bond_priority_when_base_pending_even_with_skill_backlog(self):
        """基础羁绊未成型时，即使技能积压（如 6 点）且木材仅 200，也必须优先锁定 bond。"""
        self.med._wood_balance = 200
        self.med._skill_points_seen = 6
        self.med._skill_points_seen_at = 100.0

        with patch.object(self.med, "_bond_base_progress_pending", return_value=True), \
             patch.object(self.med, "_bond_step_blocked", return_value=None):
            target, why = self.med._solo_plan_panel(self.frame, 100.0, "skill")
            self.assertEqual(target, "bond")
            self.assertIn("基础羁绊未成型", why)

    def test_skill_runs_when_bond_blocked_during_base_pending(self):
        """基础羁绊未成型但羁绊受阻（如木材不足 20）时，允许消耗积压的技能点。"""
        self.med._wood_balance = 10
        self.med._skill_points_seen = 6
        self.med._skill_points_seen_at = 100.0

        with patch.object(self.med, "_bond_base_progress_pending", return_value=True), \
             patch.object(self.med, "_bond_step_blocked", return_value="木材 10 < 20"):
            target, why = self.med._solo_plan_panel(self.frame, 100.0, "skill")
            self.assertEqual(target, "skill")
            self.assertIn("技能积压", why)

    def test_runtime_mediator_bond_presets_complete_semantics(self):
        """RuntimeMediator._bond_presets_complete: 空配置不误判为 True；未拿齐不返回 True。"""
        empty_settings = Settings(ocr_mode="off", mode_id="normal_farm", cards=[], bonds=[])
        rm_empty = RuntimeMediator(empty_settings, ROOT)
        self.assertFalse(rm_empty._bond_presets_complete())

        rm_configured = RuntimeMediator(self.settings, ROOT)
        rm_configured._bond_cards_owned = ["经济"]
        self.assertFalse(rm_configured._bond_presets_complete())


if __name__ == "__main__":
    unittest.main()
