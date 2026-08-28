"""本地习惯权重 + 学习模式观测（免订阅）。

- ``habit_preference.json``：允许集合内的 name_scores（tie-break）
- ``learning/*.jsonl``：学习模式（原 dry_run）下的纯观察记录，供后续自适应调参

不读屏、不点击。硬约束：分数只影响允许集合内的并列排序，见 choice_policy._match_preset。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VALID_PANELS = frozenset({"skill", "bond", "treasure", "l0"})


from shuabao.paths import (
    get_canonical_app_data_dir,
    habit_preference_path,
    learning_dir,
)


def _local_app_data() -> Path:
    return get_canonical_app_data_dir()


def default_habit_path() -> Path:
    return habit_preference_path()


def default_learning_dir() -> Path:
    """学习模式 JSONL 根目录：%LocalAppData%\\ShuaBao\\learning\\"""
    return learning_dir()

def learning_log_path(day: str | None = None) -> Path:
    stamp = day or datetime.now().strftime("%Y%m%d")
    return default_learning_dir() / f"observations_{stamp}.jsonl"


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


def append_learning_observation(
    record: Mapping[str, Any],
    *,
    path: Path | None = None,
) -> Path:
    """追加一条学习模式观测（JSONL）。失败时吞掉 IO 错误，不打断主循环。"""
    target = path or learning_log_path()
    payload = dict(record)
    payload.setdefault("mode", "learning")
    payload.setdefault("ts", datetime.now(timezone.utc).isoformat())
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        return target
    return target


def observations_to_name_scores(
    records: list[Mapping[str, Any]],
    panel: str,
    *,
    select_weight: float = 1.0,
) -> dict[str, float]:
    """把学习观测粗聚合为 name_scores（后续自适应接线用；当前纯函数）。

    仅统计 ``decision.action == SELECT_SLOT`` 且带规范名的槽位。
    """
    if panel not in VALID_PANELS:
        return {}
    scores: dict[str, float] = {}
    for row in records:
        if str(row.get("panel_kind") or "") != panel:
            continue
        decision = row.get("decision") or {}
        if str(decision.get("action") or "") != "SELECT_SLOT":
            continue
        idx = decision.get("index")
        slots = row.get("slots") or []
        if not isinstance(slots, list) or not isinstance(idx, int):
            continue
        if idx < 0 or idx >= len(slots):
            continue
        slot = slots[idx] or {}
        name = str(slot.get("name") or "").strip()
        if not name:
            continue
        scores[name] = scores.get(name, 0.0) + float(select_weight)
    return scores
