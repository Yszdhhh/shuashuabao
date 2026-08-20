"""LogEventSink: no builtins.print assignment, subscriber + file, no deadlock."""

from __future__ import annotations

import builtins
import logging
import re
import threading
from pathlib import Path
from unittest.mock import patch

from shuabao.log_sink import LogEventSink, LOGGER, emit_print
from shuabao.mediator import Phase
from shuabao.runtime_mediator import Mediator as RuntimeMediator
from shuabao.settings import Settings
from shuabao.shell.headless_runner import HeadlessRunner
from shuabao.shell.live_execute import execute_runtime_mediator
from shuabao.stop_signal import StopSignal

ROOT = Path(__file__).resolve().parents[2]


_ASSIGN_PRINT = re.compile(r"\bbuiltins\.print\s*=")


def _production_py_files() -> list[Path]:
    skip = {"tests", "references", "build", "dist", "_old", "__pycache__", "site-packages"}
    out: list[Path] = []
    for path in ROOT.rglob("*.py"):
        if any(
            part in skip or part.startswith("build") or part.startswith(".venv")
            for part in path.parts
        ):
            continue
        out.append(path)
    return out


def test_production_sources_never_assign_builtins_print():
    hits: list[str] = []
    for path in _production_py_files():
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if _ASSIGN_PRINT.search(stripped):
                hits.append(f"{path.relative_to(ROOT)}:{i}:{stripped}")
    assert hits == []


def test_runtime_mediator_log_reaches_sink_and_file(tmp_path: Path):
    real_print = builtins.print
    received: list[str] = []
    sink = LogEventSink()
    sink.subscribe(lambda text, _kind: received.append(text))
    log_file = tmp_path / "runtime.log"
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(message)s"))
    LOGGER.addHandler(sink)
    LOGGER.addHandler(file_handler)
    LOGGER.setLevel(logging.INFO)
    try:
        med = RuntimeMediator(Settings(ocr_mode="off", dry_run=True), ROOT)
        med.set_phase(Phase.MAIN_LINE, "sink-test")
    finally:
        LOGGER.removeHandler(sink)
        LOGGER.removeHandler(file_handler)
        file_handler.close()
    assert builtins.print is real_print
    joined = "\n".join(received)
    assert "MAIN_LINE" in joined
    assert "sink-test" in joined
    file_text = log_file.read_text(encoding="utf-8")
    assert "MAIN_LINE" in file_text
    assert "sink-test" in file_text


def test_execute_runtime_mediator_never_assigns_print_and_sink_gets_line(tmp_path: Path):
    real_print = builtins.print
    received: list[tuple[str, str]] = []

    class FakeMediator:
        def __init__(self, settings, root, *args, **kwargs):
            self.settings = settings
            self.game_count = 0
            self.phase = type("P", (), {"name": "BOOT"})()
            self._ocr_bootstrap_health = {"healthy": True, "skipped": True}
            self._ocr_client = None

        def prepare_live_dependencies(self) -> bool:
            return True

        def run(self, max_steps=None) -> None:
            emit_print("[med] Run learning_mode=True mode=0 auto_room=True")

        def set_trace(self, path) -> None:
            return None

    with patch("shuabao.runtime_mediator.Mediator", FakeMediator):
        result = execute_runtime_mediator(
            settings=Settings(dry_run=True, ocr_mode="off"),
            root_dir=ROOT,
            incident_dir=tmp_path / "incidents",
            stop_signal=StopSignal(),
            log=lambda text, kind: received.append((text, kind)),
        )

    assert builtins.print is real_print
    texts = [t for t, _ in received]
    assert any("RuntimeMediator ready" in t or "execute_runtime_mediator start" in t for t in texts)
    assert any("[med] Run learning_mode=True" in t for t in texts)
    live_log = (tmp_path / "incidents" / "live.log").read_text(encoding="utf-8")
    assert "RuntimeMediator ready" in live_log or "execute_runtime_mediator start" in live_log
    assert "[med] Run learning_mode=True" in live_log
    assert result.get("log_sink") is not None


def test_headless_runner_print_identity_stable(tmp_path: Path):
    real_print = builtins.print
    seen: dict[str, object] = {}

    class FakeMediator:
        def __init__(self, *args, **kwargs):
            seen["print_during_init"] = builtins.print
            self.game_count = 0
            self.phase = type("P", (), {"name": "BOOT"})()
            self._ocr_bootstrap_health = {"healthy": True}
            self._ocr_client = None

        def prepare_live_dependencies(self) -> bool:
            seen["print_during_prepare"] = builtins.print
            return True

        def run(self, max_steps=None) -> None:
            seen["print_during_run"] = builtins.print

        def set_trace(self, path) -> None:
            return None

    with patch("shuabao.runtime_mediator.Mediator", FakeMediator):
        HeadlessRunner(tmp_path, ROOT).run_blocking(Settings(dry_run=True), max_steps=1)

    assert builtins.print is real_print
    assert seen["print_during_init"] is real_print
    assert seen["print_during_prepare"] is real_print
    assert seen["print_during_run"] is real_print


def test_two_threads_publish_no_deadlock_or_print_assign():
    real_print = builtins.print
    sink = LogEventSink()
    received: list[str] = []
    lock = threading.Lock()

    def _on(text: str, _kind: str) -> None:
        with lock:
            received.append(text)

    sink.subscribe(_on)
    LOGGER.addHandler(sink)
    LOGGER.setLevel(logging.INFO)
    errors: list[BaseException] = []

    def _worker(tag: str) -> None:
        try:
            for i in range(40):
                sink.publish(f"{tag}-{i}", "info")
                assert builtins.print is real_print
        except BaseException as exc:
            errors.append(exc)

    try:
        threads = [
            threading.Thread(target=_worker, args=("a",)),
            threading.Thread(target=_worker, args=("b",)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
            assert not t.is_alive()
    finally:
        LOGGER.removeHandler(sink)

    assert errors == []
    assert builtins.print is real_print
    assert any(item.startswith("a-") for item in received)
    assert any(item.startswith("b-") for item in received)
    assert len(received) == 80
