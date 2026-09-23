"""对齐原 GameScript.Models.Settings + JsonSettingsBase。"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

# 兼容旧版/上游官方保存路径（仅用于外部导入与向下兼容读取，非本系统主路径）
LEGACY_UPSTREAM_APPDATA_SETTINGS_PATH = Path(os.environ.get("APPDATA", "")) / "GameScript" / "Settings" / "Settings.json"
# 向后兼容别名，保留供旧引用访问
OFFICIAL_SETTINGS = LEGACY_UPSTREAM_APPDATA_SETTINGS_PATH

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


# Dashboard Contract v2 strategy vocabulary. These are stable wire values, not
# display labels; keeping them here lets the facade validate before persistence.
DASHBOARD_BOND_OPTIONS = ("祝福", "成长", "经济", "贪婪", "挑战")
DASHBOARD_ATTRIBUTE_OPTIONS = ("int", "str", "agi")
_INT_RANGES: dict[str, tuple[int, int]] = {
    "stage1": (1, 50), "stage2": (1, 50),
    "reputation_type": (1, 6), "reputation_level": (1, 10),
    "artifact_slots": (1, 3),
    "query_timeout": (10, 600), "game_timeout": (1, 120),
    "click_delay_ms": (0, 2000), "loop_sleep_ms": (0, 5000),
    "choice_interval": (30, 3600), "artifact_cd": (30, 3600),
    "dragon_ball_count": (1, 10), "treasure_num": (0, 20),
    "cycle_num": (0, 999), "kill_boss_num": (0, 9999),
    "follow_cycle_num": (0, 999), "hitch_cycle_num": (0, 999),
    "hitch_rotate_interval": (1, 100),
    "boss_live_time": (0, 3600), "archive_boss_time": (0, 3600),
    "auto_clean_interval": (0, 99), "develop_time": (0, 3000),
    "close_main_line_time": (0, 3600), "auto_gambling_time": (0, 3600),
    "reputation_stage1": (0, 50), "reputation_stage2": (0, 50),
    "round_timeout_s": (60, 7200), "round_tail_window_s": (30, 600),
    "recovery_timeout_s": (10, 120), "recovery_action_limit": (1, 10),
    "failure_streak_limit": (1, 10), "downgrade_after_failures": (0, 20),
    "panel_action_limit_per_fingerprint": (1, 10),
    "panel_episode_limit_per_kind": (1, 50), "ocr_timeout_ms": (200, 5000),
    "ocr_warmup_timeout_ms": (10000, 30000),
    "merchant_max_rerolls": (0, 20), "merchant_gold_reserve": (0, 1_000_000),
}
_FLOAT_RANGES: dict[str, tuple[float, float]] = {
    "recovery_retry_interval_s": (0.5, 30.0),
    "panel_visible_timeout_s": (0.5, 10.0),
    "ui_action_interval_s": (0.5, 10.0),
    "panel_reopen_cooldown_s": (2.0, 15.0),
    "incident_sample_rate": (0.0, 1.0),
    "challenge_recheck_interval_s": (5.0, 300.0),
    "auto_task_unknown_timeout_s": (30.0, 60.0),
    "match_threshold": (0.5, 0.99),
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
    # 运行方式目录 id（normal_farm / lobby_hitch / …）。不是 OBSERVE/LIVE。
    mode_id: str = "normal_farm"
    hitch_stage_prefix: str = "4,3,速"  # 大厅找房搜索词，默认 4→3→速，可逗号分隔多词轮换
    hitch_rotate_interval: int = 1  # 搜索无可进房时立即随机轮换到另一个搜索词
    subscription_base_url: str = "https://quebec-luis-flooring-kenneth.trycloudflare.com"  # 默认云端鉴权中台地址
    subscription_mode: str = "enforce"  # 订阅模式：off / shadow / enforce
    follow_cycle_num: int = 100  # 跟车目标局数；启动时投影到 cycle_num
    hitch_cycle_num: int = 100  # 蹭车目标局数；启动时投影到 cycle_num
    follow_after_room: str = "solo"  # 房间解散/被踢后预案：solo / arch / hitch
    hitch_after_goal: str = "solo"  # 达到蹭车目标后预案：solo / arch / end
    follow_pair_code: str = ""  # 带车端配对信息；当前只持久化，运行同步待接线
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
    reputation_level: int = 1  # 已验证难度 1-10（多阵营模式下单阵营上限）
    # 多阵营声望分配表：{阵营ID: 点数}，如 {3: 5, 5: 2} = 肯瑞托5点 + 元素领主2点。
    # 必须是 Settings 真字段——UI 曾用动态属性写入导致 asdict() 静默丢弃（同 C-04 模式），
    # 重启后 _hero_alloc_plan() 回退单阵营肯瑞托，元素领主等被静默跳过。
    reputation_allocations: dict[str, int] = field(default_factory=dict)
    reputation_stage1: int = 0
    reputation_stage2: int = 0
    reputation_cjb_boss: str = ""
    reputation_sgzx_boss: str = ""
    cjb_boss: str = ""
    sgzx_boss: str = ""
    skills: list[str] = field(default_factory=lambda: ["jq", "pg"])
    # Dashboard Contract v2 strategy fields. Empty selections are deliberate.
    bonds: list[str] = field(default_factory=lambda: ["成长", "经济", "贪婪", "挑战"])
    attributes: list[str] = field(default_factory=list)
    merchant_enabled: bool = True
    merchant_max_rerolls: int = 0
    merchant_gold_reserve: int = 0
    cards: list[str] = field(default_factory=list)
    # Unknown bond cards must not bypass the declared strategy.
    bond_whitelist_mode: str = "hard"
    bond_must_take: list[str] = field(default_factory=list)
    # 负面宝物放行名单（拿了会断资源/断成长的卡，默认一张都不选）。
    # 面板『宝物 · 负面卡』折叠区逐张打勾后写入；放行是逐卡的，不是全局开关。
    # 语义与判定见 config/choice_policy.json 与 shuabao.choice_policy。
    treasure_allow_negative: list[str] = field(default_factory=list)
    # 技能存档等级（短码 → 等级；0=未知不存）。曾只是看板动态属性，
    # asdict() 静默丢弃导致"填了就丢"（C-04）；现为真实字段，
    # _from_dict 只接受 {短码: int} 映射并做值域清洗（0..50，0 剔除）。
    skill_archive_levels: dict[str, int] = field(default_factory=dict)
    # 四技能智能路线微调：列出“关闭协同提权”的挂件技能短码。
    # 默认空 = 3 个挂件全部启用跨系增伤/易伤/控制/覆盖率提权。
    # 该字段必须是 Settings 真字段，确保 mode overlay / deepcopy 后仍进入 live policy。
    smart_route_disabled_amplifiers: list[str] = field(default_factory=list)
    # 技能优先级：有序技能短码（≤4，索引 0 最高优先）。
    # 空 = 完全回退现有排序，行为零变化。该字段必须是 Settings 真字段，
    # 确保保存/读取与 mode overlay 后仍进入 live policy（同 C-04 教训）。
    skill_priority: list[str] = field(default_factory=list)
    # 技能路线偏好：{短码: route id}。route id 不透明，策略层不做语义解析；
    # 空 = 无路线偏好。
    skill_custom_routes: dict[str, str] = field(default_factory=dict)
    auto_bond: bool = True       # 主动按 F 开羁绊面板（低频，防烧木材）
    auto_treasure: bool = True   # 主动按 V 开宝物面板（低频，防烧刷新次数）
    choice_interval: int = 120   # 主动开面板的最小间隔（秒）
    # 默认关闭：羁绊栏只有"数量"没有逐格身份，随机吞掉一张卡不可授权。
    # 存档里的显式 true 照旧读回（_from_dict 透传），但缺字段=不授权。
    auto_devour_dan: bool = False # 自动使用吞噬丹（需逐格身份，默认关闭）
    evolve_mystic_priority: bool = False  # 未知/神秘进化优先（True=排最前，False=默认排在 SSR 之后、SR 之前）
    auto_artifact: bool = True   # 神器 Q/W/E 槽定时释放
    artifact_cd: int = 120       # 神器冷却秒数
    artifact_slots: int = 3      # 神器槽位数（1-3，对应 Q/W/E；空槽自动跳过）
    auto_archaeology: bool = False  # 选关页黄色挑战券清空后自动进考古模式（默认关闭）
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
    #   独立的、从进入 MAIN_LINE 起不可续期的单局硬期限（秒）。
    #   20260822：900s（15 分钟）是短局测试期的取值；实测长线程刷图一局
    #   （以打完 Boss / 结算为界）远超 15 分钟（kill_boss_num=800 配置下更是
    #   以小时计），900s 会在局中强制 QUIT（trace 181735 第一局 18:33:18 即此）。
    #   默认放宽到 3600s（1 小时硬上限，仍由 victory/settlement 正常收局），
    #   game_timeout 继续 only 承担 idle watchdog（可被受确认的正常进展刷新）。
    round_timeout_s: int = 3600
    round_tail_window_s: int = 120      # 局尾窗口：距 round deadline 不足该秒数才做未验证战后入口检查
    recovery_timeout_s: int = 60        # 失败/断线恢复总预算（不可续期）
    recovery_action_limit: int = 3      # 每恢复步骤动作/观测尝试上限
    recovery_retry_interval_s: float = 1.5  # 恢复动作最小间隔
    failure_streak_limit: int = 3       # 连续不成功局上限（FAILURE/TIMEOUT/DISCONNECT 均累计）
    # 打不过自动降级（Owner 2026-09-15）：连续 N 局非胜利后，本次运行内把选关
    # 目标降一级（同章节 index-1，最低 1-1），并清零 _failure_streak 避免降级
    # 那局还没打就被熔断；不回写 user_settings.json。0 = 关闭。
    downgrade_after_failures: int = 0
    panel_visible_timeout_s: float = 2.0    # 主动打开面板的可见确认窗
    ui_action_interval_s: float = 1.5       # UI-changing 输入最小间隔
    panel_reopen_cooldown_s: float = 3.0    # 物理隐藏后同类 G/F/V 重开冷却
    challenge_recheck_interval_s: float = 30.0  # 四挑战 ON 的周期复查间隔（钳制 5..300s）
    panel_hard_deadline_s: float = 15.0     # 单个面板 episode 无进展硬超时
    auto_task_unknown_timeout_s: float = 45.0  # 自动任务 UNKNOWN 熔断（钳制 30–60s）
    panel_action_limit_per_fingerprint: int = 3  # 同 fingerprint 同动作上限
    panel_episode_limit_per_kind: int = 24      # 每局每类异常重开上限；正常成功面板不消耗
    incident_sample_rate: float = 0.1           # 正常 panel episode 抽样归档率
    # OCR 只给三选一面板提供“名字证据”；live 时技能/羁绊没有可靠名字就不点。
    # Paddle 运行在独立 sidecar，主 EXE 不加载模型依赖。
    ocr_mode: str = "live"                      # off / shadow / live
    ocr_repo_root: str = ""                     # sidecar 的本地源码/模型根目录
    ocr_timeout_ms: int = 2500                   # 单槽热推理超时（稳准优先，live 另有 2500ms 下限）
    ocr_warmup_timeout_ms: int = 20000           # 首次模型加载/预热超时
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
        """读取上游官方 %AppData%\\GameScript\\Settings\\Settings.json（兼容外部配置）。"""
        p = Path(path) if path else LEGACY_UPSTREAM_APPDATA_SETTINGS_PATH
        if not p.is_file():
            raise FileNotFoundError(f"legacy upstream official settings not found: {p}")
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
                elif k in ("room_name", "room_password", "cjb_boss", "sgzx_boss",
                           "reputation_cjb_boss", "reputation_sgzx_boss", "window_title_contains"):
                    clean[k] = ""
                elif k in (
                    "skills", "cards", "stage_targets", "treasure_allow_negative",
                    "bond_must_take", "bonds", "attributes", "smart_route_disabled_amplifiers",
                    "skill_priority", "skill_custom_routes",
                ):
                    clean[k] = []
        # 2. 字符串字段防护：仅在 fallback 模式防护（仅接受 str）；无 fallback 精确保持 32633f4 原样
        str_fields = {
            "room_name", "room_password", "room_create_side",
            "reputation_cjb_boss", "reputation_sgzx_boss",
            "cjb_boss", "sgzx_boss", "window_title_contains",
            "ocr_repo_root", "images_dir", "bond_whitelist_mode",
            "mode_id", "hitch_stage_prefix", "hitch_rotate_interval", "follow_after_room",
            "subscription_base_url", "subscription_mode",
            "hitch_after_goal", "follow_pair_code",
        }
        if fallback is not None:
            for k in str_fields:
                if k in clean and not isinstance(clean[k], str):
                    clean.pop(k)
        # 3. int / float 字段清洗
        int_fields = {
            "stage1", "stage2", "query_timeout", "game_timeout", "game_mode",
            "dragon_ball_count", "close_main_line_time", "auto_clean_interval",
            "develop_time", "reputation_type", "reputation_level",
            "reputation_stage1", "reputation_stage2", "boss_live_time",
            "kill_boss_num", "cycle_num", "archive_boss_time", "treasure_num",
            "follow_cycle_num", "hitch_cycle_num", "hitch_rotate_interval",
            "auto_gambling_time", "click_delay_ms", "loop_sleep_ms",
            "artifact_cd", "artifact_slots", "choice_interval",
            "round_timeout_s", "round_tail_window_s", "recovery_timeout_s",
            "recovery_action_limit", "failure_streak_limit",
            "panel_action_limit_per_fingerprint", "panel_episode_limit_per_kind",
            "ocr_timeout_ms", "ocr_warmup_timeout_ms", "merchant_max_rerolls", "merchant_gold_reserve",
            "downgrade_after_failures",
        }
        float_fields = {
            "recovery_retry_interval_s", "panel_visible_timeout_s", "panel_hard_deadline_s",
            "ui_action_interval_s", "panel_reopen_cooldown_s", "incident_sample_rate",
            "challenge_recheck_interval_s", "auto_task_unknown_timeout_s",
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
            "auto_secret_realm", "auto_close_main_line", "auto_archaeology", "auto_card", "auto_weapon",
            "damage_increase_card", "develop_priority", "auto_reputation",
            "continue_reputation", "auto_bond", "auto_treasure", "auto_artifact",
            "merchant_enabled", "dry_run",
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
        # 兼容读取仍会钳制；DashboardFacade.validate_patch 在写入前严格拒绝。
        for key, (lo, hi) in _INT_RANGES.items():
            if key in clean:
                try:
                    clean[key] = max(lo, min(hi, int(clean[key])))
                except (TypeError, ValueError):
                    clean.pop(key)
        for key, (lo, hi) in _FLOAT_RANGES.items():
            if key in clean:
                try:
                    clean[key] = max(lo, min(hi, float(clean[key])))
                except (TypeError, ValueError):
                    clean.pop(key)
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
        for key, allowed in (
            ("bonds", set(DASHBOARD_BOND_OPTIONS)),
            ("attributes", set(DASHBOARD_ATTRIBUTE_OPTIONS)),
        ):
            if key not in clean:
                continue
            raw_items = clean[key]
            if isinstance(raw_items, (list, tuple)):
                clean[key] = [str(v).strip() for v in raw_items if str(v).strip() in allowed]
            elif fallback is not None:
                clean.pop(key)
            else:
                clean[key] = []
        # 看板羁绊是严格白名单；空列表也有意义，不能补回未选的“祝福”。
        if "bond_must_take" in clean:
            raw_bond_must = clean["bond_must_take"]
            if isinstance(raw_bond_must, (list, tuple)):
                items = [str(v).strip() for v in raw_bond_must if str(v).strip()]
                # 旧版把“祝福”无条件塞进此字段；它不是用户在当前看板做出的选择。
                if items == ["祝福"]:
                    items = []
                clean["bond_must_take"] = list(dict.fromkeys(items))
            elif fallback is not None:
                clean.pop("bond_must_take")
            else:
                clean["bond_must_take"] = []
        if "bond_whitelist_mode" in clean:
            mode = str(clean["bond_whitelist_mode"]).strip().lower()
            if mode in {"soft", "hard"}:
                clean["bond_whitelist_mode"] = mode
            else:
                clean.pop("bond_whitelist_mode")
        if "mode_id" in clean:
            mid = str(clean["mode_id"] or "").strip()
            clean["mode_id"] = mid or "normal_farm"
        if "hitch_stage_prefix" in clean:
            search_text = str(clean["hitch_stage_prefix"] or "").strip()[:64]
            clean["hitch_stage_prefix"] = search_text or "4,3,速"
        for key, allowed, default in (
            ("follow_after_room", {"solo", "arch", "hitch"}, "solo"),
            ("hitch_after_goal", {"solo", "arch", "end"}, "solo"),
        ):
            if key not in clean:
                continue
            if not isinstance(clean[key], str):
                if fallback is not None:
                    clean.pop(key)
                else:
                    clean[key] = default
                continue
            value = clean[key].strip().lower()
            if value in allowed:
                clean[key] = value
            elif fallback is not None:
                clean.pop(key)
            else:
                clean[key] = default
        if "follow_pair_code" in clean:
            if isinstance(clean["follow_pair_code"], str):
                clean["follow_pair_code"] = clean["follow_pair_code"].strip()[:24]
            elif fallback is not None:
                clean.pop("follow_pair_code")
            else:
                clean["follow_pair_code"] = ""
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
        # 智能路线挂件微调：只接受字符串列表，去重保序，最多 4 个技能短码/族名。
        if "smart_route_disabled_amplifiers" in clean:
            raw_disabled = clean["smart_route_disabled_amplifiers"]
            if isinstance(raw_disabled, (list, tuple)):
                clean["smart_route_disabled_amplifiers"] = list(dict.fromkeys(
                    str(v).strip() for v in raw_disabled if str(v).strip()
                ))[:MAX_SELECTED_SKILLS]
            elif fallback is not None:
                clean.pop("smart_route_disabled_amplifiers")
            else:
                clean["smart_route_disabled_amplifiers"] = []
        # 技能优先级：只接受字符串列表，去重保序，最多 4 个短码；空 = 完全回退现有排序。
        if "skill_priority" in clean:
            raw_priority = clean["skill_priority"]
            if isinstance(raw_priority, (list, tuple)):
                clean["skill_priority"] = list(dict.fromkeys(
                    str(v).strip() for v in raw_priority if str(v).strip()
                ))[:MAX_SELECTED_SKILLS]
            elif fallback is not None:
                clean.pop("skill_priority")
            else:
                clean["skill_priority"] = []
        if "skill_custom_routes" in clean:
            raw_route_cfg = clean["skill_custom_routes"]
            if isinstance(raw_route_cfg, dict):
                cleaned_routes: dict[str, str] = {}
                for rk, rv in raw_route_cfg.items():
                    if not isinstance(rv, str):
                        continue
                    key_s = str(rk).strip()
                    val_s = rv.strip()
                    if key_s and val_s:
                        cleaned_routes[key_s] = val_s
                clean["skill_custom_routes"] = cleaned_routes
            elif fallback is not None:
                clean.pop("skill_custom_routes")
            else:
                clean["skill_custom_routes"] = {}
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
        # 声望分配：只接受 {阵营ID字符串: int点数}；值域清洗（1..10，超出钳制），
        # 键统一为规范短码/ID 字符串，与 dataclass 声明 dict[str, int] 对齐。
        if "reputation_allocations" in clean:
            raw_alloc = clean["reputation_allocations"]
            if isinstance(raw_alloc, dict):
                allocs: dict[str, int] = {}
                for k, v in raw_alloc.items():
                    try:
                        pts = int(v)
                    except (TypeError, ValueError):
                        continue
                    if 1 <= pts <= 10:
                        allocs[str(k).strip()] = pts
                clean["reputation_allocations"] = allocs
            elif fallback is not None:
                clean.pop("reputation_allocations")
            else:
                clean["reputation_allocations"] = {}
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

    @classmethod
    def validate_patch(cls, data: dict[str, Any], fallback: "Settings") -> list[str]:
        """Reject dashboard patches before _from_dict can coerce or clamp them."""
        errors: list[str] = []
        known = cls.__dataclass_fields__
        string_lists = {
            "stage_targets", "skills", "cards", "bond_must_take", "treasure_allow_negative",
            "smart_route_disabled_amplifiers", "skill_priority", "bonds", "attributes",
        }
        for key, value in data.items():
            if key not in known:
                errors.append(f"未知字段: {key}")
                continue
            current = getattr(fallback, key)
            if isinstance(current, bool):
                if type(value) is not bool:
                    errors.append(f"字段类型非法: {key} 必须为 bool")
                continue
            if isinstance(current, int):
                if type(value) is not int:
                    errors.append(f"字段类型非法: {key} 必须为 int")
                    continue
                bounds = _INT_RANGES.get(key)
                if bounds and not bounds[0] <= value <= bounds[1]:
                    errors.append(f"字段范围非法: {key}")
                continue
            if isinstance(current, float):
                if type(value) not in (int, float):
                    errors.append(f"字段类型非法: {key} 必须为 number")
                    continue
                bounds = _FLOAT_RANGES.get(key)
                if bounds and not bounds[0] <= float(value) <= bounds[1]:
                    errors.append(f"字段范围非法: {key}")
                continue
            if isinstance(current, str):
                if type(value) is not str:
                    errors.append(f"字段类型非法: {key} 必须为 string")
                    continue
                if key == "follow_pair_code" and len(value) > 24:
                    errors.append("follow_pair_code 最多 24 字符")
                elif key == "bond_whitelist_mode" and value not in {"soft", "hard"}:
                    errors.append("bond_whitelist_mode 取值非法")
                elif key == "hitch_stage_prefix" and (not value.strip() or len(value.strip()) > 64):
                    errors.append("hitch_stage_prefix 必须为 1-64 个非空字符")
                elif key == "follow_after_room" and value not in {"solo", "arch", "hitch"}:
                    errors.append("follow_after_room 取值非法")
                elif key == "hitch_after_goal" and value not in {"solo", "arch", "end"}:
                    errors.append("hitch_after_goal 取值非法")
                elif key == "ocr_mode" and value not in {"off", "shadow", "live"}:
                    errors.append("ocr_mode 取值非法")
                continue
            if isinstance(current, list):
                if type(value) is not list:
                    errors.append(f"字段类型非法: {key} 必须为 list")
                elif key == "window_size":
                    if len(value) != 2 or any(type(item) is not int or item <= 0 for item in value):
                        errors.append("字段值非法: window_size")
                elif key in string_lists:
                    if any(type(item) is not str or not item for item in value):
                        errors.append(f"字段值非法: {key}")
                    elif key == "skills" and len(value) > MAX_SELECTED_SKILLS:
                        errors.append(f"skills 最多 {MAX_SELECTED_SKILLS} 个")
                    elif key == "bonds" and (len(set(value)) != len(value) or not set(value) <= set(DASHBOARD_BOND_OPTIONS)):
                        errors.append("字段值非法: bonds")
                    elif key == "attributes" and (len(set(value)) != len(value) or not set(value) <= set(DASHBOARD_ATTRIBUTE_OPTIONS)):
                        errors.append("字段值非法: attributes")
                else:
                    errors.append(f"字段类型未声明: {key}")
                continue
            if isinstance(current, dict):
                if type(value) is not dict:
                    errors.append(f"字段类型非法: {key} 必须为 object")
                elif key == "reputation_allocations" and any(
                    type(item_key) is not str or type(item_value) is not int or not 1 <= item_value <= 10
                    for item_key, item_value in value.items()
                ):
                    errors.append("字段值非法: reputation_allocations")
                elif key == "skill_archive_levels" and any(
                    type(item_key) is not str or type(item_value) is not int or not 1 <= item_value <= 50
                    for item_key, item_value in value.items()
                ):
                    errors.append("字段值非法: skill_archive_levels")
                elif key == "skill_custom_routes" and any(
                    type(item_key) is not str or type(item_value) is not str or not item_key or not item_value
                    for item_key, item_value in value.items()
                ):
                    errors.append("字段值非法: skill_custom_routes")
        return errors

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, p)

    def images_path(self, root: Path) -> Path:
        p = Path(self.images_dir)
        if p.is_absolute():
            return p
        candidate = root / p
        if not candidate.exists() and (root / "_internal" / p).exists():
            return root / "_internal" / p
        return candidate

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
