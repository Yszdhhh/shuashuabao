"""lobby_hitch: 搜房 executor、forbidden_actions、跟车/蹭车尾链、选择面板 Fail-Closed。"""

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
    med._hitch_hit_override = _hit("lobby_refresh")
    return med


def _wrap_clicks(med: Mediator) -> list[str]:
    clicks: list[str] = []
    real = med.act_click

    def _wrapped(hit, reason=""):
        clicks.append(reason)
        return real(hit, reason)

    med.act_click = _wrapped  # type: ignore[method-assign]
    return clicks


def test_hitch_refresh_respects_3s_debounce_and_three_attempts_then_home():
    med = _hitch_mediator(hitch_stage_prefix="4")
    clock = FakeClock(start=100.0)
    med.executor = FakeInputExecutor(StopSignal(), clock)
    med.set_phase(Phase.LOBBY_ROOM, "hitch search test")
    med._hitch_match_override = False
    med._hitch_lobby_home_override = True
    frame = _frame()
    clicks = _wrap_clicks(med)

    with clock.install(), patch.object(med, "_detect_context", return_value="UNKNOWN"), \
            patch.object(med, "_find_room_start", return_value=None):
        clock.set(100.0)
        assert med._tick_l0(frame) is LoopAction.Continue
        assert med._hitch_search_actions == ["refresh"]
        clock.set(101.0)
        med._tick_l0(frame)
        clock.set(102.9)
        med._tick_l0(frame)
        assert med._hitch_search_actions == ["refresh"]
        clock.set(103.0)
        med._tick_l0(frame)
        clock.set(106.0)
        med._tick_l0(frame)
        assert med._hitch_sm.prefix == "4"
        assert med._hitch_join_refresh_count == 3
        assert med._hitch_search_actions == ["refresh", "refresh", "refresh"]
        clock.set(109.0)
        assert med._tick_l0(frame) is LoopAction.Continue
        assert med.phase is Phase.LOBBY_ROOM
        assert "HitchGoHome" in clicks
        assert med._hitch_status != "大厅主页"
        assert med._hitch_sm.go_home_clicked is True
        clock.set(110.0)
        assert med._tick_l0(frame) is LoopAction.Continue
        assert med._hitch_status == "大厅主页"
        clock.set(111.0)
        assert med._tick_l0(frame) is LoopAction.Continue
        assert med._hitch_status == "休眠重试"
        for i in range(8):
            clock.set(112.0 + i)
            med._tick_l0(frame)
        assert med._hitch_join_refresh_count == 3
        assert med._hitch_search_actions == ["refresh", "refresh", "refresh"]
        assert all(reason != "RoomStart" and reason != "CreateRoom-open" for reason in clicks)
        assert clicks.count("HitchRefresh") == 3


def test_hitch_search_120s_unmatched_go_home_needs_lobby_evidence():
    med = _hitch_mediator(hitch_stage_prefix="3")
    clock = FakeClock(start=100.0)
    med.executor = FakeInputExecutor(StopSignal(), clock)
    med.set_phase(Phase.LOBBY_ROOM, "hitch 120s test")
    med._hitch_match_override = False
    med._hitch_lobby_home_override = False
    frame = _frame()
    clicks = _wrap_clicks(med)

    with clock.install(), patch.object(med, "_detect_context", return_value="UNKNOWN"), \
            patch.object(med, "_find_room_start", return_value=None):
        clock.set(100.0)
        med._tick_l0(frame)
        clock.set(220.0)
        med._tick_l0(frame)
        assert med.phase is Phase.LOBBY_ROOM
        assert med._hitch_status != "大厅主页"
        assert "HitchGoHome" in clicks
        med._hitch_lobby_home_override = True
        clock.set(223.0)
        med._tick_l0(frame)
        assert med._hitch_status == "大厅主页"
        assert med._hitch_join_refresh_count <= 3
        assert len([a for a in med._hitch_search_actions if a == "refresh"]) <= 3
        clock.set(224.0)
        med._tick_l0(frame)
        assert med._hitch_status == "休眠重试"
        assert med._hitch_sm.prefix == "3"


def test_hitch_join_requires_prefix_evidence_and_post_confirm():
    med = _hitch_mediator()
    clock = FakeClock(start=100.0)
    med.executor = FakeInputExecutor(StopSignal(), clock)
    med.set_phase(Phase.LOBBY_ROOM, "hitch join")
    med._hitch_match_override = True
    med._hitch_ocr_override = ""
    frame = _frame()
    clicks = _wrap_clicks(med)

    with clock.install(), patch.object(med, "_detect_context", return_value="UNKNOWN"), \
            patch.object(med, "_find_room_start", return_value=None):
        clock.set(100.0)
        med._tick_l0(frame)
        assert "join" not in med._hitch_search_actions
        assert "HitchJoin" not in clicks
        med._hitch_sm = med._new_hitch_sm()
        med._hitch_search_actions.clear()
        med._hitch_ocr_override = "3/4 速30"
        clock.set(200.0)
        med._tick_l0(frame)
        assert med._hitch_search_actions[-1] == "join"
        assert "HitchJoin" in clicks
        assert med._hitch_sm.pending_join is True
        assert med._hitch_sm.attempts == 0
        clock.set(201.0)
        med._tick_l0(frame)
        assert med._hitch_sm.pending_join is True
        assert med._hitch_sm.attempts == 0

    room = _hit("lobby/room_start", 800, 700)
    with clock.install(), patch.object(med, "_detect_context", return_value="ROOM_WAITING"), \
            patch.object(med, "_find_room_start", return_value=room):
        clock.set(202.0)
        med._tick_l0(frame)
        assert med._hitch_sm.pending_join is False
        assert med._hitch_sm.attempts == 1
        assert med.phase is Phase.ROOM_WAITING
        assert all("RoomStart" not in r for r in clicks)


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


@pytest.mark.parametrize("kind,pick_label", [("treasure", "宝物"), ("skill", "技能"), ("bond", "羁绊"), ("unknown", "未知")])
def test_hitch_and_follow_fail_close_all_choice_panels(kind, pick_label):
    for mode_id in ("lobby_hitch", "follow_team"):
        med = Mediator(Settings(mode_id=mode_id, dry_run=True, ocr_mode="off", auto_create_room=False), ROOT)
        clock = FakeClock(start=100.0)
        clicks: list[str] = []
        pick = (pick_label, _hit("skills/jq", 500, 260))
        close = _hit("treasure_hide_btn" if kind == "treasure" else "skill_hide", 600, 580)
        frame = _frame()
        med.executor = FakeInputExecutor(StopSignal(), clock)
        med.set_phase(Phase.MAIN_LINE, "panel fail-close")
        med._auto_task_done = True
        med._capture_best = lambda *a, **k: frame
        with clock.install(), \
                patch.object(med, "find_scene", return_value=None), \
                patch.object(med, "_selection_anchor", return_value=close), \
                patch.object(med, "_panel_kind_of", return_value=kind), \
                patch.object(med, "_post_game_state", return_value=None), \
                patch.object(med, "_ensure_auto_task_enabled", return_value=None), \
                patch.object(med, "_ensure_challenge_buttons", return_value=None), \
                patch.object(med, "_find_stage_page", return_value=False), \
                patch.object(med, "_handle_self_opened_compact_panel", return_value=None), \
                patch.object(med, "_maybe_fire_artifacts", return_value=None), \
                patch.object(med, "_find_reward_choice", return_value=pick), \
                patch.object(med, "_close_current_panel", return_value=close), \
                patch.object(med, "act_click", side_effect=lambda _h, reason="": clicks.append(reason) or True):
            clock.set(130.0)
            assert med.tick() is LoopAction.Continue
        assert clicks == ["HitchPanelFailClosed"], (mode_id, kind, clicks)
        assert f"{pick_label}选择" not in clicks
        assert not any("刷新" in r for r in clicks)


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


def test_follow_team_never_emits_roomstart_or_create_room():
    med = Mediator(Settings(mode_id="follow_team", dry_run=True, ocr_mode="off", auto_create_room=False), ROOT)
    clock = FakeClock(start=100.0)
    med.executor = FakeInputExecutor(StopSignal(), clock)
    med.set_phase(Phase.BOOT, "follow")
    frame = _frame()
    start = _hit("lobby/room_start", 800, 700)
    clicks = _wrap_clicks(med)
    with clock.install(), patch.object(med, "_detect_context", return_value="ROOM_WAITING"), \
            patch.object(med, "_find_room_start", return_value=start):
        clock.set(100.0)
        med._tick_l0(frame)
        med.set_phase(Phase.ROOM_WAITING, "force")
        clock.set(101.0)
        med._tick_l0(frame)
    assert all(
        "RoomStart" not in r and "CreateRoom" not in r and "quick_join" not in r and "quick_match" not in r
        for r in clicks
    )
    assert med.phase is Phase.ROOM_WAITING


def test_normal_farm_still_may_room_start():
    med = Mediator(Settings(mode_id="normal_farm", dry_run=True, ocr_mode="off"), ROOT)
    clock = FakeClock(start=100.0)
    med.executor = FakeInputExecutor(StopSignal(), clock)
    med.set_phase(Phase.ROOM_WAITING, "farm")
    frame = _frame()
    start = _hit("lobby/room_start", 800, 700)
    clicks = _wrap_clicks(med)
    with clock.install(), patch.object(med, "_detect_context", return_value="ROOM_WAITING"), \
            patch.object(med, "_find_room_start", return_value=start), \
            patch.object(med, "_find_stage_page", return_value=False):
        clock.set(100.0)
        med._tick_l0(frame)
    assert any(r == "RoomStart" or r.startswith("RoomStart") for r in clicks)


def test_hitch_after_exit_researches_lobby_not_same_room_wait():
    med = _hitch_mediator()
    clock = FakeClock(start=200.0)
    med.executor = FakeInputExecutor(StopSignal(), clock)
    frame = _frame()
    clicks = _wrap_clicks(med)
    med._hitch_after_exit(200.0)
    assert med._awaiting_room_return is False
    assert med._hitch_re_search is True
    assert med.phase is Phase.LOBBY_ROOM
    with clock.install(), patch.object(med, "_detect_context", return_value="UNKNOWN"), \
            patch.object(med, "_find_room_start", return_value=None):
        clock.set(200.0)
        med._tick_l0(frame)
    assert med.phase is Phase.LOBBY_ROOM
    assert med._hitch_search_actions[-1] == "refresh"
    assert "HitchRefresh" in clicks
    assert med.phase is not Phase.ROOM_WAITING


def test_follow_after_exit_stays_same_room_wait():
    med = Mediator(Settings(mode_id="follow_team", dry_run=True, ocr_mode="off", auto_create_room=False), ROOT)
    clock = FakeClock(start=200.0)
    med.executor = FakeInputExecutor(StopSignal(), clock)
    med._awaiting_room_return = True
    med.set_phase(Phase.PREPARE, "follow exit")
    frame = _frame()
    start = _hit("lobby/room_start", 800, 700)
    clicks = _wrap_clicks(med)
    with clock.install(), patch.object(med, "_detect_context", return_value="ROOM_WAITING"), \
            patch.object(med, "_find_room_start", return_value=start):
        clock.set(200.0)
        med._tick_l0(frame)
        assert med._awaiting_room_return is False
        assert med.phase is Phase.ROOM_WAITING
        clock.set(201.0)
        med._tick_l0(frame)
    assert med.phase is Phase.ROOM_WAITING
    assert all("RoomStart" not in r for r in clicks)


def test_follow_team_act_click_roomstart_denied_by_guard():
    med = Mediator(Settings(mode_id="follow_team", dry_run=True, ocr_mode="off", auto_create_room=False), ROOT)
    clock = FakeClock(start=100.0)
    med.executor = FakeInputExecutor(StopSignal(), clock)
    clicks = _wrap_clicks(med)
    hit = _hit("lobby/room_start", 800, 700)
    with clock.install():
        clock.set(100.0)
        assert med.act_click(hit, "RoomStart") is False
        assert med.act_click(hit, "RoomStart-retry") is False
        assert med.act_click(hit, "CreateRoom-open") is False
        assert med.act_click(hit, "quick_join") is False
    assert clicks == ["RoomStart", "RoomStart-retry", "CreateRoom-open", "quick_join"]
    assert med.executor.action_ledger == []


def test_forbidden_actions_align_with_mediator_click_reasons():
    import re

    from shuabao.shell.mode_catalog import action_is_forbidden, load_specs

    src = (ROOT / "src" / "shuabao" / "mediator.py").read_text(encoding="utf-8")
    reasons = set(re.findall(r'act_click\([^)]*?["\']([^"\']+)["\']', src))
    reasons.update(re.findall(r'reason=["\']([^"\']+)["\']', src))
    live_l0 = {"RoomStart", "RoomStart-retry", "CreateRoom-open", "CreateRoom-confirm"}
    missing = live_l0 - reasons
    assert not missing, f"mediator lost L0 click reasons: {missing}"
    specs = load_specs()
    for mode_id in ("follow_team", "lobby_hitch"):
        forbidden = specs[mode_id].forbidden_actions
        for reason in live_l0:
            assert action_is_forbidden(reason, forbidden), (mode_id, reason)
        for token in forbidden:
            assert action_is_forbidden(token, forbidden), token
            matches_live = any(action_is_forbidden(r, (token,)) for r in reasons | {token})
            assert matches_live, f"{mode_id} forbidden {token!r} matches no mediator reason"


def test_follow_team_sm_never_requests_start():
    from shuabao.lobby_hitch import FollowPhase, FollowTeamSM

    sm = FollowTeamSM()
    assert sm.tick(in_game=False, in_room=True, stage_page=False) is FollowPhase.WAIT_HOST
    assert sm.tick(in_game=True, in_room=True, stage_page=False) is FollowPhase.IN_GAME
    assert sm.tick(in_game=False, in_room=False, stage_page=True) is FollowPhase.STAGE_WAIT
    assert sm.tick(in_game=False, in_room=False, stage_page=False) is FollowPhase.WAIT_ROOM
