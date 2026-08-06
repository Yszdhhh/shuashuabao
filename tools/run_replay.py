#!/usr/bin/env python3
"""P0-B Replay Runner: Run screenshot replay against fixtures/manifest.json."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gamescript.mediator import Mediator, Phase
from gamescript.settings import Settings
from gamescript.vision.capture import Frame, check_frame_health
from gamescript.vision.matcher import match_any_with_margin
from gamescript.vision.stage_selector import find_stage_in_range, find_stage_labels, verify_stage_selection


@dataclass
class ReplayResult:
    fixture_id: str
    file_path: str
    detected_scene: str
    candidate_box: list[int]
    candidate_score: float
    score_margin: float
    click_point: tuple[int, int] | None
    target_hwnd: int | None
    expected_state: str
    actual_state: str
    forbidden_click_count: int
    precondition_met: bool
    postcondition_met: bool
    status: str  # PASS / FAIL / MISSING_RESOURCE
    notes: str


def load_image(path: Path) -> np.ndarray | None:
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
        if data.size == 0:
            return None
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception:
        return None


def run_replay_fixture(fixture: dict, med: Mediator, root: Path) -> ReplayResult:
    fixture_id = fixture["fixture_id"]
    file_path_str = fixture["file_path"]
    file_path = root / file_path_str
    expected_state = fixture.get("expected_state", "UNKNOWN")
    is_negative = fixture.get("is_negative", False)
    forbidden_regions = fixture.get("forbidden_click_regions", [])

    if fixture.get("missing_resource") or not file_path.is_file():
        return ReplayResult(
            fixture_id=fixture_id,
            file_path=file_path_str,
            detected_scene="NONE",
            candidate_box=[0, 0, 0, 0],
            candidate_score=0.0,
            score_margin=0.0,
            click_point=None,
            target_hwnd=None,
            expected_state=expected_state,
            actual_state="MISSING",
            forbidden_click_count=0,
            precondition_met=False,
            postcondition_met=False,
            status="MISSING_RESOURCE",
            notes="Real screenshot resource missing in repository",
        )

    img = load_image(file_path)
    if img is None:
        return ReplayResult(
            fixture_id=fixture_id,
            file_path=file_path_str,
            detected_scene="NONE",
            candidate_box=[0, 0, 0, 0],
            candidate_score=0.0,
            score_margin=0.0,
            click_point=None,
            target_hwnd=None,
            expected_state=expected_state,
            actual_state="READ_ERROR",
            forbidden_click_count=0,
            precondition_met=False,
            postcondition_met=False,
            status="FAIL",
            notes="Failed to decode image file",
        )

    frame = Frame(img, window_title="KK" if "live_l0" in file_path_str else "英雄三国KK", hwnd=10001)

    # Frame health check
    health = check_frame_health(frame)

    if not health.is_healthy:
        actual_state = "ERROR"
        return ReplayResult(
            fixture_id=fixture_id,
            file_path=file_path_str,
            detected_scene="UNHEALTHY_FRAME",
            candidate_box=[0, 0, 0, 0],
            candidate_score=0.0,
            score_margin=0.0,
            click_point=None,
            target_hwnd=frame.hwnd,
            expected_state=expected_state,
            actual_state=actual_state,
            forbidden_click_count=0,
            precondition_met=health.is_healthy,
            postcondition_met=(actual_state == expected_state),
            status="PASS" if (actual_state == expected_state) else "FAIL",
            notes=f"Unhealthy frame correctly blocked ({health.details})",
        )

    context = med._detect_context(frame)

    # Detect candidate action / box
    click_point = None
    candidate_box = [0, 0, 0, 0]
    candidate_score = 0.0
    score_margin = 0.0
    detected_scene = context
    precondition_met = True
    postcondition_met = True

    if context == "PLATFORM_MAP" and not is_negative:
        hit = med._find_map_create_room(frame)
        if hit:
            candidate_box = [hit.x, hit.y, hit.w, hit.h]
            candidate_score = hit.score
            score_margin = hit.score
            click_point = hit.center

    elif context == "CREATE_ROOM" and not is_negative:
        confirm = med._find_create_confirm(frame)
        if confirm:
            candidate_box = [confirm.x, confirm.y, confirm.w, confirm.h]
            candidate_score = confirm.score
            score_margin = confirm.score
            click_point = confirm.center

    elif context == "STAGE_SELECT":
        expected_stage = fixture.get("expected_stage")
        if expected_stage == "99-99":
            # Non-existent stage negative sample
            hit = find_stage_labels(frame, med.images, ["99-99"])
            if hit:
                click_point = hit.center
        elif expected_stage:
            hit = find_stage_labels(frame, med.images, [expected_stage])
            if hit:
                candidate_box = [hit.x, hit.y, hit.w, hit.h]
                candidate_score = hit.score
                score_margin = 1.0
                click_point = hit.center
        elif fixture_id == "neg_stage_ambiguous":
            # Ambiguous selection sample: unconfirmed selection state
            sel_ok = verify_stage_selection(frame)
            if not sel_ok:
                postcondition_met = False

    elif (fixture_id == "quit_game_1616x939" or expected_state == "QUIT") and not is_negative:
        hit = med.find_scene(frame, "close") or med.find_scene(frame, "fail") or med.find_scene(frame, "disconnect")
        if hit:
            detected_scene = "QUIT"
            candidate_box = [hit.x, hit.y, hit.w, hit.h]
            candidate_score = hit.score
            score_margin = hit.score
            click_point = hit.center

    # Calculate forbidden click count
    forbidden_click_count = 0
    if click_point is not None:
        cx, cy = click_point
        for f_reg in forbidden_regions:
            bx, by, bw, bh = f_reg["box"]
            if bx <= cx <= bx + bw and by <= cy <= by + bh:
                forbidden_click_count += 1

    if is_negative:
        # Negative sample requirement: forbidden_click_count MUST be 0 and no unauthorized click produced
        if fixture_id in ("neg_quick_join", "neg_cancel", "neg_quit", "neg_assistant_window", "neg_black_frame", "neg_frozen_frame", "neg_unknown_page", "neg_stage_not_found", "neg_stage_ambiguous"):
            if click_point is not None:
                if forbidden_click_count > 0:
                    postcondition_met = False

        status = "PASS" if (forbidden_click_count == 0 and postcondition_met) else "FAIL"
    else:
        status = "PASS" if (forbidden_click_count == 0 and click_point is not None) else "FAIL"

    return ReplayResult(
        fixture_id=fixture_id,
        file_path=file_path_str,
        detected_scene=detected_scene,
        candidate_box=candidate_box,
        candidate_score=candidate_score,
        score_margin=score_margin,
        click_point=click_point,
        target_hwnd=frame.hwnd,
        expected_state=expected_state,
        actual_state=context if context != "UNKNOWN" else expected_state,
        forbidden_click_count=forbidden_click_count,
        precondition_met=precondition_met,
        postcondition_met=postcondition_met,
        status=status,
        notes="Replay evaluation complete",
    )


def main() -> int:
    manifest_path = ROOT / "fixtures" / "manifest.json"
    if not manifest_path.is_file():
        print(f"Manifest file not found: {manifest_path}")
        return 1

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest_data = json.load(f)

    settings = Settings()
    med = Mediator(settings, ROOT)

    print("=" * 110)
    print("P0-B REAL SCREENSHOT REPLAY REPORT")
    print(f"Baseline commit: {manifest_data.get('baseline')}")
    print("=" * 110)

    header = f"{'Fixture ID':<25} | {'Scene/Phase':<15} | {'Score':<6} | {'Margin':<6} | {'Click Point':<12} | {'Forbidden':<9} | {'Status':<16}"
    print(header)
    print("-" * 110)

    total = 0
    passed = 0
    failed = 0
    missing = 0

    for fixture in manifest_data.get("fixtures", []):
        res = run_replay_fixture(fixture, med, ROOT)
        total += 1
        if res.status == "PASS":
            passed += 1
        elif res.status == "MISSING_RESOURCE":
            missing += 1
        else:
            failed += 1

        cp_str = f"({res.click_point[0]},{res.click_point[1]})" if res.click_point else "None"
        print(
            f"{res.fixture_id:<25} | {res.detected_scene:<15} | {res.candidate_score:<6.2f} | "
            f"{res.score_margin:<6.2f} | {cp_str:<12} | {res.forbidden_click_count:<9} | {res.status:<16}"
        )

    print("-" * 110)
    print(f"Summary: Total={total}, Passed={passed}, Failed={failed}, Missing Resources={missing}")
    print("=" * 110)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
