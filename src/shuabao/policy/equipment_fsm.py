"""Pure action lease and visual quarantine for equipment interactions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class EquipmentSlotState(Enum):
    READY = auto()
    LEASED = auto()
    CONFIRMED = auto()
    QUARANTINED = auto()
    EXPIRED = auto()


@dataclass(frozen=True)
class EquipmentFSM:
    """One equipment input may be in flight; no second slot may bypass its lease or quarantine."""

    pending_slot: int | None = None
    lease_until: float = 0.0
    quarantine_until: float = 0.0
    last_fingerprint: str = ""
    states: tuple[tuple[int, EquipmentSlotState], ...] = ()

    def slot_state(self, slot: int) -> EquipmentSlotState:
        return dict(self.states).get(slot, EquipmentSlotState.READY)

    def can_use(self, slot: int, now: float) -> bool:
        if self.pending_slot is not None and now < self.lease_until:
            return False
        if now < self.quarantine_until:
            return False
        return self.slot_state(slot) in (EquipmentSlotState.READY, EquipmentSlotState.CONFIRMED, EquipmentSlotState.EXPIRED)

    def begin(self, slot: int, now: float, *, lease_s: float = 1.0, fingerprint: str = "") -> "EquipmentFSM":
        if not self.can_use(slot, now):
            return self
        next_states = dict(self.states)
        next_states[slot] = EquipmentSlotState.LEASED
        return EquipmentFSM(
            pending_slot=slot,
            lease_until=now + max(0.0, lease_s),
            quarantine_until=self.quarantine_until,
            last_fingerprint=fingerprint,
            states=tuple(sorted(next_states.items())),
        )

    def observe(self, now: float, current_fingerprint: str = "") -> "EquipmentFSM":
        if self.pending_slot is None:
            return self
        slot = self.pending_slot
        next_states = dict(self.states)

        # Visual confirmation: fingerprint changed -> success
        if current_fingerprint and self.last_fingerprint and current_fingerprint != self.last_fingerprint:
            next_states[slot] = EquipmentSlotState.CONFIRMED
            return EquipmentFSM(
                pending_slot=None,
                lease_until=0.0,
                quarantine_until=now + 0.5,
                last_fingerprint=current_fingerprint,
                states=tuple(sorted(next_states.items())),
            )

        # Timeout expired without confirmation -> quarantine to prevent spam
        if now >= self.lease_until:
            next_states[slot] = EquipmentSlotState.QUARANTINED
            return EquipmentFSM(
                pending_slot=None,
                lease_until=0.0,
                quarantine_until=now + 2.0,  # 2s cooldown quarantine
                last_fingerprint=current_fingerprint,
                states=tuple(sorted(next_states.items())),
            )

        return self
