"""P0 确定性选择策略（蓝图 §12，纯函数）。

本模块只做一件事：把识别层输出的结构化候选，映射为有限动作枚举 + 槽位编号。

规则（与蓝图 §12 一致）：

- 技能：恒定严格档（用户至多勾选 4 系；:func:`assemble_policy_settings` 把
  勾选短码归一为焦点系并展开）。只允许已配置焦点系/卡（skill_focus_families
  展开 ∪ skill_presets），配置外一律不选；宁可不拿也不乱拿。统一用
  skill_catalog 排序：
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
  必拿特权只在剔除后名单内生效；无安全候选 → 直接 CLOSE，由执行层匹配 skill_hide/card_hide 等物理
  隐藏模板退出；不再用 WAIT/REFRESH 微观预算维持阻塞面板；
- 技能学习优先于羁绊/宝物循环（同帧多面板时由 :func:`panel_priority` 排序）。

安全不变量：

- 不读屏、不点击、无隐式全局状态、无时钟依赖——所有输入显式传入；
- 同一输入恒返回同一 :class:`PolicyDecision`（纯函数；并列优先级用固定
  tie-break：配置顺序 → 槽位 index 升序 → set 名字典序）；
- 返回值仅 :class:`PolicyAction` 枚举 + slot index（:class:`PolicyDecision`），
  绝无坐标/像素/原始文本；
- 技能 SELECT 仅当槽位名通过严格档判定（焦点集内：skill_focus_families 展开
  ∪ skill_presets），且 confidence >= min_confidence；羁绊/宝物 SELECT 仅当
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

from shuabao.skill_catalog import (
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
    owned_families,
    prereq_met,
    skill_chain_rank,
    skill_penalty_rank,
    waived_prereq_names,
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
#   "hard" —— 用户显式要求时仍可禁止预设外羁绊；系统必拿特权不受其影响。
#   "soft" —— 长程默认：预设未命中时按套装进度/品质兜底，避免三张都隐藏空手而归。
WHITELIST_HARD = "hard"
WHITELIST_SOFT = "soft"
VALID_WHITELIST_MODES = frozenset({WHITELIST_HARD, WHITELIST_SOFT})

# 真机 2026-08-16 长程证据：祝福即使没有在前端单独勾选也应直接拿。
# 子串匹配覆盖「祝福」「祝福1级/2级/3级」等规范化结果；运行时装配会把
# 这条系统特权与配置合并，因此即使旧配置缺字段也不会丢失。
DEFAULT_BOND_MUST_TAKE = ("祝福",)

# 前四个独立技能系尚未占满时允许从“已入库且 legal”的通用技能池补位；
# 四系已满后恢复严格焦点/预设升级，避免前期因神技未刷出而长期空技能槽。
DEFAULT_SKILL_SLOT_CAP = 4

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

    @property
    def target_slot(self) -> int | None:
        return self.index

    @classmethod
    def select(cls, index: int, reason: str = "") -> "PolicyDecision":
        return cls(PolicyAction.SELECT_SLOT, int(index), reason)

    @classmethod
    def close(cls, reason: str = "") -> "PolicyDecision":
        return cls(PolicyAction.CLOSE, None, reason)

@dataclass(frozen=True)
class SlotCandidate:
    """识别层输出的单个候选槽位（结构化；绝不含像素坐标）。"""

    index: int
    name: str | None = None       # 词典规范名；None 表示 unknown（绝不可点击）
    confidence: float = 0.0
    evidence: str = ""            # trace：证据说明（ROI/锚点/帧号等）
    rarity: str | None = None     # 品质带（red/orange/purple/blue/white/green 或 SSR/SR/R/N…）
    description: str = ""         # 卡面效果描述原文（宝物负面判定用；识别层填，可为空）
    family: str | None = None     # 角标归属系名（如 "奥术箭", "冰霜", "通用"）
    prereq_marker: bool = False   # 是否检测到前置宝石/前置卡标记
    is_new: bool = False          # 是否有 NEW 标记
    skill_level: int | None = None  # 数字技能等级
    card_fact: Any = None         # 关联的 CardFact 实例
    family_source: str = "unknown" # 来源 ("badge" | "legacy_name" | "unknown")
    def to_card_fact(self) -> Any:
        """转换为 Badge-first 的 CardFact 事实对象。"""
        from shuabao.card_fact import CardFact
        if self.card_fact is not None and isinstance(self.card_fact, CardFact):
            return self.card_fact
        fam = self.family
        source = self.family_source
        if not fam and self.name:
            fam = family_of(self.name) or ""
            if fam and source == "unknown":
                source = "legacy_name"
        return CardFact(
            slot=self.index,
            family=str(fam or ""),
            rarity=str(self.rarity or "white"),
            prereq_marker=self.prereq_marker,
            is_new=self.is_new,
            exact_name=self.name,
            skill_level=self.skill_level,
            family_source=source,
        )

@dataclass(frozen=True)
class PolicySettings:
    """策略配置（预设/品质序）。所有字段显式传入，缺省用保守默认。"""

    skill_presets: tuple[str, ...] = ()
    bond_presets: tuple[str, ...] = ()
    treasure_presets: tuple[str, ...] = ()
    quality_order: tuple[str, ...] = DEFAULT_QUALITY_ORDER
    min_confidence: float = 0.0   # 可点击下限；低于该置信度的槽位不可选
    # 羁绊/卡牌白名单语义：长程默认 soft，预设 miss 仍可安全降级。
    bond_whitelist_mode: str = WHITELIST_SOFT
    # 系统必拿羁绊；默认祝福，运行时会与配置做不可删除的并集。
    bond_must_take: tuple[str, ...] = DEFAULT_BOND_MUST_TAKE
    # 宝物负面描述模式；命中即视为负面。
    treasure_negative_patterns: tuple[str, ...] = DEFAULT_NEGATIVE_PATTERNS
    # 已确认的负面宝物名单（与描述判定并存，互为冗余）。
    treasure_negative_names: tuple[str, ...] = DEFAULT_NEGATIVE_NAMES
    # 负面宝物放行名单（UI 里折叠勾选后才进来）：只有名字在此名单内的负面宝物才可选。
    treasure_allow_negative: tuple[str, ...] = ()
    # 本地习惯权重：规范名 → 分数。仅在已允许集合内做 tie-break；空 = 行为与旧版一致。
    habit_name_scores: tuple[tuple[str, float], ...] = ()
    allow_skill_giveup: bool = False
    # 焦点技能系（原始勾选的主技能中文名，配置顺序即用户意图）。
    skill_focus_families: tuple[str, ...] = ()
    # 前四个独立技能系未占满时，允许目录内合法的新技能系做通用补位。
    # 直接构造默认 False 以保持纯函数旧调用兼容；运行时配置默认开启。
    skill_fill_empty_slots: bool = False
    # 各系存档等级（不可变 (名称, 等级) 对；由 skill_catalog 消费，用于
    # 前置豁免 / 减伤核实 / 进池门槛）。空 = 未知，走最保守排序，绝不放宽。
    skill_archive_levels: tuple[tuple[str, int], ...] = ()
    # 必拿宝物名单（子串匹配、大小写不敏感）；缺省保留旧版全能宝物特权。
    treasure_must_take: tuple[str, ...] = DEFAULT_TREASURE_MUST_TAKE
    # 宝物无安全候选时是否允许盲刷。直接构造保持旧兼容=True；运行时装配
    # 默认 False，避免 20260818 无刷新按钮时 REFRESH→零输入永久循环。
    treasure_refresh_on_no_safe: bool = True

    def __post_init__(self) -> None:
        if self.bond_whitelist_mode not in VALID_WHITELIST_MODES:
            raise ValueError(
                f"bond_whitelist_mode={self.bond_whitelist_mode!r} "
                f"not in {sorted(VALID_WHITELIST_MODES)}"
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
        bond_must_take = raw.get("bond_must_take")
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
        return cls(
            skill_presets=tuple(str(s) for s in (raw.get("skill_presets") or ())),
            bond_presets=tuple(str(s) for s in (raw.get("bond_presets") or ())),
            treasure_presets=tuple(str(s) for s in (raw.get("treasure_presets") or ())),
            quality_order=(
                tuple(str(s) for s in qo) if qo is not None else DEFAULT_QUALITY_ORDER
            ),
            min_confidence=0.0 if min_conf is None else float(min_conf),
            bond_whitelist_mode=WHITELIST_SOFT if bond_mode is None else str(bond_mode),
            bond_must_take=tuple(dict.fromkeys(
                DEFAULT_BOND_MUST_TAKE
                + tuple(str(s) for s in (bond_must_take or ()))
            )),
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
            skill_focus_families=tuple(
                str(s) for s in (raw.get("skill_focus_families") or ())
            ),
            skill_fill_empty_slots=bool(raw.get("skill_fill_empty_slots", False)),
            skill_archive_levels=normalize_archive_levels(
                raw.get("skill_archive_levels")
            ),
            treasure_must_take=(
                tuple(str(s) for s in must_take)
                if must_take is not None
                else DEFAULT_TREASURE_MUST_TAKE
            ),
            treasure_refresh_on_no_safe=bool(
                raw.get("treasure_refresh_on_no_safe", True)
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
      ``treasure.refresh_on_no_safe``（缺省 False，禁止无安全候选盲刷）/
      ``treasure.allow_negative``（仅当 settings 未提供放行名单时兜底）。

    技能恒为严格档（无模式字段）：勾选短码经 skill_labels 归一为焦点系
    （配置顺序，去重）；``skill_presets`` = 焦点系经
    skill_catalog.expand_skill_preset_names 展开的卡名集。未配置任何技能
    时两字段均空 → 面板直接 CLOSE（不刷新/不放弃）。
    """
    raw = dict(policy_doc or {})
    skill_cfg = raw.get("skill") if isinstance(raw.get("skill"), Mapping) else {}
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
            "skill_fill_empty_slots": bool(skill_cfg.get("fill_empty_slots", True)),
            "skill_archive_levels": getattr(settings, "skill_archive_levels", None),
            "bond_presets": tuple(bond_presets),
            "treasure_presets": (),
            "quality_order": raw.get("quality_order"),
            "min_confidence": 0.60 if min_conf is None else min_conf,
            "bond_whitelist_mode": (
                getattr(settings, "bond_whitelist_mode", None)
                or bond_cfg.get("whitelist_mode", WHITELIST_SOFT)
            ),
            "bond_must_take": tuple(dict.fromkeys(
                DEFAULT_BOND_MUST_TAKE
                + tuple(str(s) for s in (getattr(settings, "bond_must_take", None) or ()))
                + tuple(str(s) for s in (bond_cfg.get("must_take_names") or ()))
            )),
            "treasure_negative_patterns": treasure_cfg.get("negative_patterns"),
            "treasure_negative_names": treasure_cfg.get("negative_names"),
            "treasure_must_take": treasure_cfg.get("must_take_names"),
            "treasure_allow_negative": tuple(str(s) for s in allow_neg),
            "treasure_refresh_on_no_safe": bool(
                treasure_cfg.get("refresh_on_no_safe", False)
            ),
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
    """SlotCandidate, CardFact 或字典形态 → SlotCandidate；其它类型直接报错（fail-fast）。"""
    if isinstance(raw, SlotCandidate):
        return raw
    if hasattr(raw, "to_slot_candidate") and callable(raw.to_slot_candidate):
        return raw.to_slot_candidate()
    if isinstance(raw, Mapping):
        known = {
            "index", "name", "confidence", "evidence", "rarity",
            "description", "family", "prereq_marker", "is_new",
            "skill_level", "card_fact", "family_source",
        }
        return SlotCandidate(**{k: v for k, v in raw.items() if k in known})
    raise TypeError(
        f"slot must be SlotCandidate, CardFact or mapping, got {type(raw).__name__}"
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

    # 未配置任何技能（skill_presets / skill_focus_families 均空）：用户显式
    # 零勾选 → 必须在任何 attempts/deadline last-resort 之前裁决 CLOSE，
    # 绝不 GIVEUP/REFRESH/SELECT，也不受 allow_skill_giveup 影响（零配置绝不花技能点）。
    if (
        cands.panel_kind == PANEL_SKILL
        and not settings.skill_presets
        and not settings.skill_focus_families
    ):
        return _skill_hold_or_hide("未配置任何技能（HARD 档空配置）")

    # 全局抢占：总期限过期 / 尝试上限耗尽 → 技能面板恒 CLOSE（绝不放弃），其余面板放弃或关闭。
    if state.deadline_exceeded or state.attempts >= state.max_attempts:
        why = (
            "总期限过期或尝试上限耗尽" if state.deadline_exceeded
            else f"尝试次数达上限 {state.max_attempts}"
        )
        if cands.panel_kind == PANEL_SKILL:
            return _skill_hold_or_hide(why)
        return _giveup_or_close(cands, why)
    if cands.panel_kind == PANEL_SKILL:
        return _decide_skill(cands, state, settings)
    return _decide_collectible(cands, state, settings)


# ---------------------------------------------------------------------------
# 技能面板（恒定严格）：只允许焦点集内卡（skill_focus_families 展开 ∪
# skill_presets）；空名/指纹不变不得放弃；无可选候选且卡名可读才刷新。
# ---------------------------------------------------------------------------
def slot_fingerprint(slots: tuple[Any, ...] | list[Any]) -> str:
    parts: list[str] = []
    for slot in slots:
        idx = getattr(slot, "slot", None) if getattr(slot, "index", None) is None else getattr(slot, "index", None)
        if idx is None:
            idx = getattr(slot, "slot", 0)
        card_fact = getattr(slot, "card_fact", None)
        fam = (card_fact.family if card_fact and card_fact.family else getattr(slot, "family", None)) or ""
        name = getattr(slot, "exact_name", None) or getattr(slot, "name", "") or ""
        rarity = getattr(slot, "rarity", "") or ""
        parts.append(f"{idx}:{name}:{fam}:{rarity}")
    return "|".join(parts)


def _all_skill_names_missing(slots: tuple[SlotCandidate, ...]) -> bool:
    if not slots:
        return False
    return all(s.name is None and not (s.card_fact and s.card_fact.family) and not s.family for s in slots)

def _refresh_unchanged(state: SessionState, slots: tuple[SlotCandidate, ...]) -> bool:
    prev = state.last_slot_fingerprint
    return bool(prev) and slot_fingerprint(slots) == prev


def _skill_hold_or_hide(why: str) -> PolicyDecision:
    return PolicyDecision(PolicyAction.CLOSE, None, f"{why}，隐藏（不放弃技能点）")


def _skill_last_resort(
    cands: PanelCandidates, settings: PolicySettings, why: str
) -> PolicyDecision:
    # 技能面板恒定严格且不乱花点：兜底裁决恒为 CLOSE，绝不 GIVEUP 或 REFRESH。
    return _skill_hold_or_hide(why)

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
    """0 = 焦点系内卡；1 = 焦点系展开集内但非焦点系的卡（严格档排序仍区分）。"""
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
    """Return deterministic slot order for legal, focused skill candidates (Badge-first).

    Sorting Rule (Invariant per Phase 2):
      1. family must belong to user's Focus set (0-4 items), otherwise eliminated;
      2. prereq_marker (prerequisite card / prereq marker / verified chain) highest priority;
      3. rarity ranking (red > orange > purple > blue > white > green);
      4. skill_level (when stable/readable);
      5. is_new (NEW preference, default preferred);
      6. user configured skill family preference order / habit scores;
      7. slot index deterministic tie-break.
    """
    focus_families = tuple(
        canonical_family(f) or family_of(f) or f for f in settings.skill_focus_families if f
    )
    focus_set = _skill_focus_set(settings)
    habit = dict(settings.habit_name_scores)
    owned_branch_families = owned_families(owned)
    ranked: list[tuple[int, int, int, int, int, int, int, float, int, int]] = []

    for slot in slots:
        if slot.confidence < settings.min_confidence:
            continue
        # Match family either from card_fact, slot.family, or fallback to catalog family_of(slot.name)
        fam = None
        if slot.card_fact and slot.card_fact.family:
            fam = canonical_family(slot.card_fact.family) or family_of(slot.card_fact.family) or slot.card_fact.family
        elif slot.family:
            fam = canonical_family(slot.family) or family_of(slot.family) or slot.family
        elif slot.name:
            fam = canonical_family(slot.name) or family_of(slot.name)
        # Focus-Miss check: if skill_focus_families configured, family must match focus_families
        if settings.skill_focus_families:
            if not fam or fam not in focus_families:
                # Also allow legacy exact name in expanded focus set if name is present
                if not (slot.name and slot.name in focus_set):
                    continue
        else:
            # Legacy preset mode
            preset_families = {
                canonical_family(f) or family_of(f) or f
                for f in expand_skill_preset_names(settings.skill_presets)
                if f
            }
            preset_families |= {
                canonical_family(p) or family_of(p) or p
                for p in settings.skill_presets
                if p
            }
            preset_families.discard(None)
            preset_families.discard("")
            if slot.name:
                if slot.name not in focus_set:
                    continue
            elif not fam or (preset_families and fam not in preset_families):
                continue

        if slot.name and not is_skill_choice_legal(slot.name, owned):
            continue

        # 1. Prereq marker / verified chain
        has_prereq = False
        if slot.name:
            card_info = lookup_card(slot.name)
            if card_info and card_info.get("prereq"):
                if prereq_met(card_info["prereq"], owned, waived_prereq_names(slot.name, settings.skill_archive_levels)):
                    has_prereq = True
        if not has_prereq:
            if slot.card_fact and slot.card_fact.prereq_marker:
                has_prereq = True
            elif getattr(slot, "prereq_marker", False):
                has_prereq = True
        prereq_rank = 0 if has_prereq else 1

        # 2. Rarity order (red > orange > purple > blue > white > green)
        rarity_rank = _skill_effective_rarity_rank(slot, settings)

        # 3. Skill level (higher level preferred when readable, or 0 if unknown)
        level = 0
        if slot.card_fact and slot.card_fact.skill_level is not None:
            level = slot.card_fact.skill_level
        elif getattr(slot, "skill_level", None) is not None:
            level = getattr(slot, "skill_level")
        level_key = -int(level)

        # 4. is_new preference (0 for is_new, 1 otherwise)
        is_new = False
        if slot.card_fact and slot.card_fact.is_new:
            is_new = True
        elif getattr(slot, "is_new", False):
            is_new = True
        is_new_rank = 0 if is_new else 1

        # 5. User configured skill family preference order
        fam_order_rank = 0
        if settings.skill_focus_families and fam and fam in focus_families:
            fam_order_rank = focus_families.index(fam)
        elif not settings.skill_focus_families and slot.name:
            fam_order_rank = _skill_config_rank(slot.name, settings)
        fam_order_rank = int(fam_order_rank)
        # 严格 6 元组：
        # (prereq_rank, rarity_rank, -skill_level, new_rank, family_preference_rank, slot.index)
        # - prereq_rank: 0=已核实前置满足, 1=前置未核实
        # - rarity_rank: 0=red ... 5=green, unknown=6（按 quality_order 索引，缺失/未知排最末）
        # - -skill_level: 等级高者优先（5 级优先于 1 级）
        # - new_rank: 0=新技能, 1=非新技能（或未标记）
        # - family_preference_rank: 0=命中焦点系/拥有系, 1=未命中 (fam_order_rank)
        # - slot.index: 确定性兜底 (0, 1, 2)
        ranked.append(
            (
                prereq_rank,
                rarity_rank,
                level_key,
                is_new_rank,
                fam_order_rank,
                slot.index,
            )
        )
    ranked.sort()
    return [int(entry[5]) for entry in ranked]


def _rank_skill_fill_candidates(
    slots: tuple[SlotCandidate, ...],
    settings: PolicySettings,
    owned: tuple[str, ...],
) -> list[int]:
    """Rank safe *new-family* skills used only while fewer than four families exist.

    This fallback is deliberately narrower than "click any readable text": a card must
    exist in the verified skill catalog, pass the normal legality checks, and belong
    to a family not already confirmed in this round.  It therefore fills empty skill
    slots without turning OCR uncertainty into click authority.
    """
    owned_set = owned_families(owned)
    if len(owned_set) >= DEFAULT_SKILL_SLOT_CAP:
        return []
    ranked: list[tuple[int, int, int, int, int]] = []
    for slot in slots:
        if not slot.name or slot.confidence < settings.min_confidence:
            continue
        card = lookup_card(slot.name)
        if card is None:
            continue
        fam = canonical_family(str(card.get("family") or "")) or family_of(slot.name)
        if not fam or fam in owned_set:
            continue
        if not is_skill_choice_legal(slot.name, owned):
            continue
        level = slot.skill_level
        if level is None and slot.card_fact is not None:
            level = getattr(slot.card_fact, "skill_level", None)
        new_flag = bool(slot.is_new or (slot.card_fact and getattr(slot.card_fact, "is_new", False)))
        ranked.append(
            (
                _skill_effective_rarity_rank(slot, settings),
                skill_chain_rank(slot.name, owned, settings.skill_archive_levels),
                0 if new_flag else 1,
                -int(level or 0),
                int(slot.index),
            )
        )
    ranked.sort()
    return [entry[4] for entry in ranked]


def _decide_skill(
    cands: PanelCandidates, state: SessionState, settings: PolicySettings
) -> PolicyDecision:
    ranked = _rank_skill_candidates(cands.slots, settings, cands.owned_skill_cards)
    if ranked:
        index = ranked[0]
        name = _slot_name(cands.slots, index)
        rarity = _slot_rarity(cands.slots, index) or "未知品质"
        return PolicyDecision.select(
            index,
            f"技能严格命中（前置/存档/稀有度优先）：{name}/{rarity} @ slot {index}",
        )
    owned_family_count = len(owned_families(cands.owned_skill_cards))
    if settings.skill_fill_empty_slots and owned_family_count < DEFAULT_SKILL_SLOT_CAP:
        fill_ranked = _rank_skill_fill_candidates(
            cands.slots, settings, cands.owned_skill_cards
        )
        if fill_ranked:
            index = fill_ranked[0]
            name = _slot_name(cands.slots, index)
            rarity = _slot_rarity(cands.slots, index) or "未知品质"
            return PolicyDecision.select(
                index,
                f"技能槽未满（{owned_family_count}/{DEFAULT_SKILL_SLOT_CAP}），"
                f"通用安全补位：{name}/{rarity} @ slot {index}",
            )
    unread = _all_skill_names_missing(cands.slots)
    stale = _refresh_unchanged(state, cands.slots)
    max_skill_waits = min(state.max_waits, 2)
    if unread:
        if state.waits < max_skill_waits:
            return PolicyDecision(
                PolicyAction.WAIT,
                None,
                "技能卡名未读出，等待（不刷新/放弃）",
            )
        return PolicyDecision(
            PolicyAction.CLOSE,
            None,
            f"技能卡名未读出，已观察 {state.waits} 次，严格关闭面板",
        )
    # 可读槽位均未命中焦点系/预设技能（Focus-Miss）：
    # 技能面板恒定严格：宁可不拿也不乱拿，不消耗刷新次数（REFRESH 不可达），不放弃技能点（GIVEUP 不可达）。
    # 遇到焦点未命中直接关闭面板。
    readable_count = sum(
        1 for s in cands.slots if (
            s.name or (s.card_fact and (getattr(s.card_fact, "exact_name", None) or getattr(s.card_fact, "family", None)))
            or s.family
        )
    )
    if readable_count > 0 and not ranked:
        return PolicyDecision(
            PolicyAction.CLOSE,
            None,
            "技能未命中预设/焦点系且不满足选择条件，关闭面板",
        )
    # 无任何合法候选（如全槽位空名或不可识别），兜底恒定 CLOSE
    return _skill_last_resort(cands, settings, "无预设/焦点技能")

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
        if kind == PANEL_BOND:
            # 系统必拿优先于 whitelist；"祝福" 子串覆盖祝福1/2/3级。
            for slot in eligible:
                if (
                    slot.confidence >= settings.min_confidence
                    and _is_must_take(slot.name, settings.bond_must_take)
                ):
                    return PolicyDecision.select(
                        slot.index,
                        f"羁绊系统必拿【{slot.name}】 @ slot {slot.index}",
                    )
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
    """No safe collectible candidate: close the blocking panel immediately.

    WAIT/REFRESH counters are unsuitable for a blocking modal whose refresh
    affordance may not exist.  The policy therefore emits CLOSE; the mediator
    maps it to verified physical hide templates and keeps one-input-per-tick
    plus mutation confirmation.
    """
    del state  # session counters are telemetry for this terminal decision
    return PolicyDecision(
        PolicyAction.CLOSE,
        None,
        f"{kind} {why}，直接关闭/隐藏面板",
    )

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
    （技能面板自严格档决策接入后不再走本原语，见 _decide_skill。）

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
