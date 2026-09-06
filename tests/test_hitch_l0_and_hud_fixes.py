# -*- coding: utf-8 -*-
"""P0 / P1 现场残留问题针对性验证套件：

1. P0: capture 候选明确排除 ToolTipSaveBits，主大厅优先，且合法业务子窗仍可探针遴选
2. P1: OverlayHud 跨 HWND 防跳动、同 HWND 位移跟随、切游戏窗口锁定
3. 强失败/断线抢占：仅真实局内阶段生效；pre-game/大厅/过渡阶段即使连续高分断线帧也严禁抢占
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
import numpy as np
import pytest
from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication

from shuabao.mediator import IN_GAME_FAILURE_PREEMPT_PHASES, Mediator, Phase
from shuabao.settings import Settings
from shuabao.shell.overlay_hud import OverlayHud
from shuabao.vision.capture import (
    Frame,
    WindowTarget,
    find_window_targets,
    is_transient_helper_window,
)
from shuabao.vision.matcher import MatchResult


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


# ===========================================================================
# P0: Tooltip 辅助 HWND 排除与 _capture_best 业务子窗测试
# ===========================================================================

def test_transient_helper_window_identification():
    """验证瞬态类名与 ToolTipSaveBits 均被识别为瞬态辅助窗。"""
    assert is_transient_helper_window("Qt5152QWindowToolTipSaveBits") is True
    assert is_transient_helper_window("QWindowToolTipSaveBits") is True
    assert is_transient_helper_window("tooltips_class32") is True
    assert is_transient_helper_window("SomeTooltipClass") is True
    assert is_transient_helper_window("Qt5152QWindowIcon") is False
    assert is_transient_helper_window("Warcraft III") is False


def test_find_window_targets_excludes_tooltip_save_bits(monkeypatch):
    """同时模拟 1334x947 正常主窗与 308x800 Qt5152QWindowToolTipSaveBits，后者必须在枚举层被彻底排除。"""
    import ctypes
    from ctypes import wintypes
    import shuabao.vision.capture as cap_mod

    class FakeUser32:
        def IsWindowVisible(self, hwnd):
            return 1
        def IsIconic(self, hwnd):
            return 0
        def GetWindowTextLengthW(self, hwnd):
            return len("KK官方对战平台")
        def GetWindowTextW(self, hwnd, buf, max_len):
            buf.value = "KK官方对战平台"
            return len("KK官方对战平台")
        def GetWindowRect(self, hwnd, rect_ref):
            rect = rect_ref._obj
            if hwnd == 10001:
                rect.left, rect.top, rect.right, rect.bottom = 199, 55, 199 + 1334, 55 + 947
            else:
                rect.left, rect.top, rect.right, rect.bottom = 744, 747, 744 + 308, 747 + 800
            return 1
        def EnumWindows(self, proc, lparam):
            proc(10001, lparam)
            proc(10002, lparam)
            return 1
        def GetForegroundWindow(self):
            return 10001
    monkeypatch.setattr(cap_mod, "_user32", FakeUser32())
    monkeypatch.setattr(cap_mod, "get_window_class_name", lambda h: "Qt5152QWindowToolTipSaveBits" if h == 10002 else "Qt5152QWindowIcon")
    monkeypatch.setattr(cap_mod, "get_window_process_info", lambda h: (5555, "Platform.exe"))
    monkeypatch.setattr(cap_mod, "get_client_rect_info", lambda h, l, t, w, hg: (l, t, w, hg))

    targets = cap_mod.find_window_targets("KK官方")
    hwnds = [t.hwnd for t in targets]
    assert 10001 in hwnds, "正常主窗 1334x947 必须入选"
    assert 10002 not in hwnds, "Qt5152QWindowToolTipSaveBits 辅助窗必须在枚举层被彻底排除！"
    assert len(targets) == 1
    assert targets[0].width == 1334 and targets[0].height == 947
def test_capture_best_selects_main_window_over_sub_without_probes(monkeypatch):
    """BOOT / 普通大厅无特定子窗探针时，_capture_best 必须稳定返回主大厅窗口，不选择小窗口。"""
    root = Path(__file__).resolve().parents[1]
    med = Mediator(Settings(), root)

    main_target = WindowTarget(
        hwnd=20001, title="KK官方对战平台", left=199, top=55, width=1334, height=947,
        pid=5555, exe="Platform.exe", class_name="Qt5152QWindowIcon"
    )
    sub_target = WindowTarget(
        hwnd=20002, title="KK官方对战平台", left=744, top=747, width=400, height=400,
        pid=5555, exe="Platform.exe", class_name="Qt5152QWindowIcon"
    )

    monkeypatch.setattr("shuabao.mediator.find_window_targets", lambda *a, **k: [main_target, sub_target])

    canvas_main = np.zeros((947, 1334, 3), dtype=np.uint8)
    canvas_sub = np.zeros((400, 400, 3), dtype=np.uint8)

    def _mock_capture_target(t):
        if t.hwnd == 20001:
            return Frame(canvas_main, hwnd=20001, window_title=t.title)
        return Frame(canvas_sub, hwnd=20002, window_title=t.title)

    monkeypatch.setattr("shuabao.mediator.capture_target", _mock_capture_target)
    # 无任何匹配场景
    monkeypatch.setattr(med, "_detect_context", lambda frame, role: "UNKNOWN")

    chosen = med._capture_best("KK官方", "l0")
    assert chosen.hwnd == 20001, "无子窗探针命中时，必须优先选主大厅窗口！"


def test_capture_best_selects_legitimate_child_window_when_probes_match(monkeypatch):
    """当存在合法的房间/建房/退出子窗口且语义探针命中时，_capture_best 仍可正确遴选子窗口。"""
    root = Path(__file__).resolve().parents[1]
    med = Mediator(Settings(), root)

    main_target = WindowTarget(
        hwnd=20001, title="KK官方对战平台", left=199, top=55, width=1334, height=947,
        pid=5555, exe="Platform.exe", class_name="Qt5152QWindowIcon"
    )
    child_room_target = WindowTarget(
        hwnd=20003, title="KK官方对战平台", left=300, top=200, width=900, height=600,
        pid=5555, exe="Platform.exe", class_name="Qt5152QWindowIcon"
    )

    monkeypatch.setattr("shuabao.mediator.find_window_targets", lambda *a, **k: [main_target, child_room_target])

    canvas_main = np.zeros((947, 1334, 3), dtype=np.uint8)
    canvas_child = np.zeros((600, 900, 3), dtype=np.uint8)

    def _mock_capture_target(t):
        if t.hwnd == 20001:
            return Frame(canvas_main, hwnd=20001, window_title=t.title)
        return Frame(canvas_child, hwnd=20003, window_title=t.title)

    monkeypatch.setattr("shuabao.mediator.capture_target", _mock_capture_target)
    # 子窗包含房间等待锚点
    def _detect_context(frame, role):
        if frame.hwnd == 20003:
            return "ROOM_WAITING"
        return "UNKNOWN"

    monkeypatch.setattr(med, "_detect_context", _detect_context)

    chosen = med._capture_best("KK官方", "l0")
    assert chosen.hwnd == 20003, "当子窗口命中业务场景锚点时，必须优先选中合法的业务子窗！"


# ===========================================================================
# P1: OverlayHud 按 HWND identity 稳定与防跳动测试
# ===========================================================================

def test_overlay_hud_cross_hwnd_stability(qapp):
    """验证云端要求的 5 项 HUD 锚定稳定性规则：
    1. hwnd=A 主大厅 (199,55,1334,947) -> HUD 锚定 A
    2. 下一帧 hwnd=B 错误子窗 (744,747,308,800) -> HUD 必须保持 A，不得跳到 B
    3. 后续仍为 hwnd=A 且真实窗口移动 -> 允许跟随
    4. 出现明确游戏 hwnd=C -> 允许切换到 C 并锁定
    """
    hud = OverlayHud()

    class FakeTarget:
        def __init__(self, hwnd, x, y, w, h, is_game=False, title="KK官方对战平台"):
            self.hwnd = hwnd
            self.rect = QRect(x, y, w, h)
            self.client_rect = self.rect
            self.left = x
            self.top = y
            self.width = w
            self.height = h
            self.window_title = "英雄三国" if is_game else title

    # 1. hwnd=A, (199, 55, 1334, 947)
    target_A = FakeTarget(1001, 199, 55, 1334, 947)
    hud.anchor_to_target(target_A)
    assert hud._anchor_hwnd == 1001
    rect_A = QRect(hud._pinned_rect)

    # 2. 下一帧 hwnd=B 错误子窗 (744, 747, 308, 800) -> 必须忽略 B，坐标保持 A
    target_B = FakeTarget(1002, 744, 747, 308, 800)
    hud.anchor_to_target(target_B)
    assert hud._anchor_hwnd == 1001, "遇不同非游戏 HWND 严禁切换锚点！"
    assert hud._pinned_rect == rect_A, "坐标必须保持为 A，绝不跳动到 B！"

    # 3. 后续仍为 hwnd=A 且发生真实位移（移动 50px）-> 允许跟随更新
    target_A_moved = FakeTarget(1001, 249, 105, 1334, 947)
    hud.anchor_to_target(target_A_moved)
    assert hud._anchor_hwnd == 1001
    assert hud._pinned_rect.x() == 249 and hud._pinned_rect.y() == 105, "同 HWND 真实移动必须跟随！"

    # 4. 出现明确游戏窗 hwnd=C -> 切换到 C 并锁定
    target_C_game = FakeTarget(2001, 100, 100, 1920, 1080, is_game=True)
    hud.anchor_to_target(target_C_game)
    assert hud._anchor_hwnd == 2001, "必须切换到游戏窗口 C！"
    assert hud._has_game_window is True, "必须标记锁定游戏窗口！"
    rect_C = QRect(hud._pinned_rect)

    # 5. 游戏窗口锁定后，哪怕再来其它平台窗口也不切换
    hud.anchor_to_target(target_A)
    assert hud._anchor_hwnd == 2001
    assert hud._pinned_rect == rect_C

    hud.close()


# ===========================================================================
# 局内强失败与全局断线抢占：正向与反向强力两帧回归测试
# ===========================================================================

@pytest.mark.parametrize("pre_game_phase", [
    Phase.BOOT,
    Phase.WAIT_EXIT,
    Phase.LOBBY_ROOM,
    Phase.PREPARE,
    Phase.PLATFORM_MAP,
    Phase.CREATE_ROOM,
    Phase.ROOM_WAITING,
    Phase.ROOM_STARTING,
    Phase.WAIT_UI,
    Phase.STAGE_SELECT,
    Phase.STAGE_STARTING,
    Phase.HERO_SETUP,
])
def test_pre_game_and_transition_phases_never_preempted_by_disconnect(pre_game_phase, monkeypatch):
    """pre-game、大厅和过渡阶段即使连续多帧出现高分 disconnect 假阳性，严禁抢占进入 RECOVER_FAILURE。"""
    root = Path(__file__).resolve().parents[1]
    med = Mediator(Settings(), root)
    med.set_phase(pre_game_phase, "init")

    # 制作真实健康帧（避免触发 FrameHealth 门禁）
    healthy_bgr = np.full((945, 1332, 3), 100, dtype=np.uint8)
    frame = Frame(healthy_bgr, hwnd=31985540, window_title="KK官方对战平台")
    monkeypatch.setattr(med, "see", lambda *a, **k: frame)
    fake_hit = MatchResult(name="retryConnect", score=0.95, x=500, y=400, w=33, h=20, screen_x=500, screen_y=400)
    monkeypatch.setattr(med, "find_scene", lambda f, s: fake_hit if s == "disconnect" else None)

    # 连续跑 3 帧
    for _ in range(3):
        med.tick()

    assert med.phase == pre_game_phase, f"阶段 {pre_game_phase.name} 严禁被 DISCONNECT 抢占！实际={med.phase.name}"
    assert med.phase != Phase.RECOVER_FAILURE
    assert getattr(med, "_failure_candidate_frames", 0) == 0


def test_main_line_in_game_preempts_to_recover_failure_on_two_consecutive_hits(monkeypatch):
    """正向测试：真实局内阶段 MAIN_LINE 连续两帧出现真实/模拟 disconnect hit，必须按时进入 RECOVER_FAILURE。"""
    root = Path(__file__).resolve().parents[1]
    settings = Settings()
    med = Mediator(settings, root)
    med.set_phase(Phase.MAIN_LINE, "in_game_test")

    rng = np.random.default_rng(2026)
    healthy_bgr = rng.integers(0, 256, size=(945, 1332, 3), dtype=np.uint8)
    frame = Frame(healthy_bgr, hwnd=40001, window_title="英雄三国")
    monkeypatch.setattr(med, "see", lambda *a, **k: frame)
    fake_hit = MatchResult(name="gameDisconnect", score=0.92, x=500, y=400, w=193, h=37, screen_x=500, screen_y=400)
    monkeypatch.setattr(med, "find_scene", lambda f, s: fake_hit if s == "disconnect" else None)
    # 第 1 帧：候选计数=1，零动作，不转 RECOVER_FAILURE
    med.tick()
    assert med.phase == Phase.MAIN_LINE
    assert getattr(med, "_failure_candidate_frames", 0) == 1
    assert getattr(med, "_failure_candidate_kind", None) == "DISCONNECT"

    # 第 2 帧：连续两帧确认，抢占进入 RECOVER_FAILURE
    med.tick()
    assert med.phase == Phase.RECOVER_FAILURE, "MAIN_LINE 连续两帧确认后必须进入 RECOVER_FAILURE！"
