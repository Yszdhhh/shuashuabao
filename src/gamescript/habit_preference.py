"""本地习惯权重（免订阅）：加载 + 转成 PolicySettings.habit_name_scores。

不读屏、不点击。未接线桌面 UI / mediator 自动采集前，可由测试或手工 JSON 喂入。
硬约束：分数只影响允许集合内的并列排序，见 choice_policy._match_preset。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

VALID_PANELS = frozenset({"skill", "bond", "treasure"})


def default_habit_path() -> Path:
    import os

    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "GameScript-Local" / "habit_preference.json"


def load_habit_preference(path: Path | None = None) -> dict[str, Any]:
    """读取习惯文件；缺失则返回空骨架（不抛）。"""
    target = path or default_habit_path()
    if not target.is_file():
        return {"version": 1, "updated_at": "", "panels": {}}
    raw = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"habit preference must be object: {target}")
    return raw


def habit_scores_for_panel(
    habit: Mapping[str, Any] | None, panel: str
) -> tuple[tuple[str, float], ...]:
    """抽出某一面板的 name_scores，供 PolicySettings.habit_name_scores 使用。"""
    if not habit or panel not in VALID_PANELS:
        return ()
    panels = habit.get("panels") or {}
    block = panels.get(panel) or {}
    scores = block.get("name_scores") or {}
    if not isinstance(scores, Mapping):
        return ()
    out: list[tuple[str, float]] = []
    for name, value in scores.items():
        try:
            out.append((str(name), float(value)))
        except (TypeError, ValueError):
            continue
    return tuple(out)


def merge_habit_into_mapping(
    policy_mapping: Mapping[str, Any],
    habit: Mapping[str, Any] | None,
    panel: str,
) -> dict[str, Any]:
    """复制 policy 映射并注入当前面板习惯分（纯函数，不改入参）。"""
    merged = dict(policy_mapping)
    merged["habit_name_scores"] = dict(habit_scores_for_panel(habit, panel))
    return merged
