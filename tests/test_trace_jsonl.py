"""JSONL tick trace 回归测试。

覆盖 Diagnostics 阶段新增：set_trace 开启后，每次 tick 在 finally 中写入
一行 JSON（phase_before/phase_after/context/hwnd/size/actions/scenes），
卡死或误操作后可回放最后几十个 tick。
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
_SRC = ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from gamescript.mediator import Mediator, Phase
from gamescript.settings import Settings
from gamescript.stop_signal import StopSignal
from gamescript.vision.capture import Frame
from tests.test_scenario_replay import FakeClock, FakeInputExecutor


def _stage_frame() -> Frame:
    p = ROOT / "fixtures" / "live_postgame_20260808" / "live_stage_select.png"
    img = cv2.imdecode(np.frombuffer(p.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
    return Frame(bgr=img, left=0, top=0, window_title="英雄三国KK", hwnd=10001, role="l1")


class TraceTest(unittest.TestCase):
    def test_tick_writes_one_jsonl_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            trace_path = str(Path(tmp) / "trace.jsonl")
            clock = FakeClock(start=10.0)
            stop_signal = StopSignal()
            with clock.install():
                med = Mediator(Settings(), ROOT, stop_signal=stop_signal)
                med.executor = FakeInputExecutor(stop_signal, clock)
                src = _StageSource()
                med._capture_best = src.capture_best
                med.set_phase(Phase.STAGE_SELECT, "trace test")
                med.set_trace(trace_path)
                med.tick()
                med.set_trace(None)  # 关闭并 flush

            lines = Path(trace_path).read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 1)
            row = json.loads(lines[0])
            self.assertEqual(row["phase_before"], "STAGE_SELECT")
            self.assertEqual(row["phase_after"], med.phase.name)
            self.assertIn("tick", row)
            self.assertIn("elapsed_ms", row)
            self.assertIn("hwnd", row)
            self.assertIn("actions", row)
            self.assertIn("scenes", row)

    def test_trace_disabled_by_default(self) -> None:
        clock = FakeClock(start=10.0)
        stop_signal = StopSignal()
        with clock.install():
            med = Mediator(Settings(), ROOT, stop_signal=stop_signal)
            self.assertIsNone(med._trace_fh)
            med.tick()
            self.assertIsNone(med._trace_fh)


class _StageSource:
    def capture_best(self, *a, **k) -> Frame:
        return _stage_frame()


if __name__ == "__main__":
    unittest.main()
