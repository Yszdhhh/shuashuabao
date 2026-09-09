"""G0 core lifecycle 回归（EXTERNAL-ALPHA-G0）。

覆盖契约：
1. 压力转移 fresh confirmation：click 仅 request，fresh frame + yalizhuanyi 消失才 confirmed。
2. 压力 bounded budget 耗尽 → _hitch_pressure_core_failed；optional 不放行但 POST_VICTORY 可观察。
3. 压力 gate 不遮蔽强失败/disconnect 全局抢占。
4. _tick_main_line 中 postgame 分类先于压力 gate。
5. Normal farm：同房返回证明 → leave-old-room episode；fresh room-list authority 才 PLATFORM_MAP。
6. Archaeology：click 仅 request；fresh generation kaogu 锚点才 COMPLETE；bounded 超时 fail-closed。
7. 终止归因：_classify_run_exit 锚点 + 外部 StopSignal reason 保留。
8. round_elapsed / exit_reason / window snapshot 可读字段语义。
9. unhealthy hitch：双窗失 → FATAL；游戏窗失 + fresh 平台房间列表 → 回 lobby；零业务输入。
"""

from __future__ import annotations

import sys
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import numpy as np
import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from shuabao.loop_action import LoopAction
from shuabao.mediator import Mediator, Phase, RecoveryKind, RoundOutcome, RunExitReason
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


class _Ctx:
    """组合 patch 列表为单个 context manager（with 内不支持 *patches）。"""

    def __init__(self, patches):
        self.patches = list(patches)

    def __enter__(self):
        stack = ExitStack()
        for p in self.patches:
            stack.enter_context(p)
        self._stack = stack
        return self

    def __exit__(self, *exc):
        self._stack.close()
        return False


def _hitch_mediator(clock: FakeClock, **kw) -> Mediator:
    med = Mediator(Settings(dry_run=False, mode_id="lobby_hitch", query_timeout=30, **kw), ROOT)
    med.executor = FakeInputExecutor(StopSignal(), clock)
    return med


def _pressure_tick_patches(med: Mediator, click_hit):
    """蹭车 MAIN_LINE tick 的通用打桩：唯一可见控件 = yalizhuanyi。

    click_hit 可以是 MatchResult/None（对所有帧生效）或 (frame)->MatchResult|None。
    """
    def find(frame, names, **_k):
        if "yalizhuanyi" in names:
            return click_hit(frame) if callable(click_hit) else click_hit
        return None

    return [
        patch.object(med, "find", side_effect=find),
        patch.object(med, "find_scene", return_value=None),
        patch.object(med, "_selection_anchor", return_value=None),
        patch.object(med, "_post_game_state", return_value=None),
        patch.object(med, "_hitch_ocr_text", return_value=""),
        patch.object(med, "_find_failure_gift", return_value=None),
        patch.object(med, "_is_in_game_hud", return_value=True),
    ]


class G0PressureTransferTests(unittest.TestCase):
    """契约 #1：click 仅 request；fresh 帧证实按钮消失才 confirmed。"""

    def test_click_is_request_only_and_fresh_frame_confirms(self) -> None:
        clock = FakeClock(start=100.0)
        med = _hitch_mediator(clock)
        med.set_phase(Phase.MAIN_LINE, "pressure request")
        frame_clicked = _noise_frame(seed=11)
        frame_same = _noise_frame(seed=11)  # 同内容：see() 复用同帧对象 → 同 generation
        frame_gone = _noise_frame(seed=12)
        pending = [frame_clicked, frame_same, frame_gone]
        med._capture_best = lambda *a, **k: pending.pop(0)
        patches = _pressure_tick_patches(med, lambda f: None if f is frame_gone else _hit("yalizhuanyi"))
        with clock.install(), _Ctx(patches):
            # tick1：发现按钮 → 点击 request，等待后置条件（非 transferred）
            self.assertIs(med.tick(), LoopAction.Continue)
            self.assertEqual(len(med.executor.action_ledger), 1, "一次 request 恰好一次输入")
            self.assertFalse(med._hitch_pressure_transferred, "click success 不构成完成")
            self.assertIsNotNone(med._hitch_pressure_click_at)
            self.assertEqual(med.last_business_action, "HitchPressureTransfer")
            clock.set(100.4)
            # tick2：同帧同 generation → 绝不确认
            self.assertIs(med.tick(), LoopAction.Continue)
            self.assertFalse(med._hitch_pressure_transferred, "同帧不确认")
            self.assertEqual(len(med.executor.action_ledger), 1, "同帧不重复点击")
            # tick3：fresh 帧 + 按钮消失 → confirmed
            self.assertIs(med.tick(), LoopAction.Continue)
            self.assertTrue(med._hitch_pressure_transferred, "fresh 帧按钮消失才确认")
            self.assertEqual(len(med.executor.action_ledger), 1, "确认零输入")

    def test_gone_without_click_never_confirms(self) -> None:
        clock = FakeClock(start=100.0)
        med = _hitch_mediator(clock)
        med.set_phase(Phase.MAIN_LINE, "pressure never clicked")
        frame = _noise_frame(seed=13)
        med._capture_best = lambda *a, **k: frame
        patches = _pressure_tick_patches(med, None)
        with clock.install(), _Ctx(patches):
            for i in range(3):
                clock.set(100.5 + i * 0.4)
                self.assertIs(med.tick(), LoopAction.Continue)
            self.assertFalse(med._hitch_pressure_transferred, "未见按钮绝不猜测完成")
            self.assertEqual(len(med.executor.action_ledger), 0, "零按钮期间零输入")


class G0PressureBudgetTests(unittest.TestCase):
    """契约 #2：bounded budget（5 次 request）耗尽 → core failed。"""

    def _rejected_click_mediator(self) -> Mediator:
        clock = FakeClock(start=100.0)
        med = _hitch_mediator(clock)
        med.set_phase(Phase.MAIN_LINE, "pressure budget")
        med._capture_best = lambda *a, **k: _noise_frame(seed=21)
        click_hit = _hit("yalizhuanyi")
        for p in _pressure_tick_patches(med, click_hit):
            p.start()
            self.addCleanup(p.stop)
        return med

    def test_click_rejected_budget_exhausts_to_core_failed(self) -> None:
        med = self._rejected_click_mediator()
        with patch.object(med, "act_click", return_value=False):
            for attempt in range(1, 6):
                res = med._maybe_click_hitch_pressure_transfer(_noise_frame(seed=21 + attempt), time.time())
                self.assertIs(res, LoopAction.Continue)
                if attempt < 5:
                    self.assertFalse(med._hitch_pressure_core_failed)
        self.assertTrue(med._hitch_pressure_core_failed, "5 次被拒后 core failed")
        self.assertFalse(med._hitch_pressure_transferred, "core failed 永不计作 pressure success")
        # core failed 后每 tick 零输入 Continue（不再点击/不 stop）
        res = med._maybe_click_hitch_pressure_transfer(_noise_frame(seed=99), time.time())
        self.assertIs(res, LoopAction.Continue)

    def test_retry_budget_exhausts_to_core_failed(self) -> None:
        med = self._rejected_click_mediator()
        now = time.time()
        with patch.object(med, "act_click", return_value=True):
            med._maybe_click_hitch_pressure_transfer(_noise_frame(seed=31), now)
            self.assertFalse(med._hitch_pressure_core_failed)
            # 按钮始终可见 + 每次等待 ≥5s：retry 与重新 click 交替消耗 budget，
            # 第 5 次 retry request 耗尽（calls 2,4,6,8,10）。
            for i in range(9):
                now += 6.0
                res = med._maybe_click_hitch_pressure_transfer(_noise_frame(seed=32 + i), now)
                self.assertIs(res, LoopAction.Continue)
                if i < 8:
                    self.assertFalse(med._hitch_pressure_core_failed)
        self.assertTrue(med._hitch_pressure_core_failed, "bounded retry budget 耗尽 → core failed")
        self.assertFalse(med._hitch_pressure_transferred)

    def test_core_failed_blocks_optional_but_postgame_observable(self) -> None:
        clock = FakeClock(start=100.0)
        med = _hitch_mediator(clock)
        med.set_phase(Phase.MAIN_LINE, "core failed wait")
        med._hitch_pressure_core_failed = True
        frame = _noise_frame(seed=41)
        with patch.object(med, "_hitch_ocr_text", return_value=""), \
                patch.object(med, "_find_failure_gift", return_value=None), \
                patch.object(med, "_post_game_state", return_value=None), \
                patch.object(med, "_maybe_click_hitch_pressure_transfer") as gate:
            # 无 post-game：零输入等待 outcome；压力 gate 也不应再被推进
            self.assertIs(med._tick_main_line(frame), LoopAction.Continue)
            gate.assert_not_called()
            self.assertEqual(len(med.executor.action_ledger), 0, "optional actions 不放行")
        # POST_VICTORY 仍可观察/可路由：post-game 分类先于 core-failed 等待
        med.set_phase(Phase.MAIN_LINE, "core failed victory")
        with patch.object(med, "_hitch_ocr_text", return_value=""), \
                patch.object(med, "_find_failure_gift", return_value=None), \
                patch.object(med, "_post_game_state", return_value="POST_VICTORY"), \
                patch.object(med, "_maybe_click_hitch_pressure_transfer") as gate, \
                patch.object(med, "find", return_value=_hit("continueGame", 800, 560)):
            self.assertIs(med._tick_main_line(frame), LoopAction.Continue)
            gate.assert_not_called()
        continue_clicks = [r for r in med.executor.action_ledger if r.method == "click"]
        self.assertEqual(len(continue_clicks), 1, "POST_VICTORY 链路仍产生 ContinueGame 输入")
        self.assertTrue(med._post_game_pending)


class G0MainLineOrderingTests(unittest.TestCase):
    """契约 #4：postgame 分类先于压力 gate。"""

    def test_postgame_state_computed_before_pressure_gate(self) -> None:
        med = _hitch_mediator(FakeClock(start=100.0))
        med.set_phase(Phase.MAIN_LINE, "ordering")
        frame = _noise_frame(seed=51)
        order: list[str] = []

        with patch.object(med, "_hitch_ocr_text", return_value=""), \
                patch.object(med, "_find_failure_gift", return_value=None), \
                patch.object(med, "_post_game_state", side_effect=lambda _f: order.append("post_game") or None), \
                patch.object(med, "_maybe_click_hitch_pressure_transfer", side_effect=lambda _f, _n: order.append("gate") or LoopAction.Continue):
            self.assertIs(med._tick_main_line(frame), LoopAction.Continue)
        self.assertEqual(order, ["post_game", "gate"], "postgame 分类必须在压力 gate 之前")


class G0GlobalPreemptionTests(unittest.TestCase):
    """契约 #3：强失败/断线全局抢占不被压力 gate 遮蔽。"""

    def _preempt_run(self, scene: str, scene_hit: MatchResult) -> Mediator:
        clock = FakeClock(start=100.0)
        med = _hitch_mediator(clock)
        med.set_phase(Phase.MAIN_LINE, "pressure preempt")
        med._capture_best = lambda *a, **k: _noise_frame(seed=61)
        patches = _pressure_tick_patches(med, None)

        def find_scene(_f, key, **_k):
            return scene_hit if key == scene else None

        with clock.install(), _Ctx(patches), \
                patch.object(med, "find_scene", side_effect=find_scene):
            # 两帧强证据 → 抢占进 RECOVER_FAILURE，而非压力 gate Continue 拖住
            clock.set(100.5)
            self.assertIs(med.tick(), LoopAction.Continue)
            clock.set(100.9)
            self.assertIs(med.tick(), LoopAction.Continue)
        return med

    def test_strong_fail_preempts_despite_unconfirmed_pressure(self) -> None:
        med = self._preempt_run("fail", _hit("fail"))
        self.assertIs(med.phase, Phase.RECOVER_FAILURE, "强失败抢占进入恢复，而非压力 Continue")
        self.assertIsNotNone(med._recovery_state)
        self.assertEqual(med._recovery_state.kind, RecoveryKind.FAIL)
        self.assertEqual(len(med.executor.action_ledger), 0, "抢占帧零业务输入")

    def test_disconnect_preempts_despite_unconfirmed_pressure(self) -> None:
        med = self._preempt_run("disconnect", _hit("gameDisconnect"))
        self.assertIs(med.phase, Phase.RECOVER_FAILURE, "断线抢占进入恢复，而非压力 Continue")
        self.assertEqual(med._recovery_state.kind, RecoveryKind.DISCONNECT)
        self.assertEqual(len(med.executor.action_ledger), 0)


class G0LeaveOldRoomTests(unittest.TestCase):
    """契约 #5：同房返回证明 → leave-old-room episode；fresh room-list authority 才 PLATFORM_MAP。"""

    def _farm_mediator(self, clock: FakeClock) -> Mediator:
        med = Mediator(Settings(dry_run=False, auto_create_room=True, query_timeout=30), ROOT)
        med.executor = FakeInputExecutor(StopSignal(), clock)
        med._capture_best = lambda *a, **k: _noise_frame(seed=73)
        return med

    def test_same_room_return_proof_enters_leave_old_room_episode(self) -> None:
        clock = FakeClock(start=100.0)
        med = self._farm_mediator(clock)
        med.set_phase(Phase.STAGE_SELECT, "round 1")
        med.set_phase(Phase.MAIN_LINE, "round 1")
        med._record_round_outcome(RoundOutcome.VICTORY, "round 1 victory chain verified")
        med._awaiting_room_return = True
        med.set_phase(Phase.PREPARE, "exit confirmed")
        with clock.install(), patch.object(med, "_find_room_start", return_value=_hit("room_start", 700, 500)):
            clock.set(100.5)
            med.tick()
        self.assertEqual(med.game_count, 1)
        self.assertIs(med.phase, Phase.PREPARE, "同房证明后进入 leave-old-room episode")
        self.assertTrue(med._room_leave_pending)
        self.assertNotEqual(med.phase, Phase.ROOM_WAITING)

    def test_fresh_room_list_authority_advances_to_platform_map(self) -> None:
        clock = FakeClock(start=100.0)
        med = self._farm_mediator(clock)
        med._room_leave_pending = True
        frame = _noise_frame(seed=71)
        with patch.object(med, "_lobby_room_list_evidence", return_value=True), \
                patch.object(med, "_find_room_start", return_value=None):
            res = med._tick_leave_old_room(frame, None, now=time.time())
        self.assertIs(res, LoopAction.Continue)
        self.assertIs(med.phase, Phase.PLATFORM_MAP, "fresh room-list authority 后才进 PLATFORM_MAP")
        self.assertFalse(med._room_leave_pending)

    def test_without_authority_single_request_then_fail_closed_timeout(self) -> None:
        clock = FakeClock(start=100.0)
        med = self._farm_mediator(clock)
        med._room_leave_pending = True
        med.set_phase(Phase.PREPARE, "leaving old room")
        frame = _noise_frame(seed=72)
        clicks: list[str] = []
        with patch.object(med, "_lobby_room_list_evidence", return_value=False), \
                patch.object(med, "_find_room_start", return_value=None), \
                patch.object(med, "_hitch_action_hit", return_value=_hit("lobby_home")), \
                patch.object(med, "act_click", side_effect=lambda _h, reason="": clicks.append(reason) or True):
            now = time.time()
            res = med._tick_leave_old_room(frame, None, now=now)
            self.assertIs(res, LoopAction.Continue)
            self.assertEqual(clicks, ["LeaveOldRoom"], "只发一次离房 request")
            self.assertTrue(med._room_leave_pending, "click success 不构成已离房")
            self.assertNotEqual(med.phase, Phase.PLATFORM_MAP, "无 authority 不盲转")
            # 冷却期内零输入
            res2 = med._tick_leave_old_room(frame, None, now=now + 1.0)
            self.assertIs(res2, LoopAction.Continue)
            self.assertEqual(clicks, ["LeaveOldRoom"], "冷却期内零输入")
            # 超时 Fail-Closed：保持安全等待，不创建新房
            med._room_action_deadline = time.time() - 1.0
            res3 = med._tick_leave_old_room(frame, None, now=now + 2.0)
            self.assertIs(res3, LoopAction.Continue)
        self.assertEqual(clicks, ["LeaveOldRoom"], "超时不产生更多输入")
        self.assertFalse(med._room_leave_pending)
        self.assertIs(med.phase, Phase.LOBBY_ROOM, "超时保持手动房等待语义")


class G0ArchaeologyHandoffTests(unittest.TestCase):
    """契约 #6：click 仅 request；fresh generation kaogu 锚点才 COMPLETE。"""

    def _arch_mediator(self) -> Mediator:
        return Mediator(Settings(dry_run=True, auto_archaeology=True), ROOT)

    def test_click_is_request_only_until_fresh_anchor(self) -> None:
        med = self._arch_mediator()
        frame1 = _noise_frame(seed=81)
        clicks: list[str] = []
        with patch.object(med, "find", return_value=None), \
                patch.object(med, "act_click", side_effect=lambda _h, reason="": clicks.append(reason) or True):
            # cycle 完成 handoff：首次调用即发 request
            med._archaeology_handoff_pending = True
            self.assertIs(med._maybe_switch_to_archaeology(frame1), LoopAction.Continue)
            self.assertEqual(clicks, ["SwitchToArchaeology"], "click 仅 request")
            self.assertIsNotNone(med._archaeology_click_at)
            self.assertFalse(med._archaeology_handoff_confirmed, "click success 不构成完成")
            self.assertNotEqual(med.phase, Phase.COMPLETE)
            # 同帧同 generation：不确认
            self.assertIs(med._maybe_switch_to_archaeology(frame1), LoopAction.Continue)
            self.assertFalse(med._archaeology_handoff_confirmed, "同帧不确认")
            self.assertEqual(clicks, ["SwitchToArchaeology"], "等待期零重复点击")
        # fresh generation + kaogu 锚点 → COMPLETE + handoff
        frame2 = _noise_frame(seed=82)
        with patch.object(med, "find", return_value=None), \
                _Ctx([patch.object(med, "_archaeology_mode_anchor", return_value=_hit("kaogu"))]):
            self.assertIs(med._maybe_switch_to_archaeology(frame2), LoopAction.Break)
        self.assertTrue(med._archaeology_handoff_confirmed)
        self.assertIs(med.phase, Phase.COMPLETE)
        self.assertEqual(med._classify_run_exit(), RunExitReason.ARCHAEOLOGY_HANDOFF_COMPLETE)

    def test_fresh_frame_without_anchor_waits_zero_action(self) -> None:
        med = self._arch_mediator()
        frame1 = _noise_frame(seed=83)
        clicks: list[str] = []
        with patch.object(med, "find", return_value=None), \
                patch.object(med, "act_click", side_effect=lambda _h, reason="": clicks.append(reason) or True), \
                _Ctx([patch.object(med, "_archaeology_mode_anchor", return_value=None)]):
            med._archaeology_handoff_pending = True
            med._maybe_switch_to_archaeology(frame1)
            # fresh 帧但锚点未出现：零动作等待（click success 单独不构成成功）
            frame2 = _noise_frame(seed=84)
            self.assertIs(med._maybe_switch_to_archaeology(frame2), LoopAction.Continue)
            self.assertFalse(med._archaeology_handoff_confirmed)
            self.assertNotEqual(med.phase, Phase.COMPLETE)
            self.assertEqual(clicks, ["SwitchToArchaeology"], "等待期零重复点击")

    def test_confirmation_timeout_fails_closed(self) -> None:
        med = self._arch_mediator()
        frame1 = _noise_frame(seed=85)
        clicks: list[str] = []
        with patch.object(med, "find", return_value=None), \
                patch.object(med, "act_click", side_effect=lambda _h, reason="": clicks.append(reason) or True), \
                _Ctx([patch.object(med, "_archaeology_mode_anchor", return_value=None)]):
            med._archaeology_handoff_pending = True
            med._maybe_switch_to_archaeology(frame1)
            # 30s 有界窗口内等待
            frame2 = _noise_frame(seed=86)
            med._archaeology_click_at = time.time() - 20.0
            self.assertIs(med._maybe_switch_to_archaeology(frame2), LoopAction.Continue)
            self.assertNotEqual(med.phase, Phase.ERROR, "30s 内不得提前 fail-closed")
            # 超过 30s 无锚点 → Fail-Closed ERROR
            med._archaeology_click_at = time.time() - 31.0
            self.assertIs(med._maybe_switch_to_archaeology(frame2), LoopAction.Break)
        self.assertEqual(clicks, ["SwitchToArchaeology"], "超时路径零额外输入")
        self.assertIs(med.phase, Phase.ERROR)
        self.assertFalse(med._archaeology_handoff_confirmed)
        self.assertEqual(med._classify_run_exit(), RunExitReason.FATAL_ENVIRONMENT_FAILURE)


class G0ExitAttributionTests(unittest.TestCase):
    """契约 #7：终止归因锚点 + 外部 StopSignal reason 保留。"""

    def test_classify_run_exit_anchors(self) -> None:
        med = Mediator(Settings(dry_run=True), ROOT)
        self.assertIsNone(med.exit_reason, "run 前无归因")
        med.phase = Phase.MAIN_LINE
        self.assertEqual(med._classify_run_exit(), RunExitReason.UNEXPECTED_TERMINATION)
        med.phase = Phase.ERROR
        self.assertEqual(med._classify_run_exit(), RunExitReason.FATAL_ENVIRONMENT_FAILURE)
        med.phase = Phase.COMPLETE
        self.assertEqual(med._classify_run_exit(), RunExitReason.CONFIGURED_CYCLE_COMPLETE)
        med.phase = Phase.MAIN_LINE
        med._archaeology_handoff_confirmed = True
        self.assertEqual(med._classify_run_exit(), RunExitReason.ARCHAEOLOGY_HANDOFF_COMPLETE)

    def test_external_stop_reason_preserved_and_stop_never_overrides(self) -> None:
        med = Mediator(Settings(dry_run=True), ROOT)
        # 外部用户 stop（RunnerService/UI）
        med.stop_signal.trigger("RunnerService.stop requested")
        med.stop()
        self.assertEqual(med.stop_signal.reason, "RunnerService.stop requested", "stop 不覆盖外部 reason")
        self.assertEqual(med._classify_run_exit(), RunExitReason.USER_STOP)
        # F12 / Shift+F12 → EMERGENCY_STOP
        for reason in ("F12 emergency stop", "Shift+F12 emergency stop"):
            sig = StopSignal()
            sig.trigger(reason)
            med2 = Mediator(Settings(dry_run=True), ROOT, stop_signal=sig)
            med2.stop()
            self.assertEqual(med2.stop_signal.reason, reason)
            self.assertEqual(med2._classify_run_exit(), RunExitReason.EMERGENCY_STOP)
        # 无外部 stop 时 Mediator.stop() 才写信号
        med3 = Mediator(Settings(dry_run=True), ROOT)
        med3.stop()
        self.assertEqual(med3.stop_signal.reason, "Mediator.stop()")

    def test_run_records_process_crash_and_reraises(self) -> None:
        med = Mediator(Settings(dry_run=True), ROOT)
        med._capture_best = lambda *a, **k: _noise_frame(seed=91)
        with patch("shuabao.mediator.find_window_targets", return_value=[]), \
                patch.object(med, "tick", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                med.run()
        self.assertEqual(med.exit_reason, RunExitReason.PROCESS_CRASH, "未捕获异常 → PROCESS_CRASH 归因后原样上抛")


class G0ObservableFieldTests(unittest.TestCase):
    """契约 #8：round_elapsed / exit_reason / window snapshot 可读字段语义。"""

    def test_round_elapsed_semantics(self) -> None:
        med = Mediator(Settings(dry_run=True), ROOT)
        self.assertIsNone(med.round_elapsed, "局未开始时为 None")
        med._round_started_at = time.time() - 5.0
        self.assertIsNotNone(med.round_elapsed)
        self.assertAlmostEqual(med.round_elapsed, 5.0, delta=1.5, msg="本局已进行秒数语义正确")
        med._round_started_at = time.time() + 10.0
        self.assertEqual(med.round_elapsed, 0.0, "clock skew 下不出现负数")

    def test_window_snapshot_and_last_action_fields(self) -> None:
        med = Mediator(Settings(dry_run=True), ROOT)
        self.assertEqual(med.game_platform_window_snapshot, {})
        self.assertIsNone(med.last_window_role)
        self.assertIsNone(med.last_window_hwnd)
        self.assertIsNone(med.last_business_action)
        # see() 记录最后窗口 role/HWND 快照
        frame = _noise_frame(hwnd=4242)
        med._capture_best = lambda *a, **k: frame
        med.see("snapshot")
        self.assertEqual(med.last_window_hwnd, 4242)
        self.assertIn(med.last_window_role, ("l0", "l1"))
        # 窗口存在性快照（游戏在、平台不在）
        def fake_targets(title, role=None, **_k):
            return [object()] if role == "l1" else []

        with patch("shuabao.mediator.find_window_targets", side_effect=fake_targets):
            med._snapshot_window_existence()
        self.assertEqual(med.game_platform_window_snapshot, {"game": True, "platform": False})
        # 最近业务动作可读（输入 reason 即动作名）
        med.executor = FakeInputExecutor(StopSignal(), FakeClock(start=100.0))
        self.assertTrue(med.act_click(_hit("x"), "G0TestAction"))
        self.assertEqual(med.last_business_action, "G0TestAction")
        # 最近恢复动作有界列表
        med._begin_recovery(RecoveryKind.FAIL)
        self.assertTrue(med.recent_recovery_actions[-1].startswith("FAIL:start:"))
        for _ in range(30):
            med.recent_recovery_actions.append("FAIL:start:1")
        med._begin_recovery(RecoveryKind.FAIL)
        self.assertLessEqual(len(med.recent_recovery_actions), 20, "恢复动作列表 fail-closed bounded")


class G0UnhealthyHitchTests(unittest.TestCase):
    """契约 #9：unhealthy hitch 双窗失 / 单窗失 + fresh 权威 / 零业务输入。"""

    def _black(self) -> Frame:
        return Frame(np.zeros((900, 1600, 3), dtype=np.uint8), window_title="英雄三国KK", hwnd=1)

    def _unhealthy_mediator(self) -> Mediator:
        med = Mediator(Settings(dry_run=False, mode_id="lobby_hitch", query_timeout=30), ROOT)
        med.executor = FakeInputExecutor(StopSignal(), FakeClock(start=100.0))
        med.set_phase(Phase.MAIN_LINE, "unhealthy hitch")
        med.see = lambda reason="": self._black()
        return med

    def test_both_windows_missing_fails_closed(self) -> None:
        med = self._unhealthy_mediator()
        med._missing_window_since = time.time() - 40.0
        with patch("shuabao.mediator.find_window_targets", return_value=[]):
            self.assertIs(med.tick(), LoopAction.Break)
        self.assertIs(med.phase, Phase.ERROR, "游戏/平台窗口均不存在超过边界 → Fail-Closed")
        self.assertEqual(med._classify_run_exit(), RunExitReason.FATAL_ENVIRONMENT_FAILURE)
        self.assertEqual(len(med.executor.action_ledger), 0, "unhealthy 期间零业务输入")

    def test_game_missing_fresh_platform_room_list_returns_lobby(self) -> None:
        med = self._unhealthy_mediator()
        med._missing_window_since = time.time() - 40.0
        platform_frame = _noise_frame(seed=95)

        def fake_targets(title, role=None, **_k):
            return [object()] if role == "l0" else []

        def capture(title, role, **_k):
            return platform_frame if role == "l0" else self._black()

        med._capture_best = capture
        with patch("shuabao.mediator.find_window_targets", side_effect=fake_targets), \
                patch.object(med, "_lobby_room_list_evidence", return_value=True):
            self.assertIs(med.tick(), LoopAction.Continue)
        self.assertIs(med.phase, Phase.LOBBY_ROOM, "游戏窗消失但平台房间列表 fresh 权威成立 → 回大厅")
        self.assertIsNone(med._missing_window_since)
        self.assertEqual(len(med.executor.action_ledger), 0, "handoff 零业务输入")

    def test_below_bound_keeps_observing_without_input(self) -> None:
        med = self._unhealthy_mediator()
        med._missing_window_since = time.time() - 5.0
        with patch("shuabao.mediator.find_window_targets", return_value=[]):
            self.assertIs(med.tick(), LoopAction.Continue, "边界内只撤销输入权继续观察")
        self.assertIs(med.phase, Phase.MAIN_LINE, "不得盲目改阶段")
        self.assertEqual(len(med.executor.action_ledger), 0)


class G0CycleCompleteArchaeologyEndToEndTests(unittest.TestCase):
    """Stage1 P1-1 回归：cycle-complete 考古 handoff 端到端（真实 med.tick()）。

    从真实状态（PREPARE、_awaiting_room_return、room_start 可见、game_count+1
    达成 cycle_num、auto_archaeology on）驱动：
    - 同房证明 → 考古 handoff 接管（S0⑥：绝不点下一局开始）；
    - ROOM_WAITING 内 room_start 仍可见时零输入，绝不出现 RoomStart 点击；
    - 选关页出现后进入考古 request/confirm 路由（click 仅 request，
      fresh kaogu 锚点前不得归因完成）。
    """

    def _load(self, relative_path: str, title: str = "英雄三国") -> Frame:
        path = ROOT / relative_path
        image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertIsNotNone(image, path)
        return Frame(image, window_title=title, hwnd=10001)

    def test_cycle_complete_handoff_never_roomstart_then_archaeology_request(self) -> None:
        med = Mediator(
            Settings(dry_run=False, cycle_num=1, auto_archaeology=True, query_timeout=60),
            ROOT,
        )
        med.executor = FakeInputExecutor(StopSignal(), FakeClock(start=100.0))
        room = self._load("fixtures/replay/room_waiting_host.png", "KK官方对战平台")
        stage = self._load("fixtures/live_postgame_20260808/live_stage_select.png")
        frames = iter([room, room, stage, stage])
        med.see = lambda reason="": next(frames)
        clicks: list[str] = []
        med.act_click = lambda hit, reason="": clicks.append(reason) or True
        med.set_phase(Phase.PREPARE, "exit confirmed; verify same room")
        med._awaiting_room_return = True

        with patch.object(med, "_find_room_start", return_value=_hit("room_start", 700, 500)):
            # tick 1：room_start 可见 → 同房证明 → cycle 达成 → 考古 handoff 接管
            self.assertIs(med.tick(), LoopAction.Continue)
            self.assertEqual(med.game_count, 1)
            self.assertTrue(med._archaeology_handoff_pending)
            self.assertIs(med.phase, Phase.ROOM_WAITING, "handoff 经既有选关路由，不立即停止")
            # tick 2：room_start 仍可见 → 必须零输入，绝不点 RoomStart（S0⑥）
            self.assertIs(med.tick(), LoopAction.Continue)
        self.assertNotIn("RoomStart", clicks, "handoff 期间绝不点下一局开始")
        self.assertEqual(clicks, [], "handoff 等待期零业务输入")
        self.assertIs(med.phase, Phase.ROOM_WAITING, "零输入等待，不盲转阶段")

        # tick 3：选关页自然出现 → 既有路由晋级 STAGE_SELECT
        self.assertIs(med.tick(), LoopAction.Continue)
        self.assertIs(med.phase, Phase.STAGE_SELECT)
        # tick 4：考古 request（click 仅 request，未确认不得 COMPLETE）
        self.assertIs(med.tick(), LoopAction.Continue)
        self.assertEqual(clicks, ["SwitchToArchaeology"], "票尽/cycle 完成共用同一 request 路由")
        self.assertFalse(med._archaeology_handoff_confirmed, "click success 不构成完成")
        self.assertNotEqual(med.phase, Phase.COMPLETE)
        self.assertIsNone(med.exit_reason, "fresh kaogu 锚点前不得归因考古完成")

    def test_handoff_stage_page_timeout_fails_closed_without_roomstart(self) -> None:
        med = Mediator(
            Settings(dry_run=False, cycle_num=1, auto_archaeology=True, query_timeout=60),
            ROOT,
        )
        med.executor = FakeInputExecutor(StopSignal(), FakeClock(start=100.0))
        room = self._load("fixtures/replay/room_waiting_host.png", "KK官方对战平台")
        med.see = lambda reason="": room
        clicks: list[str] = []
        med.act_click = lambda hit, reason="": clicks.append(reason) or True
        med.set_phase(Phase.PREPARE, "exit confirmed; verify same room")
        med._awaiting_room_return = True
        with patch.object(med, "_find_room_start", return_value=_hit("room_start", 700, 500)):
            self.assertIs(med.tick(), LoopAction.Continue)  # 同房证明 → handoff
            self.assertTrue(med._archaeology_handoff_pending)
            med._room_action_deadline = time.time() - 1.0  # 选关页始终不出现
            self.assertIs(med.tick(), LoopAction.Break, "有界：超时 Fail-Closed，不盲等")
        self.assertNotIn("RoomStart", clicks, "超时路径也绝不点下一局开始")
        self.assertIs(med.phase, Phase.ERROR)
        self.assertEqual(med._classify_run_exit(), RunExitReason.FATAL_ENVIRONMENT_FAILURE)


if __name__ == "__main__":
    unittest.main()
