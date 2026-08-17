"""P0 确定性选择策略（蓝图 §12，纯函数）。

本模块只做一件事：把识别层输出的结构化候选，映射为有限动作枚举 + 槽位编号。

规则（与蓝图 §12 一致）：

- 技能：按 HARD / ALL_ROUND 两档决策（:func:`assemble_policy_settings` 按
  原始勾选技能数判定：0..4 → HARD，5+ → ALL_ROUND）。
  HARD 只允许已配置焦点系/卡（skill_focus_families 展开 ∪ skill_presets）；
  ALL_ROUND 允许任意目录识别且合法（is_skill_choice_legal）的升级卡，
  焦点系为优先。两档统一用 skill_catalog 排序：
  合法性过滤 → 前置/链条（skill_chain_rank，owned 与存档豁免参与）
  → 存档解锁/减伤核实（skill_penalty_rank / archive unlock）
  → 稀有度（槽位品质缺失/含混时用已核实的目录稀有度兜底）
  → 焦点配置顺序 → 习惯分 → 槽位 index。卡名未读出或刷新指纹不变 → 只
  WAIT/隐藏，禁止放弃技能点；无可选候选且刷新耗尽 → 默认隐藏；
  仅 allow_skill_giveup 才 GIVEUP；
- 羁绊：预设优先 → 接近合成者（set_progress 可验证字段，含 owned 成员清单）
  → 品质降级（quality_order 确定性规则）；unknown 名称绝不冒充词典内羁绊
  （只能 WAIT/REFRESH）；
- 宝物：必拿名单（treasure_must_take，配置缺省时保留旧版「全都要/卡牌大师」
  子串特权）→ 预设 + 套装进度优先（龙珠进度必须来自可验证字段
  set_progress.members/owned）→ 品质序降级；负面效果卡先整体剔除，
  必拿特权只在剔除后名单内生效；无安全候选 → WAIT（有上限）
  → REFRESH → GIVEUP / CLOSE；
- 技能学习优先于羁绊/宝物循环（同帧多面板时由 :func:`panel_priority` 排序）。

安全不变量：

- 不读屏、不点击、无隐式全局状态、无时钟依赖——所有输入显式传入；
- 同一输入恒返回同一 :class:`PolicyDecision`（纯函数；并列优先级用固定
  tie-break：配置顺序 → 槽位 index 升序 → set 名字典序）；
- 返回值仅 :class:`PolicyAction` 枚举 + slot index（:class:`PolicyDecision`），
  绝无坐标/像素/原始文本；
- 技能 SELECT 仅当槽位名通过技能档判定（HARD：焦点集内；ALL_ROUND：目录
  识别且合法），且 confidence >= min_confidence；羁绊/宝物 SELECT 仅当
  ``slot.name`` 非空（词典规范名）且 ``confidence >= min_confidence``——
  unknown 槽位永不直接点击；
- WAIT 有总次数上限（``max_waits``），无安全候选且 WAIT/REFRESH 均耗尽时
  必然落 GIVEUP / CLOSE，禁止无限等待；
- 总期限（时钟）在外部由执行层判定并置 ``session.deadline_exceeded``，
  本模块只做纯布尔判断。

接线（集成波）：识别层输出 PanelCandidates（技能面板附 owned_skill_cards =
本局已学卡名历史）→ ``choose_action(candidates, session)`` → PolicyDecision；
执行层只消费 ``decision.action`` + ``decision.index``，
后置确认后更新 ``SessionState`` 记账（attempts/refreshes/waits）。
运行时装配用 :func:`assemble_policy_settings`（纯函数，无 I/O）。
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from gamescript.skill_catalog import (
    canonical_family,
    card_archive_unlock_level,
    card_rarity,
    card_unlocked_by_archive,
    expand_skill_preset_names,
    family_of,
    is_skill_choice_legal,
    lookup_card,
    names_match,
    normalize_archive_levels,
    skill_chain_rank,
    skill_penalty_rank,
)

PANEL_SKILL = "skill"
PANEL_BOND = "bond"
PANEL_TREASURE = "treasure"
VALID_PANEL_KINDS = frozenset({PANEL_SKILL, PANEL_BOND, PANEL_TREASURE})

# 合成接近度上限：need - have 落在 [1, MAX_SYNTHESIS_GAP] 才视为“接近合成”。
# 1 格之差的套装严格优先于 2 格；超过该上限不进入合成优先（避免把一个刚起步
# 的套装当作合成候选）。
MAX_SYNTHESIS_GAP = 2

# 默认品质序（与 mediator.RARITY_BANDS 对齐：红 > 橙 > 紫 > 蓝 > 白 > 绿）。
# green 在实机宝物面板确有出现（如「双倍神符」绿边），且是最低档；旧版本
# RARITY_BANDS 缺 green 会让绿边卡在品质逻辑里变成「无颜色」。
# 品质带不在序中或缺失的槽位一律排最末（最差），保证确定性。
DEFAULT_QUALITY_ORDER = ("red", "orange", "purple", "blue", "white", "green")

# 羁绊/卡牌白名单语义：
#   "hard" —— 未勾选（不在 presets 内）一律不可选；三槽全未勾选 → 刷新/放弃/隐藏，
#             宁可不拿也不乱拿。用户 2026-08-12 明确要求（"海盗都明确 ban 了还是每次拿"）。
#   "soft" —— 旧行为：预设未命中时仍按套装进度/品质兜底挑一张。
WHITELIST_HARD = "hard"
WHITELIST_SOFT = "soft"
VALID_WHITELIST_MODES = frozenset({WHITELIST_HARD, WHITELIST_SOFT})

# 技能面板白名单语义（按原始勾选技能数由 assemble_policy_settings 派生）：
#   "hard"（0..4 个）—— 只允许已配置焦点系/卡（skill_focus_families 展开 ∪
#              skill_presets），未配置一律不可选；宁可不拿也不乱拿。
#   "all_round"（5+ 个）—— 允许任意目录识别且合法的升级卡；焦点系仍为优先。
# 两档的候选排序统一见 _decide_skill（skill_catalog 前置/链条/存档/稀有度）。
SKILL_MODE_HARD = "hard"
SKILL_MODE_ALL_ROUND = "all_round"
VALID_SKILL_MODES = frozenset({SKILL_MODE_HARD, SKILL_MODE_ALL_ROUND})

# 必拿宝物缺省名单 = 旧版硬编码的「全能宝物」子串特权（2026-08-13 前行为：
# 名字含「全都要」或「卡牌大师」即无视预设秒选）。策略配置缺省时原样保留，
# 不回归；配置提供 must_take_names 时以配置为准（子串匹配、大小写不敏感）。
DEFAULT_TREASURE_MUST_TAKE = ("全都要", "卡牌大师")

# 目录稀有度（中文档）→ 品质带。只映射有证据的档位；未知中文档 → None
# （绝不臆造）。粉/红为后续实机可能出现的更高档（容忍映射，不写死禁用）。
_CATALOG_RARITY_TO_BAND = {
    "白": "white",
    "蓝": "blue",
    "紫": "purple",
    "橙": "orange",
    "粉": "pink",
    "红": "red",
    "绿": "green",
}

# 负面宝物默认判定模式（描述文本中出现即视为负面）。
# 依据：实机宝物面板的效果描述就在卡名下方且可 OCR（如「每消耗500金币，获得1点
# 随机属性」）。按描述判定而非卡名黑名单，可覆盖未见过的新卡。
DEFAULT_NEGATIVE_PATTERNS = (
    "不再获得",
    "不再增长",
    "不再升级",
    "不再提升",
    "无法获得",
    "无法升级",
    "停止获得",
    "停止升级",
    # 2026-08-12：fixtures/treasure_negative/DESCRIPTIONS.json pattern_hints 已证实
    "消耗全部金币",
    "将恒定",
    "杀敌数清0",
    "宝物效果-",
)

# 用户 2026-08-12 逐张确认的负面宝物（拿了会断资源/断成长）。
# 名字判定与描述判定并存：描述读不到时名字仍然拦得住；名字变了描述仍然拦得住。
DEFAULT_NEGATIVE_NAMES = (
    "透支力量",
    "贪婪献祭",
    "金转木",
    "杀敌梭哈",
    "伐木契约",
    "等级优势",
)

# 会话/动作上限默认值（蓝图 §12：技能 3 次免费刷新后放弃；WAIT 有总次数上限；
# 每个 panel episode 有尝试上限）。集成波可用配置覆盖。
DEFAULT_MAX_ATTEMPTS = 12
DEFAULT_MAX_REFRESHES = 3
DEFAULT_MAX_WAITS = 5


class PolicyAction(str, Enum):
    """有限动作枚举。执行层只接受该枚举 + 槽位编号。"""

    SELECT_SLOT = "SELECT_SLOT"  # 点击槽位（index 见 PolicyDecision.index）
    REFRESH = "REFRESH"          # 刷新面板
    GIVEUP = "GIVEUP"            # 放弃面板（面板存在放弃按钮）
    CLOSE = "CLOSE"              # 关闭面板（无放弃按钮 / 必须退出）
    WAIT = "WAIT"                # 本 tick 不输入，下一 tick 重观察（有上限）
    NONE = "NONE"                # 无面板/无候选：什么都不做


@dataclass(frozen=True)
class PolicyDecision:
    """策略输出：动作 + 槽位编号 + trace 理由。"""

    action: PolicyAction
    index: int | None = None
    reason: str = ""

    @classmethod
    def select(cls, index: int, reason: str = "") -> "PolicyDecision":
        return cls(PolicyAction.SELECT_SLOT, int(index), reason)


@dataclass(frozen=True)
class SlotCandidate:
    """识别层输出的单个候选槽位（结构化；绝不含像素坐标）。"""

    index: int
    name: str | None = None       # 词典规范名；None 表示 unknown（绝不可点击）
    confidence: float = 0.0
    evidence: str = ""            # trace：证据说明（ROI/锚点/帧号等）
    rarity: str | None = None     # 品质带（red/orange/purple/blue/white/green 或 SSR/SR/R/N…）
    description: str = ""         # 卡面效果描述原文（宝物负面判定用；识别层填，可为空）


@dataclass(frozen=True)
class PolicySettings:
    """策略配置（预设/品质序）。所有字段显式传入，缺省用保守默认。"""

    skill_presets: tuple[str, ...] = ()
    bond_presets: tuple[str, ...] = ()
    treasure_presets: tuple[str, ...] = ()
    quality_order: tuple[str, ...] = DEFAULT_QUALITY_ORDER
    min_confidence: float = 0.0   # 可点击下限；低于该置信度的槽位不可选
    # 羁绊/卡牌白名单语义（默认硬禁用：未勾选一律不选）。
    bond_whitelist_mode: str = WHITELIST_HARD
    # 宝物负面描述模式；命中即视为负面。
    treasure_negative_patterns: tuple[str, ...] = DEFAULT_NEGATIVE_PATTERNS
    # 已确认的负面宝物名单（与描述判定并存，互为冗余）。
    treasure_negative_names: tuple[str, ...] = DEFAULT_NEGATIVE_NAMES
    # 负面宝物放行名单（UI 里折叠勾选后才进来）：只有名字在此名单内的负面宝物才可选。
    treasure_allow_negative: tuple[str, ...] = ()
    # 本地习惯权重：规范名 → 分数。仅在已允许集合内做 tie-break；空 = 行为与旧版一致。
    habit_name_scores: tuple[tuple[str, float], ...] = ()
    allow_skill_giveup: bool = False
    # 技能面板白名单档：hard（仅焦点系/卡）| all_round（目录合法卡，焦点优先）。
    # 运行时由 assemble_policy_settings 按原始勾选技能数派生；直接构造缺省 hard
    # （与旧「仅预设」行为一致，源兼容）。
    skill_whitelist_mode: str = SKILL_MODE_HARD
    # 焦点技能系（原始勾选的主技能中文名，配置顺序即用户意图）。
    skill_focus_families: tuple[str, ...] = ()
    # 各系存档等级（不可变 (名称, 等级) 对；由 skill_catalog 消费，用于
    # 前置豁免 / 减伤核实 / 进池门槛）。空 = 未知，走最保守排序，绝不放宽。
    skill_archive_levels: tuple[tuple[str, int], ...] = ()
    # 必拿宝物名单（子串匹配、大小写不敏感）；缺省保留旧版全能宝物特权。
    treasure_must_take: tuple[str, ...] = DEFAULT_TREASURE_MUST_TAKE

    def __post_init__(self) -> None:
        if self.bond_whitelist_mode not in VALID_WHITELIST_MODES:
            raise ValueError(
                f"bond_whitelist_mode={self.bond_whitelist_mode!r} "
                f"not in {sorted(VALID_WHITELIST_MODES)}"
            )
        if self.skill_whitelist_mode not in VALID_SKILL_MODES:
            raise ValueError(
                f"skill_whitelist_mode={self.skill_whitelist_mode!r} "
                f"not in {sorted(VALID_SKILL_MODES)}"
            )
        # 存档等级归一为 (名称, 等级) 对并按名称字典序排列（确定性）。
        object.__setattr__(
            self,
            "skill_archive_levels",
            tuple(sorted(normalize_archive_levels(self.skill_archive_levels).items())),
        )

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> "PolicySettings":
        """从任意映射（如 settings 配置对象/JSON）确定性构造。

        未知键忽略；缺失键取默认；列表顺序即用户配置顺序（有意义，不排序）。
        """
        if raw is None:
            return cls()
        if isinstance(raw, PolicySettings):
            return raw
        qo = raw.get("quality_order")
        neg = raw.get("treasure_negative_patterns")
        neg_names = raw.get("treasure_negative_names")
        must_take = raw.get("treasure_must_take")
        habit_raw = raw.get("habit_name_scores") or {}
        if isinstance(habit_raw, Mapping):
            habit_scores = tuple(
                (str(k), float(v)) for k, v in habit_raw.items()
            )
        else:
            habit_scores = tuple(
                (str(k), float(v)) for k, v in (habit_raw or ())
            )
        min_conf = raw.get("min_confidence")
        bond_mode = raw.get("bond_whitelist_mode")
        skill_mode = raw.get("skill_whitelist_mode")
        return cls(
            skill_presets=tuple(str(s) for s in (raw.get("skill_presets") or ())),
            bond_presets=tuple(str(s) for s in (raw.get("bond_presets") or ())),
            treasure_presets=tuple(str(s) for s in (raw.get("treasure_presets") or ())),
            quality_order=(
                tuple(str(s) for s in qo) if qo is not None else DEFAULT_QUALITY_ORDER
            ),
            min_confidence=0.0 if min_conf is None else float(min_conf),
            bond_whitelist_mode=WHITELIST_HARD if bond_mode is None else str(bond_mode),
            treasure_negative_patterns=(
                tuple(str(s) for s in neg)
                if neg is not None
                else DEFAULT_NEGATIVE_PATTERNS
            ),
            treasure_negative_names=(
                tuple(str(s) for s in neg_names)
                if neg_names is not None
                else DEFAULT_NEGATIVE_NAMES
            ),
            treasure_allow_negative=tuple(
                str(s) for s in (raw.get("treasure_allow_negative") or ())
            ),
            habit_name_scores=habit_scores,
            allow_skill_giveup=bool(raw.get("allow_skill_giveup", False)),
            skill_whitelist_mode=SKILL_MODE_HARD if skill_mode is None else str(skill_mode),
            skill_focus_families=tuple(
                str(s) for s in (raw.get("skill_focus_families") or ())
            ),
            skill_archive_levels=normalize_archive_levels(
                raw.get("skill_archive_levels")
            ),
            treasure_must_take=(
                tuple(str(s) for s in must_take)
                if must_take is not None
                else DEFAULT_TREASURE_MUST_TAKE
            ),
        )


def assemble_policy_settings(
    *,
    settings: Any,
    skill_labels: Mapping[str, Any],
    fetter_labels: Mapping[str, Any],
    policy_doc: Mapping[str, Any] | None,
    habit_name_scores: tuple[tuple[str, float], ...] = (),
) -> PolicySettings:
    """运行时装配 PolicySettings（纯函数，无 I/O；policy_doc 由调用方读入）。

    - ``settings``：运行配置对象（鸭子类型）。读取 ``skills``（技能短码列表）、
      ``cards``（羁绊文件名/短码列表）、``treasure_allow_negative``（负面宝物
      放行名单）、``skill_archive_levels``（{短码: 等级}，可缺省 → 未知）。
    - ``skill_labels``：技能短码 → 中文主技能名（config/skill_labels.json）。
    - ``fetter_labels``：羁绊文件名 stem → 规范名（config/fetter_labels.json）。
    - ``policy_doc``：策略文档（config/choice_policy.json）。解析键：
      ``quality_order`` / ``min_confidence``（缺省 0.60）/
      ``allow_skill_giveup``（缺省 False）/ ``bond.whitelist_mode``（缺省 hard）/
      ``treasure.negative_patterns`` / ``treasure.negative_names`` /
      ``treasure.must_take_names``（缺省保留旧版全能宝物特权）/
      ``treasure.allow_negative``（仅当 settings 未提供放行名单时兜底）。

    模式派生（先数原始勾选技能，再展开）：0..4 个 → HARD（仅焦点系/卡）；
    5+ 个 → ALL_ROUND（目录合法卡，焦点优先）。焦点系 = 勾选短码经
    skill_labels 归一的中文主技能名（配置顺序，去重）；``skill_presets`` =
    焦点系经 skill_catalog.expand_skill_preset_names 展开的卡名集。
    """
    raw = dict(policy_doc or {})
    bond_cfg = raw.get("bond") if isinstance(raw.get("bond"), Mapping) else {}
    treasure_cfg = raw.get("treasure") if isinstance(raw.get("treasure"), Mapping) else {}

    seen: set[str] = set()
    skill_families: list[str] = []
    for code in getattr(settings, "skills", None) or ():
        label = skill_labels.get(code)
        text = str(label or "").strip() if label else ""
        if text and text not in seen:
            seen.add(text)
            skill_families.append(text)
    # 模式按原始勾选技能数判定（展开后卡数再多也不算 all_round）。
    raw_count = len(skill_families)
    mode = SKILL_MODE_ALL_ROUND if raw_count >= 5 else SKILL_MODE_HARD

    bond_presets: list[str] = []
    for item in getattr(settings, "cards", None) or ():
        text = str(item or "").strip()
        if not text:
            continue
        stem = Path(text).stem
        bond_presets.append(str(fetter_labels.get(stem, stem)))

    allow_neg = getattr(settings, "treasure_allow_negative", None)
    if allow_neg is None:
        allow_neg = treasure_cfg.get("allow_negative", ())

    min_conf = raw.get("min_confidence")
    return PolicySettings.from_mapping(
        {
            "skill_presets": expand_skill_preset_names(tuple(skill_families)),
            "skill_focus_families": tuple(skill_families),
            "skill_whitelist_mode": mode,
            "skill_archive_levels": getattr(settings, "skill_archive_levels", None),
            "bond_presets": tuple(bond_presets),
            "treasure_presets": (),
            "quality_order": raw.get("quality_order"),
            "min_confidence": 0.60 if min_conf is None else min_conf,
            "bond_whitelist_mode": bond_cfg.get("whitelist_mode", WHITELIST_HARD),
            "treasure_negative_patterns": treasure_cfg.get("negative_patterns"),
            "treasure_negative_names": treasure_cfg.get("negative_names"),
            "treasure_must_take": treasure_cfg.get("must_take_names"),
            "treasure_allow_negative": tuple(str(s) for s in allow_neg),
            "habit_name_scores": habit_name_scores,
            "allow_skill_giveup": bool(raw.get("allow_skill_giveup", False)),
        }
    )


@dataclass(frozen=True)
class SessionState:
    """本次 panel episode 会话记账（由执行层维护并传入；本模块只读）。

    attempts = 已执行的 UI 动作数（SELECT/REFRESH/GIVEUP/CLOSE）；WAIT 不计入
    （不改变 UI）。总期限（时钟）由执行层判定后置 ``deadline_exceeded``。
    """

    attempts: int = 0
    refreshes: int = 0
    waits: int = 0
    deadline_exceeded: bool = False
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    max_refreshes: int = DEFAULT_MAX_REFRESHES
    max_waits: int = DEFAULT_MAX_WAITS
    last_slot_fingerprint: str | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> "SessionState":
        if raw is None:
            return cls()
        if isinstance(raw, SessionState):
            return raw
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known})


@dataclass(frozen=True)
class PanelCandidates:
    """识别层输出的单面板候选。逐面板调用；同帧多面板排序见 :func:`panel_priority`。

    ``refresh_count``：识别层可验证的“本面板已刷新次数”（可为 0）；
    与 ``SessionState.refreshes`` 的关系见 :func:`choose_action`。
    """

    panel_kind: str | None = None  # "skill" | "bond" | "treasure"；None → NONE
    slots: tuple[SlotCandidate, ...] = ()
    set_progress: Mapping[str, Mapping[str, Any]] | None = None
    refresh_count: int = 0
    has_giveup: bool = False
    settings: PolicySettings | Mapping[str, Any] | None = None
    # 本局已学技能卡名历史（执行层维护；用于 skill_catalog 前置/互斥判定）。
    # 缺失历史 = 未知，绝不臆造。
    owned_skill_cards: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.panel_kind is not None and self.panel_kind not in VALID_PANEL_KINDS:
            raise ValueError(
                f"panel_kind={self.panel_kind!r} not in {sorted(VALID_PANEL_KINDS)}"
            )
        # 槽位既接受 SlotCandidate 也接受字典形态 {index, name, confidence,
        # evidence, rarity}（契约文档形态）；确定性：按 index 升序归一。
        object.__setattr__(
            self,
            "slots",
            tuple(
                sorted(
                    (_coerce_slot(s) for s in self.slots),
                    key=lambda s: int(s.index),
                )
            ),
        )
        # 确定性：配置归一为不可变 PolicySettings。
        if not isinstance(self.settings, PolicySettings):
            object.__setattr__(
                self, "settings", PolicySettings.from_mapping(self.settings)
            )
        # 已学卡名：去空串但保留重复次数。部分升级前置明确要求同卡 x2；
        # 去重会把已经满足的前置误判成未满足，破坏链条优先级。
        object.__setattr__(
            self,
            "owned_skill_cards",
            tuple(str(s).strip() for s in self.owned_skill_cards if str(s).strip()),
        )


def _coerce_slot(raw: Any) -> SlotCandidate:
    """SlotCandidate 或字典形态 → SlotCandidate；其它类型直接报错（fail-fast）。"""
    if isinstance(raw, SlotCandidate):
        return raw
    if isinstance(raw, Mapping):
        known = {"index", "name", "confidence", "evidence", "rarity"}
        return SlotCandidate(**{k: v for k, v in raw.items() if k in known})
    raise TypeError(
        f"slot must be SlotCandidate or mapping, got {type(raw).__name__}"
    )


def panel_priority(kinds: Any) -> str | None:
    """同帧多面板时技能优先：skill > bond > treasure（确定性固定序）。

    输入为面板种类可迭代（如 ["treasure", "skill"]）；返回应最先处理的面板
    种类；无任何面板返回 None。集成波按该顺序逐面板调用 :func:`choose_action`，
    技能面板永远先于羁绊/宝物执行。
    """
    present = set(kinds or ())
    for kind in (PANEL_SKILL, PANEL_BOND, PANEL_TREASURE):
        if kind in present:
            return kind
    return None


def choose_action(
    candidates: PanelCandidates | Mapping[str, Any],
    session: SessionState | Mapping[str, Any] | None = None,
) -> PolicyDecision:
    """把结构化候选映射为有限动作。纯函数：同输入恒同输出。

    ``session`` 缺省时以 ``candidates.refresh_count`` 作为已刷新次数
    （其余上限取默认）；显式传入 session 时以 session 记账为准
    （执行层权威计数）。返回 :class:`PolicyDecision`。
    """
    cands = (
        candidates
        if isinstance(candidates, PanelCandidates)
        else PanelCandidates(**dict(candidates))
    )
    state = (
        session
        if isinstance(session, SessionState)
        else SessionState.from_mapping(session)
    )
    if session is None:
        state = SessionState(
            refreshes=int(cands.refresh_count or 0),
            attempts=state.attempts,
            waits=state.waits,
            deadline_exceeded=state.deadline_exceeded,
            max_attempts=state.max_attempts,
            max_refreshes=state.max_refreshes,
            max_waits=state.max_waits,
        )
    settings = cands.settings
    assert isinstance(settings, PolicySettings)

    # 无面板 / 无候选 → 什么都不做。
    if cands.panel_kind is None:
        return PolicyDecision(PolicyAction.NONE, None, "无面板")

    # HARD 档且未配置任何技能（skill_presets / skill_focus_families 均空）：
    # 用户显式零勾选 → 必须在任何 attempts/deadline last-resort 之前裁决 CLOSE，
    # 绝不 GIVEUP/REFRESH/SELECT，也不受 allow_skill_giveup 影响（零配置绝不花技能点）。
    if (
        cands.panel_kind == PANEL_SKILL
        and settings.skill_whitelist_mode == SKILL_MODE_HARD
        and not settings.skill_presets
        and not settings.skill_focus_families
    ):
        return _skill_hold_or_hide("未配置任何技能（HARD 档空配置）")

    # 全局抢占：总期限过期 / 尝试上限耗尽 → 放弃或关闭（不再做任何动作）。
    if state.deadline_exceeded or state.attempts >= state.max_attempts:
        return _giveup_or_close(
            cands,
            "总期限过期或尝试上限耗尽" if state.deadline_exceeded
            else f"尝试次数达上限 {state.max_attempts}",
        )

    if cands.panel_kind == PANEL_SKILL:
        return _decide_skill(cands, state, settings)
    return _decide_collectible(cands, state, settings)


# ---------------------------------------------------------------------------
# 技能面板：HARD（仅焦点系/卡）/ ALL_ROUND（目录合法卡，焦点优先）；
# 空名/指纹不变不得放弃；无可选候选且卡名可读才刷新。
# ---------------------------------------------------------------------------
def slot_fingerprint(slots: tuple[SlotCandidate, ...] | list[SlotCandidate]) -> str:
    parts: list[str] = []
    for slot in slots:
        parts.append(f"{slot.index}:{slot.name or ''}:{slot.rarity or ''}")
    return "|".join(parts)


def _all_skill_names_missing(slots: tuple[SlotCandidate, ...]) -> bool:
    return bool(slots) and all(s.name is None for s in slots)


def _refresh_unchanged(state: SessionState, slots: tuple[SlotCandidate, ...]) -> bool:
    prev = state.last_slot_fingerprint
    return bool(prev) and slot_fingerprint(slots) == prev


def _skill_hold_or_hide(why: str) -> PolicyDecision:
    return PolicyDecision(PolicyAction.CLOSE, None, f"{why}，隐藏（不放弃技能点）")


def _skill_last_resort(
    cands: PanelCandidates, settings: PolicySettings, why: str
) -> PolicyDecision:
    if settings.allow_skill_giveup:
        return _giveup_or_close(cands, why)
    return _skill_hold_or_hide(why)


def _catalog_recognized(name: str) -> bool:
    """目录识别：卡名在升级卡目录或主技能系内。未知名称绝不给点击权。"""
    text = str(name or "").strip()
    if not text:
        return False
    return lookup_card(text) is not None or family_of(text) is not None


def _catalog_rarity_band(name: str) -> str | None:
    """已核实的目录稀有度（中文档）→ 品质带；未核实/未知 → None（不臆造）。"""
    rarity = card_rarity(name)
    if not rarity:
        return None
    return _CATALOG_RARITY_TO_BAND.get(rarity)


def _skill_effective_rarity_rank(
    slot: SlotCandidate, settings: PolicySettings
) -> int:
    """槽位品质缺失/含混时用已核实的目录稀有度兜底；都没有 → 排最末。

    只允许核实证据补位，绝不凭空编造档位。
    """
    if slot.rarity and slot.rarity in settings.quality_order:
        return settings.quality_order.index(slot.rarity)
    band = _catalog_rarity_band(slot.name or "")
    if band and band in settings.quality_order:
        return settings.quality_order.index(band)
    return len(settings.quality_order)


def _skill_archive_unlock_rank(
    name: str, archive_levels: tuple[tuple[str, int], ...]
) -> int:
    """0 = 无进池门槛或门槛已核实解锁；1 = 有门槛但存档未知/未够（fail-closed 排序靠后，不硬拒）。"""
    unlocked = card_unlocked_by_archive(name, archive_levels)
    if unlocked is True:
        return 0
    if card_archive_unlock_level(name) is None:
        return 0
    return 1


def _focus_rank(name: str, settings: PolicySettings) -> int:
    """焦点系配置顺序（越小越优先）：系内卡按焦点系顺序；非焦点排最后。"""
    fam = family_of(name)
    for rank, focus in enumerate(settings.skill_focus_families):
        focus_fam = canonical_family(focus) or family_of(focus)
        if names_match(name, focus) or (fam and focus_fam and fam == focus_fam):
            return rank
    return len(settings.skill_focus_families)

def _skill_focus_presence_rank(name: str, settings: PolicySettings) -> int:
    """0 = 已配置焦点系；1 = 全能模式下允许的非焦点系。"""
    if not settings.skill_focus_families:
        return 0
    return int(_focus_rank(name, settings) >= len(settings.skill_focus_families))



def _skill_config_rank(name: str, settings: PolicySettings) -> int:
    """配置顺序：焦点系非空 → 按焦点系；否则（旧式直接构造）按 skill_presets 顺序。"""
    if settings.skill_focus_families:
        return _focus_rank(name, settings)
    presets = settings.skill_presets
    if name in presets:
        return presets.index(name)
    return len(presets)


def _skill_focus_set(settings: PolicySettings) -> frozenset[str]:
    """HARD 档的焦点集：焦点系展开 ∪ 显式 skill_presets（旧式构造兼容）。"""
    if settings.skill_focus_families:
        expanded = expand_skill_preset_names(settings.skill_focus_families)
    else:
        expanded = settings.skill_presets
    return frozenset(expanded) | frozenset(settings.skill_presets)


def _rank_skill_candidates(
    slots: tuple[SlotCandidate, ...],
    settings: PolicySettings,
    owned: tuple[str, ...],
) -> list[int]:
    """确定性排序全部可选技能槽位，返回升序槽位 index 列表。

    档位判定：

    - HARD：仅焦点集内卡（用户明确勾选，绝不越权）；
    - ALL_ROUND：任意目录识别且合法（is_skill_choice_legal）的升级卡，
      焦点系仍为优先。

    排序键（升序优先）：前置/链条 → 存档减伤核实 → 存档进池门槛 →
    稀有度 → 焦点/非焦点 → 习惯分 → 焦点配置顺序 → 槽位 index。
    unknown / 低置信 / 不合法 / 未识别一律不进入候选（绝不点击）。
    """
    all_round = settings.skill_whitelist_mode == SKILL_MODE_ALL_ROUND
    focus_set = _skill_focus_set(settings)
    habit = dict(settings.habit_name_scores)
    ranked: list[tuple[float, float, float, int, int, float, int, int]] = []
    for slot in slots:
        if slot.name is None or slot.confidence < settings.min_confidence:
            continue
        if all_round:
            if not _catalog_recognized(slot.name):
                continue
        elif slot.name not in focus_set:
            continue
        if not is_skill_choice_legal(slot.name, owned):
            continue
        chain = skill_chain_rank(slot.name, owned, settings.skill_archive_levels)
        penalty = skill_penalty_rank(slot.name, settings.skill_archive_levels)
        archive = _skill_archive_unlock_rank(slot.name, settings.skill_archive_levels)
        rarity = _skill_effective_rarity_rank(slot, settings)
        focus = _skill_focus_presence_rank(slot.name, settings)
        habit_key = -float(habit.get(slot.name, 0.0))
        config = _skill_config_rank(slot.name, settings)
        ranked.append(
            (chain, penalty, archive, rarity, focus, habit_key, config, slot.index)
        )
    ranked.sort()
    return [int(entry[7]) for entry in ranked]


def _decide_skill(
    cands: PanelCandidates, state: SessionState, settings: PolicySettings
) -> PolicyDecision:
    # HARD 档且未配置任何技能（skill_presets / skill_focus_families 均空）：
    # 用户显式零勾选 → 面板无可学内容，直接 CLOSE（不 WAIT 不 REFRESH，
    # 也不受 allow_skill_giveup 影响——零配置绝不花技能点）。
    if (
        settings.skill_whitelist_mode == SKILL_MODE_HARD
        and not settings.skill_presets
        and not settings.skill_focus_families
    ):
        return _skill_hold_or_hide("未配置任何技能（HARD 档空配置）")
    ranked = _rank_skill_candidates(cands.slots, settings, cands.owned_skill_cards)
    if ranked:
        index = ranked[0]
        name = _slot_name(cands.slots, index)
        rarity = _slot_rarity(cands.slots, index) or "未知品质"
        mode = (
            "HARD" if settings.skill_whitelist_mode == SKILL_MODE_HARD else "ALL_ROUND"
        )
        return PolicyDecision.select(
            index,
            f"技能{mode}命中（前置/存档/稀有度优先）：{name}/{rarity} @ slot {index}",
        )
    unread = _all_skill_names_missing(cands.slots) or not any(s.name for s in cands.slots)
    stale = _refresh_unchanged(state, cands.slots)
    if unread:
        if state.waits < state.max_waits:
            return PolicyDecision(
                PolicyAction.WAIT,
                None,
                "技能卡名未读出，等待（不刷新/放弃）",
            )
        return _skill_hold_or_hide("技能卡名未读出")
    if stale:
        if state.waits < state.max_waits:
            return PolicyDecision(
                PolicyAction.WAIT,
                None,
                "刷新后三张卡指纹未变，等待（不刷新/放弃）",
            )
        return _skill_hold_or_hide("刷新后三张卡指纹未变")
    if state.refreshes < state.max_refreshes:
        return PolicyDecision(
            PolicyAction.REFRESH,
            None,
            f"技能无可选候选（已刷新 {state.refreshes}/{state.max_refreshes}），刷新",
        )
    return _skill_last_resort(cands, settings, "刷新耗尽仍无可选技能")


# ---------------------------------------------------------------------------
# 羁绊/宝物面板：预设 → 接近合成 → 品质降级；无安全候选 → WAIT→REFRESH→退出。
# ---------------------------------------------------------------------------
def _decide_collectible(
    cands: PanelCandidates, state: SessionState, settings: PolicySettings
) -> PolicyDecision:
    kind = cands.panel_kind
    presets = (
        settings.bond_presets if kind == PANEL_BOND else settings.treasure_presets
    )
    # 宝物：负面效果卡先整体剔除（未勾选放行则永不进入任何候选路径，
    # 含必拿/预设/套装/品质四条），避免「拿了就断金币/断木材/断升级」。
    if kind == PANEL_TREASURE:
        eligible = _drop_negative_treasures(cands.slots, settings)
        # 必拿特权：treasure_must_take 名单命中（子串、大小写不敏感）→
        # 无视预设直接优先秒选。缺省名单保留旧版「全都要/卡牌大师」行为。
        for slot in eligible:
            if (
                slot.confidence >= settings.min_confidence
                and _is_must_take(slot.name, settings.treasure_must_take)
            ):
                return PolicyDecision.select(
                    slot.index, f"宝物必拿秒选【{slot.name}】 @ slot {slot.index}"
                )
    else:
        eligible = cands.slots
    preset_hit = _match_preset(
        eligible, presets, settings.min_confidence,
        quality_order=settings.quality_order,
        habit_name_scores=settings.habit_name_scores,
    )
    if preset_hit is not None:
        name = _slot_name(cands.slots, preset_hit)
        return PolicyDecision.select(
            preset_hit, f"{kind} 预设命中：{name} @ slot {preset_hit}"
        )

    # 羁绊/卡牌硬禁用：未勾选的一律不选，绝不落到套装/品质兜底。
    # 三槽全未勾选 → WAIT/REFRESH/GIVEUP（宁可不拿也不乱拿）。
    if kind == PANEL_BOND and settings.bond_whitelist_mode == WHITELIST_HARD:
        return _no_safe_candidate(
            cands, state, kind, "白名单外不可选（硬禁用）"
        )

    synth_hit = _match_synthesis(cands, settings.min_confidence, slots=eligible)
    if synth_hit is not None:
        name = _slot_name(cands.slots, synth_hit)
        return PolicyDecision.select(
            synth_hit, f"{kind} 套装进度优先：{name} @ slot {synth_hit}"
        )

    quality_hit = _match_quality(cands, settings, slots=eligible)
    if quality_hit is not None:
        name = _slot_name(cands.slots, quality_hit)
        return PolicyDecision.select(
            quality_hit, f"{kind} 品质降级：{name} @ slot {quality_hit}"
        )

    return _no_safe_candidate(cands, state, kind, "无安全候选")


def _no_safe_candidate(
    cands: PanelCandidates, state: SessionState, kind: str | None, why: str
) -> PolicyDecision:
    """没有可选候选时的统一收口：WAIT（有上限）→ REFRESH → GIVEUP / CLOSE。

    禁止无限等待，也禁止「反正要动一下」式的兜底点击。
    """
    if state.waits < state.max_waits and state.refreshes < state.max_refreshes:
        return PolicyDecision(
            PolicyAction.WAIT,
            None,
            f"{kind} {why}，等待重观察（{state.waits + 1}/{state.max_waits}）",
        )
    if state.refreshes < state.max_refreshes:
        return PolicyDecision(
            PolicyAction.REFRESH,
            None,
            f"{kind} 无安全候选且 WAIT 耗尽，刷新（{state.refreshes + 1}/{state.max_refreshes}）",
        )
    return _giveup_or_close(cands, f"{kind} 无安全候选且刷新耗尽")


# ---------------------------------------------------------------------------
# 匹配原语（全部确定性；并列用固定 tie-break）。
# ---------------------------------------------------------------------------
def _match_preset(
    slots: tuple[SlotCandidate, ...],
    presets: tuple[str, ...],
    min_confidence: float,
    quality_order: tuple[str, ...] = DEFAULT_QUALITY_ORDER,
    rarity_first: bool = False,
    habit_name_scores: tuple[tuple[str, float], ...] = (),
) -> int | None:
    """预设命中；同一预设的多个槽位用稀有度做 tie-break。

    ``rarity_first=False``（羁绊/宝物）：配置顺序优先（用户顺序有意义），
    同一预设名的多个槽位取稀有度更高者，再取最小 index。

    ``rarity_first=True``：稀有度优先——预设集合内先比稀有度
    （红>橙>紫>蓝>白>绿），同稀有度再按配置顺序，最后按 index。
    （技能面板自 HARD/ALL_ROUND 决策接入后不再走本原语，见 _decide_skill。）

    ``habit_name_scores``：仅在上述键并列时影响排序（分数越高越优先）；
    空元组时行为与旧版逐字节一致。不得引入预设外的名字。

    仅匹配名称与预设完全一致的槽位；unknown（name 为 None）永不命中。
    """
    preset_rank = {preset: rank for rank, preset in enumerate(presets)}
    habit = dict(habit_name_scores)
    # (主键, 次键, 习惯分负数, index)
    hits: list[tuple[float, float, float, int]] = []
    for slot in slots:
        if slot.name is None or slot.confidence < min_confidence:
            continue
        rank = preset_rank.get(slot.name)
        if rank is None:
            continue
        rarity_rank = _rarity_rank(slot.rarity, quality_order)
        habit_key = -float(habit.get(slot.name, 0.0))
        if rarity_first:
            # 稀有度 → 习惯分 → 配置序 → index
            hits.append((rarity_rank, habit_key, float(rank), slot.index))
        else:
            # 配置序 → 稀有度 → 习惯分 → index
            hits.append((rank, rarity_rank, habit_key, slot.index))
    if not hits:
        return None
    hits.sort()
    return hits[0][3]


def _rarity_rank(rarity: str | None, quality_order: tuple[str, ...]) -> int:
    """品质带 → 序号（越小越好）；未知/缺失一律排最末，保证确定性。"""
    if rarity and rarity in quality_order:
        return quality_order.index(rarity)
    return len(quality_order)


def _is_must_take(name: str | None, must_take: tuple[str, ...]) -> bool:
    """必拿名单命中：子串匹配、大小写不敏感（与旧版特权语义一致）。"""
    if not name or not must_take:
        return False
    lowered = name.lower()
    return any(token and token.lower() in lowered for token in must_take)


def is_negative_treasure(slot: SlotCandidate, settings: PolicySettings) -> bool:
    """宝物是否带负面效果（拿了会断资源/断成长），且未被勾选放行。

    两条互为冗余的判定，任一命中即为负面：

    1. **已确认名单**（``treasure_negative_names``）：用户逐张确认过的卡
       （透支力量/贪婪献祭/金转木/杀敌梭哈/伐木契约/等级优势）。描述 OCR
       读失败时这条仍然拦得住。
    2. **描述原文模式**（``treasure_negative_patterns``）：实机宝物面板的效果
       描述就在卡名下方且可 OCR，按描述判定能覆盖没见过的新卡（如「获得
       50万金币，5分钟后不再获得金币」）。卡名换皮时这条仍然拦得住。

    描述为空且不在名单内 → 视为非负面（不在本模块凭卡名臆测；识别层负责
    把描述读出来，读不到就由白名单/品质继续把关）。

    勾选放行（``treasure_allow_negative``）优先于上述两条——用户在 UI 折叠区
    显式打勾的负面宝物才允许被选。
    """
    if slot.name and slot.name in settings.treasure_allow_negative:
        return False
    if slot.name and slot.name in settings.treasure_negative_names:
        return True
    text = slot.description or ""
    if not text:
        return False
    return any(pattern in text for pattern in settings.treasure_negative_patterns)


def _drop_negative_treasures(
    slots: tuple[SlotCandidate, ...], settings: PolicySettings
) -> tuple[SlotCandidate, ...]:
    """剔除负面宝物槽位（默认不选；勾选放行的保留）。"""
    return tuple(s for s in slots if not is_negative_treasure(s, settings))


def _match_synthesis(
    cands: PanelCandidates,
    min_confidence: float,
    slots: tuple[SlotCandidate, ...] | None = None,
) -> int | None:
    """接近合成者：need - have 最小（1 格优先）且不超过 MAX_SYNTHESIS_GAP。

    套装进度必须来自可验证字段
    ``set_progress[set] = {have, need, members, owned}``：
    ``owned`` 列出已拥有的成员名，缺失成员 = members - owned；
    没有 ``owned`` 就无法证明“缺哪张”→ 该套装不参与合成优先（绝不猜测，
    与龙珠进度“必须来自可验证字段”一致）。字段缺失/不可解析一律跳过。
    并列按 (gap 升序, set 名字典序, 槽位 index 升序)——与 dict 插入顺序无关。
    """
    prog = cands.set_progress
    if not prog:
        return None
    hits: list[tuple[int, str, int]] = []
    for set_name, info in prog.items():
        if not isinstance(info, Mapping):
            continue
        try:
            have = int(info.get("have", 0))
            need = int(info.get("need", 0))
        except (TypeError, ValueError):
            continue  # 字段不可验证 → 跳过
        gap = need - have
        members_raw = info.get("members")
        owned_raw = info.get("owned")
        # 成员/已拥有清单必须是名称列表（字符串会被拒绝，防字符级误拆）。
        if not isinstance(members_raw, (list, tuple, set, frozenset)) or not members_raw:
            continue
        if owned_raw is None or isinstance(owned_raw, (str, bytes)):
            continue
        if not isinstance(owned_raw, (list, tuple, set, frozenset)):
            continue
        if gap <= 0 or gap > MAX_SYNTHESIS_GAP:
            continue  # 已完成 / 差距过大 → 跳过
        members = tuple(members_raw)
        owned_set = {str(o) for o in owned_raw}
        for slot in (cands.slots if slots is None else slots):
            if (
                slot.name is not None
                and slot.name in members
                and slot.name not in owned_set  # 只选缺失成员，绝不点已拥有
                and slot.confidence >= min_confidence
            ):
                hits.append((gap, str(set_name), slot.index))
    if not hits:
        return None
    hits.sort()  # (gap 升序, set 名字典序, index 升序)
    return hits[0][2]


def _match_quality(
    cands: PanelCandidates,
    settings: PolicySettings,
    slots: tuple[SlotCandidate, ...] | None = None,
) -> int | None:
    """品质降级：quality_order 中 rank 最小者胜；未知/缺失品质带排最末。

    仅词典内规范名（name 非空）且置信度达标者可入选——unknown 绝不点击；
    并列取最小槽位 index。
    """
    best: tuple[int, int] | None = None
    for slot in (cands.slots if slots is None else slots):
        if not slot.name or slot.confidence < settings.min_confidence:
            continue  # unknown / 低置信不可选
        key = (_rarity_rank(slot.rarity, settings.quality_order), slot.index)
        if best is None or key < best:
            best = key
    return best[1] if best is not None else None


def _slot_rarity(slots: tuple[SlotCandidate, ...], index: int) -> str | None:
    for slot in slots:
        if slot.index == index:
            return slot.rarity
    return None


def _slot_name(slots: tuple[SlotCandidate, ...], index: int) -> str:
    for slot in slots:
        if slot.index == index and slot.name:
            return slot.name
    return f"slot{index}"


def _giveup_or_close(cands: PanelCandidates, why: str) -> PolicyDecision:
    if cands.has_giveup:
        return PolicyDecision(PolicyAction.GIVEUP, None, f"{why}，放弃")
    return PolicyDecision(PolicyAction.CLOSE, None, f"{why}，关闭面板")
