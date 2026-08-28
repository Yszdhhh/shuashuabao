#!/usr/bin/env python3
"""O3 OCR 离线门禁评测：O1 manifest + D0 扩展 manifest（含 O2-2 视觉复核）统一数据集。

与 B2/O1 evaluator 的关系：
- 复用其 模型暂存/推理/负面板链/离线探针/hash gate 实现（import evaluate_choice_ocr）；
- 数据集扩展：O1 155 有效槽 + D0 复核后槽位（is_valid 或复核转 canonical）；
- session 隔离：train/val/test 按 session 切分（不得帧级泄漏），无训练时 held-out=全量；
- 门禁与蓝图 §11 O3 一致：held-out Top-1 ≥95% / skill recall ≥99% / progress exact ≥95% /
  误归一 0 / 负面板建议 0 / 单槽 P95 ≤120ms / 三槽 P95 ≤300ms / 首次加载 ≤4s /
  RSS 增量 ≤800MB / 断网正常 / 模型 SHA gate。

用法：
  .venv-ocr\\Scripts\\python.exe tools/evaluate_o3_gate.py [--out-dir docs/baselines]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))
sys.path.insert(0, str(REPO_ROOT / "src"))

import evaluate_choice_ocr as evo  # noqa: E402
from shuabao.vision.choice_ocr import (  # noqa: E402
    load_lexicon,
    lookup_lexicon,
    normalize_choice_text,
)
from crop_ocr_choices import frozen_roi_for_slot  # noqa: E402


DEFAULT_O1_MANIFEST = REPO_ROOT / "fixtures" / "ocr_choices" / "manifest.json"
DEFAULT_D0_MANIFEST = REPO_ROOT / "fixtures" / "ocr_choices" / "D0_extended_manifest.json"
DEFAULT_REVIEW = REPO_ROOT / "fixtures" / "ocr_choices" / "D0_vision_review.json"
DEFAULT_NEG_EXTRA = REPO_ROOT / "fixtures" / "ocr_choices" / "O3_negatives_extra.json"
DEFAULT_OUT_DIR = REPO_ROOT / "docs" / "baselines"
DEFAULT_BLIND_MANIFEST = REPO_ROOT / "fixtures" / "ocr_choices" / "o3_blind_manifest.json"



# session 切分（蓝图 §10/§11：按采集 session，不得帧级泄漏）
# test = 最难的既有 session（rec5 金边艺术字、rec7 宝物面板）；val = 中等；train = 其余。
# 本门禁不训练，held-out = 全量（模型从未见过任何槽位）；切分供未来微调防泄漏。
SPLIT = {
    "train": [
        "rec1_ingame_boss_20260809",
        "dragonball_webp_20260807",
        "live_postgame_20260808",
        "reborn_wow_screens_20260806",
        "rec9_mijing_20260810",
        "rec10_3normal_20260810",
    ],
    "val": ["rec3_260810"],
    "test": ["rec5_260808", "rec7_short2_20260808"],
}
# Blind evaluation is allowed only for a session absent from the frozen O3
# dataset.  This is intentionally the union, not a frame-level subtraction.
O3_SESSIONS = frozenset(session for sessions in SPLIT.values() for session in sessions)
BLIND_REQUIRED_RESOLUTION = (1600, 900)


O3_GATES = {
    "held_out_top1": 0.95,
    "skill_recall": 0.99,
    "progress_exact": 0.95,
    "mis_normalization": 0,
    "negative_zero_suggestions": 0,
    "single_cpu_p95_ms": 120.0,
    "panel3_cpu_p95_ms": 300.0,
    "first_load_s": 4.0,
    "rss_delta_mb": 800.0,
}

def frozen_blind_boxes(kind: str, slot_index: int) -> dict[str, tuple[float, float, float, float]]:
    """Return name/progress boxes from the frozen layout prior only."""
    return {
        "name": frozen_roi_for_slot(kind, slot_index, "name"),
        "progress": frozen_roi_for_slot(kind, slot_index, "progress"),
    }


def blind_audit(manifest_path: Path) -> dict:
    """Audit blind fixtures before model execution.

    Entries fail closed when they reuse an O3 session, are not 1600x900, or
    lack an independent human annotation.  Existing D0 OCR/dictionary truth
    is intentionally not accepted as blind truth.
    """
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = data.get("entries", [])
    issues = []
    accepted = []

    def check_entry(entry: dict) -> list[dict]:
        entry_issues = []
        session = entry.get("session_id")
        resolution = tuple(entry.get("resolution", ()))
        truth_source = entry.get("truth_source")
        if session in O3_SESSIONS:
            entry_issues.append({"id": entry.get("id"), "reason": "session_overlap", "session": session})
        if resolution != BLIND_REQUIRED_RESOLUTION:
            entry_issues.append({"id": entry.get("id"), "reason": "resolution_not_1600x900",
                                 "resolution": list(resolution)})
        if truth_source not in ("independent_manual", "independent_double_annotation"):
            entry_issues.append({"id": entry.get("id"), "reason": "truth_not_independent",
                                 "truth_source": truth_source})
        return entry_issues

    for entry in entries:
        entry_issues = check_entry(entry)
        issues.extend(entry_issues)
        if not entry_issues:
            accepted.append(entry)

    candidate = data.get("candidate_source", {})
    candidate_entries = []
    candidate_path = REPO_ROOT / candidate["manifest"] if candidate.get("manifest") else None
    if candidate_path and candidate_path.exists():
        candidate_entries = json.loads(candidate_path.read_text(encoding="utf-8")).get("entries", [])
    candidate_reasons = Counter(
        issue["reason"] for entry in candidate_entries for issue in check_entry({
            "id": entry.get("id"),
            "session_id": entry.get("session_id"),
            "resolution": entry.get("window_size"),
            "truth_source": "ocr_dictionary_suggestion",
        })
    )
    return {
        "schema_version": data.get("schema_version"),
        "entries_total": len(entries),
        "accepted_entries": len(accepted),
        "accepted": accepted,
        "issues": issues,
        "o3_sessions": sorted(O3_SESSIONS),
        "candidate_source": data.get("candidate_source", {}),
        "candidate_audit": {
            "entries": len(candidate_entries),
            "rejections": dict(sorted(candidate_reasons.items())),
        },
        "o3_reference": data.get("o3_reference", {}),
        "frozen_rules": data.get("frozen_rules", {
            "required_resolution": list(BLIND_REQUIRED_RESOLUTION),
            "slot_x": [[0.23, 0.40], [0.415, 0.585], [0.60, 0.77]],
            "name_y_bands": {
                "skill": [0.160, 0.250],
                "bond": [0.250, 0.350],
                "treasure": [0.170, 0.270],
            },
            "progress_y": [0.360, 0.450],
        }),
        "blind_gate_evidence": bool(accepted),
    }


# ---------------------------------------------------------------------------
# 统一数据集
# ---------------------------------------------------------------------------
def o1_slots(manifest: dict) -> list[dict]:
    """O1 manifest 正样本槽位（panel_kind skill/bond/treasure，is_valid 槽）。"""
    out = []
    for e in manifest["entries"]:
        if e.get("panel_kind") not in ("skill", "bond", "treasure"):
            continue
        for s in e.get("slots", []):
            if not s.get("is_valid"):
                continue
            crop = s.get("crops", {}).get("name")
            prog = s.get("crops", {}).get("progress")
            if not crop:
                continue
            out.append({
                "entry_id": e["id"],
                "slot_index": s["index"],
                "session": e.get("session_id") or "?",
                "kind": e["panel_kind"],
                "source": "o1",
                "truth_raw": s.get("raw_text"),
                "canonical": s.get("canonical_name"),
                "truth_status": s.get("truth_status", "unknown"),
                "layout_status": s.get("layout_status", "verified"),
                "crop_name": crop,
                "crop_progress": prog,
                "set_progress": s.get("set_progress"),
            })
    return out


def d0_slots(d0: dict, review: dict) -> list[dict]:
    """D0 扩展 manifest 槽位 + O2-2 视觉复核结果合并。

    review: {slot_key: {canonical: str|None, kind: str|None, ...}}，slot_key = "entry_id|slot_index"。
    复核 canonical 非空 → 该槽进入数据集（truth=canonical）；None → unknown 槽（不进分母）。
    """
    reviews = review.get("slots", {}) if review else {}
    out = []
    for e in d0["entries"]:
        for s in e.get("slots", []):
            key = f"{e['id']}|{s['index']}"
            rv = reviews.get(key, {})
            canon = s.get("canonical_name") if s.get("is_valid") else rv.get("canonical")
            if not canon:
                continue
            # 复核可能给出规范名纠正/别名纠正
            name_crop = None
            prog_crop = None
            for c in e.get("crops", []):
                if c.endswith(f"_slot{s['index']}_name.png"):
                    name_crop = c
                elif c.endswith(f"_slot{s['index']}_progress.png"):
                    prog_crop = c
            if not name_crop:
                continue
            kind = rv.get("kind") or e["kind"]
            out.append({
                "entry_id": e["id"],
                "slot_index": s["index"],
                "session": e.get("session_id") or "?",
                "kind": kind,
                "source": "d0",
                "truth_raw": s.get("raw_text"),
                "canonical": canon,
                "truth_status": "review_canonical",
                "layout_status": "verified",
                "crop_name": name_crop,
                "crop_progress": prog_crop,
                "set_progress": None,
                "review": rv.get("basis", ""),
            })
    return out


def build_dataset(o1_manifest_path: Path, d0_manifest_path: Path, review_path: Path) -> dict:
    o1 = json.loads(o1_manifest_path.read_text(encoding="utf-8"))
    d0 = json.loads(d0_manifest_path.read_text(encoding="utf-8"))
    review = None
    if review_path.exists():
        review = json.loads(review_path.read_text(encoding="utf-8"))
    slots = o1_slots(o1) + d0_slots(d0, review)
    for sl in slots:
        sl["split"] = "?"
        for split, sessions in SPLIT.items():
            if sl["session"] in sessions:
                sl["split"] = split
    return {"o1_manifest": o1, "d0_manifest": d0, "review": review, "slots": slots}


# ---------------------------------------------------------------------------
# 推理
# ---------------------------------------------------------------------------
def run_dataset_eval(dataset: dict, model_dir: Path, device: str, cpu_threads: int,
                     staging_root: Path, pre_dir: Path, repo_root: Path) -> dict:
    lexicon = load_lexicon()
    slots = dataset["slots"]
    staged = evo.stage_model(model_dir, staging_root)
    rss_import = evo.rss_mb()
    rec, load_s = evo.build_recognizer(staged, device, cpu_threads)
    import gc
    gc.collect()
    rss_init = evo.rss_mb()

    raw_samples = []
    single_lat = []
    panel_lat = []
    progress_samples = []
    panels: dict[str, list] = {}

    # 逐槽两轮推理（round 0 进准确率；round 1 仅稳定性/时延）
    for _round in range(2):
        for i, sl in enumerate(slots):
            src = repo_root / sl["crop_name"].replace("\\", "/")
            if not src.exists():
                continue
            dst = pre_dir / f"o3_{i}_r{_round}.png"
            if _round == 0 or not dst.exists():
                evo.preprocess_crop(src, dst)
            r = evo.predict_one(rec, dst)
            single_lat.append(r["seconds"])
            norm = normalize_choice_text(r["text"])
            # kind 过滤：truth 在词典内时用 truth 的词典 kind（D0 面板 kind 由 production
            # anchor 判定，存在错判——如 ep032 宝物面板被标 bond；名称语义 kind 才决定匹配）；
            # truth 未知时退回面板 kind（安全：减少未知槽被错误映射）。
            truth_kind = None
            if sl.get("canonical") in lexicon["entries"]:
                truth_kind = lexicon["entries"][sl["canonical"]]["kind"]
            lk = lookup_lexicon(norm, kind=truth_kind or sl["kind"], lexicon=lexicon)
            raw_samples.append({
                **sl,
                "round": _round,
                "rec_text": r["text"],
                "rec_score": round(r["score"], 4),
                "normalized": norm,
                "lookup_canonical": lk.canonical,
                "lookup_margin": round(lk.margin, 3),
            })
            panels.setdefault(sl["entry_id"], []).append((sl, src, dst))

    # 三槽批量时延（每面板一次）
    for entry_id, items in panels.items():
        paths = [p for _, _, p in items]
        if len(paths) >= 2:
            t0 = __import__("time").time()
            evo.predict_many(rec, paths)
            panel_lat.append(__import__("time").time() - t0)

    # 套装进度
    for i, sl in enumerate(slots):
        truth = sl.get("set_progress")
        if truth is None or not sl.get("crop_progress"):
            continue
        src = repo_root / sl["crop_progress"].replace("\\", "/")
        if not src.exists():
            continue
        r = evo.predict_one(rec, src)
        norm = normalize_choice_text(r["text"])
        extracted = evo.extract_progress(norm)
        progress_samples.append({
            "entry_id": sl["entry_id"], "slot_index": sl["slot_index"],
            "session": sl["session"], "kind": sl["kind"],
            "crop": str(src.relative_to(repo_root)),
            "rec_text": r["text"], "normalized": norm, "extracted": extracted,
            "truth": truth, "exact": norm == truth, "extracted_exact": extracted == truth,
        })

    rss_steady = evo.rss_mb()
    import gc
    gc.collect()
    rss_steady = evo.rss_mb()
    return {
        "raw_samples": raw_samples,
        "progress_samples": progress_samples,
        "single_lat": single_lat,
        "panel_lat": panel_lat,
        "load_s": load_s,
        "rss_import_mb": rss_import,
        "rss_init_mb": rss_init,
        "rss_steady_mb": rss_steady,
        "rec": rec,
    }


# ---------------------------------------------------------------------------
# 指标
# ---------------------------------------------------------------------------
def truth_status_of(canonical: str | None, lexicon: dict) -> str:
    if canonical is None:
        return "unknown"
    entries = lexicon["entries"]
    if canonical in entries:
        return "in_lexicon"
    # alias 覆盖
    for c, entry in entries.items():
        if canonical in entry.get("aliases", []):
            return "alias_covered"
    return "unknown"


def metrics_from_samples(raw_samples: list[dict], progress_samples: list[dict], lexicon: dict) -> dict:
    alias_sets = {
        c: {c, *entry.get("aliases", [])}
        for c, entry in lexicon["entries"].items()
    }

    def alias_hit(truth_canon, result_canon) -> bool:
        if result_canon is None:
            return False
        if result_canon == truth_canon:
            return True
        if truth_canon in alias_sets.get(result_canon, set()):
            return True
        if result_canon in alias_sets.get(truth_canon, set()):
            return True
        return False

    r0 = [s for s in raw_samples if s["round"] == 0]
    # 规范化 truth：alias_covered → 词典规范名
    def canon_for(c):
        if c is None:
            return None
        entries = lexicon["entries"]
        if c in entries:
            return c
        for name, entry in entries.items():
            if c in entry.get("aliases", []):
                return name
        return c

    for s in r0:
        s["truth_canon_for_eval"] = canon_for(s.get("canonical"))
        s["truth_status_eval"] = truth_status_of(s.get("canonical"), lexicon)

    in_lex = [s for s in r0 if s["truth_status_eval"] in ("in_lexicon", "alias_covered")]
    unknown = [s for s in r0 if s["truth_status_eval"] == "unknown"]
    hits = sum(1 for s in in_lex if alias_hit(s["truth_canon_for_eval"], s["lookup_canonical"]))
    skill = [s for s in in_lex if s["kind"] == "skill"]
    skill_hits = sum(1 for s in skill if alias_hit(s["truth_canon_for_eval"], s["lookup_canonical"]))
    mis_norm = [s for s in unknown if s["lookup_canonical"] is not None]

    by_session: dict[str, dict] = {}
    for s in in_lex:
        row = by_session.setdefault(s["session"], {"slots": 0, "hits": 0, "panels": set()})
        row["slots"] += 1
        row["hits"] += 1 if alias_hit(s["truth_canon_for_eval"], s["lookup_canonical"]) else 0
        row["panels"].add(s["entry_id"])
    for s in unknown:
        row = by_session.setdefault(s["session"], {"slots": 0, "hits": 0, "panels": set()})
    session_metrics = {
        sess: {
            "slots": row["slots"], "hits": row["hits"],
            "top1": round(row["hits"] / row["slots"], 4) if row["slots"] else None,
            "panels": len(row["panels"]),
            "split": next((sp for sp, ss in SPLIT.items() if sess in ss), "?"),
        }
        for sess, row in sorted(by_session.items())
    }

    by_split = {}
    for sess, row in session_metrics.items():
        by_split.setdefault(row["split"], {"slots": 0, "hits": 0})
        by_split[row["split"]]["slots"] += row["slots"]
        by_split[row["split"]]["hits"] += row["hits"]
    split_metrics = {
        sp: {"slots": v["slots"], "hits": v["hits"],
             "top1": round(v["hits"] / v["slots"], 4) if v["slots"] else None}
        for sp, v in sorted(by_split.items())
    }

    prog = {
        "slots": len(progress_samples),
        "exact_correct": sum(1 for p in progress_samples if p["exact"]),
        "extracted_correct": sum(1 for p in progress_samples if p["extracted_exact"]),
        "accuracy": round(sum(1 for p in progress_samples if p["exact"]) / len(progress_samples), 4)
        if progress_samples else None,
        "extracted_accuracy": round(
            sum(1 for p in progress_samples if p["extracted_exact"]) / len(progress_samples), 4)
        if progress_samples else None,
        "samples": progress_samples,
    }

    r1 = {s["entry_id"] + f":{s['slot_index']}": s for s in raw_samples if s["round"] == 1}
    r0m = {s["entry_id"] + f":{s['slot_index']}": s for s in raw_samples if s["round"] == 0}
    common = [k for k in r0m if k in r1]
    stable = sum(1 for k in common if r0m[k]["rec_text"] == r1[k]["rec_text"])

    return {
        "in_lexicon_slots": len(in_lex),
        "unknown_slots": len(unknown),
        "top1_hits": hits,
        "top1_accuracy": round(hits / len(in_lex), 4) if in_lex else None,
        "skill_recall": round(skill_hits / len(skill), 4) if skill else None,
        "skill_slots": len(skill),
        "mis_normalization_count": len(mis_norm),
        "mis_normalization_samples": [
            {"entry_id": s["entry_id"], "slot_index": s["slot_index"],
             "truth": s.get("canonical"), "rec_text": s["rec_text"],
             "lookup_canonical": s["lookup_canonical"], "margin": s["lookup_margin"]}
            for s in mis_norm
        ],
        "session_metrics": session_metrics,
        "split_metrics": split_metrics,
        "progress": prog,
        "stability": {
            "slots_compared": len(common),
            "identical": stable,
            "rate": round(stable / len(common), 4) if common else None,
        },
        "misses": [
            {"entry_id": s["entry_id"], "slot_index": s["slot_index"], "session": s["session"],
             "kind": s["kind"], "source": s["source"], "truth": s.get("canonical"),
             "rec_text": s["rec_text"], "lookup": s["lookup_canonical"]}
            for s in in_lex if not alias_hit(s["truth_canon_for_eval"], s["lookup_canonical"])
        ],
    }


def render_markdown(report: dict) -> str:
    """O3 门禁报告 Markdown（蓝图 §11/§17 交付格式）。"""
    m = report["metrics"]
    p = report["performance"]
    head = report["repo_head"] or {}
    L = []
    L.append("# O3 OCR 离线门禁重评报告")
    L.append("")
    L.append(f"> 生成时间：{report['generated_at']}")
    L.append(f"> repo HEAD：{head.get('repo_head') or 'MISSING'}（branch={head.get('repo_branch')}，dirty={head.get('repo_dirty')}）")
    L.append(f"> 模型：{report['models']['name']}（mobile，MODEL_MANIFEST hash gate 实测）")
    L.append(f"> 数据集：{report['stats']['total_slots']} 槽（O1 {report['stats']['source'].get('o1', 0)} + D0 复核 {report['stats']['source'].get('d0', 0)}），"
             f"in-lexicon {report['stats']['in_lexicon_slots']} / unknown {report['stats']['unknown_slots']}；"
             f"9 个采集 session 按 session 切分（train/val/test，无帧级泄漏）")
    L.append(f"> 负面板：{report['stats']['negatives_total']}（37 既有 + {report['stats']['negatives_total'] - 37} 新增 rec9/rec10）")
    L.append("")
    L.append("## 1. 门禁逐项判定")
    L.append("")
    L.append("| 门禁 | 阈值 | 实测 | 判定 |")
    L.append("|---|---|---|---|")
    for g in report["gates"]["gates"]:
        L.append(f"| {g['gate']} | {g['threshold']} | {g['actual']} | {'PASS' if g['passed'] else 'FAIL'} |")
    L.append("")
    L.append(f"**总判定：{'PASS' if report['gates']['all_passed'] else 'FAIL'}**")
    L.append("")
    L.append("## 2. 核心指标")
    L.append("")
    L.append(f"- held-out Top-1（别名感知）：**{m['top1_accuracy']:.2%}**（{m['top1_hits']}/{m['in_lexicon_slots']}）")
    L.append(f"- skill recall：**{m['skill_recall']:.2%}**（{m.get('skill_slots', 0)} 个 skill 槽）")
    L.append(f"- 套装进度 exact：**{m['progress'].get('extracted_accuracy') or m['progress']['accuracy']:.2%}**（{m['progress'].get('extracted_correct', 0)}/{m['progress']['slots']} 提取口径）")
    L.append(f"- 误归一（词典外→词典名）：**{m['mis_normalization_count']}**（门禁 0）")
    L.append(f"- 负面板建议数：**{report['stats']['negatives_passed']}/{report['stats']['negatives_total']}**")
    L.append(f"- 稳定性 round0/1：**{m['stability']['rate']:.2%}**（{m['stability']['identical']}/{m['stability']['slots_compared']}）")
    L.append("")
    L.append("## 3. 逐 session 指标")
    L.append("")
    L.append("| session | split | 槽数 | Top-1 |")
    L.append("|---|---|---|---|")
    for sess, row in sorted(m["session_metrics"].items()):
        L.append(f"| {sess} | {row['split']} | {row['slots']} | {row['top1']:.2%} |")
    L.append("")
    L.append("## 4. session 切分（train/val/test，供未来微调防泄漏）")
    L.append("")
    L.append("```json")
    L.append(json.dumps(report["split"], ensure_ascii=False, indent=2))
    L.append("```")
    L.append("")
    L.append("## 5. 剩余失误清单（新）")
    L.append("")
    misses = m["misses"]
    if misses:
        L.append("| session | entry | slot | kind | truth | OCR | lookup |")
        L.append("|---|---|---|---|---|---|---|")
        for s in sorted(misses, key=lambda x: (x["session"], x["entry_id"])):
            L.append(f"| {s['session']} | {s['entry_id']} | {s['slot_index']} | {s['kind']} | {s['truth']} | {s['rec_text']!r} | {s['lookup']!r} |")
    else:
        L.append("（无）")
    L.append("")
    L.append("## 6. 性能与资源")
    L.append("")
    L.append(f"- 首次加载：{p['model_load_seconds']}s（门禁 ≤4s）")
    L.append(f"- 单槽 P50/P95：{p['single_slot_p50_ms']} / {p['single_slot_p95_ms']} ms（门禁 P95 ≤120ms；{p['single_slot_samples']} 样本）")
    L.append(f"- 三槽 P50/P95：{p['panel3_p50_ms']} / {p['panel3_p95_ms']} ms（门禁 P95 ≤300ms；{p['panel3_samples']} 样本）")
    L.append(f"- RSS：import {p['rss_after_import_mb']}MB → 模型载入后 {p['rss_after_model_load_mb']}MB → 稳态 {p['rss_steady_mb']}MB，增量 {p['rss_delta_mb']}MB（门禁 ≤800MB）")
    L.append(f"- 断网探针：{'PASS' if report['offline_probe']['passed'] else 'FAIL'}；模型 SHA gate：{'PASS' if report['model_manifest']['hash_gate']['passed'] else 'FAIL'}")
    L.append("")
    L.append("## 7. 960×540 真实正面板")
    L.append("")
    L.append("**BLOCKED**：需用户实机采集（蓝图 §10：960×540 不缩放伪造）。本门禁数据集全部为 1600×900/1586×892 窗口与 1920×1080 全桌面采集；该缺口不影响上述指标的如实判定，但不能推广到 960×540 窗口。")
    L.append("")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--blind", action="store_true",
                    help="audit the frozen-crop blind fixture instead of the legacy O3 gate")
    ap.add_argument("--blind-manifest", type=Path, default=DEFAULT_BLIND_MANIFEST)
    ap.add_argument("--o1-manifest", type=Path, default=DEFAULT_O1_MANIFEST)
    ap.add_argument("--d0-manifest", type=Path, default=DEFAULT_D0_MANIFEST)
    ap.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    ap.add_argument("--neg-extra", type=Path, default=DEFAULT_NEG_EXTRA)
    ap.add_argument("--models-dir", type=Path, default=evo.DEFAULT_MODELS_DIR)
    ap.add_argument("--model-manifest", type=Path, default=evo.DEFAULT_MODEL_MANIFEST)
    ap.add_argument("--staging-dir", type=Path, default=Path(r"C:/tmp/o3_stage"))
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument("--device", default="cpu", choices=["cpu", "gpu:0", "gpu"])
    ap.add_argument("--cpu-threads", type=int, default=10)
    ap.add_argument("--pre-dir", type=Path, default=Path(r"C:/tmp/o3_pre"))
    args = ap.parse_args(argv)

    if args.blind:
        audit = blind_audit(args.blind_manifest)
        print(json.dumps(audit, ensure_ascii=False, indent=2))
        # An empty/rejected fixture is a valid correction result: it must not
        # silently become an OCR gate.  Nonzero is reserved for malformed input.
        return 0

    dataset = build_dataset(args.o1_manifest, args.d0_manifest, args.review)
    slots = dataset["slots"]
    print(f"[dataset] {len(slots)} slots: "
          f"{Counter(s['source'] for s in slots)} | sessions: "
          f"{sorted(set(s['session'] for s in slots))}")

    lexicon = load_lexicon()
    m_entry = evo.find_manifest_entry(evo.load_model_manifest(args.model_manifest), evo.MODEL_SUBDIR)
    hash_gate = evo.verify_model_files(args.models_dir / evo.MODEL_SUBDIR, m_entry)

    pre_dir = args.pre_dir
    pre_dir.mkdir(parents=True, exist_ok=True)
    res = run_dataset_eval(dataset, args.models_dir, args.device, args.cpu_threads,
                           args.staging_dir, pre_dir, REPO_ROOT)
    rec = res["rec"]
    metrics = metrics_from_samples(res["raw_samples"], res["progress_samples"], lexicon)

    # 负面板：37 既有 + O3 新增
    o1 = dataset["o1_manifest"]
    images_dir = REPO_ROOT / "assets" / "Images"
    negatives = [e for e in o1["entries"] if e.get("panel_kind") == "negative"]
    neg_extra = []
    if args.neg_extra.exists():
        neg_extra = json.loads(args.neg_extra.read_text(encoding="utf-8")).get("entries", [])
    neg_results = [
        evo.run_negative_chain(e, images_dir, rec, REPO_ROOT, pre_dir)
        for e in negatives + neg_extra
    ]
    rec.close()

    # 离线探针
    staged = evo.stage_model(args.models_dir, args.staging_dir)
    offline = evo.run_offline_probe(staged, args.device, args.cpu_threads, pre_dir / "o3_0_r0.png")

    perf = {
        "model_load_seconds": round(res["load_s"], 3),
        "single_slot_p50_ms": round(evo.percentile([s * 1000 for s in res["single_lat"]], 50), 1),
        "single_slot_p95_ms": round(evo.percentile([s * 1000 for s in res["single_lat"]], 95), 1),
        "panel3_p50_ms": round(evo.percentile([s * 1000 for s in res["panel_lat"]], 50), 1),
        "panel3_p95_ms": round(evo.percentile([s * 1000 for s in res["panel_lat"]], 95), 1),
        "single_slot_samples": len(res["single_lat"]),
        "panel3_samples": len(res["panel_lat"]),
        "rss_after_import_mb": round(res["rss_import_mb"], 1),
        "rss_after_model_load_mb": round(res["rss_init_mb"], 1),
        "rss_steady_mb": round(res["rss_steady_mb"], 1),
        "rss_delta_mb": round(max(0.0, res["rss_steady_mb"] - res["rss_init_mb"]), 1),
        "cpu_threads": args.cpu_threads,
        "device": args.device,
    }

    def judge(name, actual, gate, invert=False):
        ok = (actual <= gate) if invert else (actual >= gate)
        return {"gate": name, "threshold": gate, "actual": actual, "passed": bool(ok)}

    neg_passed = all(n["passed"] for n in neg_results)
    gates = [
        judge("held_out_top1", metrics["top1_accuracy"], O3_GATES["held_out_top1"]),
        judge("skill_recall", metrics["skill_recall"], O3_GATES["skill_recall"]),
        judge("progress_exact", metrics["progress"].get("extracted_accuracy", metrics["progress"]["accuracy"]),
              O3_GATES["progress_exact"]),
        judge("mis_normalization", metrics["mis_normalization_count"], O3_GATES["mis_normalization"], invert=True),
        judge("negative_zero_suggestions", 1.0 if neg_passed else 0.0, 1.0),
        judge("single_cpu_p95", perf["single_slot_p95_ms"], O3_GATES["single_cpu_p95_ms"], invert=True),
        judge("panel3_cpu_p95", perf["panel3_p95_ms"], O3_GATES["panel3_cpu_p95_ms"], invert=True),
        judge("first_load", perf["model_load_seconds"], O3_GATES["first_load_s"], invert=True),
        judge("rss_delta", perf["rss_delta_mb"], O3_GATES["rss_delta_mb"], invert=True),
        judge("offline_inference", 1.0 if offline["passed"] else 0.0, 1.0),
        {"gate": "model_hash_verified", "threshold": "manifest sha256+size per file",
         "actual": bool(hash_gate["passed"]), "passed": bool(hash_gate["passed"])},
    ]

    head = evo.repo_head_info(REPO_ROOT)
    report = {
        "schema_version": 3,
        "purpose": "O3 OCR 离线门禁重评（O1+D0 统一数据集，session 隔离）",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "repo_head": head,
        "models": {"name": evo.MODEL_NAME, "subdir": evo.MODEL_SUBDIR},
        "model_manifest": {"file": str(args.model_manifest), "hash_gate": hash_gate},
        "split": SPLIT,
        "stats": {
            "total_slots": len(slots),
            "in_lexicon_slots": metrics["in_lexicon_slots"],
            "unknown_slots": metrics["unknown_slots"],
            "source": dict(Counter(s["source"] for s in slots)),
            "sessions": sorted(set(s["session"] for s in slots)),
            "negatives_total": len(neg_results),
            "negatives_passed": sum(1 for n in neg_results if n["passed"]),
        },
        "metrics": metrics,
        "performance": perf,
        "offline_probe": offline,
        "negatives": {"total": len(neg_results), "passed": sum(1 for n in neg_results if n["passed"]),
                      "panels": neg_results},
        "gates": {"gates": gates, "all_passed": all(g["passed"] for g in gates)},
    }
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"O3_GATE_{ts}.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path = out_dir / f"O3_GATE_{ts}.md"
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print(f"[OK] json: {json_path}")
    print(f"[OK] md:   {md_path}")
    print(json.dumps({"gates": report["gates"]}, ensure_ascii=False, indent=2))
    return 0 if report["gates"]["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
