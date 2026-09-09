"""可靠性地基：进度令牌、代际绑定、观测溯源、执行评估与影子授权内核。

纯数据/纯逻辑模块，不导入任何生产组件、不触碰 Win32 —— 供上层
mediator/授权链做 fail-closed 判定用的秩序锚。
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from enum import Enum, auto
from typing import Optional


class BusinessProgressToken(Enum):
    """业务进展里程碑（单调推进的目标秩序）。"""

    SESSION_START = auto()
    LOBBY_READY = auto()
    SEARCH_SUBMITTED = auto()
    ROOM_ENTERED = auto()
    ROUND_STARTED = auto()
    ROUND_RESOLVED = auto()
    LOOT_COLLECTED = auto()
    ROOM_EXITED = auto()


@dataclass(frozen=True)
class ProgressRecord:
    """一次进度令牌的落账。"""

    token: BusinessProgressToken
    timestamp: float
    note: str = ""


class ProgressTracker:
    """记录业务进度令牌，回答「多久没进展了」（停滞）与「离某里程碑多久了」（年龄）。"""

    def __init__(self) -> None:
        self._records: list[ProgressRecord] = []

    def record(
        self,
        token: BusinessProgressToken,
        *,
        now: Optional[float] = None,
        note: str = "",
    ) -> ProgressRecord:
        rec = ProgressRecord(token=token, timestamp=time.time() if now is None else now, note=note)
        self._records.append(rec)
        return rec

    def last(self, token: BusinessProgressToken) -> Optional[ProgressRecord]:
        for rec in reversed(self._records):
            if rec.token is token:
                return rec
        return None

    @property
    def records(self) -> tuple[ProgressRecord, ...]:
        return tuple(self._records)

    def age(self, token: BusinessProgressToken, *, now: Optional[float] = None) -> Optional[float]:
        """距该令牌最近一次落账的秒数；从未落账返回 None。"""
        rec = self.last(token)
        if rec is None:
            return None
        return (time.time() if now is None else now) - rec.timestamp

    def stagnation(self, *, now: Optional[float] = None) -> Optional[float]:
        """距最近一次任何进度落账的秒数；没有任何落账返回 None。"""
        if not self._records:
            return None
        return (time.time() if now is None else now) - self._records[-1].timestamp

    def is_stagnant(self, threshold_seconds: float, *, now: Optional[float] = None) -> bool:
        """从未进展视为已停滞（fail-closed）。"""
        span = self.stagnation(now=now)
        return span is None or span > threshold_seconds


class BindingGeneration:
    """窗口绑定代际：代数只增不减，旧代观测/意图一律失效。"""

    def __init__(self, hwnd: int, generation: int = 0) -> None:
        self.hwnd = hwnd
        self.generation = generation

    def bump(self) -> int:
        self.generation += 1
        return self.generation

    def matches(self, hwnd: int, generation: int) -> bool:
        """校验 hwnd 与代数是否都匹配当前绑定。"""
        return hwnd == self.hwnd and generation == self.generation

    def validate(self, hwnd: int, generation: int) -> None:
        """不匹配即抛错（fail-closed）。"""
        if not self.matches(hwnd, generation):
            raise ValueError(
                f"binding mismatch: expected hwnd={self.hwnd} gen={self.generation}, "
                f"got hwnd={hwnd} gen={generation}"
            )


class RoundGeneration:
    """局代际：bump 后旧代作废。"""

    def __init__(self) -> None:
        self.generation = 0

    def bump(self) -> int:
        self.generation += 1
        return self.generation

    def is_current(self, generation: int) -> bool:
        return generation == self.generation


class TransactionGeneration:
    """事务代际：open 后 active，只能收敛到 committed 或 ambiguous。"""

    _IDLE = "idle"
    _ACTIVE = "active"
    _COMMITTED = "committed"
    _AMBIGUOUS = "ambiguous"

    def __init__(self) -> None:
        self.generation = 0
        self.state = self._IDLE

    def open(self) -> int:
        self.generation += 1
        self.state = self._ACTIVE
        return self.generation

    def _resolve(self, state: str) -> None:
        if self.state != self._ACTIVE:
            raise RuntimeError(f"transaction gen={self.generation} is {self.state}, cannot resolve")
        self.state = state

    def commit(self) -> None:
        self._resolve(self._COMMITTED)

    def mark_ambiguous(self) -> None:
        self._resolve(self._AMBIGUOUS)

    @property
    def is_active(self) -> bool:
        return self.state == self._ACTIVE

    @property
    def is_resolved(self) -> bool:
        return self.state in (self._COMMITTED, self._AMBIGUOUS)


@dataclass(frozen=True)
class ObservationProvenance:
    """一次观测的溯源：哪一帧、哪个后端、哪个窗口、哪一代绑定。"""

    frame_id: int
    timestamp: float
    backend: str
    hwnd: int
    pid: int
    rect: tuple[int, int, int, int]
    dpi: float
    binding_gen: int

    def matches_binding(self, binding: BindingGeneration) -> bool:
        """与绑定代际兼容 = 窗口一致且代数一致。"""
        return binding.matches(self.hwnd, self.binding_gen)


class BusinessOutcome(Enum):
    """执行后业务结果的判定档位。"""

    CONFIRMED_SUCCESS = auto()
    CONFIRMED_NO_EFFECT = auto()
    REJECTED = auto()
    AMBIGUOUS = auto()
    OBSERVATION_FAILED = auto()


@dataclass(frozen=True)
class ExecutionAssessment:
    """对一次执行的评估：结果档位 + 支撑该判定的观测溯源。"""

    outcome: BusinessOutcome
    provenance: Optional[ObservationProvenance] = None
    detail: str = ""

    @property
    def is_confirmed(self) -> bool:
        return self.outcome in (BusinessOutcome.CONFIRMED_SUCCESS, BusinessOutcome.CONFIRMED_NO_EFFECT)


class AuthorizationVerdict(Enum):
    """影子授权内核的裁决（只裁决，不执行）。"""

    ALLOW = auto()
    DENY_WRONG_HWND = auto()
    DENY_STALE_BINDING = auto()
    DENY_UNKNOWN_CONTEXT = auto()
    DENY_PROTECTED_PERSONAL_RESOURCE = auto()
    DENY_AMBIGUOUS_TRANSACTION = auto()


@dataclass(frozen=True)
class ActionIntent:
    """待裁决的动作意图。"""

    action: str
    target_hwnd: Optional[int] = None
    binding_gen: Optional[int] = None
    context_known: bool = False
    personal_protected_resource: bool = False
    transaction_state: Optional[str] = None  # TransactionGeneration.state 或 None


class ActionSafetyPolicy:
    """影子授权内核：硬拒绝一切可疑意图，宁拒勿放（fail-closed）。"""

    def authorize(self, intent: ActionIntent, binding: BindingGeneration) -> AuthorizationVerdict:
        if not intent.context_known:
            return AuthorizationVerdict.DENY_UNKNOWN_CONTEXT
        if intent.target_hwnd != binding.hwnd:
            return AuthorizationVerdict.DENY_WRONG_HWND
        if intent.binding_gen != binding.generation:
            return AuthorizationVerdict.DENY_STALE_BINDING
        if intent.personal_protected_resource:
            return AuthorizationVerdict.DENY_PROTECTED_PERSONAL_RESOURCE
        if intent.transaction_state == TransactionGeneration._AMBIGUOUS:
            return AuthorizationVerdict.DENY_AMBIGUOUS_TRANSACTION
        return AuthorizationVerdict.ALLOW


@dataclass(frozen=True)
class RuntimeIdentityManifest:
    """运行时身份自述：这 binary 是谁构建的、带哪套模型与素材。"""

    source_sha: str
    build_id: str
    model_id: str
    asset_id: str
    channel: str = "dev"

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> "RuntimeIdentityManifest":
        return cls(**json.loads(text))
