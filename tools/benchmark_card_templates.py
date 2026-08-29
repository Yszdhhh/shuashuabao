#!/usr/bin/env python3
"""Benchmark approved bond-card templates on annotated real captures.

This is an evidence tool, not a production matcher change.  It evaluates the
same small card crops with a threshold curve, separates approved positives
from unknown-card hard negatives, and records blank/idle false fires.  The
OCR result is included only as a reference because it is a different corpus
and task unit.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "fixtures" / "card_template_assertions" / "templates_index.json"
CARDS_DIR = ROOT / "assets" / "Images" / "cards"
DEFAULT_OUTPUT = ROOT / "docs" / "distillation" / "CARD_TEMPLATE_BENCHMARK.json"
DEFAULT_OCR_REFERENCE = ROOT / "docs" / "distillation" / "VISION_OCR_BENCHMARK.json"

# Slots are title bands, expressed as frame-relative x intervals.  The three
# and four-card layouts are the two layouts present in the captured evidence.
CASES = (
    {
        "frame": "fixtures/card_template_assertions/positives/bond_choice_3.png",
        "slot_count": 3,
        "slots": [
            {"observed_label": "祝福", "expected_template": "zhufu"},
            {"observed_label": "祝福", "expected_template": "zhufu"},
            {"observed_label": "祝福", "expected_template": "zhufu"},
        ],
    },
    {
        "frame": "fixtures/card_template_assertions/positives/bond_choice_4_20260829.jpg",
        "slot_count": 4,
        "slots": [
            {"observed_label": "乱世三国", "expected_template": None},
            {"observed_label": "刀刀", "expected_template": None},
            {"observed_label": "挑战", "expected_template": "tz"},
            {"observed_label": "暴击", "expected_template": "baoji"},
        ],
    },
    {
        "frame": "fixtures/card_template_assertions/positives/bond_choice_4_jingji_20260829.jpg",
        "slot_count": 4,
        "slots": [
            {"observed_label": "经济", "expected_template": "jj"},
            {"observed_label": "刀刀", "expected_template": None},
            {"observed_label": "藏宝图(三)", "expected_template": None},
            {"observed_label": "刀刀", "expected_template": None},
        ],
    },
)

NEGATIVE_CASES = (
    {
        "frame": "fixtures/card_template_assertions/negatives/black_frame.png",
        "case_type": "blank_negative",
        "slot_count": 4,
    },
    {
        "frame": "fixtures/card_template_assertions/negatives/idle_hud.png",
        "case_type": "idle_negative",
        "slot_count": 4,
    },
)


def _load_image(path: Path):
    import cv2

    if not path.is_file():
        raise FileNotFoundError(path)
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        raise ValueError(f"cannot decode image: {path}")
    return image


def _match_score(image: Any, template: Any) -> float:
    import cv2

    if image.shape[0] < template.shape[0] or image.shape[1] < template.shape[1]:
        return -1.0
    result = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
    return float(cv2.minMaxLoc(result)[1])


def _slot_crop(frame: Any, slot_index: int, slot_count: int) -> Any:
    height, width = frame.shape[:2]
    if slot_count == 3:
        intervals = ((0.23, 0.39), (0.415, 0.585), (0.61, 0.77))
    elif slot_count == 4:
        intervals = ((0.18, 0.33), (0.335, 0.485), (0.49, 0.64), (0.645, 0.80))
    else:
        raise ValueError(f"unsupported slot_count={slot_count}")
    x0, x1 = intervals[slot_index]
    y0, y1 = 0.14, 0.31
    return frame[round(height * y0):round(height * y1), round(width * x0):round(width * x1)]


def _rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def _git_head() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, encoding="utf-8"
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _reference_ocr(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"status": "not_available", "reason": f"missing reference: {_rel(path)}"}
    report = json.loads(path.read_text(encoding="utf-8"))
    bond = ((report.get("metrics") or {}).get("current_6_variant") or {}).get("by_scene", {}).get("bond_choice", {})
    return {
        "status": "REFERENCE_ONLY_NOT_COMPARABLE",
        "source": _rel(path),
        "reason": "OCR uses 54 labeled title crops; template evidence uses annotated frame slots and 39 approved templates",
        "current_6_variant_bond_reference": {
            key: bond.get(key)
            for key in ("samples", "top1", "precision", "recall", "fp", "fn", "unmatched")
            if key in bond
        },
        "negative_panel_false_positive": report.get("negative_panel_false_positive"),
    }


def benchmark(output: Path, operating_threshold: float = 0.82) -> dict[str, Any]:
    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    codes = list(index.get("shortcodes") or [])
    if not codes:
        raise ValueError("templates_index has no shortcodes")
    templates = {code: _load_image(CARDS_DIR / f"{code}.png") for code in codes}

    scores: list[dict[str, Any]] = []
    positive_pairs: list[dict[str, Any]] = []
    similar_glyphs: list[dict[str, Any]] = []
    for case in CASES:
        frame_path = ROOT / case["frame"]
        frame = _load_image(frame_path)
        for slot_index, slot in enumerate(case["slots"]):
            crop = _slot_crop(frame, slot_index, int(case["slot_count"]))
            expected = slot.get("expected_template")
            if expected is not None and expected not in templates:
                raise ValueError(f"unknown expected template {expected!r} in {case['frame']}")
            slot_scores: list[tuple[str, float]] = []
            for code, template in templates.items():
                score = _match_score(crop, template)
                if expected == code:
                    case_type = "positive"
                else:
                    case_type = "hard_negative"
                row = {
                    "frame": case["frame"],
                    "slot": slot_index,
                    "observed_label": slot.get("observed_label"),
                    "expected_template": expected,
                    "template": code,
                    "case_type": case_type,
                    "score": round(score, 6),
                }
                scores.append(row)
                slot_scores.append((code, score))
                if case_type == "positive":
                    positive_pairs.append(row)
            if expected is not None:
                similar_glyphs.append(
                    {
                        "frame": case["frame"],
                        "slot": slot_index,
                        "expected_template": expected,
                        "observed_label": slot.get("observed_label"),
                        "top_non_target": [
                            {"template": code, "score": round(score, 6)}
                            for code, score in sorted(
                                (item for item in slot_scores if item[0] != expected),
                                key=lambda item: item[1],
                                reverse=True,
                            )[:3]
                        ],
                    }
                )

    for case in NEGATIVE_CASES:
        frame_path = ROOT / case["frame"]
        frame = _load_image(frame_path)
        for slot_index in range(int(case["slot_count"])):
            crop = _slot_crop(frame, slot_index, int(case["slot_count"]))
            for code, template in templates.items():
                scores.append(
                    {
                        "frame": case["frame"],
                        "slot": slot_index,
                        "observed_label": None,
                        "expected_template": None,
                        "template": code,
                        "case_type": case["case_type"],
                        "score": round(_match_score(crop, template), 6),
                    }
                )

    def rows(case_type: str) -> list[dict[str, Any]]:
        return [row for row in scores if row["case_type"] == case_type]

    def rate(items: list[dict[str, Any]], threshold: float) -> dict[str, Any]:
        hits = sum(float(row["score"]) >= threshold for row in items)
        return {"count": len(items), "hits": hits, "rate": hits / len(items) if items else None}

    thresholds = [round(0.50 + index * 0.01, 2) for index in range(46)]
    positive = rows("positive")
    hard_negative = rows("hard_negative")
    blank = rows("blank_negative")
    idle = rows("idle_negative")
    curve = [
        {
            "threshold": threshold,
            "positive_recall": rate(positive, threshold),
            "hard_negative_fp": rate(hard_negative, threshold),
            "blank_fp": rate(blank, threshold),
            "idle_fp": rate(idle, threshold),
        }
        for threshold in thresholds
    ]
    at_operating = next(item for item in curve if item["threshold"] == round(operating_threshold, 2))

    report = {
        "schema_version": 1,
        "status": "COMPLETED",
        "repo_head": _git_head(),
        "evidence": {
            "cases": [case["frame"] for case in CASES],
            "negative_cases": [case["frame"] for case in NEGATIVE_CASES],
            "slot_crop": {"x_layouts": {"3": "0.23/0.39, 0.415/0.585, 0.61/0.77", "4": "0.18/0.33, 0.335/0.485, 0.49/0.64, 0.645/0.80"}, "y": "0.14/0.31"},
            "annotation_note": "expected_template=null means the observed card has no approved runtime template; it is a hard negative for the current inventory, not a claim that the card is semantically negative",
        },
        "inventory": {"count": len(codes), "shortcodes": codes, "index": _rel(INDEX_PATH)},
        "thresholds": {
            "operating": operating_threshold,
            "curve_start": 0.50,
            "curve_end": 0.95,
            "approved_positive_min": index.get("thresholds", {}).get("positive_min"),
            "approved_negative_max": index.get("thresholds", {}).get("negative_max"),
            "operating_result": at_operating,
        },
        "counts": {
            "positive_pairs": len(positive),
            "hard_negative_pairs": len(hard_negative),
            "blank_negative_pairs": len(blank),
            "idle_negative_pairs": len(idle),
        },
        "curve": curve,
        "similar_glyphs": similar_glyphs,
        "scores": scores,
        "ocr_fallback_reference": _reference_ocr(DEFAULT_OCR_REFERENCE),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--operating-threshold", type=float, default=0.82)
    args = parser.parse_args(argv)
    report = benchmark(args.json_out, args.operating_threshold)
    print(json.dumps({"status": report["status"], "json": str(args.json_out.resolve()), "threshold": report["thresholds"]["operating_result"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
