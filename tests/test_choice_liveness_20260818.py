from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from shuabao.choice_policy import (
    PANEL_BOND,
    PANEL_SKILL,
    WHITELIST_HARD,
    WHITELIST_SOFT,
    PanelCandidates,
    PolicyAction,
    PolicySettings,
    SlotCandidate,
    assemble_policy_settings,
    choose_action,
)
from shuabao.mediator import Mediator, PanelState
from shuabao.settings import Settings
from shuabao.vision.capture import Frame

ROOT = Path(__file__).resolve().parents[1]


def slot(index: int, name: str, *, rarity: str = "white", confidence: float = 0.99):
    return SlotCandidate(index=index, name=name, rarity=rarity, confidence=confidence)


def test_blessing_is_system_must_take_even_in_explicit_hard_mode():
    cands = PanelCandidates(
        panel_kind=PANEL_BOND,
        slots=(slot(0, "普通羁绊"), slot(1, "祝福3级", rarity="green"), slot(2, "另一羁绊")),
        settings=PolicySettings(
            bond_presets=(),
            bond_whitelist_mode=WHITELIST_HARD,
            min_confidence=0.60,
        ),
    )
    decision = choose_action(cands)
    assert decision.action == PolicyAction.SELECT_SLOT
    assert decision.index == 1
    assert "系统必拿" in decision.reason


def test_runtime_bond_default_is_soft_and_quality_falls_back():
    runtime = SimpleNamespace(
        skills=[], cards=[], skill_archive_levels={}, treasure_allow_negative=[],
        bond_whitelist_mode="soft", bond_must_take=["祝福"],
    )
    settings = assemble_policy_settings(
        settings=runtime,
        skill_labels={},
        fetter_labels={},
        policy_doc={"bond": {"whitelist_mode": "soft"}, "min_confidence": 0.60},
    )
    assert settings.bond_whitelist_mode == WHITELIST_SOFT
    decision = choose_action(PanelCandidates(
        panel_kind=PANEL_BOND,
        slots=(slot(0, "甲", rarity="blue"), slot(1, "乙", rarity="orange"), slot(2, "丙", rarity="white")),
        settings=settings,
    ))
    assert (decision.action, decision.index) == (PolicyAction.SELECT_SLOT, 1)
    assert "品质降级" in decision.reason


def test_skill_safe_fill_uses_new_catalog_family_before_four_slots():
    ps = PolicySettings(
        skill_presets=("寒冰箭",),
        skill_focus_families=("寒冰箭",),
        skill_fill_empty_slots=True,
        min_confidence=0.60,
    )
    decision = choose_action(PanelCandidates(
        panel_kind=PANEL_SKILL,
        slots=(slot(0, "奥术箭矢", rarity="blue"),),
        owned_skill_cards=("剑气", "地震", "火球"),
        settings=ps,
    ))
    assert (decision.action, decision.index) == (PolicyAction.SELECT_SLOT, 0)
    assert "技能槽未满" in decision.reason


def test_skill_safe_fill_turns_strict_after_four_families():
    ps = PolicySettings(
        skill_presets=("寒冰箭",),
        skill_focus_families=("寒冰箭",),
        skill_fill_empty_slots=True,
        min_confidence=0.60,
    )
    decision = choose_action(PanelCandidates(
        panel_kind=PANEL_SKILL,
        slots=(slot(0, "奥术箭矢", rarity="red"),),
        owned_skill_cards=("剑气", "地震", "火球", "奥数激光"),
        settings=ps,
    ))
    assert decision.action == PolicyAction.CLOSE


def test_bond_slot0_logged_screen_coordinate_matches_window_offset():
    med = object.__new__(Mediator)
    frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), left=160, top=102)
    hit = med._choice_slot_hit(frame, "bond", 0, "ocr_bond:祝福")
    # 0.331 * 1600 -> local x=529; 0.44 * 900 -> local y=396.
    # The real-machine log (689, 498) is exactly local + HWND origin (160, 102).
    assert (hit.x, hit.y) == (529, 396)
    assert (hit.screen_x, hit.screen_y) == (689, 498)


def _semantic_mediator(action: str):
    med = object.__new__(Mediator)
    med.settings = SimpleNamespace(panel_reopen_cooldown_s=12.0)
    med._panel_cooldown_until = {}
    med._panel_pending_choice_action = action
    med._panel_pending_choice_fingerprint = ("bond", "ocr_bond:祝福", 86, 62)
    med._l1_cycle_owned_panel = True
    med._l1_cycle_step = "bond"
    med._l1_cycle_selected = False
    med._panel_kind = "bond"
    med._last_skill_panel = 30.0
    return med


def test_selection_is_not_success_until_mutation_confirmation():
    med = _semantic_mediator("select")
    assert med._l1_cycle_selected is False
    med._confirm_panel_choice_action(100.0)
    assert med._l1_cycle_selected is True
    assert med._panel_pending_choice_action is None


def test_unconfirmed_select_expires_without_becoming_success():
    med = _semantic_mediator("select")
    action = med._expire_panel_choice_action()
    assert action == "select"
    assert med._l1_cycle_selected is False
    assert med._panel_pending_choice_action is None


def test_confirmed_physical_close_arms_twelve_second_reopen_cooldown():
    med = _semantic_mediator("close")
    med._confirm_panel_choice_action(100.0)
    assert med._panel_cooldown_until["bond"] == 112.0
    assert med._l1_cycle_selected is False


def test_default_settings_persist_soft_bond_and_panel_cooldown():
    raw = json.loads((ROOT / "config/default_settings.json").read_text(encoding="utf-8"))
    assert raw["bond_whitelist_mode"] == "soft"
    assert "祝福" in raw["bond_must_take"]
    assert raw["panel_reopen_cooldown_s"] == 12.0
    loaded = Settings.load(ROOT / "config/default_settings.json")
    assert loaded.bond_whitelist_mode == "soft"
    assert loaded.bond_must_take[0] == "祝福"
    assert loaded.panel_reopen_cooldown_s == 12.0
