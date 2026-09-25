from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.mediator import LoopAction, Mediator
from shuabao.runtime_mediator import Mediator as RuntimeMediator
from shuabao.settings import Settings
from shuabao.vision.capture import Frame


def load_fixture_f0147() -> Frame:
    path = ROOT / "fixtures" / "solo_round4_20260925" / "f0147.png"
    bgr = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert bgr is not None, f"Failed to load fixture {path}"
    return Frame(bgr, window_title="英雄三国KK", hwnd=1)


@pytest.mark.parametrize("cls", [Mediator, RuntimeMediator])
def test_f0147_evolve_bar_resets_cycle_flag_and_blocks_inventory(cls) -> None:
    """真实帧 f0147（约 02:55 进化金条再次亮起）：

    1. 金条再次亮起时检测到进化按钮，必须重置 _evolve_ok_this_cycle 为 False；
    2. _maybe_use_inventory_item / _maybe_use_inventory_slot 在 _has_evolve_button 为真时一律不点物品栏；
    3. 进化未完成前决不向物品栏 2 槽（英雄卡）派发点击。
    """
    med = cls(Settings(ocr_mode="off"), ROOT)
    frame = load_fixture_f0147()

    # 验证真实帧上的进化金条定位
    assert med._has_evolve_button(frame) is True
    assert med._evolve_gold_center(frame) == (877, 705)

    # 模拟第一轮进化已完成
    med._evolve_ok_this_cycle = True
    assert med._evolve_ok_this_cycle is True

    # 重新检测到进化金条亮起，_evolve_ok_this_cycle 必须被重置为 False
    assert med._has_evolve_button(frame) is True
    assert med._evolve_ok_this_cycle is False

    # 即使强制设为 True，进入物品栏方法也一律零输入并重置
    med._evolve_ok_this_cycle = True
    with patch.object(med, "act_click", return_value=True) as mock_click:
        res_item = med._maybe_use_inventory_item(frame)
        res_slot = med._maybe_use_inventory_slot(frame, time.time())
        assert res_item is None
        assert res_slot is None
        assert med._evolve_ok_this_cycle is False
        mock_click.assert_not_called()

    # 机会点击进化能够正常识别并派发
    now = time.time()
    with patch.object(med, "act_click", return_value=True) as mock_click:
        evolve_res = med._maybe_opportunistic_evolve(frame, now)
        assert evolve_res is LoopAction.Continue
        mock_click.assert_called_once()
        assert mock_click.call_args[0][1] == "ClickEvolve"

    # 进化完成后通过 _complete_evolve_hero_pick 闭环置 True
    med._complete_evolve_hero_pick()
    assert med._evolve_ok_this_cycle is True
    assert med._evolve_awaiting_hero_pick is False
