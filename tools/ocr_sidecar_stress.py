#!/usr/bin/env python3
"""O4 persistent-sidecar stress and timing harness.

Default run sends 10,000 sequential slot requests through one child process,
then reports protocol alignment, bounded client cache, child lifetime, RSS,
and three-slot panel P95.  It never sends an input action.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gamescript.vision.ocr_shadow import ShadowClient

def _rss_mb(proc) -> float | None:
    try:
        import psutil
        if proc is not None and proc.pid:
            root = psutil.Process(proc.pid)
            total = root.memory_info().rss
            for child in root.children(recursive=True):
                total += child.memory_info().rss
            return total / (1024 * 1024)
    except Exception:
        pass
    return None


def _child_count(proc) -> int | None:
    try:
        import psutil
        if proc is not None and proc.pid:
            return len(psutil.Process(proc.pid).children(recursive=True))
    except Exception:
        pass
    return None


def _crops() -> list[Path]:
    paths: list[Path] = []
    for manifest_name in ("manifest.json", "D0_extended_manifest.json"):
        path = ROOT / "fixtures" / "ocr_choices" / manifest_name
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for entry in data.get("entries", []):
            for slot in entry.get("slots", []):
                for crop in (slot.get("crops") or {}).values():
                    if crop:
                        candidate = ROOT / str(crop).replace("\\", "/")
                        if candidate.exists() and candidate not in paths:
                            paths.append(candidate)
    if not paths:
        raise FileNotFoundError("no OCR fixture crops found")
    return paths


def _image_bbox(data: bytes) -> tuple[int, int, int, int]:
    import cv2
    import numpy as np
    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("fixture is not a decodable image")
    return (0, 0, int(image.shape[1]), int(image.shape[0]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=int, default=10000)
    parser.add_argument("--timeout-ms", type=int, default=400)
    parser.add_argument("--warmup-s", type=float, default=120.0)
    parser.add_argument("--model-dir", type=Path, default=ROOT / "models" / "ocr")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.requests < 3:
        parser.error("--requests must be >= 3 for a three-slot measurement")
    paths = _crops()
    client = ShadowClient(timeout_ms=args.timeout_ms, model_dir=args.model_dir)
    # Warm up the persistent worker so the timed loop measures real inference.
    warmup_started = time.perf_counter()
    warmup_ready = False
    warmup_deadline = time.monotonic() + args.warmup_s
    while time.monotonic() < warmup_deadline:
        if client.ping():
            warmup_ready = True
            break
        time.sleep(0.2)
    warmup_s = time.perf_counter() - warmup_started
    if not warmup_ready:
        print(json.dumps({"requests": 0, "warmup_s": round(warmup_s, 1), "error": "worker not ready"}, ensure_ascii=False, indent=2))
        client.close()
        return 2
    latencies: list[float] = []
    panel_latencies: list[float] = []
    unavailable = 0
    protocol_errors = 0
    reason_counts: dict[str, int] = {}
    rss_samples: list[dict] = []
    rss_start = None
    rss_end = None
    child_max = 0
    started = time.perf_counter()
    try:
        # Include image bytes as the frame and use its full extent as bbox.
        for i in range(args.requests):
            path = paths[i % len(paths)]
            frame = path.read_bytes()
            bbox = _image_bbox(frame)
            panel_id = f"stress-panel-{i // 3}"
            slot_id = i % 3
            slot = {"slot_id": slot_id, "bbox": bbox, "kind": "skill"}
            t0 = time.perf_counter()
            response = client.shadow_predict(frame, panel_id, slot, fingerprint=f"stress-{i // 3}-{i}")
            elapsed = (time.perf_counter() - t0) * 1000
            latencies.append(elapsed)
            unavailable += int(response.status != "ok")
            if response.reason:
                reason_counts[response.reason] = reason_counts.get(response.reason, 0) + 1
            protocol_errors += int(response.reason in {"protocol", "bad_json"})
            if i == 0:
                rss_start = _rss_mb(client.process)
            if slot_id == 2:
                panel_latencies.append(sum(latencies[-3:]))
            child_max = max(child_max, _child_count(client.process) or 0)
            if i % 500 == 0:
                rss_samples.append({"i": i, "rss_mb": _rss_mb(client.process)})
        rss_end = _rss_mb(client.process)
    finally:
        client.close()
    ordered = sorted(latencies)
    panels = sorted(panel_latencies)
    p95 = ordered[max(0, int(len(ordered) * 0.95) - 1)]
    panel_p95 = panels[max(0, int(len(panels) * 0.95) - 1)]
    report = {
        "requests": args.requests,
        "warmup_s": round(warmup_s, 2),
        "elapsed_total_s": round(time.perf_counter() - started, 3),
        "single_slot_p50_ms": round(ordered[len(ordered) // 2], 3),
        "single_slot_p95_ms": round(p95, 3),
        "three_slot_panels": len(panel_latencies),
        "three_slot_p95_ms": round(panel_p95, 3),
        "unavailable": unavailable,
        "unavailable_reasons": reason_counts,
        "protocol_errors": protocol_errors,
        "worker_restarts": client._crashes,
        "rss_samples": rss_samples,
        "rss_start_mb": None if rss_start is None else round(rss_start, 2),
        "rss_end_mb": None if rss_end is None else round(rss_end, 2),
        "rss_delta_mb": None if rss_start is None or rss_end is None else round(rss_end - rss_start, 2),
        "max_child_processes": child_max,
        "child_clean_exit": client.process is None or client.process.poll() is not None,
        "cache_panel_bound": len(client._cache) <= client._max_cache_panels,
        "model_load_ms": round(client._load_ms, 1) if client._load_ms else None,
        "model_validated": bool(client._model_validated),
        "model_dir": str(args.model_dir),
        "pass": protocol_errors == 0 and child_max <= 1 and panel_p95 <= 400,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
