from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys

import numpy as np
import pytest

from shuabao.loop_action import LoopAction
from shuabao.mediator import PanelState, Phase
from shuabao.runtime_mediator import Mediator as RuntimeMediator
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult
from shuabao.vision.ocr_shadow.production import (
    ProductionShadowClient,
    _resolve_production_worker,
)


ROOT = Path(__file__).resolve().parents[2]


def _frame(hwnd: int = 12345) -> Frame:
    return Frame(np.zeros((720, 1280, 3), dtype=np.uint8), hwnd=hwnd)


def _anchor() -> MatchResult:
    return MatchResult(
        name="bond_panel_anchor",
        score=0.99,
        x=100,
        y=100,
        w=20,
        h=20,
        screen_x=100,
        screen_y=100,
    )


class _HealthyClient:
    ready_reason = "ok"
    model_validated = True
    model_name = "PP-OCRv5_mobile_rec_infer"
    model_hash = "ABC123"
    python_executable = "ShuaBaoOCR.exe"
    model_dir = "models/ocr"

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.closed = False

    def start(self) -> bool:
        self.calls.append("start")
        return True

    def ping(self, timeout_ms=None) -> bool:
        self.calls.append("ping")
        return True

    def warmup(self, timeout_ms=None) -> bool:
        self.calls.append("warmup")
        return True

    def health_check(self):
        self.calls.append("health")
        return {
            "healthy": True,
            "process_alive": True,
            "ready": True,
            "model_validated": True,
            "model_name": self.model_name,
            "model_hash": self.model_hash,
            "disabled": False,
            "crashes": 0,
            "ready_reason": "ok",
            "load_ms": 12.0,
        }

    def close(self) -> None:
        self.calls.append("close")
        self.closed = True


def test_live_bootstrap_requires_start_ping_warmup_then_health():
    med = object.__new__(RuntimeMediator)
    med.settings = SimpleNamespace(ocr_mode="live", ocr_timeout_ms=1200)
    med._ocr_bootstrap_health = None
    client = _HealthyClient()
    med._ocr_client = client

    assert med.prepare_live_dependencies() is True
    assert client.calls == ["start", "ping", "warmup", "health"]
    assert med._ocr_bootstrap_health["healthy"] is True
    assert med._ocr_bootstrap_health["stage"] == "ready"


def test_live_bootstrap_fails_closed_when_warmup_fails():
    med = object.__new__(RuntimeMediator)
    med.settings = SimpleNamespace(ocr_mode="live", ocr_timeout_ms=1200)
    med._ocr_bootstrap_health = None
    client = _HealthyClient()
    client.warmup = lambda timeout_ms=None: client.calls.append("warmup") or False
    med._ocr_client = client

    assert med.prepare_live_dependencies() is False
    assert client.calls == ["start", "ping", "warmup", "close"]
    assert med._ocr_bootstrap_health["stage"] == "warmup"
    assert client.closed is True


def test_persistent_physical_panel_survives_core_episode_reset_and_stops():
    med = RuntimeMediator(Settings(ocr_mode="off"), ROOT)
    med._physical_panel_deadline_s = 5.0
    med._panel_kind = "bond"
    frame = _frame()
    anchor = _anchor()
    incidents: list[str] = []
    med._record_fail_closed_incident = incidents.append

    assert med._physical_panel_watchdog(frame, anchor, 100.0) is None
    signature = med._physical_panel_signature

    # Simulate the core episode finishing/cooling down while the same physical
    # modal never disappeared.  Runtime physical history must not be erased.
    med._panel_state = PanelState.CLOSED
    med._panel_episode_id = None
    med._panel_episode_started = None
    med._panel_kind = "bond"
    assert med._physical_panel_signature == signature

    action = med._physical_panel_watchdog(frame, anchor, 106.0)
    assert action == LoopAction.Break
    assert med.phase == Phase.ERROR
    assert med.stop_signal.is_set()
    assert incidents and "physical_panel_stagnation" in incidents[0]


def test_physical_panel_guard_resets_only_after_sustained_absence():
    med = RuntimeMediator(Settings(ocr_mode="off"), ROOT)
    med._panel_kind = "bond"
    frame = _frame()
    anchor = _anchor()

    med._physical_panel_watchdog(frame, anchor, 100.0)
    assert med._physical_panel_signature is not None
    med._physical_panel_watchdog(frame, None, 100.2)
    assert med._physical_panel_signature is not None
    med._physical_panel_watchdog(frame, None, 101.3)
    assert med._physical_panel_signature is None


def test_frozen_runtime_never_uses_main_shuabao_executable_as_python(tmp_path: Path):
    main_exe = tmp_path / "ShuaBao.exe"
    main_exe.touch()
    meipass = tmp_path / "_internal"
    meipass.mkdir()

    with patch.object(sys, "frozen", True, create=True), \
         patch.object(sys, "executable", str(main_exe)), \
         patch.object(sys, "_MEIPASS", str(meipass), create=True):
        with pytest.raises(FileNotFoundError, match="ShuaBaoOCR.exe"):
            _resolve_production_worker(tmp_path)

        sidecar = tmp_path / "vision" / "ShuaBaoOCR.exe"
        sidecar.parent.mkdir()
        sidecar.touch()
        resolved, standalone = _resolve_production_worker(tmp_path)
        assert resolved == sidecar.resolve()
        assert standalone is True
        assert resolved != main_exe.resolve()


def test_packaged_production_client_marks_sidecar_as_explicit_worker(tmp_path: Path):
    main_exe = tmp_path / "ShuaBao.exe"
    main_exe.touch()
    sidecar = tmp_path / "vision" / "ShuaBaoOCR.exe"
    sidecar.parent.mkdir()
    sidecar.touch()
    model_dir = tmp_path / "models" / "ocr"
    model_dir.mkdir(parents=True)

    with patch.object(sys, "frozen", True, create=True), \
         patch.object(sys, "executable", str(main_exe)), \
         patch.object(sys, "_MEIPASS", str(tmp_path / "_internal"), create=True):
        client = ProductionShadowClient(repo_root=tmp_path)
        assert client.worker_command == [str(sidecar.resolve())]
        assert client._command() == [str(sidecar.resolve())]
        assert client.python_executable == str(sidecar.resolve())
