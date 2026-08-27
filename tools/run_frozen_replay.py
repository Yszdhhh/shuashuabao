import sys
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
#!/usr/bin/env python3
"""R0.1 冻结端到端回放集运行器（fixtures/baselines/replay_frozen/）。

用途：把 R0.1 六类场景（fail+panel / giveUp+panel / 存档挑战 / 主线 HUD / stage /
退出确认）在仓库既有 1600×900 素材上以真实 Mediator.tick() 冻结运行，逐帧断言
phase/context/action/action_result/phase_after/loop_action + 终态 phase，并与
manifest.json 的 ledger 预期逐行比对；断线场景（素材缺失）如实报告 BLOCKED。

复用的既有基建（不修改生产代码）：
  - tests/test_scenario_replay.py：ReplayCaseLoader / FakeClock / FakeInputExecutor /
    ReplayFrameSource / ActionProbe / ContextProbe / 六项硬断言语义；
  - tools/compare_ledger.py：off/shadow 双模式 ledger 等价 diff（compare_ledger 字段）。

零输入：所有输入经 FakeInputExecutor 记账（dry_run=True），不产生真实游戏输入。

用法：
  .venv\\Scripts\\python.exe tools/run_frozen_replay.py                  # 全部场景 off 模式
  .venv\\Scripts\\python.exe tools/run_frozen_replay.py --mode shadow    # shadow 模式
  .venv\\Scripts\\python.exe tools/run_frozen_replay.py --only giveup_panel_not_fail
  .venv\\Scripts\\python.exe tools/run_frozen_replay.py --diff           # off/shadow 双跑 + ledger diff（必须 diff=0）
  .venv\\Scripts\\python.exe tools/run_frozen_replay.py --diff --out docs/baselines/R0_LEDGER_20260811
  .venv\\Scripts\\python.exe tools/run_frozen_replay.py --check          # 门禁退出码
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tools"))

from shuabao.mediator import Mediator, Phase  # noqa: E402
from shuabao.settings import Settings  # noqa: E402
from shuabao.stop_signal import StopSignal  # noqa: E402
from test_scenario_replay import (  # noqa: E402
    ActionProbe,
    ContextProbe,
    FakeClock,
    FakeInputExecutor,
    ReplayCaseLoader,
    ReplayFrameSource,
    _INPUT_KIND,
    _action_matches,
    _result_matches,
)

FROZEN = ROOT / "fixtures" / "baselines" / "replay_frozen"
MANIFEST_PATH = FROZEN / "manifest.json"
DEFAULT_OUT_DIR = FROZEN / "ledger"


@dataclass
class FrameRun:
    frame_index: int
    frame_id: str
    at_s: float
    phase_before: str
    context: str
    action_count: int
    action: dict | None
    action_result: dict | None
    phase_after: str
    loop_action: str
    failures: list[str] = field(default_factory=list)

    def ledger_row(self, scene_id: str, mode: str) -> dict:
        name = "none"
        kind = "none"
        point = None
        if self.action is not None:
            name = self.action.get("reason") or self.action.get("kind") or "action"
            kind = self.action.get("input_kind") or "none"
            if self.action.get("point") is not None:
                point = list(self.action["point"])
        return {
            "fixture_id": f"{scene_id}#f{self.frame_index}",
            "scene_id": scene_id,
            "frame_index": self.frame_index,
            "frame_id": self.frame_id,
            "phase": self.phase_after,
            "context": self.context,
            "action_name": name,
            "action_kind": kind,
            "click_point": point,
            "at_s": round(self.at_s, 3),
            "hwnd": 10001,
            "score": 0.0,
            "status": "PASS" if not self.failures else "FAIL",
            "required": True,
            "ocr_mode": mode,
            "dry_run": True,
        }


@dataclass
class SceneRun:
    scene_id: str
    mode: str
    status: str  # PASS / FAIL / BLOCKED
    frames: list[FrameRun] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    ledger_mismatches: list[str] = field(default_factory=list)


def _run_tick_collect(scene_id: str, case, med, executor, frame_source, action_probe,
                      context_probe, clock, stop_signal, index, spec, expected) -> FrameRun:
    """单帧 tick + 六项硬断言（收集失败不中断）。"""
    failures: list[str] = []

    def check(ok: bool, label: str, exp: object, act: object) -> None:
        if not ok:
            failures.append(f"{label} expected={exp!r} actual={act!r}")

    clock.set(spec.at_s)
    ss = spec.control.get("stop_signal", "unchanged")
    if ss == "set":
        stop_signal.trigger("frozen control: set")
    elif ss == "clear":
        stop_signal.reset()
    if spec.control.get("before_action") == "trigger_stop_signal":
        executor.before_result = lambda method, record: stop_signal.trigger(f"frozen before_action: {method}")
    else:
        executor.before_result = None
    executor.begin_tick(index)
    action_probe.begin_tick(index)
    context_probe.begin_tick(index)
    frame_source.begin_tick(index)

    phase_before = med.phase.name
    check(phase_before == expected.phase_before, "phase_before", expected.phase_before, phase_before)

    if expected.input_injection is not None:
        executor.inject_next(expected.input_injection)

    loop_action = med.tick()

    seen = context_probe.contexts_since_tick_start()
    context = seen[0] if seen else "STOP_SIGNAL"
    check(context == expected.context, "context", expected.context, context)

    records = executor.records_since_tick_start()
    if len(records) > 1:
        dump = "\n".join(
            f"  ledger[{r.call_index}] {r.method}{r.args} -> {r.result.status if r.result else None}"
            for r in records
        )
        failures.append(f"action_count={len(records)} > 1（一帧连点）\nledger:\n{dump}")
    check(len(records) == expected.action_count, "action_count", expected.action_count, len(records))

    probe_records = action_probe.records_since_tick_start()
    action = None
    if records:
        rec = records[0]
        pr = probe_records[0] if probe_records else None
        action = {
            "kind": rec.method,
            "reason": pr.reason if pr else "",
            "target": pr.target if pr else None,
            "input_kind": _INPUT_KIND.get(rec.method, rec.method),
        }
        if rec.method == "click":
            action["point"] = (int(rec.args[0]), int(rec.args[1]))
        elif rec.method == "right_click":
            action["point"] = (int(rec.args[0]), int(rec.args[1]))
        elif rec.method == "scroll":
            action["point"] = (int(rec.args[0]), int(rec.args[1]))
    check(_action_matches(expected.action, action), "action", expected.action, action)

    action_result = None
    if records:
        r = records[0].result
        action_result = {"success": r.success, "status": r.status, "message": r.message}
    check(_result_matches(expected.action_result, action_result), "action_result", expected.action_result, action_result)

    phase_after = med.phase.name
    check(phase_after == expected.phase_after, "phase_after", expected.phase_after, phase_after)
    if expected.loop_action is not None:
        check(loop_action.name == expected.loop_action, "loop_action", expected.loop_action, loop_action.name)

    return FrameRun(
        frame_index=index,
        frame_id=spec.id,
        at_s=spec.at_s,
        phase_before=phase_before,
        context=context,
        action_count=len(records),
        action=action,
        action_result=action_result,
        phase_after=phase_after,
        loop_action=loop_action.name,
        failures=failures,
    )


def run_scene(scene: dict, mode: str) -> SceneRun:
    scene_id = scene["scene_id"]
    if scene.get("missing_resource"):
        return SceneRun(scene_id=scene_id, mode=mode, status="BLOCKED",
                        failures=[scene.get("material_gap", "material missing")])
    case_dir = FROZEN / scene["case_dir"]
    loader = ReplayCaseLoader(ROOT)
    case = loader.load(case_dir)
    frames = loader.load_frames(case)

    clock = FakeClock(start=case.frames[0].at_s)
    stop_signal = StopSignal()
    with clock.install():
        settings = Settings()
        settings.ocr_mode = mode
        for key, value in case.settings_overrides.items():
            setattr(settings, key, value)
        med = Mediator(settings, ROOT, stop_signal=stop_signal)
        med.set_phase(Phase[case.phase], "frozen replay initial phase")
        executor = FakeInputExecutor(stop_signal, clock)
        med.executor = executor
        frame_source = ReplayFrameSource(frames)
        med._capture_best = frame_source.capture_best
        action_probe = ActionProbe(med)
        context_probe = ContextProbe(med)

        run = SceneRun(scene_id=scene_id, mode=mode, status="PASS")
        for index, (spec, expected) in enumerate(zip(case.frames, case.expect_actions)):
            fr = _run_tick_collect(scene_id, case, med, executor, frame_source, action_probe,
                                   context_probe, clock, stop_signal, index, spec, expected)
            run.frames.append(fr)
            run.failures.extend(f"{fr.frame_id} f{index}: {f}" for f in fr.failures)
        if med.phase.name != case.final_phase:
            run.failures.append(f"final_phase expected={case.final_phase} actual={med.phase.name}")
        if run.failures:
            run.status = "FAIL"

    # manifest ledger 预期比对
    expected_rows = scene.get("ledger_expectation") or []
    for row in expected_rows:
        idx = row.get("frame_index")
        if idx is None or idx >= len(run.frames):
            run.ledger_mismatches.append(f"frame_index {idx} 超出实际帧数 {len(run.frames)}")
            continue
        fr = run.frames[idx]
        actual = fr.ledger_row(scene_id, mode)
        for fld in ("phase", "context", "action_name", "action_kind", "click_point"):
            if row.get(fld) != actual.get(fld):
                run.ledger_mismatches.append(
                    f"ledger f{idx}.{fld}: expected={row.get(fld)!r} actual={actual.get(fld)!r}"
                )
    if run.ledger_mismatches and run.status == "PASS":
        run.status = "FAIL"
    return run


def write_ledger(runs: list[SceneRun], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8") as fh:
        for run in runs:
            if run.status == "BLOCKED":
                continue
            for fr in run.frames:
                fh.write(json.dumps(fr.ledger_row(run.scene_id, run.mode), ensure_ascii=False) + "\n")
                n += 1
    return n


def main(argv: list[str] | None = None) -> int:
    from compare_ledger import load_rows

    p = argparse.ArgumentParser(description="R0.1 冻结端到端回放集运行器")
    p.add_argument("--mode", choices=("off", "shadow"), default="off", help="ocr_mode（默认 off）")
    p.add_argument("--only", default=None, help="只跑单个 scene_id")
    p.add_argument("--ledger", metavar="PATH", default=None, help="写本模式 ledger JSONL")
    p.add_argument("--diff", action="store_true", help="off+shadow 双跑并 compare_ledger 等价 diff（必须 0）")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR, help="--diff 的 ledger 输出目录")
    p.add_argument("--check", action="store_true", help="门禁退出码（0=全部必需可跑场景 PASS 且 diff=0）")
    p.add_argument("--json", action="store_true", help="机器可读汇总")
    args = p.parse_args(argv)

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    scenes = manifest["scenes"]
    if args.only:
        scenes = [s for s in scenes if s["scene_id"] == args.only]
        if not scenes:
            print(f"[ERROR] 未知 scene_id: {args.only}")
            return 2

    if args.diff:
        summaries = {}
        failed = False
        for mode in ("off", "shadow"):
            runs = [run_scene(s, mode) for s in scenes]
            ledger_path = args.out / f"{mode}.jsonl"
            n = write_ledger(runs, ledger_path)
            summaries[mode] = {
                "ledger": str(ledger_path),
                "rows": n,
                "scenes": {r.scene_id: r.status for r in runs},
                "failures": {r.scene_id: r.failures for r in runs if r.failures},
            }
            print(f"[{mode}] ledger rows={n} -> {ledger_path}")
            for r in runs:
                print(f"  {r.scene_id}: {r.status}"
                      + (f"  ledger_mismatch={len(r.ledger_mismatches)}" if r.ledger_mismatches else ""))
                if r.status == "FAIL":
                    failed = True
                    for f_ in r.failures[:8]:
                        print(f"      FAIL {f_}")
        base = load_rows(args.out / "off.jsonl")
        cand = load_rows(args.out / "shadow.jsonl")
        diffs = []
        for fid in sorted(set(base) | set(cand)):
            b, c = base.get(fid), cand.get(fid)
            if b is None:
                diffs.append(f"[DIFF] {fid}: only in shadow")
                continue
            if c is None:
                diffs.append(f"[DIFF] {fid}: only in off")
                continue
            for fld in ("fixture_id", "phase", "context", "action_name", "action_kind", "click_point", "required"):
                if b.get(fld) != c.get(fld):
                    diffs.append(f"[DIFF] {fid}.{fld}: {b.get(fld)!r} -> {c.get(fld)!r}")
        print(f"off/shadow ledger compare: off={len(base)} rows, shadow={len(cand)} rows, diffs={len(diffs)}")
        for d in diffs:
            print(" ", d)
        if args.json:
            print(json.dumps({**summaries, "diff_count": len(diffs), "diff": diffs[:20]}, ensure_ascii=False, indent=1))
        if diffs or failed:
            return 1 if args.check else (1 if diffs else 0)
        print("[OK] 冻结回放全部场景 PASS，off/shadow ledger diff=0")
        return 0

    runs = [run_scene(s, args.mode) for s in scenes]
    total = passed = blocked = failed = 0
    for r in runs:
        total += 1
        if r.status == "PASS":
            passed += 1
        elif r.status == "BLOCKED":
            blocked += 1
        else:
            failed += 1
        print(f"{r.scene_id:<28} | {r.mode:<7} | {r.status:<8} | frames={len(r.frames)}"
              + (f" | failures={len(r.failures)} ledger_mismatch={len(r.ledger_mismatches)}" if r.failures or r.ledger_mismatches else ""))
        for f_ in r.failures[:8]:
            print(f"    FAIL {f_}")
        for m in r.ledger_mismatches[:8]:
            print(f"    LEDGER {m}")

    if args.ledger:
        n = write_ledger(runs, Path(args.ledger))
        print(f"[ledger] {n} rows -> {args.ledger}")

    summary = {
        "mode": args.mode,
        "total": total,
        "passed": passed,
        "blocked": blocked,
        "failed": failed,
        "scenes": {r.scene_id: r.status for r in runs},
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=1))
    print(f"Summary: Total={total} Passed={passed} Blocked={blocked} Failed={failed}")
    if failed:
        print("[ERROR] 冻结回放存在 FAIL 场景")
        return 1 if args.check else 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
