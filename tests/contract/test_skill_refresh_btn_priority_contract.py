"""技能刷新必须点面板专用钮，不能被通用 refresh 模板抢走。

giveup_panel_not_fail 在生产锚点上 FAIL ledger_mismatch=1，不是没点，是点错了：

    期望 skill_refresh_btn @ [1020, 654]
    实际 refresh            @ [1171, 677]（分数 0.936 压过专用钮 0.759）

根因：_find_panel_refresh 按 names 顺序返回第一个命中，skill 列表把通用
`refresh` 放在专用 `skill_refresh_btn` 前面。函数注释已经防了 bwRefresh，
漏防了 refresh。这是产品语义，不是某次夹具的偶然。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.mediator import Mediator  # noqa: E402
from shuabao.settings import Settings  # noqa: E402
from shuabao.vision.capture import Frame  # noqa: E402
from shuabao.vision.matcher import MatchResult  # noqa: E402

DEDICATED = MatchResult("skill_refresh_btn", 0.759, 1000, 640, 40, 28, 1020, 654)
GENERIC = MatchResult("refresh", 0.936, 1151, 663, 40, 28, 1171, 677)


def _frame() -> Frame:
    return Frame(np.zeros((1080, 1920, 3), dtype=np.uint8),
                 window_title="英雄三国KK", hwnd=10001, role="l1")


def _med() -> Mediator:
    return Mediator(Settings(ocr_mode="off"), ROOT)


def _find_by_first_name(name_to_hit: dict[str, MatchResult]):
    def _find(frame, names, **kwargs):
        key = names[0] if names else None
        return name_to_hit.get(key)
    return _find


class DedicatedSkillRefreshBeatsGeneric(unittest.TestCase):
    """专用钮即使分数更低，也必须先于通用 refresh 被选中。"""

    def test_generic_refresh_must_not_steal_skill_refresh_btn(self):
        med = _med()
        hits = {
            "refresh": GENERIC,
            "skill_refresh_btn": DEDICATED,
        }
        with patch.object(med, "find", side_effect=_find_by_first_name(hits)):
            hit = med._find_panel_refresh(_frame(), "skill")
        self.assertIsNotNone(hit)
        self.assertEqual(hit.name, "skill_refresh_btn")
        self.assertEqual(hit.center, (1020, 654))

    def test_giveup_panel_fixture_clicks_skill_refresh_not_generic_refresh(self):
        """门禁夹具 giveup_panel.jpg：真实模板匹配也必须落到专用钮。"""
        path = ROOT / "tests" / "performance" / "fixtures" / "giveup_panel.jpg"
        data = np.fromfile(str(path), dtype=np.uint8)
        bgr = cv2.imdecode(data, cv2.IMREAD_COLOR)
        self.assertIsNotNone(bgr, "unreadable giveup_panel.jpg")
        frame = Frame(bgr, window_title="英雄三国KK", hwnd=10001, role="l1")
        hit = _med()._find_panel_refresh(frame, "skill")
        self.assertIsNotNone(hit)
        self.assertEqual(hit.name, "skill_refresh_btn")
        self.assertEqual(list(hit.center), [1020, 654])


if __name__ == "__main__":
    unittest.main()
