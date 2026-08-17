"""对齐原 GameScript.Models.Settings + JsonSettingsBase。"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

# 官方保存路径（授权后）
OFFICIAL_SETTINGS = Path(os.environ.get("APPDATA", "")) / "GameScript" / "Settings" / "Settings.json"

# 技能选择上限（用户 2026-08-17 确认：至多 4 个、无 all_round 全能档）。
# 解析边界（_from_dict/load/load_official/load_lab_settings）统一截断，
# 外壳 SkillCardGrid 与图鉴 apply 复用同一常量，避免第二事实源。
MAX_SELECTED_SKILLS = 4

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
    "AutoDevourDan": "auto_devour_dan",
}


@dataclass
class Settings:
    stage1: int = 3
    stage2: int = 2
    stage_targets: list[str] = field(default_factory=list)
    room_name: str = ""
    room_password: str = ""
    # Solo is expected to be a complete L0→L1 chain in this local build.
    # Real input is guarded by dry_run / 看板「学习模式」（默认关闭=真机实操）。
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
    # 负面宝物放行名单（拿了会断资源/断成长的卡，默认一张都不选）。
    # 面板『宝物 · 负面卡』折叠区逐张打勾后写入；放行是逐卡的，不是全局开关。
    # 语义与判定见 config/choice_policy.json 与 shuabao.choice_policy。
    treasure_allow_negative: list[str] = field(default_factory=list)
    # 技能存档等级（短码 → 等级；0=未知不存）。曾只是看板动态属性，
    # asdict() 静默丢弃导致"填了就丢"（C-04）；现为真实字段，
    # _from_dict 只接受 {短码: int} 映射并做值域清洗（0..50，0 剔除）。
    skill_archive_levels: dict[str, int] = field(default_factory=dict)
    auto_bond: bool = True       # 主动按 F 开羁绊面板（低频，防烧木材）
    auto_treasure: bool = True   # 主动按 V 开宝物面板（低频，防烧刷新次数）
    choice_interval: int = 120   # 主动开面板的最小间隔（秒）
    auto_devour_dan: bool = True # 自动使用吞噬丹（需羁绊栏非空）
    auto_artifact: bool = True   # 神器 Q/W/E 槽定时释放
    artifact_cd: int = 120       # 神器冷却秒数
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
    # ---- S0 长期运行安全状态机（2026-08-11，迁移决定见下）----
    # 旧字段映射决定（CODEX_N2_S0_IMPLEMENTATION S0-④ 前置文档）：
    #   game_timeout=15 的官方语义是"单局超时"（分钟，review_mediator.md 实测作为
    #   MAIN_LINE idle watchdog：idle_minutes >= max(game_timeout,5)），不是秒。
    #   本轮不再把 game_timeout 直接接成 hard deadline；新增 round_timeout_s 作为
    #   独立的、从进入 MAIN_LINE 起不可续期的单局硬期限（秒），默认 = 15 分钟换算
    #   （15*60=900s），保留官方"整局最长 15 分钟"语义为硬上限。game_timeout 继续
    #   只承担 idle watchdog（可被受确认的正常进展刷新），与 hard deadline 分离。
    round_timeout_s: int = 900
    round_tail_window_s: int = 120      # 局尾窗口：距 round deadline 不足该秒数才做未验证战后入口检查
    recovery_timeout_s: int = 60        # 失败/断线恢复总预算（不可续期）
    recovery_action_limit: int = 3      # 每恢复步骤动作/观测尝试上限
    recovery_retry_interval_s: float = 1.5  # 恢复动作最小间隔
    failure_streak_limit: int = 3       # 连续不成功局上限（FAILURE/TIMEOUT/DISCONNECT 均累计）
    panel_visible_timeout_s: float = 2.0    # 主动打开面板的可见确认窗
    ui_action_interval_s: float = 1.5       # UI-changing 输入最小间隔
    challenge_recheck_interval_s: float = 30.0  # 四挑战 ON 的周期复查间隔（钳制 5..300s）
    panel_action_limit_per_fingerprint: int = 3  # 同 fingerprint 同动作上限
    panel_episode_limit_per_kind: int = 5       # 每局每类面板会话上限
    incident_sample_rate: float = 0.1           # 正常 panel episode 抽样归档率
    # OCR 只给三选一面板提供“名字证据”；live 时技能/羁绊没有可靠名字就不点。
    # Paddle 运行在独立 sidecar，主 EXE 不加载模型依赖。
    ocr_mode: str = "off"                       # off / shadow / live
    ocr_repo_root: str = ""                     # sidecar 的本地源码/模型根目录
    ocr_timeout_ms: int = 1200                   # 单槽热推理超时（模型启动另有 6s 窗）
    # N2.3 替代语义：主循环已改为状态分级 cadence（动作后 100ms / 稳定 HUD 300ms /
    # loading 500ms，见 Mediator._cadence_for_current_state）。本字段仅保留为兼容
    # 默认/上限：run() 中 sleep = max(0, min(cadence, loop_sleep_ms/1000) - elapsed)。
    loop_sleep_ms: int = 400
    window_title_contains: str = "英雄三国"
    window_size: list[int] = field(default_factory=lambda: [1600, 900])
    images_dir: str = "assets/Images"
    # 看板称「学习模式」：True=只观察记录、零真实输入；False=真机实操。
    # 默认关闭，避免「看不见的 dry_run」导致创房永远等不到弹窗。
    dry_run: bool = False

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
        mapped.setdefault("dry_run", False)
        mapped.setdefault("window_title_contains", "英雄三国")
        mapped.setdefault("images_dir", "assets/Images")
        mapped.setdefault("match_threshold", 0.85)
        mapped.setdefault("click_delay_ms", 120)
        mapped.setdefault("loop_sleep_ms", 400)
        mapped.setdefault("window_size", [1600, 900])
        return cls._from_dict(mapped)

    @classmethod
    def _from_dict(cls, data: dict[str, Any] | None, fallback: Settings | None = None) -> "Settings":
        if not isinstance(data, dict):
            return replace(fallback) if fallback is not None else cls()
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        clean = {k: v for k, v in data.items() if k in known}
        # 1. None 缺损清洗
        for k, v in list(clean.items()):
            if v is None:
                if fallback is not None:
                    # fallback 模式：所有 None 视为 overlay 缺损并 pop，保留 base
                    clean.pop(k)
                else:
                    # 无 fallback 模式：精确保持 32633f4 旧语义
                    if k in ("room_name", "room_password", "cjb_boss", "sgzx_boss",
                             "reputation_cjb_boss", "reputation_sgzx_boss", "window_title_contains"):
                        clean[k] = ""
                    elif k in ("skills", "cards", "stage_targets", "treasure_allow_negative"):
                        clean[k] = []
        # 2. 字符串字段防护：仅在 fallback 模式防护（仅接受 str）；无 fallback 精确保持 32633f4 原样
        str_fields = {
            "room_name", "room_password", "room_create_side",
            "reputation_cjb_boss", "reputation_sgzx_boss",
            "cjb_boss", "sgzx_boss", "window_title_contains",
            "ocr_repo_root", "images_dir",
        }
        if fallback is not None:
            for k in str_fields:
                if k in clean:
                    if not isinstance(clean[k], str):
                        clean.pop(k)
        # 3. int / float 字段清洗
        int_fields = {
            "stage1", "stage2", "query_timeout", "game_timeout", "game_mode",
            "dragon_ball_count", "close_main_line_time", "auto_clean_interval",
            "develop_time", "reputation_type", "reputation_level",
            "reputation_stage1", "reputation_stage2", "boss_live_time",
            "kill_boss_num", "cycle_num", "archive_boss_time", "treasure_num",
            "auto_gambling_time", "click_delay_ms", "loop_sleep_ms",
            "artifact_cd", "artifact_slots", "choice_interval",
            "round_timeout_s", "round_tail_window_s", "recovery_timeout_s",
            "recovery_action_limit", "failure_streak_limit",
            "panel_action_limit_per_fingerprint", "panel_episode_limit_per_kind",
            "ocr_timeout_ms",
        }
        float_fields = {
            "recovery_retry_interval_s", "panel_visible_timeout_s",
            "ui_action_interval_s", "incident_sample_rate",
            "challenge_recheck_interval_s",
        }
        for k in float_fields:
            if k in clean:
                if isinstance(clean[k], (list, dict)) or clean[k] is None:
                    clean.pop(k)
                else:
                    try:
                        clean[k] = float(clean[k])
                    except (TypeError, ValueError):
                        clean.pop(k)
        for k in int_fields:
            if k in clean:
                if isinstance(clean[k], (list, dict)) or clean[k] is None:
                    clean.pop(k)
                else:
                    try:
                        clean[k] = int(clean[k])
                    except (TypeError, ValueError):
                        clean.pop(k)
        # 4. bool 字段清洗
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
                        # 未知字符串：回落（无 fallback 默认值，有 fallback 保留 base）
                        clean.pop(k)
                elif fallback is not None:
                    if isinstance(v, (int, float)):
                        clean[k] = bool(v)
                    else:
                        clean.pop(k)
                else:
                    clean[k] = bool(v)
        if "match_threshold" in clean:
            if isinstance(clean["match_threshold"], (list, dict)) or clean["match_threshold"] is None:
                clean.pop("match_threshold")
            else:
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
            # S0 安全默认范围（超出回落安全区间，绝不静默放大时限/次数）
            "round_timeout_s": (60, 7200), "round_tail_window_s": (30, 600),
            "recovery_timeout_s": (10, 600), "recovery_action_limit": (1, 10),
            "failure_streak_limit": (1, 10),
            "panel_action_limit_per_fingerprint": (1, 10),
            "panel_episode_limit_per_kind": (1, 50),
            "ocr_timeout_ms": (200, 5000),
        }
        for k, (lo, hi) in _RANGES.items():
            if k in clean:
                try:
                    clean[k] = max(lo, min(hi, int(clean[k])))
                except (TypeError, ValueError):
                    clean.pop(k)
        float_ranges: dict[str, tuple[float, float]] = {
            "recovery_retry_interval_s": (0.5, 30.0),
            "panel_visible_timeout_s": (0.5, 10.0),
            "ui_action_interval_s": (0.5, 10.0),
            "incident_sample_rate": (0.0, 1.0),
            "challenge_recheck_interval_s": (5.0, 300.0),
        }
        for k, (lo, hi) in float_ranges.items():
            if k in clean:
                try:
                    clean[k] = max(lo, min(hi, float(clean[k])))
                except (TypeError, ValueError):
                    clean.pop(k)
        if "match_threshold" in clean:
            clean["match_threshold"] = max(0.5, min(0.99, float(clean["match_threshold"])))
        # 技能最多 MAX_SELECTED_SKILLS 个（解析边界集中截断，保序、剔除空串；
        # 覆盖 Settings.load / load_official / load_lab_settings 全部入口）。
        if "skills" in clean:
            raw_skills = clean["skills"]
            if isinstance(raw_skills, (list, tuple)):
                kept: list[str] = []
                for s in raw_skills:
                    text = str(s).strip() if s is not None else ""
                    if text:
                        kept.append(text)
                    if len(kept) >= MAX_SELECTED_SKILLS:
                        break
                clean["skills"] = kept
            elif fallback is not None:
                clean.pop("skills")
            else:
                clean["skills"] = []
        # 负面宝物放行名单：只接受字符串列表；类型不对一律回落为空（不放行任何负面卡）。
        if "treasure_allow_negative" in clean:
            raw_allow = clean["treasure_allow_negative"]
            if isinstance(raw_allow, (list, tuple)):
                clean["treasure_allow_negative"] = [
                    str(v).strip() for v in raw_allow if str(v).strip()
                ]
            elif fallback is not None:
                clean.pop("treasure_allow_negative")
            else:
                clean["treasure_allow_negative"] = []
        # 技能存档等级：只接受 {短码: int} 映射；值域清洗（0..50，0=未知剔除），
        # 类型/范围损坏一律回落为空映射（保守：未知存档不放宽任何前置/减伤）。
        if "skill_archive_levels" in clean:
            raw_levels = clean["skill_archive_levels"]
            if isinstance(raw_levels, dict):
                levels: dict[str, int] = {}
                for code, lv in raw_levels.items():
                    try:
                        value = int(lv)
                    except (TypeError, ValueError):
                        continue
                    if value <= 0:
                        continue
                    levels[str(code).strip()] = max(0, min(50, value))
                clean["skill_archive_levels"] = levels
            elif fallback is not None:
                clean.pop("skill_archive_levels")
            else:
                clean["skill_archive_levels"] = {}
        if "window_size" in clean:
            ws = clean["window_size"]
            if not (isinstance(ws, list) and len(ws) == 2
                    and all(isinstance(v, int) and v > 0 for v in ws)):
                clean.pop("window_size")
        if "ocr_mode" in clean:
            v = clean["ocr_mode"]
            if isinstance(v, str):
                mode = v.strip().lower()
                if mode in {"off", "shadow", "live"}:
                    clean["ocr_mode"] = mode
                else:
                    clean.pop("ocr_mode")
            else:
                clean.pop("ocr_mode")

        if fallback is not None:
            return replace(fallback, **clean)
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
