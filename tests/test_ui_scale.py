"""会话级 UI 缩放（ui_scale）回归测试。

覆盖 acb1755 修复：
1. 960x540（=1600x900 x 0.6）选关页经 _ui_scale 校准后可识别（修复前全部模板 scales 0.85-1.2 错过 → UNKNOWN）
2. _adapt_scales 把 ui_scale 邻域并入任意 scales 元组
3. see() 每帧自动校准 _ui_scale
4. ROOM_STARTING 超时但游戏窗口已出现 → 不回退 ROOM_WAITING（平台窗可能已关闭）
5. ROOM_STARTING 超时且窗口不存在 → 回退 ROOM_WAITING（原有行为保持）
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
_SRC = ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from gamescript.loop_action import LoopAction
from gamescript.mediator import Mediator, Phase
from gamescript.settings import Settings
from gamescript.stop_signal import StopSignal
from gamescript.vision.capture import Frame
from tests.test_scenario_replay import FakeClock, FakeInputExecutor


def _load(name: str) -> np.ndarray:
    p = ROOT / "fixtures" / "live_postgame_20260808" / name
    img = cv2.imdecode(np.frombuffer(p.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
    assert img is not None, f"无法解码 {p}"
    return img


class AdaptScalesTest(unittest.TestCase):
    """_adapt_scales 单元行为。"""

    def test_baseline_scale_untouched(self) -> None:
        med = Mediator(Settings(), ROOT)
        self.assertEqual(med._adapt_scales((0.9, 1.0, 1.1)), (0.9, 1.0, 1.1))

    def test_ui_scale_close_to_baseline_untouched(self) -> None:
        med = Mediator(Settings(), ROOT)
        med._ui_scale = 1.03
        self.assertEqual(med._adapt_scales((0.9, 1.0, 1.1)), (0.9, 1.0, 1.1))

    def test_ui_scale_neighborhood_merged(self) -> None:
        med = Mediator(Settings(), ROOT)
        med._ui_scale = 0.6
        out = med._adapt_scales((0.9, 1.0, 1.1))
        for expected in (round(0.6 * 0.94, 3), 0.6, round(0.6 * 1.06, 3), 0.9, 1.0, 1.1):
            self.assertIn(expected, out)
        self.assertEqual(out, tuple(sorted(out)))

    def test_no_duplicate_when_overlapping(self) -> None:
        med = Mediator(Settings(), ROOT)
        med._ui_scale = 0.95
        out = med._adapt_scales((0.9, 1.0, 1.1))
        # 0.95*0.94=0.893 与 0.9 间距 <0.03 → 不插；0.95 本身与 0.9/1.0 各差 0.05 → 插入；
        # 0.95*1.06=1.007 与 1.0 间距 <0.03 → 不插 → 共 4 个
        self.assertEqual(out, (0.9, 0.95, 1.0, 1.1))


class ScaleDetectionTest(unittest.TestCase):
    """960x540 帧的真实识别（回归：修复前 UNKNOWN）。"""

    def test_stage_select_recognized_at_960x540(self) -> None:
        small = cv2.resize(_load("live_stage_select.png"), (960, 540))
        med = Mediator(Settings(), ROOT)
        med._ui_scale = 0.6  # 模拟 see() 已完成校准
        fr = Frame(bgr=small, left=0, top=0, window_title="英雄三国KK", hwnd=10001, role="l1")
        self.assertEqual(med._detect_context(fr, role="l1"), "STAGE_SELECT")

    def test_baseline_1600x900_still_recognized(self) -> None:
        img = _load("live_stage_select.png")
        med = Mediator(Settings(), ROOT)
        fr = Frame(bgr=img, left=0, top=0, window_title="英雄三国KK", hwnd=10001, role="l1")
        self.assertEqual(med._detect_context(fr, role="l1"), "STAGE_SELECT")


class AutoCalibrationTest(unittest.TestCase):
    """see() 每帧自动校准 _ui_scale。"""

    def test_see_calibrates_ui_scale_from_frame(self) -> None:
        med = Mediator(Settings(), ROOT)
        small = cv2.resize(_load("live_stage_select.png"), (960, 540))
        fr = Frame(bgr=small, left=0, top=0, window_title="英雄三国KK", hwnd=10001)
        med._capture_best = lambda *a, **k: fr
        med.see("tick")
        self.assertEqual(med._ui_scale, 0.6)

    def test_see_keeps_baseline_scale(self) -> None:
        med = Mediator(Settings(), ROOT)
        img = _load("live_stage_select.png")
        fr = Frame(bgr=img, left=0, top=0, window_title="英雄三国KK", hwnd=10001)
        med._capture_best = lambda *a, **k: fr
        med.see("tick")
        self.assertEqual(med._ui_scale, 1.0)


class _FakeFrameSource:
    """按调用次数返回预设帧序列（循环最后一张）。"""

    def __init__(self, frames: list[Frame]) -> None:
        self._frames = frames

    def capture_best(self, *a, **k) -> Frame:
        if not self._frames:
            return Frame(bgr=None, left=0, top=0, window_title="", hwnd=None, is_valid=False)
        return self._frames[min(len(self._frames) - 1, 0)]


def _noise_frame() -> Frame:
    """熵足够、不匹配任何场景的帧（context=UNKNOWN 且健康）。"""
    rng = np.random.default_rng(42)
    img = rng.integers(0, 255, (540, 960, 3), dtype=np.uint8)
    return Frame(bgr=img, left=0, top=0, window_title="英雄三国KK", hwnd=10001, role="l1")


class RoomStartingNoFallbackTest(unittest.TestCase):
    """ROOM_STARTING 超时的回退语义（acb1755）。"""

    def _med(self, clock: FakeClock, frame: Frame | None):
        stop_signal = StopSignal()
        with clock.install():
            med = Mediator(Settings(), ROOT, stop_signal=stop_signal)
            med.executor = FakeInputExecutor(stop_signal, clock)
            src = _FakeFrameSource([frame] if frame is not None else [])
            med._capture_best = src.capture_best
            med.set_phase(Phase.ROOM_STARTING, "test setup")
            med._room_action_deadline = 0.0  # 必然超时（clock >= 0）
        return med

    def test_window_present_keeps_room_starting(self) -> None:
        clock = FakeClock(start=100.0)
        med = self._med(clock, _noise_frame())
        with clock.install():
            action = med.tick()
            self.assertEqual(med.phase, Phase.ROOM_STARTING, "窗口已出现时不得回退到平台房间页")
            self.assertIsNot(action, LoopAction.Break)
            # deadline 被重置，避免下一 tick 立即再次超时
            self.assertIsNotNone(med._room_action_deadline)

    def test_window_missing_falls_back_to_room_waiting(self) -> None:
        clock = FakeClock(start=100.0)
        med = self._med(clock, None)
        with clock.install():
            action = med.tick()
            self.assertEqual(med.phase, Phase.ROOM_WAITING, "窗口不存在时仍回退房间等待")
            self.assertIsNot(action, LoopAction.Break)


if __name__ == "__main__":
    unittest.main()
