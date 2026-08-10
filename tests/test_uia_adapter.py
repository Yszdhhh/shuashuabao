"""LobbyUiaAdapter 单测：动作执行 / 读回 / 后置锚点 / Fail-Closed 计时。

全部使用 FakeSource + 假时钟，无 COM、无 cv2。
覆盖蓝图 §13 L0 门禁的适配器侧语义：
- 找不到控件 30s 内 Fail-Closed，零盲点连击（不执行任何动作）；
- 值读回以后续证据为准（stability_frames 连续一致）；
- 关卡 1-16 读回必须判失败（STAGE_RE 拒绝）；
- dry_run 不产生真实动作。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from gamescript.ui.uia.adapter import AdapterOptions, LobbyUiaAdapter
from gamescript.ui.uia.model import (
    AnchorCondition,
    ControlMapping,
    FailClosedError,
    PatternKind,
    PostAnchorSpec,
    ReadbackKind,
    ReadbackSpec,
    UiaSelector,
)
from gamescript.ui.uia.mappings import KK_LOBBY_MAPPINGS
from gamescript.ui.uia.source import PROP_AUTOMATION_ID, PROP_CLASS_NAME, PROP_CONTROL_TYPE, PROP_NAME, PROP_PROCESS_ID

WINDOW_KEY = (111, "Qt5QWindowIcon", "KK官方对战平台")
HWND = 0x1234


class FakeElement:
    def __init__(self, eid, name=None, auto_id=None, ctype=None, cls=None, pid=111, children=None):
        self.eid = eid
        self.name = name
        self.auto_id = auto_id
        self.ctype = ctype
        self.cls = cls
        self.pid = pid
        self.children = list(children or [])
        self.patterns: set[int] = set()
        self.value_text = ""
        self.toggle_state_val = 0


class FakeSource:
    """可编程假 UIA 源：记录动作、支持树变化、可让控件“不可用”。"""

    def __init__(self, elements: dict, root_id: str):
        self.elements = elements
        self.root_id = root_id
        self.actions: list[tuple] = []
        self.available = True
        self.after_invoke: dict[str, callable] = {}
        self.pattern_gate: set[str] = set()  # 元素 id -> pattern 不可获取

    def is_available(self):
        return self.available

    def describe(self):
        return "fake"

    def element_from_handle(self, hwnd):
        if not hwnd or self.root_id not in self.elements:
            return None
        return self.root_id

    def get_property(self, element, prop_id):
        el = self.elements.get(element)
        if el is None:
            return None
        return {
            PROP_NAME: el.name,
            PROP_AUTOMATION_ID: el.auto_id,
            PROP_CONTROL_TYPE: el.ctype,
            PROP_CLASS_NAME: el.cls,
            PROP_PROCESS_ID: el.pid,
        }.get(prop_id)

    def children(self, element):
        el = self.elements.get(element)
        return list(el.children) if el else []

    def get_pattern(self, element, pattern_id):
        el = self.elements.get(element)
        if el is None or element in self.pattern_gate or pattern_id not in el.patterns:
            return None
        return (pattern_id, element)

    def invoke(self, pattern):
        pid, eid = pattern
        self.actions.append(("invoke", eid))
        hook = self.after_invoke.get(eid)
        if hook:
            hook()

    def set_value(self, pattern, text):
        pid, eid = pattern
        self.actions.append(("set_value", eid, text))
        self.elements[eid].value_text = text

    def toggle(self, pattern):
        pid, eid = pattern
        self.actions.append(("toggle", eid))
        self.elements[eid].toggle_state_val = 1 - self.elements[eid].toggle_state_val

    def value(self, pattern):
        pid, eid = pattern
        return self.elements[eid].value_text

    def toggle_state(self, pattern):
        pid, eid = pattern
        return self.elements[eid].toggle_state_val

    def close(self):
        pass


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


class KKTree:
    """脚本化的 KK 局外树：map 页 → 弹窗 → 房间 → 选关。"""

    def __init__(self):
        self.elements: dict[str, FakeElement] = {}
        self.root = "win"
        self.elements["win"] = FakeElement("win", name="KK官方对战平台", ctype=50032, children=["map_pane"])
        self.elements["map_pane"] = FakeElement("map_pane", name="", ctype=50033, children=["btn_create"])
        self.elements["btn_create"] = FakeElement(
            "btn_create", name="创建房间", auto_id="btnCreate", ctype=50000, cls="Button", children=[]
        )
        self.elements["btn_create"].patterns.add(10000)
        self.source = FakeSource(self.elements, "win")

    def open_dialog(self):
        """创建房间点击后：弹窗出现（含两个 Edit + 确认按钮）。"""
        self.elements["dialog"] = FakeElement("dialog", name="创建房间", ctype=50032, children=["edit_name", "edit_pwd", "btn_confirm"])
        self.elements["edit_name"] = FakeElement("edit_name", name="", ctype=50004, cls="Edit")
        self.elements["edit_name"].patterns.add(10002)
        self.elements["edit_pwd"] = FakeElement("edit_pwd", name="", ctype=50004, cls="Edit")
        self.elements["edit_pwd"].patterns.add(10002)
        self.elements["btn_confirm"] = FakeElement("btn_confirm", name="确定", ctype=50000, cls="Button")
        self.elements["btn_confirm"].patterns.add(10000)
        self.elements["win"].children = ["map_pane", "dialog"]

    def enter_room(self):
        """确认后：房间页（开始游戏按钮）。"""
        self.elements["btn_start"] = FakeElement("btn_start", name="开始游戏", ctype=50000, cls="Button")
        self.elements["btn_start"].patterns.add(10000)
        self.elements["win"].children = ["room_pane"]
        self.elements["room_pane"] = FakeElement("room_pane", name="", ctype=50033, children=["btn_start"])

    def open_stage(self, stage_name="1-15"):
        """开始游戏后：选关页（关卡行 + 开始按钮）。"""
        self.elements["stage_item"] = FakeElement("stage_item", name=stage_name, ctype=50007, cls="ListItem")
        self.elements["stage_item"].patterns.add(10000)
        self.elements["btn_stage_start"] = FakeElement("btn_stage_start", name="开始游戏", ctype=50000, cls="Button")
        self.elements["btn_stage_start"].patterns.add(10000)
        self.elements["win"].children = ["stage_pane"]
        self.elements["stage_pane"] = FakeElement("stage_pane", name="", ctype=50033, children=["stage_item", "btn_stage_start"])


def make_adapter(
    tree: KKTree,
    clock: FakeClock,
    dry_run: bool = False,
    mappings: dict | None = None,
    window_resolver=None,
    fail_timeout: float = 30.0,
) -> LobbyUiaAdapter:
    return LobbyUiaAdapter(
        source=tree.source,
        mappings=mappings or KK_LOBBY_MAPPINGS,
        options=AdapterOptions(dry_run=dry_run, snapshot_max_age_s=60.0),
        clock=clock,
        resolve_window=window_resolver or (lambda: (HWND, WINDOW_KEY)),
        sleep=lambda s: clock.advance(s),
    )


class AdapterHappyPathTests(unittest.TestCase):
    def setUp(self):
        self.tree = KKTree()
        self.clock = FakeClock()
        self.adapter = make_adapter(self.tree, self.clock, dry_run=False)

    def test_invoke_create_room_and_anchor(self):
        self.tree.source.after_invoke["btn_create"] = self.tree.open_dialog
        trace = self.adapter.act("create_room_button")
        self.assertTrue(trace.action_ok)
        self.assertTrue(trace.selector_resolved)
        self.assertTrue(trace.anchor_ok)
        self.assertIn(("invoke", "btn_create"), self.tree.source.actions)
        self.assertIn("创建房间", trace.selector_detail)

    def test_value_set_room_name_with_readback(self):
        self.tree.open_dialog()
        self.adapter._cache.invalidate()
        mapping = self.tree_room_mapping("room_name_input", "我的房间")
        self.adapter.mappings["room_name_input"] = mapping
        trace = self.adapter.act("room_name_input")
        self.assertTrue(trace.action_ok)
        self.assertTrue(trace.readback_ok)
        self.assertIn(("set_value", "edit_name", "我的房间"), self.tree.source.actions)
        self.assertEqual(trace.readback_values[-1], "我的房间")

    def tree_room_mapping(self, key, value):
        m = KK_LOBBY_MAPPINGS[key]
        return ControlMapping(
            key=key,
            selector=m.selector,
            action=m.action,
            value=value,
            readback=ReadbackSpec(kind=ReadbackKind.VALUE, expected=value, stability_frames=2),
            fail_timeout_s=30.0,
        )

    def test_room_name_and_password_index_semantics(self):
        """两个同属性 Edit 按 index 0/1 分别命中。"""
        self.tree.open_dialog()
        self.adapter._cache.invalidate()
        self.adapter.mappings["room_name_input"] = self.tree_room_mapping("room_name_input", "roomA")
        self.adapter.mappings["room_password_input"] = self.tree_room_mapping("room_password_input", "pwd1")
        t1 = self.adapter.act("room_name_input")
        t2 = self.adapter.act("room_password_input")
        self.assertIn(("set_value", "edit_name", "roomA"), self.tree.source.actions)
        self.assertIn(("set_value", "edit_pwd", "pwd1"), self.tree.source.actions)
        self.assertTrue(t1.readback_ok and t2.readback_ok)

    def test_stage_readback_accepts_1_15(self):
        self.tree.open_stage("1-15")
        self.adapter._cache.invalidate()
        trace = self.adapter.act("stage_item")
        self.assertTrue(trace.readback_ok)
        self.assertTrue(trace.action_ok)

    def test_stage_readback_rejects_1_16(self):
        """蓝图门禁：关卡配置 1-15 时读回不得为 1-16。"""
        self.tree.open_stage("1-16")
        self.adapter._cache.invalidate()
        with self.assertRaises(FailClosedError):
            self.adapter.act("stage_item")

    def test_toggle_pattern(self):
        self.tree.elements["chk"] = FakeElement("chk", name="自动准备", ctype=50002, cls="CheckBox", children=[])
        self.tree.elements["chk"].patterns.add(10016)
        self.tree.elements["win"].children = ["map_pane", "chk"]
        mapping = ControlMapping(
            key="auto_ready",
            selector=UiaSelector(name="自动准备", scope="descendants"),
            action=PatternKind.TOGGLE,
            readback=ReadbackSpec(kind=ReadbackKind.TOGGLE_STATE, expected=1, stability_frames=2),
            fail_timeout_s=30.0,
        )
        self.adapter.mappings["auto_ready"] = mapping
        self.adapter._cache.invalidate()
        trace = self.adapter.act("auto_ready")
        self.assertTrue(trace.action_ok)
        self.assertIn(("toggle", "chk"), self.tree.source.actions)
        self.assertEqual(trace.readback_values[-1], 1)

    def test_anchor_absent_condition(self):
        """退出回房：选关页关卡行消失才算生效（房间页也有开始按钮）。"""
        self.tree.open_stage("1-15")
        mapping = ControlMapping(
            key="exit",
            selector=UiaSelector(name="退出", control_type=50000, scope="descendants"),
            action=PatternKind.INVOKE,
            post_anchor=PostAnchorSpec(
                selector=UiaSelector(name_re=r"^1-(1[0-5]|[1-9])$", scope="descendants"),
                condition=AnchorCondition.ABSENT,
            ),
            fail_timeout_s=30.0,
        )
        self.adapter.mappings["exit"] = mapping
        # 点击“退出”后选关页消失（返回房间页）
        self.tree.elements["btn_exit"] = FakeElement("btn_exit", name="退出", ctype=50000)
        self.tree.elements["btn_exit"].patterns.add(10000)
        self.tree.elements["stage_pane"].children = ["stage_item", "btn_stage_start", "btn_exit"]

        def _exit():
            self.tree.elements["win"].children = ["room_pane"]
            self.tree.elements["room_pane"] = FakeElement("room_pane", name="", ctype=50033, children=["btn_start"])
            self.tree.elements["btn_start"] = FakeElement("btn_start", name="开始游戏", ctype=50000)

        self.tree.source.after_invoke["btn_exit"] = _exit
        self.adapter._cache.invalidate()
        trace = self.adapter.act("exit")
        self.assertTrue(trace.action_ok)
        self.assertTrue(trace.anchor_ok)


class AdapterFailClosedTests(unittest.TestCase):
    def setUp(self):
        self.tree = KKTree()
        self.clock = FakeClock()
        self.adapter = make_adapter(self.tree, self.clock, dry_run=False, fail_timeout=30.0)

    def test_control_missing_fails_closed_within_timeout(self):
        """控件永远不出现：30s 内 Fail-Closed，且零动作。"""
        start = self.clock()
        with self.assertRaises(FailClosedError) as ctx:
            self.adapter.act("stage_item")  # 树里没有选关页
        elapsed = ctx.exception.elapsed_s
        self.assertGreaterEqual(elapsed, 29.0)
        self.assertLess(elapsed, 31.0)
        self.assertEqual(self.tree.source.actions, [])  # 零盲点连击

    def test_window_missing_fails_closed(self):
        adapter = make_adapter(self.tree, self.clock, window_resolver=lambda: None)
        with self.assertRaises(FailClosedError) as ctx:
            adapter.act("create_room_button")
        self.assertIn("window not found", ctx.exception.reason)
        self.assertGreaterEqual(ctx.exception.elapsed_s, 29.0)

    def test_readback_mismatch_fails_closed(self):
        """写入后读回永远不匹配 → Fail-Closed（不以点击完成为准）。"""
        self.tree.open_dialog()
        self.tree.source.set_value = lambda pattern, text: None  # 写入被吞（控件不生效）
        self.adapter._cache.invalidate()
        self.adapter.mappings["room_name_input"] = self.tree_room_mapping("room_name_input", "期望房名")
        with self.assertRaises(FailClosedError) as ctx:
            self.adapter.act("room_name_input")
        self.assertIn("readback mismatch", ctx.exception.reason)

    def tree_room_mapping(self, key, value):
        m = KK_LOBBY_MAPPINGS[key]
        return ControlMapping(
            key=key,
            selector=m.selector,
            action=m.action,
            value=value,
            readback=ReadbackSpec(kind=ReadbackKind.VALUE, expected=value, stability_frames=2),
            fail_timeout_s=30.0,
        )

    def test_pattern_unavailable_fails_closed(self):
        """控件找到了但没有 Invoke pattern → 拒绝执行。"""
        self.tree.source.pattern_gate.add("btn_create")
        with self.assertRaises(FailClosedError) as ctx:
            self.adapter.act("create_room_button")
        self.assertIn("pattern unavailable", ctx.exception.reason)
        self.assertEqual(self.tree.source.actions, [])

    def test_post_anchor_missing_fails_closed(self):
        """点击后页面锚点不出现 → Fail-Closed。"""
        # 点击创建房间后弹窗不出现
        self.tree.source.after_invoke["btn_create"] = lambda: None
        with self.assertRaises(FailClosedError) as ctx:
            self.adapter.act("create_room_button")
        self.assertIn("post anchor", ctx.exception.reason)

    def test_unknown_mapping_raises_immediately(self):
        with self.assertRaises(FailClosedError):
            self.adapter.act("no_such_key")

    def test_anchor_absent_never_satisfied_fails_closed(self):
        self.tree.open_stage("1-15")
        mapping = ControlMapping(
            key="exit",
            selector=UiaSelector(name="退出", control_type=50000, scope="descendants"),
            action=PatternKind.INVOKE,
            post_anchor=PostAnchorSpec(
                selector=UiaSelector(name_re=r"^1-(1[0-5]|[1-9])$", scope="descendants"),
                condition=AnchorCondition.ABSENT,
            ),
            fail_timeout_s=30.0,
        )
        self.adapter.mappings["exit"] = mapping
        self.tree.elements["btn_exit"] = FakeElement("btn_exit", name="退出", ctype=50000)
        self.tree.elements["btn_exit"].patterns.add(10000)
        self.tree.elements["stage_pane"].children = ["stage_item", "btn_stage_start", "btn_exit"]
        self.tree.source.after_invoke["btn_exit"] = lambda: None  # 页面不变
        self.adapter._cache.invalidate()
        with self.assertRaises(FailClosedError):
            self.adapter.act("exit")


class AdapterDryRunTests(unittest.TestCase):
    def setUp(self):
        self.tree = KKTree()
        self.tree.open_dialog()
        self.clock = FakeClock()
        self.adapter = make_adapter(self.tree, self.clock, dry_run=True)

    def test_dry_run_no_mutation(self):
        self.adapter.act("create_room_button")
        self.adapter.act("room_name_input")
        self.assertEqual(self.tree.source.actions, [])  # 零真实输入

    def test_dry_run_requires_pattern_availability(self):
        self.tree.source.pattern_gate.add("btn_create")
        with self.assertRaises(FailClosedError):
            self.adapter.act("create_room_button")

    def test_dry_run_value_set_records_current_value(self):
        self.tree.elements["edit_name"].value_text = "旧房名"
        self.adapter._cache.invalidate()
        trace = self.adapter.act("room_name_input")
        self.assertTrue(trace.action_ok)
        self.assertEqual(trace.readback_values, ["旧房名"])

    def test_password_readback_is_redacted(self):
        """仓库策略：密码值不得出现在 trace/日志。"""
        self.tree.elements["edit_pwd"].value_text = "super-secret-pwd"
        self.adapter._cache.invalidate()
        trace = self.adapter.act("room_password_input")
        self.assertTrue(trace.action_ok)
        self.assertIn("<redacted", trace.readback_values[0])
        self.assertNotIn("super-secret-pwd", str(trace.readback_values))
        result = self.adapter.probe_mapping("room_password_input")
        self.assertIn("<redacted", str(result["readback_now"]))

    def test_probe_mapping_read_only(self):
        result = self.adapter.probe_mapping("room_name_input")
        self.assertTrue(result["resolved"])
        self.assertTrue(result["pattern_available"])
        self.assertEqual(self.tree.source.actions, [])

    def test_dump_tree_serializes(self):
        tree = self.adapter.dump_tree(HWND, WINDOW_KEY)
        self.assertEqual(tree["node_count"], 7)  # win+map_pane+btn_create+dialog+2edit+confirm
        self.assertEqual(tree["window_key"], list(WINDOW_KEY))
        self.assertIsNotNone(tree["root"])


if __name__ == "__main__":
    unittest.main()
