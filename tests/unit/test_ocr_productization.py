# -*- coding: utf-8 -*-
"""Comprehensive unit tests for OCR Shadow sidecar productization.

Covers:
- Silent Windows subprocess spawning (CREATE_NO_WINDOW, STARTUPINFO, SW_HIDE).
- Stdout / Stderr pipe capture and routing to logging / diagnostics.
- True READY validation (worker process alive, protocol ready, status ok, model_validated).
- Ping and health query contracts.
- Frozen / PyInstaller packaging runtime discovery vs development repository root.
- Bounded restart, crash accounting, cooldown, and recovery state machine.
- Fault injection: crashes, corrupt outputs, timeouts, sequence desync, and missing assets.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
import numpy as np

from shuabao.vision.ocr_shadow.client import (
    ShadowClient,
    _resolve_ocr_python,
    _resolve_model_dir,
    _resolve_src_dir,
)
from shuabao.vision.ocr_shadow.protocol import (
    ShadowCandidate,
    ShadowResponse,
    decode_response,
    encode_request,
    panel_fingerprint,
)
from shuabao.vision.ocr_shadow.worker import (
    _validate_model,
    _manifest_entry,
    _model_dir,
    _stage_model,
)


def _dummy_frame() -> np.ndarray:
    return np.zeros((100, 100, 3), dtype=np.uint8)


def _dummy_slot() -> dict[str, Any]:
    return {"slot_id": 0, "bbox": (10, 10, 50, 50), "kind": "skill"}


# =========================================================================
# 1. Silent Process Spawning & Windows Subprocess Configuration
# =========================================================================

class TestSilentProcessSpawn:
    """Verify silent process creation flags on Windows to prevent console windows popping up."""

    def test_build_startupinfo_windows(self):
        client = ShadowClient(worker_command=["dummy"])
        with mock.patch("sys.platform", "win32"):
            startupinfo, creationflags = client._build_startupinfo()
            assert creationflags & getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) != 0
            if hasattr(subprocess, "STARTUPINFO"):
                assert startupinfo is not None
                assert startupinfo.dwFlags & getattr(subprocess, "STARTF_USESHOWWINDOW", 1) != 0
                assert startupinfo.wShowWindow == 0  # SW_HIDE

    def test_build_startupinfo_non_windows(self):
        client = ShadowClient(worker_command=["dummy"])
        with mock.patch("sys.platform", "linux"):
            startupinfo, creationflags = client._build_startupinfo()
            assert startupinfo is None
            assert creationflags == 0

    def test_spawn_passes_silent_flags_to_popen(self):
        client = ShadowClient(worker_command=["dummy"])
        with mock.patch("subprocess.Popen") as mock_popen:
            mock_proc = mock.MagicMock()
            mock_proc.poll.return_value = None
            mock_proc.stdout = [
                json.dumps(
                    {"type": "ready", "seq": 0, "status": "ok", "model_validated": True, "elapsed_ms": 1.0}
                ) + "\n"
            ]
            mock_proc.stderr = []
            mock_popen.return_value = mock_proc
            success = client.start()
            assert success is True
            assert mock_popen.called
            _, kwargs = mock_popen.call_args
            assert "startupinfo" in kwargs or "creationflags" in kwargs
            client.close()

# =========================================================================
# 2. Frozen Runtime Discovery & Path Resolution
# =========================================================================

class TestFrozenPackagingDiscovery:
    """Verify asset and python discovery in both dev mode and PyInstaller frozen mode."""

    def test_resolve_ocr_python_dev_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            custom_python = root / "custom_py.exe"
            custom_python.touch()
            resolved = _resolve_ocr_python(root, custom_python)
            assert Path(resolved) == custom_python

    def test_resolve_ocr_python_frozen_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            meipass = Path(tmp) / "_internal"
            meipass.mkdir()
            ocr_exe = meipass / "ocr_worker.exe"
            ocr_exe.touch()

            with mock.patch.object(sys, "frozen", True, create=True), \
                 mock.patch.object(sys, "_MEIPASS", str(meipass), create=True), \
                 mock.patch.object(sys, "executable", str(Path(tmp) / "ShuaBao.exe"), create=True):
                resolved = _resolve_ocr_python(Path(tmp), None)
                assert str(ocr_exe) in resolved or str(Path(tmp) / "ShuaBao.exe") in resolved

    def test_resolve_model_dir_frozen_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            meipass = Path(tmp) / "_internal"
            model_dir = meipass / "models" / "ocr"
            model_dir.mkdir(parents=True)

            with mock.patch.object(sys, "frozen", True, create=True), \
                 mock.patch.object(sys, "_MEIPASS", str(meipass), create=True):
                resolved = _resolve_model_dir(Path(tmp), None)
                assert resolved == model_dir.resolve()

    def test_resolve_src_dir_frozen_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            meipass = Path(tmp) / "_internal"
            meipass.mkdir()

            with mock.patch.object(sys, "frozen", True, create=True), \
                 mock.patch.object(sys, "_MEIPASS", str(meipass), create=True):
                resolved = _resolve_src_dir(Path(tmp), None)
                assert resolved == meipass.resolve()


# =========================================================================
# 3. Model Manifest & Worker Validation
# =========================================================================

class TestModelManifestAndWorkerHealth:
    """Verify model manifest loading, hash verification, and worker validation."""

    def test_validate_model_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            model_dir = Path(tmp)
            model_subdir = model_dir / "PP-OCRv5_mobile_rec_infer"
            model_subdir.mkdir()
            payload = b"mock model payload"
            digest = hashlib.sha256(payload).hexdigest().upper()
            for fname in ("inference.json", "inference.pdiparams", "inference.yml"):
                (model_subdir / fname).write_bytes(payload)

            manifest = {
                "manifest_version": "1.0",
                "models": [
                    {
                        "name": "PP-OCRv5_mobile_rec_infer",
                        "type": "rec",
                        "files": {
                            "inference.json": {"size_bytes": len(payload), "sha256": digest},
                            "inference.pdiparams": {"size_bytes": len(payload), "sha256": digest},
                            "inference.yml": {"size_bytes": len(payload), "sha256": digest},
                        },
                    }
                ]
            }
            (model_dir / "MODEL_MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")

            with mock.patch("shuabao.vision.ocr_shadow.worker._model_dir", return_value=model_subdir):
                reason = _validate_model(model_subdir)
                assert reason is None

    def test_validate_model_missing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            model_dir = Path(tmp) / "PP-OCRv5_mobile_rec_infer"
            reason = _validate_model(model_dir)
            assert reason == "model_missing"

    def test_validate_model_corrupt_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            model_dir = Path(tmp)
            model_subdir = model_dir / "PP-OCRv5_mobile_rec_infer"
            model_subdir.mkdir()
            for fname in ("inference.json", "inference.pdiparams", "inference.yml"):
                (model_subdir / fname).write_bytes(b"bad content")

            manifest = {
                "manifest_version": "1.0",
                "models": [
                    {
                        "name": "PP-OCRv5_mobile_rec_infer",
                        "files": {
                            "inference.json": {"size_bytes": 100, "sha256": "CORRECT_SHA256"},
                        },
                    }
                ]
            }
            (model_dir / "MODEL_MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
            with mock.patch("shuabao.vision.ocr_shadow.worker._model_dir", return_value=model_subdir):
                reason = _validate_model(model_subdir)
                assert reason == "model_corrupt"


# =========================================================================
# 4. True READY Protocol Validation & Health Properties
# =========================================================================

class TestTrueReadyProtocol:
    """Verify that ShadowClient enforces strict True READY semantics."""

    def test_client_ready_properties(self):
        worker_script = (
            "import json, sys\n"
            "ready = {\n"
            "  'type': 'ready',\n"
            "  'seq': 0,\n"
            "  'status': 'ok',\n"
            "  'candidates': [],\n"
            "  'elapsed_ms': 5.2,\n"
            "  'load_ms': 120.0,\n"
            "  'model_validated': True,\n"
            "  'model_name': 'PP-OCRv5_rec',\n"
            "  'model_hash': 'abcdef123456'\n"
            "}\n"
            "print(json.dumps(ready), flush=True)\n"
            "for line in sys.stdin:\n"
            "  req = json.loads(line)\n"
            "  if req.get('type') == 'ping':\n"
            "    print(json.dumps({'type':'pong','seq':req['seq'],'status':'ok','candidates':[],'elapsed_ms':0.1}), flush=True)\n"
        )
        client = ShadowClient(
            worker_command=[sys.executable, "-c", worker_script],
            timeout_ms=500,
        )
        try:
            assert client.start() is True
            assert client.is_ready is True
            assert client.is_available is True
            assert client.model_validated is True
            assert client.model_name == "PP-OCRv5_rec"
            assert client.model_hash == "abcdef123456"
            assert client.load_ms == 120.0
            assert client.crashes == 0
            assert client.model_hash == "abcdef123456"
            assert client.load_ms == 120.0
            assert client.ping() is True

            health = client.health()
            assert health["alive"] is True
            assert health["ready"] is True
            assert health["status"] == "ok"
            assert health["model_name"] == "PP-OCRv5_rec"
            assert health["model_hash"] == "abcdef123456"
        finally:
            client.close()

    def test_client_rejects_unvalidated_model(self):
        worker_script = (
            "import json, sys\n"
            "ready = {\n"
            "  'type': 'ready',\n"
            "  'seq': 0,\n"
            "  'status': 'ok',\n"
            "  'candidates': [],\n"
            "  'elapsed_ms': 1.0,\n"
            "  'model_validated': False,\n"
            "  'reason': 'manifest_hash_mismatch'\n"
            "}\n"
            "print(json.dumps(ready), flush=True)\n"
            "for line in sys.stdin: pass\n"
        )
        client = ShadowClient(
            worker_command=[sys.executable, "-c", worker_script],
            timeout_ms=500,
            startup_timeout_ms=500,
        )
        try:
            assert client.start() is False
            assert client.is_ready is False
            assert client.is_available is False
            assert client.model_validated is False
            assert client.ready_reason == "manifest_hash_mismatch"
        finally:
            client.close()

# =========================================================================
# 5. Bounded Restart, Cooldown & Recovery State Machine
# =========================================================================

class TestBoundedRestartAndRecovery:
    """Verify crash counting, maximum restarts, cooldown backoff, and recovery."""

    def test_crash_increments_and_disables_after_max_restarts(self):
        worker_script = "import sys; sys.exit(1)\n"
        client = ShadowClient(
            worker_command=[sys.executable, "-c", worker_script],
            max_restarts=2,
            restart_cooldown_s=10.0,
            startup_timeout_ms=100,
        )
        try:
            # Attempt 1: fails
            resp1 = client.shadow_predict(_dummy_frame(), "p1", _dummy_slot())
            assert resp1.status == "unavailable"

            # Attempt 2: fails
            resp2 = client.shadow_predict(_dummy_frame(), "p2", _dummy_slot())
            assert resp2.status == "unavailable"

            # After max_restarts reached, client enters disabled / cooldown state
            assert client.crashes >= 2
            assert client.disabled is True

            # Attempt 3: directly blocked by cooldown without trying to spawn
            resp3 = client.shadow_predict(_dummy_frame(), "p3", _dummy_slot())
            assert resp3.status == "unavailable"
            assert resp3.reason in ("disabled", "disabled_cooldown")
        finally:
            client.close()
    def test_cooldown_expiry_allows_rearm(self):
        worker_script = "import sys; sys.exit(1)\n"
        client = ShadowClient(
            worker_command=[sys.executable, "-c", worker_script],
            max_restarts=1,
            restart_cooldown_s=0.1,  # Short cooldown for test
            startup_timeout_ms=100,
        )
        try:
            client.shadow_predict(_dummy_frame(), "p1", _dummy_slot())
            assert client.disabled is True

            # Wait for cooldown to expire
            time.sleep(0.15)
            assert client.disabled is False

            # Can attempt rearm
            client.rearm()
            assert client.disabled is False
            assert client.crashes == 0
        finally:
            client.close()


# =========================================================================
# 6. Fault Injection Scenarios
# =========================================================================

class TestFaultInjectionScenarios:
    """Verify fault tolerance against corrupted data, timeouts, and process anomalies."""

    def test_worker_emits_garbage_lines_during_predict(self):
        worker_script = (
            "import json, sys\n"
            "print(json.dumps({'type':'ready','seq':0,'status':'ok','candidates':[],'elapsed_ms':0,'model_validated':True}), flush=True)\n"
            "for line in sys.stdin:\n"
            "  print('<html>502 Bad Gateway</html>', flush=True)\n"
        )
        client = ShadowClient(
            worker_command=[sys.executable, "-c", worker_script],
            timeout_ms=200,
        )
        try:
            resp = client.shadow_predict(_dummy_frame(), "p1", _dummy_slot())
            assert resp.status == "unavailable"
            assert resp.reason in ("protocol", "bad_json")
        finally:
            client.close()
    def test_worker_hangs_triggers_timeout_without_desync(self):
        worker_script = (
            "import json, sys, time\n"
            "print(json.dumps({'type':'ready','seq':0,'status':'ok','candidates':[],'elapsed_ms':0,'model_validated':True}), flush=True)\n"
            "for line in sys.stdin:\n"
            "  req = json.loads(line)\n"
            "  if req.get('panel_id') == 'hang':\n"
            "    time.sleep(0.5)\n"
            "  print(json.dumps({'seq':req['seq'],'status':'ok','candidates':[{'name':'测试技能','confidence':0.95}],'elapsed_ms':1}), flush=True)\n"
        )
        client = ShadowClient(
            worker_command=[sys.executable, "-c", worker_script],
            timeout_ms=50,  # 50ms timeout
        )
        try:
            # 1. First request hangs -> timeout
            resp1 = client.shadow_predict(_dummy_frame(), "hang", _dummy_slot())
            assert resp1.status == "unavailable"
            assert resp1.reason == "timeout"

            # 2. Wait for worker to finish delayed output
            time.sleep(0.5)

            # 3. Subsequent request with new sequence matches cleanly
            resp2 = client.shadow_predict(_dummy_frame(), "normal", _dummy_slot(), fingerprint="f2")
            assert resp2.status == "ok"
            assert len(resp2.candidates) == 1
            assert resp2.candidates[0].name == "测试技能"
        finally:
            client.close()

    def test_sequence_desync_recovery(self):
        worker_script = (
            "import json, sys\n"
            "print(json.dumps({'type':'ready','seq':0,'status':'ok','candidates':[],'elapsed_ms':0,'model_validated':True}), flush=True)\n"
            "for line in sys.stdin:\n"
            "  req = json.loads(line)\n"
            "  # Send wrong seq first, then correct seq\n"
            "  print(json.dumps({'seq':9999,'status':'ok','candidates':[],'elapsed_ms':1}), flush=True)\n"
            "  print(json.dumps({'seq':req['seq'],'status':'ok','candidates':[{'name':'恢复成功','confidence':0.99}],'elapsed_ms':1}), flush=True)\n"
        )
        client = ShadowClient(
            worker_command=[sys.executable, "-c", worker_script],
            timeout_ms=500,
        )
        try:
            resp = client.shadow_predict(_dummy_frame(), "p1", _dummy_slot())
            assert resp.status == "ok"
            assert resp.candidates[0].name == "恢复成功"
        finally:
            client.close()

    def test_trace_logging_integration(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace_file = Path(tmp) / "trace.jsonl"
            worker_script = (
                "import json, sys\n"
                "print(json.dumps({'type':'ready','seq':0,'status':'ok','candidates':[],'elapsed_ms':0,'model_validated':True}), flush=True)\n"
                "for line in sys.stdin:\n"
                "  req = json.loads(line)\n"
                "  print(json.dumps({'seq':req['seq'],'status':'ok','candidates':[{'name':'追踪命中','confidence':0.88}],'elapsed_ms':2}), flush=True)\n"
            )
            client = ShadowClient(
                worker_command=[sys.executable, "-c", worker_script],
                trace_path=trace_file,
                timeout_ms=500,
            )
            try:
                resp = client.shadow_predict(_dummy_frame(), "p_trace", _dummy_slot())
                assert resp.status == "ok"
                assert trace_file.exists()
                lines = [json.loads(line) for line in trace_file.read_text(encoding="utf-8").strip().splitlines()]
                # Should contain lifecycle events and prediction trace event
                assert len(lines) >= 2
                events = [r.get("event") for r in lines]
                assert "ocr_worker" in events
                pred_record = [r for r in lines if r.get("event") == "prediction" or "panel_id" in r][0]
                assert pred_record["panel_id"] == "p_trace"
                assert pred_record["status"] == "ok"
                assert pred_record["candidates"][0]["name"] == "追踪命中"
            finally:
                client.close()
