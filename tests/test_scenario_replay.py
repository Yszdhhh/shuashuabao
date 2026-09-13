"""Scenario Replay 测试 Harness。

按 docs/agent_digs_20260808/scenario_harness_design.md 实现：声明式 case.json
轨迹 + 真实 Mediator.tick() + FakeClock/FakeInputExecutor/ReplayFrameSource/
ActionProbe/ContextProbe 测试替身。每帧执行六项硬断言：
phase_before / context / action_count(<=1) / action / action_result / phase_after
(+ loop_action 与 final_phase)。

不修改生产代码：只注入 `_capture_best` 边界、替换 `med.executor`、包裹
`act_*`/`see` 记录语义，Mediator 的状态机与识别逻辑全部真实执行。
"""

from __future__ import annotations

import contextlib
import json
import sys
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Literal, Sequence

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
_SRC = ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import shuabao.mediator as mediator_module
from shuabao.input.keyboard_mouse import ActionResult
from shuabao.loop_action import LoopAction
from shuabao.mediator import Mediator, Phase
from shuabao.settings import Settings
from shuabao.stop_signal import StopSignal
from shuabao.vision.capture import Frame

SCENARIOS_DIR = ROOT / "fixtures" / "scenarios"

Outcome = Literal["SUCCESS", "OBSCURED", "NOT_ELEVATED", "SENDINPUT_FAILED"]

# outcome 注入名 → 真实 ActionResult 形状（与生产 InputExecutor 状态一致）
_OUTCOME_RESULTS: dict[str, ActionResult] = {
    "SUCCESS": ActionResult(True, "SUCCESS", "injected success"),
    "OBSCURED": ActionResult(False, "CANCELLED_WINDOW_OBSCURED", "injected: window obscured"),
    "NOT_ELEVATED": ActionResult(False, "CANCELLED_NOT_ELEVATED", "injected: not elevated"),
    "SENDINPUT_FAILED": ActionResult(False, "CANCELLED_SENDINPUT_FAILED", "injected: sendinput failed"),
}
_EMERGENCY_RESULT = ActionResult(False, "CANCELLED_EMERGENCY_STOP", "injected: emergency stop signal")

_INPUT_KIND: dict[str, str] = {
    "click": "left_click",
    "right_click": "right_click",
    "press_key": "key",
    "hotkey": "hotkey",
    "paste_text": "text",
    "scroll": "scroll",
    "type_text": "text",
}


class CaseFailure(AssertionError):
    """带 case/frame/index/at_s 上下文的断言失败。"""


# ---------------------------------------------------------------------------
# FakeClock
# ---------------------------------------------------------------------------

class FakeClock:
    """单调、无睡眠、可显式推进的时钟；install 后 mediator 内部
    time.time()/time.sleep 全部读到同一假时钟。
    """

    def __init__(self, start: float = 0.0) -> None:
        self._now = float(start)

    def now(self) -> float:
        return self._now

    def set(self, value: float) -> None:
        if value < self._now:
            raise ValueError(f"FakeClock.set 回拨时间: {value} < {self._now}")
        self._now = float(value)

    def advance(self, seconds: float) -> float:
        if seconds < 0:
            raise ValueError(f"FakeClock.advance 负数: {seconds}")
        self._now += float(seconds)
        return self._now

    def sleep(self, seconds: float) -> None:
        self.advance(seconds)

    def install(self, module: ModuleType = mediator_module) -> "_ClockInstall":
        return _ClockInstall(self, module)


class _ClockInstall(contextlib.AbstractContextManager):
    """patch module.time.time / module.time.sleep，退出恢复原对象。"""

    def __init__(self, clock: FakeClock, module: ModuleType) -> None:
        self._clock = clock
        self._module = module
        self._orig_time = module.time.time
        self._orig_sleep = module.time.sleep

    def __enter__(self) -> FakeClock:
        self._module.time.time = self._clock.now
        self._module.time.sleep = self._clock.sleep
        return self._clock

    def __exit__(self, *exc_info: object) -> None:
        self._module.time.time = self._orig_time
        self._module.time.sleep = self._orig_sleep


# ---------------------------------------------------------------------------
# FakeInputExecutor
# ---------------------------------------------------------------------------

@dataclass
class ActionRecord:
    call_index: int
    at_s: float
    method: str
    args: tuple[object, ...]
    kwargs: dict[str, object]
    result: ActionResult | None = None


class FakeInputExecutor:
    """替换 med.executor：每次调用先写 ledger，再按注入/急停解析 ActionResult。

    结果解析顺序（设计文档 §6）：
      1. 记录 method/坐标/按键/target_hwnd/dry_run/当前 clock.now()
      2. stop_signal 已 set → CANCELLED_EMERGENCY_STOP（不消费普通 outcome）
      3. 若有 before_result，先调用（trigger_stop_signal 在此设置 StopSignal）
      4. stop_signal 复检 → CANCELLED_EMERGENCY_STOP（验证急停不被 SUCCESS 覆盖）
      5. 按 inject_for_call / inject_next / 队列 / default 选 outcome
    """

    def __init__(
        self,
        stop_signal: StopSignal,
        clock: FakeClock,
        outcomes: Sequence[Outcome] = (),
        default_outcome: Outcome = "SUCCESS",
        before_result: Callable[[str, ActionRecord], None] | None = None,
    ) -> None:
        self._stop_signal = stop_signal
        self._clock = clock
        self._queue: list[Outcome] = list(outcomes)
        self._default: Outcome = default_outcome
        self.before_result = before_result
        self._injected: dict[int, Outcome] = {}
        self._call_index = 0
        self._ledger: list[ActionRecord] = []
        self._tick_start_index = 0

    # -- ledger 访问 --

    @property
    def action_ledger(self) -> list[ActionRecord]:
        return list(self._ledger)

    def clear(self) -> None:
        self._ledger.clear()
        self._queue.clear()
        self._injected.clear()
        self._call_index = 0
        self._tick_start_index = 0

    def begin_tick(self, index: int) -> None:
        self._tick_start_index = len(self._ledger)

    def records_since_tick_start(self) -> list[ActionRecord]:
        return self._ledger[self._tick_start_index:]

    # -- outcome 注入 --

    def inject_next(self, outcome: Outcome) -> None:
        self._queue.append(outcome)

    def inject_for_call(self, call_index: int, outcome: Outcome) -> None:
        self._injected[call_index] = outcome

    # -- 解析核心 --

    def _resolve(self, method: str, args: tuple[object, ...], kwargs: dict[str, object]) -> ActionResult:
        record = ActionRecord(self._call_index, self._clock.now(), method, args, dict(kwargs))
        self._call_index += 1
        self._ledger.append(record)
        if self._stop_signal.is_set():
            record.result = _EMERGENCY_RESULT
            return record.result
        if self.before_result is not None:
            self.before_result(method, record)
        if self._stop_signal.is_set():
            record.result = _EMERGENCY_RESULT
            return record.result
        outcome = self._injected.pop(record.call_index, None)
        if outcome is None and self._queue:
            outcome = self._queue.pop(0)
        if outcome is None:
            outcome = self._default
        record.result = _OUTCOME_RESULTS[outcome]
        return record.result

    # -- Mediator 实际使用的方法（每次调用都写 ledger）--

    def click(self, x: int, y: int, target_hwnd: int | None = None,
              dry_run: bool = True, delay_ms: int = 120) -> ActionResult:
        return self._resolve("click", (x, y), {"target_hwnd": target_hwnd, "dry_run": dry_run, "delay_ms": delay_ms})

    def right_click(self, x: int, y: int, target_hwnd: int | None = None,
                    dry_run: bool = True, delay_ms: int = 120) -> ActionResult:
        return self._resolve("right_click", (x, y), {"target_hwnd": target_hwnd, "dry_run": dry_run, "delay_ms": delay_ms})

    def press_key(self, key: str, target_hwnd: int | None = None, dry_run: bool = True) -> ActionResult:
        return self._resolve("press_key", (key,), {"target_hwnd": target_hwnd, "dry_run": dry_run})

    def hotkey(self, *keys: str, target_hwnd: int | None = None, dry_run: bool = True) -> ActionResult:
        return self._resolve("hotkey", keys, {"target_hwnd": target_hwnd, "dry_run": dry_run})

    def paste_text(self, text: str, target_hwnd: int | None = None, dry_run: bool = True) -> ActionResult:
        return self._resolve("paste_text", (text,), {"target_hwnd": target_hwnd, "dry_run": dry_run})

    def scroll(self, x: int, y: int, clicks: int, target_hwnd: int | None = None,
               dry_run: bool = True) -> ActionResult:
        return self._resolve("scroll", (x, y, clicks), {"target_hwnd": target_hwnd, "dry_run": dry_run})

    def type_text(self, text: str, target_hwnd: int | None = None, dry_run: bool = True) -> ActionResult:
        return self._resolve("type_text", (text,), {"target_hwnd": target_hwnd, "dry_run": dry_run})

    def search_text(self, x: int, y: int, text: str, target_hwnd: int | None = None,
                    dry_run: bool = True) -> ActionResult:
        return self._resolve(
            "search_text",
            (x, y, text),
            {"target_hwnd": target_hwnd, "dry_run": dry_run},
        )


# ---------------------------------------------------------------------------
# Probes / ReplayFrameSource
# ---------------------------------------------------------------------------

@dataclass
class SemanticAction:
    kind: str
    reason: str
    target: str | None


class ActionProbe:
    """包裹 Mediator 输入入口，按 ledger 调用顺序记录语义标签。"""

    def __init__(self, med: Mediator) -> None:
        self._med = med
        self._records: list[SemanticAction] = []
        self._tick_start = 0
        self._orig_click = med.act_click
        self._orig_right = med.act_right_click
        self._orig_key = med.act_key
        self._orig_scroll = med.act_scroll
        self._orig_search = med.act_search_box
        med.act_click = self._wrap_click
        med.act_right_click = self._wrap_right
        med.act_key = self._wrap_key
        med.act_scroll = self._wrap_scroll
        med.act_search_box = self._wrap_search

    def begin_tick(self, index: int) -> None:
        self._tick_start = len(self._records)

    def records_since_tick_start(self) -> list[SemanticAction]:
        return self._records[self._tick_start:]

    def _wrap_click(self, hit: Any, reason: str = "") -> bool:
        self._records.append(SemanticAction("click", reason, getattr(hit, "name", None)))
        return self._orig_click(hit, reason)

    def _wrap_right(self, hit: Any, reason: str = "") -> bool:
        self._records.append(SemanticAction("right_click", reason, getattr(hit, "name", None)))
        return self._orig_right(hit, reason)

    def _wrap_key(self, key: str, reason: str = "") -> bool:
        self._records.append(SemanticAction("press_key", reason, key))
        return self._orig_key(key, reason)

    def _wrap_scroll(self, x: int, y: int, clicks: int, reason: str = "") -> bool:
        self._records.append(SemanticAction("scroll", reason, None))
        return self._orig_scroll(x, y, clicks, reason)

    def _wrap_search(self, hit: Any, text: str, reason: str = "") -> bool:
        self._records.append(SemanticAction("search_text", reason, text))
        return self._orig_search(hit, text, reason)


class ContextProbe:
    """记录 see() 的观察上下文；StopSignal 入口短路（未调用 see）时由
    runner 记为 STOP_SIGNAL。"""

    def __init__(self, med: Mediator) -> None:
        self._med = med
        self._contexts: list[str] = []
        self._tick_start = 0
        self._orig_see = med.see
        med.see = self._wrap_see

    def begin_tick(self, index: int) -> None:
        self._tick_start = len(self._contexts)

    def contexts_since_tick_start(self) -> list[str]:
        return self._contexts[self._tick_start:]

    def _wrap_see(self, reason: str = "") -> Frame:
        frame = self._orig_see(reason)
        self._contexts.append(self._med._context_cache_value)
        return frame


class ReplayFrameSource:
    """替换 Mediator._capture_best 边界：按 (tick_index, role) 返回同一逻辑帧，
    保留 see() 的静态帧复用 / _last_frame 更新 / context cache 行为。"""

    def __init__(self, frames: list[Frame]) -> None:
        self._frames = frames
        self._tick_index = 0
        self._served: dict[tuple[int, str], Frame] = {}

    def begin_tick(self, index: int) -> None:
        self._tick_index = index
        self._served.clear()

    def capture_best(self, title: str, role: str) -> Frame:
        key = (self._tick_index, role)
        frame = self._served.get(key)
        if frame is None:
            frame = self._frames[self._tick_index]
            self._served[key] = frame
        return frame


# ---------------------------------------------------------------------------
# ReplayCaseLoader
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FrameSpec:
    id: str
    at_s: float
    file: str
    window_title: str | None
    hwnd: int | None
    left: int
    top: int
    capture_role: str
    control: dict[str, Any]


@dataclass(frozen=True)
class ExpectAction:
    phase_before: str
    context: str
    action_count: int
    action: dict[str, Any] | None
    action_result: dict[str, Any] | None
    phase_after: str
    loop_action: str | None
    input_injection: str | None


@dataclass(frozen=True)
class Case:
    schema_version: int
    case: str
    description: str
    phase: str
    settings_overrides: dict[str, Any]
    frames: list[FrameSpec]
    expect_actions: list[ExpectAction]
    final_phase: str
    path: Path


class ReplayCaseLoader:
    def __init__(self, root: Path) -> None:
        self.root = root

    def load(self, case_dir: Path) -> Case:
        path = case_dir / "case.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        errors: list[str] = []

        def req(key: str) -> Any:
            if key not in raw:
                errors.append(f"{path.name}: 缺少必填字段 '{key}'")
                return None
            return raw[key]

        def phase_valid(name: Any, label: str) -> None:
            if name not in Phase.__members__:
                errors.append(f"{path.name}: {label} '{name}' 不是有效 Phase")

        schema_version = req("schema_version")
        if schema_version != 1:
            errors.append(f"{path.name}: schema_version={schema_version} 未知（仅支持 1）")
        case_name = req("case")
        if case_name != case_dir.name:
            errors.append(f"{path.name}: case '{case_name}' 与目录名 '{case_dir.name}' 不一致")
        phase = req("phase")
        if phase is not None:
            phase_valid(phase, "phase")
        final_phase = req("final_phase")
        if final_phase is not None:
            phase_valid(final_phase, "final_phase")

        overrides = raw.get("settings_overrides") or {}
        known = {f.name for f in Settings.__dataclass_fields__.values()}
        for k in overrides:
            if k not in known:
                errors.append(f"{path.name}: settings_overrides 未知字段 '{k}'（仅允许已有 Settings 字段）")

        frames_raw = req("frames")
        expect_raw = req("expect_actions")
        frames: list[FrameSpec] = []
        if not isinstance(frames_raw, list) or not frames_raw:
            errors.append(f"{path.name}: frames 必须是非空数组")
        else:
            prev_at_s: float | None = None
            for i, fr in enumerate(frames_raw):
                label = f"frames[{i}]"
                if not isinstance(fr, dict):
                    errors.append(f"{path.name}: {label} 不是对象")
                    continue
                fid = fr.get("id")
                at_s = fr.get("at_s")
                file = fr.get("file")
                if not isinstance(fid, str) or not fid:
                    errors.append(f"{path.name}: {label}.id 必须是非空字符串")
                if not isinstance(at_s, (int, float)):
                    errors.append(f"{path.name}: {label}.at_s 必须是数字")
                elif prev_at_s is not None and at_s < prev_at_s:
                    errors.append(f"{path.name}: {label}.at_s 时间回拨（{at_s} < {prev_at_s}），必须非递减")
                else:
                    prev_at_s = float(at_s)
                if not isinstance(file, str) or not file:
                    errors.append(f"{path.name}: {label}.file 必须是非空路径")
                else:
                    img_path = self.root / file
                    if not img_path.is_file():
                        errors.append(f"{path.name}: {label}.file 不存在: {file}")
                role = fr.get("capture_role", "l1")
                if role not in ("l0", "l1"):
                    errors.append(f"{path.name}: {label}.capture_role 必须是 l0/l1")
                control = fr.get("control") or {}
                if not isinstance(control, dict):
                    errors.append(f"{path.name}: {label}.control 必须是对象")
                else:
                    ss = control.get("stop_signal", "unchanged")
                    if ss not in ("clear", "set", "unchanged"):
                        errors.append(f"{path.name}: {label}.control.stop_signal 必须是 clear/set/unchanged")
                    ba = control.get("before_action")
                    if ba not in (None, "trigger_stop_signal"):
                        errors.append(f"{path.name}: {label}.control.before_action 必须是 null/trigger_stop_signal")
                frames.append(FrameSpec(
                    id=fid if isinstance(fid, str) else f"frame_{i}",
                    at_s=float(at_s) if isinstance(at_s, (int, float)) else 0.0,
                    file=file if isinstance(file, str) else "",
                    window_title=fr.get("window_title"),
                    hwnd=fr.get("hwnd"),
                    left=fr.get("left", 0) or 0,
                    top=fr.get("top", 0) or 0,
                    capture_role=role,
                    control=control if isinstance(control, dict) else {},
                ))

        expects: list[ExpectAction] = []
        if not isinstance(expect_raw, list):
            errors.append(f"{path.name}: expect_actions 必须是数组")
        elif frames and len(expect_raw) != len(frames):
            errors.append(f"{path.name}: expect_actions 长度 {len(expect_raw)} != frames 长度 {len(frames)}")
        else:
            for i, ex in enumerate(expect_raw):
                label = f"expect_actions[{i}]"
                if not isinstance(ex, dict):
                    errors.append(f"{path.name}: {label} 不是对象")
                    continue
                pb, ctx, cnt, pa = ex.get("phase_before"), ex.get("context"), ex.get("action_count"), ex.get("phase_after")
                for key, val in (("phase_before", pb), ("context", ctx), ("phase_after", pa)):
                    if not isinstance(val, str) or not val:
                        errors.append(f"{path.name}: {label}.{key} 必须是非空字符串")
                if not isinstance(cnt, int) or cnt not in (0, 1):
                    errors.append(f"{path.name}: {label}.action_count 必须是 0 或 1")
                action = ex.get("action")
                action_result = ex.get("action_result")
                if (action is None) != (action_result is None):
                    errors.append(f"{path.name}: {label}.action 与 action_result 必须同为 null 或同非 null")
                if action is not None:
                    if not isinstance(action, dict) or not isinstance(action.get("kind"), str):
                        errors.append(f"{path.name}: {label}.action.kind 必须是非空字符串")
                    if action.get("kind") not in _INPUT_KIND:
                        errors.append(f"{path.name}: {label}.action.kind 非法: {action.get('kind')}")
                if action_result is not None:
                    if not isinstance(action_result, dict):
                        errors.append(f"{path.name}: {label}.action_result 必须是对象")
                    else:
                        if not isinstance(action_result.get("success"), bool):
                            errors.append(f"{path.name}: {label}.action_result.success 必须是 bool")
                        if not isinstance(action_result.get("status"), str):
                            errors.append(f"{path.name}: {label}.action_result.status 必须是非空字符串")
                loop_action = ex.get("loop_action")
                if loop_action not in (None, "Continue", "Break"):
                    errors.append(f"{path.name}: {label}.loop_action 必须是 Continue/Break")
                inj = ex.get("input_injection")
                if inj not in (None, "SUCCESS", "OBSCURED", "NOT_ELEVATED", "SENDINPUT_FAILED"):
                    errors.append(f"{path.name}: {label}.input_injection 非法: {inj}")
                expects.append(ExpectAction(
                    phase_before=pb if isinstance(pb, str) else "",
                    context=ctx if isinstance(ctx, str) else "",
                    action_count=cnt if isinstance(cnt, int) else 0,
                    action=action,
                    action_result=action_result,
                    phase_after=pa if isinstance(pa, str) else "",
                    loop_action=loop_action,
                    input_injection=inj,
                ))

        if errors:
            raise AssertionError(f"case 校验失败 [{case_dir.name}]:\n" + "\n".join(errors))

        return Case(
            schema_version=int(schema_version),
            case=str(case_name),
            description=str(raw.get("description") or ""),
            phase=str(phase),
            settings_overrides=dict(overrides),
            frames=frames,
            expect_actions=expects,
            final_phase=str(final_phase),
            path=path,
        )

    def load_frames(self, case: Case) -> list[Frame]:
        frames: list[Frame] = []
        for spec in case.frames:
            img = cv2.imdecode(np.fromfile(str(self.root / spec.file), dtype=np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                raise AssertionError(f"case={case.case}: 无法解码图片 {spec.file}")
            default_title = "KK" if spec.capture_role == "l0" else "英雄三国KK"
            frames.append(Frame(
                bgr=img,
                left=spec.left,
                top=spec.top,
                window_title=spec.window_title if spec.window_title is not None else default_title,
                hwnd=10001 if spec.hwnd is None else spec.hwnd,
                timestamp=spec.at_s,
                role=spec.capture_role,
            ))
        return frames


def _apply_settings_overrides(settings: Settings, overrides: dict[str, Any]) -> None:
    for key, value in overrides.items():
        setattr(settings, key, value)


# ---------------------------------------------------------------------------
# 断言辅助
# ---------------------------------------------------------------------------

def _semantic_action(probe_records: list[SemanticAction], ledger_records: list[ActionRecord]) -> dict[str, Any] | None:
    """把本 tick 的 ledger 记录与 probe 语义标签按顺序关联。"""
    if not ledger_records:
        return None
    rec = ledger_records[0]
    probe = probe_records[0] if probe_records else None
    return {
        "kind": rec.method,
        "reason": probe.reason if probe else "",
        "target": probe.target if probe else None,
        "input_kind": _INPUT_KIND.get(rec.method, rec.method),
    }


def _action_matches(expected: dict[str, Any] | None, actual: dict[str, Any] | None) -> bool:
    if expected is None:
        return actual is None
    if actual is None:
        return False
    for key in ("kind", "reason", "target", "input_kind"):
        if expected.get(key) is not None and expected[key] != actual[key]:
            return False
    return True


def _result_matches(expected: dict[str, Any] | None, actual: dict[str, Any] | None) -> bool:
    if expected is None:
        return actual is None
    if actual is None:
        return False
    if expected.get("success") is not None and expected["success"] != actual["success"]:
        return False
    if expected.get("status") is not None and expected["status"] != actual["status"]:
        return False
    mc = expected.get("message_contains")
    if mc is not None and mc not in (actual.get("message") or ""):
        return False
    return True


# ---------------------------------------------------------------------------
# ScenarioRunner
# ---------------------------------------------------------------------------

class ScenarioRunner:
    """每帧：clock.set → 应用 control → begin_tick → 六项硬断言 → 最后 final_phase。"""

    def __init__(self, root: Path) -> None:
        self.root = root

    def run_case(self, case_dir: Path) -> None:
        loader = ReplayCaseLoader(self.root)
        case = loader.load(case_dir)
        frames = loader.load_frames(case)

        clock = FakeClock(start=case.frames[0].at_s)
        stop_signal = StopSignal()
        with clock.install():
            settings = Settings()
            _apply_settings_overrides(settings, case.settings_overrides)
            med = Mediator(settings, self.root, stop_signal=stop_signal)
            med.set_phase(Phase[case.phase], "scenario initial phase")
            executor = FakeInputExecutor(stop_signal, clock)
            med.executor = executor
            frame_source = ReplayFrameSource(frames)
            med._capture_best = frame_source.capture_best
            action_probe = ActionProbe(med)
            context_probe = ContextProbe(med)

            for index, (spec, expected) in enumerate(zip(case.frames, case.expect_actions)):
                self._run_tick(case, med, executor, frame_source, action_probe, context_probe,
                               clock, stop_signal, index, spec, expected)

            if med.phase.name != case.final_phase:
                raise CaseFailure(
                    f"case={case.case}\n"
                    f"final_phase expected={case.final_phase} actual={med.phase.name}"
                )

    @staticmethod
    def _apply_control(control: dict[str, Any], stop_signal: StopSignal, executor: FakeInputExecutor) -> None:
        ss = control.get("stop_signal", "unchanged")
        if ss == "set":
            stop_signal.trigger("scenario control: set")
        elif ss == "clear":
            stop_signal.reset()
        if control.get("before_action") == "trigger_stop_signal":
            executor.before_result = lambda method, record: stop_signal.trigger(
                f"scenario before_action: {method}"
            )
        else:
            executor.before_result = None

    def _run_tick(self, case: Case, med: Mediator, executor: FakeInputExecutor,
                  frame_source: ReplayFrameSource, action_probe: ActionProbe,
                  context_probe: ContextProbe, clock: FakeClock, stop_signal: StopSignal,
                  index: int, spec: FrameSpec, expected: ExpectAction) -> None:
        failures: list[str] = []

        def check(ok: bool, label: str, exp: Any, act: Any) -> None:
            if not ok:
                failures.append(f"{label} expected={exp!r} actual={act!r}")

        clock.set(spec.at_s)
        self._apply_control(spec.control, stop_signal, executor)
        executor.begin_tick(index)
        action_probe.begin_tick(index)
        context_probe.begin_tick(index)
        frame_source.begin_tick(index)

        # 硬断言 1：phase_before（tick 前）
        phase_before = med.phase.name
        check(phase_before == expected.phase_before, "phase_before", expected.phase_before, phase_before)

        if expected.input_injection is not None:
            executor.inject_next(expected.input_injection)

        loop_action = med.tick()

        # 硬断言 2：context（StopSignal 入口短路 → STOP_SIGNAL sentinel）
        seen = context_probe.contexts_since_tick_start()
        context = seen[0] if seen else "STOP_SIGNAL"
        check(context == expected.context, "context", expected.context, context)

        # 硬断言 3：action_count <= 1（>1 时必须打印全部 ledger）
        records = executor.records_since_tick_start()
        if len(records) > 1:
            dump = "\n".join(
                f"  ledger[{r.call_index}] {r.method}{r.args} -> "
                f"{r.result.status if r.result else None} ({r.result.message if r.result else ''})"
                for r in records
            )
            raise CaseFailure(
                f"case={case.case} frame={spec.id} index={index} at_s={spec.at_s}\n"
                f"action_count={len(records)} > 1（一帧连点）\nledger 全部记录:\n{dump}"
            )
        check(len(records) == expected.action_count, "action_count", expected.action_count, len(records))

        # 硬断言 4：action（语义 kind/reason/target/input_kind）
        probe_records = action_probe.records_since_tick_start()
        actual_action = _semantic_action(probe_records, records)
        check(_action_matches(expected.action, actual_action), "action", expected.action, actual_action)

        # 硬断言 5：ActionResult（success + 精确 status）
        actual_result = None
        if records:
            r = records[0].result
            actual_result = {"success": r.success, "status": r.status, "message": r.message}
        check(_result_matches(expected.action_result, actual_result), "action_result", expected.action_result, actual_result)

        # 硬断言 6：phase_after + loop_action
        phase_after = med.phase.name
        check(phase_after == expected.phase_after, "phase_after", expected.phase_after, phase_after)
        if expected.loop_action is not None:
            check(loop_action.name == expected.loop_action, "loop_action", expected.loop_action, loop_action.name)

        if failures:
            header = f"case={case.case} frame={spec.id} index={index} at_s={spec.at_s}"
            raise CaseFailure(header + "\n" + "\n".join(failures) + f"\nledger_delta={len(records)}")


# ---------------------------------------------------------------------------
# 测试：从 fixtures/scenarios/*/case.json glob 发现，每个 case 一个测试方法
# ---------------------------------------------------------------------------

class ScenarioReplayTests(unittest.TestCase):
    """每个 case 一个独立测试方法（可 -k 筛选）；证据缺失的 case 标记 XFAIL。"""

    # case 名 → XFAIL 原因（证据缺失；补充真实截图后可移除并让 case 按设计契约通过）
    XFAIL_REASONS: dict[str, str] = {
        "fail_recovery_three_frames": (
            "fixtures 缺少当前版本全屏断线/失败弹窗证据（reborn_wow README 与 fixtures/manifest.json 均标注 "
            "missing）；case 复用 reborn_wow/choices/skill_choice_3.png（最接近的含 fail 锚点证据：旧版 giveUp "
            "模板 0.945 命中）作为三帧，但该帧实为选择面板而非失败弹窗：无任何现有帧同时命中 fail/disconnect "
            "锚点与 ok 模板，设计契约的 fail→ok→close 各一次点击实际为 1/0/1（WAIT_OK 帧无 ok 命中）。"
        ),
        "ticket_zero_archaeology": (
            "所有现有选关页证据（含 live_stage_select.png 与 2026-08-09 B站视频归档帧，见 "
            "frames_unverified/）在 ticket ROI 内均无 lobby/ticket_zero 字形命中（视频全部 120/120 非 0，"
            "zero 模板最高 0.698 < 0.72）；case 以 live_stage_select.png 作版式参考（caveat），"
            "设计契约的 0/0/SwitchToArchaeology 实际为连续滚动（SelectStage 目标不在列表）。"
        ),
    }

    def test_discover_cases(self) -> None:
        """case.json 是发现入口：至少发现 5 个场景目录。"""
        cases = _discover_cases()
        self.assertGreaterEqual(len(cases), 5, f"fixtures/scenarios 下应至少 5 个 case，实际 {len(cases)}")
        for name in ("fail_recovery_three_frames", "stop_start_race", "skill_panel_one_missing",
                     "stage_starting_env_hud", "ticket_zero_archaeology"):
            self.assertTrue(any(c.name == name for c in cases), f"缺少场景 {name}")


def _discover_cases() -> list[Path]:
    if not SCENARIOS_DIR.is_dir():
        return []
    return sorted(p.parent for p in SCENARIOS_DIR.glob("*/case.json"))


def _make_case_test(case_dir: Path, xfail_reason: str | None) -> Callable[["ScenarioReplayTests"], None]:
    runner = ScenarioRunner(ROOT)

    def test(self: ScenarioReplayTests) -> None:
        runner.run_case(case_dir)

    if xfail_reason:
        test = unittest.expectedFailure(test)  # type: ignore[assignment]
    test.__name__ = f"test_case_{case_dir.name}"
    test.__doc__ = f"Scenario Replay: {case_dir.name}" + (f"\nXFAIL: {xfail_reason}" if xfail_reason else "")
    return test


for _case_dir in _discover_cases():
    _reason = ScenarioReplayTests.XFAIL_REASONS.get(_case_dir.name)
    setattr(ScenarioReplayTests, f"test_case_{_case_dir.name}", _make_case_test(_case_dir, _reason))


if __name__ == "__main__":
    unittest.main()
