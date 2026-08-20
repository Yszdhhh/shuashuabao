"""大厅蹭车（lobby_hitch）搜房/退房状态机。

可注入时钟与 OCR 文本，测试不需要游戏窗或真实 sidecar。
join_attempts 以本模块的 3 为准（mode_specs 历史值 2 不再采用）。
刷新间隔来自 mode_specs budgets refresh_s_min/refresh_s_max（默认 3–4s）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

JOIN_ATTEMPTS = 3
SEARCH_TIMEOUT_S = 120.0
SLEEP_RETRY_S = 120.0
REFRESH_S_MIN = 3.0
REFRESH_S_MAX = 4.0
ALLOWED_PREFIXES = ("3", "4")

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
    if not text:
        return "3"
    head = text[0]
    return head if head in ALLOWED_PREFIXES else "3"


def classify_hitch_ocr(text: str) -> str | None:
    raw = str(text or "")
    if any(marker in raw for marker in KICK_MARKERS):
        return "被踢出"
    if any(marker in raw for marker in DISSOLVE_MARKERS):
        return "房间解散"
    return None


def has_prefix_evidence(text: str, prefix: str) -> bool:
    """Visible 3/4 occupancy or search evidence. Empty OCR is not evidence."""
    raw = str(text or "").strip()
    want = normalize_prefix(prefix)
    if not raw:
        return False
    if raw == want:
        return True
    if f"{want}/" in raw.replace(" ", ""):
        return True
    for match in _PREFIX_RE.finditer(raw):
        if match.group(1) == want:
            return True
    return False


@dataclass
class HitchDecision:
    action: HitchAction
    phase: HitchPhase
    reason: str
    attempts: int
    elapsed_s: float


class HitchSearchSM:
    """有界搜房：成功刷新/进房后置确认计 attempt，3 次或 120s → GO_HOME（需大厅页证据）。"""

    def __init__(
        self,
        prefix: str = "3",
        *,
        join_limit: int = JOIN_ATTEMPTS,
        search_timeout_s: float = SEARCH_TIMEOUT_S,
        sleep_s: float = SLEEP_RETRY_S,
        refresh_s_min: float = REFRESH_S_MIN,
        refresh_s_max: float = REFRESH_S_MAX,
    ) -> None:
        self.prefix = normalize_prefix(prefix)
        self.join_limit = max(1, int(join_limit))
        self.search_timeout_s = float(search_timeout_s)
        self.sleep_s = float(sleep_s)
        lo = float(refresh_s_min)
        hi = float(refresh_s_max)
        if lo > hi:
            lo, hi = hi, lo
        self.refresh_s_min = max(0.0, lo)
        self.refresh_s_max = max(self.refresh_s_min, hi)
        self.phase = HitchPhase.SEARCH
        self.attempts = 0
        self.search_started_at: float | None = None
        self.sleep_until = 0.0
        self.next_allowed_at = 0.0
        self.pending_join = False

    def reset_lobby(self, now: float, reason: str = "reset") -> HitchDecision:
        self.phase = HitchPhase.LOBBY_HOME
        self.attempts = 0
        self.search_started_at = None
        self.sleep_until = 0.0
        self.next_allowed_at = 0.0
        self.pending_join = False
        return HitchDecision(
            action=HitchAction.RESET,
            phase=self.phase,
            reason=reason,
            attempts=0,
            elapsed_s=0.0,
        )

    def note_refresh(self, now: float) -> None:
        self.attempts += 1
        self.next_allowed_at = float(now) + self.refresh_s_min
        self.pending_join = False

    def note_join_click(self, now: float) -> None:
        self.pending_join = True
        self.next_allowed_at = float(now) + self.refresh_s_min

    def complete_join(self) -> None:
        if self.pending_join:
            self.attempts += 1
        self.pending_join = False

    def note_go_home(self, now: float) -> None:
        self.next_allowed_at = float(now) + self.refresh_s_min

    def confirm_lobby_home(self) -> None:
        self.phase = HitchPhase.LOBBY_HOME
        self.pending_join = False

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
            elapsed = self._elapsed(now)
            if elapsed >= self.search_timeout_s:
                self.pending_join = False
                return self._decision(HitchAction.GO_HOME, "search_exhausted", now)
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
        if exhausted:
            if now < self.next_allowed_at:
                return self._decision(HitchAction.NONE, "await_go_home", now)
            return self._decision(HitchAction.GO_HOME, "search_exhausted", now)
        if now < self.next_allowed_at:
            return self._decision(HitchAction.NONE, "debounce", now)
        if matched and prefix_ok:
            return self._decision(HitchAction.JOIN, "match", now)
        return self._decision(HitchAction.REFRESH, "unmatched", now)
