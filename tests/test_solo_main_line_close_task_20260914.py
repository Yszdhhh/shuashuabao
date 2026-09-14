# -*- coding: utf-8 -*-
"""单人 5-5 后取消自动主线任务：右上角任务栏 OCR 触发回归测试。

看板配置「5-5 后取消自动主线」：
- (章, 节) <= (5, 5) 时不触发，确保 5-5 打完且提前挑战出现；
- (章, 节) > (5, 5)（如 5-6..5-9, 6-1）时触发取消自动任务；
- 局内最多每 10s OCR 扫描一次；
- 真实帧回归：f0250 (5-5) 不触发，f0582 (5-6 弹窗) 触发，f0410 (6-1) 触发，
  f0581 (5-6 无弹窗, 自动任务 ON) 触发并执行 DisableAutoTask。
"""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
import pytest

from shuabao.loop_action import LoopAction
from shuabao.mediator import Mediator, Phase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "solo_live_20260914"

F0250 = FIXTURES / "f0250_action_after.png"
F0410 = FIXTURES / "f0410_action_after.png"
F0581 = FIXTURES / "f0581_action_before.png"
F0582 = FIXTURES / "tqtz_confirm_dialog_f0582.png"


def _load_frame(path: Path) -> Frame:
    if not path.exists():
        pytest.skip(f"Fixture {path} not found")
    bgr = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert bgr is not None, f"Failed to load image: {path}"
    return Frame(bgr)


def test_main_line_5_5_does_not_trigger_close_task() -> None:
    """f0250 (6.7min) 任务栏显示主线5-5，尚未打完 5-5，严格不触发取消自动任务。"""
    frame = _load_frame(F0250)
    med = Mediator(Settings(ocr_mode="live", auto_close_main_line=True), ROOT)
    res = med._maybe_close_main_line_after_5_5(frame, time.time())
    assert res is None
    assert not med._close_main_line_triggered
    assert not med._main_line_closed_done


def test_main_line_6_1_triggers_close_task() -> None:
    """f0410 (11.3min) 任务栏显示主线6-1（全部主线已完成），触发取消自动任务。"""
    frame = _load_frame(F0410)
    med = Mediator(Settings(ocr_mode="live", auto_close_main_line=True), ROOT)
    res = med._maybe_close_main_line_after_5_5(frame, time.time())
    assert med._close_main_line_triggered


def test_main_line_5_6_dialog_triggers_close_task() -> None:
    """f0582 (11.5min) 任务栏显示主线5-6（中间有提前挑战确认弹窗），仍能识别并触发。"""
    frame = _load_frame(F0582)
    med = Mediator(Settings(ocr_mode="live", auto_close_main_line=True), ROOT)
    res = med._maybe_close_main_line_after_5_5(frame, time.time())
    assert med._close_main_line_triggered


def test_main_line_5_6_clean_triggers_and_disables_auto_task() -> None:
    """f0581 任务栏显示主线5-6且自动任务为 ON，触发取消并发出 DisableAutoTask 点击。"""
    frame = _load_frame(F0581)
    med = Mediator(Settings(ocr_mode="live", auto_close_main_line=True, dry_run=True), ROOT)
    res = med._maybe_close_main_line_after_5_5(frame, time.time())
    assert med._close_main_line_triggered
    assert med._main_line_closed_done
    assert res == LoopAction.Continue


def test_main_line_tick_disables_auto_task_in_full_cycle() -> None:
    """完整 _tick_main_line 调度：自动任务 ON + 任务栏 5-6 -> 发出 DisableAutoTask。"""
    frame = _load_frame(F0581)
    med = Mediator(Settings(ocr_mode="live", auto_close_main_line=True, dry_run=True), ROOT)
    med.set_phase(Phase.MAIN_LINE, "test")
    med._main_line_started_at = time.time() - 100.0
    med._tqtz_clicked = True  # 提前挑战已点击过

    res = med._tick_main_line(frame)
    assert med._close_main_line_triggered
    assert med._main_line_closed_done
    assert res == LoopAction.Continue


def test_taskbar_ocr_interval_throttling() -> None:
    """任务栏 OCR 每 10s 最多一次；未到冷却期不调用 OCR worker。"""
    frame = _load_frame(F0581)
    med = Mediator(Settings(ocr_mode="live", auto_close_main_line=True), ROOT)
    now = 1000.0
    # 第一次调用
    stage = med._read_main_line_stage(frame, now)
    assert stage == (5, 6)
    assert med._main_line_ocr_next_at == 1010.0

    # 5 秒后再次调用，仍在冷却期，直接返回 None
    with patch.object(med._ocr_client, "shadow_predict") as mock_predict:
        stage_cached = med._read_main_line_stage(frame, now + 5.0)
        assert stage_cached is None
        mock_predict.assert_not_called()

    # 10 秒后再次调用，冷却到期，允许重新识别
    stage_after_cd = med._read_main_line_stage(frame, now + 10.1)
    assert stage_after_cd == (5, 6)
