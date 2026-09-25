# -*- coding: utf-8 -*-
"""Solo F/G scheduling around the 500-wood skill-first line (Owner 2026-09-24).

The HUD readers are patched (not the cached attributes): _solo_plan_panel
refreshes _wood_balance/_skill_points_seen from them on every call.
"""
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from shuabao.mediator import Mediator, Settings
from shuabao.runtime_mediator import Mediator as RuntimeMediator
from shuabao.vision.capture import Frame
from tests.test_scenario_replay import FakeClock

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

    def _plan(self, *, wood, skill, treasure=0, base_pending=True, blocked=None, step="skill", now=100.0):
        with patch.object(self.med, "_hud_wood_balance", return_value=wood), \
             patch.object(self.med, "_hud_skill_points", return_value=skill), \
             patch.object(self.med, "_hud_treasure_pending", return_value=treasure), \
             patch.object(self.med, "_bond_base_progress_pending", return_value=base_pending), \
             patch.object(self.med, "_bond_step_blocked", return_value=blocked):
            return self.med._solo_plan_panel(self.frame, now, step)

    def test_low_wood_with_skill_backlog_clicks_skills_first(self):
        target, why = self._plan(wood=200, skill=6)
        self.assertEqual(target, "skill")
        self.assertIn("< 500", why)

    def test_bond_first_from_500_wood_while_base_pending(self):
        # 羁绊优先只属于 bond 轮换步：同条件下 skill 步不再被抢占（实机 230841
        # 519 秒技能 G 100% 饿死）。bond 步的断言见本用例，skill 步见下。
        target, why = self._plan(wood=500, skill=6, step="bond")
        self.assertEqual(target, "bond")
        self.assertIn("基础羁绊未成型", why)

    def test_skill_step_not_preempted_by_bond_priority(self):
        """Solo-Executor B：木材充足/基础未成型时 skill 步也必须放行技能。"""
        clock = FakeClock(start=100.0)
        target, why = self._plan(wood=1200, skill=6, step="skill", now=clock.now())
        self.assertEqual(target, "skill")
        self.assertIn("技能积压", why)

    def test_skill_interval_slot_honored_below_backlog_force(self):
        """积压未达阈值（<4）时 skill 轮换步仍按间隔执行，不回退给羁绊。"""
        clock = FakeClock(start=100.0)
        target, why = self._plan(wood=1200, skill=2, step="skill", now=clock.now())
        self.assertEqual(target, "skill")
        self.assertIn("按轮换", why)

    def test_skill_step_with_zero_points_skips(self):
        """角标为 0 的 skill 步直接让过（不硬开面板），推进轮换。"""
        clock = FakeClock(start=100.0)
        target, why = self._plan(wood=1200, skill=0, step="skill", now=clock.now())
        self.assertIsNone(target)
        self.assertIn("角标为 0", why)

    def test_high_wood_cycle_keeps_bond_rhythm_with_skill_intervals(self):
        """高木材 + 技能积压下游完整轮换：bond 步仍归羁绊（主节奏），
        skill 步归技能（固定间隔插入，不再被羁绊抢占）。"""
        clock = FakeClock(start=100.0)
        order = self.med._l1_cycle_order()
        self.assertIn("bond", order)
        self.assertIn("skill", order)
        for step in order:
            if step not in ("bond", "skill"):
                continue
            with patch.object(self.med, "_hud_wood_balance", return_value=1200), \
                 patch.object(self.med, "_hud_skill_points", return_value=6), \
                 patch.object(self.med, "_hud_treasure_pending", return_value=0), \
                 patch.object(self.med, "_bond_base_progress_pending", return_value=True), \
                 patch.object(self.med, "_bond_step_blocked", return_value=None):
                target, why = self.med._solo_plan_panel(self.frame, clock.now(), step)
            clock.advance(2.0)
            with self.subTest(step=step):
                self.assertEqual(target, step, why)

    def test_low_wood_without_skill_backlog_does_not_lock_bond(self):
        target, _why = self._plan(wood=300, skill=0, treasure=5, step="treasure")
        self.assertEqual(target, "treasure")

    def test_skill_runs_when_bond_blocked(self):
        target, why = self._plan(wood=800, skill=6, blocked="羁绊长冷却中")
        self.assertEqual(target, "skill")
        self.assertIn("技能积压", why)

    def test_runtime_bond_presets_never_complete_the_round(self):
        """Repeat cards upgrade/merge, so F stays available all round."""
        empty_settings = Settings(ocr_mode="off", mode_id="normal_farm", cards=[], bonds=[])
        self.assertFalse(RuntimeMediator(empty_settings, ROOT)._bond_presets_complete())

        rm = RuntimeMediator(self.settings, ROOT)
        rm._bond_cards_owned = list(rm._configured_bond_presets())
        self.assertFalse(rm._bond_presets_complete())


if __name__ == "__main__":
    unittest.main()
