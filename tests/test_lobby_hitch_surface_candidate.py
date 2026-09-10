# -*- coding: utf-8 -*-
"""本地 Lobby Hitch candidate 的真实截图 recognition contract。

这些测试直接调用 production detector，使用仓库中的真实截图；不替换
``find``/``find_scene``，也不构造 fabricated MatchResult。
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from shuabao.mediator import Mediator
from shuabao.settings import Settings
from shuabao.vision.capture import Frame, WindowTarget


ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None, path
    return image


def _frame(path: Path, hwnd: int = 91001) -> Frame:
    return Frame(
        _load(path),
        window_title="KK官方对战平台",
        hwnd=hwnd,
        role="l0",
    )


def _med() -> Mediator:
    return Mediator(Settings(dry_run=True, ocr_mode="off", mode_id="lobby_hitch"), ROOT)


ROOM_LIST_FIXTURES = [
    ROOT / "fixtures" / "lobby_hitch_20260814" / "list_search3_joinable_t038.png",
    ROOT / "fixtures" / "lobby_hitch_search_20260907" / "search_results4_t040.png",
    ROOT / "fixtures" / "lobby_hitch_20260814" / "list_empty_search_t000.png",
    ROOT / "tests" / "fixtures" / "gt_kk_platform_modal_normal_lobby.png",
    ROOT / "fixtures" / "lobby_hitch_detail_20260814" / "t0002.00.png",
]


def test_real_room_list_surfaces_are_not_room_authority() -> None:
    med = _med()
    for path in ROOM_LIST_FIXTURES:
        frame = _frame(path)
        assert med._lobby_room_list_evidence(frame) is True, path.name
        assert med._is_confirmed_room_frame(frame) is False, path.name


def test_real_room_surfaces_and_ready_contract() -> None:
    med = _med()
    cases = [
        (
            ROOT / "tests" / "fixtures" / "real_room_window_frame.png",
            {"start"},
        ),
        (
            ROOT / "fixtures" / "lobby_hitch_20260814" / "kk_room_ready_btn_t040.png",
            {"ready"},
        ),
        (
            ROOT / "fixtures" / "lobby_hitch_20260814" / "kk_room_cancel_ready_t041.png",
            {"cancel_ready"},
        ),
    ]
    for path, expected_states in cases:
        frame = _frame(path, hwnd=91002)
        assert med._is_confirmed_room_frame(frame) is True, path.name
        state, hit = med._hitch_room_ready_contract(frame)
        assert state in expected_states, (path.name, state)
        if state == "ready":
            assert hit is not None
        else:
            assert hit is None
        assert med._hitch_room_seat_decision(frame) == "unknown"


def test_real_platform_modal_shell_owns_all_modal_variants_only() -> None:
    med = _med()
    modal_paths = [
        ROOT / "tests" / "fixtures" / "gt_kk_platform_modal_level_insufficient_overlay.png",
        ROOT / "fixtures" / "lobby_hitch_20260814" / "popup_password.png",
        ROOT / "tests" / "fixtures" / "gt_kk_platform_modal_kicked_child.png",
        ROOT / "tests" / "fixtures" / "real_kicked_modal_frame.jpg",
        ROOT / "fixtures" / "lobby_hitch_detail_20260814" / "t0046.00.png",
    ]
    for path in modal_paths:
        frame = _frame(path, hwnd=91003)
        assert med._kk_platform_modal_shell(frame) is not None, path.name
        assert med._is_confirmed_room_frame(frame) is False, path.name
        assert med._lobby_room_list_evidence(frame) is False, path.name


def test_real_normal_lobby_has_no_platform_modal_shell() -> None:
    med = _med()
    frame = _frame(ROOT / "tests" / "fixtures" / "gt_kk_platform_modal_normal_lobby.png")
    assert med._kk_platform_modal_shell(frame) is None
    assert med._is_confirmed_room_frame(frame) is False


def test_single_kk_window_binds_current_hwnd_after_real_room_evidence(monkeypatch) -> None:
    """单窗口/全屏 KK 也必须把真实 ROOM 证据绑定到当前 HWND。"""
    med = _med()
    path = ROOT / "tests" / "fixtures" / "real_room_window_frame.png"
    frame = _frame(path, hwnd=91004)
    target = WindowTarget(
        hwnd=91004,
        title="KK官方对战平台",
        left=0,
        top=0,
        width=frame.width,
        height=frame.height,
    )
    monkeypatch.setattr("shuabao.mediator.find_window_targets", lambda *args, **kwargs: [target])
    monkeypatch.setattr("shuabao.mediator.capture_target", lambda _target: frame)

    selected = med._capture_best("KK官方对战平台", "l0")

    assert selected.hwnd == 91004
    assert med._confirmed_room_hwnd == 91004
