"""对齐原 GameScript.Models.Settings + JsonSettingsBase。"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# 官方保存路径（授权后）
OFFICIAL_SETTINGS = Path(os.environ.get("APPDATA", "")) / "GameScript" / "Settings" / "Settings.json"

# 官方 PascalCase → 本地 snake_case
_OFFICIAL_MAP = {
    "Stage1": "stage1",
    "Stage2": "stage2",
    "RoomPassword": "room_password",
    "RoomName": "room_name",
    "QueryTimeOut": "query_timeout",
    "DragonBallCount": "dragon_ball_count",
    "AutoSecretRealm": "auto_secret_realm",
    "Skills": "skills",
    "CJBBoss": "cjb_boss",
    "SGZXBoss": "sgzx_boss",
    "GameMode": "game_mode",
    "GameTimeOut": "game_timeout",
    "AutoCloseMainLine": "auto_close_main_line",
    "AutoCleanInterval": "auto_clean_interval",
    "DamageIncreaseCard": "damage_increase_card",
    "AutoReputation": "auto_reputation",
    "ReputationStage1": "reputation_stage1",
    "ReputationStage2": "reputation_stage2",
    "ReputationCJBBoss": "reputation_cjb_boss",
    "ReputationSGZXBoss": "reputation_sgzx_boss",
    "AutoCard": "auto_card",
    "AutoWeapon": "auto_weapon",
    "NewRoomEveryTimes": "new_room_every_times",
    "Cards": "cards",
    "BoosLiveTime": "boss_live_time",
    "KillBossNum": "kill_boss_num",
    "DevelopTime": "develop_time",
    "CycleNum": "cycle_num",
    "ArchiveBossTime": "archive_boss_time",
    "TreasureNum": "treasure_num",
    "AutoGamblingTime": "auto_gambling_time",
    "ContinueReputation": "continue_reputation",
    "CloseMainLineTime": "close_main_line_time",
    "DevelopPriority": "develop_priority",
    "FindLongzhuWhereMultiGame": "find_longzhu_where_multi_game",
}


@dataclass
class Settings:
    stage1: int = 3
    stage2: int = 2
    stage_targets: list[str] = field(default_factory=list)
    room_name: str = ""
    room_password: str = ""
    # Solo is expected to be a complete L0→L1 chain in this local build.
    # Keep real input separately guarded by dry_run=True by default.
    auto_create_room: bool = True
    room_create_side: str = "left"
    new_room_every_times: bool = False
    query_timeout: int = 60
    game_timeout: int = 15
    game_mode: int = 0  # 0=独狼/自己刷图
    dragon_ball_count: int = 7
    find_longzhu_where_multi_game: bool = False
    auto_secret_realm: bool = False
    auto_close_main_line: bool = False
    close_main_line_time: int = 0
    auto_clean_interval: int = 0
    auto_card: bool = True
    auto_weapon: bool = True
    damage_increase_card: bool = False
    develop_priority: bool = False
    develop_time: int = 0
    auto_reputation: bool = False
    continue_reputation: bool = False
    reputation_type: int = 3  # 安全首版仅开放录屏验证过的肯瑞托
    reputation_level: int = 1  # 已验证难度 1-5
    reputation_stage1: int = 0
    reputation_stage2: int = 0
    reputation_cjb_boss: str = ""
    reputation_sgzx_boss: str = ""
    cjb_boss: str = ""
    sgzx_boss: str = ""
    skills: list[str] = field(default_factory=lambda: ["jq", "pg"])
    cards: list[str] = field(default_factory=list)
    auto_bond: bool = False      # 主动按 F 开羁绊面板（低频，防烧木材）
    auto_treasure: bool = False  # 主动按 V 开宝物面板（低频，防烧刷新次数）
    choice_interval: int = 120   # 主动开面板的最小间隔（秒）
    boss_live_time: int = 0
    kill_boss_num: int = 0
    cycle_num: int = 0
    archive_boss_time: int = 0
    treasure_num: int = 0
    auto_gambling_time: int = 0
    match_threshold: float = 0.85
    click_delay_ms: int = 120
    loop_sleep_ms: int = 400
    window_title_contains: str = "英雄三国"
    window_size: list[int] = field(default_factory=lambda: [1600, 900])
    images_dir: str = "assets/Images"
    dry_run: bool = True

    @classmethod
    def load(cls, path: str | Path) -> "Settings":
        p = Path(path)
        data: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
        return cls._from_dict(data)

    @classmethod
    def load_official(cls, path: str | Path | None = None) -> "Settings":
        """读取官方 %AppData%\\GameScript\\Settings\\Settings.json。"""
        p = Path(path) if path else OFFICIAL_SETTINGS
        if not p.is_file():
            raise FileNotFoundError(f"official settings not found: {p}")
        raw = json.loads(p.read_text(encoding="utf-8"))
        mapped: dict[str, Any] = {}
        for ok, lk in _OFFICIAL_MAP.items():
            if ok not in raw:
                continue
            v = raw[ok]
            if v is None and lk in ("room_name", "room_password", "cjb_boss", "sgzx_boss"):
                v = ""
            if lk in ("skills", "cards") and not isinstance(v, list):
                v = list(v) if v else []
            mapped[lk] = v
        # 本地自用默认：独狼 + 不点真机除非改
        mapped.setdefault("game_mode", 0)
        mapped.setdefault("dry_run", True)
        mapped.setdefault("window_title_contains", "英雄三国")
        mapped.setdefault("images_dir", "assets/Images")
        mapped.setdefault("match_threshold", 0.85)
        mapped.setdefault("click_delay_ms", 120)
        mapped.setdefault("loop_sleep_ms", 400)
        mapped.setdefault("window_size", [1600, 900])
        return cls._from_dict(mapped)

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> "Settings":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        clean = {k: v for k, v in data.items() if k in known}
        # None → 安全默认
        for k, v in list(clean.items()):
            if v is None:
                if k in ("room_name", "room_password", "cjb_boss", "sgzx_boss",
                         "reputation_cjb_boss", "reputation_sgzx_boss", "window_title_contains"):
                    clean[k] = ""
                elif k in ("skills", "cards", "stage_targets"):
                    clean[k] = []
        return cls(**clean)

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")

    def images_path(self, root: Path) -> Path:
        p = Path(self.images_dir)
        return p if p.is_absolute() else (root / p)

    def skill_template_names(self) -> list[str]:
        """技能短码 → 找图名（含 skills/ 前缀）。"""
        out: list[str] = []
        for s in self.skills:
            s = (s or "").strip()
            if not s:
                continue
            out.append(s)
            out.append(f"skills/{s}")
        return out
