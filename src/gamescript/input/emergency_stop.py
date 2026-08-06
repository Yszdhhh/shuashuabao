"""Global Shift+F12 emergency stop listener using Win32 API / ctypes."""

from __future__ import annotations

import threading
import time

from gamescript.stop_signal import StopSignal

VK_SHIFT = 0x10
VK_F12 = 0x7B


def check_key_pressed_win32(vk_code: int) -> bool:
    """Mockable Win32 key press check using GetAsyncKeyState."""
    try:
        import ctypes

        state = ctypes.windll.user32.GetAsyncKeyState(vk_code)
        return bool(state & 0x8000)
    except Exception:
        return False


class EmergencyStopListener:
    """Background listener that monitors Shift+F12 key combination."""

    def __init__(self, stop_signal: StopSignal, poll_interval: float = 0.05) -> None:
        self.stop_signal = stop_signal
        self.poll_interval = poll_interval
        self._running = False
        self._thread: threading.Thread | None = None

    def _poll_loop(self) -> None:
        while self._running:
            if not self.stop_signal.is_set():
                shift_down = check_key_pressed_win32(VK_SHIFT)
                f12_down = check_key_pressed_win32(VK_F12)
                if shift_down and f12_down:
                    print("[emergency_stop] Global Shift+F12 detected! Triggering emergency stop.")
                    self.stop_signal.trigger("Shift+F12 emergency stop")
            time.sleep(self.poll_interval)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="EmergencyStopListener")
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.5)
            self._thread = None
