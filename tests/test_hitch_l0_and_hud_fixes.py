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


def test_hitch_tangible_room_evidence_excludes_lobby_quick_join(monkeypatch):
    """验证：大厅房间列表 + Quick Join 蓝色按钮时，tangible_room 必须为 False。"""
    settings = Settings()
    med = Mediator(settings, Path(__file__).resolve().parents[1])
    rng = np.random.default_rng(777)
    frame = Frame(rng.integers(0, 256, size=(945, 1332, 3), dtype=np.uint8))

    # 模拟大厅可见
    monkeypatch.setattr(med, "_lobby_room_list_evidence", lambda f: True)
    # 模拟出现大厅底部的蓝色动作控件（例如 Quick Join / 创建房间）
    fake_hit = MatchResult(name="room_blue_action", score=0.9, x=900, y=850, w=100, h=40, screen_x=900, screen_y=850)
    monkeypatch.setattr(med, "_hitch_room_action_control", lambda f: (fake_hit, 40))
    # 房间专属正向模板不命中
    monkeypatch.setattr(med, "find_scene", lambda f, s, **k: None)
    monkeypatch.setattr(med, "find", lambda f, t, **k: None)

    # 低信息/通用蓝色几何不再拥有 ROOM control authority。
    assert med._hitch_room_controls_visible(frame) is False
    assert med._hitch_tangible_room_evidence(frame) is False
    assert med._lobby_room_list_evidence(frame) is True


def test_hitch_tangible_room_evidence_requires_real_room_surface():
    """随机帧上的 readyBtn 假命中不能授予 ROOM；真实 GT 另由 candidate contract 覆盖。"""
    settings = Settings()
    med = Mediator(settings, Path(__file__).resolve().parents[1])
    rng = np.random.default_rng(888)
    frame = Frame(rng.integers(0, 256, size=(945, 1332, 3), dtype=np.uint8))

    assert med._hitch_tangible_room_evidence(frame) is False


def test_hitch_floor_exit_pending_clears_on_lobby_with_quick_join(monkeypatch):
    """验证：floor_exit_pending 状态下，面对大厅（含 Quick Join 蓝色按钮），必须成功清除 pending 并推进。"""
    settings = Settings()
    settings.mode_id = "lobby_hitch"
    med = Mediator(settings, Path(__file__).resolve().parents[1])
    med.set_phase(Phase.ROOM_WAITING, "test_exit_pending")
    med._hitch_floor_exit_pending = True
    med._hitch_floor_exit_confirmed = True

    rng = np.random.default_rng(999)
    frame = Frame(rng.integers(0, 256, size=(945, 1332, 3), dtype=np.uint8))

    monkeypatch.setattr(med, "see", lambda *a, **k: frame)
    monkeypatch.setattr(med, "_lobby_room_list_evidence", lambda f: True)
    # 模拟大厅底部有蓝色控件
    fake_hit = MatchResult(name="room_blue_action", score=0.9, x=900, y=850, w=100, h=40, screen_x=900, screen_y=850)
    monkeypatch.setattr(med, "_hitch_room_action_control", lambda f: (fake_hit, 40))
    monkeypatch.setattr(med, "find_scene", lambda f, s, **k: None)
    monkeypatch.setattr(med, "find", lambda f, t, **k: None)

    # 运行一次 tick
    action = med.tick()
    # 必须清除 _hitch_floor_exit_pending，不再被死锁
    assert med._hitch_floor_exit_pending is False
    assert med.phase == Phase.LOBBY_ROOM



def test_hitch_single_kk_task_page_switches_to_room_list(monkeypatch):
    """验证回归 1：1 KK + 真实'任务'页 + Quick Join -> in_room=False，继续走切'房间列表'Tab。"""
    settings = Settings()
    settings.mode_id = "lobby_hitch"
    repo_root = Path(__file__).resolve().parents[1]
    med = Mediator(settings, repo_root)
    med.set_phase(Phase.LOBBY_ROOM, "test_task_page")
    med._capture_candidates = 1  # 拓扑硬门禁：仅 1 个 KK HWND

    import cv2
    task_frame_path = repo_root / "tests" / "fixtures" / "real_task_page_frame.png"
    if task_frame_path.exists():
        task_bgr = cv2.imdecode(np.fromfile(str(task_frame_path), dtype=np.uint8), cv2.IMREAD_COLOR)
    else:
        task_bgr = np.ones((945, 1332, 3), dtype=np.uint8) * 120
    frame = Frame(task_bgr, left=519, top=40)

    clicked_actions = []
    monkeypatch.setattr(med, "see", lambda *a, **k: frame)
    monkeypatch.setattr(med, "act_click", lambda hit, reason: clicked_actions.append(reason) or True)

    # 模拟真实大厅任务页：非房间列表，但能找到房间列表 Tab
    tab_hit = MatchResult(name="lobby_room_list_tab_slot", score=1.0, x=352, y=245, w=1, h=1, screen_x=871, screen_y=285)
    monkeypatch.setattr(med, "_find_hitch_room_list_tab", lambda f: tab_hit)
    monkeypatch.setattr(med, "_lobby_room_list_evidence", lambda f: False)

    action = med.tick()
    # 拓扑只有 1 个窗口，in_room 必须为 False，绝不能卡在房间一楼退出死锁，而是点击切换房间列表 Tab
    assert "HitchSelectTab" in clicked_actions


def test_case_a_lobby_plus_pet_window_not_room(monkeypatch):
    """Case A: 大厅 + 宠物/探险第二 KK 窗口, KK HWND 数 = 2 -> confirmed_room_hwnd=None, in_room=False"""
    settings = Settings()
    settings.mode_id = "lobby_hitch"
    repo_root = Path(__file__).resolve().parents[1]
    med = Mediator(settings, repo_root)

    import cv2
    lobby_bgr = cv2.imdecode(np.fromfile(str(repo_root / "tests/fixtures/real_task_page_frame.png"), dtype=np.uint8), cv2.IMREAD_COLOR)
    pet_bgr = cv2.imdecode(np.fromfile(str(repo_root / "tests/fixtures/real_pet_window_frame.png"), dtype=np.uint8), cv2.IMREAD_COLOR)

    lobby_frame = Frame(lobby_bgr, left=0, top=0, hwnd=1001)
    pet_frame = Frame(pet_bgr, left=100, top=100, hwnd=1002)

    from shuabao.vision.capture import WindowTarget
    t_lobby = WindowTarget(hwnd=1001, title="KK官方对战平台", left=0, top=0, width=1332, height=945)
    t_pet = WindowTarget(hwnd=1002, title="KK官方对战平台", left=100, top=100, width=600, height=818)

    monkeypatch.setattr("shuabao.mediator.find_window_targets", lambda *a, **k: [t_lobby, t_pet])
    monkeypatch.setattr("shuabao.mediator.capture_target", lambda t: lobby_frame if t.hwnd == 1001 else pet_frame)

    frame = med._capture_best("KK官方对战平台", role="l0")
    assert med._confirmed_room_hwnd is None

    confirmed_room_hwnd = getattr(med, "_confirmed_room_hwnd", None)
    in_room = bool(
        frame.hwnd is not None
        and confirmed_room_hwnd is not None
        and frame.hwnd == confirmed_room_hwnd
        and med._is_confirmed_room_frame(frame)
    )
    assert in_room is False


def test_case_b_lobby_plus_real_room_selects_room(monkeypatch):
    """Case B: 大厅 + 用户提供的真实房间窗口, KK HWND 数 = 2 -> 必须选择真实房间 HWND"""
    settings = Settings()
    settings.mode_id = "lobby_hitch"
    repo_root = Path(__file__).resolve().parents[1]
    med = Mediator(settings, repo_root)

    import cv2
    lobby_bgr = cv2.imdecode(np.fromfile(str(repo_root / "tests/fixtures/real_task_page_frame.png"), dtype=np.uint8), cv2.IMREAD_COLOR)
    room_bgr = cv2.imdecode(np.fromfile(str(repo_root / "tests/fixtures/real_room_window_frame.png"), dtype=np.uint8), cv2.IMREAD_COLOR)

    lobby_frame = Frame(lobby_bgr, left=0, top=0, hwnd=1001)
    room_frame = Frame(room_bgr, left=100, top=100, hwnd=1003)

    from shuabao.vision.capture import WindowTarget
    t_lobby = WindowTarget(hwnd=1001, title="KK官方对战平台", left=0, top=0, width=1332, height=945)
    t_room = WindowTarget(hwnd=1003, title="KK官方对战平台", left=100, top=100, width=1032, height=721)

    monkeypatch.setattr("shuabao.mediator.find_window_targets", lambda *a, **k: [t_lobby, t_room])
    monkeypatch.setattr("shuabao.mediator.capture_target", lambda t: lobby_frame if t.hwnd == 1001 else room_frame)

    med._hitch_sm.pending_join = True
    best_frame = med._capture_best("KK官方对战平台", role="l0")
    assert med._confirmed_room_hwnd == 1003
    assert best_frame.hwnd == 1003

    confirmed_room_hwnd = getattr(med, "_confirmed_room_hwnd", None)
    in_room = bool(
        best_frame.hwnd is not None
        and confirmed_room_hwnd is not None
        and best_frame.hwnd == confirmed_room_hwnd
        and med._is_confirmed_room_frame(best_frame)
    )
    assert in_room is True


def test_case_c_lobby_plus_pet_plus_room_selects_room(monkeypatch):
    """Case C: 大厅 + 宠物窗口 + 房间窗口, KK HWND 数 = 3 -> 必须忽略宠物 HWND，选择房间 HWND"""
    settings = Settings()
    settings.mode_id = "lobby_hitch"
    repo_root = Path(__file__).resolve().parents[1]
    med = Mediator(settings, repo_root)

    import cv2
    lobby_bgr = cv2.imdecode(np.fromfile(str(repo_root / "tests/fixtures/real_task_page_frame.png"), dtype=np.uint8), cv2.IMREAD_COLOR)
    pet_bgr = cv2.imdecode(np.fromfile(str(repo_root / "tests/fixtures/real_pet_window_frame.png"), dtype=np.uint8), cv2.IMREAD_COLOR)
    room_bgr = cv2.imdecode(np.fromfile(str(repo_root / "tests/fixtures/real_room_window_frame.png"), dtype=np.uint8), cv2.IMREAD_COLOR)

    lobby_frame = Frame(lobby_bgr, left=0, top=0, hwnd=1001)
    pet_frame = Frame(pet_bgr, left=100, top=100, hwnd=1002)
    room_frame = Frame(room_bgr, left=200, top=200, hwnd=1003)

    from shuabao.vision.capture import WindowTarget
    t_lobby = WindowTarget(hwnd=1001, title="KK官方对战平台", left=0, top=0, width=1332, height=945)
    t_pet = WindowTarget(hwnd=1002, title="KK官方对战平台", left=100, top=100, width=600, height=818)
    t_room = WindowTarget(hwnd=1003, title="KK官方对战平台", left=200, top=200, width=1032, height=721)

    monkeypatch.setattr("shuabao.mediator.find_window_targets", lambda *a, **k: [t_lobby, t_pet, t_room])
    def mock_capture(t):
        if t.hwnd == 1001:
            return lobby_frame
        elif t.hwnd == 1002:
            return pet_frame
        else:
            return room_frame
    monkeypatch.setattr("shuabao.mediator.capture_target", mock_capture)

    med._hitch_sm.pending_join = True
    best_frame = med._capture_best("KK官方对战平台", role="l0")
    assert med._confirmed_room_hwnd == 1003
    assert best_frame.hwnd == 1003


# ===========================================================================
# 蹭车统计（局数/胜负/难度）与 Boss 防呆滞防死锁验证
# ===========================================================================

def test_hitch_stats_tracking_and_formatting(monkeypatch):
    """验证蹭车局数、胜负、局内 HUD 关卡统计以及格式化输出。"""
    from shuabao.mediator import RoundOutcome
    from shuabao.vision.stage_selector import StageId

    settings = Settings(mode_id="lobby_hitch")
    root = Path(__file__).resolve().parents[1]
    med = Mediator(settings, root)
    med.set_phase(Phase.MAIN_LINE, "test")

    # 1. 初始状态为空
    assert med.format_hitch_stats_progress() == ""
    assert med.format_hitch_stats_summary() == ""
    assert med.format_hitch_stage_summary() == "无"

    # 2. 局内 HUD 的章节-关卡标签是 2-7，旁边独立的波次标签不参与统计。
    frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), hwnd=1001)
    med._hitch_pending_selected_stage = "1-1"
    monkeypatch.setattr("shuabao.mediator.detect_ingame_stage_label", lambda f, img: StageId(2, 7))
    med._tick_main_line(frame)
    assert med._hitch_stats_started == 1
    assert med._hitch_stats_current_stage == "2-7"
    assert med._hitch_stats_stages == {"2-7": 1}
    assert med.format_hitch_stats_progress() == "关卡2-7"
    med._record_hitch_challenge("金币(确认开启)")
    med._record_hitch_challenge("档案-strengthen(已点击)")

    # 局 1 取得胜利
    med._record_round_outcome(RoundOutcome.VICTORY, "victory test")
    assert med._hitch_stats_victories == 1
    assert med._hitch_stats_failures == 0
    assert med.format_hitch_stats_progress() == "胜1 败0 关卡2-7"
    assert med.format_hitch_stats_summary() == (
        "蹭车开局 1 把 / 完成 0 把 (胜 1 / 败 0) · 章节选择分布 2-7:1把 · "
        "本局关卡 2-7 · 本局挑战 金币(确认开启)、档案-strengthen(已点击) · "
        "门票约消耗 0 张 · 单刷完成 0 把"
    )

    # 3. 局 1 退出，进入 episode 重置
    med._hitch_after_exit(100.0)
    assert med._hitch_round_started_counted is False
    assert med._hitch_stats_stage_recorded_this_round is False
    assert med._hitch_stats_current_stage is None
    assert med._hitch_stats_current_challenges == []
    # 累计统计保留
    assert med._hitch_stats_started == 1
    assert med._hitch_stats_victories == 1
    med.game_count = 1

    # 4. 局 2 局内 HUD 读到 3-9，优先于选关页候选 3-4。
    med._hitch_pending_selected_stage = "3-4"
    monkeypatch.setattr("shuabao.mediator.detect_ingame_stage_label", lambda f, img: StageId(3, 9))
    med._tick_main_line(frame)
    assert med._hitch_stats_started == 2
    assert med._hitch_stats_current_stage == "3-9"
    assert med._hitch_stats_stages == {"2-7": 1, "3-9": 1}
    assert med.format_hitch_stage_summary() == "2-7:1把 3-9:1把"

    # 局 2 超时失败
    med._record_round_outcome(RoundOutcome.TIMEOUT, "timeout test")
    assert med._hitch_stats_victories == 1
    assert med._hitch_stats_failures == 1
    assert med.format_hitch_stats_summary() == (
        "蹭车开局 2 把 / 完成 1 把 (胜 1 / 败 1) · 章节选择分布 2-7:1把 3-9:1把 · "
        "本局关卡 3-9 · 本局挑战 无确认记录 · 门票约消耗 2 张 · 单刷完成 0 把"
    )
    med.game_count = 2
    med.settings.mode_id = "normal_farm"
    assert med.format_hitch_stats_summary().startswith("蹭车开局 2 把 / 完成 2 把")
    assert "门票约消耗 4 张" in med.format_hitch_stats_summary()
    assert med.format_hitch_stats_progress() == med.format_hitch_stats_summary()


def test_overlay_hud_stats_display(qapp):
    """验证 OverlayHud 在运行中与停止后正确渲染统计文案。"""
    hud = OverlayHud()

    # 运行中带进度统计
    hud.update_status(
        running=True,
        phase="MAIN_LINE",
        game_count=3,
        cycle_num=10,
        mode="lobby_hitch",
        stats_text="胜2 败0 章节2",
    )
    assert "胜2 败0 章节2" in hud.round_chip.text()
    assert "胜2 败0 章节2" in hud.detail_label.text()

    # 停止后带总战绩统计
    hud.update_status(
        running=False,
        game_count=10,
        cycle_num=10,
        mode="lobby_hitch",
        terminal_reason="cycle_num reached",
        stats_text="蹭车开局 10 把 / 完成 10 把 · 章节选择分布 1-1:1把 2-7:6把 3-9:2把",
    )
    assert "蹭车开局 10 把 / 完成 10 把 · 章节选择分布 1-1:1把 2-7:6把 3-9:2把" in hud.detail_label.text()


def test_boss_challenge_attempt_limit_deadlock_prevention(monkeypatch):
    """验证 Boss 挑战达到 3 次上限时返回 None 并推进到 archive 关闭路径，绝不死锁循环。"""
    settings = Settings(sgzx_boss="15莫格莱尼", ocr_mode="off")
    root = Path(__file__).resolve().parents[1]
    med = Mediator(settings, root)
    med.set_phase(Phase.MAIN_LINE, "test")
    med._boss_challenge_attempts = 3

    frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), hwnd=1001)
    monkeypatch.setattr(med, "_post_game_state", lambda f: "ARCHIVE_PANEL")

    # 达到 3 次必须返回 None，且设置 _time_cave_boss_done = True
    action = med._maybe_challenge_configured_boss(frame, 10.0)
    assert action is None
    assert med._time_cave_boss_done is True
    assert med._post_game_route == "archive"

    # 调用重置函数后所有计数清空
    med._reset_boss_challenge_round_state()
    assert med._boss_challenge_attempts == 0
    assert med._time_cave_boss_done is False
    assert med._time_cave_boss_search_attempts == 0
    assert med._boss_anomaly_retry_attempts == 0


def test_hitch_l0_sleep_backoff_and_modal_close(monkeypatch):
    """验证 L0 阶段递增沉睡退避、KK 最小化唤醒与平台弹窗优先关闭按钮机制。"""
    settings = Settings(mode_id="lobby_hitch", ocr_mode="off")
    root = Path(__file__).resolve().parents[1]
    med = Mediator(settings, root)

    # 1. 退避序列单调递增
    intervals = med._HITCH_L0_BACKOFF_INTERVALS
    assert len(intervals) >= 5
    assert all(intervals[i] <= intervals[i + 1] for i in range(len(intervals) - 1))
    assert intervals[0] == 30
    assert intervals[-1] == 1800

    # 2. _sleep_with_stop_check 支持受急停中断
    med._running = True
    assert med._sleep_with_stop_check(0.05, slice_s=0.01) is True
    med.stop_signal.trigger("test")
    assert med._sleep_with_stop_check(10.0, slice_s=0.01) is False
    med.stop_signal.reset()

    # 3. 弹窗有 shell.close 时优先点击 close
    from shuabao.mediator import PlatformModalShell

    close_btn = MatchResult("test_close", 1.0, 100, 100, 10, 10, 100, 100)
    shell = PlatformModalShell("main_overlay", close_btn)
    frame = Frame(np.zeros((364, 560, 3), dtype=np.uint8), hwnd=2001)

    clicked_reasons = []
    monkeypatch.setattr(med, "act_click", lambda hit, reason: clicked_reasons.append(reason) or True)
    monkeypatch.setattr(med, "act_key", lambda key, reason: clicked_reasons.append(reason) or True)

    med._tick_hitch_platform_modal(frame, shell, 100.0)
    assert clicked_reasons == ["HitchDismissPlatformModalClose"]
    assert med._hitch_platform_modal_last_action == "close"


