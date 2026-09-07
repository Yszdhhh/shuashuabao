# -*- coding: utf-8 -*-
"""b15da05 修复的真实帧回归测试。

四个真实捕获帧（tests/fixtures/）：
- real_leaderboard_frame.png  KK 大厅非房间列表弹窗页（等级不满足弹窗）
- real_kicked_modal_frame.jpg KK 房间已满弹窗页（含蓝色主按钮，用于购买陷阱拦截）
- real_archive_panel_frame.jpg 真实存档挑战面板（reborn_wow endgame 实拍）
- real_midgame_hitch_hud_frame.png 真实局内蹭车 HUD（压力转移按钮可见、自动任务未勾）

覆盖任务书 1-6 号用例。
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
import pytest

from shuabao.mediator import Mediator, Phase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame

ROOT = Path(__file__).resolve().parents[1]

FIXTURES = {
    "leaderboard": ROOT / "tests" / "fixtures" / "real_leaderboard_frame.png",
    "kicked": ROOT / "tests" / "fixtures" / "real_kicked_modal_frame.jpg",
    "archive": ROOT / "tests" / "fixtures" / "real_archive_panel_frame.jpg",
    "midgame": ROOT / "tests" / "fixtures" / "real_midgame_hitch_hud_frame.png",
}


def _load(name: str) -> np.ndarray:
    path = FIXTURES[name]
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None, f"fixture missing: {path}"
    return image


def _kk_frame(name: str, hwnd: int = 10002) -> Frame:
    return Frame(_load(name), window_title="KK官方对战平台", hwnd=hwnd, role="l0")


def _game_frame(name: str, hwnd: int = 10001) -> Frame:
    return Frame(_load(name), window_title="英雄三国KK", hwnd=hwnd, role="l1")


def _hitch_mediator() -> Mediator:
    return Mediator(Settings(dry_run=True, ocr_mode="off", mode_id="lobby_hitch"), ROOT)


def test_real_leaderboard_not_room_list_authority() -> None:
    """P1-A：真实非房间列表帧上 _lobby_room_list_evidence 必须返回 False，
    且状态机进入 _tick_hitch_room_list_tab 尝试切换 Tab。"""
    med = _hitch_mediator()
    frame = _kk_frame("leaderboard")
    assert med._lobby_room_list_evidence(frame) is False

    med.set_phase(Phase.LOBBY_ROOM)
    calls: list[tuple[str, object]] = []

    def fake_tab_click(frame_arg, now):
        calls.append(("tab", frame_arg))
        return None  # 交给后续搜索状态机

    with patch.object(med, "_tick_hitch_room_list_tab", side_effect=fake_tab_click):
        med._tick_lobby_hitch(frame, "LOBBY_ROOM")
    assert calls, "未触发 _tick_hitch_room_list_tab"


def test_real_archive_panel_cold_start_reconcile() -> None:
    """P0-A：真实存档挑战帧上冷启动必须分类为 ARCHIVE_PANEL，
    _tick_l0 / _tick_main_line 接管战后流程而绝不进入 Phase.ERROR。"""
    med = Mediator(Settings(dry_run=True, ocr_mode="off"), ROOT)
    frame = _game_frame("archive")
    assert med._startup_state(frame) == "ARCHIVE_PANEL"

    # _tick_l0 冷启动接管
    med.set_phase(Phase.BOOT)
    with patch.object(med, "stop") as stop:
        med._tick_l0(frame)
    assert med.phase is Phase.MAIN_LINE
    assert med._post_game_pending is True
    assert med._post_game_route == "archive"
    stop.assert_not_called()

    # _tick_main_line 启动对齐后执行，不 Fail-Closed
    med2 = Mediator(Settings(dry_run=True, ocr_mode="off"), ROOT)
    med2.set_phase(Phase.BOOT)
    med2._tick_l0(frame)
    with patch.object(med2, "stop") as stop2:
        med2._tick_main_line(frame)
    assert med2.phase is not Phase.ERROR
    assert med2._post_game_pending is True
    # 真实面板帧会直接驱动存档挑战点击（route → archive_active 属正常战后链）；
    # 回归断言核心是：不 ERROR、pending 保持、route 处于合法存档链。
    assert med2._post_game_route in {"archive", "archive_active"}
    assert med2.phase is Phase.MAIN_LINE
    stop2.assert_not_called()

def test_real_kicked_modal_safe_dismiss() -> None:
    """P1-B：真实被踢弹窗帧（OCR 注入被踢文本）上，绝不能点击「立即购买」/
    确认按钮，只允许 Esc 安全关闭并重置回大厅继续找房。"""
    med = _hitch_mediator()
    med._hitch_ocr_override = "你已被房主踢出房间"
    frame = _kk_frame("kicked")
    med._hitch_pending_row_y = 385
    med._hitch_sm.note_join_click(1.0)  # pending_join，验证被一并拒绝
    assert med._hitch_sm.pending_join

    # _hitch_ocr_override 携带被踢文本 → classify_hitch_ocr 在 tick 头部即触发
    # 被踢 reset（fail-closed），绝不点击任何按钮；Esc 由通用弹窗链发出。
    keys: list[str] = []
    clicks: list[str] = []
    with patch.object(med, "act_key", side_effect=lambda key, reason: keys.append(key) or True), \
         patch.object(med, "act_click", side_effect=lambda hit, reason: clicks.append(reason) or True):
        med._tick_lobby_hitch(frame, "LOBBY_ROOM")

    assert not clicks, f"被踢弹窗上严禁任何点击（含 HitchConfirmLeave/立即购买），实际: {clicks}"
    assert med._hitch_sm.pending_join is False
    assert med.phase is Phase.LOBBY_ROOM
    assert med._hitch_re_search is False
    assert med._hitch_search is None
    assert med._hitch_pending_row_y is None


def test_see_minimized_zero_activation() -> None:
    """P0-C：窗口最小化时 see() 全程零 activate_window 调用，仅标记 is_minimized。"""
    med = Mediator(Settings(dry_run=True, ocr_mode="off"), ROOT)
    med.set_phase(Phase.LOBBY_ROOM)
    minimized = Frame(
        np.zeros((0, 0, 3), dtype=np.uint8),
        window_title="KK官方对战平台", hwnd=555, role="l0",
        is_valid=False, error="Window is minimized",
    )
    with patch.object(med, "_capture_best", return_value=minimized), \
         patch("shuabao.vision.capture.is_window_minimized", return_value=True), \
         patch("shuabao.mediator.activate_window") as activate:
        frame = med.see("regression")
    activate.assert_not_called()
    assert frame.is_minimized is True


def test_hitch_bootstrap_priority() -> None:
    """P0-D：真实局内帧上压力转移先于自动任务门禁执行；
    自动任务 OFF 时压力转移仍被调用（不破坏压力转移）。"""
    med = _hitch_mediator()
    med.set_phase(Phase.MAIN_LINE)
    frame = _game_frame("midgame")
    order: list[str] = []

    def fake_pressure(frame_arg, now):
        order.append("pressure")
        return None

    def fake_auto_task(frame_arg):
        order.append("auto_task")
        return None

    with patch.object(med, "_find_failure_gift", return_value=None), \
         patch.object(med, "_post_game_state", return_value=None), \
         patch.object(med, "_find_stage_page", return_value=False), \
         patch.object(med, "_is_in_game_hud", return_value=True), \
         patch.object(med, "_maybe_click_hitch_pressure_transfer", side_effect=fake_pressure), \
         patch.object(med, "_ensure_auto_task_enabled", side_effect=fake_auto_task), \
         patch.object(med, "find", return_value=None):
        med._tick_main_line(frame)

    assert order[:2] == ["pressure", "auto_task"], f"压力转移必须先于自动任务: {order}"


def test_ready_180s_timeout_and_blacklist() -> None:
    """P0-B：Ready 状态维持 >= 180 秒时，房号加入黑名单并安全退房回大厅。"""
    med = _hitch_mediator()
    frame = _kk_frame("kicked")  # 任意非黑帧 KK 帧
    med.set_phase(Phase.ROOM_WAITING)
    med._confirmed_room_hwnd = frame.hwnd
    med._hitch_pending_room_key = "room-765432"
    med._hitch_ready_confirmed_at = 0.0

    now = 200.0  # 0.0 + 200 >= 180
    with patch.object(med, "find_scene", return_value=None), \
         patch.object(med, "_is_confirmed_room_frame", return_value=True), \
         patch.object(med, "_find_hitch_ready_button", return_value=None), \
         patch.object(med, "_find_hitch_exit_button", return_value=None), \
         patch.object(med, "act_key", return_value=True) as act_key, \
         patch.object(med, "act_click", return_value=False) as act_click, \
         patch.object(med, "find", return_value=None), \
         patch("shuabao.mediator.time.time", return_value=now):
        med._tick_lobby_hitch(frame, "ROOM_WAITING")

    assert "room-765432" in med._hitch_blacklisted_room_keys
    # 安全退房：Esc 输入发出，状态重置回大厅找房
    assert act_key.called
    reasons = [call.args[1] for call in act_key.call_args_list]
    assert any("exit" in r.lower() for r in reasons), reasons
    assert med.phase is Phase.LOBBY_ROOM
    assert med._hitch_re_search is True
    assert med._hitch_pending_room_key is None
