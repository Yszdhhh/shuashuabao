"""看板测试配置：只接受可见运行字段，永不改变学习模式。"""

from __future__ import annotations

import copy
import json
import re
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
        "treasure_allow_negative",
    }
)
PROFILE_ROOT_FIELDS = frozenset({"schema_version", "name", "mode_id", "settings"})
MAINLINE_STAGE_MAX = {1: 23, 2: 7, 3: 9, 4: 3}


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
    targets = settings["stage_targets"]
    _require(isinstance(targets, list) and len(targets) == 1 and isinstance(targets[0], str), "stage_targets 必须恰好含一个关卡")
    match = re.fullmatch(r"([1-9]\d*)-([1-9]\d*)", targets[0])
    _require(match is not None, "stage_targets 必须是“章节-关卡”正整数格式")
    chapter, stage = (int(value) for value in match.groups())
    _require(chapter in MAINLINE_STAGE_MAX and stage <= MAINLINE_STAGE_MAX[chapter], "stage_targets 不在当前主线范围内")
    for key in ("auto_create_room", "new_room_every_times", "auto_reputation", "auto_secret_realm"):
        if key in settings:
            _require(isinstance(settings[key], bool), f"{key} 必须是布尔值")
    for key in ("cycle_num", "reputation_type", "reputation_level"):
        if key in settings:
            _require(isinstance(settings[key], int) and not isinstance(settings[key], bool), f"{key} 必须是整数")
    if "cycle_num" in settings:
        _require(0 <= settings["cycle_num"] <= 999, "cycle_num 必须在 0..999")
    if "reputation_type" in settings:
        _require(1 <= settings["reputation_type"] <= 6, "reputation_type 必须在 1..6")
    if "reputation_level" in settings:
        _require(1 <= settings["reputation_level"] <= 5, "reputation_level 必须在 1..5")
    for key in ("room_name",):
        if key in settings:
            _require(isinstance(settings[key], str), f"{key} 必须是字符串")
    for key in ("skills", "cards"):
        if key in settings:
            _require(isinstance(settings[key], list) and all(isinstance(item, str) for item in settings[key]), f"{key} 必须是字符串数组")
    if "treasure_allow_negative" in settings:
        _require(
            isinstance(settings["treasure_allow_negative"], list)
            and len(settings["treasure_allow_negative"]) == 0,
            "测试配置中的 treasure_allow_negative 仅允许为空数组 []",
        )
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
    updated.stage1 = updated.stage2 = int(first.split("-", 1)[1])
    return updated


def export_profile(settings: Settings, name: str = "当前看板配置") -> dict[str, Any]:
    raw = asdict(settings)
    selected = {key: copy.deepcopy(raw[key]) for key in PROFILE_SETTING_FIELDS if key in raw}
    if "treasure_allow_negative" in selected and selected["treasure_allow_negative"] != []:
        selected["treasure_allow_negative"] = []
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
