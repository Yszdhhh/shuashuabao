"""Deterministic, deadline-aged scheduler; it never captures or sends input."""
from __future__ import annotations

from dataclasses import dataclass, replace
import math

from .transactions import Lease, Outcome, Receipt


@dataclass(frozen=True)
class TaskSpec:
    name: str
    priority: int
    max_wait: float
    quantum: float
    retry_base: float = 30.0
    retry_max: float = 120.0
    no_progress_limit: int = 3

    def __post_init__(self) -> None:
        if not self.name or any(not math.isfinite(x) or x <= 0 for x in (
            self.max_wait, self.quantum, self.retry_base, self.retry_max
        )) or self.no_progress_limit < 1 or self.retry_max < self.retry_base:
            raise ValueError("invalid task budget")


# Engineering service targets, NOT measured game mechanics or hard guarantees.
DEFAULT_TASKS = (
    TaskSpec("hero", 0, 10, 8), TaskSpec("critical_item", 1, 15, 8),
    TaskSpec("bond", 2, 45, 8), TaskSpec("skill", 3, 30, 8),
    TaskSpec("treasure", 3, 30, 8), TaskSpec("pickup", 4, 30, 3),
    TaskSpec("overflow", 4, 30, 8), TaskSpec("personal_bag", 5, 60, 8),
    TaskSpec("equipment", 5, 60, 8), TaskSpec("artifact", 4, 60, 3),
    TaskSpec("silver_moon", 5, 60, 8), TaskSpec("merchant", 6, 90, 8),
    TaskSpec("public_bag", 6, 90, 8), TaskSpec("devour_inspect", 7, 120, 5),
)


@dataclass(frozen=True)
class Demand:
    task: str
    requested: bool
    eligible: bool
    revision: str
    blocked_reason: str = ""
    urgency: int = 0  # bounded preference, cannot defeat overdue service


@dataclass(frozen=True)
class Account:
    pending_since: float | None = None
    eligible_wait: float = 0.0
    last_seen: float = -math.inf
    was_eligible: bool = False
    revision: str = ""
    cooldown_until: float = 0.0
    no_progress: int = 0
    last_service: float = -math.inf
    service_count: int = 0
    confirmed_count: int = 0


@dataclass(frozen=True)
class Grant:
    token: str
    task: str
    started_at: float
    deadline: float
    generation: int
    revision: str
    reason: str
    eligible_wait: float
    wall_wait: float


@dataclass(frozen=True)
class Decision:
    grant: Grant | None
    reason: str
    overdue: tuple[str, ...] = ()


class Arbiter:
    """A round-local object driven by explicit monotonic time and fresh facts.

    max_wait measures wait for a SERVICE ATTEMPT, not guaranteed game progress.
    Repeated no-progress probes open a circuit until relevant revision changes.
    The caller must bound/reconcile every transaction; expiry never releases it.
    """
    def __init__(self, round_id: str, specs: tuple[TaskSpec, ...] = DEFAULT_TASKS,
                 max_observation_age: float = 3.0) -> None:
        if (not round_id or not specs or len({s.name for s in specs}) != len(specs)
                or not math.isfinite(max_observation_age) or max_observation_age <= 0):
            raise ValueError("invalid round, task registry or observation age")
        self.round_id = round_id
        self.specs = {s.name: s for s in specs}
        self.accounts = {s.name: Account() for s in specs}
        self.demands: dict[str, Demand] = {}
        self.active: Grant | None = None
        self.max_age = max_observation_age
        self._now = -math.inf
        self._observed_at = -math.inf
        self._generation = -1
        self._seq = 0

    def _time(self, now: float) -> None:
        if not math.isfinite(now) or now < self._now:
            raise ValueError("non-monotonic or non-finite time")
        self._now = now

    def observe(self, demands: tuple[Demand, ...], now: float, generation: int) -> None:
        self._time(now)
        if generation <= self._generation:
            raise ValueError("a new observation generation is required")
        if (len({d.task for d in demands}) != len(demands)
                or any(d.task not in self.specs or not d.revision
                       or (d.eligible and not d.requested)
                       or (d.requested and not d.eligible and not d.blocked_reason)
                       or not 0 <= d.urgency <= 2 for d in demands)):
            raise ValueError("invalid demand registry or evidence revision")
        incoming = {d.task: d for d in demands}
        for name, old in self.accounts.items():
            d = incoming.get(name)
            requested = d is not None and d.requested
            ready = bool(requested and d.eligible)
            gap = now - old.last_seen
            credit = gap if old.was_eligible and ready and 0 <= gap <= self.max_age else 0.0
            revision_changed = bool(d and d.revision != old.revision)
            # Missing observations do not silently erase an existing demand's age.
            pending = (old.pending_since if d is None else
                       (old.pending_since if old.pending_since is not None else now)
                       if requested else None)
            self.accounts[name] = replace(
                old, pending_since=pending,
                eligible_wait=(old.eligible_wait + credit if pending is not None else 0.0),
                was_eligible=ready, last_seen=now,
                revision=d.revision if d else old.revision,
                no_progress=0 if revision_changed else old.no_progress,
                cooldown_until=min(old.cooldown_until, now) if revision_changed else old.cooldown_until,
            )
        self.demands = incoming
        self._generation = generation
        self._observed_at = now

    def choose(self, now: float, *, input_safe: bool, owner: Lease | None = None) -> Decision:
        self._time(now)
        if owner is not None:
            return Decision(None, "owner_requires_reconcile" if now >= owner.deadline else "owner_continuation")
        if self.active is not None:
            return Decision(None, "grant_requires_reconcile" if now >= self.active.deadline else "grant_in_progress")
        if input_safe is not True:
            return Decision(None, "unsafe_surface_zero_input")
        if now - self._observed_at > self.max_age:
            return Decision(None, "stale_observation_zero_input")
        ready: list[str] = []
        for name, d in self.demands.items():
            a, s = self.accounts[name], self.specs[name]
            if (d.requested and d.eligible and now >= a.cooldown_until
                    and a.no_progress < s.no_progress_limit):
                ready.append(name)
        overdue = tuple(sorted(n for n in ready if self.accounts[n].eligible_wait >= self.specs[n].max_wait))
        if not ready:
            return Decision(None, "no_eligible_work", overdue)

        def key(name: str) -> tuple:
            a, s, d = self.accounts[name], self.specs[name], self.demands[name]
            if name in overdue:
                return (0, s.max_wait - a.eligible_wait, a.last_service, name)
            return (1, s.priority - d.urgency, -a.eligible_wait / s.max_wait, a.last_service, name)

        winner = min(ready, key=key)
        a, s, d = self.accounts[winner], self.specs[winner], self.demands[winner]
        self._seq += 1
        self.active = Grant(
            f"{self.round_id}:{self._seq}", winner, now, now + s.quantum,
            self._generation, d.revision,
            "deadline_service" if winner in overdue else "priority_with_aging",
            a.eligible_wait, now - a.pending_since if a.pending_since is not None else 0.0,
        )
        return Decision(self.active, self.active.reason, overdue)

    def finish(self, receipt: Receipt, now: float) -> None:
        self._time(now)
        g = self.active
        if (g is None or receipt.token != g.token or receipt.owner != g.task
                or receipt.generation < g.generation or receipt.closed_at > now
                or receipt.closed_at < g.started_at or not math.isfinite(receipt.closed_at)):
            raise ValueError("receipt does not settle this grant")
        a, s = self.accounts[g.task], self.specs[g.task]
        confirmed = receipt.outcome is Outcome.CONFIRMED
        if confirmed and receipt.closed_at >= g.deadline:
            raise ValueError("late success receipt requires reconciliation")
        if not isinstance(receipt.outcome, Outcome):
            raise ValueError("invalid receipt outcome")
        failures = 0 if confirmed else a.no_progress + 1
        delay = 0.0 if confirmed else min(s.retry_max, s.retry_base * 2 ** min(failures - 1, 16))
        self.accounts[g.task] = replace(
            a, pending_since=now, eligible_wait=0.0, was_eligible=False,
            last_service=now, cooldown_until=now + delay, no_progress=failures,
            service_count=a.service_count + 1,
            confirmed_count=a.confirmed_count + int(confirmed),
        )
        self.active = None
        # An action invalidates the old observation. A fresh snapshot must re-admit work.
        self._observed_at = -math.inf

    def diagnostics(self, now: float) -> dict:
        self._time(now)
        return {n: {
            "wall_wait": now - a.pending_since if a.pending_since is not None else 0.0,
            "eligible_wait": a.eligible_wait, "service_count": a.service_count,
            "max_wait_target": self.specs[n].max_wait,
            "deadline_miss": a.eligible_wait >= self.specs[n].max_wait,
            "confirmed_count": a.confirmed_count, "no_progress": a.no_progress,
            "circuit_open": a.no_progress >= self.specs[n].no_progress_limit,
            "blocked_reason": self.demands[n].blocked_reason if n in self.demands else "not_observed",
        } for n, a in self.accounts.items()}
