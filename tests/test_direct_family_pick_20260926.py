from __future__ import annotations

import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.choice_policy import PolicySettings
from shuabao.loop_action import LoopAction
from shuabao.mediator import Mediator
from shuabao.runtime_mediator import Mediator as RuntimeMediator
from shuabao.settings import Settings
from shuabao.vision.capture import Frame


def _mediator() -> Mediator:
    # 模板快路必须在 OCR 完全关闭时也成立；否则测试会把外部 OCR 启动误当依赖。
    med = Mediator(Settings(ocr_mode="off"), ROOT)
    med._cached_policy_settings = PolicySettings(
        bond_presets=("祝福", "成长", "经济", "海盗"),
        bond_base_presets=("祝福", "成长", "经济"),
        bond_must_take=("祝福",),
        bond_advanced_presets=("海盗",),
        bond_advanced_groups=(("海盗",),),
    )
    med._advanced_groups_completed = 0
    return med


def _slots(*names: str) -> list[dict]:
    return [
        {
            "index": index,
            "name": name,
            "confidence": 0.91,
            "template_score": 0.91,
            "source": "template",
        }
        for index, name in enumerate(names)
    ]


def test_direct_family_pick_obeys_owner_priority_and_skips_rarity_reads() -> None:
    med = _mediator()
    frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8))
    with patch.object(med, "_read_slot_rarity_badge") as rarity:
        assert med._direct_template_bond_pick(frame, _slots("成长", "海盗", "祝福", "经济")) == 2
    rarity.assert_not_called()


def test_direct_family_pick_advances_to_growth_after_three_blessings() -> None:
    med = _mediator()
    med._bond_cards_owned = ["祝福", "祝福", "祝福"]
    frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8))
    assert med._blessing_set_pending() is False
    assert med._direct_template_bond_pick(frame, _slots("海盗", "成长", "经济", "固守")) == 1


def test_bond_visit_does_not_advance_while_blessing_set_is_incomplete() -> None:
    med = _mediator()
    med._l1_cycle_step = "bond"
    med._l1_cycle_step_successes = 3
    med._wood_balance = 0
    assert med._l1_step_visit_exhausted(time.time() + 1) is False


def test_growth_and_economy_use_the_saved_target_order() -> None:
    med = _mediator()
    med._bond_cards_owned = ["祝福"] * 3
    frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8))
    assert med._direct_template_bond_pick(frame, _slots("经济", "成长", "海盗", "固守")) == 1


def test_direct_family_pick_uses_rarity_only_for_same_priority_ties() -> None:
    med = _mediator()
    med._bond_cards_owned = ["祝福"] * 3
    frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8))
    with patch.object(med, "_read_slot_rarity_badge", side_effect=[("R", "blue"), ("SSR", "orange")]) as rarity:
        assert med._direct_template_bond_pick(frame, _slots("成长", "成长", "海盗", "固守")) == 1
    assert rarity.call_count == 2


def test_direct_family_pick_ignores_unmatched_slots() -> None:
    med = _mediator()
    frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8))
    assert med._direct_template_bond_pick(frame, _slots("固守", "无关", "未知", "其他")) is None


def test_direct_family_pick_accepts_a_confident_target_with_other_unrecognized_slots() -> None:
    med = _mediator()
    frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8))
    slots = _slots("成长", "", "", "")
    for slot in slots[1:]:
        slot["template_score"] = 0.0
    assert med._direct_template_bond_pick(frame, slots) == 0




def test_direct_family_pick_obeys_current_advanced_group_sequence() -> None:
    med = _mediator()
    med._cached_policy_settings = PolicySettings(
        bond_presets=("祝福", "成长", "经济", "海盗", "白赚海盗", "异火"),
        bond_must_take=("祝福",),
        bond_advanced_presets=("海盗", "白赚海盗", "异火"),
        bond_advanced_groups=(("海盗", "白赚海盗"), ("异火",)),
    )
    med._bond_cards_owned = ["祝福"] * 3
    frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8))
    with patch.object(med, "_bond_bar_occupancy", return_value=5):
        assert med._direct_template_bond_pick(frame, _slots("异火", "海盗")) == 1
        med._advanced_groups_completed = 1
        assert med._direct_template_bond_pick(frame, _slots("异火", "海盗")) == 0


def test_direct_family_pick_obeys_prerequisite_gate() -> None:
    med = _mediator()
    med._cached_policy_settings = PolicySettings(
        bond_presets=("祝福", "安身法", "禁字法"),
        bond_advanced_presets=("安身法", "禁字法"),
        bond_advanced_groups=(("安身法", "禁字法"),),
    )
    med._bond_cards_owned = ["祝福"] * 3
    frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8))
    with patch.object(med, "_bond_bar_occupancy", return_value=5):
        assert med._direct_template_bond_pick(frame, _slots("禁字法", "无关")) is None
        med._bond_cards_owned.append("安身法")
        assert med._direct_template_bond_pick(frame, _slots("禁字法", "无关")) == 0


def test_direct_family_pick_obeys_full_bar_immediate_merge_only() -> None:
    med = _mediator()
    med._cached_policy_settings = PolicySettings(
        bond_presets=("成长",),
        bond_base_presets=("成长",),
        bond_whitelist_mode="hard",
    )
    frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8))
    with patch.object(med, "_bond_bar_occupancy", return_value=10):
        med._bond_cards_owned = ["成长", "成长"]
        assert med._direct_template_bond_pick(frame, _slots("成长", "无关")) is None
        med._bond_cards_owned = ["成长", "成长", "成长"]
        assert med._direct_template_bond_pick(frame, _slots("成长", "无关")) == 0


def test_production_ocr_path_rechecks_policy_instead_of_trusting_direct_index() -> None:
    med = RuntimeMediator(Settings(ocr_mode="off"), ROOT)
    med._cached_policy_settings = PolicySettings(
        bond_presets=("海盗", "异火"),
        bond_advanced_presets=("海盗", "异火"),
        bond_advanced_groups=(("海盗",), ("异火",)),
    )
    med._bond_cards_owned = ["祝福"] * 3
    frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), hwnd=1)
    # 生产槽位几何只接受真实 3/4 槽布局；用 4 槽验证最终点击映射。
    slots = _slots("异火", "海盗", "无关", "其他")

    def panel_slots(_frame, _kind):
        med._last_template_direct_pick = 0
        med._last_slots_from_template = True
        return slots

    with (
        patch.object(med, "_ocr_panel_slots", side_effect=panel_slots),
        patch.object(med, "_panel_can_refresh", return_value=True),
        patch.object(med, "_panel_has_giveup", return_value=False),
        patch.object(med, "_extract_live_set_progress", return_value=None),
        patch.object(med, "_bond_bar_occupancy", return_value=5),
        patch.object(med, "_bond_refresh_affordable", return_value=(True, 9999, 40)),
    ):
        hit = med._ocr_reward_choice(frame, "bond")
    assert hit is not None
    assert hit.name == "ocr_bond:海盗"


def test_four_challenges_are_clicked_then_verified_from_one_fresh_frame() -> None:
    med = _mediator()
    frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8))
    controls = ("coin_challenge", "wood_challenge", "experience_challenge", "treasure_challenge")
    hits = [
        SimpleNamespace(x=10 + index * 40, y=10, w=20, h=20, score=0.9, name=key, center=(20 + index * 40, 20))
        for index, key in enumerate(controls)
    ]
    with (
        patch.object(med, "_passenger_mode", return_value=False),
            patch.object(med, "_find_challenge_button", side_effect=[(hit, hit) for hit in hits] * 2),
        patch.object(med, "_resolve_challenge_state", side_effect=[med._challenge_states[controls[0]].OFF] * 4 + [med._challenge_states[controls[0]].ON] * 4),
        patch.object(med, "_challenge_green_count", return_value=50),
        patch.object(med, "_capture_best", return_value=frame) as capture,
        patch.object(med, "act_right_click", return_value=True) as click,
    ):
        assert med._ensure_challenge_buttons(frame) == LoopAction.Continue
    assert click.call_count == 4
    capture.assert_called_once()
    assert med._challenge_done == set(controls)


def test_four_challenge_batch_retries_still_off_wood_immediately() -> None:
    med = _mediator()
    frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8))
    controls = ("coin_challenge", "wood_challenge", "experience_challenge", "treasure_challenge")
    hits = {
        key: SimpleNamespace(
            x=10 + index * 40,
            y=10,
            w=20,
            h=20,
            score=0.9,
            name=key,
            center=(20 + index * 40, 20),
        )
        for index, key in enumerate(controls)
        }
    find_hits = [(hits[key], hits[key]) for key in controls]
    find_hits += [(hits[key], hits[key]) for key in controls]
    find_hits += [(hits["wood_challenge"], hits["wood_challenge"])]
    find_hits += [(hits[key], hits[key]) for key in controls]
    states = [med._challenge_states[controls[0]].OFF] * 4
    states += [
        med._challenge_states[controls[0]].ON,
        med._challenge_states[controls[0]].OFF,
        med._challenge_states[controls[0]].ON,
        med._challenge_states[controls[0]].ON,
        med._challenge_states[controls[0]].OFF,
    ]
    states += [med._challenge_states[controls[0]].ON] * 4
    with (
        patch.object(med, "_passenger_mode", return_value=False),
        patch.object(med, "_find_challenge_button", side_effect=find_hits),
        patch.object(med, "_resolve_challenge_state", side_effect=states),
        patch.object(med, "_challenge_green_count", return_value=50),
        patch.object(med, "_capture_best", side_effect=[frame, frame]) as capture,
        patch.object(med, "act_right_click", return_value=True) as click,
    ):
        assert med._ensure_challenge_buttons(frame) == LoopAction.Continue
    assert click.call_count == 5
    assert capture.call_count == 2
    assert med._challenge_attempts["wood_challenge"] == 2
    assert med._challenge_done == set(controls)


def test_challenge_batch_gate_allows_only_challenge_inputs_from_current_evidence() -> None:
    med = _mediator()
    evidence = SimpleNamespace(gen=7)
    med._evidence = evidence
    med._tick_evidence = evidence
    med._tick_gen = 7
    med._tick_input_seq = 0
    med._input_seq = 1
    med._challenge_batch_input_active = True
    assert med._action_gate_ok("金币Challenge-right_click") is True
    assert med._action_gate_ok("evolve-click") is False
