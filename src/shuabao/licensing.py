"""订阅租约 stub（fail-closed）。未接入 LIVE / mediator。

规格见 docs/research/DISTRIBUTION_AND_IP_PLAN_20260812.md。
本模块只回答「此刻是否允许 LIVE」；识别与点击仍在本机其它模块。
"""

from __future__ import annotations

import hashlib
import os
import platform
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class Lease:
    """本地缓存的有期限授权。"""

    machine_id: str
    expires_at: float  # unix seconds
    entitled: bool = True
    issuer: str = "local-stub"


def machine_id() -> str:
    """稳定机器指纹（非加密强度；防随手拷贝够用）。"""
    raw = "|".join(
        [
            platform.node(),
            platform.system(),
            os.environ.get("COMPUTERNAME", ""),
            os.environ.get("USERNAME", ""),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:32]


def evaluate_lease(
    lease: Lease | None,
    *,
    now: float | None = None,
    expected_machine_id: str | None = None,
    grace_seconds: float = 0.0,
) -> bool:
    """是否允许 LIVE。

    规则：
    - lease 缺失 / entitled=False → False
    - 机器码不匹配 → False
    - now > expires_at + grace → False
    - 否则 True
    """
    if lease is None or not lease.entitled:
        return False
    mid = expected_machine_id or machine_id()
    if lease.machine_id != mid:
        return False
    clock = time.time() if now is None else float(now)
    return clock <= float(lease.expires_at) + float(grace_seconds)


def issue_lease(*, days: float = 7.0, now: float | None = None) -> Lease:
    """开发用签发：绑本机，默认 7 天。"""
    clock = time.time() if now is None else float(now)
    return Lease(
        machine_id=machine_id(),
        expires_at=clock + float(days) * 86400.0,
        entitled=True,
    )
