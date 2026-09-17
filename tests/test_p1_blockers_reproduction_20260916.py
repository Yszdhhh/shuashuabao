# -*- coding: utf-8 -*-
"""Reproduction test suite for P1-01, P1-02, P1-03 blocker issues (2026-09-16).

Verifies the exact failure cases identified by Cloud Audit:
- P1-01: RuntimeMediator scheduling divergence (advance_at / successes reset, high-wood retention)
- P1-02: Stall recovery bond whitelist poisoning via substring matches_bond_preset
- P1-03: Passenger treasure fallback selecting negative or unnamed cards
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from shuabao.choice_policy import (
    PolicyAction,
    PolicyDecision,
    PolicySettings,
    SlotCandidate,
)
from shuabao.mediator import LoopAction, MatchResult, Mediator, PanelState, Phase
from shuabao.runtime_mediator import Mediator as RuntimeMediator
from shuabao.settings import Settings
from shuabao.vision.capture import Frame

ROOT = Path(__file__).resolve().parents[1]


def make_frame() -> Frame:
    img = np.zeros((720, 1280, 3), dtype=np.uint8)
    return Frame(img, window_title="英雄三国", hwnd=100, role="l1")


# =========================================================================
# P1-01: RuntimeMediator / CoreMediator scheduling convergence tests
# =========================================================================
class TestP1_01_RuntimeMediatorCycle:
    def test_runtime_mediator_step_successes_and_advance_at_reset(self) -> None:
        """P1-01: RuntimeMediator._advance_l1_cycle must reset successes and update advance_at."""
        settings = Settings(mode_id="normal_farm", ocr_mode="off")
        med = RuntimeMediator(settings, ROOT)
        med._l1_cycle_step = "bond"
        med._l1_cycle_index = 0
        med._l1_cycle_step_successes = 5
        med._l1_cycle_last_advance_at = 100.0

        with patch("time.time", return_value=500.0):
            med._advance_l1_cycle("bond")

        assert med._l1_cycle_step == "skill"
        assert med._l1_cycle_index == 1
        assert med._l1_cycle_step_successes == 0, "successes count must reset to 0 upon advance"
        assert med._l1_cycle_last_advance_at == 500.0, "last_advance_at must update upon advance"

    def test_runtime_mediator_high_wood_does_not_starve_treasure_after_second_skill(self) -> None:
        """P1-01: high wood retains F/G priority only within a bounded full cycle."""
        settings = Settings(mode_id="normal_farm", ocr_mode="off")
        med = RuntimeMediator(settings, ROOT)
        med._wood_balance = 5000  # >= 1000
        med._l1_cycle_index = 3
        med._l1_cycle_step = "skill"
        med._l1_cycle_step_successes = 2

        with patch("time.time", return_value=600.0):
            med._advance_l1_cycle("skill")

        assert med._l1_cycle_step == "treasure", "second skill must hand service to treasure"
        assert med._l1_cycle_step_successes == 0
        assert med._l1_cycle_last_advance_at == 600.0

        # The remaining side branches must also be reachable before wraparound.
        visited = [med._l1_cycle_step]
        for _ in range(len(med._L1_CYCLE_ORDER) * 2):
            with patch("time.time", return_value=650.0 + len(visited)):
                med._advance_l1_cycle(med._l1_cycle_step)
            visited.append(med._l1_cycle_step)
        assert set(med._L1_CYCLE_ORDER) <= set(visited)

        # The normal order still returns from the first bond to skill.
        med._l1_cycle_step = "bond"
        med._l1_cycle_index = 0
        with patch("time.time", return_value=650.0):
            med._advance_l1_cycle("bond")
        assert med._l1_cycle_step == "skill"
        assert med._l1_cycle_step_successes == 0
        assert med._l1_cycle_last_advance_at == 650.0

    def test_runtime_mediator_low_wood_ten_step_progression(self) -> None:
        """P1-01: Low wood progresses through all 10 steps, respecting duplicate bond/skill."""
        settings = Settings(mode_id="normal_farm", ocr_mode="off")
        med = RuntimeMediator(settings, ROOT)
        med._wood_balance = 200  # < 1000
        expected_order = med._L1_CYCLE_ORDER

        med._l1_cycle_step = expected_order[0]
        med._l1_cycle_index = 0

        for i in range(len(expected_order)):
            expected_next_idx = (i + 1) % len(expected_order)
            expected_next_step = expected_order[expected_next_idx]
            current_step = expected_order[i]

            med._l1_cycle_step_successes = 3
            med._advance_l1_cycle(current_step)

            assert med._l1_cycle_index == expected_next_idx, f"Step {i} ({current_step}) -> next idx mismatch"
            assert med._l1_cycle_step == expected_next_step, f"Step {i} ({current_step}) -> next step mismatch"
            assert med._l1_cycle_step_successes == 0
            assert med._l1_cycle_last_advance_at is not None

    def test_runtime_mediator_lobby_hitch_cycle_unaffected(self) -> None:
        """P1-01: Lobby hitch mode preserves merchant -> treasure -> pickup -> public_bag."""
        settings = Settings(mode_id="lobby_hitch", ocr_mode="off")
        med = RuntimeMediator(settings, ROOT)
        assert med._hitch_enabled() is True
        assert med._passenger_mode() is True

        order = med._HITCH_L1_CYCLE_ORDER
        med._l1_cycle_step = order[0]
        med._l1_cycle_index = 0

        for i in range(len(order)):
            expected_next_idx = (i + 1) % len(order)
            expected_next_step = order[expected_next_idx]
            current_step = order[i]

            med._advance_l1_cycle(current_step)
            assert med._l1_cycle_step == expected_next_step


# =========================================================================
# P1-02: Stall recovery bond whitelist poisoning tests
# =========================================================================
class TestP1_02_StallRecoveryBondIdentity:
    def test_stall_recovery_rejects_family_substring_candidate(self) -> None:
        """P1-02: Stall recovery + owned='智力' must NOT select candidate '智力祝福(2/3)'."""
        settings = Settings(mode_id="normal_farm", ocr_mode="off")
        med = Mediator(settings, ROOT)
        med.set_phase(Phase.MAIN_LINE)
        med._main_line_stall_reason = "combat_stalled"  # _main_line_stalled() is True
        med._confirmed_bond_cards = lambda: ("智力",)
        med._bond_bar_occupancy = lambda f: 2
        med._panel_can_refresh = lambda f, k: True
        med._bond_refresh_affordable = lambda f: (True, 500, 20)

        med._ocr_panel_slots = lambda f, k: [
            {"index": 0, "name": "智力祝福(2/3)", "confidence": 0.95, "rarity": "SSR"}
        ]

        fr = make_frame()
        result = med._ocr_reward_choice(fr, "bond")

        # Must NOT select slot 0 ('智力祝福(2/3)')!
        assert result is None or not result.name.startswith("ocr_bond:智力祝福"), (
            f"Stall recovery must NOT select '智力祝福(2/3)' when only '智力' is owned! Got {getattr(result, 'name', None)}"
        )

    def test_stall_recovery_allows_exact_owned_debt(self) -> None:
        """P1-02: Stall recovery + owned='智力' allows exact same card candidate '智力(2/4)'."""
        settings = Settings(mode_id="normal_farm", ocr_mode="off")
        med = Mediator(settings, ROOT)
        med.set_phase(Phase.MAIN_LINE)
        med._main_line_stall_reason = "combat_stalled"
        med._confirmed_bond_cards = lambda: ("智力",)
        med._bond_bar_occupancy = lambda f: 2
        med._panel_can_refresh = lambda f, k: True
        med._bond_refresh_affordable = lambda f: (True, 500, 20)

        # Slot 0 is '智力(2/4)' (exact same card identity debt)
        med._ocr_panel_slots = lambda f, k: [
            {"index": 0, "name": "智力(2/4)", "confidence": 0.95, "rarity": "N"}
        ]

        fr = make_frame()
        result = med._ocr_reward_choice(fr, "bond")

        # Allowed to select slot 0 because it is the exact same card debt
        assert result is not None
        assert result.name == "ocr_bond:智力(2/4)"

    def test_stall_recovery_releases_completed_card(self) -> None:
        """P1-02: Stall recovery releases completed 4/4 card; must not pick completed card."""
        settings = Settings(mode_id="normal_farm", ocr_mode="off")
        med = Mediator(settings, ROOT)
        med.set_phase(Phase.MAIN_LINE)
        med._main_line_stall_reason = "combat_stalled"
        med._confirmed_bond_cards = lambda: ("智力(4/4)",)
        med._bond_bar_occupancy = lambda f: 2
        med._panel_can_refresh = lambda f, k: True
        med._bond_refresh_affordable = lambda f: (True, 500, 20)

        med._ocr_panel_slots = lambda f, k: [
            {"index": 0, "name": "智力", "confidence": 0.95, "rarity": "N"}
        ]

        fr = make_frame()
        result = med._ocr_reward_choice(fr, "bond")

        assert result is None or not result.name.startswith("ocr_bond:智力"), (
            f"Stall recovery must NOT select completed 4/4 card '智力'! Got {getattr(result, 'name', None)}"
        )

    def test_stall_recovery_preserves_genuine_stall_presets(self) -> None:
        """P1-02: Legitimate _STALL_COMBAT_BOND_PRESETS (e.g. '急速') are still selected."""
        settings = Settings(mode_id="normal_farm", ocr_mode="off")
        med = Mediator(settings, ROOT)
        med.set_phase(Phase.MAIN_LINE)
        med._main_line_stall_reason = "combat_stalled"
        med._confirmed_bond_cards = lambda: ()
        med._bond_bar_occupancy = lambda f: 2
        med._panel_can_refresh = lambda f, k: True
        med._bond_refresh_affordable = lambda f: (True, 500, 20)

        med._ocr_panel_slots = lambda f, k: [
            {"index": 0, "name": "急速(1/3)", "confidence": 0.95, "rarity": "R"}
        ]

        fr = make_frame()
        result = med._ocr_reward_choice(fr, "bond")

        assert result is not None
        assert result.name == "ocr_bond:急速(1/3)"


# =========================================================================
# P1-03: Passenger treasure non-negative hard gate tests
# =========================================================================
class TestP1_03_PassengerTreasureNegativeGate:
    def test_passenger_treasure_all_negative_candidates_closes_zero_click(self) -> None:
        """P1-03: When all candidates are negative treasures, must CLOSE, never select candidates[0]."""
        settings = Settings(mode_id="lobby_hitch", ocr_mode="off")
        med = Mediator(settings, ROOT)
        med.set_phase(Phase.MAIN_LINE)
        med._hitch_treasure_total_refreshes = 3  # budget exhausted

        # All negative cards (defined in DEFAULT_NEGATIVE_NAMES)
        med._ocr_panel_slots = lambda f, k: [
            {"index": 0, "name": "透支力量", "confidence": 0.95, "rarity": "N"},
            {"index": 1, "name": "贪婪献祭", "confidence": 0.95, "rarity": "N"},
        ]

        fr = make_frame()
        result = med._ocr_reward_choice(fr, "treasure")

        # Must NOT select slot 0 or slot 1! Result should be close button or None, never choice slot!
        if result is not None:
            assert not result.name.startswith("ocr_treasure:"), (
                f"Must NOT select negative treasure! Got {result.name}"
            )

    def test_passenger_treasure_all_unnamed_candidates_closes_zero_click(self) -> None:
        """P1-03: When all candidates have no readable name, must CLOSE, never blind click slot 0."""
        settings = Settings(mode_id="lobby_hitch", ocr_mode="off")
        med = Mediator(settings, ROOT)
        med.set_phase(Phase.MAIN_LINE)
        med._hitch_treasure_total_refreshes = 3  # budget exhausted

        med._ocr_panel_slots = lambda f, k: [
            {"index": 0, "name": "", "confidence": 0.0, "rarity": "N"},
            {"index": 1, "name": None, "confidence": 0.0, "rarity": "N"},
        ]

        fr = make_frame()
        result = med._ocr_reward_choice(fr, "treasure")

        if result is not None:
            assert not result.name.startswith("ocr_treasure:"), (
                f"Must NOT blind click unnamed slot! Got {result.name}"
            )

    def test_passenger_treasure_positive_candidate_selected(self) -> None:
        """P1-03: 1 non-negative positive + 1 negative card -> selects the non-negative card."""
        settings = Settings(mode_id="lobby_hitch", ocr_mode="off")
        med = Mediator(settings, ROOT)
        med.set_phase(Phase.MAIN_LINE)
        med._hitch_treasure_total_refreshes = 3  # budget exhausted

        med._ocr_panel_slots = lambda f, k: [
            {"index": 0, "name": "透支力量", "confidence": 0.95, "rarity": "N"},
            {"index": 1, "name": "防御神符", "confidence": 0.95, "rarity": "R"},
        ]

        fr = make_frame()
        result = med._ocr_reward_choice(fr, "treasure")

        assert result is not None
        assert result.name == "ocr_treasure:防御神符", f"Expected slot 1 ('防御神符'), got {result.name}"

    def test_passenger_treasure_shareable_priority_preserved(self) -> None:
        """P1-03: Shareable items (e.g. 英雄卡) selected before regular positive cards."""
        settings = Settings(mode_id="lobby_hitch", ocr_mode="off")
        med = Mediator(settings, ROOT)
        med.set_phase(Phase.MAIN_LINE)
        med._hitch_treasure_total_refreshes = 0

        med._ocr_panel_slots = lambda f, k: [
            {"index": 0, "name": "普通铁剑", "confidence": 0.95, "rarity": "N"},
            {"index": 1, "name": "英雄卡·关羽", "confidence": 0.95, "rarity": "SR"},
        ]

        fr = make_frame()
        result = med._ocr_reward_choice(fr, "treasure")

        assert result is not None
        assert result.name == "ocr_treasure:英雄卡·关羽", f"Expected slot 1 (英雄卡), got {result.name}"
