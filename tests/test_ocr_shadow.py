"""O4 OCR shadow protocol, lifecycle, cache, and degradation tests.

These tests use a tiny JSONL fake worker for timing/crash cases, so the main
application test environment never imports Paddle.  The model-missing case
runs the real worker in degraded mode and likewise never loads Paddle.
"""

from __future__ import annotations

import json
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from shuabao.vision.ocr_shadow import ShadowClient, decode_response, encode_request, panel_fingerprint


FAKE_WORKER = textwrap.dedent(
    r"""
    import json, sys, time
    print(json.dumps({'type':'ready','seq':0,'status':'ok','candidates':[],'elapsed_ms':0}), flush=True)
    for line in sys.stdin:
        try: req=json.loads(line)
        except Exception: print('not-json', flush=True); continue
        if req.get('type') == 'ping':
            print(json.dumps({'type':'pong','seq':req['seq'],'status':'ok','candidates':[],'elapsed_ms':0}), flush=True); continue
        if req.get('panel_id') == 'badjson':
            print('not-json', flush=True); continue
        if req.get('panel_id') == 'timeout':
            time.sleep(0.25)
        if req.get('panel_id') == 'crash':
            sys.exit(3)
        print(json.dumps({'seq':req['seq'],'status':'ok','candidates':[{'name':'奥术增幅β','confidence':0.91}],'elapsed_ms':1}), flush=True)
    """
)


def fake_command() -> list[str]:
    return [sys.executable, "-c", FAKE_WORKER]


def frame() -> np.ndarray:
    return np.zeros((80, 120, 3), dtype=np.uint8)


def slot(index: int = 0) -> dict:
    return {"slot_id": index, "bbox": (10 + index * 20, 10, 30 + index * 20, 40), "kind": "skill"}


class TestProtocol(unittest.TestCase):
    def test_round_trip(self):
        request = {"seq": 7, "frame_ref": "f", "session": "s", "panel_id": "p", "slot_id": 0, "bbox": [1, 2, 3, 4], "id": "p:0", "sent_at": 1.2}
        decoded = json.loads(encode_request(request))
        self.assertEqual(decoded, request)
        response = decode_response('{"seq":7,"status":"ok","candidates":[{"name":"A","confidence":0.8}],"elapsed_ms":2}')
        self.assertEqual(response["seq"], 7)
        with self.assertRaises(ValueError):
            decode_response("not-json")

    def test_fingerprint_changes_with_panel_content(self):
        first = frame()
        second = first.copy()
        second[20, 20, 0] = 1
        self.assertNotEqual(panel_fingerprint(first), panel_fingerprint(second))
        self.assertEqual(panel_fingerprint(first), panel_fingerprint(first))


class TestClientLifecycle(unittest.TestCase):
    def new_client(self, **kwargs) -> ShadowClient:
        return ShadowClient(
            worker_command=fake_command(),
            timeout_ms=kwargs.pop("timeout_ms", 400),
            max_restarts=kwargs.pop("max_restarts", 3),
            restart_cooldown_s=kwargs.pop("restart_cooldown_s", 2.0),
            **kwargs,
        )

    def test_jsonl_round_trip_and_ping(self):
        client = self.new_client()
        try:
            self.assertTrue(client.ping())
            response = client.shadow_predict(frame(), "panel", slot(0), fingerprint="fp1")
            self.assertTrue(response.available)
            self.assertEqual(response.candidates[0].name, "奥术增幅β")
        finally:
            client.close()

    def test_bad_json_is_unavailable(self):
        client = self.new_client()
        try:
            response = client.shadow_predict(frame(), "badjson", slot(), fingerprint="bad")
            self.assertEqual(response.status, "unavailable")
            self.assertIn(response.reason, {"protocol", "timeout"})
        finally:
            client.close()

    def test_timeout_is_unavailable_and_does_not_desync(self):
        client = self.new_client(timeout_ms=50)
        client.ping()
        time.sleep(0.15)
        try:
            started = time.perf_counter()
            response = client.shadow_predict(frame(), "timeout", slot(), fingerprint="t")
            self.assertEqual(response.status, "unavailable")
            self.assertEqual(response.reason, "timeout")
            self.assertLess(time.perf_counter() - started, 0.20)
            client.ping()
            time.sleep(0.15)
            response = client.shadow_predict(frame(), "after-timeout", slot(), fingerprint="u")
            self.assertTrue(response.available)
        finally:
            client.close()

    def test_crash_skips_this_frame_then_can_rearm(self):
        client = self.new_client(max_restarts=3, restart_cooldown_s=30)
        try:
            for _ in range(3):
                response = client.shadow_predict(frame(), "crash", slot(), fingerprint=str(time.time_ns()))
                self.assertEqual(response.status, "unavailable")
            self.assertTrue(client.disabled)
            response = client.shadow_predict(frame(), "crash", slot(), fingerprint="new")
            self.assertEqual(response.reason, "disabled")
        finally:
            client.close()

    def test_spawn_fail_does_not_permanently_disable(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace = Path(tmp) / "ocr_shadow.jsonl"
            client = ShadowClient(
                worker_command=["__no_such_ocr_worker__"],
                timeout_ms=200,
                max_restarts=2,
                restart_cooldown_s=0.0,
                trace_path=trace,
            )
            try:
                first = client.shadow_predict(frame(), "missing", slot(), fingerprint="a")
                second = client.shadow_predict(frame(), "missing", slot(), fingerprint="b")
                self.assertEqual(first.status, "unavailable")
                self.assertEqual(second.status, "unavailable")
                self.assertIn(first.reason, {"spawn", "disabled"})
                records = [
                    json.loads(line)
                    for line in trace.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
                self.assertTrue(
                    any(row.get("event") == "ocr_spawn_failure" for row in records),
                    records,
                )
                client.worker_command = fake_command()
                recovered = client.shadow_predict(frame(), "after-spawn", slot(), fingerprint="c")
                self.assertTrue(recovered.available)
                self.assertFalse(client.disabled)
            finally:
                client.close()

    def test_cache_is_bound_to_panel_fingerprint_and_invalidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = self.new_client(trace_path=Path(tmp) / "shadow.jsonl")
            try:
                first = client.shadow_predict(frame(), "panel", slot(), fingerprint="fp1")
                second = client.shadow_predict(frame(), "panel", slot(), fingerprint="fp1")
                self.assertFalse(first.cache_hit)
                self.assertTrue(second.cache_hit)
                changed = client.shadow_predict(frame(), "panel", slot(), fingerprint="fp2")
                self.assertFalse(changed.cache_hit)
                frame_changed = frame()
                frame_changed[0, 0, 0] = 1
                content_changed = client.shadow_predict(frame_changed, "panel", slot())
                self.assertFalse(content_changed.cache_hit)
                records = [
                    json.loads(line)
                    for line in (Path(tmp) / "shadow.jsonl").read_text(encoding="utf-8").splitlines()
                    if '"panel_id"' in line
                ]
                self.assertEqual(len(records), 4)
                self.assertTrue(records[1]["cache_hit"])
                self.assertEqual(records[2]["panel_fingerprint"], "fp2")
            finally:
                client.close()

    def test_model_missing_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = ShadowClient(
                repo_root=ROOT,
                python_executable=sys.executable,
                model_dir=Path(tmp) / "missing-model",
                timeout_ms=500,
            )
            try:
                response = client.shadow_predict(frame(), "missing", slot(), fingerprint="m")
                self.assertEqual(response.status, "unavailable")
                self.assertEqual(response.reason, "model_missing")
                self.assertFalse(client.disabled)
            finally:
                client.close()

    def test_corrupt_model_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / "PP-OCRv5_mobile_rec_infer"
            model.mkdir()
            for name in ("inference.json", "inference.pdiparams", "inference.yml"):
                (model / name).write_bytes(b"corrupt")
            client = ShadowClient(
                repo_root=ROOT,
                python_executable=sys.executable,
                model_dir=Path(tmp),
                timeout_ms=500,
            )
            try:
                client.ping()
                time.sleep(0.2)
                response = client.shadow_predict(frame(), "corrupt", slot(), fingerprint="c")
                self.assertEqual(response.status, "unavailable")
                self.assertIn(response.reason, {"model_corrupt", "model_missing", "model_load_failed"})
            finally:
                client.close()


if __name__ == "__main__":
    unittest.main()
