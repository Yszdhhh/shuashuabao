import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.choice_policy import PolicySettings
from shuabao.loop_action import LoopAction
from shuabao.mediator import ChallengeState, Mediator, PanelState, Phase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult


def hit(name: str, x: int = 100, y: int = 100) -> MatchResult:
    return MatchResult(name, 0.95, x, y, 30, 30, x, y)


class L1CycleRecheckMerchantTests(unittest.TestCase):
    def setUp(self):
        self.med = Mediator(Settings(), ROOT)
        self.frame = Frame(
            np.zeros((900, 1600, 3), dtype=np.uint8),
            window_title="game",
            hwnd=1,
        )

    def test_panel_cycle_advances_only_after_an_empty_owned_episode(self):
        self.med._l1_cycle_step = "skill"
        self.med._panel_kind = "skill"
        self.med._l1_cycle_owned_panel = True
        self.med._l1_cycle_selected = True
        self.med._finish_panel_episode()
        self.assertEqual(self.med._l1_cycle_step, "skill")

        self.med._panel_kind = "skill"
        self.med._l1_cycle_owned_panel = True
        self.med._l1_cycle_selected = False
        self.med._finish_panel_episode()
        self.assertEqual(self.med._l1_cycle_step, "bond")

    def test_background_cycle_uses_inventory_pickup_merchant_then_artifact(self):
        self.assertEqual(
            self.med._L1_CYCLE_ORDER,
            ("skill", "bond", "treasure", "evolve", "equipment", "pickup", "merchant", "artifact"),
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
                patch.object(self.med, "act_key", return_value=True) as key:
            self.assertIs(self.med._tick_main_line(self.frame), LoopAction.Continue)
        key.assert_called_once_with("z", "Pickup-Z")
        self.assertEqual(self.med._l1_cycle_step, "merchant")

    def test_legacy_five_episode_cap_no_longer_starves_rest_of_game(self):
        self.med._l1_cycle_step = "skill"
        self.med._panel_episode_count["skill"] = 5
        with patch.object(self.med, "act_click") as click:
            result = self.med._maybe_open_choice_panel(self.frame, anchor=None)
        self.assertEqual(result, LoopAction.Continue)
        self.assertEqual(self.med._panel_episode_count["skill"], 0)
        self.assertEqual(self.med._l1_cycle_step, "bond")
        click.assert_not_called()

        self.med._l1_cycle_step = "skill"
        with patch.object(self.med, "act_click", return_value=True) as click:
            result = self.med._maybe_open_choice_panel(self.frame, anchor=None)
        self.assertEqual(result, LoopAction.Continue)
        click.assert_called_once()

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
        wood = self.med.find(
            frame,
            ["merchant_wood", "woodgift"],
            threshold=0.72,
            scales=(0.75, 0.9, 1.0, 1.1, 1.25),
            roi=(0.70, 0.67, 0.90, 0.79),
        )
        self.assertIsNotNone(wood)
        self.assertEqual(wood.name, "merchant_wood")

    def test_merchant_default_zero_auto_gambling_is_zero_input(self):
        """默认 auto_gambling_time=0：_maybe_black_merchant 第一行即零输入返回。

        不做任何 find/click（不进入购买/刷新路径）；结果 falsy。
        """
        self.assertEqual(self.med.settings.auto_gambling_time, 0)
        self.med._merchant_next_at = 0.0
        with patch.object(self.med, "_black_merchant_present") as present, \
                patch.object(self.med, "find", return_value=None) as find, \
                patch.object(self.med, "act_click", return_value=True) as click:
            result = self.med._maybe_black_merchant(self.frame)
        self.assertIsNone(result)
        self.assertFalse(result)
        present.assert_not_called()
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
        self.med.settings.auto_gambling_time = 1  # 显式 opt-in 才进入实验性购买/刷新路径
        pill = hit("danGif", 1160, 640)
        wood = hit("woodgift", 1280, 650)

        def find_known(_frame, names, **_kwargs):
            return pill if names == ["danGif"] else wood

        with patch.object(self.med, "_black_merchant_present", return_value=True), patch.object(
            self.med, "_bond_bar_nonempty", return_value=True
        ), patch.object(self.med, "find", side_effect=find_known), patch.object(
            self.med, "act_click", return_value=True
        ) as click:
            result = self.med._maybe_black_merchant(self.frame)
        self.assertEqual(result, LoopAction.Continue)
        self.assertEqual(click.call_args.args[1], "BlackMerchant-swallow_pill")

        self.med._merchant_next_at = 0.0
        self.med.settings.auto_gambling = True  # 显式开启自动刷新
        with patch.object(self.med, "_black_merchant_present", return_value=True), patch.object(
            self.med, "_bond_bar_nonempty", return_value=False
        ), patch.object(self.med, "find", return_value=None), patch.object(
            self.med, "_merchant_refresh_available", return_value=True
        ), patch.object(self.med, "act_click", return_value=True) as click:
            result = self.med._maybe_black_merchant(self.frame)
        self.assertEqual(result, LoopAction.Continue)
        self.assertEqual(click.call_args.args[1], "BlackMerchant-refresh")


class L1RuntimeAccountingTests(unittest.TestCase):
    """Commit3：三面板时间戳初始化 / choice_interval 重开限制 / attempts 记账 /
    trace 帧指纹缓存（Frame 强引用 + is 判同）。
    """

    def setUp(self):
        self.med = Mediator(Settings(), ROOT)
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

    def test_choice_interval_blocks_reopen_within_interval(self):
        # 当前 kind 成功主动打开后：间隔未满不重开，也不推进循环。
        self.med.settings.choice_interval = 120
        self.med._panel_episode_count["skill"] = 1  # 跳过 snapshot 兼容迁移
        self.med._l1_cycle_step = "skill"
        self.med._last_skill_panel = 100.0
        with patch("shuabao.mediator.time.time", return_value=200.0), \
                patch.object(self.med, "act_click") as click:
            result = self.med._maybe_open_choice_panel(self.frame, anchor=None)
        self.assertIs(result, LoopAction.Continue)
        click.assert_not_called()
        self.assertEqual(self.med._l1_cycle_step, "skill")

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
        with patch.object(med, "act_click") as click:
            self._enter_live_bond(med, slots)
        click.assert_not_called()
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
