"""Attributed active endings for a production run.

Legal hitch soak terminals are the five product reasons. Non-hitch fail-closed
stops stay attributable via FAIL_CLOSED so a hitch run cannot newly die on an
optional-step failure, and every stop/Break remains inspectable.
"""

from __future__ import annotations

from enum import Enum


class RunExitReason(str, Enum):
    USER_STOP = "USER_STOP"
    EMERGENCY_STOP = "EMERGENCY_STOP"
    CONFIGURED_CYCLE_COMPLETE = "CONFIGURED_CYCLE_COMPLETE"
    UIPI_FATAL = "UIPI"
    UNRECOVERABLE_CRASH = "UNRECOVERABLE_CRASH"
    # Non-hitch Fail-Closed. Not a hitch legal soak terminal.
    FAIL_CLOSED = "FAIL_CLOSED"


LEGAL_HITCH_TERMINALS = frozenset(
    {
        RunExitReason.USER_STOP,
        RunExitReason.EMERGENCY_STOP,
        RunExitReason.CONFIGURED_CYCLE_COMPLETE,
        RunExitReason.UIPI_FATAL,
        RunExitReason.UNRECOVERABLE_CRASH,
    }
)


def coerce_run_exit_reason(value: RunExitReason | str | None) -> RunExitReason | None:
    if value is None:
        return None
    if isinstance(value, RunExitReason):
        return value
    text = str(value).strip()
    if not text:
        return None
    for item in RunExitReason:
        if text == item.value or text == item.name:
            return item
    return classify_stop_signal_reason(text)


def classify_stop_signal_reason(reason: str | None) -> RunExitReason:
    text = str(reason or "").strip()
    lowered = text.lower()
    if not text:
        return RunExitReason.FAIL_CLOSED
    if "shift+f12" in lowered or "emergency stop" in lowered or lowered.startswith("f12"):
        return RunExitReason.EMERGENCY_STOP
    if "uipi" in lowered or "elevation" in lowered or "管理员" in text or "提权" in text:
        return RunExitReason.UIPI_FATAL
    if "cycle_num" in lowered or "configured_cycle" in lowered or "指定局数" in text:
        return RunExitReason.CONFIGURED_CYCLE_COMPLETE
    if (
        "user" in lowered
        or "runner" in lowered
        or "stop requested" in lowered
        or "用户" in text
        or "主动停止" in text
    ):
        return RunExitReason.USER_STOP
    if "crash" in lowered or "unrecoverable" in lowered or "异常退出" in text:
        return RunExitReason.UNRECOVERABLE_CRASH
    return RunExitReason.FAIL_CLOSED


def is_legal_hitch_terminal(reason: RunExitReason | str | None) -> bool:
    coerced = coerce_run_exit_reason(reason)
    return coerced in LEGAL_HITCH_TERMINALS
