"""Public-bag deposit geometry and fail-closed transfer state machine.

Ground truth: ``docs/gt_lab/PUBLIC_BAG_GT_SPEC_20260909.md``.

Every constant below was measured from the 2026-09-09 live capture
``_public_bag_gt_20260909/keyframes/t12_0.png`` after cropping the KK client
rect out of the 1920x1080 recording.  The crop origin (160, 102) and the
1600x900 client size are not guesses: the same run's own log prints
``capture tick 1600x900 @(160,102)`` for every tick.

Section 5 of the spec forbids hard-coded screen coordinates.  Nothing here is
one: the panel origin comes from a matched anchor at run time and every slot is
``panel_origin + margin + [col * step_x, row * step_y]``, scaled by the frame's
own 16:9 scale factor.

Operation order
---------------
The spec lists ``[2] right-click source`` before ``[3] press B``.  The real
2026-09-09 gesture capture runs the other way round: the bag page is opened
first (t11.5), the source item is right-clicked inside the panel's 物品栏 at
t13.5, and the carried item lands on the public grid at t14.  We follow the
captured gesture, because the always-visible bottom-right HUD strip is labelled
``右击十连`` — right-clicking *there* is a ten-shot use gesture, not a pickup,
and using a team pill is exactly the loss the spec's input-safety invariant
exists to prevent.  Every spec step is still performed, and step 3 is
explicitly conditional ("press B **if** the public bag view is not visible").

The one left click this machine can ever emit lands on a slot that
``BagLayout.public_slot_rect`` produced and that was verified empty in a fresh
frame.  Personal-bag and 物品栏 slots are right-click-only by construction.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum, auto


# --- baseline geometry (1600x900 client), measured from the GT keyframe ------

BASELINE_WIDTH = 1600
BASELINE_HEIGHT = 900

PANEL_WIDTH = 677.0
PANEL_HEIGHT = 491.0

GRID_ROWS = 8
GRID_COLS = 7
SLOT_STEP_X = 46.75
SLOT_STEP_Y = 43.5
#: Inset applied to every slot rect so the separator bands never leak into a
#: slot's occupancy sample.
SLOT_INSET = 5.0

#: Grid origins relative to the panel origin (top-left of the dialog frame).
PERSONAL_GRID_MARGIN = (3.75, 40.0)
PUBLIC_GRID_MARGIN = (343.0, 40.0)

#: 物品栏 (item bar) — the six source slots along the bottom of the panel.
ITEM_BAR_MARGIN = (20.0, 433.0)
ITEM_BAR_STEP_X = 51.6
ITEM_BAR_SLOTS = 6
ITEM_BAR_SLOT_WIDTH = 40.0
ITEM_BAR_SLOT_HEIGHT = 41.0

#: Anchor template top-left offsets relative to the panel origin.
ANCHOR_MARGINS: dict[str, tuple[float, float]] = {
    "bag/public_bag_title": (461.0, 11.0),
    "bag/bag_sell_equipment": (229.0, 397.0),
}

#: Search windows for the two anchors, as frame ratios.  Wide enough for the
#: panel drift seen between recordings, narrow enough to stay page-specific.
ANCHOR_ROIS: dict[str, tuple[float, float, float, float]] = {
    "bag/public_bag_title": (0.60, 0.04, 0.90, 0.22),
    "bag/bag_sell_equipment": (0.46, 0.42, 0.70, 0.64),
    # The right-edge HUD carries clickable twins of the B / Z hotkeys.  Mouse
    # input is the only injection path with live evidence in this project, so
    # these buttons are how the bag actually gets opened.
    "bag/bag_toggle_button": (0.92, 0.78, 0.98, 0.88),
    "bag/hud_pickup_button": (0.92, 0.73, 0.98, 0.83),
}

#: Click point offsets inside those button templates (their own centres).
HUD_BUTTON_TEMPLATES = ("bag/bag_toggle_button", "bag/hud_pickup_button")

#: 物品栏 cells carry a drawn border, so their *full* rect never looks flat
#: (empty slot std 20-24).  Probing the inner area instead separates cleanly:
#: empty 1.6-2.0, occupied 42-76.
ITEM_BAR_PROBE_INSET = 8.0

#: Occupancy thresholds, calibrated on the GT keyframes and on the 20260910
#: multiplayer capture (背包.mp4).  Measured on the inner probe rect:
#:
#:   empty  public / personal / 物品栏 : std 1.6-8.2,  saturated 0
#:   occupied                          : std 42-76,    saturated 103-823
#:   mouse cursor over an empty slot   : std 24-76,    saturated <=118
#:
#: Empty and occupied are therefore two *separate* positive tests, and a
#: cursor-occluded cell answers neither — it is skipped, not guessed.
EMPTY_SLOT_MAX_STD = 12.0
EMPTY_SLOT_MAX_SATURATED = 200.0
OCCUPIED_SLOT_MIN_STD = 30.0
OCCUPIED_SLOT_MIN_SATURATED = 140.0
SLOT_SATURATION_MIN = 110
SLOT_VALUE_MIN = 80


def _int_rect(x0: float, y0: float, x1: float, y1: float) -> tuple[int, int, int, int]:
    return (int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1)))


@dataclass(frozen=True)
class BagLayout:
    """Slot geometry for one observed bag panel, in frame pixel coordinates."""

    origin_x: float
    origin_y: float
    scale: float = 1.0

    @classmethod
    def from_anchor(
        cls,
        anchor_name: str,
        anchor_x: float,
        anchor_y: float,
        scale: float = 1.0,
    ) -> "BagLayout | None":
        margin = ANCHOR_MARGINS.get(anchor_name)
        if margin is None or scale <= 0.0:
            return None
        return cls(anchor_x - margin[0] * scale, anchor_y - margin[1] * scale, scale)

    # -- structural checks ---------------------------------------------------

    def anchor_origin(self, anchor_name: str) -> tuple[float, float] | None:
        margin = ANCHOR_MARGINS.get(anchor_name)
        if margin is None:
            return None
        return (
            self.origin_x + margin[0] * self.scale,
            self.origin_y + margin[1] * self.scale,
        )

    def anchor_matches(
        self, anchor_name: str, anchor_x: float, anchor_y: float, tolerance: float = 8.0
    ) -> bool:
        """True when a second anchor sits where this layout predicts it does.

        Two independent anchors agreeing on one panel origin is what separates a
        real bag page from a lucky single-template hit on a busy battlefield.
        """
        expected = self.anchor_origin(anchor_name)
        if expected is None:
            return False
        limit = max(1.0, tolerance * self.scale)
        return abs(expected[0] - anchor_x) <= limit and abs(expected[1] - anchor_y) <= limit

    # -- rects ---------------------------------------------------------------

    def panel_rect(self) -> tuple[int, int, int, int]:
        return _int_rect(
            self.origin_x,
            self.origin_y,
            self.origin_x + PANEL_WIDTH * self.scale,
            self.origin_y + PANEL_HEIGHT * self.scale,
        )

    def _grid_rect(
        self, margin: tuple[float, float], row: int, col: int
    ) -> tuple[int, int, int, int] | None:
        if not (0 <= row < GRID_ROWS and 0 <= col < GRID_COLS):
            return None
        x0 = self.origin_x + (margin[0] + SLOT_STEP_X * col) * self.scale
        y0 = self.origin_y + (margin[1] + SLOT_STEP_Y * row) * self.scale
        inset = SLOT_INSET * self.scale
        return _int_rect(
            x0 + inset,
            y0 + inset,
            x0 + (SLOT_STEP_X * self.scale) - inset,
            y0 + (SLOT_STEP_Y * self.scale) - inset,
        )

    def public_slot_rect(self, row: int, col: int) -> tuple[int, int, int, int] | None:
        return self._grid_rect(PUBLIC_GRID_MARGIN, row, col)

    def personal_slot_rect(self, row: int, col: int) -> tuple[int, int, int, int] | None:
        return self._grid_rect(PERSONAL_GRID_MARGIN, row, col)

    def item_bar_slot_rect(self, index: int) -> tuple[int, int, int, int] | None:
        if not (0 <= index < ITEM_BAR_SLOTS):
            return None
        x0 = self.origin_x + (ITEM_BAR_MARGIN[0] + ITEM_BAR_STEP_X * index) * self.scale
        y0 = self.origin_y + ITEM_BAR_MARGIN[1] * self.scale
        return _int_rect(
            x0,
            y0,
            x0 + ITEM_BAR_SLOT_WIDTH * self.scale,
            y0 + ITEM_BAR_SLOT_HEIGHT * self.scale,
        )

    # -- centers -------------------------------------------------------------

    @staticmethod
    def _center(rect: tuple[int, int, int, int] | None) -> tuple[int, int] | None:
        if rect is None:
            return None
        x0, y0, x1, y1 = rect
        return ((x0 + x1) // 2, (y0 + y1) // 2)

    def public_slot_center(self, row: int, col: int) -> tuple[int, int] | None:
        return self._center(self.public_slot_rect(row, col))

    def personal_slot_center(self, row: int, col: int) -> tuple[int, int] | None:
        return self._center(self.personal_slot_rect(row, col))

    def item_bar_slot_center(self, index: int) -> tuple[int, int] | None:
        return self._center(self.item_bar_slot_rect(index))

    def item_bar_slot_probe_rect(self, index: int) -> tuple[int, int, int, int] | None:
        """Inner area of a 物品栏 slot, excluding its drawn border."""
        rect = self.item_bar_slot_rect(index)
        if rect is None:
            return None
        inset = int(round(ITEM_BAR_PROBE_INSET * self.scale))
        x0, y0, x1, y1 = rect
        if x1 - x0 <= 2 * inset or y1 - y0 <= 2 * inset:
            return rect
        return (x0 + inset, y0 + inset, x1 - inset, y1 - inset)

    # -- lookups -------------------------------------------------------------

    def item_bar_slot_index(self, x: float, y: float) -> int | None:
        """Map a template hit back to the 物品栏 slot that contains it."""
        for index in range(ITEM_BAR_SLOTS):
            rect = self.item_bar_slot_rect(index)
            if rect is None:
                continue
            x0, y0, x1, y1 = rect
            if x0 <= x <= x1 and y0 <= y <= y1:
                return index
        return None

    def public_slots(self):
        """Row-major deposit order — the game fills the grid the same way."""
        for row in range(GRID_ROWS):
            for col in range(GRID_COLS):
                yield row, col

    def inside_public_grid(self, x: float, y: float) -> bool:
        for row, col in self.public_slots():
            rect = self.public_slot_rect(row, col)
            if rect is None:
                continue
            x0, y0, x1, y1 = rect
            if x0 <= x <= x1 and y0 <= y <= y1:
                return True
        return False

    def inside_personal_surface(self, x: float, y: float) -> bool:
        """True for the personal grid and the 物品栏 — the never-left-click area."""
        for row, col in self.public_slots():
            rect = self.personal_slot_rect(row, col)
            if rect is None:
                continue
            x0, y0, x1, y1 = rect
            if x0 <= x <= x1 and y0 <= y <= y1:
                return True
        for index in range(ITEM_BAR_SLOTS):
            rect = self.item_bar_slot_rect(index)
            if rect is None:
                continue
            x0, y0, x1, y1 = rect
            if x0 <= x <= x1 and y0 <= y <= y1:
                return True
        return False


# --- transfer state machine ----------------------------------------------------


class PublicBagPhase(Enum):
    IDLE = auto()
    BAG_OPEN_REQUESTED = auto()
    BAG_VISIBLE = auto()
    SOURCE_SELECTED = auto()
    DEPOSIT_REQUESTED = auto()
    ABORTED = auto()


#: Phases in which a left click may be dispatched at all.  Anything else must
#: produce zero input.
_LEFT_CLICK_PHASES = frozenset({PublicBagPhase.SOURCE_SELECTED})


@dataclass(frozen=True)
class PublicBagFSM:
    """One item in flight at a time, with the bag page held open between them.

    The 20260910 multiplayer capture shows the operator's real cadence: press B
    once, then keep depositing for the rest of the round without ever closing
    the panel (the page is up from t5 to t17 while the fight continues, and the
    public grid fills (0,0) -> (0,1) -> (0,2) as loot arrives).  So a confirmed
    deposit returns to BAG_VISIBLE, not to a close-and-reopen cycle.

    The machine never returns a click target of its own - it only says which
    step is authorised.  Coordinates come from :class:`BagLayout`, so a phase
    can never authorise a click on a personal slot.
    """

    phase: PublicBagPhase = PublicBagPhase.IDLE
    source_id: str = ""
    #: "item_bar" or "personal" - which surface the carried item came from.
    source_kind: str = ""
    #: 物品栏 slot index, or the personal grid cell as (row, col).
    source_slot: int = -1
    source_cell: tuple[int, int] | None = None
    target_slot: tuple[int, int] | None = None
    deadline: float = 0.0
    deposits: int = 0
    aborts: int = 0
    cooldown_until: float = 0.0
    abort_reason: str = ""
    opened_by_us: bool = False

    # -- queries -------------------------------------------------------------

    @property
    def active(self) -> bool:
        return self.phase not in (PublicBagPhase.IDLE, PublicBagPhase.ABORTED)

    @property
    def carrying(self) -> bool:
        """True while an item is attached to the cursor."""
        return self.phase in (PublicBagPhase.SOURCE_SELECTED, PublicBagPhase.DEPOSIT_REQUESTED)

    def can_left_click(self) -> bool:
        return self.phase in _LEFT_CLICK_PHASES

    def can_start(self, now: float) -> bool:
        """May we spend a B press to open the page?"""
        return self.phase is PublicBagPhase.IDLE and now >= self.cooldown_until

    def can_adopt_open_page(self) -> bool:
        """An already-open page costs no input, so no cooldown applies.

        Offline replay of 背包.mp4 caught this: after one open timed out, the
        20s cooldown kept the machine IDLE for the rest of the clip even though
        the panel was up and full of loot the whole time.
        """
        return self.phase is PublicBagPhase.IDLE

    # -- transitions ---------------------------------------------------------

    def request_bag_open(self, now: float, *, timeout_s: float = 5.0) -> "PublicBagFSM":
        """Step 3: the B key was accepted while the bag page was not visible."""
        if self.phase is not PublicBagPhase.IDLE:
            return self
        return replace(
            self,
            phase=PublicBagPhase.BAG_OPEN_REQUESTED,
            deadline=now + max(0.0, timeout_s),
            opened_by_us=True,
        )

    def confirm_bag_visible(self, now: float) -> "PublicBagFSM":
        """Steps 4+5: a fresh frame carries both the bag page and the public bag.

        BAG_VISIBLE is the resting state and carries no deadline: an idle round
        with nothing to deposit must not be an abort.
        """
        if self.phase not in (
            PublicBagPhase.IDLE,
            PublicBagPhase.BAG_OPEN_REQUESTED,
            PublicBagPhase.DEPOSIT_REQUESTED,
        ):
            return self
        return replace(
            self,
            phase=PublicBagPhase.BAG_VISIBLE,
            source_id="",
            source_kind="",
            source_slot=-1,
            source_cell=None,
            target_slot=None,
            deadline=0.0,
        )

    def select_source(
        self,
        source_id: str,
        now: float,
        *,
        kind: str = "item_bar",
        slot_index: int = -1,
        cell: tuple[int, int] | None = None,
        timeout_s: float = 6.0,
    ) -> "PublicBagFSM":
        """Steps 1+2: the source was fresh-confirmed and right-clicked."""
        if self.phase is not PublicBagPhase.BAG_VISIBLE:
            return self
        return replace(
            self,
            phase=PublicBagPhase.SOURCE_SELECTED,
            source_id=str(source_id),
            source_kind=str(kind),
            source_slot=int(slot_index),
            source_cell=cell,
            deadline=now + max(0.0, timeout_s),
        )

    def request_deposit(
        self, row: int, col: int, now: float, *, timeout_s: float = 4.0
    ) -> "PublicBagFSM":
        """Step 7: the left click on a verified empty public slot was accepted."""
        if self.phase is not PublicBagPhase.SOURCE_SELECTED:
            return self
        return replace(
            self,
            phase=PublicBagPhase.DEPOSIT_REQUESTED,
            target_slot=(int(row), int(col)),
            deadline=now + max(0.0, timeout_s),
        )

    def confirm_deposit(self, now: float) -> "PublicBagFSM":
        """Step 8: a fresh frame proved the transfer; stay on the open page."""
        if self.phase is not PublicBagPhase.DEPOSIT_REQUESTED:
            return self
        return replace(self, deposits=self.deposits + 1).confirm_bag_visible(now)

    def abort(self, reason: str, now: float, *, cooldown_s: float = 20.0) -> "PublicBagFSM":
        if self.phase is PublicBagPhase.ABORTED:
            return self
        return replace(
            self,
            phase=PublicBagPhase.ABORTED,
            aborts=self.aborts + 1,
            abort_reason=str(reason),
            source_id="",
            source_kind="",
            source_slot=-1,
            source_cell=None,
            target_slot=None,
            deadline=now + 3.0,
            cooldown_until=now + max(0.0, cooldown_s),
        )

    def release(self, now: float) -> "PublicBagFSM":
        """Drop the lease and keep the accumulated counters."""
        return PublicBagFSM(
            phase=PublicBagPhase.IDLE,
            deposits=self.deposits,
            aborts=self.aborts,
            cooldown_until=max(self.cooldown_until, now),
        )

    # -- observation ---------------------------------------------------------

    def observe(
        self,
        now: float,
        *,
        bag_visible: bool,
        deposit_confirmed: bool | None = None,
    ) -> "PublicBagFSM":
        """Advance or fail-close on this tick's evidence.

        ``deposit_confirmed`` is tri-state: ``None`` means "not decided yet",
        which keeps DEPOSIT_REQUESTED waiting until its deadline.
        """
        if self.phase is PublicBagPhase.IDLE:
            return self

        if self.phase is PublicBagPhase.BAG_OPEN_REQUESTED:
            if bag_visible:
                return self.confirm_bag_visible(now)
            if now >= self.deadline:
                # B 没落地只是键没生效，不是危险动作：短冷却后重按。
                return self.abort("bag_page_not_visible", now, cooldown_s=5.0)
            return self

        if self.phase is PublicBagPhase.BAG_VISIBLE:
            # Resting state: hold the open page with zero input for as long as
            # the round lasts.  Only losing the page ends the lease.
            if not bag_visible:
                return self.abort("bag_page_lost", now, cooldown_s=2.0)
            return self

        if self.phase is PublicBagPhase.SOURCE_SELECTED:
            if not bag_visible:
                return self.abort("bag_page_lost_while_carrying", now)
            if now >= self.deadline:
                return self.abort("deposit_slot_timeout", now)
            return self

        if self.phase is PublicBagPhase.DEPOSIT_REQUESTED:
            if deposit_confirmed is True:
                return self.confirm_deposit(now)
            if deposit_confirmed is False:
                return self.abort("deposit_postcondition_failed", now)
            if now >= self.deadline:
                return self.abort("deposit_postcondition_timeout", now)
            return self

        if self.phase is PublicBagPhase.ABORTED:
            if now >= self.deadline:
                return self.release(now)
            return self

        return self
