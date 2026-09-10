"""S0 长期运行安全状态机测试（蓝图 §8 / Codex S0 章 / grok §7 强制顺序）。

覆盖：
  ① scenes 拆分（STRONG_FAIL / giveup / disconnect）
  ② 全局抢占（两帧 STRONG_FAIL 优先于 selection/panel FSM）
  ③ RECOVER_FAILURE 门闩（anchor∧input_ok∧(mutation∨post_anchor)）+ 分脚本 + 预算
  ④ round hard deadline（不可续期；到期先 QUIT 后 ERROR）
  ⑤ Panel FSM（WAIT_VISIBLE 可见窗 / 同指纹重试上限 / F1 shadow 灰度）
  ⑥ cycle_num / failure_streak / outcome
  ⑦ 生产 incident 入口（desktop_worker_writes_fail_closed_incident 在 test_desktop_app.py）

约束：不得删除/放宽/XFAIL 现有测试；断线真实素材缺失（missing_disconnect_modal）
登记为完成阻塞项，本文件用合成 matcher 证据（patch find_scene）验证恢复路径。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from shuabao.loop_action import LoopAction
from shuabao.mediator import (
    Mediator,
    PanelState,
    Phase,
    RecoveryKind,
    RecoveryStep,
    RoundOutcome,
)
from shuabao.scenes import load_scenes, scene_templates
from shuabao.settings import Settings
from shuabao.stop_signal import StopSignal
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult
from tests.test_scenario_replay import FakeClock, FakeInputExecutor


def _noise_frame(seed: int = 7, hwnd: int = 10001) -> Frame:
    rng = np.random.default_rng(seed)
    return Frame(
        rng.integers(0, 255, (900, 1600, 3), dtype=np.uint8),
        window_title="英雄三国KK",
        hwnd=hwnd,
    )


def _hit(name: str = "hit", x: int = 100, y: int = 100) -> MatchResult:
    return MatchResult(name=name, score=0.95, x=x, y=y, w=20, h=20, screen_x=x, screen_y=y)


class S0ScenesSplitTests(unittest.TestCase):
    """① scenes 拆分：STRONG_FAIL 不含 giveUp；giveup 独立；disconnect 独立。"""

    def test_giveup_not_in_strong_fail_templates(self) -> None:
        doc = load_scenes(ROOT)
        self.assertNotIn("giveUp", scene_templates(doc, "fail"))
        self.assertIn("fail", scene_templates(doc, "fail"))
        self.assertIn("gameFail", scene_templates(doc, "fail"))
        # giveUp 仍可作独立 giveup 场景加载（面板锚点证据）
        self.assertEqual(["giveUp"], scene_templates(doc, "giveup"))
        # disconnect 独立场景与恢复脚本入口
        self.assertEqual(["gameDisconnect", "retryConnect"], scene_templates(doc, "disconnect"))
        # giveup 不进强失败优先级
        priority = list(doc.get("priority") or [])
        self.assertNotIn("giveup", priority)
        self.assertLess(priority.index("disconnect"), priority.index("fail"))

    def test_strong_fail_with_panel_preempts_selection(self) -> None:
        """② fail+panel 同时存在：连续两帧 STRONG_FAIL 抢占 → RECOVER_FAILURE，
        selection/panel 输入 = 0（翻转旧「面板存在忽略失败」语义）。"""
        med = Mediator(Settings(), ROOT)
        clock = FakeClock(start=100.0)
        stop = StopSignal()
        executor = FakeInputExecutor(stop, clock)
        med.executor = executor
        med.set_phase(Phase.MAIN_LINE, "preempt test")
        frame = _noise_frame(seed=11)
        med._capture_best = lambda *a, **k: frame

        def find_scene(_f, scene, **_k):
            if scene == "fail":
                return _hit("fail")
            return None

        with clock.install(), \
                patch.object(med, "find_scene", side_effect=find_scene), \
                patch.object(med, "_selection_anchor", return_value=_hit("skill_hide", 600, 580)), \
                patch.object(med, "_post_game_state", return_value=None):
            # 帧1：候选（零输入）
            clock.set(100.5)
            self.assertIs(med.tick(), LoopAction.Continue)
            self.assertIs(med.phase, Phase.MAIN_LINE)
            self.assertEqual(len(executor.action_ledger), 0)
            # 帧2：抢占 → RECOVER_FAILURE，selection/panel 零输入
            clock.set(100.9)
            self.assertIs(med.tick(), LoopAction.Continue)
            self.assertIs(med.phase, Phase.RECOVER_FAILURE)
            self.assertEqual(len(executor.action_ledger), 0, "强失败+面板两帧选卡输入必须为 0")
            self.assertIsNotNone(med._recovery_state)
            self.assertEqual(med._recovery_state.kind, RecoveryKind.FAIL)

    def test_giveup_only_panel_is_not_failure(self) -> None:
        """① ② giveUp+有效面板锚点：AMBIGUOUS_GIVEUP，不进恢复、不变 QUIT。"""
        med = Mediator(Settings(), ROOT)
        clock = FakeClock(start=100.0)
        stop = StopSignal()
        executor = FakeInputExecutor(stop, clock)
        med.executor = executor
        med.set_phase(Phase.MAIN_LINE, "giveup panel test")
        frame = _noise_frame(seed=12)
        med._capture_best = lambda *a, **k: frame

        def find_scene(_f, scene, **_k):
            if scene == "giveup":
                return _hit("giveUp", 939, 668)
            return None

        with clock.install(), \
                patch.object(med, "find_scene", side_effect=find_scene), \
                patch.object(med, "_selection_anchor", return_value=_hit("bond_hide_btn", 600, 580)), \
                patch.object(med, "_post_game_state", return_value=None), \
                patch.object(med, "_find_reward_choice", return_value=None):
            for i in range(3):
                clock.set(101.0 + i * 4.0)
                self.assertIs(med.tick(), LoopAction.Continue)
                self.assertIs(med.phase, Phase.MAIN_LINE, "giveUp+锚点不得进入 QUIT/恢复")
            self.assertIsNone(med._recovery_state, "giveUp+锚点不得触发恢复")
            self.assertIsNone(med._round_outcome, "RoundOutcome 不变")
            self.assertGreater(med._ambiguous_giveup_frames, 0, "giveup 歧义证据应被记录")
            self.assertEqual(len(executor.action_ledger), 0, "giveUp 无恢复动作权")


class S0RecoveryTests(unittest.TestCase):
    """③ RECOVER_FAILURE：锚点/输入成功/mutation 门闩 + FAIL/DISCONNECT 分脚本 + 预算。"""

    def _recovery_mediator(self, clock: FakeClock, **settings_kw) -> Mediator:
        # dry_run=False：ERROR/停止在 tick() 可见（dry-run 观察模式会把 ERROR Break
        # 转回 Continue 并恢复 phase，无法断言熔断行为）。
        med = Mediator(Settings(dry_run=False, **settings_kw), ROOT)
        med.executor = FakeInputExecutor(StopSignal(), clock)
        med.set_phase(Phase.MAIN_LINE, "recovery test")
        frame = _noise_frame(seed=21)
        med._capture_best = lambda *a, **k: frame
        return med

    def test_recovery_does_not_advance_without_anchor_or_success(self) -> None:
        """缺锚点 / 点击失败 / 无 mutation 三个子例均停在同 step、无后续动作。"""
        # (a) 缺锚点：停留 FAIL_CONFIRM，零输入，有界重试
        med = self._recovery_mediator(FakeClock(start=100.0))
        clock = FakeClock(start=100.0)
        med.executor = FakeInputExecutor(StopSignal(), clock)
        with clock.install(), \
                patch.object(med, "find_scene", side_effect=lambda _f, s, **_k: _hit("fail") if s == "fail" else None), \
                patch.object(med, "_selection_anchor", return_value=None), \
                patch.object(med, "_post_game_state", return_value=None):
            clock.set(100.5)
            med.tick()
            clock.set(100.9)
            med.tick()
            self.assertIs(med.phase, Phase.RECOVER_FAILURE)
        # 锚点消失：停在 FAIL_CONFIRM，零输入
        with clock.install(), \
                patch.object(med, "find_scene", return_value=None), \
                patch.object(med, "_selection_anchor", return_value=None), \
                patch.object(med, "act_click", side_effect=lambda _h, reason="": (_ for _ in ()).throw(AssertionError("缺锚点不得点击"))):
            for i in range(2):
                clock.set(102.0 + i * 1.6)
                self.assertIs(med.tick(), LoopAction.Continue)
                self.assertIs(med._recovery_state.step, RecoveryStep.FAIL_CONFIRM)
                self.assertIs(med.phase, Phase.RECOVER_FAILURE)
            # 有界重试：第 3 次缺锚点后仍不推进；再观测 → 恢复失败 ERROR
            clock.set(105.2)
            self.assertIs(med.tick(), LoopAction.Continue)
            self.assertIs(med._recovery_state.step, RecoveryStep.FAIL_CONFIRM)
            clock.set(106.8)
            self.assertIs(med.tick(), LoopAction.Break)
            self.assertIs(med.phase, Phase.ERROR)

        # (b) 输入被拒：停在同 step，不推进（无 mutation 不授予状态推进）
        med2 = self._recovery_mediator(FakeClock(start=200.0))
        clock2 = FakeClock(start=200.0)
        med2.executor = FakeInputExecutor(StopSignal(), clock2)
        with clock2.install(), \
                patch.object(med2, "find_scene", side_effect=lambda _f, s, **_k: _hit("fail") if s == "fail" else _hit("ok") if s == "ok" else None), \
                patch.object(med2, "_selection_anchor", return_value=None), \
                patch.object(med2, "act_click", return_value=False):
            clock2.set(200.5)
            med2.tick()
            clock2.set(200.9)
            med2.tick()
            self.assertIs(med2.phase, Phase.RECOVER_FAILURE)
            clock2.set(201.5)
            self.assertIs(med2.tick(), LoopAction.Continue)
            self.assertIs(med2._recovery_state.step, RecoveryStep.FAIL_CONFIRM, "点击失败不推进")
            clock2.set(203.1)
            self.assertIs(med2.tick(), LoopAction.Continue)
            self.assertIs(med2._recovery_state.step, RecoveryStep.FAIL_CONFIRM)

        # (c) 点击成功但无 mutation：停在同 step（WAIT_CONFIRM 超时后回 READY，不推进下一步）
        med3 = self._recovery_mediator(FakeClock(start=300.0))
        clock3 = FakeClock(start=300.0)
        med3.executor = FakeInputExecutor(StopSignal(), clock3)
        with clock3.install(), \
                patch.object(med3, "find_scene", side_effect=lambda _f, s, **_k: _hit("fail") if s == "fail" else _hit("ok") if s == "ok" else None), \
                patch.object(med3, "_selection_anchor", return_value=None):
            clock3.set(300.5)
            med3.tick()
            clock3.set(300.9)
            med3.tick()
            self.assertIs(med3.phase, Phase.RECOVER_FAILURE)
            clock3.set(301.5)
            self.assertIs(med3.tick(), LoopAction.Continue)  # 点击 ok 成功 → WAIT_CONFIRM
            self.assertTrue(med3._recovery_state.waiting_confirm)
            # 无 mutation：确认窗（15s）超时 → 回 READY，step 不变
            clock3.set(317.0)
            self.assertIs(med3.tick(), LoopAction.Continue)
            self.assertIs(med3._recovery_state.step, RecoveryStep.FAIL_CONFIRM)
            self.assertIs(med3.phase, Phase.RECOVER_FAILURE)

    def test_disconnect_uses_disconnect_path(self) -> None:
        """断线恢复只操作 disconnect/retry 锚点；fail 的 ok/close 永不被调用。"""
        med = self._recovery_mediator(FakeClock(start=100.0))
        clock = FakeClock(start=100.0)
        med.executor = FakeInputExecutor(StopSignal(), clock)
        clicked: list[str] = []
        disconnect_name = ["retryConnect"]

        def find_scene(_f, scene, **_k):
            if scene == "disconnect":
                return _hit(disconnect_name[0])
            return None

        with clock.install(), \
                patch.object(med, "find_scene", side_effect=find_scene), \
                patch.object(med, "_selection_anchor", return_value=None), \
                patch.object(med, "act_click", side_effect=lambda _h, reason="": clicked.append(reason) or True):
            # 两帧断线 → RECOVER_FAILURE(DISCONNECT)
            clock.set(100.5)
            med.tick()
            clock.set(100.9)
            med.tick()
            self.assertIs(med.phase, Phase.RECOVER_FAILURE)
            self.assertEqual(med._recovery_state.kind, RecoveryKind.DISCONNECT)
            # 断线弹窗只有 gameDisconnect 文字（无重连按钮）→ 零输入等待
            disconnect_name[0] = "gameDisconnect"
            clock.set(101.5)
            self.assertIs(med.tick(), LoopAction.Continue)
            self.assertEqual(clicked, [], "无重连锚点时零输入")
            # 重连按钮出现 → 点击 retryConnect；绝无 fail 的 ok/close
            disconnect_name[0] = "retryConnect"
            clock.set(103.0)
            self.assertIs(med.tick(), LoopAction.Continue)
            self.assertEqual(clicked, ["Recovery-DISCONNECT-DISCONNECT_RETRY"])
            # 断线弹窗消失（mutation）→ 完成 → outcome DISCONNECT → QUIT
            def find_scene_gone(_f, scene, **_k):
                return None  # 全部弹窗消失 = mutation 证据

            with patch.object(med, "find_scene", side_effect=find_scene_gone):
                clock.set(104.6)
                self.assertIs(med.tick(), LoopAction.Continue)
            self.assertIs(med.phase, Phase.QUIT)
            self.assertEqual(med._round_outcome, RoundOutcome.DISCONNECT)
            self.assertEqual(med._disconnect_count, 1)
            self.assertEqual(med._failure_streak, 1, "断线也计入不成功局（防绕开熔断）")
        self.assertFalse(any("FAIL" in r for r in clicked), "断线路径不得调用 fail 脚本")
        self.assertFalse(any(r in ("ok", "close") for r in clicked))

    def test_secret_realm_failure_uses_top_exit_then_standard_confirm(self) -> None:
        """Strong rift failure has no center modal: quit and confirm stay anchored."""
        clock = FakeClock(start=100.0)
        med = self._recovery_mediator(clock)
        med._secret_realm_active = True
        frame = _noise_frame(seed=23)
        clicked: list[tuple[str, str]] = []
        exit_dialog_visible = False

        def find_scene(_frame, scene, **_kwargs):
            if scene == "fail":
                return _hit("gameFail", 800, 90)
            return None

        def find_exit_confirm(_frame):
            if exit_dialog_visible:
                return _hit("exit_confirm_btn", 740, 554)
            return None

        def act_click(hit, reason=""):
            clicked.append((hit.name, reason))
            return True

        with clock.install(), \
                patch.object(med, "find_scene", side_effect=find_scene), \
                patch.object(med, "_find_failure_exit_button", return_value=None), \
                patch.object(med, "_find_game_exit", return_value=_hit("quit", 76, 58)), \
                patch.object(med, "_find_exit_confirm", side_effect=find_exit_confirm), \
                patch.object(med, "act_click", side_effect=act_click):
            med._begin_recovery(RecoveryKind.FAIL)
            clock.set(100.1)
            self.assertIs(med._tick_recovery(frame), LoopAction.Continue)
            self.assertEqual(clicked, [
                ("failure_open_exit", "Recovery-FAIL-FAIL_CONFIRM")
            ])
            self.assertTrue(med._recovery_state.opening_exit_confirm)
            self.assertTrue(med._recovery_state.waiting_confirm)

            # The standard confirmation dialog is a required post-click anchor;
            # seeing it advances the state but sends no second input in this tick.
            exit_dialog_visible = True
            clock.set(101.7)
            self.assertIs(med._tick_recovery(frame), LoopAction.Continue)
            self.assertEqual(med._recovery_state.step, RecoveryStep.FAIL_EXIT_CONFIRM)
            self.assertEqual(len(clicked), 1)

            clock.set(103.3)
            self.assertIs(med._tick_recovery(frame), LoopAction.Continue)

        self.assertEqual(clicked[-1], (
            "exit_confirm_btn", "Recovery-FAIL-FAIL_EXIT_CONFIRM"
        ))
        self.assertIs(med.phase, Phase.PREPARE)
        self.assertTrue(med._awaiting_room_return)
        self.assertIs(med._round_outcome, RoundOutcome.VICTORY)
        self.assertEqual(med._success_count, 1)
        self.assertEqual(med._failure_streak, 0)
        self.assertIsNone(med._recovery_state)

    def test_recovery_exit_timeout_starts_after_recovery(self) -> None:
        """46.9s 恢复后退出期限从恢复完成时刻起算，而非恢复开始时刻。"""
        med = self._recovery_mediator(FakeClock(start=100.0))
        clock = FakeClock(start=100.0)
        med.executor = FakeInputExecutor(StopSignal(), clock)
        ok_visible = False
        fail_visible = True

        def find_scene(_f, scene, **_k):
            if scene == "fail":
                return _hit("fail") if fail_visible else None
            if scene == "ok":
                return _hit("ok") if ok_visible else None
            return None

        with clock.install(), \
                patch.object(med, "find_scene", side_effect=find_scene), \
                patch.object(med, "_selection_anchor", return_value=None):
            # 抢占（恢复在 t≈100.9 开始）
            clock.set(100.5)
            med.tick()
            clock.set(100.9)
            med.tick()
            self.assertIs(med.phase, Phase.RECOVER_FAILURE)
            recovery_started = med._recovery_state.started_at
            # 缺 ok 按钮：零输入等待至 t=146.9（恢复耗时约 46.0s）
            clock.set(146.9)
            self.assertIs(med.tick(), LoopAction.Continue)
            self.assertIs(med.phase, Phase.RECOVER_FAILURE)
            # ok 出现 → 点击；随后失败弹窗消失 → 完成（总恢复 ≈46.9s）
            ok_visible = True
            clock.set(147.8)
            self.assertIs(med.tick(), LoopAction.Continue)
            self.assertTrue(med._recovery_state.waiting_confirm)
            ok_visible = False
            fail_visible = False
            clock.set(147.9)
            self.assertIs(med.tick(), LoopAction.Continue)
            self.assertIs(med.phase, Phase.QUIT, "恢复完成后才进入 QUIT")
            recovery_completed = clock.now()
            self.assertGreaterEqual(recovery_completed - recovery_started, 46.9 - 0.5)
            # 退出窗口从恢复完成开始：_exit_since == recovery_completed_at
            self.assertAlmostEqual(med._exit_since, recovery_completed, places=6)
            exit_window = max(3, min(med.settings.query_timeout, 15))
            self.assertAlmostEqual(med._exit_since + exit_window, recovery_completed + exit_window, places=6)
            self.assertGreater(med._exit_since, recovery_started, "不得从恢复开始起算退出窗口")
            # 恢复期间 QUIT 输入为 0
            self.assertEqual(len(med.executor.action_ledger), 1, "只有 ok 一次点击")


class S0RoundDeadlineTests(unittest.TestCase):
    """④ round hard deadline：进入 MAIN_LINE 固定，不可续期。"""

    def test_periodic_panel_actions_do_not_extend_round_deadline(self) -> None:
        med = Mediator(Settings(round_timeout_s=60), ROOT)
        clock = FakeClock(start=100.0)
        med.executor = FakeInputExecutor(StopSignal(), clock)
        frame = _noise_frame(seed=31)
        med._capture_best = lambda *a, **k: frame

        with clock.install(), \
                patch.object(med, "find_scene", return_value=None), \
                patch.object(med, "_selection_anchor", return_value=_hit("skill_hide", 600, 580)), \
                patch.object(med, "_post_game_state", return_value=None), \
                patch.object(med, "_find_reward_choice", return_value=("技能", _hit("skills/jq", 500, 260))), \
                patch.object(med, "_panel_mutation_confirmed", return_value=True):
            med.set_phase(Phase.MAIN_LINE, "round start")
            deadline = med._round_deadline
            self.assertAlmostEqual(deadline, 160.0, places=6)
            # 3 个合法面板动作（每个间隔 ≥1.5s，mutation 确认后回到 ACTIVE）
            for i in range(3):
                clock.set(101.0 + i * 2.0)
                self.assertIs(med.tick(), LoopAction.Continue)  # ACTIVE → 点击
                clock.set(101.6 + i * 2.0)
                self.assertIs(med.tick(), LoopAction.Continue)  # WAIT_MUTATION → ACTIVE
            self.assertEqual(med._round_deadline, deadline, "周期面板动作不得延长 round deadline")
            # 到期：先 QUIT（记录 TIMEOUT），动作不再产生
            clicks_before = len(med.executor.action_ledger)
            clock.set(161.0)
            self.assertIs(med.tick(), LoopAction.Continue)
            self.assertIs(med.phase, Phase.QUIT)
            self.assertEqual(med._round_outcome, RoundOutcome.TIMEOUT)
            self.assertEqual(med._failure_streak, 1)
            self.assertEqual(len(med.executor.action_ledger), clicks_before, "到期后动作不再产生")

    def test_round_deadline_set_once_per_round(self) -> None:
        med = Mediator(Settings(round_timeout_s=90), ROOT)
        clock = FakeClock(start=100.0)
        with clock.install():
            med.set_phase(Phase.MAIN_LINE, "entry 1")
            d1 = med._round_deadline
            self.assertAlmostEqual(d1, 190.0, places=6)
            # 同一局重复 set_phase 不得覆盖
            clock.set(120.0)
            med.set_phase(Phase.MAIN_LINE, "re-entry same round")
            self.assertEqual(med._round_deadline, d1)
            # 新局（经 STAGE_SELECT）重新计时
            clock.set(121.0)
            med.set_phase(Phase.STAGE_SELECT, "new round")
            self.assertIsNone(med._round_deadline)
            clock.set(122.0)
            med.set_phase(Phase.MAIN_LINE, "round 2")
            self.assertAlmostEqual(med._round_deadline, 212.0, places=6)


class S0PanelFsmTests(unittest.TestCase):
    """⑤ Panel FSM：可见窗 / 间隔 / 指纹上限 / F1 shadow。"""

    def _panel_mediator(self, clock: FakeClock, **kw) -> Mediator:
        # FSM 时序测试与输入模式无关（act_click 整体 mock）；钉住 dry_run，
        # 否则 1d8f101 翻默认后 tick1 落进真实输入专属的 20s 预部署静默窗。
        settings = Settings(**kw)
        settings.dry_run = True
        med = Mediator(settings, ROOT)
        med.executor = FakeInputExecutor(StopSignal(), clock)
        med.set_phase(Phase.MAIN_LINE, "panel fsm test")
        med._auto_task_done = True
        frame = _noise_frame(seed=41)
        med._capture_best = lambda *a, **k: frame
        return med

    def test_panel_waits_for_visibility_before_close(self) -> None:
        """打开后 2s 可见窗内不得下一 tick 反点关闭。"""
        med = self._panel_mediator(FakeClock(start=100.0), panel_visible_timeout_s=2.0)
        med._l1_cycle_step = "skill"
        clock = FakeClock(start=100.0)
        med.executor = FakeInputExecutor(StopSignal(), clock)
        anchor_visible = False
        clicked: list[str] = []

        def anchor(frame):
            return _hit("skill_hide", 600, 580) if anchor_visible else None

        with clock.install(), \
                patch.object(med, "find_scene", return_value=None), \
                patch.object(med, "_selection_anchor", side_effect=anchor), \
                patch.object(med, "_post_game_state", return_value=None), \
                patch.object(med, "_ensure_auto_task_enabled", return_value=None), \
                patch.object(med, "_ensure_challenge_buttons", return_value=None), \
                patch.object(med, "_find_stage_page", return_value=False), \
                patch.object(med, "_handle_self_opened_compact_panel", return_value=None), \
                patch.object(med, "_maybe_fire_artifacts", return_value=None), \
                patch.object(med, "act_click", side_effect=lambda _h, reason="": clicked.append(reason) or True):
            # tick1：主动打开技能面板（G）
            clock.set(100.5)
            self.assertIs(med.tick(), LoopAction.Continue)
            self.assertIn("OpenSkillPanel", clicked)
            self.assertIs(med._panel_state, PanelState.OPEN_REQUESTED)
            # tick2/3：可见窗内 anchor 未出现 → 零动作（不得反点关闭）
            clock.set(100.7)
            self.assertIs(med.tick(), LoopAction.Continue)
            self.assertIs(med._panel_state, PanelState.WAIT_VISIBLE)
            clock.set(101.0)
            self.assertIs(med.tick(), LoopAction.Continue)
            self.assertEqual(clicked, ["OpenSkillPanel"], "2s 可见窗内不得点击关闭")
            # anchor 在窗内出现 → ACTIVE
            anchor_visible = True
            clock.set(101.5)
            self.assertIs(med.tick(), LoopAction.Continue)
            self.assertIs(med._panel_state, PanelState.ACTIVE)
            self.assertEqual(clicked, ["OpenSkillPanel"], "可见后仍不盲点关闭")

        # 2s 到期未见 anchor → COOLDOWN、零盲点/盲关闭
        med2 = self._panel_mediator(FakeClock(start=200.0), panel_visible_timeout_s=2.0)
        med2._l1_cycle_step = "skill"
        clock2 = FakeClock(start=200.0)
        med2.executor = FakeInputExecutor(StopSignal(), clock2)
        clicked2: list[str] = []
        with clock2.install(), \
                patch.object(med2, "find_scene", return_value=None), \
                patch.object(med2, "_selection_anchor", return_value=None), \
                patch.object(med2, "_post_game_state", return_value=None), \
                patch.object(med2, "_ensure_auto_task_enabled", return_value=None), \
                patch.object(med2, "_ensure_challenge_buttons", return_value=None), \
                patch.object(med2, "_find_stage_page", return_value=False), \
                patch.object(med2, "_handle_self_opened_compact_panel", return_value=None), \
                patch.object(med2, "_maybe_fire_artifacts", return_value=None), \
                patch.object(med2, "act_click", side_effect=lambda _h, reason="": clicked2.append(reason) or True):
            clock2.set(200.5)
            med2.tick()  # 打开
            clock2.set(200.7)
            med2.tick()  # WAIT_VISIBLE
            clock2.set(202.8)  # 超过 2s 可见窗
            self.assertIs(med2.tick(), LoopAction.Continue)
            self.assertIs(med2._panel_state, PanelState.COOLDOWN)
            self.assertEqual(clicked2, ["OpenSkillPanel"], "可见窗到期是 cooldown/zero input，不盲点关闭")

    def test_panel_same_fingerprint_has_bounded_retries_and_cooldown(self) -> None:
        """同 fingerprint 同动作 ≤3 次；第四次被拒并进入 cooldown（FakeInput 次数=3）。"""
        med = self._panel_mediator(
            FakeClock(start=100.0),
            panel_action_limit_per_fingerprint=3,
            ui_action_interval_s=1.5,
        )
        clock = FakeClock(start=100.0)
        executor = FakeInputExecutor(StopSignal(), clock)
        med.executor = executor

        with clock.install(), \
                patch.object(med, "find_scene", return_value=None), \
                patch.object(med, "_selection_anchor", return_value=_hit("skill_hide", 600, 580)), \
                patch.object(med, "_post_game_state", return_value=None), \
                patch.object(med, "_find_reward_choice", return_value=("技能", _hit("skills/jq", 500, 260))), \
                patch.object(med, "_panel_mutation_confirmed", return_value=True):
            # 第 1-3 次：同 fingerprint 点击
            for i in range(3):
                clock.set(101.0 + i * 2.0)
                self.assertIs(med.tick(), LoopAction.Continue)
                clock.set(101.6 + i * 2.0)
                self.assertIs(med.tick(), LoopAction.Continue)  # mutation → ACTIVE
            choice_clicks = [r for r in executor.action_ledger if r.method == "click"]
            self.assertEqual(len(choice_clicks), 3, "同 fingerprint 同动作最多 3 次点击")
            # 第 4 次同 fingerprint：被拒（零点击）并进入 CLOSING 物理关闭
            clock.set(108.0)
            self.assertIs(med.tick(), LoopAction.Continue)
            self.assertIs(med._panel_state, PanelState.CLOSING, "第四次进入 CLOSING 物理关闭")
            self.assertEqual(
                len([r for r in executor.action_ledger if r.method == "click"]),
                3,
                "第四次同 fingerprint 点击被拒绝",
            )

    def test_f1_shadow_20_correct_zero_misfire_goes_live(self) -> None:
        med = self._panel_mediator(FakeClock(start=100.0))
        self.assertFalse(med._f1_live)
        for _ in range(19):
            med._panel_f1_shadow_record(True, True)
        self.assertFalse(med._f1_live)
        med._panel_f1_shadow_record(True, True)
        self.assertTrue(med._f1_live, "累计 20 次正确、0 误触才允许 LIVE")
        med._panel_f1_shadow_record(True, True)  # LIVE 后不再重复计数
        self.assertEqual(med._f1_shadow_correct, 20)

    def test_f1_shadow_any_misfire_resets_and_keeps_closed(self) -> None:
        med = self._panel_mediator(FakeClock(start=100.0))
        for _ in range(10):
            med._panel_f1_shadow_record(True, True)
        med._panel_f1_shadow_record(True, False)  # 误触
        self.assertEqual(med._f1_shadow_correct, 0, "任一误触清零正确计数")
        self.assertEqual(med._f1_shadow_misfire, 1)
        self.assertFalse(med._f1_live)

    def test_f1_shadow_recorded_at_most_once_per_episode(self) -> None:
        med = self._panel_mediator(FakeClock(start=100.0))
        clock = FakeClock(start=100.0)
        med.executor = FakeInputExecutor(StopSignal(), clock)
        calls: list[bool] = []

        with clock.install(), \
                patch.object(med, "find_scene", return_value=None), \
                patch.object(med, "_selection_anchor", return_value=_hit("skill_hide", 600, 580)), \
                patch.object(med, "_post_game_state", return_value=None), \
                patch.object(med, "_find_reward_choice", return_value=None), \
                patch.object(med, "_panel_f1_shadow_record", side_effect=lambda w, c: calls.append(w)):
            clock.set(101.0)
            self.assertIs(med.tick(), LoopAction.Continue)
            clock.set(102.0)
            self.assertIs(med.tick(), LoopAction.Continue)
        self.assertEqual(calls, [True], "每 panel episode 最多一次 F1 shadow")


class S0CrossRoundTests(unittest.TestCase):
    """⑥ cycle_num / failure_streak / outcome 跨局语义。"""

    def _round_mediator(self, clock: FakeClock, **kw) -> Mediator:
        med = Mediator(Settings(dry_run=False, **kw), ROOT)
        med.executor = FakeInputExecutor(StopSignal(), clock)
        frame = _noise_frame(seed=51)
        med._capture_best = lambda *a, **k: frame
        return med

    def _fail_one_round(self, med: Mediator, clock: FakeClock, fail_visible=True) -> None:
        """一局失败全链：两帧抢占 → ok → 弹窗消失 → QUIT → 确认退出 → 回房。"""
        ok_visible = [False]
        fail_on = [fail_visible]

        def find_scene(_f, scene, **_k):
            if scene == "fail":
                return _hit("fail") if fail_on[0] else None
            if scene == "ok":
                return _hit("ok") if ok_visible[0] else None
            return None

        with patch.object(med, "find_scene", side_effect=find_scene), \
                patch.object(med, "_selection_anchor", return_value=None), \
                patch.object(med, "_post_game_state", return_value=None):
            clock.set(clock.now() + 0.4)
            med.tick()
            clock.set(clock.now() + 0.4)
            med.tick()  # RECOVER_FAILURE
            ok_visible[0] = True
            clock.set(clock.now() + 1.6)
            med.tick()  # 点 ok
            fail_on[0] = False
            clock.set(clock.now() + 1.6)
            med.tick()  # mutation → QUIT
            self.assertIs(med.phase, Phase.QUIT)
            # 退出确认 → NEXT → PREPARE（回房等待）
            with patch.object(med, "_find_exit_confirm", return_value=_hit("exit_confirm")), \
                    patch.object(med, "_find_game_exit", return_value=None):
                clock.set(clock.now() + 0.5)
                med.tick()  # QUIT → NEXT
                clock.set(clock.now() + 1.6)
                med.tick()  # NEXT → 点确认 → PREPARE
            self.assertTrue(med._awaiting_room_return)

    def _room_return(self, med: Mediator, clock: FakeClock) -> None:
        with patch.object(med, "_find_room_start", return_value=_hit("room_start", 700, 500)):
            clock.set(clock.now() + 0.5)
            med.tick()

    def _victory_round(self, med: Mediator, clock: FakeClock, round_no: int) -> None:
        """一局完整胜利链：选关（清 outcome 守卫）→ MAIN_LINE → NPC_HUB 确认点
        （VICTORY 落账）→ 退出确认 → 回房。"""
        med.set_phase(Phase.STAGE_SELECT, f"round {round_no}")
        med.set_phase(Phase.MAIN_LINE, f"round {round_no}")
        med._record_round_outcome(RoundOutcome.VICTORY, f"round {round_no} victory chain verified")
        med._awaiting_room_return = True
        med.set_phase(Phase.PREPARE, "exit confirmed")
        self._room_return(med, clock)

    def test_three_failed_rounds_fail_closed_and_victory_resets_streak(self) -> None:
        med = self._round_mediator(FakeClock(start=100.0), failure_streak_limit=3)
        clock = FakeClock(start=100.0)
        med.executor = FakeInputExecutor(StopSignal(), clock)
        with clock.install():
            # 局 1：失败
            med.set_phase(Phase.MAIN_LINE, "round 1")
            self._fail_one_round(med, clock)
            self._room_return(med, clock)
            self.assertEqual(med.game_count, 1)
            self.assertEqual(med._failure_streak, 1)
            # G0 contract #7：同房返回证明完成后进入 LeaveOldRoom episode
            #（PREPARE + _room_leave_pending），不再直接 ROOM_WAITING。
            self.assertIs(med.phase, Phase.PREPARE)
            self.assertTrue(med._room_leave_pending)

            # 局 2：中间一局完整胜利链 → streak 清零
            self._victory_round(med, clock, round_no=2)
            self.assertEqual(med._success_count, 1)
            self.assertEqual(med._failure_streak, 0, "确认完整胜利链后 streak 清零")
            self.assertEqual(med.game_count, 2)

            # 局 3-5：连续失败 → 局 5 回房后熔断 ERROR，绝不尝试下一局
            for round_no in (3, 4, 5):
                med.set_phase(Phase.STAGE_SELECT, f"round {round_no}")
                med.set_phase(Phase.MAIN_LINE, f"round {round_no}")
                self._fail_one_round(med, clock)
                self._room_return(med, clock)
            self.assertEqual(med._failure_streak, 3)
            self.assertIs(med.phase, Phase.ERROR, "连续 3 局失败安全停止")
            self.assertFalse(med._running)

    def test_cycle_num_two_stops_before_third_room_start(self) -> None:
        med = self._round_mediator(FakeClock(start=100.0), cycle_num=2)
        clock = FakeClock(start=100.0)
        med.executor = FakeInputExecutor(StopSignal(), clock)
        with clock.install():
            self._victory_round(med, clock, round_no=1)
            self.assertEqual(med.game_count, 1)
            # G0 contract #7：第 1 局后同房证明完成 → LeaveOldRoom episode
            #（PREPARE + _room_leave_pending），cycle 尚未达成、继续。
            self.assertIs(med.phase, Phase.PREPARE)
            self.assertTrue(med._room_leave_pending)
            self._victory_round(med, clock, round_no=2)
            self.assertEqual(med.game_count, 2)
            self.assertIs(med.phase, Phase.COMPLETE, "cycle_num=2 达成后转 COMPLETE")
            # 第三次 room start 可见：act_click 未调用（绝不点下一局开始）
            room_clicks = [r for r in med.executor.action_ledger if r.method == "click"]
            self.assertFalse(
                any("RoomStart" in str(r.args) or "room_start" in str(r.args) for r in room_clicks),
                "达到 cycle_num 后绝不点击下一局开始",
            )
            self.assertFalse(med._running)


class S0SettingsTests(unittest.TestCase):
    """Settings 新安全默认与范围校验。"""

    def test_s0_defaults_and_range_clamping(self) -> None:
        s = Settings()
        self.assertEqual(s.round_timeout_s, 3600)
        self.assertEqual(s.recovery_timeout_s, 60)
        self.assertEqual(s.recovery_action_limit, 3)
        self.assertEqual(s.recovery_retry_interval_s, 1.5)
        self.assertEqual(s.failure_streak_limit, 3)
        self.assertEqual(s.panel_visible_timeout_s, 2.0)
        self.assertEqual(s.ui_action_interval_s, 1.5)
        self.assertEqual(s.panel_action_limit_per_fingerprint, 3)
        self.assertEqual(s.panel_episode_limit_per_kind, 24)
        self.assertAlmostEqual(s.incident_sample_rate, 0.1)

        clamped = Settings._from_dict({
            "round_timeout_s": 5,        # <60 → 60
            "failure_streak_limit": 99,  # >10 → 10
            "incident_sample_rate": 5.0,  # >1.0 → 1.0
            "recovery_retry_interval_s": 0.1,  # <0.5 → 0.5
            "round_timeout_s_str": "bad",  # 未知键忽略
        })
        self.assertEqual(clamped.round_timeout_s, 60)
        self.assertEqual(clamped.failure_streak_limit, 10)
        self.assertEqual(clamped.incident_sample_rate, 1.0)
        self.assertEqual(clamped.recovery_retry_interval_s, 0.5)

    def test_round_timeout_migration_decision_documented(self) -> None:
        """旧 game_timeout=15 是分钟级 idle watchdog；round_timeout_s 是秒级硬期限。
        20260822：900s 是短局测试期取值，长线程刷图一局以打完 Boss 为界远超 15 分钟，
        默认放宽到 3600s（文档见 settings.py），与 game_timeout（idle watchdog）分离。"""
        import inspect
        import shuabao.settings as settings_mod

        src = inspect.getsource(settings_mod)
        self.assertIn("round_timeout_s", src)
        self.assertIn("idle watchdog", src)
        s = Settings()
        self.assertEqual(s.round_timeout_s, 3600)



class HeroChangedPixelsRegressionTests(unittest.TestCase):
    """_panel_mutation_confirmed 崩溃回归：cv2.countNonZero 仅接受单通道，
    BGR ROI（刷新按钮场景）实测抛 'cn == 1'；修复为 BGR->灰度后不崩溃。"""

    def test_bgr_input_does_not_crash_and_matches_gray(self) -> None:
        import numpy as np
        import cv2
        from shuabao.mediator import Mediator

        before = np.random.randint(0, 255, (300, 500, 3), dtype=np.uint8)
        after = before.copy()
        after[50:80, 60:120] = np.random.randint(0, 255, (30, 60, 3), dtype=np.uint8)
        bgr_n = Mediator._hero_changed_pixels(before, after)
        g1 = cv2.cvtColor(before, cv2.COLOR_BGR2GRAY)
        g2 = cv2.cvtColor(after, cv2.COLOR_BGR2GRAY)
        self.assertEqual(bgr_n, Mediator._hero_changed_pixels(g1, g2))
        self.assertGreater(bgr_n, 0)

    def test_identical_bgr_frames_zero(self) -> None:
        import numpy as np
        from shuabao.mediator import Mediator

        before = np.random.randint(0, 255, (300, 500, 3), dtype=np.uint8)
        self.assertEqual(Mediator._hero_changed_pixels(before, before.copy()), 0)

    def test_shape_mismatch_zero(self) -> None:
        import numpy as np
        from shuabao.mediator import Mediator

        a = np.zeros((100, 100, 3), dtype=np.uint8)
        b = np.zeros((90, 90, 3), dtype=np.uint8)
        self.assertEqual(Mediator._hero_changed_pixels(a, b), 0)


if __name__ == "__main__":
    unittest.main()
