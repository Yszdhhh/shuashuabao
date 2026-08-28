"""树快照构建/预算/环检测与缓存失效单测（FakeSource，无 COM）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from shuabao.ui.uia.source import (
    PROP_AUTOMATION_ID,
    PROP_CLASS_NAME,
    PROP_CONTROL_TYPE,
    PROP_FRAMEWORK_ID,
    PROP_NAME,
    PROP_PROCESS_ID,
    SnapshotCache,
    SnapshotOptions,
    build_snapshot,
    collect_nodes,
)

WINDOW_KEY = (111, "Qt5QWindowIcon", "KK官方对战平台")


class FakeElement:
    def __init__(self, eid, name=None, auto_id=None, ctype=None, cls=None, pid=111, children=None):
        self.eid = eid
        self.name = name
        self.auto_id = auto_id
        self.ctype = ctype
        self.cls = cls
        self.pid = pid
        self.children = list(children or [])

    def __repr__(self):
        return f"FakeElement({self.eid})"


class FakeSource:
    """按协议实现的假 UIA 元素源。"""

    def __init__(self, elements: dict, root_id: str):
        self.elements = elements
        self.root_id = root_id
        self.fail_children: set[str] = set()

    def is_available(self):
        return True

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
            PROP_FRAMEWORK_ID: "Fake",
            PROP_PROCESS_ID: el.pid,
        }.get(prop_id)

    def children(self, element):
        el = self.elements.get(element)
        if el is None or element in self.fail_children:
            return []
        return list(el.children)

    def get_pattern(self, element, pattern_id):
        return None

    def invoke(self, pattern):
        pass

    def set_value(self, pattern, text):
        pass

    def toggle(self, pattern):
        pass

    def value(self, pattern):
        return ""

    def toggle_state(self, pattern):
        return -1

    def close(self):
        pass


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


class SnapshotBuildTests(unittest.TestCase):
    def setUp(self):
        # window -> [pane] -> [button a, edit b]
        self.elements = {
            "win": FakeElement("win", name="KK窗口", ctype=50032),
            "pane": FakeElement("pane", name="", ctype=50033, children=["btn_a", "edit_b"]),
            "btn_a": FakeElement("btn_a", name="创建房间", auto_id="a", ctype=50000, cls="Button"),
            "edit_b": FakeElement("edit_b", name="", auto_id="b", ctype=50004, cls="Edit"),
        }
        self.elements["win"].children = ["pane"]
        self.source = FakeSource(self.elements, "win")

    def test_build_snapshot_structure(self):
        snap = build_snapshot(self.source, 12345, window_key=WINDOW_KEY)
        self.assertIsNotNone(snap.root)
        self.assertEqual(snap.root.name, "KK窗口")
        self.assertEqual(snap.root.control_type, 50032)
        self.assertEqual(snap.node_count, 4)
        self.assertFalse(snap.truncated)
        self.assertEqual(snap.window_key, WINDOW_KEY)
        names = [n.name for n in collect_nodes(snap)]
        self.assertEqual(names, ["", "创建房间", ""])

    def test_node_budget_truncation(self):
        snap = build_snapshot(
            self.source, 12345, options=SnapshotOptions(max_nodes=2, max_depth=8)
        )
        self.assertTrue(snap.truncated)
        self.assertLessEqual(snap.node_count, 2)

    def test_depth_cap(self):
        chain = {}
        prev = None
        for i in range(10):
            eid = f"n{i}"
            chain[eid] = FakeElement(eid, name=f"n{i}", ctype=50033, children=[prev] if prev else [])
            prev = eid
        source = FakeSource(chain, "n9")
        snap = build_snapshot(source, 1, options=SnapshotOptions(max_depth=3))
        # 深度上限：最多 root(0) + 3 层
        self.assertLessEqual(max(n.depth for n in collect_nodes(snap)), 3)

    def test_cycle_guard(self):
        # 真环：win -> a -> b -> a（a 作为自身后代）
        elements = {
            "win": FakeElement("win", name="w", ctype=50032, children=["a"]),
            "a": FakeElement("a", name="a", ctype=50033, children=["b"]),
            "b": FakeElement("b", name="b", ctype=50033, children=["a"]),
        }
        source = FakeSource(elements, "win")
        snap = build_snapshot(source, 1)
        self.assertIsNotNone(snap.root)
        # 环不会无限递归；a 在路径上只展开一次
        self.assertEqual(snap.node_count, 3)
        self.assertEqual([n.name for n in collect_nodes(snap)], ["a", "b"])

    def test_children_failure_is_leaf(self):
        self.source.fail_children.add("pane")
        snap = build_snapshot(self.source, 12345)
        self.assertEqual(snap.node_count, 2)  # win + pane（pane 的子级缺失）

    def test_identical_sibling_controls_are_kept(self):
        # 建房弹窗两个同属性 Edit（name='' autoId='' class='Edit'）必须都保留，
        # 否则 room_name/room_password 的 index 0/1 语义失效。
        self.elements = {
            "win": FakeElement("win", name="建房弹窗", ctype=50032, children=["edit0", "edit1"]),
            "edit0": FakeElement("edit0", name="", ctype=50004, cls="Edit"),
            "edit1": FakeElement("edit1", name="", ctype=50004, cls="Edit"),
        }
        source = FakeSource(self.elements, "win")
        snap = build_snapshot(source, 1)
        self.assertEqual(snap.node_count, 3)
        nodes = collect_nodes(snap)
        self.assertEqual(len(nodes), 2)
        self.assertNotEqual(nodes[0].handle, nodes[1].handle)

    def test_no_window_returns_empty(self):
        snap = build_snapshot(self.source, None)
        self.assertIsNone(snap.root)
        self.assertEqual(snap.node_count, 0)

    def test_element_from_handle_failure(self):
        source = FakeSource({}, "missing")
        snap = build_snapshot(source, 1)
        self.assertIsNone(snap.root)


class SnapshotCacheTests(unittest.TestCase):
    def setUp(self):
        self.elements = {
            "win": FakeElement("win", name="KK窗口", ctype=50032, children=["btn"]),
            "btn": FakeElement("btn", name="创建房间", ctype=50000),
        }
        self.source = FakeSource(self.elements, "win")
        self.clock = FakeClock()

    def test_cache_ttl_invalidation(self):
        cache = SnapshotCache(max_age_s=5.0, now=self.clock)
        snap1 = cache.get(self.source, 1, window_key=WINDOW_KEY)
        self.clock.advance(3)
        snap2 = cache.get(self.source, 1, window_key=WINDOW_KEY)
        self.assertIs(snap1, snap2)  # 未过期复用
        self.clock.advance(3)
        snap3 = cache.get(self.source, 1, window_key=WINDOW_KEY)
        self.assertIsNot(snap1, snap3)  # 过期重建

    def test_cache_window_key_change(self):
        cache = SnapshotCache(max_age_s=60, now=self.clock)
        snap1 = cache.get(self.source, 1, window_key=WINDOW_KEY)
        other = (222, "Chrome_WidgetWin_1", "英雄三国KK")
        snap2 = cache.get(self.source, 1, window_key=other)
        self.assertIsNot(snap1, snap2)
        self.assertTrue(snap2.matches_window(other))

    def test_cache_invalidate(self):
        cache = SnapshotCache(max_age_s=60, now=self.clock)
        snap1 = cache.get(self.source, 1, window_key=WINDOW_KEY)
        cache.invalidate()
        snap2 = cache.get(self.source, 1, window_key=WINDOW_KEY)
        self.assertIsNot(snap1, snap2)

    def test_cache_force_rebuild(self):
        cache = SnapshotCache(max_age_s=60, now=self.clock)
        snap1 = cache.get(self.source, 1, window_key=WINDOW_KEY)
        snap2 = cache.get(self.source, 1, window_key=WINDOW_KEY, force=True)
        self.assertIsNot(snap1, snap2)


if __name__ == "__main__":
    unittest.main()
