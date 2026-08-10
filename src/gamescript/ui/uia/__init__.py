"""局外（L0）UIA 链路：KK 对战平台建房语义控件。

分层（自底向上）：
- backend.py    纯 ctypes 的 UIAutomationCore 后端（零第三方依赖）
- source.py     ElementSource 协议 + 树快照（有界遍历/缓存/失效）
- selector.py   多属性控件选择器匹配引擎
- model.py      数据模型（控件映射/读回/锚点/Fail-Closed 异常）
- mappings.py   KK 局外建房控件映射表（候选值，待实机回填）
- adapter.py    LobbyUiaAdapter：窗口身份 → 控件 → 动作 → 读回 → 锚点
"""

from __future__ import annotations

from .adapter import AdapterOptions, LobbyUiaAdapter, VisualFallback
from .backend import CtypesUiaBackend
from .mappings import KK_LOBBY_MAPPINGS, WINDOW_PLATFORM_MAP, WINDOW_ROOM
from .model import (
    AnchorCondition,
    ControlMapping,
    FailClosedError,
    PatternKind,
    PostAnchorSpec,
    ReadbackKind,
    ReadbackSpec,
    UiaActionTrace,
    UiaNode,
    UiaSelector,
    UiaWindowSpec,
)
from .source import ElementSource, SnapshotCache, SnapshotOptions, TreeSnapshot, build_snapshot, collect_nodes

__all__ = [
    "AdapterOptions",
    "AnchorCondition",
    "ControlMapping",
    "CtypesUiaBackend",
    "ElementSource",
    "FailClosedError",
    "KK_LOBBY_MAPPINGS",
    "LobbyUiaAdapter",
    "PatternKind",
    "PostAnchorSpec",
    "ReadbackKind",
    "ReadbackSpec",
    "SnapshotCache",
    "SnapshotOptions",
    "TreeSnapshot",
    "UiaActionTrace",
    "UiaNode",
    "UiaSelector",
    "UiaWindowSpec",
    "VisualFallback",
    "WINDOW_PLATFORM_MAP",
    "WINDOW_ROOM",
    "build_snapshot",
    "collect_nodes",
]
