import hashlib
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.choice_policy import PolicyAction, PolicySettings, SlotCandidate
from shuabao.loop_action import LoopAction
from shuabao.mediator import ChallengeState, Mediator, PanelState, Phase
from shuabao.merchant_scanner import MERCHANT_STRIP_ROI, MerchantScanner, MerchantSlotItem
from shuabao.policy.merchant_fsm import MerchantFSM, MerchantPhase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult


def hit(name: str, x: int = 100, y: int = 100) -> MatchResult:
    return MatchResult(name, 0.95, x, y, 30, 30, x, y)


class L1CycleRecheckMerchantTests(unittest.TestCase):
    def setUp(self):
        s = Settings()
        s.merchant_enabled = True
        self.med = Mediator(s, ROOT)
        # Merchant spend tests below exercise stock/FSM decisions.  The live
        # HUD reader has its own focused tests; keep these legacy cases from
        # accidentally treating a synthetic black frame as a spending grant.
        self.med._merchant_kill_balance = lambda _frame: 10_000
        self.frame = Frame(
            np.zeros((900, 1600, 3), dtype=np.uint8),
            window_title="game",
            hwnd=1,
        )

    def test_panel_cycle_advances_only_after_an_empty_owned_episode(self):
        self.med._l1_cycle_step = "bond"
        self.med._panel_kind = "bond"
        self.med._l1_cycle_owned_panel = True
        self.med._l1_cycle_selected = True
        self.med._finish_panel_episode()
        self.assertEqual(self.med._l1_cycle_step, "bond")

        self.med._panel_kind = "bond"
        self.med._l1_cycle_owned_panel = True
        self.med._l1_cycle_selected = False
        self.med._finish_panel_episode()
        self.assertEqual(self.med._l1_cycle_step, "skill")

    def test_hitch_round_cycles_merchant_treasure_pickup_public_bag(self):
        """蹭车环整局滚动，不再停在 hitch_idle。

        停车位存在时公共背包只有一次机会，而队伍资产是整局陆续掉的：录像
        背包.mp4 里公共格 (0,0)→(0,1)→(0,2) 是分几次填满的。
        """
        med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
        med.set_phase(Phase.MAIN_LINE, "live hitch round")
        self.assertEqual(med._l1_cycle_step, "merchant")

        seen = []
        for _ in range(8):
            med._advance_l1_cycle()
            seen.append(med._l1_cycle_step)
        self.assertEqual(
            seen,
            ["treasure", "pickup", "public_bag", "merchant"] * 2,
        )
        self.assertNotIn("bond", seen, "蹭车不拿羁绊：那是发育自己")
        self.assertNotIn("skill", seen, "蹭车不拿技能：那是发育自己")
        self.assertNotIn("evolve", seen, "蹭车不点进化")
        self.assertNotIn("equipment", seen, "蹭车不升级自己的装备")

    def test_legacy_hitch_idle_state_rejoins_the_ring(self):
        med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
        med.set_phase(Phase.MAIN_LINE, "live hitch round")
        med._l1_cycle_step = "hitch_idle"
        med._advance_l1_cycle()
        self.assertEqual(med._l1_cycle_step, "merchant")

    def test_hitch_opens_treasure_but_keeps_bond_passive(self):
        med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
        med._l1_cycle_step = "treasure"
        with patch.object(med, "_selection_anchor", return_value=None), \
                patch.object(med, "_bond_base_progress_pending", return_value=True), \
                patch.object(med, "act_click", return_value=True) as click:
            self.assertIs(med._maybe_open_choice_panel(self.frame), LoopAction.Continue)
        self.assertEqual(click.call_args.args[1], "OpenTreasurePanel")

        passive = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
        passive._l1_cycle_step = "bond"
        with patch.object(passive, "_selection_anchor", return_value=None), \
                patch.object(passive, "act_click", return_value=True) as click2:
            self.assertIsNone(passive._maybe_open_choice_panel(self.frame))
        click2.assert_not_called()

    def test_hitch_treasure_ocr_selects_only_green_named_talisman(self):
        med = Mediator(Settings(mode_id="lobby_hitch", ocr_mode="live"), ROOT)
        med._panel_opened_by_us = "treasure"
        med._panel_kind = "treasure"
        med._l1_cycle_step = "treasure"
        med._l1_cycle_owned_panel = True
        slots = (
            SlotCandidate(index=0, name="卡牌大师", rarity="orange", confidence=0.99),
            SlotCandidate(index=1, name="恢复神符", rarity="green", confidence=0.90),
        )
        selected = hit("selected", 800, 400)
        with patch.object(med, "_ocr_panel_slots", return_value=[{"index": 0}]), \
                patch.object(med, "_slots_to_candidates", return_value=slots), \
                patch.object(med, "_extract_live_set_progress", return_value=None), \
                patch.object(med, "_bond_bar_occupancy", return_value=None), \
                patch.object(med, "_panel_has_giveup", return_value=True), \
                patch.object(med, "_panel_can_refresh", return_value=True), \
                patch.object(med, "_policy_decision_to_hit", return_value=("treasure", selected)) as mapped:
            self.assertIsNone(med._ocr_reward_choice(self.frame, "treasure"))
            self.assertIs(med._ocr_reward_choice(self.frame, "treasure"), selected)

        decision = mapped.call_args.args[2]
        self.assertIs(decision.action, PolicyAction.SELECT_SLOT)
        self.assertEqual(decision.index, 1)

    def test_hitch_confirmed_pill_purchase_advances_to_treasure(self):
        med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
        med._l1_cycle_step = "merchant"
        med._merchant_fsm = MerchantFSM(
            phase=MerchantPhase.VERIFYING,
            fingerprint="old",
            purchases=1,
            pending_fingerprint="old",
            deadline=time.time() + 5,
        )
        with patch.object(med, "_black_merchant_present", return_value=True), \
                patch.object(med, "_black_merchant_cards_present", return_value=False), \
                patch.object(med, "_merchant_refresh_available", return_value=False), \
                patch.object(med, "_merchant_fingerprint", return_value="new"):
            self.assertIs(med._maybe_black_merchant(self.frame), LoopAction.Continue)
        self.assertEqual(med._l1_cycle_step, "treasure")

    def test_hitch_auto_task_retry_exhaustion_skips_without_stopping_round(self):
        med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
        med._auto_task_attempts = 3
        toggle = hit("auto_task_toggle", 1450, 530)
        with patch.object(med, "_auto_task_state", return_value=("OFF", toggle)), \
                patch.object(med, "_find_auto_task_toggle", return_value=toggle), \
                patch.object(med, "act_click") as click:
            self.assertIsNone(med._ensure_auto_task_enabled(self.frame))
        self.assertTrue(med._auto_task_done)
        self.assertFalse(med.stop_signal.is_set())
        click.assert_not_called()

    def test_hitch_challenge_retry_exhaustion_skips_all_without_stopping_round(self):
        med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
        keys = tuple(med._challenge_states)
        med._challenge_attempts = {key: 3 for key in keys}
        with patch.object(med, "_find_challenge_button", return_value=None), \
                patch.object(med, "act_right_click") as right_click:
            self.assertIsNone(med._ensure_challenge_buttons(self.frame))
        self.assertEqual(med._challenge_done, set(keys))
        self.assertFalse(med.stop_signal.is_set())
        right_click.assert_not_called()

    def test_hitch_pressure_gate_does_not_expire_with_round_time(self):
        med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
        med._main_line_started_at = 100.0
        med._main_line_since = 129.0
        pressure = hit("yalizhuanyi", 1200, 700)
        with patch.object(med, "_is_in_game_hud", return_value=True) as hud, \
                patch.object(med, "_post_game_state", return_value=None), \
                patch.object(med, "find", return_value=pressure) as find, \
                patch.object(med, "act_click", return_value=True) as click:
            self.assertIs(
                med._maybe_click_hitch_pressure_transfer(self.frame, 130.0),
                LoopAction.Continue,
            )
        self.assertTrue(hud.called)
        self.assertTrue(find.called)
        click.assert_called_once_with(pressure, "HitchPressureTransfer")
        self.assertEqual(getattr(med, "_hitch_pressure_click_at", None), 130.0)
        self.assertFalse(getattr(med, "_hitch_pressure_transferred", False))
        self.assertFalse(getattr(med, "_hitch_pressure_core_failed", False))

    def test_hitch_non_pill_stock_without_refresh_yields_to_treasure(self):
        med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
        with patch.object(med, "_black_merchant_present", return_value=True), \
                patch.object(med, "_black_merchant_cards_present", return_value=False), \
                patch.object(med, "_merchant_refresh_available", return_value=False), \
                patch.object(med, "find", side_effect=[None, hit("merchant_wood")]), \
                patch.object(med, "_in_merchant_strip", return_value=True), \
                patch.object(med, "_merchant_slot_index", return_value=1):
            self.assertIsNone(med._maybe_black_merchant(self.frame))

    def test_background_cycle_skips_range_pickup_until_the_item_bar_overflows(self):
        self.assertEqual(
            self.med._L1_CYCLE_ORDER,
            # 20260822：evolve 前置于 equipment（装备词缀弹窗异步渲染防双模态冲突）。
            ("bond", "skill", "bond", "skill", "treasure", "evolve", "equipment", "pickup", "merchant", "artifact"),
        )

        self.med._l1_cycle_step = "pickup"
        self.med._auto_task_done = True
        self.med._main_line_started_at = 1.0
        with patch.object(self.med, "_post_game_state", return_value=None), \
                patch.object(self.med, "find", return_value=None), \
                patch.object(self.med, "_find_equipment_affix_choice", return_value=None), \
                patch.object(self.med, "_selection_anchor", return_value=None), \
                patch.object(self.med, "_ensure_auto_task_enabled", return_value=None), \
                patch.object(self.med, "_ensure_challenge_buttons", return_value=None), \
                patch.object(self.med, "_find_stage_page", return_value=False), \
                patch.object(self.med, "_handle_self_opened_compact_panel", return_value=None), \
                patch.object(self.med, "_maybe_open_choice_panel", return_value=None), \
                patch.object(self.med, "_maybe_ensure_hero_panel_focus", return_value=None), \
                patch.object(self.med, "act_key", return_value=True) as key:
            self.assertIs(self.med._tick_main_line(self.frame), LoopAction.Continue)
        key.assert_not_called()
        self.assertEqual(self.med._l1_cycle_step, "merchant")

    def test_range_pickup_runs_when_all_movable_item_slots_are_full(self):
        self.med._l1_cycle_step = "pickup"
        self.med._auto_task_done = True
        self.med._main_line_started_at = 1.0
        with patch.object(self.med, "_post_game_state", return_value=None), \
                patch.object(self.med, "find", return_value=None), \
                patch.object(self.med, "_find_equipment_affix_choice", return_value=None), \
                patch.object(self.med, "_selection_anchor", return_value=None), \
                patch.object(self.med, "_ensure_auto_task_enabled", return_value=None), \
                patch.object(self.med, "_ensure_challenge_buttons", return_value=None), \
                patch.object(self.med, "_find_stage_page", return_value=False), \
                patch.object(self.med, "_handle_self_opened_compact_panel", return_value=None), \
                patch.object(self.med, "_maybe_open_choice_panel", return_value=None), \
                patch.object(self.med, "_maybe_ensure_hero_panel_focus", return_value=None), \
                patch.object(self.med, "_hud_item_bar_overflowed", return_value=True), \
                patch.object(self.med, "_pickup_bag_has_space", return_value=True), \
                patch.object(self.med, "act_key", return_value=True) as key:
            self.assertIs(self.med._tick_main_line(self.frame), LoopAction.Continue)
        key.assert_called_once_with("z", "Pickup-Z")
        self.assertEqual(self.med._l1_cycle_step, "merchant")

    def test_skill_episode_cap_keeps_opening_g_until_empty(self):
        self.med._l1_cycle_step = "skill"
        self.med._panel_episode_count["skill"] = 5
        with patch.object(self.med, "act_click", return_value=True) as click:
            result = self.med._maybe_open_choice_panel(self.frame, anchor=None)
        self.assertEqual(result, LoopAction.Continue)
        self.assertEqual(self.med._l1_cycle_step, "skill")
        click.assert_called_once()

    def test_main_line_entry_resets_auto_task_recheck_deadline(self):
        self.med._auto_task_recheck_at = time.time() + 1000
        self.med.set_phase(Phase.MAIN_LINE, "new game")
        self.assertEqual(self.med._auto_task_recheck_at, 0.0)

    def test_periodic_auto_task_off_starts_fresh_repair_episode(self):
        toggle = hit("auto_task_toggle", 1450, 530)
        self.med._auto_task_done = True
        self.med._auto_task_recheck_at = time.time() - 1.0
        with patch.object(
            self.med,
            "_auto_task_state_detail",
            return_value=("OFF", toggle, 0.1, 0.95),
        ), patch.object(
            self.med, "_auto_task_state", return_value=("OFF", toggle)
        ), patch.object(
            self.med, "_find_auto_task_toggle", return_value=toggle
        ), patch.object(
            self.med, "act_click", return_value=True
        ) as click:
            result = self.med._ensure_auto_task_enabled(self.frame)
        self.assertEqual(result, LoopAction.Continue)
        self.assertFalse(self.med._auto_task_done)
        self.assertEqual(self.med._auto_task_attempts, 1)
        self.assertIsNotNone(self.med._auto_task_pending_since)
        click.assert_called_once()

    def test_periodic_challenge_off_rearms_only_that_toggle(self):
        keys = (
            "coin_challenge",
            "wood_challenge",
            "experience_challenge",
            "treasure_challenge",
        )
        self.med._challenge_done.update(keys)
        future = time.time() + 1000
        self.med._challenge_recheck_at = {key: future for key in keys}
        self.med._challenge_recheck_at["coin_challenge"] = time.time() - 1.0
        label = hit("coin_challenge", 150, 650)
        click_hit = hit("coin_challenge", 150, 650)
        with patch.object(
            self.med, "_find_challenge_button", return_value=(label, click_hit)
        ), patch.object(
            self.med, "_resolve_challenge_state", return_value=ChallengeState.OFF
        ), patch.object(
            self.med, "_challenge_green_count", return_value=0
        ), patch.object(
            self.med, "act_right_click", return_value=True
        ) as right_click:
            result = self.med._ensure_challenge_buttons(self.frame)
        self.assertEqual(result, LoopAction.Continue)
        self.assertNotIn("coin_challenge", self.med._challenge_done)
        self.assertEqual(self.med._challenge_attempts["coin_challenge"], 1)
        self.assertIsNotNone(self.med._challenge_pending_since["coin_challenge"])
        right_click.assert_called_once()

    def test_real_strip_fixture_is_a_merchant_anchor(self):
        path = ROOT / "fixtures" / "replay" / "black_merchant_card_strip.png"
        strip = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        canvas = np.zeros((900, 1600, 3), dtype=np.uint8)
        canvas[603 : 603 + strip.shape[0], 1120 : 1120 + strip.shape[1]] = strip
        frame = Frame(canvas, window_title="game", hwnd=1)
        self.assertTrue(self.med._black_merchant_present(frame))
        self.assertTrue(self.med._merchant_refresh_available(frame))
        refresh = self.med._merchant_refresh_hit(frame)
        self.assertGreaterEqual(refresh.x, 1120)
        self.assertLessEqual(refresh.x, 1470)
        self.assertGreaterEqual(refresh.y, 603)
        self.assertLessEqual(refresh.y, 691)
        wood = self.med.find(
            frame,
            ["merchant_wood"],
            threshold=0.72,
            scales=(0.75, 0.9, 1.0, 1.1, 1.25),
            roi=(0.70, 0.67, 0.90, 0.79),
        )
        self.assertIsNotNone(wood)
        self.assertEqual(wood.name, "merchant_wood")

    def test_merchant_fingerprint_uses_slot_identity_not_whole_strip_pixels(self):
        x0, y0, x1, y1 = (
            int(1600 * MERCHANT_STRIP_ROI[0]),
            int(900 * MERCHANT_STRIP_ROI[1]),
            int(1600 * MERCHANT_STRIP_ROI[2]),
            int(900 * MERCHANT_STRIP_ROI[3]),
        )
        canvas = np.zeros((900, 1600, 3), dtype=np.uint8)
        slot_w = (x1 - x0) // 5
        for index in range(5):
            sx0 = x0 + index * slot_w + 6
            sx1 = x0 + (index + 1) * slot_w - 6
            canvas[y0 + 4 : y1 - 24, sx0:sx1] = (30 + index * 12, 90, 170 - index * 8)
        pill = MerchantSlotItem(2, (0.78, 0.72), "devour_pill", "danGif")
        roi = canvas[y0:y1, x0:x1]
        baseline = MerchantScanner.compute_merchant_fingerprint(roi, [pill])
        jitter = canvas.copy()
        rng = np.random.RandomState(7)
        noise = rng.randint(-5, 6, jitter[y0:y1, x0:x1].shape, dtype=np.int16)
        jitter[y0:y1, x0:x1] = np.clip(
            jitter[y0:y1, x0:x1].astype(np.int16) + noise, 0, 255
        ).astype(np.uint8)
        jittered_roi = jitter[y0:y1, x0:x1]
        self.assertNotEqual(hashlib.md5(roi.tobytes()).digest(), hashlib.md5(jittered_roi.tobytes()).digest())
        self.assertEqual(
            baseline,
            MerchantScanner.compute_merchant_fingerprint(jittered_roi, [pill]),
        )
        empty = np.zeros_like(roi)
        self.assertNotEqual(
            baseline,
            MerchantScanner.compute_merchant_fingerprint(empty, [pill]),
        )

    def test_merchant_absent_is_zero_input(self):
        self.med._merchant_next_at = 0.0
        with patch.object(self.med, "_black_merchant_present", return_value=False) as present, \
                patch.object(self.med, "find", return_value=None) as find, \
                patch.object(self.med, "act_click", return_value=True) as click:
            result = self.med._maybe_black_merchant(self.frame)
        self.assertIsNone(result)
        present.assert_called()
        find.assert_not_called()
        click.assert_not_called()

    def test_policy_settings_cached_no_per_tick_disk_read(self):
        """_policy_settings 是缓存 getter：绝不每 panel tick 读 choice_policy.json。"""
        med = self.med
        first = med._policy_settings()
        with patch("shuabao.mediator.json.loads",
                   side_effect=AssertionError("per-tick disk read")), \
                patch.object(Path, "read_text",
                             side_effect=AssertionError("per-tick disk read")):
            second = med._policy_settings()
        self.assertIs(first, second)
        self.assertIsInstance(first, PolicySettings)

    def test_policy_settings_consumes_shared_contract(self):
        """消费 choice_policy.assemble_policy_settings 契约字段（严格档焦点系语义）。"""
        ps = self.med._policy_settings()
        # 默认配置 2 个技能（jq/pg）→ 焦点系非空（严格白名单，无模式字段）。
        self.assertIsInstance(ps.skill_focus_families, tuple)
        self.assertGreaterEqual(len(ps.skill_focus_families), 1)
        self.assertIsInstance(ps.skill_archive_levels, tuple)
        self.assertIsInstance(ps.treasure_must_take, tuple)
        self.assertIsInstance(ps.habit_name_scores, tuple)

    def test_settings_challenge_recheck_interval_default_and_clamp(self):
        s = Settings()
        self.assertEqual(s.challenge_recheck_interval_s, 30.0)
        self.assertEqual(
            Settings._from_dict({"challenge_recheck_interval_s": 999}).challenge_recheck_interval_s,
            300.0,
        )
        self.assertEqual(
            Settings._from_dict({"challenge_recheck_interval_s": 1}).challenge_recheck_interval_s,
            5.0,
        )
        self.assertEqual(
            Settings._from_dict({"challenge_recheck_interval_s": "bad"}).challenge_recheck_interval_s,
            30.0,
        )

    def test_settings_skill_archive_levels_normalize_and_round_trip(self):
        """存档等级是真实 Settings 字段：默认空映射、值域清洗、save/load 往返。"""
        s = Settings()
        self.assertEqual(s.skill_archive_levels, {})
        norm = Settings._from_dict(
            {"skill_archive_levels": {"asj": 47, "tl": -5, "hq": 0, "bad": "x", "big": 999}}
        )
        self.assertEqual(norm.skill_archive_levels, {"asj": 47, "big": 50})
        s.skill_archive_levels = {"asj": 47, "jq": 13}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            s.save(path)
            loaded = Settings.load(path)
        self.assertEqual({"asj": 47, "jq": 13}, loaded.skill_archive_levels)

    def test_skill_card_click_stages_canonical_card_only(self):
        """技能选卡点击成功 → 暂存一个规范卡名；未确认前不算已学。"""
        med = self.med
        med._panel_state = PanelState.ACTIVE
        med._panel_kind = "skill"
        card_hit = MatchResult("jq", 0.95, 500, 300, 40, 40, 500, 300)
        with patch.object(med, "_find_reward_choice", return_value=("技能", card_hit)), \
                patch.object(med, "act_click", return_value=True) as click:
            result = med._tick_panel_fsm(self.frame, hit("card_hide", 500, 500), time.time())
        self.assertEqual(result, LoopAction.Continue)
        click.assert_called_once()
        self.assertEqual(med._panel_state, PanelState.WAIT_MUTATION)
        self.assertEqual(med._skill_cards_pending, ["剑气"])
        self.assertEqual(med._skill_cards_owned, [])

    def test_skill_refresh_click_does_not_stage_ownership(self):
        """刷新/关闭类点击绝不暂存为技能卡归属。"""
        med = self.med
        med._panel_state = PanelState.ACTIVE
        med._panel_kind = "skill"
        refresh_hit = MatchResult("skill_refresh_btn", 0.95, 500, 300, 40, 40, 500, 300)
        with patch.object(med, "_find_reward_choice", return_value=("技能刷新", refresh_hit)), \
                patch.object(med, "act_click", return_value=True):
            result = med._tick_panel_fsm(self.frame, hit("card_hide", 500, 500), time.time())
        self.assertEqual(result, LoopAction.Continue)
        self.assertEqual(med._skill_cards_pending, [])

    def test_skill_card_ownership_committed_on_mutation_confirm(self):
        """WAIT_MUTATION 观察到内容变化 → 暂存卡确认学得。"""
        med = self.med
        med._panel_state = PanelState.WAIT_MUTATION
        med._panel_kind = "skill"
        baseline = np.zeros((900, 1600, 3), dtype=np.uint8)
        med._panel_mutation_baseline = med._panel_roi_region(
            Frame(baseline, window_title="game", hwnd=1)
        )
        changed = baseline.copy()
        changed[300:500, 800:1000] = 255  # 200x200 白块 → 40000 变化像素 ≥ 2000
        frame = Frame(changed, window_title="game", hwnd=1)
        med._skill_cards_pending.append("奥数箭")
        result = med._tick_panel_fsm(frame, hit("card_hide", 500, 500), time.time())
        self.assertEqual(result, LoopAction.Continue)
        self.assertEqual(med._panel_state, PanelState.ACTIVE)
        self.assertIn("奥数箭", med._skill_cards_owned)
        self.assertEqual(med._skill_cards_pending, [])

    def test_skill_card_ownership_committed_on_panel_disappearance(self):
        """WAIT_MUTATION 面板消失 → 已点技能卡确认学得。"""
        med = self.med
        med._panel_state = PanelState.WAIT_MUTATION
        med._panel_kind = "skill"
        med._skill_cards_pending.append("剑气")
        result = med._tick_panel_fsm(self.frame, None, time.time())
        self.assertEqual(result, LoopAction.Continue)
        self.assertIn("剑气", med._skill_cards_owned)
        self.assertEqual(med._skill_cards_pending, [])

    def test_skill_card_ownership_preserves_duplicate_learns(self):
        """同一升级卡学两次必须保留两条记录，供 x2 前置计数。"""
        med = self.med
        med._skill_cards_pending.append("箭矢增幅")
        med._commit_pending_skill_cards()
        med._skill_cards_pending.append("箭矢增幅")
        med._commit_pending_skill_cards()
        self.assertEqual(
            med._confirmed_skill_cards(),
            ("箭矢增幅", "箭矢增幅"),
        )

    def test_unconfirmed_click_timeout_clears_pending_without_commit(self):
        """确认窗超时（无 mutation、面板仍在）→ 只清暂存，绝不记为已学。"""
        med = self.med
        med._panel_state = PanelState.WAIT_MUTATION
        med._panel_kind = "skill"
        med._panel_mutation_baseline = None
        med._panel_last_input_at = time.time() - 30.0  # 超过确认窗上限 15s
        med._skill_cards_pending.append("寒冰箭")
        result = med._tick_panel_fsm(self.frame, hit("card_hide", 500, 500), time.time())
        self.assertEqual(result, LoopAction.Continue)
        self.assertEqual(med._panel_state, PanelState.ACTIVE)
        self.assertEqual(med._skill_cards_pending, [])
        self.assertNotIn("寒冰箭", med._skill_cards_owned)

    def test_commit_records_verified_grant_on_learn_card(self):
        """确认学得时，仅通过 verified skill_catalog 助手记录赠卡。"""
        med = self.med
        med._skill_cards_pending.append("奥数箭")
        with patch("shuabao.mediator.grant_on_learn_card", return_value="寒冰箭"):
            med._commit_pending_skill_cards()
        self.assertIn("奥数箭", med._skill_cards_owned)
        self.assertIn("寒冰箭", med._skill_cards_owned)
        self.assertEqual(med._skill_cards_pending, [])

    def test_round_reset_clears_skill_card_ownership(self):
        """set_phase(MAIN_LINE) 按局重置 pending/owned；owned 传给 PanelCandidates。"""
        med = self.med
        med._skill_cards_pending.append("地震")
        med._skill_cards_owned.append("奥数箭")
        med.set_phase(Phase.MAIN_LINE, "new round")
        self.assertEqual(med._skill_cards_pending, [])
        self.assertEqual(med._skill_cards_owned, [])
        med._skill_cards_owned.append("奥数箭")
        self.assertEqual(med._confirmed_skill_cards(), ("奥数箭",))

    def test_merchant_prefers_pill_then_wood_and_refreshes_when_neither_exists(self):
        self.med.settings.auto_gambling_time = 1
        pill = hit("danGif", 1160, 640)
        wood = hit("woodgift", 1280, 650)

        def find_known(_frame, names, **_kwargs):
            return pill if names == ["danGif"] else wood

        with patch.object(self.med, "_black_merchant_present", return_value=True), patch.object(
            self.med, "_bond_bar_nonempty", return_value=True
        ), patch.object(self.med, "find", side_effect=find_known), patch.object(
            self.med, "act_click", return_value=True
        ) as click:
            self.assertEqual(self.med._maybe_black_merchant(self.frame), LoopAction.Continue)
            result = self.med._maybe_black_merchant(self.frame)
        self.assertEqual(result, LoopAction.Continue)
        self.assertEqual(click.call_args.args[1], "BlackMerchant-swallow_pill")

        self.med._merchant_next_at = 0.0
        self.med._merchant_fsm = MerchantFSM()
        self.med.settings.merchant_enabled = True
        self.med.settings.merchant_max_rerolls = 3
        self.med.settings.auto_gambling = True  # 显式开启自动刷新
        with patch.object(self.med, "_black_merchant_present", return_value=True), patch.object(
            self.med, "_bond_bar_nonempty", return_value=False
        ), patch.object(self.med, "find", return_value=None), patch.object(
            self.med, "_merchant_refresh_available", return_value=True
        ), patch.object(self.med, "act_click", return_value=True) as click:
            self.assertEqual(self.med._maybe_black_merchant(self.frame), LoopAction.Continue)
            result = self.med._maybe_black_merchant(self.frame)
        self.assertEqual(result, LoopAction.Continue)
        self.assertEqual(click.call_args.args[1], "BlackMerchant-refresh")

    def test_unknown_stock_refreshes_even_when_rerolls_setting_is_zero(self):
        """After taking known targets, remaining unknown cards still refresh."""
        self.med.settings.merchant_enabled = True
        self.med.settings.merchant_max_rerolls = 0
        self.med.settings.auto_gambling_time = 0
        self.med._merchant_next_at = 0.0
        with patch.object(self.med, "_black_merchant_present", return_value=True), \
                patch.object(Mediator, "_black_merchant_cards_present", return_value=True), \
                patch.object(self.med, "_merchant_refresh_available", return_value=True), \
                patch.object(self.med, "find", return_value=None), \
                patch.object(self.med, "act_click", return_value=True) as click:
            self.assertEqual(self.med._maybe_black_merchant(self.frame), LoopAction.Continue)
            self.assertEqual(self.med._maybe_black_merchant(self.frame), LoopAction.Continue)

        click.assert_called_once()
        self.assertEqual(click.call_args.args[1], "BlackMerchant-refresh")

    def test_empty_merchant_strip_refreshes_before_scanning_the_same_encounter(self):
        """A refresh-only merchant surface is still one merchant flow."""
        self.med.settings.merchant_enabled = True
        self.med._merchant_next_at = 0.0
        with patch.object(Mediator, "_black_merchant_cards_present", return_value=False), \
                patch.object(Mediator, "_merchant_refresh_available", return_value=True), \
                patch.object(self.med, "find", return_value=None), \
                patch.object(self.med, "act_click", return_value=True) as click:
            self.assertEqual(self.med._maybe_black_merchant(self.frame), LoopAction.Continue)
            self.assertEqual(self.med._maybe_black_merchant(self.frame), LoopAction.Continue)

        click.assert_called_once()
        self.assertEqual(click.call_args.args[1], "BlackMerchant-refresh")

    def test_empty_merchant_keeps_refreshing_when_no_pill_is_visible(self):
        self.med.settings.merchant_enabled = True
        self.med._merchant_next_at = 0.0
        tick = {"value": 0}

        def find_after_refresh(_frame, names, **_kwargs):
            return None

        with patch.object(self.med, "_black_merchant_present", return_value=True), \
                patch.object(Mediator, "_black_merchant_cards_present", side_effect=[False, False, True, True]), \
                patch.object(self.med, "_merchant_refresh_available", side_effect=[True, True, True, True]), \
                patch.object(self.med, "_merchant_fingerprint", side_effect=["empty", "empty", "filled", "filled"]), \
                patch.object(self.med, "find", side_effect=find_after_refresh), \
                patch.object(self.med, "act_click", return_value=True) as click, \
                patch("shuabao.mediator.time.time", side_effect=[100.0, 100.0, 102.0, 102.0]):
            for _ in range(4):
                self.med._maybe_black_merchant(self.frame)
                tick["value"] += 1

        self.assertEqual(
            [call.args[1] for call in click.call_args_list],
            ["BlackMerchant-refresh", "BlackMerchant-refresh"],
        )

    def test_solo_merchant_buys_wood_before_refreshing(self):
        self.med.settings.merchant_enabled = True
        self.med._merchant_next_at = 0.0
        wood = hit("merchant_wood", 1280, 650)

        def find_wood(_frame, names, **_kwargs):
            return wood if names == ["merchant_wood"] else None

        with patch.object(self.med, "_black_merchant_present", return_value=True), \
                patch.object(self.med, "_merchant_refresh_available", return_value=True), \
                patch.object(self.med, "find", side_effect=find_wood), \
                patch.object(self.med, "act_click", return_value=True) as click:
            self.assertEqual(self.med._maybe_black_merchant(self.frame), LoopAction.Continue)
            self.assertEqual(self.med._maybe_black_merchant(self.frame), LoopAction.Continue)

        click.assert_called_once()
        self.assertEqual(click.call_args.args[1], "BlackMerchant-wood")

    def test_merchant_pill_purchase_does_not_use_inventory_bond_gate(self):
        self.med.settings.merchant_enabled = True
        self.med._merchant_next_at = 0.0
        self.med._merchant_fsm = MerchantFSM(phase=MerchantPhase.READY, fingerprint="filled")
        pill = hit("danGif", 1280, 643)

        def find_pill(_frame, names, **_kwargs):
            return pill if names == ["danGif"] else None

        with patch.object(self.med, "_black_merchant_present", return_value=True), \
                patch.object(Mediator, "_black_merchant_cards_present", return_value=True), \
                patch.object(self.med, "_merchant_refresh_available", return_value=False), \
                patch.object(self.med, "_merchant_fingerprint", return_value="filled"), \
                patch.object(self.med, "_bond_bar_nonempty", return_value=False), \
                patch.object(self.med, "find", side_effect=find_pill), \
                patch.object(self.med, "act_click", return_value=True) as click:
            result = self.med._maybe_black_merchant(self.frame)

        self.assertEqual(result, LoopAction.Continue)
        click.assert_called_once()
        self.assertEqual(click.call_args.args[1], "BlackMerchant-swallow_pill")

    def test_merchant_pill_requires_a_live_400_kill_balance(self):
        """A visible pill is not purchase authority while the HUD shows 399."""
        self.med._merchant_next_at = 0.0
        self.med._merchant_fsm = MerchantFSM(phase=MerchantPhase.READY, fingerprint="pill")
        pill = hit("danGif", 1280, 643)
        with patch.object(self.med, "_black_merchant_present", return_value=True), \
                patch.object(Mediator, "_black_merchant_cards_present", return_value=True), \
                patch.object(self.med, "_merchant_refresh_available", return_value=False), \
                patch.object(self.med, "_merchant_fingerprint", return_value="pill"), \
                patch.object(self.med, "_bond_bar_nonempty", return_value=True), \
                patch.object(self.med, "_merchant_kill_balance", return_value=399), \
                patch.object(self.med, "find", side_effect=lambda _f, names, **_k: pill if names == ["danGif"] else None), \
                patch.object(self.med, "act_click") as click:
            result = self.med._maybe_black_merchant(self.frame)

        self.assertIsNone(result)
        click.assert_not_called()
        self.assertGreater(self.med._merchant_budget_retry_at, time.time())

    def test_merchant_refresh_reserves_the_follow_up_pill_budget(self):
        """520 can pay a reroll but cannot pay its expected 400-pill follow-up."""
        self.med._merchant_next_at = 0.0
        self.med._merchant_fsm = MerchantFSM(phase=MerchantPhase.READY, fingerprint="empty")
        with patch.object(self.med, "_black_merchant_present", return_value=True), \
                patch.object(Mediator, "_black_merchant_cards_present", return_value=False), \
                patch.object(self.med, "_merchant_refresh_available", return_value=True), \
                patch.object(self.med, "_merchant_fingerprint", return_value="empty"), \
                patch.object(self.med, "_merchant_kill_balance", return_value=520), \
                patch.object(self.med, "find", return_value=None), \
                patch.object(self.med, "act_click") as click:
            result = self.med._maybe_black_merchant(self.frame)

        self.assertIsNone(result)
        click.assert_not_called()
        self.assertGreater(self.med._merchant_budget_retry_at, time.time())

    def test_merchant_spends_at_the_exact_budget_thresholds(self):
        """400 authorizes a pill; a fresh 750 authorizes a reroll-plus-pill plan."""
        pill = hit("danGif", 1280, 643)
        self.med._merchant_next_at = 0.0
        self.med._merchant_fsm = MerchantFSM(phase=MerchantPhase.READY, fingerprint="pill")
        with patch.object(self.med, "_black_merchant_present", return_value=True), \
                patch.object(Mediator, "_black_merchant_cards_present", return_value=True), \
                patch.object(self.med, "_merchant_refresh_available", return_value=False), \
                patch.object(self.med, "_merchant_fingerprint", return_value="pill"), \
                patch.object(self.med, "_bond_bar_nonempty", return_value=True), \
                patch.object(self.med, "_merchant_kill_balance", return_value=400), \
                patch.object(self.med, "find", side_effect=lambda _f, names, **_k: pill if names == ["danGif"] else None), \
                patch.object(self.med, "act_click", return_value=True) as pill_click:
            self.assertIs(self.med._maybe_black_merchant(self.frame), LoopAction.Continue)
        pill_click.assert_called_once()
        self.assertEqual(pill_click.call_args.args[1], "BlackMerchant-swallow_pill")

        self.med._merchant_next_at = 0.0
        self.med._merchant_fsm = MerchantFSM(phase=MerchantPhase.READY, fingerprint="empty")
        with patch.object(self.med, "_black_merchant_present", return_value=True), \
                patch.object(Mediator, "_black_merchant_cards_present", return_value=False), \
                patch.object(self.med, "_merchant_refresh_available", return_value=True), \
                patch.object(self.med, "_merchant_fingerprint", return_value="empty"), \
                patch.object(self.med, "_merchant_kill_balance", return_value=750), \
                patch.object(self.med, "find", return_value=None), \
                patch.object(self.med, "act_click", return_value=True) as refresh_click:
            self.assertIs(self.med._maybe_black_merchant(self.frame), LoopAction.Continue)
        refresh_click.assert_called_once()
        self.assertEqual(refresh_click.call_args.args[1], "BlackMerchant-refresh")

    def test_merchant_kill_balance_accepts_only_high_confidence_numeric_ocr(self):
        calls = []

        class FakeOcr:
            is_available = True

            def shadow_predict(self, _frame, _panel_id, slot, **_kwargs):
                calls.append(slot)
                return SimpleNamespace(status="ok", raw_text="38", candidates=(), rec_score=0.99)

        med = Mediator(Settings(), ROOT)
        med._ocr_client = FakeOcr()
        self.assertEqual(med._merchant_kill_balance(self.frame), 38)
        # A parsed balance is cached for an unchanged HUD crop, avoiding five
        # OCR requests in the same merchant encounter.
        self.assertEqual(med._merchant_kill_balance(self.frame), 38)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["bbox"], (1340, 10, 1390, 35))

    def test_solo_merchant_buys_explicit_two_or_five_fold_ocr(self):
        self.med.settings.merchant_enabled = True
        self.med._merchant_next_at = 0.0
        calls = []

        class FakeOcr:
            is_available = True

            def shadow_predict(self, _frame, _panel_id, slot, **kwargs):
                calls.append((slot["index"], slot["bbox"], kwargs["fingerprint"]))
                text = "2折" if slot["index"] == 2 else ""
                return SimpleNamespace(
                    status="ok",
                    raw_text=text,
                    candidates=(),
                    rec_score=0.96,
                )

        self.med._ocr_client = FakeOcr()
        with patch.object(self.med, "_black_merchant_present", return_value=True), \
                patch.object(Mediator, "_black_merchant_cards_present", return_value=True), \
                patch.object(self.med, "_merchant_refresh_available", return_value=False), \
                patch.object(self.med, "find", return_value=None), \
                patch.object(self.med, "act_click", return_value=True) as click:
            self.assertEqual(self.med._maybe_black_merchant(self.frame), LoopAction.Continue)
            self.assertEqual(self.med._maybe_black_merchant(self.frame), LoopAction.Continue)

        self.assertEqual([call[0] for call in calls[:5]], [0, 1, 2, 3, 4])
        self.assertEqual(calls[0][1], (1150, 617, 1190, 640))
        self.assertEqual(calls[4][1], (1370, 617, 1410, 640))
        self.assertEqual(len(calls[0][2].rsplit(":", 1)[1]), 32)
        self.assertEqual(click.call_args.args[1], "BlackMerchant-discount")

    def test_merchant_normalizes_only_observed_discount_ocr_aliases(self):
        self.assertEqual(self.med._normalize_merchant_discount("15折"), "5折")
        self.assertEqual(self.med._normalize_merchant_discount("A2"), "2折")
        self.assertEqual(self.med._normalize_merchant_discount("12折"), "2折")
        self.assertEqual(self.med._normalize_merchant_discount("2S"), "2S")

    def test_solo_merchant_wood_match_authorizes_a_slot_click(self):
        self.med.settings.merchant_enabled = True
        self.med._merchant_next_at = 0.0
        # The old equal-width ROI mapping would classify this fifth-slot match
        # as slot 3; use the stable in-game slot center instead.
        wood = MatchResult("merchant_wood", 0.99, 1363, 609, 57, 61, 1520, 711)
        with patch.object(self.med, "_black_merchant_present", return_value=True), \
                patch.object(Mediator, "_black_merchant_cards_present", return_value=False), \
                patch.object(self.med, "_merchant_refresh_available", return_value=False), \
                patch.object(self.med, "find", side_effect=lambda _f, names, **_k: wood if names == ["merchant_wood"] else None), \
                patch.object(self.med, "act_click", return_value=True) as click:
            self.med._maybe_black_merchant(self.frame)
            self.med._maybe_black_merchant(self.frame)

        self.assertEqual(click.call_args.args[1], "BlackMerchant-wood")

    def test_solo_discount_fingerprint_authorizes_a_purchase(self):
        class FakeOcr:
            is_available = True

            def shadow_predict(self, _frame, _panel_id, slot, **_kwargs):
                text = "5折" if slot["index"] == 4 else ""
                return SimpleNamespace(status="ok", raw_text=text, candidates=(), rec_score=0.96)

        fingerprints = []

        def merchant_fingerprint(_frame, slots=None):
            kinds = tuple((item.slot_index, item.item_type) for item in (slots or ()))
            fingerprints.append(kinds)
            return "with_discount" if any(kind == "discount" for _, kind in kinds) else "base"

        self.med._merchant_next_at = 0.0
        self.med._merchant_fsm = MerchantFSM(
            phase=MerchantPhase.READY,
            fingerprint="with_discount",
        )
        self.med._ocr_client = FakeOcr()
        with patch.object(self.med, "_black_merchant_present", return_value=True), \
                patch.object(Mediator, "_black_merchant_cards_present", return_value=True), \
                patch.object(self.med, "_merchant_refresh_available", return_value=False), \
                patch.object(self.med, "_merchant_fingerprint", side_effect=merchant_fingerprint), \
                patch.object(self.med, "find", return_value=None), \
                patch.object(self.med, "act_click", return_value=True) as click:
            self.assertEqual(self.med._maybe_black_merchant(self.frame), LoopAction.Continue)

        self.assertEqual(click.call_args.args[1], "BlackMerchant-discount")
        self.assertTrue(any(kind == "discount" for _, kind in fingerprints[-1]))
        self.assertEqual(self.med._merchant_fsm.pending_fingerprint, "with_discount")

    def test_merchant_uses_only_high_confidence_full_item_templates(self):
        observed = {}

        def record_find(_frame, names, **kwargs):
            observed[tuple(names)] = kwargs["threshold"]
            return None

        with patch.object(self.med, "_black_merchant_present", return_value=True), \
                patch.object(Mediator, "_black_merchant_cards_present", return_value=False), \
                patch.object(self.med, "_merchant_refresh_available", return_value=False), \
                patch.object(self.med, "find", side_effect=record_find):
            self.med._maybe_black_merchant(self.frame)

        self.assertEqual(observed[("danGif",)], 0.90)
        self.assertEqual(observed[("merchant_wood",)], 0.95)
        self.assertNotIn(("merchant_wood", "woodgift"), observed)

    def test_merchant_ignores_wood_outside_strip_and_refreshes(self):
        self.med.settings.merchant_enabled = True
        self.med.settings.merchant_max_rerolls = 3
        self.med._merchant_next_at = 0.0
        fake_wood = hit("merchant_wood", 1413, 711)

        with patch.object(self.med, "_black_merchant_present", return_value=True), patch.object(
            self.med, "_bond_bar_nonempty", return_value=False
        ), patch.object(self.med, "find", return_value=fake_wood), patch.object(
            self.med, "_merchant_refresh_available", return_value=True
        ), patch.object(self.med, "act_click", return_value=True) as click:
            self.assertEqual(self.med._maybe_black_merchant(self.frame), LoopAction.Continue)
            result = self.med._maybe_black_merchant(self.frame)
        self.assertEqual(result, LoopAction.Continue)
        self.assertEqual(click.call_args.args[1], "BlackMerchant-refresh")


class L1RuntimeAccountingTests(unittest.TestCase):
    """Commit3：三面板时间戳初始化 / choice_interval 重开限制 / attempts 记账 /
    trace 帧指纹缓存（Frame 强引用 + is 判同）。
    """

    def setUp(self):
        s = Settings()
        s.merchant_enabled = True
        self.med = Mediator(s, ROOT)
        self.frame = Frame(
            np.zeros((900, 1600, 3), dtype=np.uint8),
            window_title="game",
            hwnd=1,
        )

    # ---- 三面板时间戳：__init__ 初始化 0.0（首次立即允许） ----

    def test_init_initializes_three_panel_timestamps_to_zero(self):
        self.assertEqual(self.med._last_skill_panel, 0.0)
        self.assertEqual(self.med._last_bond_attempt, 0.0)
        self.assertEqual(self.med._last_treasure_attempt, 0.0)

    def test_short_hide_cooldown_blocks_reopen_without_leaving_skill(self):
        self.med._l1_cycle_step = "skill"
        self.med._panel_cooldown_until["skill"] = 203.0
        with patch("shuabao.mediator.time.time", return_value=200.0), \
                patch.object(self.med, "act_click") as click:
            result = self.med._maybe_open_choice_panel(self.frame, anchor=None)
        self.assertIn(result, (LoopAction.Continue, None))
        click.assert_not_called()
        self.assertEqual(self.med._l1_cycle_step, "skill")

    def test_long_cooldown_moves_the_cycle_on_without_reopening(self):
        """Owner 2026-09-15: a long panel cooldown never parks the L1 cycle."""
        self.med._l1_cycle_step = "skill"
        self.med._panel_cooldown_until["skill"] = 250.0
        with patch("shuabao.mediator.time.time", return_value=200.0), \
                patch.object(self.med, "act_click") as click:
            result = self.med._maybe_open_choice_panel(self.frame, anchor=None)
        self.assertIs(result, LoopAction.Continue)
        click.assert_not_called()
        self.assertNotEqual(self.med._l1_cycle_step, "skill")

    def test_choice_interval_first_open_immediately_allowed(self):
        # 首次（时间戳 0.0）：立即允许打开并记录成功时间戳。
        self.med.settings.choice_interval = 120
        self.med._l1_cycle_step = "skill"
        self.assertEqual(self.med._last_skill_panel, 0.0)
        with patch.object(self.med, "act_click", return_value=True) as click:
            result = self.med._maybe_open_choice_panel(self.frame, anchor=None)
        self.assertIs(result, LoopAction.Continue)
        click.assert_called_once()
        self.assertGreater(self.med._last_skill_panel, 0.0)

    def test_choice_interval_rejected_open_does_not_advance_timestamp(self):
        # 打开被拒绝（act_click False）→ 不推进冷却时间戳，下 tick 可重试。
        self.med.settings.choice_interval = 120
        self.med._l1_cycle_step = "skill"
        with patch.object(self.med, "act_click", return_value=False) as click:
            result = self.med._maybe_open_choice_panel(self.frame, anchor=None)
        self.assertIs(result, LoopAction.Continue)
        click.assert_called_once()
        self.assertEqual(self.med._last_skill_panel, 0.0)

    # ---- attempts：成功 SELECT/REFRESH/GIVEUP/CLOSE 才 +1；WAIT/拒绝不加 ----

    def _enter_live_bond(self, med: Mediator, slots: list[dict]) -> MatchResult:
        anchor = MatchResult("card_hide", 0.85, 758, 574, 10, 10, 758, 574)
        with patch.object(med, "_ocr_panel_slots", return_value=slots):
            self.assertIs(
                med._tick_panel_fsm(self.frame, anchor, time.time()),
                LoopAction.Continue,
            )
        return anchor

    def test_successful_select_increments_choice_attempts(self):
        med = Mediator(Settings(ocr_mode="live", cards=["祝福"]), ROOT)
        slots = [
            {"index": 0, "name": "祝福", "confidence": 0.99, "raw_text": "祝福(2/3)"},
        ]
        with patch.object(med, "act_click", return_value=True) as click:
            self._enter_live_bond(med, slots)
        click.assert_called_once()
        self.assertEqual(med._choice_session.attempts, 1)

    def test_wait_does_not_increment_choice_attempts(self):
        med = Mediator(Settings(ocr_mode="live", cards=["祝福"]), ROOT)
        slots = [{"index": 0, "name": None, "confidence": 0.0, "raw_text": ""}]
        with patch.object(med, "act_click", return_value=False) as click:
            self._enter_live_bond(med, slots)
        self.assertEqual(med._choice_session.attempts, 0)

    def test_rejected_click_does_not_increment_choice_attempts(self):
        med = Mediator(Settings(ocr_mode="live", cards=["祝福"]), ROOT)
        slots = [
            {"index": 0, "name": "祝福", "confidence": 0.99, "raw_text": "祝福(2/3)"},
        ]
        with patch.object(med, "act_click", return_value=False) as click:
            self._enter_live_bond(med, slots)
        click.assert_called_once()
        self.assertEqual(med._choice_session.attempts, 0)

    # ---- trace 帧指纹缓存：Frame 强引用 + is 判同（不用 id） ----

    def test_trace_fingerprint_cache_holds_frame_strong_reference(self):
        import gc
        import weakref

        frame = Frame(
            np.zeros((900, 1600, 3), dtype=np.uint8),
            window_title="game",
            hwnd=1,
        )
        self.med._trace_frame_fingerprint(frame)
        ref = weakref.ref(frame)
        del frame
        gc.collect()
        self.assertIsNotNone(ref(), "trace 指纹缓存必须持有 Frame 强引用")
        self.assertIs(self.med._trace_fingerprint_cache[0], ref())

    def test_trace_fingerprint_cache_uses_is_not_id(self):
        frame_a = Frame(
            np.zeros((900, 1600, 3), dtype=np.uint8),
            window_title="game",
            hwnd=1,
        )
        fp_a = self.med._trace_frame_fingerprint(frame_a)
        self.assertIsNotNone(fp_a)
        # 缓存项本体就是 Frame（旧实现缓存 id 整数，assertIs 必然失败）
        self.assertIs(self.med._trace_fingerprint_cache[0], frame_a)
        # 内容相同但对象不同 → 必须重新计算并切换缓存，而非按 id 误命中
        frame_b = Frame(
            np.zeros((900, 1600, 3), dtype=np.uint8),
            window_title="game",
            hwnd=1,
        )
        fp_b = self.med._trace_frame_fingerprint(frame_b)
        self.assertEqual(fp_a, fp_b)
        self.assertIs(self.med._trace_fingerprint_cache[0], frame_b)


if __name__ == "__main__":
    unittest.main()
