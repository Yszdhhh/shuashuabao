"""UIA 元素源协议与树快照构建（与后端解耦，mockable）。

ElementSource 是 adapter 与真实 COM 后端之间的唯一通道：
- 单测注入 FakeElementSource 即可覆盖遍历/选择器/Fail-Closed；
- 生产使用 backend.CtypesUiaBackend（或批准后的 comtypes 后端）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from .model import TreeSnapshot, UiaNode


class ElementSource(Protocol):
    """UIA 元素访问的最小协议（按需懒加载属性）。"""

    def is_available(self) -> bool: ...

    def element_from_handle(self, hwnd: int) -> Any | None:
        """返回不透明元素句柄；失败返回 None（不抛）。"""

    def get_property(self, element: Any, prop_id: int) -> Any:
        """读取属性：30005 Name / 30011 AutomationId / 30003 ControlType /
        30012 ClassName / 30032 FrameworkId / 30002 ProcessId。
        不支持或失败返回 None。"""

    def children(self, element: Any) -> list[Any]:
        """直接子元素列表（已过滤无效）；失败返回 []。"""

    def get_pattern(self, element: Any, pattern_id: int) -> Any | None:
        """获取 pattern 对象；不可用返回 None（不抛）。"""

    def invoke(self, pattern: Any) -> None: ...

    def set_value(self, pattern: Any, text: str) -> None: ...

    def toggle(self, pattern: Any) -> None: ...

    def value(self, pattern: Any) -> str:
        """ValuePattern.CurrentValue 读回。"""

    def toggle_state(self, pattern: Any) -> int:
        """TogglePattern.CurrentToggleState 读回。"""

    def describe(self) -> str:
        """后端描述（ctypes / comtypes / mock），用于 trace。"""

    def close(self) -> None:
        """释放 COM 资源。"""


# UIA 属性 ID（与 model.py 注释一致）
PROP_NAME = 30005
PROP_CONTROL_TYPE = 30003
PROP_AUTOMATION_ID = 30011
PROP_CLASS_NAME = 30012
PROP_FRAMEWORK_ID = 30032
PROP_PROCESS_ID = 30002

# Pattern ID
PATTERN_INVOKE = 10000
PATTERN_VALUE = 10002
PATTERN_TOGGLE = 10016

# 树快照默认预算
DEFAULT_MAX_NODES = 2000
DEFAULT_MAX_DEPTH = 32


@dataclass
class SnapshotOptions:
    max_nodes: int = DEFAULT_MAX_NODES
    max_depth: int = DEFAULT_MAX_DEPTH
    include_rect: bool = True


def _node_key(node: UiaNode) -> tuple[Any, ...]:
    """环检测键：同一元素在树中出现两次（provider 环）时结构相同。"""
    return (node.name, node.automation_id, node.control_type, node.class_name, node.rect)


def build_snapshot(
    source: ElementSource,
    hwnd: int | None,
    window_key: tuple[Any, ...] | None = None,
    options: SnapshotOptions | None = None,
    now: float | None = None,
) -> TreeSnapshot:
    """从后端构建一棵树快照（有界：节点预算 + 深度上限 + 环检测）。

    - FindAll/children 失败的元素按叶子处理，不中断整棵树。
    - truncated=True 表示预算截断（trace 中标注，不能当完整证据）。
    """
    opts = options or SnapshotOptions()
    snap = TreeSnapshot(
        taken_at=now if now is not None else time.monotonic(),
        window_key=window_key,
        source_desc=source.describe(),
    )
    root_handle = source.element_from_handle(hwnd) if hwnd else None
    if root_handle is None:
        return snap

    budget = opts.max_nodes
    path_keys: set[tuple[Any, ...]] = set()  # 当前递归路径上的节点键（真环检测）

    def read_node(handle: Any, depth: int) -> UiaNode | None:
        nonlocal budget
        if budget <= 0 or depth > opts.max_depth:
            return None
        node = UiaNode(
            name=_s(source.get_property(handle, PROP_NAME)),
            automation_id=_s(source.get_property(handle, PROP_AUTOMATION_ID)),
            control_type=_as_int(source.get_property(handle, PROP_CONTROL_TYPE)),
            class_name=_s(source.get_property(handle, PROP_CLASS_NAME)),
            framework_id=_s(source.get_property(handle, PROP_FRAMEWORK_ID)),
            pid=_as_int(source.get_property(handle, PROP_PROCESS_ID)),
            depth=depth,
            handle=handle,
        )
        key = _node_key(node)
        # 路径级环检测：同一元素作为自身后代出现才剪枝；
        # 兄弟节点属性相同（如弹窗里两个同名 Edit）不误伤。
        if key in path_keys:
            return None
        path_keys.add(key)
        try:
            budget -= 1
            snap.node_count += 1
            for child_handle in source.children(handle):
                child = read_node(child_handle, depth + 1)
                if child is not None:
                    node.children.append(child)
            if budget <= 0:
                snap.truncated = True
        finally:
            path_keys.discard(key)
        return node

    snap.root = read_node(root_handle, 0)
    return snap


def collect_nodes(snapshot: TreeSnapshot) -> list[UiaNode]:
    """按树序展平快照节点（不含根）。"""
    out: list[UiaNode] = []

    def walk(node: UiaNode) -> None:
        for child in node.children:
            out.append(child)
            walk(child)

    if snapshot.root is not None:
        walk(snapshot.root)
    return out


def _s(value: Any) -> str | None:
    # 空字符串保留（'' 与 None 语义不同：属性存在但为空 vs 读取失败）
    if value is None:
        return None
    return str(value)


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class SnapshotCache:
    """树快照缓存：窗口身份变化 / 过期 / 显式失效即重建。

    - 一次动作（act）的生命周期内复用同一快照，避免每 tick 全树重扫；
    - 动作成功后显式 invalidate()，下一动作强制重建，保证读到最新状态。
    """

    def __init__(self, max_age_s: float = 5.0, now: float | None = None) -> None:
        self.max_age_s = max_age_s
        self._now = now  # 注入时钟（单测用）
        self._snapshot: TreeSnapshot | None = None

    def _clock(self) -> float:
        return self._now() if callable(self._now) else time.monotonic()

    def get(
        self,
        source: ElementSource,
        hwnd: int | None,
        window_key: tuple[Any, ...] | None = None,
        options: SnapshotOptions | None = None,
        force: bool = False,
    ) -> TreeSnapshot | None:
        snap = self._snapshot
        if snap is not None and not force:
            if window_key is not None and snap.window_key != window_key:
                snap = None
            elif snap.is_stale(self.max_age_s, self._clock()):
                snap = None
        if snap is None or force:
            snap = build_snapshot(source, hwnd, window_key=window_key, options=options, now=self._clock())
            self._snapshot = snap
        return snap

    def invalidate(self) -> None:
        self._snapshot = None
