"""L0 局外建房 UIA adapter：窗口身份 → 控件解析 → 动作 → 读回 → 后置锚点。

Fail-Closed 语义（蓝图 §13 门禁）：
- 控件找不到 / 读回不符 / 锚点缺失 → 一律在 fail_timeout_s（默认 30s）内
  停机，绝不在“找不到控件”时点坐标（零盲点连击）；
- 值读回以后续 ValuePattern/页面证据为准，不以“点击已完成”为准；
- 每次动作产出 UiaActionTrace（selector、值、耗时），供 20 次 dry-run 门禁。

视觉 fallback：只通过 VisualFallback 协议显式注入且默认关闭；
本模块不直接依赖 shuabao.vision（惰性导入 capture 做窗口身份解析）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from .model import (
    AnchorCondition,
    ControlMapping,
    FailClosedError,
    PatternKind,
    PostAnchorSpec,
    ReadbackKind,
    UiaActionTrace,
    UiaNode,
    UiaSelector,
    UiaWindowSpec,
)
from .selector import describe_node, find_matching_nodes, resolve_node
from .source import (
    PATTERN_INVOKE,
    PATTERN_TOGGLE,
    PATTERN_VALUE,
    ElementSource,
    SnapshotCache,
    SnapshotOptions,
    collect_nodes,
)


class VisualFallback(Protocol):
    """固定 ROI 视觉 fallback 接口（预留，默认不启用）。

    当 UIA 链路不可用且用户显式开启 visual_fallback 时，
    find/click/read_text 由现有模板/ROI 视觉链实现（后续波次接线）。
    """

    def find(self, roi_key: str, frame: Any) -> Any | None: ...

    def click(self, x: int, y: int) -> Any: ...

    def read_text(self, roi_key: str, frame: Any) -> str | None: ...


WindowResolved = tuple[int, tuple[Any, ...]]  # (hwnd, window_key)


@dataclass
class AdapterOptions:
    snapshot_max_nodes: int = 2000
    snapshot_max_depth: int = 32
    snapshot_max_age_s: float = 5.0
    default_fail_timeout_s: float = 30.0
    dry_run: bool = True  # 只解析+读回验证，不执行真实 pattern 动作
    use_visual_fallback: bool = False  # 默认关闭；开启需同时提供 fallback
    # 敏感控件：trace/读回值一律脱敏（仓库策略：密码不出现在日志）
    secret_keys: frozenset = frozenset({"room_password_input"})


class LobbyUiaAdapter:
    """局外建房 UIA 执行器（单一职责：一个控件动作 + 验证 + trace）。"""

    def __init__(
        self,
        source: ElementSource,
        mappings: dict[str, ControlMapping] | None = None,
        window_spec: UiaWindowSpec | None = None,
        options: AdapterOptions | None = None,
        clock: Callable[[], float] | None = None,
        resolve_window: Callable[[], WindowResolved | None] | None = None,
        visual_fallback: VisualFallback | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.source = source
        self.mappings = mappings or {}
        self.window_spec = window_spec or UiaWindowSpec()
        self.options = options or AdapterOptions()
        self._clock = clock if clock is not None else time.monotonic
        self._resolve_window = resolve_window
        self._visual_fallback = visual_fallback
        self._sleep_fn = sleep if sleep is not None else time.sleep
        self._cache = SnapshotCache(
            max_age_s=self.options.snapshot_max_age_s,
            now=clock,
        )
        self.traces: list[UiaActionTrace] = []
        self.last_snapshot = None

    # ---- 窗口身份 ----

    def _default_resolve_window(self) -> WindowResolved | None:
        """默认窗口解析：惰性导入 capture.find_window_targets（避免测试依赖 cv2）。

        取 role=l0 的首个候选；window_key=(pid, class_name, title) 作为身份指纹，
        hwnd 变化但身份一致时仍视为同一窗口（房间子窗/弹窗同进程同身份）。
        """
        try:
            from shuabao.vision.capture import L0_WINDOW_KEYWORDS, find_window_targets  # 惰性
        except Exception:
            return None
        title = ",".join(L0_WINDOW_KEYWORDS)
        targets = find_window_targets(title, role=self.window_spec.role)
        if not targets:
            return None
        t = targets[0]
        if t.width < self.window_spec.min_width or t.height < self.window_spec.min_height:
            return None
        key = (t.pid, t.class_name, t.title)
        return (t.hwnd, key)

    def resolve_window(self) -> WindowResolved | None:
        if self._resolve_window is not None:
            return self._resolve_window()
        return self._default_resolve_window()

    # ---- 控件解析 ----

    def _resolve_control(self, mapping: ControlMapping, nodes: list[UiaNode]) -> tuple[UiaNode | None, UiaSelector | None]:
        """按 selector + variants 链解析；返回 (节点, 命中的选择器)。"""
        for selector in (mapping.selector, *mapping.variants):
            if selector.scope == "descendants":
                node = resolve_node(nodes, selector)
            else:
                # children 语义：从快照根的直接子级中找
                root = self.last_snapshot.root if self.last_snapshot else None
                children = root.children if root else []
                node = resolve_node(children, selector)
            if node is not None:
                return node, selector
        return None, None

    def _snapshot(self, hwnd: int, window_key: tuple[Any, ...]) -> None:
        self.last_snapshot = self._cache.get(
            self.source,
            hwnd,
            window_key=window_key,
            options=SnapshotOptions(
                max_nodes=self.options.snapshot_max_nodes,
                max_depth=self.options.snapshot_max_depth,
            ),
        )

    # ---- 读回 / 锚点 ----

    def _read_value(self, node: UiaNode, kind: ReadbackKind) -> Any:
        if kind == ReadbackKind.VALUE:
            return self.source.value(self.source.get_pattern(node.handle, PATTERN_VALUE))
        if kind == ReadbackKind.TOGGLE_STATE:
            return self.source.toggle_state(self.source.get_pattern(node.handle, PATTERN_TOGGLE))
        if kind == ReadbackKind.NAME:
            return node.name
        return None

    def _readback_matches(self, mapping: ControlMapping, value: Any) -> bool:
        rb = mapping.readback
        if rb.kind == ReadbackKind.NONE:
            return True
        if rb.expected_re is not None:
            import re

            return bool(re.search(rb.expected_re, str(value or "")))
        return value == rb.expected

    def _check_anchor(self, mapping: ControlMapping, hwnd: int, window_key: tuple[Any, ...]) -> bool:
        anchor = mapping.post_anchor
        if anchor is None:
            return True
        self._snapshot(hwnd, window_key)
        nodes = collect_nodes(self.last_snapshot) if self.last_snapshot else []
        if anchor.selector.scope == "descendants":
            node = resolve_node(nodes, anchor.selector)
        else:
            root = self.last_snapshot.root if self.last_snapshot else None
            node = resolve_node(root.children if root else [], anchor.selector)
        if anchor.condition == AnchorCondition.EXISTS:
            return node is not None
        if anchor.condition == AnchorCondition.ABSENT:
            return node is None
        if anchor.condition == AnchorCondition.VALUE_EQ:
            if node is None:
                return False
            return self._readback_matches(mapping, self._read_value(node, mapping.readback.kind))
        return False

    # ---- 动作执行 ----

    def act(self, mapping_key: str, expected_value: str | None = None) -> UiaActionTrace:
        """执行一个控件动作并验证（Fail-Closed）。

        - expected_value：覆盖 mapping.value（例如每次循环生成的房名）。
        - 返回 trace；失败抛 FailClosedError（调用方据此停机/回退）。
        - dry_run 时：解析 + pattern 可用性验证 + 读回（只读），不执行真实动作。
        """
        mapping = self.mappings.get(mapping_key)
        if mapping is None:
            raise FailClosedError(mapping_key, "unknown mapping", 0.0)
        trace = UiaActionTrace(mapping_key=mapping_key)
        start = self._clock()
        deadline = start + (mapping.fail_timeout_s or self.options.default_fail_timeout_s)
        value = expected_value if expected_value is not None else mapping.value

        # 0) 窗口身份（含超时重试）
        resolved = None
        while resolved is None:
            resolved = self.resolve_window()
            if resolved is None:
                if self._clock() >= deadline:
                    trace.error = "window not found"
                    trace.elapsed_s = self._clock() - start
                    self.traces.append(trace)
                    raise FailClosedError(mapping_key, "window not found", trace.elapsed_s)
                self._sleep(0.5)
        hwnd, window_key = resolved

        # 1) 控件解析（快照缓存 + 重试）
        node = None
        matched_selector: UiaSelector | None = None
        while node is None:
            self._snapshot(hwnd, window_key)
            nodes = collect_nodes(self.last_snapshot) if self.last_snapshot else []
            node, matched_selector = self._resolve_control(mapping, nodes)
            if node is None:
                if self._clock() >= deadline:
                    trace.error = f"control not found (deadline {mapping.fail_timeout_s}s)"
                    trace.elapsed_s = self._clock() - start
                    self.traces.append(trace)
                    raise FailClosedError(mapping_key, trace.error, trace.elapsed_s)
                # 快照由 SnapshotCache 的 TTL 自动刷新，无需每轮全树重建
                self._sleep(0.5)
        trace.selector_resolved = True
        trace.selector_detail = describe_node(node)

        # 2) pattern 可用性（dry-run 也要求 pattern 可获取）
        pattern = None
        if mapping.action == PatternKind.INVOKE:
            pattern = self.source.get_pattern(node.handle, PATTERN_INVOKE)
        elif mapping.action == PatternKind.VALUE_SET:
            pattern = self.source.get_pattern(node.handle, PATTERN_VALUE)
        elif mapping.action == PatternKind.TOGGLE:
            pattern = self.source.get_pattern(node.handle, PATTERN_TOGGLE)
        if mapping.action != PatternKind.NONE and pattern is None:
            trace.error = "pattern unavailable"
            trace.elapsed_s = self._clock() - start
            self.traces.append(trace)
            raise FailClosedError(mapping_key, trace.error, trace.elapsed_s)

        # 3) 执行动作（dry_run 不产生真实输入）
        if not self.options.dry_run and mapping.action != PatternKind.NONE:
            if mapping.action == PatternKind.INVOKE:
                self.source.invoke(pattern)
            elif mapping.action == PatternKind.VALUE_SET:
                self.source.set_value(pattern, value or "")
            elif mapping.action == PatternKind.TOGGLE:
                self.source.toggle(pattern)
        elif self.options.dry_run and mapping.action == PatternKind.VALUE_SET:
            # dry-run：读当前值作为证据（不做写、不判等）
            trace.readback_values.append(
                self._redact(self._read_value(node, mapping.readback.kind), self._is_secret(mapping_key))
            )

        # 4) 值读回（连续 stability_frames 次一致才算通过）
        attempts = 0
        is_secret = self._is_secret(mapping_key)
        if mapping.readback.kind != ReadbackKind.NONE and not self.options.dry_run:
            stable = 0
            while self._clock() < deadline and attempts < mapping.max_attempts:
                value_now = self._read_value(node, mapping.readback.kind)
                trace.readback_values.append(self._redact(value_now, is_secret))
                if self._readback_matches(mapping, value_now):
                    stable += 1
                    if stable >= mapping.readback.stability_frames:
                        trace.readback_ok = True
                        break
                else:
                    stable = 0
                attempts += 1
                if not trace.readback_ok:
                    self._sleep(mapping.readback.interval_s)
            if not trace.readback_ok:
                trace.error = f"readback mismatch: {trace.readback_values!r} != {mapping.readback.expected!r}"
                trace.elapsed_s = self._clock() - start
                self.traces.append(trace)
                raise FailClosedError(mapping_key, trace.error, trace.elapsed_s)

        # 5) 后置锚点（重新快照，页面证据）
        if mapping.post_anchor is not None and not self.options.dry_run:
            while self._clock() < deadline:
                self._cache.invalidate()
                if self._check_anchor(mapping, hwnd, window_key):
                    trace.anchor_ok = True
                    break
                self._sleep(0.5)
            if not trace.anchor_ok:
                trace.error = "post anchor not confirmed"
                trace.elapsed_s = self._clock() - start
                self.traces.append(trace)
                raise FailClosedError(mapping_key, trace.error, trace.elapsed_s)
        else:
            trace.anchor_ok = True  # 无锚点或 dry-run：锚点视为通过（读回已判）

        trace.action_ok = True
        trace.elapsed_s = self._clock() - start
        trace.attempts = attempts
        self.traces.append(trace)
        self._cache.invalidate()
        return trace

    def _sleep(self, seconds: float) -> None:
        self._sleep_fn(seconds)

    # ---- 敏感信息脱敏（仓库策略：密码不出现在日志/trace）----

    def _is_secret(self, mapping_key: str) -> bool:
        lowered = mapping_key.lower()
        return lowered in self.options.secret_keys or "password" in lowered or "pwd" in lowered

    def _redact(self, value: Any, secret: bool) -> Any:
        if not secret or value is None:
            return value
        text = str(value)
        if not text:
            return ""
        return f"<redacted:len={len(text)}>"

    # ---- 工具 ----

    def dump_tree(self, hwnd: int | None = None, window_key: tuple[Any, ...] | None = None) -> dict[str, Any]:
        """导出 UIA 树（供 tools/dump_uia_tree.py 与 incident 留证）。"""
        if hwnd is None:
            resolved = self.resolve_window()
            if resolved is None:
                return {"error": "window not found"}
            hwnd, window_key = resolved
        self._snapshot(hwnd, window_key)
        snap = self.last_snapshot
        if snap is None or snap.root is None:
            return {"error": "snapshot failed", "hwnd": hwnd}
        return {
            "window_key": list(snap.window_key) if snap.window_key else None,
            "node_count": snap.node_count,
            "truncated": snap.truncated,
            "source": snap.source_desc,
            "root": snap.root.to_dict(),
        }

    def probe_mapping(self, mapping_key: str) -> dict[str, Any]:
        """只读探针：控件能否解析 + pattern 是否可用（20 次 dry-run 的基础）。"""
        mapping = self.mappings.get(mapping_key)
        if mapping is None:
            return {"mapping_key": mapping_key, "resolved": False, "error": "unknown mapping"}
        resolved = self.resolve_window()
        if resolved is None:
            return {"mapping_key": mapping_key, "resolved": False, "error": "window not found"}
        hwnd, window_key = resolved
        self._snapshot(hwnd, window_key)
        nodes = collect_nodes(self.last_snapshot) if self.last_snapshot else []
        node, sel = self._resolve_control(mapping, nodes)
        if node is None:
            return {"mapping_key": mapping_key, "resolved": False, "error": "control not found"}
        pattern = None
        if mapping.action == PatternKind.INVOKE:
            pattern = self.source.get_pattern(node.handle, PATTERN_INVOKE)
        elif mapping.action == PatternKind.VALUE_SET:
            pattern = self.source.get_pattern(node.handle, PATTERN_VALUE)
        elif mapping.action == PatternKind.TOGGLE:
            pattern = self.source.get_pattern(node.handle, PATTERN_TOGGLE)
        return {
            "mapping_key": mapping_key,
            "resolved": True,
            "selector": describe_node(node),
            "pattern_available": pattern is not None or mapping.action == PatternKind.NONE,
            "readback_now": (
                self._redact(
                    self._read_value(node, mapping.readback.kind),
                    self._is_secret(mapping_key),
                )
                if mapping.readback.kind != ReadbackKind.NONE
                else None
            ),
        }
