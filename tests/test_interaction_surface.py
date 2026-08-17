"""Unit tests for InteractionSurface arbitration and PendingAction post-conditions."""

import pytest

from shuabao.interaction_surface import (
    InteractionSurface,
    PendingAction,
    resolve_interaction_surface,
    verify_card_slot_changed_or_disappeared,
    verify_merchant_slot_consumed,
    verify_inventory_item_consumed,
)


def test_interaction_surface_priority():
    # 1. Recovery modal has highest priority
    assert resolve_interaction_surface(
        recovery_modal=True,
        hero_choice_modal=True,
        equipment_affix_modal=True,
        center_card_modal=True,
        merchant_modal=True,
    ) == InteractionSurface.RECOVERY_MODAL

    # 2. Equipment affix modal priority (AFFIX > HERO > CARD > MERCHANT > HUD)
    assert resolve_interaction_surface(
        recovery_modal=False,
        hero_choice_modal=False,
        equipment_affix_modal=True,
        center_card_modal=False,
        merchant_modal=False,
    ) == InteractionSurface.EQUIPMENT_AFFIX_MODAL

    # 3. Hero choice modal priority
    assert resolve_interaction_surface(
        recovery_modal=False,
        hero_choice_modal=True,
        equipment_affix_modal=False,
        center_card_modal=False,
        merchant_modal=False,
    ) == InteractionSurface.HERO_CHOICE_MODAL

    # 4. Center card modal priority
    assert resolve_interaction_surface(
        recovery_modal=False,
        hero_choice_modal=False,
        equipment_affix_modal=False,
        center_card_modal=True,
        merchant_modal=False,
    ) == InteractionSurface.CENTER_CARD_MODAL

    # 5. Merchant surface
    assert resolve_interaction_surface(
        recovery_modal=False,
        hero_choice_modal=False,
        equipment_affix_modal=False,
        center_card_modal=False,
        merchant_modal=True,
    ) == InteractionSurface.MERCHANT

    # 6. HUD only (no modals / merchant)
    assert resolve_interaction_surface(
        recovery_modal=False,
        hero_choice_modal=False,
        equipment_affix_modal=False,
        center_card_modal=False,
        merchant_modal=False,
    ) == InteractionSurface.HUD_ONLY


def test_interaction_surface_conflict():
    # Conflict between mutually exclusive modals (e.g. affix + hero when recovery is false)
    assert resolve_interaction_surface(
        recovery_modal=False,
        hero_choice_modal=True,
        equipment_affix_modal=True,
        center_card_modal=False,
        merchant_modal=False,
    ) == InteractionSurface.CONFLICT


def test_pending_action_verification():
    # Test card slot verification
    assert verify_card_slot_changed_or_disappeared(
        current_fingerprint="abc",
        baseline_fingerprint="xyz",
        panel_present=True,
    ) is True
    assert verify_card_slot_changed_or_disappeared(
        current_fingerprint="xyz",
        baseline_fingerprint="xyz",
        panel_present=False,
    ) is True
    assert verify_card_slot_changed_or_disappeared(
        current_fingerprint="xyz",
        baseline_fingerprint="xyz",
        panel_present=True,
    ) is False

    # Test merchant slot verification
    assert verify_merchant_slot_consumed(
        slot_purchasable=False,
        current_gold=100,
        baseline_gold=200,
    ) is True
    assert verify_merchant_slot_consumed(
        slot_purchasable=True,
        current_gold=100,
        baseline_gold=200,
    ) is True
    assert verify_merchant_slot_consumed(
        slot_purchasable=True,
        current_gold=200,
        baseline_gold=200,
    ) is False

    # Test inventory consumable verification
    assert verify_inventory_item_consumed(
        current_count=2,
        baseline_count=3,
        occupied_bonds_decreased=False,
    ) is True
    assert verify_inventory_item_consumed(
        current_count=3,
        baseline_count=3,
        occupied_bonds_decreased=True,
    ) is True
    assert verify_inventory_item_consumed(
        current_count=3,
        baseline_count=3,
        occupied_bonds_decreased=False,
    ) is False

def test_pending_action_is_expired():
    action = PendingAction(
        kind="WAIT_HERO_CHOICE",
        target_id="hero_card_item",
        deadline=100.0,
        verifier=lambda: True,
    )
    assert action.is_expired(99.9) is False
    assert action.is_expired(100.0) is True
    assert action.is_expired(100.1) is True
