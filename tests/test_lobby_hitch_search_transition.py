"""Production-seam regressions for the 20260907 lobby search deadlock.

Real-machine failure being regressed (source SHA ``0128342e``):

    room-list tab -> search box located -> physical input '4' succeeds ->
    KK filters the list -> production OCR reads the box as "a" ->
    postcondition never confirms -> confirmation times out ->
    the recovery path asks for the EMPTY-search-box template again ->
    the typed box no longer matches it -> early return ->
    ``HitchSearchSM.tick()`` unreachable -> Refresh/Join unreachable ->
    zero-input loop for the remaining 87 ticks of the run.

These tests drive ``Mediator._tick_lobby_hitch`` — the production decision
function — with the real incident frames.  Nothing between the frame and the
business decision is stubbed: the locator, the room-list authority, the
content crop, ``has_prefix_evidence`` and ``HitchSearchSM`` are all the
shipped implementations, and no test seeds ``_hitch_search`` by hand on the
forward path.  Only the two process boundaries are faked, and only because an
offline test may not send real input or spawn the OCR sidecar:

* ``FakeInputExecutor`` stands in for SendInput;
* ``ReplayShadowClient`` stands in for the OCR worker process and replays the
  text that the *real* worker returned for these exact frames.

``tools/replay_hitch_search_ocr.py`` covers the other half: it runs the real
production OCR worker against the same fixtures with no stub at all.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
import pytest

from shuabao.input.keyboard_mouse import ActionResult, InputExecutor
from shuabao.lobby_hitch import HitchPhase, SearchTransaction
from shuabao.mediator import Mediator
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.ocr_shadow.protocol import ShadowResponse

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "lobby_hitch_search_20260907"
LEGACY_FIXTURES = ROOT / "fixtures" / "lobby_hitch_20260814"

# The incident client rect, straight from the run log's capture line.
CLIENT_LEFT, CLIENT_TOP = 559, 36
CLIENT_HWND = 31985540

EMPTY = "search_empty_t035.png"
TYPED = "search_typed4_t038.png"
RESULTS = "search_results4_t040.png"


def _read(path: Path) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None, path
    return image


def _frame(name: str, *, left: int = CLIENT_LEFT, top: int = CLIENT_TOP) -> Frame:
    return Frame(
        _read(FIXTURES / name),
        left=left,
        top=top,
        window_title="KK官方对战平台",
        hwnd=CLIENT_HWND,
        role="l0",
    )


def _legacy_frame(name: str) -> Frame:
    """A 1600x900 client crop recorded in a different session (20260814)."""
    return Frame(
        _read(LEGACY_FIXTURES / name),
        left=203,
        top=84,
        window_title="KK官方对战平台",
        hwnd=20002,
        role="l0",
    )


class FakeInputExecutor(InputExecutor):
    """Record every action instead of sending it to the real client."""

    def __init__(self, *, succeed: bool = True) -> None:
        super().__init__(stop_signal=None)
        self.succeed = succeed
        self.calls: list[tuple] = []

    def _record(self, kind: str, *args) -> ActionResult:
        self.calls.append((kind, *args))
        if self.succeed:
            return ActionResult(True, "SUCCESS", f"fake {kind}")
        return ActionResult(False, "CANCELLED_FAKE", f"fake {kind} refused")

    def search_text(self, x, y, text, target_hwnd=None, dry_run=True):
        return self._record("search_text", int(x), int(y), str(text))

    def click(self, x, y, target_hwnd=None, dry_run=True, delay_ms=120):
        return self._record("click", int(x), int(y))

    def double_click(self, x, y, target_hwnd=None, dry_run=True, delay_ms=50):
        return self._record("double_click", int(x), int(y))

    def press_key(self, key, target_hwnd=None, dry_run=True):
        return self._record("press_key", str(key))

    def hotkey(self, *keys, target_hwnd=None, dry_run=True):
        return self._record("hotkey", "+".join(str(k) for k in keys))

    def type_text(self, text, target_hwnd=None, dry_run=True):
        return self._record("type_text", str(text))

    def kinds(self, kind: str) -> list[tuple]:
        return [c for c in self.calls if c[0] == kind]


class ReplayShadowClient:
    """Stand in for the OCR worker process, replaying real recorded text."""

    def __init__(self, text: str | list[str], status: str = "ok") -> None:
        self._texts = [text] if isinstance(text, str) else list(text)
        self._status = status
        self.requests: list[tuple[int, int, int, int]] = []

    def shadow_predict(self, frame, panel_id, slot, **kwargs):
        bbox = tuple(int(v) for v in slot["bbox"])
        self.requests.append(bbox)
        if self._status != "ok":
            return ShadowResponse.unavailable(len(self.requests), self._status)
        idx = min(len(self.requests) - 1, len(self._texts) - 1)
        return ShadowResponse(
            seq=len(self.requests),
            status="ok",
            raw_text=self._texts[idx],
            rec_score=0.95,
        )


def _mediator(
    *,
    prefix: str = "4",
    ocr: object | None = None,
    executor: FakeInputExecutor | None = None,
) -> tuple[Mediator, FakeInputExecutor]:
    med = Mediator(Settings(mode_id="lobby_hitch", hitch_stage_prefix=prefix), ROOT)
    exe = executor or FakeInputExecutor()
    med.executor = exe
    med._ocr_client = ocr
    return med, exe


class _Clock:
    """A monotonic fake clock the mediator reads through ``time.time``."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += seconds
        return self.now


def _tick(med: Mediator, frame: Frame, clock: _Clock, context: str = "LOBBY_ROOM"):
    """One production decision on one real frame, under the fake clock."""
    med._last_frame = frame
    med.invalidate_evidence("new frame")
    with patch("shuabao.mediator.time.time", clock):
        return med._tick_lobby_hitch(frame, context)


@lru_cache(maxsize=4)
def _off_room_list_image(kind: str) -> np.ndarray:
    return _build_off_room_list_image(kind)


def _off_room_list_frame(kind: str) -> Frame:
    """A real lobby frame that is *not* the trusted room list.

    ``kind="unselected"`` keeps the room-list nav tab legible but removes the
    blue selection, so the tab is clickable while the surface is unproven.
    ``kind="notab"`` also paints the nav slot out, so the tab is unreachable.
    Both keep the search magnifier fully visible, which is what makes them
    useful: a locator must not be able to grant room-list authority.
    """
    return Frame(
        _off_room_list_image(kind), left=CLIENT_LEFT, top=CLIENT_TOP,
        window_title="KK官方对战平台", hwnd=CLIENT_HWND, role="l0",
    )


def _build_off_room_list_image(kind: str) -> np.ndarray:
    image = _read(FIXTURES / EMPTY).copy()
    height, width = image.shape[:2]
    # Remove the room list's own refresh control (a genuine surface authority).
    image[270:320, 1010:1090] = 0
    y0, y1 = int(height * 0.22), int(height * 0.31)
    x0, x1 = int(width * 0.20), int(width * 0.36)
    if kind == "unselected":
        gray = cv2.cvtColor(image[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
        image[y0:y1, x0:x1] = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    elif kind == "notab":
        image[y0:y1, x0:x1] = 0
    else:  # pragma: no cover - guards a typo in a test
        raise AssertionError(kind)
    return image


# --------------------------------------------------------------------------
# Stable locator
# --------------------------------------------------------------------------

def test_search_locator_holds_across_empty_typed_and_results() -> None:
    """The locator must not be invalidated by the action it is proving."""
    med, _ = _mediator()
    threshold = med.settings.match_threshold
    seen = {}
    for name in (EMPTY, TYPED, RESULTS):
        frame = _frame(name)
        med.invalidate_evidence("new frame")
        icon = med.find_scene(frame, "lobby_search_icon")
        assert icon is not None, f"{name}: stable locator lost"
        assert icon.score >= threshold, (name, icon.score, threshold)
        seen[name] = (icon.x, icon.y)

    # Same control, same place, in every content state.
    assert len(set(seen.values())) == 1, seen


def test_old_search_box_asset_is_the_regressed_failure() -> None:
    """Pin the defect: the shipped box asset dies exactly when text appears."""
    med, _ = _mediator()
    threshold = med.settings.match_threshold
    scores = {}
    for name in (EMPTY, TYPED, RESULTS):
        frame = _frame(name)
        med.invalidate_evidence("new frame")
        hit = med.find_scene(frame, "lobby_search_box")
        scores[name] = hit.score if hit is not None else 0.0

    assert scores[EMPTY] >= threshold
    # Typing the prefix is what pushed it under the production threshold.
    assert scores[TYPED] < threshold
    assert scores[RESULTS] < threshold


def test_search_locator_survives_a_different_client_size_and_session() -> None:
    med, _ = _mediator()
    threshold = med.settings.match_threshold
    for name in (
        "list_empty_search_t000.png",
        "list_search4_all_ingame_t036.png",
        "list_search3_joinable_t038.png",
    ):
        frame = _legacy_frame(name)
        med.invalidate_evidence("new frame")
        icon = med.find_scene(frame, "lobby_search_icon")
        assert icon is not None and icon.score >= threshold, (name, icon)


def test_search_locator_never_resolves_to_the_top_bar_search_box() -> None:
    """KK's global search box carries the same magnifier; geometry excludes it."""
    med, _ = _mediator()
    for name in (EMPTY, TYPED, RESULTS):
        frame = _frame(name)
        med.invalidate_evidence("new frame")
        icon = med.find_scene(frame, "lobby_search_icon")
        assert icon is not None
        # The room-list control sits near y≈0.30h; the top bar is at y≈0.02h.
        assert icon.y > frame.height * 0.16, (name, icon.y)


# --------------------------------------------------------------------------
# Content evidence geometry
# --------------------------------------------------------------------------

def test_content_crop_is_derived_from_the_locator_and_excludes_the_icon() -> None:
    med, _ = _mediator()
    for frame in (_frame(RESULTS), _legacy_frame("list_search4_all_ingame_t036.png")):
        med.invalidate_evidence("new frame")
        icon = med.find_scene(frame, "lobby_search_icon")
        assert icon is not None
        x0, y0, x1, y1 = med._hitch_search_content_bbox(frame, icon, "4")
        # Left-anchored inside the edit box, never reaching the magnifier.
        assert x0 == icon.x - med._SEARCH_BOX_TEXT_W
        assert x1 <= icon.x
        assert y0 < icon.y and y1 > icon.y + icon.h
        # And far tighter than the shipped fixed band it replaces.
        assert (x1 - x0) < med._SEARCH_BOX_TEXT_W


def test_content_crop_widens_with_the_prefix_it_must_prove() -> None:
    """Generic over prefix values: no ``if prefix == "4"`` special case."""
    med, _ = _mediator()
    frame = _frame(RESULTS)
    icon = med.find_scene(frame, "lobby_search_icon")
    widths = {}
    for prefix in ("3", "4", "34", "1234"):
        x0, _, x1, _ = med._hitch_search_content_bbox(frame, icon, prefix)
        widths[prefix] = x1 - x0
    assert widths["3"] == widths["4"]
    assert widths["34"] > widths["4"]
    assert widths["1234"] > widths["34"]


# --------------------------------------------------------------------------
# The mandatory forward transition: empty -> typed -> confirmed -> join
# --------------------------------------------------------------------------

def test_real_visual_transition_reaches_a_join_decision() -> None:
    clock = _Clock()
    ocr = ReplayShadowClient("4")           # what the real worker reads here
    med, exe = _mediator(ocr=ocr)

    # --- Frame A: empty box.  Production locator drives one search action. ---
    _tick(med, _frame(EMPTY), clock)
    searches = exe.kinds("search_text")
    assert len(searches) == 1, exe.calls
    assert searches[0][3] == "4"
    tx = med._hitch_search
    assert tx is not None and tx.awaiting_confirm and not tx.confirmed
    assert med._hitch_prefix_ok() is False

    # The click landed inside the edit box, left of the magnifier.
    icon = med.find_scene(_frame(EMPTY), "lobby_search_icon")
    click_x = searches[0][1] - CLIENT_LEFT
    assert icon.x - med._SEARCH_BOX_TEXT_W < click_x < icon.x

    # --- Frame B: the typed box.  Real crop -> replayed real OCR text. ---
    clock.advance(1.0)
    _tick(med, _frame(TYPED), clock)
    assert ocr.requests, "the postcondition never asked the OCR worker"
    assert med._hitch_search.confirmed is True
    assert med._hitch_prefix_ok() is True
    # A confirming tick still must not use the list it just proved.
    assert len(exe.calls) == 1

    # --- Frame C: a fresh result frame is what unlocks the row scan. ---
    clock.advance(1.0)
    _tick(med, _frame(RESULTS), clock)
    joins = exe.kinds("double_click")
    assert len(joins) == 1, exe.calls
    assert med._hitch_sm.pending_join is True


def test_unicode_search_confirmation_unlocks_join_decision() -> None:
    clock = _Clock()
    med, exe = _mediator(prefix="速", ocr=ReplayShadowClient("速"))

    _tick(med, _frame(EMPTY), clock)
    assert exe.kinds("search_text")[0][3] == "速"

    clock.advance(1.0)
    _tick(med, _frame(TYPED), clock)
    assert med._hitch_prefix_ok() is True

    clock.advance(1.0)
    _tick(med, _frame(RESULTS), clock)
    assert len(exe.kinds("double_click")) == 1
    assert med._hitch_sm.pending_join is True


def test_confirmation_reads_the_derived_crop_not_a_fixed_band() -> None:
    clock = _Clock()
    ocr = ReplayShadowClient("4")
    med, _ = _mediator(ocr=ocr)
    _tick(med, _frame(EMPTY), clock)
    clock.advance(1.0)
    _tick(med, _frame(TYPED), clock)

    frame = _frame(TYPED)
    med.invalidate_evidence("new frame")
    icon = med.find_scene(frame, "lobby_search_icon")
    expected = med._hitch_search_content_bbox(frame, icon, "4")
    assert ocr.requests[0] == expected
    # The shipped band that produced "a" on this very frame.
    assert ocr.requests[0] != (1092, 245, 1292, 302)


# --------------------------------------------------------------------------
# The incident itself: OCR reads "a"
# --------------------------------------------------------------------------

def test_incident_ocr_a_never_confirms_and_never_joins() -> None:
    """The recorded failure must stay a failure — and must stay bounded."""
    clock = _Clock()
    ocr = ReplayShadowClient("a")           # the exact incident reading
    med, exe = _mediator(ocr=ocr)
    med._hitch_sm.search_timeout_s = 60.0

    frames = {0: EMPTY, 1: TYPED}
    step = 0
    for step in range(200):
        _tick(med, _frame(frames.get(step, RESULTS)), clock)
        clock.advance(1.0)
        if med._hitch_sm.phase is HitchPhase.SLEEP_RETRY:
            break

    assert med._hitch_prefix_ok() is False
    assert med._hitch_search is None
    assert exe.kinds("double_click") == [], "joined on an unproven search"
    # Bounded, and by the architecture's own safe baseline: budget spent ->
    # HitchSearchSM reached -> GO_HOME -> lobby home -> sleep retry.
    assert med._hitch_sm.phase is HitchPhase.SLEEP_RETRY
    assert med._hitch_sm.sleep_until > clock.now
    assert clock.now - 1000.0 < 2 * med._hitch_sm.search_timeout_s
    # It retried the input rather than freezing after the first failure...
    assert len(exe.kinds("search_text")) > 1
    # ...but the retries were throttled by the cooldown, not spun per tick.
    assert len(exe.kinds("search_text")) < step / 3
    # Every attempt read the tight derived crop, never the shipped band.
    assert ocr.requests and all(r != (1092, 245, 1292, 302) for r in ocr.requests)


def test_failed_confirmation_can_retype_because_the_locator_survives() -> None:
    """The shipped build could not do this: the locator was gone by now."""
    clock = _Clock()
    ocr = ReplayShadowClient("a")
    med, exe = _mediator(ocr=ocr)

    _tick(med, _frame(EMPTY), clock)
    assert len(exe.kinds("search_text")) == 1

    # Burn the confirmation window on the typed frame.
    for _ in range(5):
        clock.advance(1.0)
        _tick(med, _frame(TYPED), clock)
    assert med._hitch_search is not None
    assert med._hitch_search.awaiting_confirm is False
    assert med._hitch_search.confirmed is False

    # Cooldown holds input back but observation continues.
    assert len(exe.kinds("search_text")) == 1

    # After the cooldown the same control is still locatable -> retype.
    for _ in range(8):
        clock.advance(1.0)
        _tick(med, _frame(TYPED), clock)
    assert len(exe.kinds("search_text")) == 2


def test_retry_does_not_refill_the_operation_budget() -> None:
    clock = _Clock()
    med, _ = _mediator(ocr=ReplayShadowClient("a"))
    _tick(med, _frame(EMPTY), clock)
    opened = med._hitch_search.opened_at
    started = med._hitch_sm.search_started_at

    for _ in range(30):
        clock.advance(1.0)
        _tick(med, _frame(TYPED), clock)

    # Same operation: neither a retype nor a successful input restarts it.
    assert med._hitch_sm.search_started_at == started
    if med._hitch_search is not None:
        assert med._hitch_search.opened_at == opened


def test_budget_is_armed_even_when_the_locator_is_never_found() -> None:
    """A missing locator used to be an unbounded early return."""
    clock = _Clock()
    med, exe = _mediator(ocr=ReplayShadowClient("4"))
    med._hitch_sm.search_timeout_s = 30.0
    # The room-list tab stays visible (and still authorises the subflow on
    # its own evidence); only the search control is painted out.
    frame = _frame(EMPTY)
    blanked = frame.bgr.copy()
    blanked[240:320, 1050:1332] = 0
    probe = Frame(
        blanked, left=CLIENT_LEFT, top=CLIENT_TOP,
        window_title="KK官方对战平台", hwnd=CLIENT_HWND, role="l0",
    )
    med.invalidate_evidence("probe")
    assert med._lobby_room_list_evidence(probe) is True
    assert med.find_scene(probe, "lobby_search_icon") is None

    for _ in range(80):
        hidden = Frame(
            blanked, left=CLIENT_LEFT, top=CLIENT_TOP,
            window_title="KK官方对战平台", hwnd=CLIENT_HWND, role="l0",
        )
        _tick(med, hidden, clock)
        clock.advance(1.0)
        if med._hitch_sm.phase is HitchPhase.SLEEP_RETRY:
            break

    assert exe.kinds("search_text") == []
    assert med._hitch_prefix_ok() is False
    # Bounded: it left the subflow for the safe baseline instead of
    # printing "未识别搜索框，零输入等待" forever, which is what the
    # shipped build did for the last 84 seconds of the incident run.
    assert med._hitch_sm.phase is HitchPhase.SLEEP_RETRY
    assert clock.now - 1000.0 < 60.0


# --------------------------------------------------------------------------
# Search transaction lifecycle
# --------------------------------------------------------------------------

def test_time_alone_never_confirms_a_search() -> None:
    clock = _Clock()
    med, _ = _mediator(ocr=ReplayShadowClient("a"))
    _tick(med, _frame(EMPTY), clock)
    for _ in range(40):
        clock.advance(2.0)
        _tick(med, _frame(RESULTS), clock)
        assert med._hitch_prefix_ok() is False


def test_unavailable_ocr_never_confirms_a_search() -> None:
    clock = _Clock()
    med, _ = _mediator(ocr=ReplayShadowClient("4", status="unavailable"))
    _tick(med, _frame(EMPTY), clock)
    clock.advance(1.0)
    _tick(med, _frame(TYPED), clock)
    assert med._hitch_prefix_ok() is False


def test_missing_ocr_client_never_confirms_a_search() -> None:
    clock = _Clock()
    med, _ = _mediator(ocr=None)
    _tick(med, _frame(EMPTY), clock)
    clock.advance(1.0)
    _tick(med, _frame(TYPED), clock)
    assert med._hitch_prefix_ok() is False


def test_confirmation_budget_starts_after_the_input_action_completes() -> None:
    """A slow SendInput must not eat the visual confirmation window."""
    clock = _Clock()
    med, _ = _mediator(ocr=ReplayShadowClient("a"))

    slow = _Clock(clock.now)

    class SlowExecutor(FakeInputExecutor):
        def search_text(self, x, y, text, target_hwnd=None, dry_run=True):
            slow.advance(1.3)          # measured 1298 ms on the real client
            return super().search_text(x, y, text, target_hwnd, dry_run)

    exe = SlowExecutor()
    med.executor = exe
    # ``time.time`` advances during the action, exactly like production.
    med._last_frame = _frame(EMPTY)
    frame = _frame(EMPTY)
    with patch("shuabao.mediator.time.time", slow):
        med._tick_lobby_hitch(frame, "LOBBY_ROOM")

    tx = med._hitch_search
    assert tx is not None and tx.typed_at is not None
    # Stamped after the action, so the whole budget is still available.
    assert tx.typed_at >= tx.opened_at + 1.3


def test_prefix_rotation_drops_a_confirmed_search() -> None:
    clock = _Clock()
    med, _ = _mediator(ocr=ReplayShadowClient("4"))
    _tick(med, _frame(EMPTY), clock)
    clock.advance(1.0)
    _tick(med, _frame(TYPED), clock)
    assert med._hitch_prefix_ok() is True

    med._hitch_sm.prefix = "3"
    clock.advance(1.0)
    _tick(med, _frame(RESULTS), clock)
    # What the box proves about "4" says nothing about "3".
    assert med._hitch_prefix_ok() is False


def test_room_exit_requires_fresh_visual_proof_even_though_kk_keeps_the_text() -> None:
    clock = _Clock()
    med, _ = _mediator(ocr=ReplayShadowClient("4"))
    _tick(med, _frame(EMPTY), clock)
    clock.advance(1.0)
    _tick(med, _frame(TYPED), clock)
    assert med._hitch_prefix_ok() is True

    med._hitch_after_exit(clock.now)
    assert med._hitch_search is None
    assert med._hitch_prefix_ok() is False


def test_rejected_search_input_leaves_no_pending_proof() -> None:
    clock = _Clock()
    med, exe = _mediator(ocr=ReplayShadowClient("4"), executor=FakeInputExecutor(succeed=False))
    _tick(med, _frame(EMPTY), clock)
    tx = med._hitch_search
    assert tx is None or tx.awaiting_confirm is False
    assert med._hitch_prefix_ok() is False
    assert exe.kinds("double_click") == []


def test_startup_on_a_prefilled_box_still_proves_the_prefix_itself() -> None:
    """Text left in the box by an earlier run is not this run's evidence."""
    clock = _Clock()
    ocr = ReplayShadowClient("4")
    med, exe = _mediator(ocr=ocr)

    # First frame already shows "4" and its filtered rows.
    _tick(med, _frame(RESULTS), clock)
    # It typed anyway rather than adopting the text it found...
    assert len(exe.kinds("search_text")) == 1
    assert med._hitch_prefix_ok() is False
    # ...and no row was touched before the postcondition held.
    assert exe.kinds("double_click") == []

    clock.advance(1.0)
    _tick(med, _frame(RESULTS), clock)
    assert med._hitch_prefix_ok() is True


def test_client_size_change_invalidates_a_confirmed_search() -> None:
    clock = _Clock()
    med, _ = _mediator(ocr=ReplayShadowClient("4"))
    _tick(med, _frame(EMPTY), clock)
    clock.advance(1.0)
    _tick(med, _frame(TYPED), clock)
    assert med._hitch_prefix_ok() is True

    # Same prefix, different client surface: the old proof does not transfer.
    clock.advance(1.0)
    _tick(med, _legacy_frame("list_search4_all_ingame_t036.png"), clock)
    assert med._hitch_prefix_ok() is False


def test_window_identity_change_invalidates_a_confirmed_search() -> None:
    clock = _Clock()
    med, _ = _mediator(ocr=ReplayShadowClient("4"))
    _tick(med, _frame(EMPTY), clock)
    clock.advance(1.0)
    _tick(med, _frame(TYPED), clock)
    assert med._hitch_prefix_ok() is True

    other = _frame(RESULTS)
    moved = Frame(
        other.bgr, left=CLIENT_LEFT, top=CLIENT_TOP,
        window_title="KK官方对战平台", hwnd=CLIENT_HWND + 1, role="l0",
    )
    clock.advance(1.0)
    _tick(med, moved, clock)
    assert med._hitch_prefix_ok() is False


def test_refresh_click_alone_does_not_grant_row_eligibility() -> None:
    """A successful Refresh is an input, not proof that the filter applied."""
    clock = _Clock()
    med, exe = _mediator(ocr=ReplayShadowClient("a"))
    med._hitch_refresh_required = True

    for _ in range(20):
        _tick(med, _frame(RESULTS), clock)
        clock.advance(1.0)

    assert med._hitch_prefix_ok() is False
    assert exe.kinds("double_click") == []


# --------------------------------------------------------------------------
# Surface authority is not the locator's job
# --------------------------------------------------------------------------

def test_search_icon_alone_never_grants_room_list_authority() -> None:
    """Locating the search control says nothing about which surface owns it."""
    med, _ = _mediator()
    for kind in ("unselected", "notab"):
        frame = _off_room_list_frame(kind)
        med.invalidate_evidence("new frame")
        icon = med.find_scene(frame, "lobby_search_icon")
        assert icon is not None and icon.score >= med.settings.match_threshold, kind
        med.invalidate_evidence("new frame")
        assert med._lobby_room_list_evidence(frame) is False, kind


def test_real_room_list_frames_still_carry_authority() -> None:
    med, _ = _mediator()
    for name in (EMPTY, TYPED, RESULTS):
        frame = _frame(name)
        med.invalidate_evidence("new frame")
        assert med._lobby_room_list_evidence(frame) is True, name


def test_an_unproven_surface_never_reaches_the_search_input() -> None:
    clock = _Clock()
    med, exe = _mediator(ocr=ReplayShadowClient("4"))
    for _ in range(5):
        _tick(med, _off_room_list_frame("unselected"), clock)
        clock.advance(1.0)
    assert exe.kinds("search_text") == []
    assert med._hitch_prefix_ok() is False


# --------------------------------------------------------------------------
# The tab stage shares the search operation's durable budget
# --------------------------------------------------------------------------

def test_tab_acquisition_arms_the_same_operation_budget() -> None:
    clock = _Clock()
    med, _ = _mediator(ocr=ReplayShadowClient("4"))
    assert med._hitch_sm.search_started_at is None
    _tick(med, _off_room_list_frame("notab"), clock)
    # The clock starts at the tab, not at the search box.
    assert med._hitch_sm.search_started_at == clock.now


def test_tab_never_found_does_not_wait_forever() -> None:
    clock = _Clock()
    med, exe = _mediator(ocr=ReplayShadowClient("4"))
    med._hitch_sm.search_timeout_s = 20.0
    for _ in range(120):
        _tick(med, _off_room_list_frame("notab"), clock)
        clock.advance(1.0)
        if med._hitch_sm.phase is HitchPhase.SLEEP_RETRY:
            break
    assert med._hitch_sm.phase is HitchPhase.SLEEP_RETRY
    assert med._hitch_sm.sleep_until > clock.now
    assert clock.now - 1000.0 < 80.0
    # The tab was never reachable, so it was never clicked...
    assert ("click", 911, 281) not in exe.calls
    # ...and an unproven surface was never searched or joined.
    assert exe.kinds("search_text") == []
    assert exe.kinds("double_click") == []
    assert med._hitch_prefix_ok() is False


def test_unconfirmed_go_home_backs_off_instead_of_reclicking_forever() -> None:
    """A navigation click is an input, not a navigation."""
    clock = _Clock()
    med, exe = _mediator(ocr=ReplayShadowClient("4"))
    med._hitch_sm.search_timeout_s = 20.0
    for _ in range(120):
        _tick(med, _off_room_list_frame("notab"), clock)
        clock.advance(1.0)
        if med._hitch_sm.phase is HitchPhase.SLEEP_RETRY:
            break
    assert med._hitch_sm.phase is HitchPhase.SLEEP_RETRY
    # The lobby page never appeared, so GO_HOME must not have been re-sent
    # on its cooldown indefinitely.
    assert len(exe.kinds("click")) <= 3, exe.calls


def test_tab_click_that_never_switches_is_bounded_not_spun() -> None:
    clock = _Clock()
    med, exe = _mediator(ocr=ReplayShadowClient("4"))
    med._hitch_sm.search_timeout_s = 30.0
    step = 0
    for step in range(120):
        _tick(med, _off_room_list_frame("unselected"), clock)
        clock.advance(1.0)
        if med._hitch_sm.phase is HitchPhase.SLEEP_RETRY:
            break
    clicks = [c for c in exe.calls if c[0] == "click"]
    assert clicks, "the tab was reachable, so it should have been tried"
    # Throttled by the cooldown rather than re-clicked every tick...
    assert len(clicks) < (step + 1) / 3, (len(clicks), step + 1)
    # ...and the whole stage stayed inside the operation budget.
    assert med._hitch_sm.phase is HitchPhase.SLEEP_RETRY
    assert clock.now - 1000.0 < 90.0
    assert exe.kinds("search_text") == []
    assert exe.kinds("double_click") == []


def test_tab_retry_honours_the_input_cooldown() -> None:
    clock = _Clock()
    med, exe = _mediator(ocr=ReplayShadowClient("4"))
    frame = _off_room_list_frame("unselected")

    _tick(med, frame, clock)
    assert len(exe.kinds("click")) == 1
    cooldown_until = med._hitch_sm.next_allowed_at
    assert cooldown_until > clock.now

    # Observation keeps running every tick; the click does not.
    while clock.now + 1.0 < cooldown_until:
        clock.advance(1.0)
        _tick(med, frame, clock)
        assert len(exe.kinds("click")) == 1, clock.now

    # Input is allowed again exactly when the cooldown elapses.
    clock.advance(1.0)
    assert clock.now == cooldown_until
    _tick(med, frame, clock)
    assert len(exe.kinds("click")) == 2


def test_tab_budget_is_not_refilled_by_retrying() -> None:
    clock = _Clock()
    med, _ = _mediator(ocr=ReplayShadowClient("4"))
    frame = _off_room_list_frame("unselected")
    _tick(med, frame, clock)
    started = med._hitch_sm.search_started_at
    for _ in range(25):
        clock.advance(1.0)
        _tick(med, frame, clock)
    assert med._hitch_sm.search_started_at == started


def test_tab_budget_exhaustion_never_fakes_the_room_list() -> None:
    clock = _Clock()
    med, exe = _mediator(ocr=ReplayShadowClient("4"))
    med._hitch_sm.search_timeout_s = 15.0
    for _ in range(50):
        _tick(med, _off_room_list_frame("notab"), clock)
        clock.advance(1.0)
        # At no point may an unproven surface become searchable or joinable.
        assert med._hitch_prefix_ok() is False
    assert exe.kinds("search_text") == []
    assert exe.kinds("double_click") == []


def test_full_tab_then_search_then_confirm_then_join_chain() -> None:
    """The whole operation, starting one stage earlier than before."""
    clock = _Clock()
    ocr = ReplayShadowClient("4")
    med, exe = _mediator(ocr=ocr)

    # Stage 1: the room list is not up yet, so the tab is clicked.
    _tick(med, _off_room_list_frame("unselected"), clock)
    assert len(exe.kinds("click")) == 1
    assert exe.kinds("search_text") == []

    # Stage 2: the tab switched; the search control is located and typed.
    # The tab click armed a cooldown, so wait it out exactly as production does.
    clock.advance(med._hitch_sm.refresh_s_min + 1.0)
    _tick(med, _frame(EMPTY), clock)
    assert len(exe.kinds("search_text")) == 1

    # Stage 3: the typed box proves the prefix through the real crop.
    clock.advance(1.0)
    _tick(med, _frame(TYPED), clock)
    assert med._hitch_prefix_ok() is True

    # Stage 4: a fresh result frame unlocks the row scan and the join.
    clock.advance(1.0)
    _tick(med, _frame(RESULTS), clock)
    assert len(exe.kinds("double_click")) == 1
    assert med._hitch_sm.pending_join is True

    # One budget covered all four stages.
    assert med._hitch_sm.search_started_at == 1000.0


# --------------------------------------------------------------------------
# Safety: dangerous ambiguity stays fail-closed
# --------------------------------------------------------------------------

def test_black_frame_produces_zero_input() -> None:
    clock = _Clock()
    med, exe = _mediator(ocr=ReplayShadowClient("4"))
    black = Frame(
        np.zeros((945, 1332, 3), dtype=np.uint8),
        left=CLIENT_LEFT, top=CLIENT_TOP,
        window_title="KK官方对战平台", hwnd=CLIENT_HWND, role="l0",
    )
    for _ in range(20):
        _tick(med, black, clock)
        clock.advance(1.0)
    assert exe.calls == [], exe.calls
    assert med._hitch_prefix_ok() is False


def test_join_is_impossible_without_a_confirmed_search() -> None:
    clock = _Clock()
    med, exe = _mediator(ocr=ReplayShadowClient("a"))
    # The result frame really does contain a joinable row...
    assert med._find_hitch_joinable_row(_frame(RESULTS)) is not None
    med.invalidate_evidence("new frame")
    # ...but an unconfirmed search must keep it ineligible.
    for _ in range(15):
        _tick(med, _frame(RESULTS), clock)
        clock.advance(1.0)
    assert exe.kinds("double_click") == []


# --------------------------------------------------------------------------
# Fixture provenance
# --------------------------------------------------------------------------

def test_incident_fixtures_declare_their_provenance() -> None:
    index = json.loads((FIXTURES / "INDEX.json").read_text(encoding="utf-8"))
    assert index["client_crop"] == {"xy": [559, 36], "wh": [1332, 945]}
    assert index["incident_production_ocr"]["raw_text"] == "a"
    assert index["locator_asset"] == "assets/Images/lobby/lobby_search_icon.png"
    for item in index["items"]:
        assert (FIXTURES / item["file"]).is_file()
