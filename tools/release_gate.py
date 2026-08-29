from __future__ import annotations

import sys
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
#!/usr/bin/env python3
"""发版门禁：把仓库既有的离线验证资产串成一条必过流水线。

背景：项目已有 pytest 套件、冻结回放、模板校验等资产，但从未被强制串联，
导致 `fixtures/baselines/replay_frozen` 在 r11 提交时已红 3 个场景却无人发现，
同期大厅建房链路连续两次回归（de77a19 / 42f3e95）。

设计要点：
  * **快照比对而非阈值**：门禁不要求"全绿"（那样会因已知过期期望永久红、被所有人忽略），
    而是把每一阶段结果与 docs/baselines/GATE_BASELINE.json 快照逐项比对。
    任何**偏离快照**都是 FAIL——新破坏立刻报警，已修好的项目提示更新快照。
  * **禁止静默 waiver**：快照里每个已知失败项必须带 `reason`；`--update-baseline`
    需显式 `--reason` 才能落盘，避免"改红为绿"混过门禁。
  * **纯离线零输入**：所有阶段不产生真实游戏输入，不依赖游戏在运行。
    实机检查（tools/diagnose_lobby.py）另行手动执行，不在本门禁内。

用法：
  python tools/release_gate.py                 # 跑门禁，退出码 0=PASS
  python tools/release_gate.py --json          # 机器可读汇总
  python tools/release_gate.py --skip pytest   # 跳过某阶段（调试用，会标记为 SKIPPED 并 FAIL）
  python tools/release_gate.py --update-baseline --reason "..."   # 刷新快照
"""


import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = ROOT / "docs" / "baselines" / "GATE_BASELINE.json"
RUNTIME_ASSET_MANIFEST = ROOT / "config" / "runtime_asset_manifest.json"

PYTHON = sys.executable


@dataclass
class StageResult:
    name: str
    title: str
    status: str  # PASS / FAIL / SKIPPED
    observed: dict = field(default_factory=dict)
    detail: str = ""
    duration_s: float = 0.0
    deviations: list[str] = field(default_factory=list)


def _run(argv: list[str], timeout: int = 1800) -> tuple[int, str]:
    proc = subprocess.run(
        argv,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


# --------------------------------------------------------------------------- #
# 各阶段采集器：只负责跑并抽出"可比对的观测值"，不做判定
# --------------------------------------------------------------------------- #

def stage_pytest() -> StageResult:
    started = time.time()
    code, out = _run([PYTHON, "-m", "pytest", "tests/test_live_tier_crossing_integration.py", "tests/test_mediator_equipment_fsm_integration.py", "tests/test_hero_mode_temporal.py", "tests/test_p0_security.py", "tests/test_p1_choice_fsm_contracts.py", "tests/test_dashboard_facade.py", "tests/test_dashboard_facade_runner.py", "tests/test_choice_policy.py", "tests/test_l1_cycle_recheck_merchant.py", "tests/contract", "-q", "--tb=short"])
    counts: dict[str, int] = {}
    for label in ("passed", "failed", "error", "xfailed", "xpassed", "skipped"):
        match = re.search(rf"(\d+) {label}", out)
        if match:
            counts[label] = int(match.group(1))
    tail = "\n".join(out.strip().splitlines()[-3:])
    return StageResult(
        name="pytest",
        title="单元/回归测试（tests/）",
        status="PASS" if code == 0 else "FAIL",
        observed=counts,
        detail=tail,
        duration_s=time.time() - started,
    )


_SCENE_ROW = re.compile(r"^(?P<scene>[a-z0-9_]+)\s*\|\s*\w+\s*\|\s*(?P<status>PASS|FAIL|BLOCKED)\b")


def stage_frozen_replay() -> StageResult:
    started = time.time()
    code, out = _run([PYTHON, "tools/run_frozen_replay.py"])
    scenes: dict[str, str] = {}
    for line in out.splitlines():
        match = _SCENE_ROW.match(line.strip())
        if match:
            scenes[match.group("scene")] = match.group("status")
    return StageResult(
        name="frozen_replay",
        title="冻结端到端回放（fixtures/baselines/replay_frozen）",
        status="PASS" if scenes else "FAIL",
        observed=scenes,
        detail="" if scenes else f"无法解析场景汇总（exit={code}）",
        duration_s=time.time() - started,
    )


def stage_scene_templates() -> StageResult:
    started = time.time()
    code, out = _run([PYTHON, "tools/validate_scenes.py"])
    observed: dict[str, int] = {}
    match = re.search(r"ok=(\d+) missing=(\d+)", out)
    if match:
        observed = {"ok": int(match.group(1)), "missing": int(match.group(2))}
    asset_result = stage_asset_leakage()
    for key, value in asset_result.observed.items():
        observed[f"asset_{key}"] = value
    return StageResult(
        name="scene_templates",
        title="scenes.json 模板完整性",
        status=(
            "PASS"
            if code == 0
            and observed.get("missing") == 0
            and asset_result.status == "PASS"
            else "FAIL"
        ),
        observed=observed,
        detail=(
            ("" if observed else f"无法解析 validate_scenes 输出（exit={code}）")
            + (f"; asset_gate={asset_result.detail}" if asset_result.detail else "")
        ),
        duration_s=time.time() - started,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stage_asset_leakage() -> StageResult:
    """Verify the whole ``ShuaBao.spec`` assets tree is runtime-only and pinned."""
    started = time.time()
    observed = {
        "spec_assets_root": 0,
        "manifest_schema": 0,
        "package_root_whole_tree": 0,
        "files": 0,
        "allowlisted": 0,
        "missing_allowlist": 0,
        "stale_manifest": 0,
        "forbidden_paths": 0,
        "metadata_missing": 0,
        "hash_mismatch": 0,
    }
    errors: list[str] = []

    spec_path = ROOT / "ShuaBao.spec"
    spec_text = spec_path.read_text(encoding="utf-8") if spec_path.is_file() else ""
    if re.search(r"PROJECT_ROOT\s*/\s*[\"']assets[\"']", spec_text):
        observed["spec_assets_root"] = 1
    else:
        errors.append("ShuaBao.spec does not declare the expected whole assets source")

    try:
        manifest = json.loads(RUNTIME_ASSET_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"runtime asset manifest unreadable: {exc}")
        manifest = {}
    if not isinstance(manifest, dict):
        errors.append("runtime asset manifest root must be an object")
        manifest = {}

    if manifest.get("schema_version") == 1:
        observed["manifest_schema"] = 1
    else:
        errors.append("runtime asset manifest schema_version must be 1")

    package_roots = manifest.get("package_roots") or []
    if any(
        item.get("source") == "assets"
        and item.get("target") == "assets"
        and item.get("mode") == "whole_tree"
        for item in package_roots
        if isinstance(item, dict)
    ):
        observed["package_root_whole_tree"] = 1
    else:
        errors.append("runtime asset manifest must pin the whole assets tree")

    asset_root = ROOT / "assets"
    actual = {
        path.relative_to(ROOT).as_posix(): path
        for path in asset_root.rglob("*")
        if path.is_file()
    }
    entries = manifest.get("entries") or []
    allowlist: dict[str, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("path"):
            errors.append("runtime asset manifest contains a malformed entry")
            continue
        path = str(entry["path"]).replace("\\", "/")
        if path in allowlist:
            errors.append(f"duplicate manifest path: {path}")
        allowlist[path] = entry

    observed["files"] = len(actual)
    missing_allowlist = sorted(set(actual) - set(allowlist))
    stale_manifest = sorted(set(allowlist) - set(actual))
    observed["missing_allowlist"] = len(missing_allowlist)
    observed["stale_manifest"] = len(stale_manifest)
    observed["allowlisted"] = len(set(actual) & set(allowlist))
    if missing_allowlist:
        errors.append(f"unallowlisted runtime assets: {missing_allowlist[:8]}")
    if stale_manifest:
        errors.append(f"stale manifest entries: {stale_manifest[:8]}")

    forbidden_tokens = [str(item).lower() for item in manifest.get("forbidden_path_tokens") or []]
    forbidden_paths = []
    metadata_missing = []
    hash_mismatch = []
    for rel, path in actual.items():
        if any(token in component.lower() for token in forbidden_tokens for component in Path(rel).parts):
            forbidden_paths.append(rel)
        entry = allowlist.get(rel)
        if entry is None:
            continue
        if not all(str(entry.get(key) or "").strip() for key in ("purpose", "provenance", "reason_required")):
            metadata_missing.append(rel)
        try:
            size_ok = int(entry.get("size_bytes", -1)) == path.stat().st_size
        except (TypeError, ValueError):
            size_ok = False
        if not size_ok or str(entry.get("sha256", "")).lower() != _sha256(path):
            hash_mismatch.append(rel)
    observed["forbidden_paths"] = len(forbidden_paths)
    observed["metadata_missing"] = len(metadata_missing)
    observed["hash_mismatch"] = len(hash_mismatch)
    if forbidden_paths:
        errors.append(f"forbidden runtime asset paths: {forbidden_paths[:8]}")
    if metadata_missing:
        errors.append(f"allowlist metadata missing: {metadata_missing[:8]}")
    if hash_mismatch:
        errors.append(f"runtime asset hash/size mismatch: {hash_mismatch[:8]}")

    return StageResult(
        name="asset_leakage",
        title="ShuaBao.spec 运行时资源泄漏门禁",
        status="PASS" if not errors else "FAIL",
        observed=observed,
        detail="; ".join(errors),
        duration_s=time.time() - started,
    )


def stage_contract() -> StageResult:
    """L0 大厅全链契约测试；目录不存在时如实报告，不静默跳过。"""
    started = time.time()
    contract_dir = ROOT / "tests" / "contract"
    if not contract_dir.is_dir():
        return StageResult(
            name="contract",
            title="L0 大厅全链契约回放（tests/contract/）",
            status="FAIL",
            observed={"present": 0},
            detail="tests/contract/ 不存在",
            duration_s=time.time() - started,
        )
    code, out = _run([PYTHON, "-m", "pytest", "tests/contract", "-q", "--tb=short"])
    counts: dict[str, int] = {}
    for label in ("passed", "failed", "error"):
        match = re.search(rf"(\d+) {label}", out)
        if match:
            counts[label] = int(match.group(1))
    counts["present"] = 1
    tail = "\n".join(out.strip().splitlines()[-3:])
    return StageResult(
        name="contract",
        title="L0 大厅全链契约回放（tests/contract/）",
        status="PASS" if code == 0 else "FAIL",
        observed=counts,
        detail=tail,
        duration_s=time.time() - started,
    )


STAGES = {
    "pytest": stage_pytest,
    "frozen_replay": stage_frozen_replay,
    "scene_templates": stage_scene_templates,
    "contract": stage_contract,
}


# --------------------------------------------------------------------------- #
# 快照比对
# --------------------------------------------------------------------------- #

def load_baseline() -> dict:
    if not BASELINE_PATH.is_file():
        return {}
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def compare(result: StageResult, baseline: dict, strict_release: bool = False) -> None:
    if strict_release:
        if result.status == "FAIL":
            result.deviations.append(f"strict-release 零缺陷模式拒绝非 PASS 状态: {result.name}")
        for key, val in result.observed.items():
            if val in ("FAIL", "BLOCKED"):
                result.status = "FAIL"
                result.deviations.append(f"strict-release 拒绝场景 {key}={val}")
    """把观测值与快照比对，偏离写进 result.deviations 并可翻转状态。"""
    expected = (baseline.get("stages") or {}).get(result.name)
    if expected is None:
        result.deviations.append("快照缺该阶段基线，请先 --update-baseline")
        result.status = "FAIL"
        return

    exp_observed = expected.get("observed") or {}

    if result.name == "frozen_replay":
        for scene, exp_status in sorted(exp_observed.items()):
            act_status = result.observed.get(scene, "MISSING")
            if act_status == exp_status:
                continue
            if exp_status in ("FAIL", "BLOCKED") and act_status == "PASS":
                result.deviations.append(f"{scene}: {exp_status} → PASS（已修好，请更新快照）")
            else:
                result.deviations.append(f"{scene}: 快照={exp_status} 实际={act_status}")
        for scene in sorted(set(result.observed) - set(exp_observed)):
            result.deviations.append(f"{scene}: 快照中不存在的新场景={result.observed[scene]}")
    elif result.name in ("pytest", "contract"):
        # 通过数只许涨不许跌：新增测试无需更新快照，删测试/跳过测试会被抓住。
        exp_pass = exp_observed.get("passed", 0)
        act_pass = result.observed.get("passed", 0)
        if result.observed.get("failed") or result.observed.get("error"):
            result.deviations.append(
                f"失败={result.observed.get('failed', 0)} 错误={result.observed.get('error', 0)}"
            )
        elif act_pass < exp_pass:
            result.deviations.append(f"通过数下降：快照={exp_pass} 实际={act_pass}（测试被删或被跳过？）")
        elif result.name == "contract" and not exp_observed.get("present"):
            result.deviations.append("快照记录 tests/contract/ 不存在，请更新快照")
    else:
        for key, exp_value in exp_observed.items():
            act_value = result.observed.get(key)
            if act_value != exp_value:
                result.deviations.append(f"{key}: 快照={exp_value} 实际={act_value}")

    if result.deviations:
        result.status = "FAIL"


def build_baseline(results: list[StageResult], reason: str, previous: dict) -> dict:
    stages: dict[str, dict] = {}
    prev_stages = previous.get("stages") or {}
    for result in results:
        entry: dict = {"title": result.title, "observed": result.observed}
        known: dict[str, str] = {}
        prev_known = (prev_stages.get(result.name) or {}).get("known_failures") or {}
        if result.name == "frozen_replay":
            for scene, status in sorted(result.observed.items()):
                if status in ("FAIL", "BLOCKED"):
                    known[scene] = prev_known.get(scene, "未填写原因（必须补）")
        if known:
            entry["known_failures"] = known
        stages[result.name] = entry
    return {
        "schema_version": 1,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "reason": reason,
        "note": (
            "发版门禁快照。任何偏离都会让 tools/release_gate.py 失败。"
            "known_failures 里的每一项必须写明原因；修好后请重新 --update-baseline。"
        ),
        "stages": stages,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="机器可读汇总")
    parser.add_argument("--skip", action="append", default=[], choices=sorted(STAGES), help="跳过阶段（调试用）")
    parser.add_argument("--only", action="append", default=[], choices=sorted(STAGES), help="只跑指定阶段")
    parser.add_argument("--strict-release", action="store_true", help="严苛零缺陷发版模式：不允许任何 FAIL 或 BLOCKED 场景")
    parser.add_argument("--update-baseline", action="store_true", help="用本次结果刷新快照")
    parser.add_argument("--reason", default="", help="刷新快照的原因（--update-baseline 必填）")
    args = parser.parse_args(argv)

    if args.update_baseline and not args.reason.strip():
        print("[ERROR] --update-baseline 必须带 --reason 说明为什么快照变了", file=sys.stderr)
        return 2

    selected = args.only or [name for name in STAGES if name not in args.skip]
    baseline = load_baseline()

    results: list[StageResult] = []
    for name in STAGES:
        if name not in selected:
            results.append(
                StageResult(name=name, title=name, status="SKIPPED", detail="被 --skip/--only 排除")
            )
            continue
        print(f"[gate] {name} ...", flush=True)
        result = STAGES[name]()
        if not args.update_baseline:
            compare(result, baseline, strict_release=args.strict_release)
        results.append(result)

    if args.update_baseline:
        ran = [r for r in results if r.status != "SKIPPED"]
        if len(ran) != len(STAGES):
            print("[ERROR] 刷新快照必须跑全部阶段（不要配合 --skip/--only）", file=sys.stderr)
            return 2
        doc = build_baseline(ran, args.reason.strip(), baseline)
        BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        BASELINE_PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[gate] 快照已更新: {BASELINE_PATH.relative_to(ROOT)}")
        for stage in doc["stages"].values():
            for scene, why in (stage.get("known_failures") or {}).items():
                if "必须补" in why:
                    print(f"  [WARN] known_failures[{scene}] 原因未填写")
        return 0

    print()
    print(f"{'阶段':<18}{'状态':<10}观测")
    for result in results:
        observed = json.dumps(result.observed, ensure_ascii=False) if result.observed else "-"
        print(f"{result.name:<18}{result.status:<10}{observed}")
        for deviation in result.deviations:
            print(f"  ! {deviation}")

    failed = [r for r in results if r.status != "PASS"]
    verdict = "PASS" if not failed else "FAIL"
    print()
    print(f"[gate] {verdict}（阶段 {len(results) - len(failed)}/{len(results)} 通过）")
    if failed:
        print("[gate] 未通过阶段: " + ", ".join(r.name for r in failed))
        print("[gate] 若偏离是有意的行为变更，先更新对应夹具期望，再 --update-baseline --reason ...")

    if args.json:
        print(json.dumps(
            {
                "verdict": verdict,
                "stages": {
                    r.name: {
                        "status": r.status,
                        "observed": r.observed,
                        "deviations": r.deviations,
                        "duration_s": round(r.duration_s, 2),
                    }
                    for r in results
                },
            },
            ensure_ascii=False,
            indent=1,
        ))

    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
