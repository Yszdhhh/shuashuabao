"""Stable Windows device identity.

Algorithm mirrors Subscription Lab bridge/app/core/fingerprint.py —
provides a stable SHA-256 combined hardware fingerprint from machine-level
attributes. No raw hardware data is logged; only the hex digest.

Server has final authority on device binding; this is a best-effort client hint.
"""
from __future__ import annotations

import hashlib
import logging
import os
import platform
import subprocess

_LOG = logging.getLogger(__name__)


def _windows_reg_value(key_path: str, value_name: str) -> str:
    """Read a single string from Windows registry; empty string on failure."""
    try:
        output = subprocess.check_output(
            ["reg", "query", key_path, "/v", value_name],
            stderr=subprocess.DEVNULL,
            timeout=2,
        ).decode("utf-8", errors="replace")
        for line in output.splitlines():
            if value_name in line:
                parts = line.strip().split(None, 2)
                if len(parts) == 3:
                    return parts[2].strip()
    except Exception:
        pass
    return ""


def _cpu_id() -> str:
    return _windows_reg_value(
        r"HKLM\HARDWARE\DESCRIPTION\System\CentralProcessor\0",
        "ProcessorNameString",
    )


def _machine_guid() -> str:
    return _windows_reg_value(
        r"HKLM\SOFTWARE\Microsoft\Cryptography",
        "MachineGuid",
    )


def _disk_serial() -> str:
    try:
        out = subprocess.check_output(
            ["wmic", "diskdrive", "get", "SerialNumber"],
            stderr=subprocess.DEVNULL,
            timeout=3,
        ).decode("utf-8", errors="replace")
        lines = [l.strip() for l in out.splitlines() if l.strip() and "SerialNumber" not in l]
        return lines[0] if lines else ""
    except Exception:
        return ""


def device_fingerprint() -> dict[str, str]:
    """Return component map + combined fingerprint hash.

    Returns dict with keys: fingerprint, hostname, cpu, machine_guid, disk_serial, platform.
    Raw hardware values are kept only in-memory; never written to disk/logs.
    """
    hostname = platform.node()
    cpu = _cpu_id()
    guid = _machine_guid()
    disk = _disk_serial()
    os_name = platform.system()
    username = os.environ.get("USERNAME", "")

    # Same join strategy as Lab machine_id but with more components
    raw = "|".join([hostname, os_name, username, cpu, guid, disk])
    combined = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()

    components: dict[str, str] = {}
    # Only non-empty components contribute — matches Lab's FingerprintMatcher MATCH_MOST logic
    if cpu:
        components["cpu"] = hashlib.sha256(cpu.encode()).hexdigest()[:16]
    if guid:
        components["machine_guid"] = hashlib.sha256(guid.encode()).hexdigest()[:16]
    if disk:
        components["disk_serial"] = hashlib.sha256(disk.encode()).hexdigest()[:16]
    if hostname:
        components["hostname"] = hashlib.sha256(hostname.encode()).hexdigest()[:16]

    # ponytail: no raw cpu/guid/disk in log output
    _LOG.debug("device_fingerprint fingerprint=%s components_count=%d", combined[:8] + "…", len(components))
    return {
        "fingerprint": combined,
        "platform": os_name.lower(),
        "hostname": hostname,
        **{k: v for k, v in components.items()},
    }
