"""技能刷新必须点真正的【刷新(N)】按钮，不能点「技能免费刷新次数+1」文字。

2026-09-24 纠错（Owner 实机 + 真帧核对）：原契约（af22c5a）把
``skill_refresh_btn`` 当成"专用钮"，但该模板截的是「刷新次数+1」这行说明文字，
在 giveup_panel.jpg（1920x1080）上命中 (1020,654)，正好压在【放弃】按钮上沿；
通用 ``refresh`` 命中的 (1171,677) 才是【刷新(3)】。旧期望是被焊进基线的错误期望。

仍然保留的产品语义：面板专用钮（如 ``bond_refresh_btn``）先于通用模板，
即使通用模板分数更高——_find_panel_refresh 按名单顺序取第一个命中。
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


class SkillRefreshClicksRealButton(unittest.TestCase):
    """技能面板不再使用文字模板；专用钮优先的顺序语义对其它面板保持。"""

    def test_skill_panel_never_uses_label_template(self):
        med = _med()
        hits = {
            "refresh": GENERIC,
            "skill_refresh_btn": DEDICATED,
        }
        with patch.object(med, "find", side_effect=_find_by_first_name(hits)):
            hit = med._find_panel_refresh(_frame(), "skill")
        self.assertIsNotNone(hit)
        self.assertEqual(hit.name, "refresh")
        self.assertEqual(hit.center, (1171, 677))

    def test_bond_dedicated_button_still_beats_higher_scoring_generic(self):
        med = _med()
        dedicated = MatchResult("bond_refresh_btn", 0.72, 1000, 640, 40, 28, 1020, 654)
        hits = {"refresh": GENERIC, "bond_refresh_btn": dedicated}
        with patch.object(med, "find", side_effect=_find_by_first_name(hits)):
            hit = med._find_panel_refresh(_frame(), "bond")
        self.assertIsNotNone(hit)
        self.assertEqual(hit.name, "bond_refresh_btn")

    def test_giveup_panel_fixture_clicks_real_refresh_button(self):
        """门禁夹具 giveup_panel.jpg：真实模板匹配落到【刷新(3)】，不落到【放弃】上沿。"""
        path = ROOT / "tests" / "performance" / "fixtures" / "giveup_panel.jpg"
        data = np.fromfile(str(path), dtype=np.uint8)
        bgr = cv2.imdecode(data, cv2.IMREAD_COLOR)
        self.assertIsNotNone(bgr, "unreadable giveup_panel.jpg")
        frame = Frame(bgr, window_title="英雄三国KK", hwnd=10001, role="l1")
        hit = _med()._find_panel_refresh(frame, "skill")
        self.assertIsNotNone(hit)
        self.assertEqual(hit.name, "refresh")
        self.assertEqual(list(hit.center), [1171, 677])


if __name__ == "__main__":
    unittest.main()
