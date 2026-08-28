"""Regression coverage for the 2026-08-11 20:50 live run."""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.choice_policy import SessionState
from shuabao.loop_action import LoopAction
from shuabao.mediator import Mediator, PanelState, Phase, RecoveryKind, RecoveryStep, RoundOutcome
from shuabao.runtime_mediator import Mediator as RuntimeMediator
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult


def frame() -> Frame:
    return Frame(np.zeros((900, 1600, 3), dtype=np.uint8), hwnd=1, window_title="英雄三国KK")


class LiveRun205044Tests(unittest.TestCase):
    def test_owned_bond_select_waits_for_second_ocr_frame(self) -> None:
        med = Mediator(Settings(ocr_mode="live", cards=["祝福"]), ROOT)
        med._panel_opened_by_us = "bond"
        med._panel_kind = "bond"
        slots = [
            {"index": 0, "name": "祝福", "confidence": 0.99, "raw_text": "祝福"},
            {"index": 1, "name": "体术", "confidence": 0.99, "raw_text": "体术"},
            {"index": 2, "name": "亡灵", "confidence": 0.99, "raw_text": "亡灵"},
            {"index": 3, "name": "刀刀", "confidence": 0.99, "raw_text": "刀刀"},
        ]
        with patch.object(med, "_ocr_panel_slots", return_value=slots):
            self.assertIsNone(med._ocr_reward_choice(frame(), "bond"))
            hit = med._ocr_reward_choice(frame(), "bond")
        self.assertIsNotNone(hit)
        self.assertIn("祝福", hit.name)

    def test_live_ocr_miss_waits_instead_of_refreshing_bond_panel(self) -> None:
        med = Mediator(Settings(ocr_mode="live", cards=["祝福"]), ROOT)
        med._panel_opened_by_us = "bond"
        med._panel_kind = "bond"
        refresh = MatchResult("bond_refresh_btn", 0.99, 1038, 575, 56, 26, 1038, 575)
        anchor = MatchResult("bond_hide_btn", 0.85, 805, 575, 94, 26, 805, 575)
        with patch.object(med, "_ocr_reward_choice", return_value=None), \
                patch.object(med, "_find_panel_refresh", return_value=refresh) as find_refresh:
            choice = med._find_reward_choice(frame(), anchor)
        self.assertIsNone(choice)
        self.assertTrue(med._choice_policy_idle)
        find_refresh.assert_not_called()

    def test_runtime_allows_awaited_hero_over_false_treasure_lock(self) -> None:
        med = RuntimeMediator(Settings(), ROOT)
        med._evolve_awaiting_hero_pick = True
        expected = MatchResult("evolution_card_1_rank_5", 0.99, 900, 320, 1, 1, 900, 320)
        with patch.object(med, "_classify_choice_panel", return_value="treasure"), \
                patch("shuabao.mediator.Mediator._find_evolution_choice", return_value=expected) as core_choice:
            self.assertIs(med._find_evolution_choice(frame()), expected)
        core_choice.assert_called_once()

    def test_evolve_feedback_pending_does_not_classify_treasure(self) -> None:
        med = Mediator(Settings(), ROOT)
        med._evolve_feedback_pending = True
        lock = MatchResult("treasure_lock_btn", 0.99, 1, 1, 1, 1, 1, 1)
        hide = MatchResult("hide", 0.96, 1, 1, 1, 1, 1, 1)

        def fake_find(_frame, names, **_kwargs):
            if "treasure_lock_btn" in names:
                return lock
            if "hide" in names:
                return hide
            return None

        with patch.object(med, "find", side_effect=fake_find):
            self.assertIsNone(med._classify_choice_panel(frame()))

    def test_main_line_starts_on_bond(self) -> None:
        med = Mediator(Settings(), ROOT)
        self.assertEqual(med._l1_cycle_step, "bond")
        med.set_phase(Phase.MAIN_LINE, "live start")
        self.assertEqual(med._l1_cycle_step, "bond")
        runtime = RuntimeMediator(Settings(), ROOT)
        runtime.set_phase(Phase.MAIN_LINE, "live start")
        self.assertEqual(runtime._l1_cycle_step, "bond")
        self.assertEqual(runtime._l1_cycle_index, 0)

    def test_runtime_rejects_evolution_detector_on_active_bond_panel(self) -> None:
        med = RuntimeMediator(Settings(), ROOT)
        med._panel_opened_by_us = "bond"
        with patch("shuabao.mediator.Mediator._find_evolution_choice") as core_choice:
            self.assertIsNone(med._find_evolution_choice(frame()))
        core_choice.assert_not_called()

    def test_strong_failure_counts_two_new_evidence_generations(self) -> None:
        med = Mediator(Settings(), ROOT)
        med.set_phase(Phase.MAIN_LINE, "live consecutive frames")
        images = iter(
            Frame(np.random.default_rng(seed).integers(0, 255, (900, 1600, 3), dtype=np.uint8),
                  hwnd=1, window_title="英雄三国KK")
            for seed in (1, 2)
        )
        med._capture_best = lambda *_a, **_k: next(images)
        fail = MatchResult("gameFail", 0.99, 752, 372, 96, 96, 752, 372)

        def scene(_frame, key, **_kwargs):
            return fail if key == "fail" else None

        with patch.object(med, "find_scene", side_effect=scene):
            self.assertIs(med.tick(), LoopAction.Continue)
            first_generation = med._failure_candidate_gen
            self.assertIs(med.phase, Phase.MAIN_LINE)
            self.assertIs(med.tick(), LoopAction.Continue)
        self.assertNotEqual(first_generation, med._failure_candidate_gen)
        self.assertIs(med.phase, Phase.RECOVER_FAILURE)
        self.assertIs(med._recovery_state.kind, RecoveryKind.FAIL)

    def test_skill_ocr_miss_refreshes_without_masquerading_as_configured(self) -> None:
        med = Mediator(Settings(skills=["assx"]), ROOT)
        slots = [
            {"index": 0, "name": "电磁网", "confidence": 0.99, "raw_text": "电磁网", "family_source": "badge"},
            {"index": 1, "name": "重创", "confidence": 0.99, "raw_text": "重创", "family_source": "badge"},
            {"index": 2, "name": None, "confidence": 0.0, "raw_text": "多重射线", "family_source": "badge"},
        ]
        refresh = MatchResult("skill_refresh_btn", 0.99, 1000, 575, 56, 26, 1000, 575)
        with patch.object(med, "_ocr_panel_slots", return_value=slots), \
                patch.object(med, "_find_panel_refresh", return_value=refresh):
            fill_hit = med._ocr_reward_choice(frame(), "skill")
        # 未读成奥数射线时，同图标/原始文本不得冒充配置技能 assx；
        # 严格白名单未命中时只刷新，绝不补位拿配置外技能。
        self.assertIsNotNone(fill_hit)
        self.assertEqual(fill_hit.name, "skill_refresh_btn")
        self.assertNotEqual(fill_hit.name, "assx")

        slots[2] = {"index": 2, "name": "奥术射线", "confidence": 0.99, "raw_text": "奥术射线", "family_source": "badge"}
        with patch.object(med, "_ocr_panel_slots", return_value=slots):
            hit = med._ocr_reward_choice(frame(), "skill")
        self.assertIsNotNone(hit)
        self.assertEqual(hit.name, "assx")
        self.assertEqual(hit.x, int(1600 * 0.646))

    def test_empty_skill_ocr_does_not_click_giveup(self) -> None:
        med = Mediator(Settings(skills=["asj", "asjg", "assx", "jq"], ocr_mode="live"), ROOT)
        slots = [
            {"index": 0, "name": None, "confidence": 0.0},
            {"index": 1, "name": None, "confidence": 0.0},
            {"index": 2, "name": None, "confidence": 0.0},
        ]
        giveup = MatchResult("skill_giveup_btn", 0.99, 580, 552, 40, 20, 580, 552)
        med._choice_session = SessionState(waits=5, max_waits=5, refreshes=3, max_refreshes=3)
        with patch.object(med, "_ocr_panel_slots", return_value=slots), \
                patch.object(med, "_panel_has_giveup", return_value=True), \
                patch.object(med, "_find_panel_giveup", return_value=giveup), \
                patch.object(med, "_find_panel_refresh", return_value=None), \
                patch.object(med, "_find_skill_hide", return_value=None):
            hit = med._ocr_reward_choice(frame(), "skill")
        if hit is not None:
            self.assertNotIn((hit.name or "").lower(), {"skill_giveup_btn", "giveup"})

    def test_bond_full_bar_allows_only_one_away_merge(self) -> None:
        # A3：硬白名单取代占用启发式。未勾选一律不选（WAIT→None）；
        # 勾选「祝福」后才可选中，与栏位是否接近满无关。
        med = Mediator(Settings(cards=["祝福"], bond_whitelist_mode="hard"), ROOT)
        unsafe = [
            {"index": 0, "name": "海盗", "confidence": 0.99, "raw_text": "海盗"},
            {"index": 1, "name": "智力", "confidence": 0.99, "raw_text": "智力(0/4)"},
            {"index": 2, "name": "军团", "confidence": 0.99, "raw_text": "军团"},
        ]
        with patch.object(med, "_ocr_panel_slots", return_value=unsafe), \
                patch.object(med, "_bond_bar_occupancy", return_value=9), \
                patch.object(med, "_find_panel_refresh", return_value=None), \
                patch.object(med, "_find_panel_giveup", return_value=None), \
                patch.object(med, "_close_current_panel", return_value=None):
            self.assertIsNone(med._ocr_reward_choice(frame(), "bond"))

        safe = list(unsafe)
        safe[0] = {"index": 0, "name": "祝福", "confidence": 0.99, "raw_text": "祝福(2/3)"}
        with patch.object(med, "_ocr_panel_slots", return_value=safe), \
                patch.object(med, "_bond_bar_occupancy", return_value=9):
            hit = med._ocr_reward_choice(frame(), "bond")
        self.assertIsNotNone(hit)
        self.assertEqual(hit.name, "ocr_bond:祝福")

    def test_basic_bond_precedes_advanced_bond(self) -> None:
        # 硬白名单：只勾「法术」时选法术；未勾的「亡灵天灾」即使接近合成也不选。
        med = Mediator(Settings(cards=["法术"], bond_whitelist_mode="hard"), ROOT)
        slots = [
            {"index": 0, "name": "亡灵天灾", "confidence": 0.99, "raw_text": "亡灵天灾(2/3)"},
            {"index": 1, "name": "法术", "confidence": 0.99, "raw_text": "法术(0/3)"},
            {"index": 2, "name": None, "confidence": 0.0, "raw_text": ""},
        ]
        with patch.object(med, "_ocr_panel_slots", return_value=slots), \
                patch.object(med, "_bond_bar_occupancy", return_value=5):
            hit = med._ocr_reward_choice(frame(), "bond")
        self.assertIsNotNone(hit)
        self.assertEqual(hit.name, "ocr_bond:法术")

    def test_early_bond_does_not_start_pirate_or_undead_variants(self) -> None:
        med = Mediator(Settings(bond_whitelist_mode="hard"), ROOT)
        slots = [
            {"index": 0, "name": "白赚海盗", "confidence": 0.99, "raw_text": "白赚海盗(0/3)"},
            {"index": 1, "name": "亡灵天灾", "confidence": 0.99, "raw_text": "亡灵天灾(0/3)"},
            {"index": 2, "name": "海盗劫掠者", "confidence": 0.99, "raw_text": "海盗劫掠者(0/3)"},
        ]
        with patch.object(med, "_ocr_panel_slots", return_value=slots), \
                patch.object(med, "_bond_bar_occupancy", return_value=2), \
                patch.object(med, "_find_panel_refresh", return_value=None), \
                patch.object(med, "_find_panel_giveup", return_value=None), \
                patch.object(med, "_close_current_panel", return_value=None):
            self.assertIsNone(med._ocr_reward_choice(frame(), "bond"))

    def test_existing_advanced_bond_progress_can_still_be_finished(self) -> None:
        # 硬白名单：用户勾选「亡灵天灾」后才可完成进度；未勾选的海盗变体仍不可选。
        med = Mediator(Settings(cards=["亡灵天灾"], bonds=[], bond_whitelist_mode="hard"), ROOT)
        slots = [
            {"index": 0, "name": "亡灵天灾", "confidence": 0.99, "raw_text": "亡灵天灾(2/3)"},
            {"index": 1, "name": "白赚海盗", "confidence": 0.99, "raw_text": "白赚海盗(0/3)"},
            {"index": 2, "name": None, "confidence": 0.0, "raw_text": ""},
        ]
        with patch.object(med, "_ocr_panel_slots", return_value=slots), \
                patch.object(med, "_bond_bar_occupancy", return_value=2):
            hit = med._ocr_reward_choice(frame(), "bond")
        self.assertIsNotNone(hit)
        self.assertEqual(hit.name, "ocr_bond:亡灵天灾")

    def test_bond_slot_centers_cover_true_middle_and_right_cards(self) -> None:
        med = Mediator(Settings(), ROOT)
        middle = med._choice_slot_hit(frame(), "bond", 1, "middle")
        right = med._choice_slot_hit(frame(), "bond", 2, "right")
        self.assertEqual(middle.x, 804)
        self.assertEqual(right.x, 1081)

    def test_live_bond_without_ocr_approval_never_falls_back_to_random(self) -> None:
        med = Mediator(Settings(ocr_mode="live"), ROOT)
        anchor = MatchResult("panel", 0.99, 800, 500, 10, 10, 800, 500)
        with patch.object(med, "_classify_choice_panel", return_value="bond"), \
                patch.object(med, "_ocr_reward_choice", return_value=None), \
                patch.object(med, "_close_current_panel", return_value=None), \
                patch.object(med, "_rarity_choice") as rarity:
            self.assertIsNone(med._find_reward_choice(frame(), anchor))
        rarity.assert_not_called()

    def test_current_bond_panel_uses_card_hide_as_safe_exit(self) -> None:
        med = Mediator(Settings(ocr_mode="live"), ROOT)
        close = MatchResult("card_hide", 0.80, 800, 575, 10, 10, 800, 575)

        def find(_frame, names, **_kwargs):
            return close if "card_hide" in names else None

        with patch.object(med, "find", side_effect=find), \
                patch.object(med, "_panel_kind_of", return_value="bond"), \
                patch.object(med, "_ocr_reward_choice", return_value=None):
            choice = med._find_reward_choice(frame(), close)

        self.assertIsNotNone(choice)
        self.assertEqual(choice[0], "bond")
        self.assertEqual(choice[1].name, "card_hide")

        med._panel_opened_by_us = "bond"
        with patch.object(med, "find", side_effect=find), \
                patch.object(med, "_panel_kind_of", return_value="bond"), \
                patch.object(med, "_ocr_reward_choice", return_value=None):
            self.assertIsNone(med._find_reward_choice(frame(), close))

    def test_inventory_hero_card_does_not_loop_on_static_evolution_label(self) -> None:
        med = Mediator(Settings(ui_action_interval_s=0.0), ROOT)
        hero = MatchResult("hero_card_item", 0.99, 1100, 800, 10, 10, 1100, 800)
        med._bond_bar_nonempty = lambda _frame: False
        med._evolve_ok_this_cycle = True
        with patch.object(med, "find", return_value=hero) as find, \
                patch.object(med, "act_click", return_value=True) as click:
            self.assertIs(med._maybe_use_inventory_item(frame()), LoopAction.Continue)
        click.assert_called_once_with(hero, "UseInventory-hero-card")
        self.assertEqual(find.call_args.args[1], ["hero_card_item"])

    def test_inventory_hero_card_requires_evolve_and_blocks_pending_repeat(self) -> None:
        """英雄卡必须等进化完成，未确认的点击不得穿透到下一次输入。"""
        med = Mediator(Settings(ui_action_interval_s=0.0), ROOT)
        hero = MatchResult("hero_card_item", 0.99, 1303, 898, 10, 10, 1303, 898)
        med._bond_bar_nonempty = lambda _frame: False
        with patch.object(med, "find", return_value=hero), \
                patch.object(med, "act_click", return_value=True) as click:
            self.assertIsNone(med._maybe_use_inventory_item(frame()))
            click.assert_not_called()
            med._evolve_ok_this_cycle = True
            self.assertIs(med._maybe_use_inventory_item(frame()), LoopAction.Continue)
            med._inventory_next_at = 0.0
            self.assertIsNone(med._maybe_use_inventory_item(frame()))
        click.assert_called_once_with(hero, "UseInventory-hero-card")

    def test_affix_prefers_green_positive_row(self) -> None:
        """装备十级词缀优先绿字「积极属性」，而非永远点第一行。"""
        med = Mediator(Settings(), ROOT)
        image = np.zeros((900, 1600, 3), dtype=np.uint8)
        cv2.rectangle(image, (560, 215), (1039, 219), (0, 170, 230), -1)
        cv2.rectangle(image, (560, 430), (1039, 434), (0, 170, 230), -1)
        for y in (240, 285, 330, 375):
            cv2.rectangle(image, (735, y + 10), (865, y + 18), (230, 230, 230), -1)
        # 小色块即可触发 HSV 排名；大色块会破坏 body 暗底门闩（需 ≥85% gray<80）。
        # BGR：第 0 行红、第 2 行绿（积极属性）→ 应选 equipment_affix_2。
        cv2.rectangle(image, (700, 250), (760, 268), (40, 40, 220), -1)
        cv2.rectangle(image, (700, 340), (760, 358), (40, 200, 40), -1)
        hit = med._find_equipment_affix_choice(Frame(image))
        self.assertIsNotNone(hit)
        self.assertEqual(hit.name, "equipment_affix_2")

    def test_single_low_score_bond_anchor_never_classifies_as_bond(self) -> None:
        # P0-3（215302 证据）：bond_refresh_btn 0.742 贴阈值单独出现曾单帧误入 bond
        # 面板；单一 bond 锚点不足为 bond 定类（需 bond_hide+bond_refresh 联合证据
        # 或 card_hide 兜底/主动打开标记），自然面板一律按分类器裁决。
        med = Mediator(Settings(ocr_mode="live"), ROOT)
        anchor = MatchResult("bond_refresh_btn", 0.742, 800, 530, 10, 10, 800, 530)
        with patch.object(med, "_classify_choice_panel", return_value=None), \
                patch.object(med, "_ocr_reward_choice", return_value=None), \
                patch.object(med, "_close_current_panel", return_value=None):
            # 无联合证据：不再轻信单锚点 bond 定类
            self.assertEqual(med._panel_kind_of(frame(), anchor), "unknown")
            self.assertIsNone(med._find_reward_choice(frame(), anchor))

        # 主动打开标记仍是可靠证据（我们刚按过 F，看见 bond 按钮即确认）
        med._panel_opened_by_us = "bond"
        self.assertEqual(med._panel_kind_of(frame(), anchor), "bond")
        med._panel_opened_by_us = "skill"
        self.assertEqual(med._panel_kind_of(frame(), anchor), "skill")

    def test_bond_classification_requires_joint_hide_and_refresh(self) -> None:
        # P0-3：bond 定类需 bond_hide_btn 与 bond_refresh_btn 同时命中；仅有
        # bond_refresh_btn（215302 中 0.70-0.79 贴阈值）不得单独定类 bond。
        med = Mediator(Settings(), ROOT)
        refresh = MatchResult("bond_refresh_btn", 0.79, 860, 552, 10, 10, 860, 552)
        hide = MatchResult("bond_hide_btn", 0.81, 580, 552, 10, 10, 580, 552)
        fr = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), hwnd=1, window_title="英雄三国KK")

        def make_find(hits: dict[str, MatchResult]) -> callable:
            def fake_find(_frame, names, **_kwargs):
                for n in names:
                    if n in hits:
                        return hits[n]
                return None

            return fake_find

        # 只有 refresh 锚点（215302 贴阈值单锚点现场）→ 非 bond
        with patch.object(med, "find", side_effect=make_find({"bond_refresh_btn": refresh})):
            self.assertNotEqual(med._classify_choice_panel_at(fr, 0.70, (1.0,)), "bond")
        # hide + refresh 联合 → bond
        with patch.object(
            med, "find", side_effect=make_find({"bond_hide_btn": hide, "bond_refresh_btn": refresh})
        ):
            self.assertEqual(med._classify_choice_panel_at(fr, 0.70, (1.0,)), "bond")

    def test_shared_skill_anchor_uses_panel_color_to_separate_treasure(self) -> None:
        med = Mediator(Settings(), ROOT)
        anchor = MatchResult("skill_refresh_btn", 0.763, 860, 552, 10, 10, 860, 552)
        self.assertEqual(med._panel_kind_of(frame(), anchor), "skill")

        image = np.zeros((900, 1600, 3), dtype=np.uint8)
        image[180:515, 450:1145] = (20, 140, 20)
        self.assertEqual(med._panel_kind_of(Frame(image), anchor), "treasure")

        card_hide = MatchResult("card_hide", 0.819, 805, 575, 10, 10, 805, 575)
        self.assertEqual(med._panel_kind_of(frame(), card_hide), "bond")

    def test_opened_skill_beats_hsv_and_lone_treasure_lock(self) -> None:
        # 13号 200601：按了 G 之后金卡三选被 HSV / treasure_lock 判成宝物。
        med = Mediator(Settings(), ROOT)
        med._panel_opened_by_us = "skill"
        refresh = MatchResult("skill_refresh_btn", 0.763, 860, 552, 10, 10, 860, 552)
        image = np.zeros((900, 1600, 3), dtype=np.uint8)
        image[180:515, 450:1145] = (20, 140, 20)
        self.assertEqual(med._panel_kind_of(Frame(image), refresh), "skill")

        lock = MatchResult("treasure_lock_btn", 0.81, 580, 572, 10, 10, 580, 572)
        self.assertEqual(med._panel_kind_of(frame(), lock), "skill")

    def test_treasure_lock_alone_is_not_treasure(self) -> None:
        med = Mediator(Settings(), ROOT)
        lock = MatchResult("treasure_lock_btn", 0.81, 580, 572, 10, 10, 580, 572)
        fr = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), hwnd=1, window_title="英雄三国KK")

        def make_find(hits: dict[str, MatchResult]):
            def fake_find(_frame, names, **_kwargs):
                for n in names:
                    if n in hits:
                        return hits[n]
                return None

            return fake_find

        with patch.object(med, "find", side_effect=make_find({"treasure_lock_btn": lock})):
            self.assertNotEqual(med._classify_choice_panel_at(fr, 0.70, (1.0,)), "treasure")
            self.assertEqual(med._panel_kind_of(fr, lock), "unknown")

    def test_two_card_evolution_modal_is_not_a_skill_panel(self) -> None:
        med = Mediator(Settings(), ROOT)
        image = np.zeros((900, 1600, 3), dtype=np.uint8)
        cv2.rectangle(image, (550, 150), (784, 510), (180, 30, 180), 4)
        cv2.rectangle(image, (816, 150), (1050, 510), (180, 180, 30), 4)
        cv2.rectangle(image, (580, 180), (760, 490), (160, 20, 160), -1)
        cv2.rectangle(image, (840, 180), (1020, 490), (160, 160, 20), -1)
        anchor = MatchResult("skill_refresh_btn", 0.736, 1020, 580, 10, 10, 1020, 580)
        choice = med._find_evolution_choice(Frame(image), anchor)
        self.assertIsNotNone(choice)
        self.assertTrue(choice.name.startswith("evolution_card_"))

    def test_failure_reward_popup_preempts_initialization(self) -> None:
        med = Mediator(Settings(), ROOT)
        med.phase = Phase.MAIN_LINE
        close = MatchResult("failGiftClose", 0.99, 930, 240, 20, 20, 930, 240)
        with patch.object(med, "_post_game_state", return_value=None), \
                patch.object(med, "find", return_value=close), \
                patch.object(med, "act_click", return_value=True) as click:
            self.assertIs(med._tick_main_line(frame()), LoopAction.Continue)
        click.assert_called_once_with(close, "DismissFailureReward")

    def test_visible_evolution_preempts_background_merchant(self) -> None:
        med = Mediator(Settings(), ROOT)
        med.phase = Phase.MAIN_LINE
        med._l1_cycle_step = "merchant"
        image = np.zeros((900, 1600, 3), dtype=np.uint8)
        cv2.rectangle(image, (550, 150), (784, 510), (180, 30, 180), 4)
        cv2.rectangle(image, (816, 150), (1050, 510), (180, 180, 30), 4)
        cv2.rectangle(image, (580, 180), (760, 490), (160, 20, 160), -1)
        cv2.rectangle(image, (840, 180), (1020, 490), (160, 160, 20), -1)
        evolution_frame = Frame(image, hwnd=1, window_title="英雄三国KK")
        anchor = MatchResult("skill_refresh_btn", 0.736, 1020, 580, 10, 10, 1020, 580)
        with patch.object(med, "_post_game_state", return_value=None), \
                patch.object(med, "find", return_value=None), \
                patch.object(med, "_find_equipment_affix_choice", return_value=None), \
                patch.object(med, "_selection_anchor", return_value=anchor), \
                patch.object(med, "act_click", return_value=True) as click, \
                patch.object(med, "_maybe_black_merchant") as merchant:
            self.assertIs(med._tick_main_line(evolution_frame), LoopAction.Continue)
        self.assertEqual(click.call_args.args[1], "SelectEvolutionCard")
        merchant.assert_not_called()
        self.assertEqual(med._l1_cycle_step, "merchant")

    def test_failure_modal_red_exit_requires_green_sibling(self) -> None:
        med = Mediator(Settings(), ROOT)
        image = np.zeros((900, 1600, 3), dtype=np.uint8)
        cv2.rectangle(image, (635, 570), (756, 608), (0, 0, 220), -1)
        cv2.rectangle(image, (843, 570), (964, 608), (0, 200, 0), -1)
        fail = MatchResult("gameFail", 0.99, 752, 372, 96, 96, 752, 372)
        with patch.object(med, "find_scene", return_value=fail):
            hit = med._find_failure_exit_button(Frame(image))
        self.assertIsNotNone(hit)
        self.assertEqual(hit.name, "failure_exit")
        self.assertTrue(690 <= hit.x <= 701)

        image[570:609, 843:965] = 0
        with patch.object(med, "find_scene", return_value=fail):
            self.assertIsNone(med._find_failure_exit_button(Frame(image)))

    def test_direct_failure_exit_returns_to_same_room_flow(self) -> None:
        med = Mediator(Settings(), ROOT)
        med.set_phase(Phase.MAIN_LINE, "direct failure")
        med._begin_recovery(RecoveryKind.FAIL)
        image = np.zeros((900, 1600, 3), dtype=np.uint8)
        cv2.rectangle(image, (635, 570), (756, 608), (0, 0, 220), -1)
        cv2.rectangle(image, (843, 570), (964, 608), (0, 200, 0), -1)
        fail = MatchResult("gameFail", 0.99, 752, 372, 96, 96, 752, 372)

        def fail_scene(_frame, key, **_kwargs):
            return fail if key == "fail" else None

        with patch.object(med, "find_scene", side_effect=fail_scene), \
                patch.object(med, "act_click", return_value=True):
            self.assertIs(med._tick_recovery(Frame(image)), LoopAction.Continue)
        self.assertTrue(med._recovery_state.direct_exit)
        self.assertTrue(med._recovery_state.waiting_confirm)
        self.assertIs(med._recovery_state.step, RecoveryStep.FAIL_CONFIRM)

        with patch.object(med, "find_scene", return_value=None):
            self.assertIs(med._tick_recovery(frame()), LoopAction.Continue)
        self.assertIs(med.phase, Phase.PREPARE)
        self.assertTrue(med._awaiting_room_return)
        self.assertIs(med._round_outcome, RoundOutcome.FAILURE)

    def test_affix_detector_rejects_plain_hud_and_accepts_four_row_modal(self) -> None:
        med = Mediator(Settings(), ROOT)
        plain = frame()
        self.assertIsNone(med._find_equipment_affix_choice(plain))

        image = np.zeros((900, 1600, 3), dtype=np.uint8)
        cv2.rectangle(image, (560, 215), (1039, 219), (0, 170, 230), -1)
        cv2.rectangle(image, (560, 430), (1039, 434), (0, 170, 230), -1)
        for y in (240, 285, 330, 375):
            cv2.rectangle(image, (735, y + 10), (865, y + 18), (230, 230, 230), -1)
        hit = med._find_equipment_affix_choice(Frame(image))
        self.assertIsNotNone(hit)
        self.assertEqual(hit.name, "equipment_affix_0")

    # ---------- P0-2：click_evolve 后置确认（164929 42 次空点 / 215302 423 次狂点） ----------

    def _evolve_main_line_ctx(self, med, *, evolve_hit):
        """把 _tick_main_line 裁到仅剩进化分支的补丁栈。"""
        from contextlib import ExitStack

        def fake_find(_frame, names, **_kwargs):
            # 只对 click_evolve 查找返回命中；其余（failGiftClose 等）一律 None，
            # 防止进化按钮命中被其它模板查找误用。
            if isinstance(names, list) and "click_evolve" in names:
                return evolve_hit
            return None

        stack = ExitStack()
        for attr, value in {
            "_post_game_state": None,
            "find_scene": None,
            "_find_equipment_affix_choice": None,
            "_selection_anchor": None,
            "_ensure_auto_task_enabled": None,
            "_ensure_challenge_buttons": None,
            "_find_stage_page": False,
            "_handle_self_opened_compact_panel": None,
            "_maybe_open_choice_panel": None,
            "act_click": True,
        }.items():
            stack.enter_context(patch.object(med, attr, return_value=value, create=True))
        stack.enter_context(patch.object(med, "find", side_effect=fake_find))
        return stack

    @staticmethod
    def _evolve_ready_med() -> "Mediator":
        med = Mediator(Settings(), ROOT)
        med.phase = Phase.MAIN_LINE
        med._auto_task_done = True
        med._main_line_started_at = 0.0
        med._l1_cycle_step = "evolve"
        return med

    def test_evolve_click_waits_for_feedback_before_advancing(self) -> None:
        # P0-2：点击进化后必须观察到面板/画面反馈才算成功；未确认前 L1 循环
        # 停留在 evolve（不推进 equipment/pickup/merchant/artifact）。
        med = self._evolve_ready_med()
        evolve_hit = MatchResult("click_evolve", 0.9, 700, 880, 90, 36, 700, 880)
        with self._evolve_main_line_ctx(med, evolve_hit=evolve_hit) as stack:
            feedback_seen = stack.enter_context(
                patch.object(med, "_evolve_feedback_seen", return_value=False, create=True)
            )
            self.assertIs(med._tick_main_line(frame()), LoopAction.Continue)
        self.assertEqual(feedback_seen.call_count, 0)  # 反馈检查本身不产生输入
        self.assertTrue(med._evolve_feedback_pending)
        self.assertEqual(med._l1_cycle_step, "evolve")

    def test_evolve_no_feedback_retries_then_skips_round(self) -> None:
        # P0-2：无反馈计失败并重试（保持 5s 冷却），每轮 ≤3 次后放弃本轮进化，
        # 绝不连续空点（164929 曾 42 次空点无任何反馈）。
        med = self._evolve_ready_med()
        evolve_hit = MatchResult("click_evolve", 0.9, 700, 880, 90, 36, 700, 880)
        with self._evolve_main_line_ctx(med, evolve_hit=evolve_hit) as stack:
            stack.enter_context(patch.object(med, "_evolve_feedback_seen", return_value=False, create=True))
            for attempt in (1, 2, 3):
                # 点击
                med._evolve_click_cooldown_until = 0.0
                self.assertIs(med._tick_main_line(frame()), LoopAction.Continue)
                self.assertTrue(med._evolve_feedback_pending, f"attempt {attempt} clicked")
                # 反馈窗超时（无反馈）
                med._evolve_click_at = 0.0
                self.assertIs(med._tick_main_line(frame()), LoopAction.Continue)
                self.assertFalse(med._evolve_feedback_pending, f"attempt {attempt} failed")
                if attempt < 3:
                    self.assertEqual(med._evolve_fail_count, attempt)
                    self.assertEqual(med._l1_cycle_step, "evolve")  # 未到上限仍留在 evolve
                else:
                    self.assertEqual(med._evolve_fail_count, 0)  # 放弃后重置
                    self.assertNotEqual(med._l1_cycle_step, "evolve")  # 跳过本轮进化

    def test_evolve_feedback_advances_cycle_once(self) -> None:
        # 点击进化有反馈后停在 evolve 等英雄三选一；未选出前不进装备、不用英雄卡。
        med = self._evolve_ready_med()
        med._evolve_feedback_pending = True
        med._evolve_fail_count = 2
        med._evolve_baseline = np.zeros((450, 832, 3), dtype=np.uint8)
        with self._evolve_main_line_ctx(med, evolve_hit=None) as stack:
            stack.enter_context(patch.object(med, "_evolve_feedback_seen", return_value=True, create=True))
            self.assertIs(med._tick_main_line(frame()), LoopAction.Continue)
        self.assertFalse(med._evolve_feedback_pending)
        self.assertEqual(med._evolve_fail_count, 0)
        self.assertEqual(med._l1_cycle_step, "evolve")
        self.assertTrue(med._evolve_awaiting_hero_pick)
        self.assertFalse(med._evolve_ok_this_cycle)

    def test_evolution_modal_handling_advances_evolve_step(self) -> None:
        # P0-2：进化面板真实出现并被处理 = 点击成功反馈 → L1 循环从 evolve 推进
        # （与反馈分支一致；避免有点数时进化饿死 equipment/pickup 等后续步骤）。
        med = Mediator(Settings(), ROOT)
        med.phase = Phase.MAIN_LINE
        med._l1_cycle_step = "evolve"
        image = np.zeros((900, 1600, 3), dtype=np.uint8)
        cv2.rectangle(image, (550, 150), (784, 510), (180, 30, 180), 4)
        cv2.rectangle(image, (816, 150), (1050, 510), (180, 180, 30), 4)
        cv2.rectangle(image, (580, 180), (760, 490), (160, 20, 160), -1)
        cv2.rectangle(image, (840, 180), (1020, 490), (160, 160, 20), -1)
        evolution_frame = Frame(image, hwnd=1, window_title="英雄三国KK")
        anchor = MatchResult("skill_refresh_btn", 0.736, 1020, 580, 10, 10, 1020, 580)
        with patch.object(med, "_post_game_state", return_value=None), \
                patch.object(med, "find", return_value=None), \
                patch.object(med, "_find_equipment_affix_choice", return_value=None), \
                patch.object(med, "_selection_anchor", return_value=anchor), \
                patch.object(med, "act_click", return_value=True):
            self.assertIs(med._tick_main_line(evolution_frame), LoopAction.Continue)
        # 20260822 循环序（test_runtime_stability_hotfix_20260821 钉死）：evolve
        # 前置于 equipment（装备词缀弹窗防双模态冲突），evolve 之后是 equipment。
        self.assertEqual(med._l1_cycle_step, "equipment")
        self.assertFalse(med._evolve_feedback_pending)

    def test_evolve_feedback_seen_anchor_or_pixels(self) -> None:
        # P0-2：反馈 = 选择面板锚点出现，或面板中央区域像素变化。
        med = Mediator(Settings(), ROOT)
        fr = frame()
        anchor = MatchResult("skill_refresh_btn", 0.9, 860, 552, 10, 10, 860, 552)
        with patch.object(med, "_selection_anchor", return_value=anchor):
            self.assertTrue(med._evolve_feedback_seen(fr))

        med2 = Mediator(Settings(), ROOT)
        med2._evolve_baseline = np.zeros((450, 832, 3), dtype=np.uint8)
        image = np.full((900, 1600, 3), 255, dtype=np.uint8)
        with patch.object(med2, "_selection_anchor", return_value=None):
            self.assertTrue(med2._evolve_feedback_seen(Frame(image)))

    def test_evolve_clicks_gold_bar_not_dirt(self) -> None:
        med = Mediator(Settings(), ROOT)
        image = np.zeros((900, 1600, 3), dtype=np.uint8)
        # 左侧羁绊图标（成长）不得当成进化
        cv2.rectangle(image, (560, 620), (760, 680), (20, 180, 230), -1)
        # 「点击进化」金条在羁绊图标右侧偏下
        cv2.rectangle(image, (800, 690), (980, 715), (20, 200, 240), -1)
        hit = med._evolve_button_hit(Frame(image, hwnd=1, window_title="英雄三国KK"))
        self.assertGreater(hit.x, 760)
        self.assertGreater(hit.y, 680)
        self.assertGreaterEqual(hit.x, int(1600 * 0.48))
        self.assertLessEqual(hit.x, int(1600 * 0.64))
        self.assertGreaterEqual(hit.y, int(900 * 0.75))
        self.assertLessEqual(hit.y, int(900 * 0.81))

    def test_orange_border_not_classified_as_green(self) -> None:
        med = Mediator(Settings(), ROOT)
        image = np.zeros((900, 1600, 3), dtype=np.uint8)
        cx, cy = 800, 300
        cv2.rectangle(image, (cx - 80, cy - 80), (cx + 80, cy + 80), (0, 140, 230), 8)
        scored = med._card_rarity_score(Frame(image), cx, cy, "treasure")
        self.assertIsNotNone(scored)
        self.assertEqual(scored[1], "orange")

    # ---------- P0-3：面板锚点双帧确认 + 联合分类 + 自然面板 OCR（215302） ----------

    def test_natural_panel_requires_two_same_anchor_frames(self) -> None:
        # P0-3：自然面板进入需同类型锚点连续 2 帧（单帧 0.742/0.799 贴阈值不得
        # 直接进入面板处理）；第 1 帧未确认 → 零输入等待。
        med = Mediator(Settings(), ROOT)
        fr = frame()
        anchor = MatchResult("card_hide", 0.799, 758, 574, 10, 10, 758, 574)
        with patch.object(med, "_find_reward_choice", return_value=None):
            self.assertIs(med._tick_panel_fsm(fr, anchor, time.time()), LoopAction.Continue)
            self.assertIs(med._panel_state, PanelState.CLOSED)
            # 同类型锚点第 2 帧 → 确认进入 ACTIVE
            self.assertIs(med._tick_panel_fsm(fr, anchor, time.time() + 1.0), LoopAction.Continue)
            self.assertIs(med._panel_state, PanelState.ACTIVE)

    def test_natural_panel_anchor_type_change_resets_confirmation(self) -> None:
        # P0-3：锚点类型在相邻帧间漂移（215302：card_hide 0.799 → bond_refresh_btn
        # 0.742 交替）→ 候选重置，绝不单帧误入面板处理。
        med = Mediator(Settings(), ROOT)
        fr = frame()
        with patch.object(med, "_find_reward_choice", return_value=None):
            for name, score in (
                ("card_hide", 0.799),
                ("bond_refresh_btn", 0.742),
                ("card_hide", 0.799),   # 类型变化后重新起计
            ):
                hit = MatchResult(name, score, 758, 574, 10, 10, 758, 574)
                self.assertIs(med._tick_panel_fsm(fr, hit, time.time()), LoopAction.Continue)
                self.assertIs(med._panel_state, PanelState.CLOSED)
            # 同类型第 2 帧 → 才确认
            hit = MatchResult("card_hide", 0.801, 758, 574, 10, 10, 758, 574)
            self.assertIs(med._tick_panel_fsm(fr, hit, time.time()), LoopAction.Continue)
            self.assertIs(med._panel_state, PanelState.ACTIVE)

    def test_natural_panel_high_score_anchor_enters_single_frame(self) -> None:
        # P0-3：anchor score ≥0.85 单帧即可进入（高置信证据不等第二帧）。
        med = Mediator(Settings(), ROOT)
        fr = frame()
        anchor = MatchResult("card_hide", 0.88, 758, 574, 10, 10, 758, 574)
        with patch.object(med, "_find_reward_choice", return_value=None):
            self.assertIs(med._tick_panel_fsm(fr, anchor, time.time()), LoopAction.Continue)
        self.assertIs(med._panel_state, PanelState.ACTIVE)

    def test_natural_bond_panel_invokes_ocr_slots(self) -> None:
        # P0-3：自然面板（非我们打开）必须走 _ocr_panel_slots；硬白名单勾选后
        # 才授权点击（A3），未勾选则 WAIT/关闭而非品质色乱点。
        med = Mediator(Settings(ocr_mode="live", cards=["祝福"]), ROOT)
        anchor = MatchResult("card_hide", 0.85, 758, 574, 10, 10, 758, 574)
        slots = [
            {"index": 0, "name": "祝福", "confidence": 0.99, "raw_text": "祝福(2/3)"},
            {"index": 1, "name": "法术", "confidence": 0.99, "raw_text": "法术(0/3)"},
            {"index": 2, "name": "体术", "confidence": 0.99, "raw_text": "体术(1/4)"},
        ]
        with patch.object(med, "_ocr_panel_slots", return_value=slots) as ocr, \
                patch.object(med, "act_click", return_value=True) as click:
            self.assertIs(med._tick_panel_fsm(frame(), anchor, time.time()), LoopAction.Continue)
        ocr.assert_called()
        click.assert_called_once()
        self.assertEqual(click.call_args.args[1], "bond选择")

    def test_215302_panel_closes_via_card_hide_not_unknown_timeout(self) -> None:
        # R8-REVIEW P0-3 补修：215302 面板 bond_hide 0.39 miss + bond_refresh 0.742
        # + card_hide 0.85 → joint bond 失败但 card_hide 高置信命中 → kind 映射 bond
        # → live OCR 无可靠名 → 走 card_hide 安全关闭，不再零输入 10s unknown timeout。
        med = Mediator(Settings(ocr_mode="live"), ROOT)
        fr = frame()
        anchor = MatchResult("bond_refresh_btn", 0.742, 795, 544, 10, 10, 795, 544)
        hide = MatchResult("card_hide", 0.85, 758, 574, 10, 10, 758, 574)

        def fake_find(_frame, names, **_kwargs):
            if "card_hide" in names:
                return hide
            if "bond_refresh_btn" in names:
                return anchor
            return None

        with patch.object(med, "find", side_effect=fake_find), \
                patch.object(med, "_ocr_reward_choice", return_value=None), \
                patch.object(med, "act_click", return_value=True) as click:
            # 第 1 帧：弱锚点（<0.85）仅建立候选，零输入
            self.assertIs(med._tick_panel_fsm(fr, anchor, time.time()), LoopAction.Continue)
            self.assertIs(med._panel_state, PanelState.CLOSED)
            # 第 2 帧：同类型确认 → ACTIVE → 分类 bond → OCR 无命中 → card_hide 关闭
            self.assertIs(med._tick_panel_fsm(fr, anchor, time.time() + 1.0), LoopAction.Continue)
        self.assertIs(med._panel_state, PanelState.WAIT_MUTATION)
        click.assert_called_once()
        self.assertEqual(click.call_args.args[1], "bond选择")
        self.assertEqual(click.call_args.args[0].name, "card_hide")
        # 10s unknown timeout 不触发：_selection_unknown_since 从未连续累积
        self.assertIsNone(med._selection_unknown_since)

    def test_natural_classified_panel_closes_via_card_hide_in_fsm(self) -> None:
        # R8-REVIEW P0-3 补修 #2：_tick_panel_fsm ACTIVE 无候选时，自然面板
        # （非我们打开）分类明确（bond/card）且 card_hide ≥ match_threshold 命中，
        # 授权安全关闭（CloseNaturalPanel + WAIT_MUTATION 后置确认），有界非盲点。
        med = Mediator(Settings(), ROOT)
        fr = frame()
        anchor = MatchResult("card_hide", 0.85, 758, 574, 10, 10, 758, 574)
        med._enter_panel_episode(fr, anchor, "card", opened=False)
        with patch.object(med, "_find_reward_choice", return_value=None), \
                patch.object(med, "find", return_value=anchor), \
                patch.object(med, "act_click", return_value=True) as click:
            self.assertIs(med._tick_panel_fsm(fr, anchor, time.time()), LoopAction.Continue)
        self.assertIs(med._panel_state, PanelState.WAIT_MUTATION)
        click.assert_called_once()
        self.assertEqual(click.call_args.args[1], "CloseNaturalPanel")

    # ---------- P0-4：205044 真实失败弹窗帧回归（r2_fail_visible/r2_pre_fail 素材） ----------

    @staticmethod
    def _load_fixture(name: str) -> np.ndarray | None:
        """读 fixtures/recovery 下的真实失败页帧（仓库路径含非 ASCII，须 imdecode）。"""
        p = ROOT / "fixtures" / "recovery" / name
        if not p.is_file():
            return None
        return cv2.imdecode(np.frombuffer(p.read_bytes(), np.uint8), cv2.IMREAD_COLOR)

    def test_real_failure_modal_frames_drive_recovery_chain(self) -> None:
        # P0-4：真实失败结算页（红【退出游戏】+绿【继续游戏】）帧上
        # _find_failure_exit_button 命中 → 恢复链点击后置确认推进。
        med = Mediator(Settings(), ROOT)
        med.set_phase(Phase.MAIN_LINE, "real fail fixtures")
        med._begin_recovery(RecoveryKind.FAIL)
        for name in ("fail_visible_01.jpg", "fail_visible_30.jpg", "fail_visible_111.jpg"):
            img = self._load_fixture(name)
            self.assertIsNotNone(img, f"missing fixture {name}")
            fr = Frame(bgr=img, left=0, top=0, window_title="英雄三国KK", hwnd=10001)
            with patch.object(med, "act_click", return_value=True):
                self.assertIs(med._tick_recovery(fr), LoopAction.Continue)
            self.assertTrue(med._recovery_state.waiting_confirm, name)
            self.assertTrue(med._recovery_state.direct_exit, name)
        # 失败页消失（点击退出后的画面）：恢复链推进到 PREPARE 回房验证
        with patch.object(med, "find_scene", return_value=None):
            self.assertIs(med._tick_recovery(frame()), LoopAction.Continue)
        self.assertIs(med.phase, Phase.PREPARE)
        self.assertTrue(med._awaiting_room_return)
        self.assertIs(med._round_outcome, RoundOutcome.FAILURE)

    def test_real_pre_fail_frame_has_no_failure_exit(self) -> None:
        # P0-4 负向：失败页出现前的战斗帧（r2_pre_fail）无 fail 场景锚点 →
        # 红绿按钮检测必须返回 None（不误点）。
        med = Mediator(Settings(), ROOT)
        img = self._load_fixture("pre_fail_20.jpg")
        self.assertIsNotNone(img)
        fr = Frame(bgr=img, left=0, top=0, window_title="英雄三国KK", hwnd=10001)
        self.assertIsNone(med.find_scene(fr, "fail"))
        self.assertIsNone(med._find_failure_exit_button(fr))


if __name__ == "__main__":
    unittest.main()
