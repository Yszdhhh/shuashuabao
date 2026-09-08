"""左栏运行方式目录。只读 config/mode_specs.json，不改 live_enabled。"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import Any

from shuabao.settings import Settings

# PyInstaller keeps config under _MEIPASS; source runs still use the repository root.
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))
SPECS_PATH = ROOT / "config" / "mode_specs.json"
PERSIST_DENYLIST = frozenset({"lab_focus"})

MODE_ORDER = (
    "normal_farm",
    "follow_team",
    "gambling_wood",
    "raid_wait",
    "lobby_hitch",
    "lab",
)


@dataclass(frozen=True)
class ModeSpec:
    id: str
    label: str
    live_enabled: bool
    desktop_start: bool
    flow: str
    visible_settings: tuple[str, ...]
    hidden_defaults: dict[str, Any]
    forbidden_actions: tuple[str, ...]
    budgets: dict[str, Any]
    evidence_status: str
    notes: str = ""


_CACHE: dict[str, ModeSpec] | None = None
_SETTINGS_FIELDS = {f.name for f in fields(Settings)}


def load_specs() -> dict[str, ModeSpec]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    raw = json.loads(SPECS_PATH.read_text(encoding="utf-8"))
    out: dict[str, ModeSpec] = {}
    for mode_id, item in (raw.get("modes") or {}).items():
        out[mode_id] = ModeSpec(
            id=str(item["id"]),
            label=str(item["label"]),
            live_enabled=bool(item["live_enabled"]),
            desktop_start=bool(item["desktop_start"]),
            flow=str(item.get("flow") or ""),
            visible_settings=tuple(item.get("visible_settings") or ()),
            hidden_defaults=dict(item.get("hidden_defaults") or {}),
            forbidden_actions=tuple(item.get("forbidden_actions") or ()),
            budgets=dict(item.get("budgets") or {}),
            evidence_status=str(item.get("evidence_status") or ""),
            notes=str(item.get("notes") or ""),
        )
    _CACHE = out
    return out


def get_spec(mode_id: str) -> ModeSpec:
    specs = load_specs()
    if mode_id not in specs:
        raise KeyError(f"unknown mode: {mode_id}")
    return specs[mode_id]


def iter_specs() -> list[ModeSpec]:
    specs = load_specs()
    out = [specs[mode_id] for mode_id in MODE_ORDER if mode_id in specs]
    for mode_id, spec in specs.items():
        if mode_id not in MODE_ORDER:
            out.append(spec)
    return out


def desktop_may_start(mode_id: str) -> bool:
    spec = get_spec(mode_id)
    return bool(spec.live_enabled and spec.desktop_start)


def apply_mode_overlay(settings: Settings, mode_id: str) -> Settings:
    spec = get_spec(mode_id)
    # budgets 与 hidden_defaults 都消费，但只接受真实 Settings 字段（未知键忽略）；
    # 同键冲突时 hidden_defaults 优先（显式默认压过预算推导）。
    merged: dict[str, Any] = {}
    for source in (spec.budgets, spec.hidden_defaults):
        for k, v in source.items():
            if k in _SETTINGS_FIELDS:
                merged[k] = v
    out = Settings._from_dict(merged, fallback=settings)
    # 目录 id 不是 overlay 键：始终盖上，供 Mediator 分支 hitch / 面板 Fail-Closed。
    return replace(out, mode_id=str(mode_id))


def collect_persistable_settings(settings: Settings) -> dict[str, Any]:
    data = asdict(settings)
    for key in PERSIST_DENYLIST:
        data.pop(key, None)
    return data


def badge_text(spec: ModeSpec) -> str:
    if spec.id == "lab":
        return "CLI"
    if desktop_may_start(spec.id):
        return "可启动"
    return "待验证 · 不可启动"


def start_button_text(spec: ModeSpec, *, running: bool) -> str:
    if running:
        return "停止运行"
    if desktop_may_start(spec.id):
        return "开始运行"
    return "待验证 · 不可启动"


def action_is_forbidden(reason: str, forbidden: tuple[str, ...] | list[str] | None) -> bool:
    """Click-time guard. RoomStart-retry counts as RoomStart; unknown keys stay closed."""
    reason = str(reason or "").strip()
    if not reason or not forbidden:
        return False
    low = reason.lower()
    for item in forbidden:
        token = str(item or "").strip()
        if not token:
            continue
        tlow = token.lower()
        if low == tlow:
            return True
        if low.startswith(tlow + "-") or low.startswith(tlow + ".") or low.startswith(tlow + "_"):
            return True
    return False


def hitch_refresh_window() -> tuple[float, float]:
    spec = get_spec("lobby_hitch")
    lo = float(spec.budgets.get("refresh_s_min", 5) or 5)
    hi = float(spec.budgets.get("refresh_s_max", 5) or 5)
    if lo > hi:
        lo, hi = hi, lo
    return max(0.0, lo), max(lo, hi)
