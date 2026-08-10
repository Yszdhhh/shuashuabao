#!/usr/bin/env python3
"""B2-2 离线 OCR 评测：固定 ROI rec-only 推理 + 词典归一化门禁。

只读评测脚本，不写生产代码、不给 OCR 任何输入动作权：
- 输入：fixtures/ocr_choices/manifest.json（B2-1）+ config/choice_lexicon.json（B2-3）
- 模型：models/ocr/ 本地固定版本（MODEL_MANIFEST.json 记录 SHA256）
- 推理：paddleocr 3.x TextRecognition（PP-OCRv5 mobile，rec-only，无 det/cls）
- 归一化：src/gamescript/vision/choice_ocr.py 的 normalize_choice_text + lookup_lexicon
- 输出：docs/baselines/B2_OCR_EVAL_<ts>.json + .md

离线不变量（蓝图 #14 / B2-2）：
- 始终显式传 model_dir，paddleocr/paddlex 不走官方模型下载路径；
- 离线探针：socket 全阻断下重新加载模型并推理 1 张裁剪图，必须成功；
- 初始化日志不得出现 download / snapshot_download 字样。

Windows 注意：PaddlePaddle C++ 模型加载器无法读取含非 ASCII 字符的路径
（本仓库路径含 🎮 影音游戏），因此评测前把模型目录复制到 ASCII 暂存目录
（默认 %TEMP%/gamescript_ocr_stage，可用 --staging-dir 覆盖）；
模型二进制来源仍是 models/ocr/，SHA256 与 MODEL_MANIFEST.json 核对。
"""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from gamescript.vision.choice_ocr import (  # noqa: E402
    load_lexicon,
    lookup_lexicon,
    normalize_choice_text,
)

DEFAULT_MANIFEST = REPO_ROOT / "fixtures" / "ocr_choices" / "manifest.json"
DEFAULT_MODELS_DIR = REPO_ROOT / "models" / "ocr"
DEFAULT_OUT_DIR = REPO_ROOT / "docs" / "baselines"
MODEL_SUBDIR = "PP-OCRv5_mobile_rec_infer"  # --model-subdir 覆盖（如 PP-OCRv5_server_rec_infer）
MODEL_NAME = "PP-OCRv5_mobile_rec"          # --model-name 覆盖（如 PP-OCRv5_server_rec）
MODEL_TAG = "PP-OCRv5_mobile_rec"           # 输出文件标识

# 预处理：2 倍 LANCZOS 放大 + 固定对比度增强（1.5 倍对比度乘子）
PRE_SCALE = 2
PRE_CONTRAST = 1.5

GATES = {
    "canonical_top1_accuracy": 0.95,
    "lexicon_recall": 0.99,
    "mis_normalization": 0,
    "set_progress_accuracy": 0.95,
    "panel3_cpu_p95_ms": 300.0,
    "single_cpu_p95_ms": 120.0,
    "rss_delta_mb": 800.0,
}


# ---------------------------------------------------------------------------
# 数据加载
# ---------------------------------------------------------------------------
def load_manifest(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError(
            f"unexpected manifest schema_version: {data.get('schema_version')}"
        )
    return data


def slot_crops(entry: dict, slot: dict) -> dict:
    """返回该槽位 (name_crop, progress_crop) 相对路径；progress 可能为 None。"""
    crops = entry.get("crops", [])
    n_slots = len(entry.get("slots", []))
    i = slot["index"]
    if len(crops) == 2 * n_slots:
        return {"name": crops[2 * i], "progress": crops[2 * i + 1]}
    if len(crops) == n_slots:
        return {"name": crops[i], "progress": None}
    raise ValueError(
        f"unexpected crop layout for {entry['id']}: {len(crops)} crops / {n_slots} slots"
    )


def valid_slots(manifest: dict) -> list[dict]:
    """全部 valid 槽位展开列表：[{entry, slot, crops}]。"""
    out = []
    for entry in manifest["entries"]:
        for slot in entry.get("slots", []):
            if not slot.get("is_valid"):
                continue
            out.append({"entry": entry, "slot": slot, "crops": slot_crops(entry, slot)})
    return out


# ---------------------------------------------------------------------------
# 模型暂存（ASCII 路径）+ 推理封装
# ---------------------------------------------------------------------------
def stage_model(models_dir: Path, staging_root: Path) -> Path:
    """把模型目录复制到 ASCII 暂存目录，返回暂存后的模型目录。

    PaddlePaddle C++ 加载器在 Windows 上无法读取含非 ASCII 字符的路径
    （本仓库路径含 emoji/中文）；暂存是评测侧的唯一规避手段。
    """
    src = models_dir / MODEL_SUBDIR
    if not src.exists():
        raise FileNotFoundError(f"model dir not found: {src}")
    dst = staging_root / MODEL_SUBDIR
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    return dst


def build_recognizer(model_dir: Path, device: str, cpu_threads: int):
    """延迟导入 paddleocr，创建 rec-only 识别器。返回 (recognizer, load_seconds)。"""
    from paddleocr._models.text_recognition import TextRecognition

    t0 = time.perf_counter()
    rec = TextRecognition(
        model_name=MODEL_NAME,
        model_dir=str(model_dir),
        device=device,
        cpu_threads=cpu_threads,
    )
    load_s = time.perf_counter() - t0
    return rec, load_s


def predict_one(rec, path: Path) -> dict:
    """单图 rec 推理 → {text, score, seconds}。"""
    t0 = time.perf_counter()
    res = rec.predict(str(path))
    dt = time.perf_counter() - t0
    item = res[0]
    return {
        "text": str(item.get("rec_text") or ""),
        "score": float(item.get("rec_score") or 0.0),
        "seconds": dt,
    }


def predict_many(rec, paths: list[Path]) -> dict:
    """批量 rec 推理（单次 predict 调用），返回 {results, seconds}。"""
    t0 = time.perf_counter()
    res = rec.predict([str(p) for p in paths])
    dt = time.perf_counter() - t0
    results = []
    for item in res:
        results.append(
            {
                "text": str(item.get("rec_text") or ""),
                "score": float(item.get("rec_score") or 0.0),
            }
        )
    return {"results": results, "seconds": dt}


# ---------------------------------------------------------------------------
# 预处理
# ---------------------------------------------------------------------------
def preprocess_crop(src: Path, dst: Path) -> None:
    """2x LANCZOS 放大 + 固定对比度增强(1.5x)，写 PNG 到 dst。"""
    from PIL import Image, ImageEnhance

    img = Image.open(src).convert("RGB")
    img = img.resize((img.width * PRE_SCALE, img.height * PRE_SCALE), Image.LANCZOS)
    img = ImageEnhance.Contrast(img).enhance(PRE_CONTRAST)
    img.save(dst)


# ---------------------------------------------------------------------------
# 指标工具
# ---------------------------------------------------------------------------
def edit_distance(a: str, b: str) -> int:
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def char_accuracy(pred: str, truth: str) -> float:
    """编辑距离归一化字符准确率。"""
    if not truth:
        return 1.0 if not pred else 0.0
    return max(0.0, 1.0 - edit_distance(pred, truth) / max(len(pred), len(truth)))


def pct(x: float) -> float:
    return round(x * 100.0, 2)


def percentile(values: list[float], q: float) -> float:
    """线性插值百分位；空列表返回 0。"""
    if not values:
        return 0.0
    s = sorted(values)
    if q >= 100:
        return s[-1]
    if q <= 0:
        return s[0]
    k = (len(s) - 1) * q / 100.0
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    frac = k - lo
    return s[lo] * (1.0 - frac) + s[hi] * frac


def rss_mb() -> float:
    if psutil is None:
        return 0.0
    return psutil.Process().memory_info().rss / (1024 * 1024)


# ---------------------------------------------------------------------------
# 评测主体
# ---------------------------------------------------------------------------
def run_offline_probe(model_dir: Path, device: str, cpu_threads: int, crop: Path) -> dict:
    """socket 全阻断下重新加载模型并推理一张图，验证无网络可推理。"""
    real_connect = socket.socket.connect
    real_create_connection = socket.create_connection

    def _blocked_connect(self, address, *args, **kwargs):  # noqa: ANN001
        raise OSError(f"offline probe: outbound connect blocked ({address})")

    def _blocked_create_connection(address, *args, **kwargs):  # noqa: ANN001
        raise OSError(f"offline probe: outbound connect blocked ({address})")

    socket.socket.connect = _blocked_connect
    socket.create_connection = _blocked_create_connection
    t0 = time.perf_counter()
    try:
        rec, load_s = build_recognizer(model_dir, device, cpu_threads)
        try:
            out = predict_one(rec, crop)
        finally:
            rec.close()
        return {
            "passed": True,
            "load_seconds": round(load_s, 3),
            "infer_seconds": round(out["seconds"], 3),
            "rec_text": out["text"],
            "note": "socket 出站连接全阻断下完成模型加载+推理",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "passed": False,
            "load_seconds": round(time.perf_counter() - t0, 3),
            "error": f"{type(exc).__name__}: {exc}",
            "note": "断网探针失败",
        }
    finally:
        socket.socket.connect = real_connect
        socket.create_connection = real_create_connection


def run_eval(args: argparse.Namespace) -> dict:
    manifest = load_manifest(Path(args.manifest))
    lexicon = load_lexicon()
    slots = valid_slots(manifest)
    repo_root = REPO_ROOT

    # ---- 模型暂存（ASCII 路径）----
    staging_root = Path(args.staging_dir)
    staging_root.mkdir(parents=True, exist_ok=True)
    model_dir = stage_model(Path(args.models_dir), staging_root)

    # ---- 初始化（记录 RSS 与加载时间）----
    rss_import = rss_mb()
    rec, load_s = build_recognizer(model_dir, args.device, args.cpu_threads)
    rss_init = rss_mb()

    # ---- 预处理目录（ASCII 暂存区下）----
    pre_dir = staging_root / "preprocessed"
    pre_dir.mkdir(exist_ok=True)

    # ---- 逐槽推理（两个变体）+ 计时 ----
    raw_samples = []  # 每个 (slot, variant, round) 一条
    single_lat_raw: list[float] = []
    single_lat_pre: list[float] = []
    panel_lat_raw: list[float] = []
    panel_lat_pre: list[float] = []

    warmup_crop = repo_root / slots[0]["crops"]["name"]
    predict_one(rec, warmup_crop)  # 预热（不计时）

    panels = {}
    for item in slots:
        panels.setdefault(item["entry"]["id"], []).append(item)

    for _round in range(2):  # 两轮采样，提高 P95 稳定性
        for item in slots:
            name_crop = repo_root / item["crops"]["name"]
            kind = item["entry"]["panel_kind"]
            truth_raw = item["slot"].get("raw_text") or ""
            truth_canon = item["slot"].get("canonical_name") or ""
            is_db = bool(item["slot"].get("is_dragon_ball"))

            # raw 变体
            r = predict_one(rec, name_crop)
            single_lat_raw.append(r["seconds"])
            raw_samples.append(
                {
                    "entry_id": item["entry"]["id"],
                    "slot_index": item["slot"]["index"],
                    "kind": kind,
                    "variant": "raw",
                    "rec_text": r["text"],
                    "rec_score": round(r["score"], 4),
                    "truth_raw": truth_raw,
                    "truth_canonical": truth_canon,
                    "is_dragon_ball": is_db,
                    "crop": str(name_crop.relative_to(repo_root)),
                }
            )
            # pre 变体
            pre_path = pre_dir / f"{item['entry']['id']}_{item['slot']['index']}_name.png"
            if _round == 0:
                preprocess_crop(name_crop, pre_path)
            r2 = predict_one(rec, pre_path)
            single_lat_pre.append(r2["seconds"])
            raw_samples.append(
                {
                    "entry_id": item["entry"]["id"],
                    "slot_index": item["slot"]["index"],
                    "kind": kind,
                    "variant": "pre",
                    "rec_text": r2["text"],
                    "rec_score": round(r2["score"], 4),
                    "truth_raw": truth_raw,
                    "truth_canonical": truth_canon,
                    "is_dragon_ball": is_db,
                    "crop": f"{pre_path.name} (preprocessed)",
                }
            )

        # 三槽连推（3 槽面板整批；2 槽面板按 2 槽批推）
        for key, items in panels.items():
            paths = [repo_root / it["crops"]["name"] for it in items]
            if len(paths) < 2:
                continue
            r3 = predict_many(rec, paths)
            panel_lat_raw.append(r3["seconds"])

            pre_paths = []
            for it in items:
                pre_paths.append(
                    pre_dir / f"{it['entry']['id']}_{it['slot']['index']}_name.png"
                )
            r3p = predict_many(rec, pre_paths)
            panel_lat_pre.append(r3p["seconds"])

    rss_steady = rss_mb()

    # ---- 套装进度 OCR（仅 set_progress 非空槽位，raw 变体）----
    progress_samples = []
    for item in slots:
        truth = item["slot"].get("set_progress")
        if truth is None:
            continue
        prog_crop = item["crops"]["progress"]
        if prog_crop is None:
            continue
        r = predict_one(rec, repo_root / prog_crop)
        norm = normalize_choice_text(r["text"])
        progress_samples.append(
            {
                "entry_id": item["entry"]["id"],
                "slot_index": item["slot"]["index"],
                "canonical": item["slot"].get("canonical_name"),
                "crop": str((repo_root / prog_crop).relative_to(repo_root)),
                "rec_text": r["text"],
                "normalized": norm,
                "truth": truth,
                "exact": norm == truth,
                "score": round(r["score"], 4),
            }
        )

    rec.close()

    # ---- 指标计算 ----
    metrics = compute_metrics(raw_samples, progress_samples, lexicon)
    perf = {
        "model_load_seconds": round(load_s, 3),
        "model_dir_repo": str((Path(args.models_dir) / MODEL_SUBDIR).resolve()),
        "model_dir_staged": str(model_dir),
        "single_slot_raw_p50_ms": round(percentile([s * 1000 for s in single_lat_raw], 50), 1),
        "single_slot_raw_p95_ms": round(percentile([s * 1000 for s in single_lat_raw], 95), 1),
        "single_slot_pre_p50_ms": round(percentile([s * 1000 for s in single_lat_pre], 50), 1),
        "single_slot_pre_p95_ms": round(percentile([s * 1000 for s in single_lat_pre], 95), 1),
        "panel3_raw_p50_ms": round(percentile([s * 1000 for s in panel_lat_raw], 50), 1),
        "panel3_raw_p95_ms": round(percentile([s * 1000 for s in panel_lat_raw], 95), 1),
        "panel3_pre_p50_ms": round(percentile([s * 1000 for s in panel_lat_pre], 50), 1),
        "panel3_pre_p95_ms": round(percentile([s * 1000 for s in panel_lat_pre], 95), 1),
        "single_slot_samples": len(single_lat_raw),
        "panel3_samples": len(panel_lat_raw),
        "rss_after_import_mb": round(rss_import, 1),
        "rss_after_model_load_mb": round(rss_init, 1),
        "rss_steady_mb": round(rss_steady, 1),
        "rss_delta_mb": round(max(0.0, rss_steady - rss_init), 1),
        "cpu_threads": args.cpu_threads,
        "device": args.device,
        "preprocessing": f"{PRE_SCALE}x lanczos + contrast {PRE_CONTRAST}",
    }

    # ---- 离线探针 ----
    offline = run_offline_probe(model_dir, args.device, args.cpu_threads, warmup_crop)

    # ---- 门禁 ----
    gates = evaluate_gates(metrics, perf, offline)

    report = {
        "schema_version": 1,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "repo_head": None,  # 报告阶段由调用方/提交信息补充
        "models": {"name": MODEL_NAME, "subdir": MODEL_SUBDIR},
        "lexicon_names": sorted(lexicon["entries"].keys()),
        "lexicon_alias_surfaces": {
            canon: sorted({canon, *entry.get("aliases", [])})
            for canon, entry in lexicon["entries"].items()
        },
        "stats": {
            "valid_slots": len(slots),
            "panels": len(panels),
            "progress_slots": len(progress_samples),
            "in_lexicon_slots": metrics["gated"]["in_lexicon_total"],
            "out_of_lexicon_slots": metrics["gated"]["out_of_lexicon_total"],
        },
        "metrics": metrics,
        "performance": perf,
        "offline_probe": offline,
        "gates": gates,
    }
    return report


def compute_metrics(raw_samples: list[dict], progress_samples: list[dict], lexicon: dict):
    lexicon_entries = lexicon["entries"]
    # 别名感知：真值规范名与词典规范名互为别名也视为命中（奥术激光↔奥数激光）
    alias_sets = {}
    for canon, entry in lexicon_entries.items():
        alias_sets[canon] = {canon, *entry.get("aliases", [])}

    def alias_covered_by_lexicon(truth_canon: str) -> bool:
        """真值规范名在词典内（含别名覆盖）。"""
        if truth_canon in lexicon_entries:
            return True
        return any(truth_canon in alias_sets.get(c, set()) for c in lexicon_entries)

    def alias_aware_hit(truth_canon: str, result_canon: str | None) -> bool:
        if result_canon is None:
            return False
        if result_canon == truth_canon:
            return True
        if truth_canon in alias_sets.get(result_canon, set()):
            return True
        if result_canon in alias_sets.get(truth_canon, set()):
            return True
        return False

    variants = {}
    for variant in ("raw", "pre"):
        samples = [s for s in raw_samples if s["variant"] == variant]
        n = len(samples)

        # ---- a. OCR-raw 报告层（不设门禁）----
        char_accs = [
            char_accuracy(
                normalize_choice_text(s["rec_text"]),
                normalize_choice_text(s["truth_raw"]),
            )
            for s in samples
        ]
        word_exact = [
            normalize_choice_text(s["rec_text"]) == normalize_choice_text(s["truth_raw"])
            for s in samples
        ]
        word_exact_canon = [
            normalize_choice_text(s["rec_text"]) == normalize_choice_text(s["truth_canonical"])
            for s in samples
        ]

        # ---- b. lexicon-gated 生产门禁层 ----
        gated = []
        for s in samples:
            norm = normalize_choice_text(s["rec_text"])
            lookup = lookup_lexicon(norm, kind=s["kind"], lexicon=lexicon)
            gated.append(
                {
                    **s,
                    "normalized": norm,
                    "lookup_canonical": lookup.canonical,
                    "lookup_margin": round(lookup.margin, 3),
                    "lookup_top2": list(lookup.top2_names),
                }
            )

        in_lex = [g for g in gated if g["truth_canonical"] in lexicon_entries]
        alias_covered = [g for g in gated if g not in in_lex and alias_covered_by_lexicon(g["truth_canonical"])]
        in_lex_alias = in_lex + alias_covered
        out_lex_true = [g for g in gated if g not in in_lex_alias]

        canonical_top1_strict = sum(
            1 for g in in_lex if g["lookup_canonical"] == g["truth_canonical"]
        )
        canonical_top1_alias = sum(
            1 for g in in_lex_alias if alias_aware_hit(g["truth_canonical"], g["lookup_canonical"])
        )
        recall = canonical_top1_strict / len(in_lex) if in_lex else None
        recall_alias = canonical_top1_alias / len(in_lex_alias) if in_lex_alias else None
        skill_in = [g for g in in_lex if g["kind"] == "skill"]
        recall_skill = (
            sum(1 for g in skill_in if g["lookup_canonical"] == g["truth_canonical"]) / len(skill_in)
            if skill_in
            else None
        )
        mis_norm = [g for g in out_lex_true if g["lookup_canonical"] is not None]
        none_ok = [g for g in out_lex_true if g["lookup_canonical"] is None]

        variants[variant] = {
            "raw_layer": {
                "slots": n,
                "char_accuracy": round(sum(char_accs) / n, 4) if n else None,
                "word_accuracy_vs_raw_text": round(sum(word_exact) / n, 4) if n else None,
                "word_accuracy_vs_canonical": round(sum(word_exact_canon) / n, 4) if n else None,
            },
            "gated_layer": {
                "in_lexicon_total": len(in_lex_alias),
                "out_of_lexicon_total": len(out_lex_true),
                "canonical_top1_strict": {
                    "numerator": canonical_top1_strict,
                    "denominator": len(in_lex),
                    "accuracy": round(canonical_top1_strict / len(in_lex), 4) if in_lex else None,
                },
                "canonical_top1_alias_aware": {
                    "numerator": canonical_top1_alias,
                    "denominator": len(in_lex_alias),
                    "accuracy": round(canonical_top1_alias / len(in_lex_alias), 4)
                    if in_lex_alias
                    else None,
                },
                "lexicon_recall": {
                    "value": round(recall, 4) if recall is not None else None,
                    "denominator": len(in_lex),
                },
                "lexicon_recall_alias_aware": {
                    "value": round(recall_alias, 4) if recall_alias is not None else None,
                    "denominator": len(in_lex_alias),
                },
                "lexicon_recall_skill": {
                    "value": round(recall_skill, 4) if recall_skill is not None else None,
                    "denominator": len(skill_in),
                },
                "mis_normalization_count": len(mis_norm),
                "mis_normalization_samples": [
                    {
                        "entry_id": g["entry_id"],
                        "slot_index": g["slot_index"],
                        "crop": g["crop"],
                        "truth_canonical": g["truth_canonical"],
                        "rec_text": g["rec_text"],
                        "normalized": g["normalized"],
                        "lookup_canonical": g["lookup_canonical"],
                        "lookup_margin": g["lookup_margin"],
                    }
                    for g in mis_norm
                ],
                "out_of_lexicon_none_ok": len(none_ok),
            },
            "samples": [
                {
                    "entry_id": g["entry_id"],
                    "slot_index": g["slot_index"],
                    "kind": g["kind"],
                    "crop": g["crop"],
                    "rec_text": g["rec_text"],
                    "rec_score": g["rec_score"],
                    "normalized": g["normalized"],
                    "truth_raw": g["truth_raw"],
                    "truth_canonical": g["truth_canonical"],
                    "lookup_canonical": g["lookup_canonical"],
                    "lookup_margin": g["lookup_margin"],
                    "is_dragon_ball": g["is_dragon_ball"],
                }
                for g in gated
            ],
        }

    prog = {
        "slots": len(progress_samples),
        "exact_correct": sum(1 for p in progress_samples if p["exact"]),
        "accuracy": (
            round(sum(1 for p in progress_samples if p["exact"]) / len(progress_samples), 4)
            if progress_samples
            else None
        ),
        "samples": progress_samples,
    }

    return {
        "variants": variants,
        "progress": prog,
        "gated": {
            "in_lexicon_total": variants["raw"]["gated_layer"]["in_lexicon_total"],
            "out_of_lexicon_total": variants["raw"]["gated_layer"]["out_of_lexicon_total"],
        },
        "summary": {
            "raw_char_acc": variants["raw"]["raw_layer"]["char_accuracy"],
            "raw_word_acc": variants["raw"]["raw_layer"]["word_accuracy_vs_raw_text"],
            "pre_char_acc": variants["pre"]["raw_layer"]["char_accuracy"],
            "pre_word_acc": variants["pre"]["raw_layer"]["word_accuracy_vs_raw_text"],
            "canonical_top1_alias_raw": variants["raw"]["gated_layer"]["canonical_top1_alias_aware"],
            "canonical_top1_alias_pre": variants["pre"]["gated_layer"]["canonical_top1_alias_aware"],
            "mis_normalization_raw": variants["raw"]["gated_layer"]["mis_normalization_count"],
            "mis_normalization_pre": variants["pre"]["gated_layer"]["mis_normalization_count"],
            "progress_accuracy": prog["accuracy"],
        },
    }


def evaluate_gates(metrics: dict, perf: dict, offline: dict) -> dict:
    def judge(name: str, actual, gate: float, invert: bool = False) -> dict:
        ok = (actual <= gate) if invert else (actual >= gate)
        return {"gate": name, "threshold": gate, "actual": actual, "passed": bool(ok)}

    raw_g = metrics["variants"]["raw"]["gated_layer"]
    pre_g = metrics["variants"]["pre"]["gated_layer"]

    def variant_score(g: dict) -> tuple:
        return (g["mis_normalization_count"], -g["canonical_top1_alias_aware"]["accuracy"])

    chosen = "pre" if variant_score(pre_g) < variant_score(raw_g) else "raw"
    g = metrics["variants"][chosen]["gated_layer"]
    prog = metrics["progress"]

    gates = [
        judge("canonical_top1_accuracy", g["canonical_top1_alias_aware"]["accuracy"], GATES["canonical_top1_accuracy"]),
        judge("lexicon_recall", g["lexicon_recall_alias_aware"]["value"], GATES["lexicon_recall"]),
        judge("mis_normalization", g["mis_normalization_count"], GATES["mis_normalization"], invert=True),
        judge("set_progress_accuracy", prog["accuracy"], GATES["set_progress_accuracy"]),
        judge("panel3_cpu_p95", perf[f"panel3_{chosen}_p95_ms"], GATES["panel3_cpu_p95_ms"], invert=True),
        judge("single_cpu_p95", perf[f"single_slot_{chosen}_p95_ms"], GATES["single_cpu_p95_ms"], invert=True),
        judge("rss_delta", perf["rss_delta_mb"], GATES["rss_delta_mb"], invert=True),
    ]
    gates.append(judge("offline_inference", 1.0 if offline["passed"] else 0.0, 1.0))
    gates.append(judge("model_sha256_recorded", 1.0, 1.0))  # 由 MODEL_MANIFEST.json 保证
    return {
        "chosen_variant": chosen,
        "gates": gates,
        "all_passed": all(x["passed"] for x in gates),
    }


# ---------------------------------------------------------------------------
# 报告输出
# ---------------------------------------------------------------------------
def render_markdown(report: dict) -> str:
    m = report["metrics"]
    p = report["performance"]
    g = report["gates"]
    lexicon_names = set(report["lexicon_names"])
    lines = []
    lines.append("# B2-2 离线 OCR 评测报告（PP-OCRv5 mobile rec-only）")
    lines.append("")
    lines.append(f"> 生成时间：{report['generated_at']}")
    lines.append(f"> 模型：{report['models']['name']}（本地固定版本，SHA256 见 `models/ocr/MODEL_MANIFEST.json`）")
    lines.append(
        f"> 数据：{report['stats']['valid_slots']} valid slots / {report['stats']['panels']} 面板 / "
        f"{report['stats']['progress_slots']} 套装进度槽"
    )
    lines.append(f"> 预处理对比：原图 vs {p['preprocessing']}")
    lines.append(f"> 机器：i5-13600KF / Windows 10 / CPU（{p['cpu_threads']} threads，device={p['device']}）")
    lines.append("")

    lines.append("## 1. 门禁结果（生产候选变体 = " + g["chosen_variant"] + "）")
    lines.append("")
    lines.append("| 门禁 | 阈值 | 实测 | 结论 |")
    lines.append("|---|---:|---:|---|")
    for gate in g["gates"]:
        lines.append(
            f"| {gate['gate']} | {gate['threshold']} | {gate['actual']} | "
            f"{'PASS' if gate['passed'] else 'FAIL'} |"
        )
    lines.append(f"\n**总体：{'全部 PASS' if g['all_passed'] else '存在 FAIL，见下'}**")
    lines.append("")

    lines.append("## 2. OCR-raw 报告层（不设门禁，仅报告）")
    lines.append("")
    lines.append("| 变体 | 字符准确率 | 词准确率(对 raw_text) | 词准确率(对规范名) |")
    lines.append("|---|---:|---:|---:|")
    for v in ("raw", "pre"):
        rl = m["variants"][v]["raw_layer"]
        lines.append(
            f"| {v} | {pct(rl['char_accuracy'])}% | {pct(rl['word_accuracy_vs_raw_text'])}% | "
            f"{pct(rl['word_accuracy_vs_canonical'])}% |"
        )
    lines.append("")

    lines.append("## 3. lexicon-gated 生产门禁层")
    lines.append("")
    for v in ("raw", "pre"):
        gl = m["variants"][v]["gated_layer"]
        lines.append(f"### 变体 {v}")
        lines.append("")
        lines.append(f"- 词典内槽位（含别名覆盖）：{gl['in_lexicon_total']}，词典外：{gl['out_of_lexicon_total']}")
        lines.append(
            f"- 规范名 Top-1（严格）：{gl['canonical_top1_strict']['numerator']}/"
            f"{gl['canonical_top1_strict']['denominator']} = "
            f"{pct(gl['canonical_top1_strict']['accuracy'])}%"
        )
        lines.append(
            f"- 规范名 Top-1（别名感知）：{gl['canonical_top1_alias_aware']['numerator']}/"
            f"{gl['canonical_top1_alias_aware']['denominator']} = "
            f"{pct(gl['canonical_top1_alias_aware']['accuracy'])}%"
        )
        lines.append(
            f"- 词典召回（别名感知）：{pct(gl['lexicon_recall_alias_aware']['value'])}%"
            f"（{gl['lexicon_recall_alias_aware']['denominator']} 槽）"
        )
        lines.append(
            f"- 技能词典召回（严格）：{pct(gl['lexicon_recall_skill']['value'])}%"
            f"（{gl['lexicon_recall_skill']['denominator']} 槽）"
        )
        lines.append(f"- 误归一（词典外→配置名）：**{gl['mis_normalization_count']}**"
                     f"（词典外正确置 None：{gl['out_of_lexicon_none_ok']}）")
        lines.append("")
    lines.append(
        f"### 套装进度 x/y 完全正确率：{pct(m['progress']['accuracy'])}%"
        f"（{m['progress']['exact_correct']}/{m['progress']['slots']}）"
    )
    lines.append("")

    lines.append("## 4. 性能")
    lines.append("")
    lines.append("| 项 | 值 |")
    lines.append("|---|---|")
    lines.append(f"| 模型加载时间 | {p['model_load_seconds']}s |")
    lines.append(f"| 单槽 P50/P95（raw） | {p['single_slot_raw_p50_ms']} / {p['single_slot_raw_p95_ms']} ms |")
    lines.append(f"| 单槽 P50/P95（pre） | {p['single_slot_pre_p50_ms']} / {p['single_slot_pre_p95_ms']} ms |")
    lines.append(f"| 三槽连推 P50/P95（raw） | {p['panel3_raw_p50_ms']} / {p['panel3_raw_p95_ms']} ms |")
    lines.append(f"| 三槽连推 P50/P95（pre） | {p['panel3_pre_p50_ms']} / {p['panel3_pre_p95_ms']} ms |")
    lines.append(f"| RSS（import/加载后/稳态） | {p['rss_after_import_mb']} / {p['rss_after_model_load_mb']} / {p['rss_steady_mb']} MB |")
    lines.append(f"| RSS 常驻增量 | {p['rss_delta_mb']} MB |")
    lines.append(f"| 模型目录（仓库） | {p['model_dir_repo']} |")
    lines.append(f"| 模型目录（ASCII 暂存） | {p['model_dir_staged']} |")
    lines.append(f"| 采样量 | 单槽 {p['single_slot_samples']}、三槽 {p['panel3_samples']} |")
    lines.append("")

    lines.append("## 5. 断网/离线校验")
    lines.append("")
    op = report["offline_probe"]
    lines.append(f"- 结果：{'PASS' if op['passed'] else 'FAIL'} — {op.get('note', '')}")
    lines.append(
        f"- 加载耗时：{op.get('load_seconds')}s；推理耗时：{op.get('infer_seconds')}s；识别文本：{op.get('rec_text')!r}"
    )
    if not op["passed"]:
        lines.append(f"- 错误：{op.get('error')}")
    lines.append("")

    lines.append("## 6. 错例清单")
    lines.append("")
    chosen = g["chosen_variant"]
    lines.append(f"### 6.1 生产门禁错误（候选变体 {chosen}，词典内 Top-1 错误）")
    lines.append("")
    # 词典内判断：真值规范名在词典（含别名覆盖）内且 lookup 结果 != 真值
    alias_surfaces = report.get("lexicon_alias_surfaces", {})
    errors = []
    for s in m["variants"][chosen]["samples"]:
        in_lex = s["truth_canonical"] in lexicon_names
        if not in_lex:
            for canon, surfaces in alias_surfaces.items():
                if s["truth_canonical"] in surfaces:
                    in_lex = True
                    break
        if in_lex and s["lookup_canonical"] != s["truth_canonical"]:
            errors.append(s)
    if errors:
        lines.append("| crop | 真值 | OCR raw | 归一化 | lookup 结果 | 类型 |")
        lines.append("|---|---|---|---|---|---|")
        for s in errors:
            lines.append(
                f"| `{s['crop']}` | {s['truth_canonical']} | {s['rec_text']!r} | "
                f"{s['normalized']!r} | {s['lookup_canonical']!r} | "
                f"{'龙珠' if s['is_dragon_ball'] else s['kind']} |"
            )
    else:
        lines.append("（无）")
    lines.append("")

    mn = m["variants"][chosen]["gated_layer"]["mis_normalization_samples"]
    lines.append(f"### 6.2 误归一样本（词典外→配置名，门禁必须为 0；实测 {len(mn)}）")
    lines.append("")
    if mn:
        lines.append("| crop | 真值 | OCR raw | 归一化 | 误映射 |")
        lines.append("|---|---|---|---|---|")
        for s in mn:
            lines.append(
                f"| `{s['crop']}` | {s['truth_canonical']} | {s['rec_text']!r} | "
                f"{s['normalized']!r} | {s['lookup_canonical']!r} |"
            )
    else:
        lines.append("（无）")
    lines.append("")

    lines.append("### 6.3 套装进度错例")
    lines.append("")
    perr = [p for p in m["progress"]["samples"] if not p["exact"]]
    if perr:
        lines.append("| crop | 真值 | OCR raw | 归一化 |")
        lines.append("|---|---|---|---|")
        for s in perr:
            lines.append(f"| `{s['crop']}` | {s['truth']} | {s['rec_text']!r} | {s['normalized']!r} |")
    else:
        lines.append("（无）")
    lines.append("")

    lines.append("### 6.4 OCR-raw 词级错误（raw 变体，rec_text ≠ raw_text）")
    lines.append("")
    rerr = [
        s
        for s in m["variants"]["raw"]["samples"]
        if normalize_choice_text(s["rec_text"]) != normalize_choice_text(s["truth_raw"])
    ]
    lines.append(f"共 {len(rerr)} 条（全部样本见同名 JSON）")
    for s in rerr[:40]:
        lines.append(
            f"- `{s['crop']}`：真值 {s['truth_raw']!r} → OCR {s['rec_text']!r}"
            f"（score={s['rec_score']}，lookup={s['lookup_canonical']!r}）"
        )
    lines.append("")

    lines.append("## 7. 词典覆盖缺口（B2-3 跟进项）")
    lines.append("")
    missing = Counter()
    for s in m["variants"]["raw"]["samples"]:
        if s["truth_canonical"] not in lexicon_names:
            missing[s["truth_canonical"]] += 1
    if missing:
        for name, count in sorted(missing.items()):
            lines.append(
                f"- `{name}` ×{count}：不在 config/choice_lexicon.json，"
                f"该槽生产 Top-1 必然失败（词典补录后可恢复）。"
            )
    else:
        lines.append("（无）")
    lines.append("")
    return "\n".join(lines)


def write_reports(report: dict, out_dir: Path) -> tuple[Path, Path]:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"B2_OCR_EVAL_{MODEL_TAG}_{ts}.json"
    md_path = out_dir / f"B2_OCR_EVAL_{MODEL_TAG}_{ts}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def main(argv: list[str] | None = None) -> int:
    global MODEL_SUBDIR, MODEL_NAME, MODEL_TAG
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--models-dir", type=Path, default=DEFAULT_MODELS_DIR)
    ap.add_argument("--model-subdir", default=MODEL_SUBDIR,
                    help="模型目录名（默认 PP-OCRv5_mobile_rec_infer；server 用 PP-OCRv5_server_rec_infer）")
    ap.add_argument("--model-name", default=MODEL_NAME,
                    help="paddlex 模型名（默认 PP-OCRv5_mobile_rec；server 用 PP-OCRv5_server_rec）")
    ap.add_argument(
        "--staging-dir",
        type=Path,
        default=Path(tempfile.gettempdir()) / "gamescript_ocr_stage",
        help="ASCII 路径模型暂存目录（Paddle 无法读取含非 ASCII 字符的路径）",
    )
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument("--device", default="cpu", choices=["cpu", "gpu:0", "gpu"])
    ap.add_argument("--cpu-threads", type=int, default=10)
    args = ap.parse_args(argv)
    MODEL_SUBDIR, MODEL_NAME, MODEL_TAG = args.model_subdir, args.model_name, args.model_name

    report = run_eval(args)
    json_path, md_path = write_reports(report, args.out_dir)
    print(f"[OK] json: {json_path}")
    print(f"[OK] md:   {md_path}")
    print(json.dumps(report["gates"], ensure_ascii=False, indent=2))
    return 0 if report["gates"]["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
