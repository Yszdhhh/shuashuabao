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
    "FindLongzhuInGame": "find_longzhu_in_game",
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
    find_longzhu_in_game: bool = False  # 1.4 新增：游戏内找龙珠（LONGZHU 重建后启用，现仅配置门闩）
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
    auto_bond: bool = True       # 主动按 F 开羁绊面板（低频，防烧木材）
    auto_treasure: bool = True   # 主动按 V 开宝物面板（低频，防烧刷新次数）
    choice_interval: int = 120   # 主动开面板的最小间隔（秒）
    auto_artifact: bool = True   # 神器 Q/W 槽定时释放（固定冷却 180s）
    artifact_cd: int = 180       # 神器冷却秒数
    artifact_slots: int = 3      # 神器槽位数（1-3，对应 Q/W/E；空槽自动跳过）
    auto_archaeology: bool = True  # 选关页黄色挑战券清空后自动进考古模式并结束脚本
    boss_live_time: int = 0
    kill_boss_num: int = 0
    cycle_num: int = 0
    archive_boss_time: int = 0
    treasure_num: int = 0
    auto_gambling_time: int = 0  # 黑商功能未接入状态机（调研报告 P2）
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
        # 类型/范围强制：损坏或异常值回落到安全默认，避免整份配置加载失败
        int_fields = {
            "stage1", "stage2", "query_timeout", "game_timeout", "game_mode",
            "dragon_ball_count", "close_main_line_time", "auto_clean_interval",
            "develop_time", "reputation_type", "reputation_level",
            "reputation_stage1", "reputation_stage2", "boss_live_time",
            "kill_boss_num", "cycle_num", "archive_boss_time", "treasure_num",
            "auto_gambling_time", "click_delay_ms", "loop_sleep_ms",
            "artifact_cd", "artifact_slots", "choice_interval",
        }
        for k in int_fields:
            if k in clean:
                try:
                    clean[k] = int(clean[k])
                except (TypeError, ValueError):
                    clean.pop(k)
        bool_fields = {
            "auto_create_room", "new_room_every_times", "find_longzhu_where_multi_game",
            "find_longzhu_in_game",
            "auto_secret_realm", "auto_close_main_line", "auto_card", "auto_weapon",
            "damage_increase_card", "develop_priority", "auto_reputation",
            "continue_reputation", "auto_bond", "auto_treasure", "auto_artifact",
            "dry_run",
        }
        for k in bool_fields:
            if k in clean and not isinstance(clean[k], bool):
                v = clean[k]
                if isinstance(v, str):
                    low = v.strip().lower()
                    if low in ("1", "true", "yes", "on"):
                        clean[k] = True
                    elif low in ("0", "false", "no", "off", ""):
                        clean[k] = False
                    else:
                        # 未知字符串：回落字段默认值，绝不悄悄改变功能开关
                        clean.pop(k)
                else:
                    # 非 bool/str 数值：按真值转换
                    clean[k] = bool(v)
        if "match_threshold" in clean:
            try:
                clean["match_threshold"] = float(clean["match_threshold"])
            except (TypeError, ValueError):
                clean.pop("match_threshold")
        # 范围钳制（集中表）：负数/极端值回落到安全区间
        _RANGES: dict[str, tuple[int, int]] = {
            "stage1": (1, 50), "stage2": (1, 50),
            "reputation_type": (1, 6), "reputation_level": (1, 10),
            "artifact_slots": (1, 3),
            "query_timeout": (10, 600), "game_timeout": (1, 120),
            "click_delay_ms": (0, 2000), "loop_sleep_ms": (0, 5000),
            "choice_interval": (30, 3600), "artifact_cd": (30, 3600),
            "dragon_ball_count": (1, 10), "treasure_num": (0, 20),
            "cycle_num": (0, 999), "kill_boss_num": (0, 9999),
            "boss_live_time": (0, 3600), "archive_boss_time": (0, 3600),
            "auto_clean_interval": (0, 99), "develop_time": (0, 3000),
            "close_main_line_time": (0, 3600), "auto_gambling_time": (0, 3600),
            "reputation_stage1": (0, 50), "reputation_stage2": (0, 50),
        }
        for k, (lo, hi) in _RANGES.items():
            if k in clean:
                try:
                    clean[k] = max(lo, min(hi, int(clean[k])))
                except (TypeError, ValueError):
                    clean.pop(k)
        if "match_threshold" in clean:
            clean["match_threshold"] = max(0.5, min(0.99, float(clean["match_threshold"])))
        if "window_size" in clean:
            ws = clean["window_size"]
            if not (isinstance(ws, list) and len(ws) == 2
                    and all(isinstance(v, int) and v > 0 for v in ws)):
                clean.pop("window_size")
        return cls(**clean)

    def save(self, path: str | Path) -> None:
        """原子写：先写同目录临时文件再 os.replace，避免中断截断配置。"""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, p)

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
