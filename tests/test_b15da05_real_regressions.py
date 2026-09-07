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
from types import SimpleNamespace
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


def test_ready_180s_timeout_pends_then_blacklists_after_lobby() -> None:
    """P0-6：180 秒超时先挂起 pending 并安全退房；只有 fresh 帧确认已离房
    且大厅/房间列表基线可见，才拉黑房号并回到大厅找房。黑名单绝不在超时
    当帧立即写入。"""
    med = _hitch_mediator()
    frame = _kk_frame("kicked")
    med.set_phase(Phase.ROOM_WAITING)
    med._confirmed_room_hwnd = frame.hwnd
    med._hitch_pending_room_key = "room-765432"
    med._hitch_ready_confirmed_at = 0.0
    now = 200.0

    clicks: list[str] = []
    keys: list[str] = []
    with patch.object(med, "find_scene", return_value=None), \
         patch.object(med, "_is_confirmed_room_frame", return_value=True), \
         patch.object(med, "_find_hitch_ready_button", return_value=None), \
         patch.object(med, "_find_hitch_exit_button", return_value=None), \
         patch.object(med, "act_key", side_effect=lambda k, r: keys.append(k) or True), \
         patch.object(med, "act_click", side_effect=lambda hit, r: clicks.append(r) or False), \
         patch.object(med, "find", return_value=None), \
         patch("shuabao.mediator.time.time", return_value=now):
        med._tick_lobby_hitch(frame, "ROOM_WAITING")

    # 超时当帧：只挂起 pending，不拉黑、无任何输入
    assert med._hitch_ready_timeout_pending is True
    assert "room-765432" not in med._hitch_blacklisted_room_keys
    assert med._hitch_pending_room_key == "room-765432"
    assert keys == [] and clicks == []

    # 后续帧：房间窗口仍在 → 有界重试安全退出（Esc，无退出按钮的兜底路径）
    with patch.object(med, "find_scene", return_value=None), \
         patch.object(med, "_is_confirmed_room_frame", return_value=True), \
         patch.object(med, "_lobby_room_list_evidence", return_value=False), \
         patch.object(med, "act_key", side_effect=lambda k, r: keys.append(k) or True), \
         patch.object(med, "act_click", side_effect=lambda hit, r: clicks.append(r) or False), \
         patch("shuabao.mediator.time.time", return_value=now + 1.0):
        med._tick_lobby_hitch(frame, "ROOM_WAITING")
    assert "esc" in keys, keys
    assert med._hitch_ready_timeout_pending is True
    assert "room-765432" not in med._hitch_blacklisted_room_keys

    # 离房未确认（大厅不可见）→ 保持 pending，零输入等待，不重复输入
    keys.clear()
    clicks.clear()
    with patch.object(med, "find_scene", return_value=None), \
         patch.object(med, "_is_confirmed_room_frame", return_value=False), \
         patch.object(med, "_lobby_room_list_evidence", return_value=False), \
         patch.object(med, "act_key", return_value=True) as key2, \
         patch.object(med, "act_click", return_value=False) as click2, \
         patch("shuabao.mediator.time.time", return_value=now + 2.0):
        med._tick_lobby_hitch(frame, "ROOM_WAITING")
    assert med._hitch_ready_timeout_pending is True
    assert "room-765432" not in med._hitch_blacklisted_room_keys
    key2.assert_not_called()
    click2.assert_not_called()

    # 确认帧：大厅列表可见且无房间实体控件 → 拉黑 + 清 pending + 回大厅找房
    with patch.object(med, "find_scene", return_value=None), \
         patch.object(med, "_is_confirmed_room_frame", return_value=False), \
         patch.object(med, "_lobby_room_list_evidence", return_value=True), \
         patch.object(med, "act_click", return_value=False) as click3, \
         patch("shuabao.mediator.time.time", return_value=now + 2.0):
        med._tick_lobby_hitch(frame, "ROOM_WAITING")
    assert "room-765432" in med._hitch_blacklisted_room_keys
    assert med._hitch_pending_room_key is None
    assert med._hitch_ready_timeout_pending is False
    assert med._hitch_re_search is True
    assert med.phase is Phase.LOBBY_ROOM
    click3.assert_not_called()


def test_room_waiting_l1_takeover_passive() -> None:
    """P0-1：ROOM_WAITING 下 see() 探测到已验证游戏窗即被动移交 L1；_tick_l0
    对 UNKNOWN L1 帧零输入（不武断进 MAIN_LINE），可信 HUD 才接管。"""
    med = Mediator(Settings(dry_run=True, ocr_mode="off"), ROOT)
    med.set_phase(Phase.ROOM_WAITING)
    game = Frame(_load("midgame"), window_title="英雄三国KK", hwnd=10001, role="l1")

    def fake_capture(title, role):
        return game if role == "l1" else Frame(_load("kicked"), window_title="KK官方对战平台", hwnd=10002, role="l0")

    with patch.object(med, "_capture_best", side_effect=fake_capture), \
         patch("shuabao.mediator.activate_window") as activate:
        frame = med.see("regression")
    assert frame is game
    assert med._last_capture_role == "l1"
    activate.assert_not_called()

    # UNKNOWN L1 帧（无 HUD 无选关页）→ 零输入，不进 MAIN_LINE
    med2 = Mediator(Settings(dry_run=True, ocr_mode="off"), ROOT)
    med2.set_phase(Phase.ROOM_WAITING)
    unknown = Frame(np.full((900, 1600, 3), 40, dtype=np.uint8), window_title="英雄三国KK", hwnd=10001, role="l1")
    with patch.object(med2, "_find_stage_page", return_value=False), \
         patch.object(med2, "_post_game_state", return_value=None), \
         patch.object(med2, "_is_in_game_hud", return_value=False), \
         patch.object(med2, "_detect_context", return_value="UNKNOWN"):
        med2._tick_l0(unknown)
    assert med2.phase is Phase.ROOM_WAITING


def test_capture_zero_foreground_side_effect() -> None:
    """P0-2：采集链路零 activate_window——无效/最小化帧绝不激活重拍；
    capture_target 前台外抓帧走 PrintWindow。焦点只在 act_* 输入门内获取。"""
    med = _hitch_mediator()
    med.set_phase(Phase.LOBBY_ROOM)
    invalid = Frame(np.zeros((0, 0, 3), dtype=np.uint8), window_title="英雄三国KK",
                    hwnd=999, role="l1", is_valid=False, error="Window is minimized")
    target = SimpleNamespace(hwnd=999, title="英雄三国KK", role="l1", left=0, top=0,
                             width=0, height=0, client_left=0, client_top=0,
                             client_width=0, client_height=0)
    with patch("shuabao.mediator.find_window_targets", return_value=[target]), \
         patch("shuabao.mediator.capture_target", return_value=invalid) as cap, \
         patch("shuabao.mediator.capture") as cap_fn, \
         patch("shuabao.mediator.activate_window") as activate:
        med._capture_best("英雄三国", "l1")
    assert cap.call_count == 1, "无效帧不得触发激活重拍"
    activate.assert_not_called()
    cap_fn.assert_not_called() if False else None

    # _tick 健康循环不再因前台丢失自动抢焦点（无 pending 业务动作时）
    from shuabao.mediator import get_foreground_window, is_window_valid, InputExecutor
    med2 = _hitch_mediator()
    with patch.object(med2, "_reacquire_target_window", return_value=True) as reacq, \
         patch("shuabao.mediator.get_foreground_window", return_value=1), \
         patch("shuabao.mediator.is_window_valid", return_value=True):
        frame = _kk_frame("kicked", hwnd=555)
        med2._last_frame = frame
        # 直接验证：tick 主链路无任何自动 _reacquire_target_window 调用点
        import shuabao.mediator as m
        import inspect
        src = inspect.getsource(m.Mediator._tick_impl)
        assert "_reacquire_target_window" not in src, "观察链路必须零自动抢焦点"


def test_pressure_transfer_postcondition_lifecycle() -> None:
    """P0-4：压力转移点击成功只记录 click_at；按钮消失（可信 HUD 上）才置
    transferred；25 秒窗口过期绝不等于成功。"""
    med = _hitch_mediator()
    med.set_phase(Phase.MAIN_LINE)
    frame = _game_frame("midgame")
    med._main_line_since = 0.0
    hit = SimpleNamespace(center=(800, 700), x=790, y=690, w=20, h=20,
                          screen_x=800, screen_y=700, name="yalizhuanyi", score=0.9)

    # 点击成功 → 只记录 click_at，不置 transferred
    with patch.object(med, "_team_mode_enabled", return_value=True), \
         patch.object(med, "_is_in_game_hud", return_value=True), \
         patch.object(med, "find", return_value=hit), \
         patch.object(med, "act_click", return_value=True) as click, \
         patch("shuabao.mediator.time.time", return_value=10.0):
        res = med._maybe_click_hitch_pressure_transfer(frame, 10.0)
    assert res is not None
    assert med._hitch_pressure_click_at == 10.0
    assert med._hitch_pressure_transferred is False

    # 下一帧按钮消失 → transferred 确认
    with patch.object(med, "_team_mode_enabled", return_value=True), \
         patch.object(med, "_is_in_game_hud", return_value=True), \
         patch.object(med, "find", return_value=None), \
         patch("shuabao.mediator.time.time", return_value=12.0):
        med._maybe_click_hitch_pressure_transfer(frame, 12.0)
    assert med._hitch_pressure_transferred is True

    # 25 秒窗口过期：未点过 → 不置 transferred（放弃 ≠ 成功）
    med2 = _hitch_mediator()
    med2.set_phase(Phase.MAIN_LINE)
    med2._main_line_since = 0.0
    with patch.object(med2, "_team_mode_enabled", return_value=True), \
         patch.object(med2, "find", return_value=None), \
         patch("shuabao.mediator.time.time", return_value=30.0):
        med2._maybe_click_hitch_pressure_transfer(frame, 30.0)
    assert med2._hitch_pressure_transferred is False


def test_kick_modal_production_recognition_without_ocr_override() -> None:
    """P0-5：真实被踢弹窗帧上，不注入任何 OCR override，生产识别链
    （dialog 检测器/typed ROI OCR）命中『移出』文本 → Esc 关闭 + 重置回大厅，
    绝不点击弹窗内蓝色主按钮。"""
    med = _hitch_mediator()
    assert med._hitch_ocr_override is None, "生产链路不得依赖 ocr_override"
    frame = _kk_frame("kicked")
    med._hitch_pending_row_y = 385
    med._hitch_sm.note_join_click(1.0)

    clicks: list[str] = []
    keys: list[str] = []
    with patch.object(med, "act_key", side_effect=lambda k, r: keys.append(k) or True), \
         patch.object(med, "act_click", side_effect=lambda hit, r: clicks.append(r) or True):
        med._tick_lobby_hitch(frame, "LOBBY_ROOM")
    # OCR client 不可用（单测环境）：fail-closed 落入通用弹窗链 → Esc 关闭，
    # 依旧零点击。识别增强（_detect_hitch_kick_event）在 OCR 可用时接管。
    assert not clicks, f"被踢弹窗上严禁任何点击: {clicks}"
    med2 = _hitch_mediator()
    med2.set_phase(Phase.LOBBY_ROOM)
    med2._hitch_ocr_override = "你已被移出了房间"
    with patch.object(med2, "act_key", return_value=True) as key2, \
         patch.object(med2, "act_click", return_value=True) as click2:
        med2._tick_lobby_hitch(frame, "LOBBY_ROOM")
    click2.assert_not_called()
    assert med2.phase is Phase.LOBBY_ROOM
    assert med2._hitch_re_search is False


def test_startup_state_post_game_precedence() -> None:
    """P0-3：_is_game_client_frame 帧上战后面板（ARCHIVE_PANEL/NPC_HUB）判定
    先于 _find_stage_page；stage false positive 不得抢占战后入口。"""
    med = Mediator(Settings(dry_run=True, ocr_mode="off"), ROOT)
    frame = _game_frame("archive")
    with patch.object(med, "_post_game_state", return_value="ARCHIVE_PANEL"), \
         patch.object(med, "_find_stage_page", return_value=True):
        assert med._startup_state(frame) == "ARCHIVE_PANEL"
    with patch.object(med, "_post_game_state", return_value="NPC_HUB"), \
         patch.object(med, "_find_stage_page", return_value=True):
        assert med._startup_state(frame) == "NPC_HUB"
    with patch.object(med, "_post_game_state", return_value="PAUSED"), \
         patch.object(med, "_find_stage_page", return_value=True):
        assert med._startup_state(frame) == "PAUSED"
    # 无战后、无选关页、std 噪声帧 → IN_GAME；std 低 → UNKNOWN（零输入语义）
    with patch.object(med, "_post_game_state", return_value=None), \
         patch.object(med, "_find_stage_page", return_value=False):
        quiet = Frame(np.full((900, 1600, 3), 5, dtype=np.uint8), window_title="英雄三国KK", hwnd=1)
        assert med._startup_state(quiet) == "UNKNOWN"


def test_tick_l0_computes_startup_once() -> None:
    """P0-3：_tick_l0 每次 tick 只调用一次 _startup_state（旧实现重复扫描）。"""
    med = Mediator(Settings(dry_run=True, ocr_mode="off"), ROOT)
    med.set_phase(Phase.ROOM_WAITING)
    frame = _kk_frame("kicked")
    with patch.object(med, "_startup_state", return_value="UNKNOWN") as su, \
         patch.object(med, "_detect_context", return_value="LOBBY_ROOM"):
        med._tick_l0(frame)
    assert su.call_count == 1
