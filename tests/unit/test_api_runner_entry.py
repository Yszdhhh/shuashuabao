"""API / headless LIVE entry: RunnerService safety path, not a naked Core Mediator."""

from __future__ import annotations

import builtins
import importlib
import importlib.util
import inspect
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from shuabao.settings import Settings
from shuabao.shell.headless_runner import HeadlessRunner
from shuabao.shell.live_execute import execute_runtime_mediator
from shuabao.stop_signal import StopSignal

ROOT = Path(__file__).resolve().parents[2]


def test_api_server_source_does_not_import_core_mediator():
    text = (ROOT / "api_server.py").read_text(encoding="utf-8")
    assert "from shuabao.mediator import Mediator" not in text
    assert "HeadlessRunner" in text
    assert "shuabao.runtime_mediator" in inspect.getsource(execute_runtime_mediator)


def test_headless_runner_loads_runtime_mediator_not_core(tmp_path: Path):
    loaded: dict[str, str] = {}

    class FakeMediator:
        def __init__(self, settings, root, *args, **kwargs):
            loaded["module"] = "shuabao.runtime_mediator"
            loaded["incident_dir"] = str(kwargs.get("incident_dir") or "")
            loaded["stop"] = type(kwargs.get("stop_signal")).__name__
            self.settings = settings
            self.game_count = 0
            self.phase = type("P", (), {"name": "BOOT"})()
            self._ocr_bootstrap_health = {"healthy": True, "skipped": True}
            self._ocr_client = None

        def prepare_live_dependencies(self) -> bool:
            return True

        def run(self, max_steps=None) -> None:
            loaded["ran"] = True
            loaded["max_steps"] = max_steps

        def set_trace(self, path) -> None:
            return None

        def stop(self) -> None:
            return None

    with patch("shuabao.runtime_mediator.Mediator", FakeMediator):
        runner = HeadlessRunner(tmp_path, ROOT)
        result = runner.run_blocking(Settings(dry_run=True), max_steps=3)

    assert loaded.get("module") == "shuabao.runtime_mediator"
    assert loaded.get("ran") is True
    assert loaded.get("max_steps") == 3
    assert "incidents" in loaded.get("incident_dir", "")
    assert loaded.get("stop") == "StopSignal"
    assert result.get("mediator") is not None


def test_print_restored_after_forced_worker_exception(tmp_path: Path):
    real_print = builtins.print

    class BoomMediator:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("forced worker exception")

    with patch("shuabao.runtime_mediator.Mediator", BoomMediator):
        runner = HeadlessRunner(tmp_path, ROOT)
        result = runner.run_blocking(Settings(dry_run=True))

    assert builtins.print is real_print
    assert "forced worker exception" in str(result.get("terminal_reason") or "")


def test_api_start_run_uses_headless_runner(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SHUABAO_APP_DATA", str(tmp_path))
    spec = importlib.util.spec_from_file_location("shuabao_api_server", ROOT / "api_server.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.runner.state = "IDLE"
    module.runner.thread = None
    module.runner.mediator = None
    module.runner.headless = None

    seen: dict[str, object] = {}

    def fake_run(self, settings, *, max_steps=None, log_fn=None, on_mediator=None):
        seen["cls"] = type(self).__name__
        seen["max_steps"] = max_steps
        seen["print_before"] = builtins.print
        if on_mediator is not None:
            med = type("M", (), {"game_count": 0, "phase": type("P", (), {"name": "BOOT"})()})()
            on_mediator(med)
        raise RuntimeError("forced api worker exception")

    with patch.object(module.HeadlessRunner, "run_blocking", fake_run):
        payload = module.start_run(module.StartRunRequest(dry_run=True, max_steps=2))
        assert payload["status"] == "started"
        thread = module.runner.thread
        if thread is not None:
            thread.join(timeout=5)

    assert seen.get("cls") == "HeadlessRunner"
    assert seen.get("max_steps") == 2
    assert builtins.print is seen.get("print_before") or builtins.print is print
    assert builtins.print is print
    assert module.runner.state == "IDLE"
    assert module.runner.mediator is None


def test_run_blocking_reuses_stop_signal_and_honors_prestop(tmp_path: Path):
    constructed: list[str] = []

    class TrackingMediator:
        def __init__(self, *args, **kwargs):
            constructed.append("init")
            raise RuntimeError("Mediator must not be built after stop()")

    runner = HeadlessRunner(tmp_path, ROOT)
    original = runner.stop_signal
    runner.stop()
    assert original.is_set()
    with patch("shuabao.runtime_mediator.Mediator", TrackingMediator):
        result = runner.run_blocking(Settings(dry_run=True))
    assert runner.stop_signal is original
    assert constructed == []
    reason = str(result.get("terminal_reason") or "")
    assert reason
    assert "stop" in reason.lower() or "停止" in reason


def test_run_blocking_does_not_mint_new_signal_on_happy_path(tmp_path: Path):
    class FakeMediator:
        def __init__(self, *args, **kwargs):
            self.game_count = 0
            self.phase = type("P", (), {"name": "BOOT"})()
            self._ocr_bootstrap_health = {"healthy": True}
            self._ocr_client = None

        def prepare_live_dependencies(self) -> bool:
            return True

        def run(self, max_steps=None) -> None:
            return None

        def set_trace(self, path) -> None:
            return None

    runner = HeadlessRunner(tmp_path, ROOT)
    original = runner.stop_signal
    with patch("shuabao.runtime_mediator.Mediator", FakeMediator):
        runner.run_blocking(Settings(dry_run=True), max_steps=1)
    assert runner.stop_signal is original
    assert original.is_set() is False


def _load_api(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SHUABAO_APP_DATA", str(tmp_path))
    spec = importlib.util.spec_from_file_location("shuabao_api_server", ROOT / "api_server.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.runner.state = "IDLE"
    module.runner.thread = None
    module.runner.mediator = None
    module.runner.headless = None
    return module


def test_bind_headless_or_abort_stopping_triggers_existing_signal(tmp_path: Path, monkeypatch):
    module = _load_api(tmp_path, monkeypatch)
    headless = module.HeadlessRunner(tmp_path, ROOT)
    original = headless.stop_signal
    module.runner.state = "STOPPING"
    module.runner.generation = 3
    assert module.bind_headless_or_abort(module.runner, 3, headless) is True
    assert module.runner.headless is headless
    assert headless.stop_signal is original
    assert original.is_set() is True


def test_api_stop_during_starting_skips_run_blocking(tmp_path: Path, monkeypatch):
    module = _load_api(tmp_path, monkeypatch)
    inited = threading.Event()
    hold = threading.Event()
    calls: list[str] = []
    Real = module.HeadlessRunner

    class SlowInit(Real):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            inited.set()
            hold.wait(timeout=5)

        def run_blocking(self, *args, **kwargs):
            calls.append("run_blocking")
            raise AssertionError("run_blocking must not run after STOPPING")

    module.HeadlessRunner = SlowInit
    payload = module.start_run(module.StartRunRequest(dry_run=True, max_steps=1))
    assert payload["status"] == "started"
    assert inited.wait(timeout=5)
    stopped = module.stop_run()
    assert stopped["status"] == "stopping"
    hold.set()
    thread = module.runner.thread
    if thread is not None:
        thread.join(timeout=5)
    assert calls == []
    assert module.runner.state == "IDLE"


def test_execute_runtime_mediator_print_restore_on_import_style_path(tmp_path: Path):
    real_print = builtins.print

    class Boom:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("boom")

    with patch("shuabao.runtime_mediator.Mediator", Boom):
        execute_runtime_mediator(
            settings=Settings(dry_run=True),
            root_dir=ROOT,
            incident_dir=tmp_path / "incidents",
            stop_signal=StopSignal(),
        )
    assert builtins.print is real_print
