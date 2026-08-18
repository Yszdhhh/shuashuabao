from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import shuabao.player_profile as profile


class _FakeKernel32:
    def __init__(self, *, exit_code: int = 259, open_ok: bool = True):
        self.exit_code = exit_code
        self.open_ok = open_ok
        self.closed: list[int] = []

    def OpenProcess(self, _access, _inherit, _pid):
        return 123 if self.open_ok else 0

    def GetExitCodeProcess(self, _handle, out_code):
        out_code._obj.value = self.exit_code
        return 1

    def CloseHandle(self, handle):
        self.closed.append(int(handle))
        return 1


class WindowsPidLivenessTests(unittest.TestCase):
    def test_windows_dispatch_never_uses_os_kill(self):
        with patch.object(profile, "_IS_WINDOWS", True), \
                patch.object(profile, "_windows_pid_alive", return_value=True) as probe, \
                patch.object(profile.os, "kill", side_effect=AssertionError("os.kill must not run on Windows")):
            self.assertTrue(profile._pid_alive(123))
        probe.assert_called_once_with(123)

    def test_windows_helper_detects_live_process_and_closes_handle(self):
        api = _FakeKernel32(exit_code=259)
        self.assertTrue(profile._windows_pid_alive(123, api))
        self.assertEqual(api.closed, [123])

    def test_windows_helper_detects_exited_process_and_closes_handle(self):
        api = _FakeKernel32(exit_code=0)
        self.assertFalse(profile._windows_pid_alive(123, api))
        self.assertEqual(api.closed, [123])

    def test_windows_helper_rejects_missing_process(self):
        api = _FakeKernel32(open_ok=False)
        self.assertFalse(profile._windows_pid_alive(123, api))
        self.assertEqual(api.closed, [])

    @unittest.skipUnless(profile.os.name == "nt", "Windows only")
    def test_windows_helper_current_process_is_alive(self):
        self.assertTrue(profile._windows_pid_alive(profile.os.getpid()))

    def test_posix_permission_error_means_process_exists(self):
        with patch.object(profile, "_IS_WINDOWS", False), \
                patch.object(profile.os, "kill", side_effect=PermissionError):
            self.assertTrue(profile._pid_alive(123))


if __name__ == "__main__":
    unittest.main()
