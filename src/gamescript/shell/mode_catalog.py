"""左栏运行方式目录。只读 config/mode_specs.json，不改 live_enabled。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import Any

from gamescript.settings import Settings

ROOT = Path(__file__).resolve().parents[3]
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


def _is_overlay_value_accepted(k: str, v: Any, parsed_v: Any) -> bool:
    default_v = getattr(Settings(), k)
    if parsed_v != default_v or v == default_v:
        return True
    if isinstance(v, (bool, int, float, list, dict)):
        return True
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("1", "true", "yes", "on", "0", "false", "no", "off", ""):
            return True
        try:
            if int(s) == parsed_v or float(s) == parsed_v:
                return True
        except (ValueError, TypeError):
            pass
    return False


def apply_mode_overlay(settings: Settings, mode_id: str) -> Settings:
    spec = get_spec(mode_id)
    # budgets 与 hidden_defaults 都消费，但只接受真实 Settings 字段（未知键忽略）；
    # 同键冲突时 hidden_defaults 优先（显式默认压过预算推导）。
    merged: dict[str, Any] = {}
    for source in (spec.budgets, spec.hidden_defaults):
        for k, v in source.items():
            if k in _SETTINGS_FIELDS:
                merged[k] = v
    # 复用 Settings._from_dict 的清洗语义（类型强制、区间钳制、损坏值回落），但只对
    # overlay 命名字段生效：每个键在最小 payload 中清洗后再 replace 仅这些键。
    # 绝不把整个 asdict 重清洗一遍——那会改到 overlay 没碰的字段（如 stage1=0 → 1）。
    # 损坏值在 _from_dict 中会被 pop，回落 dataclass 默认值；此时不得用默认值覆盖 base。
    cleaned: dict[str, Any] = {}
    for k, v in merged.items():
        parsed_v = getattr(Settings._from_dict({k: v}), k)
        if _is_overlay_value_accepted(k, v, parsed_v):
            cleaned[k] = parsed_v
    return replace(settings, **cleaned)


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
