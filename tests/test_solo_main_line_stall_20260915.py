# -*- coding: utf-8 -*-
"""P1-8: stalled main-line recovery keeps skill picks ahead of economy bonds."""
from pathlib import Path

from shuabao.choice_policy import PolicySettings, SlotCandidate
from shuabao.mediator import Mediator
from shuabao.settings import Settings


ROOT = Path(__file__).resolve().parents[1]


def _med() -> Mediator:
    return Mediator(Settings(ocr_mode="off"), ROOT)


def test_same_stage_for_ninety_seconds_lowers_skill_backlog_to_one() -> None:
    med = _med()
    med._record_main_line_stage((4, 5), 100.0)
    med._record_main_line_stage((4, 5), 189.9)
    assert not med._main_line_stalled()
    med._record_main_line_stage((4, 5), 190.0)
    assert med._main_line_stalled()
    assert med._skill_backlog_force() == 1


def test_progress_clears_the_stall_and_failure_text_triggers_it() -> None:
    med = _med()
    med._record_main_line_stage((4, 5), 0.0)
    med._record_main_line_stage((4, 5), 90.0)
    assert med._main_line_stalled()
    med._record_main_line_stage((4, 6), 91.0)
    assert not med._main_line_stalled()
    med._record_main_line_failure("主线挑战失败，请提升实力后再来挑战")
    assert med._main_line_stalled()


def test_stall_bond_filter_keeps_combat_and_selected_targets() -> None:
    med = _med()
    slots = (
        SlotCandidate(index=0, name="经济", confidence=0.99),
        SlotCandidate(index=1, name="法术(1/3)", confidence=0.99),
        SlotCandidate(index=2, name="成长", confidence=0.99),
    )
    kept = med._stall_combat_bond_slots(slots)
    assert [slot.name for slot in kept] == ["经济", "法术(1/3)", "成长"]
    policy = med._stall_combat_bond_policy(PolicySettings(bond_presets=("经济",)))
    assert policy.bond_presets == ("经济",) + med._STALL_COMBAT_BOND_PRESETS
    assert not policy.bond_base_presets
    assert policy.bond_must_take == PolicySettings().bond_must_take
