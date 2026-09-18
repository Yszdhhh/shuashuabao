"""Offline contracts for the thin Test Dashboard; never starts live input."""

from __future__ import annotations

import json
from pathlib import Path

import tools.test_dashboard as dashboard


def test_dashboard_has_no_second_window_ocr_or_native_settings_authority() -> None:
    source = Path(dashboard.__file__).read_text(encoding="utf-8")

    for forbidden in (
        "PreflightChecker",
        "OpenDesktopW",
        "SetThreadDesktop",
        "EnumWindows",
        "find_window_targets",
        "from shuabao.vision",
        "from shuabao.shell.main_window import",
        "APP_DATA =",
        "user_settings.json",
    ):
        assert forbidden not in source


def test_canonical_blocked_result_never_launches_one_click() -> None:
    popen_calls: list[tuple[object, dict]] = []

    def fake_popen(*args, **kwargs):
        popen_calls.append((args, kwargs))

    for reason in (
        "identity BLOCKED",
        "missing OCR evidence",
        "window BLOCKED",
        "start surface BLOCKED",
        "single-instance busy",
    ):
        report = {"status": "BLOCKED", "blocked_reasons": [reason]}
        assert dashboard.launch_canonical_one_click(report, fake_popen) is False

    assert popen_calls == []


def test_canonical_ready_result_is_the_only_launch_path() -> None:
    popen_calls: list[tuple[object, dict]] = []

    def fake_popen(*args, **kwargs):
        popen_calls.append((args, kwargs))

    assert dashboard.launch_canonical_one_click({"status": "READY"}, fake_popen) is True
    assert len(popen_calls) == 1
    command = popen_calls[0][0][0]
    assert str(dashboard.CANONICAL_ONE_CLICK) in command
    assert "one_click_test.cmd" not in command


def test_canonical_readiness_blocked_disables_combined_result(monkeypatch) -> None:
    called = []
    monkeypatch.setattr(
        dashboard,
        "run_canonical_readiness",
        lambda: {"ready_for_gt": False, "blocked_reasons": ["wrong Test SHA"]},
    )
    monkeypatch.setattr(dashboard, "run_canonical_prepare", lambda: called.append("prepare"))

    report = dashboard.run_canonical_gt_readiness()

    assert report["status"] == "BLOCKED"
    assert report["phase"] == "readiness"
    assert called == []


def test_readiness_exit_code_is_required_before_prepare(monkeypatch) -> None:
    called = []
    monkeypatch.setattr(
        dashboard,
        "run_canonical_readiness",
        lambda: {"ready_for_gt": True, "_command_exit_code": 1},
    )
    monkeypatch.setattr(dashboard, "run_canonical_prepare", lambda: called.append("prepare"))

    report = dashboard.run_canonical_gt_readiness()

    assert report["status"] == "BLOCKED"
    assert report["phase"] == "readiness"
    assert called == []


def test_canonical_preflight_blocked_disables_combined_result(monkeypatch) -> None:
    monkeypatch.setattr(
        dashboard,
        "run_canonical_readiness",
        lambda: {"ready_for_gt": True, "_command_exit_code": 0},
    )
    monkeypatch.setattr(
        dashboard,
        "run_canonical_prepare",
        lambda: {"status": "READY", "_command_exit_code": 0},
    )
    monkeypatch.setattr(
        dashboard,
        "run_canonical_preflight",
        lambda _manifest: {
            "status": "BLOCKED",
            "_command_exit_code": 0,
            "blocked_reasons": ["window BLOCKED"],
        },
    )

    report = dashboard.run_canonical_gt_readiness()

    assert report["status"] == "BLOCKED"
    assert report["phase"] == "preflight"
    assert dashboard.canonical_ready_for_start(report) is False


def test_prepare_exit_code_is_required_before_preflight(monkeypatch) -> None:
    called = []
    monkeypatch.setattr(
        dashboard,
        "run_canonical_readiness",
        lambda: {"ready_for_gt": True, "_command_exit_code": 0},
    )
    monkeypatch.setattr(
        dashboard,
        "run_canonical_prepare",
        lambda: {"status": "READY", "_command_exit_code": 1},
    )
    monkeypatch.setattr(dashboard, "run_canonical_preflight", lambda _manifest: called.append("preflight"))

    report = dashboard.run_canonical_gt_readiness()

    assert report["status"] == "BLOCKED"
    assert report["phase"] == "prepare"
    assert called == []


def test_preflight_exit_code_is_required_for_ready_result(monkeypatch) -> None:
    monkeypatch.setattr(
        dashboard,
        "run_canonical_readiness",
        lambda: {"ready_for_gt": True, "_command_exit_code": 0},
    )
    monkeypatch.setattr(
        dashboard,
        "run_canonical_prepare",
        lambda: {"status": "READY", "_command_exit_code": 0},
    )
    monkeypatch.setattr(
        dashboard,
        "run_canonical_preflight",
        lambda _manifest: {"status": "READY", "_command_exit_code": 1},
    )

    report = dashboard.run_canonical_gt_readiness()

    assert report["status"] == "BLOCKED"
    assert report["phase"] == "preflight"
    assert dashboard.canonical_ready_for_start(report) is False


def test_exit_code_blocked_results_keep_start_disabled_and_do_not_popen() -> None:
    popen_calls: list[tuple[object, dict]] = []

    def fake_popen(*args, **kwargs):
        popen_calls.append((args, kwargs))

    for phase in ("readiness", "prepare", "preflight"):
        report = {"status": "BLOCKED", "phase": phase}
        assert dashboard.canonical_ready_for_start(report) is False
        assert dashboard.launch_canonical_one_click(report, fake_popen) is False

    assert popen_calls == []


def test_canonical_ready_requires_all_three_canonical_stages(monkeypatch) -> None:
    monkeypatch.setattr(
        dashboard,
        "run_canonical_readiness",
        lambda: {"ready_for_gt": True, "_command_exit_code": 0},
    )
    monkeypatch.setattr(
        dashboard,
        "run_canonical_prepare",
        lambda: {
            "status": "READY",
            "_command_exit_code": 0,
            "settings_path": "session/settings.json",
        },
    )
    monkeypatch.setattr(
        dashboard,
        "run_canonical_preflight",
        lambda _manifest: {"status": "READY", "_command_exit_code": 0},
    )

    report = dashboard.run_canonical_gt_readiness()

    assert report["status"] == "READY"
    assert dashboard.canonical_ready_for_start(report) is True


def test_prepare_manifest_is_read_only_to_dashboard(tmp_path: Path, monkeypatch) -> None:
    session = tmp_path / "session"
    session.mkdir()
    (session / "manifest.json").write_text(
        json.dumps({"status": "READY", "settings_path": str(session / "settings.json")}),
        encoding="utf-8",
    )

    class Result:
        returncode = 0
        stdout = f"SESSION={session}\n"
        stderr = ""

    monkeypatch.setattr(dashboard.subprocess, "run", lambda *args, **kwargs: Result())
    result = dashboard.run_canonical_prepare()

    assert result["status"] == "READY"
    assert not (tmp_path / "user_settings.json").exists()
    assert not (session / "user_settings.json").exists()
