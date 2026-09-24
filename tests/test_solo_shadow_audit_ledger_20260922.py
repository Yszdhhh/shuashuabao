"""Read failures are not an observed empty inventory (no game frames)."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.solo_shadow import build_snapshot, snapshot_summary

FIELDS = (
    ("_confirmed_bond_cards", "confirmed_bond_cards"),
    ("_confirmed_skill_cards", "confirmed_skill_cards"),
)


@pytest.mark.parametrize("source,field", FIELDS)
@pytest.mark.parametrize("value", [None, "card", {"card": 1}, 1, [None], [""]])
def test_missing_or_malformed_ledger_is_not_confirmed_empty(source, field, value):
    med = SimpleNamespace(**{source: value})
    fact = getattr(build_snapshot(med, now=1.0), field)
    assert not fact.ok
    assert fact.value is None
    assert fact.state == ("missing" if value is None else "invalid")


@pytest.mark.parametrize("source,field", FIELDS)
def test_absent_ledger_remains_missing_in_snapshot_and_json(source, field):
    snap = build_snapshot(SimpleNamespace(), now=1.0)
    assert getattr(snap, field).state == "missing"
    assert snapshot_summary(snap)[field]["value"] is None


@pytest.mark.parametrize("source,field", FIELDS)
def test_raising_getter_is_invalid_without_affecting_other_signals(source, field):
    def broken():
        raise RuntimeError("ledger read failed")
    med = SimpleNamespace(_wood_balance=100, **{source: broken})
    snap = build_snapshot(med, now=1.0)
    assert getattr(snap, field).state == "invalid"
    assert getattr(snap, field).value is None
    assert snap.wood.value == 100


@pytest.mark.parametrize("source,field", FIELDS)
def test_genuine_empty_and_duplicate_cards_keep_confirmed_semantics(source, field):
    for value in ([], (), ["card", "card"], ("card", "card")):
        med = SimpleNamespace(**{source: lambda value=value: value})
        fact = getattr(build_snapshot(med, now=1.0), field)
        assert fact.ok and fact.value == list(value)
        assert fact.source == "mediator." + source


def test_requested_cards_stay_outside_confirmed_ledger_and_source_is_unchanged():
    owned = ["owned", "owned"]
    pending = ["requested"]
    med = SimpleNamespace(
        _confirmed_bond_cards=owned, _confirmed_skill_cards=[],
        _bond_cards_pending=pending,
    )
    before = vars(med).copy()
    snap = build_snapshot(med, now=1.0)
    assert snap.confirmed_bond_cards.value == ["owned", "owned"]
    assert [r.state for r in snap.pending_records] == ["requested"]
    assert all(not r.advances_ledger for r in snap.pending_records)
    snap.confirmed_bond_cards.value.append("local-copy-only")
    assert owned == ["owned", "owned"] and pending == ["requested"]
    assert vars(med) == before
