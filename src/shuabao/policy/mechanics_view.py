"""Read-only fail-closed adapter between game_mechanics_kb and choice policy.

Only facts with boolean ``live_verified is True`` AND ``wired_to_decision is True``
are exposed. Guide text, conflict notes, nested evidence objects, and illegal
schema all fail-closed to empty / 0.0 / False and never raise.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any


_DROP_KEYS = frozenset({"guide", "conflicts"})
_CHAIN_BUCKETS = ("chains", "skill_chains", "prereq_chains")
_CARD_BUCKETS = ("cards", "card_priority", "priority_modifiers")
_ACTION_BUCKETS = ("auto_actions", "safe_auto_actions", "script_auto_actions")


def _repo_root(explicit: Path | None = None) -> Path | None:
    if explicit is not None:
        return Path(explicit)
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    here = Path(__file__).resolve()
    for parent in (here.parent, *here.parents):
        if (parent / "config" / "game_mechanics_kb.json").is_file():
            return parent
    return None


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(k): v for k, v in value.items() if str(k) not in _DROP_KEYS}
    return {}


def _dual_gated(obj: Any) -> bool:
    """Boolean identity gate: nested objects / 'true' strings / 1 are not True."""
    if not isinstance(obj, Mapping):
        return False
    return obj.get("live_verified") is True and obj.get("wired_to_decision") is True


def _str_list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (str, int, float)):
            continue
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return tuple(out)


def _as_float(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return default
    return parsed


def _truthy_bool(value: Any) -> bool:
    return value is True


class MechanicsPolicyView:
    """Immutable snapshot of dual-gated mechanics facts. Queries never mutate."""

    __slots__ = ("_prereqs", "_mutex", "_priority", "_safe_actions")

    def __init__(self, payload: Any = None) -> None:
        prereqs: dict[str, tuple[str, ...]] = {}
        mutex: dict[str, tuple[str, ...]] = {}
        priority: dict[str, float] = {}
        safe_actions: dict[str, bool] = {}
        try:
            self._ingest(payload, prereqs, mutex, priority, safe_actions)
        except Exception:
            prereqs, mutex, priority, safe_actions = {}, {}, {}, {}
        object.__setattr__(self, "_prereqs", MappingProxyType(prereqs))
        object.__setattr__(self, "_mutex", MappingProxyType(mutex))
        object.__setattr__(self, "_priority", MappingProxyType(priority))
        object.__setattr__(self, "_safe_actions", MappingProxyType(safe_actions))

    def __setattr__(self, name: str, value: Any) -> None:
        if name in MechanicsPolicyView.__slots__ and not hasattr(self, name):
            object.__setattr__(self, name, value)
            return
        raise AttributeError("MechanicsPolicyView is immutable")

    @classmethod
    def empty(cls) -> "MechanicsPolicyView":
        return cls({})

    @classmethod
    def from_mapping(cls, payload: Any) -> "MechanicsPolicyView":
        return cls(payload)

    @classmethod
    def from_path(cls, path: str | Path) -> "MechanicsPolicyView":
        try:
            text = Path(path).read_text(encoding="utf-8")
            data = json.loads(text)
        except (OSError, ValueError, TypeError, UnicodeError):
            return cls.empty()
        return cls(data)

    @classmethod
    def from_repo(cls, root: str | Path | None = None) -> "MechanicsPolicyView":
        try:
            base = _repo_root(Path(root) if root is not None else None)
            if base is None:
                return cls.empty()
            return cls.from_path(base / "config" / "game_mechanics_kb.json")
        except Exception:
            return cls.empty()

    def get_prerequisites(self, chain_id: str) -> list[str]:
        try:
            key = str(chain_id or "").strip()
            if not key:
                return []
            return list(self._prereqs.get(key, ()))
        except Exception:
            return []

    def get_mutually_exclusive(self, chain_id: str) -> list[str]:
        try:
            key = str(chain_id or "").strip()
            if not key:
                return []
            return list(self._mutex.get(key, ()))
        except Exception:
            return []

    def get_priority_modifier(self, card_name: str) -> float:
        try:
            key = str(card_name or "").strip()
            if not key:
                return 0.0
            return float(self._priority.get(key, 0.0))
        except Exception:
            return 0.0

    def is_safe_auto_action(self, action_id: str) -> bool:
        try:
            key = str(action_id or "").strip()
            if not key:
                return False
            return self._safe_actions.get(key, False) is True
        except Exception:
            return False

    def _ingest(
        self,
        payload: Any,
        prereqs: dict[str, tuple[str, ...]],
        mutex: dict[str, tuple[str, ...]],
        priority: dict[str, float],
        safe_actions: dict[str, bool],
    ) -> None:
        if payload is None:
            return
        if isinstance(payload, (bytes, bytearray)):
            payload = payload.decode("utf-8")
        if isinstance(payload, str):
            text = payload.strip()
            if not text:
                return
            payload = json.loads(text)
        if not isinstance(payload, Mapping):
            return
        data = _as_mapping(payload)
        self._ingest_chain_bucket(data, prereqs, mutex)
        self._ingest_card_bucket(data, priority)
        self._ingest_action_bucket(data, safe_actions)
        facts = data.get("facts")
        if isinstance(facts, list):
            for row in facts:
                self._ingest_fact_row(row, prereqs, mutex, priority, safe_actions)
        elif isinstance(facts, Mapping):
            for key, row in facts.items():
                if not isinstance(row, Mapping):
                    continue
                merged = dict(row)
                merged.setdefault("id", key)
                self._ingest_fact_row(merged, prereqs, mutex, priority, safe_actions)

    def _ingest_chain_bucket(
        self,
        data: Mapping[str, Any],
        prereqs: dict[str, tuple[str, ...]],
        mutex: dict[str, tuple[str, ...]],
    ) -> None:
        for bucket in _CHAIN_BUCKETS:
            raw = data.get(bucket)
            if not isinstance(raw, Mapping):
                continue
            for chain_id, row in raw.items():
                self._apply_chain(str(chain_id), row, prereqs, mutex)

    def _ingest_card_bucket(
        self,
        data: Mapping[str, Any],
        priority: dict[str, float],
    ) -> None:
        for bucket in _CARD_BUCKETS:
            raw = data.get(bucket)
            if not isinstance(raw, Mapping):
                continue
            for card_name, row in raw.items():
                self._apply_card(str(card_name), row, priority)

    def _ingest_action_bucket(
        self,
        data: Mapping[str, Any],
        safe_actions: dict[str, bool],
    ) -> None:
        for bucket in _ACTION_BUCKETS:
            raw = data.get(bucket)
            if not isinstance(raw, Mapping):
                continue
            for action_id, row in raw.items():
                self._apply_action(str(action_id), row, safe_actions)

    def _ingest_fact_row(
        self,
        row: Any,
        prereqs: dict[str, tuple[str, ...]],
        mutex: dict[str, tuple[str, ...]],
        priority: dict[str, float],
        safe_actions: dict[str, bool],
    ) -> None:
        if not isinstance(row, Mapping) or not _dual_gated(row):
            return
        kind = str(row.get("kind") or row.get("type") or "").strip().lower()
        ident = str(row.get("id") or row.get("name") or row.get("chain_id") or "").strip()
        if kind in {"chain", "skill_chain"} or "prerequisites" in row or "mutually_exclusive" in row:
            self._apply_chain(ident or str(row.get("chain_id") or ""), row, prereqs, mutex)
        if kind in {"card", "priority"} or "priority_modifier" in row:
            self._apply_card(ident or str(row.get("card_name") or ""), row, priority)
        if kind in {"auto_action", "action"} or "safe" in row or "is_safe_auto_action" in row:
            self._apply_action(ident or str(row.get("action_id") or ""), row, safe_actions)

    def _apply_chain(
        self,
        chain_id: str,
        row: Any,
        prereqs: dict[str, tuple[str, ...]],
        mutex: dict[str, tuple[str, ...]],
    ) -> None:
        key = str(chain_id or "").strip()
        if not key or not _dual_gated(row):
            return
        body = _as_mapping(row)
        req = _str_list(body.get("prerequisites") or body.get("prereq") or body.get("requires"))
        excl = _str_list(
            body.get("mutually_exclusive")
            or body.get("mutex")
            or body.get("excludes")
        )
        if req:
            prereqs[key] = req
        if excl:
            mutex[key] = excl

    def _apply_card(self, card_name: str, row: Any, priority: dict[str, float]) -> None:
        key = str(card_name or "").strip()
        if not key or not _dual_gated(row):
            return
        body = _as_mapping(row)
        modifier = _as_float(body.get("priority_modifier", body.get("modifier", 0.0)))
        priority[key] = modifier

    def _apply_action(self, action_id: str, row: Any, safe_actions: dict[str, bool]) -> None:
        key = str(action_id or "").strip()
        if not key or not _dual_gated(row):
            return
        body = _as_mapping(row)
        safe = _truthy_bool(body.get("safe", body.get("is_safe_auto_action", body.get("safe_auto"))))
        if safe:
            safe_actions[key] = True
