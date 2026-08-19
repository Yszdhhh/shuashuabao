"""技能升级卡目录：截图入库的「卡名 → 主技能 + 效果」。

供 OCR 套系归属（set_membership）和策略 never_pick / 前置 / 互斥使用。
不读屏、不点击。缺字段的卡不得编造数值。
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

def _config_path(name: str) -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "config" / name
    return Path(__file__).resolve().parents[2] / "config" / name


def _catalog_path() -> Path:
    return _config_path("skill_card_catalog.json")


CATALOG_PATH = _catalog_path()
ARCHIVE_UNLOCKS_PATH = _config_path("skill_archive_unlocks.json")
RARITY_PATH = _config_path("skill_card_rarity.json")


@lru_cache(maxsize=1)
def load_skill_catalog() -> dict[str, Any]:
    try:
        data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {"cards": []}
    if not isinstance(data, dict):
        return {"cards": []}
    cards = data.get("cards")
    if not isinstance(cards, list):
        data["cards"] = []
    return data


def skill_family_map() -> dict[str, str]:
    """规范名/别名 → 主技能中文名（与 skill_labels 一致，如 奥数箭）。"""
    out: dict[str, str] = {}
    for card in load_skill_catalog().get("cards") or []:
        if not isinstance(card, dict):
            continue
        family = str(card.get("family") or "").strip()
        name = str(card.get("name") or "").strip()
        if not family or not name:
            continue
        out[name] = family
        for alias in card.get("aliases") or []:
            text = str(alias).strip()
            if text:
                out[text] = family
    return out


def skill_skip_names() -> tuple[str, ...]:
    names: list[str] = []
    for card in load_skill_catalog().get("cards") or []:
        if isinstance(card, dict) and card.get("never_pick"):
            name = str(card.get("name") or "").strip()
            if name:
                names.append(name)
    return tuple(names)


def _arcane_alias(name: str) -> str | None:
    if name.startswith("奥数"):
        return "奥术" + name[2:]
    if name.startswith("奥术"):
        return "奥数" + name[2:]
    return None


def expand_skill_preset_names(families: tuple[str, ...]) -> tuple[str, ...]:
    """主技能名 + 奥术/奥数别名 + 该系目录卡名，供预设命中（不必只靠 set_name）。"""
    wanted = {str(n).strip() for n in families if str(n).strip()}
    if not wanted:
        return ()
    extra: list[str] = []
    for name in families:
        text = str(name).strip()
        if not text:
            continue
        extra.append(text)
        alias = _arcane_alias(text)
        if alias:
            extra.append(alias)
            wanted.add(alias)
            wanted.add(text)
    for card_name, family in skill_family_map().items():
        if family in wanted or _arcane_alias(family) in wanted:
            extra.append(card_name)
    seen: set[str] = set()
    out: list[str] = []
    for name in extra:
        if name not in seen:
            seen.add(name)
            out.append(name)
    return tuple(out)


_STACK_TOKEN = re.compile(r"^(.*?)x(\d+)$", re.IGNORECASE)


def parse_req_tokens(text: str) -> tuple[tuple[str, int], ...]:
    """``箭矢增幅x2,奥术箭`` → ``(("箭矢增幅", 2), ("奥术箭", 1))``。含「等」的糊条目丢掉。"""
    raw = str(text or "").strip()
    if not raw:
        return ()
    out: list[tuple[str, int]] = []
    for part in raw.replace("，", ",").split(","):
        token = part.strip()
        if not token or "等" in token:
            continue
        match = _STACK_TOKEN.fullmatch(token)
        if match:
            name = match.group(1).strip()
            if name:
                out.append((name, int(match.group(2))))
        else:
            out.append((token, 1))
    return tuple(out)


@lru_cache(maxsize=1)
def _card_index() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for card in load_skill_catalog().get("cards") or []:
        if not isinstance(card, dict):
            continue
        name = str(card.get("name") or "").strip()
        if not name:
            continue
        out[name] = card
        alt = _arcane_alias(name)
        if alt:
            out.setdefault(alt, card)
        for alias in card.get("aliases") or []:
            text = str(alias).strip()
            if text:
                out[text] = card
    return out


def lookup_card(name: str) -> dict[str, Any] | None:
    text = str(name or "").strip()
    if not text:
        return None
    index = _card_index()
    card = index.get(text)
    if card is not None:
        return card
    alt = _arcane_alias(text)
    return index.get(alt) if alt else None


def canonical_family(name: str) -> str | None:
    text = str(name or "").strip()
    if not text:
        return None
    codes = load_skill_catalog().get("family_to_code") or {}
    if text in codes:
        return text
    alt = _arcane_alias(text)
    if alt in codes:
        return alt
    return None


def family_of(name: str) -> str | None:
    fam = canonical_family(name)
    if fam:
        return fam
    card = lookup_card(name)
    if card:
        return str(card.get("family") or "").strip() or None
    mapped = skill_family_map().get(str(name or "").strip())
    return mapped or None


def names_match(left: str, right: str) -> bool:
    a = str(left or "").strip()
    b = str(right or "").strip()
    if not a or not b:
        return False
    if a == b:
        return True
    fa, fb = canonical_family(a), canonical_family(b)
    if fa and fa == fb:
        return True
    ca, cb = lookup_card(a), lookup_card(b)
    if ca is not None and cb is not None and ca is cb:
        return True
    if ca is not None and str(ca.get("name") or "") == b:
        return True
    if cb is not None and str(cb.get("name") or "") == a:
        return True
    return False


def owned_families(owned: Sequence[str]) -> frozenset[str]:
    out: set[str] = set()
    for name in owned:
        fam = family_of(name)
        if fam:
            out.add(canonical_family(fam) or fam)
    return frozenset(out)


def count_owned(token: str, owned: Sequence[str]) -> int:
    return sum(1 for name in owned if names_match(name, token))


def prereq_met(
    prereq: str,
    owned: Sequence[str],
    waived: Sequence[str] = (),
) -> bool:
    tokens = parse_req_tokens(prereq)
    if not tokens:
        return True
    families = owned_families(owned)
    waived_names = tuple(str(n).strip() for n in waived if str(n).strip())
    for token, need in tokens:
        if any(names_match(token, w) for w in waived_names):
            continue
        if count_owned(token, owned) >= need:
            continue
        if need == 1:
            fam = canonical_family(token)
            if fam and fam in families:
                continue
        return False
    return True


def exclude_blocked(exclude: str, owned: Sequence[str]) -> bool:
    return any(count_owned(token, owned) >= 1 for token, _need in parse_req_tokens(exclude))


def is_skill_choice_legal(
    name: str,
    owned: Sequence[str],
    presets: Sequence[str] = (),
) -> bool:
    """目录否决：never_pick / 已点过互斥支。

    **前置不在此列**：面板上出现的卡就是游戏判定可学的，本目录是截图推断出来的，
    不得拿它去否决实机候选（20260814 实机：次级箭/爆炸箭矢因前置「没见过」被判非法，
    连续三轮放弃技能点）。前置只用于排序偏好，见 :func:`skill_chain_rank`。
    """
    del presets
    text = str(name or "").strip()
    if not text:
        return False
    card = lookup_card(text)
    if card is None:
        return True
    if card.get("never_pick"):
        return False
    if exclude_blocked(str(card.get("exclude") or ""), owned):
        return False
    for have in owned:
        other = lookup_card(have)
        if other is None:
            continue
        # 官方不对称排斥：exclude_asymmetric 的卡只拦「自己进池」，
        # 不把对方从池子里踢出去。例：先点磁暴 → 审判之雷不再进池；
        # 先点审判之雷 → 磁暴仍可出。
        if other.get("exclude_asymmetric"):
            continue
        if exclude_blocked(str(other.get("exclude") or ""), (text,)):
            return False
    return True


def skill_combo_rank(name: str, owned: Sequence[str]) -> int:
    """0 = 卡组还缺这一系；1 = 已有该系，继续点树。先凑组合再点树。"""
    fam = family_of(name)
    if not fam:
        return 0
    return 0 if fam not in owned_families(owned) else 1


def skill_chain_rank(
    name: str,
    owned: Sequence[str],
    archive_levels: Mapping[str, int] | Sequence[tuple[str, int]] | None = None,
) -> int:
    """0 = 本局已看到前置（接着链子学）；1 = 前置没确认。只排序，不否决。

    ``archive_levels`` 为空/未知时不放宽前置。只有存档门槛核实且调用方
    明确传入等级时，才把 waive_prereq 里的代币当成已满足。
    """
    card = lookup_card(name)
    if card is None:
        return 0
    waived = waived_prereq_names(name, archive_levels)
    return 0 if prereq_met(str(card.get("prereq") or ""), owned, waived=waived) else 1


def skill_penalty_rank(
    name: str,
    archive_levels: Mapping[str, int] | Sequence[tuple[str, int]] | None = None,
) -> int:
    """0 = 该卡「不再降低伤害」已核实且存档够级；1 = 未知或未够。只排序。"""
    return 0 if damage_penalty_removed(name, archive_levels) else 1


def _archive_unlocks_path() -> Path:
    return ARCHIVE_UNLOCKS_PATH


@lru_cache(maxsize=1)
def load_skill_archive_unlocks() -> dict[str, Any]:
    try:
        data = json.loads(_archive_unlocks_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {"skills": []}
    if not isinstance(data, dict):
        return {"skills": []}
    skills = data.get("skills")
    if not isinstance(skills, list):
        data["skills"] = []
    return data


def normalize_archive_levels(
    raw: Mapping[str, Any] | Sequence[tuple[str, Any]] | None,
) -> dict[str, int]:
    if not raw:
        return {}
    items: Sequence[tuple[Any, Any]]
    if isinstance(raw, Mapping):
        items = tuple(raw.items())
    else:
        items = tuple(raw)
    out: dict[str, int] = {}
    for key, value in items:
        name = str(key or "").strip()
        if not name:
            continue
        try:
            level = int(value)
        except (TypeError, ValueError):
            continue
        if level >= 0:
            out[name] = level
    return out


def _skill_keys(skill: Mapping[str, Any]) -> tuple[str, ...]:
    keys = [str(skill.get("skill_id") or "").strip(), str(skill.get("name") or "").strip()]
    for alias in skill.get("aliases") or []:
        text = str(alias).strip()
        if text:
            keys.append(text)
    name = str(skill.get("name") or "").strip()
    alt = _arcane_alias(name)
    if alt:
        keys.append(alt)
    return tuple(k for k in keys if k)


def archive_level_of(
    skill_key: str,
    archive_levels: Mapping[str, int] | Sequence[tuple[str, int]] | None,
) -> int | None:
    """查某主技能的调用方存档等级。对不上或未传入 → None（未知）。"""
    levels = normalize_archive_levels(archive_levels)
    if not levels:
        return None
    text = str(skill_key or "").strip()
    if not text:
        return None
    if text in levels:
        return levels[text]
    alt = _arcane_alias(text)
    if alt and alt in levels:
        return levels[alt]
    fam = canonical_family(text) or family_of(text)
    if fam and fam in levels:
        return levels[fam]
    fam_alt = _arcane_alias(fam) if fam else None
    if fam_alt and fam_alt in levels:
        return levels[fam_alt]
    for skill in load_skill_archive_unlocks().get("skills") or []:
        if not isinstance(skill, dict):
            continue
        keys = _skill_keys(skill)
        if text in keys or (fam and fam in keys) or (alt and alt in keys):
            for key in keys:
                if key in levels:
                    return levels[key]
    return None


def _payload_cards(payload: Mapping[str, Any] | None) -> tuple[str, ...]:
    if not isinstance(payload, Mapping):
        return ()
    names: list[str] = []
    card = str(payload.get("card") or "").strip()
    if card:
        names.append(card)
    for item in payload.get("cards") or []:
        text = str(item).strip()
        if text:
            names.append(text)
    return tuple(names)


def _row_verified_level(row: Mapping[str, Any]) -> int | None:
    if str(row.get("level_status") or "") != "verified":
        return None
    try:
        level = int(row.get("level"))
    except (TypeError, ValueError):
        return None
    return level if level >= 0 else None


def _iter_verified_rows(kind: str):
    for skill in load_skill_archive_unlocks().get("skills") or []:
        if not isinstance(skill, dict):
            continue
        for row in skill.get("unlocks") or []:
            if not isinstance(row, dict):
                continue
            if str(row.get("kind") or "") != kind:
                continue
            level = _row_verified_level(row)
            if level is None:
                continue
            yield skill, row, level


def waived_prereq_names(
    card_name: str,
    archive_levels: Mapping[str, int] | Sequence[tuple[str, int]] | None = None,
) -> frozenset[str]:
    """存档够级且核实后，该卡可忽略的前置代币。未知存档 → 空。"""
    levels = normalize_archive_levels(archive_levels)
    if not levels:
        return frozenset()
    text = str(card_name or "").strip()
    if not text:
        return frozenset()
    out: set[str] = set()
    for skill, row, need in _iter_verified_rows("waive_prereq"):
        have = archive_level_of(str(skill.get("skill_id") or skill.get("name") or ""), levels)
        if have is None or have < need:
            continue
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        targets = _payload_cards(payload)
        if not any(names_match(text, t) for t in targets):
            continue
        for token in payload.get("waived") or []:
            name = str(token).strip()
            if name:
                out.add(name)
    return frozenset(out)


def damage_penalty_removed(
    card_name: str,
    archive_levels: Mapping[str, int] | Sequence[tuple[str, int]] | None = None,
) -> bool:
    """齐射/连发类「不再降低伤害」：仅 verified 且存档>=N 为 True。"""
    levels = normalize_archive_levels(archive_levels)
    if not levels:
        return False
    text = str(card_name or "").strip()
    if not text:
        return False
    for skill, row, need in _iter_verified_rows("remove_damage_penalty"):
        have = archive_level_of(str(skill.get("skill_id") or skill.get("name") or ""), levels)
        if have is None or have < need:
            continue
        if any(names_match(text, t) for t in _payload_cards(row.get("payload") if isinstance(row.get("payload"), dict) else {})):
            return True
    return False


def grant_on_learn_card(
    skill_name: str,
    archive_levels: Mapping[str, int] | Sequence[tuple[str, int]] | None = None,
) -> str | None:
    """学得该主技能会立即获得的白卡。未知或未够级 → None。"""
    levels = normalize_archive_levels(archive_levels)
    if not levels:
        return None
    text = str(skill_name or "").strip()
    if not text:
        return None
    for skill, row, need in _iter_verified_rows("grant_on_learn"):
        keys = _skill_keys(skill)
        if text not in keys and not any(names_match(text, k) for k in keys):
            continue
        have = archive_level_of(str(skill.get("skill_id") or skill.get("name") or ""), levels)
        if have is None or have < need:
            continue
        cards = _payload_cards(row.get("payload") if isinstance(row.get("payload"), dict) else {})
        return cards[0] if cards else None
    return None


def card_archive_unlock_level(card_name: str) -> int | None:
    """该卡因存档门槛进池的核实等级。无核实行 → None。"""
    text = str(card_name or "").strip()
    if not text:
        return None
    found: int | None = None
    for _skill, row, need in _iter_verified_rows("unlock_card"):
        if any(names_match(text, t) for t in _payload_cards(row.get("payload") if isinstance(row.get("payload"), dict) else {})):
            if found is None or need < found:
                found = need
    return found


def card_unlocked_by_archive(
    card_name: str,
    archive_levels: Mapping[str, int] | Sequence[tuple[str, int]] | None = None,
) -> bool | None:
    """某卡是否因存档等级进池。未知存档或无核实门槛 → None（fail-closed）。"""
    need = card_archive_unlock_level(card_name)
    if need is None:
        return None
    text = str(card_name or "").strip()
    for skill, row, level in _iter_verified_rows("unlock_card"):
        if level != need:
            continue
        if not any(names_match(text, t) for t in _payload_cards(row.get("payload") if isinstance(row.get("payload"), dict) else {})):
            continue
        have = archive_level_of(str(skill.get("skill_id") or skill.get("name") or ""), archive_levels)
        if have is None:
            return None
        return have >= need
    return None


@lru_cache(maxsize=1)
def load_skill_rarity() -> dict[str, Any]:
    """Load the authoritative card-rarity catalog used by choice policy."""
    try:
        data = json.loads(RARITY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {"cards": []}
    if not isinstance(data, dict):
        return {"cards": []}
    if not isinstance(data.get("cards"), list):
        data["cards"] = []
    return data


@lru_cache(maxsize=1)
def _rarity_index() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in load_skill_rarity().get("cards") or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        out[name] = row
        alt = _arcane_alias(name)
        if alt:
            out.setdefault(alt, row)
        for alias in row.get("aliases") or []:
            text = str(alias).strip()
            if text:
                out.setdefault(text, row)
    return out


def lookup_rarity(name: str) -> dict[str, Any] | None:
    """查稀有度行。无证据 → None。会走奥术/奥数别名和本表 aliases。"""
    text = str(name or "").strip()
    if not text:
        return None
    index = _rarity_index()
    row = index.get(text)
    if row is not None:
        return row
    alt = _arcane_alias(text)
    if alt and alt in index:
        return index[alt]
    card = lookup_card(text)
    if card is not None:
        canon = str(card.get("name") or "").strip()
        if canon and canon in index:
            return index[canon]
    return None


def card_rarity(name: str) -> str | None:
    """游戏内叫法（白/蓝/紫/橙/粉/红）。无证据或 unverified → None。"""
    row = lookup_rarity(name)
    if row is None:
        return None
    if str(row.get("rarity_status") or "") == "unverified":
        return None
    rarity = str(row.get("rarity") or "").strip()
    return rarity or None


def card_rarity_status(name: str) -> str:
    """screenshot / video_frame / unverified / live_confirmed；无行 → unverified。"""
    row = lookup_rarity(name)
    if row is None:
        return "unverified"
    status = str(row.get("rarity_status") or "").strip()
    return status or "unverified"


def card_seen_levels(name: str) -> tuple[int, ...]:
    """卡面/存档截图上出现过的等级。没有 → 空。不替代 archive unlocks。"""
    row = lookup_rarity(name)
    if row is None:
        return ()
    out: list[int] = []
    for item in row.get("seen_levels") or []:
        if not isinstance(item, dict):
            continue
        try:
            level = int(item.get("level"))
        except (TypeError, ValueError):
            continue
        if level >= 0:
            out.append(level)
    return tuple(out)
