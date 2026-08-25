"""UIA 局外（L0）链路：纯数据模型（无第三方依赖）。

本模块只定义数据结构与异常，不触碰任何 Win32/COM API，
保证可在任意平台导入与单测。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


# ---- UIA 常量（uiautomationcore.h / uiautomationclient.h 的公开取值）----

class ControlType(Enum):
    """UIA ControlTypeId 子集（局外建房最常用）。"""

    BUTTON = 50000
    CHECKBOX = 50002
    COMBOBOX = 50003
    EDIT = 50004
    IMAGE = 50006
    LIST_ITEM = 50007
    LIST = 50008
    MENU_ITEM = 50011
    RADIO_BUTTON = 50013
    TAB = 50018
    TAB_ITEM = 50019
    TEXT = 50020
    TREE_ITEM = 50024
    CUSTOM = 50025
    GROUP = 50026
    WINDOW = 50032
    PANE = 50033
    TITLE_BAR = 50038


class PatternKind(Enum):
    """控件动作类型（对应 UIA pattern 的封装）。"""

    NONE = auto()      # 只读（页面锚点 / 值读回）
    INVOKE = auto()    # IUIAutomationInvokePattern.Invoke
    VALUE_SET = auto() # IUIAutomationValuePattern.SetValue
    TOGGLE = auto()    # IUIAutomationTogglePattern.Toggle


class ReadbackKind(Enum):
    """动作后的值/页面证据读回方式。"""

    NONE = auto()          # 不需要值读回，只依赖 post_anchor
    VALUE = auto()         # ValuePattern.CurrentValue 文本
    TOGGLE_STATE = auto()  # TogglePattern.CurrentToggleState (0/1/2)
    NAME = auto()          # 元素 Name 属性


class AnchorCondition(Enum):
    """后置确认锚点的判定条件。"""

    EXISTS = auto()     # 锚点元素存在（页面已切换）
    ABSENT = auto()     # 锚点元素消失（弹窗已关闭等）
    VALUE_EQ = auto()   # 锚点元素值读回 == expected（与 ReadbackSpec 配合）


class FailClosedError(RuntimeError):
    """Fail-Closed：控件不可用/读回不符/锚点缺失，超时后抛出的唯一停机路径。

    携带最后一次可用的证据（树快照指纹、读回历史、已耗时长）。
    """

    def __init__(
        self,
        mapping_key: str,
        reason: str,
        elapsed_s: float,
        evidence: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(f"[L0-UIA] Fail-Closed {mapping_key}: {reason} (elapsed={elapsed_s:.1f}s)")
        self.mapping_key = mapping_key
        self.reason = reason
        self.elapsed_s = elapsed_s
        self.evidence = evidence or {}


# ---- 窗口身份 ----

@dataclass(frozen=True)
class UiaWindowSpec:
    """局外窗口的稳定身份（与 find_window_targets 的 WindowTarget 对齐）。

    - 窗口身份优先用 pid + class_name + title 组合匹配；hwnd 是结果而非条件。
    - role="l0" 复用 capture.py 的 L0 关键字语义（KK 平台/房间），
      role="l1" 用于局内窗口（本链路不适用，仅占位防误用）。
    """

    title_contains: tuple[str, ...] = ("KK",)
    class_name: str | None = None        # 例如 "Qt5QWindowIcon" / "Chrome_WidgetWin_1"
    pid: int | None = None               # 平台进程 pid（房间/弹窗同进程）
    role: str = "l0"
    min_width: int = 200
    min_height: int = 200


# ---- 控件选择器 ----

@dataclass(frozen=True)
class UiaSelector:
    """多属性控件选择器。

    所有字段均为 AND 语义；None 字段不参与匹配。
    - name / name_re：Name 属性（精确或正则）
    - automation_id / class_name：AutomationId / ClassName 属性
    - control_type：ControlType 枚举或 int
    - index：第 n 个命中（0-based）；None 表示取第一个
    - scope："children" 只搜直接子级；"descendants" 递归（受树快照预算限制）
    """

    name: str | None = None
    name_re: str | None = None
    automation_id: str | None = None
    control_type: int | ControlType | None = None
    class_name: str | None = None
    index: int | None = None
    scope: str = "children"

    def __post_init__(self) -> None:
        if self.name is not None and self.name_re is not None:
            raise ValueError("name and name_re are mutually exclusive")
        if self.scope not in ("children", "descendants"):
            raise ValueError(f"invalid scope {self.scope!r}")

    def compile(self) -> "_CompiledSelector":
        return _CompiledSelector(self)


class _CompiledSelector:
    """预编译的正则，避免每次匹配重复编译。"""

    __slots__ = ("index", "scope", "_name_re", "automation_id", "_control_type", "class_name")

    def __init__(self, sel: UiaSelector) -> None:
        self.index = sel.index
        self.scope = sel.scope
        self.automation_id = sel.automation_id
        self.class_name = sel.class_name
        self._control_type = (
            sel.control_type.value if isinstance(sel.control_type, ControlType) else sel.control_type
        )
        if sel.name is not None:
            self._name_re = re.compile(re.escape(sel.name))
        elif sel.name_re is not None:
            self._name_re = re.compile(sel.name_re)
        else:
            self._name_re = None

    def matches(self, node: "UiaNode") -> bool:
        if self._name_re is not None and not self._name_re.search(node.name or ""):
            return False
        if self.automation_id is not None and node.automation_id != self.automation_id:
            return False
        if self.class_name is not None and node.class_name != self.class_name:
            return False
        if self._control_type is not None and node.control_type != self._control_type:
            return False
        return True


# ---- 读回 / 后置锚点 / 控件映射 ----

@dataclass(frozen=True)
class ReadbackSpec:
    """动作后的值读回：以“读取回值/页面证据”为准，不以点击完成为准。

    - kind=NONE 时只依赖 post_anchor
    - expected：期望值（VALUE 为字符串；TOGGLE_STATE 为 int；NAME 为字符串）
    - expected_re：正则（与 expected 二选一）
    - stability_frames：连续 N 次读回一致才判定成功（防瞬态）
    - interval_s：两次读回间隔
    """

    kind: ReadbackKind = ReadbackKind.NONE
    expected: Any = None
    expected_re: str | None = None
    stability_frames: int = 2
    interval_s: float = 0.5

    def __post_init__(self) -> None:
        if self.expected is not None and self.expected_re is not None:
            raise ValueError("expected and expected_re are mutually exclusive")


@dataclass(frozen=True)
class PostAnchorSpec:
    """动作的后置页面确认锚点（必须出现/消失才算动作生效）。"""

    selector: UiaSelector
    condition: AnchorCondition = AnchorCondition.EXISTS
    timeout_s: float | None = None  # None -> 使用动作的 fail_timeout


@dataclass(frozen=True)
class ControlMapping:
    """一个局外控件的完整动作定义。

    - selector：控件定位（多属性 + 备选链见 mappings.py 的 variants）
    - action：INVOKE / VALUE_SET / TOGGLE / NONE(纯读)
    - value：VALUE_SET 时写入的文本（来自 settings.room_name / room_password）
    - readback：动作后值读回方式
    - post_anchor：动作后页面证据（可空）
    - fail_timeout_s：Fail-Closed 总期限（默认 30s，蓝图 L0 门禁）
    - max_attempts：读回/锚点不满足时的重试预算（有界，不无限重试）
    """

    key: str
    selector: UiaSelector
    action: PatternKind = PatternKind.NONE
    value: str | None = None
    readback: ReadbackSpec = field(default_factory=ReadbackSpec)
    post_anchor: PostAnchorSpec | None = None
    fail_timeout_s: float = 30.0
    max_attempts: int = 3
    # 备选选择器链：selector 未命中时按序尝试（皮肤/版本变体），
    # 全部未命中才 Fail-Closed。
    variants: tuple[UiaSelector, ...] = ()


# ---- 树节点与快照 ----

@dataclass
class UiaNode:
    """UIA 元素的可序列化快照（与后端解耦，供 selector/trace 使用）。"""

    name: str | None = None
    automation_id: str | None = None
    control_type: int | None = None
    class_name: str | None = None
    framework_id: str | None = None
    pid: int | None = None
    rect: tuple[int, int, int, int] | None = None  # (left, top, right, bottom) 物理像素
    children: list["UiaNode"] = field(default_factory=list)
    depth: int = 0
    # 后端句柄（不参与序列化/比较；快照后立即使用，不跨快照保存）
    handle: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "automation_id": self.automation_id,
            "control_type": self.control_type,
            "class_name": self.class_name,
            "framework_id": self.framework_id,
            "pid": self.pid,
            "rect": self.rect,
            "depth": self.depth,
            "children": [c.to_dict() for c in self.children],
        }


@dataclass
class TreeSnapshot:
    """一次 UIA 树快照：根节点 + 采集元数据 + 失效规则。"""

    root: UiaNode | None = None
    taken_at: float = field(default_factory=time.monotonic)
    window_key: tuple[Any, ...] | None = None  # (pid, class_name, title) 窗口身份指纹
    node_count: int = 0
    truncated: bool = False  # 达到节点预算被截断（仍可用，但缺失部分子树）
    source_desc: str = ""    # 后端描述（ctypes / mock / comtypes）

    def is_stale(self, max_age_s: float, now: float | None = None) -> bool:
        now = now if now is not None else time.monotonic()
        return (now - self.taken_at) > max_age_s

    def matches_window(self, window_key: tuple[Any, ...]) -> bool:
        return self.window_key == window_key


# ---- 动作 trace ----

@dataclass
class UiaActionTrace:
    """每次建房的 UIA 动作记录（selector、值、耗时），供 20 次 dry-run 门禁统计。"""

    mapping_key: str
    selector_resolved: bool = False
    selector_detail: str = ""          # 命中的节点属性摘要
    readback_values: list[Any] = field(default_factory=list)
    readback_ok: bool = False
    anchor_ok: bool = False
    action_ok: bool = False
    elapsed_s: float = 0.0
    attempts: int = 0
    error: str | None = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mapping_key": self.mapping_key,
            "selector_resolved": self.selector_resolved,
            "selector_detail": self.selector_detail,
            "readback_values": self.readback_values,
            "readback_ok": self.readback_ok,
            "anchor_ok": self.anchor_ok,
            "action_ok": self.action_ok,
            "elapsed_s": round(self.elapsed_s, 3),
            "attempts": self.attempts,
            "error": self.error,
            "timestamp": self.timestamp,
        }
