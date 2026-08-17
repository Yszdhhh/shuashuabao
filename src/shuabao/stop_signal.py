"""Unified cancellation and emergency stop signal."""

from __future__ import annotations

import threading


class StopSignal:
    """Shared cancellation signal across Mediator, API, Hotkey, and InputExecutor."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._reason: str = ""

    def trigger(self, reason: str = "Stop requested") -> None:
        self._reason = reason
        self._event.set()

    def is_set(self) -> bool:
        return self._event.is_set()

    def is_stopped(self) -> bool:
        return self._event.is_set()
    @property
    def reason(self) -> str:
        return self._reason

    def reset(self) -> None:
        self._reason = ""
        self._event.clear()
