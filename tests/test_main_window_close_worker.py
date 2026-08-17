"""closeEvent 与运行中 worker 的边界安全测试。

背景：worker 卡死时 closeEvent 先 wait(15s) 再 wait(60s)，若仍未退出，
旧实现继续 release_after_finish()（释放 ShuaBao.live.lock）并 event.accept()，
窗口关闭但 worker 还活着——锁被提前释放，第二个实例可入场抢同一 LIVE。
要求：等待完成后 worker 仍运行 → event.ignore()、不 release_after_finish、
保留 live.lock、不强杀线程；只有 worker 已停止才释放并 accept。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QLockFile  # noqa: E402
from PySide6.QtGui import QCloseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gamescript.shell.main_window import MainWindow  # noqa: E402
from gamescript.shell.runner_service import live_lock_path  # noqa: E402
from gamescript.shell.runtime_status import RUNNER_IDLE  # noqa: E402


class _StuckWorker:
    """worker 永不退出：isRunning 恒真，wait 恒失败。"""

    def isRunning(self):
        return True

    def wait(self, timeout_ms):
        return False


class _StoppedWorker:
    """worker 已停止：isRunning 恒假。"""

    def isRunning(self):
        return False

    def wait(self, timeout_ms):
        return True


class _WaitsThenStopsWorker:
    """worker 在第一次等待窗口内退出：wait 成功后 isRunning 变假。"""

    def __init__(self):
        self._stopped = False

    def isRunning(self):
        return not self._stopped

    def wait(self, timeout_ms):
        self._stopped = True
        return True


class MainWindowCloseWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app_data = Path(self.tmp.name)
        self.window = MainWindow(app_data=self.app_data)
        self.window.log = Mock()

    def tearDown(self):
        # 先摘掉 worker，避免 close 触发真实 75s 等待
        self.window.worker_thread = None
        try:
            self.window.close()
        finally:
            self.tmp.cleanup()

    def _hold_lock(self) -> QLockFile:
        lock = QLockFile(str(live_lock_path(self.app_data)))
        self.assertTrue(lock.tryLock(100), "测试前置：live.lock 必须可占用")
        self.window.runner._live_lock = lock
        return lock

    def test_worker_still_running_close_is_ignored_lock_kept_no_release(self):
        self.window.worker_thread = _StuckWorker()
        lock = self._hold_lock()
        with patch.object(self.window.runner, "stop") as stop_mock, \
             patch.object(self.window.runner, "release_after_finish") as release_mock:
            event = QCloseEvent()
            self.window.closeEvent(event)
            self.assertFalse(event.isAccepted(), "worker 仍在运行时必须 event.ignore()")
            stop_mock.assert_called_once()
            release_mock.assert_not_called()
            self.assertIs(self.window.runner._live_lock, lock, "live.lock 必须保留")
            self.assertTrue(lock.isLocked(), "live.lock 文件必须仍被占用")
            self.assertIsNotNone(self.window.worker_thread, "不得清理 worker 引用")

    def test_worker_stopped_close_is_accepted_lock_released(self):
        self.window.worker_thread = _StoppedWorker()
        lock = self._hold_lock()
        with patch.object(self.window.runner, "stop") as stop_mock, \
             patch.object(self.window.runner, "release_after_finish") as release_mock, \
             patch.object(self.window, "_write_user_bundle") as write_mock:
            event = QCloseEvent()
            self.window.closeEvent(event)
            self.assertTrue(event.isAccepted())
            stop_mock.assert_not_called()
            release_mock.assert_called_once()
            write_mock.assert_called_once()

    def test_worker_exits_during_wait_close_is_accepted_lock_released(self):
        self.window.worker_thread = _WaitsThenStopsWorker()
        lock = self._hold_lock()
        with patch.object(self.window.runner, "stop") as stop_mock, \
             patch.object(self.window.runner, "release_after_finish") as release_mock, \
             patch.object(self.window, "_write_user_bundle") as write_mock:
            event = QCloseEvent()
            self.window.closeEvent(event)
            self.assertTrue(event.isAccepted())
            stop_mock.assert_called_once()
            release_mock.assert_called_once()
            write_mock.assert_called_once()

    def test_no_worker_close_is_accepted(self):
        with patch.object(self.window.runner, "release_after_finish") as release_mock, \
             patch.object(self.window, "_write_user_bundle") as write_mock:
            event = QCloseEvent()
            self.window.closeEvent(event)
            self.assertTrue(event.isAccepted())
            release_mock.assert_called_once()
            write_mock.assert_called_once()


class MainWindowCloseNormalStopTests(unittest.TestCase):
    """正常停止后 closeEvent accept 的锁释放与 queued finished 幂等性。

    用真实 RunnerService/QLockFile（不 mock release_after_finish）证明：
    - worker 已停止 → closeEvent accept 后 live.lock 文件已释放；
    - 随后 worker 的 finished 信号（queued）触发 _on_worker_finished 时
      不会重复破坏状态：锁不重现占用、runner 状态保持 IDLE。
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app_data = Path(self.tmp.name)
        self.window = MainWindow(app_data=self.app_data)
        self.window.log = Mock()

    def tearDown(self):
        self.window.worker_thread = None
        try:
            self.window.close()
        finally:
            self.tmp.cleanup()

    def _hold_lock(self) -> QLockFile:
        lock = QLockFile(str(live_lock_path(self.app_data)))
        self.assertTrue(lock.tryLock(100), "测试前置：live.lock 必须可占用")
        self.window.runner._live_lock = lock
        return lock

    def test_worker_stopped_close_accept_releases_live_lock(self):
        self.window.worker_thread = _StoppedWorker()
        lock = self._hold_lock()
        with patch.object(self.window, "_write_user_bundle") as write_mock:
            event = QCloseEvent()
            self.window.closeEvent(event)
            self.assertTrue(event.isAccepted(), "worker 已停止时 closeEvent 必须 accept")
            write_mock.assert_called_once()
        self.assertFalse(lock.isLocked(), "closeEvent accept 后 live.lock 必须已释放")
        self.assertIsNone(self.window.runner._live_lock, "runner 不得再持有锁引用")
        self.assertEqual(RUNNER_IDLE, self.window.runner.runner_state)

    def test_queued_worker_finished_after_close_is_idempotent(self):
        self.window.worker_thread = _StoppedWorker()
        self.window.worker_thread.mediator = None
        lock = self._hold_lock()
        with patch.object(self.window, "_write_user_bundle"):
            event = QCloseEvent()
            self.window.closeEvent(event)
            self.assertTrue(event.isAccepted())
        # worker 的 finished 信号已在关闭流程中排队，close 之后才投递
        self.window._on_worker_finished()
        self.assertFalse(lock.isLocked(), "queued finished 不得重新占用/破坏 live.lock")
        self.assertIsNone(self.window.runner._live_lock)
        self.assertEqual(RUNNER_IDLE, self.window.runner.runner_state)
        self.assertIsNone(self.window.worker_thread, "queued finished 仍应清理 worker 引用")

    def test_worker_finished_then_close_event_lock_stays_released(self):
        # 反序：finished 先到（正常停止），随后 closeEvent —— 同样不得重现占用
        self.window.worker_thread = _StoppedWorker()
        self.window.worker_thread.mediator = None
        lock = self._hold_lock()
        with patch.object(self.window, "_write_user_bundle"):
            self.window._on_worker_finished()
            event = QCloseEvent()
            self.window.closeEvent(event)
            self.assertTrue(event.isAccepted())
        self.assertFalse(lock.isLocked(), "两次释放路径后 live.lock 必须仍处于释放状态")
        self.assertIsNone(self.window.runner._live_lock)
        self.assertEqual(RUNNER_IDLE, self.window.runner.runner_state)


if __name__ == "__main__":
    unittest.main()
