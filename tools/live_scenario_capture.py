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
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Callable

import cv2
import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]

# Tier-0 scenarios run the frozen production candidate from an explicit
# source root while this Harness worktree remains the owner of the runner,
# tests, and bundle schema.  Keep the default import behaviour unchanged for
# the existing non-Tier-0 targets.
PRODUCTION_TEST_CANDIDATE_SHA: str = ""


def _argv_value(name: str) -> str | None:
    """Read a simple CLI option before argparse and production imports run."""
    try:
        index = sys.argv.index(name)
    except ValueError:
        return None
    if index + 1 >= len(sys.argv):
        return None
    value = str(sys.argv[index + 1]).strip()
    return value or None


def _configured_production_source_root(explicit: str | Path | None = None) -> Path | None:
    value = explicit or os.environ.get("SHUABAO_PRODUCTION_SOURCE_ROOT") or _argv_value(
        "--production-source-root"
    )
    if not value:
        return None
    return Path(value).expanduser().resolve()


def _configured_production_source_sha(explicit: str | None = None) -> str | None:
    value = explicit or os.environ.get("SHUABAO_PRODUCTION_SOURCE_SHA") or _argv_value(
        "--production-source-sha"
    )
    value = str(value).strip() if value else ""
    return value or None


_PRODUCTION_SOURCE_ROOT = _configured_production_source_root()
if _PRODUCTION_SOURCE_ROOT is not None:
    _injected_src = _PRODUCTION_SOURCE_ROOT / "src"
    if _injected_src.is_dir():
        sys.path.insert(0, str(_injected_src))

if str(ROOT / "src") not in sys.path:
    if _PRODUCTION_SOURCE_ROOT is None:
        sys.path.insert(0, str(ROOT / "src"))
    else:
        sys.path.append(str(ROOT / "src"))
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from live_harness_identity import (  # noqa: E402
    FROZEN_PRODUCTION_CODE_BASELINE,
    HARNESS_BASE_SHA,
    format_identity_text as _base_format_identity_text,
    identity_report,
)

from shuabao.input.keyboard_mouse import (
    ActionResult,
    InputExecutor,
    is_current_process_elevated,
)  # noqa: E402
from shuabao.input.emergency_stop import EmergencyStopListener  # noqa: E402
from shuabao.loop_action import LoopAction  # noqa: E402
from shuabao.mediator import BUILD_ID, Mediator, Phase  # noqa: E402
from shuabao.player_profile import LiveLane, LiveLaneBusy  # noqa: E402
from shuabao.settings import Settings  # noqa: E402
from shuabao.stop_signal import StopSignal  # noqa: E402
from shuabao.vision.capture import (  # noqa: E402
    Frame,
    WindowRole,
    capture,
    classify_window_role,
)
from shuabao.vision.matcher import _load_template  # noqa: E402
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


def _format_identity_text(report: dict[str, Any]) -> str:
    """Render the injected production SHA, not the Harness baseline, as candidate."""
    text = _base_format_identity_text(report)
    source_sha = str(report.get("production_source_sha") or "").strip()
    if not source_sha:
        return text
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("Production Candidate SHA:"):
            lines[index] = f"Production Candidate SHA: {source_sha}"
            break
    return "\r\n".join(lines)


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
        "start_condition": "已在局内 HUD 停在黑商商品条附近，且本局至少完成过一次进化；同一遭遇内买吞噬丹/木材/2折5折，买完就刷新；同时调用现有背包吞噬丹、英雄卡与神器 Q/W/E handler，持续观察到 600 秒安全上限。",
        "production_entry": "依次调用现有 Mediator._maybe_black_merchant(frame)、_maybe_use_inventory_item(frame)、_maybe_fire_artifacts(frame)；每 tick 最多一个真实输入。",
        "expected_steps": (
            "DETECT", "SCAN", "REFRESH", "VERIFY_REFRESH", "TARGET_FOUND",
            "TAKE", "VERIFY_TAKE", "EXIT",
        ),
        "success_postcondition": "吞噬丹/木材/已识别折扣的购买后置、背包吞噬丹 WAIT_DEVOUR_DAN 确认，或英雄卡打开真实英雄选择页，才是 LIVE_PROBE_PASS；刷新成功只记 REFRESH_PASS，绝不只以 click success 判定。",
        "fail_condition": "刷新/目标商品已识别但输入被拒绝、既有验证超时、画面/商品后置未变化，或生产 handler 进入 ERROR；刷新成功不能覆盖后续 TARGET_FOUND/TAKE 失败。",
        "blocked_condition": "capture 无效、吞噬丹/神器既有生产前置不满足，或当前画面没有可安全识别的目标商品；刷新控件瞬时未检出只记观察证据，不再提前结束长探针。",
        "max_probe_time_s": 600.0,
        "natural_e2e_eligible": "仅连续 mediator_tick 实机链、观察到上述业务后置状态、且无 FAIL/MANUAL_INTERVENTION bookmark 时仍有资格；probe 本身不算 Natural E2E。",
        "bundle_replay": "bundle 的事件帧经 ReplayCaseLoader 转为 schema-v1 case；由真实 Mediator.tick() + FakeInputExecutor 重放 baseline 和四个故障变体。",
        "runbook_manual": "把游戏停在黑商商品条附近；确保 1600×900、未暂停，吞噬丹/神器相关开关沿用真实设置。",
        "runbook_hands_off": "命令启动后不要再点击商品条、刷新、背包或神器 Q/W/E 区域。",
        "runbook_pass": "自动确认刷新后目标商品获取的业务后置状态才是 Live Probe PASS；p 只保存人工证据，刷新变化不是整链 PASS。",
        "runbook_manual_intervention": "生产链 FAIL 留证后，可人工处理弹窗并标记 MANUAL_INTERVENTION，继续采集后续场景。",
    },
    "inventory_item": {
        "handler": "_maybe_use_inventory_item",
        "call": "frame",
        "start_condition": "已在无中央面板、无黑商的局内 HUD，且本局至少完成过一次进化；目标为右下背包吞噬丹或英雄卡。吞噬丹还要求羁绊数量至少 4 且 auto_devour_dan 已开启。",
        "production_entry": "Mediator._maybe_use_inventory_item(frame)",
        "expected_steps": (
            "DETECT_SLOT", "IDENTIFY", "USE", "VERIFY_CONSUMED", "VERIFY_NO_REPEAT",
        ),
        "success_postcondition": "现有 WAIT_DEVOUR_DAN verifier 确认吞噬丹消耗，或 WAIT_HERO_CHOICE verifier 确认英雄卡打开真实英雄选择页；且没有对同一物品重复发送输入。绝不以 click success 判定。",
        "fail_condition": "输入被拒绝、PendingAction 到期未确认、同一槽位无后置变化仍被重复使用，或生产 handler 进入 ERROR。",
        "blocked_condition": "capture 无效、黑商/中央面板抢占、目标物品或既有启用前置不满足。",
        "max_probe_time_s": 15.0,
        "natural_e2e_eligible": "仅连续 mediator_tick 实机链、消耗后置事实已观察到、且无 FAIL/MANUAL_INTERVENTION bookmark 时仍有资格；probe 本身不算 Natural E2E。",
        "bundle_replay": "bundle 记录动作前后帧与 PendingAction 收敛，再由现有 ReplayCaseLoader/FakeInputExecutor 生成并重放 case。",
        "runbook_manual": "本局完成一次进化后，把游戏停在无弹窗的局内 HUD；背包准备吞噬丹或英雄卡。吞噬丹另需羁绊至少 4 个并开启现有开关。",
        "runbook_hands_off": "命令启动后不要点击背包槽位、黑商或中央选卡面板。",
        "runbook_pass": "吞噬丹被既有 verifier 确认消耗，或英雄卡确实打开英雄选择页，且没有重复点击，才是 Live Probe PASS；p 只留证。",
        "runbook_manual_intervention": "若目标被其他弹窗遮住或生产 FAIL，先标 FAIL；人工清理后标 MANUAL_INTERVENTION，再继续采集。",
    },
    "boss_challenge": {
        "handler": "_maybe_challenge_configured_boss",
        "call": "frame_now",
        "start_condition": "完整整链：从仍在运行的局内 HUD 交给现有 Mediator.tick()，让 tqtz→Boss→结算自然发生；若只做局部复验，也可人工打开 boss_entry 列表并使用本 target 的窄探针。现有 cjb_boss/sgzx_boss 中只保留本次要测的一个 Boss。",
        "production_entry": "整链 capture 使用现有 Mediator.tick()（包含既有 tqtz/early-challenge/post-game 分支）；Boss 测试会隔离自动秘境，局部 probe 只调用 Mediator._maybe_challenge_configured_boss(frame, time.time())。",
        "expected_steps": (
            "ENTRY_VISIBLE", "CLICK", "TRANSITION", "DESTINATION_CONFIRMED",
            "POSTGAME_DETECT", "ARCHIVE_1_TO_8", "HEIRLOOM_SELECT",
        ),
        "success_postcondition": "现有生产链确认挑战目的地 HUD；战后已分类存档面板逐项尝试 8 个卡位、再由现有配置 Boss handler 确认传家宝进入。单次 click success 不是成功。",
        "fail_condition": "入口/卡位/配置 Boss 未命中、输入被拒绝、目标页/局内 HUD 不变，或生产 handler 进入 ERROR。",
        "blocked_condition": "capture 无效、没有唯一 cjb_boss、战后页面未被现有分类器确认，或卡面 crop 无有效证据；不得用盲点替代。",
        "max_probe_time_s": 60.0,
        "natural_e2e_eligible": "只有从局内 HUD 开始的连续 mediator_tick 整链、Boss 目的地由真实状态确认、且无 FAIL/MANUAL_INTERVENTION bookmark 时仍有资格；局部 probe 不算 Natural E2E。",
        "bundle_replay": "整链 capture 与局部 probe 都复用现有 schema-v1 ReplayCaseLoader；存档八卡、传家宝点击和转场按事件帧转换，并用 FakeInputExecutor/FakeClock 注入四种故障。",
        "runbook_manual": "整链测试：把游戏留在局内 HUD；局部复验可停在存档挑战面板或传家宝 Boss 列表，并确认 cjb_boss 已配置。",
        "runbook_hands_off": "启动后不要点存档卡、传家宝 Boss、结算页或时光之穴；让脚本完成存档 8 项和传家宝选择。秘境请另用 secret_realm 测试。",
        "runbook_pass": "只有真实挑战 HUD/转场后置确认才是 Live Probe PASS；存档卡点击和页面打开仅是步骤证据；p 只保存人工证据。",
        "runbook_manual_intervention": "若需要手动越过列表/弹窗，先留 FAIL，再操作并标 MANUAL_INTERVENTION。",
    },
    "time_cave": {
        "handler": "_maybe_challenge_configured_boss",
        "call": "frame_now",
        "start_condition": "人工打开时光之穴 Boss 选择页；脚本只接管末位可识别 Boss fallback。",
        "production_entry": "Mediator._maybe_challenge_configured_boss(frame, time.time())，复用现有 Boss 模板/滚动/末位 fallback。",
        "expected_steps": (
            "ENTRY_VISIBLE", "CLICK", "REQUEST", "CONFIRM", "TRANSITION", "DESTINATION_CONFIRMED",
        ),
        "success_postcondition": "真实 Boss 挑战 HUD 出现；单次 click success 不算成功。",
        "fail_condition": "入口/可选 Boss 未识别、输入被拒绝、目标页/局内 HUD 不变，或生产 handler 进入 ERROR。",
        "blocked_condition": "没有稳定的时光之穴 Boss 列表或真实挑战 HUD 时，Fail-Closed 零输入。",
        "max_probe_time_s": 60.0,
        "natural_e2e_eligible": "只有真实列表、末位 Boss 点击及挑战 HUD 后置确认全部成立才算 Natural E2E。",
        "bundle_replay": "整链 capture 与局部 probe 复用 ReplayCaseLoader；fallback 点击和转场按事件帧重放。",
        "runbook_manual": "先把游戏停在已打开的时光之穴 Boss 列表，传家宝本轮不参与。",
        "runbook_hands_off": "启动后不要手动点击 Boss，让脚本自动选择最后一个可识别 Boss。",
        "runbook_pass": "必须出现真实挑战 HUD 才算 Live Probe PASS。",
        "runbook_manual_intervention": "入口不稳定时按 m 停止自动输入，保留 bundle 证据。",
    },
    "heirloom": {
        # 实际分发在 _invoke_target_handler 里走 _tick_main_line；这里的文案
        # 曾经写成面板内的 Boss handler，容易让人以为要手动把弹窗开好。
        "handler": "_tick_main_line",
        "call": "frame",
        "start_condition": "把真实游戏停在战后挑战广场（NPC_HUB）或已打开的传家宝弹窗；不要手点 NPC。有 cjb_boss 时点配置 Boss，没有则点列表最后一张可识别卡。",
        "production_entry": "Mediator._tick_main_line(frame)：必要时先关背包→OpenHeirloomChallenges→HEIRLOOM_DIALOG→配置 Boss 或最后可识别卡。",
        "expected_steps": (
            "POSTGAME_DETECT", "ENTRY_VISIBLE", "CLICK", "REQUEST", "CONFIRM", "TRANSITION", "DESTINATION_CONFIRMED",
        ),
        "success_postcondition": "配置的 cjb_boss 卡被现有 handler 命中，随后真实局内 HUD/挑战目的地出现；click success 单独不算成功。",
        "fail_condition": "Boss 卡未命中、滚动后仍无证据、输入被拒绝、页面/局内 HUD 不变或生产 handler 进入 ERROR。",
        "blocked_condition": "capture 无效，或页面既不是 NPC_HUB 也不是 HEIRLOOM_DIALOG。",
        "max_probe_time_s": 90.0,
        "natural_e2e_eligible": "只有从真实传家宝页开始且真实 HUD 后置确认、无 FAIL/MANUAL_INTERVENTION bookmark 时才有资格；局部 probe 不算 Natural E2E。",
        "bundle_replay": "捕获的 postgame/entry/transition 关键帧按原 ReplayCaseLoader 格式重放，故障变体不改原始截图。",
        "runbook_manual": "停在挑战广场或已打开的传家宝弹窗。背包若开着由 production 先关。",
        "runbook_hands_off": "启动后不要点 NPC、Boss 卡或滚动。",
        "runbook_pass": "配置 Boss 进入后的真实 HUD/挑战后置确认才算 Live Probe PASS；p 只保存人工证据。",
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
    "lobby_hitch": {
        "handler": "_tick_lobby_hitch",
        "start_condition": "把游戏停在可信大厅对战页；若未在房间列表，production 先点击可识别的房间列表 Tab。搜索词默认 3，也可自定义；脚本一次输入并回车搜索，之后按刷新 CD 搜房，遇到特殊房间弹窗自动关闭。",
        "production_entry": "Mediator._tick_lobby_hitch(frame, context, room_start, stage_page)",
        "expected_steps": (
            "LOBBY_DETECT", "SCAN", "REFRESH", "ROOM_FOUND", "JOIN", "ROOM_WAITING_CONFIRMED",
        ),
        "success_postcondition": "成功匹配前缀并点击加入后，画面进入房间等待界面（ROOM_WAITING 或 room_start 锚点出现），且 _hitch_sm 确认进房成功；单次 click success 不算成功。",
        "fail_condition": "刷新/进房输入被拒绝、超过 join_attempts/search_timeout 仍未进房且无大厅退回、或进入错误状态。",
        "blocked_condition": "capture 无效、既未确认大厅房间列表也未识别到可切入的房间列表 Tab、或当前无可识别房间。",
        "max_probe_time_s": 600.0,
        "natural_e2e_eligible": "只有从真实大厅列表开始、识别到目标前缀、点击进房并由真实 ROOM_WAITING HUD 确认、且无 FAIL/MANUAL_INTERVENTION bookmark 时才算 Natural E2E。",
        "bundle_replay": "重放大厅搜房、刷新与进房转场帧；四种故障变体按标准 Loader 注入。",
        "runbook_manual": "把游戏停在大厅房间列表页；确保未在房间内且窗口 1600×900。",
        "runbook_hands_off": "启动后不要手动刷新或点击房间列表，让脚本自动搜房并加入。",
        "runbook_pass": "成功进入房间并停在 ROOM_WAITING 状态才算 Live Probe PASS。",
        "runbook_manual_intervention": "若卡在密码房或弹窗，可手动处理后标 MANUAL_INTERVENTION。",
    },
    "lobby_search": {
        "handler": "_tick_lobby_hitch",
        "start_condition": "把 KK 官方对战平台停在英雄三国可信大厅页；若未在房间列表，production 先切入可识别的房间列表 Tab。随后脚本输入当前 hitch_stage_prefix，并只点击人数未满、非游戏中、非锁定的房间；无候选时按 5 秒 CD 刷新。",
        "production_entry": "Mediator._tick_lobby_hitch(frame, context, room_start, stage_page)；默认探针最长 90 秒，桌面整链使用 --until-success 持续到准备成功。",
        "expected_steps": ("LOBBY_DETECT", "SEARCH_INPUT", "SEARCH_CONFIRMED", "ROW_SCAN", "JOIN_OR_REFRESH", "REJECT_OR_READY", "READY_CONFIRMED"),
        "success_postcondition": "搜索输入得到确认，并在拒绝满员/密码/首槽不合规房与 5 秒 CD 刷新后，进入合规房间、真实点击客人“准备”，且准备按钮状态发生变化。刷新只算过程证据。",
        "fail_condition": "搜索、刷新或安全房间行输入被拒绝，或动作成功但 5 秒内没有对应视觉后置证据。",
        "blocked_condition": "未提权、KK 窗口不可用、既未确认房间列表也未识别到可切入的房间列表 Tab、搜索框/刷新模板不可用，或房间行安全证据不足。",
        "max_probe_time_s": 90.0,
        "natural_e2e_eligible": "只有从真实列表持续执行到合规房客人准备后置确认，且无人工介入，才有资格作为大厅搜房 Natural E2E。",
        "bundle_replay": "记录真实搜索动作前后帧和五步输入结果；冻结重放只验证证据结构，不替代实机输入。",
        "runbook_manual": "把 KK 停在英雄三国房间列表，不要预先聚焦或修改搜索框。",
        "runbook_hands_off": "启动后不要触碰鼠标键盘；桌面整链会持续搜房、拒绝异常房并按 5 秒 CD 刷新，直到准备成功；紧急停止仍用 Shift+F12。绝不点 Quick Join、创建房间或开始游戏。",
        "runbook_pass": "只有真实进入合规房间并点击准备、且按钮状态变化得到确认，才是 Live Probe PASS；Refresh 不是终态。",
        "runbook_manual_intervention": "若 UAC 未确认或窗口被遮挡，结束本次并重新从桌面快捷方式启动。",
    },
    "s01_lobby_surface_identity": {
        "handler": "_detect_context",
        "start_condition": "手工把 KK 停在房间列表、未准备房间、已准备房间、普通大厅其它页或平台弹窗之一；Scenario 默认零业务输入。",
        "production_entry": "每次 fresh capture 调用 production Mediator 的页面/弹窗/Ready detector；Scenario 只记录分类、HWND 连续性与 contract。",
        "expected_steps": ("CAPTURE", "WINDOW_IDENTITY", "SURFACE_CLASSIFIED", "READY_CONTRACT"),
        "success_postcondition": "ROOM、ROOM_LIST、PLATFORM_MODAL、UNKNOWN 与 ready contract 均来自 production detector；UNKNOWN 始终零业务输入。",
        "fail_condition": "ROOM_LIST 被判为 ROOM、ROOM 被判为 ROOM_LIST、普通大厅被判为 MODAL、或 UNKNOWN 上出现业务输入。",
        "blocked_condition": "没有有效 KK capture/HWND；无窗口只允许 BLOCKED，不伪造页面分类。",
        "max_probe_time_s": 30.0,
        "natural_e2e_eligible": "仅用于页面身份 Ground Truth；不以本 target 宣称业务链 Live PASS。",
        "bundle_replay": "保存真实 capture/frame identity/production classification；不生成 fabricated MatchResult。",
        "runbook_manual": "依次手工停在 ROOM_LIST、未准备 ROOM、已准备 ROOM、普通大厅其它页或 KK platform modal。",
        "runbook_hands_off": "启动后不要点击；该 target 默认零业务输入。",
        "runbook_pass": "每个手工页面都由 production detector 给出正确身份；UNKNOWN 零输入。",
        "runbook_manual_intervention": "页面不稳定时停止并保留 bundle，不在 Scenario 中手工分类。",
    },
    "s02_lobby_platform_modal": {
        "handler": "tick",
        "start_condition": "手工制造一个 KK blocking modal：等级不足、密码、被踢、房主离开、会员提示或同 shell 平台提示。",
        "production_entry": "调用 production Mediator.tick()；只允许统一 Platform Modal Shell 的 neutral Esc/X dismiss。",
        "expected_steps": ("MODAL_CONFIRMED", "NEUTRAL_DISMISS", "FRESH_REACQUIRE", "SURFACE_RECLASSIFIED"),
        "success_postcondition": "fresh capture 证明 modal shell 消失，随后 fresh surface 被 production 重新分类为可信 lobby/platform surface；Esc dispatch success 单独不算 PASS。",
        "fail_condition": "非 neutral 输入、modal 消失未被 fresh capture 证实、或 recovery 后仍错误停在旧 identity。",
        "blocked_condition": "启动帧不是 production PLATFORM_MODAL；无 KK 窗口时 BLOCKED。",
        "max_probe_time_s": 60.0,
        "natural_e2e_eligible": "只有真实 modal 消失与后续 surface fresh-confirm 后才有资格；Scenario 不替代 production handler。",
        "bundle_replay": "保存 modal 前后 frame、capture generation、HWND、trace、input 与 postcondition；静态像素也必须以新 capture generation 识别。",
        "runbook_manual": "制造一个等级不足/密码/被踢/房主离开/会员提示等 KK 平台弹窗。",
        "runbook_hands_off": "不要点击正向按钮；仅允许 production neutral dismiss。",
        "runbook_pass": "modal shell 消失并由 fresh capture 重新分类；预算耗尽也不得 ERROR/stop/Break。",
        "runbook_manual_intervention": "无法恢复时标 FAIL，保留完整 bundle 后停止该 Scenario。",
    },
    "s03_lobby_room_ready": {
        "handler": "_tick_lobby_hitch",
        "start_condition": "手工进入真实 ROOM；分别测试未准备、已准备和 ROOM=True 但 Ready contract UNKNOWN。",
        "production_entry": "先由 production fresh-confirm ROOM，再读取 production Ready/CancelReady contract；仅在 ready contract=ready 时调用现有 Ready action。",
        "expected_steps": ("ROOM_CONFIRMED", "READY_CONTRACT", "READY_OR_WAIT", "CANCEL_READY_CONFIRMED"),
        "success_postcondition": "未准备房间 fresh-confirm CancelReady/已准备；已准备房间 Ready 点击次数为 0；UNKNOWN contract 零输入并 reobserve。",
        "fail_condition": "ROOM 未确认就输入、已准备重复点 Ready、或 UNKNOWN seat/contract 导致退出房间/拉黑房号。",
        "blocked_condition": "启动帧不是 production ROOM；无 KK 窗口时 BLOCKED。",
        "max_probe_time_s": 60.0,
        "natural_e2e_eligible": "仅真实 Ready/CancelReady 后置确认后才有资格；点击成功单独不算 PASS。",
        "bundle_replay": "保存 ROOM/Ready contract/CancelReady fresh evidence、输入、HWND 与 trace；不补造 ready 模板。",
        "runbook_manual": "先进入别人真实房间，分别停在未准备、已准备和无法判断 Ready contract 的页面。",
        "runbook_hands_off": "不要手动点 Ready/CancelReady/退出。",
        "runbook_pass": "未准备只点一次 Ready 并 fresh-confirm CancelReady；已准备零 Ready click；UNKNOWN 零输入。",
        "runbook_manual_intervention": "真实页面不满足 contract 时标 FAIL/BLOCKED，不手工替代 detector。",
    },
    "s04_lobby_single_hwnd_room": {
        "handler": "_detect_context",
        "start_condition": "尽量使用单 KK HWND、全屏或仅一个可捕获平台窗口，并手工停在真实 ROOM。",
        "production_entry": "fresh capture 调用 production ROOM detector 与 confirmed_room_hwnd 归属；Scenario 默认零输入。",
        "expected_steps": ("CAPTURE", "ROOM_CONFIRMED", "SINGLE_HWND_CONTINUITY", "ROOM_WAIT"),
        "success_postcondition": "ROOM=True 且 confirmed_room_hwnd 等于当前实际 HWND；不会因 len(targets)==1 回退 ROOM_LIST/GO_HOME。",
        "fail_condition": "真实 ROOM 被判为 ROOM_LIST/UNKNOWN，confirmed_room_hwnd 丢失，或单窗口导致盲点退出/回家。",
        "blocked_condition": "没有有效单 HWND KK capture；不以多窗口模拟单窗口 PASS。",
        "max_probe_time_s": 30.0,
        "natural_e2e_eligible": "只验证单窗口 ROOM identity continuity；后续 Ready 业务由 S03/S05 验证。",
        "bundle_replay": "保存实际 HWND、窗口 title/role、frame size、generation 与 production classification。",
        "runbook_manual": "使用单 KK HWND/全屏或只有一个可捕获平台窗口，实际停在 ROOM。",
        "runbook_hands_off": "启动后不要点击；该 target 默认零业务输入。",
        "runbook_pass": "fresh production ROOM evidence 与当前 HWND 连续一致。",
        "runbook_manual_intervention": "窗口形态不满足时标 BLOCKED，不改 detector 迎合测试。",
    },
    "s05_lobby_search_join_ready": {
        "handler": "_tick_lobby_hitch",
        "start_condition": "手工停在真实 ROOM_LIST；由 production 完成搜索词确认、可加入行扫描、Join、modal neutral recovery、ROOM、Ready 与 CancelReady fresh-confirm。",
        "production_entry": "调用现有 production _tick_lobby_hitch；Harness 不复制搜索、座位、退出或弹窗 FSM。",
        "expected_steps": ("SEARCH_CONFIRMED", "JOIN_REQUEST", "ROOM_CONFIRMED", "READY_CONFIRMED"),
        "success_postcondition": "SEARCH、JOIN、ROOM fresh-confirm、READY/CancelReady fresh-confirm 全部发生；click success、frame mutation、pending_join 单独不算 PASS。",
        "fail_condition": "任一业务后置缺失、UNKNOWN 页面上输入、重复 Ready、或错误退出/拉黑。",
        "blocked_condition": "没有可信 ROOM_LIST/搜索资源/KK window；无窗口时 BLOCKED。",
        "max_probe_time_s": 600.0,
        "natural_e2e_eligible": "完整真实大厅→搜索→进房→Ready 链且无 FAIL/MANUAL_INTERVENTION 才有资格。",
        "bundle_replay": "沿用现有 event-driven bundle、trace 与 ReplayCaseLoader；只回放证据，不把 Lobby FSM 复制进 Harness。",
        "runbook_manual": "把 KK 停在英雄三国 ROOM_LIST，确认没有其它刷刷宝实例运行。",
        "runbook_hands_off": "启动后不要点搜索、房间、Ready、弹窗或退出；紧急停止仍用 Shift+F12。",
        "runbook_pass": "四个 production fresh business postcondition 全部确认。",
        "runbook_manual_intervention": "被异常房/弹窗卡住时先留 FAIL，再停止本次 Scenario。",
    },
    "s06_lobby_recovery_chain": {
        "handler": "tick",
        "start_condition": "S01–S05 已通过后从真实 ROOM_LIST 启动；连续运行 10–20 分钟或至少 5 次 production join attempt。",
        "production_entry": "连续调用 production Mediator.tick()；所有 Lobby 输入、恢复、弹窗与 seat decision 均由 production handler 产生。",
        "expected_steps": ("SEARCH", "JOIN", "RECOVER", "READY", "RECLASSIFY", "SOAK_SAFETY"),
        "success_postcondition": "达到时间/次数门槛且 SILENT_STOP、永久零输入 stall、ROOM_LIST-as-ROOM、ROOM-as-MODAL、READY_REPEAT、UNKNOWN_SEAT_EXIT、BLIND_GO_HOME、unexpected_inputs 均为 0。",
        "fail_condition": "任一安全指标非 0、生产 ERROR/stop、或未达到门槛即宣称 PASS。",
        "blocked_condition": "S01–S05 未完成、无 KK 窗口或无法取得有效 capture/trace。",
        "max_probe_time_s": 1200.0,
        "natural_e2e_eligible": "仅达到至少 5 次 join 或 10 分钟并通过全部 safety metrics 才有资格。",
        "bundle_replay": "保存 soak 期间事件帧、trace、HWND、classification、inputs、postconditions 与汇总 metrics。",
        "runbook_manual": "完成 S01–S05 后，把 KK 停在 ROOM_LIST；准备让异常房/弹窗自然出现。",
        "runbook_hands_off": "全程不要手动操作 Lobby；紧急停止仍用 Shift+F12。",
        "runbook_pass": "达到 soak 门槛且所有安全指标为 0。",
        "runbook_manual_intervention": "任何人工接管都会使本次 Natural E2E 失格并保留 bundle。",
    },
    "public_backpack_deposit": {
        "handler": "_maybe_public_backpack_deposit",
        "start_condition": "真实局内 HUD；物品栏除 1 号格外至少两格有吞噬丹或神符。production 打开背包，物品栏先放入个人格再迁公共格，搬完关闭。",
        "production_entry": "Mediator._maybe_public_backpack_deposit：HUD 开包→物品栏右键→个人空格→个人右键→公共空格→关包。",
        "expected_steps": ("HUD_AUTHORITY", "BAG_OPEN", "ITEM_BAR_STASH", "PUBLIC_DEPOSIT", "BAG_CLOSE"),
        "success_postcondition": "公共格从空变非空，物品栏对应格清空，随后背包关闭；click success 不算 PASS。",
        "fail_condition": "在 modal/outcome/UNKNOWN 上输入、左键点到物品栏/已占用个人格、或 transfer 后置缺失。",
        "blocked_condition": "HUD 未确认、背包双锚点未确认、或物品栏 2–6 号可搬格不足两格。",
        "max_probe_time_s": 120.0,
        "natural_e2e_eligible": "局部 probe 不算 Natural E2E；整链仍要单独验收。",
        "bundle_replay": "保存 before/action/after frame、HWND、尺寸、item bbox、public/private bag bbox、trace 与 production postcondition；不生成 fabricated MatchResult。",
        "runbook_manual": "停在局内 HUD，物品栏 2 号及以后至少两格有吞噬丹/神符。不要手搬。",
        "runbook_hands_off": "启动后不要点背包、物品栏或公共格。",
        "runbook_pass": "公共格占用变化且背包已关才算 Live Probe PASS。",
        "runbook_manual_intervention": "需要人工推进时标 MANUAL_INTERVENTION；本次不计 Natural E2E PASS。",
    },
    "hitch_runtime": {
        "handler": "tick",
        "call": "frame",
        "start_condition": "游戏窗口已经处于已确认的蹭车局内 HUD，或 production classifier 已确认的战后存档/传家宝页面；不再从 KK 大厅/房间窗口启动。",
        "production_entry": "Mediator.tick()，从局内接管时跳过仅属于自然开局的压力转移，继续自动任务、四挑战与既有战后 Boss 路由。",
        "expected_steps": ("HUD", "PRESSURE_SKIPPED_ON_TAKEOVER", "AUTO_TASK", "FOUR_CHALLENGES", "POSTGAME_ARCHIVE", "BOSS_FALLBACK"),
        "success_postcondition": "自动任务、挑战和战后 Boss 均须各自通过既有视觉后置条件；单次输入不算成功。",
        "fail_condition": "输入被拒绝、既有生产 handler 进入 ERROR，或页面缺少既有分类/模板证据。",
        "blocked_condition": "捕获无效、启动帧不是已确认局内 HUD 或 production 分类的战后页面时，BLOCKED 且不发业务输入。",
        "max_probe_time_s": 3600.0,
        "natural_e2e_eligible": "仅连续真机 Mediator.tick() 链、无人工干预、并由各生产后置条件确认时有资格。",
        "bundle_replay": "沿用现有事件帧、ReplayCaseLoader 和 FakeInputExecutor；不创建另一套蹭车局内状态机。",
        "runbook_manual": "把游戏停在已确认局内 HUD，或已经打开的存档/传家宝页面；不要停在 KK 大厅/房间窗口。紧急停止用 Shift+F12。",
        "runbook_hands_off": "启动后不要手动点自动任务、挑战、存档卡或 Boss；测试 11 从局内接管，不检查压力转移。",
        "runbook_pass": "记录实际动作和各自的真实后置证据；不得用 click success 代替。",
        "runbook_manual_intervention": "需要手动推进页面时先标记 FAIL，再标 MANUAL_INTERVENTION。",
    },
    "solo_ingame_chain": {
        "handler": "tick",
        "call": "frame",
        "start_condition": "KK 英雄三国地图页、建房弹窗、已创建房间或游戏内选关页之一可由 production L0 classifier 确认；正式看板的自动建房开关决定是否由 production 创建房间。",
        "production_entry": "RuntimeMediator.tick() / Mediator.tick()，初始 phase=BOOT；production _tick_l0 完成地图→建房→房间→选关，之后继续既有 Hero setup、MAIN_LINE、局尾与秘境/Boss 路由。Harness 不复制建房或局内决策。",
        "expected_steps": (
            "STAGE_SELECT_CONFIRMED", "STAGE_TARGET_VISIBLE", "STAGE_SELECTED_CONFIRMED",
            "STAGE_START_REQUEST", "STAGE_START_CONFIRMED", "GAME_HWND_CONFIRMED",
            "INGAME_HUD_CONFIRMED", "L1_CYCLE_ACTIVE", "POSTGAME_SURFACE_CLASSIFIED",
            "POSTGAME_ROUTE_PROGRESS",
        ),
        "success_postcondition": "生产 classifier 先确认真实 Stage Select，再确认 startChallenge 后的 Hero/HUD；随后局内循环和战后既有秘境/Boss/存档/传家宝路由由真实 Mediator.tick() 继续。羁绊、技能、宝物、进化、装备、拾取、黑商等随机或条件事件未出现只记 NOT_OBSERVED，不以 click success 或 phase-only 计 PASS。",
        "fail_condition": "production runtime 进入 ERROR、UNKNOWN 页面上出现输入、生产输入执行失败、Stage/Hero/HUD 业务后置未确认，或战后路由进入错误状态。",
        "blocked_condition": "启动帧不是可由 production classifier 确认的地图/建房/房间/选关页面、游戏窗口/OCR/RuntimeMediator/权限不可用，或外部窗口抢焦点/遮挡导致 ownership guard 拒绝输入；BLOCKED 时不发出业务输入。",
        "max_probe_time_s": 3600.0,
        "natural_e2e_eligible": "只有从真实大厅/地图/房间或选关页开始，连续 mediator_tick 完成建房、选关进局、真实 HUD/L1、战后页面及既有路线进展，且无 ERROR/UNKNOWN 输入、FAIL 或 MANUAL_INTERVENTION 时才有资格。",
        "bundle_replay": "沿用事件驱动 capture、trace 和 ReplayCaseLoader；metadata 只保存生产 classifier 观察，不复制 startChallenge、MAIN_LINE 或战后 FSM。",
        "runbook_manual": "把 KK 停在英雄三国地图页、建房弹窗、房间或游戏内选关页；确认正式看板配置已保存，尤其自动建房、局数、关卡、技能、羁绊、秘境和 Boss 选项。",
        "runbook_hands_off": "点击按钮后不要再点建房、开始、关卡、英雄、羁绊/技能/宝物、装备、进化、黑商、秘境或 Boss 页面；紧急停止仍用 Shift+F12，p/f/m 只记录证据。",
        "runbook_pass": "必须先有生产确认的地图/建房/房间/Stage Select → Hero/HUD → L1，再有战后页面及既有路线后置证据；随机黑商或特定面板未自然出现只记 NOT_OBSERVED。",
        "runbook_manual_intervention": "若需要人工越过页面或遮挡，先记录 FAIL；人工操作后记录 MANUAL_INTERVENTION，本次不能作为无人值守 PASS。",
    },
    "hitch_lobby_chain": {
        "handler": "tick",
        "call": "frame",
        "start_condition": "HITCH_FULL_NATURAL_E2E：把 KK 停在英雄三国真实 ROOM_LIST；不要预先点房间。由 production Mediator.tick() 连续处理搜房、Join、blocking modal、ROOM/Ready、进局、Pressure、局内 optional routes、Victory/Failure、真实退出、回到大厅并搜下一轮。",
        "production_entry": "Mediator.tick() → production _tick_l0/_tick_lobby_hitch/_tick_main_line；Harness 只采证据和汇总，不复制 Lobby/L1 FSM。",
        "expected_steps": (
            "ROOM_LIST", "SEARCH_CONFIRMED", "JOIN", "MODAL_RECOVERY",
            "ROOM_READY", "INGAME_HUD_CONFIRMED", "PRESSURE_CONFIRMED",
            "OPTIONAL_ROUTES", "OUTCOME", "REAL_EXIT", "LOBBY_RETURN", "NEXT_ROUND",
            "ARCHAEOLOGY_HANDOFF",
        ),
        "success_postcondition": "完成配置的 hitch_cycle_num 个 hitch round；每轮由 production fresh-confirm 搜索/进房/Ready/Pressure/Outcome/真实回厅，至少覆盖一次 blocking modal recovery 和一次 Victory 或 Failure；hitch_after_goal=arch 时，最后还须经既有单人选关路由得到 fresh 考古锚点。首次公共背包动作只作为 GT_CAPTURE/MANUAL_INTERVENTION，不计 Natural E2E PASS。",
        "fail_condition": "production runtime ERROR/静默停止/永久零输入 stall、UNKNOWN 上输入、ROOM_LIST-as-ROOM、ROOM-as-MODAL、重复 Ready、盲 GO_HOME、Pressure 未确认即放行、或回厅未 fresh-confirm。",
        "blocked_condition": "窗口身份/页面 UNKNOWN、无可信 ROOM_LIST、candidate source 未验证、或尚未取得 Public Backpack GT；BLOCKED 时零业务输入。",
        "max_probe_time_s": 3600.0,
        "natural_e2e_eligible": "HITCH_FULL_NATURAL_E2E 只认连续真实 Mediator.tick()；完成配置的 rounds，hitch_after_goal=arch 时还须 fresh-confirm 考古，且无人工介入；public backpack GT capture 不算 PASS。",
        "bundle_replay": "沿用现有事件帧、trace、ReplayCaseLoader 和 FakeInputExecutor；只重放证据结构，不把大厅/局内 FSM 复制到 Harness。",
        "runbook_manual": "把 KK 停在英雄三国房间列表；确认普通刷刷宝未运行。紧急停止用 Shift+F12。",
        "runbook_hands_off": "启动后不要点房间、刷新、准备、开始、压力、黑商、宝物、背包或退出；让 production Mediator.tick() 接管。",
        "runbook_pass": "至少 3 个完整 round 的 production fresh postcondition 和安全统计通过；click success/单次 frame mutation 不是 PASS。",
        "runbook_manual_intervention": "卡在密码房或弹窗时先 FAIL，再标 MANUAL_INTERVENTION。",
    },
    "choice_bond_skill": {
        "handler": "_tick_panel_fsm",
        "call": "frame_now",
        "start_condition": "请将真实游戏停在局内 HUD，或已经打开的羁绊/技能选卡面板。不要停在大厅。",
        "production_entry": "先调用现有 Mediator._tick_panel_fsm(frame, anchor, now)；若面板未打开，再调用 _maybe_open_choice_panel(frame)。不复制选卡策略。",
        "expected_steps": ("PANEL_OR_HUD", "OPEN_OR_ACTIVE", "SELECT", "MUTATION_CONFIRMED"),
        "success_postcondition": "生产面板 FSM 进入 WAIT_MUTATION 后，fresh frame 上观察到面板变化或面板关闭；click success 单独不算 PASS。",
        "fail_condition": "输入被拒绝、生产 ERROR，或选择后没有 mutation/关闭后置。",
        "blocked_condition": "窗口/页面 UNKNOWN、不是局内 HUD/选卡面板时 ZERO INPUT。",
        "max_probe_time_s": 45.0,
        "natural_e2e_eligible": "probe 本身不算 Natural E2E。",
        "bundle_replay": "沿用事件帧和 ReplayCaseLoader。",
        "runbook_manual": "把游戏停在局内 HUD 或已打开的羁绊/技能面板。",
        "runbook_hands_off": "启动后不要再点 G/F 或卡牌。",
        "runbook_pass": "只有生产 mutation/关闭后置才是 PASS。",
        "runbook_manual_intervention": "被其他弹窗挡住时先 FAIL。",
    },
    "treasure": {
        "handler": "_tick_panel_fsm",
        "call": "frame_now",
        "start_condition": "请将真实游戏停在局内 HUD，或已经打开的宝物面板。",
        "production_entry": "现有 Mediator._tick_panel_fsm / _maybe_open_choice_panel；Harness 只把 cycle step 设为 treasure，不实现宝物策略。",
        "expected_steps": ("PANEL_OR_HUD", "OPEN_OR_ACTIVE", "SELECT", "MUTATION_CONFIRMED"),
        "success_postcondition": "生产宝物面板 mutation 或关闭被 fresh frame 确认；click success 不算 PASS。",
        "fail_condition": "输入被拒绝、生产 ERROR，或无 mutation 后置。",
        "blocked_condition": "不是局内 HUD/宝物面板，或 auto_treasure 关闭导致无入口时 BLOCKED。",
        "max_probe_time_s": 45.0,
        "natural_e2e_eligible": "probe 本身不算 Natural E2E。",
        "bundle_replay": "沿用事件帧和 ReplayCaseLoader。",
        "runbook_manual": "把游戏停在局内 HUD 或已打开宝物面板，并确认自动宝物已开。",
        "runbook_hands_off": "启动后不要再点 V 或宝物卡。",
        "runbook_pass": "只有生产 mutation/关闭后置才是 PASS。",
        "runbook_manual_intervention": "被其他弹窗挡住时先 FAIL。",
    },
    "hero_evolve": {
        "handler": "_tick_main_line",
        "call": "frame",
        "start_condition": "请将真实游戏停在能够触发进化的合法局内 HUD（金色「点击进化」可见，无中央选卡面板抢占）。",
        "production_entry": "现有 Mediator._tick_main_line(frame)；仅把 _l1_cycle_step 设为 evolve，让生产进化分支与 _evolve_feedback_seen 后置生效。",
        "expected_steps": ("EVOLVE_VISIBLE", "CLICK", "FEEDBACK_CONFIRMED"),
        "success_postcondition": "ClickEvolve 之后生产 _evolve_feedback_seen 或英雄三选一面板出现；输入 API 成功单独不算 PASS。",
        "fail_condition": "输入被拒绝、连续无反馈，或生产 ERROR。",
        "blocked_condition": "进化按钮不可见、窗口 UNKNOWN 时 ZERO INPUT。",
        "max_probe_time_s": 30.0,
        "natural_e2e_eligible": "probe 本身不算 Natural E2E。",
        "bundle_replay": "沿用事件帧和 ReplayCaseLoader。",
        "runbook_manual": "把游戏停在进化按钮可见的局内 HUD。",
        "runbook_hands_off": "启动后不要再点进化或英雄卡。",
        "runbook_pass": "必须有生产进化反馈或英雄选择面板。",
        "runbook_manual_intervention": "被面板挡住时先 FAIL。",
    },
    "inventory_devour": {
        "handler": "_maybe_use_inventory_item",
        "call": "frame",
        "start_condition": "请将真实游戏停在无中央面板、无黑商的局内 HUD；背包已有吞噬丹，本局至少完成过一次进化，羁绊数量至少 4 且 auto_devour_dan 已开启。",
        "production_entry": "Mediator._maybe_use_inventory_item(frame)；只接受 WAIT_DEVOUR_DAN 业务后置。",
        "expected_steps": ("DETECT_SLOT", "USE", "VERIFY_CONSUMED"),
        "success_postcondition": "现有 WAIT_DEVOUR_DAN verifier 确认吞噬丹消耗；click success 不算 PASS。",
        "fail_condition": "输入被拒绝、PendingAction 到期未确认，或生产 ERROR。",
        "blocked_condition": "HUD/物品前置不满足时 ZERO INPUT。",
        "max_probe_time_s": 15.0,
        "natural_e2e_eligible": "probe 本身不算 Natural E2E。",
        "bundle_replay": "沿用事件帧和 ReplayCaseLoader。",
        "runbook_manual": "停在无弹窗局内 HUD，背包准备吞噬丹。",
        "runbook_hands_off": "不要点击背包槽位。",
        "runbook_pass": "只有 WAIT_DEVOUR_DAN 确认才是 PASS。",
        "runbook_manual_intervention": "被弹窗挡住时先 FAIL。",
    },
    "inventory_hero_card": {
        "handler": "_maybe_use_inventory_item",
        "call": "frame",
        "start_condition": "请将真实游戏停在无中央面板、无黑商的局内 HUD；背包已有英雄卡，本局至少完成过一次进化。",
        "production_entry": "Mediator._maybe_use_inventory_item(frame)；只接受 WAIT_HERO_CHOICE 业务后置。",
        "expected_steps": ("DETECT_SLOT", "USE", "VERIFY_HERO_CHOICE"),
        "success_postcondition": "现有 WAIT_HERO_CHOICE verifier 确认打开真实英雄选择页；click success 不算 PASS。",
        "fail_condition": "输入被拒绝、PendingAction 到期未确认，或生产 ERROR。",
        "blocked_condition": "HUD/物品前置不满足时 ZERO INPUT。",
        "max_probe_time_s": 15.0,
        "natural_e2e_eligible": "probe 本身不算 Natural E2E。",
        "bundle_replay": "沿用事件帧和 ReplayCaseLoader。",
        "runbook_manual": "停在无弹窗局内 HUD，背包准备英雄卡。",
        "runbook_hands_off": "不要点击背包槽位。",
        "runbook_pass": "只有英雄选择页后置才是 PASS。",
        "runbook_manual_intervention": "被弹窗挡住时先 FAIL。",
    },
    "archive_challenge": {
        "handler": "_tick_main_line",
        "call": "frame",
        "start_condition": "请将真实游戏停在战后挑战广场（NPC_HUB）或已打开的存档挑战面板；开面板这一步由 production 自己点 NPC 完成。",
        "production_entry": "Mediator._tick_main_line(frame)：NPC_HUB→OpenArchiveChallenges→ARCHIVE_PANEL 打卡→关闭；Harness 不实现开面板也不实现卡位策略。",
        "expected_steps": ("NPC_HUB", "OPEN_ARCHIVE_CHALLENGES", "ARCHIVE_PANEL", "CLICK", "CHALLENGE_HUD_CONFIRMED"),
        "success_postcondition": "对应真实挑战 HUD / 合法后续业务页面被 production classifier 确认；click success 不算 PASS。",
        "fail_condition": "输入被拒绝、页面不变，或生产 ERROR。",
        "blocked_condition": "不是 NPC_HUB/ARCHIVE_PANEL，或缺少现有 NPC/卡位锚点时 ZERO INPUT。",
        "max_probe_time_s": 30.0,
        "natural_e2e_eligible": "probe 本身不算 Natural E2E。",
        "bundle_replay": "沿用事件帧和 ReplayCaseLoader。",
        "runbook_manual": "停在战后挑战广场或已打开的存档挑战面板。",
        "runbook_hands_off": "不要再点 NPC 或存档卡。",
        "runbook_pass": "必须出现真实挑战 HUD/后续业务页。",
        "runbook_manual_intervention": "卡面不可点时先 FAIL。",
    },
}

# HARNESS readiness and production readiness are intentionally independent.
# The facts below describe what this checkpoint actually wires; time cave stays
# Ground Truth-only until its production entry is separately designed.
TARGET_PRODUCTION_FACTS: dict[str, dict[str, Any]] = {
    "black_merchant": {
        "production_readiness": "CONDITIONAL",
        "scope": "同一黑商遭遇内：买吞噬丹/木材/折扣并持续刷新；背包吞噬丹与英雄卡走各自现有 verifier，神器 Q/W/E 仅按现有开关、槽位与冷却条件释放。悬赏令仅留 Ground Truth。",
        "routes": (
            {"route": "black_merchant_swallow_pill", "readiness": "CONDITIONAL"},
            {"route": "black_merchant_wood", "readiness": "CONDITIONAL"},
            {"route": "black_merchant_discount_2_5", "readiness": "CONDITIONAL"},
        ),
        "ground_truth_only": False,
    },
    "inventory_item": {
        "production_readiness": "CONDITIONAL",
        "scope": "吞噬丹（羁绊至少 4 个 + WAIT_DEVOUR_DAN）与英雄卡（完成进化 + WAIT_HERO_CHOICE）可实测；海盗悬赏令尚无生产模板和后置验证，仅采 Ground Truth。",
        "routes": (
            {"route": "inventory_swallow_pill", "readiness": "CONDITIONAL"},
            {"route": "inventory_hero_card", "readiness": "CONDITIONAL"},
            {"route": "inventory_pirate_bounty", "readiness": "BLOCKED_GROUND_TRUTH_ONLY"},
        ),
        "ground_truth_only": False,
    },
    "boss_challenge": {
        "production_readiness": "CONDITIONAL",
        "scope": "整链 capture 复用现有 Mediator.tick()，覆盖 tqtz→配置 Boss→转场→战后存档 8 卡；战后时光之穴与传家宝配置 Boss 路径均使用末位可识别 Boss fallback；本 target 隔离自动秘境。",
        "routes": (
            {"route": "configured_boss", "readiness": "CONDITIONAL"},
            {"route": "postgame_archive_8", "readiness": "CONDITIONAL"},
            {"route": "postgame_heirloom", "readiness": "CONDITIONAL"},
            {"route": "tqtz_to_sgzx", "readiness": "CONDITIONAL"},
        ),
        "ground_truth_only": False,
    },
    "time_cave": {
        "production_readiness": "CONDITIONAL",
        "scope": "已打开时光之穴 Boss 列表后，复用现有 handler 选择最后一个可识别 Boss 并确认真实挑战 HUD。",
        "routes": ({"route": "open_time_cave_boss_list", "readiness": "CONDITIONAL"},),
        "ground_truth_only": False,
    },
    "heirloom": {
        "production_readiness": "CONDITIONAL",
        "scope": "战后广场可由 production 自动打开传家宝 NPC；配置 cjb_boss 时优先匹配，未配置时滚到底选择最后一个模板可识别 Boss。Live PASS 仍必须由真实挑战 HUD 后置确认。",
        "routes": ({"route": "heirloom_boss_selection", "readiness": "CONDITIONAL"},),
        "ground_truth_only": False,
    },
    "secret_realm": {
        "production_readiness": "CONDITIONAL",
        "scope": "只允许现有 OpenGreatRift/ConfirmGreatRift；Live PASS 必须到真实 HUD + _secret_realm_active。",
        "routes": ({"route": "secret_realm_entry", "readiness": "CONDITIONAL"},),
        "ground_truth_only": False,
    },
    "lobby_hitch": {
        "production_readiness": "CONDITIONAL",
        "scope": "在大厅房间列表按自定义搜索词搜房；支持刷新 CD、点击房间行与失败弹窗兜底；不点 Quick Join、创建房间或开始游戏。",
        "routes": (
            {"route": "lobby_hitch_search", "readiness": "CONDITIONAL"},
            {"route": "lobby_hitch_join", "readiness": "CONDITIONAL"},
        ),
        "ground_truth_only": False,
    },
    "lobby_search": {
        "production_readiness": "CONDITIONAL",
        "scope": "调用大厅生产 handler 持续搜索、跳过失败房、按 5 秒 CD 刷新并在合规房点击客人准备；禁止 Quick Join、创建房间或开始游戏。",
        "routes": ({"route": "lobby_hitch_search_ready", "readiness": "CONDITIONAL"},),
        "ground_truth_only": False,
    },
    "s01_lobby_surface_identity": {
        "production_readiness": "GROUND_TRUTH_ONLY",
        "scope": "只采集 production 页面身份、Platform Modal Shell、Ready/CancelReady contract、WindowRole、HWND 与 capture generation；默认零输入。",
        "routes": ({"route": "lobby_surface_classification", "readiness": "GROUND_TRUTH_ONLY"},),
        "ground_truth_only": True,
    },
    "s02_lobby_platform_modal": {
        "production_readiness": "CONDITIONAL",
        "scope": "只调用 production tick 的统一 Platform Modal Shell neutral Esc/X recovery；禁止所有正向业务按钮。",
        "routes": ({"route": "platform_modal_neutral_dismiss", "readiness": "CONDITIONAL"},),
        "ground_truth_only": False,
    },
    "s03_lobby_room_ready": {
        "production_readiness": "CONDITIONAL",
        "scope": "真实 ROOM 中验证 production Ready/CancelReady contract；仅 ready contract=ready 允许 Ready，UNKNOWN 零输入。",
        "routes": ({"route": "room_ready_contract", "readiness": "CONDITIONAL"},),
        "ground_truth_only": False,
    },
    "s04_lobby_single_hwnd_room": {
        "production_readiness": "GROUND_TRUTH_ONLY",
        "scope": "只采集单 KK HWND/全屏 ROOM identity continuity 与 confirmed_room_hwnd；默认零输入。",
        "routes": ({"route": "single_hwnd_room_continuity", "readiness": "GROUND_TRUTH_ONLY"},),
        "ground_truth_only": True,
    },
    "s05_lobby_search_join_ready": {
        "production_readiness": "CONDITIONAL",
        "scope": "调用 production Lobby handler 完成搜索、Join、异常 modal neutral recovery、ROOM、Ready 与 CancelReady fresh-confirm；禁止 Quick Join/建房/开始。",
        "routes": ({"route": "search_join_ready_chain", "readiness": "CONDITIONAL"},),
        "ground_truth_only": False,
    },
    "s06_lobby_recovery_chain": {
        "production_readiness": "CONDITIONAL",
        "scope": "在 S01–S05 通过后运行 10–20 分钟或至少 5 次 join attempt，统计 Lobby 恢复和零安全回归指标。",
        "routes": ({"route": "lobby_recovery_soak", "readiness": "CONDITIONAL"},),
        "ground_truth_only": False,
    },
    "public_backpack_deposit": {
        "production_readiness": "CONDITIONAL",
        "scope": "K：局内 HUD 上物品栏除 1 号外至少两件可搬物；production 开包、物品栏→个人格→公共格、搬完关闭。公共格占用变化才算 probe PASS。",
        "routes": ({"route": "public_backpack_deposit", "readiness": "CONDITIONAL"},),
        "ground_truth_only": False,
    },
    "hitch_runtime": {
        "production_readiness": "CONDITIONAL",
        "scope": "从当前蹭车局随时接管：已确认 HUD 不再检查压力转移，直接复用自动任务、四挑战与既有战后存档/时光之穴/传家宝末位 Boss fallback。",
        "routes": (
            {"route": "hitch_pressure_transfer", "readiness": "CONDITIONAL"},
            {"route": "hitch_auto_task_and_challenges", "readiness": "CONDITIONAL"},
            {"route": "hitch_postgame_boss_fallback", "readiness": "CONDITIONAL"},
        ),
        "ground_truth_only": False,
    },
    "solo_ingame_chain": {
        "production_readiness": "CONDITIONAL",
        "scope": "从 KK 地图/建房/房间或游戏内选关页接管真实 normal_farm；沿用正式看板自动建房，覆盖生产 L0、Hero setup、MAIN_LINE、局尾与既有秘境/Boss/存档/传家宝路线。",
        "routes": (
            {"route": "solo_lobby_to_stage_to_hud", "readiness": "CONDITIONAL"},
            {"route": "solo_ingame_l1_policy_handlers", "readiness": "CONDITIONAL"},
            {"route": "solo_ingame_postgame_secret_or_boss", "readiness": "CONDITIONAL"},
        ),
        "ground_truth_only": False,
    },
    "hitch_lobby_chain": {
        "production_readiness": "CONDITIONAL",
        "scope": "HITCH_FULL_NATURAL_E2E：从真实 ROOM_LIST 连续调用 production Mediator.tick()，覆盖搜房、Join、blocking modal recovery、ROOM/Ready、Pressure、局内黑商/宝物/背包、Victory/Failure、真实退出、fresh 回厅与下一轮；Public Backpack 在真实 GT 前只记录 GT_CAPTURE。",
        "routes": (
            {"route": "production_lobby_hitch_search_join_ready", "readiness": "CONDITIONAL"},
            {"route": "production_hitch_pressure_and_ingame", "readiness": "CONDITIONAL"},
            {"route": "production_hitch_outcome_exit_lobby_return", "readiness": "CONDITIONAL"},
            {"route": "public_backpack_gt_capture", "readiness": "BLOCKED_UNTIL_GT"},
        ),
        "ground_truth_only": False,
    },
    "choice_bond_skill": {
        "production_readiness": "CONDITIONAL",
        "scope": "只调用现有面板 FSM / 打开羁绊或技能面板入口；PASS 需要 mutation 后置。",
        "routes": ({"route": "production_panel_fsm_bond_skill", "readiness": "CONDITIONAL"},),
        "ground_truth_only": False,
    },
    "treasure": {
        "production_readiness": "CONDITIONAL",
        "scope": "只调用现有宝物面板入口；PASS 需要 mutation 后置。",
        "routes": ({"route": "production_panel_fsm_treasure", "readiness": "CONDITIONAL"},),
        "ground_truth_only": False,
    },
    "hero_evolve": {
        "production_readiness": "CONDITIONAL",
        "scope": "只进入 production 进化分支；PASS 需要 _evolve_feedback_seen 或英雄选择面板。",
        "routes": ({"route": "production_click_evolve", "readiness": "CONDITIONAL"},),
        "ground_truth_only": False,
    },
    "inventory_devour": {
        "production_readiness": "CONDITIONAL",
        "scope": "只走现有吞噬丹 verifier。",
        "routes": ({"route": "inventory_swallow_pill", "readiness": "CONDITIONAL"},),
        "ground_truth_only": False,
    },
    "inventory_hero_card": {
        "production_readiness": "CONDITIONAL",
        "scope": "只走现有英雄卡 WAIT_HERO_CHOICE verifier。",
        "routes": ({"route": "inventory_hero_card", "readiness": "CONDITIONAL"},),
        "ground_truth_only": False,
    },
    "archive_challenge": {
        "production_readiness": "CONDITIONAL",
        "scope": "复用现有 main-line 战后链：从挑战广场自动打开存档 NPC，或在已打开面板消费 1~8 卡位；PASS 必须看到挑战 HUD/后续业务页，而不是 click success。",
        "routes": ({"route": "archive_challenge_1_to_8", "readiness": "CONDITIONAL"},),
        "ground_truth_only": False,
    },
}

TARGETED_PROBE_MENU = (
    ("A", "choice_bond_skill", "羁绊 / 技能选卡"),
    ("B", "treasure", "宝物"),
    ("C", "hero_evolve", "英雄进化"),
    ("D", "inventory_devour", "背包 - 吞噬丹"),
    ("E", "inventory_hero_card", "背包 - 英雄卡"),
    ("F", "black_merchant", "黑商"),
    ("G", "archive_challenge", "存档挑战 1~8"),
    ("H", "heirloom", "传家宝 / Boss"),
    ("I", "secret_realm", "秘境"),
    ("J", "lobby_search", "大厅搜房 / Join"),
    ("K", "public_backpack_deposit", "公共背包 GT / Deposit"),
)
TIER0_LOBBY_TARGETS = (
    "s01_lobby_surface_identity",
    "s02_lobby_platform_modal",
    "s03_lobby_room_ready",
    "s04_lobby_single_hwnd_room",
    "s05_lobby_search_join_ready",
    "s06_lobby_recovery_chain",
)
TIER0_MODAL_DISMISS_REASONS = {
    "HitchDismissPlatformModalEsc",
    "HitchDismissPlatformModalClose",
    # 主窗口「平台提示」点取消（Esc 实机关不掉）及其 Esc 兜底
    "HitchDismissPlatformPrompt",
    "HitchDismissPlatformPromptEsc",
}
TIER0_LOBBY_SAFE_REASONS = {
    "HitchSearchBox",
    "HitchSearchType",
    "HitchSearchEnter",
    "HitchSelectTab",
    "HitchRefresh",
    "HitchJoin",
    "HitchReady",
    "HitchDismissPlatformModalEsc",
    "HitchDismissPlatformModalClose",
    "HitchDismissPlatformPrompt",
    "HitchDismissPlatformPromptEsc",
    "HitchStallWatchdogEsc",
    "HitchLeaveFloorOne",
    "HitchConfirmLeave",
    "HitchLeaveRoom",
    "HitchGoHome",
}
PRIMARY_LIVE_TARGET = "hitch_lobby_chain"
PRIMARY_LIVE_SCENARIO = "HITCH_FULL_NATURAL_E2E"
PUBLIC_BACKPACK_TARGET = "public_backpack_deposit"
LONG_CHAIN_TARGETS = ("hitch_runtime", "solo_ingame_chain", "hitch_lobby_chain")
PROBE_RESULT_STATUSES = (
    "PASS",
    "FAIL",
    "BLOCKED_PRECONDITION",
    "BLOCKED_MISSING_GT",
    "BLOCKED_NO_PRODUCTION_ENTRYPOINT",
    "BLOCKED_REQUIRES_PRODUCTION_CHANGE",
    "BLOCKED_PRECHECK",
    "UNKNOWN",
    "TIMEOUT_FAIL_CLOSED",
    "ABORTED",
)

SOLO_INGAME_CHECKPOINTS = (
    "PRECHECK_OK",
    "STAGE_SELECT_CONFIRMED",
    "STAGE_TARGET_VISIBLE",
    "STAGE_SELECTED_CONFIRMED",
    "STAGE_START_REQUEST",
    "STAGE_START_CONFIRMED",
    "GAME_HWND_CONFIRMED",
    "INGAME_HUD_CONFIRMED",
    "AUTO_TASK_CONFIRMED",
    "CHALLENGE_STATE_OBSERVED",
    "L1_CYCLE_ACTIVE",
    "POSTGAME_SURFACE_CLASSIFIED",
    "POSTGAME_ROUTE_PROGRESS",
)
SOLO_OPTIONAL_EVENTS = ("BLACK_MERCHANT", "RANDOM_SKILL_PANEL", "RANDOM_BOND_PANEL", "RANDOM_TREASURE_PANEL")
SOLO_ROUTE_OBSERVATIONS = ("EARLY_CHALLENGE", "ARCHIVE_LOOT", "HEIRLOOM_ROUTE", "SECRET_REALM_ROUTE")
_WINDOW_GUARD_STATUSES = {
    "CANCELLED_NO_TARGET_HWND",
    "CANCELLED_WINDOW_INVALID",
    "CANCELLED_WINDOW_CHANGED",
    # Post-injection foreground change: the operator's desktop stole focus after
    # the input reached the game.  Environment, not a production defect.
    "CANCELLED_WINDOW_CHANGED_AFTER_INPUT",
    "CANCELLED_WINDOW_OBSCURED",
}


def _new_route_observations() -> dict[str, dict[str, Any]]:
    return {
        name: {
            "status": "NOT_OBSERVED",
            "request_status": "NOT_OBSERVED",
            "confirmation_status": "NOT_OBSERVED",
        }
        for name in SOLO_ROUTE_OBSERVATIONS
    }


def _physical_surfaces(med: Mediator, frame: Frame | None) -> dict[str, Any]:
    """Use existing production classifiers only; missing evidence stays false."""
    observed: dict[str, Any] = {
        "room": False, "platform": False, "stage": False, "stage_target": False,
        "hero": False, "hud": False, "game_hwnd": False, "boss_entry": False,
        "lobby": False, "postgame": None,
    }
    if not _frame_is_valid(frame):
        return observed
    for key, method in (
        ("room", "_find_room_start"), ("platform", "_find_map_create_room"),
        ("stage", "_find_stage_page"), ("stage_target", "_find_stage_target"),
        ("hero", "_hero_modal_buttons"), ("hud", "_is_in_game_hud"),
        ("game_hwnd", "_is_game_client_frame"),
        ("lobby", "_lobby_room_list_evidence"),
    ):
        try:
            observed[key] = bool(getattr(med, method)(frame))
        except (AttributeError, TypeError):
            continue
    try:
        observed["boss_entry"] = bool(med.find_scene(frame, "boss_entry"))
    except (AttributeError, TypeError):
        pass
    try:
        observed["postgame"] = med._post_game_state(frame)
    except (AttributeError, TypeError):
        pass
    return observed


def _production_lobby_surface(med: Mediator, frame: Frame | None) -> dict[str, Any]:
    """Normalize production lobby evidence for bundles; never classify pixels here."""
    generation = int(getattr(med, "_capture_generation", 0) or 0)
    title = str(getattr(frame, "window_title", "") or "") if frame is not None else ""
    role_value = getattr(getattr(frame, "role", None), "value", getattr(frame, "role", None))
    window_role = classify_window_role(title).value
    result: dict[str, Any] = {
        "classification": "UNKNOWN",
        "room": False,
        "room_list": False,
        "platform_modal": False,
        "ready_contract": "unknown",
        "ready_bbox": None,
        "confirmed_room_hwnd": getattr(med, "_confirmed_room_hwnd", None),
        "hwnd": getattr(frame, "hwnd", None) if frame is not None else None,
        "window_title": title,
        "window_role": window_role,
        "frame_role": role_value,
        "capture_generation": generation,
        "capture_timestamp": getattr(frame, "timestamp", None) if frame is not None else None,
        "frame_size": [getattr(frame, "width", 0), getattr(frame, "height", 0)] if frame is not None else None,
        "modal_shell": None,
        "context": None,
    }
    if not _frame_is_valid(frame):
        return result

    modal = None
    try:
        modal = med._kk_platform_modal_shell(frame)
    except (AttributeError, TypeError):
        pass
    try:
        result["context"] = str(med._detect_context(frame, "l0"))
    except (AttributeError, TypeError):
        result["context"] = None
    room = False
    room_list = False
    try:
        room = bool(med._is_confirmed_room_frame(frame))
    except (AttributeError, TypeError):
        try:
            room = bool(med._hitch_room_controls_visible(frame))
        except (AttributeError, TypeError):
            pass
    try:
        room_list = bool(med._lobby_room_list_evidence(frame))
    except (AttributeError, TypeError):
        pass
    result["room"] = room
    result["room_list"] = room_list
    if modal is not None:
        result.update({
            "classification": "PLATFORM_MODAL",
            "platform_modal": True,
            "modal_shell": _jsonable(modal),
        })
        return result
    if room and room_list:
        # Conflicting production evidence must not grant either page authority.
        result["classification"] = "UNKNOWN"
        result["context"] = "CONFLICTING_ROOM_AND_ROOM_LIST"
    elif room:
        result["classification"] = "ROOM"
        try:
            ready_state, ready_hit = med._hitch_room_ready_contract(frame)
        except (AttributeError, TypeError):
            ready_state, ready_hit = "unknown", None
        result["ready_contract"] = str(ready_state or "unknown")
        if ready_hit is not None:
            result["ready_bbox"] = [
                int(getattr(ready_hit, "x", 0)), int(getattr(ready_hit, "y", 0)),
                int(getattr(ready_hit, "w", 0)), int(getattr(ready_hit, "h", 0)),
            ]
    elif room_list:
        result["classification"] = "ROOM_LIST"
    elif window_role == WindowRole.PLATFORM.value or str(result.get("context") or "") not in {"UNKNOWN", "None", ""}:
        result["classification"] = "LOBBY"
    return result


class _SoloRouteDiagnosticsMixin:
    """Observation-only request/postcondition ledger.  No clicks, no FSM."""

    def _init_route_diagnostics(self) -> None:
        self._route_request_frame_fingerprints: dict[str, str | None] = {}
        self.route_observations = _new_route_observations()

    @staticmethod
    def _request_status(action: dict[str, Any] | None) -> str:
        status = str((action or {}).get("input_status") or "SUCCESS")
        if status in _WINDOW_GUARD_STATUSES:
            return "BLOCKED"
        if status != "SUCCESS":
            return "FAIL"
        return "PASS"

    def _route_request(self, name: str, *, action: dict[str, Any] | None, evidence: dict[str, Any], frame: Frame | None) -> None:
        item = self.route_observations[name]
        if item["request_status"] != "NOT_OBSERVED":
            return
        request_status = self._request_status(action)
        item["request_status"] = request_status
        item["request_evidence"] = _jsonable(evidence)
        self._route_request_frame_fingerprints[name] = _frame_fingerprint(frame)
        if request_status in {"FAIL", "BLOCKED"}:
            item["status"] = request_status

    def _route_confirmation(self, name: str, *, evidence: dict[str, Any]) -> None:
        item = self.route_observations[name]
        if item["request_status"] != "PASS" or item["confirmation_status"] == "PASS":
            return
        item["confirmation_status"] = "PASS"
        item["confirmation_evidence"] = _jsonable(evidence)
        item["status"] = "PASS"

    def _observe_route_diagnostics(
        self,
        med: Mediator,
        state: dict[str, Any],
        frame: Frame | None,
        surfaces: dict[str, Any],
        reason: str,
        action: dict[str, Any] | None,
        evidence: dict[str, Any],
    ) -> None:
        if reason == "ClickTQTZ":
            self._route_request("EARLY_CHALLENGE", action=action, evidence=evidence, frame=frame)
        elif reason == "ArchiveChallenge-loot":
            self._route_request("ARCHIVE_LOOT", action=action, evidence=evidence, frame=frame)
        elif reason in {"OpenGreatRift", "ConfirmGreatRift"}:
            self._route_request("SECRET_REALM_ROUTE", action=action, evidence=evidence, frame=frame)
        elif reason.startswith("BossConfigured") and surfaces.get("postgame") == "HEIRLOOM_DIALOG":
            self._route_request("HEIRLOOM_ROUTE", action=action, evidence=evidence, frame=frame)
        fingerprint = _frame_fingerprint(frame)
        for name in SOLO_ROUTE_OBSERVATIONS:
            request_fp = self._route_request_frame_fingerprints.get(name)
            if not request_fp or not fingerprint or fingerprint == request_fp:
                continue
            if name == "EARLY_CHALLENGE" and surfaces.get("boss_entry"):
                self._route_confirmation(name, evidence=evidence)
            elif name == "ARCHIVE_LOOT" and surfaces.get("postgame") == "ARCHIVE_PANEL":
                try:
                    completed = bool(med._archive_challenge_completed(frame, 3))
                except (AttributeError, TypeError):
                    completed = False
                if completed:
                    self._route_confirmation(name, evidence=evidence)
            elif name == "HEIRLOOM_ROUTE" and surfaces.get("postgame") == "HEIRLOOM_DIALOG":
                self._route_confirmation(name, evidence=evidence)
            elif name == "SECRET_REALM_ROUTE" and bool(state.get("secret_realm_active")) and bool(surfaces.get("hud")):
                self._route_confirmation(name, evidence=evidence)


class SoloIngameChainObserver(_SoloRouteDiagnosticsMixin):
    """Observe the production stage-to-post-game chain without adding FSM logic."""

    def __init__(self) -> None:
        self._observation_no = 0
        self._postgame_seen = False
        self._init_route_diagnostics()
        self.failed_reason: str | None = None
        self.blocked_reason: str | None = None
        self.blocked_evidence: dict[str, Any] | None = None
        self.manual_intervention_seen = False
        self.checkpoints = {name: {"status": "NOT_OBSERVED"} for name in SOLO_INGAME_CHECKPOINTS}
        self.optional_events = {name: {"status": "NOT_OBSERVED"} for name in SOLO_OPTIONAL_EVENTS}

    def _pass(self, name: str, *, evidence: dict[str, Any]) -> None:
        if self.checkpoints[name]["status"] == "NOT_OBSERVED":
            self.checkpoints[name] = {"status": "PASS", "evidence": _jsonable(evidence)}

    def fail(self, reason: str, *, evidence: dict[str, Any] | None = None) -> None:
        if self.failed_reason is None:
            self.failed_reason = reason
        if self.checkpoints["POSTGAME_ROUTE_PROGRESS"]["status"] == "NOT_OBSERVED":
            self.checkpoints["POSTGAME_ROUTE_PROGRESS"] = {
                "status": "FAIL", "reason": reason, "evidence": _jsonable(evidence or {}),
            }

    def block(self, reason: str, *, evidence: dict[str, Any] | None = None) -> None:
        if self.blocked_reason is None:
            self.blocked_reason = reason
            self.blocked_evidence = _jsonable(evidence or {})
        if self.checkpoints["POSTGAME_ROUTE_PROGRESS"]["status"] == "NOT_OBSERVED":
            self.checkpoints["POSTGAME_ROUTE_PROGRESS"] = {
                "status": "BLOCKED", "reason": reason, "evidence": _jsonable(evidence or {}),
            }

    def manual_intervention(self) -> None:
        self.manual_intervention_seen = True

    def precheck(self, ready: bool, detail: dict[str, Any]) -> None:
        if ready:
            self._pass("PRECHECK_OK", evidence=detail)
        else:
            self.checkpoints["PRECHECK_OK"] = {"status": "BLOCKED", "evidence": _jsonable(detail)}
            self.block("live input preflight blocked", evidence=detail)

    def observe(
        self,
        med: Mediator,
        state: dict[str, Any],
        frame: Frame | None,
        trace_row: dict[str, Any] | None,
        action: dict[str, Any] | None,
    ) -> bool:
        self._observation_no += 1
        phase = str(state.get("phase") or "")
        context = str(state.get("context") or "")
        reason = str((action or {}).get("reason") or "")
        controls = [item for item in list((trace_row or {}).get("controls") or []) if isinstance(item, dict)]
        surfaces = _physical_surfaces(med, frame)
        evidence = {
            "observation": self._observation_no,
            "phase": phase,
            "context": context,
            "reason": reason,
            "physical_surfaces": surfaces,
        }
        if phase == "ERROR":
            self.fail("production runtime entered ERROR", evidence=evidence)
        if action is not None and context == "UNKNOWN":
            self.fail("production input on UNKNOWN context", evidence=evidence)
        if str((action or {}).get("input_status") or "") in _WINDOW_GUARD_STATUSES:
            self.block("environment window-ownership guard rejected production input", evidence=evidence)
        if surfaces["stage"]:
            self._pass("STAGE_SELECT_CONFIRMED", evidence=evidence)
        if surfaces["stage"] and surfaces["stage_target"]:
            self._pass("STAGE_TARGET_VISIBLE", evidence=evidence)
        if surfaces["stage"] and bool(getattr(med, "_stage_selected", False)):
            self._pass("STAGE_SELECTED_CONFIRMED", evidence=evidence)
        if reason == "StageStart":
            self._pass("STAGE_START_REQUEST", evidence=evidence)
        if self.checkpoints["STAGE_START_REQUEST"]["status"] == "PASS" and (surfaces["hero"] or surfaces["hud"]):
            self._pass("STAGE_START_CONFIRMED", evidence=evidence)
        if surfaces["game_hwnd"] and frame is not None and getattr(frame, "hwnd", None):
            self._pass("GAME_HWND_CONFIRMED", evidence=evidence)
        if surfaces["hud"]:
            self._pass("INGAME_HUD_CONFIRMED", evidence=evidence)
        if surfaces["hud"] and any(item.get("control") == "auto_task" and item.get("state") == "ON" for item in controls):
            self._pass("AUTO_TASK_CONFIRMED", evidence=evidence)
        if surfaces["hud"] and any(str(item.get("control", "")).endswith("_challenge") and item.get("state") == "ON" for item in controls):
            self._pass("CHALLENGE_STATE_OBSERVED", evidence=evidence)
        if surfaces["hud"] and state.get("l1_cycle_step") is not None and (
            controls or list((trace_row or {}).get("scenes") or [])
        ):
            self._pass("L1_CYCLE_ACTIVE", evidence=evidence)
        postgame = surfaces["postgame"]
        if postgame:
            self._postgame_seen = True
            self._pass("POSTGAME_SURFACE_CLASSIFIED", evidence={**evidence, "surface": postgame})
        if self._postgame_seen and (
            bool(state.get("post_game_pending"))
            or bool(state.get("secret_realm_active"))
            or reason in {"ContinueGame", "BossConfigured", "OpenGreatRift", "ConfirmGreatRift"}
        ):
            self._pass("POSTGAME_ROUTE_PROGRESS", evidence=evidence)
        reason_lower = reason.lower()
        for name, markers in (
            ("BLACK_MERCHANT", ("blackmerchant", "merchant")),
            ("RANDOM_SKILL_PANEL", ("skill",)),
            ("RANDOM_BOND_PANEL", ("bond",)),
            ("RANDOM_TREASURE_PANEL", ("treasure",)),
        ):
            if self.optional_events[name]["status"] == "NOT_OBSERVED" and any(marker in reason_lower for marker in markers):
                self.optional_events[name] = {"status": "OBSERVED", "evidence": _jsonable(evidence)}
        self._observe_route_diagnostics(med, state, frame, surfaces, reason, action, evidence)
        return self.is_pass

    @property
    def is_pass(self) -> bool:
        return (
            self.failed_reason is None
            and self.blocked_reason is None
            and not self.manual_intervention_seen
            and all(self.checkpoints[name]["status"] == "PASS" for name in SOLO_INGAME_CHECKPOINTS)
        )

    def payload(self) -> dict[str, Any]:
        return {
            "contract_version": 1,
            "checkpoints": _jsonable(self.checkpoints),
            "optional_events": _jsonable(self.optional_events),
            "route_observations": _jsonable(self.route_observations),
            "natural_e2e": "PASS" if self.is_pass else (
                "DISQUALIFIED_MANUAL_INTERVENTION" if self.manual_intervention_seen
                else ("BLOCKED" if self.blocked_reason else "PENDING_OR_FAILED")
            ),
            "failure_reason": self.failed_reason,
            "blocked_reason": self.blocked_reason,
            "blocked_evidence": _jsonable(self.blocked_evidence),
        }


class HitchLobbyChainObserver:
    """Ledger for the primary HITCH_FULL_NATURAL_E2E production chain.

    This object observes production state/trace only. It does not search, pick
    rows, choose seats, dismiss modals, or implement a recovery FSM.
    """

    _PRESSURE_CORE_REASONS = {
        "OpenSkillPanel", "OpenBondPanel", "OpenTreasurePanel", "ClickEvolve",
        "UseInventory-swallow_pill", "UseInventory-hero-card", "Pickup-Z",
        "Artifact-Q", "Artifact-W", "Artifact-E", "ClearPressureMonsters",
    }

    def __init__(self, *, required_rounds: int = 3, require_archaeology: bool = False) -> None:
        # 配置 1 局也要能达标：只兜底非法值，不再把下限抬到 3。
        self.required_rounds = max(1, int(required_rounds or 3))
        self.require_archaeology = bool(require_archaeology)
        self.failed_reason: str | None = None
        self.blocked_reason: str | None = None
        self.blocked_evidence: dict[str, Any] | None = None
        self.manual_intervention_seen = False
        self.observation_no = 0
        self._last_observation_at = time.monotonic()
        self._last_progress_at = self._last_observation_at
        self._last_surface_key: tuple[Any, ...] | None = None
        self._search_request_generation: int | None = None
        self._join_request_generation: int | None = None
        self._ready_request_generation: int | None = None
        self._pressure_request_generation: int | None = None
        self._modal_request_generation: int | None = None
        self._merchant_request_generation: int | None = None
        self._talisman_request_generation: int | None = None
        self._active_round = False
        self._outcome_seen_this_round = False
        self._last_outcome: str | None = None
        self._last_outcome_token: tuple[Any, ...] | None = None
        self._last_lobby_generation: int | None = None
        self._last_watchdog_episodes: int | None = None
        self._permanent_stall_counted = False
        self.checkpoints = {
            "PRECHECK_OK": {"status": "NOT_OBSERVED"},
            "ROOM_LIST_CONFIRMED": {"status": "NOT_OBSERVED"},
            "SEARCH_CONFIRMED": {"status": "NOT_OBSERVED"},
            "ROOM_JOINED": {"status": "NOT_OBSERVED"},
            "READY_CONFIRMED": {"status": "NOT_OBSERVED"},
            "MODAL_RECOVERY": {"status": "NOT_OBSERVED"},
            "INGAME_HUD_CONFIRMED": {"status": "NOT_OBSERVED"},
            "PRESSURE_CONFIRMED": {"status": "NOT_OBSERVED"},
            "OUTCOME_OBSERVED": {"status": "NOT_OBSERVED"},
            "LOBBY_RETURN_CONFIRMED": {"status": "NOT_OBSERVED"},
            "CONFIGURED_ROUNDS_CONFIRMED": {"status": "NOT_OBSERVED"},
            "ARCHAEOLOGY_HANDOFF_CONFIRMED": {
                "status": "NOT_OBSERVED" if self.require_archaeology else "NOT_REQUIRED"
            },
        }
        self.metrics: dict[str, Any] = {
            "rounds_started": 0,
            "rooms_joined": 0,
            "ready_confirmed": 0,
            "pressure_confirmed": 0,
            "pressure_core_failure": 0,
            "modals_dismissed": 0,
            "merchant_devour_acquired": 0,
            "talisman_acquired": 0,
            "public_bag_deposit_attempts": 0,
            "public_bag_deposit_confirmed": 0,
            "public_bag_deposit_failed": 0,
            "victory_count": 0,
            "failure_count": 0,
            "lobby_returns": 0,
            "longest_stall_s": 0.0,
            "silent_stop_count": 0,
            "zero_input_watchdog_episodes": 0,
            "manual_intervention_count": 0,
            "unexpected_inputs": 0,
            "reclassifications": 0,
            "recoveries": 0,
            "permanent_zero_input_stall": 0,
            "room_list_as_room_false_positive": 0,
            "room_as_modal_false_positive": 0,
            "ready_repeat": 0,
            "unknown_seat_exit": 0,
            "blind_go_home": 0,
        }

    def _pass(self, name: str, *, evidence: dict[str, Any]) -> None:
        if self.checkpoints[name]["status"] == "NOT_OBSERVED":
            self.checkpoints[name] = {"status": "PASS", "evidence": _jsonable(evidence)}

    def fail(self, reason: str, *, evidence: dict[str, Any] | None = None) -> None:
        if self.failed_reason is None:
            self.failed_reason = reason
        self._last_failure_evidence = _jsonable(evidence or {})

    def block(self, reason: str, *, evidence: dict[str, Any] | None = None) -> None:
        if self.blocked_reason is None:
            self.blocked_reason = reason
            self.blocked_evidence = _jsonable(evidence or {})

    def manual_intervention(self) -> None:
        self.manual_intervention_seen = True
        self.metrics["manual_intervention_count"] += 1

    def precheck(self, ready: bool, detail: dict[str, Any]) -> None:
        if ready:
            self._pass("PRECHECK_OK", evidence=detail)
        else:
            self.checkpoints["PRECHECK_OK"] = {"status": "BLOCKED", "evidence": _jsonable(detail)}
            self.block("live input preflight blocked", evidence=detail)

    @staticmethod
    def _action_success(action: dict[str, Any] | None) -> bool:
        if (action or {}).get("input_success") is False:
            return False
        return str((action or {}).get("input_status") or "SUCCESS") == "SUCCESS"

    @staticmethod
    def _generation(state: dict[str, Any], surface: dict[str, Any]) -> int:
        value = surface.get("capture_generation")
        if value is None:
            value = state.get("evidence_gen")
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def _mark_recovery(self, surface: dict[str, Any], generation: int) -> None:
        if self._modal_request_generation is None:
            return
        if generation <= self._modal_request_generation:
            return
        if surface.get("classification") != "PLATFORM_MODAL":
            self.metrics["modals_dismissed"] += 1
            self.metrics["recoveries"] += 1
            self._modal_request_generation = None
            self._pass("MODAL_RECOVERY", evidence=surface) if "MODAL_RECOVERY" in self.checkpoints else None

    def observe(
        self,
        med: Mediator,
        state: dict[str, Any],
        frame: Frame | None,
        trace_row: dict[str, Any] | None,
        action: dict[str, Any] | None,
    ) -> bool:
        self.observation_no += 1
        now = time.monotonic()
        elapsed = max(0.0, now - self._last_observation_at)
        self._last_observation_at = now
        self.metrics["longest_stall_s"] = round(max(float(self.metrics["longest_stall_s"]), elapsed), 3)
        phase = str(state.get("phase") or "")
        reason = str((action or {}).get("reason") or "")
        surface = _production_lobby_surface(med, frame)
        physical = _physical_surfaces(med, frame)
        generation = self._generation(state, surface)
        surface_key = (
            surface.get("classification"), surface.get("ready_contract"),
            surface.get("hwnd"), generation,
        )
        if self._last_surface_key is not None and surface_key[:3] != self._last_surface_key[:3]:
            self.metrics["reclassifications"] += 1
        if surface_key[:3] != (None, None, None):
            self._last_progress_at = now
        self._last_surface_key = surface_key
        evidence = {
            "observation": self.observation_no,
            "phase": phase,
            "reason": reason,
            "surface": surface,
            "physical_surfaces": physical,
            "trace": _jsonable(trace_row or {}),
        }

        watchdog_episodes = state.get("runtime_watchdog_stall_episodes_total")
        try:
            watchdog_episodes = int(watchdog_episodes) if watchdog_episodes is not None else None
        except (TypeError, ValueError):
            watchdog_episodes = None
        if watchdog_episodes is not None:
            if self._last_watchdog_episodes is not None and watchdog_episodes > self._last_watchdog_episodes:
                self.metrics["zero_input_watchdog_episodes"] += (
                    watchdog_episodes - self._last_watchdog_episodes
                )
            self._last_watchdog_episodes = watchdog_episodes
        watchdog_stalled = bool(state.get("runtime_watchdog_stalled"))
        if watchdog_stalled:
            first_stall_at = state.get("runtime_watchdog_first_stall_at")
            try:
                stagnant_for = max(0.0, time.time() - float(first_stall_at))
            except (TypeError, ValueError):
                stagnant_for = 0.0
            self.metrics["longest_stall_s"] = round(
                max(float(self.metrics["longest_stall_s"]), stagnant_for), 3
            )
            if stagnant_for >= 60.0 and not self._permanent_stall_counted:
                self.metrics["permanent_zero_input_stall"] += 1
                self._permanent_stall_counted = True
                self.fail("production zero-input watchdog exceeded bounded stall budget", evidence=evidence)
        else:
            self._permanent_stall_counted = False

        if phase == "ERROR":
            self.fail("production runtime entered ERROR", evidence=evidence)
        if (
            str((trace_row or {}).get("loop_action") or "") == "Break"
            and phase != "ERROR"
            and not (self.require_archaeology and bool(state.get("archaeology_handoff_confirmed")))
        ):
            self.metrics["silent_stop_count"] += 1
            self.fail("production loop returned Break without ERROR evidence", evidence=evidence)
        if action is not None:
            if not self._action_success(action):
                if reason == "HitchPressureTransfer":
                    self.metrics["pressure_core_failure"] += 1
                if reason.startswith("PublicBackpack") or reason.startswith("PUBLIC_BACKPACK"):
                    self.metrics["public_bag_deposit_failed"] += 1
            if surface.get("classification") == "UNKNOWN":
                self.fail("production input on UNKNOWN lobby/game surface", evidence=evidence)
            if reason in {"HitchReady", "HitchReadyTimeoutExit"} and surface.get("ready_contract") != "ready":
                if reason == "HitchReady" and self.metrics["ready_confirmed"] > 0:
                    self.metrics["ready_repeat"] += 1
            if reason in {"HitchLeaveFloorOne", "HitchConfirmLeave", "HitchLeaveRoom", "HitchGoHome", "HitchReadyTimeoutExit"}:
                if surface.get("classification") == "UNKNOWN" or (
                    surface.get("classification") == "ROOM"
                    and surface.get("ready_contract") == "unknown"
                ):
                    self.metrics["unknown_seat_exit"] += 1
            if reason == "HitchGoHome" and not bool(surface.get("room") or surface.get("room_list")):
                self.metrics["blind_go_home"] += 1
            if reason.startswith(("CreateRoom", "QuickJoin", "RoomStart", "StartHeroMode")) and not bool(state.get("hitch_goal_archaeology_handoff")):
                self.metrics["unexpected_inputs"] += 1
                self.fail("forbidden positive Lobby input in hitch chain", evidence=evidence)
            if reason in self._PRESSURE_CORE_REASONS and not bool(state.get("hitch_pressure_transferred")):
                self.metrics["pressure_core_failure"] += 1

            if reason in {"HitchSearchBox", "HitchSearchType", "HitchSearchEnter"} and self._action_success(action):
                self._search_request_generation = generation
            elif reason == "HitchJoin" and self._action_success(action):
                self._join_request_generation = generation
            elif reason == "HitchReady" and self._action_success(action):
                if self.metrics["ready_confirmed"] > 0:
                    self.metrics["ready_repeat"] += 1
                self._ready_request_generation = generation
            elif reason == "HitchPressureTransfer" and self._action_success(action):
                self._pressure_request_generation = generation
            elif reason in TIER0_MODAL_DISMISS_REASONS and self._action_success(action):
                self._modal_request_generation = generation
            elif reason == "BlackMerchant-swallow_pill" and self._action_success(action):
                self._merchant_request_generation = generation
            elif (
                ("treasure" in reason.lower() or "宝物" in reason)
                and ("选择" in reason or "select" in reason.lower())
                and self._action_success(action)
            ):
                self._talisman_request_generation = generation
            elif reason.startswith("PublicBackpack") or reason.startswith("PUBLIC_BACKPACK"):
                self.metrics["public_bag_deposit_attempts"] += 1

        if surface.get("classification") == "ROOM_LIST":
            self._pass("ROOM_LIST_CONFIRMED", evidence=evidence)
            if self._search_request_generation is not None and generation > self._search_request_generation:
                self._search_request_generation = None
                self._pass("SEARCH_CONFIRMED", evidence=evidence)
            if self._active_round and self._outcome_seen_this_round:
                self.metrics["lobby_returns"] += 1
                self._active_round = False
                self._outcome_seen_this_round = False
                self._last_outcome = None
                self._last_lobby_generation = generation
                self._pass("LOBBY_RETURN_CONFIRMED", evidence=evidence)
        elif surface.get("classification") == "ROOM":
            if self.metrics["rounds_started"] == 0 or not self._active_round:
                self.metrics["rounds_started"] += 1
                self.metrics["rooms_joined"] += 1
                self._active_round = True
                self._outcome_seen_this_round = False
            if self._join_request_generation is not None and generation > self._join_request_generation:
                self._join_request_generation = None
                self._pass("ROOM_JOINED", evidence=evidence)
            if surface.get("ready_contract") in {"cancel_ready", "start"}:
                if self._ready_request_generation is not None and generation > self._ready_request_generation:
                    self.metrics["ready_confirmed"] += 1
                    self._ready_request_generation = None
                    self._pass("READY_CONFIRMED", evidence=evidence)
                elif self.metrics["ready_confirmed"] == 0 and self._active_round:
                    # A manually already-ready room is valid proof for the
                    # chain only when the production contract says so.
                    self.metrics["ready_confirmed"] += 1
                    self._pass("READY_CONFIRMED", evidence=evidence)
            if self._search_request_generation is not None and generation > self._search_request_generation:
                self._search_request_generation = None
                self._pass("SEARCH_CONFIRMED", evidence=evidence)
        if surface.get("classification") == "PLATFORM_MODAL":
            # A room never yields modal authority; this is only a diagnostic
            # consistency check around the production shell detector.
            if physical.get("room"):
                self.metrics["room_as_modal_false_positive"] += 1
        if surface.get("room") and surface.get("room_list"):
            self.metrics["room_list_as_room_false_positive"] += 1
        self._mark_recovery(surface, generation)

        if physical.get("hud") and physical.get("game_hwnd"):
            self._pass("INGAME_HUD_CONFIRMED", evidence=evidence)
            if self._pressure_request_generation is not None and generation > self._pressure_request_generation:
                if bool(state.get("hitch_pressure_transferred")):
                    self.metrics["pressure_confirmed"] += 1
                    self._pressure_request_generation = None
                    self._pass("PRESSURE_CONFIRMED", evidence=evidence)
            if self._pressure_request_generation is None and bool(state.get("hitch_pressure_transferred")):
                self._pass("PRESSURE_CONFIRMED", evidence=evidence)

        trace_s0 = (trace_row or {}).get("s0") or {}
        outcome = str(
            state.get("round_outcome")
            or trace_s0.get("round_outcome")
            or trace_s0.get("last_outcome")
            or ""
        )
        outcome_token = (
            outcome,
            state.get("success_count"),
            state.get("failure_count"),
            state.get("disconnect_count"),
            state.get("timeout_count"),
        )
        if outcome and outcome_token != self._last_outcome_token:
            self._last_outcome_token = outcome_token
            self._last_outcome = outcome
            self._outcome_seen_this_round = True
            if outcome == "VICTORY":
                self.metrics["victory_count"] += 1
            elif outcome in {"FAILURE", "TIMEOUT", "DISCONNECT"}:
                self.metrics["failure_count"] += 1
            self._pass("OUTCOME_OBSERVED", evidence=evidence)

        if self._merchant_request_generation is not None and generation > self._merchant_request_generation:
            pending = state.get("pending_action")
            merchant = state.get("merchant_fsm") or {}
            if (
                pending is None
                and int(merchant.get("purchases") or 0) > 0
                and str(merchant.get("phase") or "") != "VERIFYING"
            ):
                self.metrics["merchant_devour_acquired"] += 1
                self._merchant_request_generation = None
        if self._talisman_request_generation is not None and generation > self._talisman_request_generation:
            if (
                state.get("panel_state") == "CLOSED"
                and state.get("l1_cycle_step") in {"hitch_idle", "merchant", None}
            ):
                self.metrics["talisman_acquired"] += 1
                self._talisman_request_generation = None
        if (
            self.metrics["rounds_started"] >= self.required_rounds
            and self.metrics["lobby_returns"] >= self.required_rounds
        ):
            self._pass("CONFIGURED_ROUNDS_CONFIRMED", evidence={"metrics": self.metrics})
        if self.require_archaeology and bool(state.get("archaeology_handoff_confirmed")):
            self._pass("ARCHAEOLOGY_HANDOFF_CONFIRMED", evidence=evidence)
        return self.is_pass

    @property
    def is_pass(self) -> bool:
        required = {
            "PRECHECK_OK", "ROOM_LIST_CONFIRMED", "SEARCH_CONFIRMED", "ROOM_JOINED",
            "READY_CONFIRMED", "MODAL_RECOVERY", "INGAME_HUD_CONFIRMED", "PRESSURE_CONFIRMED",
            "OUTCOME_OBSERVED", "LOBBY_RETURN_CONFIRMED", "CONFIGURED_ROUNDS_CONFIRMED",
        }
        if self.require_archaeology:
            required.add("ARCHAEOLOGY_HANDOFF_CONFIRMED")
        safety_zero = (
            self.metrics["silent_stop_count"] == 0
            and self.metrics["permanent_zero_input_stall"] == 0
            and self.metrics["room_list_as_room_false_positive"] == 0
            and self.metrics["room_as_modal_false_positive"] == 0
            and self.metrics["ready_repeat"] == 0
            and self.metrics["unknown_seat_exit"] == 0
            and self.metrics["blind_go_home"] == 0
            and self.metrics["unexpected_inputs"] == 0
            and self.metrics["pressure_core_failure"] == 0
        )
        return (
            self.failed_reason is None
            and self.blocked_reason is None
            and not self.manual_intervention_seen
            and safety_zero
            and self.metrics["rounds_started"] >= self.required_rounds
            and self.metrics["lobby_returns"] >= self.required_rounds
            and all(self.checkpoints[name]["status"] == "PASS" for name in required)
        )

    def payload(self) -> dict[str, Any]:
        return {
            "contract_version": 2,
            "scenario": PRIMARY_LIVE_SCENARIO,
            "primary_target": PRIMARY_LIVE_TARGET,
            "required_rounds": self.required_rounds,
            "require_archaeology": self.require_archaeology,
            "checkpoints": _jsonable(self.checkpoints),
            "metrics": _jsonable(self.metrics),
            "public_backpack": {
                "status": "GT_CAPTURE_PENDING" if self.metrics["public_bag_deposit_attempts"] == 0 else (
                    "PASS" if self.metrics["public_bag_deposit_confirmed"] else "PENDING_OR_FAILED"
                ),
                "natural_e2e_eligible": False,
            },
            "natural_e2e": "PASS" if self.is_pass else (
                "DISQUALIFIED_MANUAL_INTERVENTION" if self.manual_intervention_seen
                else ("BLOCKED" if self.blocked_reason else "PENDING_OR_FAILED")
            ),
            "failure_reason": self.failed_reason,
            "failure_evidence": _jsonable(getattr(self, "_last_failure_evidence", None)),
            "blocked_reason": self.blocked_reason,
            "blocked_evidence": _jsonable(self.blocked_evidence),
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
            "UseInventory-swallow_pill",
            "UseInventory-hero-card",
            "Artifact-Q",
            "Artifact-W",
            "Artifact-E",
        },
        "inventory_item": {"UseInventory-swallow_pill", "UseInventory-hero-card"},
        "boss_challenge": {
            "ArchiveChallenge-skill", "ArchiveChallenge-strengthen",
            "ArchiveChallenge-gem", "ArchiveChallenge-loot",
            "ArchiveChallenge-key", "ArchiveChallenge-recast",
            "ArchiveChallenge-blessing", "ArchiveChallenge-skill2",
            "BossConfigured", "BossConfigured-scroll",
        },
        "heirloom": {
            # H may begin on the post-game plaza. Opening the verified
            # heirloom NPC is production behavior, so the narrow probe must
            # not cancel it before the Boss selection branch can run.
            "OpenHeirloomChallenges", "BossConfigured", "BossConfigured-scroll",
            "BossLastVisibleFallback", "BossLastVisibleFallback-scroll",
            "PublicBackpackClose",
        },
        "secret_realm": {"OpenGreatRift", "ConfirmGreatRift"},
        "lobby_hitch": {
            "HitchRefresh", "HitchJoin", "HitchGoHome", "HitchLeaveRoom",
            "HitchDismissPopup", "HitchSearchBox", "HitchSearchType",
            "HitchSearchEnter", "HitchSelectTab",
        },
        "lobby_search": {
            "HitchSearchBox", "HitchRefresh", "HitchJoin", "HitchReady",
            "HitchDismissPopup", "HitchLeaveFloorOne", "HitchConfirmLeave",
            "HitchSelectTab", "HitchDismissPlatformModalEsc",
            "HitchDismissPlatformModalClose", "HitchLeaveRoom", "HitchGoHome",
            "HitchDismissPlatformPrompt", "HitchDismissPlatformPromptEsc",
            "HitchStallWatchdogEsc",
        },
        "s02_lobby_platform_modal": TIER0_MODAL_DISMISS_REASONS,
        "s03_lobby_room_ready": {"HitchReady"},
        "s05_lobby_search_join_ready": TIER0_LOBBY_SAFE_REASONS,
        "s06_lobby_recovery_chain": TIER0_LOBBY_SAFE_REASONS,
        "hitch_runtime": None,  # Whole-loop runtime target: do not restrict reasons
        "solo_ingame_chain": None,
        "hitch_lobby_chain": None,
        "public_backpack_deposit": {
            "PublicBackpackDeposit",
            "PUBLIC_BACKPACK_DEPOSIT",
            "PublicBackpackDepositRightClick",
            "PublicBackpackDepositB",
            "PublicBackpackStash",
            "PublicBackpackClose",
        },
        "choice_bond_skill": {
            "OpenSkillPanel", "OpenBondPanel", "技能选择", "羁绊选择",
            "CloseSelfOpenedPanel", "CloseNaturalPanel", "CloseFallback",
            "PanelClose", "CompactSkillChoice",
        },
        "treasure": {
            "OpenTreasurePanel", "宝物选择", "CloseSelfOpenedPanel",
            "CloseNaturalPanel", "CloseFallback", "PanelClose",
        },
        "hero_evolve": {"ClickEvolve", "SelectEvolutionCard"},
        "inventory_devour": {"UseInventory-swallow_pill"},
        "inventory_hero_card": {"UseInventory-hero-card"},
        "archive_challenge": {
            "OpenArchiveChallenges", "CloseArchivePanel",
            "BossConfigured", "BossConfigured-scroll",
            "BossLastVisibleFallback", "BossLastVisibleFallback-scroll",
            "ArchiveChallenge-skill", "ArchiveChallenge-strengthen",
            "ArchiveChallenge-gem", "ArchiveChallenge-loot",
            "ArchiveChallenge-key", "ArchiveChallenge-recast",
            "ArchiveChallenge-blessing", "ArchiveChallenge-skill2",
            "BossConfigured", "BossConfigured-scroll",
            "BossLastVisibleFallback", "BossLastVisibleFallback-scroll",
        },
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


def _git_branch(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return "unknown"
    branch = result.stdout.strip()
    return branch if result.returncode == 0 and branch else "unknown"


def _window_evidence(frame: Frame | None) -> dict[str, Any]:
    if frame is None:
        return {
            "hwnd": None,
            "title": None,
            "rect": None,
            "role": None,
            "valid": False,
        }
    return {
        "hwnd": getattr(frame, "hwnd", None),
        "title": str(getattr(frame, "window_title", "") or ""),
        "rect": [
            int(getattr(frame, "left", 0) or 0),
            int(getattr(frame, "top", 0) or 0),
            int(getattr(frame, "width", 0) or 0),
            int(getattr(frame, "height", 0) or 0),
        ],
        "role": getattr(frame, "role", None),
        "valid": _frame_is_valid(frame),
    }


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
        "boss_challenge_scroll_attempts": getattr(med, "_boss_challenge_scroll_attempts", None),
        "hitch_refresh_count": getattr(med, "_hitch_join_refresh_count", 0),
        "hitch_search_actions": getattr(med, "_hitch_search_actions", []),
        "hitch_rejected_rows": sorted(getattr(med, "_hitch_rejected_row_ys", set())),
        "hitch_blacklisted_room_count": len(getattr(med, "_hitch_blacklisted_room_keys", set())),
        "hitch_refresh_required": getattr(med, "_hitch_refresh_required", False),
        "hitch_pressure_transferred": getattr(med, "_hitch_pressure_transferred", False),
        "hitch_pressure_click_at": getattr(med, "_hitch_pressure_click_at", None),
        "hitch_pressure_request_generation": getattr(med, "_hitch_pressure_request_generation", None),
        "hitch_ready_confirmed_at": getattr(med, "_hitch_ready_confirmed_at", None),
        "hitch_re_search": getattr(med, "_hitch_re_search", False),
        "hitch_status": getattr(med, "_hitch_status", None),
        # Per-round stage read from the in-game HUD (or the stage page as a
        # fallback).  It used to reach stdout only, so the 2026-09-25 run's
        # stages had to be re-read from frames afterwards.
        "hitch_round_stage": getattr(med, "_hitch_stats_current_stage", None),
        "hitch_stage_counts": dict(getattr(med, "_hitch_stats_stages", {}) or {}),
        "hitch_round_challenges": list(getattr(med, "_hitch_stats_current_challenges", []) or []),
        "hitch_goal_archaeology_handoff": getattr(med, "_hitch_goal_archaeology_handoff", False),
        "archaeology_handoff_confirmed": getattr(med, "_archaeology_handoff_confirmed", False),
        "game_count": getattr(med, "game_count", None),
        "disconnect_count": getattr(med, "_disconnect_count", None),
        "timeout_count": getattr(med, "_timeout_count", None),
        "last_outcome": getattr(getattr(med, "_last_outcome", None), "name", None),
        "outcome_recorded": getattr(med, "_outcome_recorded", None),
        "success_count": getattr(med, "_success_count", None),
        "failure_count": getattr(med, "_failure_count", None),
        "round_outcome": getattr(getattr(med, "_round_outcome", None), "name", None),
        "runtime_watchdog_stall_episodes_total": getattr(
            med, "_runtime_watchdog_stall_episodes_total", None
        ),
        "runtime_watchdog_stalled": getattr(med, "_runtime_watchdog_stalled", None),
        "runtime_watchdog_first_stall_at": getattr(
            med, "_runtime_watchdog_first_stall_at", None
        ),
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
        "input_status": record.get("status"),
        "input_success": record.get("success"),
    }
    args = record.get("args") or []
    if record.get("method") in {"click", "right_click", "scroll", "search_text"} and len(args) >= 2:
        action["point"] = [int(args[0]), int(args[1])]
    if record.get("method") == "search_text" and len(args) >= 3:
        action["text"] = str(args[2])
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
    *,
    before_frame: Frame | None = None,
    input_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Add only target-specific, production-observable business evidence."""
    reason = str((action or {}).get("reason") or "")

    if target in {"s03_lobby_room_ready", "s05_lobby_search_join_ready"}:
        return _target_postcondition_snapshot(
            "lobby_search",
            med,
            frame,
            after_state,
            action,
            base,
            before_frame=before_frame,
            input_record=input_record,
        )

    if target == "s02_lobby_platform_modal":
        if reason not in {"", *TIER0_MODAL_DISMISS_REASONS}:
            return {"observed": False, "state": "unexpected_action", "kind": reason or "platform_modal"}
        if reason == "":
            return {"observed": False, "state": "modal_waiting", "kind": "platform_modal"}
        if not bool((input_record or {}).get("success")):
            return {"observed": False, "state": "input_rejected", "kind": "platform_modal_dismiss"}
        fresh = bool(
            _frame_is_valid(before_frame)
            and _frame_is_valid(frame)
            and getattr(before_frame, "timestamp", None) != getattr(frame, "timestamp", None)
        )
        modal_visible = False
        try:
            modal_visible = med._kk_platform_modal_shell(frame) is not None if _frame_is_valid(frame) else True
        except (AttributeError, TypeError):
            modal_visible = True
        return {
            "observed": bool(fresh and not modal_visible),
            "state": "confirmed" if fresh and not modal_visible else "modal_not_dismissed",
            "kind": "platform_modal_dismiss",
            "authoritative": True,
            "fresh_capture": fresh,
            "modal_visible": modal_visible,
        }

    if target == PUBLIC_BACKPACK_TARGET:
        verifier = getattr(med, "_public_backpack_deposit_postcondition", None)
        if callable(verifier) and _frame_is_valid(frame):
            try:
                verified = verifier(before_frame, frame)
            except (AttributeError, TypeError, ValueError):
                verified = None
            if isinstance(verified, dict):
                return {**_jsonable(verified), "authoritative": bool(verified.get("observed"))}
            if verified is True:
                return {
                    "observed": True,
                    "state": "confirmed",
                    "kind": "public_backpack_deposit",
                    "authoritative": True,
                }
        return {
            "observed": False,
            "state": "production_deposit_verifier_missing",
            "kind": "public_backpack_deposit",
            "authoritative": False,
        }

    if target == "lobby_search":
        if reason not in {
            "", "HitchSearchBox", "HitchRefresh", "HitchJoin", "HitchReady",
            "HitchDismissPopup", "HitchLeaveFloorOne", "HitchConfirmLeave",
            "HitchSelectTab", "HitchDismissPlatformModalEsc",
            "HitchDismissPlatformModalClose", "HitchLeaveRoom", "HitchGoHome",
        }:
            return {"observed": False, "state": "unexpected_action", "kind": reason or "lobby_search"}
        if reason == "HitchDismissPopup":
            if not bool((input_record or {}).get("success")):
                return {"observed": False, "state": "input_rejected", "kind": "lobby_popup_dismiss"}
            if not (_frame_is_valid(before_frame) and _frame_is_valid(frame)):
                return {"observed": False, "state": "missing_frame_evidence", "kind": "lobby_popup_dismiss"}
            if before_frame.bgr.shape != frame.bgr.shape:
                return {"observed": False, "state": "incomparable_frame_evidence", "kind": "lobby_popup_dismiss"}
            delta = cv2.absdiff(before_frame.bgr, frame.bgr)
            changed = int(np.count_nonzero(np.any(delta > 8, axis=2)))
            rejected_rows = list(after_state.get("hitch_rejected_rows") or [])
            observed = changed >= 8 or bool(rejected_rows)
            return {
                "observed": observed,
                "state": "confirmed" if observed else "popup_close_not_observed",
                "kind": "lobby_popup_dismiss",
                "authoritative": False,
                "visual_change": {"changed_pixels": changed, "rejected_rows": rejected_rows},
            }
        if reason == "HitchLeaveFloorOne":
            if not bool((input_record or {}).get("success")):
                return {"observed": False, "state": "input_rejected", "kind": "lobby_floor_one_rejected"}
            if not (_frame_is_valid(before_frame) and _frame_is_valid(frame)):
                return {"observed": False, "state": "missing_frame_evidence", "kind": "lobby_floor_one_rejected"}
            if before_frame.bgr.shape != frame.bgr.shape:
                return {"observed": False, "state": "incomparable_frame_evidence", "kind": "lobby_floor_one_rejected"}
            try:
                room_gone = not med._hitch_room_controls_visible(frame)
            except (AttributeError, TypeError):
                room_gone = False
            delta = cv2.absdiff(before_frame.bgr, frame.bgr)
            changed = int(np.count_nonzero(np.any(delta > 8, axis=2)))
            observed = room_gone and changed >= 8
            return {
                "observed": observed,
                "state": "confirmed" if observed else "waiting_lobby_return",
                "kind": "lobby_floor_one_rejected",
                "authoritative": False,
                "visual_change": {"changed_pixels": changed},
            }
        if reason == "HitchConfirmLeave":
            if not bool((input_record or {}).get("success")):
                return {"observed": False, "state": "input_rejected", "kind": "lobby_exit_confirm"}
            if not (_frame_is_valid(before_frame) and _frame_is_valid(frame)):
                return {"observed": False, "state": "missing_frame_evidence", "kind": "lobby_exit_confirm"}
            if before_frame.bgr.shape != frame.bgr.shape:
                return {"observed": False, "state": "incomparable_frame_evidence", "kind": "lobby_exit_confirm"}
            delta = cv2.absdiff(before_frame.bgr, frame.bgr)
            changed = int(np.count_nonzero(np.any(delta > 8, axis=2)))
            return {
                "observed": changed >= 8,
                "state": "confirmed" if changed >= 8 else "waiting_lobby_return",
                "kind": "lobby_exit_confirm",
                "authoritative": False,
                "visual_change": {"changed_pixels": changed},
            }
        if reason == "HitchReady":
            if not bool((input_record or {}).get("success")):
                return {"observed": False, "state": "input_rejected", "kind": "lobby_hitch_ready"}
            if not (_frame_is_valid(before_frame) and _frame_is_valid(frame)):
                return {"observed": False, "state": "missing_frame_evidence", "kind": "lobby_hitch_ready"}
            if before_frame.bgr.shape != frame.bgr.shape:
                return {"observed": False, "state": "incomparable_frame_evidence", "kind": "lobby_hitch_ready"}
            ready_gone = False
            controls_visible = False
            try:
                ready_gone = med._find_hitch_ready_button(frame) is None
                controls_visible = med._hitch_room_controls_visible(frame)
            except (AttributeError, TypeError):
                pass
            delta = cv2.absdiff(before_frame.bgr, frame.bgr)
            changed = int(np.count_nonzero(np.any(delta > 8, axis=2)))
            observed = ready_gone and controls_visible and changed >= 8
            return {
                "observed": observed,
                "state": "confirmed" if observed else "ready_not_observed",
                "kind": "lobby_hitch_ready",
                "authoritative": True,
                "visual_change": {"changed_pixels": changed},
            }
        if reason in {"", "HitchJoin"}:
            if reason == "HitchJoin" and not bool((input_record or {}).get("success")):
                return {"observed": False, "state": "input_rejected", "kind": "lobby_hitch_join"}
            room_controls = False
            room_start = None
            if _frame_is_valid(frame):
                try:
                    room_controls = med._hitch_room_controls_visible(frame)
                    room_start = med._find_room_start(frame)
                except (AttributeError, TypeError):
                    pass
            if room_controls or (
                after_state.get("phase") == "ROOM_WAITING" and room_start is not None
            ):
                return {
                    "observed": True,
                    "state": "confirmed",
                    "kind": "lobby_hitch_in_room",
                    # Entering the room is intermediate evidence.  The short
                    # live probe succeeds only after the guest Ready action.
                    "authoritative": False,
                }
            return {
                "observed": False,
                "state": "waiting_room_confirm" if reason == "HitchJoin" else "not_observed",
                "kind": "lobby_hitch_join",
            }
        result_ok = bool((input_record or {}).get("success"))
        point = (action or {}).get("point")
        if not result_ok or not isinstance(point, list) or len(point) != 2:
            return {"observed": False, "state": "input_rejected", "kind": "lobby_search_input"}
        if not (_frame_is_valid(before_frame) and _frame_is_valid(frame)):
            return {"observed": False, "state": "missing_frame_evidence", "kind": "lobby_search_input"}
        x, y = int(point[0]), int(point[1])
        if reason == "HitchRefresh":
            before_list = before_frame.bgr[
                int(before_frame.height * 0.34):int(before_frame.height * 0.90),
                int(before_frame.width * 0.16):int(before_frame.width * 0.97),
            ]
            after_list = frame.bgr[
                int(frame.height * 0.34):int(frame.height * 0.90),
                int(frame.width * 0.16):int(frame.width * 0.97),
            ]
            if before_list.shape != after_list.shape or before_list.size == 0:
                return {"observed": False, "state": "incomparable_result_evidence", "kind": "lobby_search_refresh"}
            delta = cv2.absdiff(before_list, after_list)
            metrics = {
                "changed_pixels": int(np.count_nonzero(np.any(delta > 8, axis=2))),
                "crop_pixels": int(delta.shape[0] * delta.shape[1]),
                "mean_absdiff": round(float(delta.mean()), 4),
            }
            before_x, before_y = x - int(before_frame.left), y - int(before_frame.top)
            after_x, after_y = x - int(frame.left), y - int(frame.top)
            half_w, half_h = 48, 20
            before_button = before_frame.bgr[
                max(0, before_y - half_h):min(before_frame.height, before_y + half_h),
                max(0, before_x - half_w):min(before_frame.width, before_x + half_w),
            ]
            after_button = frame.bgr[
                max(0, after_y - half_h):min(frame.height, after_y + half_h),
                max(0, after_x - half_w):min(frame.width, after_x + half_w),
            ]
            button_changed = 0
            if before_button.shape == after_button.shape and before_button.size:
                button_delta = cv2.absdiff(before_button, after_button)
                button_changed = int(np.count_nonzero(np.any(button_delta > 8, axis=2)))
            observed = metrics["changed_pixels"] >= 8 or button_changed >= 8
            refresh_count = int(after_state.get("hitch_refresh_count", 0) or 0)
            return {
                "observed": observed,
                "state": "confirmed" if observed else "refresh_not_observed",
                "kind": "lobby_search_refresh",
                "authoritative": False,
                "visual_change": {
                    "room_list": metrics,
                    "refresh_button": {"changed_pixels": button_changed},
                    "refresh_count": refresh_count,
                },
            }
        before_x, before_y = x - int(before_frame.left), y - int(before_frame.top)
        after_x, after_y = x - int(frame.left), y - int(frame.top)
        half_w, half_h = 96, 18
        before_crop = before_frame.bgr[
            max(0, before_y - half_h):min(before_frame.height, before_y + half_h),
            max(0, before_x - half_w):min(before_frame.width, before_x + half_w),
        ]
        after_crop = frame.bgr[
            max(0, after_y - half_h):min(frame.height, after_y + half_h),
            max(0, after_x - half_w):min(frame.width, after_x + half_w),
        ]
        if before_crop.shape != after_crop.shape or before_crop.size == 0:
            return {"observed": False, "state": "incomparable_frame_evidence", "kind": "lobby_search_input"}
        delta = cv2.absdiff(before_crop, after_crop)
        changed_pixels = int(np.count_nonzero(np.any(delta > 8, axis=2)))
        search_box_metrics = {
            "changed_pixels": changed_pixels,
            "crop_pixels": int(delta.shape[0] * delta.shape[1]),
            "mean_absdiff": round(float(delta.mean()), 4),
        }
        before_list = before_frame.bgr[
            int(before_frame.height * 0.34):int(before_frame.height * 0.90),
            int(before_frame.width * 0.16):int(before_frame.width * 0.97),
        ]
        after_list = frame.bgr[
            int(frame.height * 0.34):int(frame.height * 0.90),
            int(frame.width * 0.16):int(frame.width * 0.97),
        ]
        if before_list.shape != after_list.shape or before_list.size == 0:
            return {"observed": False, "state": "incomparable_result_evidence", "kind": "lobby_search_input"}
        list_delta = cv2.absdiff(before_list, after_list)
        list_changed_pixels = int(np.count_nonzero(np.any(list_delta > 8, axis=2)))
        room_list_metrics = {
            "changed_pixels": list_changed_pixels,
            "crop_pixels": int(list_delta.shape[0] * list_delta.shape[1]),
            "mean_absdiff": round(float(list_delta.mean()), 4),
        }
        metrics = {"search_box": search_box_metrics, "room_list": room_list_metrics}
        existing_results = False
        if changed_pixels >= 8 and med is not None:
            try:
                existing_results = bool(med._lobby_room_list_evidence(frame))
            except (AttributeError, TypeError):
                existing_results = False
        if changed_pixels >= 8 and (list_changed_pixels >= 8 or existing_results):
            return {
                "observed": True,
                "state": "confirmed" if list_changed_pixels >= 8 else "confirmed_existing_results",
                "kind": "lobby_search_input",
                "authoritative": False,
                "visual_change": metrics,
            }
        state = "input_not_observed" if changed_pixels < 8 else "search_results_not_observed"
        return {
            "observed": False,
            "state": state,
            "kind": "lobby_search_input",
            "visual_change": metrics,
        }

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
        if "UseInventory-swallow_pill" in reason and base.get("observed") is True:
            return {"observed": True, "state": "confirmed", "kind": "inventory_swallow_pill"}
        if "UseInventory-hero-card" in reason and base.get("observed") is True:
            return {"observed": True, "state": "confirmed", "kind": "inventory_hero_card"}
        return {"observed": False, "state": "not_observed", "kind": reason or "merchant_target"}

    # Inventory pass remains limited to production routes with a real verifier.
    # Pirate bounty orders stay Ground Truth only until their postcondition is known.
    if target == "inventory_item":
        if "UseInventory-swallow_pill" in reason and base.get("observed") is True:
            return {"observed": True, "state": "confirmed", "kind": "inventory_swallow_pill"}
        if "UseInventory-hero-card" in reason and base.get("observed") is True:
            return {"observed": True, "state": "confirmed", "kind": "inventory_hero_card"}
    # Time-cave and heirloom selection use the existing configured-Boss
    # handler; success requires the real in-game challenge HUD.
    if target in {"time_cave", "heirloom", "boss_challenge"} and reason in {"BossConfigured", "CloseArchivePanel"} and _frame_is_valid(frame):
        try:
            if med._post_game_state(frame) is None and med._is_in_game_hud(frame):
                return {"observed": True, "state": "confirmed", "kind": "destination_hud"}
            if target == "time_cave" and reason == "BossConfigured":
                return {"observed": True, "state": "confirmed", "kind": "time_cave_boss_fallback"}
        except (AttributeError, TypeError):
            pass

    if target == "secret_realm":
        if after_state.get("secret_realm_active") and _frame_is_valid(frame):
            try:
                if med._is_in_game_hud(frame):
                    return {"observed": True, "state": "confirmed", "kind": "secret_realm_hud"}
            except (AttributeError, TypeError):
                pass
        return {"observed": False, "state": "waiting", "kind": "secret_realm_hud"}

    if target == "lobby_hitch":
        room_anchor = None
        if _frame_is_valid(frame):
            try:
                room_anchor = med.find_scene(frame, "room_start")
            except (AttributeError, TypeError):
                room_anchor = None
        if (
            "HitchJoin" in reason
            and after_state.get("phase") == "ROOM_WAITING"
            and room_anchor is not None
        ):
            return {"observed": True, "state": "confirmed", "kind": "lobby_hitch_in_room"}
        if "HitchJoin" in reason:
            return {"observed": False, "state": "waiting_room_confirm", "kind": "lobby_hitch_join"}
        if "HitchRefresh" in reason:
            return {"observed": False, "state": "partial_refresh_only", "kind": "lobby_hitch_refresh"}
        return {"observed": False, "state": "not_observed", "kind": reason or "lobby_hitch_search"}

    if target in {"choice_bond_skill", "treasure"}:
        panel_state = str(after_state.get("panel_state") or "")
        if panel_state == "WAIT_MUTATION" or (
            str(after_state.get("panel_kind") or "") in {"skill", "bond", "treasure"}
            and panel_state in {"CLOSING", "COOLDOWN"}
        ):
            return {"observed": True, "state": "confirmed", "kind": "panel_mutation"}
        return {"observed": False, "state": "waiting", "kind": "panel_mutation"}

    if target == "hero_evolve":
        if reason == "ClickEvolve":
            try:
                seen = bool(med._evolve_feedback_seen(frame)) if _frame_is_valid(frame) else False
            except (AttributeError, TypeError):
                seen = False
            if seen or bool(getattr(med, "_evolve_awaiting_hero_pick", False)):
                return {"observed": True, "state": "confirmed", "kind": "evolve_feedback"}
            return {"observed": False, "state": "waiting", "kind": "evolve_feedback"}
        if reason == "SelectEvolutionCard":
            return {"observed": True, "state": "confirmed", "kind": "evolve_hero_pick"}
        return {"observed": False, "state": "not_observed", "kind": reason or "hero_evolve"}

    if target == "inventory_devour":
        if "UseInventory-swallow_pill" in reason and base.get("observed") is True:
            return {"observed": True, "state": "confirmed", "kind": "inventory_swallow_pill"}
        return {"observed": False, "state": "not_observed", "kind": reason or "inventory_devour"}

    if target == "inventory_hero_card":
        if "UseInventory-hero-card" in reason and base.get("observed") is True:
            return {"observed": True, "state": "confirmed", "kind": "inventory_hero_card"}
        return {"observed": False, "state": "not_observed", "kind": reason or "inventory_hero_card"}

    if target == "archive_challenge":
        if reason.startswith("ArchiveChallenge-") and _frame_is_valid(frame):
            try:
                hud = bool(med._is_in_game_hud(frame)) and med._post_game_state(frame) is None
            except (AttributeError, TypeError):
                hud = False
            if hud:
                return {"observed": True, "state": "confirmed", "kind": "archive_challenge_hud"}
            return {"observed": False, "state": "waiting", "kind": "archive_challenge_hud"}
        return {"observed": False, "state": "not_observed", "kind": reason or "archive_challenge"}

    if target == "hitch_lobby_chain":
        if after_state.get("phase") == "ROOM_WAITING":
            return {"observed": True, "state": "confirmed", "kind": "lobby_hitch_in_room", "authoritative": False}
        if _frame_is_valid(frame):
            try:
                if med._is_in_game_hud(frame) and med._is_game_client_frame(frame):
                    # An in-game HUD is only an intermediate checkpoint.  The
                    # hitch target is authoritative after the configured
                    # number of complete rounds, never on the first HUD.
                    return {
                        "observed": True,
                        "state": "confirmed",
                        "kind": "hitch_ingame_hud",
                        "authoritative": False,
                    }
            except (AttributeError, TypeError):
                pass
        return {"observed": False, "state": "waiting", "kind": "hitch_lobby_chain"}

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


def _invoke_choice_probe(med: Mediator, frame: Frame, *, cycle_step: str) -> Any:
    """Compose existing production panel entrypoints.  No card policy lives here."""
    now = time.time()
    setattr(med, "_l1_cycle_step", cycle_step)
    setattr(med, "_choice_target", cycle_step)
    anchor = None
    try:
        anchor = med._selection_anchor(frame)
    except (AttributeError, TypeError):
        anchor = None
    panel = med._tick_panel_fsm(frame, anchor, now)
    if panel is not None:
        return panel
    return med._maybe_open_choice_panel(frame, anchor=anchor)


def _invoke_target_handler(med: Mediator, target: str, frame: Frame) -> Any:
    if target in {"hitch_runtime", "solo_ingame_chain", "hitch_lobby_chain"}:
        return med.tick()
    if target == "choice_bond_skill":
        return _invoke_choice_probe(med, frame, cycle_step="bond")
    if target == "treasure":
        return _invoke_choice_probe(med, frame, cycle_step="treasure")
    if target == "hero_evolve":
        setattr(med, "_l1_cycle_step", "evolve")
        return med._tick_main_line(frame)
    if target in {"inventory_devour", "inventory_hero_card"}:
        return med._maybe_use_inventory_item(frame)
    if target in {"archive_challenge", "time_cave", "heirloom"}:
        # 业务链是「广场 → 点 NPC 开面板 → 打卡 → 关面板 → 下一段」，整条都在
        # production 里。之前 archive_challenge 直接调面板内的打卡 handler，
        # 等于要求操作者先手动把面板开好——那既不是被测的业务，也让 preflight
        # 只能死等 ARCHIVE_PANEL。统一走 production 的战后分发。
        return med._tick_main_line(frame)
    if target == PUBLIC_BACKPACK_TARGET:
        operation = getattr(med, "_maybe_public_backpack_deposit", None)
        if not callable(operation):
            return LoopAction.Continue
        return operation(frame, time.time())
    if target in {
        "lobby_hitch", "lobby_search", "s02_lobby_platform_modal",
        "s03_lobby_room_ready", "s05_lobby_search_join_ready",
    }:
        if med._lobby_room_list_evidence(frame):
            context = "LOBBY_ROOM"
            stage_page = False
            room_start = None
        elif med._hitch_room_controls_visible(frame):
            context = "ROOM_WAITING"
            stage_page = False
            room_start = None
        else:
            context = med._detect_context(frame, "l0")
            stage_page = context == "STAGE_SELECT"
            room_start = None if stage_page else med._find_room_start(frame)
        return med._tick_lobby_hitch(frame, context, room_start=room_start, stage_page=stage_page)
    contract = _target_contract(target)
    handler = getattr(med, str(contract["handler"]))
    if contract.get("call") == "frame_now":
        return handler(frame, time.time())
    return handler(frame)


def _invoke_black_merchant_probe_handlers(
    med: Mediator,
    frame: Frame,
    *,
    input_sent: Callable[[], bool],
) -> Any:
    """Compose existing production handlers for the long merchant probe.

    The adapter contributes no recognition or decision policy.  It only keeps
    the production one-input-per-tick invariant while exercising merchant,
    inventory-consumable, and artifact handlers in that order.
    """
    result = med._maybe_black_merchant(frame)
    if result is LoopAction.Break or input_sent():
        return result

    inventory_result = med._maybe_use_inventory_item(frame)
    if inventory_result is not None:
        result = inventory_result
    if result is LoopAction.Break or input_sent():
        return result

    artifact_result = med._maybe_fire_artifacts(frame)
    return artifact_result if artifact_result is not None else result


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

    if target == PUBLIC_BACKPACK_TARGET:
        return "DEPOSIT_POSTCONDITION" if observed else (
            "RIGHT_CLICK_B_GT_CAPTURE" if "right_click" in reason or "press_key" in reason
            else "BAG_SURFACE_CONFIRMED" if state.get("public_backpack_surface")
            else "ITEM_SLOT_CONFIRMED"
        )

    if target in {"s01_lobby_surface_identity", "s04_lobby_single_hwnd_room"}:
        return "SURFACE_CLASSIFIED" if observed else "CAPTURE"

    if target == "s02_lobby_platform_modal":
        return "SURFACE_RECLASSIFIED" if observed else (
            "NEUTRAL_DISMISS" if "hitchdismissplatformmodal" in reason else "MODAL_CONFIRMED"
        )

    if target in {"s03_lobby_room_ready", "s05_lobby_search_join_ready"}:
        if "hitchready" in reason:
            return "READY_CONFIRMED" if observed else "READY"
        if "hitchjoin" in reason:
            return "ROOM_WAITING_CONFIRMED" if observed else "JOIN"
        if "hitchsearch" in reason:
            return "SEARCH_CONFIRMED" if observed else "SEARCH_INPUT"
        return "ROOM_CONFIRMED" if state.get("phase") == "ROOM_WAITING" else "ROOM_DETECT"

    if target == "lobby_search":
        if "hitchready" in reason:
            return "READY_CONFIRMED" if observed else "READY"
        if "hitchleavefloorone" in reason:
            return "FLOOR_ONE_REJECTED" if observed else "LEAVE_FLOOR_ONE"
        if "hitchdismisspopup" in reason:
            return "POPUP_DISMISSED" if observed else "POPUP"
        if "hitchjoin" in reason:
            return "ROOM_WAITING_CONFIRMED" if observed else "JOIN"
        if "hitchrefresh" in reason:
            return "REFRESH_CONFIRMED" if observed else "REFRESH"
        if observed:
            return "SEARCH_CONFIRMED"
        if "hitchsearchbox" in reason:
            return "SEARCH_INPUT"
        return "LOBBY_DETECT"

    if target == "lobby_hitch":
        if state.get("phase") == "ROOM_WAITING" or observed:
            return "ROOM_WAITING_CONFIRMED"
        if "hitchjoin" in reason:
            return "JOIN"
        if "hitchrefresh" in reason:
            return "REFRESH"
        if "lobby" in template_names or "room" in template_names:
            return "SCAN"
        return "LOBBY_DETECT"

    if observed:
        return "DESTINATION_CONFIRMED"
    if "bossconfigured-scroll" in reason:
        return "ENTRY_VISIBLE"
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
        record_kwargs = dict(kwargs)
        if method == "search_text":
            record_kwargs["steps"] = getattr(self._delegate, "_last_search_steps", [])
        self._on_result(method, args, record_kwargs, result)
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

    def double_click(self, x: int, y: int, target_hwnd: int | None = None, dry_run: bool = True, delay_ms: int = 50) -> ActionResult:
        return self._call("double_click", x, y, target_hwnd=target_hwnd, dry_run=dry_run, delay_ms=delay_ms)

    def search_text(self, x: int, y: int, text: str, target_hwnd: int | None = None, dry_run: bool = True) -> ActionResult:
        return self._call("search_text", x, y, text, target_hwnd=target_hwnd, dry_run=dry_run)

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
        production_source_root: Path | None = None,
        production_source_sha: str | None = None,
    ) -> None:
        self.bundle_dir = Path(bundle_dir).resolve()
        self.frames_dir = self.bundle_dir / "frames"
        self.bundle_dir.mkdir(parents=True, exist_ok=True)
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.bundle_dir / "manifest.json"
        self.trace_path = self.bundle_dir / "trace.jsonl"
        self._trace_offset = 0
        self._recent_trace: deque[dict[str, Any]] = deque(maxlen=6)
        self._saved_by_signature: dict[str, str] = {}
        self._frame_number = 0
        self._event_number = 0
        self._last_state: dict[str, Any] | None = None
        self._pending_event_index: int | None = None
        self._blocked_recorded = False
        self._clock_start = time.monotonic()
        self.inputs_this_tick: list[dict[str, Any]] = []
        self._frame_write_queue: queue.Queue[tuple[Path, Frame] | None] = queue.Queue()
        self._frame_write_errors: list[str] = []
        self._frame_writer = threading.Thread(
            target=self._write_frame_queue,
            name="shuabao-frame-writer",
            daemon=True,
        )
        self._frame_writer.start()
        self._frame_writer_closed = False
        contract = _target_contract(target)
        production_fact = _production_fact(target)
        settings_snapshot = _settings_snapshot(settings)
        identity = _scenario_identity(
            repo_root=repo_root,
            production_source_root=production_source_root,
            production_source_sha=production_source_sha,
        )
        natural_e2e_eligible = execution_mode == "mediator_tick"
        natural_e2e_state = (
            "REQUIRED_LIVE_PASS"
            if natural_e2e_eligible
            else ("GROUND_TRUTH_ONLY" if execution_mode == "ground_truth_only" else "TARGET_PROBE_ONLY")
        )
        self.manifest: dict[str, Any] = {
            "capture_schema_version": 1,
            "bundle_id": self.bundle_dir.name,
            "run_id": self.bundle_dir.name,
            "process_pid": os.getpid(),
            "parent_process_pid": os.getppid(),
            "created_at_utc": _utc_now(),
            "timestamp": _utc_now(),
            "completed_at_utc": None,
            "target": target,
            "scenario": PRIMARY_LIVE_SCENARIO if target == PRIMARY_LIVE_TARGET else target,
            "primary_live_target": PRIMARY_LIVE_TARGET,
            "production_handler": (
                None
                if production_fact.get("ground_truth_only")
                else (
                    "Mediator.tick"
                    if execution_mode == "mediator_tick"
                    else TARGET_HANDLERS.get(target)
                )
            ),
            "production_readiness": production_fact["production_readiness"],
            "production_scope": production_fact["scope"],
            "ground_truth_only": bool(production_fact.get("ground_truth_only")),
            "target_contract": {
                key: _jsonable(contract[key])
                for key in TARGET_CONTRACT_FIELDS
            },
            "execution_mode": execution_mode,
            "tested_commit_sha": identity["harness_head"],
            "harness_sha": identity["harness_head"],
            "harness_base_sha": identity["harness_base"],
            "production_source_root": identity.get("production_source_root"),
            "production_source_sha": identity.get("production_source_sha"),
            "production_source_expected_sha": identity.get("production_source_expected_sha"),
            "production_source_clean": identity.get("production_source_clean"),
            "candidate_source_injection": identity.get("candidate_source_injection", "INACTIVE"),
            "runtime_worktree_sha": identity["runtime_worktree_sha"],
            "production_baseline_sha": identity["frozen_production_code_baseline"],
            "production_diff_status": identity["production_code_diff"],
            "ready_for_gt": bool(identity["ready_for_gt"]),
            "harness_identity": {
                "branch": identity["harness_branch"],
                "sha": identity["harness_head"],
                "harness_base_sha": identity["harness_base"],
                "production_baseline_sha": identity["frozen_production_code_baseline"],
                "production_diff_status": identity["production_code_diff"],
                "runtime_kind": "SOURCE_RUNTIME",
                "runtime_type": "SOURCE_RUNTIME",
                "runtime_worktree": identity["runtime_worktree"],
                "runtime_source_sha": identity["runtime_worktree_sha"],
                "runtime_source_path": identity.get("runtime_source_path"),
                "runtime_source_verified": identity.get("runtime_source_verified"),
                "production_source_root": identity.get("production_source_root"),
                "production_source_sha": identity.get("production_source_sha"),
                "candidate_source_injection": identity.get("candidate_source_injection", "INACTIVE"),
                "ready_for_gt": bool(identity["ready_for_gt"]),
                "mode_id": settings_snapshot.get("mode_id"),
            },
            "repo_root": str(repo_root.resolve()),
            "initial_phase": initial_phase,
            "settings": settings_snapshot,
            "window": {"hwnd": None, "title": None, "rect": None, "role": None},
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
            "final_status": "UNKNOWN",
            "final_reason": None,
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
        self.solo_observer_key: str | None = None
        self.solo_observer: SoloIngameChainObserver | HitchLobbyChainObserver | None
        if target == "solo_ingame_chain":
            self.solo_observer_key = "solo_ingame_chain"
            self.solo_observer = SoloIngameChainObserver()
            self.manifest[self.solo_observer_key] = self.solo_observer.payload()
        elif target == "hitch_lobby_chain":
            self.solo_observer_key = "hitch_lobby_chain"
            configured_rounds = getattr(settings, "hitch_cycle_num", 3)
            self.solo_observer = HitchLobbyChainObserver(
                required_rounds=configured_rounds,
                require_archaeology=str(getattr(settings, "hitch_after_goal", "solo") or "solo") == "arch",
            )
            self.manifest[self.solo_observer_key] = self.solo_observer.payload()
        else:
            self.solo_observer = None

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
        if status not in {"BLOCKED", "BLOCKED_PRECHECK", "BLOCKED_PRECONDITION"}:
            raise ValueError(f"未知 automatic blocked status: {status}")
        self._blocked_recorded = True
        if frame is not None:
            self.manifest["window"] = _window_evidence(frame)
        elif isinstance(self.manifest.get("live_preflight"), dict) and self.manifest["live_preflight"].get("window"):
            self.manifest["window"] = self.manifest["live_preflight"]["window"]
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
        self._flush_frame_writes()
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
        # PNG compression is expensive enough to distort the live tick cadence.
        # The immutable copy keeps evidence intact after capture moves to its next frame.
        self._frame_write_queue.put((path, _copy_frame(frame) or frame))
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

    def _write_frame_queue(self) -> None:
        while True:
            job = self._frame_write_queue.get()
            try:
                if job is None:
                    return
                path, frame = job
                _write_png(path, frame)
            except OSError as exc:
                self._frame_write_errors.append(str(exc))
            finally:
                self._frame_write_queue.task_done()

    def _flush_frame_writes(self) -> None:
        self._frame_write_queue.join()
        if self._frame_write_errors:
            raise OSError("; ".join(self._frame_write_errors))

    def _close_frame_writer(self) -> None:
        if self._frame_writer_closed:
            return
        self._flush_frame_writes()
        self._frame_write_queue.put(None)
        self._frame_writer.join()
        self._frame_writer_closed = True

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
                if target_observed and pending_postcondition.get("authoritative", True):
                    self._record_authoritative_target_result(
                        event_id=pending_event.get("event_id"),
                        postcondition=pending_event["postcondition"],
                        target_stage=pending_event.get("target_stage"),
                    )
                self._pending_event_index = None
                self._write_manifest(checkpoint=False)
        state_changed = self._last_state is None or before_state != after_state
        should_save = self._last_state is None or bool(self.inputs_this_tick) or state_changed or loop_action is LoopAction.Break
        self._last_state = after_state
        if not should_save:
            if self.solo_observer is not None:
                self.solo_observer.observe(
                    med, after_state, after_frame or before_frame, trace_row, action
                )
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
            before_frame=before_frame,
            input_record=input_record,
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
            "recent_trace": list(self._recent_trace),
        }
        self._event_number += 1
        self.manifest["events"].append(_jsonable(event))
        if (
            event["postcondition"].get("observed") is True
            and event["postcondition"].get("authoritative", True)
        ):
            self._record_authoritative_target_result(
                event_id=event["event_id"],
                postcondition=event["postcondition"],
                target_stage=event["target_stage"],
            )
        if action is not None and event["postcondition"].get("observed") is not True:
            self._pending_event_index = len(self.manifest["events"]) - 1
        if before_frame is not None:
            self.manifest["window"] = _window_evidence(before_frame)
        elif after_frame is not None:
            self.manifest["window"] = _window_evidence(after_frame)
        if self.solo_observer is not None:
            self.solo_observer.observe(med, after_state, after_frame or before_frame, trace_row, action)
            self.manifest[str(self.solo_observer_key)] = self.solo_observer.payload()
        self._write_manifest(checkpoint=False)
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
        after_frame = _capture_after(med) if self.inputs_this_tick else None
        if (
            self.manifest["target"] == "lobby_search"
            and self.inputs_this_tick
            and self.inputs_this_tick[0].get("success")
            and _frame_is_valid(frame)
        ):
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                probe = _target_postcondition_snapshot(
                    "lobby_search",
                    med,
                    after_frame,
                    {},
                    _action_from_tick(med, self.inputs_this_tick),
                    {},
                    before_frame=frame,
                    input_record=self.inputs_this_tick[0],
                )
                if probe.get("observed") is True:
                    break
                time.sleep(0.2)
                after_frame = _capture_after(med)
        return self.record_tick(
            med,
            phase_before=phase_before,
            before_state=before_state,
            before_frame=frame,
            after_frame=after_frame,
            loop_action=result if isinstance(result, LoopAction) else LoopAction.Continue,
            at_s=at_s,
        )

    def _write_manifest(self, *, checkpoint: bool = True) -> None:
        if not checkpoint:
            return
        payload = dict(self.manifest)
        payload["frame_count"] = len(self.manifest["frames"])
        payload["event_count"] = len(self.manifest["events"])
        payload["recent_trace"] = list(self._recent_trace)
        self.manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def finalize(self) -> Path:
        self._close_frame_writer()
        self._read_trace()
        self.manifest["completed_at_utc"] = _utc_now()
        if self.solo_observer is not None:
            self.manifest[str(self.solo_observer_key)] = self.solo_observer.payload()
            # Hitch HUD/room observations are intermediate evidence.  Promote
            # the target result only after the observer has verified every
            # required round and lobby return; this prevents a first-HUD
            # capture from being reported as a natural-E2E PASS.
            if (
                self.manifest.get("target") == "hitch_lobby_chain"
                and getattr(self.solo_observer, "is_pass", False)
            ):
                last_event = (self.manifest.get("events") or [{}])[-1]
                self._record_authoritative_target_result(
                    event_id=last_event.get("event_id"),
                    postcondition={
                        "kind": "hitch_rounds_and_archaeology_complete"
                        if getattr(self.solo_observer, "require_archaeology", False)
                        else "hitch_rounds_complete",
                    },
                    target_stage="ARCHAEOLOGY_HANDOFF_CONFIRMED"
                    if getattr(self.solo_observer, "require_archaeology", False)
                    else "CONFIGURED_ROUNDS_CONFIRMED",
                )
        window = self.manifest.get("window") or {}
        preflight_window = (self.manifest.get("live_preflight") or {}).get("window") or {}
        if not window.get("hwnd") and preflight_window:
            self.manifest["window"] = preflight_window
        self.manifest["final_status"], self.manifest["final_reason"] = self._compute_final_status()
        self._write_manifest()
        return self.manifest_path

    def _compute_final_status(self) -> tuple[str, str]:
        preflight = self.manifest.get("live_preflight") or {}
        preflight_status = str(preflight.get("status") or "")
        if preflight_status in {"BLOCKED_PRECHECK", "BLOCKED_PRECONDITION"}:
            return preflight_status, "; ".join(preflight.get("blocked_reasons") or [preflight_status])
        if self.manifest.get("ready_for_gt") is False and self.manifest.get("execution_mode") != "ground_truth_only":
            if str((self.manifest.get("capture_options") or {}).get("requested_live_input")) in {"True", "true"} or preflight_status == "BLOCKED_PRECHECK":
                reasons = list((self.manifest.get("harness_identity") or {}).get("blocked_reasons") or [])
                reasons.extend(preflight.get("blocked_reasons") or [])
                return "BLOCKED_PRECHECK", "; ".join(reasons) or "READY FOR GT = NO"
        if self.solo_observer is not None and getattr(self.solo_observer, "blocked_reason", None):
            return "BLOCKED_PRECONDITION", str(self.solo_observer.blocked_reason)
        if self.solo_observer is not None and getattr(self.solo_observer, "manual_intervention_seen", False):
            return "ABORTED", "MANUAL_INTERVENTION"
        failures = list(self.manifest.get("automatic_failures") or [])
        fail_notes = [str(item.get("note") or item.get("status") or "") for item in failures]
        if any("emergency" in note.lower() or "shift+f12" in note.lower() for note in fail_notes):
            return "ABORTED", "emergency stop"
        if any(str(item.get("status")) in {"BLOCKED", "BLOCKED_PRECHECK", "BLOCKED_PRECONDITION"} for item in failures):
            status = str(failures[-1].get("status") or "BLOCKED_PRECONDITION")
            return status, str(failures[-1].get("note") or status)
        if any("timeout" in note.lower() for note in fail_notes):
            return "TIMEOUT_FAIL_CLOSED", fail_notes[-1] if fail_notes else "timeout"
        if self.manifest.get("target_result", {}).get("authoritative"):
            return "PASS", "authoritative business postcondition"
        if self.solo_observer is not None and getattr(self.solo_observer, "is_pass", False):
            return "PASS", "observer business postcondition"
        if self.solo_observer is not None and getattr(self.solo_observer, "failed_reason", None):
            return "FAIL", str(self.solo_observer.failed_reason)
        if failures or self.manifest.get("verification", {}).get("fail_bookmark_seen"):
            return "FAIL", fail_notes[-1] if fail_notes else "FAIL bookmark"
        return "UNKNOWN", "no authoritative business postcondition"


def _capture_after(med: Mediator) -> Frame | None:
    """Capture once after an input; ordinary no-action ticks never call this."""
    try:
        return _copy_frame(capture(med._capture_title(), role=_role_for_phase(med.phase)))
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


def _git_paths_clean(repo_root: Path, *pathspecs: str) -> bool | None:
    """Check only the injected production source path, not runtime captures."""
    try:
        result = subprocess.run(
            [
                "git", "status", "--porcelain", "--untracked-files=all", "--",
                *(pathspecs or ("src/shuabao",)),
            ],
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


def _module_source_path(module_name: str) -> Path | None:
    module = sys.modules.get(module_name)
    raw = getattr(module, "__file__", None) if module is not None else None
    if not raw:
        return None
    try:
        return Path(raw).resolve()
    except OSError:
        return None


def _scenario_identity(
    *,
    repo_root: Path = ROOT,
    automation_exe: Path | None = None,
    require_exe: bool = False,
    production_source_root: Path | None = None,
    production_source_sha: str | None = None,
) -> dict[str, Any]:
    """Return Harness identity plus an auditable candidate-source injection.

    ``live_harness_identity.identity_report`` intentionally protects the
    Harness worktree.  Tier-0 additionally proves that the imported
    ``shuabao`` package is from the frozen production candidate and that only
    its production source path is clean; runtime bundles are outside that
    source-path check.
    """
    repo_root = Path(repo_root).resolve()
    identity = dict(identity_report(
        repo_root=repo_root,
        automation_exe=automation_exe,
        require_exe=require_exe,
    ))
    source_root = production_source_root or _configured_production_source_root()
    if source_root is None:
        return identity

    source_root = Path(source_root).resolve()
    expected_sha = str(
        production_source_sha
        or _configured_production_source_sha()
        or PRODUCTION_TEST_CANDIDATE_SHA
    ).strip()
    reasons = [
        str(reason)
        for reason in identity.get("blocked_reasons") or []
        # The base helper sees this process's intentionally injected package
        # and reports only its Harness-path mismatch. Re-prove the path below.
        if not str(reason).startswith("imported shuabao is")
        and not str(reason).startswith("production code diff is NOT_CLEAN")
    ]
    package_path = _module_source_path("shuabao")
    expected_package = (source_root / "src" / "shuabao").resolve()
    source_sha = _commit_sha(source_root)
    source_clean = _git_paths_clean(source_root, "src/shuabao")
    source_ok = source_root.is_dir() and (source_root / "src" / "shuabao" / "__init__.py").is_file()
    package_ok = bool(package_path and (package_path == expected_package / "__init__.py" or expected_package in package_path.parents))
    if not source_ok:
        reasons.append(f"production source root is missing or has no shuabao package: {source_root}")
    if not expected_sha:
        reasons.append("production candidate SHA is not specified; explicit --production-source-sha required")
    elif source_sha != expected_sha:
        reasons.append(f"production candidate SHA mismatch: expected={expected_sha} actual={source_sha}")
    if source_clean is not True:
        reasons.append("production candidate src/shuabao is not clean")
    if not package_ok:
        reasons.append(f"imported shuabao is {package_path}, not {expected_package}")

    identity.update({
        "production_source_root": str(source_root),
        "production_source_expected_sha": expected_sha,
        "production_source_sha": source_sha,
        "production_source_clean": source_clean,
        "candidate_source_injection": "ACTIVE",
        "runtime_worktree": str(source_root),
        "runtime_worktree_sha": source_sha,
        "runtime_source_path": str(package_path) if package_path else None,
        "runtime_source_verified": package_ok and bool(expected_sha) and source_sha == expected_sha and source_clean is True,
        "blocked_reasons": reasons,
        "ready_for_gt": not reasons,
        "match": "READY" if not reasons else "NO",
    })
    return identity


def _build_identity_check(
    *,
    repo_root: Path,
    automation_exe: Path | None,
    build_identity_path: Path | None = None,
    source_sha: str | None = None,
    source_clean: bool | None = None,
    allow_dev_source: bool = False,
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
    if allow_dev_source and automation_exe is None:
        # Source-runtime may skip EXE matching, but never skips the production
        # baseline / worktree gate in `_live_input_preflight`.
        record["status"] = "READY"
        record["dev_source_override"] = True
        record["runtime_kind"] = "SOURCE_RUNTIME"
        return record
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


def _window_preflight(settings: Settings, target: str | None = None) -> tuple[Frame | None, dict[str, Any]]:
    # Only targets that intentionally start in KK own the L0 window.
    is_lobby = target in {
        "lobby_hitch", "lobby_search", "hitch_lobby_chain",
        *TIER0_LOBBY_TARGETS,
    }
    role = "l0" if is_lobby else "l1"
    title = "" if is_lobby else str(getattr(settings, "window_title_contains", "") or "")
    try:
        frame = capture(title, role=role, allow_fallback=True)
    except Exception as exc:
        return None, {
            "status": "BLOCKED",
            "requested_title": title,
            "reason": f"window capture exception: {exc}",
        }
    if (
        target == "solo_ingame_chain"
        and not _frame_is_valid(frame)
        and getattr(frame, "error", None) != "Window is minimized"
    ):
        # The solo contract starts on the KK map / create-room / room page,
        # before any game client exists (live 2026-09-14: every KK start was
        # BLOCKED on "Target window not found: '英雄三国'").  Fall back to the
        # KK window only; _start_surface_preflight must still classify it as
        # a production L0 start surface before any input.
        try:
            kk = capture("", role="l0", allow_fallback=True)
        except Exception:
            kk = None
        kk_title = str(getattr(kk, "window_title", "") or "").lower()
        if _frame_is_valid(kk) and any(token in kk_title for token in ("kk", "英雄三国", "warcraft")):
            frame, role, title = kk, "l0", ""
    window_title = str(getattr(frame, "window_title", "") or "")
    is_minimized = getattr(frame, "error", None) == "Window is minimized"
    if is_minimized and getattr(frame, "hwnd", None):
        # A live run cannot verify its start surface from a minimized target.
        # Report the actionable reason here; the caller will send zero input.
        status = "BLOCKED"
        reason = "target window is minimized; restore it before starting live capture"
    else:
        status = "READY" if _frame_is_valid(frame) else "BLOCKED"
        reason = getattr(frame, "error", None)
    if is_lobby and window_title and not any(
        token in window_title.lower() for token in ("kk", "英雄三国", "warcraft")
    ):
        status = "BLOCKED"
        reason = f"unexpected lobby window title: {window_title}"
    record = {
        "status": status,
        "requested_title": title,
        "hwnd": getattr(frame, "hwnd", None),
        "title": window_title,
        "rect": [
            int(getattr(frame, "left", 0) or 0),
            int(getattr(frame, "top", 0) or 0),
            int(getattr(frame, "width", 0) or 0),
            int(getattr(frame, "height", 0) or 0),
        ],
        "role": getattr(frame, "role", None) or role,
        "size": [getattr(frame, "width", 0), getattr(frame, "height", 0)],
        "frame_fingerprint": _frame_fingerprint(frame),
        "reason": reason,
    }
    return frame, record


def _start_surface_preflight(
    med: Mediator,
    target: str,
    frame: Frame | None,
) -> dict[str, Any]:
    """Check the operator-provided start surface with production classifiers."""
    result: dict[str, Any] = {
        "target": target,
        "status": "NOT_REQUIRED",
        "observed": True,
        "classifier": None,
        "runbook": str((_target_contract(target).get("runbook_manual") or "")),
    }
    if not _frame_is_valid(frame):
        if target in {
            "solo_ingame_chain", "hitch_runtime", "hitch_lobby_chain",
            "choice_bond_skill", "treasure", "hero_evolve",
            "inventory_devour", "inventory_hero_card", "inventory_item",
            "black_merchant", "archive_challenge", "secret_realm",
            "heirloom", "time_cave", "lobby_hitch", "lobby_search",
            *TIER0_LOBBY_TARGETS, PUBLIC_BACKPACK_TARGET,
        }:
            result.update({
                "status": "BLOCKED",
                "observed": False,
                "reason": "start surface frame is missing or invalid; ZERO INPUT",
            })
        return result

    def _ok(classifier: str, observed: bool, reason_ok: str, reason_bad: str) -> dict[str, Any]:
        result.update({
            "status": "READY" if observed else "BLOCKED",
            "classifier": classifier,
            "observed": observed,
            "reason": reason_ok if observed else reason_bad,
        })
        return result

    if target == "s01_lobby_surface_identity":
        surface = _production_lobby_surface(med, frame)
        return _ok(
            "_production_lobby_surface",
            True,
            f"production surface capture available: {surface['classification']}",
            "production lobby surface capture unavailable; ZERO INPUT",
        )
    if target == "s02_lobby_platform_modal":
        surface = _production_lobby_surface(med, frame)
        return _ok(
            "_production_lobby_surface==PLATFORM_MODAL",
            surface.get("classification") == "PLATFORM_MODAL",
            "production Platform Modal Shell confirmed",
            "blocking Platform Modal Shell was not confirmed; ZERO INPUT",
        )
    if target in {"s03_lobby_room_ready", "s04_lobby_single_hwnd_room"}:
        surface = _production_lobby_surface(med, frame)
        room_ok = surface.get("classification") == "ROOM"
        if target == "s04_lobby_single_hwnd_room":
            room_ok = room_ok and bool(surface.get("hwnd")) and surface.get("confirmed_room_hwnd") == surface.get("hwnd")
        return _ok(
            "_production_lobby_surface==ROOM",
            room_ok,
            "production ROOM and HWND continuity confirmed",
            "production ROOM/ready start surface was not confirmed; ZERO INPUT",
        )
    if target == PUBLIC_BACKPACK_TARGET:
        operation = callable(getattr(med, "_maybe_public_backpack_deposit", None))
        surface = False
        try:
            # 局内 HUD 或战后挑战广场：广场上队友还在房里，公共背包仍然可用，
            # 「局末把手里剩下的交出去」是这条链最自然的收尾时机。判据跟
            # production 的 _public_bag_surface_ok 保持一致。
            surface = bool(med._public_bag_surface_ok(frame))
        except (AttributeError, TypeError):
            try:
                surface = bool(med._is_in_game_hud(frame))
            except (AttributeError, TypeError):
                pass
        return _ok(
            "production PUBLIC_BACKPACK_DEPOSIT + HUD or open bag page",
            operation and surface,
            "production public-backpack operation and a usable surface confirmed",
            "HUD 未确认且背包页未打开；局内开着的背包本身就是起始面",
        )

    if target == "solo_ingame_chain":
        try:
            startup = str(med._startup_state(frame))
        except (AttributeError, TypeError):
            startup = "UNKNOWN"
        observed = startup in {"PLATFORM_MAP", "CREATE_ROOM", "ROOM_WAITING", "STAGE_SELECT", "IN_GAME"}
        return _ok(
            "_startup_state",
            observed,
            f"production single-player start surface confirmed: {startup}",
            "expected production map/create-room/room/stage surface was not confirmed; ZERO INPUT",
        )
    if target == "hitch_runtime":
        try:
            observed = bool(med._is_in_game_hud(frame)) or bool(med._post_game_state(frame))
        except (AttributeError, TypeError):
            observed = False
        return _ok(
            "_is_in_game_hud/_post_game_state",
            observed,
            "production in-game HUD/post-game classifier confirmed",
            "expected in-game HUD or post-game surface was not confirmed; ZERO INPUT",
        )
    if target in {
        "hitch_lobby_chain", "lobby_hitch", "lobby_search",
        "s05_lobby_search_join_ready", "s06_lobby_recovery_chain",
    }:
        try:
            in_room_list = bool(med._lobby_room_list_evidence(frame))
        except (AttributeError, TypeError):
            in_room_list = False
        tab = None
        if not in_room_list:
            try:
                tab = med._find_hitch_room_list_tab(frame)
            except (AttributeError, TypeError):
                tab = None
        return _ok(
            "_lobby_room_list_evidence/_find_hitch_room_list_tab",
            in_room_list or tab is not None,
            "production lobby room-list classifier confirmed" if in_room_list else "production room-list tab locator confirmed; Mediator will acquire the list before searching",
            "expected lobby room list or a selectable room-list tab was not confirmed; ZERO INPUT",
        )
    if target in {"choice_bond_skill", "treasure", "hero_evolve", "inventory_devour", "inventory_hero_card", "inventory_item", "black_merchant"}:
        try:
            hud = bool(med._is_in_game_hud(frame))
        except (AttributeError, TypeError):
            hud = False
        panel = False
        try:
            panel = med._selection_anchor(frame) is not None
        except (AttributeError, TypeError):
            panel = False
        evolve = False
        if target == "hero_evolve":
            try:
                evolve = bool(med._has_evolve_button(frame))
            except (AttributeError, TypeError):
                evolve = False
            observed = hud and (evolve or panel)
            return _ok(
                "_has_evolve_button",
                observed,
                "evolve-capable HUD confirmed",
                "expected evolve-capable in-game HUD was not confirmed; ZERO INPUT",
            )
        observed = hud or panel
        return _ok(
            "_is_in_game_hud/_selection_anchor",
            observed,
            "in-game HUD or choice panel confirmed",
            "expected in-game HUD/panel was not confirmed; ZERO INPUT",
        )
    if target == "archive_challenge":
        try:
            observed = med._post_game_state(frame) in {"ARCHIVE_PANEL", "NPC_HUB", "POST_VICTORY"}
        except (AttributeError, TypeError):
            observed = False
        return _ok(
            "_post_game_state in {ARCHIVE_PANEL, NPC_HUB, POST_VICTORY}",
            observed,
            "archive challenge start surface confirmed",
            "expected challenge plaza or archive panel was not confirmed; ZERO INPUT",
        )
    if target == "secret_realm":
        try:
            observed = med._post_game_state(frame) in {"NPC_HUB", "POST_VICTORY"}
        except (AttributeError, TypeError):
            observed = False
        return _ok(
            "_post_game_state NPC_HUB",
            observed,
            "secret-realm start surface confirmed",
            "expected NPC hub/post-victory surface was not confirmed; ZERO INPUT",
        )
    if target in {"heirloom", "time_cave"}:
        try:
            observed = med._post_game_state(frame) in {"HEIRLOOM_DIALOG", "NPC_HUB", "ARCHIVE_PANEL"}
        except (AttributeError, TypeError):
            observed = False
        if not observed and target == "heirloom":
            try:
                observed = med._find_post_game_hub_entry(frame, "heirloom") is not None
            except (AttributeError, TypeError):
                observed = False
        return _ok(
            "_post_game_state boss list",
            observed,
            "boss/heirloom start surface confirmed",
            "expected boss/heirloom surface was not confirmed; ZERO INPUT",
        )
    return result


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


def _lobby_resource_preflight(med: Mediator, target: str | None) -> list[str]:
    if target not in {
        "lobby_hitch", "lobby_search", "hitch_lobby_chain",
        "s05_lobby_search_join_ready", "s06_lobby_recovery_chain",
    }:
        return []
    images = Path(getattr(med, "images", "") or "")
    # Search is the requested first action. Row-safety assets are checked at
    # join time so a bad lock template cannot suppress the initial search.
    # lobby_search_icon is what the production locator resolves the search
    # control with; the whole-box asset it replaced stopped matching as soon
    # as a prefix was typed, so requiring it here proved nothing.
    required = ("lobby_search_icon.png", "lobby_refresh.png", "lobby_room_list_tab.png") if target == "lobby_search" else (
        "lobby_search_icon.png", "lobby_refresh.png", "lobby_room_list_tab.png", "lobby_room_list_selected.png",
    )
    missing: list[str] = []
    for name in required:
        path = images / "lobby" / name
        if not path.is_file():
            missing.append(str(path))
            continue
        template = _load_template(path)
        if template is None or float(np.std(template)) < 8.0:
            missing.append(f"{path} (blank or low-contrast)")
    return missing


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


def _await_start_surface(
    med: Mediator,
    target: str,
    frame: Frame | None,
    window: dict[str, Any],
    settings: Settings,
    *,
    timeout_s: float = 0.0,
    poll_s: float = 1.0,
) -> tuple[dict[str, Any], Frame | None, dict[str, Any]]:
    """Re-check the start surface for a bounded window before blocking.

    The probe spends ~15s booting OCR before it ever looks at the screen
    (20260910 archive_challenge/heirloom bundles: created 13:17:40, finished
    13:17:57, one frame, BLOCKED).  A one-shot check that lands 15s after the
    operator clicks the menu is unusable for the panel-gated probes: 存档挑战 and
    传家宝 have to be open at that exact instant.  Polling for a bounded window
    lets the operator open the panel after starting the probe, and costs
    nothing for targets whose surface is already up.

    Zero input throughout: this only captures and classifies.
    """
    surface = _start_surface_preflight(med, target, frame)
    if surface.get("status") != "BLOCKED" or timeout_s <= 0.0:
        return surface, frame, window
    deadline = time.time() + timeout_s
    print(
        f"[preflight] {target} 起始界面尚未确认，最多等待 {timeout_s:.0f}s："
        f"{surface.get('reason') or 'start surface not confirmed'}",
        flush=True,
    )
    print("[preflight] 本等待期零输入。下面每秒回报一次 production 当前判定的页面。", flush=True)
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        time.sleep(min(poll_s, remaining))
        next_frame, next_window = _window_preflight(settings, target=target)
        if next_window.get("status") != "READY":
            print(
                f"[preflight] 剩余 {max(0.0, deadline - time.time()):.0f}s｜窗口未就绪："
                f"{next_window.get('reason') or next_window.get('status')}",
                flush=True,
            )
            continue
        candidate = _start_surface_preflight(med, target, next_frame)
        if candidate.get("status") != "BLOCKED":
            print(f"[preflight] {target} 起始界面已确认，开始跑。", flush=True)
            return candidate, next_frame, next_window
        # 打印分类器当前看到的页面：静默 90 秒和挂死无法区分，而"它现在
        # 认成什么"正是操作者判断自己站错地方所需要的唯一信息。
        try:
            seen = med._post_game_state(next_frame)
        except (AttributeError, TypeError):
            seen = None
        print(
            f"[preflight] 剩余 {max(0.0, deadline - time.time()):.0f}s｜"
            f"当前战后页面判定 = {seen or 'None（不在战后页面）'}",
            flush=True,
        )
        surface, frame, window = candidate, next_frame, next_window
    print(f"[preflight] {target} 等待超时，仍未确认起始界面；零输入退出。", flush=True)
    return surface, frame, window


def _live_input_preflight(
    *,
    args: argparse.Namespace,
    med: Mediator,
    settings: Settings,
    repo_root: Path,
    runtime_mediator_error: str | None,
) -> tuple[dict[str, Any], LiveLane | None, Frame | None]:
    """Gather every mandatory live-input fact before dispatching a handler."""
    scenario_identity = _scenario_identity(
        repo_root=repo_root,
        automation_exe=getattr(args, "automation_exe", None),
        require_exe=bool(getattr(args, "live_input", False) and not getattr(args, "allow_dev_source", False)),
        production_source_root=getattr(args, "production_source_root", None),
        production_source_sha=getattr(args, "production_source_sha", None),
    )
    source_root = _configured_production_source_root(getattr(args, "production_source_root", None))
    identity = _build_identity_check(
        repo_root=repo_root,
        automation_exe=getattr(args, "automation_exe", None),
        build_identity_path=getattr(args, "build_identity", None),
        source_sha=(scenario_identity.get("production_source_sha") or _commit_sha(repo_root)),
        source_clean=(scenario_identity.get("production_source_clean") if source_root is not None else None),
        allow_dev_source=bool(getattr(args, "allow_dev_source", False)),
    )
    elevation_blocked = bool(getattr(args, "live_input", False)) and not bool(
        getattr(settings, "dry_run", True)
    ) and not is_current_process_elevated()
    frame, window = _window_preflight(settings, target=getattr(args, "target", None))
    target = str(getattr(args, "target", "") or "")
    if elevation_blocked:
        ocr_health = {
            "healthy": False,
            "stage": "input_preflight",
            "reason": "Real input requires an elevated process; accept the UAC prompt from the desktop launcher",
        }
    elif target == "lobby_search":
        ocr_health = {
            "healthy": True,
            "skipped": True,
            "stage": "not_required",
            "reason": "visual-only lobby search does not require OCR",
        }
    else:
        ocr_health = _ocr_bootstrap_preflight(med) if runtime_mediator_error is None else {
            "healthy": False,
            "stage": "runtime_mediator",
            "reason": runtime_mediator_error,
        }
    reasons = list(identity.get("blocked_reasons") or [])
    gt_identity = _scenario_identity(
        repo_root=repo_root,
        automation_exe=getattr(args, "automation_exe", None),
        require_exe=bool(getattr(args, "live_input", False) and not getattr(args, "allow_dev_source", False)),
        production_source_root=getattr(args, "production_source_root", None),
        production_source_sha=getattr(args, "production_source_sha", None),
    )
    if not gt_identity.get("ready_for_gt"):
        reasons.extend(list(gt_identity.get("blocked_reasons") or []))
    if elevation_blocked:
        reasons.append(str(ocr_health["reason"]))
    resource_missing = _lobby_resource_preflight(med, getattr(args, "target", None))
    if resource_missing:
        reasons.append("lobby templates unavailable: " + ", ".join(resource_missing))
    if not bool(ocr_health.get("healthy")):
        reasons.append(f"ocr_bootstrap_unhealthy: {ocr_health.get('reason') or ocr_health.get('stage')}")
    start_surface, frame, window = _await_start_surface(
        med,
        target,
        frame,
        window,
        settings,
        timeout_s=float(getattr(args, "start_surface_wait", 0.0) or 0.0),
    )
    if window.get("status") != "READY":
        reasons.append(f"game window unavailable: {window.get('reason') or window.get('requested_title')}")
    if start_surface.get("status") == "BLOCKED":
        reasons.append(f"BLOCKED_PRECONDITION: {start_surface.get('reason') or 'start surface not confirmed'}")

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

    blocked_status = "BLOCKED_PRECHECK"
    if any(str(reason).startswith("BLOCKED_PRECONDITION") for reason in reasons) and identity.get("status") == "READY" and gt_identity.get("ready_for_gt"):
        blocked_status = "BLOCKED_PRECONDITION"
    return ({
        "status": "READY" if not reasons else blocked_status,
        "tested_source_sha": scenario_identity.get("production_source_sha") or _commit_sha(repo_root),
        "production_source_root": scenario_identity.get("production_source_root"),
        "production_source_sha": scenario_identity.get("production_source_sha"),
        "candidate_source_injection": scenario_identity.get("candidate_source_injection", "INACTIVE"),
        "actual_exe": identity,
        "harness_identity": gt_identity,
        "ready_for_gt": bool(gt_identity.get("ready_for_gt")),
        "settings_snapshot": _settings_snapshot(settings),
        "ocr_bootstrap_health": ocr_health,
        "window": window,
        "start_surface": start_surface,
        "resource_preflight": {"missing": resource_missing},
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
    for method_name in ("act_click", "act_right_click", "act_key", "act_scroll", "act_type_text", "act_double_click", "act_search_box"):
        if not hasattr(med, method_name):
            continue
        original = getattr(med, method_name)

        def guarded(
            *args: Any,
            _original: Callable[..., Any] = original,
            _method_name: str = method_name,
            **kwargs: Any,
        ) -> Any:
            reason = kwargs.get("reason")
            if reason is None:
                # act_scroll(x, y, clicks, reason) — index 1 is the Y pixel.
                # Take the last non-empty string so the probe guard sees
                # BossConfigured-scroll, not "498".
                for arg in reversed(args):
                    if isinstance(arg, str) and arg:
                        reason = arg
                        break
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
        if target == "s02_lobby_platform_modal" and reason not in TIER0_MODAL_DISMISS_REASONS:
            return f"{target} permits neutral modal dismiss only"
        if target in {"s05_lobby_search_join_ready", "s06_lobby_recovery_chain"} and reason not in TIER0_LOBBY_SAFE_REASONS:
            return f"{target} action {(reason or method)!r} is outside the production Lobby safety allowlist"
        if target == PUBLIC_BACKPACK_TARGET and not (
            reason in (allowed or set())
            or reason.startswith("PublicBackpack")
            or reason.startswith("PUBLIC_BACKPACK")
        ):
            return f"{target} action {(reason or method)!r} is outside the production deposit contract"
        if execution_mode != "target_handler" or allowed is None:
            return None
        if reason not in allowed:
            return (
                f"{target} probe action {(reason or method)!r} is outside the allowed production "
                "action/reason set"
            )
        return None

    return guard


def _load_operator_settings(path: Path | None) -> Settings:
    if path is not None:
        return Settings.load(path)
    try:
        return Settings.load_official()
    except (FileNotFoundError, OSError, TypeError, ValueError):
        return Settings()


def _prepare_settings(path: Path | None, target: str, live_input: bool) -> Settings:
    settings = _load_operator_settings(path)
    if not live_input:
        settings.dry_run = True
    # A Ground Truth-only target remains zero-input even when an operator
    # accidentally supplied --live-input. Never turn a production flag on in
    # Boss/时间之穴测试只在内存中使用不可用哨兵，强制验证最后可识别 Boss fallback。
    # 不修改 Settings.json。
    if target in {"boss_challenge", "time_cave"}:
        settings.cjb_boss = "55吞咽者布鲁"
        settings.sgzx_boss = "55吞咽者布鲁"
        settings.auto_secret_realm = False
    if target in {
        "lobby_hitch", "lobby_search", "hitch_runtime", "hitch_lobby_chain",
        *TIER0_LOBBY_TARGETS, PUBLIC_BACKPACK_TARGET,
    }:
        settings.mode_id = "lobby_hitch"
        # The desktop runner projects this mode-specific value before it
        # constructs Mediator. The harness constructs it directly, so make
        # the same explicit projection here; otherwise a stale generic
        # cycle_num can silently turn the requested two-round hitch run into
        # a three-round one.
        settings.cycle_num = int(getattr(settings, "hitch_cycle_num", settings.cycle_num) or 0)
        settings.auto_create_room = False
        settings.skip_password_rooms = True
        settings.never_quick_join = True
    if target in {"lobby_hitch", "lobby_search", "hitch_runtime", "hitch_lobby_chain"}:
        # The desktop runner projects this mode-specific value before it
        # constructs Mediator. The harness constructs it directly, so make
        # the same explicit projection here; otherwise a stale generic
        # cycle_num can silently turn the requested two-round hitch run into
        # a three-round one.
        settings.cycle_num = int(getattr(settings, "hitch_cycle_num", settings.cycle_num) or 0)
    if target == "hitch_lobby_chain":
        # Full live chain: black merchant only buys a verified swallow pill;
        # the production treasure policy independently prioritizes green talismans.
        settings.merchant_enabled = True
        settings.auto_devour_dan = True
        settings.auto_treasure = True
        settings.auto_secret_realm = False
    if target == "hitch_runtime":
        # 蹭车续跑在传家宝挑战确认后按既有退出链收敛；秘境另行显式配置。
        settings.auto_secret_realm = False
    if target == "solo_ingame_chain":
        settings.mode_id = "normal_farm"
    if target == "treasure":
        settings.auto_treasure = True
    if target == "choice_bond_skill":
        settings.auto_bond = True
    return settings


def _bootstrap_target_probe(
    med: Mediator, target: str, frame: Frame | None = None
) -> dict[str, Any]:
    """Seed only the existing production state required to enter a target mid-flow.

    The values are not a replacement FSM and never select/click anything.  They
    let an operator place the game at an already-open post-game target while
    retaining the exact production handler for all subsequent decisions.
    """
    now = time.time()
    if target in {"black_merchant", "inventory_item"}:
        # Target probes start after the operator has fulfilled the existing
        # evolution prerequisite; production still decides whether an item matches.
        med._evolve_ok_this_cycle = True
    if target == "black_merchant":
        # A black-merchant encounter necessarily occurs well after entering
        # MAIN_LINE.  A fresh probe process has no historic start timestamp,
        # so record that known start fact for the existing artifact warm-up.
        med._main_line_started_at = now - 30.0
        return {
            "main_line_started_at": "probe_start_minus_30s",
            "evolve_ok_this_cycle": True,
            "reason": "target starts in an established in-game HUD after one evolution; existing inventory/artifact handlers retain their recognition and cooldown gates",
        }
    if target == "inventory_item":
        return {
            "evolve_ok_this_cycle": True,
            "reason": "operator start condition confirms one completed evolution; existing inventory handler retains all recognition and postcondition gates",
        }
    if target in {"time_cave", "heirloom"}:
        # The probe can begin at the NPC plaza or at the already-open list.
        # Only the existing production classifier may distinguish the two.
        post_game = med._post_game_state(frame) if _frame_is_valid(frame) else None
        med._post_game_pending = True
        med._post_game_route = (
            "archive"
            if target == "time_cave"
            else ("heirloom_active" if post_game == "HEIRLOOM_DIALOG" else "heirloom")
        )
        return {
            "post_game_pending": True,
            "post_game_route": med._post_game_route,
            "classified_start_surface": post_game,
            "reason": "production classifier routes a verified challenge plaza or already-open challenge panel",
        }
    if target in {"lobby_hitch", "lobby_search", "s03_lobby_room_ready", "s05_lobby_search_join_ready"}:
        med.set_phase(Phase.LOBBY_ROOM, "lobby hitch target probe")
        med._hitch_re_search = False
        if target in {"lobby_search", "s05_lobby_search_join_ready"}:
            med._hitch_sm.continuous = True
        return {
            "phase": "LOBBY_ROOM",
            "mode_id": "lobby_hitch",
            "continuous_until_ready": target in {"lobby_search", "s05_lobby_search_join_ready"},
            "reason": (
                "target probe starts from the KK room list and repeats safe search cycles until verified guest Ready"
                if target in {"lobby_search", "s05_lobby_search_join_ready"}
                else "target probe starts from game lobby room list to search and join room"
            ),
        }
    if target in {"black_merchant", "inventory_item", "inventory_devour", "inventory_hero_card"}:
        med._evolve_ok_this_cycle = True
        if target == "inventory_devour":
            return {
                "evolve_ok_this_cycle": True,
                "reason": "operator start condition confirms one completed evolution; existing devour-pill handler retains all gates",
            }
        if target == "inventory_hero_card":
            return {
                "evolve_ok_this_cycle": True,
                "reason": "operator start condition confirms one completed evolution; existing hero-card handler retains all gates",
            }
    if target == "hero_evolve":
        med._l1_cycle_step = "evolve"
        return {"l1_cycle_step": "evolve", "reason": "probe starts at production evolve cycle step"}
    if target == "choice_bond_skill":
        med._l1_cycle_step = "bond"
        med._choice_target = "bond"
        return {"l1_cycle_step": "bond", "reason": "probe starts at production bond/skill panel entry"}
    if target == "treasure":
        med._l1_cycle_step = "treasure"
        med._choice_target = "treasure"
        return {"l1_cycle_step": "treasure", "reason": "probe starts at production treasure panel entry"}
    if target == "archive_challenge":
        med._post_game_pending = True
        med._post_game_route = "archive"
        return {
            "post_game_pending": True,
            "post_game_route": "archive",
            "classified_start_surface": (
                med._post_game_state(frame) if _frame_is_valid(frame) else None
            ),
            "reason": "production main-line handler opens the archive NPC from the plaza or continues an open archive panel",
        }
    if target != "secret_realm":
        return {}
    med._post_game_pending = True
    med._post_game_route = "secret"
    med._secret_realm_request_pending = False
    med._secret_realm_request_since = None
    med._secret_realm_request_attempts = 0
    med._secret_realm_confirm_attempts = 0
    med._secret_realm_next_observe_at = 0.0
    med._secret_realm_confirm_next_observe_at = 0.0
    return {
        "post_game_pending": True,
        "post_game_route": "secret",
        "secret_realm_request_pending": False,
        "reason": "target probe starts from NPC_HUB plaza to initiate great rift entry",
    }


def _bootstrap_direct_boss_postgame_start(
    med: Mediator, target: str, frame: Frame
) -> dict[str, Any]:
    """Accept an already-open post-game challenge page as a capture start state.

    This is capture setup only: the page is classified by the existing
    Mediator post-game classifier, then the normal ``Mediator.tick()`` path is
    allowed to run. No Boss recognition, scrolling, or click policy lives here.
    """
    if target not in {"boss_challenge", "time_cave", "heirloom", "hitch_runtime"} or getattr(med, "_post_game_pending", False):
        return {}
    if not _frame_is_valid(frame):
        return {}
    post_game = med._post_game_state(frame)
    if post_game not in {"ARCHIVE_PANEL", "NPC_HUB", "HEIRLOOM_DIALOG"}:
        return {}
    med._post_game_pending = True
    med._post_game_route = "heirloom_active" if post_game == "HEIRLOOM_DIALOG" else "archive"
    med._boss_challenge_attempts = 0
    med._boss_challenge_scroll_attempts = 0
    med._boss_challenge_next_at = 0.0
    return {
        "post_game_pending": True,
        "post_game_route": med._post_game_route,
        "reason": (
            "operator started with an already classified post-game page "
            f"({post_game}); existing Mediator.tick() handles the archive-first route"
        ),
    }


def _require_live_confirmation(live_input: bool, confirmed: bool) -> None:
    if live_input and not confirmed:
        raise ValueError("启用 --live-input 必须同时传 --confirm-live-input；默认 probe/capture 为 dry-run")


def _is_emergency_reason(reason: str | None) -> bool:
    text = str(reason or "").lower()
    return "emergency" in text or "shift+f12" in text or "f12 emergency" in text


def _initial_phase_for_target(target: str) -> Phase:
    if target == "solo_ingame_chain":
        return Phase.BOOT
    if target in {"lobby_hitch", "lobby_search", "hitch_lobby_chain", "s01_lobby_surface_identity", "s02_lobby_platform_modal", "s05_lobby_search_join_ready", "s06_lobby_recovery_chain"}:
        return Phase.LOBBY_ROOM
    if target in {"s03_lobby_room_ready", "s04_lobby_single_hwnd_room"}:
        return Phase.ROOM_WAITING
    if target == "hitch_runtime":
        return Phase.MAIN_LINE
    return Phase.MAIN_LINE


def _arm_direct_archaeology_after_stage_select(med: Mediator, enabled: bool) -> bool:
    """Arm the harness-only archaeology handoff only after production reaches Stage Select."""
    if not enabled or med.phase is not Phase.STAGE_SELECT:
        return False
    if bool(getattr(med, "_archaeology_handoff_pending", False)):
        return False
    med._archaeology_handoff_pending = True
    return True


def _arm_current_room_archaeology_handoff(med: Mediator) -> None:
    """Arm the short live handoff after the operator places self on floor one."""
    med.settings.mode_id = "normal_farm"
    med.settings.auto_create_room = True
    med.settings.auto_archaeology = True
    med._hitch_goal_archaeology_handoff = True
    med._archaeology_handoff_pending = True
    med._room_leave_pending = True
    med._room_leave_next_at = 0.0
    med._room_action_deadline = time.time() + min(med.settings.query_timeout, 30)
    med.set_phase(Phase.ROOM_WAITING, "current room handoff; leave for archaeology")


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
    until_success = bool(getattr(args, "until_success", False))
    until_success_ok = (
        args.live_input
        and (
            (probe and target == "lobby_search")
            or (not probe and target == "hitch_lobby_chain")
        )
    )
    if until_success and not until_success_ok:
        raise ValueError("--until-success 仅允许 lobby_search probe 或 hitch_lobby_chain capture 的真实输入")
    contract = _target_contract(target)
    _require_live_confirmation(args.live_input, args.confirm_live_input)
    repo_root = Path(args.repo_root).resolve()
    settings = _prepare_settings(Path(args.settings) if args.settings else None, target, args.live_input)
    direct_archaeology = bool(getattr(args, "direct_archaeology", False))
    if direct_archaeology:
        if target != "solo_ingame_chain":
            raise ValueError("--direct-archaeology 仅支持 solo_ingame_chain")
        # This is a harness-only request.  It is armed only after production
        # L0 has reached Stage Select, so room creation and RoomStart keep
        # their normal production behavior.  Production archaeology handoff
        # owns the actual click and fresh-anchor confirmation.
        settings.mode_id = "normal_farm"
        settings.auto_create_room = True
        settings.auto_archaeology = True
    current_room_archaeology = bool(getattr(args, "current_room_archaeology", False))
    if current_room_archaeology:
        if target != "hitch_lobby_chain":
            raise ValueError("--current-room-archaeology 仅支持 hitch_lobby_chain")
        if not args.live_input:
            raise ValueError("--current-room-archaeology 必须使用 --live-input")
        settings.mode_id = "normal_farm"
        settings.auto_create_room = True
        settings.auto_archaeology = True
    output_root = Path(args.out).resolve()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    bundle_dir = output_root / f"{target}_{stamp}"
    stop_signal = StopSignal()
    execution_mode = (
        "ground_truth_only"
        if _ground_truth_only(target)
        else ("target_handler" if probe else "mediator_tick")
    )
    runtime_root = _configured_production_source_root(getattr(args, "production_source_root", None)) or repo_root
    runtime_mediator_error: str | None = None
    elevation_blocked = bool(args.live_input) and not bool(getattr(settings, "dry_run", True)) and not is_current_process_elevated()
    if args.live_input and not elevation_blocked:
        med, runtime_mediator_error = _new_live_mediator(
            settings,
            runtime_root,
            stop_signal,
            bundle_dir / "incidents",
        )
    else:
        med = Mediator(settings, runtime_root, stop_signal=stop_signal, incident_dir=bundle_dir / "incidents")
        if elevation_blocked:
            runtime_mediator_error = "Real input requires an elevated process; accept the UAC prompt from the desktop launcher"
    initial_phase = Phase.ROOM_WAITING if current_room_archaeology else _initial_phase_for_target(target)
    med.set_phase(initial_phase, f"{target} {'target probe' if probe else 'live capture'}")
    if target == "hitch_lobby_chain":
        med._hitch_re_search = False
        try:
            med._hitch_sm.continuous = True
        except AttributeError:
            pass
    if runtime_root != repo_root:
        print(f"[source-injection] production runtime={runtime_root} sha={_commit_sha(runtime_root)}")
    # Post-game probes require the preflight frame to choose between a plaza
    # and an already-open dialog. Do not seed a generic route before that
    # authoritative production classification is available.
    post_game_probe_targets = {"archive_challenge", "time_cave", "heirloom"}
    probe_bootstrap = (
        _bootstrap_target_probe(med, target)
        if probe and execution_mode == "target_handler" and target not in post_game_probe_targets
        else {}
    )
    recorder = BundleRecorder(
        bundle_dir,
        repo_root=repo_root,
        target=target,
        settings=settings,
        initial_phase=med.phase.name,
        execution_mode=execution_mode,
        production_source_root=runtime_root if runtime_root != repo_root else None,
        production_source_sha=getattr(args, "production_source_sha", None),
    )
    if current_room_archaeology:
        recorder.solo_observer = None
        recorder.solo_observer_key = None
        recorder.manifest["current_room_archaeology"] = {
            "operator_precondition": "当前 KK 房间内已把自己放到一楼",
            "handoff": "leave_old_room -> fresh_lobby -> create_room -> archaeology",
        }
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
        recorder.manifest["window"] = preflight.get("window") or recorder.manifest.get("window")
        recorder.manifest["ready_for_gt"] = bool(preflight.get("ready_for_gt", recorder.manifest.get("ready_for_gt")))
        if recorder.solo_observer is not None:
            recorder.solo_observer.precheck(preflight.get("status") == "READY", preflight)
            recorder.manifest[str(recorder.solo_observer_key)] = recorder.solo_observer.payload()
        if current_room_archaeology:
            if not _frame_is_valid(preflight_frame) or not med._is_confirmed_room_frame(preflight_frame):
                raise ValueError("当前房间考古短链要求预检帧确认真实 ROOM 页面；请先把自己放到一楼")
            _arm_current_room_archaeology_handoff(med)
    else:
        dry_identity = _scenario_identity(
            repo_root=repo_root,
            automation_exe=getattr(args, "automation_exe", None),
            production_source_root=getattr(args, "production_source_root", None),
            production_source_sha=getattr(args, "production_source_sha", None),
        )
        recorder.record_preflight({
            "status": "NOT_REQUESTED",
            "tested_source_sha": _commit_sha(repo_root),
            "harness_identity": dry_identity,
            "ready_for_gt": bool(dry_identity.get("ready_for_gt")),
            "settings_snapshot": _settings_snapshot(settings),
            "reason": "dry-run or Ground Truth capture without --live-input",
        })
        recorder.manifest["ready_for_gt"] = bool(dry_identity.get("ready_for_gt"))

    if (
        probe
        and execution_mode == "target_handler"
        and target in post_game_probe_targets
        and _frame_is_valid(preflight_frame)
    ):
        probe_bootstrap = _bootstrap_target_probe(med, target, preflight_frame)
        recorder.manifest["probe_bootstrap"] = probe_bootstrap
        recorder._write_manifest()

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
    deadline = None if until_success else time.monotonic() + duration_s
    ticks = 0
    original_see = med.see
    current_frame: dict[str, Frame | None] = {"value": None}
    live_preflight_blocked = bool(
        args.live_input
        and str(recorder.manifest.get("live_preflight", {}).get("status") or "").startswith("BLOCKED")
    )

    def capture_for_tick(reason: str = "") -> Frame:
        frame = original_see(reason)
        current_frame["value"] = _copy_frame(frame)
        direct_start = _bootstrap_direct_boss_postgame_start(med, target, frame)
        if direct_start:
            recorder.manifest["capture_bootstrap"] = direct_start
            recorder._write_manifest()
        return frame

    def process_bookmarks() -> None:
        nonlocal awaiting_manual_resume
        for status, note in bookmark_reader.poll():
            bookmark_frame = current_frame["value"] or _capture_after(med)
            recorder.bookmark(status, med, bookmark_frame, note=note)
            print(f"[bookmark] {status} {note}".rstrip())
            if status == "MANUAL_INTERVENTION" and recorder.solo_observer is not None:
                recorder.solo_observer.manual_intervention()
                recorder.manifest[str(recorder.solo_observer_key)] = recorder.solo_observer.payload()
            if (
                awaiting_manual_resume
                and status == "MANUAL_INTERVENTION"
                and not _is_emergency_reason(stop_signal.reason)
            ):
                _resume_after_manual_intervention(med)
                awaiting_manual_resume = False
                print("[capture] manual intervention recorded; observation loop resumed")

    print(_format_identity_text(_scenario_identity(
        repo_root=repo_root,
        automation_exe=getattr(args, "automation_exe", None),
        production_source_root=getattr(args, "production_source_root", None),
        production_source_sha=getattr(args, "production_source_sha", None),
    )))
    print(f"[runbook] 请将真实游戏停在以下页面/状态：{contract['runbook_manual']}")
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
            blocked_status = str(recorder.manifest["live_preflight"].get("status") or "BLOCKED_PRECHECK")
            if blocked_status not in {"BLOCKED", "BLOCKED_PRECHECK", "BLOCKED_PRECONDITION"}:
                blocked_status = "BLOCKED_PRECHECK"
            recorder.record_blocked(
                med,
                current_frame["value"],
                status=blocked_status,
                note=f"live input refused before target handler: {note}",
            )
            print(
                f"[preflight] {blocked_status}: {note or 'live precondition not met'}; "
                "no business handler or game input was attempted"
            )
            return bundle_dir

        med.emergency_listener = EmergencyStopListener(stop_signal)
        med.emergency_listener.start()

        if args.live_input:
            import threading

            def _run_hud():
                try:
                    import tkinter as tk
                    root = tk.Tk()
                    root.title("ShuaBao Test HUD")
                    root.overrideredirect(True)
                    root.attributes("-topmost", True)
                    root.attributes("-alpha", 0.95)
                    root.geometry("400x42+600+10")
                    root.configure(bg="#141821")
                    lbl = tk.Label(root, text=f"【刷刷宝实机测试】{target}", fg="#00F0FF", bg="#141821", font=("Microsoft YaHei", 9, "bold"))
                    lbl.pack(side=tk.LEFT, padx=12)
                    def _on_stop():
                        stop_signal.trigger("User clicked HUD stop")
                        try:
                            root.destroy()
                        except Exception:
                            pass
                    btn = tk.Button(root, text="■ 停止测试 (点此退出)", fg="white", bg="#E63946", activebackground="#C1121F", activeforeground="white", font=("Microsoft YaHei", 9, "bold"), relief=tk.FLAT, command=_on_stop, cursor="hand2")
                    btn.pack(side=tk.RIGHT, padx=10, pady=5)
                    while not stop_signal.is_set():
                        try:
                            root.update()
                        except Exception:
                            break
                        time.sleep(0.05)
                    try:
                        root.destroy()
                    except Exception:
                        pass
                except Exception as exc:
                    print(f"[HUD] 悬浮窗启动异常 (不影响测试): {exc}")

            threading.Thread(target=_run_hud, daemon=True).start()
        while (
            (until_success or ticks < args.max_ticks)
            and (deadline is None or time.monotonic() <= deadline)
        ):
            process_bookmarks()
            if awaiting_manual_resume:
                if _is_emergency_reason(stop_signal.reason):
                    break
                time.sleep(min(0.2, max(0.01, float(args.interval))))
                continue
            recorder.begin_tick()
            if _arm_direct_archaeology_after_stage_select(med, direct_archaeology):
                print("[scenario] 生产 L0 已确认选关页，启用直达考古 handoff")
                recorder.manifest["direct_archaeology_arm"] = {
                    "phase": med.phase.name,
                    "tick": ticks,
                }
                recorder._write_manifest()
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
                # Existing production handlers only. Black merchant also consumes
                # bought devour pills through the existing inventory entry.
                med._tick_no += 1
                med._trace_actions = []
                med._trace_scenes = []
                med._trace_controls = []
                med._trace_ocr_suggestion = None
                frame = med.see("target live probe")
                if not _frame_is_valid(frame):
                    loop_action = LoopAction.Continue
                else:
                    if target == "black_merchant":
                        result = _invoke_black_merchant_probe_handlers(
                            med,
                            frame,
                            input_sent=lambda: bool(recorder.inputs_this_tick),
                        )
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
            if current_room_archaeology and getattr(med, "_archaeology_handoff_confirmed", False):
                if not recorder.manifest["target_result"].get("authoritative"):
                    last_event = (recorder.manifest.get("events") or [{}])[-1]
                    recorder._record_authoritative_target_result(
                        event_id=last_event.get("event_id"),
                        postcondition={"kind": "current_room_archaeology_handoff_complete"},
                        target_stage="ARCHAEOLOGY_HANDOFF_CONFIRMED",
                    )
            if not _frame_is_valid(current_frame["value"]):
                # 坚韧容错原则：无论切屏、最小化还是转场黑屏，不直接退出进程自杀！记录并等待恢复
                print(f"[live] 当前帧无效或正在过渡/最小化中，等待画面恢复 (tick {ticks})")
                time.sleep(1.0)
                continue
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
            if (
                target == "lobby_search"
                and recorder.manifest["target_result"].get("authoritative")
            ):
                ticks += 1
                break
            ticks += 1
            if stop_signal.is_set() and not awaiting_manual_resume:
                break
            if args.interval > 0:
                time.sleep(float(args.interval))
        if (
            probe
            and args.live_input
            and execution_mode == "target_handler"
            and deadline is not None
            and time.monotonic() >= deadline
            and ticks >= 1
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
        if (
            probe
            and target == "lobby_search"
            and ticks >= 1
            and not recorder.manifest["target_result"].get("authoritative")
            and not recorder.manifest["automatic_failures"]
            and not _is_emergency_reason(stop_signal.reason)
        ):
            last_event = (recorder.manifest.get("events") or [{}])[-1]
            post_state = (last_event.get("postcondition") or {}).get("state") or "not_observed"
            recorder.bookmark(
                "FAIL",
                med,
                current_frame["value"],
            note=f"lobby search/room-select visual postcondition failed: {post_state}",
            )
    finally:
        if med.emergency_listener:
            med.emergency_listener.stop()
            med.emergency_listener = None
        recorder.stop_trace(med)
        recorder.manifest["capture_ticks"] = ticks
        recorder.manifest["capture_options"] = {
            "duration_s": None if until_success else duration_s,
            "max_probe_time_s": float(contract["max_probe_time_s"]),
            "max_ticks": None if until_success else int(args.max_ticks),
            "until_success": until_success,
            "terminal_condition": "verified_guest_ready" if until_success else "bounded_probe",
            "interval_s": float(args.interval),
            "requested_live_input": bool(args.live_input),
            "effective_live_input": bool(args.live_input and not _ground_truth_only(target)),
            "execution_mode": execution_mode,
            "production_readiness": _production_fact(target)["production_readiness"],
            "bookmark_file": str(bookmark_file),
            "continue_after_failure": bool(getattr(args, "continue_after_failure", False)),
            "direct_archaeology": direct_archaeology,
            "current_room_archaeology": current_room_archaeology,
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
    production_source_root: Path | None = None,
    production_source_sha: str | None = None,
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
    identity = _scenario_identity(
        repo_root=repo_root,
        production_source_root=production_source_root,
        production_source_sha=production_source_sha,
    )
    return {
        "readiness_schema_version": 2,
        "repo_root": str(repo_root),
        "tested_commit_sha": sha,
        "primary_live_scenario": PRIMARY_LIVE_SCENARIO,
        "primary_live_target": PRIMARY_LIVE_TARGET,
        "production_source_sha": identity.get("production_source_sha"),
        "production_source_root": identity.get("production_source_root"),
        "harness_identity": identity,
        "ready_for_gt": bool(identity.get("ready_for_gt")),
        "replay_self_check": {"status": "PASS" if replay_ok else "FAIL", "detail": replay_detail},
        "live_input_preflight": {
            "status": "REQUIRED",
            "required_facts": (
                "tested_source_sha", "actual_exe_build_hash", "settings_snapshot",
                "ocr_bootstrap_health", "hwnd_title_size", "single_instance",
                "harness_base", "production_code_diff", "runtime_worktree",
            ),
        },
        "targets": targets,
    }


def _print_readiness(report: dict[str, Any], *, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    print(f"[readiness] commit={report.get('tested_commit_sha')}")
    identity = report.get("harness_identity") or {}
    if identity:
        print(_format_identity_text(identity))
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
        if name == "boss_challenge":
            print(
                "2. 执行：python tools/live_scenario_capture.py capture "
                f"--target {name} --out C:/tmp/shuabao-captures "
                "--duration 600 --max-ticks 5000 "
                "--automation-exe C:/path/to/ShuaBao.exe --live-input "
                "--confirm-live-input --continue-after-failure --generate"
            )
        elif fact["production_readiness"] == "BLOCKED":
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
    parser.add_argument(
        "--production-source-root",
        type=Path,
        default=None,
        help="Tier-0 candidate worktree whose src/shuabao is imported at runtime",
    )
    parser.add_argument(
        "--production-source-sha",
        default=None,
        help="expected injected production SHA (required for GT runs when candidate source is injected)",
    )
    parser.add_argument("--settings", type=Path, default=None)
    parser.add_argument(
        "--direct-archaeology",
        action="store_true",
        help="仅单人链路：建房并到达选关页后，直接走 production 考古 handoff",
    )
    parser.add_argument(
        "--current-room-archaeology",
        action="store_true",
        help="当前房间已把自己放到一楼：真实离旧房→自建房→选关→考古",
    )
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument(
        "--start-surface-wait",
        type=float,
        default=60.0,
        help=(
            "在宣告 BLOCKED 之前，等待起始界面出现的秒数（零输入轮询）。"
            "存档挑战/传家宝这类必须先开面板的 probe 靠它才有可操作时间；0 = 一次性判定。"
        ),
    )
    parser.add_argument("--interval", type=float, default=0.3)
    parser.add_argument("--max-ticks", type=int, default=1000)
    parser.add_argument(
        "--until-success",
        action="store_true",
        help="lobby_search probe 或 hitch_lobby_chain capture：忽略 duration/max-ticks，直到生产后置确认",
    )
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
    parser.add_argument(
        "--allow-dev-source",
        action="store_true",
        default=False,
        help="允许在本地源码/开发测试环境直接运行实机探针",
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
    readiness_parser = sub.add_parser("readiness", help="启动主链实机前检查 Harness/candidate contract、capture、bookmark 与 replay 能力")
    readiness_parser.add_argument("--repo-root", type=Path, default=ROOT)
    readiness_parser.add_argument("--production-source-root", type=Path, default=None)
    readiness_parser.add_argument("--production-source-sha", default=None)
    readiness_parser.add_argument("--settings", type=Path, default=None, help="可选：同时检查本次 settings 的 target 前置")
    readiness_parser.add_argument("--quick", action="store_true", help="跳过临时 bundle 的离线 replay self-check")
    readiness_parser.add_argument("--json", action="store_true")
    identity_parser = sub.add_parser("identity", help="打印 Harness/production/runtime 身份与 READY FOR GT")
    identity_parser.add_argument("--repo-root", type=Path, default=ROOT)
    identity_parser.add_argument("--automation-exe", type=Path, default=None)
    identity_parser.add_argument("--production-source-root", type=Path, default=None)
    identity_parser.add_argument("--production-source-sha", default=None)
    identity_parser.add_argument("--json", action="store_true")
    contracts_parser = sub.add_parser("contracts", help="显示主链与窄诊断 Target Test Contract")
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
    return str((manifest.get("live_preflight") or {}).get("status") or "").startswith("BLOCKED")


def _bundle_exit_code(bundle_dir: Path) -> int:
    """Return and persist the process result for launcher diagnostics."""
    path = Path(bundle_dir) / "manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return 2
    if str((manifest.get("live_preflight") or {}).get("status") or "").startswith("BLOCKED"):
        code = 3
    elif manifest.get("target") == "lobby_search":
        events = manifest.get("events") or []
        search_observed = any(
            str((event.get("action") or {}).get("reason")) == "HitchSearchBox"
            and (event.get("postcondition") or {}).get("observed") is True
            for event in events
        )
        result = manifest.get("target_result") or {}
        terminal_kind = str((result.get("evidence") or {}).get("kind") or "")
        terminal_observed = bool(result.get("authoritative")) and terminal_kind == "lobby_hitch_ready"
        code = 0 if search_observed and terminal_observed else 4
    else:
        code = 0
    manifest["process_exit_code"] = code
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return code


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "capture":
            bundle = _run_live_capture(args)
            return _bundle_exit_code(bundle)
        if args.command == "probe":
            bundle = _run_live_capture(args, probe=True)
            return _bundle_exit_code(bundle)
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
        if args.command == "identity":
            report = _scenario_identity(
                repo_root=args.repo_root,
                automation_exe=args.automation_exe,
                production_source_root=args.production_source_root,
                production_source_sha=args.production_source_sha,
            )
            if args.json:
                print(json.dumps(report, ensure_ascii=False, indent=2))
            else:
                print(_format_identity_text(report))
            return 0 if report["ready_for_gt"] else 1
        if args.command == "readiness":
            settings = _load_operator_settings(args.settings)
            report = readiness_report(
                repo_root=args.repo_root,
                settings=settings,
                run_replay_self_check=not args.quick,
                production_source_root=args.production_source_root,
                production_source_sha=args.production_source_sha,
            )
            _print_readiness(report, as_json=args.json)
            harness_ok = all(item["harness_readiness"] == "READY" for item in report["targets"])
            return 0 if harness_ok and report.get("ready_for_gt", True) else 1
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
