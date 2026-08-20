"""lobby_hitch: 搜房有界重试、选择面板 Fail-Closed、踢出/解散不记 TIMEOUT。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from shuabao.loop_action import LoopAction
from shuabao.mediator import Mediator, Phase, RoundOutcome
from shuabao.settings import Settings
from shuabao.stop_signal import StopSignal
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult
from tests.test_scenario_replay import FakeClock, FakeInputExecutor

ROOT = Path(__file__).resolve().parents[2]


def _frame(hwnd: int = 10001) -> Frame:
    rng = np.random.default_rng(7)
    return Frame(
        rng.integers(0, 255, (900, 1600, 3), dtype=np.uint8),
        window_title="KK",
        hwnd=hwnd,
    )


def _hit(name: str = "skill_hide", x: int = 600, y: int = 580) -> MatchResult:
    return MatchResult(name=name, score=0.95, x=x, y=y, w=20, h=20, screen_x=x, screen_y=y)


def _hitch_settings(**kw) -> Settings:
    data = dict(
        mode_id="lobby_hitch",
        auto_create_room=False,
        dry_run=True,
        hitch_stage_prefix="3",
        ocr_mode="off",
    )
    data.update(kw)
    return Settings(**data)


def _hitch_mediator(**kw) -> Mediator:
    med = Mediator(_hitch_settings(**kw), ROOT)
    med._auto_task_done = True
    return med


def test_hitch_search_three_failed_attempts_go_home_and_sleep():
    med = _hitch_mediator(hitch_stage_prefix="4")
    clock = FakeClock(start=100.0)
    med.executor = FakeInputExecutor(StopSignal(), clock)
    med.set_phase(Phase.LOBBY_ROOM, "hitch search test")
    med._hitch_match_override = False
    frame = _frame()
    clicks: list[str] = []

    with clock.install(), patch.object(med, "_detect_context", return_value="UNKNOWN"), \
            patch.object(med, "_find_room_start", return_value=None), \
            patch.object(med, "act_click", side_effect=lambda _h, reason="": clicks.append(reason) or True):
        for i in range(3):
            clock.set(100.0 + i)
            assert med._tick_l0(frame) is LoopAction.Continue
        assert med._hitch_sm.prefix == "4"
        assert med._hitch_join_refresh_count == 3
        assert med._hitch_search_actions == ["refresh", "refresh", "refresh"]
        clock.set(104.0)
        assert med._tick_l0(frame) is LoopAction.Continue
        assert med.phase is Phase.LOBBY_ROOM
        assert med._hitch_status == "大厅主页"
        clock.set(105.0)
        assert med._tick_l0(frame) is LoopAction.Continue
        assert med._hitch_status == "休眠重试"
        for i in range(8):
            clock.set(106.0 + i)
            med._tick_l0(frame)
        assert med._hitch_join_refresh_count == 3
        assert med._hitch_search_actions == ["refresh", "refresh", "refresh"]
        assert clicks == []
        assert all(reason != "RoomStart" and reason != "CreateRoom-open" for reason in clicks)


def test_hitch_search_120s_unmatched_goes_home_with_at_most_three_attempts():
    med = _hitch_mediator(hitch_stage_prefix="3")
    clock = FakeClock(start=100.0)
    med.set_phase(Phase.LOBBY_ROOM, "hitch 120s test")
    med._hitch_match_override = False
    frame = _frame()

    with clock.install(), patch.object(med, "_detect_context", return_value="UNKNOWN"), \
            patch.object(med, "_find_room_start", return_value=None), \
            patch.object(med, "act_click", return_value=True):
        clock.set(100.0)
        med._tick_l0(frame)
        clock.set(220.0)
        med._tick_l0(frame)
        assert med.phase is Phase.LOBBY_ROOM
        assert med._hitch_status == "大厅主页"
        assert med._hitch_join_refresh_count <= 3
        assert len(med._hitch_search_actions) <= 3
        clock.set(221.0)
        med._tick_l0(frame)
        assert med._hitch_status == "休眠重试"
        clock.set(230.0)
        med._tick_l0(frame)
        assert med._hitch_join_refresh_count <= 3
        assert med._hitch_sm.prefix == "3"


def test_hitch_panel_fail_closed_zero_pick_zero_refresh():
    hitch = _hitch_mediator()
    control = Mediator(Settings(mode_id="normal_farm", dry_run=True, ocr_mode="off"), ROOT)
    clock = FakeClock(start=100.0)
    hitch_clicks: list[str] = []
    control_clicks: list[str] = []
    pick = ("技能", _hit("skills/jq", 500, 260))
    close = _hit("skill_hide", 600, 580)
    frame = _frame()

    def _drive(med: Mediator, bucket: list[str], at: float) -> None:
        med.executor = FakeInputExecutor(StopSignal(), clock)
        med.set_phase(Phase.MAIN_LINE, "panel hitch test")
        med._auto_task_done = True
        med._capture_best = lambda *a, **k: frame
        with clock.install(), \
                patch.object(med, "find_scene", return_value=None), \
                patch.object(med, "_selection_anchor", return_value=close), \
                patch.object(med, "_post_game_state", return_value=None), \
                patch.object(med, "_ensure_auto_task_enabled", return_value=None), \
                patch.object(med, "_ensure_challenge_buttons", return_value=None), \
                patch.object(med, "_find_stage_page", return_value=False), \
                patch.object(med, "_handle_self_opened_compact_panel", return_value=None), \
                patch.object(med, "_maybe_fire_artifacts", return_value=None), \
                patch.object(med, "_find_reward_choice", return_value=pick), \
                patch.object(med, "_close_current_panel", return_value=close), \
                patch.object(med, "act_click", side_effect=lambda _h, reason="": bucket.append(reason) or True):
            clock.set(at)
            assert med.tick() is LoopAction.Continue

    _drive(hitch, hitch_clicks, 101.0)
    _drive(control, control_clicks, 121.0)

    assert hitch_clicks == ["HitchPanelFailClosed"]
    assert not any("刷新" in r or r.endswith("选择") for r in hitch_clicks)
    assert "技能选择" in control_clicks
    assert "HitchPanelFailClosed" not in control_clicks


@pytest.mark.parametrize("ocr_text", ["被踢出房间", "房间已解散"])
def test_hitch_kick_or_dissolve_resets_lobby_without_timeout(ocr_text: str):
    med = Mediator(
        _hitch_settings(dry_run=False, round_timeout_s=900),
        ROOT,
    )
    clock = FakeClock(start=100.0)
    med.executor = FakeInputExecutor(StopSignal(), clock)
    frame = _frame()
    med._capture_best = lambda *a, **k: frame
    incidents: list[str] = []
    med._record_round_timeout_incident = lambda: incidents.append("round_timeout")
    med.set_phase(Phase.MAIN_LINE, "hitch in game")
    med._round_deadline = 50.0
    med._hitch_ocr_override = ocr_text

    with clock.install(), \
            patch.object(med, "find_scene", return_value=None), \
            patch.object(med, "_selection_anchor", return_value=None), \
            patch.object(med, "_post_game_state", return_value=None), \
            patch.object(med, "_ensure_auto_task_enabled", return_value=None), \
            patch.object(med, "_ensure_challenge_buttons", return_value=None), \
            patch.object(med, "_find_stage_page", return_value=False):
        clock.set(100.0)
        assert med.tick() is LoopAction.Continue

    assert med.phase is Phase.LOBBY_ROOM
    assert med._round_outcome is not RoundOutcome.TIMEOUT
    assert incidents == []
    assert med._hitch_status == "大厅主页"
    assert med._round_deadline is None
