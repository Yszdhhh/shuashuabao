"""外壳用运行快照。进度只认有界量测，不画 phase 下标百分比。"""

from __future__ import annotations

from dataclasses import dataclass

try:
    from shuabao.runtime_status import RuntimeStatus, runtime_status_from_mediator
except ImportError:  # Infra 的快照模块尚未入仓时，外壳仍能显示局数
    RuntimeStatus = None  # type: ignore[misc,assignment]
    runtime_status_from_mediator = None  # type: ignore[misc,assignment]

RUNNER_IDLE = "IDLE"
RUNNER_STARTING = "STARTING"
RUNNER_RUNNING = "RUNNING"
RUNNER_STOPPING = "STOPPING"
RUNNER_COMPLETE = "COMPLETE"
RUNNER_FAILED = "FAILED"


@dataclass(frozen=True)
class ShellProgress:
    """三种合法进度：局数比 / 已完成数字 / 无条。禁止全局百分比。"""

    kind: str  # ratio | count | none
    game_count: int
    cycle_num: int
    label: str


def progress_from_counts(game_count: int, cycle_num: int, *, running: bool) -> ShellProgress:
    count = max(0, int(game_count or 0))
    cycle = max(0, int(cycle_num or 0))
    if not running and count <= 0 and cycle <= 0:
        return ShellProgress("none", 0, 0, "空闲")
    if cycle > 0:
        return ShellProgress("ratio", count, cycle, f"第 {count} / {cycle} 局")
    return ShellProgress("count", count, 0, f"已完成 {count} 局")


__all__ = [
    "RUNNER_COMPLETE",
    "RUNNER_FAILED",
    "RUNNER_IDLE",
    "RUNNER_RUNNING",
    "RUNNER_STARTING",
    "RUNNER_STOPPING",
    "RuntimeStatus",
    "ShellProgress",
    "progress_from_counts",
    "runtime_status_from_mediator",
]
