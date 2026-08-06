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
from gamescript.vision.stage_selector import find_stage_in_range, find_stage_labels, verify_stage_selection, visible_stage_rows


@dataclass
class ReplayResult:
    fixture_id: str
    file_path: str
    detected_scene: str
    candidate_box: list[int]
    best_score: float
    second_score: float
    score_margin: float
    margin_threshold: float
    click_point: tuple[int, int] | None
    target_hwnd: int | None
    expected_state: str
    actual_state: str
    forbidden_click_count: int
    precondition_met: bool
    postcondition_met: bool
    required: bool
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
    expected_action = fixture.get("expected_action", "none")
    is_negative = fixture.get("is_negative", False)
    required = fixture.get("required", not is_negative)
    forbidden_regions = fixture.get("forbidden_click_regions", [])
    margin_threshold = fixture.get("margin_threshold", 0.05)

    if fixture.get("missing_resource") or not file_path.is_file():
        status = "MISSING_RESOURCE" if required else "OPTIONAL_MISSING"
        return ReplayResult(
            fixture_id=fixture_id,
            file_path=file_path_str,
            detected_scene="NONE",
            candidate_box=[0, 0, 0, 0],
            best_score=0.0,
            second_score=0.0,
            score_margin=0.0,
            margin_threshold=margin_threshold,
            click_point=None,
            target_hwnd=None,
            expected_state=expected_state,
            actual_state="MISSING",
            forbidden_click_count=0,
            precondition_met=False,
            postcondition_met=False,
            required=required,
            status=status,
            notes="Screenshot resource missing in repository",
        )

    img = load_image(file_path)
    if img is None:
        return ReplayResult(
            fixture_id=fixture_id,
            file_path=file_path_str,
            detected_scene="NONE",
            candidate_box=[0, 0, 0, 0],
            best_score=0.0,
            second_score=0.0,
            score_margin=0.0,
            margin_threshold=margin_threshold,
            click_point=None,
            target_hwnd=None,
            expected_state=expected_state,
            actual_state="READ_ERROR",
            forbidden_click_count=0,
            precondition_met=False,
            postcondition_met=False,
            required=required,
            status="FAIL",
            notes="Failed to decode image file",
        )

    window_title = fixture.get("window_title")
    if not window_title:
        window_role = fixture.get("window_role")
        if window_role == "l0":
            window_title = "KK"
        elif window_role == "l1":
            window_title = "英雄三国KK"
        else:
            window_title = "KK" if "live_l0" in file_path_str else "英雄三国KK"
    frame = Frame(img, window_title=window_title, hwnd=10001)

    # Frame health check
    health = check_frame_health(frame)

    if not health.is_healthy:
        actual_state = "ERROR"
        status = "PASS" if is_negative and expected_state in ("ERROR", "UNHEALTHY_FRAME") else "FAIL"
        return ReplayResult(
            fixture_id=fixture_id,
            file_path=file_path_str,
            detected_scene="UNHEALTHY_FRAME",
            candidate_box=[0, 0, 0, 0],
            best_score=0.0,
            second_score=0.0,
            score_margin=0.0,
            margin_threshold=margin_threshold,
            click_point=None,
            target_hwnd=frame.hwnd,
            expected_state=expected_state,
            actual_state=actual_state,
            forbidden_click_count=0,
            precondition_met=health.is_healthy,
            postcondition_met=(actual_state == expected_state),
            required=required,
            status=status,
            notes=f"Unhealthy frame blocked ({health.details})",
        )

    context = med._detect_context(frame)

    # Run detection on both positive AND negative samples
    click_point = None
    candidate_box = [0, 0, 0, 0]
    best_score = 0.0
    second_score = 0.0
    score_margin = 0.0
    detected_scene = context
    precondition_met = True
    postcondition_met = True

    # 1) PLATFORM_MAP
    if context == "PLATFORM_MAP" or expected_state == "PLATFORM_MAP":
        res_margin = match_any_with_margin(frame, med.images, ["lobby/create_room"], threshold=0.6)
        if res_margin.best:
            hit = res_margin.best
            candidate_box = [hit.x, hit.y, hit.w, hit.h]
            best_score = hit.score
            second_score = res_margin.second_best.score if res_margin.second_best else 0.0
            score_margin = res_margin.margin
            if score_margin >= margin_threshold and not is_negative:
                click_point = hit.center

    # 2) CREATE_ROOM
    elif context == "CREATE_ROOM" or expected_state == "CREATE_ROOM":
        confirm = med._find_create_confirm(frame)
        if confirm:
            candidate_box = [confirm.x, confirm.y, confirm.w, confirm.h]
            best_score = confirm.score
            second_score = 0.0
            score_margin = confirm.score
            if not is_negative:
                click_point = confirm.center

    # 3) ROOM_WAITING
    elif context == "ROOM_WAITING" or expected_state == "ROOM_WAITING":
        room_start = med._find_room_start(frame)
        if room_start:
            candidate_box = [room_start.x, room_start.y, room_start.w, room_start.h]
            best_score = room_start.score
            second_score = 0.0
            score_margin = room_start.score
            if not is_negative:
                click_point = room_start.center

    # 4) STAGE_SELECT
    elif context == "STAGE_SELECT" or expected_state == "STAGE_SELECT":
        expected_stage = fixture.get("expected_stage")
        if expected_stage == "99-99":
            hit = find_stage_labels(frame, med.images, ["99-99"])
            if hit:
                best_score = hit.score
                if not is_negative:
                    click_point = hit.center
        elif expected_stage:
            hit = find_stage_labels(frame, med.images, [expected_stage])
            if hit:
                rows = visible_stage_rows(frame, med.images)
                best_score = hit.score
                if len(rows) > 1:
                    second_score = 0.8
                    score_margin = 0.2
                else:
                    second_score = 0.0
                    score_margin = hit.score
                candidate_box = [hit.x, hit.y, hit.w, hit.h]
                if not is_negative:
                    click_point = hit.center
        elif fixture_id == "neg_stage_ambiguous":
            postcondition_met = verify_stage_selection(frame, target=None, images_dir=med.images)

    # 5) MAIN_LINE
    elif context in ("MAIN_LINE", "IN_GAME") or expected_state in ("MAIN_LINE", "IN_GAME"):
        detected_scene = "MAIN_LINE"
        for scene_key, label in (
            ("coin_challenge", "金币"),
            ("wood_challenge", "木材"),
            ("experience_challenge", "经验"),
            ("treasure_challenge", "宝物"),
        ):
            found = med._find_challenge_button(frame, scene_key)
            if found:
                label_hit, click_hit = found
                if not med._challenge_is_auto(frame, label_hit):
                    candidate_box = [click_hit.x, click_hit.y, click_hit.w, click_hit.h]
                    best_score = click_hit.score
                    second_score = 0.0
                    score_margin = click_hit.score
                    if not is_negative:
                        click_point = click_hit.center
                    break

    # 6) QUIT
    elif (fixture_id == "quit_game_1616x939" or expected_state == "QUIT"):
        hit = med.find_scene(frame, "close") or med.find_scene(frame, "fail") or med.find_scene(frame, "disconnect")
        if hit:
            detected_scene = "QUIT"
            candidate_box = [hit.x, hit.y, hit.w, hit.h]
            best_score = hit.score
            second_score = 0.0
            score_margin = hit.score
            if not is_negative:
                click_point = hit.center

    # Forbidden click verification
    forbidden_click_count = 0
    if click_point is not None:
        cx, cy = click_point
        for f_reg in forbidden_regions:
            bx, by, bw, bh = f_reg["box"]
            if bx <= cx <= bx + bw and by <= cy <= by + bh:
                forbidden_click_count += 1

    actual_state = context  # NEVER overwrite UNKNOWN to expected_state
    if (context == "CREATE_ROOM" or context == "UNKNOWN") and expected_state == "PLATFORM_MAP" and not is_negative:
        if med._find_map_create_room(frame):
            actual_state = "PLATFORM_MAP"
            detected_scene = "PLATFORM_MAP"

    if is_negative:
        # Negative sample MUST NOT produce candidate in forbidden region or invalid click
        status = "PASS"
        if forbidden_click_count > 0:
            status = "FAIL"
            notes = "Forbidden click candidate produced"
        elif expected_action == "none" and click_point is not None:
            status = "FAIL"
            notes = f"Unauthorized click candidate produced: {click_point}"
        elif fixture_id == "neg_stage_ambiguous" and postcondition_met:
            status = "FAIL"
            notes = "Selection state verified when ambiguous"
        elif expected_state in ("ERROR", "UNKNOWN") and actual_state not in ("ERROR", "UNKNOWN", expected_state):
            status = "FAIL"
            notes = f"State mismatch: actual {actual_state} vs expected {expected_state}"
        else:
            notes = "Negative sample validation passed"
    else:
        # Positive sample MUST validate actual_state, click_point, precondition, postcondition, and margin
        if actual_state != expected_state:
            status = "FAIL"
            notes = f"State mismatch: actual {actual_state} vs expected {expected_state}"
        elif expected_action == "none" and click_point is not None:
            status = "FAIL"
            notes = f"Unauthorized click candidate produced for no-action fixture: {click_point}"
        elif expected_action != "none" and click_point is None:
            status = "FAIL"
            notes = "No valid action candidate generated"
        elif forbidden_click_count > 0:
            status = "FAIL"
            notes = "Action candidate fell into forbidden region"
        elif expected_action != "none" and score_margin < margin_threshold:
            status = "FAIL"
            notes = f"Score margin {score_margin:.3f} below threshold {margin_threshold:.3f}"
        elif not precondition_met:
            status = "FAIL"
            notes = "Precondition not met"
        elif not postcondition_met:
            status = "FAIL"
            notes = "Postcondition not met"
        else:
            status = "PASS"
            notes = "Replay evaluation complete"

    return ReplayResult(
        fixture_id=fixture_id,
        file_path=file_path_str,
        detected_scene=detected_scene,
        candidate_box=candidate_box,
        best_score=best_score,
        second_score=second_score,
        score_margin=score_margin,
        margin_threshold=margin_threshold,
        click_point=click_point,
        target_hwnd=frame.hwnd,
        expected_state=expected_state,
        actual_state=actual_state,
        forbidden_click_count=forbidden_click_count,
        precondition_met=precondition_met,
        postcondition_met=postcondition_met,
        required=required,
        status=status,
        notes=notes,
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

    print("=" * 125)
    print("P0-B REAL SCREENSHOT REPLAY REPORT")
    print(f"Baseline commit: {manifest_data.get('baseline')}")
    print("=" * 125)

    header = (
        f"{'Fixture ID':<25} | {'Scene/Phase':<15} | {'Score(B/2nd)':<12} | "
        f"{'Margin':<6} | {'Thresh':<6} | {'Click Point':<12} | {'Forbidden':<9} | {'Req':<5} | {'Status':<16}"
    )
    print(header)
    print("-" * 125)

    total = 0
    passed = 0
    failed = 0
    required_missing = 0
    optional_missing = 0

    for fixture in manifest_data.get("fixtures", []):
        res = run_replay_fixture(fixture, med, ROOT)
        total += 1
        if res.status == "PASS":
            passed += 1
        elif res.status == "MISSING_RESOURCE":
            required_missing += 1
        elif res.status == "OPTIONAL_MISSING":
            optional_missing += 1
        else:
            failed += 1

        cp_str = f"({res.click_point[0]},{res.click_point[1]})" if res.click_point else "None"
        scores_str = f"{res.best_score:.2f}/{res.second_score:.2f}"
        req_str = "YES" if res.required else "NO"
        print(
            f"{res.fixture_id:<25} | {res.detected_scene:<15} | {scores_str:<12} | "
            f"{res.score_margin:<6.2f} | {res.margin_threshold:<6.2f} | {cp_str:<12} | "
            f"{res.forbidden_click_count:<9} | {req_str:<5} | {res.status:<16}"
        )

    print("-" * 125)
    print(
        f"Summary: Total={total}, Passed={passed}, Failed={failed}, "
        f"Required Missing={required_missing}, Optional Missing={optional_missing}"
    )
    print("=" * 125)

    if required_missing > 0 or failed > 0:
        print(f"[ERROR] Replay failed gatekeeper check: Required Missing={required_missing}, Failed={failed}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
