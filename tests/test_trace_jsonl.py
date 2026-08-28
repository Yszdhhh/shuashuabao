"""JSONL tick trace 回归测试。

覆盖 Diagnostics 阶段新增：set_trace 开启后，每次 tick 在 finally 中写入
一行 JSON（phase_before/phase_after/context/hwnd/size/actions/scenes），
卡死或误操作后可回放最后几十个 tick。

B1-1 扩展：build_id / settings_summary（密码类字段掩码）/ frame_fingerprint /
panel / ocr_suggestion / decision / post_confirm；异常退出后最后一行完整；
set_trace 幂等（重复调用只保留一个句柄）。
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

from shuabao.mediator import Mediator, Phase
from shuabao.settings import Settings
from shuabao.stop_signal import StopSignal
from shuabao.vision.capture import Frame
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
            # B1-1 证据与遥测字段
            self.assertIn("build_id", row)
            self.assertTrue(row["build_id"])
            self.assertIn("settings_summary", row)
            self.assertIn("frame_fingerprint", row)
            self.assertIn("panel", row)
            self.assertIn("ocr_suggestion", row)
            self.assertIsNone(row["ocr_suggestion"])  # shadow 阶段前恒 None
            self.assertIn("decision", row)
            self.assertIn("post_confirm", row)
            summary = row["settings_summary"]
            self.assertIn("ocr_mode", summary)
            self.assertIn("skills", summary)
            self.assertIn("challenge", summary)

    def test_trace_disabled_by_default(self) -> None:
        clock = FakeClock(start=10.0)
        stop_signal = StopSignal()
        with clock.install():
            med = Mediator(Settings(), ROOT, stop_signal=stop_signal)
            self.assertIsNone(med._trace_fh)
            med.tick()
            self.assertIsNone(med._trace_fh)

    def test_settings_summary_masks_password_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            trace_path = str(Path(tmp) / "trace.jsonl")
            clock = FakeClock(start=10.0)
            stop_signal = StopSignal()
            settings = Settings(room_password="hunter2-secret", skills=["jq", "pg"])
            with clock.install():
                med = Mediator(settings, ROOT, stop_signal=stop_signal)
                med.executor = FakeInputExecutor(stop_signal, clock)
                med._capture_best = _StageSource().capture_best
                med.set_phase(Phase.STAGE_SELECT, "trace test")
                med.set_trace(trace_path)
                med.tick()
                med.set_trace(None)

            row = json.loads(Path(trace_path).read_text(encoding="utf-8").strip().splitlines()[0])
            summary = row["settings_summary"]
            self.assertEqual(summary["skills"], ["jq", "pg"])
            self.assertEqual(summary["ocr_mode"], "off")
            self.assertNotIn("room_password", str(summary))
            self.assertNotIn("hunter2-secret", str(summary))

            def assert_no_password_keys(value, where="summary"):
                if isinstance(value, dict):
                    for k, v in value.items():
                        self.assertNotIn("password", k.lower(), f"{where}.{k}")
                        assert_no_password_keys(v, f"{where}.{k}")
                elif isinstance(value, list):
                    for i, v in enumerate(value):
                        assert_no_password_keys(v, f"{where}[{i}]")

            assert_no_password_keys(summary)

    def test_every_line_is_independent_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            trace_path = str(Path(tmp) / "trace.jsonl")
            clock = FakeClock(start=10.0)
            stop_signal = StopSignal()
            with clock.install():
                med = Mediator(Settings(), ROOT, stop_signal=stop_signal)
                med.executor = FakeInputExecutor(stop_signal, clock)
                med._capture_best = _StageSource().capture_best
                med.set_phase(Phase.STAGE_SELECT, "trace test")
                med.set_trace(trace_path)
                for _ in range(3):
                    med.tick()
                med.set_trace(None)

            lines = Path(trace_path).read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 3)
            for line in lines:
                parsed = json.loads(line)  # 每行必须可独立 json.loads
                self.assertIsInstance(parsed, dict)
            ticks = [json.loads(line)["tick"] for line in lines]
            self.assertEqual(ticks, [1, 2, 3])

    def test_last_line_intact_after_exception(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            trace_path = str(Path(tmp) / "trace.jsonl")
            clock = FakeClock(start=10.0)
            stop_signal = StopSignal()
            with clock.install():
                med = Mediator(Settings(), ROOT, stop_signal=stop_signal)
                med.executor = FakeInputExecutor(stop_signal, clock)
                med._capture_best = _StageSource().capture_best
                med.set_phase(Phase.STAGE_SELECT, "trace test")
                med.set_trace(trace_path)
                med.tick()

                def boom(*a, **k):
                    raise RuntimeError("simulated crash")

                med._capture_best = boom
                with self.assertRaises(RuntimeError):
                    med.tick()  # finally 仍写 trace 行，异常向外传播
                med.set_trace(None)  # 异常结束后句柄仍被关闭

            lines = Path(trace_path).read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 2)
            for line in lines:
                json.loads(line)  # 每行（含异常 tick 写入的最后一行）完整可解析
            last = json.loads(lines[-1])
            self.assertEqual(last["tick"], 2)
            self.assertEqual(last["phase_before"], "STAGE_SELECT")

    def test_set_trace_is_idempotent_single_handle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            trace_path = str(Path(tmp) / "trace.jsonl")
            clock = FakeClock(start=10.0)
            stop_signal = StopSignal()
            with clock.install():
                med = Mediator(Settings(), ROOT, stop_signal=stop_signal)
                med.executor = FakeInputExecutor(stop_signal, clock)
                med._capture_best = _StageSource().capture_best
                med.set_phase(Phase.STAGE_SELECT, "trace test")
                med.set_trace(trace_path)
                med.set_trace(trace_path)  # 重复开启：旧句柄先关，不出现双句柄
                self.assertIsNotNone(med._trace_fh)
                med.tick()
                med.set_trace(None)
                self.assertIsNone(med._trace_fh)

            lines = Path(trace_path).read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 1)  # 只有一个句柄写入，无重复行


class _StageSource:
    def capture_best(self, *a, **k) -> Frame:
        return _stage_frame()


if __name__ == "__main__":
    unittest.main()
