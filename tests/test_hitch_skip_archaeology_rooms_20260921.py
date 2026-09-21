"""搜房阶段不得引入房名识别 / OCR。

Owner 明确否决了搜房阶段的房名识别（会拖慢抢房速度）。
本文件钉死此项断言，防止被顺手加回去。
"""

from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.mediator import Mediator  # noqa: E402
from shuabao.settings import Settings  # noqa: E402


def _med() -> Mediator:
    return Mediator(Settings(mode_id="lobby_hitch", dry_run=True), ROOT)


class RoomSearchNoOcrCheck(unittest.TestCase):
    def test_room_search_never_reads_room_names(self) -> None:
        """搜房候选筛选必须保持纯像素/模板，不得引入任何 OCR 调用。

        Owner 明确否决了搜房阶段的房名识别（会拖慢抢房）。这条把它钉死，
        防止以后又被"顺手"加回去。
        """
        med = _med()
        self.assertFalse(hasattr(med, "_hitch_room_name_blocked"))
        self.assertFalse(hasattr(med, "_hitch_room_name_text"))

        source = inspect.getsource(Mediator._find_hitch_joinable_row)
        for banned in ("shadow_predict", "_ocr_client", "room_name", "ocr"):
            self.assertNotIn(banned, source.lower(),
                             f"搜房候选筛选里不得出现 {banned}")


if __name__ == "__main__":
    unittest.main()
