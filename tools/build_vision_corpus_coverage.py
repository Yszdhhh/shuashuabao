#!/usr/bin/env python3
"""Build a read-only coverage matrix from the local vision corpus.

This module deliberately imports only the standard library.  It reads existing
fixtures and distillation reports and writes evaluation artifacts; it does not
import or modify the production runtime.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
IMAGE_EXTENSIONS = frozenset({".bmp", ".gif", ".jpeg", ".jpg", ".png", ".webp"})
DEFAULT_JSON = ROOT / "docs" / "distillation" / "VISION_CORPUS_COVERAGE.json"
DEFAULT_MARKDOWN = ROOT / "docs" / "distillation" / "VISION_CORPUS_COVERAGE.md"


def _path(value: str | Path) -> Path:
    candidate = Path(value)
    return candidate if candidate.is_absolute() else ROOT / candidate


def _images(value: str | Path) -> list[Path]:
    candidate = _path(value)
    if candidate.is_file():
        return [candidate] if candidate.suffix.lower() in IMAGE_EXTENSIONS else []
    if not candidate.is_dir():
        return []
    return sorted(
        (item for item in candidate.rglob("*") if item.is_file() and item.suffix.lower() in IMAGE_EXTENSIONS),
        key=lambda item: str(item).casefold(),
    )


def _unique_images(values: Iterable[str | Path]) -> list[Path]:
    found: dict[str, Path] = {}
    for value in values:
        for image in _images(value):
            try:
                key = str(image.resolve()).casefold()
            except OSError:
                key = str(image.absolute()).casefold()
            found[key] = image
    return sorted(found.values(), key=lambda item: str(item).casefold())


def _named_images(root: str | Path, prefix: str) -> list[Path]:
    return [image for image in _images(root) if image.name.startswith(prefix)]


def _display(value: str | Path) -> str:
    candidate = _path(value)
    try:
        return candidate.resolve().relative_to(ROOT.resolve()).as_posix()
    except (OSError, ValueError):
        return str(candidate)


def scan_root(root_id: str, root: str | Path, classification: str, note: str = "") -> dict:
    """Return image count/bytes for one explicitly named corpus root."""

    candidate = _path(root)
    images = _images(candidate)
    total_bytes = 0
    for image in images:
        try:
            total_bytes += image.stat().st_size
        except OSError:
            pass
    return {
        "id": root_id,
        "path": _display(candidate),
        "classification": classification,
        "exists": candidate.exists(),
        "image_files": len(images),
        "bytes": total_bytes,
        "notes": note,
    }


def default_raw_roots() -> list[tuple[str, Path, str, str]]:
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    return [
        ("repo_fixtures", ROOT / "fixtures", "TEST_ONLY / DEV_ONLY", "Indexed fixtures and replay assets; not all are gold samples."),
        ("testjia", ROOT.parent / "测试夹", "DEV_ONLY", "Incident/test images outside the authoritative repository."),
        ("video_frames", ROOT.parent / "video_frames", "DEV_ONLY", "Locally extracted video frames when present."),
        ("codex_evidence", ROOT.parent / "_codex_skill_video_evidence", "DEV_ONLY", "Codex evidence images, not a production asset source."),
        ("video_archive", Path("G:/测试视频+抽帧"), "DEV_ONLY", "Raw sequential video frames; no deduplication claim."),
        ("appdata_shuabao", Path(local_appdata) / "ShuaBao", "DEV_ONLY", "Runtime incidents/traces; incident evidence only."),
        ("legacy_1_5_1", Path("G:/下载/1.5.1.zip/Images"), "DEV_REF", "Legacy reference images; not current-version approval."),
    ]


def _load_json(path: str | Path, default: object) -> object:
    candidate = _path(path)
    try:
        return json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _load_jsonl(path: str | Path) -> list[dict]:
    candidate = _path(path)
    rows: list[dict] = []
    try:
        lines = candidate.read_text(encoding="utf-8").splitlines()
    except OSError:
        return rows
    for line in lines:
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _evidence(
    units: int,
    paths: Iterable[str | Path] = (),
    *,
    source_labels: Iterable[str] = (),
    unique_images: int | None = None,
    note: str = "",
) -> dict:
    image_count = len(_unique_images(paths)) if unique_images is None else unique_images
    labels = list(source_labels) or [_display(value) for value in paths]
    return {
        "units": units,
        "unique_images": image_count,
        "sources": labels,
        "note": note,
    }


def _sessions(real_ids: Iterable[str] = (), snapshot_ids: Iterable[str] = ()) -> dict:
    real = list(real_ids)
    snapshots = list(snapshot_ids)
    return {
        "real_capture_sessions": len(real),
        "real_capture_ids": real,
        "snapshot_collections": snapshots,
    }


def _component(status: str, evidence: Iterable[str]) -> dict:
    return {"status": status, "evidence": list(evidence)}


def _row(
    scene_id: str,
    layer: str,
    business_scenario: str,
    positive: dict,
    negative: dict,
    hard_negative: dict,
    sessions: dict,
    roi_or_parameters: dict,
    algorithm: dict,
    kpi: dict,
    compression_status: str,
    raw_material_disposition: str,
    gap: str,
) -> dict:
    return {
        "scene_id": scene_id,
        "layer": layer,
        "business_scenario": business_scenario,
        "positive": positive,
        "negative": negative,
        "hard_negative": hard_negative,
        "sessions": sessions,
        "roi_or_parameters": roi_or_parameters,
        "algorithm": algorithm,
        "kpi": kpi,
        "compression_status": compression_status,
        "raw_material_disposition": raw_material_disposition,
        "gap": gap,
    }


def _fixture_entries() -> list[dict]:
    data = _load_json("fixtures/manifest.json", {})
    return data.get("fixtures", []) if isinstance(data, dict) else []


def _fixture_evidence(
    *,
    targets: Iterable[str] = (),
    prefixes: Iterable[str] = (),
    is_negative: bool | None = None,
) -> dict:
    target_set = set(targets)
    prefix_tuple = tuple(prefixes)
    selected: list[dict] = []
    for entry in _fixture_entries():
        target = str(entry.get("target_scene", ""))
        if target_set and target not in target_set and not any(target.startswith(prefix) for prefix in prefix_tuple):
            continue
        if is_negative is not None and bool(entry.get("is_negative", False)) != is_negative:
            continue
        selected.append(entry)
    paths = [_path(str(entry.get("file_path", ""))) for entry in selected]
    existing = [path for path in paths if _images(path)]
    return _evidence(
        len(existing),
        existing,
        source_labels=["fixtures/manifest.json"],
        note=f"{len(selected) - len(existing)} manifest entries have no readable image file." if len(selected) != len(existing) else "",
    )


def _eval_data() -> tuple[dict, list[dict]]:
    rows = _load_jsonl("docs/distillation/VISION_EVAL_MANIFEST.jsonl")
    meta = rows[0].get("_manifest", {}) if rows and "_manifest" in rows[0] else {}
    return (meta if isinstance(meta, dict) else {}, [row for row in rows if "_manifest" not in row])


def _choice_evidence(scene: str, eval_rows: list[dict]) -> dict:
    selected = [row for row in eval_rows if row.get("scene") == scene]
    paths = [_path(str(row.get("corpus_root", ""))) / str(row.get("source_crop", "")) for row in selected]
    return _evidence(
        len(selected),
        paths,
        source_labels=["docs/distillation/VISION_EVAL_MANIFEST.jsonl", "fixtures/ocr_choices"],
        note="Title-crop units; unique image count is hash/path deduplicated within this scene.",
    )


def _longrun_data() -> tuple[dict, dict]:
    trace = _load_json("fixtures/longtest_20260814/trace_aligned.json", {})
    decisions = _load_json("fixtures/longtest_20260814/choice_decisions.json", {})
    return (
        trace if isinstance(trace, dict) else {},
        decisions if isinstance(decisions, dict) else {},
    )


def build_coverage(raw_roots: Iterable[tuple[str, str | Path, str, str]] | None = None) -> dict:
    """Build the matrix from current files without touching runtime/config."""

    roots = list(raw_roots) if raw_roots is not None else default_raw_roots()
    root_records = [scan_root(*root) for root in roots]
    eval_meta, eval_rows = _eval_data()
    trace, decisions = _longrun_data()
    trace_counts = trace.get("counts", {}) if isinstance(trace.get("counts", {}), dict) else {}
    runs = trace.get("runs", []) if isinstance(trace.get("runs", []), list) else []
    decision_summary = decisions.get("summary", {}) if isinstance(decisions.get("summary", {}), dict) else {}

    common_negative = _evidence(
        55,
        ["fixtures/ocr_choices/negatives"],
        source_labels=["fixtures/ocr_choices/negatives"],
        note="Shared explicit non-choice pool; it is not a scene-specific confusion set for every choice family.",
    )
    matrix: list[dict] = []

    for scene, label in (("skill_choice", "技能选择"), ("bond_choice", "羁绊选择"), ("treasure_choice", "宝物选择")):
        hard = _evidence(0, source_labels=["未建立 scene-specific hard-negative set"], note="缺少该场景独立、带期望 no-action 的 hard-negative 标注。")
        algorithm_evidence = ["docs/distillation/VISION_OCR_BENCHMARK.json", "existing choice OCR implementation (reference only)"]
        if scene == "bond_choice":
            hard = _evidence(
                423,
                ["fixtures/card_template_assertions/positives"],
                source_labels=["docs/distillation/CARD_TEMPLATE_BENCHMARK.json"],
                unique_images=6,
                note="Template pair units; 6 positive frames are compared against 423 hard-negative pairs.",
            )
            algorithm_evidence.append("docs/distillation/CARD_TEMPLATE_BENCHMARK.json")
        elif scene == "treasure_choice":
            hard = _evidence(
                10,
                _named_images("fixtures/treasure_negative", "panel_"),
                source_labels=["fixtures/treasure_negative"],
                note="Ten full-panel negative observations across six named negative cards; descriptions are semantic evidence, not approved templates.",
            )
        matrix.append(
            _row(
                scene,
                "L1/perception+decision",
                label,
                _choice_evidence(scene, eval_rows),
                common_negative,
                hard,
                _sessions(eval_meta.get("session_counts", {}).keys(), ["fixtures/ocr_choices"]),
                _component("PRESENT", ["VISION_EVAL_MANIFEST.json: source_crop + roi + hash", "current six-variant OCR evaluation"]),
                _component("PRESENT", algorithm_evidence),
                _component("PRESENT", ["VISION_OCR_BENCHMARK.json", "CARD_TEMPLATE_BENCHMARK.json (bond/template scope)"]),
                "COMPRESSED",
                "COMPRESSED",
                "当前 KPI 不是全业务闭环证明；需继续补齐场景级 no-action/hard-negative 和多分辨率样本。",
            )
        )

    matrix.extend(
        [
            _row(
                "l0_platform_room_create",
                "L0/platform",
                "地图页→创建房间→确认",
                _fixture_evidence(targets=("map_create_room", "create_room_confirm"), is_negative=False),
                _fixture_evidence(targets=("quick_join", "cancel"), is_negative=True),
                _evidence(
                    2,
                    ["fixtures/lobby_hitch_20260814/popup_level_unmet.png", "fixtures/lobby_hitch_20260814/popup_password.png"],
                    source_labels=["fixtures/lobby_hitch_20260814/INDEX.json"],
                    note="Modal/room-entry confusions; no claim of successful join.",
                ),
                _sessions(["live_e2e_20260807"], ["fixtures/replay"]),
                _component("PRESENT", ["fixtures/manifest.json", "config/scenes.json existing room/create ROIs"]),
                _component("PARTIAL", ["existing template probes in Stage 2A evidence"]),
                _component("PARTIAL", ["release gate scene/template checks", "no reliable end-to-end join KPI"]),
                "PARTIAL",
                "COMPRESSED",
                "创建/确认证据可定位；大厅真实点击成功率、取消/密码/等级弹窗的动作等价性仍未形成稳定 KPI。",
            ),
            _row(
                "l0_room_list_join_ready",
                "L0/platform",
                "房间列表筛选→识别可加入房→准备/等待",
                _evidence(
                    5,
                    [
                        "fixtures/lobby_hitch_20260814/list_empty_search_t000.png",
                        "fixtures/lobby_hitch_20260814/list_search3_joinable_t038.png",
                        "fixtures/lobby_hitch_20260814/kk_room_ready_btn_t040.png",
                        "fixtures/lobby_hitch_detail_20260814/t0000.00.png",
                        "fixtures/lobby_hitch_detail_20260814/t0092.00.png",
                    ],
                    source_labels=["fixtures/lobby_hitch_20260814/INDEX.json", "fixtures/lobby_hitch_detail_20260814/README.md"],
                    note="Five representative positive states, while the detailed video contributes 20 client crops as research frames.",
                ),
                _evidence(3, source_labels=["fixtures/lobby_hitch_20260814/README.md"], note="Create/quick-join/quick-match were explicitly not clicked in the capture."),
                _evidence(
                    5,
                    [
                        "fixtures/lobby_hitch_20260814/list_search4_all_ingame_t036.png",
                        "fixtures/lobby_hitch_detail_20260814/t0046.00.png",
                        "fixtures/lobby_hitch_20260814/kk_room_cancel_ready_t041.png",
                    ],
                    source_labels=["fixtures/lobby_hitch_20260814/INDEX.json", "fixtures/lobby_hitch_detail_20260814/README.md"],
                    note="Visually confusable full/locked/guest-ready states; not yet an audited confusion benchmark.",
                ),
                _sessions(["lobby_hitch_20260814", "lobby_hitch_detail_20260814"]),
                _component("PARTIAL", ["client crop 203,84 / 1600x900", "existing room/list template probes"]),
                _component("PARTIAL", ["template matching evidence only; no join-success action replay"]),
                _component("MISSING", ["no reliable join→ready→start KPI"]),
                "PARTIAL",
                "RESEARCH_ONLY",
                "有真实录像代表帧，但无法证明蹭车加入成功；列表行、房间满、密码/锁标和准备态仍需成对标注。",
            ),
            _row(
                "l0_room_waiting_ready_start",
                "L0/platform",
                "房间等待/准备态→开始倒计时",
                _evidence(1, ["fixtures/replay/room_waiting_host.png"], source_labels=["fixtures/replay/room_waiting_host.png"]),
                _evidence(0, source_labels=["未建立独立 negative"]),
                _evidence(
                    2,
                    ["fixtures/lobby_hitch_20260814/kk_room_ready_btn_t040.png", "fixtures/lobby_hitch_20260814/kk_room_cancel_ready_t041.png"],
                    source_labels=["fixtures/lobby_hitch_20260814/INDEX.json"],
                    note="Guest-ready/cancel-ready are dangerous room_start confusions; current template probe is below approved threshold for some states.",
                ),
                _sessions(["live_e2e_20260807", "lobby_hitch_detail_20260814"]),
                _component("PARTIAL", ["room_waiting_host replay asset", "room_start template threshold evidence"]),
                _component("PARTIAL", ["no full state/action sequence benchmark"]),
                _component("MISSING", ["no stable false-start/ready-state KPI"]),
                "PARTIAL",
                "RESEARCH_ONLY",
                "等待、客人准备和房主开始三态尚未形成可安全放行的完整正负样本闭环。",
            ),
            _row(
                "l0_stage_select_start",
                "L0/platform",
                "选关/难度/挑战→开始主线",
                _fixture_evidence(
                    targets=("stage_target_1-10",),
                    is_negative=False,
                ),
                _evidence(
                    2,
                    ["fixtures/scenarios/stage_starting_env_hud", "fixtures/scenarios/ticket_zero_archaeology/frames"],
                    source_labels=["fixtures/scenarios/", "fixtures/manifest.json"],
                    note="Some are transition/archaeology evidence, not clean no-action labels.",
                ),
                _evidence(0, source_labels=["未建立独立 hard-negative"]),
                _sessions(["lobby_hitch_detail_20260814"], ["reborn_wow_screens_20260806"]),
                _component("PARTIAL", ["stage target coordinates/scene templates", "stage_select_20260814/ representative frame"]),
                _component("PARTIAL", ["frozen stage-select scroll replay PASS"]),
                _component("PARTIAL", ["no reliable ticket-zero / wrong-stage action KPI"]),
                "PARTIAL",
                "RESEARCH_ONLY",
                "目标关卡样本存在；ticket 0/120 与挑战票据仍是 XFAIL/CAVEAT，不能当作真实修复证据。",
            ),
            _row(
                "l0_hero_setup",
                "L0/platform",
                "英雄选择/属性/等级/开始",
                _evidence(1, ["fixtures/hero_modal_20260812_180825/client_1600x900.png"], source_labels=["fixtures/hero_modal_20260812_180825"]),
                _evidence(0, source_labels=["未建立独立 negative"]),
                _evidence(0, source_labels=["54 ROI/level/card/strip crops are state variations, not validated hard negatives"]),
                _sessions(["hero_modal_20260812_180825"]),
                _component("PARTIAL", ["client_1600x900 + 54 ROI/state crops"]),
                _component("MISSING", ["no action-level detector/selector benchmark"]),
                _component("MISSING", ["no complete target-level→Start KPI"]),
                "RESEARCH_ONLY",
                "RESEARCH_ONLY",
                "有素材蒸馏价值，但视频没有完整目标等级与 Start 闭环；不能压缩成生产参数。",
            ),
            _row(
                "l1_main_hud_challenges",
                "L1/in-game",
                "主 HUD/自动任务/四挑战可见与切换",
                _evidence(
                    2,
                    ["fixtures/replay/main_line_auto_off.png", "fixtures/replay/main_line_auto_on.png"],
                    source_labels=["fixtures/replay/", "fixtures/lobby_hitch_detail_20260814/README.md"],
                    note="Auto off/on representative states; the detailed capture says four challenges are visible, but has no per-challenge action labels.",
                ),
                _evidence(1, ["fixtures/replay/main_line_auto_on.png"], source_labels=["fixtures/replay/main_line_auto_on.png"], note="Auto-on is a state negative for an auto-off action, not a global negative frame."),
                _evidence(2, ["fixtures/ocr_choices/negatives/rec1_ingame_boss_20260809", "fixtures/ocr_choices/negatives/rec3_260810"], source_labels=["fixtures/ocr_choices/negatives"], note="Shared HUD/non-panel hard-negative candidates; not yet scene-paired."),
                _sessions(["lobby_hitch_detail_20260814", "longtest_20260814"], ["reborn_wow_screens_20260806"]),
                _component("PARTIAL", ["main_line_auto_on/off and challenge scene assets", "existing challenge ROIs"]),
                _component("PARTIAL", ["existing scene/template probes; no coverage-wide benchmark"]),
                _component("PARTIAL", ["long-run event counts; no per-action precision/recall"]),
                "PARTIAL",
                "RESEARCH_ONLY",
                "主线与挑战的正面代表帧有；需要自动开/关、四挑战、不可见/遮挡和误点击对照的动作级 KPI。",
            ),
            _row(
                "l1_long_run_session",
                "L1/liveness+telemetry",
                "长线程主循环、选择、刷新、羁绊与异常事件",
                _evidence(
                    len(runs),
                    ["fixtures/longtest_20260814/focus"],
                    source_labels=["fixtures/longtest_20260814/trace_aligned.json", "fixtures/longtest_20260814/focus"],
                    unique_images=len(_images("fixtures/longtest_20260814/focus")),
                    note="Two real runs are compressed to session telemetry; focus images remain diagnostic samples.",
                ),
                _evidence(0, source_labels=["未定义 session-level negative"]),
                _evidence(
                    int(trace_counts.get("incident", 0)) + int(trace_counts.get("room_stuck_candidate", 0)),
                    ["fixtures/longtest_20260814/focus"],
                    source_labels=["fixtures/longtest_20260814/trace_aligned.json"],
                    unique_images=len(_images("fixtures/longtest_20260814/focus")),
                    note="Incident/stuck-event units, not hard-negative image labels.",
                ),
                _sessions([str(run.get("label", "")) for run in runs if run.get("label")], ["longtest_20260814/focus"]),
                _component("PRESENT", ["trace_aligned.json: 2 runs / 2996.4s / 6525 ticks", "choice_decisions.json"]),
                _component("PARTIAL", ["event/decision telemetry; no new algorithm is introduced here"]),
                _component("PRESENT", [
                    f"n_decisions={decision_summary.get('n_decisions', 0)}",
                    f"n_refreshes={decision_summary.get('n_refreshes', 0)}",
                    f"n_window_loss_ticks={decision_summary.get('n_window_loss_ticks', 0)}",
                    "room_stuck_candidate=6; incident=90",
                ]),
                "PARTIAL",
                "COMPRESSED",
                "长跑已压缩为 session/KPI，但不能把 incident/focus 图直接当作覆盖完成或生产 detector KPI。",
            ),
            _row(
                "l1_dragonball",
                "L1/treasure semantics",
                "龙珠/进度型宝物识别与语义",
                _evidence(2, ["fixtures/ocr_choices/frames/dragonball_webp_20260807"], source_labels=["fixtures/ocr_choices/frames/dragonball_webp_20260807"]),
                _evidence(0, source_labels=["未建立龙珠 negative"]),
                _evidence(0, source_labels=["未建立龙珠 hard-negative"]),
                _sessions(["dragonball_webp_20260807"]),
                _component("PARTIAL", ["2 full-frame WebP + name/progress crops"]),
                _component("MISSING", ["no progress-state algorithm benchmark"]),
                _component("MISSING", ["no false-positive / progression KPI"]),
                "RESEARCH_ONLY",
                "RESEARCH_ONLY",
                "只有研究素材和语义线索；缺少不同进度、非龙珠相似卡、跨 session 的可靠样本。",
            ),
            _row(
                "l1_wood_secret_merchant",
                "L1/in-game",
                "木材挑战/秘境/黑市与掉落链",
                _evidence(
                    2,
                    ["fixtures/lobby_hitch_detail_20260814/t0250.00.png", "fixtures/lobby_hitch_detail_20260814/t0282.00.png"],
                    source_labels=["fixtures/lobby_hitch_detail_20260814/README.md"],
                    note="Representative black-market/drop frames only; no click/action annotation.",
                ),
                _evidence(0, source_labels=["未建立独立 negative"]),
                _evidence(0, source_labels=["未建立独立 hard-negative"]),
                _sessions(["lobby_hitch_detail_20260814"]),
                _component("PARTIAL", ["existing wood/challenge/merchant scene assets", "two representative full frames"]),
                _component("MISSING", ["no coverage-stage algorithm benchmark"]),
                _component("MISSING", ["no merchant/secret/wood action KPI"]),
                "RESEARCH_ONLY",
                "RESEARCH_ONLY",
                "原始帧能说明业务存在，但缺少完整出现/不出现/遮挡/点击后状态转移样本。",
            ),
            _row(
                "l1_post_victory_archive_boss",
                "L1/endgame",
                "胜利→归档/挑战 NPC/传家宝/大裂隙",
                _evidence(
                    5,
                    ["fixtures/replay/victory_continue.png", "fixtures/replay/archive_challenge_panel.png", "fixtures/replay/challenge_npc_hub.png", "fixtures/replay/heirloom_challenge_bosses.png", "fixtures/replay/great_rift_confirm.png"],
                    source_labels=["fixtures/replay/", "fixtures/reborn_wow/manifest.json"],
                    note="One catalog frame per state; not a complete endgame session.",
                ),
                _evidence(0, source_labels=["未建立 endgame no-action pool"]),
                _evidence(1, ["fixtures/live_postgame_20260808"], source_labels=["fixtures/live_postgame_20260808/README.md"], note="archive_panel is documented as a safe-zone/minimap marker, not the actual archive modal."),
                _sessions(["live_postgame_20260808", "lobby_hitch_detail_20260814"]),
                _component("PARTIAL", ["frozen replay/endgame catalog assets"]),
                _component("PARTIAL", ["archive/exit replay guards; current-version chain is incomplete"]),
                _component("PARTIAL", ["frozen archive/exit checks, but no full chain KPI"]),
                "PARTIAL",
                "RESEARCH_ONLY",
                "单帧目录与部分 frozen replay 已有；真正胜利后链路、误识别安全区、连续 session 仍不够。",
            ),
            _row(
                "recovery_fail_giveup",
                "Recovery",
                "失败/放弃面板的区分与收口",
                _evidence(3, ["fixtures/scenarios/fail_recovery_three_frames/frames"], source_labels=["fixtures/scenarios/fail_recovery_three_frames/"], note="fail/ok/close replay evidence; giveup baseline is a frozen replay outcome."),
                _evidence(0, source_labels=["未建立独立 recovery negative"]),
                _evidence(1, ["fixtures/scenarios/fail_recovery_three_frames/frames"], source_labels=["fixtures/scenarios/fail_recovery_three_frames/case.json"], note="Giveup-vs-fail distinction is represented by the replay guard, not a broad image benchmark."),
                _sessions(["fail_recovery_three_frames"]),
                _component("PRESENT", ["fail/giveup scene anchors and three-frame harness"]),
                _component("PRESENT", ["fail/giveup replay guard"]),
                _component("PRESENT", ["giveup_panel_not_fail PASS", "fail_panel_preempt PASS"]),
                "COMPRESSED",
                "COMPRESSED",
                "已压缩为场景 guard/replay KPI；仍不等于真实断线弹窗覆盖。",
            ),
            _row(
                "recovery_pause_overlay",
                "Recovery",
                "暂停覆盖层与恢复动作",
                _evidence(0, source_labels=["没有可审计的 current-version positive"]),
                _evidence(0, source_labels=["没有可审计的 current-version negative"]),
                _evidence(0, source_labels=["没有可审计的 current-version hard-negative"]),
                _sessions([], ["tests/performance/fixtures/manifest.json"]),
                _component("MISSING", ["仅有场景配置/历史测试入口"]),
                _component("MISSING", ["full current-version pause overlay 未建立"]),
                _component("MISSING", ["pause action KPI 未建立"]),
                "MISSING",
                "MISSING",
                "暂停 overlay 的现有测试回归与素材边界未完成，不能以配置条目替代实机证据。",
            ),
            _row(
                "recovery_disconnect",
                "Recovery",
                "断线/退出确认弹窗 fail-closed",
                _evidence(0, source_labels=["fixtures/missing_disconnect.png (missing)"]),
                _evidence(0, source_labels=["未建立 disconnect negative"]),
                _evidence(0, source_labels=["未建立 disconnect hard-negative"]),
                _sessions([], ["fixtures/manifest.json"]),
                _component("MISSING", ["disconnect modal positive fixture missing"]),
                _component("MISSING", ["no current-version visual algorithm evaluation"]),
                _component("BLOCKED", ["release gate: disconnect_modal_missing BLOCKED baseline-consistent"]),
                "MISSING",
                "MISSING",
                "保持 BLOCKED；不得用合成帧或相邻退出弹窗替代。",
            ),
            _row(
                "treasure_business_semantics",
                "L1/decision semantics",
                "必拿/负向宝物/描述负模式/刷新策略",
                _evidence(4, ["fixtures/treasure_must_take"], source_labels=["fixtures/treasure_must_take/README.md"]),
                _evidence(6, _named_images("fixtures/treasure_negative", "name_"), source_labels=["fixtures/treasure_negative/INDEX.json"], note="Six named negative semantic card classes."),
                _evidence(10, _named_images("fixtures/treasure_negative", "panel_"), source_labels=["fixtures/treasure_negative/INDEX.json"], note="Ten full-panel observations; not all are independent hard-negative labels."),
                _sessions([], ["fixtures/treasure_must_take", "fixtures/treasure_negative"]),
                _component("PARTIAL", ["name/description crops and business lists", "description/negative_patterns retained"]),
                _component("PRESENT", ["choice_policy semantic lists", "treasure description decision-equivalence replay"]),
                _component("PRESENT", ["12276 unavailable desc calls; paired replay mismatch_count=0"]),
                "PARTIAL",
                "COMPRESSED",
                "业务语义已保留并可评测；仍需把必拿/负向卡放回真实多布局 panel/session 做识别 KPI。",
            ),
            _row(
                "ur_attr_route_semantics",
                "L1/decision semantics",
                "UR 属性路线：智力/力量/敏捷",
                _evidence(9, ["fixtures/ur_attr_routes"], source_labels=["fixtures/ur_attr_routes/INDEX.json"], note="Nine semantic source images across three routes."),
                _evidence(0, source_labels=["未建立路线 negative"]),
                _evidence(0, source_labels=["未建立路线 hard-negative"]),
                _sessions([], ["fixtures/ur_attr_routes"]),
                _component("RESEARCH_ONLY", ["source.png semantic cards; no click-template ROI"]),
                _component("MISSING", ["no route recognition benchmark"]),
                _component("MISSING", ["no route precision/recall or outcome KPI"]),
                "RESEARCH_ONLY",
                "RESEARCH_ONLY",
                "当前只能支持业务知识蒸馏，不能支持视觉生产接入或路线成功率结论。",
            ),
        ]
    )

    report = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "repo": str(ROOT),
            "purpose": "Vision Corpus Coverage: asset distillation and evaluation only",
            "raw_file_observation": "Counts are current filesystem observations; no global deduplication or gold-quality claim.",
            "production_integration": "NOT_APPLIED",
            "forbidden_changes": ["fallback", "watchdog", "thread", "recovery_manager", "FSM", "runtime wiring"],
        },
        "raw_roots": root_records,
        "indexed_evaluation": {
            "vision_eval_samples": len(eval_rows),
            "vision_eval_sessions": int(eval_meta.get("counts", {}).get("sessions", 0)),
            "vision_eval_by_scene": {
                scene: sum(1 for row in eval_rows if row.get("scene") == scene)
                for scene in ("skill_choice", "bond_choice", "treasure_choice")
            },
            "ocr_treasure_description_calls": 12276,
            "ocr_treasure_description_status": "all unavailable",
            "treasure_decision_replay_mismatches": 0,
        },
        "matrix": matrix,
        "disposition": {
            "compressed": [
                "skill_choice / bond_choice / treasure_choice title-crop ROI + OCR/template KPI",
                "recovery_fail_giveup frozen replay guard and KPI",
                "treasure_business_semantics lists + decision-equivalence evidence",
                "longtest_20260814 two-session telemetry/KPI (not detector coverage)",
            ],
            "research_only": [
                "raw incident images and sequential video frames",
                "hero setup ROI/state crops",
                "dragonball, wood/secret/merchant representative frames",
                "treasure must-take and UR attribute route source images",
                "single-frame endgame catalog and live postgame safe-zone marker",
            ],
            "missing_or_unreliable": [
                "current-version disconnect modal positive",
                "current-version pause overlay positive/negative pair",
                "full lobby join→ready→start→return action sequence KPI",
                "ticket-zero challenge evidence",
                "complete hero setup target-level→Start loop",
                "scene-specific negative/hard-negative/session KPI for dragonball, wood, secret, merchant and endgame chain",
            ],
        },
    }
    return report


def _percent(value: int, total: int) -> str:
    return f"{(100.0 * value / total):.2f}%" if total else "—"


def render_markdown(report: dict) -> str:
    roots = report["raw_roots"]
    rows = report["matrix"]
    indexed = report["indexed_evaluation"]
    lines = [
        "# Vision Corpus Coverage（Stage 2 Coverage）",
        "",
        f"> 生成时间：`{report['generated_at_utc']}`。本报告只做本地素材蒸馏与评测盘点，不接生产；不引入 fallback/watchdog/thread/recovery manager/FSM。",
        "",
        "## 结论先行",
        "",
        f"当前可见原始图片文件为 `{sum(root['image_files'] for root in roots):,}` 个、`{sum(root['bytes'] for root in roots) / (1024 ** 3):.3f} GiB`；这是按明确目录的文件计数，不是去重后的样本数。已有选择类评测 `{indexed['vision_eval_samples']}` 个样本、`{indexed['vision_eval_sessions']}` 个 capture session；treasure description 的 `{indexed['ocr_treasure_description_calls']:,}` 次 unavailable 调用做过 decision-equivalence replay，mismatch 为 `{indexed['treasure_decision_replay_mismatches']}`。",
        "",
        "Coverage 阶段的生产边界是 `NOT_APPLIED`：本次产物只落在 `tools/`、`tests/`、`docs/distillation/`，不改 `src/`、不改 `config/`，也不把 Gray_2x、cards template、HSV、vision_profiles 接入生产。",
        "",
        "## Coverage matrix",
        "",
        "`units` 是评测/事件/语义单元；`unique_images` 是能定位到的去重文件数。两者可能不同：同一张截图可承担多个 slot/pair，事件也可能没有一一对应的图片。",
        "",
        "| 场景 | 正向 | 负向 | Hard-negative | 实机 session | ROI/参数 | 算法 | KPI | 结论 |",
        "|---|---:|---:|---:|---:|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            "| `{scene}` | {p} / {pi}图 | {n} / {ni}图 | {h} / {hi}图 | {s} | {roi} | {algo} | {kpi} | `{status}` |".format(
                scene=row["scene_id"],
                p=row["positive"]["units"],
                pi=row["positive"]["unique_images"],
                n=row["negative"]["units"],
                ni=row["negative"]["unique_images"],
                h=row["hard_negative"]["units"],
                hi=row["hard_negative"]["unique_images"],
                s=row["sessions"]["real_capture_sessions"],
                roi=row["roi_or_parameters"]["status"],
                algo=row["algorithm"]["status"],
                kpi=row["kpi"]["status"],
                status=row["compression_status"],
            )
        )
    lines += ["", "## 逐项 gap / 原始素材处置", ""]
    for row in rows:
        lines += [
            f"### `{row['scene_id']}` — {row['business_scenario']}",
            "",
            f"- 处置：`{row['raw_material_disposition']}`；{row['gap']}",
            f"- 正向来源：{'; '.join(row['positive']['sources']) or '—'}；负向来源：{'; '.join(row['negative']['sources']) or '—'}；hard-negative 来源：{'; '.join(row['hard_negative']['sources']) or '—'}。",
            f"- ROI/参数：`{row['roi_or_parameters']['status']}` — {'；'.join(row['roi_or_parameters']['evidence'])}。",
            f"- 算法：`{row['algorithm']['status']}` — {'；'.join(row['algorithm']['evidence'])}。KPI：`{row['kpi']['status']}` — {'；'.join(row['kpi']['evidence'])}。",
            "",
        ]
    lines += [
        "## 已成功压缩为 ROI / 算法参数 / KPI",
        "",
        "- 选择类：155 个 title-crop 样本已按 session、ROI、hash 和 train/tune/blind split 建索引；skill/bond/treasure 的 OCR KPI 已落盘。bond 的 template 评测另有 operating threshold `0.82`、6 positive、423 hard-negative pair、blank/idle 各 156 pair。",
        "- treasure description：12,276 次历史 unavailable 调用已被审计；关闭调用的 paired replay 对 SELECT/CLOSE/REFRESH/slot 决策 `mismatch_count=0`，但运行时调用仍保留，业务 `description`、`negative_patterns`、`negative_names` 仍保留。",
        "- fail/giveup：三帧 replay/harness 已压缩为场景 guard 与 KPI；`giveup_panel_not_fail` 和 `fail_panel_preempt` 已通过。",
        "- 长跑：两个真实 session 已压缩为 2,996.4 秒、6,525 ticks、选择/刷新/incident/stuck 计数；这属于 session telemetry，不是所有 detector 已验证。",
        "",
        "## 仍只有研发价值的截图",
        "",
        "- `G:/测试视频+抽帧` 的顺序帧、`%LOCALAPPDATA%/ShuaBao/incidents` 的 incident/panel 图、`测试夹` 与 `_codex_skill_video_evidence`：可用于追问题和选候选帧，未统一标注，不能当 gold corpus。",
        "- hero setup 的全屏/level/card/strip/plus ROI、dragonball 进度图、木材/秘境/黑市代表帧、treasure must-take、UR 属性路线 source.png：已保留业务语义或候选 ROI，但缺少 paired negative/hard-negative 与动作 KPI。",
        "- live postgame 的 `archive_panel` 已由 README 明确为 safe-zone/minimap marker，不是实际 archive modal；只能作为 hard-negative/研发证据。",
        "",
        "## 仍缺可靠素材的业务场景",
        "",
        *[f"- {item}" for item in report["disposition"]["missing_or_unreliable"]],
        "",
        "## 原始目录观察",
        "",
        "| 目录 | 分类 | 图片文件 | 大小 | 说明 |",
        "|---|---|---:|---:|---|",
    ]
    for root in roots:
        lines.append(
            f"| `{root['path']}` | `{root['classification']}` | {root['image_files']:,} | {root['bytes'] / (1024 ** 3):.3f} GiB | {root['notes']} |"
        )
    lines += [
        "",
        "## 边界与下一步",
        "",
        "- `disconnect_modal_missing` 继续 `BLOCKED`；没有实机素材就不以合成帧更新 baseline。",
        "- 本阶段不把任何 coverage 结论接入生产，不扩展 fallback/watchdog/FSM，不调整运行时路径。",
        "- 下一步应优先补齐每个缺口的真实 session paired positive/negative/hard-negative，再把算法评测写成可重复 replay；不是先增加 detector 层。",
        "",
    ]
    return "\n".join(lines)


def write_outputs(json_path: str | Path = DEFAULT_JSON, markdown_path: str | Path = DEFAULT_MARKDOWN) -> dict:
    report = build_coverage()
    json_target = _path(json_path)
    markdown_target = _path(markdown_path)
    json_target.parent.mkdir(parents=True, exist_ok=True)
    markdown_target.parent.mkdir(parents=True, exist_ok=True)
    json_target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_target.write_text(render_markdown(report), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-out", default=str(DEFAULT_JSON))
    parser.add_argument("--markdown-out", default=str(DEFAULT_MARKDOWN))
    args = parser.parse_args()
    report = write_outputs(args.json_out, args.markdown_out)
    print(json.dumps({
        "json": _display(args.json_out),
        "markdown": _display(args.markdown_out),
        "raw_image_files": sum(root["image_files"] for root in report["raw_roots"]),
        "eval_samples": report["indexed_evaluation"]["vision_eval_samples"],
        "matrix_rows": len(report["matrix"]),
        "production_integration": report["scope"]["production_integration"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
