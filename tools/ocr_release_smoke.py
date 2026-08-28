#!/usr/bin/env python3
"""Boot a frozen OCR worker and exercise its release protocol end to end."""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKER = ROOT / "dist" / "ShuaBao" / "vision" / "ShuaBaoOCR.exe"
DEFAULT_MODEL_DIR = ROOT / "dist" / "ShuaBao" / "vision" / "_internal" / "models" / "ocr"
DEFAULT_IMAGE = ROOT / "fixtures" / "ocr_choices" / "skill" / "rec1_ingame_boss_20260809" / "t_015s_技能面板_giveUp证据_slot0_name.png"


class SmokeError(RuntimeError):
    pass


def _drain(stream, output: queue.Queue[str | None]) -> None:  # noqa: ANN001
    try:
        for line in stream:
            output.put(line)
    finally:
        output.put(None)


def _read_json(output: queue.Queue[str | None], timeout_s: float) -> dict:
    try:
        line = output.get(timeout=timeout_s)
    except queue.Empty as exc:
        raise SmokeError(f"worker response timeout after {timeout_s:.1f}s") from exc
    if line is None:
        raise SmokeError("worker exited before sending a response")
    try:
        value = json.loads(line)
    except json.JSONDecodeError as exc:
        raise SmokeError(f"worker emitted invalid JSON: {line.strip()!r}") from exc
    if not isinstance(value, dict):
        raise SmokeError("worker response is not a JSON object")
    return value


def _available_text(output: queue.Queue[str | None]) -> str:
    lines: list[str] = []
    while True:
        try:
            line = output.get_nowait()
        except queue.Empty:
            break
        if line is not None:
            lines.append(line.rstrip())
    return "\n".join(lines)


def _request(process: subprocess.Popen[str], output: queue.Queue[str | None], request: dict, timeout_s: float) -> dict:
    if process.stdin is None:
        raise SmokeError("worker stdin is unavailable")
    process.stdin.write(json.dumps(request, ensure_ascii=False, separators=(",", ":")) + "\n")
    process.stdin.flush()
    return _read_json(output, timeout_s)


def run_smoke(worker: Path, model_dir: Path, image: Path, expected: str, timeout_s: float) -> dict[str, object]:
    for path, label in ((worker, "worker"), (model_dir, "model directory"), (image, "OCR fixture")):
        if not path.exists():
            raise SmokeError(f"{label} missing: {path}")
    env = os.environ.copy()
    env["SHUABAO_OCR_MODEL_DIR"] = str(model_dir)
    env["SHUABAO_OCR_REPO_ROOT"] = str(worker.parent)
    process = subprocess.Popen(
        [str(worker)],
        cwd=str(worker.parent),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=env,
    )
    stdout: queue.Queue[str | None] = queue.Queue()
    stderr: queue.Queue[str | None] = queue.Queue()
    threading.Thread(target=_drain, args=(process.stdout, stdout), daemon=True).start()
    threading.Thread(target=_drain, args=(process.stderr, stderr), daemon=True).start()
    started = time.perf_counter()
    try:
        ready = _read_json(stdout, timeout_s)
        if ready.get("type") != "ready" or ready.get("status") != "ok" or ready.get("model_validated") is not True:
            detail = _available_text(stderr)
            suffix = f"\nstderr:\n{detail}" if detail else ""
            raise SmokeError(f"worker did not become ready with a validated model: {ready}{suffix}")
        if not ready.get("model_hash"):
            raise SmokeError(f"worker ready response has no model hash: {ready}")

        pong = _request(process, stdout, {"type": "ping", "seq": 1}, min(timeout_s, 10.0))
        if pong.get("type") != "pong" or pong.get("status") != "ok":
            raise SmokeError(f"worker ping failed: {pong}")

        warmup = _request(process, stdout, {"type": "warmup", "seq": 2}, timeout_s)
        if warmup.get("type") != "warmup_ack" or warmup.get("status") != "ok":
            raise SmokeError(f"worker warmup failed: {warmup}")

        image_b64 = base64.b64encode(image.read_bytes()).decode("ascii")
        prediction = _request(
            process,
            stdout,
            {"type": "predict", "seq": 3, "kind": "skill", "image_b64": image_b64},
            min(timeout_s, 30.0),
        )
        names = {str(candidate.get("name")) for candidate in prediction.get("candidates", []) if isinstance(candidate, dict)}
        if prediction.get("status") != "ok" or expected not in names:
            raise SmokeError(f"OCR prediction did not contain {expected!r}: {prediction}")
        return {
            "status": "pass",
            "model_name": ready.get("model_name"),
            "model_hash": ready.get("model_hash"),
            "load_ms": ready.get("load_ms"),
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
            "expected": expected,
        }
    finally:
        if process.stdin is not None:
            process.stdin.close()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", type=Path, default=DEFAULT_WORKER)
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--image", type=Path, default=DEFAULT_IMAGE)
    parser.add_argument("--expected", default="次级箭")
    parser.add_argument("--timeout-s", type=float, default=60.0)
    args = parser.parse_args()
    try:
        result = run_smoke(args.worker.resolve(), args.model_dir.resolve(), args.image.resolve(), args.expected, args.timeout_s)
    except (OSError, SmokeError) as exc:
        print(f"ERROR: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
