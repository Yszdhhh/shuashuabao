"""P0 确定性选择策略（蓝图 §12，纯函数）。

本模块只做一件事：把识别层输出的结构化候选，映射为有限动作枚举 + 槽位编号。

规则（与蓝图 §12 一致）：

- 技能：恒定严格档（用户至多勾选 4 系；:func:`assemble_policy_settings` 把
  勾选短码归一为焦点系并展开）。只允许已配置焦点系/卡（skill_focus_families
  展开 ∪ skill_presets），配置外一律不选；宁可不拿也不乱拿。统一用
  skill_catalog 排序：
  合法性过滤 → 前置/链条（skill_chain_rank，owned 与存档豁免参与）
  → 4 技能角色协同（最高存档等级 CARRY；其余 AMPLIFIER）
  → 存档解锁/减伤核实（skill_penalty_rank / archive unlock）
  → 稀有度（槽位品质缺失/含混时用已核实的目录稀有度兜底）
  → 焦点配置顺序 → 习惯分 → 槽位 index。卡名未读出仅短暂 WAIT；可读的
  焦点未命中恒 CLOSE（不刷新、不放弃、不盲选），默认不补空槽；
- 羁绊：默认硬白名单；预设/必拿优先，再按可验证 set_progress 的 2/4/6
  跨档、剩余缺口、合成奖励排序。free_slots=2 拒绝散卡，=1 只收核心/跨档，
  =0 只收合成或零成本；
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

import math
import re
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
    lookup_rarity,
    names_match,
    normalize_archive_levels,
    owned_families,
    prereq_met,
    skill_chain_rank,
    skill_penalty_rank,
    waived_prereq_names,
)
from shuabao.smart_route import skill_role_rank
from shuabao.policy.mechanics_view import MechanicsPolicyView

PANEL_SKILL = "skill"
PANEL_BOND = "bond"
PANEL_TREASURE = "treasure"
VALID_PANEL_KINDS = frozenset({PANEL_SKILL, PANEL_BOND, PANEL_TREASURE})

MAX_SYNTHESIS_GAP = 2
DEFAULT_QUALITY_ORDER = ("red", "orange", "purple", "blue", "white", "green")
WHITELIST_HARD = "hard"
WHITELIST_SOFT = "soft"
VALID_WHITELIST_MODES = frozenset({WHITELIST_HARD, WHITELIST_SOFT})
DEFAULT_BOND_MUST_TAKE: tuple[str, ...] = ()
DEFAULT_SKILL_SLOT_CAP = 4
DEFAULT_TREASURE_MUST_TAKE = ("全都要", "卡牌大师")
_CATALOG_RARITY_TO_BAND = {
    "白": "white",
    "蓝": "blue",
    "紫": "purple",
    "橙": "orange",
    "粉": "pink",
    "红": "red",
    "绿": "green",
    "N": "green",
    "R": "blue",
    "SR": "purple",
    "SSR": "orange",
    "UR": "red",
    "EX": "red",
}
DEFAULT_NEGATIVE_PATTERNS = (
    "不再获得",
    "不再增长",
    "不再升级",
    "不再提升",
    "无法获得",
    "无法升级",
    "停止获得",
    "停止升级",
    "消耗全部金币",
    "将恒定",
    "杀敌数清0",
    "宝物效果-",
    "攻击间隔",
    "基础攻击间隔",
)
DEFAULT_NEGATIVE_NAMES = (
    "透支力量",
    "贪婪献祭",
    "金转木",
    "杀敌梭哈",
    "伐木契约",
    "等级优势",
)
DEFAULT_MAX_ATTEMPTS = 12
DEFAULT_MAX_REFRESHES = 3
DEFAULT_MAX_WAITS = 5
_BOND_PROGRESS_RE = re.compile(r"(\d+)\s*/\s*(\d+)")
_BOND_NEAR_COMPLETE_CONF = 0.40


from shuabao.interaction_surface import ActionLifecycle


class PolicyAction(str, Enum):
    """有限动作枚举。执行层只接受该枚举 + 槽位编号。"""

    SELECT_SLOT = "SELECT_SLOT"
    REFRESH = "REFRESH"
    GIVEUP = "GIVEUP"
    CLOSE = "CLOSE"
    WAIT = "WAIT"
    NONE = "NONE"


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
    name: str | None = None
    confidence: float = 0.0
    evidence: str = ""
    rarity: str | None = None
    rarity_letter: str | None = None
    description: str = ""
    family: str | None = None
    prereq_marker: bool = False
    is_new: bool = False
    skill_level: int | None = None
    card_fact: Any = None
    family_source: str = "unknown"
    zero_cost: bool = False

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
    # 高级卡只在基础卡已达到目标比例后才进入候选；两者仍共用同一白名单。
    bond_base_presets: tuple[str, ...] = ()
    bond_advanced_presets: tuple[str, ...] = ()
    bond_advanced_groups: tuple[tuple[str, ...], ...] = ()
    # 属性线门卡之后的链路卡（秘法师→法神→湮灭者 等）：在白名单里、任何阶段都可拿，
    # 但不计入基础卡 80% 进度，也不是高级卡组。
    bond_chain_presets: tuple[str, ...] = ()
    bond_base_completion_ratio: float = 0.80
    # 基础卡进度门槛的时间兜底：开局这么多秒后高级卡组不再等基础卡（0 = 关）。
    bond_advanced_unlock_s: float = 0.0
    treasure_presets: tuple[str, ...] = ()
    quality_order: tuple[str, ...] = DEFAULT_QUALITY_ORDER
    min_confidence: float = 0.0
    bond_whitelist_mode: str = WHITELIST_HARD
    bond_must_take: tuple[str, ...] = DEFAULT_BOND_MUST_TAKE
    treasure_negative_patterns: tuple[str, ...] = DEFAULT_NEGATIVE_PATTERNS
    treasure_negative_names: tuple[str, ...] = DEFAULT_NEGATIVE_NAMES
    treasure_allow_negative: tuple[str, ...] = ()
    habit_name_scores: tuple[tuple[str, float], ...] = ()
    allow_skill_giveup: bool = False
    skill_focus_families: tuple[str, ...] = ()
    skill_fill_empty_slots: bool = False
    # 严格白名单未命中时是否在已验证刷新按钮上重抽；仍绝不选配置外技能。
    skill_refresh_on_focus_miss: bool = False
    skill_archive_levels: tuple[tuple[str, int], ...] = ()
    # 挂件协同关闭名单；只改变已合法候选之间的排序，不改变焦点/前置/互斥合法性。
    skill_disabled_amplifiers: tuple[str, ...] = ()
    # 用户技能族优先级（canonical 族名，保序，索引 0 最高）。
    # 空 = 完全回退现有排序键，行为零变化。
    skill_priority: tuple[str, ...] = ()
    # {canonical 族名: route id}；route id 不透明，策略层不做语义解析。空 = 无路线偏好。
    skill_custom_routes: tuple[tuple[str, str], ...] = ()
    # (族名, route id, prefer 标签, avoid 标签)；仅在显式传入 v2 skill_routes 文档时非空。
    skill_route_preferences: tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]], ...] = ()
    treasure_must_take: tuple[str, ...] = DEFAULT_TREASURE_MUST_TAKE
    treasure_refresh_on_no_safe: bool = True
    # Dual-gated KB snapshot. None / empty view never changes ranking.
    mechanics_view: Any = None
    # 运行方式目录 id（normal_farm / lobby_hitch / …）。决定宝物选择裁决分支。
    mode_id: str = "normal_farm"

    def __post_init__(self) -> None:
        if self.bond_whitelist_mode not in VALID_WHITELIST_MODES:
            raise ValueError(
                f"bond_whitelist_mode={self.bond_whitelist_mode!r} "
                f"not in {sorted(VALID_WHITELIST_MODES)}"
            )
        object.__setattr__(
            self,
            "skill_archive_levels",
            tuple(sorted(normalize_archive_levels(self.skill_archive_levels).items())),
        )
        object.__setattr__(
            self,
            "skill_disabled_amplifiers",
            tuple(dict.fromkeys(str(s).strip() for s in self.skill_disabled_amplifiers if str(s).strip())),
        )
        object.__setattr__(
            self,
            "skill_priority",
            tuple(dict.fromkeys(
                canonical_family(s) or family_of(s) or s
                for s in (str(x).strip() for x in self.skill_priority)
                if s
            )),
        )
        object.__setattr__(self, "bond_base_presets", tuple(dict.fromkeys(
            str(s).strip() for s in self.bond_base_presets if str(s).strip()
        )))
        object.__setattr__(self, "bond_advanced_presets", tuple(dict.fromkeys(
            str(s).strip() for s in self.bond_advanced_presets if str(s).strip()
        )))
        object.__setattr__(self, "bond_chain_presets", tuple(dict.fromkeys(
            str(s).strip() for s in self.bond_chain_presets if str(s).strip()
        )))
        object.__setattr__(self, "bond_advanced_groups", tuple(
            tuple(dict.fromkeys(str(s).strip() for s in group if str(s).strip()))
            for group in self.bond_advanced_groups
            if group
        ))
        object.__setattr__(self, "bond_base_completion_ratio", max(
            0.0, min(1.0, float(self.bond_base_completion_ratio))
        ))

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> "PolicySettings":
        """从任意映射（如 settings 配置对象/JSON）确定性构造。"""
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
            habit_scores = tuple((str(k), float(v)) for k, v in habit_raw.items())
        else:
            habit_scores = tuple((str(k), float(v)) for k, v in (habit_raw or ()))
        min_conf = raw.get("min_confidence")
        bond_mode = raw.get("bond_whitelist_mode")
        custom_raw = raw.get("skill_custom_routes")
        if isinstance(custom_raw, Mapping):
            custom_items = tuple(
                (str(k).strip(), str(v).strip())
                for k, v in custom_raw.items()
                if str(k).strip() and str(v).strip()
            )
        else:
            custom_items = tuple(
                (str(k).strip(), str(v).strip())
                for k, v in (custom_raw or ())
                if str(k).strip() and str(v).strip()
            )
        route_prefs_raw = raw.get("skill_route_preferences") or ()
        route_prefs = tuple(
            (
                str(fam).strip(),
                str(rid).strip(),
                tuple(str(t).strip() for t in prefers if str(t).strip()),
                tuple(str(t).strip() for t in avoids if str(t).strip()),
            )
            for fam, rid, prefers, avoids in route_prefs_raw
            if str(fam).strip() and str(rid).strip()
        )
        return cls(
            skill_presets=tuple(str(s) for s in (raw.get("skill_presets") or ())),
            bond_presets=tuple(str(s) for s in (raw.get("bond_presets") or ())),
            bond_base_presets=tuple(str(s) for s in (raw.get("bond_base_presets") or ())),
            bond_advanced_presets=tuple(str(s) for s in (raw.get("bond_advanced_presets") or ())),
            bond_chain_presets=tuple(str(s) for s in (raw.get("bond_chain_presets") or ())),
            bond_advanced_groups=tuple(
                tuple(str(x).strip() for x in group if str(x).strip())
                for group in (raw.get("bond_advanced_groups") or ())
                if group
            ),
            bond_base_completion_ratio=float(raw.get("bond_base_completion_ratio", 0.80)),
            bond_advanced_unlock_s=float(raw.get("bond_advanced_unlock_s", 0.0) or 0.0),
            treasure_presets=tuple(str(s) for s in (raw.get("treasure_presets") or ())),
            quality_order=(tuple(str(s) for s in qo) if qo is not None else DEFAULT_QUALITY_ORDER),
            min_confidence=0.0 if min_conf is None else float(min_conf),
            bond_whitelist_mode=WHITELIST_HARD if bond_mode is None else str(bond_mode),
            bond_must_take=tuple(dict.fromkeys(str(s) for s in (bond_must_take or ()))),
            treasure_negative_patterns=(
                tuple(str(s) for s in neg) if neg is not None else DEFAULT_NEGATIVE_PATTERNS
            ),
            treasure_negative_names=(
                tuple(str(s) for s in neg_names) if neg_names is not None else DEFAULT_NEGATIVE_NAMES
            ),
            skill_priority=tuple(
                str(s).strip() for s in (raw.get("skill_priority") or ()) if str(s).strip()
            ),
            skill_custom_routes=custom_items,
            skill_route_preferences=route_prefs,
            treasure_allow_negative=tuple(str(s) for s in (raw.get("treasure_allow_negative") or ())),
            habit_name_scores=habit_scores,
            allow_skill_giveup=bool(raw.get("allow_skill_giveup", False)),
            skill_focus_families=tuple(str(s) for s in (raw.get("skill_focus_families") or ())),
            skill_fill_empty_slots=bool(raw.get("skill_fill_empty_slots", False)),
            skill_refresh_on_focus_miss=bool(raw.get("skill_refresh_on_focus_miss", False)),
            skill_archive_levels=normalize_archive_levels(raw.get("skill_archive_levels")),
            skill_disabled_amplifiers=tuple(
                str(s) for s in (raw.get("skill_disabled_amplifiers") or ()) if str(s).strip()
            ),
            treasure_must_take=(
                tuple(str(s) for s in must_take) if must_take is not None else DEFAULT_TREASURE_MUST_TAKE
            ),
            mode_id=str(raw.get("mode_id", "normal_farm") or "normal_farm"),
            treasure_refresh_on_no_safe=bool(raw.get("treasure_refresh_on_no_safe", True)),
            mechanics_view=raw.get("mechanics_view"),
        )


# 属性线 = 门卡(4) → 中环(4) → 次环(3) → UR(3)，与 config/official_strategy_defaults.json
# attr_routes.*.chain 一致（tests 校验不漂移）。support 卡（法术/魔法师/箭术…）不是属性线，
# 由看板基础卡组单独勾选。
_ATTRIBUTE_CHAINS = {
    "int": ("智力", "秘法师", "法神", "湮灭者"),
    "str": ("力量", "野蛮人", "战神", "屠戮者"),
    "agi": ("敏捷", "猎魔人", "弓神", "收割者"),
}
_ECONOMY_BOND_ORDER = ("经济", "祝福", "贪婪", "挑战", "成长")
_ATTRIBUTE_IDS = {
    "int": "int", "intelligence": "int", "智力": "int",
    "str": "str", "strength": "str", "力量": "str",
    "agi": "agi", "agility": "agi", "敏捷": "agi",
}


def assemble_policy_settings(
    *,
    settings: Any,
    skill_labels: Mapping[str, Any],
    fetter_labels: Mapping[str, Any],
    policy_doc: Mapping[str, Any] | None,
    habit_name_scores: tuple[tuple[str, float], ...] = (),
    mechanics_view: Any = None,
    skill_routes_doc: Any = None,
) -> PolicySettings:
    """运行时装配 PolicySettings（纯函数，无 I/O；policy_doc / view 由调用方读入）。"""
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

    advanced_names = tuple(
        str(item).strip() for item in (bond_cfg.get("advanced_names") or ()) if str(item).strip()
    )
    # Whitelist order = pick priority (_match_bond_preset ranks by position):
    #   1. economy bonds by payback (KB 2026-09-15 card text: 祝福 nets wood
    #      at once, 经济 ~10 min, 贪婪 key +150 wood, 挑战 indirect, 成长
    #      ~22 min -- outside the 5-5 window)
    #   2. basic cards ticked on the dashboard
    #   3. attribute lines gate -> UR (live 000229: taking them early cost
    #      8-14 extra F draws and ran wood dry at 5:24)
    #   4. advanced packs
    # Attribute-line cards never count toward the 80% basic gate.
    bond_presets: list[str] = []
    economy: list[str] = []
    for item in getattr(settings, "bonds", None) or ():
        text = str(item or "").strip()
        if text and text not in economy:
            economy.append(text)
    economy.sort(key=lambda name: _ECONOMY_BOND_ORDER.index(name) if name in _ECONOMY_BOND_ORDER else len(_ECONOMY_BOND_ORDER))
    bond_presets.extend(economy)
    card_presets: list[str] = []
    for item in getattr(settings, "cards", None) or ():
        text = str(item or "").strip()
        if not text:
            continue
        stem = Path(text).stem
        text = str(fetter_labels.get(stem, stem))
        if text and text not in card_presets:
            card_presets.append(text)
    for text in card_presets:
        if not matches_bond_preset(text, advanced_names) and text not in bond_presets:
            bond_presets.append(text)
    chain_presets: list[str] = []
    for item in getattr(settings, "attributes", None) or ():
        chain = _ATTRIBUTE_CHAINS.get(_ATTRIBUTE_IDS.get(str(item or "").strip(), ""))
        if not chain:
            continue
        for name in chain:
            if name not in bond_presets:
                bond_presets.append(name)
            if name not in chain_presets:
                chain_presets.append(name)
    for text in card_presets:
        if text not in bond_presets:
            bond_presets.append(text)
    catalog_groups: list[tuple[str, ...]] = []
    for group in (bond_cfg.get("advanced_groups") or ()):
        names = tuple(str(x).strip() for x in (group or ()) if str(x).strip())
        if names:
            catalog_groups.append(names)
    selected_groups: list[tuple[str, ...]] = []
    used_groups: set[tuple[str, ...]] = set()
    for item in card_presets:
        for group in catalog_groups:
            if group in used_groups:
                continue
            if item in group or matches_bond_preset(item, group):
                used_groups.add(group)
                selected_groups.append(group)
                for name in group:
                    if name not in bond_presets:
                        bond_presets.append(name)
                break

    advanced_presets = tuple(
        item for item in bond_presets if matches_bond_preset(item, advanced_names)
    )
    base_presets = tuple(
        item for item in bond_presets
        if item not in advanced_presets and item not in chain_presets
    )

    allow_neg = getattr(settings, "treasure_allow_negative", None)
    if allow_neg is None:
        allow_neg = treasure_cfg.get("allow_negative", ())

    # 技能优先级：短码 → 标签 → canonical 族名（与 skill_focus_families 同一标签通道）。
    priority_families: list[str] = []
    for code in getattr(settings, "skill_priority", None) or ():
        label = skill_labels.get(code)
        text = str(label or "").strip() if label else ""
        text = text or str(code or "").strip()
        canon = canonical_family(text) or family_of(text) or text
        if canon and canon not in priority_families:
            priority_families.append(canon)

    # 路线偏好：{短码: route id} → [(canonical 族名, route id)]，保序去重。
    custom_pairs: list[tuple[str, str]] = []
    for code, route_id in (getattr(settings, "skill_custom_routes", None) or {}).items():
        label = skill_labels.get(code)
        text = str(label or "").strip() if label else ""
        text = text or str(code or "").strip()
        canon = canonical_family(text) or family_of(text) or text
        rid = str(route_id or "").strip()
        if canon and rid and all(pair[0] != canon for pair in custom_pairs):
            custom_pairs.append((canon, rid))

    # v2 routes 文档：只为「该族被用户选了路线」的族提取 prefer/avoid 标签。
    route_prefs: list[tuple[str, str, tuple[str, ...], tuple[str, ...]]] = []
    families_doc = (
        skill_routes_doc.get("families") if isinstance(skill_routes_doc, Mapping) else None
    )
    if isinstance(families_doc, Mapping):
        selected_routes = dict(custom_pairs)
        for slug, fam_entry in families_doc.items():
            if not isinstance(fam_entry, Mapping):
                continue
            label = skill_labels.get(str(slug))
            text = str(label or slug or "").strip()
            canon = canonical_family(text) or family_of(text) or text
            want = selected_routes.get(canon)
            if not want:
                continue
            for spec in fam_entry.get("routes") or ():
                if not isinstance(spec, Mapping):
                    continue
                if str(spec.get("id") or "").strip() != want:
                    continue
                route_prefs.append((
                    canon,
                    want,
                    tuple(str(t).strip() for t in (spec.get("prefer") or ()) if str(t).strip()),
                    tuple(str(t).strip() for t in (spec.get("avoid") or ()) if str(t).strip()),
                ))
                break

    min_conf = raw.get("min_confidence")
    return PolicySettings.from_mapping(
        {
            "skill_presets": expand_skill_preset_names(tuple(skill_families)),
            "skill_focus_families": tuple(skill_families),
            "skill_fill_empty_slots": bool(skill_cfg.get("fill_empty_slots", False)),
            "skill_refresh_on_focus_miss": bool(skill_cfg.get("refresh_on_focus_miss", False)),
            "skill_archive_levels": getattr(settings, "skill_archive_levels", None),
            "skill_disabled_amplifiers": getattr(settings, "smart_route_disabled_amplifiers", None),
            "bond_presets": tuple(bond_presets),
            "bond_base_presets": base_presets,
            "bond_advanced_presets": advanced_presets,
            "bond_chain_presets": tuple(chain_presets),
            "bond_advanced_groups": tuple(selected_groups),
            "bond_base_completion_ratio": bond_cfg.get("base_completion_ratio", 0.80),
            "bond_advanced_unlock_s": bond_cfg.get("advanced_unlock_s", 0.0),
            "treasure_presets": (),
            "quality_order": raw.get("quality_order"),
            "min_confidence": 0.60 if min_conf is None else min_conf,
            "bond_whitelist_mode": (
                getattr(settings, "bond_whitelist_mode", None)
                or bond_cfg.get("whitelist_mode", WHITELIST_HARD)
            ),
            "bond_must_take": tuple(dict.fromkeys(
                tuple(str(s) for s in (getattr(settings, "bond_must_take", None) or ()))
                + tuple(str(s) for s in (bond_cfg.get("must_take_names") or ()))
            )),
            "treasure_negative_patterns": treasure_cfg.get("negative_patterns"),
            "treasure_negative_names": treasure_cfg.get("negative_names"),
            "treasure_must_take": treasure_cfg.get("must_take_names"),
            "skill_priority": tuple(priority_families),
            "skill_custom_routes": tuple(custom_pairs),
            "skill_route_preferences": tuple(route_prefs),
            "treasure_allow_negative": tuple(str(s) for s in allow_neg),
            "treasure_refresh_on_no_safe": bool(treasure_cfg.get("refresh_on_no_safe", False)),
            "mode_id": str(getattr(settings, "mode_id", "normal_farm") or "normal_farm"),
            "habit_name_scores": habit_name_scores,
            "allow_skill_giveup": bool(raw.get("allow_skill_giveup", False)),
            "mechanics_view": mechanics_view,
        }
    )


@dataclass(frozen=True)
class SessionState:
    """本次 panel episode 会话记账（由执行层维护并传入；本模块只读）。"""

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
    """识别层输出的单面板候选。逐面板调用；同帧多面板排序见 :func:`panel_priority`。"""

    panel_kind: str | None = None
    slots: tuple[SlotCandidate, ...] = ()
    set_progress: Mapping[str, Any] | None = None
    refresh_count: int = 0
    has_giveup: bool = False
    # 20260822：执行层探测到的刷新按钮可用性。此前该字段从未被填充，
    # REFRESH 分支恒为死代码（羁绊/技能"不刷新"的结构性根因）。
    can_refresh: bool = False
    settings: PolicySettings | Mapping[str, Any] | None = None
    owned_skill_cards: tuple[str, ...] = ()
    owned_bond_cards: tuple[str, ...] = ()
    free_slots: int | None = None
    # Seconds since the round started (None = unknown); drives time releases.
    round_elapsed_s: float | None = None
    def __post_init__(self) -> None:
        if self.panel_kind is not None and self.panel_kind not in VALID_PANEL_KINDS:
            raise ValueError(
                f"panel_kind={self.panel_kind!r} not in {sorted(VALID_PANEL_KINDS)}"
            )
        object.__setattr__(
            self,
            "slots",
            tuple(sorted((_coerce_slot(s) for s in self.slots), key=lambda s: int(s.index))),
        )
        if not isinstance(self.settings, PolicySettings):
            object.__setattr__(self, "settings", PolicySettings.from_mapping(self.settings))
        object.__setattr__(
            self,
            "owned_skill_cards",
            tuple(str(s).strip() for s in self.owned_skill_cards if str(s).strip()),
        )
        object.__setattr__(
            self,
            "owned_bond_cards",
            tuple(str(s).strip() for s in self.owned_bond_cards if str(s).strip()),
        )

def _coerce_slot(raw: Any) -> SlotCandidate:
    if isinstance(raw, SlotCandidate):
        return raw
    if hasattr(raw, "to_slot_candidate") and callable(raw.to_slot_candidate):
        return raw.to_slot_candidate()
    if isinstance(raw, Mapping):
        known = {
            "index", "name", "confidence", "evidence", "rarity",
            "description", "family", "prereq_marker", "is_new",
            "skill_level", "card_fact", "family_source", "zero_cost",
        }
        return SlotCandidate(**{k: v for k, v in raw.items() if k in known})
    raise TypeError(f"slot must be SlotCandidate, CardFact or mapping, got {type(raw).__name__}")


def panel_priority(kinds: Any) -> str | None:
    present = set(kinds or ())
    for kind in (PANEL_SKILL, PANEL_BOND, PANEL_TREASURE):
        if kind in present:
            return kind
    return None


def choose_action(
    candidates: PanelCandidates | Mapping[str, Any],
    session: SessionState | Mapping[str, Any] | None = None,
) -> PolicyDecision:
    cands = candidates if isinstance(candidates, PanelCandidates) else PanelCandidates(**dict(candidates))
    state = session if isinstance(session, SessionState) else SessionState.from_mapping(session)
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

    if cands.panel_kind is None:
        return PolicyDecision(PolicyAction.NONE, None, "无面板")

    # 安全底线：0 预设先于 attempts/deadline 兜底裁决，恒定 CLOSE。
    if (
        cands.panel_kind == PANEL_SKILL
        and not settings.skill_presets
        and not settings.skill_focus_families
    ):
        return _skill_hold_or_hide("未配置任何技能（HARD 档空配置）")

    if state.deadline_exceeded or state.attempts >= state.max_attempts:
        why = (
            "总期限过期或尝试上限耗尽"
            if state.deadline_exceeded
            else f"尝试次数达上限 {state.max_attempts}"
        )
        if cands.panel_kind == PANEL_SKILL:
            return _skill_hold_or_hide(why)
        return _giveup_or_close(cands, why)
    if cands.panel_kind == PANEL_SKILL:
        return _decide_skill(cands, state, settings)
    return _decide_collectible(cands, state, settings)


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




def _skill_hold_or_hide(why: str) -> PolicyDecision:
    return PolicyDecision(PolicyAction.CLOSE, None, f"{why}，隐藏（不放弃技能点）")


def _skill_last_resort(
    cands: PanelCandidates, settings: PolicySettings, why: str
) -> PolicyDecision:
    return _skill_hold_or_hide(why)


def _catalog_rarity_band(name: str) -> str | None:
    rarity = card_rarity(name)
    if not rarity:
        return None
    return _CATALOG_RARITY_TO_BAND.get(rarity)


def _skill_effective_rarity_rank(slot: SlotCandidate, settings: PolicySettings) -> int:
    row = lookup_rarity(slot.name or "")
    if row and str(row.get("face") or "") != "archive_icon":
        band = _CATALOG_RARITY_TO_BAND.get(str(row.get("rarity") or "").strip())
        if band and band in settings.quality_order:
            return settings.quality_order.index(band)
    if slot.rarity and slot.rarity in settings.quality_order:
        return settings.quality_order.index(slot.rarity)
    return len(settings.quality_order)


def _skill_archive_unlock_rank(
    name: str, archive_levels: tuple[tuple[str, int], ...]
) -> int:
    unlocked = card_unlocked_by_archive(name, archive_levels)
    if unlocked is True:
        return 0
    if card_archive_unlock_level(name) is None:
        return 0
    return 1


def _focus_rank(name: str, settings: PolicySettings) -> int:
    fam = family_of(name)
    for rank, focus in enumerate(settings.skill_focus_families):
        focus_fam = canonical_family(focus) or family_of(focus)
        if names_match(name, focus) or (fam and focus_fam and fam == focus_fam):
            return rank
    return len(settings.skill_focus_families)


def _skill_focus_presence_rank(name: str, settings: PolicySettings) -> int:
    if not settings.skill_focus_families:
        return 0
    return int(_focus_rank(name, settings) >= len(settings.skill_focus_families))


def _mechanics_view_of(settings: PolicySettings) -> MechanicsPolicyView:
    view = getattr(settings, "mechanics_view", None)
    if isinstance(view, MechanicsPolicyView):
        return view
    return MechanicsPolicyView.empty()


def _skill_config_rank(name: str, settings: PolicySettings) -> int:
    if settings.skill_focus_families:
        return _focus_rank(name, settings)
    presets = settings.skill_presets
    if name in presets:
        return presets.index(name)
    return len(presets)


def _skill_focus_set(settings: PolicySettings) -> frozenset[str]:
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
    """Return deterministic order for already-legal focused skill candidates.

    The four-skill role bucket is deliberately a *ranking-only* key. It runs
    after strict focus/legality/prerequisite checks and therefore cannot make an
    out-of-focus, mutually exclusive, low-confidence, or unknown card clickable.
    """
    focus_families = tuple(
        canonical_family(f) or family_of(f) or f for f in settings.skill_focus_families if f
    )
    focus_set = _skill_focus_set(settings)
    owned_branch_families = owned_families(owned)
    # 20260822 实机（trace 181735 tick42）：面板出现红色预设主技能「剑气」，
    # 却被已拥有族的紫色堆叠卡（箭矢齐射）以 priority_rank 压过，导致四个
    # 预设主技能整局一个都没主动拿、技能槽全被族内堆叠卡占满（用户口中的"乱拿"）。
    # 未拥有的预设主技能（卡名与焦点族名同名）必须先于一切族内堆叠卡。
    missing_main_names = frozenset(
        name for name in focus_families if name and name not in owned_branch_families
    )
    ranked: list[tuple[int, int, int, int, int, int, int, int, float, int, float, int]] = []
    # 用户技能族优先级 + 路线偏好（均为 ranking-only 键；空值时恒为 0，行为零变化）。
    user_priority_order = {fam: pos for pos, fam in enumerate(settings.skill_priority)}
    habit_scores = dict(settings.habit_name_scores)
    route_pref_by_family = {
        fam: (prefers, avoids)
        for fam, _rid, prefers, avoids in settings.skill_route_preferences
    }

    for slot in slots:
        if slot.confidence < settings.min_confidence:
            continue
        fam = None
        if slot.card_fact and slot.card_fact.family:
            fam = canonical_family(slot.card_fact.family) or family_of(slot.card_fact.family) or slot.card_fact.family
        elif slot.family:
            fam = canonical_family(slot.family) or family_of(slot.family) or slot.family
        elif slot.name:
            fam = canonical_family(slot.name) or family_of(slot.name)

        if settings.skill_focus_families:
            if not fam or fam not in focus_families:
                if not (slot.name and slot.name in focus_set):
                    continue
        else:
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

        view = _mechanics_view_of(settings)
        owned_names = tuple(str(x) for x in owned if str(x).strip())
        chain_keys = tuple(k for k in (str(fam or "").strip(), str(slot.name or "").strip()) if k)
        skip_slot = False
        for chain_id in chain_keys:
            extra_prereqs = view.get_prerequisites(chain_id)
            if extra_prereqs and not all(item in owned_names for item in extra_prereqs):
                skip_slot = True
                break
            mutex = view.get_mutually_exclusive(chain_id)
            if mutex and any(item in owned_names for item in mutex):
                skip_slot = True
                break
        if skip_slot:
            continue

        has_prereq = False
        if slot.name:
            card_info = lookup_card(slot.name)
            if card_info and card_info.get("prereq"):
                if prereq_met(
                    card_info["prereq"],
                    owned,
                    waived_prereq_names(slot.name, settings.skill_archive_levels),
                ):
                    has_prereq = True
        if not has_prereq:
            if slot.card_fact and slot.card_fact.prereq_marker:
                has_prereq = True
            elif getattr(slot, "prereq_marker", False):
                has_prereq = True
        priority_rank = 0 if has_prereq or (fam and fam in owned_branch_families) else 1

        # 智能角色权重：仅恰好 4 个焦点系时生效；其它情况 helper 恒返回 neutral=1。
        role_rank = 1
        if slot.name:
            role_rank = skill_role_rank(
                slot.name,
                settings.skill_focus_families,
                settings.skill_archive_levels,
                disabled_amplifiers=settings.skill_disabled_amplifiers,
                carry_priority=(
                    settings.skill_priority[0] if settings.skill_priority else ""
                ),
            )

        user_priority_rank = (
            user_priority_order.get(fam, len(user_priority_order)) if user_priority_order else 0
        )
        route_score = 0
        route_tags = route_pref_by_family.get(fam)
        if route_tags and (slot.name or slot.description):
            text = f"{slot.name or ''} {slot.description}"
            prefers, avoids = route_tags
            route_score = sum(1 for t in prefers if t in text) - sum(1 for t in avoids if t in text)

        rarity_rank = _skill_effective_rarity_rank(slot, settings)
        level = 0
        if slot.card_fact and slot.card_fact.skill_level is not None:
            level = slot.card_fact.skill_level
        elif getattr(slot, "skill_level", None) is not None:
            level = getattr(slot, "skill_level")
        level_key = -int(level)
        is_new = bool(
            (slot.card_fact and slot.card_fact.is_new) or getattr(slot, "is_new", False)
        )
        is_new_rank = 0 if is_new else 1
        # 习惯分只在合法性、前置、角色、品质、等级和 NEW 状态完全相同时
        # 打破平局；它不能让配置外或低置信候选获得点击权限。
        habit_rank = -float(habit_scores.get(slot.name, 0.0)) if slot.name else 0.0
        fam_order_rank = 0
        if settings.skill_focus_families and fam and fam in focus_families:
            fam_order_rank = focus_families.index(fam)
        elif not settings.skill_focus_families and slot.name:
            fam_order_rank = _skill_config_rank(slot.name, settings)

        modifier = 0.0
        if slot.name:
            modifier = float(view.get_priority_modifier(slot.name) or 0.0)
        # 预设主技能缺失优先键：卡名与焦点族名同名的卡且该主技能尚未拥有 → 0，
        # 其余（含族内堆叠卡）→ 1。此键置于 priority_rank 之前，
        # 保证「先集齐四个预设主技能，再堆叠」的顺序（乱拿修复核心）。
        main_missing_rank = 0 if (missing_main_names and slot.name and slot.name in missing_main_names) else 1
        ranked.append(
            (
                int(main_missing_rank),
                int(priority_rank),
                int(user_priority_rank),
                -int(route_score),
                int(role_rank),
                int(rarity_rank),
                int(level_key),
                int(is_new_rank),
                habit_rank,
                int(fam_order_rank),
                -modifier,
                int(slot.index),
            )
        )
    ranked.sort()
    return [entry[11] for entry in ranked]


def _rank_skill_fill_candidates(
    slots: tuple[SlotCandidate, ...],
    settings: PolicySettings,
    owned: tuple[str, ...],
) -> list[int]:
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
            f"技能严格命中（前置/角色协同/稀有度优先）：{name}/{rarity} @ slot {index}",
        )
    owned_family_count = len(owned_families(cands.owned_skill_cards))
    if settings.skill_fill_empty_slots and owned_family_count < DEFAULT_SKILL_SLOT_CAP:
        fill_ranked = _rank_skill_fill_candidates(cands.slots, settings, cands.owned_skill_cards)
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
    max_skill_waits = min(state.max_waits, 8)
    if unread:
        if state.waits < max_skill_waits:
            return PolicyDecision(PolicyAction.WAIT, None, "技能卡名未读出，等待（不刷新/放弃）")
        return _skill_refresh_or_close(
            cands, state, settings,
            f"技能卡名未读出，已观察 {state.waits} 次",
        )
    readable_count = sum(
        1 for s in cands.slots if (
            s.name
            or (s.card_fact and (
                getattr(s.card_fact, "exact_name", None) or getattr(s.card_fact, "family", None)
            ))
            or s.family
        )
    )
    if readable_count > 0 and not ranked:
        return _skill_refresh_or_close(cands, state, settings, "技能未命中预设/焦点系")
    return _skill_last_resort(cands, settings, "无预设/焦点技能")


def _skill_refresh_or_close(
    cands: PanelCandidates, state: SessionState, settings: PolicySettings, why: str
) -> PolicyDecision:
    if (
        settings.skill_refresh_on_focus_miss
        and (settings.skill_presets or settings.skill_focus_families)
        and cands.can_refresh
        and state.refreshes < state.max_refreshes
    ):
        return PolicyDecision(
            PolicyAction.REFRESH,
            None,
            f"{why}，第 {state.refreshes + 1}/{state.max_refreshes} 次刷新",
        )
    return PolicyDecision(PolicyAction.CLOSE, None, f"{why}，严格关闭面板")


def _slot_stack_progress(slot: SlotCandidate) -> tuple[int, int] | None:
    blob = f"{slot.name or ''} {slot.evidence or ''}"
    hit = _BOND_PROGRESS_RE.search(blob)
    if not hit:
        return None
    have, need = int(hit.group(1)), int(hit.group(2))
    if need > 1:
        return have, need
    return None


_BOND_PROGRESS_RATIO_RE = re.compile(r"[\[（(]\s*\d+\s*/\s*\d+\s*[\])）)]")


def canonical_bond_identity(name: str | None) -> str:
    """返回严格的规范化羁绊卡牌身份名（纯函数）。

    1. 剥离 OCR (x/y) 等级/进度数字串；
    2. 经由 choice_lexicon 查表映射 alias -> canonical；
    3. 若词典未收录，退避为去除进度后缀与多余空白的基础名称；
    4. 绝不使用 substring/family 包含作为身份判定。
    """
    if not name:
        return ""
    text = str(name).strip()
    if not text:
        return ""
    try:
        from shuabao.vision.choice_ocr import lookup_lexicon

        looked = lookup_lexicon(text, kind="bond").canonical
        if looked:
            return looked
    except Exception:
        pass
    return _BOND_PROGRESS_RATIO_RE.sub("", text).strip()


def same_bond_identity(name1: str | None, name2: str | None) -> bool:
    """严格判断两个卡名是否代表同一张羁绊卡（Same Card Identity）。

    必须 canonical card identity 相等，严禁用 preset in text 这种 family substring。
    """
    if not name1 or not name2:
        return False
    c1 = canonical_bond_identity(name1)
    c2 = canonical_bond_identity(name2)
    return bool(c1 and c2 and c1 == c2)


def _near_complete_bond_slots(
    cands: PanelCandidates, settings: PolicySettings
) -> tuple[SlotCandidate, ...]:
    """差一张就能合成的预设/已持有卡，无脑拿。"""
    owned = tuple(str(name).strip() for name in cands.owned_bond_cards if str(name).strip())
    from shuabao.bond_capacity import stack_need

    found: list[SlotCandidate] = []
    for slot in cands.slots:
        name = str(slot.name or "").strip()
        if not name or float(slot.confidence or 0.0) < _BOND_NEAR_COMPLETE_CONF:
            continue
        allowed = matches_bond_preset(name, settings.bond_presets) or any(
            same_bond_identity(name, have) for have in owned
        )
        if not allowed:
            continue
        progress = _slot_stack_progress(slot)
        if progress is None:
            need = stack_need(name)
            have = sum(1 for item in owned if same_bond_identity(name, item))
        else:
            have, need = progress
        if need and have is not None and int(need) - int(have) == 1:
            found.append(slot)
    return tuple(found)


def _is_uncompleted_merge_upgrade(
    slot: SlotCandidate, owned_cards: tuple[str, ...]
) -> bool:
    """已持有羁绊卡是否处于未满星/未完成的待补债合成状态。

    1/4～3/4 或拥有张数未达 need 时返回 True，允许补债；
    若卡片已达完成态（如 4/4、已拥有张数 >= need），返回 False，不得仅因历史 owned 记录无限优先拿。
    使用严格 canonical card identity 匹配，绝不使用 family substring。
    """
    if not slot.name or not owned_cards:
        return False
    matching = [
        b for b in owned_cards
        if b and same_bond_identity(slot.name, b)
    ]
    if not matching:
        return False
    # 若已持有卡中已明确为完成态（如 4/4、已满张），不再视为未完成待补债
    for b in matching:
        hit = _BOND_PROGRESS_RE.search(str(b))
        if hit:
            have_o, need_o = int(hit.group(1)), int(hit.group(2))
            if need_o > 1 and have_o >= need_o:
                return False
    prog = _slot_stack_progress(slot)
    if prog is not None:
        have, need = prog
        if have >= need:
            return False
        return True
    from shuabao.bond_capacity import stack_need

    need = stack_need(slot.name)
    if need is not None:
        have = len(matching)
        if have >= need:
            return False
    return True


def _bond_progress_hits(
    cands: PanelCandidates, slots: tuple[SlotCandidate, ...]
) -> tuple[tuple[SlotCandidate, int, int, str], ...]:
    """Verified (slot, tier-cross rank, remaining gap, set name) facts only."""
    hits: list[tuple[SlotCandidate, int, int, str]] = []
    for set_name, raw_info in (cands.set_progress or {}).items():
        if isinstance(raw_info, int):
            have = raw_info
            need = 2 if have < 2 else (4 if have < 4 else 6)
            info = {"have": have, "need": need, "members": [s.name for s in slots if s.name and (set_name in s.name or set_name in getattr(s.card_fact, "bonds", ()))], "owned": []}
        elif isinstance(raw_info, Mapping):
            info = raw_info
        else:
            continue
        try:
            have, need = int(info.get("have", 0)), int(info.get("need", 0))
        except (TypeError, ValueError):
            continue
        members, owned = info.get("members"), info.get("owned")
        if (
            not isinstance(members, (list, tuple, set, frozenset))
            or not members
            or not isinstance(owned, (list, tuple, set, frozenset))
            or isinstance(owned, (str, bytes))
        ):
            continue
        gap = need - have
        if gap <= 0 or gap > MAX_SYNTHESIS_GAP:
            continue
        owned_names = {str(name) for name in owned}
        tier_rank = 0 if have + 1 in (2, 4, 6) else 1
        for slot in slots:
            if slot.name and slot.name in members and slot.name not in owned_names:
                hits.append((slot, tier_rank, gap - 1, str(set_name)))
    return tuple(hits)


def _bond_capacity_candidates(
    cands: PanelCandidates, slots: tuple[SlotCandidate, ...], settings: PolicySettings
) -> tuple[SlotCandidate, ...]:
    """Apply explicit capacity pressure without guessing a replacement."""
    free = cands.free_slots
    if free is None or free >= 3:
        return slots
    progress = _bond_progress_hits(cands, slots)
    progress_names = {slot.name for slot, _tier, _gap, _set in progress}
    tier_names = {slot.name for slot, tier, _gap, _set in progress if tier == 0}
    owned = tuple(name for name in cands.owned_bond_cards if name)
    kept: list[SlotCandidate] = []
    for slot in slots:
        merge = bool(slot.name and _is_uncompleted_merge_upgrade(slot, owned))
        core = _is_must_take(slot.name, settings.bond_must_take) or matches_bond_preset(
            slot.name, settings.bond_presets
        )
        if free <= 0:
            allowed = merge or slot.zero_cost
        elif free == 1:
            allowed = merge or core or slot.name in tier_names
        else:
            allowed = merge or slot.name in progress_names
        if allowed:
            kept.append(slot)
    return tuple(kept)


def _decide_collectible(
    cands: PanelCandidates, state: SessionState, settings: PolicySettings
) -> PolicyDecision:
    kind = cands.panel_kind
    presets = settings.bond_presets if kind == PANEL_BOND else settings.treasure_presets
    if not any(s.name for s in cands.slots):
        return _no_safe_candidate(cands, state, kind, "卡名未读出/无安全候选")
    if kind == PANEL_TREASURE:
        eligible = _drop_negative_treasures(cands.slots, settings)
        if not eligible:
            return _no_safe_candidate(cands, state, kind, "无安全候选（全部为负面宝物）")

        # 蹭车模式：只拿能交给车队的共享道具
        if getattr(settings, "mode_id", "normal_farm") == "lobby_hitch":
            pick, reason = hitch_treasure_pick(eligible, settings)
            if pick is not None:
                return PolicyDecision.select(pick.index, reason)

        # 普通模式（及蹭车无绿色神符时）：
        # Owner 2026-09-15：EX（ONEPIECE/至高进化/一身神装/满级大佬/全都要/卡牌大师）
        # 出现就拿——EX 本身就是最高品质，不再受边框品质采样约束（d4aa92c 曾限在最高档内）。
        for slot in eligible if getattr(settings, "mode_id", "normal_farm") != "lobby_hitch" else ():
            if (
                slot.confidence >= settings.min_confidence
                and _is_must_take(slot.name, settings.treasure_must_take)
            ):
                return PolicyDecision.select(
                    slot.index, f"宝物必拿秒选【{slot.name}】（EX 不看品质） @ slot {slot.index}"
                )
        # 其余先过滤黑名单，只按现有品质顺序选择，不让 presets / synthesis 压过更高品质。
        best_quality_hit = _match_quality(cands, settings, slots=eligible, allow_unnamed=True)
        if best_quality_hit is None:
            return _no_safe_candidate(cands, state, kind, "无安全候选")

        best_rarity = _slot_rarity(eligible, best_quality_hit)
        best_rank = _rarity_rank(best_rarity, settings.quality_order)
        top_eligible = tuple(
            slot for slot in eligible
            if _rarity_rank(slot.rarity, settings.quality_order) == best_rank
        )

        for slot in top_eligible:
            if (
                slot.confidence >= settings.min_confidence
                and _is_must_take(slot.name, settings.treasure_must_take)
            ):
                return PolicyDecision.select(
                    slot.index, f"宝物必拿秒选【{slot.name}】 @ slot {slot.index}"
                )

        preset_hit = _match_preset(
            top_eligible,
            presets,
            settings.min_confidence,
            quality_order=settings.quality_order,
            habit_name_scores=settings.habit_name_scores,
        )
        if preset_hit is not None:
            name = _slot_name(cands.slots, preset_hit)
            return PolicyDecision.select(preset_hit, f"{kind} 预设命中：{name} @ slot {preset_hit}")

        synth_hit = _match_synthesis(cands, settings.min_confidence, slots=top_eligible)
        if synth_hit is not None:
            name = _slot_name(cands.slots, synth_hit)
            return PolicyDecision.select(synth_hit, f"{kind} 套装进度优先：{name} @ slot {synth_hit}")

        name = _slot_name(cands.slots, best_quality_hit)
        rarity = best_rarity or "未知品质"
        return PolicyDecision.select(best_quality_hit, f"{kind} 品质降级：{name}/{rarity} @ slot {best_quality_hit}")
    else:
        eligible = cands.slots
        if kind == PANEL_BOND:
            near = _near_complete_bond_slots(cands, settings)
            if near:
                slot = max(near, key=lambda item: (float(item.confidence or 0.0), -int(item.index)))
                return PolicyDecision.select(
                    slot.index,
                    f"羁绊差一张合成秒选【{slot.name}】 @ slot {slot.index}",
                )
            eligible = _bond_capacity_candidates(cands, eligible, settings)
            owned_bonds = tuple(str(name).strip() for name in cands.owned_bond_cards if str(name).strip())
            if not _bond_base_ready(cands, settings):
                eligible = tuple(
                    slot for slot in eligible
                    if (
                        matches_bond_preset(slot.name, settings.bond_base_presets)
                        or matches_bond_preset(slot.name, settings.bond_chain_presets)
                        # A past run may already contain an advanced card. Let
                        # its duplicate finish/merge, but never start another.
                        or _is_uncompleted_merge_upgrade(slot, owned_bonds)
                    )
                )
                if not eligible:
                    if state.refreshes < state.max_refreshes and getattr(cands, "can_refresh", False):
                        return PolicyDecision(
                            PolicyAction.REFRESH,
                            None,
                            f"基础羁绊未达 80%，第 {state.refreshes + 1}/{state.max_refreshes} 次刷新",
                        )
                    return _no_safe_candidate(cands, state, kind, "基础羁绊未达 80%，本页无基础卡")
            else:
                active_adv = _active_advanced_presets(cands, settings)
                if settings.bond_advanced_presets and active_adv:
                    eligible = tuple(
                        slot for slot in eligible
                        if (
                            matches_bond_preset(slot.name, settings.bond_base_presets)
                            or matches_bond_preset(slot.name, settings.bond_chain_presets)
                            or matches_bond_preset(slot.name, active_adv)
                            or _is_uncompleted_merge_upgrade(slot, owned_bonds)
                        )
                    )
                    if not eligible:
                        if state.refreshes < state.max_refreshes and getattr(cands, "can_refresh", False):
                            return PolicyDecision(
                                PolicyAction.REFRESH,
                                None,
                                f"当前高级卡组未完成，第 {state.refreshes + 1}/{state.max_refreshes} 次刷新",
                            )
                        return _no_safe_candidate(cands, state, kind, "当前高级卡组未完成，本页无合法卡")
            if settings.bond_whitelist_mode == WHITELIST_HARD:
                eligible = tuple(
                    slot for slot in eligible
                    if _is_must_take(slot.name, settings.bond_must_take)
                    or matches_bond_preset(slot.name, settings.bond_presets)
                    or _is_uncompleted_merge_upgrade(slot, owned_bonds)
                )
        if kind == PANEL_BOND:
            for slot in eligible:
                if (
                    slot.confidence >= settings.min_confidence
                    and _is_must_take(slot.name, settings.bond_must_take)
                ):
                    return PolicyDecision.select(
                        slot.index, f"羁绊系统必拿【{slot.name}】 @ slot {slot.index}"
                    )
            # 20260822：已持有的羁绊卡合成跃升（如 1/3, 2/3 未满星卡牌）
            # 只要手中已持有过某羁绊卡，且当前面板再次出现该卡，优先合成升级，绝不可刷新丢弃！
            for slot in eligible:
                if (
                    slot.confidence >= settings.min_confidence
                    and _is_uncompleted_merge_upgrade(slot, owned_bonds)
                ):
                    return PolicyDecision.select(
                        slot.index, f"羁绊已持有合成优先：{slot.name} @ slot {slot.index}"
                    )
    preset_hit = (
        _match_bond_preset(eligible, presets, settings.min_confidence, settings.quality_order)
        if kind == PANEL_BOND
        else _match_preset(
            eligible,
            presets,
            settings.min_confidence,
            quality_order=settings.quality_order,
            habit_name_scores=settings.habit_name_scores,
        )
    )
    if preset_hit is not None:
        name = _slot_name(cands.slots, preset_hit)
        return PolicyDecision.select(preset_hit, f"{kind} 预设命中：{name} @ slot {preset_hit}")

    if kind == PANEL_BOND:
        # 20260822 实机（trace 181735）：软/硬模式在预设未命中时都先尝试木材刷新，
        # 刷完预算后软模式才回落到套装/品质，硬模式直接收口。
        # 老行为（软模式直接品质降级）导致羁绊整局只拿 4 张且从不刷新。
        if state.refreshes < state.max_refreshes and getattr(cands, "can_refresh", False):
            return PolicyDecision(
                PolicyAction.REFRESH,
                None,
                f"羁绊未命中预设（第 {state.refreshes + 1}/{state.max_refreshes} 次木材刷新）",
            )
        if settings.bond_whitelist_mode == WHITELIST_HARD:
            return _no_safe_candidate(cands, state, kind, "白名单外不可选（硬禁用，刷新已耗尽）")

    synth_hit = _match_synthesis(cands, settings.min_confidence, slots=eligible)
    if synth_hit is not None:
        name = _slot_name(cands.slots, synth_hit)
        return PolicyDecision.select(synth_hit, f"{kind} 套装进度优先：{name} @ slot {synth_hit}")

    # 20260822 实机（trace 203910 20:42:19/22）：宝物面板橙/紫卡 OCR 读不出
    # 名字（conf=0）时品质降级只能在"可读的绿卡"里挑——用户裁决：宝物走红→
    # 橙→紫优先链，未读名的槽位按边框采样稀有度参与排序（按槽位坐标点击）。
    # 羁绊/英雄卡保持"未读名不可选"的安全语义不变。
    quality_hit = _match_quality(
        cands, settings, slots=eligible, allow_unnamed=(kind == PANEL_TREASURE)
    )
    if quality_hit is not None:
        name = _slot_name(cands.slots, quality_hit)
        rarity = _slot_rarity(cands.slots, quality_hit) or "未知品质"
        return PolicyDecision.select(quality_hit, f"{kind} 品质降级：{name}/{rarity} @ slot {quality_hit}")

    return _no_safe_candidate(cands, state, kind, "无安全候选")


def _bond_base_ready(cands: PanelCandidates, settings: PolicySettings) -> bool:
    """高级卡只在已确认取得 80% 配置基础卡后才有选择权（或到了时间兜底）。"""
    bases = settings.bond_base_presets
    if not bases or not settings.bond_advanced_presets:
        return True
    unlock = float(settings.bond_advanced_unlock_s or 0.0)
    elapsed = cands.round_elapsed_s
    if unlock > 0 and elapsed is not None and elapsed >= unlock:
        return True
    required = math.ceil(len(bases) * settings.bond_base_completion_ratio)
    owned = tuple(str(name).strip() for name in cands.owned_bond_cards if str(name).strip())
    completed = sum(
        any(matches_bond_preset(name, (base,)) for name in owned)
        for base in bases
    )
    return completed >= required


def _active_advanced_presets(cands: PanelCandidates, settings: PolicySettings) -> tuple[str, ...]:
    """同一时刻只推进一套高级卡组，顺序取自用户白名单里这套卡第一次出现的位置。"""
    groups = settings.bond_advanced_groups
    if not groups:
        return settings.bond_advanced_presets
    owned = tuple(str(name).strip() for name in cands.owned_bond_cards if str(name).strip())
    for group in groups:
        required = max(1, math.ceil(len(group) * settings.bond_base_completion_ratio))
        have = sum(
            any(matches_bond_preset(name, (card,)) for name in owned)
            for card in group
        )
        if have < required:
            return group
    return groups[-1]


def _no_safe_candidate(
    cands: PanelCandidates, state: SessionState, kind: str | None, why: str
) -> PolicyDecision:
    settings = cands.settings
    if (
        kind == PANEL_TREASURE
        and settings.treasure_refresh_on_no_safe
        and cands.can_refresh
        and state.refreshes < state.max_refreshes
    ):
        return PolicyDecision(
            PolicyAction.REFRESH,
            None,
            f"宝物 {why}，第 {state.refreshes + 1}/{state.max_refreshes} 次刷新",
        )
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
    preset_rank = {preset: rank for rank, preset in enumerate(presets)}
    habit = dict(habit_name_scores)
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
            hits.append((rarity_rank, habit_key, float(rank), slot.index))
        else:
            hits.append((rank, rarity_rank, habit_key, slot.index))
    if not hits:
        return None
    hits.sort()
    return hits[0][3]


def matches_bond_preset(name: str | None, presets: tuple[str, ...]) -> bool:
    """羁绊家族允许“成长”匹配“成长之根”，但空白名单永不放行。"""
    text = str(name or "").strip()
    return bool(text and any(preset and (text == preset or preset in text) for preset in presets))


def _match_bond_preset(
    slots: tuple[SlotCandidate, ...],
    presets: tuple[str, ...],
    min_confidence: float,
    quality_order: tuple[str, ...],
) -> int | None:
    hits: list[tuple[int, int, int]] = []
    for slot in slots:
        if not slot.name or slot.confidence < min_confidence:
            continue
        rank = next(
            (i for i, preset in enumerate(presets) if preset and (slot.name == preset or preset in slot.name)),
            None,
        )
        if rank is not None:
            hits.append((rank, _rarity_rank(slot.rarity, quality_order), slot.index))
    return min(hits)[2] if hits else None


_RARITY_LETTER_TO_BAND = {
    "EX": "red",
    "UR": "red",
    "SSR": "orange",
    "SR": "purple",
    "R": "blue",
    "N": "green",
}


def _rarity_rank(rarity: str | None, quality_order: tuple[str, ...]) -> int:
    if not rarity:
        return len(quality_order)
    if rarity in quality_order:
        return quality_order.index(rarity)
    band = _RARITY_LETTER_TO_BAND.get(str(rarity).upper())
    if band and band in quality_order:
        return quality_order.index(band)
    return len(quality_order)


def _is_must_take(name: str | None, must_take: tuple[str, ...]) -> bool:
    if not name or not must_take:
        return False
    lowered = name.lower()
    return any(token and token.lower() in lowered for token in must_take)


def is_negative_treasure(slot: SlotCandidate, settings: PolicySettings) -> bool:
    if slot.name and slot.name in settings.treasure_allow_negative:
        return False
    if slot.name and (slot.name in settings.treasure_negative_names or slot.name in DEFAULT_NEGATIVE_NAMES or slot.name == "压制"):
        return True
    text = slot.description or ""
    if not text:
        return False
    return any(pattern in text for pattern in settings.treasure_negative_patterns)


#: 蹭车 = 打辅助。羁绊/技能/装备/进化都只强化自己，一律不碰；能交给车队的
#: 只有宝物这一类共享道具。优先级由车主定：神符 > 吞噬丹 > 英雄卡 > 最高品质
#: （EX/传说，预算够就拿），拿到手一律进公共背包。
HITCH_TREASURE_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("神符", "神符"),
    ("吞噬丹", "吞噬丹"),
    ("英雄卡", "英雄卡"),
)


def hitch_treasure_pick(slots, settings):
    """Return (slot, reason) for the first shareable treasure worth taking.

    Named keywords come first in the owner's stated order; the top rarity band
    is the last resort so an EX/legendary still gets picked up when nothing
    named matches.  A slot whose name was not read confidently is never chosen —
    an unnamed pick cannot be justified to the team.
    """
    named = [
        slot for slot in slots
        if slot.confidence >= settings.min_confidence and str(slot.name or "")
    ]
    for keyword, label in HITCH_TREASURE_KEYWORDS:
        for slot in named:
            if keyword in str(slot.name):
                return slot, f"蹭车共享道具·{label}【{slot.name}】 @ slot {slot.index}"
    best_rank = None
    best_slot = None
    for slot in named:
        rank = _rarity_rank(slot.rarity, settings.quality_order)
        if rank >= len(settings.quality_order):
            continue
        if best_rank is None or rank < best_rank:
            best_rank, best_slot = rank, slot
    if best_slot is not None and best_rank == 0:
        return best_slot, f"蹭车共享道具·最高品质【{best_slot.name}】 @ slot {best_slot.index}"
    return None, ""


def _drop_negative_treasures(
    slots: tuple[SlotCandidate, ...], settings: PolicySettings
) -> tuple[SlotCandidate, ...]:
    return tuple(s for s in slots if not is_negative_treasure(s, settings))


def _match_synthesis(
    cands: PanelCandidates,
    min_confidence: float,
    slots: tuple[SlotCandidate, ...] | None = None,
) -> int | None:
    prog = cands.set_progress
    if not prog:
        return None
    hits: list[tuple[int, int, int, str, int]] = []
    owned = {name for name in cands.owned_bond_cards if name}
    for slot, tier_rank, remaining_gap, set_name in _bond_progress_hits(
        cands, cands.slots if slots is None else slots
    ):
        if slot.confidence >= min_confidence:
            merge_rank = 0 if slot.name in owned else 1
            hits.append((tier_rank, remaining_gap, merge_rank, set_name, slot.index))
    if not hits:
        return None
    hits.sort()
    return hits[0][4]


def _match_quality(
    cands: PanelCandidates,
    settings: PolicySettings,
    slots: tuple[SlotCandidate, ...] | None = None,
    allow_unnamed: bool = False,
) -> int | None:
    """品质降级：按稀有度带排序取最优槽位。

    ``allow_unnamed``（仅宝物品质链）：OCR 读不出名字但边框采样到稀有度
    的槽位按坐标参与排序；无名槽必须有正采样稀有度，且同稀有度时有名
    槽优先——避免把"全未知"面板变成盲选。
    """
    best: tuple[int, int, int] | None = None
    for slot in (cands.slots if slots is None else slots):
        if slot.confidence < settings.min_confidence and not (allow_unnamed and slot.rarity):
            continue
        if not slot.name:
            if not allow_unnamed or not slot.rarity:
                continue
        key = (
            _rarity_rank(slot.rarity, settings.quality_order),
            0 if slot.name else 1,
            slot.index,
        )
        if best is None or key < best:
            best = key
    return best[2] if best is not None else None


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
