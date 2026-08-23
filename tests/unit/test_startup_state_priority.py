import time
from pathlib import Path
from unittest.mock import patch

import numpy as np
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
        for i in range(6):
            action = med._maybe_resume_paused(frame, float(i * 6))
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

    raw = np.fromfile(str(ROOT / "v012653_10s.png"), dtype=np.uint8)
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


# 20260823 复审：v012653_80s 帧是真实暂停页，但 pauseGame 主锚点仅 0.77
# （低于 0.80 阈值），必须由恢复按钮第二锚点兜住，否则暂停页静默漏检。
REAL_PAUSE_FRAMES = (
    "v012653_0s.png", "v012653_5s.png", "v012653_10s.png",
    "v012653_20s.png", "v012653_50s.png", "v012653_80s.png",
    "pause_40s_full.png", "pause_117s_full.png",
)
RESUMED_FRAMES = ("v012653_40s.png", "v012653_100s.png", "v012653_120s.png")


def _load_real_frame(name):
    import cv2

    raw = np.fromfile(str(ROOT / name), dtype=np.uint8)
    img = cv2.imdecode(raw, cv2.IMREAD_COLOR)
    assert img is not None, f"实机夹具缺失: {name}"
    return Frame(img.copy(), left=0, top=0, window_title="英雄三国KK", hwnd=1)


def test_post_game_state_detects_pause_on_all_real_frames():
    med = Mediator(Settings(), ROOT)
    for name in REAL_PAUSE_FRAMES:
        med.invalidate_evidence("review")
        assert med._post_game_state(_load_real_frame(name)) == "PAUSED", name


def test_post_game_state_no_pause_false_positive_after_resume():
    med = Mediator(Settings(), ROOT)
    for name in RESUMED_FRAMES:
        med.invalidate_evidence("review")
        assert med._post_game_state(_load_real_frame(name)) is None, name


def test_boot_prefers_game_window_over_visible_platform_room():
    """用户规则：英雄三国进程存在 = 一定走游戏内流程，优先于 KK 房间窗。"""
    med = Mediator(Settings(), ROOT)
    med.set_phase(Phase.BOOT)
    room = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), left=0, top=0, hwnd=111, window_title="KK对战平台")
    game = Frame(
        np.random.default_rng(2).integers(0, 255, (900, 1600, 3), dtype=np.uint8),
        left=10, top=10, hwnd=222, window_title="英雄三国KK",
    )

    calls = []

    def fake_capture(title, role):
        calls.append((title, role))
        return game if role == "l1" else room

    with patch.object(med, "_capture_best", side_effect=fake_capture), \
         patch.object(med, "_frame_signal", side_effect=lambda f, r: 100 if f is room else 0):
        frame = med.see("test")
    assert frame.window_title == "英雄三国KK"
    assert frame.hwnd == 222
    assert calls[0][1] == "l1"


def test_bond_progress_maps_member_card_to_synthesis_set():
    med = Mediator(Settings(), ROOT)
    med._bond_cards_owned[:] = ["体魄"]
    progress = med._bond_choice_progress([
        {"name": "体魄", "raw_text": "体魄(2/3)"},
    ])
    assert progress["体术"]["have"] == 2
    assert progress["体术"]["need"] == 3
    assert "体魄" in progress["体术"]["members"]


def test_bond_replacement_arms_for_runtime_bond_label():
    med = Mediator(Settings(), ROOT)
    frame = _frame()
    anchor = MatchResult("card_hide", 0.90, 758, 574, 10, 10, 758, 574)
    selected = MatchResult("ocr_bond:体术", 0.99, 500, 400, 80, 40, 685, 481)
    med._bond_replace_candidate = "体术"
    with patch.object(med, "_find_reward_choice", return_value=("bond", selected)), \
         patch.object(med, "act_click", return_value=True):
        med._tick_panel_fsm(frame, anchor, time.time())
    assert med._bond_replace_pending == "体术"


def test_bond_occupancy_unknown_fails_closed_without_crashing():
    med = Mediator(Settings(cards=["体术"]), ROOT)
    slots = [{"index": 0, "name": "体术", "confidence": 0.99, "raw_text": "体术(2/3)"}]
    with patch.object(med, "_ocr_panel_slots", return_value=slots), \
         patch.object(med, "_bond_bar_occupancy", return_value=None):
        assert med._ocr_reward_choice(_frame(), "bond") is not None
    assert med._bond_replace_candidate is None


def test_bond_near_full_arms_replacement_before_last_cell_is_consumed():
    med = Mediator(Settings(cards=["经济"]), ROOT)
    slots = [{"index": 0, "name": "经济", "confidence": 0.99, "raw_text": "经济(2/3)"}]
    with patch.object(med, "_ocr_panel_slots", return_value=slots), \
         patch.object(med, "_bond_bar_occupancy", return_value=9):
        hit = med._ocr_reward_choice(_frame(), "bond")
    assert hit is not None
    assert med._bond_replace_candidate == "经济"


def test_see_restores_minimized_target_window():
    """用户规则：所有窗口都可能最小化；无效帧 + IsIconic → SW_RESTORE。"""
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
        med.see("test")
    assert restore.call_count == 1
    assert restore.call_args.args[0] == 333


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


def test_tqtz_is_one_shot_and_blocks_regular_choice_until_confirmed():
    med = Mediator(Settings(), ROOT)
    frame = _frame()
    tqtz_hit = MatchResult("tqtz", .85, 438, 79, 85, 22, 665, 171)
    with patch.object(med, "find", return_value=tqtz_hit), \
         patch.object(med, "_auto_task_state", return_value=("OFF", None)), \
         patch.object(med, "act_click", return_value=True) as click:
        assert med._maybe_click_tqtz(frame, 100.0) is LoopAction.Continue
        assert med._maybe_click_tqtz(frame, 102.0) is None
    assert click.call_count == 1

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

    # 连续 2 帧确认消失后才退出 pending
    with patch.object(med, "find_scene", return_value=False):
        assert med._tick_early_challenge(frame, 10.5) is LoopAction.Continue
        assert med._early_challenge_pending is True
        assert med._tick_early_challenge(frame, 11.0) is LoopAction.Continue
        assert med._early_challenge_pending is False


def test_tqtz_clicked_but_entry_never_closes_resets_clicked_at_after_timeout():
    med = Mediator(Settings(cjb_boss="04大范"), ROOT)
    frame = _frame()
    med._early_challenge_pending = True
    med._early_challenge_clicked_at = 10.0
    # boss_entry 一直存在超过 8s，重置 clicked_at 允许重试
    with patch.object(med, "find_scene", return_value=True):
        assert med._tick_early_challenge(frame, 19.0) is LoopAction.Continue
        assert med._early_challenge_clicked_at is None
        assert med._early_challenge_pending is True

def test_runtime_bond_duplicate_is_retained_for_merge_priority():
    from shuabao.runtime_mediator import Mediator as RuntimeMediator
    med = RuntimeMediator(Settings(cards=["力量"]), ROOT)
    med._bond_cards_owned.clear()
    med._stage_bond_card("力量")
    med._commit_pending_bond_cards()
    med._stage_bond_card("力量")
    med._commit_pending_bond_cards()
    assert med._bond_cards_owned == ["力量", "力量"]


def test_runtime_bond_duplicate_retained_even_if_not_in_preset():
    from shuabao.runtime_mediator import Mediator as RuntimeMediator
    med = RuntimeMediator(Settings(cards=["修仙"]), ROOT)
    med._bond_cards_owned.clear()
    # "力量" 不在用户 preset ("修仙") 中，但通过品质兜底被拿到时，Runtime 仍必须记录
    med._stage_bond_card("力量")
    med._commit_pending_bond_cards()
    med._stage_bond_card("力量")
    med._commit_pending_bond_cards()
    assert med._bond_cards_owned == ["力量", "力量"]


def test_runtime_watchdog_does_not_interfere_with_early_challenge_or_paused():
    from shuabao.runtime_mediator import Mediator as RuntimeMediator
    med = RuntimeMediator(Settings(), ROOT)
    med.phase = Phase.MAIN_LINE
    frame = _frame()
    now = time.time()
    # 1. 提前挑战 pending 时看门狗禁止触发
    med._early_challenge_pending = True
    with patch.object(med, "_post_game_state", return_value=None):
        assert med._runtime_watchdog_allowed(frame, now) is False

    # 2. 暂停恢复尝试中时看门狗禁止触发
    med._early_challenge_pending = False
    med._pause_resume_attempts = 1
    with patch.object(med, "_post_game_state", return_value=None):
        assert med._runtime_watchdog_allowed(frame, now) is False

    # 3. 暂停恢复按钮未匹配计数 > 0 时看门狗禁止触发
    med._pause_resume_attempts = 0
    med._pause_resume_unmatched_attempts = 1
    with patch.object(med, "_post_game_state", return_value=None):
        assert med._runtime_watchdog_allowed(frame, now) is False


def test_hero_focus_requires_two_consecutive_frames_to_dispatch_f1():
    med = Mediator(Settings(), ROOT)
    frame = _frame()
    with patch("shuabao.input.keyboard_mouse.is_current_process_elevated", return_value=True), \
         patch.object(med, "find", return_value=None), \
         patch.object(med, "act_key", return_value=True) as mock_act_key:
        # 第 1 帧：仅计数，不发按键，但返回 Continue 阻断当前 tick 业务输入
        res1 = med._maybe_ensure_hero_panel_focus(frame, 1.0)
        assert res1 is LoopAction.Continue
        assert med._hero_focus_lost_count == 1
        mock_act_key.assert_not_called()

        # 第 2 帧：连续缺失，发送 F1 并重置计数器
        res2 = med._maybe_ensure_hero_panel_focus(frame, 2.5)
        assert res2 is LoopAction.Continue
        assert med._hero_focus_lost_count == 0
        mock_act_key.assert_called_once_with("F1", "HeroFocusFallback")
def test_close_main_line_waits_for_off_state_confirmation():
    med = Mediator(Settings(auto_close_main_line=True), ROOT)
    frame = _frame()
    med._close_main_line_triggered = True
    on_hit = MatchResult("auto_task_on", .90, 800, 200, 40, 20, 820, 210)

    # 状态为 ON 时点击取消，但不立即标记完成
    with patch.object(med, "_auto_task_state", return_value=("ON", on_hit)), \
         patch.object(med, "act_click", return_value=True) as mock_click:
        res = med._maybe_close_main_line_after_5_5(frame, 1.0)
        assert res is LoopAction.Continue
        assert getattr(med, "_main_line_closed_done", False) is False
        mock_click.assert_called_once_with(on_hit, "DisableAutoTask")

    # 再次观察到 OFF 时才最终确认完成
    with patch.object(med, "_auto_task_state", return_value=("OFF", None)):
        res = med._maybe_close_main_line_after_5_5(frame, 2.5)
        assert res is None
        assert getattr(med, "_main_line_closed_done", False) is True

def test_watchdog_arbitration_blocks_esc_on_first_frame_paused_or_tqtz():
    from shuabao.runtime_mediator import Mediator as RuntimeMediator
    med = RuntimeMediator(Settings(), ROOT)
    frame = _frame()
    med.phase = Phase.MAIN_LINE
    med._last_runtime_progress_at = 0.0
    now = 100.0

    # 第一帧 PAUSED：即便 _pause_resume_attempts 为 0，看门狗仍被严格阻断
    with patch.object(med, "_post_game_state", return_value="PAUSED"):
        assert med._runtime_watchdog_allowed(frame, now) is False

    # 第一帧 tqtz 出现：通过真实 _find_tqtz 共享检测，看门狗仍被严格阻断
    tqtz_hit = MatchResult("tqtz", .85, 438, 79, 85, 22, 665, 171)
    with patch.object(med, "_post_game_state", return_value=None), \
         patch.object(med, "_find_tqtz", return_value=tqtz_hit), \
         patch.object(med, "_classify_choice_panel", return_value=None):
        assert med._runtime_watchdog_allowed(frame, now) is False


def test_close_main_line_fail_forward_retry_episode_after_5_attempts():
    med = Mediator(Settings(auto_close_main_line=True), ROOT)
    frame = _frame()
    on_hit = MatchResult("auto_task_on", .9, 100, 100, 50, 20, 125, 110)

    med._close_main_line_triggered = True
    med._close_main_line_attempts = 5
    with patch.object(med, "_auto_task_state", return_value=("ON", on_hit)):
        res = med._maybe_close_main_line_after_5_5(frame, 1.0)
        assert res is None
        assert med._close_main_line_attempts == 0
        assert med._close_main_line_next_at == 11.0
        assert getattr(med, "_main_line_closed_done", False) is False


def test_paused_unmatched_attempts_reset_when_paused_cleared():
    med = Mediator(Settings(), ROOT)
    frame = _frame()
    med.phase = Phase.MAIN_LINE
    med._pause_resume_unmatched_attempts = 3
    med._pause_resume_attempts = 0

    # 模拟暂停状态已消失（post_game != "PAUSED"）
    with patch.object(med, "_post_game_state", return_value=None), \
         patch.object(med, "_round_tail_checks_active", return_value=False):
        med._tick_main_line(frame)
    assert med._pause_resume_unmatched_attempts == 0
    assert med._pause_resume_attempts == 0
