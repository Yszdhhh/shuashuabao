#!/usr/bin/env python3
"""Live Scenario Capture -> existing scenario replay cases.

This is a small adapter around the existing scenario harness used by
``run_frozen_replay.py``.  It does not implement game decisions: live capture
runs ``Mediator.tick()`` and target probe dispatches to the selected production
handler.  Captured screenshots are event driven
(first/state-change/action-before/action-after); it never writes an interval's
worth of screenshots to the bundle.

Examples::

    python tools/live_scenario_capture.py capture --target black_merchant \
        --out C:/tmp/shuabao-captures --duration 60 --generate
    python tools/live_scenario_capture.py probe --target inventory_item \
        --out C:/tmp/shuabao-probes --duration 15
    python tools/live_scenario_capture.py replay --bundle C:/tmp/.../bundle

``Natural E2E`` remains a separate live PASS.  A frozen replay PASS is only an
offline regression result and is recorded as such in the bundle metadata.
"""

from __future__ import annotations

import argparse
from collections import deque
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict, fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))

from shuabao.input.keyboard_mouse import ActionResult, InputExecutor  # noqa: E402
from shuabao.input.emergency_stop import EmergencyStopListener  # noqa: E402
from shuabao.loop_action import LoopAction  # noqa: E402
from shuabao.mediator import BUILD_ID, Mediator, Phase  # noqa: E402
from shuabao.player_profile import LiveLane, LiveLaneBusy  # noqa: E402
from shuabao.settings import Settings  # noqa: E402
from shuabao.stop_signal import StopSignal  # noqa: E402
from shuabao.vision.capture import Frame, capture  # noqa: E402
from test_scenario_replay import (  # noqa: E402
    ActionProbe,
    Case,
    ContextProbe,
    ExpectAction,
    FakeClock,
    FakeInputExecutor,
    FrameSpec,
    ReplayCaseLoader,
    ReplayFrameSource,
    ScenarioRunner,
    _INPUT_KIND,
)


TARGET_CONTRACT_FIELDS = (
    "start_condition",
    "production_entry",
    "expected_steps",
    "success_postcondition",
    "fail_condition",
    "blocked_condition",
    "max_probe_time_s",
    "natural_e2e_eligible",
    "bundle_replay",
)

# This is deliberately data, not another execution FSM.  A probe only calls
# the named existing Mediator method; these fields make its entry conditions
# and evidence bar visible before a live session starts.
TARGET_CONTRACTS: dict[str, dict[str, Any]] = {
    "black_merchant": {
        "handler": "_maybe_black_merchant",
        "call": "frame",
        "start_condition": "已在局内 HUD 停在黑商商品条附近；若五格为空但刷新控件可见，脚本先刷新，再在同一次遭遇中扫描并获取吞噬丹、木材或已识别的 2/5 折扣商品。",
        "production_entry": "Mediator._maybe_black_merchant(frame)",
        "expected_steps": (
            "DETECT", "SCAN", "REFRESH", "VERIFY_REFRESH", "TARGET_FOUND",
            "TAKE", "VERIFY_TAKE", "EXIT",
        ),
        "success_postcondition": "只有 BlackMerchant-swallow_pill、BlackMerchant-wood 或已识别折扣商品的现有业务后置验证完成才是 LIVE_PROBE_PASS；REFRESH_PASS 仅证明 VERIFY_REFRESH，绝不只以 click success 判定。",
        "fail_condition": "刷新/目标商品已识别但输入被拒绝、既有验证超时、画面/商品后置未变化，或生产 handler 进入 ERROR；刷新成功不能覆盖后续 TARGET_FOUND/TAKE 失败。",
        "blocked_condition": "capture 无效、黑商条/刷新控件未出现、吞噬丹前置不满足，或当前画面没有可安全识别的目标商品。",
        "max_probe_time_s": 25.0,
        "natural_e2e_eligible": "仅连续 mediator_tick 实机链、观察到上述业务后置状态、且无 FAIL/MANUAL_INTERVENTION bookmark 时仍有资格；probe 本身不算 Natural E2E。",
        "bundle_replay": "bundle 的事件帧经 ReplayCaseLoader 转为 schema-v1 case；由真实 Mediator.tick() + FakeInputExecutor 重放 baseline 和四个故障变体。",
        "runbook_manual": "把游戏停在黑商商品条附近；商品为空时保留刷新控件可见，并确保可购买木材/吞噬丹时资金与前置满足。",
        "runbook_hands_off": "命令启动后不要再点击商品条、刷新或背包区域。",
        "runbook_pass": "自动确认刷新后目标商品获取的业务后置状态才是 Live Probe PASS；p 只保存人工证据，刷新变化不是整链 PASS。",
        "runbook_manual_intervention": "生产链 FAIL 留证后，可人工处理弹窗并标记 MANUAL_INTERVENTION，继续采集后续场景。",
    },
    "inventory_item": {
        "handler": "_maybe_use_inventory_item",
        "call": "frame",
        "start_condition": "已在无中央面板、无黑商的局内 HUD；目标为右下背包吞噬丹，羁绊栏非空且 auto_devour_dan 已开启。",
        "production_entry": "Mediator._maybe_use_inventory_item(frame)",
        "expected_steps": (
            "DETECT_SLOT", "IDENTIFY", "USE", "VERIFY_CONSUMED", "VERIFY_NO_REPEAT",
        ),
        "success_postcondition": "仅现有 WAIT_DEVOUR_DAN verifier 确认吞噬丹消耗，且没有对同一物品重复发送输入；绝不以 click success 判定。",
        "fail_condition": "输入被拒绝、PendingAction 到期未确认、同一槽位无后置变化仍被重复使用，或生产 handler 进入 ERROR。",
        "blocked_condition": "capture 无效、黑商/中央面板抢占、目标物品或既有启用前置不满足。",
        "max_probe_time_s": 15.0,
        "natural_e2e_eligible": "仅连续 mediator_tick 实机链、消耗后置事实已观察到、且无 FAIL/MANUAL_INTERVENTION bookmark 时仍有资格；probe 本身不算 Natural E2E。",
        "bundle_replay": "bundle 记录动作前后帧与 PendingAction 收敛，再由现有 ReplayCaseLoader/FakeInputExecutor 生成并重放 case。",
        "runbook_manual": "把游戏停在无弹窗的局内 HUD，确保吞噬丹、非空羁绊栏和现有开关都已满足。",
        "runbook_hands_off": "命令启动后不要点击背包槽位、黑商或中央选卡面板。",
        "runbook_pass": "只有吞噬丹被既有 PendingAction verifier 自动确认消耗且没有重复点击，才是 Live Probe PASS；p 只留证。",
        "runbook_manual_intervention": "若目标被其他弹窗遮住或生产 FAIL，先标 FAIL；人工清理后标 MANUAL_INTERVENTION，再继续采集。",
    },
    "boss_challenge": {
        "handler": "_maybe_challenge_configured_boss",
        "call": "frame_now",
        "start_condition": "已打开 boss_entry 对应的 Boss 列表；现有 cjb_boss/sgzx_boss 中只保留本次要测的一个已配置 Boss。tqtz→SGZX 可作为同一既有 handler 的条件性路线采样。",
        "production_entry": "Mediator._maybe_challenge_configured_boss(frame, time.time())",
        "expected_steps": (
            "ENTRY_VISIBLE", "CLICK", "TRANSITION", "DESTINATION_CONFIRMED",
        ),
        "success_postcondition": "配置 Boss 卡确实消失或进入目标挑战/局内 HUD；单次 BossConfigured click success 不是成功。",
        "fail_condition": "boss_entry 可见但配置 Boss 未命中、输入被拒绝、入口/目标页不变，或生产 handler 进入 ERROR。",
        "blocked_condition": "capture 无效、Boss 列表未打开，或没有唯一的已配置 Boss。",
        "max_probe_time_s": 20.0,
        "natural_e2e_eligible": "仅连续 mediator_tick 实机链、挑战目的地已由现有生产状态确认、且无 FAIL/MANUAL_INTERVENTION bookmark 时仍有资格；probe 本身不算 Natural E2E。",
        "bundle_replay": "入口、点击和转场的事件帧直接转换为现有 schema-v1 replay case，并注入拒绝/不变/缺后置/超时分支。",
        "runbook_manual": "先打开目标 Boss 列表，并在设置里仅保留本次要测的一个 Boss。",
        "runbook_hands_off": "启动后不要点 Boss 卡、返回按钮或开始挑战。",
        "runbook_pass": "只有代码自动确认 Boss 目的地/局内 HUD 才是 Live Probe PASS；p 只保存人工证据。",
        "runbook_manual_intervention": "若需要手动越过列表/弹窗，先留 FAIL，再操作并标 MANUAL_INTERVENTION。",
    },
    "time_cave": {
        "handler": "_maybe_challenge_configured_boss",
        "call": "frame_now",
        "start_condition": "人工完整走到时光之穴相关页面；当前只做关键帧、trace 与状态 Ground Truth capture。",
        "production_entry": "BLOCKED：当前没有已验证的战后时光之穴 NPC 生产入口；capture 不调用 Boss 选择 handler。",
        "expected_steps": (
            "POSTGAME_DETECT", "ENTRY_VISIBLE", "CLICK", "REQUEST", "CONFIRM", "TRANSITION", "DESTINATION_CONFIRMED",
        ),
        "success_postcondition": "本轮没有 Live Probe PASS；只保存完整人工链的 Ground Truth，供后续单独设计生产实现。",
        "fail_condition": "仅记录 capture/preflight 异常，不把人工链路缺口归因为现有生产 handler。",
        "blocked_condition": "production BLOCKED：战后时光之穴 NPC 未接线；测试侧强制 zero-input。",
        "max_probe_time_s": 25.0,
        "natural_e2e_eligible": "Ground Truth capture 永不构成 Live Probe PASS 或 Natural E2E；未来完成独立生产设计后重新评估。",
        "bundle_replay": "捕获的 postgame/entry/transition 关键帧按原 ReplayCaseLoader 格式重放，故障变体不改原始截图。",
        "runbook_manual": "手动完成可到达的时光之穴链路；不用配置生产 Boss 选择作为验收前置。",
        "runbook_hands_off": "启动后脚本只取证，绝不会点击 Boss、确认或返回；可继续人工推进稀有页面。",
        "runbook_pass": "本 target 无 Live Probe PASS；capture bundle 成功保存即为 Ground Truth 完成。",
        "runbook_manual_intervention": "需要继续人工推进时按 m；它保留后续 Ground Truth，但不产生 Natural E2E。",
    },
    "heirloom": {
        "handler": "_maybe_challenge_configured_boss",
        "call": "frame_now",
        "start_condition": "人工完整走到传家宝 Boss 选择附近；当前只做关键帧、trace 与状态 Ground Truth capture。",
        "production_entry": "BLOCKED：当前生产只验证 DismissHeirloomDialog 安全关闭；capture 不调用 Boss 选择 handler。",
        "expected_steps": (
            "POSTGAME_DETECT", "ENTRY_VISIBLE", "CLICK", "REQUEST", "CONFIRM", "TRANSITION", "DESTINATION_CONFIRMED",
        ),
        "success_postcondition": "本轮没有 Live Probe PASS；只保存完整人工链的 Ground Truth，供后续单独设计生产实现。",
        "fail_condition": "仅记录 capture/preflight 异常，不把人工链路缺口归因为现有生产 handler。",
        "blocked_condition": "production BLOCKED：传家宝 Boss 选择未接线，当前仅有安全关闭；测试侧强制 zero-input。",
        "max_probe_time_s": 25.0,
        "natural_e2e_eligible": "Ground Truth capture 永不构成 Live Probe PASS 或 Natural E2E；未来完成独立生产设计后重新评估。",
        "bundle_replay": "捕获的 postgame/entry/transition 关键帧按原 ReplayCaseLoader 格式重放，故障变体不改原始截图。",
        "runbook_manual": "手动完成可到达的传家宝链路；保留 Boss 选择页和前后转场的 Ground Truth。",
        "runbook_hands_off": "启动后脚本只取证，绝不会点击 Boss、确认或关闭传家宝页面；可继续人工推进。",
        "runbook_pass": "本 target 无 Live Probe PASS；capture bundle 成功保存即为 Ground Truth 完成。",
        "runbook_manual_intervention": "需要继续人工推进时按 m；它保留后续 Ground Truth，但不产生 Natural E2E。",
    },
    "secret_realm": {
        "handler": "_tick_main_line",
        "call": "frame",
        "start_condition": "已到胜利后的 NPC_HUB 或大秘境确认页；用户 settings 中 auto_secret_realm 已开启，并满足生产链现有前置。",
        "production_entry": "Mediator._tick_main_line(frame)",
        "expected_steps": (
            "POSTGAME_DETECT", "ENTRY_VISIBLE", "REQUEST", "CONFIRM", "TRANSITION", "DESTINATION_CONFIRMED",
        ),
        "success_postcondition": "只有 OpenGreatRift/ConfirmGreatRift 后，既有 _is_in_game_hud() 真实确认且 _secret_realm_active=True，才是 Live Probe PASS。",
        "fail_condition": "请求/确认输入被拒绝、现有请求或进入验证超时、仍停在 NPC_HUB，或生产 handler 进入 ERROR。",
        "blocked_condition": "capture 无效、未在 NPC_HUB/确认页、auto_secret_realm 未启用、既有前置未满足，或 probe 试图发出 OpenGreatRift/ConfirmGreatRift 之外的主线动作。",
        "max_probe_time_s": 30.0,
        "natural_e2e_eligible": "仅连续 mediator_tick 实机链、_secret_realm_active=True 由真实 HUD 证实、且无 FAIL/MANUAL_INTERVENTION bookmark 时仍有资格；probe 本身不算 Natural E2E。",
        "bundle_replay": "捕获的请求、确认和 HUD 转场帧交给现有 ReplayCaseLoader；四种故障只由 FakeInputExecutor/FakeClock/时间线控制注入。",
        "runbook_manual": "把游戏停在胜利后 NPC 广场或大秘境确认页，并确认 settings 中自动秘境开关已开启。",
        "runbook_hands_off": "启动后不要右键 NPC、点击“是”或切换回大厅。",
        "runbook_pass": "只有代码自动确认局内 HUD 且 _secret_realm_active=True 才是 Live Probe PASS；p 只保存人工证据。",
        "runbook_manual_intervention": "若要人工确认或绕过阻塞，先标 FAIL；操作后标 MANUAL_INTERVENTION，继续收集后续 Ground Truth。",
    },
}

# HARNESS readiness and production readiness are intentionally independent.
# The facts below are the read-only historical triage boundary for this
# checkpoint; changing a BLOCKED fact requires a separate production design,
# not a test-harness change.
TARGET_PRODUCTION_FACTS: dict[str, dict[str, Any]] = {
    "black_merchant": {
        "production_readiness": "CONDITIONAL",
        "scope": "同一黑商遭遇内：空条先刷新，再按现有 handler 获取吞噬丹/木材；折扣候选仅在有可靠识别证据时获取。",
        "routes": (
            {"route": "black_merchant_swallow_pill", "readiness": "CONDITIONAL"},
            {"route": "black_merchant_wood", "readiness": "CONDITIONAL"},
            {"route": "black_merchant_discount_2_5", "readiness": "CONDITIONAL"},
        ),
        "ground_truth_only": False,
    },
    "inventory_item": {
        "production_readiness": "CONDITIONAL",
        "scope": "仅吞噬丹（WAIT_DEVOUR_DAN verifier）可优先实测。",
        "routes": ({"route": "inventory_swallow_pill", "readiness": "CONDITIONAL"},),
        "ground_truth_only": False,
    },
    "boss_challenge": {
        "production_readiness": "CONDITIONAL",
        "scope": "已配置 Boss 列表与 tqtz→SGZX 只作为条件性既有 handler 路线。",
        "routes": (
            {"route": "configured_boss", "readiness": "CONDITIONAL"},
            {"route": "tqtz_to_sgzx", "readiness": "CONDITIONAL"},
        ),
        "ground_truth_only": False,
    },
    "time_cave": {
        "production_readiness": "BLOCKED",
        "scope": "战后时光之穴 NPC 未接线；只采完整人工链 Ground Truth，零输入。",
        "routes": ({"route": "postgame_time_cave_npc", "readiness": "BLOCKED"},),
        "ground_truth_only": True,
    },
    "heirloom": {
        "production_readiness": "BLOCKED",
        "scope": "Boss 选择未接线；当前生产只验证安全关闭，故只采完整人工链 Ground Truth，零输入。",
        "routes": ({"route": "heirloom_boss_selection", "readiness": "BLOCKED"},),
        "ground_truth_only": True,
    },
    "secret_realm": {
        "production_readiness": "CONDITIONAL",
        "scope": "只允许现有 OpenGreatRift/ConfirmGreatRift；Live PASS 必须到真实 HUD + _secret_realm_active。",
        "routes": ({"route": "secret_realm_entry", "readiness": "CONDITIONAL"},),
        "ground_truth_only": False,
    },
}


def _production_fact(target: str) -> dict[str, Any]:
    try:
        return TARGET_PRODUCTION_FACTS[target]
    except KeyError as exc:
        raise ValueError(f"未知 target production fact: {target}") from exc


def _ground_truth_only(target: str) -> bool:
    return bool(_production_fact(target).get("ground_truth_only"))


def _probe_allowed_reasons(target: str) -> set[str] | None:
    """Return the test-side action allowlist for a narrow target probe.

    This is an assertion around an existing production handler, not a second
    handler or a policy implementation. ``None`` means the probe has no
    additional action restriction beyond the normal production gate.
    """
    if _ground_truth_only(target):
        return set()
    return {
        "black_merchant": {
            "BlackMerchant-swallow_pill",
            "BlackMerchant-wood",
            "BlackMerchant-discount",
            "BlackMerchant-refresh",
        },
        "inventory_item": {"UseInventory-swallow_pill"},
        "boss_challenge": {"BossConfigured"},
        "secret_realm": {"OpenGreatRift", "ConfirmGreatRift"},
    }.get(target)

SUPPORTED_TARGETS = tuple(TARGET_CONTRACTS)
FAILURE_VARIANTS = (
    "click_rejected",
    "postcondition_missing",
    "frame_unchanged",
    "timeout",
)
BOOKMARK_STATUSES = ("PASS", "FAIL", "MANUAL_INTERVENTION")
_BOOKMARK_KEYS = {"p": "PASS", "f": "FAIL", "m": "MANUAL_INTERVENTION"}
TARGET_HANDLERS = {
    target: str(contract["handler"])
    for target, contract in TARGET_CONTRACTS.items()
}

FAILURE_TAXONOMY = (
    "L0_CAPTURE_ENV",
    "L1_SCENE_DETECTION",
    "L2_VISION_OCR",
    "L3_POLICY_DECISION",
    "L4_INPUT_EXECUTION",
    "L5_POSTCONDITION",
    "L6_FSM_TRANSITION",
    "L7_LIVENESS_RESET",
    "L8_TEST_EVIDENCE",
)


class BookmarkCommandReader:
    """Read non-blocking bookmark commands from a file or the console."""

    def __init__(self, command_file: Path | None = None) -> None:
        self.command_file = Path(command_file).resolve() if command_file else None
        self._consumed_lines = 0

    @staticmethod
    def _parse(raw: str) -> tuple[str, str] | None:
        status_raw, separator, note = raw.strip().partition("|")
        status = status_raw.strip().upper()
        if status not in BOOKMARK_STATUSES:
            return None
        return status, note.strip() if separator else ""

    def poll(self) -> list[tuple[str, str]]:
        commands: list[tuple[str, str]] = []
        if self.command_file is not None and self.command_file.exists():
            try:
                lines = self.command_file.read_text(encoding="utf-8").splitlines()
            except OSError:
                lines = []
            if len(lines) < self._consumed_lines:
                self._consumed_lines = 0
            for line in lines[self._consumed_lines:]:
                parsed = self._parse(line)
                if parsed is not None:
                    commands.append(parsed)
            self._consumed_lines = len(lines)
        try:
            import msvcrt

            while msvcrt.kbhit():
                parsed = self._parse(_BOOKMARK_KEYS.get(msvcrt.getwch().lower(), ""))
                if parsed is not None:
                    commands.append(parsed)
        except (ImportError, OSError):
            pass
        return commands


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _jsonable(value: Any) -> Any:
    """Convert small runtime snapshots to JSON without serialising frame data."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.name
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.generic):
        return value.item()
    if callable(value):
        return None
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if is_dataclass(value):
        return {
            f.name: _jsonable(getattr(value, f.name))
            for f in fields(value)
            if f.name not in {"verifier", "frame_ref", "bgr"}
        }
    if isinstance(value, np.ndarray):
        return {"shape": list(value.shape), "dtype": str(value.dtype)}
    return str(value)


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(k): _scrub(v)
            for k, v in value.items()
            if "password" not in str(k).lower()
        }
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return _jsonable(value)


def _settings_snapshot(settings: Settings | dict[str, Any]) -> dict[str, Any]:
    raw = asdict(settings) if is_dataclass(settings) else dict(settings)
    return _scrub(raw)


def _commit_sha(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return "unknown"
    sha = result.stdout.strip()
    return sha if result.returncode == 0 and sha else "unknown"


def _copy_frame(frame: Frame | None, timestamp: float | None = None) -> Frame | None:
    if frame is None or frame.bgr is None or frame.bgr.size == 0:
        return None
    return Frame(
        bgr=np.array(frame.bgr, copy=True),
        left=frame.left,
        top=frame.top,
        window_title=frame.window_title,
        hwnd=frame.hwnd,
        timestamp=frame.timestamp if timestamp is None else timestamp,
        is_valid=frame.is_valid,
        error=frame.error,
        role=frame.role,
    )


def _frame_fingerprint(frame: Frame | None) -> str | None:
    if frame is None or frame.bgr is None or frame.bgr.size == 0:
        return None
    digest = hashlib.sha256(frame.bgr.tobytes()).hexdigest()
    return f"{frame.width}x{frame.height}:{digest}"


def _write_png(path: Path, frame: Frame) -> None:
    encoded_ok, encoded = cv2.imencode(".png", frame.bgr)
    if not encoded_ok:
        raise OSError(f"无法编码截图: {path}")
    encoded.tofile(str(path))


def _role_for_phase(phase: Phase) -> str:
    return "l0" if phase in {
        Phase.BOOT,
        Phase.WAIT_EXIT,
        Phase.LOBBY_ROOM,
        Phase.PREPARE,
        Phase.PLATFORM_MAP,
        Phase.CREATE_ROOM,
        Phase.ROOM_WAITING,
    } else "l1"


def _state_snapshot(med: Mediator, context: str | None = None) -> dict[str, Any]:
    pending = getattr(med, "_pending_action", None)
    pending_info = None
    if pending is not None:
        pending_info = {
            "kind": getattr(pending, "kind", None),
            "target_id": getattr(pending, "target_id", None),
            "deadline": getattr(pending, "deadline", None),
        }
    recovery = getattr(med, "_recovery_state", None)
    recovery_info = _jsonable(recovery) if recovery is not None else {
        "step": getattr(med, "_recovery_step", None),
    }
    merchant = getattr(med, "_merchant_fsm", None)
    equipment = getattr(med, "_equipment_fsm", None)
    return _jsonable({
        "phase": getattr(getattr(med, "phase", None), "name", getattr(med, "phase", None)),
        "context": context if context is not None else getattr(med, "_context_cache_value", None),
        "l1_cycle_step": getattr(med, "_l1_cycle_step", None),
        "panel_state": getattr(getattr(med, "_panel_state", None), "name", getattr(med, "_panel_state", None)),
        "panel_kind": getattr(med, "_panel_kind", None),
        "merchant_fsm": merchant,
        "equipment_fsm": equipment,
        "recovery_fsm": recovery_info,
        "pending_action": pending_info,
        "post_game_pending": getattr(med, "_post_game_pending", None),
        "secret_realm_request_pending": getattr(med, "_secret_realm_request_pending", None),
        "secret_realm_entering_since": getattr(med, "_secret_realm_entering_since", None),
        "secret_realm_active": getattr(med, "_secret_realm_active", None),
        "boss_challenge_attempts": getattr(med, "_boss_challenge_attempts", None),
        "round_outcome": getattr(getattr(med, "_round_outcome", None), "name", None),
    })


def _action_from_tick(med: Mediator, input_records: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not input_records:
        return None
    record = input_records[0]
    trace_actions = list(getattr(med, "_trace_actions", []) or [])
    trace_action = trace_actions[0] if trace_actions else {}
    intent = str(trace_action.get("intent") or "")
    target = intent.split(":", 1)[1] if ":" in intent else None
    action = {
        "kind": record.get("method"),
        "reason": trace_action.get("reason", ""),
        "target": target,
        "input_kind": _INPUT_KIND.get(record.get("method"), record.get("method")),
    }
    args = record.get("args") or []
    if record.get("method") in {"click", "right_click", "scroll"} and len(args) >= 2:
        action["point"] = [int(args[0]), int(args[1])]
    return action


def _evidence_snapshot(med: Mediator, frame: Frame | None) -> dict[str, Any]:
    scenes = []
    for raw in list(getattr(med, "_trace_scenes", []) or []):
        item = dict(raw)
        scene_name = item.get("scene")
        if scene_name and hasattr(med, "_scene_roi"):
            roi = med._scene_roi(scene_name)
            if roi is not None:
                item["roi"] = list(roi)
        scenes.append(item)
    return _jsonable({
        "context": getattr(med, "_context_cache_value", None),
        "evidence_gen": getattr(getattr(med, "_evidence", None), "gen", None),
        "frame_fingerprint": _frame_fingerprint(frame),
        "templates": scenes,
        "ocr": getattr(med, "_trace_ocr_suggestion", None),
        "panel_candidates": getattr(med, "_trace_panel_candidates", lambda: [])(),
    })


def _postcondition_snapshot(
    med: Mediator,
    before_state: dict[str, Any],
    after_state: dict[str, Any],
    action: dict[str, Any] | None,
    trace_row: dict[str, Any] | None,
) -> dict[str, Any]:
    if action is None:
        return {"observed": None, "state": "not_applicable", "kind": None}
    if trace_row and trace_row.get("post_confirm") is True:
        return {"observed": True, "state": "confirmed", "kind": "trace_post_confirm"}
    before_pending = before_state.get("pending_action")
    after_pending = after_state.get("pending_action")
    if before_pending is not None and after_pending is None:
        return {"observed": True, "state": "confirmed", "kind": before_pending.get("kind")}
    merchant_before = before_state.get("merchant_fsm") or {}
    merchant_after = after_state.get("merchant_fsm") or {}
    if (
        merchant_before.get("phase") == "VERIFYING"
        and merchant_after.get("phase") not in {"VERIFYING", None}
    ):
        return {"observed": True, "state": "confirmed", "kind": "merchant_fsm"}
    equipment_before = before_state.get("equipment_fsm") or {}
    equipment_after = after_state.get("equipment_fsm") or {}
    if (
        equipment_before.get("pending_slot") is not None
        and equipment_after.get("pending_slot") is None
        and equipment_after.get("states")
    ):
        return {"observed": True, "state": "confirmed", "kind": "equipment_fsm"}
    if after_pending is not None or merchant_after.get("phase") == "VERIFYING" or equipment_after.get("pending_slot") is not None:
        kind = (after_pending or {}).get("kind") or "handler_verification"
        return {"observed": False, "state": "waiting", "kind": kind}
    return {"observed": False, "state": "not_observed", "kind": action.get("reason")}


def _target_postcondition_snapshot(
    target: str,
    med: Mediator,
    frame: Frame | None,
    after_state: dict[str, Any],
    action: dict[str, Any] | None,
    base: dict[str, Any],
) -> dict[str, Any]:
    """Add only target-specific, production-observable business evidence."""
    reason = str((action or {}).get("reason") or "")

    # A black-merchant refresh is useful evidence, but must never turn the
    # whole target green. Only the production swallow-pill verifier is an
    # authoritative target postcondition in this checkpoint.
    if target == "black_merchant":
        if "BlackMerchant-swallow_pill" in reason and base.get("observed") is True:
            return {"observed": True, "state": "confirmed", "kind": "merchant_swallow_pill"}
        if "BlackMerchant-refresh" in reason:
            return {"observed": False, "state": "partial_refresh_only", "kind": "merchant_refresh"}
        if "BlackMerchant-wood" in reason and base.get("observed") is True:
            return {"observed": True, "state": "confirmed", "kind": "merchant_wood"}
        if "BlackMerchant-discount" in reason and base.get("observed") is True:
            return {"observed": True, "state": "confirmed", "kind": "merchant_discount"}
        return {"observed": False, "state": "not_observed", "kind": reason or "merchant_target"}

    # Inventory is intentionally narrowed to the historically supported
    # swallow-pill route. A generic inventory state transition cannot claim
    # this target's pass.
    if target == "inventory_item":
        if "UseInventory-swallow_pill" in reason and base.get("observed") is True:
            return {"observed": True, "state": "confirmed", "kind": "inventory_swallow_pill"}
        return {"observed": False, "state": "not_observed", "kind": reason or "inventory_swallow_pill"}

    # These targets are capture-only until a separate production design is
    # approved. Their historical screenshots can never become a probe pass.
    if target in {"time_cave", "heirloom"}:
        return {"observed": False, "state": "ground_truth_only", "kind": "production_blocked"}

    if target == "secret_realm":
        if after_state.get("secret_realm_active") and _frame_is_valid(frame):
            try:
                if med._is_in_game_hud(frame):
                    return {"observed": True, "state": "confirmed", "kind": "secret_realm_hud"}
            except (AttributeError, TypeError):
                pass
        return {"observed": False, "state": "waiting", "kind": "secret_realm_hud"}

    if target == "boss_challenge" and "BossConfigured" in reason and _frame_is_valid(frame):
        try:
            if med._is_in_game_hud(frame):
                return {"observed": True, "state": "confirmed", "kind": "destination_hud"}
        except (AttributeError, TypeError):
            pass
    return base


def _postcondition_transition_observed(
    before_state: dict[str, Any],
    after_state: dict[str, Any],
    trace_row: dict[str, Any] | None = None,
) -> bool:
    if trace_row and trace_row.get("post_confirm") is True:
        return True
    if before_state.get("pending_action") is not None and after_state.get("pending_action") is None:
        return True
    merchant_before = before_state.get("merchant_fsm") or {}
    merchant_after = after_state.get("merchant_fsm") or {}
    if merchant_before.get("phase") == "VERIFYING" and merchant_after.get("phase") not in {"VERIFYING", None}:
        return True
    equipment_before = before_state.get("equipment_fsm") or {}
    equipment_after = after_state.get("equipment_fsm") or {}
    return bool(
        equipment_before.get("pending_slot") is not None
        and equipment_after.get("pending_slot") is None
        and equipment_after.get("states")
    )


def _target_contract(target: str) -> dict[str, Any]:
    try:
        return TARGET_CONTRACTS[target]
    except KeyError as exc:
        raise ValueError(f"未知 target: {target}") from exc


def _invoke_target_handler(med: Mediator, target: str, frame: Frame) -> Any:
    """Invoke exactly one existing production entry point for a target probe."""
    contract = _target_contract(target)
    handler = getattr(med, str(contract["handler"]))
    if contract.get("call") == "frame_now":
        return handler(frame, time.time())
    return handler(frame)


def _template_items(evidence: dict[str, Any] | None) -> list[dict[str, Any]]:
    templates = (evidence or {}).get("templates") or []
    return [item for item in templates if isinstance(item, dict)]


def _best_anchor(evidence: dict[str, Any] | None) -> dict[str, Any] | None:
    templates = _template_items(evidence)
    if not templates:
        return None

    def score(item: dict[str, Any]) -> float:
        raw = item.get("score", item.get("confidence", -1.0))
        try:
            return float(raw)
        except (TypeError, ValueError):
            return -1.0

    item = max(templates, key=score)
    return {
        "name": item.get("scene") or item.get("name") or item.get("template"),
        "score": item.get("score", item.get("confidence")),
        "roi": item.get("roi"),
    }


def _ocr_fields(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {
            "raw": value.get("raw", value.get("text")),
            "normalized": value.get("normalized", value.get("normalised")),
            "candidate": value.get("candidate", value.get("selected")),
            "all": _jsonable(value),
        }
    return {"raw": value, "normalized": None, "candidate": None, "all": _jsonable(value)}


def _last_trace_value(rows: list[dict[str, Any]], key: str) -> Any:
    for row in reversed(rows):
        if isinstance(row, dict) and row.get(key) is not None:
            return row.get(key)
    return None


def _stage_from_observation(
    target: str,
    state: dict[str, Any] | None,
    evidence: dict[str, Any] | None,
    action: dict[str, Any] | None = None,
    postcondition: dict[str, Any] | None = None,
) -> str:
    """Label capture diagnostics from existing production evidence only."""
    contract = _target_contract(target)
    valid = set(contract["expected_steps"])
    state = state or {}
    evidence = evidence or {}
    action = action or {}
    postcondition = postcondition or {}
    reason = str(action.get("reason") or "").lower()
    template_names = " ".join(
        str(item.get("scene") or item.get("name") or item.get("template") or "").lower()
        for item in _template_items(evidence)
    )
    observed = postcondition.get("observed") is True

    if target == "black_merchant":
        merchant = state.get("merchant_fsm") or {}
        phase = str(merchant.get("phase") or "").upper()
        if observed:
            return "VERIFY_REFRESH" if "refresh" in reason else "VERIFY_TAKE"
        if "refresh" in reason:
            return "VERIFY_REFRESH" if phase == "VERIFYING" else "REFRESH"
        if "blackmerchant" in reason:
            return "VERIFY_TAKE" if phase == "VERIFYING" else "TAKE"
        if phase == "VERIFYING":
            return "VERIFY_TAKE"
        return "SCAN" if template_names else "DETECT"

    if target == "inventory_item":
        pending = state.get("pending_action") or {}
        if observed or str(pending.get("kind") or "").startswith("WAIT_"):
            return "VERIFY_CONSUMED"
        if "useinventory" in reason:
            return "USE"
        return "IDENTIFY" if template_names else "DETECT_SLOT"

    if target == "secret_realm":
        if state.get("secret_realm_active"):
            return "DESTINATION_CONFIRMED"
        if observed:
            return "DESTINATION_CONFIRMED"
        if "confirmgreatrift" in reason or "mijingok" in template_names:
            return "CONFIRM"
        if "opengreatrift" in reason or "damijing" in template_names:
            return "REQUEST"
        if state.get("post_game_pending"):
            return "ENTRY_VISIBLE"
        return "POSTGAME_DETECT"

    if observed:
        return "DESTINATION_CONFIRMED"
    if "bossconfigured" in reason:
        return "TRANSITION"
    if "boss_entry" in template_names or "boss" in template_names:
        return "ENTRY_VISIBLE"
    return "POSTGAME_DETECT" if "POSTGAME_DETECT" in valid else next(iter(valid))


def _frame_is_valid(frame: Frame | None) -> bool:
    return bool(
        frame is not None
        and getattr(frame, "is_valid", True)
        and getattr(frame, "bgr", None) is not None
        and frame.bgr.size > 0
    )


def _replay_command(bundle_dir: Path) -> str:
    return f'python tools/live_scenario_capture.py reproduce --bundle "{Path(bundle_dir).resolve()}"'


def _failure_class_hints(summary: dict[str, Any]) -> list[dict[str, str]]:
    """Classify only when a recorded field directly supports the hint."""
    hints: list[dict[str, str]] = []

    def add(layer: str, evidence: str) -> None:
        if layer not in FAILURE_TAXONOMY:
            raise AssertionError(f"unknown failure taxonomy layer: {layer}")
        if not any(item["layer"] == layer for item in hints):
            hints.append({"layer": layer, "evidence": evidence})

    if summary.get("status") == "BLOCKED_PRECHECK":
        preflight = summary.get("preflight") or {}
        reasons = preflight.get("blocked_reasons") or []
        return [{
            "layer": "L8_TEST_EVIDENCE",
            "evidence": "live-input preflight blocked before any business handler: " + "; ".join(map(str, reasons)),
        }]

    evidence = summary.get("evidence") or {}
    action = summary.get("action") or {}
    input_result = summary.get("input_result") or {}
    actual = summary.get("actual_postcondition") or {}
    note = str(summary.get("note") or "").lower()
    frame_changed = summary.get("frame_fingerprint_changed")
    phase_changed = summary.get("phase_changed")
    fsm_changed = summary.get("fsm_state_changed")
    ocr = summary.get("ocr") or {}

    if not summary.get("frame_fingerprint") or evidence.get("capture_valid") is False:
        add("L0_CAPTURE_ENV", "capture frame is missing, invalid, or has no fingerprint")
    visual_note = any(token in note for token in ("人眼", "visible", "可见"))
    if visual_note and not _template_items(evidence):
        add("L1_SCENE_DETECTION", "operator note says the target is visible but the saved template evidence is empty")
    if ocr.get("raw") is not None and ocr.get("candidate") is None and not action:
        add("L2_VISION_OCR", "OCR produced raw text but no normalized candidate/action is recorded")
    policy = summary.get("policy_decision")
    if policy is not None and not action:
        add("L3_POLICY_DECISION", "production trace contains a policy decision but no input action followed")
    if action and (input_result.get("success") is False or str(input_result.get("status") or "").startswith("CANCELLED")):
        add("L4_INPUT_EXECUTION", "recorded input result is rejected/cancelled")
    if action and input_result.get("success") is True and frame_changed is False:
        add("L4_INPUT_EXECUTION", "input succeeded but the recorded before/after frame fingerprint is unchanged")
        add("L5_POSTCONDITION", "input succeeded but no visual change was recorded")
    if action and input_result.get("success") is True and actual.get("observed") is False:
        add("L5_POSTCONDITION", "input succeeded but the recorded business postcondition was not observed")
    if frame_changed is True and actual.get("observed") is True and not phase_changed and not fsm_changed:
        add("L6_FSM_TRANSITION", "visual/business postcondition changed but phase and captured FSM snapshot did not advance")
    if any(token in note for token in ("liveness", "reset", "residual", "残留")):
        add("L7_LIVENESS_RESET", "bookmark/failure note explicitly reports liveness or residual-state evidence")
    if not summary.get("recent_trace") or not evidence:
        add("L8_TEST_EVIDENCE", "trace or evidence snapshot is absent")
    if not hints:
        hints.append({"layer": "UNKNOWN", "evidence": "recorded fields do not isolate a layer"})
    return hints


def _build_failure_summary(
    *,
    status: str,
    manifest: dict[str, Any],
    bundle_dir: Path,
    bookmark: dict[str, Any],
) -> dict[str, Any]:
    events = manifest.get("events") or []
    event = next((item for item in reversed(events) if isinstance(item, dict)), {})
    evidence = bookmark.get("evidence") or event.get("evidence") or {}
    if not isinstance(evidence, dict):
        evidence = {"raw": _jsonable(evidence)}
    evidence = dict(evidence)
    evidence["capture_valid"] = bool(
        bookmark.get("capture_valid", bookmark.get("frame_fingerprint") is not None)
    )
    fsm_before = event.get("fsm_before") or {}
    fsm_after = event.get("fsm_after") or bookmark.get("fsm_state") or {}
    action = event.get("action") or {}
    input_record = event.get("input") or {}
    input_result = event.get("input_result") or {}
    postcondition = event.get("postcondition") or {"observed": None, "state": "not_recorded"}
    recent_trace = bookmark.get("recent_trace") or event.get("recent_trace") or []
    if not isinstance(recent_trace, list):
        recent_trace = []
    decision = _last_trace_value(recent_trace, "decision")
    policy_reason = action.get("reason") or _last_trace_value(recent_trace, "reason")
    anchor = _best_anchor(evidence)
    ocr = _ocr_fields(evidence.get("ocr"))
    target = str(manifest.get("target") or "unknown")
    stage = _stage_from_observation(target, fsm_after, evidence, action, postcondition)
    before_fp = event.get("frame_before")
    after_fp = event.get("frame_after")
    frame_changed: bool | None
    if before_fp is None or after_fp is None:
        frame_changed = None
    else:
        frame_changed = not bool(event.get("frame_unchanged"))
    phase_before = event.get("phase_before") or fsm_before.get("phase")
    phase_after = event.get("phase_after") or fsm_after.get("phase")
    summary: dict[str, Any] = {
        "failure_summary_schema_version": 1,
        "status": status,
        "target": target,
        "tested_commit_sha": manifest.get("tested_commit_sha"),
        "current_phase": fsm_after.get("phase"),
        "fsm_state": fsm_after,
        "target_stage": stage,
        "last_successful_anchor": anchor,
        "template_score": anchor.get("score") if anchor else None,
        "template_evidence": _template_items(evidence),
        "ocr": ocr,
        "policy_decision": _jsonable(decision),
        "policy_reason": _jsonable(policy_reason),
        "action": action or None,
        "input_sent": bool(input_record),
        "input_result": input_result or None,
        "frame_fingerprint": bookmark.get("frame_fingerprint"),
        "frame_fingerprint_changed": frame_changed,
        "expected_postcondition": _target_contract(target)["success_postcondition"],
        "actual_postcondition": postcondition,
        "phase_changed": phase_before != phase_after if phase_before is not None and phase_after is not None else None,
        "fsm_state_changed": bool(fsm_before and fsm_after and fsm_before != fsm_after),
        "bundle_path": str(Path(bundle_dir).resolve()),
        "bookmark_id": bookmark.get("bookmark_id"),
        "bookmark_status": bookmark.get("status"),
        "note": bookmark.get("note", ""),
        "recent_trace": recent_trace,
        "evidence": evidence,
        "preflight": manifest.get("live_preflight"),
        "replay_command": _replay_command(bundle_dir),
        "relevant_files": [],
    }
    summary["failure_class_hints"] = _failure_class_hints(summary)
    summary["failure_class_hint"] = ", ".join(item["layer"] for item in summary["failure_class_hints"])
    return _jsonable(summary)


def _failure_summary_markdown(summary: dict[str, Any]) -> str:
    hints = summary.get("failure_class_hints") or []
    lines = [
        "# Failure Summary",
        "",
        f"TARGET: {summary.get('target')}",
        f"FAILURE_CLASS_HINT: {summary.get('failure_class_hint')}",
        f"BUNDLE_PATH: {summary.get('bundle_path')}",
        f"BOOKMARK_ID: {summary.get('bookmark_id')}",
        f"REPLAY_COMMAND: {summary.get('replay_command')}",
        "RELEVANT_FILES:",
    ]
    lines.extend(f"- {path}" for path in summary.get("relevant_files") or [])
    lines.extend([
        "",
        f"tested_commit_sha: {summary.get('tested_commit_sha')}",
        f"phase / FSM: {summary.get('current_phase')} / {json.dumps(summary.get('fsm_state'), ensure_ascii=False)}",
        f"target_stage: {summary.get('target_stage')}",
        f"last_anchor: {json.dumps(summary.get('last_successful_anchor'), ensure_ascii=False)}",
        f"OCR raw / normalized / candidate: {summary.get('ocr', {}).get('raw')} / {summary.get('ocr', {}).get('normalized')} / {summary.get('ocr', {}).get('candidate')}",
        f"policy decision / reason: {json.dumps(summary.get('policy_decision'), ensure_ascii=False)} / {summary.get('policy_reason')}",
        f"input sent / result: {summary.get('input_sent')} / {json.dumps(summary.get('input_result'), ensure_ascii=False)}",
        f"live preflight: {json.dumps(summary.get('preflight'), ensure_ascii=False)}",
        f"frame fingerprint changed: {summary.get('frame_fingerprint_changed')}",
        f"expected postcondition: {summary.get('expected_postcondition')}",
        f"actual postcondition: {json.dumps(summary.get('actual_postcondition'), ensure_ascii=False)}",
        f"phase / FSM changed: {summary.get('phase_changed')} / {summary.get('fsm_state_changed')}",
        "",
        "Classification evidence:",
    ])
    lines.extend(f"- {item.get('layer')}: {item.get('evidence')}" for item in hints)
    return "\n".join(lines) + "\n"


class RecordingInputExecutor(InputExecutor):
    """Delegate to the real executor while preserving every ActionResult."""

    def __init__(
        self,
        delegate: InputExecutor,
        on_result: Callable[..., None],
        *,
        reason_provider: Callable[[], str] | None = None,
        input_guard: Callable[[str, str], str | None] | None = None,
        on_guard: Callable[[str, str, str], None] | None = None,
    ) -> None:
        super().__init__(stop_signal=delegate.stop_signal)
        self._delegate = delegate
        self._on_result = on_result
        self._reason_provider = reason_provider
        self._input_guard = input_guard
        self._on_guard = on_guard

    def _call(self, method: str, *args: Any, **kwargs: Any) -> ActionResult:
        reason = self._reason_provider() if self._reason_provider is not None else ""
        denial = self._input_guard(method, reason) if self._input_guard is not None else None
        if denial:
            result = ActionResult(False, "CANCELLED_PROBE_GUARD", denial)
            if self._on_guard is not None:
                self._on_guard(method, reason, denial)
        else:
            result = getattr(self._delegate, method)(*args, **kwargs)
        if not isinstance(result, ActionResult):
            result = ActionResult(bool(result), "SUCCESS" if result else "CANCELLED_UNKNOWN", "")
        self._on_result(method, args, kwargs, result)
        return result

    def click(self, x: int, y: int, target_hwnd: int | None = None, dry_run: bool = True, delay_ms: int = 120) -> ActionResult:
        return self._call("click", x, y, target_hwnd=target_hwnd, dry_run=dry_run, delay_ms=delay_ms)

    def right_click(self, x: int, y: int, target_hwnd: int | None = None, dry_run: bool = True, delay_ms: int = 120) -> ActionResult:
        return self._call("right_click", x, y, target_hwnd=target_hwnd, dry_run=dry_run, delay_ms=delay_ms)

    def press_key(self, key: str, target_hwnd: int | None = None, dry_run: bool = True) -> ActionResult:
        return self._call("press_key", key, target_hwnd=target_hwnd, dry_run=dry_run)

    def hotkey(self, *keys: str, target_hwnd: int | None = None, dry_run: bool = True) -> ActionResult:
        return self._call("hotkey", *keys, target_hwnd=target_hwnd, dry_run=dry_run)

    def paste_text(self, text: str, target_hwnd: int | None = None, dry_run: bool = True) -> ActionResult:
        return self._call("paste_text", text, target_hwnd=target_hwnd, dry_run=dry_run)

    def scroll(self, x: int, y: int, clicks: int, target_hwnd: int | None = None, dry_run: bool = True) -> ActionResult:
        return self._call("scroll", x, y, clicks, target_hwnd=target_hwnd, dry_run=dry_run)

    def type_text(self, text: str, target_hwnd: int | None = None, dry_run: bool = True) -> ActionResult:
        return self._call("type_text", text, target_hwnd=target_hwnd, dry_run=dry_run)


class BundleRecorder:
    """Write event-driven frames plus the production trace into one bundle."""

    def __init__(
        self,
        bundle_dir: Path,
        *,
        repo_root: Path,
        target: str,
        settings: Settings | dict[str, Any],
        initial_phase: str,
        execution_mode: str,
    ) -> None:
        self.bundle_dir = Path(bundle_dir).resolve()
        self.frames_dir = self.bundle_dir / "frames"
        self.bundle_dir.mkdir(parents=True, exist_ok=True)
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.bundle_dir / "manifest.json"
        self.trace_path = self.bundle_dir / "trace.jsonl"
        self._trace_offset = 0
        self._recent_trace: deque[dict[str, Any]] = deque(maxlen=20)
        self._saved_by_signature: dict[str, str] = {}
        self._frame_number = 0
        self._event_number = 0
        self._last_state: dict[str, Any] | None = None
        self._pending_event_index: int | None = None
        self._blocked_recorded = False
        self._clock_start = time.monotonic()
        self.inputs_this_tick: list[dict[str, Any]] = []
        contract = _target_contract(target)
        production_fact = _production_fact(target)
        natural_e2e_eligible = execution_mode == "mediator_tick"
        natural_e2e_state = (
            "REQUIRED_LIVE_PASS"
            if natural_e2e_eligible
            else ("GROUND_TRUTH_ONLY" if execution_mode == "ground_truth_only" else "TARGET_PROBE_ONLY")
        )
        self.manifest: dict[str, Any] = {
            "capture_schema_version": 1,
            "bundle_id": self.bundle_dir.name,
            "created_at_utc": _utc_now(),
            "completed_at_utc": None,
            "target": target,
            "production_handler": None if production_fact.get("ground_truth_only") else TARGET_HANDLERS.get(target),
            "production_readiness": production_fact["production_readiness"],
            "production_scope": production_fact["scope"],
            "ground_truth_only": bool(production_fact.get("ground_truth_only")),
            "target_contract": {
                key: _jsonable(contract[key])
                for key in TARGET_CONTRACT_FIELDS
            },
            "execution_mode": execution_mode,
            "tested_commit_sha": _commit_sha(repo_root),
            "repo_root": str(repo_root.resolve()),
            "initial_phase": initial_phase,
            "settings": _settings_snapshot(settings),
            "frames": [],
            "events": [],
            "trace_file": "trace.jsonl",
            "recent_trace": [],
            "bookmarks": [],
            "bookmark_summary": {status: 0 for status in BOOKMARK_STATUSES},
            "automatic_failures": [],
            "failure_summaries": [],
            "generated_cases": [],
            "target_result": {
                "expected_postcondition": contract["success_postcondition"],
                "observed": False,
                "evidence": None,
                "authoritative": False,
            },
            "live_preflight": {"status": "NOT_REQUESTED"},
            "verification": {
                "frozen_replay": "PENDING",
                "natural_e2e": natural_e2e_state,
                "natural_e2e_eligible": natural_e2e_eligible,
                "fail_bookmark_seen": False,
                "manual_intervention_seen": False,
                "live_probe": "PENDING" if execution_mode == "target_handler" else "NOT_A_PROBE",
            },
        }

    def elapsed(self) -> float:
        return max(0.0, time.monotonic() - self._clock_start)

    def begin_tick(self) -> None:
        self.inputs_this_tick = []

    def record_input(self, method: str, args: tuple[Any, ...], kwargs: dict[str, Any], result: ActionResult) -> None:
        self.inputs_this_tick.append({
            "method": method,
            "args": _jsonable(args),
            "kwargs": _jsonable(kwargs),
            "success": bool(result.success),
            "status": result.status,
            "message": result.message,
        })

    def record_preflight(self, payload: dict[str, Any]) -> None:
        """Persist the read-only proof required before any real game input."""
        self.manifest["live_preflight"] = _jsonable(payload)
        self._write_manifest()

    def _record_authoritative_target_result(
        self,
        *,
        event_id: str | None,
        postcondition: dict[str, Any],
        target_stage: str | None,
    ) -> None:
        self.manifest["target_result"] = {
            "expected_postcondition": _target_contract(str(self.manifest["target"]))["success_postcondition"],
            "observed": True,
            "authoritative": True,
            "evidence": {
                "event_id": event_id,
                "kind": postcondition.get("kind"),
                "target_stage": target_stage,
            },
        }
        if self.manifest.get("execution_mode") == "target_handler":
            self.manifest["verification"]["live_probe"] = "AUTO_POSTCONDITION_PASS"

    def bookmark(
        self,
        status: str,
        med: Mediator,
        frame: Frame | None = None,
        *,
        note: str = "",
        at_s: float | None = None,
    ) -> dict[str, Any]:
        """Persist one evidence bookmark without changing the mediator loop."""
        status = str(status).strip().upper()
        if status not in BOOKMARK_STATUSES:
            raise ValueError(f"未知 evidence bookmark: {status}")
        return self._record_evidence_bookmark(
            status,
            med,
            frame,
            note=note,
            at_s=at_s,
            automatic=False,
        )

    def record_blocked(
        self,
        med: Mediator,
        frame: Frame | None = None,
        *,
        note: str,
        status: str = "BLOCKED",
        at_s: float | None = None,
    ) -> dict[str, Any] | None:
        """Persist a concrete capture blockage without exposing BLOCKED as a user marker."""
        if self._blocked_recorded:
            return None
        if status not in {"BLOCKED", "BLOCKED_PRECHECK"}:
            raise ValueError(f"未知 automatic blocked status: {status}")
        self._blocked_recorded = True
        return self._record_evidence_bookmark(
            status,
            med,
            frame,
            note=note,
            at_s=at_s,
            automatic=True,
        )

    def _record_evidence_bookmark(
        self,
        status: str,
        med: Mediator,
        frame: Frame | None,
        *,
        note: str,
        at_s: float | None,
        automatic: bool,
    ) -> dict[str, Any]:
        at_s = self.elapsed() if at_s is None else float(at_s)
        current_frame = _copy_frame(frame) or _copy_frame(getattr(med, "_last_frame", None))
        frame_id = self._save_frame(current_frame, f"bookmark_{status.lower()}", at_s)
        self._read_trace()
        bookmark_id = f"b{len(self.manifest['bookmarks']) + len(self.manifest['automatic_failures']):04d}"
        state = _state_snapshot(med, getattr(med, "_context_cache_value", None))
        record = {
            "bookmark_id": bookmark_id,
            "status": status,
            "at_s": round(at_s, 3),
            "created_at_utc": _utc_now(),
            "bundle": str(self.bundle_dir),
            "bundle_id": self.manifest["bundle_id"],
            "tested_commit_sha": self.manifest["tested_commit_sha"],
            "phase": state.get("phase"),
            "fsm_state": state,
            "frame": frame_id,
            "frame_fingerprint": _frame_fingerprint(current_frame),
            "capture_valid": _frame_is_valid(current_frame),
            "evidence": _evidence_snapshot(med, current_frame),
            "recent_trace": list(self._recent_trace),
            "target_postcondition": dict(self.manifest.get("target_result") or {}),
            "note": str(note).strip(),
            "ground_truth_eligible": not status.startswith("BLOCKED"),
            "counts_as_natural_e2e_pass": False,
            "authoritative_live_probe_pass": False,
        }
        bookmark_dir = self.bundle_dir / "bookmarks"
        bookmark_dir.mkdir(parents=True, exist_ok=True)
        sidecar = bookmark_dir / f"{bookmark_id}.json"
        manifest_record = {
            key: record[key]
            for key in (
                "bookmark_id", "status", "at_s", "created_at_utc", "phase",
                "frame", "frame_fingerprint", "note", "ground_truth_eligible",
                "counts_as_natural_e2e_pass",
            )
        }
        manifest_record["file"] = f"bookmarks/{sidecar.name}"
        record["target_stage"] = _stage_from_observation(
            str(self.manifest["target"]),
            state,
            record["evidence"],
        )
        manifest_record["target_stage"] = record["target_stage"]
        verification = self.manifest["verification"]
        if status == "FAIL":
            verification["fail_bookmark_seen"] = True
            verification["natural_e2e_eligible"] = False
            if not verification.get("manual_intervention_seen"):
                verification["natural_e2e"] = "FAILED_BOOKMARK"
        elif status == "MANUAL_INTERVENTION":
            verification["manual_intervention_seen"] = True
            verification["natural_e2e_eligible"] = False
            verification["natural_e2e"] = "DISQUALIFIED_MANUAL_INTERVENTION"
        elif status.startswith("BLOCKED"):
            verification["natural_e2e_eligible"] = False
            verification["natural_e2e"] = status

        if status == "FAIL" or status.startswith("BLOCKED"):
            summary = self._write_failure_summary(status, record, sidecar)
            record["failure_summary_file"] = summary["json_file"]
            manifest_record["failure_summary_file"] = summary["json_file"]
            self.manifest["failure_summaries"].append({
                "bookmark_id": bookmark_id,
                "status": status,
                "file": summary["json_file"],
                "markdown_file": summary["markdown_file"],
                "failure_class_hint": summary["failure_class_hint"],
            })

        sidecar.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        if automatic:
            self.manifest["automatic_failures"].append(manifest_record)
        else:
            self.manifest["bookmarks"].append(manifest_record)
            self.manifest["bookmark_summary"][status] += 1
        self._write_manifest()
        if status == "FAIL" or status.startswith("BLOCKED"):
            self._print_failure_summary(record["failure_summary_file"])
        return record

    def _write_failure_summary(
        self,
        status: str,
        bookmark: dict[str, Any],
        sidecar: Path,
    ) -> dict[str, str]:
        failure_dir = self.bundle_dir / "failures"
        failure_dir.mkdir(parents=True, exist_ok=True)
        stem = f"{bookmark['bookmark_id']}_{status.lower()}"
        json_path = failure_dir / f"{stem}.json"
        markdown_path = failure_dir / f"{stem}.md"
        summary = _build_failure_summary(
            status=status,
            manifest=self.manifest,
            bundle_dir=self.bundle_dir,
            bookmark=bookmark,
        )
        summary["relevant_files"] = [
            str(self.manifest_path),
            str(self.trace_path),
            str(sidecar),
            str(json_path),
            str(markdown_path),
        ]
        json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        markdown_path.write_text(_failure_summary_markdown(summary), encoding="utf-8")
        return {
            "json_file": json_path.relative_to(self.bundle_dir).as_posix(),
            "markdown_file": markdown_path.relative_to(self.bundle_dir).as_posix(),
            "failure_class_hint": str(summary["failure_class_hint"]),
        }

    def _print_failure_summary(self, relative_summary_file: str) -> None:
        summary_path = self.bundle_dir / relative_summary_file
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        print("[failure-summary]")
        print(f"TARGET: {summary.get('target')}")
        print(f"FAILURE_CLASS_HINT: {summary.get('failure_class_hint')}")
        print(f"BUNDLE_PATH: {summary.get('bundle_path')}")
        print(f"BOOKMARK_ID: {summary.get('bookmark_id')}")
        print(f"REPLAY_COMMAND: {summary.get('replay_command')}")
        print("RELEVANT_FILES:")
        for path in summary.get("relevant_files") or []:
            print(f"- {path}")

    def start_trace(self, med: Mediator) -> None:
        med.set_trace(str(self.trace_path))
        self._trace_offset = self.trace_path.stat().st_size if self.trace_path.exists() else 0

    def stop_trace(self, med: Mediator) -> None:
        med.set_trace(None)
        self._read_trace()

    def _read_trace(self) -> list[dict[str, Any]]:
        if not self.trace_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        try:
            with self.trace_path.open("rb") as fh:
                fh.seek(self._trace_offset)
                data = fh.read()
                self._trace_offset = fh.tell()
        except OSError:
            return []
        for line in data.decode("utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except (TypeError, ValueError):
                continue
            if isinstance(row, dict):
                rows.append(row)
                self._recent_trace.append(row)
        return rows

    def _save_frame(self, frame: Frame | None, kind: str, at_s: float) -> str | None:
        if frame is None or frame.bgr is None or frame.bgr.size == 0:
            return None
        fingerprint = _frame_fingerprint(frame)
        if fingerprint is None:
            return None
        signature = (
            f"{fingerprint}|{frame.left}|{frame.top}|{frame.hwnd}|"
            f"{frame.role}|{frame.window_title}"
        )
        existing = self._saved_by_signature.get(signature)
        if existing is not None:
            return existing
        safe_kind = re.sub(r"[^A-Za-z0-9_.-]+", "_", kind).strip("_") or "frame"
        frame_id = f"f{self._frame_number:04d}_{safe_kind}"
        path = self.frames_dir / f"{frame_id}.png"
        _write_png(path, frame)
        self._frame_number += 1
        self._saved_by_signature[signature] = frame_id
        self.manifest["frames"].append({
            "id": frame_id,
            "kind": kind,
            "at_s": round(float(at_s), 3),
            "file": f"frames/{path.name}",
            "fingerprint": fingerprint,
            "window_title": frame.window_title,
            "hwnd": frame.hwnd,
            "left": frame.left,
            "top": frame.top,
            "capture_role": frame.role or "l1",
            "width": frame.width,
            "height": frame.height,
            "timestamp": frame.timestamp,
            "is_valid": frame.is_valid,
            "error": frame.error,
        })
        return frame_id

    def _fallback_trace(
        self,
        med: Mediator,
        phase_before: str,
        phase_after: str,
        loop_action: str,
        at_s: float,
    ) -> dict[str, Any]:
        return _jsonable({
            "tick": getattr(med, "_tick_no", None),
            "ts": round(at_s, 3),
            "phase_before": phase_before,
            "phase_after": phase_after,
            "context": getattr(med, "_context_cache_value", None),
            "actions": getattr(med, "_trace_actions", []),
            "controls": getattr(med, "_trace_controls", []),
            "scenes": getattr(med, "_trace_scenes", []),
            "decision": getattr(med, "_trace_decision", lambda: None)(),
            "post_confirm": getattr(med, "_trace_post_confirm", lambda: None)(),
            "loop_action": loop_action,
        })

    def _append_trace(self, row: dict[str, Any]) -> None:
        with self.trace_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        self._recent_trace.append(row)

    def record_tick(
        self,
        med: Mediator,
        *,
        phase_before: str,
        before_state: dict[str, Any] | None = None,
        before_frame: Frame | None,
        after_frame: Frame | None,
        loop_action: LoopAction,
        at_s: float | None = None,
    ) -> dict[str, Any] | None:
        at_s = self.elapsed() if at_s is None else float(at_s)
        new_trace = self._read_trace()
        trace_row = new_trace[-1] if new_trace else self._fallback_trace(
            med, phase_before, med.phase.name, loop_action.name, at_s
        )
        if not new_trace:
            self._append_trace(trace_row)
        phase_after = med.phase.name
        context = getattr(med, "_context_cache_value", None)
        after_state = _state_snapshot(med, context)
        if before_state is None:
            before_state = self._last_state or dict(after_state)
        action = _action_from_tick(med, self.inputs_this_tick)
        if self._pending_event_index is not None:
            pending_event = self.manifest["events"][self._pending_event_index]
            pending_base = _postcondition_snapshot(
                med,
                pending_event["fsm_after"],
                after_state,
                pending_event.get("action"),
                trace_row,
            )
            pending_postcondition = _target_postcondition_snapshot(
                str(self.manifest["target"]),
                med,
                before_frame,
                after_state,
                pending_event.get("action"),
                pending_base,
            )
            generic_transition = _postcondition_transition_observed(
                pending_event["fsm_after"], after_state, trace_row
            )
            target_observed = pending_postcondition.get("observed") is True
            if generic_transition or target_observed:
                pending_event["postcondition"] = {
                    "observed": target_observed,
                    "state": "confirmed" if target_observed else "transition_not_target_pass",
                    "kind": pending_postcondition.get("kind") or pending_event.get("postcondition", {}).get("kind") or "state_transition",
                    "generic_transition_observed": generic_transition,
                    "confirmed_at_s": round(at_s, 3),
                    "confirmed_by_event": f"e{self._event_number:04d}",
                }
                if target_observed:
                    self._record_authoritative_target_result(
                        event_id=pending_event.get("event_id"),
                        postcondition=pending_event["postcondition"],
                        target_stage=pending_event.get("target_stage"),
                    )
                self._pending_event_index = None
                self._write_manifest()
        state_changed = self._last_state is None or before_state != after_state
        should_save = self._last_state is None or bool(self.inputs_this_tick) or state_changed or loop_action is LoopAction.Break
        self._last_state = after_state
        if not should_save:
            return None
        before_id = self._save_frame(before_frame, "action_before" if action else "state_change", at_s)
        after_id = None
        if action is not None:
            after_id = self._save_frame(after_frame, "action_after", max(at_s, self.elapsed()))
        input_record = self.inputs_this_tick[0] if self.inputs_this_tick else None
        input_result = None
        if input_record is not None:
            input_result = {
                "success": input_record.get("success"),
                "status": input_record.get("status"),
                "message": input_record.get("message"),
            }
        evidence = _evidence_snapshot(med, before_frame)
        postcondition = _target_postcondition_snapshot(
            str(self.manifest["target"]),
            med,
            after_frame or before_frame,
            after_state,
            action,
            _postcondition_snapshot(med, before_state, after_state, action, trace_row),
        )
        event = {
            "event_id": f"e{self._event_number:04d}",
            "at_s": round(at_s, 3),
            "kind": "action" if action else "state_change",
            "phase_before": phase_before,
            "phase_after": phase_after,
            "loop_action": loop_action.name,
            "frame_before": before_id,
            "frame_after": after_id,
            "frame_unchanged": bool(before_id and after_id and before_id == after_id),
            "action": action,
            "input": input_record,
            "input_result": input_result,
            "fsm_before": before_state,
            "fsm_after": after_state,
            "fsm_state": after_state,
            "evidence": evidence,
            "postcondition": postcondition,
            "target_stage": _stage_from_observation(
                str(self.manifest["target"]),
                after_state,
                evidence,
                action,
                postcondition,
            ),
            "trace_tail": list(self._recent_trace),
            "recent_trace": list(self._recent_trace),
        }
        self._event_number += 1
        self.manifest["events"].append(_jsonable(event))
        if event["postcondition"].get("observed") is True:
            self._record_authoritative_target_result(
                event_id=event["event_id"],
                postcondition=event["postcondition"],
                target_stage=event["target_stage"],
            )
        if action is not None and event["postcondition"].get("observed") is not True:
            self._pending_event_index = len(self.manifest["events"]) - 1
        self._write_manifest()
        return event

    def record_direct(
        self,
        med: Mediator,
        *,
        phase_before: str,
        before_state: dict[str, Any] | None = None,
        frame: Frame | None,
        result: LoopAction,
        at_s: float | None = None,
    ) -> dict[str, Any] | None:
        """Record a target probe without introducing a second decision path."""
        return self.record_tick(
            med,
            phase_before=phase_before,
            before_state=before_state,
            before_frame=frame,
            after_frame=_capture_after(med) if self.inputs_this_tick else None,
            loop_action=result if isinstance(result, LoopAction) else LoopAction.Continue,
            at_s=at_s,
        )

    def _write_manifest(self) -> None:
        payload = dict(self.manifest)
        payload["frame_count"] = len(self.manifest["frames"])
        payload["event_count"] = len(self.manifest["events"])
        payload["recent_trace"] = list(self._recent_trace)
        self.manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def finalize(self) -> Path:
        self._read_trace()
        self.manifest["completed_at_utc"] = _utc_now()
        self._write_manifest()
        return self.manifest_path


def _capture_after(med: Mediator) -> Frame | None:
    """Capture once after an input; ordinary no-action ticks never call this."""
    try:
        return _copy_frame(capture(med._capture_title(), role=_role_for_phase(med.phase), activate=False))
    except Exception:
        return _copy_frame(getattr(med, "_last_frame", None))


BUILD_IDENTITY_FILENAME = "build_identity.json"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_worktree_clean(repo_root: Path) -> bool | None:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return not bool(result.stdout.strip())


def _build_identity_check(
    *,
    repo_root: Path,
    automation_exe: Path | None,
    build_identity_path: Path | None = None,
    source_sha: str | None = None,
    source_clean: bool | None = None,
) -> dict[str, Any]:
    """Compare the actual packaged EXE with its build-time source identity.

    A live-input session must not infer this identity from a version label. The
    build sidecar is emitted by ``build_release.ps1`` and pins both the source
    commit and the actual EXE SHA-256.
    """
    tested_sha = source_sha or _commit_sha(repo_root)
    worktree_clean = _git_worktree_clean(repo_root) if source_clean is None else source_clean
    record: dict[str, Any] = {
        "status": "BLOCKED",
        "tested_source_sha": tested_sha,
        "source_worktree_clean": worktree_clean,
        "expected_build_id": BUILD_ID,
        "automation_exe": None,
        "build_identity_path": None,
        "blocked_reasons": [],
    }
    reasons: list[str] = record["blocked_reasons"]
    if tested_sha == "unknown":
        reasons.append("tested source SHA unavailable")
    if worktree_clean is not True:
        reasons.append("tested source worktree is not clean")
    if automation_exe is None:
        reasons.append("--automation-exe is required for --live-input")
        return record

    exe_path = Path(automation_exe).resolve()
    record["automation_exe"] = str(exe_path)
    if not exe_path.is_file():
        reasons.append(f"automation EXE not found: {exe_path}")
        return record
    try:
        actual_hash = _sha256_file(exe_path)
    except OSError as exc:
        reasons.append(f"cannot hash automation EXE: {exc}")
        return record
    record["actual_exe_sha256"] = actual_hash

    identity_path = (
        Path(build_identity_path).resolve()
        if build_identity_path is not None
        else exe_path.parent / BUILD_IDENTITY_FILENAME
    )
    record["build_identity_path"] = str(identity_path)
    if not identity_path.is_file():
        reasons.append(f"build identity sidecar missing: {identity_path}")
        return record
    try:
        identity = json.loads(identity_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError) as exc:
        reasons.append(f"build identity sidecar unreadable: {exc}")
        return record
    if not isinstance(identity, dict):
        reasons.append("build identity sidecar is not a JSON object")
        return record
    record["build_identity"] = _scrub(identity)
    identity_sha = str(identity.get("source_sha") or identity.get("tested_source_sha") or "")
    identity_hash = str(identity.get("exe_sha256") or "").lower()
    identity_build_id = str(identity.get("build_id") or "")
    if not identity_sha:
        reasons.append("build identity has no source_sha")
    elif identity_sha != tested_sha:
        reasons.append(f"source/EXE identity mismatch: source={tested_sha} exe={identity_sha}")
    if not identity_hash:
        reasons.append("build identity has no exe_sha256")
    elif identity_hash != actual_hash.lower():
        reasons.append("actual EXE hash does not match build identity")
    if not identity_build_id:
        reasons.append("build identity has no build_id")
    elif identity_build_id != BUILD_ID:
        reasons.append(f"source/EXE build_id mismatch: source={BUILD_ID} exe={identity_build_id}")
    if identity.get("source_tree_clean") is not True:
        reasons.append("build identity does not attest a clean source worktree")
    if not reasons:
        record["status"] = "READY"
    return record


def _window_preflight(settings: Settings) -> tuple[Frame | None, dict[str, Any]]:
    title = str(getattr(settings, "window_title_contains", "") or "")
    try:
        frame = capture(title, role="l1", activate=False)
    except Exception as exc:
        return None, {
            "status": "BLOCKED",
            "requested_title": title,
            "reason": f"window capture exception: {exc}",
        }
    record = {
        "status": "READY" if _frame_is_valid(frame) else "BLOCKED",
        "requested_title": title,
        "hwnd": getattr(frame, "hwnd", None),
        "title": getattr(frame, "window_title", ""),
        "size": [getattr(frame, "width", 0), getattr(frame, "height", 0)],
        "frame_fingerprint": _frame_fingerprint(frame),
        "reason": getattr(frame, "error", None),
    }
    return frame, record


def _ocr_bootstrap_preflight(med: Mediator) -> dict[str, Any]:
    prepare = getattr(med, "prepare_live_dependencies", None)
    if not callable(prepare):
        return {
            "healthy": False,
            "stage": "runtime_mediator",
            "reason": "RuntimeMediator.prepare_live_dependencies unavailable",
        }
    try:
        healthy = bool(prepare())
    except Exception as exc:
        return {"healthy": False, "stage": "exception", "reason": str(exc)}
    health = getattr(med, "_ocr_bootstrap_health", None)
    record = dict(health) if isinstance(health, dict) else {}
    record["healthy"] = bool(healthy and record.get("healthy", healthy))
    if not record.get("healthy") and not record.get("reason"):
        record["reason"] = "OCR bootstrap health unavailable"
    return _jsonable(record)


def _new_live_mediator(
    settings: Settings,
    repo_root: Path,
    stop_signal: StopSignal,
    incident_dir: Path,
) -> tuple[Mediator, str | None]:
    """Use the existing production RuntimeMediator for real-input sessions."""
    try:
        from shuabao.runtime_mediator import Mediator as RuntimeMediator

        return RuntimeMediator(settings, repo_root, stop_signal=stop_signal, incident_dir=incident_dir), None
    except Exception as exc:
        # The core mediator is only a container for the precheck evidence. The
        # RuntimeMediator load error itself blocks all real inputs below.
        return Mediator(settings, repo_root, stop_signal=stop_signal, incident_dir=incident_dir), str(exc)


def _live_input_preflight(
    *,
    args: argparse.Namespace,
    med: Mediator,
    settings: Settings,
    repo_root: Path,
    runtime_mediator_error: str | None,
) -> tuple[dict[str, Any], LiveLane | None, Frame | None]:
    """Gather every mandatory live-input fact before dispatching a handler."""
    identity = _build_identity_check(
        repo_root=repo_root,
        automation_exe=getattr(args, "automation_exe", None),
        build_identity_path=getattr(args, "build_identity", None),
    )
    frame, window = _window_preflight(settings)
    ocr_health = _ocr_bootstrap_preflight(med) if runtime_mediator_error is None else {
        "healthy": False,
        "stage": "runtime_mediator",
        "reason": runtime_mediator_error,
    }
    reasons = list(identity.get("blocked_reasons") or [])
    if not bool(ocr_health.get("healthy")):
        reasons.append(f"ocr_bootstrap_unhealthy: {ocr_health.get('reason') or ocr_health.get('stage')}")
    if window.get("status") != "READY":
        reasons.append(f"game window unavailable: {window.get('reason') or window.get('requested_title')}")

    lane: LiveLane | None = None
    single_instance: dict[str, Any] = {
        "status": "NOT_ACQUIRED",
        "lock_path": str(LiveLane("live_scenario_capture").path),
    }
    if not reasons:
        lane = LiveLane("live_scenario_capture")
        single_instance["lock_path"] = str(lane.path)
        try:
            lane.acquire()
        except LiveLaneBusy as exc:
            reasons.append(f"single-instance busy: {exc}")
            single_instance.update({"status": "BLOCKED", "reason": str(exc)})
            lane = None
        else:
            single_instance.update({"status": "READY", "owner": lane.owner})
    else:
        single_instance["reason"] = "not acquired because an earlier precheck failed"

    return ({
        "status": "READY" if not reasons else "BLOCKED_PRECHECK",
        "tested_source_sha": _commit_sha(repo_root),
        "actual_exe": identity,
        "settings_snapshot": _settings_snapshot(settings),
        "ocr_bootstrap_health": ocr_health,
        "window": window,
        "single_instance": single_instance,
        "blocked_reasons": reasons,
    }, lane, frame)


def _close_live_ocr(med: Mediator) -> None:
    client = getattr(med, "_ocr_client", None)
    if client is not None:
        try:
            client.close()
        except Exception:
            pass


def _install_action_reason_bridge(med: Mediator) -> Callable[[], str]:
    """Make the production action reason visible to the test-side executor guard."""
    setattr(med, "_live_capture_action_reason", "")
    for method_name in ("act_click", "act_right_click", "act_key"):
        original = getattr(med, method_name)

        def guarded(*args: Any, _original: Callable[..., Any] = original, **kwargs: Any) -> Any:
            reason = kwargs.get("reason")
            if reason is None and len(args) >= 2:
                reason = args[1]
            setattr(med, "_live_capture_action_reason", str(reason or ""))
            try:
                return _original(*args, **kwargs)
            finally:
                setattr(med, "_live_capture_action_reason", "")

        setattr(med, method_name, guarded)
    return lambda: str(getattr(med, "_live_capture_action_reason", "") or "")


def _capture_input_guard(target: str, execution_mode: str) -> Callable[[str, str], str | None]:
    allowed = _probe_allowed_reasons(target)

    def guard(method: str, reason: str) -> str | None:
        if _ground_truth_only(target):
            return f"{target} production is BLOCKED; Ground Truth capture is zero-input"
        if execution_mode != "target_handler" or allowed is None:
            return None
        if reason not in allowed:
            return (
                f"{target} probe action {(reason or method)!r} is outside the allowed production "
                "action/reason set"
            )
        return None

    return guard


def _prepare_settings(path: Path | None, target: str, live_input: bool) -> Settings:
    settings = Settings.load(path) if path else Settings()
    # A Ground Truth-only target remains zero-input even when an operator
    # accidentally supplied --live-input. Never turn a production flag on in
    # the adapter; the recorded settings must be the operator's real settings.
    settings.dry_run = not live_input or _ground_truth_only(target)
    return settings


def _bootstrap_target_probe(med: Mediator, target: str) -> dict[str, Any]:
    """Seed only the existing production state required to enter a target mid-flow.

    The values are not a replacement FSM and never select/click anything.  They
    let an operator place the game at an already-open post-game target while
    retaining the exact production handler for all subsequent decisions.
    """
    if target != "secret_realm":
        return {}
    now = time.time()
    med._post_game_pending = True
    med._secret_realm_request_pending = True
    med._secret_realm_request_since = now
    med._secret_realm_next_observe_at = 0.0
    med._secret_realm_confirm_next_observe_at = 0.0
    return {
        "post_game_pending": True,
        "secret_realm_request_pending": True,
        "secret_realm_request_since": "probe_start",
        "reason": "existing _tick_main_line requires post-game state before NPC_HUB/confirmation handling",
    }


def _require_live_confirmation(live_input: bool, confirmed: bool) -> None:
    if live_input and not confirmed:
        raise ValueError("启用 --live-input 必须同时传 --confirm-live-input；默认 probe/capture 为 dry-run")


def _is_emergency_reason(reason: str | None) -> bool:
    text = str(reason or "").lower()
    return "emergency" in text or "shift+f12" in text or "f12 emergency" in text


def _resume_after_manual_intervention(med: Mediator) -> None:
    """Resume the observation loop only after an explicit manual bookmark."""
    med.stop_signal.reset()
    med.set_phase(Phase.MAIN_LINE, "manual evidence continuation")
    med._running = True


def _append_bookmark_command(
    bundle_dir: Path,
    status: str,
    note: str = "",
    command_file: Path | None = None,
) -> Path:
    status = str(status).strip().upper()
    if status not in BOOKMARK_STATUSES:
        raise ValueError(f"未知 evidence bookmark: {status}")
    bundle_dir = Path(bundle_dir).resolve()
    if not bundle_dir.is_dir():
        raise ValueError(f"bundle 不存在或尚未启动: {bundle_dir}")
    path = Path(command_file).resolve() if command_file else bundle_dir / "bookmark.commands"
    path.parent.mkdir(parents=True, exist_ok=True)
    clean_note = str(note).replace("\r", " ").replace("\n", " ").strip()
    with path.open("a", encoding="utf-8") as fh:
        fh.write(status + (f"|{clean_note}" if clean_note else "") + "\n")
    return path


def _run_live_capture(args: argparse.Namespace, *, probe: bool = False) -> Path:
    target = args.target
    contract = _target_contract(target)
    _require_live_confirmation(args.live_input, args.confirm_live_input)
    repo_root = Path(args.repo_root).resolve()
    settings = _prepare_settings(Path(args.settings) if args.settings else None, target, args.live_input)
    output_root = Path(args.out).resolve()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    bundle_dir = output_root / f"{target}_{stamp}"
    stop_signal = StopSignal()
    execution_mode = (
        "ground_truth_only"
        if _ground_truth_only(target)
        else ("target_handler" if probe else "mediator_tick")
    )
    runtime_mediator_error: str | None = None
    if args.live_input:
        med, runtime_mediator_error = _new_live_mediator(
            settings,
            repo_root,
            stop_signal,
            bundle_dir / "incidents",
        )
    else:
        med = Mediator(settings, repo_root, stop_signal=stop_signal, incident_dir=bundle_dir / "incidents")
    med.set_phase(Phase.MAIN_LINE, f"{target} {'target probe' if probe else 'live capture'}")
    probe_bootstrap = _bootstrap_target_probe(med, target) if probe and execution_mode == "target_handler" else {}
    recorder = BundleRecorder(
        bundle_dir,
        repo_root=repo_root,
        target=target,
        settings=settings,
        initial_phase=med.phase.name,
        execution_mode=execution_mode,
    )
    if probe_bootstrap:
        recorder.manifest["probe_bootstrap"] = probe_bootstrap
    if execution_mode == "ground_truth_only":
        recorder.manifest["ground_truth_capture"] = {
            "reason": _production_fact(target)["scope"],
            "zero_input_guard": True,
        }

    live_lane: LiveLane | None = None
    preflight_frame: Frame | None = None
    if args.live_input:
        preflight, live_lane, preflight_frame = _live_input_preflight(
            args=args,
            med=med,
            settings=settings,
            repo_root=repo_root,
            runtime_mediator_error=runtime_mediator_error,
        )
        recorder.record_preflight(preflight)
    else:
        recorder.record_preflight({
            "status": "NOT_REQUESTED",
            "tested_source_sha": _commit_sha(repo_root),
            "settings_snapshot": _settings_snapshot(settings),
            "reason": "dry-run or Ground Truth capture without --live-input",
        })

    guard_events: list[dict[str, str]] = []

    def on_guard(method: str, reason: str, denial: str) -> None:
        guard_events.append({"method": method, "reason": reason, "denial": denial})

    reason_provider = _install_action_reason_bridge(med)
    med.executor = RecordingInputExecutor(
        med.executor,
        recorder.record_input,
        reason_provider=reason_provider,
        input_guard=_capture_input_guard(target, execution_mode),
        on_guard=on_guard,
    )
    recorder.start_trace(med)
    bookmark_file = (
        Path(getattr(args, "bookmark_file", None)).resolve()
        if getattr(args, "bookmark_file", None)
        else bundle_dir / "bookmark.commands"
    )
    bookmark_reader = BookmarkCommandReader(bookmark_file)
    awaiting_manual_resume = False
    requested_duration = float(getattr(args, "duration", 60.0))
    duration_s = max(0.0, requested_duration)
    if probe:
        duration_s = min(duration_s, float(contract["max_probe_time_s"]))
    deadline = time.monotonic() + duration_s
    ticks = 0
    original_see = med.see
    current_frame: dict[str, Frame | None] = {"value": None}
    live_preflight_blocked = bool(
        args.live_input
        and recorder.manifest.get("live_preflight", {}).get("status") == "BLOCKED_PRECHECK"
    )

    def capture_for_tick(reason: str = "") -> Frame:
        frame = original_see(reason)
        current_frame["value"] = _copy_frame(frame)
        return frame

    def process_bookmarks() -> None:
        nonlocal awaiting_manual_resume
        for status, note in bookmark_reader.poll():
            bookmark_frame = current_frame["value"] or _capture_after(med)
            recorder.bookmark(status, med, bookmark_frame, note=note)
            print(f"[bookmark] {status} {note}".rstrip())
            if (
                awaiting_manual_resume
                and status == "MANUAL_INTERVENTION"
                and not _is_emergency_reason(stop_signal.reason)
            ):
                _resume_after_manual_intervention(med)
                awaiting_manual_resume = False
                print("[capture] manual intervention recorded; observation loop resumed")

    print(
        f"[capture] bundle={bundle_dir} bookmark_file={bookmark_file} "
        "keys: p=PASS f=FAIL m=MANUAL_INTERVENTION"
    )
    med.see = capture_for_tick
    try:
        if live_preflight_blocked:
            current_frame["value"] = _copy_frame(preflight_frame)
            recorder.begin_tick()
            if _frame_is_valid(current_frame["value"]):
                recorder.record_direct(
                    med,
                    phase_before=med.phase.name,
                    before_state=_state_snapshot(med),
                    frame=current_frame["value"],
                    result=LoopAction.Continue,
                    at_s=0.0,
                )
            note = "; ".join(recorder.manifest["live_preflight"].get("blocked_reasons") or [])
            recorder.record_blocked(
                med,
                current_frame["value"],
                status="BLOCKED_PRECHECK",
                note=f"live input refused before target handler: {note}",
            )
            print("[preflight] BLOCKED_PRECHECK; no business handler or game input was attempted")
            return bundle_dir

        med.emergency_listener = EmergencyStopListener(stop_signal)
        med.emergency_listener.start()
        while ticks < args.max_ticks and time.monotonic() <= deadline:
            process_bookmarks()
            if awaiting_manual_resume:
                if _is_emergency_reason(stop_signal.reason):
                    break
                time.sleep(min(0.2, max(0.01, float(args.interval))))
                continue
            recorder.begin_tick()
            phase_before = med.phase.name
            state_before = _state_snapshot(med)
            current_frame["value"] = None
            if execution_mode == "ground_truth_only":
                # BLOCKED production routes are observable, but deliberately
                # never dispatched. This is not a second production path.
                med._tick_no += 1
                med._trace_actions = []
                med._trace_scenes = []
                med._trace_controls = []
                med._trace_ocr_suggestion = None
                med.see("ground truth capture")
                loop_action = LoopAction.Continue
                recorder.record_direct(
                    med,
                    phase_before=phase_before,
                    before_state=state_before,
                    frame=current_frame["value"],
                    result=loop_action,
                )
            elif probe:
                # Only the selected production handler is invoked here.
                med._tick_no += 1
                med._trace_actions = []
                med._trace_scenes = []
                med._trace_controls = []
                med._trace_ocr_suggestion = None
                frame = med.see("target live probe")
                if not _frame_is_valid(frame):
                    loop_action = LoopAction.Continue
                else:
                    result = _invoke_target_handler(med, target, frame)
                    loop_action = result if isinstance(result, LoopAction) else LoopAction.Continue
                recorder.record_direct(
                    med,
                    phase_before=phase_before,
                    before_state=state_before,
                    frame=current_frame["value"],
                    result=loop_action,
                )
            else:
                loop_action = med.tick()
                recorder.record_tick(
                    med,
                    phase_before=phase_before,
                    before_state=state_before,
                    before_frame=current_frame["value"],
                    after_frame=_capture_after(med) if recorder.inputs_this_tick else None,
                    loop_action=loop_action,
                )
            if not _frame_is_valid(current_frame["value"]):
                recorder.record_blocked(
                    med,
                    current_frame["value"],
                    note="capture returned no valid frame; no more target input was attempted",
                )
                break
            if guard_events:
                blocked = guard_events[-1]
                recorder.record_blocked(
                    med,
                    current_frame["value"],
                    note=(
                        f"zero-input guard blocked {blocked['method']} "
                        f"reason={blocked['reason']!r}: {blocked['denial']}"
                    ),
                )
            if loop_action is LoopAction.Break:
                if med.phase is not Phase.ERROR:
                    break
                failure_reason = (
                    getattr(med, "_interrupt_reason", None)
                    or getattr(med, "_tick_reason", None)
                    or stop_signal.reason
                    or "Mediator returned Break"
                )
                recorder.bookmark(
                    "FAIL",
                    med,
                    current_frame["value"],
                    note=f"automatic Mediator failure: {failure_reason}",
                )
                if (
                    getattr(args, "continue_after_failure", False)
                    and not _is_emergency_reason(stop_signal.reason)
                ):
                    awaiting_manual_resume = True
                    print(
                        "[capture] failure evidence saved; waiting for "
                        "MANUAL_INTERVENTION bookmark to resume"
                    )
                else:
                    break
            process_bookmarks()
            ticks += 1
            if stop_signal.is_set() and not awaiting_manual_resume:
                break
            if args.interval > 0:
                time.sleep(float(args.interval))
        if (
            probe
            and execution_mode == "target_handler"
            and time.monotonic() >= deadline
            and not recorder.manifest["target_result"].get("authoritative")
            and not recorder.manifest["automatic_failures"]
            and not _is_emergency_reason(stop_signal.reason)
        ):
            recorder.bookmark(
                "FAIL",
                med,
                current_frame["value"],
                note=(
                    f"target probe timeout after {duration_s:.1f}s; "
                    "no operator PASS bookmark was recorded"
                ),
            )
    finally:
        if med.emergency_listener:
            med.emergency_listener.stop()
            med.emergency_listener = None
        recorder.stop_trace(med)
        recorder.manifest["capture_ticks"] = ticks
        recorder.manifest["capture_options"] = {
            "duration_s": duration_s,
            "max_probe_time_s": float(contract["max_probe_time_s"]),
            "interval_s": float(args.interval),
            "requested_live_input": bool(args.live_input),
            "effective_live_input": bool(args.live_input and not _ground_truth_only(target)),
            "execution_mode": execution_mode,
            "production_readiness": _production_fact(target)["production_readiness"],
            "bookmark_file": str(bookmark_file),
            "continue_after_failure": bool(getattr(args, "continue_after_failure", False)),
        }
        recorder.finalize()
        if live_lane is not None:
            live_lane.release()
        _close_live_ocr(med)
    if getattr(args, "generate", False):
        try:
            generated = generate_cases(bundle_dir, repo_root=repo_root)
        except ValueError as exc:
            print(f"[capture] replay cases not generated: {exc}")
        else:
            print(f"[capture] generated {len(generated)} replay case(s) under {bundle_dir / 'cases'}")
    print(f"[capture] bundle={bundle_dir} events={len(recorder.manifest['events'])} frames={len(recorder.manifest['frames'])}")
    return bundle_dir


def _case_file(bundle_dir: Path, frame_record: dict[str, Any], repo_root: Path) -> str:
    absolute = (bundle_dir / str(frame_record["file"])).resolve()
    try:
        return absolute.relative_to(repo_root).as_posix()
    except ValueError:
        return str(absolute)


def _load_manifest(bundle_dir: Path) -> dict[str, Any]:
    path = Path(bundle_dir) / "manifest.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("capture_schema_version") != 1:
        raise ValueError(f"不支持的 capture bundle: {path}")
    if not isinstance(raw.get("events"), list) or not raw["events"]:
        raise ValueError(f"bundle 没有可生成 case 的事件: {path}")
    return raw


def _replay_settings(manifest: dict[str, Any], variant: str | None) -> dict[str, Any]:
    known = set(Settings.__dataclass_fields__)
    settings = {k: v for k, v in (manifest.get("settings") or {}).items() if k in known}
    settings["dry_run"] = True
    settings["ocr_mode"] = "off"
    if variant == "timeout":
        settings["round_timeout_s"] = 1
    return settings


def _timeline(
    bundle_dir: Path,
    manifest: dict[str, Any],
    repo_root: Path,
    variant: str | None,
) -> list[FrameSpec]:
    frame_map = {str(f["id"]): f for f in manifest.get("frames", [])}
    specs: list[FrameSpec] = []
    previous_at = 0.0
    for index, event in enumerate(manifest["events"]):
        before_id = event.get("frame_before")
        before = frame_map.get(str(before_id))
        if before is None:
            raise ValueError(f"事件 {event.get('event_id')} 缺少 frame_before={before_id}")
        at_s = max(previous_at, float(event.get("at_s", 0.0)))
        if specs and at_s == previous_at:
            at_s += 0.001
        control = event.get("control") or {"stop_signal": "unchanged", "before_action": None}
        specs.append(FrameSpec(
            id=f"{event.get('event_id', index)}_before",
            at_s=round(at_s, 3),
            file=_case_file(bundle_dir, before, repo_root),
            window_title=before.get("window_title"),
            hwnd=before.get("hwnd"),
            left=int(before.get("left", 0) or 0),
            top=int(before.get("top", 0) or 0),
            capture_role=before.get("capture_role", "l1"),
            control=control,
        ))
        previous_at = at_s
        if (
            event.get("action") is None
            and event.get("input") is None
            and event.get("input_result") is None
        ):
            continue
        after_id = event.get("frame_after") or before_id
        if variant in {"postcondition_missing", "frame_unchanged"}:
            after_id = before_id
        after = frame_map.get(str(after_id)) or before
        after_at = max(previous_at + 0.1, float(event.get("after_at_s", previous_at + 0.1)))
        specs.append(FrameSpec(
            id=f"{event.get('event_id', index)}_after",
            at_s=round(after_at, 3),
            file=_case_file(bundle_dir, after, repo_root),
            window_title=after.get("window_title"),
            hwnd=after.get("hwnd"),
            left=int(after.get("left", 0) or 0),
            top=int(after.get("top", 0) or 0),
            capture_role=after.get("capture_role", "l1"),
            control={"stop_signal": "unchanged", "before_action": None},
        ))
        previous_at = after_at
    if variant == "timeout" and specs:
        # A timeout branch must contain an observation after the hard deadline;
        # otherwise a short successful sample would silently produce no
        # timeout at all.
        last = specs[-1]
        timeout_at = max(last.at_s + 1.1, specs[0].at_s + 1.1)
        specs.append(FrameSpec(
            id="timeout_after_deadline",
            at_s=round(timeout_at, 3),
            file=last.file,
            window_title=last.window_title,
            hwnd=last.hwnd,
            left=last.left,
            top=last.top,
            capture_role=last.capture_role,
            control={"stop_signal": "unchanged", "before_action": None},
        ))
    return specs


def _actual_action(records: list[Any], probes: list[Any]) -> dict[str, Any] | None:
    if not records:
        return None
    record = records[0]
    probe = probes[0] if probes else None
    action: dict[str, Any] = {
        "kind": record.method,
        "reason": getattr(probe, "reason", "") if probe else "",
        "target": getattr(probe, "target", None) if probe else None,
        "input_kind": _INPUT_KIND.get(record.method, record.method),
    }
    if record.method in {"click", "right_click", "scroll"} and len(record.args) >= 2:
        action["point"] = [int(record.args[0]), int(record.args[1])]
    return action


def _observe_case(case: Case, repo_root: Path, variant: str | None) -> tuple[list[ExpectAction], str]:
    """Observe a case with the existing fake harness and return its contract."""
    loader = ReplayCaseLoader(repo_root)
    frames = loader.load_frames(case)
    clock = FakeClock(start=case.frames[0].at_s)
    stop_signal = StopSignal()
    expectations: list[ExpectAction] = []
    rejected_queued = False
    rejected_used = False
    with clock.install():
        settings = Settings()
        for key, value in case.settings_overrides.items():
            setattr(settings, key, value)
        med = Mediator(settings, repo_root, stop_signal=stop_signal)
        med.set_phase(Phase[case.phase], "generated case observation")
        executor = FakeInputExecutor(stop_signal, clock)
        med.executor = executor
        source = ReplayFrameSource(frames)
        med._capture_best = source.capture_best
        action_probe = ActionProbe(med)
        context_probe = ContextProbe(med)
        for index, (spec, _frame) in enumerate(zip(case.frames, frames)):
            clock.set(spec.at_s)
            ScenarioRunner._apply_control(spec.control, stop_signal, executor)
            executor.begin_tick(index)
            action_probe.begin_tick(index)
            context_probe.begin_tick(index)
            source.begin_tick(index)
            if variant == "click_rejected" and not rejected_used and not rejected_queued:
                executor.inject_next("SENDINPUT_FAILED")
                rejected_queued = True
            phase_before = med.phase.name
            loop_action = med.tick()
            seen = context_probe.contexts_since_tick_start()
            context = seen[0] if seen else "STOP_SIGNAL"
            records = executor.records_since_tick_start()
            probes = action_probe.records_since_tick_start()
            if len(records) > 1:
                raise ValueError(f"生成 case 发现同一 tick 多于一个输入: {case.case} f{index}")
            action = _actual_action(records, probes)
            action_result = None
            injection = None
            if records:
                result = records[0].result
                action_result = {"success": result.success, "status": result.status}
                if result.status == "CANCELLED_SENDINPUT_FAILED":
                    rejected_used = True
                    injection = "SENDINPUT_FAILED"
            expectations.append(ExpectAction(
                phase_before=phase_before,
                context=context,
                action_count=len(records),
                action=action,
                action_result=action_result,
                phase_after=med.phase.name,
                loop_action=loop_action.name,
                input_injection=injection,
            ))
    return expectations, med.phase.name


def _expect_json(expectation: ExpectAction) -> dict[str, Any]:
    return {
        "phase_before": expectation.phase_before,
        "context": expectation.context,
        "action_count": expectation.action_count,
        "action": expectation.action,
        "action_result": expectation.action_result,
        "phase_after": expectation.phase_after,
        "loop_action": expectation.loop_action,
        "input_injection": expectation.input_injection,
    }


def _safe_case_name(name: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("._")
    if not clean:
        raise ValueError("case name 不能为空")
    return clean


def generate_cases(
    bundle_dir: Path,
    *,
    repo_root: Path = ROOT,
    case_name: str | None = None,
    variants: tuple[str, ...] | None = None,
) -> list[Path]:
    """Generate schema-v1 cases and runnable failure branches from one bundle."""
    bundle_dir = Path(bundle_dir).resolve()
    manifest = _load_manifest(bundle_dir)
    target_name = _safe_case_name(case_name or str(manifest.get("target") or "live_scenario"))
    selected_variants = FAILURE_VARIANTS if variants is None else tuple(variants)
    unknown = set(selected_variants) - set(FAILURE_VARIANTS)
    if unknown:
        raise ValueError(f"未知失败变体: {sorted(unknown)}")
    selected = ("baseline",) + selected_variants
    output_root = bundle_dir / "cases"
    output_root.mkdir(parents=True, exist_ok=True)
    verification = manifest.get("verification") or {}
    generated: list[Path] = []
    generated_records: list[dict[str, Any]] = []
    for variant_name in selected:
        variant = None if variant_name == "baseline" else variant_name
        name = target_name if variant is None else f"{target_name}__{variant_name}"
        name = _safe_case_name(name)
        case_dir = output_root / name
        case_dir.mkdir(parents=True, exist_ok=True)
        frame_specs = _timeline(bundle_dir, manifest, repo_root, variant)
        if not frame_specs:
            raise ValueError(f"bundle 没有帧: {bundle_dir}")
        settings = _replay_settings(manifest, variant)
        provisional = Case(
            schema_version=1,
            case=name,
            description=f"Live capture {manifest.get('bundle_id')} target={manifest.get('target')} variant={variant_name}",
            phase=str(manifest.get("initial_phase") or manifest["events"][0].get("phase_before") or "MAIN_LINE"),
            settings_overrides=settings,
            frames=frame_specs,
            expect_actions=[],
            final_phase="MAIN_LINE",
            path=case_dir / "case.json",
        )
        expectations, final_phase = _observe_case(provisional, repo_root, variant)
        payload = {
            "schema_version": 1,
            "case": name,
            "description": provisional.description,
            "phase": provisional.phase,
            "settings_overrides": settings,
            "frames": [
                {
                    "id": spec.id,
                    "at_s": spec.at_s,
                    "file": spec.file,
                    "window_title": spec.window_title,
                    "hwnd": spec.hwnd,
                    "left": spec.left,
                    "top": spec.top,
                    "capture_role": spec.capture_role,
                    "control": spec.control,
                }
                for spec in frame_specs
            ],
            "expect_actions": [_expect_json(item) for item in expectations],
            "final_phase": final_phase,
            "capture": {
                "bundle": str(bundle_dir),
                "tested_commit_sha": manifest.get("tested_commit_sha"),
                "target": manifest.get("target"),
                "failure_variant": variant,
                "natural_e2e": verification.get("natural_e2e", "REQUIRED_LIVE_PASS"),
                "natural_e2e_eligible": bool(verification.get("natural_e2e_eligible", True)),
                "ground_truth_collection": "ELIGIBLE",
            },
            "failure_simulation": {
                "kind": variant,
                "strategy": {
                    None: "recorded successful path",
                    "click_rejected": "inject SENDINPUT_FAILED at first action",
                    "postcondition_missing": "reuse action-before pixels as action-after",
                    "frame_unchanged": "reuse action-before pixels as action-after",
                    "timeout": "set round_timeout_s=1 and replay a bounded trace",
                }[variant],
            },
        }
        path = case_dir / "case.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        generated.append(path)
        generated_records.append({
            "case": name,
            "variant": variant,
            "path": str(path),
            "final_phase": final_phase,
        })
    generated_names = {str(row["case"]) for row in generated_records}
    manifest["generated_cases"] = [
        row for row in manifest.get("generated_cases", [])
        if str(row.get("case")) not in generated_names
    ]
    manifest["generated_cases"].extend(generated_records)
    manifest["verification"]["frozen_replay"] = "PENDING"
    (bundle_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return generated


def replay_cases(case_dirs: list[Path], repo_root: Path) -> int:
    runner = ScenarioRunner(repo_root)
    failures = 0
    for case_dir in case_dirs:
        try:
            runner.run_case(case_dir)
            print(f"[replay] PASS {case_dir}")
        except Exception as exc:  # preserve case context from the existing runner
            failures += 1
            print(f"[replay] FAIL {case_dir}: {exc}")
    bundle_dirs = {
        case_dir.resolve().parent.parent
        for case_dir in case_dirs
        if case_dir.resolve().parent.name == "cases"
    }
    if len(bundle_dirs) == 1:
        bundle_dir = next(iter(bundle_dirs))
        manifest_path = bundle_dir / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(manifest, dict):
                verification = manifest.setdefault("verification", {})
                verification["frozen_replay"] = "PASS" if failures == 0 else "FAIL"
                case_names = {case_dir.name for case_dir in case_dirs}
                for row in manifest.get("generated_cases", []):
                    if row.get("case") in case_names:
                        row["frozen_replay"] = "PASS" if failures == 0 else "FAIL"
                manifest_path.write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
        except (OSError, TypeError, ValueError):
            pass
    return failures


def reproduce_bundle(
    bundle_dir: Path,
    *,
    repo_root: Path = ROOT,
    variants: tuple[str, ...] = FAILURE_VARIANTS,
) -> int:
    """Generate then replay one bundle through the existing scenario harness."""
    generated = generate_cases(bundle_dir, repo_root=repo_root, variants=variants)
    print(f"[reproduce] generated {len(generated)} case(s) under {Path(bundle_dir) / 'cases'}")
    return replay_cases([path.parent for path in generated], repo_root)


def _synthetic_replay_self_check(repo_root: Path) -> tuple[bool, str]:
    """Exercise conversion and existing FakeClock/FakeInputExecutor without live capture."""
    source = repo_root / "fixtures" / "scenarios" / "stage_starting_env_hud" / "frames" / "env_hud_visible.png"
    if not source.exists():
        return False, f"missing synthetic replay source: {source}"
    with tempfile.TemporaryDirectory(prefix="shuabao_live_capture_readiness_") as temp_root:
        bundle = Path(temp_root) / "bundle"
        frames_dir = bundle / "frames"
        frames_dir.mkdir(parents=True)
        shutil.copy2(source, frames_dir / "env.png")
        manifest = {
            "capture_schema_version": 1,
            "bundle_id": "readiness_self_check",
            "target": "inventory_item",
            "initial_phase": "STAGE_STARTING",
            "settings": {"dry_run": True, "ocr_mode": "off"},
            "tested_commit_sha": _commit_sha(repo_root),
            "frames": [{
                "id": "env",
                "file": "frames/env.png",
                "capture_role": "l1",
                "window_title": "英雄三国KK",
                "hwnd": 10001,
                "left": 0,
                "top": 0,
            }],
            "events": [
                {"event_id": "e0", "at_s": 0.0, "frame_before": "env"},
                {"event_id": "e1", "at_s": 1.0, "frame_before": "env"},
            ],
            "generated_cases": [],
            "verification": {"frozen_replay": "PENDING", "natural_e2e": "REQUIRED_LIVE_PASS"},
        }
        (bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        try:
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                failures = reproduce_bundle(bundle, repo_root=repo_root)
        except (OSError, ValueError, KeyError) as exc:
            return False, f"replay conversion self-check failed: {exc}"
    return (failures == 0, "existing ReplayCaseLoader/FakeClock/FakeInputExecutor path passed" if failures == 0 else "generated replay case failed")


def _target_readiness_settings_gaps(target: str, settings: Settings | None) -> list[str]:
    """Optional production prerequisites; they never alter production settings."""
    if settings is None:
        return []
    if _ground_truth_only(target):
        return []
    if target == "black_merchant" and getattr(settings, "merchant_enabled", True) is False:
        return ["merchant_enabled=false"]
    if target == "black_merchant" and not getattr(settings, "auto_devour_dan", True):
        return ["auto_devour_dan=false (swallow-pill route disabled)"]
    if target == "inventory_item" and not getattr(settings, "auto_devour_dan", True):
        return ["auto_devour_dan=false (swallow-pill route disabled)"]
    if target == "boss_challenge" and not (str(settings.cjb_boss).strip() or str(settings.sgzx_boss).strip()):
        return ["configure exactly one cjb_boss or sgzx_boss"]
    if target == "secret_realm" and not settings.auto_secret_realm:
        return ["auto_secret_realm=false"]
    return []


def readiness_report(
    *,
    repo_root: Path = ROOT,
    settings: Settings | None = None,
    run_replay_self_check: bool = True,
) -> dict[str, Any]:
    """Report harness capability separately from production capability.

    ``HARNESS_READY`` proves only capture/bookmark/failure-summary/replay
    plumbing. It deliberately says nothing about whether production behavior
    is wired or authorized for a real input session.
    """
    repo_root = Path(repo_root).resolve()
    sha = _commit_sha(repo_root)
    replay_ok, replay_detail = (
        _synthetic_replay_self_check(repo_root)
        if run_replay_self_check
        else (True, "not run (--quick)")
    )
    shared_missing: list[str] = []
    if sha == "unknown":
        shared_missing.append("tested commit SHA unavailable")
    if not callable(capture):
        shared_missing.append("capture backend unavailable")
    if not callable(BundleRecorder.bookmark):
        shared_missing.append("bookmark writer unavailable")
    if not callable(_build_failure_summary):
        shared_missing.append("failure-summary writer unavailable")
    if not replay_ok:
        shared_missing.append(replay_detail)
    targets: list[dict[str, Any]] = []
    for target in SUPPORTED_TARGETS:
        contract = _target_contract(target)
        harness_missing = [field for field in TARGET_CONTRACT_FIELDS if not contract.get(field)]
        handler = str(contract.get("handler") or "")
        harness_missing.extend(shared_missing)
        harness_readiness = "READY" if not harness_missing else "PARTIAL"
        fact = _production_fact(target)
        production_readiness = str(fact["production_readiness"])
        production_entry_status = (
            "NOT_INVOKED_GROUND_TRUTH_ONLY"
            if _ground_truth_only(target)
            else ("PRESENT" if handler and hasattr(Mediator, handler) else "MISSING")
        )
        production_missing: list[str] = []
        if not _ground_truth_only(target) and production_entry_status == "MISSING":
            production_readiness = "BLOCKED"
            production_missing.append(f"production entry unavailable: {handler or 'missing handler'}")
        runtime_gaps = _target_readiness_settings_gaps(target, settings)
        targets.append({
            "target": target,
            "harness_readiness": harness_readiness,
            "harness_missing": harness_missing,
            "production_readiness": production_readiness,
            "production_scope": fact["scope"],
            "production_routes": _jsonable(fact["routes"]),
            "production_missing": production_missing,
            "production_prerequisites": runtime_gaps,
            "production_entry_status": production_entry_status,
            "ground_truth_only": _ground_truth_only(target),
            "production_entry": contract["production_entry"],
            "max_probe_time_s": contract["max_probe_time_s"],
            "capture": "READY" if callable(capture) else "MISSING",
            "bookmark": "READY" if callable(BundleRecorder.bookmark) else "MISSING",
            "tested_sha": sha,
            "failure_summary": "READY" if callable(_build_failure_summary) else "MISSING",
            "replay_conversion": "READY" if replay_ok else "MISSING",
        })
    return {
        "readiness_schema_version": 2,
        "repo_root": str(repo_root),
        "tested_commit_sha": sha,
        "replay_self_check": {"status": "PASS" if replay_ok else "FAIL", "detail": replay_detail},
        "live_input_preflight": {
            "status": "REQUIRED",
            "required_facts": (
                "tested_source_sha", "actual_exe_build_hash", "settings_snapshot",
                "ocr_bootstrap_health", "hwnd_title_size", "single_instance",
            ),
        },
        "targets": targets,
    }


def _print_readiness(report: dict[str, Any], *, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    print(f"[readiness] commit={report.get('tested_commit_sha')}")
    replay = report.get("replay_self_check") or {}
    print(f"[readiness] replay_self_check={replay.get('status')}: {replay.get('detail')}")
    print("TARGET             HARNESS_READINESS  PRODUCTION_READINESS  MAX_PROBE  SCOPE / GAPS")
    for item in report.get("targets") or []:
        details = (
            list(item.get("harness_missing") or [])
            + list(item.get("production_missing") or [])
            + list(item.get("production_prerequisites") or [])
        )
        detail = "; ".join(details) if details else "-"
        print(
            f"{str(item['target']):<18} {str(item['harness_readiness']):<18} "
            f"{str(item['production_readiness']):<21} "
            f"{float(item['max_probe_time_s']):>7.0f}s  {item['production_scope']}"
        )
        if detail != "-":
            print(f"{'':<18} {'':<18} {'':<21} {'':>7}  gaps: {detail}")


def _print_contracts(target: str | None = None, *, as_json: bool = False) -> None:
    selected = {target: _target_contract(target)} if target else TARGET_CONTRACTS
    if as_json:
        payload = {
            name: {
                **contract,
                "harness_semantics": "HARNESS_READY only proves capture/replay plumbing",
                "production_fact": _production_fact(name),
            }
            for name, contract in selected.items()
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=_jsonable))
        return
    for name, contract in selected.items():
        print(f"[{name}]")
        fact = _production_fact(name)
        print("HARNESS_SEMANTICS: HARNESS_READY only proves capture/replay plumbing")
        print(f"PRODUCTION_READINESS: {fact['production_readiness']}")
        print(f"PRODUCTION_SCOPE: {fact['scope']}")
        for field in TARGET_CONTRACT_FIELDS:
            value = contract[field]
            if isinstance(value, tuple):
                value = " -> ".join(value)
            label = "MAX_PROBE_TIME" if field == "max_probe_time_s" else field.upper()
            suffix = "s" if field == "max_probe_time_s" else ""
            print(f"{label}: {value}{suffix}")


def _print_runbook(target: str | None = None) -> None:
    targets = (target,) if target else SUPPORTED_TARGETS
    for name in targets:
        contract = _target_contract(name)
        fact = _production_fact(name)
        print(f"[{name}]")
        print(f"1. 手动做到：{contract['runbook_manual']}")
        if fact["production_readiness"] == "BLOCKED":
            print(
                "2. 执行：python tools/live_scenario_capture.py probe "
                f"--target {name} --out C:/tmp/shuabao-captures "
                f"--duration {int(contract['max_probe_time_s'])} --continue-after-failure --generate"
            )
        else:
            print(
                "2. 执行：python tools/live_scenario_capture.py probe "
                f"--target {name} --out C:/tmp/shuabao-captures "
                f"--duration {int(contract['max_probe_time_s'])} "
                "--automation-exe C:/path/to/ShuaBao.exe --live-input "
                "--confirm-live-input --continue-after-failure --generate"
            )
        print(f"3. 放手：{contract['runbook_hands_off']}")
        print(f"4. PASS：{contract['runbook_pass']}")
        print("5. 出错：按 f 留 FAIL（紧急停止仍为 Shift+F12）。")
        print(f"6. MANUAL_INTERVENTION：{contract['runbook_manual_intervention']}")


def _common_live_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--target", choices=SUPPORTED_TARGETS, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--settings", type=Path, default=None)
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--interval", type=float, default=0.3)
    parser.add_argument("--max-ticks", type=int, default=1000)
    parser.add_argument(
        "--bookmark-file",
        type=Path,
        default=None,
        help="bookmark command file; lines are STATUS or STATUS|note",
    )
    parser.add_argument(
        "--continue-after-failure",
        action="store_true",
        help="FAIL 后保留采集进程，等待 MANUAL_INTERVENTION 再恢复",
    )
    parser.add_argument("--live-input", action="store_true", help="允许真实输入；默认 dry-run")
    parser.add_argument("--confirm-live-input", action="store_true", help="与 --live-input 联用的显式安全确认")
    parser.add_argument(
        "--automation-exe",
        type=Path,
        default=None,
        help="真实生产 ShuaBao.exe；--live-input 时必须与 build_identity.json 匹配",
    )
    parser.add_argument(
        "--build-identity",
        type=Path,
        default=None,
        help="可选 build identity sidecar；默认读取 automation EXE 同目录 build_identity.json",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Live Scenario Capture -> Frozen Replay")
    sub = parser.add_subparsers(dest="command", required=True)
    capture_parser = sub.add_parser("capture", help="运行真实 Mediator.tick() 并保存事件 bundle")
    _common_live_args(capture_parser)
    capture_parser.add_argument("--generate", action="store_true", help="capture 结束后生成 baseline+4 变体 case")
    probe_parser = sub.add_parser("probe", help="只调用目标生产 handler 的实机探针")
    _common_live_args(probe_parser)
    probe_parser.add_argument("--generate", action="store_true", help="probe 结束后生成 baseline+4 变体 case")
    bookmark_parser = sub.add_parser("bookmark", help="向运行中的 capture/probe 写入一个非阻塞 bookmark 命令")
    bookmark_parser.add_argument("--bundle", type=Path, required=True)
    bookmark_parser.add_argument("--status", choices=BOOKMARK_STATUSES, required=True)
    bookmark_parser.add_argument("--note", default="")
    bookmark_parser.add_argument("--bookmark-file", type=Path, default=None)
    generate_parser = sub.add_parser("generate", help="从 bundle 生成现有 schema-v1 replay cases")
    generate_parser.add_argument("--bundle", type=Path, required=True)
    generate_parser.add_argument("--repo-root", type=Path, default=ROOT)
    generate_parser.add_argument("--case-name", default=None)
    generate_parser.add_argument("--variants", default=",".join(FAILURE_VARIANTS), help="逗号分隔的失败变体")
    reproduce_parser = sub.add_parser("reproduce", help="一条命令生成并通过现有 FakeInput/FakeClock 流程重放 bundle")
    reproduce_parser.add_argument("--bundle", type=Path, required=True)
    reproduce_parser.add_argument("--repo-root", type=Path, default=ROOT)
    reproduce_parser.add_argument("--variants", default=",".join(FAILURE_VARIANTS), help="逗号分隔的失败变体")
    replay_parser = sub.add_parser("replay", help="用现有 ScenarioRunner 重跑生成的 case")
    replay_parser.add_argument("--case", dest="case_dir", type=Path, default=None)
    replay_parser.add_argument("--bundle", type=Path, default=None)
    replay_parser.add_argument("--repo-root", type=Path, default=ROOT)
    readiness_parser = sub.add_parser("readiness", help="启动实机前检查六个 target 的 contract/capture/bookmark/replay 能力")
    readiness_parser.add_argument("--repo-root", type=Path, default=ROOT)
    readiness_parser.add_argument("--settings", type=Path, default=None, help="可选：同时检查本次 settings 的 target 前置")
    readiness_parser.add_argument("--quick", action="store_true", help="跳过临时 bundle 的离线 replay self-check")
    readiness_parser.add_argument("--json", action="store_true")
    contracts_parser = sub.add_parser("contracts", help="显示六个 Target Test Contract")
    contracts_parser.add_argument("--target", choices=SUPPORTED_TARGETS, default=None)
    contracts_parser.add_argument("--json", action="store_true")
    runbook_parser = sub.add_parser("runbook", help="显示极简 target live runbook")
    runbook_parser.add_argument("--target", choices=SUPPORTED_TARGETS, default=None)
    return parser


def _bundle_preflight_blocked(bundle_dir: Path) -> bool:
    try:
        manifest = json.loads((Path(bundle_dir) / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    return bool((manifest.get("live_preflight") or {}).get("status") == "BLOCKED_PRECHECK")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "capture":
            bundle = _run_live_capture(args)
            return 3 if _bundle_preflight_blocked(bundle) else 0
        if args.command == "probe":
            bundle = _run_live_capture(args, probe=True)
            return 3 if _bundle_preflight_blocked(bundle) else 0
        if args.command == "bookmark":
            path = _append_bookmark_command(
                args.bundle,
                args.status,
                args.note,
                args.bookmark_file,
            )
            print(f"[bookmark] queued {args.status} -> {path}")
            return 0
        if args.command == "generate":
            raw_variants = tuple(v.strip() for v in args.variants.split(",") if v.strip())
            unknown = set(raw_variants) - set(FAILURE_VARIANTS)
            if unknown:
                raise ValueError(f"未知失败变体: {sorted(unknown)}")
            paths = generate_cases(
                args.bundle,
                repo_root=args.repo_root.resolve(),
                case_name=args.case_name,
                variants=raw_variants,
            )
            for path in paths:
                print(f"[generate] {path}")
            return 0
        if args.command == "reproduce":
            raw_variants = tuple(v.strip() for v in args.variants.split(",") if v.strip())
            unknown = set(raw_variants) - set(FAILURE_VARIANTS)
            if unknown:
                raise ValueError(f"未知失败变体: {sorted(unknown)}")
            return 0 if reproduce_bundle(
                args.bundle,
                repo_root=args.repo_root.resolve(),
                variants=raw_variants,
            ) == 0 else 1
        if args.command == "readiness":
            settings = Settings.load(args.settings) if args.settings else None
            report = readiness_report(
                repo_root=args.repo_root,
                settings=settings,
                run_replay_self_check=not args.quick,
            )
            _print_readiness(report, as_json=args.json)
            return 0 if all(item["harness_readiness"] == "READY" for item in report["targets"]) else 1
        if args.command == "contracts":
            _print_contracts(args.target, as_json=args.json)
            return 0
        if args.command == "runbook":
            _print_runbook(args.target)
            return 0
        if args.case_dir is not None:
            case_dirs = [args.case_dir]
        elif args.bundle is not None:
            case_dirs = sorted((args.bundle / "cases").glob("*/case.json"))
        else:
            raise ValueError("replay 需要 --case 或 --bundle")
        if not case_dirs:
            raise ValueError("没有找到 replay case.json")
        return 0 if replay_cases([p.parent for p in case_dirs], args.repo_root.resolve()) == 0 else 1
    except (OSError, ValueError, KeyError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
