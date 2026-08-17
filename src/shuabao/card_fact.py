"""CardFact: Badge-first minimal perception data structure for skill and card selection.

Represents the minimal factual attributes observed on a card slot (family badge,
rarity border, prereq marker, NEW marker, optional exact name / skill level).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

# Default rarity hierarchy (highest priority to lowest priority)
DEFAULT_CARD_FACT_RARITY_ORDER: tuple[str, ...] = (
    "red",
    "orange",
    "purple",
    "blue",
    "white",
    "green",
)


@dataclass(frozen=True)
class CardFact:
    """Minimal factual representation of a single card slot on screen.

    Fields:
      slot: 0-indexed slot position (0, 1, 2).
      family: Observed or mapped skill family badge (e.g. "奥术箭", "冰霜", "通用").
      rarity: Border rarity color band ("red" > "orange" > "purple" > "blue" > "white" > "green").
      prereq_marker: Whether a prerequisite marker / gem indicator is observed.
      is_new: Whether a 'NEW' badge is observed on the card.
      exact_name: Full card name if OCR has high confidence (optional, not a gate).
      skill_level: Optional numeric skill level / rank if stably readable.
    """

    slot: int
    family: str
    rarity: str = "white"
    prereq_marker: bool = False
    is_new: bool = False
    exact_name: str | None = None
    skill_level: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.slot, int):
            object.__setattr__(self, "slot", int(self.slot))
        if not isinstance(self.family, str):
            object.__setattr__(self, "family", str(self.family or ""))
        if not isinstance(self.rarity, str):
            object.__setattr__(self, "rarity", str(self.rarity or "white"))
        if not isinstance(self.prereq_marker, bool):
            object.__setattr__(self, "prereq_marker", bool(self.prereq_marker))
        if not isinstance(self.is_new, bool):
            object.__setattr__(self, "is_new", bool(self.is_new))
        if self.exact_name is not None and not isinstance(self.exact_name, str):
            object.__setattr__(self, "exact_name", str(self.exact_name))
        if self.skill_level is not None and not isinstance(self.skill_level, int):
            try:
                object.__setattr__(self, "skill_level", int(self.skill_level))
            except (ValueError, TypeError):
                object.__setattr__(self, "skill_level", None)

    @classmethod
    def from_slot(cls, slot: Any) -> "CardFact":
        """Extract or construct a CardFact from a SlotCandidate or mapping."""
        return card_fact_from_slot(slot)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CardFact":
        return cls(
            slot=int(data.get("slot", 0)),
            family=str(data.get("family", "")),
            rarity=str(data.get("rarity", "white")),
            prereq_marker=bool(data.get("prereq_marker", False)),
            is_new=bool(data.get("is_new", False)),
            exact_name=data.get("exact_name"),
            skill_level=data.get("skill_level"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot": self.slot,
            "family": self.family,
            "rarity": self.rarity,
            "prereq_marker": self.prereq_marker,
            "is_new": self.is_new,
            "exact_name": self.exact_name,
            "skill_level": self.skill_level,
        }

    def to_slot_candidate(self) -> Any:
        """Convert CardFact to choice_policy.SlotCandidate."""
        from shuabao.choice_policy import SlotCandidate

        return SlotCandidate(
            index=self.slot,
            name=self.exact_name,
            confidence=1.0 if self.exact_name else (0.9 if self.family else 0.0),
            evidence="CardFact badge-first observation",
            rarity=self.rarity,
            family=self.family,
            prereq_marker=self.prereq_marker,
            is_new=self.is_new,
            skill_level=self.skill_level,
            card_fact=self,
        )


def card_fact_from_slot(slot: Any) -> CardFact:
    """Extract or construct a CardFact from a SlotCandidate or mapping."""
    if isinstance(slot, CardFact):
        return slot
    if hasattr(slot, "to_card_fact") and callable(slot.to_card_fact):
        return slot.to_card_fact()
    if hasattr(slot, "card_fact") and getattr(slot, "card_fact") is not None:
        return getattr(slot, "card_fact")
    if isinstance(slot, Mapping):
        return CardFact.from_dict(slot)
    # Default fallback from object attributes
    s_idx = getattr(slot, "index", getattr(slot, "slot", 0))
    s_name = getattr(slot, "name", getattr(slot, "exact_name", None))
    s_fam = getattr(slot, "family", None)
    if not s_fam and s_name:
        try:
            from shuabao.skill_catalog import family_of

            s_fam = family_of(s_name)
        except Exception:
            s_fam = ""
    s_rarity = getattr(slot, "rarity", "white") or "white"
    s_prereq = bool(getattr(slot, "prereq_marker", False))
    s_is_new = bool(getattr(slot, "is_new", False))
    s_level = getattr(slot, "skill_level", None)
    return CardFact(
        slot=int(s_idx),
        family=str(s_fam or ""),
        rarity=str(s_rarity),
        prereq_marker=s_prereq,
        is_new=s_is_new,
        exact_name=s_name,
        skill_level=s_level,
    )
