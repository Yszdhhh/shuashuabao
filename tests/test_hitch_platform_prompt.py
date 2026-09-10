# -*- coding: utf-8 -*-
"""被踢「平台提示」与大厅无进展看门狗的真实帧回归。

实机 2026-09-10 19:31：被房主移出后 KK 主窗口弹出「平台提示 / 立即购买 / 取消」，
旧 lobby_popup_dialog 模板（裁进了房间列表背景）不命中、整框 OCR 只读出「2」，
production 零输入 73s，Esc 连按 3 次也关不掉，最后人工处理。
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from shuabao.mediator import LoopAction, Mediator, Phase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"


def _load(name: str) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(str(FIXTURES / name), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None, name
    return image


def _med() -> Mediator:
    return Mediator(Settings(dry_run=True, ocr_mode="off", mode_id="lobby_hitch"), ROOT)


def _kicked_frame() -> Frame:
    return Frame(_load("real_kk_platform_prompt_kicked.jpg"), window_title="KK官方对战平台", hwnd=1253046, role="l0")


def test_real_kicked_prompt_clicks_cancel_and_returns_to_lobby() -> None:
    med = _med()
    med.set_phase(Phase.ROOM_WAITING)
    med._hitch_pending_room_key = "829849"
    with patch.object(med, "act_click", return_value=True) as click, \
         patch.object(med, "act_key", return_value=True) as key:
        result = med._tick_lobby_hitch(_kicked_frame(), "UNKNOWN")

    assert result is LoopAction.Continue
    click.assert_called_once()
    hit, reason = click.call_args.args
    assert reason == "HitchDismissPlatformPrompt"
    # 取消按钮在弹窗右下（x 673..841, y 513..557），绝不是左边蓝色「立即购买」。
    assert 673 <= hit.x + hit.w // 2 <= 841 and 513 <= hit.y + hit.h // 2 <= 557
    key.assert_not_called()
    # 3A: Cancel 发起后等待消失确认，不立刻 reset 大厅
    assert med.phase is Phase.ROOM_WAITING
    # 后续 fresh 帧证明弹窗已消失 -> reset 大厅并拉黑该房
    result2 = med._tick_lobby_hitch(_unknown_l0_frame(), "UNKNOWN")
    assert med.phase is Phase.LOBBY_ROOM
    assert "829849" in med._hitch_blacklisted_room_keys


def test_rejected_cancel_click_does_not_fall_back_to_esc() -> None:
    med = _med()
    med.set_phase(Phase.ROOM_WAITING)
    with patch.object(med, "act_click", return_value=False), \
         patch.object(med, "act_key", return_value=True) as key:
        med._tick_lobby_hitch(_kicked_frame(), "UNKNOWN")
    key.assert_not_called()
    assert med.phase is Phase.ROOM_WAITING


def test_exit_confirm_child_window_cancel_is_never_clicked() -> None:
    """退出确认也是「平台提示/取消」，但它是 440x260 子窗口；点取消会中断离房。"""
    med = _med()
    med.set_phase(Phase.ROOM_WAITING)
    frame = Frame(_load("real_kk_exit_confirm_child.png"), window_title="KK官方对战平台", hwnd=15278574, role="l0")
    assert med._find_hitch_platform_prompt_cancel(frame) is not None  # 模板本身能认出
    assert med._tick_hitch_platform_prompt(frame, 100.0) is None


def test_platform_prompt_not_detected_on_plain_lobby() -> None:
    med = _med()
    frame = Frame(_load("real_leaderboard_frame.png"), window_title="KK官方对战平台", hwnd=1, role="l0")
    assert med._find_hitch_platform_prompt_cancel(frame) is None


def _unknown_l0_frame() -> Frame:
    return Frame(np.full((945, 1332, 3), 30, dtype=np.uint8), window_title="KK官方对战平台", hwnd=1253046, role="l0")


def test_stall_watchdog_escapes_after_30s_of_unknown_without_input() -> None:
    med = _med()
    med.set_phase(Phase.ROOM_WAITING)
    frame = _unknown_l0_frame()
    with patch.object(med, "act_key", return_value=True) as key:
        assert med._tick_hitch_stall_watchdog(frame, "UNKNOWN", 1000.0) is None
        assert med._tick_hitch_stall_watchdog(frame, "UNKNOWN", 1029.0) is None
        assert med._tick_hitch_stall_watchdog(frame, "UNKNOWN", 1030.5) is LoopAction.Continue
    key.assert_called_once_with("esc", "HitchStallWatchdogEsc")


def test_stall_watchdog_counts_from_last_input_and_resets_on_known_context() -> None:
    med = _med()
    med.set_phase(Phase.LOBBY_ROOM)
    frame = _unknown_l0_frame()
    with patch.object(med, "act_key", return_value=True) as key:
        med._tick_hitch_stall_watchdog(frame, "UNKNOWN", 1000.0)
        med._last_input_at = 1020.0  # 刷新/搜房等正常输入
        assert med._tick_hitch_stall_watchdog(frame, "UNKNOWN", 1045.0) is None
        med._tick_hitch_stall_watchdog(frame, "LOBBY_ROOM", 1046.0)
        assert med._hitch_unknown_since is None
        assert med._tick_hitch_stall_watchdog(frame, "UNKNOWN", 1047.0) is None
    key.assert_not_called()


def test_stall_watchdog_never_escapes_inside_room_window() -> None:
    """开局倒计时盖住房间按钮时 context 也是 UNKNOWN；房间里 Esc 等于离房。"""
    med = _med()
    med.set_phase(Phase.ROOM_WAITING)
    room = Frame(_load("real_kk_room_window.png"), window_title="KK官方对战平台", hwnd=7152024, role="l0")
    overlay = Frame(_load("real_kk_room_anticheat_overlay.png"), window_title="KK官方对战平台", hwnd=7152024, role="l0")
    with patch.object(med, "act_key", return_value=True) as key:
        med._tick_hitch_stall_watchdog(room, "ROOM_WAITING", 990.0)  # 真实准备/退出按钮 → 记住房间窗口
        med._tick_hitch_stall_watchdog(overlay, "UNKNOWN", 1000.0)
        assert med._tick_hitch_stall_watchdog(overlay, "UNKNOWN", 1100.0) is None
    key.assert_not_called()


def test_kicked_prompt_is_not_a_room_at_live_ui_scale() -> None:
    """旧 room signature（空白暗块模板）在实机缩放 0.833 下把被踢提示判成房间，
    压住了弹窗 Esc、零输入 73s。G0 多信号 ROOM 契约必须判为非房间。"""
    med = _med()
    med.set_phase(Phase.ROOM_WAITING)
    med._ui_scale = 0.833
    frame = _kicked_frame()
    assert med._is_confirmed_room_frame(frame) is False
    assert med._kk_platform_modal_shell(frame) is not None
    assert med._find_hitch_platform_prompt_cancel(frame) is not None
    # 3D: 存在 platform prompt / modal shell 时看门狗不越权发 Esc，让位给专用提示/模态 owner
    with patch.object(med, "act_key", return_value=True) as key:
        med._tick_hitch_stall_watchdog(frame, "UNKNOWN", 1000.0)
        assert med._tick_hitch_stall_watchdog(frame, "UNKNOWN", 1031.0) is None
    key.assert_not_called()


def test_kicked_prompt_cancel_clicked_at_live_ui_scale() -> None:
    med = _med()
    med.set_phase(Phase.ROOM_WAITING)
    med._ui_scale = 0.833
    with patch.object(med, "act_click", return_value=True) as click, \
         patch.object(med, "act_key", return_value=True):
        med._tick_lobby_hitch(_kicked_frame(), "UNKNOWN")
    assert click.call_args.args[1] == "HitchDismissPlatformPrompt"
    assert med.phase is Phase.ROOM_WAITING
    # 后续 fresh 帧证明弹窗已消失 -> reset 大厅
    med._tick_lobby_hitch(_unknown_l0_frame(), "UNKNOWN")
    assert med.phase is Phase.LOBBY_ROOM


def test_stall_watchdog_waits_60s_on_game_window_for_loading() -> None:
    med = _med()
    med.set_phase(Phase.ROOM_WAITING)
    game = Frame(np.full((900, 1600, 3), 30, dtype=np.uint8), window_title="英雄三国KK", hwnd=7348632, role="l1")
    with patch.object(med, "_is_game_client_frame", return_value=True), \
         patch.object(med, "act_key", return_value=True) as key:
        med._tick_hitch_stall_watchdog(game, "UNKNOWN", 1000.0)
        assert med._tick_hitch_stall_watchdog(game, "UNKNOWN", 1045.0) is None
        assert med._tick_hitch_stall_watchdog(game, "UNKNOWN", 1061.0) is LoopAction.Continue
    key.assert_called_once_with("esc", "HitchStallWatchdogEsc")
