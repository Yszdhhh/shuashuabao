"""看板测试配置：只接受可见运行字段，永不改变学习模式。"""

from __future__ import annotations

import copy
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from gamescript.settings import Settings

SCHEMA_VERSION = 1
PROFILE_MODE_ID = "normal_farm"
# Password is intentionally absent: profile files are shareable test artifacts.
PROFILE_SETTING_FIELDS = frozenset(
    {
        "stage_targets",
        "auto_create_room",
        "room_name",
        "new_room_every_times",
        "cycle_num",
        "auto_reputation",
        "reputation_type",
        "reputation_level",
        "auto_secret_realm",
        "skills",
        "cards",
    }
)
PROFILE_ROOT_FIELDS = frozenset({"schema_version", "name", "mode_id", "settings"})


class TestProfileError(ValueError):
    """A profile crossed the dashboard trust boundary."""

    __test__ = False


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise TestProfileError(message)


def validate_profile_document(document: Any) -> dict[str, Any]:
    _require(isinstance(document, dict), "测试配置必须是 JSON 对象")
    unknown = set(document) - PROFILE_ROOT_FIELDS
    _require(not unknown, f"测试配置含未知字段：{', '.join(sorted(unknown))}")
    _require(document.get("schema_version") == SCHEMA_VERSION, "不支持的 schema_version")
    _require(isinstance(document.get("name"), str) and document["name"].strip(), "测试配置缺少 name")
    _require(document.get("mode_id") == PROFILE_MODE_ID, "测试配置只支持 normal_farm")
    settings = document.get("settings")
    _require(isinstance(settings, dict), "测试配置的 settings 必须是对象")
    unknown_settings = set(settings) - PROFILE_SETTING_FIELDS
    _require(not unknown_settings, f"测试配置含禁止或未知 settings 字段：{', '.join(sorted(unknown_settings))}")
    _require("stage_targets" in settings, "测试配置必须指定 stage_targets")
    _require(
        isinstance(settings["stage_targets"], list)
        and all(isinstance(item, str) and item.strip() for item in settings["stage_targets"]),
        "stage_targets 必须是非空字符串数组",
    )
    for key in ("auto_create_room", "new_room_every_times", "auto_reputation", "auto_secret_realm"):
        if key in settings:
            _require(isinstance(settings[key], bool), f"{key} 必须是布尔值")
    for key in ("cycle_num", "reputation_type", "reputation_level"):
        if key in settings:
            _require(isinstance(settings[key], int) and not isinstance(settings[key], bool), f"{key} 必须是整数")
    for key in ("room_name",):
        if key in settings:
            _require(isinstance(settings[key], str), f"{key} 必须是字符串")
    for key in ("skills", "cards"):
        if key in settings:
            _require(isinstance(settings[key], list) and all(isinstance(item, str) for item in settings[key]), f"{key} 必须是字符串数组")
    return copy.deepcopy(document)


def load_test_profiles(path: str | Path) -> list[dict[str, Any]]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    _require(isinstance(raw, dict) and isinstance(raw.get("profiles"), list), "内置测试配置格式错误")
    return [validate_profile_document(item) for item in raw["profiles"]]


def apply_profile(settings: Settings, document: Any) -> Settings:
    profile = validate_profile_document(document)
    updated = copy.deepcopy(settings)
    for key, value in profile["settings"].items():
        setattr(updated, key, copy.deepcopy(value))
    # stage1/stage2 are legacy fields; retain the UI's existing parsing quirk.
    first = updated.stage_targets[0]
    try:
        updated.stage1, updated.stage2 = (int(part) for part in first.split("-", 1))
    except (TypeError, ValueError):
        pass
    return updated


def export_profile(settings: Settings, name: str = "当前看板配置") -> dict[str, Any]:
    raw = asdict(settings)
    selected = {key: copy.deepcopy(raw[key]) for key in PROFILE_SETTING_FIELDS if key in raw}
    return {
        "schema_version": SCHEMA_VERSION,
        "name": name,
        "mode_id": PROFILE_MODE_ID,
        "settings": selected,
    }


def profile_diff(before: Settings, after: Settings) -> dict[str, tuple[Any, Any]]:
    old, new = asdict(before), asdict(after)
    return {
        key: (old[key], new[key])
        for key in PROFILE_SETTING_FIELDS
        if old.get(key) != new.get(key)
    }
