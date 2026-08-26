#!/usr/bin/env python3
"""N0 性能基准：统一复现 刷刷宝热路径耗时（冷 / warm-changed / exact-static）。

对每个 fixture 帧记录 capture(decode)/context/health/decision/action 耗时，
统计 cv2.matchTemplate 调用次数与搜索像素总量，输出 JSON + Markdown。
同一命令可重跑（固定输出文件名，覆写；时间戳与环境记录在内容中）。

用法:
    .venv\\Scripts\\python.exe tools/benchmark_hot_path.py [--iterations N] [--out-dir docs/baselines] [--live-capture]

验收门禁 N0:
    - 一条命令完成基准且 exit 0
    - 连续运行 3 次，中位耗时偏差 <= 10%（比较 warm-changed MAIN_LINE P50）
    - 报告含 commit / 环境 / 模板聚合 SHA256 / P50/P95 / 匹配次数 / 搜索像素
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.mediator import Mediator, PanelState, Phase  # noqa: E402
from shuabao.settings import Settings  # noqa: E402
from shuabao.vision.capture import Frame, check_frame_health  # noqa: E402
from shuabao.vision.matcher import clear_template_cache  # noqa: E402

IMAGES_DIR = ROOT / "assets" / "Images"
FIXTURES_DIR = ROOT / "tests" / "performance" / "fixtures"
MANIFEST = FIXTURES_DIR / "manifest.json"

# 需要与 see() 对齐的会话级 UI 缩放校准
REF_W, REF_H = 1600, 900

# ---- cv2.matchTemplate 计数包装（全局，覆盖本进程内所有 matcher 调用）----
_orig_match = cv2.matchTemplate
_match_count = 0
_match_pixels = 0  # 每次调用扫描的图像面积（宽*高）累计


def _counting_match(image, templ, method, *args, **kwargs):
    global _match_count, _match_pixels
    _match_count += 1
    _match_pixels += int(image.shape[0]) * int(image.shape[1])
    return _orig_match(image, templ, method, *args, **kwargs)


cv2.matchTemplate = _counting_match


def reset_match_counters() -> None:
    global _match_count, _match_pixels
    _match_count = 0
    _match_pixels = 0


def match_count() -> int:
    return _match_count


def match_pixels() -> int:
    return _match_pixels


# ---- 环境 / 版本记录 ----
def git_head() -> dict:
    try:
        sha = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=15
        ).stdout.strip()
        branch = subprocess.run(
            ["git", "-C", str(ROOT), "branch", "--show-current"], capture_output=True, text=True, timeout=15
        ).stdout.strip()
        dirty = bool(subprocess.run(
            ["git", "-C", str(ROOT), "status", "--porcelain"], capture_output=True, text=True, timeout=15
        ).stdout.strip())
    except Exception as exc:  # pragma: no cover
        return {"repo_head": None, "branch": None, "dirty": None, "error": str(exc)}
    return {"repo_head": sha, "branch": branch, "dirty": dirty}


def template_sha256(images_dir: Path) -> str:
    """assets/Images 全部 PNG/JPG 的聚合 SHA256（按相对路径排序，逐文件字节）。"""
    h = hashlib.sha256()
    for p in sorted(images_dir.rglob("*.png")) + sorted(images_dir.rglob("*.jpg")):
        rel = str(p.relative_to(images_dir))
        data = np.fromfile(str(p), dtype=np.uint8)
        h.update(rel.encode("utf-8"))
        h.update(b"\x00")
        h.update(str(len(data)).encode("ascii"))
        h.update(b"\x00")
        h.update(data)
    return h.hexdigest()


def env_record() -> dict:
    try:
        import platform as _p

        cpu = _p.processor() or platform.machine()
    except Exception:
        cpu = "unknown"
    return {
        "python": sys.version.split()[0],
        "opencv": cv2.__version__,
        "numpy": np.__version__,
        "cpu": cpu,
        "machine": platform.machine(),
        "os": platform.platform(),
    }


# ---- fixture 装载 ----
def load_image(path: Path) -> np.ndarray | None:
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
        if data.size == 0:
            return None
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception:
        return None


def make_frame(bgr: np.ndarray, title: str = "英雄三国KK") -> Frame:
    return Frame(bgr, window_title=title, hwnd=10001)


def calibrate_ui_scale(w: int, h: int) -> float:
    if w < 200 or h < 200:
        return 1.0
    scale = min(w / REF_W, h / REF_H)
    return round(min(scale, 1.0), 3) if scale < 1.0 else 1.0


# ---- 决策阶段：镜像 _tick_impl 的分发（无 see/捕获、无 incident 副作用）----
L0_PHASES = {
    Phase.BOOT, Phase.WAIT_EXIT, Phase.LOBBY_ROOM, Phase.PREPARE, Phase.WAIT_UI,
    Phase.PLATFORM_MAP, Phase.CREATE_ROOM, Phase.ROOM_WAITING, Phase.ROOM_STARTING,
    Phase.STAGE_SELECT, Phase.STAGE_STARTING, Phase.HERO_SETUP,
}


def run_decision(med: Mediator, frame: Frame, health_ok: bool) -> dict:
    """返回 {context_ms, decision_ms, action, action_ms, fail_hit, context}。

    镜像 _tick_impl：健康门禁 → 全局 fail/disconnect 优先（面板互斥）→ 按阶段分发。
    输入为 dry-run（Settings.dry_run=True），绝不产生真实输入。
    """
    out: dict = {"context_ms": 0.0, "decision_ms": 0.0, "action": None, "action_ms": 0.0, "fail_hit": False, "context": None}
    if not health_ok:
        return out  # 生产在非静态不健康帧直接跳过决策
    t0 = time.perf_counter()
    context = med._detect_context(frame)
    out["context_ms"] = (time.perf_counter() - t0) * 1000.0
    out["context"] = context
    # 全局 fail/disconnect 优先（与 _tick_impl 一致：面板存在时跳过 fail 误检）
    panel_present = bool(med._selection_anchor(frame))
    fail_hit = med.find_scene(frame, "disconnect") or med.find_scene(frame, "fail")
    out["fail_hit"] = bool(fail_hit)
    if fail_hit and not panel_present:
        out["decision_ms"] = (time.perf_counter() - t0) * 1000.0
        return out
    t0 = time.perf_counter()
    if med.phase in L0_PHASES:
        action = med._tick_l0(frame)
    elif med.phase == Phase.MAIN_LINE:
        action = med._tick_main_line(frame)
    else:
        action = None
    out["decision_ms"] = (time.perf_counter() - t0) * 1000.0
    if action is not None:
        out["action"] = action.name
        # action 阶段 = 决策返回动作后的分派开销（dry-run 下 executor 零成本；
        # 真实输入另有 ~390ms 固定等待，见报告说明）
        ta = time.perf_counter()
        out["action_ms"] = 0.0  # 动作执行本身在决策内已完成（dry-run）；这里记录 0 + 说明
        out["action_dispatch_ms"] = (time.perf_counter() - ta) * 1000.0
    return out


# ---- tick 状态重置：exact-static 模式复用同一 Mediator 时需要（保持各次迭代同一代码路径）----
# 仅覆盖 tick 会变更的字段，显式给回初始值；context/scene 缓存类不在此列。
def reset_tick_state(med: Mediator, manifest_entry: dict) -> None:
    from shuabao.mediator import ChallengeState

    med._selection_click_cooldown_until = 0.0
    med._post_game_pending = False
    med._victory_continue_attempts = 0
    med._victory_continue_since = None
    med._post_game_close_attempts = 0
    med._selection_repeat_key = None
    med._selection_repeat_attempts = 0
    med._skill_refresh_attempts = 0
    med._auto_task_done = False
    med._auto_task_attempts = 0
    med._challenge_done = set()
    med._challenge_attempts = {}
    med._challenge_unknown_since = {}
    med._challenge_states = {k: ChallengeState.PENDING for k in med._challenge_states}
    med._failure_candidate_frames = 0
    med._failure_candidate_kind = None
    med._failure_candidate_gen = None
    med._recovery_step = None
    med._recovery_state = None
    med._main_line_since = None
    med._last_skill_panel = 0.0
    med._panel_opened_by_us = None
    med._selection_unknown_attempts = 0
    med._selection_unknown_since = None
    med._evolve_click_cooldown_until = 0.0
    # S0 状态机 tick 可变字段：与生产同语义重置（统计口径不变）
    med._round_started_at = None
    med._round_deadline = None
    med._outcome_recorded = False
    med._round_outcome = None
    med._last_outcome = None
    med._failure_streak = 0
    med._panel_state = PanelState.CLOSED
    med._panel_kind = None
    med._panel_episode_started = None
    med._panel_visible_deadline = None
    med._panel_mutation_baseline = None
    med._panel_last_input_at = 0.0
    med._panel_episode_count = {}
    med._panel_cooldown_until = {}
    med._panel_fingerprint = None
    med._panel_fingerprint_attempts = 0
    med._ambiguous_giveup_frames = 0
    med._exit_button_attempts = 0
    med._exit_confirm_attempts = 0
    med._exit_since = None
    med._stage_click_cooldown_until = 0.0
    med._stage_scroll_cooldown_until = 0.0
    med._stage_selected = False
    med._room_dialog_filled = False
    med._room_action_deadline = None
    med._room_action_attempts = 0
    med._l0_cycle_count = 0
    med._challenge_start_state = None
    med._challenge_start_attempts = 0
    med._challenge_start_deadline = None
    med._challenge_start_hud_frames = 0
    med._challenge_start_hero_modal_frames = 0
    med._aux_dialog_attempts = {"HEIRLOOM_DIALOG": 0, "GREAT_RIFT_CONFIRM": 0}
    med._longzhu_deadline = None
    med._boss_clicked = False
    med._f1_fallback_done = False
    med._last_frame = None
    med._prev_frame = None
    med._last_capture_role = None
    # 注意：_context_cache_* 故意不清空 —— 生产 see() 对静态帧（同对象）恒命中
    # context 缓存（_context_cache_frame is frame），这正是 exact-static 的关键路径。


def fresh_mediator(manifest_entry: dict) -> Mediator:
    med = Mediator(Settings(), ROOT)
    skills = manifest_entry.get("skills")
    if skills:
        med.settings.skills = list(skills)
    med.set_phase(Phase[manifest_entry.get("expected_phase", "MAIN_LINE")], "benchmark")
    return med


# ---- 单次 tick 基准 ----
@dataclass
class StageTiming:
    capture_ms: float = 0.0
    health_ms: float = 0.0
    context_ms: float = 0.0
    decision_ms: float = 0.0
    action_ms: float = 0.0
    total_ms: float = 0.0
    match_calls: int = 0
    match_pixels: int = 0
    context: str | None = None
    action: str | None = None


def bench_one(
    med: Mediator, frame: Frame, prev: Frame | None,
    entry: dict, decode_ms: float, health_ok_override: bool | None = None,
) -> StageTiming:
    reset_match_counters()
    med._scene_cache.clear()  # 镜像 see()
    med._last_frame = frame
    med._prev_frame = prev
    st = StageTiming(capture_ms=decode_ms)

    t0 = time.perf_counter()
    health = check_frame_health(frame, prev_frame=prev)
    st.health_ms = (time.perf_counter() - t0) * 1000.0
    if health_ok_override is not None:
        health_ok = health_ok_override
    else:
        # 镜像 _tick_impl：frozen/old_frame 属静态帧放行，其余不健康跳过决策
        issue_values = {i.value for i in health.issues}
        health_ok = health.is_healthy or issue_values.issubset({"frozen", "old_frame"})

    res = run_decision(med, frame, health_ok)
    st.decision_ms = res["decision_ms"]
    st.context_ms = res["context_ms"]
    st.action_ms = res["action_ms"]
    st.context = res["context"]
    st.action = res["action"]
    st.match_calls = match_count()
    st.match_pixels = match_pixels()
    st.total_ms = st.capture_ms + st.health_ms + st.context_ms + st.decision_ms + st.action_ms
    return st


# ---- 每种模式跑 N 次 ----
def bench_mode(
    entry: dict, iterations: int,
) -> dict:
    t_decode = time.perf_counter()
    bgr = load_image(FIXTURES_DIR / entry["file"])
    decode_ms = (time.perf_counter() - t_decode) * 1000.0  # capture 阶段代理：帧解码
    if bgr is None:
        return {"error": "fixture read error", "mode": entry["mode"]}
    ui_scale = calibrate_ui_scale(bgr.shape[1], bgr.shape[0])
    title = entry.get("window_title", "英雄三国KK")
    runs: list[StageTiming] = []

    if entry["mode"] == "cold":
        clear_template_cache()
        for _ in range(iterations):
            frame = make_frame(bgr.copy(), title)
            med = fresh_mediator(entry)
            med._ui_scale = ui_scale
            runs.append(bench_one(med, frame, None, entry, decode_ms))
    elif entry["mode"] == "warm_changed":
        clear_template_cache()
        med0 = fresh_mediator(entry)  # 预热模板缓存
        bench_one(med0, make_frame(bgr.copy(), title), None, entry, 0.0)
        for _ in range(iterations):
            frame = make_frame(bgr.copy(), title)
            med = fresh_mediator(entry)
            med._ui_scale = ui_scale
            runs.append(bench_one(med, frame, None, entry, decode_ms))
    else:  # exact_static
        clear_template_cache()
        med0 = fresh_mediator(entry)
        frame0 = make_frame(bgr.copy(), title)
        med0._ui_scale = ui_scale
        bench_one(med0, frame0, None, entry, 0.0)  # 预热
        for _ in range(iterations):
            reset_tick_state(med0, entry)
            med0._ui_scale = ui_scale
            runs.append(bench_one(med0, frame0, None, entry, 0.0))

    def agg(attr: str) -> dict:
        vals = sorted(getattr(r, attr) for r in runs)
        return {
            "p50_ms": round(statistics.median(vals), 1),
            "p95_ms": round(vals[min(len(vals) - 1, int(0.95 * len(vals)))], 1),
            "min_ms": round(vals[0], 1),
            "max_ms": round(vals[-1], 1),
            "samples": len(vals),
        }

    return {
        "mode": entry["mode"],
        "fixture": entry["fixture_id"],
        "total_ms": agg("total_ms"),
        "capture_ms": agg("capture_ms"),
        "health_ms": agg("health_ms"),
        "context_ms": agg("context_ms"),
        "decision_ms": agg("decision_ms"),
        "action_ms": agg("action_ms"),
        "match_calls": agg("match_calls"),
        "match_pixels": agg("match_pixels"),
        "contexts": sorted({r.context for r in runs}),
        "actions": sorted({r.action for r in runs if r.action}),
    }


# ---- 实时捕获基准（可选，尽力而为）----
def live_capture_bench(iterations: int = 5) -> dict:
    from shuabao.vision import capture as cap_mod

    out: dict = {"enabled": True}
    try:
        targets = cap_mod.find_window_targets("英雄三国KK", role="l1")
        if not targets:
            targets = cap_mod.find_window_targets("KK", role="l0")
    except Exception as exc:
        out.update({"note": f"window scan failed: {exc}", "times_ms": []})
        return out
    try:
        if targets:
            tgt = targets[0]
            times = []
            for _ in range(iterations):
                t0 = time.perf_counter()
                cap_mod.capture_target(tgt, activate=False)
                times.append((time.perf_counter() - t0) * 1000.0)
            out.update({"target": tgt.title, "hwnd": tgt.hwnd, "times_ms": [round(t, 1) for t in times]})
        else:
            import mss
            times = []
            with mss.mss() as sct:
                mon = sct.monitors[1]
                for _ in range(iterations):
                    t0 = time.perf_counter()
                    sct.grab(mon)
                    times.append((time.perf_counter() - t0) * 1000.0)
            out.update({"target": "full-screen reference (no game window found)", "times_ms": [round(t, 1) for t in times]})
    except Exception as exc:
        out.update({"note": f"capture failed: {exc}", "times_ms": []})
    return out


# ---- 主流程 ----
def load_manifest() -> list[dict]:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return data["fixtures"]


def build_entries(fixtures: list[dict]) -> list[dict]:
    entries = []
    for f in fixtures:
        if f.get("missing_resource"):
            continue
        for mode in ("cold", "warm_changed", "exact_static"):
            e = dict(f)
            e["mode"] = mode
            entries.append(e)
    return entries


def main() -> int:
    ap = argparse.ArgumentParser(description="N0 hot-path benchmark (per-fixture, 3 modes)")
    ap.add_argument("--iterations", type=int, default=3, help="per mode iterations (default 3)")
    ap.add_argument("--out-dir", type=Path, default=ROOT / "docs" / "baselines")
    ap.add_argument("--fixture", default=None, help="run only one fixture_id (debug)")
    ap.add_argument("--no-live-capture", action="store_true", help="skip live capture section")
    args = ap.parse_args()

    fixtures = load_manifest()
    if args.fixture:
        fixtures = [f for f in fixtures if f["fixture_id"] == args.fixture]
    entries = build_entries(fixtures)
    if not entries:
        print(f"no fixtures to run (manifest: {MANIFEST})", file=sys.stderr)
        return 2

    head = git_head()
    env = env_record()
    tpl_sha = template_sha256(IMAGES_DIR)
    run_ts = time.strftime("%Y-%m-%dT%H:%M:%S")

    results = []
    t_start = time.perf_counter()
    for e in entries:
        r = bench_mode(e, args.iterations)
        r["fixture_id"] = e["fixture_id"]
        r["file"] = e["file"]
        r["expected_context"] = e.get("expected_context")
        r["expected_phase"] = e.get("expected_phase")
        r["expected_health"] = e.get("expected_health")
        exp_ctx = e.get("expected_context")
        obs_ctxs = [c for c in (r.get("contexts") or []) if c is not None]
        if exp_ctx and exp_ctx in obs_ctxs:
            ctx_pass = True
        elif not obs_ctxs and str(e.get("expected_health", "")).startswith("unhealthy"):
            ctx_pass = True  # 健康门禁拦截 → 无 context（黑屏类）
        elif not obs_ctxs and exp_ctx == "UNKNOWN":
            ctx_pass = True  # 决策被跳过时以健康门禁为准
        else:
            ctx_pass = bool(exp_ctx and exp_ctx in obs_ctxs)
        r["context_verified"] = bool(ctx_pass)
        results.append(r)
        print(
            f"[{time.strftime('%H:%M:%S')}] {e['fixture_id']:<14} {e['mode']:<13} "
            f"total P50={r.get('total_ms', {}).get('p50_ms')}ms "
            f"matches P50={r.get('match_calls', {}).get('p50_ms')} "
            f"pixels P50={r.get('match_pixels', {}).get('p50_ms')} "
            f"ctx_ok={r.get('context_verified')}",
            flush=True,
        )
    elapsed_s = time.perf_counter() - t_start

    live = {} if args.no_live_capture else live_capture_bench()

    report = {
        "schema": "N0-benchmark-v1",
        "generated_at": run_ts,
        "elapsed_s": round(elapsed_s, 1),
        "git": head,
        "environment": env,
        "template_sha256": tpl_sha,
        "template_count": len(list(IMAGES_DIR.rglob("*.png"))) + len(list(IMAGES_DIR.rglob("*.jpg"))),
        "iterations_per_mode": args.iterations,
        "fixtures": results,
        "live_capture_ms": live,
    }

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "N0_BENCHMARK.json"
    md_path = out_dir / "N0_BENCHMARK.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    return 0


def render_markdown(report: dict) -> str:
    lines = [
        "# N0 热路径基准报告",
        "",
        f"> 生成时间：{report['generated_at']}（耗时 {report['elapsed_s']}s）",
        f"> repo HEAD：{report['git'].get('repo_head') or 'MISSING'}（branch={report['git'].get('branch')}，dirty={report['git'].get('dirty')}）",
        f"> 环境：Python {report['environment']['python']} / OpenCV {report['environment']['opencv']} / numpy {report['environment']['numpy']} / CPU {report['environment']['cpu']}",
        f"> 模板聚合 SHA256：`{report['template_sha256']}`（{report['template_count']} 个文件，assets/Images）",
        f"> 每模式迭代数：{report['iterations_per_mode']}",
        "",
        "## 逐 fixture 结果（P50 ms / P95 ms）",
        "",
        "| fixture | mode | total P50/P95 | capture | health | context | decision | action | matches P50 | pixels P50 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in report["fixtures"]:
        t = r["total_ms"]
        lines.append(
            f"| {r['fixture_id']} | {r['mode']} | {t['p50_ms']}/{t['p95_ms']} | "
            f"{r['capture_ms']['p50_ms']} | {r['health_ms']['p50_ms']} | {r['context_ms']['p50_ms']} | "
            f"{r['decision_ms']['p50_ms']} | {r['action_ms']['p50_ms']} | "
            f"{r['match_calls']['p50_ms']} | {r['match_pixels']['p50_ms']} |"
        )
    lines += ["", "## 实时捕获参考（本机）", ""]
    lc = report.get("live_capture_ms") or {}
    if lc.get("times_ms"):
        times = lc["times_ms"]
        lines.append(f"- target: {lc.get('target')}")
        lines.append(f"- times_ms: {times}  P50={statistics.median(times):.1f}  P95={sorted(times)[max(0, int(0.95*len(times))-1)]:.1f}")
    else:
        lines.append(f"- {lc.get('note', 'skipped')}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
