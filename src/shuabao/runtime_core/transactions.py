"""Exclusive UI ownership with positive, fresh postconditions and safe release."""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import math


class Phase(str, Enum):
    READY = "READY"
    VERIFYING = "VERIFYING"
    RECONCILE = "RECONCILE"


class Outcome(str, Enum):
    CONFIRMED = "CONFIRMED"
    NO_PROGRESS = "NO_PROGRESS"
    ABORTED_SAFE = "ABORTED_SAFE"


@dataclass(frozen=True)
class Proof:
    generation: int
    captured_at: float
    epoch: str
    valid: bool
    postcondition: bool | None = None
    cursor_empty: bool | None = None
    surface_released: bool | None = None

    def fresh(self, now: float, max_age: float) -> bool:
        return (self.valid is True and self.generation >= 0 and bool(self.epoch)
                and math.isfinite(self.captured_at) and math.isfinite(now)
                and 0 <= now - self.captured_at <= max_age)


@dataclass(frozen=True)
class Lease:
    token: str
    owner: str
    deadline: float
    epoch: str
    phase: Phase = Phase.READY
    before_generation: int = -1
    last_generation: int = -1
    dispatched_at: float = 0.0
    action_id: str = ""
    confirmed_steps: int = 0
    compensating: bool = False
    reason: str = ""


@dataclass(frozen=True)
class Receipt:
    """Internal protocol object, not independent proof that LIVE occurred."""
    token: str
    owner: str
    outcome: Outcome
    generation: int
    closed_at: float


class LeaseBook:
    """One owner across panel, cursor, bag and consumption operations.

    Expiry is NOT release. Only a verified safe boundary releases ownership.
    All time values must come from one monotonic clock supplied by the caller.
    """
    def __init__(self, max_proof_age: float = 2.0) -> None:
        if not math.isfinite(max_proof_age) or max_proof_age <= 0:
            raise ValueError("positive proof age required")
        self.max_proof_age = max_proof_age
        self.current: Lease | None = None
        self._clock = -math.inf
        self._used_tokens: set[str] = set()

    def _time(self, now: float) -> None:
        if not math.isfinite(now) or now < self._clock:
            raise ValueError("non-monotonic or non-finite time")
        self._clock = now

    def _owned(self, token: str) -> Lease:
        if self.current is None or self.current.token != token:
            raise ValueError("wrong or released transaction token")
        return self.current

    def acquire(self, token: str, owner: str, now: float,
                timeout: float, proof: Proof) -> Lease:
        self._time(now)
        if self.current is not None:
            raise RuntimeError("UI already leased")
        if not token or token in self._used_tokens or not owner:
            raise ValueError("unique token and owner required")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("positive finite timeout required")
        if not proof.fresh(now, self.max_proof_age):
            raise ValueError("no fresh entry proof")
        self.current = Lease(token, owner, now + timeout, proof.epoch,
                             last_generation=proof.generation)
        self._used_tokens.add(token)
        return self.current

    def dispatch(self, token: str, action_id: str, now: float, proof: Proof) -> Lease:
        self._time(now)
        lease = self._owned(token)
        if lease.phase is not Phase.READY or now >= lease.deadline:
            raise RuntimeError("no dispatch authority")
        if (not action_id or not proof.fresh(now, self.max_proof_age)
                or proof.epoch != lease.epoch
                or proof.generation < lease.last_generation):
            raise ValueError("stale or unrelated dispatch proof")
        # This records a request, NEVER a successful game mutation.
        self.current = replace(lease, phase=Phase.VERIFYING,
                               before_generation=proof.generation,
                               dispatched_at=now, action_id=action_id)
        return self.current

    def observe(self, token: str, now: float, proof: Proof) -> Lease:
        self._time(now)
        lease = self._owned(token)
        if now >= lease.deadline:
            self.current = replace(lease, phase=Phase.RECONCILE, reason="deadline")
        elif proof.epoch != lease.epoch:
            self.current = replace(lease, phase=Phase.RECONCILE, reason="epoch_changed")
        elif (lease.phase is Phase.VERIFYING
              and proof.fresh(now, self.max_proof_age)
              and proof.generation > lease.before_generation
              and proof.captured_at >= lease.dispatched_at):
            if proof.postcondition is True:
                self.current = replace(lease, phase=Phase.READY,
                                       last_generation=proof.generation,
                                       confirmed_steps=lease.confirmed_steps + 1)
            elif proof.postcondition is False:
                self.current = replace(lease, phase=Phase.RECONCILE,
                                       reason="postcondition_failed")
        return self.current

    def compensate(self, token: str, now: float, timeout: float, proof: Proof) -> Lease:
        """Caller must supply a separately authorized reversible action plan.

        This permits no clicks itself and does not claim the game was rolled back.
        """
        self._time(now)
        lease = self._owned(token)
        if lease.phase is not Phase.RECONCILE or lease.compensating:
            raise RuntimeError("one compensation attempt allowed after reconciliation")
        if (not math.isfinite(timeout) or timeout <= 0
                or not proof.fresh(now, self.max_proof_age)
                or proof.generation <= lease.before_generation):
            raise ValueError("fresh compensation evidence required")
        self.current = replace(lease, phase=Phase.READY, epoch=proof.epoch,
                               deadline=now + timeout, last_generation=proof.generation,
                               compensating=True, reason="compensation_only")
        return self.current

    def release(self, token: str, outcome: Outcome, now: float, proof: Proof) -> Receipt:
        self._time(now)
        lease = self._owned(token)
        if (not isinstance(outcome, Outcome) or lease.phase is Phase.VERIFYING
                or not proof.fresh(now, self.max_proof_age)
                or proof.epoch != lease.epoch
                or proof.generation < lease.last_generation
                or proof.generation <= lease.before_generation
                or proof.cursor_empty is not True
                or proof.surface_released is not True):
            raise RuntimeError("unverified safe boundary: retain owner")
        if outcome is Outcome.CONFIRMED and (
            lease.phase is not Phase.READY or lease.confirmed_steps == 0
            or lease.compensating or now >= lease.deadline
        ):
            raise RuntimeError("dispatch/timeout/compensation is not business success")
        if outcome is Outcome.NO_PROGRESS and (
            lease.confirmed_steps or lease.phase is not Phase.READY or lease.compensating
        ):
            raise RuntimeError("no-progress receipt cannot erase unresolved work")
        receipt = Receipt(lease.token, lease.owner, outcome, proof.generation, now)
        self.current = None
        return receipt
