"""蹭车达标 → 考古交接：自建房里必须点开始，否则死等一个永不出现的选关页。

实机症状（2026-09-20 hitch_lobby_chain bundle）：5 局跑完、旧房也退出了，
自建新房之后"又不开始游戏"，最终 `production input on UNKNOWN lobby/game
surface`，`ARCHAEOLOGY_HANDOFF_CONFIRMED=NOT_OBSERVED`。

根因是 `_tick_l0` 的 `ROOM_WAITING` 分支里存在逻辑死锁::

    if stage_page:                      # 选关页出现才前进
        -> STAGE_SELECT
    if self._archaeology_handoff_pending:
        # "绝不点 RoomStart 开新局" + "零输入等选关页自然出现"
        -> 超时 ERROR
    if room_start:
        -> 点开始（永远到不了）

**在 ROOM_WAITING 下选关页不会自然出现** —— 它是点了「开始」之后才出现的。

而"绝不点开始"这条本身是过宽的：点开始进的是 `ROOM_STARTING → STAGE_SELECT`，
不是直接开一局；真正开局要在选关页选关再确认，而选关页上
`_maybe_switch_to_archaeology` 会抢先点考古。

区分点在于**这间房是不是我们自己为交接新建的**：
* 别人的蹭车房 / 尚未自建 -> 绝不点开始（原规则保留）
* 自己刚建的房 -> 必须点开始才能到选关页

按钮 14「单人考古直达」之所以一直是通的，是因为它在**选关页之后**才 arm
（`live_scenario_capture._arm_direct_archaeology_after_stage_select`），
根本不经过这个分支。
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
from shuabao.vision.matcher import MatchResult  # noqa: E402


def _frame() -> Frame:
    return Frame(np.zeros((900, 1600, 3), dtype=np.uint8), window_title="KK", hwnd=10001)


def _hit(name: str, x: int = 700, y: int = 800) -> MatchResult:
    return MatchResult(name, 0.93, x, y, 120, 40, x + 60, y + 20)


def _mediator() -> Mediator:
    return Mediator(Settings(auto_create_room=True, dry_run=True), ROOT)


def _run_l0(med: Mediator, **anchors) -> tuple[str, list[tuple[str, str]]]:
    clicks: list[tuple[str, str]] = []

    def record(hit, reason, *a, **kw):  # noqa: ANN001
        clicks.append((getattr(hit, "name", str(hit)), reason))
        return True

    with patch.object(med, "_detect_context", return_value=anchors["context"]), \
            patch.object(med, "_find_room_start", return_value=anchors.get("room_start")), \
            patch.object(med, "_find_create_confirm", return_value=anchors.get("create_confirm")), \
            patch.object(med, "_find_map_create_room", return_value=anchors.get("map_create")), \
            patch.object(med, "_find_stage_page", return_value=anchors.get("stage_page")), \
            patch.object(med, "act_click", side_effect=record):
        med._tick_l0(_frame())
    return med.phase.name, clicks


class ArchaeologyHandoffOwnRoom(unittest.TestCase):
    def test_own_room_clicks_start_to_reach_stage_page(self) -> None:
        """自建房 + 交接待处理 -> 必须点开始，这是去选关页的唯一路径。"""
        med = _mediator()
        med.set_phase(Phase.ROOM_WAITING, "test")
        med._archaeology_handoff_pending = True
        med._archaeology_handoff_own_room = True

        phase, clicks = _run_l0(med, context="ROOM_WAITING", room_start=_hit("kk_start"))

        self.assertEqual([r for _, r in clicks], ["RoomStart"],
                         "自建房里不点开始，选关页永远不会出现")
        self.assertEqual(phase, "ROOM_STARTING")

    def test_foreign_room_still_never_clicks_start(self) -> None:
        """别人的蹭车房 / 尚未自建 -> 原规则不变，绝不点开始。"""
        med = _mediator()
        med.set_phase(Phase.ROOM_WAITING, "test")
        med._archaeology_handoff_pending = True
        med._archaeology_handoff_own_room = False

        phase, clicks = _run_l0(med, context="ROOM_WAITING", room_start=_hit("kk_start"))

        self.assertEqual(clicks, [], "非自建房必须零输入")
        self.assertEqual(phase, "ROOM_WAITING")

    def test_create_confirm_marks_the_room_as_ours(self) -> None:
        """建房确认是"这间房是我们的"的唯一凭据；没有交接待处理时不置位。"""
        med = _mediator()
        med.set_phase(Phase.CREATE_ROOM, "test")
        med._archaeology_handoff_pending = True
        med._room_dialog_filled = True

        phase, _ = _run_l0(med, context="CREATE_ROOM", create_confirm=_hit("create_confirm"))

        self.assertEqual(phase, "ROOM_WAITING")
        self.assertTrue(med._archaeology_handoff_own_room)

    def test_stage_page_still_wins_over_everything(self) -> None:
        """选关页一旦出现就直接前进，不受自建房标志影响。"""
        for own in (True, False):
            with self.subTest(own_room=own):
                med = _mediator()
                med.set_phase(Phase.ROOM_WAITING, "test")
                med._archaeology_handoff_pending = True
                med._archaeology_handoff_own_room = own

                phase, clicks = _run_l0(med, context="STAGE_SELECT", stage_page=1)

                self.assertEqual(phase, "STAGE_SELECT")
                self.assertEqual(clicks, [], "仅相位推进，不产生输入")


if __name__ == "__main__":
    unittest.main()
