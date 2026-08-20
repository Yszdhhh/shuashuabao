"""Desktop / API / CLI share one AppData root and live.lock; controller is not Core Mediator LIVE."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from PySide6.QtCore import QLockFile
from PySide6.QtWidgets import QApplication

from shuabao.incidents import default_incident_dir
from shuabao.shell.headless_runner import default_headless_app_data
from shuabao.shell.live_execute import live_lock_path
from shuabao.shell.main_window import MainWindow
from shuabao.shell.main_window import _app_data_dir


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    return app


def test_mainwindow_default_appdata_is_shuabao_not_cjk(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("SHUABAO_APP_DATA", raising=False)
    window = MainWindow()
    expected = (tmp_path / "ShuaBao").resolve()
    try:
        assert window.app_data == expected
        assert window.app_data == default_incident_dir().parent.resolve()
        assert window.app_data == default_headless_app_data().resolve()
        assert live_lock_path(window.app_data) == expected / "ShuaBao.live.lock"
        assert "刷刷宝" not in str(window.app_data)
        assert _app_data_dir().resolve() == expected
    finally:
        window.close()


def test_shuabao_app_data_override_still_isolates(qapp, tmp_path, monkeypatch):
    isolated = tmp_path / "isolated"
    monkeypatch.setenv("SHUABAO_APP_DATA", str(isolated))
    window = MainWindow()
    try:
        assert window.app_data == isolated.resolve()
        assert default_incident_dir().parent.resolve() == isolated.resolve()
        assert default_headless_app_data().resolve() == isolated.resolve()
    finally:
        window.close()


def test_second_lock_client_fails_on_same_live_lock(qapp, tmp_path):
    lock_path = live_lock_path(tmp_path)
    first = QLockFile(str(lock_path))
    assert first.tryLock(100)
    second = QLockFile(str(lock_path))
    assert second.tryLock(100) is False
    first.unlock()


def test_controller_source_does_not_live_import_core_mediator():
    text = (ROOT / "controller.py").read_text(encoding="utf-8")
    assert "from shuabao.mediator import Mediator" not in text
    assert "HeadlessRunner" in text
    assert "default_headless_app_data" in text


def test_main_py_run_uses_headless_runner():
    text = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "HeadlessRunner" in text
    assert "default_headless_app_data" in text
    assert "from shuabao.mediator import Mediator" not in text
    assert "from shuabao.runtime_mediator import Mediator" not in text
    run_block = text.split("def cmd_run", 1)[1].split("def cmd_inventory", 1)[0]
    assert "HeadlessRunner" in run_block
    dry_block = text.split("def cmd_dry_run", 1)[1].split("def cmd_run", 1)[0]
    assert "HeadlessRunner" in dry_block
    assert "Mediator(" not in dry_block
