"""Offline scalar-cost contracts; these are not game-frame evidence."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.solo_scheduler import Candidate, Cost, Fact, UNKNOWN_PRICE, _dominates, _paid_legal


def _candidate(costs, *, cash_in_rank=1):
    return Candidate(
        action_id="audit", target="bond", kind="PAID_DRAW", legal=True,
        reject_reason="", fact_refs=(), costs=tuple(costs),
        expected_cash_in="confirmed_card", bottleneck="card",
        executor="existing", confirm_ref="confirmed", goal="same_goal",
        cash_in_rank=cash_in_rank, evidence_rank=1,
    )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), -1, True, "20", None, UNKNOWN_PRICE, 10**400])
def test_invalid_price_never_authorizes_shadow_spend(value):
    assert not Fact.observed(value).price_known
    assert not Cost("wood", value).price_known
    assert _paid_legal([Cost("wood", value)], {"wood": Fact.observed(100)}, spend_id="audit")[0] is False


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), -1, True, "100", None, 10**400])
def test_invalid_balance_never_authorizes_even_zero_cost(value):
    assert _paid_legal([Cost("wood", 0)], {"wood": Fact.observed(value)}, spend_id="audit")[0] is False


def test_same_currency_costs_share_one_budget_not_reusable_balance():
    costs = [Cost("wood", 40), Cost("wood", 20)]
    assert _paid_legal(costs, {"wood": Fact.observed(50)}, spend_id="chain") == (False, "INSUFFICIENT_BALANCE")
    assert _paid_legal(costs, {"wood": Fact.observed(60)}, spend_id="chain") == (True, "")
    assert _candidate(costs).cost_of("wood").amount == 60


def test_cost_aggregation_keeps_model_provenance_and_unknowns():
    total = _candidate([Cost("wood", 40), Cost("wood", 20, model_derived=True)]).cost_of("wood")
    assert total.amount == 60 and total.model_derived
    unknown = _candidate([Cost("wood", 40), Cost("wood", UNKNOWN_PRICE)]).cost_of("wood")
    assert not unknown.price_known


def test_duplicate_costs_cannot_fake_a_cheaper_dominating_candidate():
    a = _candidate([Cost("wood", 10), Cost("wood", 100)])
    b = _candidate([Cost("wood", 50)])
    assert not _dominates(a, b)
    assert _dominates(b, a)


def test_unknown_or_nonfinite_cost_cannot_dominate_via_another_dimension():
    for amount in (UNKNOWN_PRICE, float("nan"), float("inf"), -1):
        a = _candidate([Cost("wood", amount)], cash_in_rank=1)
        b = _candidate([Cost("wood", 50)], cash_in_rank=2)
        assert not _dominates(a, b)


def test_currency_budgets_remain_separate_and_known_zero_is_valid():
    assert _paid_legal([Cost("wood", 0)], {"wood": Fact.observed(0)}, spend_id="zero") == (True, "")
    assert not _paid_legal([Cost("wood", 0)], {"wood": Fact.unknown()}, spend_id="unknown")[0]
    assert not _paid_legal(
        [Cost("wood", 60), Cost("kill", 40)],
        {"wood": Fact.observed(50), "kill": Fact.observed(10000)}, spend_id="no_exchange",
    )[0]
