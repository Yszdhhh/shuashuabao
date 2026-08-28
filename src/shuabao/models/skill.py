"""对齐原 GameScript.Models.Skill 数据入口。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Skill:
    name: str  # 文件短码，如 jq
    cn_name: str = ""
    path: Path | None = None


def get_all_skills(images_dir: Path) -> list[Skill]:
    d = images_dir / "skills"
    if not d.is_dir():
        return []
    out: list[Skill] = []
    for f in sorted(d.glob("*.png")):
        out.append(Skill(name=f.stem, path=f))
    return out


def get_boss_list(images_dir: Path, key: str = "boss") -> list[Skill]:
    """key: boss | chuanjiaobao"""
    d = images_dir / key
    if not d.is_dir():
        return []
    return [Skill(name=f.stem, cn_name=f.stem, path=f) for f in sorted(d.glob("*.png"))]


def get_all_card_groups(images_dir: Path) -> list[Skill]:
    d = images_dir / "cards"
    if not d.is_dir():
        return []
    return [Skill(name=f.stem, path=f) for f in sorted(d.glob("*.png"))]
