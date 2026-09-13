#!/usr/bin/env python3
"""Reproducible OCR benchmark for the Stage 2A vision evidence baseline.

This evaluator is deliberately read-only with respect to production code.  It
uses the same local PP-OCRv5 rec model and the same labeled crop set for two
candidate paths:

``current_6_variant``
    The six preprocessing variants and lexicon-gated best-candidate rule used
    by ``src/shuabao/vision/ocr_shadow/worker.py``.

``gray_2x``
    One grayscale crop resized 2x with Lanczos.  It is a benchmark candidate
    only; this script never changes the worker or production settings.

The report separates OCR recognition false positives (a wrong canonical name)
from negative-panel false positives.  The JSONL corpus contains labeled
positive title crops, so the latter is reported as ``not_available`` rather
than being invented from positive samples.  Historical O3 (388 slots / 9
sessions) remains a reference and is explicitly marked non-comparable to this
155-sample corpus.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))
sys.path.insert(0, str(REPO_ROOT / "src"))

import evaluate_choice_ocr as evo  # noqa: E402
from shuabao.vision.choice_ocr import (  # noqa: E402
    load_lexicon,
    lookup_lexicon,
    normalize_choice_text,
)


DEFAULT_MANIFEST = REPO_ROOT / "docs" / "distillation" / "VISION_EVAL_MANIFEST.jsonl"
DEFAULT_MODELS_DIR = REPO_ROOT / "models" / "ocr"
DEFAULT_MODEL_MANIFEST = DEFAULT_MODELS_DIR / "MODEL_MANIFEST.json"
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "distillation" / "VISION_OCR_BENCHMARK.json"
DEFAULT_MODEL_SUBDIR = "PP-OCRv5_mobile_rec_infer"
DEFAULT_MODEL_NAME = "PP-OCRv5_mobile_rec"

SCENE_TO_KIND = {
    "skill_choice": "skill",
    "bond_choice": "bond",
    "treasure_choice": "treasure",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_jsonl_manifest(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    meta: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        item = json.loads(raw)
        if not isinstance(item, dict):
            raise ValueError(f"{path}:{line_no}: manifest row is not an object")
        if "_manifest" in item:
            meta = dict(item["_manifest"] or {})
        else:
            rows.append(item)
    if not rows:
        raise ValueError(f"{path}: no sample rows")
    return meta, rows


def resolve_corpus_root(meta: dict[str, Any], rows: list[dict[str, Any]], override: Path | None) -> Path:
    if override is not None:
        return (override if override.is_absolute() else REPO_ROOT / override).resolve()
    configured = meta.get("corpus_root") or rows[0].get("corpus_root")
    if not configured:
        raise ValueError("manifest must declare corpus_root")
    configured_path = Path(str(configured))
    return (configured_path if configured_path.is_absolute() else REPO_ROOT / configured_path).resolve()


def resolve_source(row: dict[str, Any], corpus_root: Path) -> Path:
    raw = str(row.get("source_crop") or "").replace("\\", "/")
    rel = Path(raw)
    if not raw or rel.is_absolute() or ".." in rel.parts:
        raise ValueError(f"invalid source_crop for {row.get('sample_id')!r}: {raw!r}")
    path = (corpus_root / rel).resolve()
    try:
        path.relative_to(corpus_root)
    except ValueError as exc:
        raise ValueError(f"source_crop escapes corpus_root: {raw!r}") from exc
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def validate_rows(meta: dict[str, Any], rows: list[dict[str, Any]], corpus_root: Path) -> dict[str, Any]:
    sample_ids = [str(row.get("sample_id") or "") for row in rows]
    if any(not value for value in sample_ids) or len(set(sample_ids)) != len(sample_ids):
        raise ValueError("sample_id values must be non-empty and unique")
    sessions: dict[str, set[str]] = defaultdict(set)
    clusters: dict[str, set[str]] = defaultdict(set)
    cluster_kinds: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        session = str(row.get("capture_session") or "").strip()
        split = str(row.get("split") or "").strip()
        cluster = str(row.get("duplicate_cluster_id") or "").strip()
        if not session:
            raise ValueError(f"missing capture_session: {row.get('sample_id')!r}")
        if split not in {"TRAIN_TUNE", "BLIND_HOLDOUT"}:
            raise ValueError(f"unsupported split {split!r}: {row.get('sample_id')!r}")
        if not re.fullmatch(r"phash_dhash_cluster_\d{4}", cluster):
            raise ValueError(f"duplicate_cluster_id is not algorithmic: {cluster!r}")
        source = resolve_source(row, corpus_root)
        if row.get("sha256") and str(row["sha256"]).lower() != _sha256(source):
            raise ValueError(f"source hash mismatch: {source}")
        sessions[session].add(split)
        clusters[cluster].add(split)
        cluster_kinds[cluster].add(str(row.get("duplicate_cluster_kind") or "unique"))
    bad_sessions = {key: sorted(value) for key, value in sessions.items() if len(value) > 1}
    bad_clusters = {key: sorted(value) for key, value in clusters.items() if len(value) > 1}
    if bad_sessions or bad_clusters:
        raise ValueError(
            f"split leakage: sessions={bad_sessions or 'none'} clusters={bad_clusters or 'none'}"
        )
    if str(meta.get("format") or "jsonl") != "jsonl":
        raise ValueError("unexpected manifest format")
    return {
        "samples": len(rows),
        "sessions": len(sessions),
        "train_tune": sum(1 for row in rows if row["split"] == "TRAIN_TUNE"),
        "blind_holdout": sum(1 for row in rows if row["split"] == "BLIND_HOLDOUT"),
        "duplicate_clusters": len(clusters),
        "near_duplicate_clusters": sum(
            1 for cluster in cluster_kinds.values() if "near_duplicate" in cluster
        ),
        "exact_duplicate_clusters": sum(
            1 for cluster in cluster_kinds.values() if "exact_duplicate" in cluster
        ),
        "source_files_exist": True,
    }


def _read_bgr(path: Path) -> np.ndarray:
    encoded = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        raise ValueError(f"cannot decode {path}")
    return image


def _worker_variants(bgr: np.ndarray) -> list[tuple[str, np.ndarray]]:
    b, g, r = (bgr[:, :, index] for index in range(3))
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return [
        ("bgr", bgr),
        ("r_minus_b", np.maximum(r.astype(np.int16) - b.astype(np.int16), 0).astype("uint8")),
        ("g_minus_b", np.maximum(g.astype(np.int16) - b.astype(np.int16), 0).astype("uint8")),
        ("b_minus_r", np.maximum(b.astype(np.int16) - r.astype(np.int16), 0).astype("uint8")),
        ("otsu", otsu),
        ("gray_threshold_180", (gray >= 180).astype("uint8") * 255),
    ]


def _gray_2x(bgr: np.ndarray):
    from PIL import Image

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    image = Image.fromarray(gray)
    return image.resize((image.width * 2, image.height * 2), Image.Resampling.LANCZOS)


def _save_variant(image: Any, path: Path) -> None:
    from PIL import Image

    if isinstance(image, Image.Image):
        image.save(path)
    else:
        Image.fromarray(image).save(path)


def _predict_path(rec: Any, path: Path) -> dict[str, Any]:
    started = time.perf_counter()
    result = rec.predict(str(path))
    elapsed = time.perf_counter() - started
    item = result[0] if result else {}
    return {
        "text": str(item.get("rec_text") or ""),
        "score": float(item.get("rec_score") or 0.0),
        "seconds": elapsed,
    }


def _annotate_prediction(raw: dict[str, Any], kind: str, lexicon: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_choice_text(raw["text"])
    lookup = lookup_lexicon(normalized, kind=kind, lexicon=lexicon)
    return {
        **raw,
        "normalized": normalized,
        "canonical": lookup.canonical,
        "lookup_margin": round(float(lookup.margin), 6),
        "lookup_top2": list(lookup.top2_names),
    }


def predict_current_6(
    rec: Any,
    bgr: np.ndarray,
    kind: str,
    temp_root: Path,
    index: int,
    lexicon: dict[str, Any],
) -> dict[str, Any]:
    best: dict[str, Any] | None = None
    best_raw: dict[str, Any] | None = None
    outputs: list[dict[str, Any]] = []
    total_seconds = 0.0
    for variant_name, image in _worker_variants(bgr):
        path = temp_root / f"current_{index}_{variant_name}.png"
        _save_variant(image, path)
        prediction = _annotate_prediction(_predict_path(rec, path), kind, lexicon)
        total_seconds += prediction["seconds"]
        outputs.append({
            "variant": variant_name,
            "text": prediction["text"],
            "score": round(prediction["score"], 6),
            "canonical": prediction["canonical"],
            "seconds": round(prediction["seconds"], 6),
        })
        if best_raw is None or prediction["score"] > best_raw["score"]:
            best_raw = prediction
        if prediction["canonical"] is not None and (
            best is None or prediction["score"] > best["score"]
        ):
            best = prediction
            if prediction["score"] >= 0.98:
                break
    chosen = best or best_raw or {
        "text": "",
        "score": 0.0,
        "normalized": "",
        "canonical": None,
        "lookup_margin": 0.0,
        "lookup_top2": [],
    }
    return {
        "text": chosen["text"],
        "normalized": chosen["normalized"],
        "canonical": chosen["canonical"],
        "score": round(float(chosen["score"]), 6),
        "seconds": total_seconds,
        "variant_count": len(outputs),
        "variants": outputs,
    }


def predict_gray_2x(
    rec: Any,
    bgr: np.ndarray,
    kind: str,
    temp_root: Path,
    index: int,
    lexicon: dict[str, Any],
) -> dict[str, Any]:
    path = temp_root / f"gray_2x_{index}.png"
    _save_variant(_gray_2x(bgr), path)
    prediction = _annotate_prediction(_predict_path(rec, path), kind, lexicon)
    return {
        "text": prediction["text"],
        "normalized": prediction["normalized"],
        "canonical": prediction["canonical"],
        "score": round(float(prediction["score"]), 6),
        "seconds": prediction["seconds"],
        "variant_count": 1,
        "variants": [{
            "variant": "gray_2x",
            "text": prediction["text"],
            "score": round(prediction["score"], 6),
            "canonical": prediction["canonical"],
            "seconds": round(prediction["seconds"], 6),
        }],
    }


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q / 100.0
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _panel_id(row: dict[str, Any]) -> str:
    sample_id = str(row.get("sample_id") or "")
    base = re.sub(r"_slot\d+$", "", sample_id)
    if base == sample_id:
        base = re.sub(r"_slot\d+[^/]*$", "", sample_id)
    return f"{row.get('capture_session', '?')}|{row.get('scene', '?')}|{base}"


def _truth(row: dict[str, Any], lexicon: dict[str, Any]) -> tuple[str | None, str]:
    label = str(row.get("label") or "")
    status = evo.truth_status(label or None, lexicon)
    return evo.truth_canonical_for(label or None, lexicon), status


def _metric_rows(rows: list[dict[str, Any]], variant: str) -> dict[str, Any]:
    eval_rows = [row for row in rows if row["truth_canonical"] is not None]
    recognized = [row for row in eval_rows if row[variant]["canonical"] is not None]
    correct = [
        row for row in recognized
        if row[variant]["canonical"] == row["truth_canonical"]
    ]
    unknown_truth = [row for row in rows if row["truth_status"] == "unknown"]
    unknown_misnormalized = [
        row for row in unknown_truth if row[variant]["canonical"] is not None
    ]

    def one(group: list[dict[str, Any]]) -> dict[str, Any]:
        group_eval = [row for row in group if row["truth_canonical"] is not None]
        group_recognized = [row for row in group_eval if row[variant]["canonical"] is not None]
        group_correct = [
            row for row in group_recognized
            if row[variant]["canonical"] == row["truth_canonical"]
        ]
        denominator = len(group_eval)
        return {
            "samples": len(group),
            "truth_known": denominator,
            "recognized": len(group_recognized),
            "top1": len(group_correct) / denominator if denominator else None,
            "precision": len(group_correct) / len(group_recognized) if group_recognized else None,
            "recall": len(group_correct) / denominator if denominator else None,
            "fp": len(group_recognized) - len(group_correct),
            "fn": denominator - len(group_correct),
            "unmatched": sum(1 for row in group_eval if row[variant]["canonical"] is None),
            "unknown_truth": sum(1 for row in group if row["truth_status"] == "unknown"),
        }

    by_scene = {
        scene: one([row for row in rows if row["scene"] == scene])
        for scene in sorted({row["scene"] for row in rows})
    }
    by_split = {
        split: one([row for row in rows if row["split"] == split])
        for split in ("TRAIN_TUNE", "BLIND_HOLDOUT")
        if any(row["split"] == split for row in rows)
    }
    by_session = {
        session: one([row for row in rows if row["capture_session"] == session])
        for session in sorted({row["capture_session"] for row in rows})
    }
    all_metrics = one(rows)
    all_metrics.update({
        "unknown_misnormalization": len(unknown_misnormalized),
        "unknown_misnormalization_samples": [row["sample_id"] for row in unknown_misnormalized],
    })
    return {
        "overall": all_metrics,
        "skill": by_scene.get("skill_choice", one([])),
        "by_scene": by_scene,
        "by_split": by_split,
        "by_capture_session": by_session,
        "errors": [
            {
                "sample_id": row["sample_id"],
                "scene": row["scene"],
                "split": row["split"],
                "truth": row["truth_canonical"],
                "text": row[variant]["text"],
                "canonical": row[variant]["canonical"],
                "score": row[variant]["score"],
                "unmatched": row[variant]["canonical"] is None,
            }
            for row in eval_rows
            if row[variant]["canonical"] != row["truth_canonical"]
        ],
    }


def _performance(rows: list[dict[str, Any]], variant: str) -> dict[str, Any]:
    single_ms = [float(row[variant]["seconds"]) * 1000.0 for row in rows]
    panel_seconds: dict[str, float] = defaultdict(float)
    panel_sizes: Counter[str] = Counter()
    for row in rows:
        panel = _panel_id(row)
        panel_seconds[panel] += float(row[variant]["seconds"])
        panel_sizes[panel] += 1
    panel_ms = [seconds * 1000.0 for panel, seconds in panel_seconds.items() if panel_sizes[panel] >= 2]
    return {
        "single_operation_count": len(single_ms),
        "single_p50_ms": _percentile(single_ms, 50),
        "single_p95_ms": _percentile(single_ms, 95),
        "panel_sequential_count": len(panel_ms),
        "panel_sequential_p50_ms": _percentile(panel_ms, 50),
        "panel_sequential_p95_ms": _percentile(panel_ms, 95),
        "panel_size_distribution": dict(sorted(Counter(panel_sizes.values()).items())),
        "definition": "panel latency is the sum of per-slot operations for each inferred capture group; no batch speedup is assumed",
    }


def _candidate_decision(metrics: dict[str, Any], performance: dict[str, Any]) -> dict[str, Any]:
    current = metrics["current_6_variant"]["overall"]
    gray = metrics["gray_2x"]["overall"]
    current_skill = metrics["current_6_variant"]["skill"]["recall"]
    gray_skill = metrics["gray_2x"]["skill"]["recall"]
    gray_better_accuracy = (
        gray["top1"] is not None and current["top1"] is not None and gray["top1"] > current["top1"]
    )
    gray_skill_not_worse = (
        gray_skill is not None and current_skill is not None and gray_skill >= current_skill
    )
    gray_latency_not_worse = (
        performance["gray_2x"]["single_p95_ms"] is not None
        and performance["current_6_variant"]["single_p95_ms"] is not None
        and performance["gray_2x"]["single_p95_ms"] <= performance["current_6_variant"]["single_p95_ms"]
    )
    production_candidate = gray_better_accuracy and gray_skill_not_worse and gray_latency_not_worse
    return {
        "status": "PRODUCTION_CANDIDATE" if production_candidate else "NO_CHANGE",
        "reason": {
            "gray_top1_strictly_better": gray_better_accuracy,
            "gray_skill_recall_not_worse": gray_skill_not_worse,
            "gray_single_p95_not_worse": gray_latency_not_worse,
        },
        "next_stage": "Stage 2B hardware shadow validation" if production_candidate else "retain current worker; collect more evidence",
        "wired_to_production": False,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = args.manifest if args.manifest.is_absolute() else REPO_ROOT / args.manifest
    meta, source_rows = load_jsonl_manifest(manifest_path)
    corpus_root = resolve_corpus_root(meta, source_rows, args.corpus_root)
    corpus_stats = validate_rows(meta, source_rows, corpus_root)
    if args.max_samples is not None:
        if args.max_samples < 1:
            raise ValueError("--max-samples must be positive")
        source_rows = source_rows[: args.max_samples]

    lexicon = load_lexicon()
    prepared: list[dict[str, Any]] = []
    for row in source_rows:
        truth_canonical, truth_status = _truth(row, lexicon)
        prepared.append({
            **row,
            "truth_canonical": truth_canonical,
            "truth_status": truth_status,
            "source_path": str(resolve_source(row, corpus_root)),
            "kind": SCENE_TO_KIND.get(str(row.get("scene")), str(row.get("scene"))),
        })

    evo.MODEL_SUBDIR = args.model_subdir
    evo.MODEL_NAME = args.model_name
    model_manifest_path = args.model_manifest if args.model_manifest.is_absolute() else REPO_ROOT / args.model_manifest
    model_manifest = evo.load_model_manifest(model_manifest_path)
    model_entry = evo.find_manifest_entry(model_manifest, args.model_subdir)
    models_dir = args.models_dir if args.models_dir.is_absolute() else REPO_ROOT / args.models_dir
    repo_model_dir = models_dir / args.model_subdir
    hash_gate = evo.verify_model_files(repo_model_dir, model_entry)
    report_base = {
        "schema_version": 1,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "repo_head": evo.repo_head_info(REPO_ROOT),
        "evaluator": {
            "script": "tools/benchmark_vision_ocr.py",
            "manifest": str(manifest_path),
            "manifest_sha256": _sha256(manifest_path),
            "manifest_meta": meta,
            "corpus_root": str(corpus_root),
            "corpus_stats": corpus_stats,
            "sample_count_used": len(prepared),
            "dataset_comparability": {
                "historical_o3_reference": "docs/baselines/O3_OFFLINE_GATE_20260811.md",
                "historical_o3_slots": 388,
                "historical_o3_sessions": 9,
                "current_dataset_slots": len(prepared),
                "status": "NOT_COMPARABLE" if len(prepared) != 388 else "requires independent schema review",
                "reason": "different corpus/schema; this benchmark does not replace historical O3",
            },
        },
        "model": {
            "name": args.model_name,
            "subdir": args.model_subdir,
            "manifest": str(model_manifest_path),
            "hash_gate": hash_gate,
        },
        "hardware": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "device": args.device,
            "cpu_threads": args.cpu_threads,
        },
    }
    if not hash_gate["passed"]:
        report_base.update({
            "status": "ABORTED_MODEL_HASH_GATE",
            "metrics": {},
            "performance": {},
            "candidate_decision": {"status": "BLOCKED", "wired_to_production": False},
        })
        return report_base

    stage_parent: tempfile.TemporaryDirectory[str] | None = None
    if args.staging_dir is None:
        stage_parent = tempfile.TemporaryDirectory(prefix="shuabao_ocr_benchmark_")
        staging_root = Path(stage_parent.name)
    else:
        staging_root = args.staging_dir if args.staging_dir.is_absolute() else REPO_ROOT / args.staging_dir
        staging_root.mkdir(parents=True, exist_ok=True)
    temp_root = staging_root / "benchmark_images"
    temp_root.mkdir(parents=True, exist_ok=True)
    staged_model: Path | None = None
    rec: Any | None = None
    try:
        staged_model = evo.stage_model(models_dir, staging_root)
        staged_hash_gate = evo.verify_model_files(staged_model, model_entry)
        if not staged_hash_gate["passed"]:
            report_base.update({
                "status": "ABORTED_STAGED_MODEL_HASH_GATE",
                "model": {**report_base["model"], "staged_hash_gate": staged_hash_gate},
                "metrics": {},
                "performance": {},
                "candidate_decision": {"status": "BLOCKED", "wired_to_production": False},
            })
            return report_base
        rec, load_seconds = evo.build_recognizer(staged_model, args.device, args.cpu_threads)
        # Warm up on a real corpus crop, outside the measured operations.
        first_image = _read_bgr(Path(prepared[0]["source_path"]))
        warmup_path = temp_root / "warmup.png"
        _save_variant(first_image, warmup_path)
        rec.predict(str(warmup_path))
        outputs: list[dict[str, Any]] = []
        for index, row in enumerate(prepared):
            bgr = _read_bgr(Path(row["source_path"]))
            current = predict_current_6(rec, bgr, row["kind"], temp_root, index, lexicon)
            gray = predict_gray_2x(rec, bgr, row["kind"], temp_root, index, lexicon)
            outputs.append({
                "sample_id": row["sample_id"],
                "scene": row["scene"],
                "kind": row["kind"],
                "capture_session": row["capture_session"],
                "split": row["split"],
                "label": row.get("label"),
                "truth_canonical": row["truth_canonical"],
                "truth_status": row["truth_status"],
                "source_crop": row["source_crop"],
                "current_6_variant": current,
                "gray_2x": gray,
            })
        metrics = {
            "current_6_variant": _metric_rows(outputs, "current_6_variant"),
            "gray_2x": _metric_rows(outputs, "gray_2x"),
        }
        performance = {
            "model_load_seconds": load_seconds,
            "current_6_variant": _performance(outputs, "current_6_variant"),
            "gray_2x": _performance(outputs, "gray_2x"),
        }
        report_base.update({
            "status": "COMPLETED",
            "model": {**report_base["model"], "staged_hash_gate": staged_hash_gate},
            "metrics": metrics,
            "performance": performance,
            "candidate_decision": _candidate_decision(metrics, performance),
            "negative_panel_false_positive": {
                "status": "not_available",
                "reason": "this corpus contains labeled positive title crops only; use the existing O3 negative-panel chain separately",
            },
            "samples": outputs,
        })
        return report_base
    finally:
        if rec is not None:
            rec.close()
        if stage_parent is not None:
            stage_parent.cleanup()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--corpus-root", type=Path)
    parser.add_argument("--models-dir", type=Path, default=DEFAULT_MODELS_DIR)
    parser.add_argument("--model-manifest", type=Path, default=DEFAULT_MODEL_MANIFEST)
    parser.add_argument("--model-subdir", default=DEFAULT_MODEL_SUBDIR)
    parser.add_argument("--model-name", default=DEFAULT_MODEL_NAME)
    parser.add_argument("--staging-dir", type=Path, default=None)
    parser.add_argument("--device", default="cpu", choices=["cpu", "gpu", "gpu:0"])
    parser.add_argument("--cpu-threads", type=int, default=4)
    parser.add_argument("--max-samples", type=int)
    parser.add_argument("--json-out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        report = run(args)
    except Exception as exc:  # noqa: BLE001
        report = {
            "schema_version": 1,
            "status": "ERROR",
            "error": f"{type(exc).__name__}: {exc}",
        }
    output = args.json_out if args.json_out.is_absolute() else REPO_ROOT / args.json_out
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[benchmark] json={output}")
    print(json.dumps({
        "status": report.get("status"),
        "candidate": (report.get("candidate_decision") or {}).get("status"),
        "current": ((report.get("metrics") or {}).get("current_6_variant") or {}).get("overall"),
        "gray_2x": ((report.get("metrics") or {}).get("gray_2x") or {}).get("overall"),
    }, ensure_ascii=False, sort_keys=True))
    return 0 if report.get("status") == "COMPLETED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
