"""Conservative facts and authorization. Configuration is intent, not observation."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math

from .transactions import Proof


class ItemKind(str, Enum):
    ARTIFACT = "artifact"
    TREASURE = "treasure"
    EQUIPMENT = "equipment"
    CONSUMABLE = "consumable"
    BOUNTY = "pirate_bounty"
    PILL = "swallow_pill"
    GOD_PILL = "god_swallow_pill"
    UNKNOWN = "unknown"


class Location(str, Enum):
    ITEM_BAR = "item_bar"
    PERSONAL_BAG = "personal_bag"
    PUBLIC_BAG = "public_bag"
    DEFER = "defer"


@dataclass(frozen=True)
class CardInstance:
    instance_id: str
    canonical_id: str
    family: str
    rarity: int | None
    protected: bool = False


@dataclass(frozen=True)
class ItemFact:
    instance_id: str
    kind: ItemKind
    owner: str  # self, team, unknown
    location: Location
    rarity: int | None = None
    compatible: bool | None = None
    marginal_gain: float | None = None
    bar_effect_verified: bool = False


@dataclass(frozen=True)
class Authorization:
    allowed: bool
    reason: str


# Stable machine IDs. A visual adapter must map observed names to these IDs.
CORE_PIRATE_IDS = frozenset({"pirate.admiral_rogers", "pirate.destruction_warship"})


def authorize_consumption(item: ItemFact, targets: tuple[CardInstance, ...], *,
                          explicitly_enabled: bool, solo: bool,
                          target_set_complete: bool, mechanism_verified: bool,
                          transaction_active: bool, proof: Proof, now: float) -> Authorization:
    """Targets means ALL possible victims, or the positively selected target.

    Never infer target safety from occupancy, configured decks, OCR word counts,
    item rarity alone, or one safe card among several possible victims.
    """
    def deny(reason: str) -> Authorization:
        return Authorization(False, reason)
    if explicitly_enabled is not True or solo is not True:
        return deny("disabled_or_non_solo")
    if transaction_active:
        return deny("another_transaction_owns_ui")
    if not proof.fresh(now, 2.0) or proof.cursor_empty is not True:
        return deny("fresh_safe_evidence_missing")
    if item.owner != "self" or item.location not in {Location.ITEM_BAR, Location.PERSONAL_BAG}:
        return deny("not_personal_asset")
    if item.kind not in {ItemKind.BOUNTY, ItemKind.PILL, ItemKind.GOD_PILL}:
        return deny("unsupported_consumption")
    if not mechanism_verified or not target_set_complete or not targets:
        return deny("target_mechanism_or_complete_target_set_missing")
    if (len({t.instance_id for t in targets}) != len(targets)
            or any(not t.instance_id or not t.canonical_id or not t.family for t in targets)):
        return deny("target_identity_missing_or_duplicate")
    if any(t.protected or t.canonical_id in CORE_PIRATE_IDS for t in targets):
        return deny("protected_target_possible")
    if item.kind is ItemKind.BOUNTY:
        if (item.rarity not in range(1, 6)
                or any(t.family != "pirate" or t.rarity not in range(1, 6)
                       or t.rarity > item.rarity for t in targets)):
            return deny("bounty_quality_or_target_unknown_or_ineligible")
    if item.kind is ItemKind.GOD_PILL and any(t.rarity != 6 for t in targets):
        return deny("god_pill_requires_confirmed_ex_targets")
    return Authorization(True, "all_possible_targets_authorized")


def destination(item: ItemFact, *, transfer_enabled: bool = False) -> Location:
    """Pure location recommendation; not movement/click authority."""
    if not item.instance_id or item.owner == "unknown" or item.kind is ItemKind.UNKNOWN:
        return Location.DEFER
    if item.owner == "team":
        return Location.PUBLIC_BAG if transfer_enabled else Location.DEFER
    if item.owner != "self":
        return Location.DEFER
    if item.kind in {ItemKind.ARTIFACT, ItemKind.TREASURE}:
        return Location.ITEM_BAR if item.bar_effect_verified else Location.DEFER
    if item.kind is ItemKind.EQUIPMENT:
        if item.compatible is None:
            return Location.DEFER
        if (item.compatible and item.marginal_gain is not None
                and math.isfinite(item.marginal_gain) and item.marginal_gain > 0):
            return Location.ITEM_BAR
        return Location.PERSONAL_BAG
    return Location.PERSONAL_BAG


@dataclass(frozen=True)
class SlotBudget:
    capacity: int
    current: tuple[CardInstance, ...]
    reserved_peak: int = 0
    uncertainty_reserve: int = 1

    def __post_init__(self) -> None:
        if (self.capacity < 1 or len(self.current) > self.capacity
                or min(self.reserved_peak, self.uncertainty_reserve) < 0
                or len({c.instance_id for c in self.current}) != len(self.current)
                or any(not c.instance_id for c in self.current)):
            raise ValueError("invalid CURRENT slot snapshot; history is not occupancy")

    @property
    def free_slots(self) -> int:
        return self.capacity - len(self.current)

    def admits_filler(self, marginal_slots: int = 1) -> bool:
        if marginal_slots < 0:
            raise ValueError("use an independently verified merge plan")
        return self.free_slots - self.reserved_peak - self.uncertainty_reserve >= marginal_slots


@dataclass(frozen=True)
class DeckFacts:
    base_ids: frozenset[str]
    base_observed: frozenset[str]
    unlocked_groups: frozenset[str]
    completed_goals: frozenset[str]
    paused_groups: frozenset[str] = frozenset()


def active_group(facts: DeckFacts, order: tuple[str, ...], *,
                 base_ratio: float = 0.8, bypass_base: bool = False) -> tuple[str | None, str]:
    """Single primary group. 'treasure' unlock must come from a confirmed event.

    completed_goals are confirmed objectives, NOT counts or configured presets.
    A locked/paused group is not DONE and need not starve other unlocked groups.
    """
    if (not math.isfinite(base_ratio) or not 0 <= base_ratio <= 1
            or len(set(order)) != len(order) or any(not n for n in order)):
        raise ValueError("invalid deck plan")
    covered = len(facts.base_ids & facts.base_observed)
    required = math.ceil(len(facts.base_ids) * base_ratio)
    if not bypass_base and covered < required:
        return None, "base_pending"
    for group in order:
        if (group not in facts.completed_goals and group not in facts.paused_groups
                and group in facts.unlocked_groups):
            return group, "primary_group"
    return None, "goals_complete" if set(order) <= facts.completed_goals else "locked_or_paused"


@dataclass(frozen=True)
class ResourceBudget:
    balance: int | None
    reserved: int = 0

    def affordable(self, cost: int | None) -> bool:
        if self.reserved < 0:
            raise ValueError("negative reservation")
        return (self.balance is not None and cost is not None
                and self.balance >= 0 and cost >= 0
                and self.balance - self.reserved >= cost)
