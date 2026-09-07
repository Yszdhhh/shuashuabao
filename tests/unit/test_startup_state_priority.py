from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from shuabao.mediator import LoopAction, Mediator, PanelState, Phase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult

ROOT = Path(__file__).resolve().parents[2]


def _frame(title="英雄三国KK"):
    return Frame(np.zeros((900, 1600, 3), dtype=np.uint8), left=185, top=81, hwnd=1184474, window_title=title)


def test_paused_overlay_clicks_continue_button_before_any_game_action():
    med = Mediator(Settings(), ROOT)
    frame = _frame()
    continue_hit = MatchResult("pause_continue_game", .98, 700, 400, 200, 50, 885, 481)
    with patch.object(med, "_post_game_state", return_value="PAUSED"), \
         patch.object(med, "find", return_value=continue_hit), \
         patch.object(med, "act_click", return_value=True) as click:
        assert med._tick_main_line(frame) is LoopAction.Continue
    assert click.call_args.args[1] == "ResumePausedGame"

def test_simple_pause_without_verified_template_is_zero_input():
    """v012653 复盘：旧固定坐标 fallback 点在按钮下方狂点；模板缺失必须零输入。"""
    med = Mediator(Settings(), ROOT)
    frame = _frame()
    with patch.object(med, "find", return_value=None), \
         patch.object(med, "act_click", return_value=True) as click:
        assert med._maybe_resume_paused(frame, 1.0) is LoopAction.Continue
    assert click.call_count == 0


def test_pause_resume_retries_are_bounded_and_fail_closed():
    med = Mediator(Settings(), ROOT)
    frame = _frame()
    continue_hit = MatchResult("pause_continue_game", .98, 700, 400, 200, 50, 980, 480)
    with patch.object(med, "find", return_value=continue_hit), \
         patch.object(med, "act_click", return_value=True) as click:
        for i in range(7):
            action = med._maybe_resume_paused(frame, float(i))
            if i < 5:
                assert action is LoopAction.Continue
            else:
                assert action is LoopAction.Break
                assert med.phase is Phase.ERROR
    assert click.call_count == 5


def test_pause_resume_confirmed_when_pause_anchor_disappears():
    med = Mediator(Settings(), ROOT)
    frame = _frame()
    continue_hit = MatchResult("pause_continue_game", .98, 700, 400, 200, 50, 980, 480)
    with patch.object(med, "find", return_value=continue_hit), \
         patch.object(med, "act_click", return_value=True):
        med._maybe_resume_paused(frame, 1.0)
    assert med._pause_resume_attempts == 1
    with patch.object(med, "_post_game_state", return_value=None), \
         patch.object(med, "find", return_value=None), \
         patch.object(med, "act_click", return_value=True):
        med._tick_main_line(frame)
    assert med._pause_resume_attempts == 0


def test_pause_continue_template_matches_real_incident_frame():
    """实机证据（20260823_012653.mp4 10s 帧）：继续游戏按钮中心约 (980,480)。"""
    import cv2

    fixture = ROOT / "v012653_10s.png"
    if not fixture.exists():
        pytest.skip("实机暂停帧夹具未随仓库提供；需补齐后才执行模板回归")
    raw = np.fromfile(str(fixture), dtype=np.uint8)
    img = cv2.imdecode(raw, cv2.IMREAD_COLOR)  # 中文路径需 imdecode
    assert img is not None, "实机暂停帧夹具缺失"
    frame = Frame(img, left=0, top=0, window_title="英雄三国KK")
    med = Mediator(Settings(), ROOT)
    hit = med.find(
        frame,
        ["pause_continue_game"],
        threshold=0.80,
        roi=(0.35, 0.20, 0.65, 0.65),
    )
    assert hit is not None and hit.score >= 0.80
    cx, cy = hit.center
    assert 940 <= cx <= 1020, f"center x={cx}"
    assert 450 <= cy <= 510, f"center y={cy}"


def test_boot_prefers_game_window_over_visible_platform_room():
    """用户规则：英雄三国进程存在 = 一定走游戏内流程，优先于 KK 房间窗。"""
    med = Mediator(Settings(), ROOT)
    med.set_phase(Phase.BOOT)
    room = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), left=0, top=0, hwnd=111, window_title="KK对战平台")
    game = Frame(
        np.random.default_rng(2).integers(0, 255, (900, 1600, 3), dtype=np.uint8),
        left=10, top=10, hwnd=222, window_title="英雄三国KK",
    )

    def fake_capture(title, role):
        return game if role == "l1" else room

    with patch.object(med, "_capture_best", side_effect=fake_capture), \
         patch.object(med, "_frame_signal", side_effect=lambda f, r: 100 if f is room else 0):
        frame = med.see("test")
    assert frame.window_title == "英雄三国KK"
    assert frame.hwnd == 222


def test_boot_binds_minimized_game_window_and_never_activates_platform():
    """20260827 实机复盘：游戏窗最小化时 l1 探测返回无效帧，旧实现静默落到
    平台流并误建房。标题路由必须仍然绑定游戏窗（fail-closed 零输入），
    且绝不激活/置前 KK 平台窗。"""
    med = Mediator(Settings(), ROOT)
    med.set_phase(Phase.BOOT)
    platform = Frame(
        np.zeros((900, 1600, 3), dtype=np.uint8),
        left=0, top=0, hwnd=111, window_title="KK官方对战平台",
    )
    minimized_game = Frame(
        np.zeros((0, 0, 3), dtype=np.uint8),
        left=0, top=0, hwnd=222, window_title="英雄三国KK", is_valid=False,
        error="Window is minimized",
    )

    def fake_capture(title, role):
        return minimized_game if role == "l1" else platform

    with patch.object(med, "_capture_best", side_effect=fake_capture), \
         patch("shuabao.mediator.activate_window", return_value=False) as act:
        frame = med.see("test")
    assert frame is minimized_game
    assert med._last_capture_role == "l1"
    # 平台窗（hwnd=111）绝不能被激活/置前
    assert all(call.args and call.args[0] != 111 for call in act.call_args_list)


def test_see_never_activates_a_valid_platform_frame():
    """感知可后台抓帧；不能因每轮 see() 把 KK 平台抢到游戏前面。"""
    med = Mediator(Settings(), ROOT)
    med.set_phase(Phase.ROOM_WAITING)
    platform = Frame(
        np.zeros((900, 1600, 3), dtype=np.uint8),
        left=0, top=0, hwnd=111, window_title="KK官方对战平台",
    )
    with patch.object(med, "_capture_best", return_value=platform), \
         patch.object(med, "_frame_signal", return_value=100), \
         patch("shuabao.mediator.activate_window", return_value=True) as activate:
        assert med.see("test") is platform
    activate.assert_not_called()


def test_see_zero_side_effect_on_minimized_target_window():
    """P0-2（20260908）：观察期零前台副作用——无效/最小化帧只标记
    is_minimized，绝不 activate/restore；焦点严格限定在真实输入动作前。"""
    med = Mediator(Settings(), ROOT)
    med.set_phase(Phase.BOOT)
    minimized = Frame(
        np.zeros((0, 0, 3), dtype=np.uint8),
        left=0, top=0, hwnd=333, window_title="KK对战平台", is_valid=False,
        error="Window is minimized",
    )
    with patch.object(med, "_capture_best", return_value=minimized), \
         patch.object(med, "_frame_signal", return_value=0), \
         patch("shuabao.vision.capture.is_window_minimized", return_value=True), \
         patch("shuabao.mediator.activate_window", return_value=True) as restore:
        frame = med.see("test")
    assert frame.is_minimized is True
    restore.assert_not_called()


def test_full_boot_tick_takes_over_paused_game_window():
    """规则④全链路：启动时游戏窗已暂停 → BOOT 接管 → MAIN_LINE → 仅允许恢复。"""
    med = Mediator(Settings(dry_run=True), ROOT)
    assert med.phase is Phase.BOOT
    game = Frame(
        np.random.default_rng(3).integers(0, 255, (900, 1600, 3), dtype=np.uint8),
        left=0, top=0, hwnd=222, window_title="英雄三国KK",
    )
    with patch.object(med, "_capture_best", return_value=game), \
         patch.object(med, "_frame_signal", return_value=0), \
         patch.object(med, "_post_game_state", return_value="PAUSED"), \
         patch.object(med, "_find_stage_page", return_value=False), \
         patch.object(med, "_find_room_start", return_value=None):
        action = med._tick_impl()
    assert action is LoopAction.Continue
    assert med.phase is Phase.MAIN_LINE


def test_startup_with_existing_game_window_enters_main_line_without_create_room():
    med = Mediator(Settings(), ROOT)
    med.set_phase(Phase.PREPARE)
    noisy = np.random.default_rng(1).integers(0, 255, (900, 1600, 3), dtype=np.uint8)
    frame = Frame(noisy, left=185, top=81, hwnd=1184474, window_title="英雄三国KK")
    with patch.object(med, "_find_stage_page", return_value=False), \
         patch.object(med, "_find_room_start", return_value=None), \
         patch.object(med, "_find_create_confirm", return_value=None), \
         patch.object(med, "_find_map_create_room", return_value=None):
        state = med._startup_state(frame)
    assert state == "IN_GAME"


def test_stage_page_handoff_precedes_auto_task_gate():
    """实机 20260828：选关页不能被局内自动任务门禁困在 MAIN_LINE。"""
    med = Mediator(Settings(), ROOT)
    med.set_phase(Phase.MAIN_LINE)
    frame = _frame()
    with patch.object(med, "_find_failure_gift", return_value=None), \
         patch.object(med, "_post_game_state", return_value=None), \
         patch.object(med, "_round_tail_checks_active", return_value=False), \
         patch.object(med, "_find_stage_page", return_value=True), \
         patch.object(med, "_is_in_game_hud", return_value=False), \
         patch.object(med, "_ensure_auto_task_enabled", return_value=None) as auto_task:
        assert med._tick_main_line(frame) is LoopAction.Continue
    assert med.phase is Phase.STAGE_SELECT
    auto_task.assert_not_called()


def test_tqtz_is_one_shot_and_blocks_regular_choice_until_confirmed():
    """B1 契约：点击成功只挂起 pending（点击≠已接受），确认前零-input 等待
    fresh 帧确认，绝不二次点击。"""
    med = Mediator(Settings(), ROOT)
    frame = _frame()
    tqtz_hit = MatchResult("tqtz", .85, 438, 79, 85, 22, 665, 171)
    with patch.object(med, "find", return_value=tqtz_hit), \
         patch.object(med, "find_scene", return_value=None), \
         patch.object(med, "act_click", return_value=True) as click:
        assert med._maybe_click_tqtz(frame, 100.0) is LoopAction.Continue
        # pending 观察窗：fresh 帧图标仍在 → 零输入等待，不落定成功
        assert med._maybe_click_tqtz(frame, 102.0) is LoopAction.Continue
    assert click.call_count == 1
    assert getattr(med, "_tqtz_pending", False) is True
    assert getattr(med, "_tqtz_clicked", False) is False

def test_tqtz_transition_waits_for_boss_entry_before_regular_cycle():
    med = Mediator(Settings(cjb_boss="04大范"), ROOT)
    frame = _frame()
    med._early_challenge_pending = True
    boss_hit = MatchResult("04大范", .95, 700, 300, 100, 100, 885, 381)
    with patch.object(med, "find_scene", return_value=True), \
         patch.object(med, "find", return_value=boss_hit), \
         patch.object(med, "act_click", return_value=True) as click:
        assert med._tick_early_challenge(frame, 10.0) is LoopAction.Continue
    assert click.call_args.args[1] == "BossConfigured"
    assert med._early_challenge_clicked_at == 10.0


def test_runtime_bond_duplicate_is_retained_for_merge_priority():
    from shuabao.runtime_mediator import Mediator as RuntimeMediator
    med = RuntimeMediator(Settings(cards=["力量"]), ROOT)
    med._bond_cards_owned.clear()
    med._stage_bond_card("力量")
    med._commit_pending_bond_cards()
    med._stage_bond_card("力量")
    med._commit_pending_bond_cards()
    assert med._bond_cards_owned == ["力量", "力量"]
