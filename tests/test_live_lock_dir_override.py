"""SHUABAO_LIVE_LOCK_DIR: source quick test shares the signed package's LIVE lock."""
from __future__ import annotations

import sys
from pathlib import Path

from shuabao import paths
from shuabao.player_profile import default_live_lock_path
from shuabao.shell import live_execute, runner_service


def test_lock_dir_wins_over_app_data_override(tmp_path, monkeypatch):
    shared = tmp_path / "ShuaBao"
    dev_app_data = tmp_path / "ShuaBao-dev"
    monkeypatch.setenv("SHUABAO_APP_DATA", str(dev_app_data))
    monkeypatch.setenv(paths.LIVE_LOCK_DIR_ENV, str(shared))
    expected = shared.resolve() / "ShuaBao.live.lock"
    assert paths.live_lock_path() == expected
    assert paths.live_lock_path(dev_app_data) == expected
    assert live_execute.live_lock_path(dev_app_data) == expected
    assert runner_service.live_lock_path(dev_app_data) == expected
    assert default_live_lock_path() == expected
    # Only the lock is shared; the rest of the dev profile stays isolated.
    assert paths.get_canonical_app_data_dir() == dev_app_data.resolve()
    assert paths.user_settings_path().parent == dev_app_data.resolve()


def test_lock_dir_unset_keeps_app_data(tmp_path, monkeypatch):
    monkeypatch.delenv(paths.LIVE_LOCK_DIR_ENV, raising=False)
    assert live_execute.live_lock_path(tmp_path) == tmp_path / "ShuaBao.live.lock"


def test_frozen_ignores_lock_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.LIVE_LOCK_DIR_ENV, str(tmp_path / "elsewhere"))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert live_execute.live_lock_path(tmp_path) == tmp_path / "ShuaBao.live.lock"
    assert paths.live_lock_path(tmp_path) == Path(tmp_path) / "ShuaBao.live.lock"


def test_shared_lock_is_mutually_exclusive_across_app_data(tmp_path, monkeypatch):
    from PySide6.QtCore import QLockFile

    shared = tmp_path / "ShuaBao"
    shared.mkdir()
    monkeypatch.setenv(paths.LIVE_LOCK_DIR_ENV, str(shared))
    holder = QLockFile(str(paths.live_lock_path(tmp_path / "signed")))
    assert holder.tryLock(100)
    try:
        assert runner_service.live_lock_busy(tmp_path / "ShuaBao-dev") is True
    finally:
        holder.unlock()
    assert runner_service.live_lock_busy(tmp_path / "ShuaBao-dev") is False
