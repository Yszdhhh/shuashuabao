"""Load config/scenes.json — single source for template groups."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_scenes(project_root: Path) -> dict[str, Any]:
    path = project_root / "config" / "scenes.json"
    if not path.exists() and (project_root / "_internal" / "config" / "scenes.json").exists():
        path = project_root / "_internal" / "config" / "scenes.json"
    return json.loads(path.read_text(encoding="utf-8"))


def scene_templates(scenes_doc: dict[str, Any], key: str) -> list[str]:
    sc = scenes_doc.get("scenes", {}).get(key) or {}
    return list(sc.get("templates") or [])


def priority_keys(scenes_doc: dict[str, Any]) -> list[str]:
    return list(scenes_doc.get("priority") or [])
