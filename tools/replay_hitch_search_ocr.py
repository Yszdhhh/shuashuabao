"""Mandatory offline replay: real production OCR worker on the real incident frames.

The pytest suite replays *recorded* OCR text so it stays deterministic and
sidecar-free.  This script closes that gap by spawning the OCR worker through
``ProductionShadowClient`` — the same class, runtime resolution and model
directory the LIVE ``RuntimeMediator`` uses — and reading the 20260907
incident frames with it, so the tight content crop is proven against the real
model rather than against a stub.

It re-reads each frame twice:

* ``shipped``  — the fixed normalized band the released build used, which
  returned ``"a"`` on the real machine at 10:49:31.070;
* ``derived``  — the crop the fixed build computes from the stable locator.

Exit code is non-zero unless every case matches its expectation.  If the OCR
worker cannot start, this fails loudly — it never skips, xfails or reports a
pass it did not observe.

Usage:
    python tools/replay_hitch_search_ocr.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.lobby_hitch import has_prefix_evidence  # noqa: E402
from shuabao.mediator import Mediator  # noqa: E402
from shuabao.settings import Settings  # noqa: E402
from shuabao.vision.capture import Frame  # noqa: E402
from shuabao.vision.ocr_shadow.production import ProductionShadowClient  # noqa: E402

FIXTURES = ROOT / "fixtures" / "lobby_hitch_search_20260907"
LEGACY = ROOT / "fixtures" / "lobby_hitch_20260814"

# The exact band the released build asked for, from ocr_shadow.jsonl.
SHIPPED_BBOX = (1092, 245, 1292, 302)

# (label, fixture path, client left/top, prefix under test, must_confirm)
CASES = [
    ("t035 EMPTY", FIXTURES / "search_empty_t035.png", 559, 36, "4", False),
    ("t038 TYPED 4", FIXTURES / "search_typed4_t038.png", 559, 36, "4", True),
    ("t040 RESULTS 4", FIXTURES / "search_results4_t040.png", 559, 36, "4", True),
    ("20260814 EMPTY", LEGACY / "list_empty_search_t000.png", 203, 84, "4", False),
    ("20260814 TYPED 4", LEGACY / "list_search4_all_ingame_t036.png", 203, 84, "4", True),
    ("20260814 TYPED 3", LEGACY / "list_search3_joinable_t038.png", 203, 84, "3", True),
]


def _frame(path: Path, left: int, top: int) -> Frame:
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise SystemExit(f"BLOCKED: cannot read fixture {path}")
    return Frame(image, left=left, top=top, window_title="KK官方对战平台", hwnd=1, role="l0")


def main() -> int:
    med = Mediator(Settings(mode_id="lobby_hitch", hitch_stage_prefix="4"), ROOT)
    try:
        # Same client, runtime resolution and model directory as LIVE.
        client = ProductionShadowClient(
            repo_root=ROOT, timeout_ms=8000, startup_timeout_ms=120000
        )
    except Exception as exc:  # pragma: no cover - environment failure path
        print(f"BLOCKED: mandatory production OCR replay unavailable ({exc!r})")
        return 2

    rows: list[dict] = []
    failures: list[str] = []
    runtime: dict = {}
    try:
        # Force startup now so a dead runtime is reported as BLOCKED rather
        # than as a per-case OCR miss.
        client.shadow_predict(
            _frame(CASES[0][1], CASES[0][2], CASES[0][3]),
            "replay_warmup",
            {"slot_id": 0, "bbox": list(SHIPPED_BBOX), "kind": "text"},
            session="hitch_search_replay",
            panel_bbox=SHIPPED_BBOX,
        )
        runtime = {
            "client": type(client).__name__,
            "worker_command": [str(v) for v in (client.worker_command or [])],
            "python_executable": str(client.python_executable),
            "model_dir": str(client.model_dir),
            "repo_root": str(client.repo_root),
            "model_name": client.model_name,
            "model_hash": client.model_hash,
            "model_validated": client.model_validated,
            "is_available": client.is_available,
            "load_ms": round(float(client.load_ms), 1),
        }
        print("\n--- production OCR runtime identity ---")
        for key, value in runtime.items():
            print(f"  {key:<18}: {value}")
        if not client.is_available or not client.model_validated:
            failures.append(
                "BLOCKED: mandatory production OCR replay unavailable "
                f"(is_available={client.is_available} "
                f"model_validated={client.model_validated})"
            )
        for label, path, left, top, prefix, must_confirm in CASES:
            frame = _frame(path, left, top)
            med.invalidate_evidence("replay")
            icon = med.find_scene(frame, "lobby_search_icon")
            if icon is None:
                failures.append(f"{label}: stable locator not found")
                continue
            derived = med._hitch_search_content_bbox(frame, icon, prefix)

            for tag, bbox in (("shipped", SHIPPED_BBOX), ("derived", derived)):
                response = client.shadow_predict(
                    frame,
                    f"replay_{tag}",
                    {"slot_id": 0, "bbox": list(bbox), "kind": "text"},
                    session="hitch_search_replay",
                    panel_bbox=bbox,
                )
                if response.status != "ok":
                    failures.append(
                        f"BLOCKED: mandatory production OCR replay unavailable "
                        f"({label}/{tag}: status={response.status} reason={response.reason})"
                    )
                    continue
                raw = str(response.raw_text or "")
                confirmed = has_prefix_evidence(raw, prefix)
                rows.append({
                    "case": label,
                    "roi": tag,
                    "bbox": list(bbox),
                    "raw_text": raw,
                    "normalized_prefix_match": confirmed,
                    "rec_score": round(float(response.rec_score or 0.0), 4),
                    "expected_confirm": must_confirm if tag == "derived" else None,
                    "locator_score": round(float(icon.score), 4),
                })
                if tag == "derived" and confirmed is not must_confirm:
                    failures.append(
                        f"{label}: derived crop confirm={confirmed} "
                        f"expected={must_confirm} raw={raw!r}"
                    )
    finally:
        client.close()

    width = max(len(r["case"]) for r in rows) if rows else 10
    print()
    print(f"{'case':<{width}} {'roi':<8} {'bbox':<24} {'raw_text':<24} "
          f"{'score':>7} {'prefix':>7}")
    for r in rows:
        print(f"{r['case']:<{width}} {r['roi']:<8} {str(tuple(r['bbox'])):<24} "
              f"{r['raw_text']!r:<24} {r['rec_score']:7.4f} "
              f"{str(r['normalized_prefix_match']):>7}")

    out = ROOT / "artifacts" / "hitch_search_ocr_replay.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"runtime": runtime, "cases": rows}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\nwrote {out}")

    # The shipped band must still misread the incident frame; if it ever stops
    # doing so the fixtures no longer carry the defect they were taken for.
    incident = [r for r in rows if r["case"] == "t038 TYPED 4" and r["roi"] == "shipped"]
    if incident and incident[0]["normalized_prefix_match"]:
        failures.append("t038 shipped band no longer reproduces the incident misread")

    if failures:
        print("\nFAIL:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nPASS: production OCR confirms the derived crop on every case")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
