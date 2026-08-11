"""JSONL OCR worker; run only in the dedicated .venv-ocr child process."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    configured = os.environ.get("GAMESCRIPT_OCR_REPO_ROOT")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[4]


MODEL_SUBDIR = "PP-OCRv5_mobile_rec_infer"


def _model_dir() -> Path:
    configured = Path(os.environ["GAMESCRIPT_OCR_MODEL_DIR"]) if os.environ.get("GAMESCRIPT_OCR_MODEL_DIR") else _repo_root() / "models" / "ocr"
    if configured.name == MODEL_SUBDIR:
        return configured
    return configured / MODEL_SUBDIR


def _manifest_entry() -> dict[str, Any] | None:
    path = _model_dir().parent / "MODEL_MANIFEST.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        for entry in data.get("models", []):
            if entry.get("name") == "PP-OCRv5_mobile_rec_infer":
                return entry
    except (OSError, ValueError, TypeError):
        return None
    return None


def _validate_model(src: Path) -> str | None:
    if not src.is_dir():
        return "model_missing"
    entry = _manifest_entry()
    files = (entry or {}).get("files") or {}
    for name in ("inference.json", "inference.pdiparams", "inference.yml"):
        path = src / name
        if not path.is_file():
            return "model_missing"
        expected = files.get(name)
        if expected:
            try:
                if path.stat().st_size != int(expected["size_bytes"]):
                    return "model_corrupt"
                digest = hashlib.sha256(path.read_bytes()).hexdigest().upper()
                if digest != str(expected["sha256"]).upper():
                    return "model_corrupt"
            except (OSError, KeyError, TypeError, ValueError):
                return "model_corrupt"
    return None


def _stage_model(src: Path) -> tuple[Path | None, str | None, tempfile.TemporaryDirectory[str] | None]:
    reason = _validate_model(src)
    if reason:
        return None, reason, None
    # Paddle's Windows loader cannot consume the repository's non-ASCII path.
    stage = tempfile.TemporaryDirectory(prefix="gamescript_ocr_stage_")
    dst = Path(stage.name) / src.name
    try:
        shutil.copytree(src, dst)
    except OSError:
        stage.cleanup()
        return None, "model_corrupt", None
    if (reason := _validate_model(dst)):
        stage.cleanup()
        return None, reason, None
    return dst, None, stage


def _load_recognizer(model: Path):
    from paddleocr._models.text_recognition import TextRecognition

    return TextRecognition(
        model_name="PP-OCRv5_mobile_rec",
        model_dir=str(model),
        device="cpu",
        cpu_threads=4,
    )


def _predict(rec: Any, image_b64: str, kind: str | None) -> tuple[list[dict[str, Any]], str | None, float]:
    import io
    from PIL import Image, ImageEnhance

    raw = base64.b64decode(image_b64, validate=True)
    with Image.open(io.BytesIO(raw)).convert("RGB") as image:
        image = image.resize((image.width * 2, image.height * 2), Image.Resampling.LANCZOS)
        image = ImageEnhance.Contrast(image).enhance(1.5)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as fh:
            path = fh.name
        try:
            image.save(path)
            result = rec.predict(path)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
    item = result[0] if result else {}
    text = str(item.get("rec_text") or "")
    rec_score = float(item.get("rec_score") or 0.0)
    # Importing the normalizer here keeps the parent process Paddle-free.
    src = str(_repo_root() / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    from gamescript.vision.choice_ocr import load_lexicon, lookup_lexicon, normalize_choice_text

    normalized = normalize_choice_text(text)
    lookup = lookup_lexicon(normalized, kind=kind, lexicon=load_lexicon())
    if lookup.canonical is None:
        return [], normalized, rec_score
    names = list(lookup.top2_names) or [lookup.canonical]
    candidates = [{"name": names[0], "confidence": max(0.0, min(1.0, rec_score))}]
    if len(names) > 1:
        candidates.append({
            "name": names[1],
            "confidence": max(0.0, min(1.0, rec_score - lookup.margin)),
        })
    return candidates, normalized, rec_score


def _emit(value: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main() -> int:
    model, model_reason, stage = _stage_model(_model_dir())
    rec = None
    if model is not None:
        try:
            rec = _load_recognizer(model)
            model_reason = None
        except Exception:  # Paddle may fail for a damaged/incompatible local model.
            model_reason = "model_corrupt"
    _emit({
        "type": "ready",
        "seq": 0,
        "status": "ok" if rec is not None else "unavailable",
        "candidates": [],
        "elapsed_ms": 0.0,
        **({"reason": model_reason} if model_reason else {}),
    })
    try:
        for line in sys.stdin:
            started = time.perf_counter()
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise ValueError("request must be an object")
            except (json.JSONDecodeError, ValueError, TypeError):
                _emit({"seq": -1, "status": "unavailable", "candidates": [], "elapsed_ms": 0.0, "reason": "bad_json"})
                continue
            seq = int(request.get("seq", -1))
            if request.get("type") == "ping":
                _emit({"type": "pong", "seq": seq, "status": "ok", "candidates": [], "elapsed_ms": 0.0})
                continue
            if request.get("type") != "predict":
                _emit({"seq": seq, "status": "unavailable", "candidates": [], "elapsed_ms": 0.0, "reason": "bad_request"})
                continue
            if rec is None:
                _emit({"seq": seq, "status": "unavailable", "candidates": [], "elapsed_ms": (time.perf_counter() - started) * 1000, "reason": model_reason or "model_missing"})
                continue
            try:
                candidates, _normalized, _score = _predict(rec, str(request.get("image_b64", "")), request.get("kind"))
                _emit({"seq": seq, "status": "ok", "candidates": candidates, "elapsed_ms": (time.perf_counter() - started) * 1000})
            except Exception:
                _emit({"seq": seq, "status": "unavailable", "candidates": [], "elapsed_ms": (time.perf_counter() - started) * 1000, "reason": "inference_error"})
    finally:
        if stage is not None:
            stage.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
