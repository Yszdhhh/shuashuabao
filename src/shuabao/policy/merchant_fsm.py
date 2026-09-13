"""Pure, fail-closed merchant action state machine."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum, auto


class MerchantPhase(Enum):
    ABSENT = auto()
    CONFIRMING = auto()
    READY = auto()
    VERIFYING = auto()
    EVICTED = auto()


@dataclass(frozen=True)
class MerchantFSM:
    """Require two identical merchant frames before input and mutation after it."""

    phase: MerchantPhase = MerchantPhase.ABSENT
    fingerprint: str = ""
    purchases: int = 0
    rerolls: int = 0
    pending_fingerprint: str = ""
    deadline: float = 0.0

    def observe(self, present: bool, fingerprint: str, now: float) -> "MerchantFSM":
        if not present:
            return MerchantFSM()
        if not fingerprint:
            return replace(self, phase=MerchantPhase.CONFIRMING, fingerprint="")
        if self.phase is MerchantPhase.EVICTED:
            # A timed-out purchase must never be retried against the same
            # stock.  A later, visibly different stock is a new encounter,
            # though: keeping EVICTED forever made every later pill invisible
            # until the whole merchant disappeared.
            if fingerprint == self.fingerprint or fingerprint == self.pending_fingerprint:
                return self
            return replace(
                self,
                phase=MerchantPhase.CONFIRMING,
                fingerprint=fingerprint,
                pending_fingerprint="",
                deadline=0.0,
            )
        if self.phase is MerchantPhase.VERIFYING:
            if fingerprint != self.pending_fingerprint:
                return replace(self, phase=MerchantPhase.CONFIRMING, fingerprint=fingerprint,
                               pending_fingerprint="", deadline=0.0)
            if now >= self.deadline:
                # A refresh of five unknown slots often keeps the same occupancy
                # fingerprint. That is not a dead merchant; keep recycling while
                # the game still shows the refresh control. A timed-out purchase
                # stays fail-closed.
                if self.purchases == 0:
                    return replace(self, phase=MerchantPhase.READY, pending_fingerprint="", deadline=0.0)
                return replace(self, phase=MerchantPhase.EVICTED)
            return self
        if self.phase is MerchantPhase.READY and fingerprint == self.fingerprint:
            return self
        if self.phase is MerchantPhase.CONFIRMING and fingerprint == self.fingerprint:
            return replace(self, phase=MerchantPhase.READY)
        return replace(self, phase=MerchantPhase.CONFIRMING, fingerprint=fingerprint)

    def can_purchase(self, cap: int) -> bool:
        return self.phase is MerchantPhase.READY and self.purchases < max(0, cap)

    def can_reroll(self, cap: int) -> bool:
        return self.phase is MerchantPhase.READY and self.rerolls < max(0, cap)

    def begin_purchase(self, now: float, *, timeout_s: float) -> "MerchantFSM":
        if not self.can_purchase(5):
            return self
        return replace(self, phase=MerchantPhase.VERIFYING, purchases=self.purchases + 1,
                       pending_fingerprint=self.fingerprint, deadline=now + max(0.0, timeout_s))

    def begin_reroll(self, now: float, *, timeout_s: float, cap: int = 20) -> "MerchantFSM":
        if not self.can_reroll(cap):
            return self
        return replace(
            self,
            phase=MerchantPhase.VERIFYING,
            rerolls=self.rerolls + 1,
            purchases=0,
            pending_fingerprint=self.fingerprint,
            deadline=now + max(0.0, timeout_s),
        )
