"""Versioned DashboardFacade ↔ Web bridge contract."""

from __future__ import annotations


# Increment whenever a method, DTO shape, or required signal changes in a way
# that an older bundle cannot safely consume.
BRIDGE_SCHEMA_VERSION = 2

BRIDGE_REQUIRED_METHODS = (
    "get_snapshot",
    "update_config",
    "update_shell",
    "validate_preflight",
    "start_run",
    "stop_run",
    "window_control",
    "set_window_layout",
    "activate_subscription",
    "get_bridge_info",
)

BRIDGE_REQUIRED_SIGNALS = (
    "snapshot_changed",
    "run_status_changed",
    "log_appended",
)


__all__ = [
    "BRIDGE_SCHEMA_VERSION",
    "BRIDGE_REQUIRED_METHODS",
    "BRIDGE_REQUIRED_SIGNALS",
]
