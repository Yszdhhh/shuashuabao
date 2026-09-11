"""大厅蹭车（lobby_hitch）搜房/退房状态机。

可注入时钟与 OCR 文本，测试不需要游戏窗或真实 sidecar。
join_attempts 以本模块的 3 为准（mode_specs 历史值 2 不再采用）。
刷新间隔来自 mode_specs budgets refresh_s_min/refresh_s_max（默认固定 5s）。
"""

from __future__ import annotations

import random
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum

from shuabao.vision.ocr_verifier import (
    MAX_LENGTH,
    NUMERIC_ALPHABET,
    parse_counter,
    verify_expected_text,
)


JOIN_ATTEMPTS = 3
SEARCH_TIMEOUT_S = 120.0
GO_HOME_CONFIRM_S = 10.0
SLEEP_RETRY_S = 120.0
REFRESH_S_MIN = 5.0
REFRESH_S_MAX = 5.0

KICK_MARKERS = ("被踢出", "你已被踢", "踢出房间")
DISSOLVE_MARKERS = ("房间解散", "房间已解散", "队伍已解散", "车队解散")

_PREFIX_RE = re.compile(r"(?:^|[\s,，])([34])(?:\s*/\s*\d|\s*[-－—]\s*\d|/)")


class HitchPhase(str, Enum):
    SEARCH = "search"
    LOBBY_HOME = "lobby_home"
    SLEEP_RETRY = "sleep_retry"



class HitchAction(str, Enum):
    NONE = "none"
    REFRESH = "refresh"
    JOIN = "join"
    GO_HOME = "go_home"
    SLEEP = "sleep"
    RESET = "reset"


def normalize_prefix(value: object) -> str:
    text = str(value or "3").strip()
    return text or "3"


def classify_hitch_ocr(text: str) -> str | None:
    raw = str(text or "")
    if any(marker in raw for marker in KICK_MARKERS):
        return "被踢出"
    if any(marker in raw for marker in DISSOLVE_MARKERS):
        return "房间解散"
    return None


def has_prefix_evidence(text: str, prefix: str) -> bool:
    """Clean observed OCR and delegate expected-value authority to the verifier."""
    normalized = unicodedata.normalize("NFKC", str(text or "")).strip()
    if not normalized or len(normalized) > MAX_LENGTH:
        return False
    expected = unicodedata.normalize("NFKC", str(prefix or "")).strip()
    if not expected or len(expected) > MAX_LENGTH:
        return False
    if not expected.isdecimal():
        return verify_expected_text(normalized, expected)
    compact = "".join(normalized.split())
    counter = parse_counter(compact)
    observed = str(counter[0]) if counter is not None else compact
    return verify_expected_text(
        observed,
        expected,
        allowed_chars=NUMERIC_ALPHABET,
    )


@dataclass
class SearchTransaction:
    """One bounded attempt to make ``prefix`` visibly take effect in the box.

    Replaces the old ``_hitch_prefix_searched`` / ``_hitch_search_pending``
    pair.  Those two booleans could encode the illegal combination "searched
    and still pending"; a single optional transaction cannot.  ``typed_at`` is
    stamped **after** the input action returns, so the visual-confirmation
    budget is never consumed by the seconds ``search_text()`` itself spends
    clicking, clearing and typing.
    """

    prefix: str
    opened_at: float
    #: ``(hwnd, client width, client height)`` this proof belongs to.  A proof
    #: about one surface says nothing about another, so the lobby subflow drops
    #: the transaction when the window identity or client size changes.  ``None``
    #: means "not bound to a surface yet" and never invalidates on its own.
    surface: tuple[object, int, int] | None = None
    typed_at: float | None = None
    confirmed: bool = False

    @property
    def awaiting_confirm(self) -> bool:
        """True once the text was typed but the box has not yet proven it."""
        return self.typed_at is not None and not self.confirmed

    def reopen_for_retype(self) -> None:
        """Drop the unconfirmed attempt, keeping this operation's start time."""
        self.typed_at = None


@dataclass
class HitchDecision:
    action: HitchAction
    phase: HitchPhase
    reason: str
    attempts: int
    elapsed_s: float


class HitchSearchSM:
    """搜房状态机；生产默认有界，实机整链可持续到准备成功。"""

    def __init__(
        self,
        prefix: str = "3",
        *,
        prefixes: list[str] | tuple[str, ...] | None = None,
        rotate_interval: int = 1,
        join_limit: int = JOIN_ATTEMPTS,
        search_timeout_s: float = SEARCH_TIMEOUT_S,
        sleep_s: float = SLEEP_RETRY_S,
        refresh_s_min: float = REFRESH_S_MIN,
        refresh_s_max: float = REFRESH_S_MAX,
        continuous: bool = False,
    ) -> None:
        if prefixes:
            self.prefixes = [normalize_prefix(p) for p in prefixes if normalize_prefix(p)]
        else:
            cleaned = normalize_prefix(prefix)
            self.prefixes = [cleaned] if cleaned else ["3"]
        if not self.prefixes:
            self.prefixes = ["3"]
        requested = normalize_prefix(prefix)
        self.prefix_idx = (
            self.prefixes.index(requested)
            if requested in self.prefixes
            else 0
        )
        self.prefix = self.prefixes[self.prefix_idx]
        self.rotate_interval = max(1, int(rotate_interval))
        self.refresh_cycles_on_prefix = 0
        self.join_limit = max(1, int(join_limit))
        self.search_timeout_s = float(search_timeout_s)
        self.sleep_s = float(sleep_s)
        lo = float(refresh_s_min)
        hi = float(refresh_s_max)
        if lo > hi:
            lo, hi = hi, lo
        self.refresh_s_min = max(0.0, lo)
        self.refresh_s_max = max(self.refresh_s_min, hi)
        self.continuous = bool(continuous)
        self.join_confirm_timeout_s = 1.0
        # A navigation click is an input, not a navigation.  If GO_HOME never
        # produces lobby-page evidence, stop re-sending it and take the
        # bounded sleep instead of clicking the same dead anchor forever.
        self.go_home_confirm_timeout_s = GO_HOME_CONFIRM_S
        self.phase = HitchPhase.SEARCH
        self.attempts = 0
        self.search_started_at: float | None = None
        self.sleep_until = 0.0
        self.next_allowed_at = 0.0
        self.pending_join = False
        self.join_clicked_at: float | None = None
        self.go_home_clicked = False
        self.go_home_clicked_at: float | None = None

    def reset_lobby(self, now: float, reason: str = "reset") -> HitchDecision:
        self.phase = HitchPhase.LOBBY_HOME
        self.attempts = 0
        self.search_started_at = None
        self.sleep_until = 0.0
        self.next_allowed_at = 0.0
        self.pending_join = False
        self.join_clicked_at = None
        self.go_home_clicked = False
        self.go_home_clicked_at = None
        return HitchDecision(
            action=HitchAction.RESET,
            phase=self.phase,
            reason=reason,
            attempts=0,
            elapsed_s=0.0,
        )

    def note_refresh(self, now: float) -> bool:
        self.attempts += 1
        self.refresh_cycles_on_prefix += 1
        self.next_allowed_at = float(now) + self.refresh_s_min
        self.pending_join = False
        self.join_clicked_at = None
        if len(self.prefixes) > 1 and self.refresh_cycles_on_prefix >= self.rotate_interval:
            self.rotate_prefix()
            return True
        return False

    def rotate_prefix(self) -> str:
        if len(self.prefixes) <= 1:
            return self.prefix
        # An exhausted result set has no joinable room.  Pick any other
        # configured term rather than repeatedly searching the same result.
        next_prefix = random.choice([item for item in self.prefixes if item != self.prefix])
        self.prefix_idx = self.prefixes.index(next_prefix)
        self.prefix = self.prefixes[self.prefix_idx]
        self.refresh_cycles_on_prefix = 0
        return self.prefix
    def defer_retry(self, now: float) -> None:
        """Throttle a retry without counting a refresh or join attempt."""
        self.next_allowed_at = max(
            self.next_allowed_at,
            float(now) + self.refresh_s_min,
        )

    def begin_search_window(self, now: float) -> None:
        """Open the bounded search operation clock; idempotent per operation.

        ``tick()`` used to be the only place that armed ``search_started_at``,
        so every early return upstream of it (missing locator, unconfirmed
        postcondition, rejected input) sat outside the budget entirely and
        could wait forever.  The lobby subflow now arms the clock as soon as
        the room list is trusted, which puts those paths inside the same
        bounded operation.
        """
        if self.search_started_at is None:
            self.search_started_at = float(now)

    def search_window_expired(self, now: float) -> bool:
        """True when this search operation has burned its durable budget."""
        if self.search_started_at is None:
            return False
        return self._elapsed(now) >= self.search_timeout_s

    def input_allowed(self, now: float) -> bool:
        """Cooldown gate for input-bearing retries only.

        Observation (capture, locator, OCR postcondition) must never be
        blocked by this: a cooldown throttles what we send, not what we look
        at.  ``defer_retry()`` writes ``next_allowed_at``; before this the
        search-input path never read it, which made that field a dead control
        surface for the one action it was meant to throttle.
        """
        return float(now) >= self.next_allowed_at

    def enter_sleep_retry(self, now: float) -> None:
        """Back off for one bounded sleep instead of spinning on a dead exit.

        ``tick()`` keeps returning GO_HOME once the operation is exhausted, so
        a lobby with no reachable navigation anchor would re-decide the same
        unreachable action every tick.  Sleeping is the state machine's own
        safe baseline, costs zero input, and lets the next wake start a fresh
        operation.
        """
        self.phase = HitchPhase.SLEEP_RETRY
        self.sleep_until = float(now) + self.sleep_s
        self.pending_join = False
        self.join_clicked_at = None
        self.go_home_clicked = False
        self.go_home_clicked_at = None

    def note_join_click(self, now: float) -> None:
        self.pending_join = True
        self.join_clicked_at = float(now)
        self.next_allowed_at = float(now) + self.refresh_s_min

    def reject_join(self, now: float) -> None:
        """Release a refused room immediately so the next row can be tried."""
        self.pending_join = False
        self.join_clicked_at = None
        self.next_allowed_at = float(now)

    def complete_join(self) -> None:
        if self.pending_join:
            self.attempts += 1
        self.pending_join = False
        self.join_clicked_at = None

    def note_go_home(self, now: float) -> None:
        # Keep the first click of a sequence as the confirmation anchor.  If
        # every re-click reset it, `go_home_confirm_timeout_s` could never
        # accumulate and the same unconfirmed navigation would repeat forever.
        if not self.go_home_clicked:
            self.go_home_clicked_at = float(now)
        self.go_home_clicked = True
        self.next_allowed_at = float(now) + self.refresh_s_min

    def confirm_lobby_home(self) -> None:
        self.phase = HitchPhase.LOBBY_HOME
        self.pending_join = False
        self.go_home_clicked = False

    def can_confirm_lobby_home(self, now: float, lobby_visible: bool) -> bool:
        """True only on a later tick than the GO_HOME click, with lobby page evidence."""
        if not self.go_home_clicked or not lobby_visible:
            return False
        clicked_at = self.go_home_clicked_at
        if clicked_at is None:
            return False
        return float(now) > float(clicked_at)

    def _elapsed(self, now: float) -> float:
        if self.search_started_at is None:
            return 0.0
        return max(0.0, float(now) - self.search_started_at)

    def _decision(self, action: HitchAction, reason: str, now: float) -> HitchDecision:
        return HitchDecision(
            action=action,
            phase=self.phase,
            reason=reason,
            attempts=self.attempts,
            elapsed_s=self._elapsed(now),
        )

    def tick(
        self,
        *,
        now: float,
        matched: bool = False,
        ocr_text: str = "",
        prefix_ok: bool = False,
        in_room: bool = False,
    ) -> HitchDecision:
        event = classify_hitch_ocr(ocr_text)
        if event:
            return self.reset_lobby(now, event)

        if self.pending_join:
            if in_room:
                self.complete_join()
                return self._decision(HitchAction.NONE, "join_confirmed", now)
            # 若超过1秒未进房（如满员/密码房/被拒），重置 pending_join 继续搜房
            join_elapsed = max(0.0, float(now) - float(self.join_clicked_at or now))
            if join_elapsed >= self.join_confirm_timeout_s:
                self.pending_join = False
                self.join_clicked_at = None
            else:
                return self._decision(HitchAction.NONE, "await_join_confirm", now)

        if self.phase == HitchPhase.SLEEP_RETRY:
            if now >= self.sleep_until:
                self.phase = HitchPhase.SEARCH
                self.attempts = 0
                self.search_started_at = now
                self.next_allowed_at = 0.0
                self.pending_join = False
                return self._decision(HitchAction.REFRESH, "sleep_retry_awake", now)
            return self._decision(HitchAction.SLEEP, "休眠重试", now)

        if self.phase == HitchPhase.LOBBY_HOME:
            self.phase = HitchPhase.SLEEP_RETRY
            self.sleep_until = now + self.sleep_s
            return self._decision(HitchAction.SLEEP, "休眠重试", now)

        if self.search_started_at is None:
            self.search_started_at = now
        elapsed = self._elapsed(now)
        exhausted = self.attempts >= self.join_limit or elapsed >= self.search_timeout_s
        if exhausted and self.continuous:
            # The explicit live end-to-end probe ends only after a verified
            # guest Ready.  Start a fresh search cycle while preserving the
            # current refresh cooldown and rejected-row evidence owned by the
            # mediator; never fall into GO_HOME merely because a cycle elapsed.
            self.attempts = 0
            self.search_started_at = now
            self.go_home_clicked = False
            self.go_home_clicked_at = None
            exhausted = False
        if exhausted:
            if self.go_home_clicked:
                waited = float(now) - float(self.go_home_clicked_at or now)
                if waited >= self.go_home_confirm_timeout_s:
                    self.enter_sleep_retry(now)
                    return self._decision(HitchAction.SLEEP, "go_home_unconfirmed", now)
                if now < self.next_allowed_at:
                    return self._decision(HitchAction.NONE, "await_lobby_home", now)
            if now < self.next_allowed_at:
                return self._decision(HitchAction.NONE, "await_go_home", now)
            return self._decision(HitchAction.GO_HOME, "search_exhausted", now)
        if now < self.next_allowed_at:
            return self._decision(HitchAction.NONE, "debounce", now)
        if matched and prefix_ok:
            return self._decision(HitchAction.JOIN, "match", now)
        return self._decision(HitchAction.REFRESH, "unmatched", now)


class FollowPhase(str, Enum):
    WAIT_ROOM = "wait_room"
    WAIT_HOST = "wait_host"
    STAGE_WAIT = "stage_wait"
    IN_GAME = "in_game"


class FollowTeamSM:
    """跟车：已在房等房主 → 进局 → 回同房再等。零 RoomStart / 创房 / quick_join。"""

    def tick(self, *, in_game: bool, in_room: bool, stage_page: bool) -> FollowPhase:
        if in_game:
            return FollowPhase.IN_GAME
        if stage_page:
            return FollowPhase.STAGE_WAIT
        if in_room:
            return FollowPhase.WAIT_HOST
        return FollowPhase.WAIT_ROOM
