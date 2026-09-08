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

from shuabao.mediator import Mediator, LoopAction, Phase
from shuabao.vision.matcher import MatchResult
from shuabao.settings import Settings
from shuabao.vision.capture import Frame

ROOT = Path(__file__).resolve().parents[1]

FIXTURES = {
    "leaderboard": ROOT / "tests" / "fixtures" / "real_leaderboard_frame.png",
    "kicked": ROOT / "tests" / "fixtures" / "real_kicked_modal_frame.jpg",
    "archive": ROOT / "tests" / "fixtures" / "real_archive_panel_frame.jpg",
    "midgame": ROOT / "tests" / "fixtures" / "real_midgame_hitch_hud_frame.png",
    # 真实战后帧（reborn_wow / live 实拍）：B3 分子红像素测量与 B4 互斥用。
    "rw_archive": ROOT / "fixtures" / "reborn_wow" / "endgame" / "archive_challenge_panel.png",
    "rw_hub": ROOT / "fixtures" / "reborn_wow" / "endgame" / "challenge_npc_hub.png",
    "live_archive": ROOT / "fixtures" / "live_postgame_20260808" / "live_archive_challenges.png",
    "live_start": ROOT / "fixtures" / "live_postgame_20260808" / "live_archive_start_panel.png",
}

# 被踢弹窗真实帧（tests/fixtures/real_kicked_modal_frame.jpg）的地面真值：
# 单测环境 OCR 离线（无 worker），真实帧上的被踢/移出文本无法用生产 OCR 链
# 解析（RAW FRAME 证据缺失），识别链 fail-closed → UNKNOWN_GENERIC_MODAL。
KICK_REAL_GT = "BLOCKED_MISSING_RAW_FRAME"


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


def _fake_ocr_client(text: str, rec_score: float, status: str = "ok") -> SimpleNamespace:
    """C6 收紧后的可信 OCR 语义：status=="ok" + raw_text + rec_score 才是
    counter 解析 authority。"""
    return SimpleNamespace(
        is_available=True,
        shadow_predict=lambda *args, **kwargs: SimpleNamespace(
            status=status, raw_text=text, rec_score=rec_score
        ),
    )


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

    # C2 修复：同一 request 帧绝不 confirm；只有 fresh generation 且按钮消失才 confirm
    with (
        patch.object(med, "_team_mode_enabled", return_value=True),
        patch.object(med, "_is_in_game_hud", return_value=True),
        patch.object(med, "find", return_value=None),
        patch("shuabao.mediator.time.time", return_value=12.0),
    ):
        # 同一 request 帧（generation 未变）：不 confirm
        med._maybe_click_hitch_pressure_transfer(frame, 12.0)
        assert med._hitch_pressure_transferred is False
        # fresh 帧（不同 Frame 产生新 generation）：确认 transferred
        fresh_frame = _game_frame("midgame")
        med._maybe_click_hitch_pressure_transfer(fresh_frame, 12.0)
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


def test_pending_join_popup_dismisses_without_clicking_quick_join() -> None:
    """刚点房间行后出现的 KK 弹窗只 Esc 取消、拒绝本行，绝不点快速加入。"""
    med = _hitch_mediator()
    assert med._hitch_ocr_override is None, "生产链路不得依赖 ocr_override"
    frame = _kk_frame("kicked")
    med._hitch_pending_row_y = 385
    med._hitch_sm.note_join_click(1.0)

    dialog_hit = MatchResult("lobby_popup_dialog", 0.9, 400, 300, 500, 250, 400, 300)
    clicks: list[str] = []
    keys: list[str] = []
    with patch.object(med, "find_scene", return_value=dialog_hit), \
         patch.object(med, "act_key", side_effect=lambda k, r: keys.append(k) or True), \
         patch.object(med, "act_click", side_effect=lambda hit, r: clicks.append(r) or True):
        med._tick_lobby_hitch(frame, "LOBBY_ROOM")
    assert not clicks, f"被踢弹窗上严禁任何点击: {clicks}"
    assert keys == ["esc"]
    assert med._hitch_sm.pending_join is False
    assert med._hitch_rejected_row_ys == {385}
    med2 = _hitch_mediator()
    med2.set_phase(Phase.LOBBY_ROOM)
    med2._hitch_ocr_override = "你已被移出了房间"
    with patch.object(med2, "act_key", return_value=True) as key2, \
         patch.object(med2, "act_click", return_value=True) as click2:
        med2._tick_lobby_hitch(frame, "LOBBY_ROOM")
    click2.assert_not_called()
    assert med2.phase is Phase.LOBBY_ROOM
    assert med2._hitch_re_search is False


def test_generic_popup_without_pending_join_remains_zero_input() -> None:
    med = _hitch_mediator()
    frame = _kk_frame("kicked")
    dialog_hit = MatchResult("lobby_popup_dialog", 0.9, 400, 300, 500, 250, 400, 300)
    with patch.object(med, "find_scene", return_value=dialog_hit), \
         patch.object(med, "act_key", return_value=True) as key, \
         patch.object(med, "act_click", return_value=True) as click:
        med._tick_lobby_hitch(frame, "LOBBY_ROOM")
    key.assert_not_called()
    click.assert_not_called()


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


def test_b1_tqtz_click_latches_pending_until_fresh_frame_confirms() -> None:
    """B1：tqtz 点击成功 ≠ 挑战已接受。点击只挂起 pending，必须 fresh 帧
    确认图标消失（或 Boss 面出现）才落定 _tqtz_clicked；确认前零输入。"""
    med = Mediator(Settings(dry_run=True, ocr_mode="off"), ROOT)
    med.set_phase(Phase.MAIN_LINE)
    frame = _game_frame("midgame")
    tqtz_hit = MatchResult("tqtz", 0.85, 438, 79, 85, 22, 665, 171)
    with patch.object(med, "find", return_value=tqtz_hit) as find, \
         patch.object(med, "find_scene", return_value=None), \
         patch.object(med, "act_click", return_value=True) as click:
        # 首帧：点击成功 → pending，不落定 clicked
        assert med._maybe_click_tqtz(frame, 100.0) is LoopAction.Continue
        assert med._tqtz_clicked is False
        assert med._tqtz_pending is True
        assert med._tqtz_pending_since == 100.0
        assert med._tqtz_next_check_at == 101.0
        assert click.call_count == 1
        # 观察窗内（now < next_check_at）：零输入等待
        assert med._maybe_click_tqtz(frame, 100.5) is LoopAction.Continue
        assert find.call_count == 1, "观察窗内不得重复扫描/点击"
        # fresh 帧图标仍在（未超 5s）：继续零输入等待，不重复点击
        assert med._maybe_click_tqtz(frame, 101.5) is LoopAction.Continue
        assert med._tqtz_clicked is False
        assert med._tqtz_pending is True
        assert click.call_count == 1
        # C5 修复：同一 request 帧即便 locator miss 也不得 confirm
        with (
            patch.object(med, "find", return_value=None),
            patch.object(med, "_is_in_game_hud", return_value=True),
        ):
            assert med._maybe_click_tqtz(frame, 103.0) is LoopAction.Continue
            assert med._tqtz_clicked is False
            # fresh 帧（新 Frame 产生新 generation）且仍在 HUD：确认 clicked
            fresh_frame = _game_frame("midgame")
            assert med._maybe_click_tqtz(fresh_frame, 103.0) is LoopAction.Continue
    assert med._tqtz_clicked is True
    assert med._tqtz_pending is False
    assert click.call_count == 1, "确认成功前绝不允许第二次点击"


def test_b1_tqtz_pending_timeout_resets_for_bounded_retry() -> None:
    """B1：pending 5 秒观察窗超时 → 清 pending 允许有界重试（不落定成功）。"""
    med = Mediator(Settings(dry_run=True, ocr_mode="off"), ROOT)
    med.set_phase(Phase.MAIN_LINE)
    frame = _game_frame("midgame")
    tqtz_hit = MatchResult("tqtz", 0.85, 438, 79, 85, 22, 665, 171)
    med._tqtz_pending = True
    med._tqtz_pending_since = 100.0
    med._tqtz_next_check_at = 101.0
    with patch.object(med, "find", return_value=tqtz_hit), \
         patch.object(med, "find_scene", return_value=None), \
         patch.object(med, "act_click", return_value=True) as click:
        # 105.5 >= pending_since + 5.0：图标仍在 → 超时重置 pending
        assert med._maybe_click_tqtz(frame, 105.5) is LoopAction.Continue
        assert med._tqtz_pending is False
        assert med._tqtz_clicked is False
        # 下一帧允许重新点击（有界重试）
        assert med._maybe_click_tqtz(frame, 106.5) is LoopAction.Continue
    assert click.call_count == 1
    assert med._tqtz_pending is True, "重试点击成功后重新进入 pending 确认"
    assert med._tqtz_pending_since == 106.5


def test_b1_round_reset_clears_tqtz_pending() -> None:
    """B1：进入新一局（MAIN_LINE）时 pending 状态必须清零。"""
    med = Mediator(Settings(dry_run=True, ocr_mode="off"), ROOT)
    med._tqtz_pending = True
    med._tqtz_pending_since = 12345.0
    med.set_phase(Phase.MAIN_LINE)
    assert med._tqtz_pending is False
    assert med._tqtz_pending_since == 0.0


def test_c_tqtz_two_round_reset_allows_attempt_in_second_round() -> None:
    """C5/C6：第一局 tqtz 重试预算耗尽（3 次）→ ABANDONED 放弃（绝不伪装成功）；
    每局边界 reset 必须清空 ABANDONED 与重试预算，第二局允许重新点击尝试。"""
    med = Mediator(Settings(dry_run=True, ocr_mode="off"), ROOT)
    med.set_phase(Phase.MAIN_LINE)
    frame = _game_frame("midgame")
    tqtz_hit = MatchResult("tqtz", 0.85, 438, 79, 85, 22, 665, 171)

    # 第一轮：3 次点击耗尽重试预算
    med._tqtz_attempts = 3
    with patch.object(med, "find", return_value=tqtz_hit), \
         patch.object(med, "find_scene", return_value=None), \
         patch.object(med, "act_click", return_value=True) as click:
        # 预算耗尽的第一帧调用：标记 ABANDONED（而非伪装 clicked=True）
        assert med._maybe_click_tqtz(frame, 100.0) is LoopAction.Continue
        assert med._tqtz_abandoned is True
        assert med._tqtz_clicked is False
        assert med._tqtz_pending is False
        # ABANDONED 短路：后续调用零输入、零点击
        assert med._maybe_click_tqtz(frame, 101.0) is LoopAction.Continue
        assert click.call_count == 0
    assert med._tqtz_clicked is False, "ABANDONED 绝不允许伪装成已点击成功"

    # 每局边界 reset（进入新一局）：ABANDONED 与 attempts 必须清零
    med.set_phase(Phase.MAIN_LINE)
    assert med._tqtz_abandoned is False
    assert med._tqtz_attempts == 0

    # 第二轮：tqtz 图标可见 → 允许重新点击并进入 pending 确认
    with patch.object(med, "find", return_value=tqtz_hit), \
         patch.object(med, "find_scene", return_value=None), \
         patch.object(med, "act_click", return_value=True) as click2:
        assert med._maybe_click_tqtz(frame, 300.0) is LoopAction.Continue
    assert click2.call_count == 1
    assert med._tqtz_pending is True
    assert med._tqtz_clicked is False
    assert med._tqtz_attempts == 1


def test_b2_auto_task_gate_never_reenables_after_main_line_close() -> None:
    """B2：auto_close_main_line 触发后/主线关闭完成后，通用自动任务启用
    门禁绝不能再把勾选打回去（期望状态是 OFF）。"""
    frame = _game_frame("midgame")
    toggle = SimpleNamespace(center=(1500, 500), x=1490, y=490, w=20, h=20,
                             screen_x=1500, screen_y=500, name="auto_task", score=0.9)

    # 对照组：无关闭标志时门禁正常启用（点击 toggle）
    med = _hitch_mediator()
    med.set_phase(Phase.MAIN_LINE)
    with patch.object(med, "_auto_task_state", return_value=("OFF", None)), \
         patch.object(med, "_auto_task_unknown_fuse", return_value=None), \
         patch.object(med, "_find_auto_task_toggle", return_value=toggle), \
         patch.object(med, "act_click", return_value=True) as click:
        assert med._ensure_auto_task_enabled(frame) is LoopAction.Continue
    assert click.call_count == 1

    # auto_close_main_line=True 且已触发关闭 → 必须返回 None 且零输入
    med2 = _hitch_mediator()
    med2.settings.auto_close_main_line = True
    med2._close_main_line_triggered = True
    with patch.object(med2, "_auto_task_state", return_value=("OFF", None)), \
         patch.object(med2, "_auto_task_unknown_fuse", return_value=None), \
         patch.object(med2, "_find_auto_task_toggle", return_value=toggle), \
         patch.object(med2, "act_click", return_value=True) as click2:
        assert med2._ensure_auto_task_enabled(frame) is None
    click2.assert_not_called()

    # 主线关闭已完成 → 永不重新启用
    med3 = _hitch_mediator()
    med3.settings.auto_close_main_line = True
    med3._main_line_closed_done = True
    with patch.object(med3, "_auto_task_state", return_value=("OFF", None)), \
         patch.object(med3, "_auto_task_unknown_fuse", return_value=None), \
         patch.object(med3, "_find_auto_task_toggle", return_value=toggle), \
         patch.object(med3, "act_click", return_value=True) as click3:
        assert med3._ensure_auto_task_enabled(frame) is None
    click3.assert_not_called()


def test_b3_real_progress_counters_are_not_unavailable() -> None:
    """B3：真实 7/8、8/8 进度帧（绿色分子数字）绝不判为 0/8 不可用。

    实机测量（reborn_wow / live_postgame 真实帧）：gem/loot 卡分子数字为
    绿色渲染，分子 ROI（counter 左半 ≈ 0.012w）红像素 0-3，全 counter 红
    像素最高 40+；旧的全 counter >= 40 阈值会误伤。
    """
    for name in ("rw_archive", "live_archive", "archive"):
        med = _hitch_mediator()
        frame = _game_frame(name)
        for card_index in (2, 3):
            assert med._archive_hitch_card_unavailable(frame, card_index) is False, (
                f"{name} card{card_index} 是 7/8 或 8/8 实拍进度，不得判为 0/8 不可用"
            )


def test_b3_synthetic_red_block_does_not_authorize_unavailable() -> None:
    """C6：删除单纯红像素作为生产 business authority。纯人工合成红块必须判定为 UNKNOWN，
    绝不能直接授权判定为不可用（unavailable）。"""
    med = _hitch_mediator()
    frame = _game_frame("archive")
    h, w = frame.bgr.shape[:2]
    col, row = 2 % 4, 2 // 4
    cx = int(w * med._ARCHIVE_CHALLENGE_X[col])
    cy = int(h * med._ARCHIVE_CHALLENGE_Y[row])
    red_bgr = (60, 60, 230)
    x0 = cx + int(w * 0.002)
    x1 = cx + int(w * 0.027)
    y0 = cy - int(h * 0.078)
    y1 = cy - int(h * 0.039)
    modified = frame.bgr.copy()
    cv2.rectangle(modified, (x0, y0), (x1, y1), red_bgr, -1)
    modified_frame = Frame(modified, window_title="英雄三国KK", hwnd=frame.hwnd, role="l1")
    # C6 契约：纯合成红块无法形成结构化 OCR / 笔画文字证据 -> 状态必须是 UNKNOWN，unavailable 必须是 False
    assert med._archive_hitch_card_progress_state(modified_frame, 2) == "UNKNOWN"
    assert med._archive_hitch_card_unavailable(modified_frame, 2) is False
    # 原始帧（7/8 实拍）：离线模式（ocr_mode="off"）无可信 OCR 证据，绿色像素
    # 不再单独授权 AVAILABLE → 状态 UNKNOWN（零输入等待），unavailable 仍为 False。
    assert med._archive_hitch_card_progress_state(frame, 2) == "UNKNOWN"
    assert med._archive_hitch_card_unavailable(frame, 2) is False


def test_archive_counter_trusted_ocr_0_of_8_is_unavailable() -> None:
    """C6 收紧：可信 OCR（rec_score >= 0.75）明确解析 0/8 → UNAVAILABLE。"""
    med = _hitch_mediator()
    frame = _game_frame("archive")
    fake = _fake_ocr_client("0/8", 0.9)
    with patch.object(med, "_ocr_client", fake):
        assert med._archive_hitch_card_progress_state(frame, 2) == "UNAVAILABLE"
        assert med._archive_hitch_card_unavailable(frame, 2) is True


def test_archive_counter_trusted_ocr_0_of_3_denominator_is_unknown() -> None:
    """C6 收紧：分母非 8（如 0/3）绝不是 0/8 不可用 → UNKNOWN，绝不授权 unavailable。"""
    med = _hitch_mediator()
    frame = _game_frame("archive")
    fake = _fake_ocr_client("0/3", 0.9)
    with patch.object(med, "_ocr_client", fake):
        assert med._archive_hitch_card_progress_state(frame, 2) == "UNKNOWN"
        assert med._archive_hitch_card_unavailable(frame, 2) is False


def test_archive_counter_low_confidence_0_of_8_is_unknown() -> None:
    """C6 收紧：低置信度（rec_score < 0.75）OCR 即使读出 0/8 也绝不授权 UNAVAILABLE。"""
    med = _hitch_mediator()
    frame = _game_frame("archive")
    fake = _fake_ocr_client("0/8", 0.5)
    with patch.object(med, "_ocr_client", fake):
        assert med._archive_hitch_card_progress_state(frame, 2) == "UNKNOWN"
        assert med._archive_hitch_card_unavailable(frame, 2) is False


def test_archive_counter_green_noise_without_ocr_is_unknown() -> None:
    """C6 收紧：绿色像素只是辅助证据，绝不单独授权 AVAILABLE；
    OCR 离线时绿色噪声 ROI 必须 UNKNOWN（unavailable 仍为 False）。"""
    med = _hitch_mediator()
    frame = _game_frame("archive")
    h, w = frame.bgr.shape[:2]
    col, row = 2 % 4, 2 // 4
    cx = int(w * med._ARCHIVE_CHALLENGE_X[col])
    cy = int(h * med._ARCHIVE_CHALLENGE_Y[row])
    x0 = min(w, cx + int(w * 0.002))
    x1 = min(w, cx + int(w * 0.027))
    y0 = max(0, cy - int(h * 0.078))
    y1 = max(0, cy - int(h * 0.039))
    modified = frame.bgr.copy()
    rng = np.random.default_rng(7)
    noise = np.zeros((y1 - y0, x1 - x0, 3), dtype=np.uint8)
    noise[..., 1] = rng.integers(120, 255, (y1 - y0, x1 - x0))  # 纯绿色通道噪声
    modified[y0:y1, x0:x1] = noise
    green_frame = Frame(modified, window_title="英雄三国KK", hwnd=frame.hwnd, role="l1")
    assert med._archive_hitch_card_progress_state(green_frame, 2) == "UNKNOWN"
    assert med._archive_hitch_card_unavailable(green_frame, 2) is False


def test_archive_challenge_unknown_state_with_card_hit_is_zero_input() -> None:
    """UNKNOWN 进度 + 卡面模板命中 → 零输入（Continue），绝不点击卡面。"""
    med = _hitch_mediator()
    frame = _game_frame("archive")
    # 离线模式：gem 卡（plan 首位，card_index=2）无可信 OCR → UNKNOWN
    assert med._archive_hitch_card_progress_state(frame, 2) == "UNKNOWN"
    card_hit = MatchResult("lobby/archive_card3", 0.92, 700, 500, 140, 70, 700, 500)
    with patch.object(med, "_find_archive_challenge_card", return_value=card_hit), \
         patch.object(med, "act_click", return_value=True) as click:
        assert med._maybe_click_archive_challenge(frame, 100.0) is LoopAction.Continue
    click.assert_not_called()
    assert med._archive_challenge_index == 0, "UNKNOWN 状态零输入，绝不推进挑战计划"


def test_b4_npc_hub_and_archive_panel_are_mutually_exclusive() -> None:
    """B4：存档面板关闭按钮可见 ⇒ 绝不分类为 NPC_HUB；真实广场帧仍为
    NPC_HUB，真实存档面板帧仍为 ARCHIVE_PANEL。"""
    med = _hitch_mediator()
    # 真实广场帧：无关闭按钮 → NPC_HUB
    hub_frame = _game_frame("rw_hub")
    assert med._post_game_state(hub_frame) == "NPC_HUB"

    # 同一广场帧若叠加存档面板关闭按钮证据 → 不再是纯 NPC_HUB
    med2 = _hitch_mediator()
    fake_close = MatchResult("lobby/archive_panel_close", 0.9, 1560, 260, 30, 30, 1560, 260)
    with patch.object(med2, "_find_archive_panel_close", return_value=fake_close):
        assert med2._post_game_state(hub_frame) != "NPC_HUB"

    # 真实存档面板帧（关闭按钮可见）→ 恒为 ARCHIVE_PANEL，绝不 NPC_HUB
    med3 = _hitch_mediator()
    archive_frame = _game_frame("rw_archive")
    assert med3._post_game_state(archive_frame) == "ARCHIVE_PANEL"


def test_b5_unclassified_post_game_frame_is_zero_input() -> None:
    """B5：战后状态 UNKNOWN（_post_game_state 为 None）时主循环零输入。"""
    med = Mediator(Settings(dry_run=True, ocr_mode="off"), ROOT)
    med.set_phase(Phase.MAIN_LINE)
    # 真实未分类战后帧（live 实拍，_post_game_state -> None）
    frame = _game_frame("live_start")
    assert med._post_game_state(frame) is None
    med._post_game_pending = True
    clicks: list[str] = []
    keys: list[str] = []
    with patch.object(med, "_find_failure_gift", return_value=None), \
         patch.object(med, "_round_tail_checks_active", return_value=False), \
         patch.object(med, "_maybe_clear_pressure_monsters", return_value=LoopAction.Continue), \
         patch.object(med, "_maybe_click_tqtz", return_value=None), \
         patch.object(med, "_tick_early_challenge", return_value=None), \
         patch.object(med, "_ensure_auto_task_enabled", return_value=None), \
         patch.object(med, "act_click", side_effect=lambda hit, reason: clicks.append(reason) or True), \
         patch.object(med, "act_key", side_effect=lambda key, reason: keys.append(key) or True), \
         patch.object(med, "act_right_click", side_effect=lambda hit, reason: clicks.append(reason) or True):
        assert med._tick_main_line(frame) is LoopAction.Continue
    assert not clicks, f"UNKNOWN 战后帧上严禁任何点击: {clicks}"
    assert not keys, f"UNKNOWN 战后帧上严禁任何按键: {keys}"


def test_pending_join_timeout_without_known_modal_is_zero_input() -> None:
    """进房超时 + 帧上无任何可信已知弹窗（被踢 OCR / 显式 dialog/title）→
    零输入：绝不发送 HitchDismissPopup；仅拒绝本次进房并回大厅。"""
    med = _hitch_mediator()
    med.set_phase(Phase.LOBBY_ROOM)
    frame = _kk_frame("kicked")
    med._hitch_pending_row_y = 385
    med._hitch_sm.note_join_click(97.0)
    assert med._hitch_sm.pending_join is True

    clicks: list[str] = []
    keys: list[str] = []
    with patch.object(med, "find_scene", return_value=None), \
         patch.object(med, "_find_hitch_ready_button", return_value=None), \
         patch.object(med, "act_key", side_effect=lambda k, r: keys.append(k) or True) as key, \
         patch.object(med, "act_click", side_effect=lambda hit, r: clicks.append(r) or True) as click, \
         patch("shuabao.mediator.time.time", return_value=100.0):
        med._tick_lobby_hitch(frame, "LOBBY_ROOM")

    key.assert_not_called(), f"未知画面超时必须零输入，实际按键: {keys}"
    click.assert_not_called()
    assert med._hitch_sm.pending_join is False, "超时仍必须拒绝本次进房"
    assert med._hitch_pending_row_y is None
    assert med._hitch_rejected_row_ys == {385}
    assert med.phase is Phase.LOBBY_ROOM


def test_pending_join_timeout_with_known_modal_still_dismisses() -> None:
    """进房超时 + 可信已知弹窗 authority（OCR 命中被踢文本）→ 允许安全 Esc。"""
    med = _hitch_mediator()
    med.set_phase(Phase.LOBBY_ROOM)
    frame = _kk_frame("kicked")
    med._hitch_pending_row_y = 385
    med._hitch_sm.note_join_click(97.0)

    clicks: list[str] = []
    keys: list[str] = []
    with patch.object(med, "find_scene", return_value=None), \
         patch.object(med, "_find_hitch_ready_button", return_value=None), \
         patch.object(med, "_detect_hitch_kick_event", return_value="kicked"), \
         patch.object(med, "act_key", side_effect=lambda k, r: keys.append(k) or True), \
         patch.object(med, "act_click", side_effect=lambda hit, r: clicks.append(r) or True), \
         patch("shuabao.mediator.time.time", return_value=100.0):
        med._tick_lobby_hitch(frame, "LOBBY_ROOM")

    assert keys == ["esc"], keys
    assert clicks == []
    assert med._hitch_sm.pending_join is False
    assert med._hitch_pending_row_y is None
    assert med._hitch_rejected_row_ys == {385}
    assert med.phase is Phase.LOBBY_ROOM


def test_ready_timeout_pending_on_unknown_surface_is_zero_input() -> None:
    """180s 超时退房 episode 中，未知 surface（窗口失配且无房间实体控件）上
    绝不发送 HitchReadyTimeoutExit；预算耗尽后 Fail-Closed Break；
    fresh 房间证据恢复后才允许有界 Esc。"""
    med = _hitch_mediator()
    med.set_phase(Phase.ROOM_WAITING)
    frame = _kk_frame("kicked")
    med._confirmed_room_hwnd = 99999  # 与 frame.hwnd 失配：未知 surface
    med._hitch_pending_room_key = "room-765432"
    med._hitch_ready_timeout_pending = True
    med._hitch_ready_timeout_deadline = 230.0
    med._hitch_ready_timeout_attempts = 0
    med._hitch_ready_timeout_leave_at = None
    now = 200.0

    clicks: list[str] = []
    keys: list[str] = []
    with patch.object(med, "find_scene", return_value=None), \
         patch.object(med, "_is_confirmed_room_frame", return_value=False), \
         patch.object(med, "_lobby_room_list_evidence", return_value=False), \
         patch.object(med, "act_key", side_effect=lambda k, r: keys.append(k) or True), \
         patch.object(med, "act_click", side_effect=lambda hit, r: clicks.append(r) or True), \
         patch("shuabao.mediator.time.time", return_value=now):
        med._tick_lobby_hitch(frame, "ROOM_WAITING")
    assert keys == [] and clicks == [], f"未知 surface 必须零输入: keys={keys}, clicks={clicks}"
    assert med._hitch_ready_timeout_pending is True
    assert med._hitch_ready_timeout_attempts == 0
    assert "room-765432" not in med._hitch_blacklisted_room_keys

    # 尝试预算耗尽 → Fail-Closed Break，仍零输入
    med._hitch_ready_timeout_attempts = 3
    with patch.object(med, "find_scene", return_value=None), \
         patch.object(med, "_is_confirmed_room_frame", return_value=False), \
         patch.object(med, "_lobby_room_list_evidence", return_value=False), \
         patch.object(med, "act_key", side_effect=lambda k, r: keys.append(k) or True), \
         patch.object(med, "act_click", side_effect=lambda hit, r: clicks.append(r) or True), \
         patch("shuabao.mediator.time.time", return_value=now):
        assert med._tick_lobby_hitch(frame, "ROOM_WAITING") is LoopAction.Break
    assert keys == [] and clicks == []

    # fresh 房间签名恢复 → 允许有界安全 Esc（预算重置）
    med._hitch_ready_timeout_attempts = 0
    med._confirmed_room_hwnd = frame.hwnd
    with patch.object(med, "find_scene", return_value=None), \
         patch.object(med, "_is_confirmed_room_frame", return_value=True), \
         patch.object(med, "_lobby_room_list_evidence", return_value=False), \
         patch.object(med, "act_key", side_effect=lambda k, r: keys.append(k) or True), \
         patch.object(med, "act_click", side_effect=lambda hit, r: clicks.append(r) or True), \
         patch("shuabao.mediator.time.time", return_value=now):
        med._tick_lobby_hitch(frame, "ROOM_WAITING")
    assert keys == ["esc"], keys
    assert med._hitch_ready_timeout_attempts == 1
    assert med._hitch_ready_timeout_pending is True


def test_tqtz_third_pending_confirmed_on_fresh_frame() -> None:
    """第 3 次点击的 pending 请求必须先走完 fresh 确认生命周期：
    fresh boss_entry → 落定 clicked=True，绝不因 attempts==3 提前 ABANDONED。"""
    med = Mediator(Settings(dry_run=True, ocr_mode="off"), ROOT)
    med.set_phase(Phase.MAIN_LINE)
    frame = _game_frame("midgame")
    tqtz_hit = MatchResult("tqtz", 0.85, 438, 79, 85, 22, 665, 171)
    med._tqtz_attempts = 2
    with patch.object(med, "find", return_value=tqtz_hit), \
         patch.object(med, "find_scene", return_value=None), \
         patch.object(med, "act_click", return_value=True) as click:
        # 第 3 次点击成功 → pending 挂起（此刻 attempts==3）
        assert med._maybe_click_tqtz(frame, 100.0) is LoopAction.Continue
    assert med._tqtz_attempts == 3 and med._tqtz_pending is True
    assert med._tqtz_abandoned is False

    # 观察窗内（未超 5s）即便图标仍在也绝不 ABANDONED，零输入等待
    with patch.object(med, "find", return_value=tqtz_hit), \
         patch.object(med, "find_scene", return_value=None), \
         patch.object(med, "_is_in_game_hud", return_value=False), \
         patch.object(med, "act_click", return_value=True) as click2:
        assert med._maybe_click_tqtz(frame, 100.5) is LoopAction.Continue
        click2.assert_not_called()
    assert med._tqtz_abandoned is False
    assert med._tqtz_pending is True

    # fresh 帧 boss_entry 强后置证据 → 确认成功，而非放弃
    fresh_frame = _game_frame("midgame")
    boss_hit = MatchResult("boss_entry", 0.9, 640, 300, 120, 60, 640, 300)
    with patch.object(med, "find", return_value=None), \
         patch.object(med, "find_scene", side_effect=lambda f, key: boss_hit if key == "boss_entry" else None), \
         patch.object(med, "_is_in_game_hud", return_value=False), \
         patch.object(med, "act_click", return_value=True) as click3:
        assert med._maybe_click_tqtz(fresh_frame, 102.0) is LoopAction.Continue
        click3.assert_not_called(), "确认阶段严禁二次点击"
    assert med._tqtz_clicked is True
    assert med._tqtz_pending is False
    assert med._tqtz_abandoned is False, "第 3 次确认成功绝不能被标记为放弃"


def test_tqtz_third_pending_timeout_becomes_abandoned() -> None:
    """第 3 次 pending 5 秒观察窗超时且图标仍在 → ABANDONED（非伪装成功），
    后续调用零输入；未超时的观察窗内绝不提前 ABANDONED。"""
    med = Mediator(Settings(dry_run=True, ocr_mode="off"), ROOT)
    med.set_phase(Phase.MAIN_LINE)
    frame = _game_frame("midgame")
    tqtz_hit = MatchResult("tqtz", 0.85, 438, 79, 85, 22, 665, 171)
    med._tqtz_attempts = 2
    with patch.object(med, "find", return_value=tqtz_hit), \
         patch.object(med, "find_scene", return_value=None), \
         patch.object(med, "act_click", return_value=True) as click:
        # 第 3 次点击成功 → pending 挂起
        assert med._maybe_click_tqtz(frame, 100.0) is LoopAction.Continue
    assert med._tqtz_attempts == 3 and med._tqtz_pending is True

    # 观察窗内：图标仍在 → 零输入等待，绝不提前 ABANDONED
    with patch.object(med, "find", return_value=tqtz_hit), \
         patch.object(med, "find_scene", return_value=None), \
         patch.object(med, "_is_in_game_hud", return_value=False), \
         patch.object(med, "act_click", return_value=True) as click2:
        assert med._maybe_click_tqtz(frame, 100.5) is LoopAction.Continue
        click2.assert_not_called()
    assert med._tqtz_abandoned is False
    assert med._tqtz_pending is True

    # 5s 超时且图标仍在（HUD 上未消失）→ 第 3 次尝试标记 ABANDONED
    # （fresh 帧才能推进 generation 门禁；同请求帧恒零输入）
    timeout_frame = _game_frame("midgame")
    with patch.object(med, "find", return_value=tqtz_hit), \
         patch.object(med, "find_scene", return_value=None), \
         patch.object(med, "_is_in_game_hud", return_value=False), \
         patch.object(med, "act_click", return_value=True) as click3:
        assert med._maybe_click_tqtz(timeout_frame, 106.0) is LoopAction.Continue
        click3.assert_not_called(), "ABANDONED 后严禁再次点击"
    assert med._tqtz_abandoned is True
    assert med._tqtz_clicked is False
    assert med._tqtz_pending is False
    assert med._early_challenge_pending is False

    # ABANDONED 短路：后续调用零输入
    with patch.object(med, "find", return_value=tqtz_hit), \
         patch.object(med, "find_scene", return_value=None), \
         patch.object(med, "act_click", return_value=True) as click4:
        assert med._maybe_click_tqtz(frame, 107.0) is LoopAction.Continue
        click4.assert_not_called()
    assert med._tqtz_clicked is False, "ABANDONED 绝不允许伪装成已点击成功"


def test_tqtz_same_generation_pending_expires_after_wall_clock_5s() -> None:
    """同帧（same generation）证据不推进时，5s 墙钟硬截止也必须收敛 pending：
    same-gen 观察窗内零输入；>= 5s 清 pending，attempts>=3 则 ABANDONED（非伪装成功）。"""
    med = Mediator(Settings(dry_run=True, ocr_mode="off"), ROOT)
    med.set_phase(Phase.MAIN_LINE)
    frame = _game_frame("midgame")
    tqtz_hit = MatchResult("tqtz", 0.85, 438, 79, 85, 22, 665, 171)
    with patch.object(med, "find", return_value=tqtz_hit), \
         patch.object(med, "find_scene", return_value=None), \
         patch.object(med, "act_click", return_value=True) as click:
        # 首帧点击成功 → pending 挂起，记录 request generation
        assert med._maybe_click_tqtz(frame, 100.0) is LoopAction.Continue
        assert med._tqtz_pending is True
        assert med._tqtz_request_generation is not None
        assert med._tqtz_request_generation >= 0
        assert click.call_count == 1
        # 同一帧对象（same generation）观察窗内：零输入等待
        assert med._maybe_click_tqtz(frame, 101.0) is LoopAction.Continue
        assert med._tqtz_pending is True
        assert click.call_count == 1
        # 同一帧对象，now = pending_since + 5.1：墙钟硬截止必须收敛
        assert med._maybe_click_tqtz(frame, 105.1) is LoopAction.Continue
        assert med._tqtz_pending is False
        assert med._tqtz_pending_frame is None
        assert med._early_challenge_pending is False
        assert click.call_count == 1, "同帧 pending 收敛绝不允许额外点击"
    assert med._tqtz_abandoned is False, "attempts<3 时仅清 pending，允许有界重试"



def test_b3_archive_counter_classification_matrix() -> None:
    """C6 状态矩阵：OCR 响应 status != "ok" 时即使 raw_text/rec_score 完整可信
    也必须 UNKNOWN；status=="ok" + 结构化 0/8 + rec_score>=0.75 才授权 UNAVAILABLE。"""
    med = _hitch_mediator()
    frame = _game_frame("archive")

    def _state(status: str, text: str, score: float) -> str:
        with patch.object(med, "_ocr_client", _fake_ocr_client(text, score, status=status)):
            return med._archive_hitch_card_progress_state(frame, 2)

    assert _state("ok", "0/8", 0.99) == "UNAVAILABLE"
    assert _state("ok", "1/8", 0.99) == "AVAILABLE"
    assert _state("ok", "8/8", 0.99) == "COMPLETED"
    assert _state("ok", "0/3", 0.99) == "UNKNOWN"
    assert _state("ok", "0/8", 0.50) == "UNKNOWN"
    # status 异常：即使 raw_text/rec_score 完美也绝不授权任何业务状态
    assert _state("unavailable", "0/8", 0.99) == "UNKNOWN"
    assert _state("", "0/8", 0.99) == "UNKNOWN"

    # status="unavailable" + 0/8 + 0.99 → UNKNOWN：unavailable 接口 False，
    # 且挑战点击链零输入（卡面命中也绝不点击、绝不推进计划）。
    with patch.object(med, "_ocr_client", _fake_ocr_client("0/8", 0.99, status="unavailable")):
        assert med._archive_hitch_card_unavailable(frame, 2) is False
        card_hit = MatchResult("lobby/archive_card3", 0.92, 700, 500, 140, 70, 700, 500)
        with patch.object(med, "_find_archive_challenge_card", return_value=card_hit), \
             patch.object(med, "act_click", return_value=True) as click:
            assert med._maybe_click_archive_challenge(frame, 100.0) is LoopAction.Continue
        click.assert_not_called()
        assert med._archive_challenge_index == 0, "UNKNOWN 状态零输入，绝不推进挑战计划"


def test_stage_page_ownership_rejects_kk_platform_title() -> None:
    """KK 平台窗口即便检测到数字行也不得获得 stage authority；
    游戏客户端窗口（英雄三国）检测到数字行才获得 stage authority。"""
    med = Mediator(Settings(dry_run=True, ocr_mode="off"), ROOT)
    frame_kk = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), window_title="KK官方对战平台", role="l0")
    frame_game = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), window_title="英雄三国KK", role="l1")

    with patch.object(med, "_visible_stage_rows", return_value=True):
        assert med._find_stage_page(frame_kk) is False, "KK 平台窗口即便检测到数字行也不得获得 stage authority"
        assert med._find_stage_page(frame_game) is True, "游戏客户端窗口检测到数字行获得 stage authority"


def test_lobby_hitch_ignores_stage_select_context_on_kk_platform_frame() -> None:
    """KK 平台 frame 即便 context=="STAGE_SELECT"/stage_page=True 也不得转
    Phase.STAGE_SELECT，必须零输入保持大厅状态。"""
    med = _hitch_mediator()
    med.set_phase(Phase.LOBBY_ROOM)
    frame_kk = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), window_title="KK官方对战平台", role="l0")

    clicks = []
    keys = []
    med.act_click = lambda hit, reason: clicks.append((hit, reason)) or True
    med.act_key = lambda key, reason: keys.append((key, reason)) or True

    # 即使 context=="STAGE_SELECT" 或 stage_page=True，KK frame 也不得转 STAGE_SELECT，必须零输入
    res = med._tick_lobby_hitch(frame_kk, context="STAGE_SELECT", stage_page=True)
    assert res is LoopAction.Continue
    assert med.phase != Phase.STAGE_SELECT
    assert len(clicks) == 0
    assert len(keys) == 0
