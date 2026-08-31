"""Task 4：DashboardFacade 真实启动/停止与状态回传面（§6.3，task-4-brief）。

覆盖：
- start_run / stop_run 进入 @Slot 白名单；
- 启动只经注入（或缺省构造）的 RunnerService；preflight 失败 / live.lock 占用 /
  already running / ModeNotEnabled 一律 {ok:false} 且不建 worker；
- Worker 的 status_updated / log_emitted 以 QueuedConnection 桥到
  run_status_changed / log_appended；
- 真实 RunnerService 路径：IDLE→RUNNING→STOPPING→IDLE 流转、live.lock 占用与释放。
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import (
    QLockFile,
    QMetaMethod,
    QObject,
    QThread,
    Signal,
)
from PySide6.QtWidgets import QApplication

from shuabao.paths import live_lock_path
from shuabao.settings import Settings
from shuabao.shell import runner_service as rs_module
from shuabao.shell.dashboard_facade import DashboardFacade
from shuabao.shell.runner_service import LogSignal, ModeNotEnabled, RunnerService, live_lock_busy


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


# ---------------------------------------------------------------- 替身


class FakeWorker(QObject):
    """与 MediatorWorker 同形的受控 worker（signals/finished/isRunning）。"""

    finished = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.signals = LogSignal()
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def isRunning(self) -> bool:
        return self.started and not self.stopped


class FakeRunner:
    """记录调用路径的最小 RunnerService 替身。"""

    def __init__(self, *, error: Exception | None = None) -> None:
        self.runner_state = "IDLE"
        self.mode_id: str | None = None
        self.worker = None
        self.start_calls: list[tuple[str, Settings]] = []
        self.stop_calls = 0
        self.released = 0
        self.error = error

    def start(self, mode_id: str, settings_snapshot: Settings):
        if self.error is not None:
            raise self.error
        self.start_calls.append((mode_id, settings_snapshot))
        self.worker = FakeWorker()
        self.mode_id = mode_id
        self.runner_state = "RUNNING"
        return self.worker

    def stop(self) -> None:
        if self.worker is None:
            return
        self.stop_calls += 1
        self.runner_state = "STOPPING"
    def release_after_finish(self) -> None:
        self.released += 1
        self.runner_state = "IDLE"


def _drain(qapp) -> None:
    """投递 QueuedConnection 队列里的信号。"""
    for _ in range(5):
        qapp.processEvents()


@pytest.fixture()
def facade(qapp, tmp_path: Path):
    runner = FakeRunner()
    f = DashboardFacade(tmp_path, runner)
    f.runner = runner
    return f


def _slot_names(obj) -> set[str]:
    meta = obj.metaObject()
    out: set[str] = set()
    for i in range(meta.methodCount()):
        m: QMetaMethod = meta.method(i)
        if m.methodType() == QMetaMethod.Method.Slot:
            out.add(bytes(m.name()).decode())
    return out


# ---------------------------------------------------------------- 白名单与启动路径


def test_start_stop_in_slot_whitelist(facade):
    slots = _slot_names(facade)
    assert {"start_run", "stop_run"} <= slots


def test_start_run_success_routes_through_runner_once(qapp, tmp_path: Path):
    runner = FakeRunner()
    f = DashboardFacade(tmp_path, runner)
    res = json.loads(f.start_run(json.dumps({"mode_id": "normal_farm"})))
    assert res["ok"] is True
    assert [c[0] for c in runner.start_calls] == ["normal_farm"]
    assert isinstance(runner.start_calls[0][1], Settings)
    assert runner.worker.started is True


def test_start_run_refuses_an_unlicensed_dashboard(monkeypatch, qapp, tmp_path: Path):
    from shuabao.subscription_client import StartPermission

    runner = FakeRunner()
    f = DashboardFacade(tmp_path, runner)
    monkeypatch.setattr(
        "shuabao.shell.dashboard_facade.check_start_permission",
        lambda: StartPermission(False, "enforce", message="请输入卡密"),
    )
    res = json.loads(f.start_run(json.dumps({"mode_id": "normal_farm"})))
    assert res["ok"] is False
    assert res["error"] == "请输入卡密"
    assert runner.start_calls == []


def test_activate_subscription_accepts_the_bridge_activation_shape(monkeypatch, qapp, tmp_path: Path):
    f = DashboardFacade(tmp_path, FakeRunner())
    monkeypatch.setattr("shuabao.shell.dashboard_facade.activate_device", lambda _key: {"ok": True, "device": {}})
    monkeypatch.setattr(
        "shuabao.shell.dashboard_facade.validate_entitlement",
        lambda _key: {"valid": True, "can_start_runner": True, "status": "ACTIVE", "expires_at": "2026-09-30"},
    )
    monkeypatch.setattr("shuabao.shell.dashboard_facade.save_license_key", lambda _path, _key: True)
    res = json.loads(f.activate_subscription(json.dumps({"key": "local-test-key"})))
    assert res["ok"] is True
    assert res["subscription"]["active"] is True


def test_preflight_failure_blocks_before_runner(qapp, tmp_path: Path):
    runner = FakeRunner()
    f = DashboardFacade(tmp_path, runner)
    f._settings = replace(Settings(), skills=[])
    res = json.loads(f.start_run(json.dumps({"mode_id": "normal_farm"})))
    assert res["ok"] is False
    assert "技能" in res["error"]
    assert runner.start_calls == []


def test_unknown_mode_blocks_before_runner(facade):
    res = json.loads(facade.start_run(json.dumps({"mode_id": "no_such_mode"})))
    assert res["ok"] is False
    assert facade.runner.start_calls == []


def test_live_lock_busy_blocks_before_runner(qapp, tmp_path: Path):
    runner = FakeRunner()
    f = DashboardFacade(tmp_path, runner)
    lock_dir = live_lock_path(tmp_path).parent
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(live_lock_path(tmp_path)))
    assert lock.tryLock(0)
    try:
        res = json.loads(f.start_run(json.dumps({"mode_id": "normal_farm"})))
        assert res["ok"] is False
        assert "live.lock" in res["error"]
        assert runner.start_calls == []
    finally:
        lock.unlock()


def test_already_running_error_surfaces(qapp, tmp_path: Path):
    runner = FakeRunner(error=RuntimeError("already running"))
    f = DashboardFacade(tmp_path, runner)
    res = json.loads(f.start_run(json.dumps({"mode_id": "normal_farm"})))
    assert res["ok"] is False
    assert "already running" in res["error"]


def test_mode_not_enabled_error_surfaces(qapp, tmp_path: Path):
    runner = FakeRunner(error=ModeNotEnabled("follow_team 未验证"))
    f = DashboardFacade(tmp_path, runner)
    res = json.loads(f.start_run(json.dumps({"mode_id": "follow_team"})))
    assert res["ok"] is False
    assert "未验证" in res["error"]


def test_default_construction_without_root_fails_closed(qapp, tmp_path: Path):
    f = DashboardFacade(tmp_path)
    res = json.loads(f.start_run(json.dumps({"mode_id": "normal_farm"})))
    assert res["ok"] is False
    res2 = json.loads(f.stop_run())
    assert res2["ok"] is False


def test_stop_run_while_idle_keeps_state_idle(qapp, tmp_path: Path):
    runner = FakeRunner()
    f = DashboardFacade(tmp_path, runner)
    assert json.loads(f.get_snapshot())["run"]["state"] == "IDLE"
    res = json.loads(f.stop_run())
    assert res["ok"] is True
    assert runner.stop_calls == 0
    assert runner.runner_state == "IDLE"
    assert json.loads(f.get_snapshot())["run"]["state"] == "IDLE"

# ---------------------------------------------------------------- 信号桥


def test_worker_signals_forward_to_facade(qapp, tmp_path: Path):
    runner = FakeRunner()
    f = DashboardFacade(tmp_path, runner)
    assert json.loads(f.start_run(json.dumps({"mode_id": "normal_farm"})))["ok"]

    logs: list[tuple[str, str]] = []
    statuses: list[dict] = []
    f.log_appended.connect(lambda t, k: logs.append((t, k)))
    f.run_status_changed.connect(lambda js: statuses.append(json.loads(js)))

    worker = runner.worker
    worker.signals.log_emitted.emit("[启动] scripted", "info")
    worker.signals.status_updated.emit(True, "FIGHT", 3, "", "识别中", "拾取掉落")
    _drain(qapp)

    assert logs == [("[启动] scripted", "info")]
    st = statuses[-1]
    assert st["state"] == "RUNNING"
    assert st["phase"] == "FIGHT"
    assert st["game_count"] == 3
    assert st["ocr_status"] == "识别中"
    assert st["last_action"] == "拾取掉落"


def test_duplicate_status_payload_suppressed(qapp, tmp_path: Path):
    runner = FakeRunner()
    f = DashboardFacade(tmp_path, runner)
    f.start_run(json.dumps({"mode_id": "normal_farm"}))
    statuses: list[str] = []
    f.run_status_changed.connect(statuses.append)
    worker = runner.worker
    worker.signals.status_updated.emit(True, "FIGHT", 1, "", "", "")
    _drain(qapp)
    n = len(statuses)
    worker.signals.status_updated.emit(True, "FIGHT", 1, "", "", "")
    _drain(qapp)
    assert len(statuses) == n, "完全相同的状态不得重复回传"


def test_worker_finished_releases_and_reports_idle(qapp, tmp_path: Path):
    runner = FakeRunner()
    f = DashboardFacade(tmp_path, runner)
    f.start_run(json.dumps({"mode_id": "normal_farm"}))
    statuses: list[dict] = []
    f.run_status_changed.connect(lambda js: statuses.append(json.loads(js)))

    runner.worker.finished.emit()
    _drain(qapp)

    assert runner.released == 1
    assert runner.runner_state == "IDLE"
    assert statuses[-1]["state"] == "IDLE"


# ---------------------------------------------------------------- stop_run


def test_stop_run_calls_runner_stop_when_running(facade):
    facade.start_run(json.dumps({"mode_id": "normal_farm"}))
    assert json.loads(facade.stop_run())["ok"] is True
    assert facade.runner.stop_calls == 1


def test_stop_run_idempotent_while_idle(facade):
    assert json.loads(facade.stop_run())["ok"] is True
    assert json.loads(facade.stop_run())["ok"] is True
    assert facade.runner.stop_calls == 0

# ---------------------------------------------------------------- 真实 RunnerService


class ScriptedWorker(QThread):
    """真实 RunnerService.start() 创建的受控 worker：阻塞直到被 stop。"""

    def __init__(self, settings, root_dir, max_steps=None,
                 incident_dir=None, stop_signal=None):
        super().__init__()
        self.signals = LogSignal()
        self.settings = settings
        self.root_dir = root_dir
        self.stop_signal = stop_signal
        self.mediator = None
        self.phase = "IDLE"
        self.terminal_reason = ""
        self.ocr_status = ""
        self.last_action = ""
        self._release = threading.Event()

    def stop(self) -> None:
        self._release.set()

    def run(self) -> None:
        self.signals.log_emitted.emit("[启动] scripted live", "info")
        self.signals.status_updated.emit(True, "STARTING", 0, "", "启动中", "")
        while not self._release.wait(timeout=0.02):
            pass
        self.phase = "COMPLETE"
        self.terminal_reason = "已完成指定局数"
        self.ocr_status = "完成"
        self.signals.status_updated.emit(
            False, self.phase, 1, self.terminal_reason, self.ocr_status, "")
        self.signals.log_emitted.emit("[结束] 任务运行结束", "info")



@pytest.fixture()
def real_facade(qapp, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(rs_module, "MediatorWorker", ScriptedWorker)
    runner = RunnerService(tmp_path, tmp_path)
    f = DashboardFacade(tmp_path, runner)
    f.runner = runner
    logs: list[tuple[str, str]] = []
    statuses: list[dict] = []
    f.log_appended.connect(lambda t, k: logs.append((t, k)))
    f.run_status_changed.connect(lambda js: statuses.append(json.loads(js)))
    f.logs = logs
    f.statuses = statuses
    return f


def _wait_worker_done(qapp, worker, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and worker.isRunning():
        qapp.processEvents()
        time.sleep(0.01)
    for _ in range(20):
        qapp.processEvents()
        if not worker.isRunning():
            break
        time.sleep(0.01)


def test_real_runner_full_lifecycle(qapp, real_facade):
    f = real_facade
    runner = f.runner

    res = json.loads(f.start_run(json.dumps({"mode_id": "normal_farm"})))
    assert res["ok"] is True
    assert runner.runner_state == "RUNNING"
    assert runner.mode_id == "normal_farm"
    assert live_lock_busy(runner.app_data), "运行期间 live.lock 必须被占用"

    worker = runner.worker
    assert isinstance(worker, ScriptedWorker)
    _drain(qapp)
    assert any("[启动]" in t for t, _ in f.logs) or runner.runner_state in ("RUNNING", "STOPPING")

    # stop_run：只触发停止，状态进入 STOPPING，由结束链回 IDLE。
    assert json.loads(f.stop_run())["ok"] is True
    assert runner.runner_state == "STOPPING"

    _wait_worker_done(qapp, worker)
    assert not worker.isRunning()
    assert runner.runner_state == "IDLE", "worker 结束必须经 release_after_finish 回 IDLE"
    assert not live_lock_busy(runner.app_data), "结束后 live.lock 必须释放"

    last = f.statuses[-1]
    assert last["state"] == "IDLE"
    assert last["terminal_reason"] == "已完成指定局数"
    assert any(k == "info" and t.startswith("[结束]") for t, k in f.logs)


def test_real_runner_snapshot_reflects_running(qapp, real_facade):
    f = real_facade
    runner = f.runner
    f.start_run(json.dumps({"mode_id": "normal_farm"}))
    try:
        run = json.loads(f.get_snapshot())["run"]
        assert run["state"] == "RUNNING"
        assert run["mode_id"] == "normal_farm"
    finally:
        f.stop_run()
        _wait_worker_done(qapp, runner.worker)


def test_runner_start_failure_releases_live_lock(tmp_path: Path, monkeypatch):
    class BrokenWorker:
        def __init__(self, *_args, **_kwargs) -> None:
            raise RuntimeError("worker construction failed")

    monkeypatch.setattr(rs_module, "MediatorWorker", BrokenWorker)
    runner = RunnerService(tmp_path, tmp_path)

    with pytest.raises(RuntimeError, match="worker construction failed"):
        runner.start("normal_farm", Settings())

    assert runner.runner_state == "IDLE"
    assert runner.worker is None
    assert not live_lock_busy(runner.app_data)


def test_runner_preserves_disabled_ocr_for_template_mode(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(rs_module, "MediatorWorker", ScriptedWorker)
    runner = RunnerService(tmp_path, tmp_path)
    worker = runner.start("normal_farm", Settings(ocr_mode="off"))

    try:
        assert worker.settings.ocr_mode == "off"
    finally:
        runner.release_after_finish()


def test_runner_releases_lock_when_worker_finishes_without_facade(qapp, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(rs_module, "MediatorWorker", ScriptedWorker)
    runner = RunnerService(tmp_path, tmp_path)
    worker = runner.start("normal_farm", Settings())
    worker.start()

    try:
        worker.stop()
        _wait_worker_done(qapp, worker)
        assert runner.runner_state == "IDLE"
        assert not live_lock_busy(runner.app_data)
    finally:
        runner.release_after_finish()


def test_runner_stop_timeout_waits_for_worker_cleanup(qapp, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(rs_module, "MediatorWorker", ScriptedWorker)
    runner = RunnerService(tmp_path, tmp_path)
    worker = runner.start("normal_farm", Settings())
    worker.start()

    runner.stop(timeout_ms=1_000)
    _wait_worker_done(qapp, worker)

    assert not worker.isRunning()
    assert runner.runner_state == "IDLE"
    assert not live_lock_busy(runner.app_data)
