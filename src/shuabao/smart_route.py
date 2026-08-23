"""Deterministic four-skill role assignment and adaptive route recommendations.

This module is intentionally UI- and I/O-light. It consumes the verified
``skill_card_knowledge.json`` catalog and caller-provided archive levels, then
produces ranking hints only. It never changes card legality and never emits UI
input, so the choice-policy fail-closed boundary remains authoritative.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

from shuabao.skill_catalog import archive_level_of, canonical_family, family_of, lookup_card


class SkillRole(str, Enum):
    CARRY = "CARRY"
    AMPLIFIER = "AMPLIFIER"


@dataclass(frozen=True)
class SkillRoleAssignment:
    code: str
    family: str
    role: SkillRole
    archive_level: int | None = None


@dataclass(frozen=True)
class RouteRecommendation:
    name: str
    build_id: str | None
    reason: str
    attr_routes: tuple[str, ...] = ()
    exact_match: bool = False


@dataclass(frozen=True)
class RouteEvaluation:
    selected_codes: tuple[str, ...]
    roles: tuple[SkillRoleAssignment, ...]
    recommendations: tuple[RouteRecommendation, ...]
    relevant_attr_routes: tuple[str, ...]

    @property
    def carry(self) -> SkillRoleAssignment | None:
        for item in self.roles:
            if item.role is SkillRole.CARRY:
                return item
        return None

    @property
    def amplifiers(self) -> tuple[SkillRoleAssignment, ...]:
        return tuple(item for item in self.roles if item.role is SkillRole.AMPLIFIER)


def _config_path(name: str) -> Path:
    if getattr(sys, "frozen", False):
        root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
        return root / "config" / name
    return Path(__file__).resolve().parents[2] / "config" / name


@lru_cache(maxsize=1)
def load_skill_knowledge() -> dict[str, Any]:
    """Load the verified 220-card knowledge layer; malformed data fails empty."""
    try:
        data = json.loads(_config_path("skill_card_knowledge.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {"cards": [], "family_to_code": {}}
    if not isinstance(data, dict):
        return {"cards": [], "family_to_code": {}}
    if not isinstance(data.get("cards"), list):
        data["cards"] = []
    if not isinstance(data.get("family_to_code"), dict):
        data["family_to_code"] = {}
    return data


def _arcane_alias(text: str) -> str | None:
    if text.startswith("奥数"):
        return "奥术" + text[2:]
    if text.startswith("奥术"):
        return "奥数" + text[2:]
    return None


def _canonical_family_text(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return str(canonical_family(text) or family_of(text) or text)


def _family_code(family: str, knowledge_doc: Mapping[str, Any] | None = None) -> str:
    doc = knowledge_doc if isinstance(knowledge_doc, Mapping) else load_skill_knowledge()
    mapping = doc.get("family_to_code") if isinstance(doc.get("family_to_code"), Mapping) else {}
    fam = _canonical_family_text(family)
    for key, code in mapping.items():
        key_text = str(key or "").strip()
        if not key_text:
            continue
        if _canonical_family_text(key_text) == fam:
            return str(code or "").strip()
        alias = _arcane_alias(key_text)
        if alias and _canonical_family_text(alias) == fam:
            return str(code or "").strip()
    return ""


def _archive_level(
    code: str,
    family: str,
    archive_levels: Mapping[str, int] | Sequence[tuple[str, int]] | None,
    knowledge_doc: Mapping[str, Any] | None = None,
) -> int | None:
    if not archive_levels:
        return None
    if isinstance(archive_levels, Mapping):
        levels = archive_levels
    else:
        levels = {str(k): v for k, v in archive_levels}
    for key in (code, family, _canonical_family_text(family), _family_code(family, knowledge_doc)):
        if key and key in levels:
            try:
                value = int(levels[key])
            except (TypeError, ValueError):
                continue
            return value if value >= 0 else None
    try:
        return archive_level_of(family or code, archive_levels)
    except Exception:
        return None


def assign_skill_roles(
    selected: Sequence[str],
    archive_levels: Mapping[str, int] | Sequence[tuple[str, int]] | None = None,
    *,
    skill_labels: Mapping[str, str] | None = None,
    knowledge_doc: Mapping[str, Any] | None = None,
    carry_priority: str | None = None,
) -> tuple[SkillRoleAssignment, ...]:
    """Assign one CARRY and remaining selected skills as AMPLIFIER.

    Highest known archive level wins CARRY. Unknown levels rank below known
    levels; ties use user selection order, so script/UI behavior is deterministic.
    When ``carry_priority`` matches one of the selected families it overrides
    the archive-level rule and that family becomes CARRY.
    """
    labels = skill_labels or {}
    items: list[tuple[int, str, str, int | None]] = []
    seen: set[str] = set()
    for index, raw in enumerate(selected):
        code = str(raw or "").strip()
        if not code:
            continue
        label = str(labels.get(code, code) or code).strip()
        family = _canonical_family_text(label)
        identity = family or code
        if identity in seen:
            continue
        seen.add(identity)
        level = _archive_level(code, family or label, archive_levels, knowledge_doc)
        items.append((index, code, family or label, level))
    if not items:
        return ()
    carry_index = max(
        range(len(items)),
        key=lambda pos: (
            -1 if items[pos][3] is None else int(items[pos][3]),
            -items[pos][0],
        ),
    )
    want_carry = _canonical_family_text(str(carry_priority or ""))
    if want_carry:
        forced = next(
            (
                pos
                for pos, (_index, code, family, _level) in enumerate(items)
                if _canonical_family_text(family or code) == want_carry
            ),
            None,
        )
        if forced is not None:
            carry_index = forced
    return tuple(
        SkillRoleAssignment(
            code=code,
            family=family,
            role=SkillRole.CARRY if pos == carry_index else SkillRole.AMPLIFIER,
            archive_level=level,
        )
        for pos, (_index, code, family, level) in enumerate(items)
    )


def _knowledge_card(name: str, knowledge_doc: Mapping[str, Any] | None = None) -> Mapping[str, Any] | None:
    text = str(name or "").strip()
    if not text:
        return None
    doc = knowledge_doc if isinstance(knowledge_doc, Mapping) else load_skill_knowledge()
    for row in doc.get("cards") or []:
        if not isinstance(row, Mapping):
            continue
        candidate = str(row.get("name") or "").strip()
        aliases = tuple(str(a or "").strip() for a in (row.get("aliases") or ()))
        if text == candidate or text in aliases:
            return row
        alt = _arcane_alias(text)
        if alt and (alt == candidate or alt in aliases):
            return row
    card = lookup_card(text)
    return card if isinstance(card, Mapping) else None


def _mentions_family(text: str, family: str) -> bool:
    if not text or not family:
        return False
    variants = {family}
    alias = _arcane_alias(family)
    if alias:
        variants.add(alias)
    return any(item and item in text for item in variants)


def _disabled_family_set(
    disabled_amplifiers: Sequence[str],
    knowledge_doc: Mapping[str, Any] | None = None,
) -> frozenset[str]:
    disabled: set[str] = set()
    doc = knowledge_doc if isinstance(knowledge_doc, Mapping) else load_skill_knowledge()
    reverse = {
        str(code or "").strip(): _canonical_family_text(str(family or ""))
        for family, code in (doc.get("family_to_code") or {}).items()
    }
    for raw in disabled_amplifiers or ():
        text = str(raw or "").strip()
        if text:
            disabled.add(_canonical_family_text(reverse.get(text, text)))
    return frozenset(x for x in disabled if x)


_SUPPORT_TERMS = (
    "受伤+", "易伤", "破甲", "冻结", "冰冻", "燃烧", "眩晕", "减速",
    "移速-", "控制", "冷却-", "范围+", "持续时间+", "目标+", "数量+",
    "次数+", "额外释放", "频率", "间隔降", "连击", "继承全部强化",
)
_CARRY_TERMS = (
    "伤害+", "进化为", "终极", "大招", "额外释放", "数量+", "次数+",
    "分裂", "爆炸", "伤害频率", "继承全部强化",
)


def skill_role_rank(
    card_name: str,
    selected_families: Sequence[str],
    archive_levels: Mapping[str, int] | Sequence[tuple[str, int]] | None = None,
    *,
    disabled_amplifiers: Sequence[str] = (),
    knowledge_doc: Mapping[str, Any] | None = None,
    carry_priority: str = "",
) -> int:
    """Return a role preference bucket for an already-legal card.

    0=strong role fit, 1=neutral, 2=role-downweighted. This helper never
    decides eligibility; caller retains all fail-closed legality checks.
    ``carry_priority`` is forwarded to :func:`assign_skill_roles` and overrides
    the highest-archive-level CARRY rule when it matches a selected family.
    """
    if len(tuple(x for x in selected_families if str(x or "").strip())) != 4:
        return 1
    doc = knowledge_doc if isinstance(knowledge_doc, Mapping) else load_skill_knowledge()
    roles = assign_skill_roles(
        selected_families,
        archive_levels,
        knowledge_doc=doc,
        carry_priority=carry_priority,
    )
    if len(roles) != 4:
        return 1
    row = _knowledge_card(card_name, doc)
    card_family = _canonical_family_text(
        str((row or {}).get("family") or "") or str(family_of(card_name) or "")
    )
    if not card_family:
        return 1
    assignment = next((r for r in roles if _canonical_family_text(r.family) == card_family), None)
    if assignment is None:
        return 1
    disabled = _disabled_family_set(disabled_amplifiers, doc)
    if assignment.role is SkillRole.AMPLIFIER and card_family in disabled:
        return 1

    effect = str((row or {}).get("effect") or "")
    name = str((row or {}).get("name") or card_name or "")
    text = f"{name} {effect}"
    carry = next((r for r in roles if r.role is SkillRole.CARRY), None)
    carry_family = _canonical_family_text(carry.family) if carry is not None else ""
    selected = tuple(_canonical_family_text(r.family) for r in roles)
    other_mentions = sum(
        1 for family in selected
        if family and family != card_family and _mentions_family(text, family)
    )
    cross_synergy = bool(
        carry_family and carry_family != card_family and _mentions_family(text, carry_family)
    ) or other_mentions >= 1
    support_signal = any(term in text for term in _SUPPORT_TERMS)
    own_damage = "伤害+" in text and _mentions_family(text, card_family)
    own_evolution = "进化为" in text and not cross_synergy

    if assignment.role is SkillRole.CARRY:
        if cross_synergy or any(term in text for term in _CARRY_TERMS):
            return 0
        return 1

    if cross_synergy:
        return 0
    if own_evolution:
        return 2
    if support_signal:
        return 0
    if own_damage or ("伤害" in text and not support_signal):
        return 2
    return 1


class RouteEvaluator:
    """Evaluate selected skills against official builds and adaptive role hints."""

    def __init__(
        self,
        *,
        official_builds: Sequence[Mapping[str, Any]] = (),
        attr_routes: Mapping[str, Mapping[str, Any]] | None = None,
        skill_labels: Mapping[str, str] | None = None,
        knowledge_doc: Mapping[str, Any] | None = None,
    ) -> None:
        self.official_builds = tuple(b for b in official_builds if isinstance(b, Mapping))
        self.attr_routes = dict(attr_routes or {})
        self.skill_labels = dict(skill_labels or {})
        self.knowledge_doc = knowledge_doc

    def _routes_for_build(self, build: Mapping[str, Any]) -> tuple[str, ...]:
        cards = {str(x or "").strip() for x in (build.get("cards") or ()) if str(x or "").strip()}
        hits: list[str] = []
        for route_id, spec in self.attr_routes.items():
            if not isinstance(spec, Mapping):
                continue
            route_tokens = {
                str(spec.get("fetter_code") or "").strip(),
                str(spec.get("set_name") or "").strip(),
                str(spec.get("gate_card") or "").strip(),
            }
            route_tokens.update(str(x or "").strip() for x in (spec.get("chain") or ()))
            route_tokens.discard("")
            if cards & route_tokens:
                hits.append(str(route_id))
        return tuple(hits)

    def _fallback_routes(self, selected_codes: Sequence[str], carry_code: str) -> tuple[str, ...]:
        chosen = set(selected_codes)
        magical = {"asj", "asjg", "assx", "tl", "sdl", "dcw", "hq", "byj", "hbj", "bsxx"}
        physical = {"jq", "pg", "ys", "dz", "ljf", "jf"}
        routes: list[str] = []
        if carry_code in physical or len(chosen & physical) > len(chosen & magical):
            if "agility" in self.attr_routes:
                routes.append("agility")
        elif "intelligence" in self.attr_routes:
            routes.append("intelligence")
        if "strength" in self.attr_routes and "strength" not in routes:
            routes.append("strength")
        return tuple(routes[:2])

    def evaluate(
        self,
        selected_codes: Sequence[str],
        archive_levels: Mapping[str, int] | Sequence[tuple[str, int]] | None = None,
        *,
        carry_priority: str | None = None,
    ) -> RouteEvaluation:
        selected = tuple(
            dict.fromkeys(str(x or "").strip() for x in selected_codes if str(x or "").strip())
        )[:4]
        if len(selected) != 4:
            return RouteEvaluation(selected, (), (), ())
        roles = assign_skill_roles(
            selected,
            archive_levels,
            skill_labels=self.skill_labels,
            knowledge_doc=self.knowledge_doc,
            carry_priority=carry_priority,
        )
        carry = next((r for r in roles if r.role is SkillRole.CARRY), None)
        carry_code = carry.code if carry is not None else selected[0]
        carry_name = self.skill_labels.get(carry_code, carry.family if carry else carry_code)

        scored: list[tuple[int, int, int, Mapping[str, Any]]] = []
        selected_set = set(selected)
        for index, build in enumerate(self.official_builds):
            skills = tuple(str(x or "").strip() for x in (build.get("skills") or ()) if str(x or "").strip())
            overlap = len(selected_set & set(skills))
            exact = int(len(skills) == 4 and set(skills) == selected_set)
            if exact or overlap >= 3:
                scored.append((-exact, -overlap, index, build))
        scored.sort()

        recommendations: list[RouteRecommendation] = []
        relevant: list[str] = []
        for neg_exact, neg_overlap, _index, build in scored[:1]:
            routes = self._routes_for_build(build)
            for route in routes:
                if route not in relevant:
                    relevant.append(route)
            exact = neg_exact == -1
            recommendations.append(
                RouteRecommendation(
                    name=str(build.get("name") or build.get("id") or "官方匹配流派"),
                    build_id=str(build.get("id") or "") or None,
                    reason=(
                        "4 技能与官方流派完全匹配；按存档等级自动划分主C/挂件"
                        if exact
                        else f"与官方流派重合 {-neg_overlap}/4；按主C/挂件角色自适应微调"
                    ),
                    attr_routes=routes,
                    exact_match=exact,
                )
            )

        fallback_routes = self._fallback_routes(selected, carry_code)
        for route in fallback_routes:
            if route not in relevant:
                relevant.append(route)
        amplifier_names = "、".join(
            self.skill_labels.get(r.code, r.family) for r in roles if r.role is SkillRole.AMPLIFIER
        )
        adaptive = RouteRecommendation(
            name=f"自适应 · {carry_name}主C + 3挂件",
            build_id=None,
            reason=f"{carry_name}按纯伤害/终极路线；{amplifier_names}优先联动增伤、易伤/控制与覆盖率",
            attr_routes=fallback_routes,
            exact_match=False,
        )
        if not recommendations or recommendations[0].name != adaptive.name:
            recommendations.append(adaptive)
        return RouteEvaluation(
            selected_codes=selected,
            roles=roles,
            recommendations=tuple(recommendations[:2]),
            relevant_attr_routes=tuple(relevant[:2]),
        )
