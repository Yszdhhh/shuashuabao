"""N2.2/N2.3：FrameEvidence 同帧证据、失效规则、动作授权与主循环 cadence。

覆盖 Codex N2 方案：
- 同帧两次 context/anchor 查询只有一次 matcher 调用（evidence cache）；
- exact-static 同帧复用，但成功输入后必须重算且 stale generation 拒绝动作；
- hwnd/scale 变化无条件失效；配置差异不命中同一 key；
- 多窗口连续一帧失配不触发全量候选分类；
- 主循环 cadence 分级与 sleep=max(0, cadence-elapsed)；
- 无法解释 tick>1s 白名单的 reason 字段。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
_SRC = ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from shuabao.input.keyboard_mouse import ActionResult
from shuabao.mediator import Mediator, Phase
from shuabao.settings import Settings
from shuabao.stop_signal import StopSignal
from shuabao.vision.capture import Frame, WindowTarget

import shuabao.mediator as mediator_module


def _load(rel: str) -> Frame:
    p = ROOT / rel
    img = cv2.imdecode(np.frombuffer(p.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
    assert img is not None, f"cannot decode {p}"
    return Frame(img, window_title="英雄三国KK", hwnd=10001)


def _noise_frame(hwnd: int = 10001) -> Frame:
    rng = np.random.default_rng(42)
    img = rng.integers(0, 255, (540, 960, 3), dtype=np.uint8)
    return Frame(bgr=img, left=0, top=0, window_title="英雄三国KK", hwnd=hwnd, role="l1")


class FrameEvidenceTests(unittest.TestCase):
    """N2.2：同帧证据、generation 失效与动作授权。"""

    def setUp(self):
        self.settings = Settings()
        self.med = Mediator(self.settings, ROOT)

    def test_same_frame_two_context_queries_one_matcher_call(self):
        f = _load("fixtures/replay/main_line_auto_on.png")
        with patch("shuabao.vision.matcher.cv2.matchTemplate", wraps=cv2.matchTemplate) as mt:
            c1 = self.med._detect_context(f, role="l1")
            first_calls = mt.call_count
            c2 = self.med._detect_context(f, role="l1")
            self.assertEqual(mt.call_count, first_calls, "同帧第二次 context 不得重新匹配")
            a = self.med._selection_anchor(f)
            self.assertEqual(mt.call_count, first_calls, "同帧 anchor 查询必须复用 context 已算结果")
        self.assertEqual(c1, c2)
        self.assertEqual(c1, "MAIN_LINE")

    def test_exact_static_reuse_and_input_invalidation_forces_recompute_and_stale_rejection(self):
        f = _load("fixtures/replay/skill_choice_3.png")
        self.med._last_frame = f
        self.med.set_phase(Phase.MAIN_LINE, "evidence test")
        self.med._detect_context(f)  # 感知入口：建立本帧证据
        with patch("shuabao.vision.matcher.cv2.matchTemplate", wraps=cv2.matchTemplate) as mt:
            anchor = self.med._selection_anchor(f)
            self.assertIsNotNone(anchor)
            n1 = mt.call_count
            anchor2 = self.med._selection_anchor(f)
            self.assertIs(anchor, anchor2, "同帧 anchor 复用同一对象")
            self.assertEqual(mt.call_count, n1, "跨 tick 同帧（无输入）复用只读证据")

        # 成功输入（真实模式）：同一控制流内证据失效
        # 注：invalidate 就地推进 gen（保持 self._evidence is tick_evidence），
        # 因此期望值必须在点击前捕获。
        self.med.settings.dry_run = False
        ev_before = self.med._evidence
        expected_gen = ev_before.gen + 1
        self.med._tick_evidence = ev_before
        self.med._tick_gen = ev_before.gen
        with patch.object(
            self.med.executor, "click",
            return_value=ActionResult(success=True, status="SUCCESS", message="ok"),
        ) as click:
            ok = self.med.act_click(anchor, "evidence-test")
            self.assertTrue(ok)
            click.assert_called_once()
        self.assertEqual(self.med._evidence.gen, expected_gen, "输入成功后 generation 必须推进")
        self.assertIs(self.med._evidence, ev_before, "invalidate 就地推进 gen（不换对象）")
        self.assertEqual(len(self.med._evidence.cache), 0, "输入成功后缓存必须丢弃")

        # 同一控制流的第二次动作：stale generation 拒绝（零输入）
        with patch.object(
            self.med.executor, "click",
            return_value=ActionResult(success=True, status="SUCCESS", message="ok"),
        ) as click2:
            ok2 = self.med.act_click(anchor, "duplicate")
            self.assertFalse(ok2, "stale generation 动作必须被拒绝")
            click2.assert_not_called()

        # 相同对象再次进入（模拟下一 tick 静态复用）：必须重新计算
        with patch("shuabao.vision.matcher.cv2.matchTemplate", wraps=cv2.matchTemplate) as mt2:
            a3 = self.med._selection_anchor(f)
            self.assertIsNotNone(a3)
            self.assertGreater(mt2.call_count, 0, "输入失效后相同帧必须重算，不得沿用旧缓存")

    def test_hwnd_or_scale_change_invalidates_evidence(self):
        f = _load("fixtures/replay/main_line_auto_on.png")
        self.med._detect_context(f)
        ev1 = self.med._evidence
        self.assertIsNotNone(ev1)
        # ui_scale 变化（即使像素相同）→ 无条件失效
        gen_first = ev1.gen  # 捕获后再失效（invalidate 就地推进旧对象 gen）
        self.med._ui_scale = 0.6
        self.med._detect_context(f)
        ev2 = self.med._evidence
        self.assertIsNot(ev1, ev2)
        # invalidate（gen+1）后重建（再 +1）→ ev2.gen == 旧 gen + 2
        self.assertEqual(ev2.gen, gen_first + 2)
        self.assertGreater(ev2.gen, ev1.gen)
        self.assertEqual(len(ev1.cache), 0, "旧证据缓存必须被丢弃（不延续旧帧授权）")
        self.assertIsNot(ev1.cache, ev2.cache, "新证据必须持有全新缓存")
        # hwnd 变化 → 无条件失效
        self.med._ui_scale = 1.0
        self.med._detect_context(f)
        ev3 = self.med._evidence
        f2 = _load("fixtures/replay/main_line_auto_on.png")
        f2.hwnd = 20002
        self.med._detect_context(f2)
        ev4 = self.med._evidence
        self.assertIsNot(ev3, ev4)
        self.assertGreater(ev4.gen, ev3.gen)

    def test_config_difference_does_not_hit_same_key(self):
        f = _load("fixtures/replay/skill_choice_3.png")
        self.med._detect_context(f)  # 先建立本帧证据（memo 前提）
        with patch("shuabao.vision.matcher.cv2.matchTemplate", wraps=cv2.matchTemplate) as mt:
            a = self.med.find(f, ["skill_refresh_btn"], threshold=0.70, roi=(0.2, 0.45, 0.8, 0.8))
            self.assertIsNotNone(a)
            n1 = mt.call_count
            # 不同阈值 → 不命中同一 key
            b = self.med.find(f, ["skill_refresh_btn"], threshold=0.75, roi=(0.2, 0.45, 0.8, 0.8))
            self.assertIsNotNone(b)
            self.assertGreater(mt.call_count, n1)
            n2 = mt.call_count
            # 相同参数 → 命中
            c = self.med.find(f, ["skill_refresh_btn"], threshold=0.70, roi=(0.2, 0.45, 0.8, 0.8))
            self.assertEqual(mt.call_count, n2, "相同配置必须命中同一缓存 key")
            # 不同 ROI → 不命中
            d = self.med.find(f, ["skill_refresh_btn"], threshold=0.70, roi=(0.2, 0.5, 0.8, 0.8))
            self.assertGreater(mt.call_count, n2, "ROI 差异不得命中同一 key")

    def test_multi_window_single_unhealthy_frame_does_not_trigger_full_candidate_classification(self):
        med = Mediator(Settings(), ROOT)
        med._last_capture_role = "l1"
        med._last_frame = _noise_frame(hwnd=101)
        targets = [
            WindowTarget(hwnd=101, title="游戏A", left=0, top=0, width=1600, height=900, role="l1"),
            WindowTarget(hwnd=202, title="游戏B", left=0, top=0, width=1600, height=900, role="l1"),
        ]

        def fake_capture(t: WindowTarget) -> Frame:
            if t.hwnd == 101:
                return Frame(bgr=None, hwnd=101, is_valid=False, error="capture failed")
            return _noise_frame(hwnd=202)

        with patch("shuabao.mediator.find_window_targets", return_value=targets), \
             patch("shuabao.mediator.capture_target", side_effect=fake_capture) as ct, \
             patch.object(med, "_frame_signal", return_value=60) as fs:
            frame = med._capture_best("英雄三国KK", "l1")
            self.assertEqual(ct.call_count, 1, "连续第 1 帧失配只抓上次健康 hwnd，不枚举候选")
            self.assertEqual(fs.call_count, 0, "未枚举候选时不得做完整分类")
            self.assertFalse(frame.is_valid)

            # 连续第 2 帧失配（N=2）→ 才枚举候选并分类
            med._capture_best("英雄三国KK", "l1")
            # 一个 HWND 每次 _capture_best 只抓一次：第 2 帧抓 101（上次 hwnd）
            # 与 202（枚举新增），101 的枚举命中 memo 不再重复抓屏。
            self.assertEqual(ct.call_count, 3, "第 2 帧失配：上次 hwnd + 候选枚举，每 HWND 仅 1 次")
            self.assertGreater(fs.call_count, 0, "枚举时才做分类排序")

    def test_frame_evidence_holds_strong_frame_reference(self):
        f = _noise_frame()
        self.med._detect_context(f)
        ev = self.med._evidence
        self.assertIs(ev.frame_ref, f, "evidence 必须强引用帧，不能只依赖 id(frame)")
        import gc
        gc.collect()
        self.assertIs(ev.frame_ref, f)


class CadenceTests(unittest.TestCase):
    """N2.3：主循环 cadence 分级与 sleep=max(0, cadence-elapsed)。"""

    def setUp(self):
        self.med = Mediator(Settings(), ROOT)

    def test_cadence_table(self):
        # 成功输入后 → 100ms 短观察窗
        self.med._tick_input_executed = True
        self.assertEqual(self.med._cadence_for_current_state(), 0.100)
        # 稳定健康 HUD → 300ms（先脱离 BOOT 档）
        self.med._tick_input_executed = False
        self.med.phase = Phase.MAIN_LINE
        self.med._context_cache_value = "MAIN_LINE"
        self.assertEqual(self.med._cadence_for_current_state(), 0.300)
        # UNKNOWN / FAIL 候选 → 300ms 或更快（不放慢到 loading）
        self.med._context_cache_value = "UNKNOWN"
        self.assertEqual(self.med._cadence_for_current_state(), 0.300)
        # loading / 窗口转场 → 500ms
        self.med._context_cache_value = "MAIN_LINE"
        self.med.phase = Phase.ROOM_STARTING
        self.assertEqual(self.med._cadence_for_current_state(), 0.500)
        self.med.phase = Phase.MAIN_LINE
        # 非静态不健康等待 → 500ms
        self.med._last_health = None
        med2 = Mediator(Settings(), ROOT)
        from shuabao.vision.capture import FrameHealthResult, FrameHealthIssue
        med2._last_health = FrameHealthResult(is_healthy=False, issues=[FrameHealthIssue.BLACK_FRAME])
        med2._context_cache_value = "MAIN_LINE"
        self.assertEqual(med2._cadence_for_current_state(), 0.500)

    def test_run_loop_sleeps_cadence_minus_elapsed(self):
        settings = Settings()
        # cadence 数学与输入模式无关；钉住 dry_run 避免落入提权守卫（1d8f101 翻默认后）。
        settings.dry_run = True
        med = Mediator(settings, ROOT)
        frame = _noise_frame()
        med._capture_best = lambda *a, **k: frame
        # f401a3b 起 tick() 内部（auto_task fuse 等）也会读 time.monotonic，
        # 固定 4 值脚本会被额外读数打穿；改为无限递增假时钟（每次 +0.01s），
        # 只锁定不变量：两 tick 之间恰好 sleep 一次，且 sleep = cadence - elapsed。
        mono_state = {"now": 100.0}

        def fake_monotonic() -> float:
            value = mono_state["now"]
            mono_state["now"] += 0.01
            return value

        sleeps: list[float] = []

        class _NoopListener:
            def __init__(self, *a, **k):
                pass

            def start(self):
                pass

            def stop(self):
                pass

        with patch("shuabao.mediator.time.monotonic", side_effect=fake_monotonic), \
             patch("shuabao.mediator.time.sleep", side_effect=lambda s: sleeps.append(s)), \
             patch("shuabao.mediator.EmergencyStopListener", _NoopListener), \
             patch.object(med, "stop") as stop:
            med.run(max_steps=2)
            stop.assert_not_called()

        # run() 启动时的 find_window_targets 窗口扫描会产生 0.05s×n 的内部
        # sleep（全局 time 模块被 patch 波及）；只对 cadence 级 sleep（>0.2s）
        # 断言：恰好一次，且 = 稳定 HUD cadence 300ms - tick 内少量耗时。
        cadence_sleeps = [x for x in sleeps if x > 0.2]
        self.assertEqual(len(cadence_sleeps), 1)
        self.assertGreater(cadence_sleeps[0], 0.25)
        self.assertLessEqual(cadence_sleeps[0], 0.30)
        self.assertEqual(med.game_count, 0)


class TickReasonWhitelistTests(unittest.TestCase):
    """无法解释 tick>1s=0 白名单：reason 字段写入 trace 并可判定。"""

    def test_tick_trace_carries_reason_and_evidence_gen(self):
        import json
        import tempfile
        from tests.test_scenario_replay import FakeClock, FakeInputExecutor

        with tempfile.TemporaryDirectory() as tmp:
            trace_path = str(Path(tmp) / "trace.jsonl")
            clock = FakeClock(start=10.0)
            stop_signal = StopSignal()
            with clock.install(), patch(
                "shuabao.mediator.time.perf_counter", return_value=100.0
            ):
                med = Mediator(Settings(), ROOT, stop_signal=stop_signal)
                med.executor = FakeInputExecutor(stop_signal, clock)
                src = _StageSource()
                med._capture_best = src.capture_best
                med.set_phase(Phase.STAGE_SELECT, "trace test")
                med.set_trace(trace_path)
                med.tick()
                med.set_trace(None)
            row = json.loads(Path(trace_path).read_text(encoding="utf-8").strip().splitlines()[0])
            self.assertIn("reason", row, "trace 必须携带 >1s 白名单 reason 字段")
            self.assertIn("evidence_gen", row, "trace 必须携带 evidence generation")
            # STAGE_SELECT 常规 tick：无白名单原因 → None
            self.assertIsNone(row["reason"])

    def test_capture_wait_reason_when_capture_exceeds_800ms(self):
        med = Mediator(Settings(), ROOT)
        frame = _noise_frame()
        med._capture_best = lambda *a, **k: frame
        with patch("shuabao.mediator.time.perf_counter", side_effect=[0.0, 0.9, 0.9, 1.0]):
            # see() 捕获计时 900ms → reason=capture_wait
            med._tick_reason = None
            med.see("slow-capture-test")
        self.assertEqual(med._tick_reason, "capture_wait")

    def test_whitelist_classifier_counts_unexplained(self):
        from tools.audit_tick_trace import classify_tick

        slow_ticks = [
            {"elapsed_ms": 1200.0, "reason": "capture_wait"},
            # N2-REVIEW #2：input_executor_wait 必须有 action_ms>=800 的成功输入
            {"elapsed_ms": 1500.0, "reason": "input_executor_wait",
             "actions": [{"intent": "click:x", "action_ms": 812.0}]},
            {"elapsed_ms": 1100.0, "reason": "incident_write"},
            {"elapsed_ms": 1300.0, "reason": "debug_trace_io"},
            {"elapsed_ms": 2000.0, "reason": "external_pause"},
            {"elapsed_ms": 900.0, "reason": None},
            {"elapsed_ms": 1400.0, "reason": None},  # 无法解释
            # 只写 reason、无 ≥800ms 动作（dry-run/短点击假绿）→ 无法解释
            {"elapsed_ms": 1600.0, "reason": "input_executor_wait",
             "actions": [{"intent": "click:x", "action_ms": 12.0}]},
            {"elapsed_ms": 1700.0, "reason": "input_executor_wait", "actions": []},
        ]
        buckets: dict[str, int] = {}
        unexplained = 0
        for t in slow_ticks:
            verdict = classify_tick(t)
            if verdict == "unexplained":
                unexplained += 1
            buckets[verdict] = buckets.get(verdict, 0) + 1
        self.assertEqual(unexplained, 3, "只写 reason 的 input_executor_wait 必须按无法解释处理")
        self.assertEqual(buckets.get("ok"), 1)
        self.assertEqual(buckets.get("input_executor_wait"), 1, "有 ≥800ms 动作才白名单")
        self.assertEqual(buckets.get("capture_wait"), 1)


class _StageSource:
    """trace 测试用帧源（STAGE_SELECT 场景帧）。"""

    def __init__(self) -> None:
        img = cv2.imdecode(
            np.frombuffer(
                (ROOT / "tests/performance/fixtures/stage_select.png").read_bytes(), np.uint8
            ),
            cv2.IMREAD_COLOR,
        )
        self._frame = Frame(img, window_title="英雄三国KK", hwnd=10001)

    def capture_best(self, *a, **k) -> Frame:
        return self._frame


class ReviewFixTests(unittest.TestCase):
    """N2-REVIEW 六项修复的回归测试（随 N2.4 交付）。"""

    def setUp(self):
        self.med = Mediator(Settings(), ROOT)

    # #3 dry-run 成功输入也走输入序列授权（LIVE/OBSERVE 语义等价）
    def test_dry_run_successful_input_advances_input_seq_and_blocks_second_action(self):
        from shuabao.vision.matcher import MatchResult

        f = _load("fixtures/replay/skill_choice_3.png")
        self.med._last_frame = f
        self.med.set_phase(Phase.MAIN_LINE, "evidence test")
        self.med.settings.dry_run = True
        self.med._detect_context(f)
        anchor = self.med._selection_anchor(f)
        self.assertIsNotNone(anchor)
        ev = self.med._evidence
        gen_before = ev.gen
        self.med._tick_evidence = ev
        self.med._tick_gen = ev.gen
        self.med._tick_input_seq = self.med._input_seq
        with patch.object(self.med.executor, "click", return_value=ActionResult(success=True, status="DRY_RUN")):
            ok = self.med.act_click(anchor, "dry-run-test")
            self.assertTrue(ok)
        self.assertEqual(ev.gen, gen_before, "dry-run 不推进 evidence gen（保留 exact-static 性能复用）")
        self.assertGreater(self.med._input_seq, 0, "dry-run 成功输入必须推进输入序列")
        with patch.object(self.med.executor, "click", return_value=ActionResult(success=True, status="DRY_RUN")) as c2:
            ok2 = self.med.act_click(anchor, "duplicate")
            self.assertFalse(ok2, "同 tick 第二次动作必须被输入序列门禁拒绝（dry-run 亦同）")
            c2.assert_not_called()

    # #2 input_executor_wait 只给真实 ≥800ms 输入
    def test_finish_input_reason_only_for_real_slow_action(self):
        res_ok = ActionResult(success=True, status="DRY_RUN")
        self.med.settings.dry_run = True
        self.med._tick_reason = None
        self.med._finish_input(res_ok, "x", action_ms=900.0)
        self.assertIsNone(self.med._tick_reason, "dry-run 点击不得标 input_executor_wait")
        self.med.settings.dry_run = False
        self.med._tick_reason = None
        self.med._finish_input(res_ok, "y", action_ms=50.0)
        self.assertIsNone(self.med._tick_reason, "真实短点击不得标 input_executor_wait")
        self.med._tick_reason = None
        self.med._finish_input(res_ok, "z", action_ms=812.0)
        self.assertEqual(self.med._tick_reason, "input_executor_wait", "真实 ≥800ms 输入才白名单")

    # #5 loading cadence 不被 loop_sleep_ms 上限压缩
    def test_loading_cadence_not_compressed_by_loop_sleep_ms(self):
        settings = Settings()
        # 同上：cadence 数学与输入模式无关，钉住 dry_run。
        settings.dry_run = True
        med = Mediator(settings, ROOT)
        frame = _noise_frame()
        med._capture_best = lambda *a, **k: frame
        med.set_phase(Phase.ROOM_STARTING, "loading")
        med._context_cache_value = "MAIN_LINE"  # loading 档判定不依赖 UNKNOWN 快捷档
        # f401a3b 起 tick() 内部（auto_task fuse 等）也会读 time.monotonic，
        # 固定 4 值脚本会被额外读数打穿；改为无限递增假时钟（每次 +0.01s），
        # 只锁定不变量：两 tick 之间恰好 sleep 一次，且 sleep = cadence - elapsed。
        mono_state = {"now": 100.0}

        def fake_monotonic() -> float:
            value = mono_state["now"]
            mono_state["now"] += 0.01
            return value

        sleeps: list[float] = []

        class _NoopListener:
            def __init__(self, *a, **k):
                pass

            def start(self):
                pass

            def stop(self):
                pass

        with patch("shuabao.mediator.time.monotonic", side_effect=fake_monotonic), \
             patch("shuabao.mediator.time.sleep", side_effect=lambda s: sleeps.append(s)), \
             patch("shuabao.mediator.EmergencyStopListener", _NoopListener), \
             patch.object(med, "set_phase", lambda phase, note="": None), \
             patch.object(med, "_detect_context", return_value="MAIN_LINE"), \
             patch.object(med, "stop") as stop:
            med.run(max_steps=2)
            stop.assert_not_called()
        # 同上：过滤掉窗口扫描的 0.05s 内部 sleep，只断言 cadence 级 sleep。
        # 关键不变量：loading 档 500ms 不被 loop_sleep_ms=400ms 上限压缩（>0.45）。
        cadence_sleeps = [x for x in sleeps if x > 0.2]
        self.assertEqual(len(cadence_sleeps), 1)
        self.assertGreater(cadence_sleeps[0], 0.45)
        self.assertLessEqual(cadence_sleeps[0], 0.50)

    # #4 HERO_SETUP 也建立 evidence（hero 点击链受 generation 门禁）
    def test_hero_setup_establishes_evidence_for_generation_gating(self):
        med = Mediator(Settings(), ROOT)
        f = _noise_frame()
        med._capture_best = lambda *a, **k: f
        med.set_phase(Phase.HERO_SETUP, "hero test")
        med.see("hero-evidence-test")
        ev = med._evidence
        self.assertIsNotNone(ev, "HERO_SETUP 帧必须建立 evidence（N2-REVIEW #4）")
        self.assertIs(ev.frame_ref, f)
        self.assertEqual(med._context_cache_value, "UNKNOWN", "context 覆盖语义保持不变")

    # #1 sticky 快路径：像素有效但无廉价信号 → 连续 2 帧后候选枚举
    def test_capture_best_sticky_valid_but_no_signal_reenumerates(self):
        med = Mediator(Settings(), ROOT)
        med._last_capture_role = "l1"
        med._last_frame = _noise_frame(hwnd=101)
        targets = [
            WindowTarget(hwnd=101, title="游戏A", left=0, top=0, width=1600, height=900, role="l1"),
            WindowTarget(hwnd=202, title="游戏B", left=0, top=0, width=1600, height=900, role="l1"),
        ]
        frames = {101: _noise_frame(hwnd=101), 202: _noise_frame(hwnd=202)}

        def fake_capture(t: WindowTarget) -> Frame:
            return frames[t.hwnd]

        with patch("shuabao.mediator.find_window_targets", return_value=targets), \
             patch("shuabao.mediator.capture_target", side_effect=fake_capture) as ct, \
             patch.object(med, "_sticky_frame_signal", return_value=False):
            f1 = med._capture_best("英雄三国KK", "l1")
            self.assertEqual(ct.call_count, 1, "第 1 帧无信号仍返回上次 hwnd（容忍 1 帧）")
            self.assertIs(f1, frames[101])
            med._capture_best("英雄三国KK", "l1")
            self.assertGreaterEqual(ct.call_count, 3, "第 2 帧连续无信号必须候选枚举（上次 hwnd + 全部候选，每 HWND 仅 1 次）")

    # #1 反向：像素有效且有信号 → 一直 sticky（不重排）
    def test_capture_best_sticky_with_signal_keeps_last_hwnd(self):
        med = Mediator(Settings(), ROOT)
        med._last_capture_role = "l1"
        med._last_frame = _noise_frame(hwnd=101)
        targets = [
            WindowTarget(hwnd=101, title="游戏A", left=0, top=0, width=1600, height=900, role="l1"),
            WindowTarget(hwnd=202, title="游戏B", left=0, top=0, width=1600, height=900, role="l1"),
        ]
        frames = {101: _noise_frame(hwnd=101), 202: _noise_frame(hwnd=202)}

        def fake_capture(t: WindowTarget) -> Frame:
            return frames[t.hwnd]

        with patch("shuabao.mediator.find_window_targets", return_value=targets), \
             patch("shuabao.mediator.capture_target", side_effect=fake_capture) as ct, \
             patch.object(med, "_sticky_frame_signal", return_value=True):
            for _ in range(3):
                f = med._capture_best("英雄三国KK", "l1")
                self.assertIs(f, frames[101], "有信号时必须持续 sticky 上次健康 hwnd")
            self.assertEqual(ct.call_count, 3, "有信号时不枚举候选")

    # #6 refresh/give_up 宽尺度回退受 _scaled_up_frame 门禁
    def test_reward_choice_wide_fallback_gated_by_scaled_up_frame(self):
        from shuabao.vision.matcher import MatchResult

        f = _load("fixtures/replay/skill_choice_3.png")
        self.med._last_frame = f
        self.med.phase = Phase.MAIN_LINE
        anchor = MatchResult("skill_giveup_btn", 0.9, 100, 100, 50, 50, 200, 200)
        calls: list[tuple[list, tuple]] = []

        def fake_find(frame, names, **kw):
            calls.append((list(names), kw.get("scales")))
            return None

        with patch.object(self.med, "_selection_anchor", return_value=anchor), \
             patch.object(self.med, "_classify_choice_panel", return_value="skill"), \
             patch.object(self.med, "_match_all_preferred", return_value=[]), \
             patch.object(self.med, "find", side_effect=fake_find), \
             patch.object(self.med, "_scaled_up_frame", return_value=False):
            result = self.med._find_reward_choice(f, anchor=anchor)
        self.assertIsNone(result)
        for names, scales in calls:
            if names == ["skill_refresh_btn"] or names == ["skill_giveup_btn", "giveUp"]:
                self.assertEqual(scales, (1.0,), "基准窗口不得触发宽尺度回退（N2-REVIEW #6）")


if __name__ == "__main__":
    unittest.main()
