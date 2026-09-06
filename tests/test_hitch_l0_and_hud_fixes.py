import cv2
import numpy as np
import pytest

from shuabao.mediator import Mediator, Phase, LoopAction
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.shell.overlay_hud import OverlayHud
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication

@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])

def test_l0_phase_never_preempted_by_disconnect_or_fail(monkeypatch):
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    settings = Settings()
    settings.mode_id = "lobby_hitch"
    med = Mediator(settings, root)
    # 模拟大厅阶段
    med.set_phase(Phase.LOBBY_ROOM, "test")
    canvas = np.zeros((800, 1280, 3), dtype=np.uint8)
    frame = Frame(canvas, hwnd=12345, window_title="KK官方对战平台")
    # 通过 monkeypatch see 方法直接返回模拟帧
    monkeypatch.setattr(med, "see", lambda *a, **k: frame)
    action = med.tick()
    assert med.phase == Phase.LOBBY_ROOM, f"L0 阶段严禁被 DISCONNECT/FAIL 抢占！当前={med.phase}"
    assert getattr(med, "_failure_candidate_frames", 0) == 0


def test_overlay_hud_geometry_stability(qapp):
    """HUD 窗口在非游戏窗切换或微幅位移时防抖稳定，不弹动。"""
    hud = OverlayHud()
    r1 = QRect(100, 100, 1334, 947)
    hud._accept_rect(r1, is_game=False)
    p1 = hud._pinned_rect
    assert p1 == r1
    
    # 微小位移（<16px）
    r2 = QRect(105, 102, 1334, 947)
    hud._accept_rect(r2, is_game=False)
    # 保持 p1 不动
    assert hud._pinned_rect == r1
    
    # 较大位移
    r3 = QRect(200, 200, 1334, 947)
    hud._accept_rect(r3, is_game=False)
    assert hud._pinned_rect == r3
    hud.close()
