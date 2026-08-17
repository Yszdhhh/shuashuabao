"""InteractionSurface single-modal arbitration and PendingAction definitions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
import hashlib
from typing import Any, Callable
import numpy as np


class InteractionSurface(Enum):
    """Priority state machine for single-modal interaction arbitration.

    Priorities:
    1. RECOVERY_MODAL: Disconnect / system popups (freeze all game controls)
    2. EQUIPMENT_AFFIX_MODAL: Equipment affix 4-choice modal
    3. HERO_CHOICE_MODAL: Hero selection / evolution modal
    4. CENTER_CARD_MODAL: In-game 3-choice card / skill modal
    5. MERCHANT: Black merchant 5-slot panel
    6. HUD_ONLY: No blocking modals (allows equipment upgrade, bag devour, pickup)
    7. CONFLICT: Mutually exclusive modals detected simultaneously -> Zero-Input.
    """
    RECOVERY_MODAL = auto()
    HERO_CHOICE_MODAL = auto()
    EQUIPMENT_AFFIX_MODAL = auto()
    CENTER_CARD_MODAL = auto()
    MERCHANT = auto()
    HUD_ONLY = auto()
    CONFLICT = auto()

    # Semantic / shorthand aliases
    HERO_CHOICE = HERO_CHOICE_MODAL
    EQUIPMENT_AFFIX = EQUIPMENT_AFFIX_MODAL
    CARD_CHOICE = CENTER_CARD_MODAL
    CENTER_CARD = CENTER_CARD_MODAL
    MERCHANT_MODAL = MERCHANT

def compute_frame_roi_fingerprint(roi: np.ndarray | None) -> str:
    """Compute a fast hash fingerprint for an image ROI."""
    if roi is None or roi.size == 0:
        return "empty"
    return hashlib.md5(roi.tobytes()).hexdigest()[:16]


def verify_card_slot_changed_or_disappeared(
    current_fingerprint: str | None,
    baseline_fingerprint: str | None,
    panel_present: bool,
) -> bool:
    """Verify that a selected card slot changed fingerprint or the panel closed."""
    if not panel_present:
        return True
    if baseline_fingerprint is not None and current_fingerprint != baseline_fingerprint:
        return True
    return False


def verify_merchant_slot_consumed(
    slot_purchasable: bool,
    current_gold: int | None = None,
    baseline_gold: int | None = None,
) -> bool:
    """Verify that merchant slot became non-purchasable or player gold decreased."""
    if not slot_purchasable:
        return True
    if current_gold is not None and baseline_gold is not None and current_gold < baseline_gold:
        return True
    return False


def verify_inventory_item_consumed(
    current_count: int | None,
    baseline_count: int | None,
    occupied_bonds_decreased: bool = False,
) -> bool:
    """Verify that bag consumable count decreased or occupied bond count reduced."""
    if occupied_bonds_decreased:
        return True
    if current_count is not None and baseline_count is not None and current_count < baseline_count:
        return True
    return False


@dataclass
class PendingAction:
    """Explicit post-condition verification for UI/game interactions.

    Replaces loose pixel diff heuristics with deterministic state / fingerprint verifiers.
    """

    kind: str  # e.g., "card_select", "merchant_buy", "inventory_consume", "hero_select"
    target_id: str | int  # slot index, card name, or item name
    deadline: float
    verifier: Callable[..., bool]
    baseline_fingerprint: str | None = None
    baseline_count: int | None = None

    def is_confirmed(self, *args: Any, **kwargs: Any) -> bool:
        try:
            return bool(self.verifier(*args, **kwargs))
        except Exception:
            return False

    def is_expired(self, now: float) -> bool:
        """Check if pending action has timed out."""
        return now >= self.deadline


def resolve_interaction_surface(
    recovery_modal: bool = False,
    hero_choice_modal: bool = False,
    equipment_affix_modal: bool = False,
    center_card_modal: bool = False,
    merchant_modal: bool = False,
) -> InteractionSurface:
    """Arbitrate interaction surface based on active modal detections.

    Priority:
    RECOVERY_MODAL > EQUIPMENT_AFFIX_MODAL > HERO_CHOICE_MODAL > CENTER_CARD_MODAL > MERCHANT > HUD_ONLY
    CONFLICT: If >=2 mutually exclusive modals are detected simultaneously.
    """
    blocking_modals = [
        ("affix", equipment_affix_modal),
        ("hero", hero_choice_modal),
        ("card", center_card_modal),
        ("merchant", merchant_modal),
    ]
    active_blocking = [name for name, active in blocking_modals if active]

    if recovery_modal:
        # Recovery modal has ultimate priority over everything
        return InteractionSurface.RECOVERY_MODAL

    # If more than 1 blocking modal is active simultaneously, we have a perceptual conflict -> CONFLICT
    if len(active_blocking) > 1:
        return InteractionSurface.CONFLICT

    if equipment_affix_modal:
        return InteractionSurface.EQUIPMENT_AFFIX_MODAL
    if hero_choice_modal:
        return InteractionSurface.HERO_CHOICE_MODAL
    if center_card_modal:
        return InteractionSurface.CENTER_CARD_MODAL
    if merchant_modal:
        return InteractionSurface.MERCHANT

    return InteractionSurface.HUD_ONLY
