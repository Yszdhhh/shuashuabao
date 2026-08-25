"""图鉴只读投影：运行时 join 权威 JSON，不写第四份卡名表。

统一条目：规范名 / 类别 / 系或张数 / 效果 / 前置与互斥 / 稀有度 /
等级档位 / 证据标签 / 图标路径。空说明显示「待补」，不编数值。
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from shuabao.bond_capacity import load_bond_stack_catalog
from shuabao.settings import MAX_SELECTED_SKILLS
from shuabao.skill_catalog import (
    card_rarity,
    load_skill_archive_unlocks,
    load_skill_catalog,
)
from shuabao.vision.choice_ocr import load_lexicon, lookup_lexicon

PENDING_TEXT = "待补"
EVIDENCE_LIVE = "实机"
EVIDENCE_GUIDE = "攻略"
EVIDENCE_PENDING = "待补"

CATEGORY_SKILL_FAMILY = "skill_family"
CATEGORY_SKILL_CARD = "skill_card"
CATEGORY_BOND = "bond"
CATEGORY_TREASURE = "treasure"
CATEGORY_MERCHANT = "merchant"

MAX_APPLY_SKILLS = MAX_SELECTED_SKILLS
MAX_APPLY_BONDS = 6

_LIVE_MARKERS = (
    "lab",
    "ocr",
    "user",
    "screenshot",
    "fixture",
    "recording",
    "live",
    "treasure_must_take",
    "ur_attr_routes",
    "卡面",
    "截图",
)
_GUIDE_MARKERS = ("抖音", "攻略", "guide", "official_strategy", "catalog")
_GUIDE_BONDS = frozenset({"提速", "生命", "血势", "血魔", "剑术"})
_JOIN_BOND_SETS = frozenset({
    "异火", "刀刀", "大圣", "封神", "神兽", "龙族", "迦拉克隆", "三国",
    "军团", "亡灵", "修仙", "神通", "海盗", "宝藏", "法宝", "恐鳌戒指",
})


def _repo_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    here = Path(__file__).resolve().parent
    for parent in (here, *here.parents):
        if (parent / "config" / "choice_lexicon.json").is_file():
            return parent
    return here.parents[1]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _index_rows(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        cards = data.get("cards")
        if isinstance(cards, list):
            return [row for row in cards if isinstance(row, dict)]
    return []


def _config_json(name: str) -> dict[str, Any]:
    return _read_json(_repo_root() / "config" / name)


def _card_pool_rules() -> dict[str, Any]:
    raw = _config_json("game_mechanics_kb.json").get("card_pool_rules")
    return raw if isinstance(raw, dict) else {}


def _rel_if_file(*parts: str) -> str | None:
    path = _repo_root().joinpath(*parts)
    return "/".join(parts) if path.is_file() else None


def _rel_existing(rel: str) -> str | None:
    text = str(rel or "").replace("\\", "/").strip()
    if not text:
        return None
    return text if (_repo_root() / text).is_file() else None


def _skip_key(key: Any) -> bool:
    return str(key).startswith("_")


def _public_str_map(raw: Mapping[str, Any] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in (raw or {}).items():
        if _skip_key(key) or not isinstance(value, str):
            continue
        name = str(key).strip()
        label = value.strip()
        if name and label:
            out[name] = label
    return out


def _has_marker(text: str, markers: tuple[str, ...]) -> bool:
    blob = str(text or "").lower()
    return any(marker.lower() in blob for marker in markers)


def _evidence_of(*, source: str = "", status: str = "", empty_body: bool = False) -> str:
    if empty_body and not _has_marker(source, _LIVE_MARKERS):
        return EVIDENCE_PENDING
    if status == "guide" or _has_marker(source, _GUIDE_MARKERS) and not _has_marker(
        source, _LIVE_MARKERS
    ):
        return EVIDENCE_GUIDE
    if status == "live" or _has_marker(source, _LIVE_MARKERS):
        return EVIDENCE_LIVE
    if _has_marker(source, _GUIDE_MARKERS):
        return EVIDENCE_GUIDE
    return EVIDENCE_PENDING


@dataclass(frozen=True)
class AtlasUnlock:
    level: int | None
    text: str
    kind: str
    verified: bool

    def display(self) -> str:
        body = self.text.strip() or PENDING_TEXT
        if self.level is None:
            return body
        return f"Lv{self.level}：{body}"


@dataclass(frozen=True)
class AtlasPiece:
    name: str
    icon_path: str | None
    stats: str


@dataclass(frozen=True)
class AtlasRoute:
    attr: str
    chain: tuple[str, ...]
    pieces: tuple[AtlasPiece, ...]
    set_effect: str
    fetter_code: str


@dataclass(frozen=True)
class AtlasEntry:
    name: str
    category: str
    family_or_need: str
    effect: str
    prereq: str
    exclude: str
    rarity: str
    archive_tiers: tuple[AtlasUnlock, ...]
    evidence: str
    icon_path: str | None
    aliases: tuple[str, ...]
    short_code: str | None = None
    whitelist_ok: bool = False
    never_pick: bool = False
    flags: tuple[str, ...] = ()
    route: AtlasRoute | None = None
    tree_prereq: tuple[str, ...] = ()
    tree_unlocks: tuple[str, ...] = ()

    def display_effect(self) -> str:
        return self.effect.strip() or PENDING_TEXT


@dataclass(frozen=True)
class AtlasMerchantPage:
    entries: tuple[AtlasEntry, ...] = ()
    known: tuple[str, ...] = ()
    pending: tuple[str, ...] = ()


@dataclass(frozen=True)
class AtlasApplyDiff:
    skills: tuple[str, ...]
    cards: tuple[str, ...]
    treasure_allow_negative: tuple[str, ...]
    rejected: tuple[str, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class AtlasView:
    entries: tuple[AtlasEntry, ...]

    def by_category(self, category: str) -> tuple[AtlasEntry, ...]:
        return tuple(item for item in self.entries if item.category == category)

    def get(self, name: str) -> AtlasEntry | None:
        token = str(name or "").strip()
        if not token:
            return None
        for item in self.entries:
            if item.name == token or item.short_code == token:
                return item
        looked = lookup_lexicon(token)
        if looked.canonical:
            for item in self.entries:
                if item.name == looked.canonical:
                    return item
        return None

    def search(self, query: str) -> tuple[AtlasEntry, ...]:
        token = str(query or "").strip()
        if not token:
            return ()
        exact: list[AtlasEntry] = []
        alias_hits: list[AtlasEntry] = []
        partial: list[AtlasEntry] = []
        seen: set[tuple[str, str]] = set()

        def _take(bucket: list[AtlasEntry], item: AtlasEntry) -> None:
            key = (item.category, item.name)
            if key in seen:
                return
            seen.add(key)
            bucket.append(item)

        primary = self.get(token)
        if primary is not None:
            _take(exact, primary)
        for item in self.entries:
            if item.name == token or item.short_code == token:
                _take(exact, item)
            elif token in item.aliases:
                _take(alias_hits, item)
            elif item.route and any(piece.name == token for piece in item.route.pieces):
                _take(alias_hits, item)
            elif token in item.name or any(token in alias for alias in item.aliases):
                _take(partial, item)
        return tuple(exact + alias_hits + partial)

    def merchant_page(self) -> AtlasMerchantPage:
        return AtlasMerchantPage(
            entries=(),
            known=_merchant_known(),
            pending=_merchant_pending(),
        )


def _lexicon_aliases(name: str, extra: Sequence[str] = ()) -> tuple[str, ...]:
    entries = load_lexicon().get("entries") or {}
    row = entries.get(name) if isinstance(entries, dict) else None
    aliases: list[str] = []
    if isinstance(row, dict):
        for alias in row.get("aliases") or []:
            text = str(alias).strip()
            if text and text != name and text not in aliases:
                aliases.append(text)
    for alias in extra:
        text = str(alias).strip()
        if text and text != name and text not in aliases:
            aliases.append(text)
    return tuple(aliases)


def _unlock_row(row: Mapping[str, Any]) -> AtlasUnlock:
    raw_level = row.get("level")
    level: int | None
    try:
        level = int(raw_level) if raw_level is not None else None
    except (TypeError, ValueError):
        level = None
    if level is not None and level < 0:
        level = None
    return AtlasUnlock(
        level=level,
        text=str(row.get("text") or "").strip(),
        kind=str(row.get("kind") or "").strip(),
        verified=str(row.get("level_status") or "") == "verified",
    )


def _archive_tiers(code: str, label: str) -> tuple[AtlasUnlock, ...]:
    wanted = {code, label}
    out: list[AtlasUnlock] = []
    for skill in load_skill_archive_unlocks().get("skills") or []:
        if not isinstance(skill, dict):
            continue
        keys = {str(skill.get("skill_id") or "").strip(), str(skill.get("name") or "").strip()}
        for alias in skill.get("aliases") or []:
            keys.add(str(alias).strip())
        if not (wanted & keys):
            continue
        for row in skill.get("unlocks") or []:
            if isinstance(row, dict):
                out.append(_unlock_row(row))
        break
    return tuple(out)


def _build_route(
    meta: Mapping[str, Any],
    fixture_route: Mapping[str, Any] | None,
) -> AtlasRoute:
    piece_docs = {}
    if isinstance(fixture_route, Mapping):
        raw_pieces = fixture_route.get("pieces") or {}
        if isinstance(raw_pieces, Mapping):
            piece_docs = raw_pieces
    pieces: list[AtlasPiece] = []
    for name in meta.get("pieces") or []:
        text = str(name).strip()
        if not text:
            continue
        doc = piece_docs.get(text) if isinstance(piece_docs.get(text), Mapping) else {}
        icon = _rel_existing(str((doc or {}).get("evidence") or ""))
        if icon is None:
            icon = _rel_if_file("fixtures", "ur_attr_routes", text, "source.png")
        pieces.append(
            AtlasPiece(
                name=text,
                icon_path=icon,
                stats=str((doc or {}).get("stats") or "").strip(),
            )
        )
    chain = tuple(str(item).strip() for item in (meta.get("chain") or []) if str(item).strip())
    return AtlasRoute(
        attr=str(meta.get("attr") or "").strip(),
        chain=chain,
        pieces=tuple(pieces),
        set_effect=str(meta.get("set_effect") or "").strip(),
        fetter_code=str(meta.get("fetter_code") or "").strip(),
    )


def _attr_routes() -> dict[str, AtlasRoute]:
    pack = _config_json("official_strategy_defaults.json")
    fixtures = (_read_json(_repo_root() / "fixtures" / "ur_attr_routes" / "INDEX.json").get("routes") or {})
    out: dict[str, AtlasRoute] = {}
    for key, meta in (pack.get("attr_routes") or {}).items():
        if _skip_key(key) or not isinstance(meta, dict) or "chain" not in meta:
            continue
        fixture = fixtures.get(key) if isinstance(fixtures, dict) else None
        route = _build_route(meta, fixture if isinstance(fixture, dict) else None)
        out[str(meta.get("set_name") or "").strip()] = route
        for name in route.chain:
            out.setdefault(name, route)
    return out


def _ex_capstone_rows() -> list[dict[str, Any]]:
    kb_cards = (_card_pool_rules().get("ex_capstones") or {}).get("cards")
    if isinstance(kb_cards, list) and kb_cards:
        return [row for row in kb_cards if isinstance(row, dict) and str(row.get("name") or "").strip()]
    return _index_rows(_repo_root() / "fixtures" / "ex_finals_20260814" / "INDEX.json")


def _ex_icons() -> dict[str, str]:
    out: dict[str, str] = {}
    for row in _index_rows(_repo_root() / "fixtures" / "ex_finals_20260814" / "INDEX.json"):
        name = str(row.get("name") or "").strip()
        filename = str(row.get("filename") or "").strip()
        icon = _rel_if_file("fixtures", "ex_finals_20260814", filename) if filename else None
        if name and icon:
            out[name] = icon
    return out


def _live_card_icons() -> dict[str, str]:
    """Join 174547 INDEX filenames to lexicon names. Missing JPGs stay None."""
    lexicon = load_lexicon().get("entries") or {}
    if not isinstance(lexicon, dict):
        return {}
    names = [
        str(name).strip()
        for name, row in lexicon.items()
        if isinstance(row, dict)
        and row.get("kind") == "bond"
        and str(row.get("set_membership") or "") in {"刀刀", "异火"}
        and str(name).strip()
        and str(name).strip() not in _JOIN_BOND_SETS
    ]
    names.sort(key=len, reverse=True)
    out: dict[str, str] = {}
    for row in _index_rows(_repo_root() / "fixtures" / "cards_174547_evidence" / "INDEX.json"):
        filename = str(row.get("filename") or "").strip()
        if not filename:
            continue
        icon = _rel_if_file("fixtures", "cards_174547_evidence", filename)
        if icon is None:
            icon = _rel_if_file("fixtures", "cards_174547_evidence", "all_slow_looks", filename)
        if icon is None:
            continue
        blob = f"{row.get('name') or ''} {filename} {row.get('description') or ''}"
        compact_blob = blob.replace("·", "")
        for name in names:
            if name in blob or name.replace("·", "") in compact_blob:
                out.setdefault(name, icon)
                break
    return out


def _bond_fixture_icons() -> dict[str, str]:
    out = dict(_live_card_icons())
    out.update(_ex_icons())
    return out


def _kb_set_routes(icons: Mapping[str, str] | None = None) -> dict[str, AtlasRoute]:
    """刀刀 / 异火链路只 join KB，不另写卡名表。"""
    rules = _card_pool_rules()
    icon_map = dict(icons or {})
    out: dict[str, AtlasRoute] = {}

    def _pieces(names: Sequence[str]) -> tuple[AtlasPiece, ...]:
        pieces: list[AtlasPiece] = []
        for name in names:
            text = str(name).strip()
            if text:
                pieces.append(AtlasPiece(name=text, icon_path=icon_map.get(text), stats=""))
        return tuple(pieces)

    def _bind(route: AtlasRoute, names: Sequence[str]) -> None:
        for name in names:
            text = str(name).strip()
            if text:
                out.setdefault(text, route)

    daodao = rules.get("daodao_chain") if isinstance(rules.get("daodao_chain"), dict) else {}
    live = daodao.get("live_verified") if isinstance(daodao.get("live_verified"), dict) else {}
    piece_names = [str(n).strip() for n in (live.get("pieces") or []) if str(n).strip()]
    daodao_chain = tuple(
        text
        for text in (
            *piece_names,
            str(live.get("unlocks") or "").strip(),
            str(live.get("ur") or "").strip(),
            str(daodao.get("ex") or "").strip(),
        )
        if text
    )
    if daodao_chain:
        route = AtlasRoute(
            attr="",
            chain=daodao_chain,
            pieces=_pieces(piece_names),
            set_effect=str(daodao.get("text") or "").strip(),
            fetter_code="",
        )
        extra: list[str] = []
        guide = daodao.get("guide") if isinstance(daodao.get("guide"), dict) else {}
        for key in ("phase1_blueprints", "phase2_blueprints", "intermediates"):
            for row in guide.get(key) or []:
                if isinstance(row, dict) and str(row.get("name") or "").strip():
                    extra.append(str(row["name"]).strip())
                    extra.extend(str(a).strip() for a in (row.get("aliases") or []) if str(a).strip())
        _bind(route, ("刀刀", *daodao_chain, *extra))

    dasheng = rules.get("dasheng_chain") if isinstance(rules.get("dasheng_chain"), dict) else {}
    dlive = dasheng.get("live_verified") if isinstance(dasheng.get("live_verified"), dict) else {}
    dguide = dasheng.get("guide") if isinstance(dasheng.get("guide"), dict) else {}
    dasheng_live = tuple(
        text
        for text in (
            str(dlive.get("piece") or "").strip(),
            str(dlive.get("badge") or "").strip(),
            str(dasheng.get("ex") or dlive.get("ex_card") or "").strip(),
        )
        if text
    )
    if dasheng_live:
        gear = [str(n).strip() for n in (dguide.get("gear") or []) if str(n).strip()]
        dacheng = [
            str(row.get("name") or "").strip()
            for row in (dguide.get("dacheng") or [])
            if isinstance(row, dict) and str(row.get("name") or "").strip()
        ]
        extras = [
            str(dguide.get("remnants_result") or "").strip(),
            "大圣套装",
            "安身法",
            "近字法",
        ]
        route = AtlasRoute(
            attr="",
            chain=dasheng_live,
            pieces=_pieces([str(dlive.get("piece") or "").strip()] if dlive.get("piece") else []),
            set_effect=str(dasheng.get("text") or "").strip(),
            fetter_code="",
        )
        for name in ("大圣", *dasheng_live, *gear, *dacheng, *extras):
            if name:
                out.setdefault(name, route)

    fengshen = rules.get("fengshen_chain") if isinstance(rules.get("fengshen_chain"), dict) else {}
    flive = fengshen.get("live_verified") if isinstance(fengshen.get("live_verified"), dict) else {}
    fguide = fengshen.get("guide") if isinstance(fengshen.get("guide"), dict) else {}
    fphase1 = fguide.get("phase1") if isinstance(fguide.get("phase1"), dict) else {}
    flesh = fphase1.get("flesh") if isinstance(fphase1.get("flesh"), dict) else {}
    fengshen_chain = tuple(
        text
        for text in (
            str(flive.get("starter") or "").strip(),
            str(fengshen.get("ex") or flive.get("ex") or "").strip(),
        )
        if text
    )
    if fengshen_chain:
        fabao = [
            str(row.get("name") or "").strip()
            for row in (fguide.get("fabao") or [])
            if isinstance(row, dict) and str(row.get("name") or "").strip()
        ]
        fextras = [
            str(flive.get("also_live") or "").strip(),
            str(fphase1.get("board") or "").strip(),
            str(flesh.get("name") or "").strip(),
            *[str(n).strip() for n in (fphase1.get("unlocks") or []) if str(n).strip()],
            *[
                str(row.get("to") or "").strip()
                for row in ((fguide.get("phase2") or {}).get("jumps") or [])
                if isinstance(row, dict)
            ],
        ]
        route = AtlasRoute(
            attr="",
            chain=fengshen_chain,
            pieces=_pieces([str(flive.get("starter") or "").strip()] if flive.get("starter") else []),
            set_effect=str(fengshen.get("text") or "").strip(),
            fetter_code="",
        )
        _bind(route, ("封神", "法宝", *fengshen_chain, *fabao, *fextras))

    wangling = rules.get("wangling_chain") if isinstance(rules.get("wangling_chain"), dict) else {}
    wlive = wangling.get("live_verified") if isinstance(wangling.get("live_verified"), dict) else {}
    wguide = wangling.get("guide") if isinstance(wangling.get("guide"), dict) else {}
    wangling_chain = tuple(
        text
        for text in (
            str(wlive.get("starter") or "").strip(),
            str(wangling.get("ex") or wlive.get("ex") or "").strip(),
        )
        if text
    )
    if wangling_chain:
        wextra = [
            str(row.get("name") or "").strip()
            for row in (wguide.get("accelerators") or [])
            if isinstance(row, dict) and str(row.get("name") or "").strip()
        ]
        wextra.extend(
            str(row.get("card") or "").strip()
            for row in (wguide.get("producers") or [])
            if isinstance(row, dict)
            and str(row.get("card") or "").strip()
            and not row.get("not_in_lexicon")
        )
        wextra.extend(
            str(wguide.get(key) or "").strip()
            for key in ("hall", "detonate")
        )
        small = wguide.get("small_ur") if isinstance(wguide.get("small_ur"), dict) else {}
        wextra.append(str(small.get("name") or "").strip())
        route = AtlasRoute(
            attr="",
            chain=wangling_chain,
            pieces=_pieces([str(wlive.get("starter") or "").strip()] if wlive.get("starter") else []),
            set_effect=str(wangling.get("text") or "").strip(),
            fetter_code="",
        )
        _bind(route, ("亡灵", *wangling_chain, *wextra))

    shenshou = rules.get("shenshou_chain") if isinstance(rules.get("shenshou_chain"), dict) else {}
    slive = shenshou.get("live_verified") if isinstance(shenshou.get("live_verified"), dict) else {}
    sguide = shenshou.get("guide") if isinstance(shenshou.get("guide"), dict) else {}
    shenshou_chain = tuple(
        text
        for text in (
            str(slive.get("starter") or "").strip(),
            str(shenshou.get("ex") or slive.get("ex") or "").strip(),
        )
        if text
    )
    if shenshou_chain:
        snames = [
            str(row.get("name") or "").strip()
            for key in ("greens", "ur_examples")
            for row in (sguide.get(key) or [])
            if isinstance(row, dict) and str(row.get("name") or "").strip()
        ]
        route = AtlasRoute(
            attr="",
            chain=shenshou_chain,
            pieces=_pieces([str(slive.get("starter") or "").strip()] if slive.get("starter") else []),
            set_effect=str(shenshou.get("text") or "").strip(),
            fetter_code="",
        )
        _bind(route, ("神兽", *shenshou_chain, *snames))

    juntuan = rules.get("juntuan_chain") if isinstance(rules.get("juntuan_chain"), dict) else {}
    jlive = juntuan.get("live_verified") if isinstance(juntuan.get("live_verified"), dict) else {}
    jguide = juntuan.get("guide") if isinstance(juntuan.get("guide"), dict) else {}
    juntuan_chain = tuple(
        text
        for text in (
            str(jlive.get("starter") or "").strip(),
            str(juntuan.get("ex") or jlive.get("ex") or "").strip(),
        )
        if text
    )
    if juntuan_chain:
        jextra: list[str] = ["扭曲虚空"]
        for row in jguide.get("swallow_helpers") or []:
            if isinstance(row, dict):
                jextra.append(str(row.get("name") or "").strip())
                jextra.extend(str(x).strip() for x in (row.get("brings") or []) if str(x).strip())
        jextra.extend(str(x).strip() for x in (jguide.get("pair_swallow") or []) if str(x).strip())
        jextra.extend(str(x).strip() for x in (jguide.get("after_three_void") or []) if str(x).strip())
        route = AtlasRoute(
            attr="",
            chain=juntuan_chain,
            pieces=_pieces([str(jlive.get("starter") or "").strip()] if jlive.get("starter") else []),
            set_effect=str(juntuan.get("text") or "").strip(),
            fetter_code="",
        )
        _bind(route, ("军团", *juntuan_chain, *jextra))

    longzu = rules.get("longzu_chain") if isinstance(rules.get("longzu_chain"), dict) else {}
    llive = longzu.get("live_verified") if isinstance(longzu.get("live_verified"), dict) else {}
    lguide = longzu.get("guide") if isinstance(longzu.get("guide"), dict) else {}
    lp1 = lguide.get("phase1") if isinstance(lguide.get("phase1"), dict) else {}
    lp2 = lguide.get("phase2") if isinstance(lguide.get("phase2"), dict) else {}
    lp3 = lguide.get("phase3") if isinstance(lguide.get("phase3"), dict) else {}
    longzu_chain = tuple(
        text
        for text in (
            str(llive.get("starter") or "").strip(),
            str(longzu.get("ex") or llive.get("ex") or "").strip(),
        )
        if text
    )
    if longzu_chain:
        lextra = [
            str(lp1.get("result") or "").strip(),
            str(lp2.get("opener") or "").strip(),
            str(lp2.get("nest") or "").strip(),
            str(lp3.get("pray5") or "").strip(),
        ]
        lextra.extend(
            str(row.get("name") or "").strip()
            for row in (lguide.get("pray_cards") or [])
            if isinstance(row, dict) and str(row.get("name") or "").strip()
        )
        lextra.extend(str(x).strip() for x in (lguide.get("wood_save") or []) if str(x).strip())
        route = AtlasRoute(
            attr="",
            chain=longzu_chain,
            pieces=_pieces([str(llive.get("starter") or "").strip()] if llive.get("starter") else []),
            set_effect=str(longzu.get("text") or "").strip(),
            fetter_code="",
        )
        _bind(route, ("龙族", "迦拉克隆", *longzu_chain, *lextra))

    sanguo = rules.get("sanguo_chain") if isinstance(rules.get("sanguo_chain"), dict) else {}
    glive = sanguo.get("live_verified") if isinstance(sanguo.get("live_verified"), dict) else {}
    gguide = sanguo.get("guide") if isinstance(sanguo.get("guide"), dict) else {}
    sanguo_chain = tuple(
        text
        for text in (
            str(glive.get("starter") or "").strip(),
            str(sanguo.get("ex") or glive.get("ex") or "").strip(),
        )
        if text
    )
    if sanguo_chain:
        gextra: list[str] = []
        for row in gguide.get("factions") or []:
            if isinstance(row, dict):
                gextra.extend(
                    str(row.get(k) or "").strip()
                    for k in ("start", "ur")
                    if str(row.get(k) or "").strip()
                )
        route = AtlasRoute(
            attr="",
            chain=sanguo_chain,
            pieces=_pieces([str(glive.get("starter") or "").strip()] if glive.get("starter") else []),
            set_effect=str(sanguo.get("text") or "").strip(),
            fetter_code="",
        )
        _bind(route, ("三国", *sanguo_chain, *gextra))

    xiuxian = rules.get("xiuxian_chain") if isinstance(rules.get("xiuxian_chain"), dict) else {}
    xlive = xiuxian.get("live_verified") if isinstance(xiuxian.get("live_verified"), dict) else {}
    xguide = xiuxian.get("guide") if isinstance(xiuxian.get("guide"), dict) else {}
    xpiece = xlive.get("piece") if isinstance(xlive.get("piece"), dict) else {}
    xiuxian_chain = tuple(
        text
        for text in (
            str(xpiece.get("name") or "").strip(),
            "练气期",
            str(xiuxian.get("ex") or xlive.get("ex") or "").strip(),
        )
        if text
    )
    if xiuxian_chain:
        xextra = [str(xlive.get("also_piece") or "").strip()]
        xextra.extend(
            str(row.get("to") or row.get("via") or row.get("name") or "").strip()
            for key in ("stages", "sure_items")
            for row in (xguide.get(key) or [])
            if isinstance(row, dict)
        )
        for row in xguide.get("sure_items") or []:
            if isinstance(row, dict):
                xextra.extend(str(x).strip() for x in (row.get("pieces") or []) if str(x).strip())
        xtreasure = xguide.get("treasure") if isinstance(xguide.get("treasure"), dict) else {}
        xextra.append(str(xtreasure.get("name") or "").strip())
        route = AtlasRoute(
            attr="",
            chain=xiuxian_chain,
            pieces=_pieces(
                [n for n in (str(xpiece.get("name") or "").strip(), str(xlive.get("also_piece") or "").strip()) if n]
            ),
            set_effect=str(xiuxian.get("text") or "").strip(),
            fetter_code="",
        )
        _bind(route, ("修仙", *xiuxian_chain, *xextra))

    haidao = rules.get("haidao_chain") if isinstance(rules.get("haidao_chain"), dict) else {}
    hlive = haidao.get("live_verified") if isinstance(haidao.get("live_verified"), dict) else {}
    hguide = haidao.get("guide") if isinstance(haidao.get("guide"), dict) else {}
    hmap = hlive.get("map_need") if isinstance(hlive.get("map_need"), dict) else {}
    haidao_chain = tuple(
        text
        for text in (
            str(hmap.get("name") or "").strip(),
            str(haidao.get("ur") or hlive.get("ur") or "").strip(),
        )
        if text
    )
    if haidao_chain:
        hextra = [str(n).strip() for n in (hlive.get("seen_pirates") or []) if str(n).strip()]
        hextra.extend(str(n).strip() for n in (hlive.get("ur_opens") or []) if str(n).strip())
        hextra.extend(
            str(row.get("name") or "").strip()
            for row in (hguide.get("cards") or [])
            if isinstance(row, dict) and str(row.get("name") or "").strip()
        )
        for row in hguide.get("cards") or []:
            if isinstance(row, dict):
                hextra.extend(str(a).strip() for a in (row.get("aliases") or []) if str(a).strip())
        hextra.extend(["悬赏令", "剑柄", "剑刃"])
        route = AtlasRoute(
            attr="",
            chain=haidao_chain,
            pieces=_pieces(
                [str(hmap.get("name") or "").strip()]
                + [str(n).strip() for n in (hlive.get("seen_pirates") or []) if str(n).strip()]
            ),
            set_effect=str(haidao.get("text") or "").strip(),
            fetter_code="",
        )
        _bind(route, ("海盗", *haidao_chain, *hextra))
        ape = haidao.get("gold_ape") if isinstance(haidao.get("gold_ape"), dict) else {}
        bao = haidao.get("baozang") if isinstance(haidao.get("baozang"), dict) else {}
        bao_chain = tuple(
            text
            for text in (
                str(ape.get("canonical") or "").strip(),
                "宝藏",
            )
            if text
        )
        if bao_chain:
            broute = AtlasRoute(
                attr="",
                chain=bao_chain,
                pieces=_pieces([str(ape.get("canonical") or "").strip()] if ape.get("canonical") else []),
                set_effect=str(bao.get("name") or "宝藏卡组").strip(),
                fetter_code="",
            )
            _bind(broute, ("宝藏", "安卡", "黄金猿", "黄金元", *bao_chain))

    yihuo = rules.get("yihuo_fenjue_pool") if isinstance(rules.get("yihuo_fenjue_pool"), dict) else {}
    ylive = yihuo.get("live_verified") if isinstance(yihuo.get("live_verified"), dict) else {}
    seen_n = [str(n).strip() for n in (ylive.get("seen_n") or []) if str(n).strip()]
    yihuo_chain = tuple(
        text
        for text in (
            "焚诀·黄阶",
            str(ylive.get("evolve_to") or "").strip(),
            "帝炎",
        )
        if text
    )
    if yihuo_chain:
        yguide = yihuo.get("guide") if isinstance(yihuo.get("guide"), dict) else {}
        yextra = [str(n).strip() for n in (yguide.get("stage_cards") or []) if str(n).strip()]
        yextra.extend(
            str(row.get("name") or "").strip()
            for row in (yguide.get("priority_cards") or [])
            if isinstance(row, dict) and str(row.get("name") or "").strip()
        )
        route = AtlasRoute(
            attr="",
            chain=yihuo_chain,
            pieces=_pieces(seen_n),
            set_effect=str(yihuo.get("text") or "").strip(),
            fetter_code="",
        )
        _bind(route, ("异火", *yihuo_chain, *seen_n, *yextra))

    kongao = rules.get("kongao_ring") if isinstance(rules.get("kongao_ring"), dict) else {}
    klive = kongao.get("live_verified") if isinstance(kongao.get("live_verified"), dict) else {}
    kongao_pieces = [
        str(row.get("name") or "").strip()
        for row in (klive.get("pieces") or [])
        if isinstance(row, dict) and str(row.get("name") or "").strip()
    ]
    if kongao_pieces:
        route = AtlasRoute(
            attr="",
            chain=("恐鳌戒指", *kongao_pieces),
            pieces=_pieces(kongao_pieces),
            set_effect=str(kongao.get("text") or "").strip(),
            fetter_code="",
        )
        for name in ("恐鳌戒指", *kongao_pieces):
            out.setdefault(name, route)
    return out


def _bond_trees() -> dict[str, dict[str, Any]]:
    pack = _config_json("official_strategy_defaults.json")
    out: dict[str, dict[str, Any]] = {}
    for name, meta in (pack.get("bond_trees") or {}).items():
        if _skip_key(name) or not isinstance(meta, dict):
            continue
        out[str(name)] = meta
    return out


def _iter_skill_families() -> list[AtlasEntry]:
    labels = _public_str_map(_config_json("skill_labels.json"))
    meta_doc = (_config_json("skill_meta.json").get("skills") or {})
    out: list[AtlasEntry] = []
    for code, label in labels.items():
        meta = meta_doc.get(code) if isinstance(meta_doc.get(code), dict) else {}
        name = str((meta or {}).get("label") or label).strip() or label
        effect = str((meta or {}).get("description") or "").strip()
        source = str((meta or {}).get("source") or "").strip()
        out.append(
            AtlasEntry(
                name=name,
                category=CATEGORY_SKILL_FAMILY,
                family_or_need=name,
                effect=effect,
                prereq="",
                exclude="",
                rarity="",
                archive_tiers=_archive_tiers(code, name),
                evidence=_evidence_of(source=source, empty_body=not effect),
                icon_path=_rel_if_file("assets", "Images", "skills", f"{code}.png"),
                aliases=_lexicon_aliases(name),
                short_code=code,
                whitelist_ok=True,
                flags=("whitelist_skill",),
            )
        )
    return out


def _iter_skill_cards() -> list[AtlasEntry]:
    out: list[AtlasEntry] = []
    for card in load_skill_catalog().get("cards") or []:
        if not isinstance(card, dict):
            continue
        name = str(card.get("name") or "").strip()
        if not name:
            continue
        family = str(card.get("family") or "").strip()
        effect = str(card.get("effect") or "").strip()
        extra_aliases = [str(a).strip() for a in (card.get("aliases") or []) if str(a).strip()]
        out.append(
            AtlasEntry(
                name=name,
                category=CATEGORY_SKILL_CARD,
                family_or_need=family,
                effect=effect,
                prereq=str(card.get("prereq") or "").strip(),
                exclude=str(card.get("exclude") or "").strip(),
                rarity=card_rarity(name) or "",
                archive_tiers=(),
                evidence=_evidence_of(
                    source=str(card.get("source") or ""),
                    empty_body=not effect,
                ),
                icon_path=None,
                aliases=_lexicon_aliases(name, extra_aliases),
                whitelist_ok=False,
                never_pick=bool(card.get("never_pick")),
                flags=("readonly_upgrade",) + (("never_pick",) if card.get("never_pick") else ()),
            )
        )
    return out


def _iter_bonds() -> list[AtlasEntry]:
    catalog = load_bond_stack_catalog()
    needs = catalog.get("needs") or {}
    unknown = [str(n).strip() for n in (catalog.get("unknown") or []) if str(n).strip()]
    fetters = _public_str_map(_config_json("fetter_labels.json"))
    name_to_code = {label: code for code, label in fetters.items()}
    trees = _bond_trees()
    fixture_icons = _bond_fixture_icons()
    routes = _attr_routes()
    set_routes = _kb_set_routes(fixture_icons)
    ex_rows = {str(row.get("name") or "").strip(): row for row in _ex_capstone_rows()}
    lexicon = load_lexicon().get("entries") or {}
    names: list[str] = []
    for name in list(needs) + unknown + list(name_to_code):
        text = str(name).strip()
        if text and text not in names:
            names.append(text)
    if isinstance(lexicon, dict):
        for name, lex_row in lexicon.items():
            if not isinstance(lex_row, dict) or lex_row.get("kind") != "bond":
                continue
            if str(lex_row.get("set_membership") or "") not in _JOIN_BOND_SETS:
                continue
            text = str(name).strip()
            if text and text not in names:
                names.append(text)
    out: list[AtlasEntry] = []
    for name in names:
        row = needs.get(name) if isinstance(needs.get(name), dict) else {}
        need = (row or {}).get("need")
        need_text = f"{int(need)}张" if isinstance(need, int) and need > 0 else ""
        tree = trees.get(name) or {}
        seen = str((row or {}).get("seen") or "")
        status = str(tree.get("status") or "")
        if name in _GUIDE_BONDS and not status:
            status = "guide"
        note = str(tree.get("note") or "").strip()
        lex_row = lexicon.get(name) if isinstance(lexicon, dict) else None
        lex_note = ""
        lex_ver = ""
        if isinstance(lex_row, dict):
            lex_note = str(lex_row.get("_note") or "").strip()
            lex_ver = str(lex_row.get("version_seen") or "").strip()
            set_name = str(lex_row.get("set_membership") or "")
            if set_name in _JOIN_BOND_SETS and not need_text:
                need_text = set_name
        route = routes.get(name) or set_routes.get(name)
        effect = ""
        if route and route.chain and name == route.chain[-1] and route.set_effect and name not in ex_rows:
            effect = route.set_effect
        elif note:
            effect = note
        elif lex_note:
            effect = lex_note
        code = name_to_code.get(name)
        flags: list[str] = ["whitelist_bond"] if code else ["knowledge_only"]
        ex_row = ex_rows.get(name)
        if ex_row is not None:
            flags.append("cannot_devour")
        icon = _rel_if_file("assets", "Images", "cards", f"{code}.png") if code else None
        if icon is None:
            icon = fixture_icons.get(name)
        out.append(
            AtlasEntry(
                name=name,
                category=CATEGORY_BOND,
                family_or_need=need_text,
                effect=effect,
                prereq=",".join(str(x) for x in (tree.get("prereq") or []) if str(x).strip()),
                exclude="",
                rarity=str((ex_row or {}).get("rarity") or "").strip(),
                archive_tiers=(),
                evidence=_evidence_of(
                    source=" ".join(part for part in (seen, lex_ver, lex_note) if part),
                    status=status,
                    empty_body=not (row or seen or lex_note),
                ),
                icon_path=icon,
                aliases=_lexicon_aliases(name),
                short_code=code,
                whitelist_ok=bool(code),
                flags=tuple(flags),
                route=route,
                tree_prereq=tuple(str(x) for x in (tree.get("prereq") or []) if str(x).strip()),
                tree_unlocks=tuple(str(x) for x in (tree.get("unlocks") or []) if str(x).strip()),
            )
        )
    return out


def _policy_treasure() -> dict[str, Any]:
    return _config_json("choice_policy.json").get("treasure") or {}


def _iter_treasures() -> list[AtlasEntry]:
    policy = _policy_treasure()
    negatives = [str(n).strip() for n in (policy.get("negative_names") or []) if str(n).strip()]
    must_take = [str(n).strip() for n in (policy.get("must_take_names") or []) if str(n).strip()]
    index = _read_json(_repo_root() / "fixtures" / "treasure_must_take" / "INDEX.json")
    cards_doc = index.get("cards") if isinstance(index.get("cards"), dict) else {}
    lexicon = load_lexicon().get("entries") or {}
    set_routes = _kb_set_routes()
    names: list[str] = []
    if isinstance(lexicon, dict):
        for name, row in lexicon.items():
            if isinstance(row, dict) and row.get("kind") == "treasure":
                names.append(str(name))
    for name in negatives + must_take:
        if name not in names:
            names.append(name)
    out: list[AtlasEntry] = []
    for name in names:
        doc = cards_doc.get(name) if isinstance(cards_doc.get(name), dict) else {}
        lex_row = lexicon.get(name) if isinstance(lexicon.get(name), dict) else {}
        is_neg = name in negatives
        is_must = name in must_take
        effect = str((doc or {}).get("description") or "").strip()
        if not effect:
            effect = str((lex_row or {}).get("_note") or "").strip()
        icon = None
        for ev in (doc or {}).get("evidence") or []:
            icon = _rel_existing(str(ev))
            if icon:
                break
        if icon is None and is_must:
            icon = _rel_if_file("fixtures", "treasure_must_take", name, "source.png")
        flags: list[str] = []
        if is_must:
            flags.append("must_take")
        if is_neg:
            flags.append("negative")
        if not flags:
            flags.append("knowledge_only")
        source = "treasure_must_take" if is_must and icon else ""
        out.append(
            AtlasEntry(
                name=name,
                category=CATEGORY_TREASURE,
                family_or_need="必拿" if is_must else ("负面" if is_neg else ""),
                effect=effect,
                prereq="",
                exclude="",
                rarity="",
                archive_tiers=(),
                evidence=_evidence_of(
                    source=" ".join(
                        part
                        for part in (source, str((lex_row or {}).get("version_seen") or ""), effect)
                        if part
                    ),
                    empty_body=not effect,
                ),
                icon_path=icon,
                aliases=_lexicon_aliases(name, [str(a) for a in (doc or {}).get("aliases") or []]),
                whitelist_ok=is_neg,
                flags=tuple(flags),
                route=set_routes.get(name),
            )
        )
    return out


def _merchant_known() -> tuple[str, ...]:
    items: list[str] = ["右下五卡条 HSV 探测（非 OCR 货名）"]
    if _rel_if_file("assets", "Images", "merchant_wood.png"):
        items.append("买木模板 merchant_wood")
    items.append("买木模板 woodgift")
    items.append("刷新键 black_merchant_refresh")
    if _rel_if_file("fixtures", "replay", "black_merchant_card_strip.png"):
        items.append("局部夹具 fixtures/replay/black_merchant_card_strip.png")
    return tuple(items)


def _merchant_pending() -> tuple[str, ...]:
    return (
        "黑商全屏 1600×900 真机帧",
        "lexicon kind=merchant 货品规范名",
        "价格/限购",
        "丹药与吞卡关系的图鉴条目",
    )


@lru_cache(maxsize=1)
def load_atlas_view() -> AtlasView:
    entries = (
        _iter_skill_families()
        + _iter_skill_cards()
        + _iter_bonds()
        + _iter_treasures()
    )
    return AtlasView(tuple(entries))


def apply_to_run(
    names: Sequence[str],
    *,
    running: bool = False,
    view: AtlasView | None = None,
) -> AtlasApplyDiff:
    """单向出口：只产出 16 系短码 / 羁绊短码 / 负面放行。不改 Settings。"""
    tokens = [str(item).strip() for item in names if str(item).strip()]
    if running:
        return AtlasApplyDiff((), (), (), tuple(tokens), ("运行中禁止应用到白名单",))
    atlas = view or load_atlas_view()
    skills: list[str] = []
    cards: list[str] = []
    negatives: list[str] = []
    rejected: list[str] = []
    reasons: list[str] = []
    for token in tokens:
        entry = atlas.get(token)
        if entry is None:
            rejected.append(token)
            reasons.append(f"{token}：图鉴无此条")
            continue
        if entry.category == CATEGORY_SKILL_CARD:
            rejected.append(entry.name)
            reasons.append(f"{entry.name}：升级卡不能写入 settings.skills")
            continue
        if entry.category == CATEGORY_SKILL_FAMILY and entry.short_code:
            if entry.short_code in skills:
                continue
            if len(skills) >= MAX_APPLY_SKILLS:
                rejected.append(entry.name)
                reasons.append(f"{entry.name}：技能系已满{MAX_APPLY_SKILLS}")
                continue
            skills.append(entry.short_code)
            continue
        if entry.category == CATEGORY_BOND and entry.whitelist_ok and entry.short_code:
            if entry.short_code in cards:
                continue
            if len(cards) >= MAX_APPLY_BONDS:
                rejected.append(entry.name)
                reasons.append(f"{entry.name}：羁绊短码已满{MAX_APPLY_BONDS}")
                continue
            cards.append(entry.short_code)
            continue
        if entry.category == CATEGORY_TREASURE and "negative" in entry.flags:
            if entry.name not in negatives:
                negatives.append(entry.name)
            continue
        rejected.append(entry.name)
        if entry.category == CATEGORY_BOND:
            reasons.append(f"{entry.name}：仅知识、无短码，不能勾到运行")
        elif entry.category == CATEGORY_TREASURE:
            reasons.append(f"{entry.name}：宝物不进 skills；必拿由策略处理")
        else:
            reasons.append(f"{entry.name}：不能应用到本局白名单")
    return AtlasApplyDiff(
        tuple(skills),
        tuple(cards),
        tuple(negatives),
        tuple(rejected),
        tuple(reasons),
    )
