#!/usr/bin/env python3
"""Replay treasure decisions with the historical description OCR field on/off.

This is a decision-equivalence check, not a pixel replay.  The historical
tick traces contain the slots/rarity/policy inputs that reached ``choose_action``;
the paired replay changes only ``SlotCandidate.description``.  The separate
OCR trace is used to prove that the targeted legacy ``:desc`` calls were all
unavailable before a removal proposal is made.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
import sys

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from shuabao.choice_policy import (  # noqa: E402
    PanelCandidates,
    PolicyAction,
    SessionState,
    SlotCandidate,
    choose_action,
)
from shuabao.mediator import Mediator  # noqa: E402
from shuabao.settings import Settings  # noqa: E402


DEFAULT_OCR_TRACE = Path(r"C:\Users\10639\AppData\Local\ShuaBao\incidents\ocr_shadow.jsonl")
DEFAULT_TICK_ROOT = Path(r"C:\Users\10639\AppData\Local\ShuaBao")
DEFAULT_OUTPUT = ROOT / "docs" / "distillation" / "TREASURE_OCR_DECISION_REPLAY.json"
DEFAULT_EXPECTED_LEGACY_CALLS = 12_276


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, 1):
            if not raw.strip():
                continue
            item = json.loads(raw)
            if not isinstance(item, dict):
                raise ValueError(f"{path}:{line_no}: row is not an object")
            yield item


def _legacy_description(row: Mapping[str, Any]) -> bool:
    panel_id = str(row.get("panel_id") or "")
    return panel_id.startswith("treasure:") and panel_id.endswith(":desc")


def _panel_names(row: Mapping[str, Any]) -> set[str]:
    names: set[str] = set()
    for field in ("panel", "scenes", "controls"):
        values = row.get(field) or ()
        if not isinstance(values, list):
            continue
        for value in values:
            if isinstance(value, Mapping):
                name = value.get("name") or value.get("control")
            else:
                name = value
            if name:
                names.add(str(name))
    return names


def _historical_action_kinds(row: Mapping[str, Any]) -> Counter[str]:
    kinds: Counter[str] = Counter()
    for action in row.get("actions") or ():
        if not isinstance(action, Mapping):
            continue
        text = " ".join(
            str(action.get(key) or "")
            for key in ("intent", "reason", "target")
        ).lower()
        if "refresh" in text:
            kinds[PolicyAction.REFRESH.value] += 1
        elif any(token in text for token in ("close", "hide", "giveup")):
            kinds[PolicyAction.CLOSE.value] += 1
        elif "treasure" in text or "select" in text:
            kinds[PolicyAction.SELECT_SLOT.value] += 1
        else:
            kinds["OTHER"] += 1
    return kinds


def _slot(raw: Mapping[str, Any], description: str) -> SlotCandidate:
    name = raw.get("name")
    return SlotCandidate(
        index=int(raw.get("index", 0)),
        name=str(name) if name is not None and str(name).strip() else None,
        confidence=float(raw.get("confidence") or 0.0),
        evidence=str(raw.get("raw_text") or ""),
        rarity=(str(raw["rarity"]) if raw.get("rarity") is not None else None),
        description=description,
        family=(str(raw["family"]) if raw.get("family") is not None else None),
        prereq_marker=bool(raw.get("prereq_marker", False)),
        is_new=bool(raw.get("is_new", False)),
        skill_level=raw.get("skill_level"),
        family_source=str(raw.get("family_source") or "unknown"),
        zero_cost=bool(raw.get("zero_cost", False)),
    )


def _decision_signature(decision: Any) -> dict[str, Any]:
    return {
        "action": decision.action.value,
        "index": decision.index,
        "reason": decision.reason,
    }


def _replay_pair(
    row: Mapping[str, Any],
    policy_settings: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    suggestion = row.get("ocr_suggestion")
    if not isinstance(suggestion, Mapping):
        raise ValueError("treasure row has no ocr_suggestion object")
    raw_slots = suggestion.get("slots")
    if not isinstance(raw_slots, list):
        raise ValueError("treasure suggestion slots is not a list")
    if not all(isinstance(item, Mapping) for item in raw_slots):
        raise ValueError("treasure suggestion contains a non-object slot")

    names = {name.lower() for name in _panel_names(row)}
    panel = PanelCandidates(
        panel_kind="treasure",
        slots=tuple(_slot(item, str(item.get("description") or "")) for item in raw_slots),
        refresh_count=0,
        has_giveup=any(any(token in name for token in ("hide", "close", "giveup")) for name in names),
        can_refresh=any("refresh" in name for name in names),
        settings=policy_settings,
        free_slots=None,
    )
    disabled = PanelCandidates(
        panel_kind=panel.panel_kind,
        slots=tuple(
            replace_description(slot, "")
            for slot in panel.slots
        ),
        refresh_count=panel.refresh_count,
        has_giveup=panel.has_giveup,
        can_refresh=panel.can_refresh,
        settings=panel.settings,
        free_slots=panel.free_slots,
    )
    session = SessionState()
    return (
        _decision_signature(choose_action(panel, session)),
        _decision_signature(choose_action(disabled, session)),
    )


def replace_description(slot: SlotCandidate, description: str) -> SlotCandidate:
    """Keep every recorded slot fact and change only the OCR description."""
    return SlotCandidate(
        index=slot.index,
        name=slot.name,
        confidence=slot.confidence,
        evidence=slot.evidence,
        rarity=slot.rarity,
        description=description,
        family=slot.family,
        prereq_marker=slot.prereq_marker,
        is_new=slot.is_new,
        skill_level=slot.skill_level,
        card_fact=slot.card_fact,
        family_source=slot.family_source,
        zero_cost=slot.zero_cost,
    )


def _load_policy_settings() -> Any:
    # OCR is explicitly off for this offline replay; the policy snapshot is
    # still assembled from the repository's current production documents.
    return Mediator(Settings(ocr_mode="off"), ROOT)._policy_settings()


def replay(
    ocr_trace: Path = DEFAULT_OCR_TRACE,
    tick_root: Path = DEFAULT_TICK_ROOT,
    output: Path = DEFAULT_OUTPUT,
    expected_legacy_calls: int = DEFAULT_EXPECTED_LEGACY_CALLS,
) -> dict[str, Any]:
    legacy_rows = list(_read_jsonl(ocr_trace)) if ocr_trace.is_file() else []
    targeted = [row for row in legacy_rows if _legacy_description(row)]
    statuses = Counter(str(row.get("status") or "missing") for row in targeted)
    unavailable = sum(status == "unavailable" for status in (str(row.get("status") or "missing") for row in targeted))

    tick_files = sorted(
        path
        for path in tick_root.rglob("trace*.jsonl")
        if path.is_file()
    ) if tick_root.is_dir() else []
    policy_settings = _load_policy_settings()
    replay_rows = 0
    action_rows = 0
    description_values = 0
    mismatch_count = 0
    mismatches: list[dict[str, Any]] = []
    errors: list[str] = []
    historical_actions: Counter[str] = Counter()
    enabled_actions: Counter[str] = Counter()
    disabled_actions: Counter[str] = Counter()

    for path in tick_files:
        try:
            rows = _read_jsonl(path)
            for row in rows:
                suggestion = row.get("ocr_suggestion")
                if not isinstance(suggestion, Mapping) or suggestion.get("kind") != "treasure":
                    continue
                replay_rows += 1
                if row.get("actions"):
                    action_rows += 1
                    historical_actions.update(_historical_action_kinds(row))
                for slot in suggestion.get("slots") or ():
                    if isinstance(slot, Mapping) and str(slot.get("description") or "").strip():
                        description_values += 1
                try:
                    enabled, disabled = _replay_pair(row, policy_settings)
                except (TypeError, ValueError, KeyError) as exc:
                    errors.append(f"{path}:{row.get('tick', '?')}: {exc}")
                    continue
                enabled_actions[enabled["action"]] += 1
                disabled_actions[disabled["action"]] += 1
                if enabled != disabled:
                    mismatch_count += 1
                    if len(mismatches) < 25:
                        mismatches.append(
                            {
                                "file": str(path),
                                "tick": row.get("tick"),
                                "frame_fingerprint": row.get("frame_fingerprint"),
                                "enabled": enabled,
                                "disabled": disabled,
                            }
                        )
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            errors.append(f"{path}: {exc}")

    all_unavailable = bool(targeted) and unavailable == len(targeted)
    count_matches = len(targeted) == expected_legacy_calls
    equivalence_pass = bool(replay_rows) and not errors and mismatch_count == 0
    recommendation = (
        "ALLOW_PROPOSAL_ONLY: legacy unavailable description call can be removed "
        "after review; retain description field and negative policy semantics"
        if all_unavailable and count_matches and equivalence_pass
        else "REJECT: do not remove the runtime description OCR call"
    )
    report = {
        "schema_version": 1,
        "status": "COMPLETED" if not errors else "FAILED",
        "scope": {
            "ocr_trace": str(ocr_trace),
            "tick_trace_root": str(tick_root),
            "description_call_selector": "panel_id starts treasure: and ends :desc (legacy format)",
            "replay_type": "historical tick decision snapshots; not a pixel/full-Mediator replay",
        },
        "legacy_description_calls": {
            "calls": len(targeted),
            "status": dict(statuses),
            "unavailable": unavailable,
            "all_unavailable": all_unavailable,
            "expected_calls": expected_legacy_calls,
            "count_matches_expected": count_matches,
        },
        "historical_treasure_decisions": {
            "trace_files": len(tick_files),
            "suggestion_rows": replay_rows,
            "action_bearing_rows": action_rows,
            "recorded_action_kinds": dict(historical_actions),
            "nonempty_description_values": description_values,
            "replayed_enabled_action_kinds": dict(enabled_actions),
            "replayed_disabled_action_kinds": dict(disabled_actions),
        },
        "decision_equivalence": {
            "enabled_field": "historical SlotCandidate.description",
            "disabled_field": "description=''",
            "compared_rows": replay_rows,
            "mismatch_count": mismatch_count,
            "mismatch_sample": mismatches,
            "status": "PASS" if equivalence_pass else "FAIL",
        },
        "business_semantics": {
            "description_field": "retained",
            "negative_patterns": "retained",
            "negative_names": "retained",
            "negative_patterns_count": len(getattr(policy_settings, "treasure_negative_patterns", ()) or ()),
            "negative_names_count": len(getattr(policy_settings, "treasure_negative_names", ()) or ()),
            "runtime_call_change_applied": False,
        },
        "removal_recommendation": recommendation,
        "errors": errors[:25],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ocr-trace", type=Path, default=DEFAULT_OCR_TRACE)
    parser.add_argument("--tick-root", type=Path, default=DEFAULT_TICK_ROOT)
    parser.add_argument("--json-out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--expected-legacy-calls", type=int, default=DEFAULT_EXPECTED_LEGACY_CALLS)
    args = parser.parse_args(argv)
    report = replay(args.ocr_trace, args.tick_root, args.json_out, args.expected_legacy_calls)
    print(
        json.dumps(
            {
                "status": report["status"],
                "json": str(args.json_out.resolve()),
                "legacy_description_calls": report["legacy_description_calls"],
                "decision_equivalence": report["decision_equivalence"],
                "removal_recommendation": report["removal_recommendation"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["status"] == "COMPLETED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
