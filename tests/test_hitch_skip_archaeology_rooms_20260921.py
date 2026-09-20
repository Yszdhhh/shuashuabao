"""蹭车进错组队考古房时必须退出 —— 但只做局内判断，绝不拖慢搜房。

Owner 2026-09-21：
* 组队考古房进去会被带进考古流程，而我们要的是蹭普通刷图局。
* **不要在找房阶段加房名识别**。搜房循环每行做一次 OCR 会直接吃掉抢房速度，
  现在已经经常来不及进 4-8 这类好房；这类房本来也不多，进错了退出即可。

所以只保留一道：局内看见 kaogu/kaoguMode 业务锚点 -> 拉黑该房 + 退出重搜。
锚点检测复用既有的 `_archaeology_mode_anchor`，搜房路径一行未动。

自己的考古交接下那个锚点是**成功**信号，必须放过 —— 见
test_own_archaeology_handoff_is_not_treated_as_a_wrong_room。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.mediator import Mediator  # noqa: E402
from shuabao.settings import Settings  # noqa: E402
from shuabao.vision.capture import Frame  # noqa: E402
from shuabao.vision.matcher import MatchResult  # noqa: E402


def _frame() -> Frame:
    return Frame(np.zeros((945, 1680, 3), dtype=np.uint8), window_title="KK", hwnd=10001)


def _med() -> Mediator:
    return Mediator(Settings(mode_id="lobby_hitch", dry_run=True), ROOT)


class InGameArchaeologyFallback(unittest.TestCase):
    def test_team_archaeology_room_is_blacklisted_and_left(self) -> None:
        med = _med()
        med._hitch_pending_room_key = "room-key-1"
        anchor = MatchResult("kaogu", 0.91, 100, 100, 40, 20, 100, 100)

        with patch.object(med, "_archaeology_mode_anchor", return_value=anchor), \
                patch.object(med, "_hitch_reset_lobby", return_value="RESET") as reset:
            result = med._tick_lobby_hitch(_frame(), context="ROOM_WAITING")

        self.assertEqual(result, "RESET")
        reset.assert_called_once()
        self.assertIn("room-key-1", med._hitch_blacklisted_room_keys)

    def test_own_archaeology_handoff_is_not_treated_as_a_wrong_room(self) -> None:
        """自己的考古交接下，该锚点是成功信号，绝不能当成进错房。"""
        med = _med()
        med._archaeology_handoff_pending = True
        anchor = MatchResult("kaoguMode", 0.91, 100, 100, 40, 20, 100, 100)

        with patch.object(med, "_archaeology_mode_anchor", return_value=anchor), \
                patch.object(med, "_hitch_reset_lobby", return_value="RESET") as reset:
            med._tick_lobby_hitch(_frame(), context="ROOM_WAITING")

        reset.assert_not_called()

    def test_no_anchor_means_no_extra_work_on_the_search_path(self) -> None:
        """没看见考古锚点时不得改变任何搜房行为（这条防的是"顺手加 OCR"）。"""
        med = _med()
        with patch.object(med, "_archaeology_mode_anchor", return_value=None), \
                patch.object(med, "_hitch_reset_lobby", return_value="RESET") as reset:
            med._tick_lobby_hitch(_frame(), context="LOBBY_ROOM")
        reset.assert_not_called()

    def test_room_search_never_reads_room_names(self) -> None:
        """搜房候选筛选必须保持纯像素/模板，不得引入任何 OCR 调用。

        Owner 明确否决了搜房阶段的房名识别（会拖慢抢房）。这条把它钉死，
        防止以后又被"顺手"加回去。
        """
        med = _med()
        self.assertFalse(hasattr(med, "_hitch_room_name_blocked"))
        self.assertFalse(hasattr(med, "_hitch_room_name_text"))

        import inspect

        source = inspect.getsource(Mediator._find_hitch_joinable_row)
        for banned in ("shadow_predict", "_ocr_client", "room_name", "ocr"):
            self.assertNotIn(banned, source.lower(),
                             f"搜房候选筛选里不得出现 {banned}")


if __name__ == "__main__":
    unittest.main()
