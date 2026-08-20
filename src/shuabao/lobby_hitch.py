"""大厅蹭车（lobby_hitch）搜房/退房纯状态机。

可注入时钟与 OCR 文本，测试不需要游戏窗或真实 sidecar。
join_attempts 以本模块的 3 为准（mode_specs 历史值 2 不再采用）。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

JOIN_ATTEMPTS = 3
SEARCH_TIMEOUT_S = 120.0
SLEEP_RETRY_S = 120.0
ALLOWED_PREFIXES = ("3", "4")

KICK_MARKERS = ("被踢出", "你已被踢", "踢出房间")
DISSOLVE_MARKERS = ("房间解散", "房间已解散", "队伍已解散", "车队解散")


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


@dataclass
class HitchDecision:
    action: HitchAction
    phase: HitchPhase
    reason: str
    attempts: int
    elapsed_s: float


class HitchSearchSM:
    """有界搜房：3 次 match/join，或 120s 未匹配 → 大厅主页 + 休眠重试。"""

    def __init__(
        self,
        prefix: str = "3",
        *,
        join_limit: int = JOIN_ATTEMPTS,
        search_timeout_s: float = SEARCH_TIMEOUT_S,
        sleep_s: float = SLEEP_RETRY_S,
    ) -> None:
        self.prefix = normalize_prefix(prefix)
        self.join_limit = max(1, int(join_limit))
        self.search_timeout_s = float(search_timeout_s)
        self.sleep_s = float(sleep_s)
        self.phase = HitchPhase.SEARCH
        self.attempts = 0
        self.search_started_at: float | None = None
        self.sleep_until = 0.0

    def reset_lobby(self, now: float, reason: str = "reset") -> HitchDecision:
        self.phase = HitchPhase.LOBBY_HOME
        self.attempts = 0
        self.search_started_at = None
        self.sleep_until = 0.0
        return HitchDecision(
            action=HitchAction.RESET,
            phase=self.phase,
            reason=reason,
            attempts=0,
            elapsed_s=0.0,
        )

    def tick(
        self,
        *,
        now: float,
        matched: bool = False,
        ocr_text: str = "",
    ) -> HitchDecision:
        event = classify_hitch_ocr(ocr_text)
        if event:
            return self.reset_lobby(now, event)

        if self.phase == HitchPhase.SLEEP_RETRY:
            if now >= self.sleep_until:
                self.phase = HitchPhase.SEARCH
                self.attempts = 0
                self.search_started_at = now
                self.attempts = 1
                return HitchDecision(
                    action=HitchAction.REFRESH,
                    phase=self.phase,
                    reason="sleep_retry_awake",
                    attempts=self.attempts,
                    elapsed_s=0.0,
                )
            elapsed = max(0.0, now - (self.search_started_at or now))
            return HitchDecision(
                action=HitchAction.SLEEP,
                phase=self.phase,
                reason="休眠重试",
                attempts=self.attempts,
                elapsed_s=elapsed,
            )

        if self.phase == HitchPhase.LOBBY_HOME:
            self.phase = HitchPhase.SLEEP_RETRY
            self.sleep_until = now + self.sleep_s
            return HitchDecision(
                action=HitchAction.SLEEP,
                phase=self.phase,
                reason="休眠重试",
                attempts=self.attempts,
                elapsed_s=0.0,
            )

        if self.search_started_at is None:
            self.search_started_at = now
        elapsed = now - self.search_started_at
        if self.attempts >= self.join_limit or elapsed >= self.search_timeout_s:
            self.phase = HitchPhase.LOBBY_HOME
            return HitchDecision(
                action=HitchAction.GO_HOME,
                phase=self.phase,
                reason="search_exhausted",
                attempts=self.attempts,
                elapsed_s=elapsed,
            )
        self.attempts += 1
        if matched:
            return HitchDecision(
                action=HitchAction.JOIN,
                phase=self.phase,
                reason="match",
                attempts=self.attempts,
                elapsed_s=elapsed,
            )
        return HitchDecision(
            action=HitchAction.REFRESH,
            phase=self.phase,
            reason="unmatched",
            attempts=self.attempts,
            elapsed_s=elapsed,
        )
