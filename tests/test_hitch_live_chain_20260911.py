"""Full ``Mediator.tick()`` chains replayed on real 2026-09-11 KK captures.

A small fake KK world owns the same-title HWNDs (lobby, room, the separate
exit-confirm prompt, a stale black room window) and changes them in response
to the inputs production sends through the executor.  No real window, focus or
input API is touched.

Covered live failures:
* a stale black room window pinned capture after HitchJoin (20:17/20:44/20:55);
* a promoted host was not recognised and the lobby tab slot clicked our own
  avatar (20:03);
* the exit prompt lives in its own 440x260 HWND, which the confirm step never
  accepted;
* user seat rules: leave as host, when sitting on floor one, or when the
  floor-one player leaves -- ready or not;
* a KK main window left on a blank page recovers through the top "游戏" tab.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from shuabao.mediator import LoopAction, Mediator, Phase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame, WindowTarget

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "hitch_live_20260911"
TITLE = "KK官方对战平台"
LOBBY, ROOM, DIALOG, STALE = 0x7A0001, 0x7A0002, 0x7A0003, 0x7A0004


def _img(name: str) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(str(FIX / name), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None, name
    return image


def _floor_one_left(image: np.ndarray) -> np.ndarray:
    """Row 1 becomes the open slot that row 2 shows (host left floor one)."""
    out = image.copy()
    out[201:241, 300:1130] = image[241:281, 300:1130]
    return out


class KKWorld:
    def __init__(self) -> None:
        self.clock = 1_000_000.0
        self.lobby_img = _img("lobby_room_list_812.png")
        self.room_img: np.ndarray | None = None
        self.dialog = False
        self.stale_black = False
        self.room_script: list[np.ndarray] = []
        self.after_ready: np.ndarray | None = None
        self.readied = False
        self.on_join = None
        self.swallow_exit = 0
        self.swallow_confirm = 0
        self.nav_fixes_lobby = True
        self.inputs: list[tuple[str, int | None]] = []

    # ---- windows --------------------------------------------------------
    def targets(self, role=None) -> list[WindowTarget]:
        if role == "l1":
            return []
        out = [WindowTarget(LOBBY, TITLE, 296, 82, 1332, 812, client_left=296, client_top=82,
                            client_width=1332, client_height=812, role="l0")]
        if self.room_img is not None:
            out.append(WindowTarget(ROOM, TITLE, 348, 73, 1224, 904, client_left=348, client_top=73,
                                    client_width=1224, client_height=904, role="l0"))
        if self.dialog:
            out.append(WindowTarget(DIALOG, TITLE, 740, 400, 440, 260, client_left=740, client_top=400,
                                    client_width=440, client_height=260, role="l0"))
        if self.stale_black:
            out.append(WindowTarget(STALE, TITLE, 348, 73, 1224, 904, client_left=348, client_top=73,
                                    client_width=1224, client_height=904, role="l0"))
        return out

    def capture(self, target: WindowTarget) -> Frame:
        if target.hwnd == LOBBY:
            image = self.lobby_img
        elif target.hwnd == ROOM:
            image = self.room_img
        elif target.hwnd == DIALOG:
            image = _img("exit_confirm_dialog_440x260.png")
        else:
            image = np.zeros((904, 1224, 3), dtype=np.uint8)
        return Frame(image, left=target.client_left, top=target.client_top, window_title=TITLE,
                     hwnd=target.hwnd, role="l0", timestamp=self.clock)

    # ---- inputs ---------------------------------------------------------
    def react(self, reason: str, hwnd: int | None) -> None:
        self.inputs.append((reason, hwnd))
        if reason == "HitchJoin" and self.on_join is not None:
            self.on_join(self)
        elif reason == "HitchReady" and self.after_ready is not None:
            self.room_img = self.after_ready
            self.readied = True
        elif reason in ("HitchLeaveFloorOne", "HitchReadyTimeoutLeave"):
            if self.swallow_exit > 0:
                self.swallow_exit -= 1
            else:
                self.dialog = True
        elif reason == "HitchConfirmLeave":
            if self.swallow_confirm > 0:
                self.swallow_confirm -= 1
            else:
                self.dialog = False
                self.room_img = None
        elif reason == "HitchNavGameTab" and self.nav_fixes_lobby:
            self.lobby_img = _img("lobby_room_list_812.png")

    def advance(self) -> None:
        self.clock += 1.5
        # Scripted room changes (someone leaves, we get promoted) happen
        # while we sit ready in the room.
        if self.readied and self.room_script and self.room_img is not None and not self.dialog:
            self.room_img = self.room_script.pop(0)


class FakeExecutor:
    """Accepts every input; the world reacts after the tick from the trace."""

    def _ok(self, *_args, **_kwargs):
        return SimpleNamespace(success=True, status="SUCCESS", message="")

    click = double_click = right_click = press_key = search_text = type_text = scroll = _ok


def _run(world: KKWorld, ticks: int, *, until=None, trace: Path | None = None):
    med = Mediator(Settings(mode_id="lobby_hitch", hitch_stage_prefix="4", ocr_mode="off"), ROOT)
    med.set_phase(Phase.LOBBY_ROOM, "chain test")
    med._hitch_search_text_override = "4"
    med.executor = FakeExecutor()
    if trace is not None:
        med.set_trace(str(trace))
    actions: list[tuple[str, int | None]] = []
    with patch("shuabao.mediator.find_window_targets",
               side_effect=lambda title="", role=None, **_k: world.targets(role)), \
         patch("shuabao.mediator.capture_target", side_effect=world.capture), \
         patch("shuabao.mediator.capture", return_value=Frame(
             np.zeros((0, 0, 3), dtype=np.uint8), is_valid=False, error="no window",
         )), \
         patch("shuabao.mediator.time.time", side_effect=lambda: world.clock), \
         patch("shuabao.vision.capture.is_window_minimized", return_value=False), \
         patch("shuabao.mediator.capture_reacquire_target_window", return_value=True), \
         patch("shuabao.mediator.reacquire_target_window", return_value=True), \
         patch("shuabao.mediator.activate_window", return_value=True):
        for _ in range(ticks):
            world.advance()
            result = med.tick()
            hwnd = med._last_frame.hwnd if med._last_frame is not None else None
            for action in med._trace_actions:
                actions.append((action["reason"], hwnd))
                world.react(action["reason"], hwnd)
            if result is LoopAction.Break or (until is not None and until(med, world)):
                break
    if trace is not None:
        med.set_trace(None)
    return med, actions


def _reasons(actions) -> list[str]:
    return [reason for reason, _hwnd in actions]


def test_stale_black_room_window_never_pins_capture_after_join() -> None:
    world = KKWorld()
    world.stale_black = True          # left over from an earlier misclick
    world.on_join = lambda w: None    # the join opens nothing

    med, actions = _run(world, 25)

    assert STALE not in [hwnd for _reason, hwnd in actions]
    assert med._last_frame.hwnd == LOBBY
    assert med._hitch_sm.pending_join is False
    assert "HitchJoin" in _reasons(actions)
    assert med.phase is Phase.LOBBY_ROOM


def _join_room(first: np.ndarray, ready: np.ndarray, script: list[np.ndarray] | None = None):
    def on_join(world: KKWorld) -> None:
        world.room_img = first
        world.after_ready = ready
        world.room_script = list(script or [])
    return on_join


def _assert_left_and_returned(med: Mediator, actions, *, exit_reason: str = "HitchLeaveFloorOne") -> None:
    reasons = _reasons(actions)
    assert exit_reason in reasons, reasons
    assert "HitchConfirmLeave" in reasons, reasons
    confirm_hwnds = {hwnd for reason, hwnd in actions if reason == "HitchConfirmLeave"}
    assert confirm_hwnds == {DIALOG}
    assert "HitchSelectTab" not in reasons
    assert med._hitch_floor_exit_pending is False
    assert med.phase is Phase.LOBBY_ROOM


def _left(med: Mediator, world: KKWorld) -> bool:
    return world.room_img is None and not med._hitch_floor_exit_pending and any(
        reason == "HitchConfirmLeave" for reason, _ in world.inputs
    )


def test_self_on_floor_one_leaves_after_ready_through_separate_confirm_hwnd() -> None:
    world = KKWorld()
    world.on_join = _join_room(
        _img("room_joined_self_row1_not_ready.png"), _img("room_self_row1_after_ready.png"),
    )

    med, actions = _run(world, 40, until=_left)

    reasons = _reasons(actions)
    assert reasons.index("HitchReady") < reasons.index("HitchLeaveFloorOne")
    _assert_left_and_returned(med, actions)
    assert med._hitch_self_row is None  # episode reset after the verified exit


def test_guest_under_floor_one_host_stays_in_room() -> None:
    world = KKWorld()
    world.on_join = _join_room(
        _img("room_joined_self_row3_host_row1.png"), _img("room_ready_self_row3_host_row1.png"),
    )

    med, actions = _run(world, 30)  # 45s simulated, below the 70s ready wait

    reasons = _reasons(actions)
    assert "HitchReady" in reasons
    assert "HitchLeaveFloorOne" not in reasons
    assert med._hitch_self_row == 3
    assert med._hitch_floor_one_baseline is not None
    assert med.phase is Phase.ROOM_WAITING


def test_floor_one_player_leaving_makes_ready_guest_leave() -> None:
    ready = _img("room_ready_self_row3_host_row1.png")
    world = KKWorld()
    world.on_join = _join_room(
        _img("room_joined_self_row3_host_row1.png"), ready,
        script=[ready] * 6 + [_floor_one_left(ready)] * 40,
    )

    med, actions = _run(world, 60, until=_left)

    _assert_left_and_returned(med, actions)
    assert "HitchReady" in _reasons(actions)


def test_promotion_to_host_makes_ready_guest_leave() -> None:
    ready = _img("room_ready_self_row3_host_row1.png")
    world = KKWorld()
    world.on_join = _join_room(
        _img("room_joined_self_row3_host_row1.png"), ready,
        script=[ready] * 6 + [_img("room_promoted_host_waiting.png")] * 40,
    )

    med, actions = _run(world, 60, until=_left)

    _assert_left_and_returned(med, actions)
    reasons = _reasons(actions)
    assert reasons.index("HitchReady") < reasons.index("HitchLeaveFloorOne")


def test_swallowed_exit_and_confirm_clicks_are_retried() -> None:
    world = KKWorld()
    world.swallow_exit = 1
    world.swallow_confirm = 1
    world.on_join = _join_room(
        _img("room_joined_self_row1_not_ready.png"), _img("room_self_row1_after_ready.png"),
    )

    med, actions = _run(world, 60, until=_left)

    reasons = _reasons(actions)
    assert reasons.count("HitchLeaveFloorOne") == 2
    assert reasons.count("HitchConfirmLeave") == 2
    _assert_left_and_returned(med, actions)


def test_exit_that_never_takes_effect_ends_blocked() -> None:
    world = KKWorld()
    world.swallow_exit = 99
    world.on_join = _join_room(
        _img("room_joined_self_row1_not_ready.png"), _img("room_self_row1_after_ready.png"),
    )

    med, actions = _run(world, 80)

    assert med.phase is Phase.ERROR
    assert _reasons(actions).count("HitchLeaveFloorOne") == Mediator._HITCH_EXIT_MAX_CLICKS
    assert "HitchSelectTab" not in _reasons(actions)


def test_blank_lobby_page_recovers_through_game_tab() -> None:
    world = KKWorld()
    world.lobby_img = _img("lobby_blank_page_after_misclick.png")

    med, actions = _run(world, 12, until=lambda m, w: "HitchSearchBox" in _reasons(w.inputs))

    reasons = _reasons(actions)
    assert reasons[0] == "HitchNavGameTab"
    assert "HitchSearchBox" in reasons
    assert med._hitch_nav_clicks == 0  # episode closed by fresh room-list evidence


def test_navigation_fallback_is_bounded() -> None:
    world = KKWorld()
    world.lobby_img = _img("lobby_blank_page_after_misclick.png")
    world.nav_fixes_lobby = False

    med, actions = _run(world, 40)

    assert med.phase is Phase.ERROR
    assert _reasons(actions).count("HitchNavGameTab") == Mediator._KK_NAV_MAX_CLICKS


def test_trace_rows_carry_capture_and_hitch_audit_fields(tmp_path) -> None:
    world = KKWorld()
    world.stale_black = True
    world.on_join = lambda w: None
    trace = tmp_path / "trace.jsonl"

    _run(world, 8, trace=trace)

    rows = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    assert rows and all("capture" in row and "hitch" in row for row in rows)
    assert any(STALE in row["capture"]["black_hwnds"] for row in rows)
    assert {"pending_join", "exit_pending", "self_row"} <= set(rows[-1]["hitch"])
