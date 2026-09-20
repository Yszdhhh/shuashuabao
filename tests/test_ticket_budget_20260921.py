"""挑战券动态预算：死算为主、机会性读数校正，票不够就转考古收尾。

Owner 定的模型（2026-09-21）：
* 正常每局消耗 2 张。
* **每局都尝试读一次**真实剩余来校正；读不出是常态（蹭车大部分时间待在 KK
  房间列表，看不见那个计数），靠死算兜着 —— 读不出就是容错空间。
* 跨零点补票之类的特殊情况，靠"真实读数一律覆盖死算"自然收敛。
* 两条收尾出口：**预设局数到了**，或者**测算票不够再来一局**。后者在票不够的
  那一局之后就不再搜房，直接走考古。

一线纪律：**读不出 ≠ 0**。从没读到过读数时预算模型弃权（不限制），
因为它只决定"要不要再搜一把房"，不授权任何输入；误判成耗尽会让长线程测试
提前收工，真正的下限由 cycle_num 与 --duration 兜。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.mediator import Mediator, Phase  # noqa: E402
from shuabao.settings import Settings  # noqa: E402
from shuabao.vision.capture import Frame  # noqa: E402


def _frame() -> Frame:
    return Frame(np.zeros((900, 1600, 3), dtype=np.uint8), window_title="KK", hwnd=10001)


def _med(**kw) -> Mediator:
    base = dict(auto_create_room=True, dry_run=True, hitch_after_goal="arch",
                auto_archaeology=True, cycle_num=100, mode_id="lobby_hitch")
    base.update(kw)
    return Mediator(Settings(**base), ROOT)


class TicketReadingCalibrates(unittest.TestCase):
    def test_unreadable_never_becomes_zero(self) -> None:
        med = _med()
        with patch.object(med, "_hud_counter", return_value=None):
            self.assertIsNone(med._observe_ticket_balance(_frame(), now=1000.0))
        self.assertIsNone(med._ticket_balance)
        self.assertIsNone(med._ticket_projected_remaining())
        # 未知不是耗尽：仍然允许再来一局
        self.assertTrue(med._ticket_budget_allows_another_round())

    def test_reading_resets_dead_reckoning(self) -> None:
        med = _med()
        with patch.object(med, "_hud_counter", return_value=120):
            med._observe_ticket_balance(_frame(), now=1000.0)
        self.assertEqual(med._ticket_projected_remaining(), 120)

        med._ticket_budget_spent_one_round()
        med._ticket_budget_spent_one_round()
        self.assertEqual(med._ticket_projected_remaining(), 116, "死算按每局 2 张扣")

        # 真实读数一律覆盖死算（含跨零点补票这类"变多了"的情况）
        with patch.object(med, "_hud_counter", return_value=130):
            med._observe_ticket_balance(_frame(), now=2000.0)
        self.assertEqual(med._ticket_projected_remaining(), 130)
        self.assertEqual(med._ticket_rounds_since_read, 0)

    def test_read_interval_is_throttled(self) -> None:
        med = _med()
        with patch.object(med, "_hud_counter", return_value=50) as counter:
            med._observe_ticket_balance(_frame(), now=1000.0)
            med._observe_ticket_balance(_frame(), now=1000.5)
            self.assertEqual(counter.call_count, 1, "间隔内不得重复 OCR")
            med._observe_ticket_balance(_frame(), now=1000.0 + med._TICKET_READ_INTERVAL_S)
            self.assertEqual(counter.call_count, 2)


class TicketBudgetGatesNextRound(unittest.TestCase):
    def test_enough_tickets_keeps_searching(self) -> None:
        med = _med()
        med._ticket_balance, med._ticket_rounds_since_read = 10, 0
        self.assertTrue(med._ticket_budget_allows_another_round())

        med.set_phase(Phase.MAIN_LINE, "test")
        med._finish_hitch_round(1000.0, "next round")
        self.assertEqual(med.phase, Phase.LOBBY_ROOM, "票够就回大厅继续搜房")

    def test_budget_out_routes_to_archaeology_without_searching(self) -> None:
        """票不够再来一局 -> 不搜房，直接进考古收尾（与局数达标同一条出口）。"""
        med = _med()
        med._ticket_balance, med._ticket_rounds_since_read = 2, 0  # 本局扣完只剩 0
        med.set_phase(Phase.MAIN_LINE, "test")

        med._finish_hitch_round(1000.0, "budget out")

        self.assertEqual(med.phase, Phase.ROOM_WAITING)
        self.assertTrue(med._archaeology_handoff_pending)
        self.assertTrue(med._room_leave_pending)
        self.assertEqual(med.settings.mode_id, "normal_farm", "交接后必须离开蹭车模式")
        self.assertTrue(med.settings.auto_create_room, "考古要自建房，建房开关必须解禁")
        self.assertLess(med.game_count, med.settings.cycle_num, "这条出口不是局数达标")

    def test_unknown_balance_does_not_end_the_run(self) -> None:
        """从没读到过读数 -> 不得误判耗尽而提前收工。"""
        med = _med()
        med.set_phase(Phase.MAIN_LINE, "test")
        med._finish_hitch_round(1000.0, "unknown balance")
        self.assertEqual(med.phase, Phase.LOBBY_ROOM)

    def test_goal_reached_still_wins(self) -> None:
        """局数达标这条出口不受预算模型影响。"""
        med = _med(cycle_num=1)
        med._ticket_balance, med._ticket_rounds_since_read = 999, 0
        med.set_phase(Phase.MAIN_LINE, "test")

        med._finish_hitch_round(1000.0, "goal")

        self.assertEqual(med.phase, Phase.ROOM_WAITING)
        self.assertTrue(med._archaeology_handoff_pending)


if __name__ == "__main__":
    unittest.main()
