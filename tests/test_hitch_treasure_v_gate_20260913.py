"""Regression tests for Hitch Treasure V (三选一) panel FSM & policy fixes (2026-09-13).

Addresses issues observed in hitch_lobby_chain_20260913_000146_191455 trace:
1. Independent V retry: Black-merchant kill balance cannot suppress treasure collection.
2. Refresh budget: Whole-session refresh budget (max 3) & consecutive no-pick cap.
3. OCR fail-closed: No candidates or OCR failure leads to safe close, never blind refresh.
4. Panel classification: Joint anchor confirmation, giveUp anchor identifies skill not treasure.
5. Close target safety: Treasure close never falls back to skill_hide or card_hide.
6. Mutation confirmation: Unconfirmed mutation prevents reopening same V immediately.
7. Action distinction: Clearly distinguishes treasure选择, treasure刷新, treasure关闭.
8. Normal selection: Standard shared items (e.g. 吞噬丹, 神符) are correctly selected.
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from shuabao.mediator import LoopAction, MatchResult, Mediator, PanelState, Phase
from shuabao.runtime_mediator import Mediator as RuntimeMediator
from shuabao.settings import Settings
from shuabao.vision.capture import Frame

ROOT = Path(__file__).resolve().parents[1]


def make_frame() -> Frame:
    img = np.zeros((720, 1280, 3), dtype=np.uint8)
    return Frame(img, window_title="英雄三国", hwnd=100, role="l1")


def make_mediator() -> Mediator:
    settings = Settings(mode_id="lobby_hitch", ocr_mode="live")
    med = Mediator(settings, ROOT)
    med.set_phase(Phase.MAIN_LINE)
    med._choice_target = "treasure"
    return med


class TestHitchTreasureVGate:
    def test_1_treasure_open_is_not_gated_by_merchant_kill_balance(self) -> None:
        """A spent/stagnant merchant balance must not strand accumulated treasures."""
        med = make_mediator()
        fr = make_frame()
        btn = MatchResult("treasure_button", 0.95, 100, 100, 20, 20, 100, 100)

        # A first V probe opens normally.
        with patch.object(med, "_merchant_kill_balance", return_value=10), \
             patch.object(med, "_hud_button_hit", return_value=btn), \
             patch.object(med, "act_click", return_value=True) as click:
            action = med._maybe_open_choice_panel(fr)
            assert action == LoopAction.Continue
            assert click.call_count == 1
            assert click.call_args[0][1] == "OpenTreasurePanel"
            assert med._hitch_last_treasure_kill_balance == 10

        # A known 10 -> 10 balance does not suppress a genuine later choice.
        med._panel_state = PanelState.CLOSED
        med._panel_cooldown_until["treasure"] = 0.0
        med._panel_opened_by_us = None
        med._choice_target = "treasure"
        with patch.object(med, "_merchant_kill_balance", return_value=10), \
             patch.object(med, "_hud_button_hit", return_value=btn), \
             patch.object(med, "act_click", return_value=True) as click:
            action = med._maybe_open_choice_panel(fr)
            assert action == LoopAction.Continue
            click.assert_called_once()

    def test_1b_treasure_empty_probe_uses_short_retry_not_kill_ocr(self) -> None:
        """An empty V is rate-limited by its own retry timer, even if OCR is unavailable."""
        med = make_mediator()
        fr = make_frame()
        btn = MatchResult("treasure_button", 0.95, 100, 100, 20, 20, 100, 100)
        med._hitch_treasure_retry_at = time.time() + 5.0

        with patch.object(med, "_merchant_kill_balance", return_value=None), \
             patch.object(med, "_hud_button_hit", return_value=btn), \
             patch.object(med, "act_click", return_value=True) as click:
            assert med._maybe_open_choice_panel(fr) == LoopAction.Continue
            click.assert_not_called()

        med._panel_state = PanelState.CLOSED
        med._panel_cooldown_until["treasure"] = 0.0
        med._panel_opened_by_us = None
        med._choice_target = "treasure"
        med._hitch_treasure_retry_at = time.time() - 0.1
        with patch.object(med, "_merchant_kill_balance", return_value=None), \
             patch.object(med, "_hud_button_hit", return_value=btn), \
             patch.object(med, "act_click", return_value=True) as click:
            assert med._maybe_open_choice_panel(fr) == LoopAction.Continue
            click.assert_called_once()

    def test_1c_treasure_balance_drop_does_not_block_unconfirmed_new_panel(self) -> None:
        """A changed panel fingerprint clears the repeat-click guard without a kill increase."""
        med = make_mediator()
        fr = make_frame()
        btn = MatchResult("treasure_button", 0.95, 100, 100, 20, 20, 100, 100)
        med._hitch_last_treasure_unconfirmed_fp = "old-panel"
        med._panel_state = PanelState.CLOSED
        med._panel_cooldown_until["treasure"] = 0.0
        med._panel_opened_by_us = None
        med._choice_target = "treasure"
        with patch.object(med, "_panel_physical_fingerprint", return_value="new-panel"), \
             patch.object(med, "_merchant_kill_balance", return_value=1), \
             patch.object(med, "_hud_button_hit", return_value=btn), \
             patch.object(med, "act_click", return_value=True) as click:
            assert med._maybe_open_choice_panel(fr) == LoopAction.Continue
            click.assert_called_once()
            assert med._hitch_last_treasure_unconfirmed_fp is None

    def test_2_refresh_budget_whole_session_cap(self) -> None:
        """Requirement 2: Refresh budget capped across session (<=3) and consecutive no-picks."""
        med = make_mediator()
        fr = make_frame()
        refresh_hit = MatchResult("treasure_refresh_btn", 0.95, 800, 500, 10, 10, 800, 500)
        close_hit = MatchResult("treasure_hide_btn", 0.95, 750, 550, 10, 10, 750, 550)

        # Slots without shared items, refresh would be chosen if budget allowed
        slots = [{"index": 0, "name": "普通攻击", "confidence": 0.95}]
        with patch.object(med, "_ocr_panel_slots", return_value=slots), \
             patch.object(med, "_panel_can_refresh", return_value=True), \
             patch.object(med, "_find_panel_refresh", return_value=refresh_hit), \
             patch.object(med, "_close_current_panel", return_value=close_hit):

            # When total refreshes reach 3: do not refresh/close-loop; pick a
            # deterministic fallback so the panel can finish and the next
            # reward can be processed.
            med._hitch_treasure_total_refreshes = 3
            res = med._ocr_reward_choice(fr, "treasure")
            assert res is not None
            assert res.name == "ocr_treasure:普通攻击"
            assert res != refresh_hit

            # The consecutive no-pick guard has the same fallback behavior.
            med._hitch_treasure_total_refreshes = 0
            med._treasure_consecutive_no_pick = 2
            res2 = med._ocr_reward_choice(fr, "treasure")
            assert res2 is not None
            assert res2.name == "ocr_treasure:普通攻击"
            assert res2 != refresh_hit

    def test_2b_no_refresh_charge_picks_positive_or_any_slot(self) -> None:
        """末段无刷新次数时，即使没有共享道具也必须落地选卡。"""
        med = make_mediator()
        fr = make_frame()
        slots = [
            {"index": 0, "name": "压制", "confidence": 0.98, "description": "降低攻速"},
            {"index": 1, "name": "力量提升", "confidence": 0.98},
        ]
        with patch.object(med, "_ocr_panel_slots", return_value=slots), \
             patch.object(med, "_panel_can_refresh", return_value=False):
            med._hitch_treasure_total_refreshes = 3
            res = med._ocr_reward_choice(fr, "treasure")
        assert res is not None
        assert res.name == "ocr_treasure:力量提升"

    def test_2c_no_refresh_charge_with_unread_names_safely_closes_never_blind_picks(self) -> None:
        """P1-03: 刷新耗尽且 OCR 名称不可用时，严格安全关闭，严禁盲选第一张未识别卡。"""
        med = make_mediator()
        fr = make_frame()
        slots = [{"index": 0, "name": "", "confidence": 0.1}]
        with patch.object(med, "_ocr_panel_slots", return_value=slots), \
             patch.object(med, "_panel_can_refresh", return_value=False):
            med._hitch_treasure_total_refreshes = 3
            res = med._ocr_reward_choice(fr, "treasure")
        if res is not None:
            assert not res.name.startswith("ocr_treasure:"), (
                f"Must safely close instead of blind picking slot! Got {res.name}"
            )

    def test_3_ocr_no_candidates_safe_close_never_refresh(self) -> None:
        """Requirement 3: OCR failure / no valid candidates safely closes, never refreshes."""
        med = make_mediator()
        fr = make_frame()
        refresh_hit = MatchResult("treasure_refresh_btn", 0.95, 800, 500, 10, 10, 800, 500)
        close_hit = MatchResult("treasure_hide_btn", 0.95, 750, 550, 10, 10, 750, 550)

        # Slots have invalid/whitespace names
        empty_slots = [{"index": 0, "name": "   ", "confidence": 0.2}]
        with patch.object(med, "_ocr_panel_slots", return_value=empty_slots), \
             patch.object(med, "_panel_can_refresh", return_value=True), \
             patch.object(med, "_find_panel_refresh", return_value=refresh_hit), \
             patch.object(med, "_close_current_panel", return_value=close_hit):
            res = med._ocr_reward_choice(fr, "treasure")
            assert res == close_hit
            assert res != refresh_hit

    def test_4_panel_classification_giveup_is_skill_not_treasure(self) -> None:
        """Requirement 4: giveUp anchor forces classification to skill, even if opened by V."""
        med = make_mediator()
        med._panel_opened_by_us = "treasure"
        med._treasure_open_request_fp = "before-v"
        fr = make_frame()

        giveup_hit = MatchResult("giveUp", 0.963, 640, 600, 20, 20, 640, 600)

        def mock_find(frame, targets, **kwargs):
            if "giveUp" in targets or "skill_giveup_btn" in targets:
                return giveup_hit
            return None

        with patch.object(med, "find", side_effect=mock_find), \
             patch.object(med, "_panel_physical_fingerprint", return_value="before-v"):
            kind = med._panel_kind_of(fr, anchor=giveup_hit)
            assert kind == "skill"
            assert kind != "treasure"

    def test_4b_opened_treasure_with_only_generic_hide_not_treasure(self) -> None:
        """Requirement: Proactively opened by V, but only generic hide matches: must NOT classify as treasure."""
        med = make_mediator()
        med._panel_opened_by_us = "treasure"
        med._treasure_open_request_fp = "before-v"
        fr = make_frame()

        hide_hit = MatchResult("hide", 0.95, 700, 600, 20, 20, 700, 600)

        def mock_find(frame, targets, **kwargs):
            if "hide" in targets and "treasure_lock_btn" not in targets and "treasure_hide_btn" not in targets and "treasure_refresh_btn" not in targets:
                return hide_hit
            return None

        with patch.object(med, "find", side_effect=mock_find), \
             patch.object(med, "_panel_physical_fingerprint", return_value="before-v"):
            kind = med._panel_kind_of(fr, anchor=hide_hit)
            assert kind != "treasure"
            assert kind == "unknown"

            classified = med._classify_choice_panel(fr)
            assert classified != "treasure"

    def test_5_treasure_close_never_falls_back_to_skill_hide(self) -> None:
        """Requirement 5: Treasure close targets only treasure_hide_btn / hide, never skill_hide."""
        med = make_mediator()
        rt_med = RuntimeMediator(Settings(), ROOT)
        fr = make_frame()

        skill_hide_hit = MatchResult("skill_hide", 0.95, 700, 600, 10, 10, 700, 600)
        queried_targets: list[str] = []

        def mock_find(frame, targets, **kwargs):
            if isinstance(targets, (list, tuple)):
                queried_targets.extend(targets)
            else:
                queried_targets.append(targets)
            if "skill_hide" in targets:
                return skill_hide_hit
            return None

        with patch.object(med, "find", side_effect=mock_find):
            # 1. In _close_current_panel, targets must exclude skill_hide & card_hide
            med._close_current_panel(fr, panel_kind="treasure")
            assert "skill_hide" not in queried_targets
            assert "card_hide" not in queried_targets

        with patch.object(rt_med, "find", side_effect=mock_find):
            # 2. In _verified_panel_close, finding skill_hide will NOT return a hit for treasure
            close_hit = rt_med._verified_panel_close(fr, kind="treasure")
            assert close_hit is None

    def test_6_unconfirmed_mutation_blocks_immediate_reopen(self) -> None:
        """Requirement 6: Unconfirmed mutation compares physical panel fingerprint and blocks reopening."""
        med = make_mediator()
        fr1 = make_frame()
        fr1.bgr[200:300, 400:600] = 120  # distinct ROI pixels

        fr2 = make_frame()
        fr2.bgr[200:300, 400:600] = 240  # different ROI pixels

        btn = MatchResult("treasure_button", 0.95, 100, 100, 20, 20, 100, 100)

        # Verify physical fingerprint is actually computed from the frame ROI
        fp1 = med._panel_physical_fingerprint(fr1)
        fp2 = med._panel_physical_fingerprint(fr2)
        assert fp1 is not None and len(fp1) == 16
        assert fp2 is not None and len(fp2) == 16
        assert fp1 != fp2

        # Set unconfirmed fingerprint to fp1
        med._hitch_last_treasure_unconfirmed_fp = fp1
        med._hitch_last_treasure_kill_balance = 10

        # Case A: Frame fr1 matches the unconfirmed physical fingerprint.
        # Even if kills grew (e.g. 20 > 10), it MUST NOT reopen while the same physical panel remains!
        with patch.object(med, "_merchant_kill_balance", return_value=20), \
             patch.object(med, "_hud_button_hit", return_value=btn), \
             patch.object(med, "act_click", return_value=True) as click:
            action = med._maybe_open_choice_panel(fr1)
            assert action == LoopAction.Continue
            click.assert_not_called()
            assert med._hitch_last_treasure_unconfirmed_fp == fp1

        # Case B: Frame fr2 has a different physical fingerprint and kills grew.
        # It is now safe to open V, and the unconfirmed fingerprint is cleared.
        with patch.object(med, "_merchant_kill_balance", return_value=20), \
             patch.object(med, "_hud_button_hit", return_value=btn), \
             patch.object(med, "act_click", return_value=True) as click:
            action = med._maybe_open_choice_panel(fr2)
            assert action == LoopAction.Continue
            assert click.call_count == 1
            assert med._hitch_last_treasure_unconfirmed_fp is None

    def test_6b_mutation_confirmed_clears_unconfirmed_fingerprint(self) -> None:
        """Requirement: When treasure select mutation is confirmed, unconfirmed fingerprint must be cleared."""
        med = make_mediator()
        now = time.time()

        # Direct confirmation via _confirm_panel_choice_action
        med._hitch_last_treasure_unconfirmed_fp = "deadbeef12345678"
        med._panel_kind = "treasure"
        med._stage_panel_choice_action("select", ("treasure", "card_0", 50, 50))
        med._confirm_panel_choice_action(now)
        assert med._hitch_last_treasure_unconfirmed_fp is None

        # FSM WAIT_MUTATION confirmation when panel disappears (anchor is None)
        med._hitch_last_treasure_unconfirmed_fp = "feedbeef87654321"
        med._panel_kind = "treasure"
        med._panel_state = PanelState.WAIT_MUTATION
        med._stage_panel_choice_action("select", ("treasure", "card_0", 50, 50))
        med._tick_panel_fsm(make_frame(), None, now)
        assert med._hitch_last_treasure_unconfirmed_fp is None

    def test_7_action_labels_distinguished(self) -> None:
        """Requirement 7: Treasure click distinguishes treasure选择, treasure刷新, treasure关闭."""
        med = make_mediator()
        fr = make_frame()
        anchor = MatchResult("treasure_lock_btn", 0.9, 500, 500, 10, 10, 500, 500)
        now = time.time()

        # 1. Selection
        card_hit = MatchResult("card_slot_0", 0.95, 400, 300, 50, 50, 400, 300)
        with patch.object(med, "act_click", return_value=True) as click, \
             patch.object(med, "_find_reward_choice", return_value=("treasure", card_hit)):
            med._panel_kind = "treasure"
            med._panel_state = PanelState.ACTIVE
            med._panel_opened_by_us = "treasure"
            med._selection_click_cooldown_until = 0.0
            med._tick_panel_fsm(fr, anchor, now)
            click.assert_called_once()
            assert click.call_args[0][1] == "treasure选择"

        # 2. Refresh
        refresh_hit = MatchResult("treasure_refresh_btn", 0.95, 800, 500, 10, 10, 800, 500)
        with patch.object(med, "act_click", return_value=True) as click, \
             patch.object(med, "_find_reward_choice", return_value=("treasure", refresh_hit)):
            med._panel_kind = "treasure"
            med._panel_state = PanelState.ACTIVE
            med._panel_opened_by_us = "treasure"
            med._selection_click_cooldown_until = 0.0
            med._tick_panel_fsm(fr, anchor, now + 10.0)
            click.assert_called_once()
            assert click.call_args[0][1] == "treasure刷新"

        # 3. Close
        close_hit = MatchResult("treasure_hide_btn", 0.95, 750, 550, 10, 10, 750, 550)
        with patch.object(med, "act_click", return_value=True) as click, \
             patch.object(med, "_find_reward_choice", return_value=("treasure", close_hit)):
            med._panel_kind = "treasure"
            med._panel_state = PanelState.ACTIVE
            med._panel_opened_by_us = "treasure"
            med._selection_click_cooldown_until = 0.0
            med._tick_panel_fsm(fr, anchor, now + 20.0)
            click.assert_called_once()
            assert click.call_args[0][1] == "treasure关闭"

    def test_8_normal_recognition_selects_shared_item(self) -> None:
        """Requirement 8: Standard shared items (e.g. 吞噬丹, 神符) are correctly selected."""
        med = make_mediator()
        fr = make_frame()
        slots = [
            {"index": 0, "name": "未知垃圾", "confidence": 0.95},
            {"index": 1, "name": "吞噬丹", "confidence": 0.98},
            {"index": 2, "name": "木材包", "confidence": 0.90},
        ]
        with patch.object(med, "_ocr_panel_slots", return_value=slots):
            res = med._ocr_reward_choice(fr, "treasure")
            assert res is not None
            assert res.name == "ocr_treasure:吞噬丹"
            assert med._treasure_consecutive_no_pick == 0
