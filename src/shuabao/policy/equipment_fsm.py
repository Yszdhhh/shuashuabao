"""Pure action lease for equipment interactions."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum, auto


class EquipmentSlotState(Enum):
    READY = auto()
    LEASED = auto()
    EXPIRED = auto()


@dataclass(frozen=True)
class EquipmentFSM:
    """One equipment input may be in flight; no second slot may bypass its lease."""

    pending_slot: int | None = None
    lease_until: float = 0.0
    states: tuple[tuple[int, EquipmentSlotState], ...] = ()

    def slot_state(self, slot: int) -> EquipmentSlotState:
        return dict(self.states).get(slot, EquipmentSlotState.READY)

    def begin(self, slot: int, now: float, *, lease_s: float) -> "EquipmentFSM":
        if self.pending_slot is not None or now < self.lease_until:
            return self
        next_states = dict(self.states)
        next_states[slot] = EquipmentSlotState.LEASED
        return EquipmentFSM(slot, now + max(0.0, lease_s), tuple(sorted(next_states.items())))

    def observe(self, now: float) -> "EquipmentFSM":
        if self.pending_slot is None or now < self.lease_until:
            return self
        next_states = dict(self.states)
        next_states[self.pending_slot] = EquipmentSlotState.EXPIRED
        return EquipmentFSM(states=tuple(sorted(next_states.items())))
