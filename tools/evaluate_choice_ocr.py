#!/usr/bin/env python3
"""O0/O1 离线 OCR 评测：固定 ROI rec-only 推理 + 词典归一化门禁 + 评测可信度门禁。

只读评测脚本，不写生产代码、不给 OCR 任何输入动作权：
- 输入：fixtures/ocr_choices/manifest.json（B2-1/O1 裁剪）+ config/choice_lexicon.json（B2-3）
- 模型：models/ocr/ 本地固定版本（MODEL_MANIFEST.json 记录 SHA256/大小/license/source_url）
- 推理：paddleocr 3.x TextRecognition（PP-OCRv5 mobile，rec-only，无 det/cls）
- 归一化：src/shuabao/vision/choice_ocr.py 的 normalize_choice_text + lookup_lexicon
- 输出：docs/baselines/B2_OCR_EVAL_<ts>.json + .md

O0 评测可信度修复（对比旧版 B2-2 evaluator）：
1. MODEL_MANIFEST.json 为合法 JSON（schema_version 2），字段含 name/sha256/size_bytes/
   license/source_url/model_dir；
2. evaluator 真实计算模型文件 SHA256 与字节大小并逐文件核对 manifest，篡改任一模型
   字节 → hash gate FAIL（不硬编码 PASS）；
3. 报告记录 repo HEAD（git rev-parse HEAD 写入输出）；
4. 准确率分母 = 独立有效槽位（(entry_id, slot_index) 唯一计一次；重复轮次只统计
   latency/稳定性）；
5. 按采集 session 留出，输出逐 session 指标；
6. 词典外 truth 单独计 unknown（truth_status=unknown），不得被错误规范化进准确率；
7. 真实负面板运行完整 触发/分类/建议 链（复刻 mediator._selection_anchor +
   _classify_choice_panel 阈值，代码只读引用），期望建议数 = 0，逐面板输出；
8. 固定可重建 OCR 依赖锁：requirements-ocr.txt + requirements-ocr.lock（paddlepaddle
   3.3.1 / paddleocr 3.7.0 / paddlex 3.7.2，下载源 PyPI）。

O1 ROI 修复配合：manifest 每槽记录显式 bbox（slot["roi"]）与 layout_status
（verified/unverified_layout）；unverified_layout 槽不进准确率分母；name 与 progress
分别紧裁（由 tools/crop_ocr_choices.py 按 per-slot roi 生成）。

离线不变量（蓝图 #14 / B2-2）：
- 始终显式传 model_dir，paddleocr/paddlex 不走官方模型下载路径；
- 离线探针：socket 全阻断下重新加载模型并推理 1 张裁剪图，必须成功；
- 初始化日志不得出现 download / snapshot_download 字样。

Windows 注意：PaddlePaddle C++ 模型加载器无法读取含非 ASCII 字符的路径
（本仓库路径含 🎮 影音游戏），因此评测前把模型目录复制到 ASCII 暂存目录
（默认 %TEMP%/shuabao_ocr_stage，可用 --staging-dir 覆盖）；
模型二进制来源仍是 models/ocr/，SHA256 与 MODEL_MANIFEST.json 核对。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shuabao.vision.choice_ocr import (  # noqa: E402
    load_lexicon,
    lookup_lexicon,
    normalize_choice_text,
    truth_canonical_for as _truth_canonical_for,
    truth_status_of as _truth_status_of,
)
from shuabao.vision.capture import Frame  # noqa: E402
from shuabao.vision.matcher import match_any  # noqa: E402

DEFAULT_MANIFEST = REPO_ROOT / "fixtures" / "ocr_choices" / "manifest.json"
DEFAULT_MODELS_DIR = REPO_ROOT / "models" / "ocr"
DEFAULT_MODEL_MANIFEST = DEFAULT_MODELS_DIR / "MODEL_MANIFEST.json"
DEFAULT_OUT_DIR = REPO_ROOT / "docs" / "baselines"
MODEL_SUBDIR = "PP-OCRv5_mobile_rec_infer"  # --model-subdir 覆盖（如 PP-OCRv5_server_rec_infer）
MODEL_NAME = "PP-OCRv5_mobile_rec"          # --model-name 覆盖（如 PP-OCRv5_server_rec）
MODEL_TAG = "PP-OCRv5_mobile_rec"           # 输出文件标识

# 预处理：2 倍 LANCZOS 放大 + 固定对比度增强（1.5 倍对比度乘子）
PRE_SCALE = 2
PRE_CONTRAST = 1.5

# 负面板 触发/分类 链：与 mediator.py 只读复刻（§_selection_anchor/_classify_choice_panel）
ANCHOR_TEMPLATES = [
    "skill_giveup_btn",
    "skill_refresh_btn",
    "bond_hide_btn",
    "bond_refresh_btn",
    "treasure_hide_btn",
    "treasure_lock_btn",
    "treasure_refresh_btn",
    "skill_hide",
    "card_hide",
    "hide",
]
ANCHOR_THRESHOLD = 0.70  # min(0.70, settings.match_threshold=0.85)
ANCHOR_SCALES = (0.85, 0.9, 1.0, 1.1, 1.15, 1.2)
ANCHOR_ROI = (0.20, 0.45, 0.80, 0.80)
CLASSIFY_SCALES = (0.9, 1.0, 1.1)
# 建议阶段的假定三槽 ROI（与生产面板几何一致；负面板无面板时仅用于计数）
NEG_SLOT_X = [(0.230, 0.400), (0.415, 0.585), (0.600, 0.770)]
NEG_NAME_Y = (0.230, 0.350)

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
# O0-3: repo HEAD
# ---------------------------------------------------------------------------
def repo_head_info(repo_root: Path) -> dict:
    """git rev-parse HEAD + branch + dirty；非 git 环境返回 None 并如实记录。"""
    def _run(*args: str) -> str | None:
        try:
            out = subprocess.run(
                ["git", *args], cwd=str(repo_root), capture_output=True, text=True, timeout=10
            )
        except Exception:  # noqa: BLE001
            return None
        if out.returncode != 0:
            return None
        return out.stdout.strip() or None

    return {
        "repo_head": _run("rev-parse", "HEAD"),
        "repo_branch": _run("branch", "--show-current"),
        "repo_dirty": bool(_run("status", "--porcelain")),
    }


# ---------------------------------------------------------------------------
# O0-1/2: MODEL_MANIFEST.json 解析 + 真实 SHA256/大小校验
# ---------------------------------------------------------------------------
def load_model_manifest(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 2:
        raise ValueError(f"unexpected MODEL_MANIFEST schema_version: {data.get('schema_version')}")
    if not isinstance(data.get("models"), list) or not data["models"]:
        raise ValueError("MODEL_MANIFEST.json: missing 'models' list")
    return data


def find_manifest_entry(manifest: dict, model_subdir: str) -> dict:
    for entry in manifest["models"]:
        if entry.get("name") == model_subdir:
            return entry
    raise KeyError(f"MODEL_MANIFEST.json has no entry for model dir {model_subdir!r}")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def verify_model_files(model_dir: Path, entry: dict) -> dict:
    """真实计算并校验 manifest 记录的全部文件（SHA256 + size_bytes）。

    ``model_dir`` 是含模型文件的目录（如 models/ocr/PP-OCRv5_mobile_rec_infer），
    manifest 的 ``files`` 键为其中的相对文件名。
    任一文件缺失 / 大小不符 / 哈希不符 → passed=False，逐文件给出证据；
    这是评测报告 hash gate 的唯一事实来源（不硬编码 PASS）。
    """
    checks: list[dict] = []
    files = entry.get("files") or {}
    if not files:
        return {"passed": False, "checks": [], "error": "manifest entry has no 'files' to verify"}
    for rel, spec in files.items():
        p = model_dir / rel
        item = {
            "file": str(p),
            "expected_sha256": spec.get("sha256"),
            "expected_size_bytes": spec.get("size_bytes"),
        }
        if not p.exists():
            item.update({"exists": False, "passed": False, "error": "file missing"})
            checks.append(item)
            continue
        size = p.stat().st_size
        digest = sha256_file(p)
        ok_size = size == spec.get("size_bytes")
        ok_hash = digest == str(spec.get("sha256", "")).upper()
        item.update(
            {
                "exists": True,
                "actual_size_bytes": size,
                "actual_sha256": digest,
                "size_ok": ok_size,
                "hash_ok": ok_hash,
                "passed": ok_size and ok_hash,
            }
        )
        checks.append(item)
    passed = all(c.get("passed") for c in checks)
    return {"passed": passed, "checks": checks, "error": None}


# ---------------------------------------------------------------------------
# 数据加载
# ---------------------------------------------------------------------------
def load_manifest(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") not in (1, 2):
        raise ValueError(f"unexpected manifest schema_version: {data.get('schema_version')}")
    return data


def slot_crops(entry: dict, slot: dict) -> dict:
    """返回该槽位 (name_crop, progress_crop) 相对路径；progress 可能为 None。

    schema 2：优先用 slot['crops'] = {"name": ..., "progress": ...|null}（逐槽记录，
    支持槽间 progress 有无混合）；schema 1：回退到 entry['crops'] 扁平数组推断。
    """
    per_slot = slot.get("crops")
    if isinstance(per_slot, dict):
        return {"name": per_slot.get("name"), "progress": per_slot.get("progress")}
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


def slot_layout_status(slot: dict) -> str:
    """槽位布局验证状态。

    - slot['layout_status'] 显式给出（verified / unverified_layout）时直接采用；
    - 否则：有显式 per-slot roi → verified；无（旧 schema-1 manifest 的全局 ROI 时代）
      视为 legacy（report 单列 legacy_bbox 计数），不计为 unverified_layout。
    """
    explicit = slot.get("layout_status")
    if explicit in ("verified", "unverified_layout"):
        return explicit
    if slot.get("roi"):
        return "verified"
    return "legacy"


def valid_slots(manifest: dict) -> list[dict]:
    """全部 valid 槽位展开列表：[{entry, slot, crops}]（每槽唯一一条）。"""
    out = []
    for entry in manifest["entries"]:
        for slot in entry.get("slots", []):
            if not slot.get("is_valid"):
                continue
            out.append({"entry": entry, "slot": slot, "crops": slot_crops(entry, slot)})
    return out


def truth_status(canonical: str | None, lexicon: dict) -> str:
    """truth 归类：in_lexicon（规范名在词典）/ alias_covered（别名覆盖，需纠正）/
    unknown（词典外，独立计 unknown，不进准确率分母）。"""
    return _truth_status_of(canonical, lexicon)


def truth_canonical_for(canonical: str | None, lexicon: dict) -> str | None:
    """把 alias_covered 的 truth 纠正为词典规范名；unknown/in_lexicon 原样返回。"""
    return _truth_canonical_for(canonical, lexicon)


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


_PROGRESS_RE = re.compile(r"(\d+)\s*/\s*(\d+)")


def extract_progress(text: str) -> str | None:
    """从 OCR 文本提取 x/y 进度（游戏显示 '套装[1/7]'，truth 为 '1/7'）。"""
    m = _PROGRESS_RE.search(text)
    if not m:
        return None
    return f"{m.group(1)}/{m.group(2)}"


# ---------------------------------------------------------------------------
# 负面板 触发/分类/建议 链（mediator 只读复刻）
# ---------------------------------------------------------------------------
def _load_frame_bgr(path: Path):
    """中文路径安全读图（cv2.imdecode + np.fromfile）。"""
    import cv2
    import numpy as np

    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"cannot decode frame: {path}")
    return img


def selection_anchor_replica(frame: Frame, images_dir: Path):
    """复刻 mediator._selection_anchor：按钮区模板 + ROI + 位置校验。"""
    hit = match_any(
        frame,
        images_dir,
        ANCHOR_TEMPLATES,
        threshold=ANCHOR_THRESHOLD,
        scales=ANCHOR_SCALES,
        roi=ANCHOR_ROI,
    )
    if not hit:
        return None
    fx = hit.screen_x - frame.left
    fy = hit.screen_y - frame.top
    if fx < frame.width * 0.20 or fx > frame.width * 0.80:
        return None
    if fy < frame.height * 0.50:
        return None
    return hit


def classify_panel_replica(frame: Frame, images_dir: Path) -> str | None:
    """复刻 mediator._classify_choice_panel：bond/treasure/skill/card 判定。"""
    if match_any(frame, images_dir, ["bond_hide_btn", "bond_refresh_btn"], threshold=0.75, scales=CLASSIFY_SCALES):
        return "bond"
    treasure_lock = match_any(frame, images_dir, ["treasure_lock_btn"], threshold=ANCHOR_THRESHOLD, scales=CLASSIFY_SCALES)
    treasure_hide = match_any(frame, images_dir, ["hide"], threshold=0.95, scales=CLASSIFY_SCALES)
    if treasure_lock and treasure_hide:
        return "treasure"
    if match_any(frame, images_dir, ["skill_giveup_btn", "skill_refresh_btn"], threshold=ANCHOR_THRESHOLD, scales=CLASSIFY_SCALES):
        return "skill"
    if treasure_lock:
        return "treasure"
    if match_any(frame, images_dir, ["card_hide"], threshold=ANCHOR_THRESHOLD, scales=CLASSIFY_SCALES):
        return "card"
    return None


def resolve_fixture_frame(entry: dict, repo_root: Path) -> Path:
    """Resolve an OCR evaluation frame from its repository-relative fixture path.

    ``original_frame`` is retained in the manifest as capture provenance.  It
    may name a historical workstation, so evaluation must never use it as a
    runtime file path.
    """
    relative = str(entry.get("fixture_frame") or "").strip()
    if not relative:
        raise ValueError(f"fixture_frame missing for {entry.get('id', '<unknown>')}")
    candidate = Path(relative)
    if candidate.is_absolute() or candidate.drive:
        raise ValueError(f"fixture_frame must be repository-relative: {relative}")
    root = repo_root.resolve()
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"fixture_frame escapes repository root: {relative}") from exc
    if not resolved.is_file():
        raise FileNotFoundError(f"fixture_frame does not exist: {relative}")
    return resolved


def run_negative_chain(
    neg_entry: dict, images_dir: Path, rec, repo_root: Path, pre_dir: Path
) -> dict:
    """对单个负面板跑完整 触发/分类/建议 链，期望建议数 = 0。"""
    frame_path = resolve_fixture_frame(neg_entry, repo_root)
    img = _load_frame_bgr(frame_path)
    h, w = img.shape[:2]
    frame = Frame(bgr=img, left=0, top=0)
    anchor = selection_anchor_replica(frame, images_dir)
    kind = classify_panel_replica(frame, images_dir) if anchor else None
    suggestions: list[dict] = []
    if anchor and kind in ("skill", "bond", "treasure"):
        import cv2
        from PIL import Image

        for idx in range(3):
            x0, x1 = NEG_SLOT_X[idx]
            y0, y1 = int(0.230 * h), int(0.350 * h)
            box = (int(x0 * w), y0, int(x1 * w), y1)
            crop = frame.bgr[box[1]:box[3], box[0]:box[2]]
            if crop.size == 0:
                continue
            pil = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
            tmp = pre_dir / f"neg_{neg_entry['id']}_slot{idx}.png"
            preprocess_crop_ndarray(pil, tmp)
            r = predict_one(rec, tmp)
            if normalize_choice_text(r["text"]):
                suggestions.append(
                    {"slot": idx, "rec_text": r["text"], "score": round(r["score"], 4)}
                )
    return {
        "id": neg_entry["id"],
        "resolution": [w, h],
        "session_id": neg_entry.get("session_id"),
        "negative_reason": neg_entry.get("negative_reason", ""),
        "anchor_triggered": bool(anchor),
        "anchor_template": anchor.name if anchor else None,
        "anchor_score": round(anchor.score, 4) if anchor else None,
        "classified_kind": kind,
        "suggestion_count": len(suggestions),
        "suggestions": suggestions,
        "expected_suggestions": 0,
        "passed": len(suggestions) == 0,
    }


def preprocess_crop_ndarray(pil_img, dst: Path) -> None:
    """对 PIL 图像做 2x LANCZOS + 对比度增强，写 PNG（负面板建议阶段用）。"""
    from PIL import Image, ImageEnhance

    img = pil_img.convert("RGB")
    img = img.resize((img.width * PRE_SCALE, img.height * PRE_SCALE), Image.LANCZOS)
    img = ImageEnhance.Contrast(img).enhance(PRE_CONTRAST)
    img.save(dst)


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

    # ---- O0-3: repo HEAD ----
    head = repo_head_info(repo_root)

    # ---- O0-1/2: MODEL_MANIFEST 解析 + 真实 hash/size 校验（模型源目录）----
    model_manifest = load_model_manifest(Path(args.model_manifest))
    m_entry = find_manifest_entry(model_manifest, MODEL_SUBDIR)
    repo_model_dir = Path(args.models_dir) / MODEL_SUBDIR
    hash_gate = verify_model_files(repo_model_dir, m_entry)
    if not hash_gate["passed"]:
        # 硬门禁：模型字节与 manifest 不符 → 立即失败，不进入推理
        return {
            "schema_version": 2,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "repo_head": head,
            "models": {"name": MODEL_NAME, "subdir": MODEL_SUBDIR},
            "model_manifest": {
                "file": str(args.model_manifest),
                "entry": m_entry.get("name"),
                "hash_gate": hash_gate,
            },
            "stats": {"valid_slots": len(slots), "panels": len({s['entry']['id'] for s in slots})},
            "metrics": {},
            "performance": {},
            "offline_probe": {"passed": False, "note": "hash gate FAIL，未进入推理"},
            "negatives": {"total": 0, "passed": 0, "panels": []},
            "gates": {
                "chosen_variant": None,
                "gates": [
                    {
                        "gate": "model_hash_verified",
                        "threshold": "manifest sha256+size per file",
                        "actual": False,
                        "passed": False,
                    }
                ],
                "all_passed": False,
            },
            "aborted_reason": "model hash gate FAIL",
        }

    # ---- 模型暂存（ASCII 路径）----
    staging_root = Path(args.staging_dir)
    staging_root.mkdir(parents=True, exist_ok=True)
    model_dir = stage_model(Path(args.models_dir), staging_root)
    # 暂存副本同样校验（防御复制损坏）
    staged_hash_gate = verify_model_files(model_dir, m_entry)
    if not staged_hash_gate["passed"]:
        return {
            "schema_version": 2,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "repo_head": head,
            "models": {"name": MODEL_NAME, "subdir": MODEL_SUBDIR},
            "model_manifest": {
                "file": str(args.model_manifest),
                "entry": m_entry.get("name"),
                "hash_gate": hash_gate,
                "staged_hash_gate": staged_hash_gate,
            },
            "stats": {},
            "metrics": {},
            "performance": {},
            "offline_probe": {"passed": False, "note": "staged model hash gate FAIL"},
            "negatives": {"total": 0, "passed": 0, "panels": []},
            "gates": {
                "chosen_variant": None,
                "gates": [
                    {
                        "gate": "model_hash_verified",
                        "threshold": "staged copy",
                        "actual": False,
                        "passed": False,
                    }
                ],
                "all_passed": False,
            },
            "aborted_reason": "staged model hash gate FAIL",
        }

    # ---- 初始化（记录 RSS 与加载时间）----
    rss_import = rss_mb()
    rec, load_s = build_recognizer(model_dir, args.device, args.cpu_threads)
    rss_init = rss_mb()

    # ---- 预处理目录（ASCII 暂存区下）----
    pre_dir = staging_root / "preprocessed"
    pre_dir.mkdir(exist_ok=True)

    # ---- 逐槽推理（两轮：round 0 供准确率，两轮都供 latency/稳定性）----
    raw_samples = []  # 每 (slot, variant, round) 一条；准确率只用 round 0
    single_lat_raw: list[float] = []
    single_lat_pre: list[float] = []
    panel_lat_raw: list[float] = []
    panel_lat_pre: list[float] = []

    warmup_crop = repo_root / slots[0]["crops"]["name"]
    predict_one(rec, warmup_crop)  # 预热（不计时）

    panels = {}
    for item in slots:
        panels.setdefault(item["entry"]["id"], []).append(item)

    for _round in range(2):  # 两轮采样，提高 P95 稳定性；准确率分母 = 独立槽位
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
                    "session_id": item["entry"].get("session_id", ""),
                    "slot_index": item["slot"]["index"],
                    "round": _round,
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
                    "session_id": item["entry"].get("session_id", ""),
                    "slot_index": item["slot"]["index"],
                    "round": _round,
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

    # ---- 套装进度 OCR（仅 set_progress 非空槽位，raw 变体，每槽一次）----
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
        extracted = extract_progress(norm)
        progress_samples.append(
            {
                "entry_id": item["entry"]["id"],
                "session_id": item["entry"].get("session_id", ""),
                "slot_index": item["slot"]["index"],
                "canonical": item["slot"].get("canonical_name"),
                "crop": str((repo_root / prog_crop).relative_to(repo_root)),
                "rec_text": r["text"],
                "normalized": norm,
                "extracted": extracted,
                "truth": truth,
                "exact": norm == truth,
                "extracted_exact": extracted == truth,
                "score": round(r["score"], 4),
            }
        )

    # ---- 负面板 触发/分类/建议 链（37 个真实负面板，期望建议数 = 0）----
    images_dir = repo_root / "assets" / "Images"
    negatives = [
        e for e in manifest["entries"] if e.get("panel_kind") == "negative"
    ]
    neg_results = [
        run_negative_chain(e, images_dir, rec, repo_root, pre_dir) for e in negatives
    ]
    rec.close()

    # ---- 指标计算（round 0 唯一槽位；round 1 用于稳定性）----
    metrics = compute_metrics(raw_samples, progress_samples, lexicon, manifest)
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
    gates = evaluate_gates(metrics, perf, offline, hash_gate, head, neg_results)

    report = {
        "schema_version": 2,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "repo_head": head,
        "models": {"name": MODEL_NAME, "subdir": MODEL_SUBDIR},
        "model_manifest": {
            "file": str(args.model_manifest),
            "entry": m_entry.get("name"),
            "hash_gate": hash_gate,
        },
        "lexicon_names": sorted(lexicon["entries"].keys()),
        "lexicon_alias_surfaces": {
            canon: sorted({canon, *entry.get("aliases", [])})
            for canon, entry in lexicon["entries"].items()
        },
        "stats": {
            "valid_slots": metrics["unique"]["valid_slots"],
            "panels": len(panels),
            "progress_slots": len(progress_samples),
            "in_lexicon_slots": metrics["unique"]["in_lexicon_slots"],
            "alias_covered_slots": metrics["unique"]["alias_covered_slots"],
            "unknown_slots": metrics["unique"]["unknown_slots"],
            "unverified_layout_slots": metrics["unique"]["unverified_layout_slots"],
            "legacy_bbox_slots": metrics["unique"]["legacy_bbox_slots"],
            "negatives_total": len(neg_results),
            "negatives_passed": sum(1 for n in neg_results if n["passed"]),
            "rounds_in_latency": 2,
        },
        "metrics": metrics,
        "performance": perf,
        "offline_probe": offline,
        "negatives": {"total": len(neg_results), "passed": sum(1 for n in neg_results if n["passed"]), "panels": neg_results},
        "gates": gates,
    }
    return report


def compute_metrics(raw_samples: list[dict], progress_samples: list[dict], lexicon: dict, manifest: dict):
    """round-0 唯一槽位口径的指标 + 逐 session 指标 + 稳定性。"""
    lexicon_entries = lexicon["entries"]

    # 别名感知
    alias_sets = {}
    for canon, entry in lexicon_entries.items():
        alias_sets[canon] = {canon, *entry.get("aliases", [])}

    def alias_covered_by_lexicon(truth_canon: str) -> bool:
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

    def annotate(s: dict) -> dict:
        canon = truth_canonical_for(s["truth_canonical"] or None, lexicon)
        status = truth_status(s["truth_canonical"] or None, lexicon)
        return {**s, "truth_canon_for_eval": canon, "truth_status": status}

    variants = {}
    for variant in ("raw", "pre"):
        round0 = [annotate(s) for s in raw_samples if s["variant"] == variant and s["round"] == 0]
        # 唯一槽位（round 0 天然唯一）
        n = len(round0)

        # ---- a. OCR-raw 报告层（不设门禁）----
        char_accs = [
            char_accuracy(
                normalize_choice_text(s["rec_text"]),
                normalize_choice_text(s["truth_raw"]),
            )
            for s in round0
        ]
        word_exact = [
            normalize_choice_text(s["rec_text"]) == normalize_choice_text(s["truth_raw"])
            for s in round0
        ]
        word_exact_canon = [
            normalize_choice_text(s["rec_text"]) == normalize_choice_text(s["truth_canon_for_eval"] or "")
            for s in round0
        ]

        # ---- b. lexicon-gated 生产门禁层 ----
        gated = []
        for s in round0:
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

        in_lex = [g for g in gated if g["truth_status"] == "in_lexicon"]
        alias_covered = [g for g in gated if g["truth_status"] == "alias_covered"]
        in_lex_alias = in_lex + alias_covered
        unknown = [g for g in gated if g["truth_status"] == "unknown"]
        unverified = [
            g for g in in_lex_alias
            if slot_layout_status(_find_slot(manifest, g)) == "unverified_layout"
        ]
        # 布局未验证槽不进分母（in_lex_alias 中剔除）
        in_lex_alias_verified = [
            g for g in in_lex_alias if slot_layout_status(_find_slot(manifest, g)) != "unverified_layout"
        ]
        in_lex_verified = [g for g in in_lex_alias_verified if g["truth_status"] == "in_lexicon"]

        canonical_top1_strict = sum(
            1 for g in in_lex_verified if g["lookup_canonical"] == g["truth_canon_for_eval"]
        )
        canonical_top1_alias = sum(
            1 for g in in_lex_alias_verified if alias_aware_hit(g["truth_canon_for_eval"], g["lookup_canonical"])
        )
        denom_strict = len(in_lex_verified)
        denom_alias = len(in_lex_alias_verified)
        recall = canonical_top1_strict / denom_strict if denom_strict else None
        recall_alias = canonical_top1_alias / denom_alias if denom_alias else None
        skill_in = [g for g in in_lex_verified if g["kind"] == "skill"]
        recall_skill = (
            sum(1 for g in skill_in if g["lookup_canonical"] == g["truth_canon_for_eval"]) / len(skill_in)
            if skill_in
            else None
        )
        mis_norm = [g for g in unknown if g["lookup_canonical"] is not None]
        none_ok = [g for g in unknown if g["lookup_canonical"] is None]

        # ---- 逐 session（round 0，唯一槽位口径）----
        by_session: dict[str, dict] = {}
        for g in in_lex_alias_verified:
            sess = g["session_id"] or "?"
            row = by_session.setdefault(
                sess, {"slots": 0, "hits": 0, "unknown": 0, "unverified": 0, "panels": set()}
            )
            row["slots"] += 1
            row["hits"] += 1 if alias_aware_hit(g["truth_canon_for_eval"], g["lookup_canonical"]) else 0
            row["panels"].add(g["entry_id"])
        for g in unknown:
            sess = g["session_id"] or "?"
            row = by_session.setdefault(sess, {"slots": 0, "hits": 0, "unknown": 0, "unverified": 0, "panels": set()})
            row["unknown"] += 1
        for g in [x for x in gated if slot_layout_status(_find_slot(manifest, x)) == "unverified_layout"]:
            sess = g["session_id"] or "?"
            row = by_session.setdefault(sess, {"slots": 0, "hits": 0, "unknown": 0, "unverified": 0, "panels": set()})
            row["unverified"] += 1
        session_metrics = {}
        for sess, row in sorted(by_session.items()):
            session_metrics[sess] = {
                "in_lexicon_slots": row["slots"],
                "top1_hits": row["hits"],
                "top1_accuracy": round(row["hits"] / row["slots"], 4) if row["slots"] else None,
                "unknown_slots": row["unknown"],
                "unverified_layout_slots": row["unverified"],
                "panels": sorted(row["panels"]),
            }

        variants[variant] = {
            "raw_layer": {
                "slots": n,
                "char_accuracy": round(sum(char_accs) / n, 4) if n else None,
                "word_accuracy_vs_raw_text": round(sum(word_exact) / n, 4) if n else None,
                "word_accuracy_vs_canonical": round(sum(word_exact_canon) / n, 4) if n else None,
            },
            "gated_layer": {
                "in_lexicon_total": len(in_lex_alias_verified),
                "in_lexicon_strict": len(in_lex_verified),
                "out_of_lexicon_total": len(unknown),
                "unverified_layout_excluded": len(unverified),
                "canonical_top1_strict": {
                    "numerator": canonical_top1_strict,
                    "denominator": denom_strict,
                    "accuracy": round(canonical_top1_strict / denom_strict, 4) if denom_strict else None,
                },
                "canonical_top1_alias_aware": {
                    "numerator": canonical_top1_alias,
                    "denominator": denom_alias,
                    "accuracy": round(canonical_top1_alias / denom_alias, 4) if denom_alias else None,
                },
                "lexicon_recall": {
                    "value": round(recall, 4) if recall is not None else None,
                    "denominator": denom_strict,
                },
                "lexicon_recall_alias_aware": {
                    "value": round(recall_alias, 4) if recall_alias is not None else None,
                    "denominator": denom_alias,
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
            "session_metrics": session_metrics,
            "samples": [
                {
                    "entry_id": g["entry_id"],
                    "session_id": g["session_id"],
                    "slot_index": g["slot_index"],
                    "kind": g["kind"],
                    "crop": g["crop"],
                    "rec_text": g["rec_text"],
                    "rec_score": g["rec_score"],
                    "normalized": g["normalized"],
                    "truth_raw": g["truth_raw"],
                    "truth_canonical": g["truth_canonical"],
                    "truth_canon_for_eval": g["truth_canon_for_eval"],
                    "truth_status": g["truth_status"],
                    "layout_status": slot_layout_status(_find_slot(manifest, g)),
                    "roi": _find_slot(manifest, g).get("roi"),
                    "lookup_canonical": g["lookup_canonical"],
                    "lookup_margin": g["lookup_margin"],
                    "is_dragon_ball": g["is_dragon_ball"],
                }
                for g in gated
            ],
        }

    # 稳定性：round0 vs round1 逐槽（raw 变体）rec_text 一致率
    r0 = {s["entry_id"] + f":{s['slot_index']}": s for s in raw_samples if s["variant"] == "raw" and s["round"] == 0}
    r1 = {s["entry_id"] + f":{s['slot_index']}": s for s in raw_samples if s["variant"] == "raw" and s["round"] == 1}
    common = [k for k in r0 if k in r1]
    stable = sum(1 for k in common if r0[k]["rec_text"] == r1[k]["rec_text"])
    stability = {
        "slots_compared": len(common),
        "round0_round1_text_identical": stable,
        "stability_rate": round(stable / len(common), 4) if common else None,
    }

    prog = {
        "slots": len(progress_samples),
        "exact_correct": sum(1 for p in progress_samples if p["exact"]),
        "accuracy": (
            round(sum(1 for p in progress_samples if p["exact"]) / len(progress_samples), 4)
            if progress_samples
            else None
        ),
        "extracted_correct": sum(1 for p in progress_samples if p.get("extracted_exact")),
        "extracted_accuracy": (
            round(sum(1 for p in progress_samples if p.get("extracted_exact")) / len(progress_samples), 4)
            if progress_samples
            else None
        ),
        "samples": progress_samples,
    }

    unique = {
        "valid_slots": len(set((s["entry_id"], s["slot_index"]) for s in raw_samples)),
        "in_lexicon_slots": len(set((s["entry_id"], s["slot_index"]) for s in raw_samples if truth_status(s.get("truth_canonical") or None, lexicon) == "in_lexicon")),
        "alias_covered_slots": len(set((s["entry_id"], s["slot_index"]) for s in raw_samples if truth_status(s.get("truth_canonical") or None, lexicon) == "alias_covered")),
        "unknown_slots": len(set((s["entry_id"], s["slot_index"]) for s in raw_samples if truth_status(s.get("truth_canonical") or None, lexicon) == "unknown")),
        "unverified_layout_slots": len(
            {
                (s["entry_id"], s["slot_index"])
                for s in raw_samples
                if slot_layout_status(_find_slot(manifest, s)) == "unverified_layout"
            }
        ),
        "legacy_bbox_slots": len(
            {
                (s["entry_id"], s["slot_index"])
                for s in raw_samples
                if slot_layout_status(_find_slot(manifest, s)) == "legacy"
            }
        ),
    }

    return {
        "variants": variants,
        "progress": prog,
        "stability": stability,
        "unique": unique,
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


def _find_slot(manifest: dict, g: dict) -> dict:
    """按 (entry_id, slot_index) 从 manifest 取 slot；找不到返回 {}。"""
    for entry in manifest["entries"]:
        if entry["id"] == g["entry_id"]:
            for slot in entry.get("slots", []):
                if slot["index"] == g["slot_index"]:
                    return slot
    return {}


def evaluate_gates(metrics: dict, perf: dict, offline: dict, hash_gate: dict, head: dict, neg_results: list) -> dict:
    def judge(name: str, actual, gate, invert: bool = False) -> dict:
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
        judge("set_progress_accuracy", prog.get("extracted_accuracy", prog["accuracy"]), GATES["set_progress_accuracy"]),
        judge("panel3_cpu_p95", perf[f"panel3_{chosen}_p95_ms"], GATES["panel3_cpu_p95_ms"], invert=True),
        judge("single_cpu_p95", perf[f"single_slot_{chosen}_p95_ms"], GATES["single_cpu_p95_ms"], invert=True),
        judge("rss_delta", perf["rss_delta_mb"], GATES["rss_delta_mb"], invert=True),
    ]
    gates.append(judge("offline_inference", 1.0 if offline["passed"] else 0.0, 1.0))
    # O0-2: 真实模型字节校验（不再是硬编码 PASS）
    gates.append({"gate": "model_hash_verified", "threshold": "manifest sha256+size per file (repo + staged)",
                  "actual": bool(hash_gate["passed"]), "passed": bool(hash_gate["passed"]),
                  "checks": hash_gate["checks"]})
    # O0-3: repo_head 非空
    gates.append({"gate": "repo_head_recorded", "threshold": "non-empty git rev-parse HEAD",
                  "actual": head["repo_head"], "passed": bool(head["repo_head"])})
    # O0-7: 负面板建议数 = 0
    neg_passed = all(n["passed"] for n in neg_results)
    gates.append({"gate": "negative_panels_zero_suggestions",
                  "threshold": "每负面板 suggestion_count == 0",
                  "actual": f"{sum(1 for n in neg_results if n['passed'])}/{len(neg_results)}",
                  "passed": bool(neg_passed)})
    return {
        "chosen_variant": chosen,
        "gates": gates,
        "all_passed": all(x["passed"] for x in gates),
    }


# ---------------------------------------------------------------------------
# 报告输出
# ---------------------------------------------------------------------------
def render_markdown(report: dict) -> str:
    if not report.get("metrics"):
        lines = [f"# OCR 评测报告（ABORTED）", ""]
        lines.append(f"> 生成时间：{report.get('generated_at')}")
        lines.append(f"> 中止原因：{report.get('aborted_reason', 'unknown')}")
        lines.append("")
        hg = report.get("model_manifest", {}).get("hash_gate", {})
        for c in hg.get("checks", []):
            lines.append(f"- {Path(c['file']).name}: {c.get('error') or ('size/hash FAIL' if not c.get('passed') else 'PASS')}")
        return "\n".join(lines)
    m = report["metrics"]
    p = report["performance"]
    g = report["gates"]
    head = report["repo_head"]
    lexicon_names = set(report["lexicon_names"])
    lines = []
    lines.append("# B2-2 离线 OCR 评测报告（PP-OCRv5 mobile rec-only，O0/O1 可信度口径）")
    lines.append("")
    lines.append(f"> 生成时间：{report['generated_at']}")
    lines.append(f"> repo HEAD：{head.get('repo_head') or 'MISSING'}（branch={head.get('repo_branch')}，dirty={head.get('repo_dirty')}）")
    lines.append(f"> 模型：{report['models']['name']}（MODEL_MANIFEST.json，hash gate 实测见 §0）")
    lines.append(
        f"> 数据：{report['stats']['valid_slots']} 独立 valid slots / {report['stats']['panels']} 面板 / "
        f"{report['stats']['progress_slots']} 套装进度槽 / "
        f"{report['stats']['unknown_slots']} unknown 槽 / "
        f"{report['stats']['unverified_layout_slots']} unverified_layout 槽（不进分母）"
    )
    lines.append(f"> 预处理对比：原图 vs {p['preprocessing']}")
    lines.append(f"> 机器：i5-13600KF / Windows 10 / CPU（{p['cpu_threads']} threads，device={p['device']}）")
    lines.append("")

    lines.append("## 0. 模型完整性门禁（真实 SHA256/大小校验）")
    lines.append("")
    hg = report["model_manifest"]["hash_gate"]
    lines.append(f"- manifest 文件：`{report['model_manifest']['file']}`（schema {2}，entry={report['model_manifest']['entry']}）")
    lines.append(f"- 结果：{'PASS' if hg['passed'] else 'FAIL'}")
    lines.append("")
    lines.append("| 文件 | 大小(字节) | SHA256 | 校验 |")
    lines.append("|---|---|---|---|")
    for c in hg.get("checks", []):
        lines.append(
            f"| {Path(c['file']).name} | {c.get('actual_size_bytes', 'missing')} | "
            f"{(c.get('actual_sha256') or '')[:16]}… | {'PASS' if c.get('passed') else 'FAIL'} |"
        )
    lines.append("")

    lines.append("## 1. 门禁结果（生产候选变体 = " + str(g["chosen_variant"]) + "）")
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

    lines.append("## 2. OCR-raw 报告层（round-0 唯一槽位口径，不设门禁）")
    lines.append("")
    lines.append("| 变体 | 槽位数 | 字符准确率 | 词准确率(对 raw_text) | 词准确率(对规范名) |")
    lines.append("|---|---:|---:|---:|---:|")
    for v in ("raw", "pre"):
        rl = m["variants"][v]["raw_layer"]
        lines.append(
            f"| {v} | {rl['slots']} | {pct(rl['char_accuracy'])}% | {pct(rl['word_accuracy_vs_raw_text'])}% | "
            f"{pct(rl['word_accuracy_vs_canonical'])}% |"
        )
    lines.append("")
    lines.append(f"稳定性（raw 变体 round0 vs round1 文本一致率）：{pct(m['stability']['stability_rate'])}%（{m['stability']['round0_round1_text_identical']}/{m['stability']['slots_compared']} 槽）")
    lines.append("")

    lines.append("## 3. lexicon-gated 生产门禁层")
    lines.append("")
    for v in ("raw", "pre"):
        gl = m["variants"][v]["gated_layer"]
        lines.append(f"### 变体 {v}")
        lines.append("")
        lines.append(f"- 词典内槽位（含别名覆盖，布局已验证）：{gl['in_lexicon_total']}，"
                     f"其中严格词典内 {gl['in_lexicon_strict']}；词典外(unknown)：{gl['out_of_lexicon_total']}；"
                     f"unverified_layout 剔除：{gl['unverified_layout_excluded']}")
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
        lines.append("#### 逐 session 指标（round-0 唯一槽位口径）")
        lines.append("")
        lines.append("| session | 词典内槽 | Top-1 命中 | Top-1 | unknown | unverified | 面板数 |")
        lines.append("|---|---:|---:|---:|---:|---:|---|")
        for sess, sm in sorted(m["variants"][v]["session_metrics"].items()):
            lines.append(
                f"| {sess} | {sm['in_lexicon_slots']} | {sm['top1_hits']} | "
                f"{pct(sm['top1_accuracy']) if sm['top1_accuracy'] is not None else '-'}% | "
                f"{sm['unknown_slots']} | {sm['unverified_layout_slots']} | {len(sm['panels'])} |"
            )
        lines.append("")
    lines.append(
        f"### 套装进度 x/y 正确率：字符串精确 {pct(m['progress']['accuracy'])}%"
        f"（{m['progress']['exact_correct']}/{m['progress']['slots']}）；"
        f"x/y 提取（'套装[1/7]'→'1/7'）{pct(m['progress']['extracted_accuracy'])}%"
        f"（{m['progress']['extracted_correct']}/{m['progress']['slots']}）"
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
    lines.append(f"| 采样量 | 单槽 {p['single_slot_samples']}、三槽 {p['panel3_samples']}（2 轮，仅 latency） |")
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

    lines.append("## 5b. 负面板 触发/分类/建议 链（期望建议数 = 0）")
    lines.append("")
    neg = report["negatives"]
    lines.append(f"- 通过：{neg['passed']}/{neg['total']}")
    lines.append("")
    lines.append("| 面板 | 分辨率 | 原因 | 触发 | 锚点模板 | 分类 | 建议数 | 结论 |")
    lines.append("|---|---:|---|---|---|---:|---|")
    for n in neg["panels"]:
        lines.append(
            f"| {n['id']} | {'x'.join(map(str, n['resolution']))} | {n['negative_reason']} | "
            f"{'是' if n['anchor_triggered'] else '否'} | {n['anchor_template'] or '-'} | "
            f"{n['classified_kind'] or '-'} | {n['suggestion_count']} | "
            f"{'PASS' if n['passed'] else 'FAIL'} |"
        )
    lines.append("")

    lines.append("## 6. 错例清单")
    lines.append("")
    chosen = g["chosen_variant"]
    lines.append(f"### 6.1 生产门禁错误（候选变体 {chosen}，词典内 Top-1 错误）")
    lines.append("")
    alias_surfaces = report.get("lexicon_alias_surfaces", {})
    errors = []
    for s in m["variants"][chosen]["samples"]:
        if s["truth_status"] in ("in_lexicon", "alias_covered") and s["layout_status"] != "unverified_layout":
            if s["lookup_canonical"] != s["truth_canon_for_eval"]:
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

    lines.append("## 7. 词典覆盖缺口（O1: 已纠正或标 unknown 的槽位）")
    lines.append("")
    missing = Counter()
    for s in m["variants"]["raw"]["samples"]:
        if s["truth_status"] == "unknown":
            missing[s["truth_canonical"]] += 1
    if missing:
        lines.append(f"unknown truth 槽共 {report['stats']['unknown_slots']} 个，独立计 unknown、不进准确率分母：")
        for name, count in sorted(missing.items()):
            lines.append(f"- `{name}` ×{count}")
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
    ap.add_argument("--model-manifest", type=Path, default=DEFAULT_MODEL_MANIFEST)
    ap.add_argument("--model-subdir", default=MODEL_SUBDIR,
                    help="模型目录名（默认 PP-OCRv5_mobile_rec_infer；server 用 PP-OCRv5_server_rec_infer）")
    ap.add_argument("--model-name", default=MODEL_NAME,
                    help="paddlex 模型名（默认 PP-OCRv5_mobile_rec；server 用 PP-OCRv5_server_rec）")
    ap.add_argument(
        "--staging-dir",
        type=Path,
        default=Path(tempfile.gettempdir()) / "shuabao_ocr_stage",
        help="ASCII 路径模型暂存目录（Paddle 无法读取含非 ASCII 字符的路径）",
    )
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument("--device", default="cpu", choices=["cpu", "gpu:0", "gpu"])
    ap.add_argument("--cpu-threads", type=int, default=10)
    args = ap.parse_args(argv)
    MODEL_SUBDIR, MODEL_NAME, MODEL_TAG = args.model_subdir, args.model_name, args.model_name

    report = run_eval(args)
    if report.get("aborted_reason"):
        # hash gate 硬失败：仍写报告留证据，但退出码非 0
        json_path, md_path = write_reports(report, args.out_dir)
        print(f"[ABORTED] {report['aborted_reason']}")
        print(f"[OK] json: {json_path}")
        print(f"[OK] md:   {md_path}")
        return 3
    json_path, md_path = write_reports(report, args.out_dir)
    print(f"[OK] json: {json_path}")
    print(f"[OK] md:   {md_path}")
    print(json.dumps(report["gates"], ensure_ascii=False, indent=2))
    return 0 if report["gates"]["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
