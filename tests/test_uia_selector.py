"""UiaSelector 匹配引擎单测（纯逻辑，无 COM）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from gamescript.ui.uia.model import UiaNode, UiaSelector
from gamescript.ui.uia.selector import describe_node, find_matching_nodes, resolve_node


def _node(
    name: str | None = None,
    auto_id: str | None = None,
    ctype: int | None = None,
    cls: str | None = None,
) -> UiaNode:
    return UiaNode(name=name, automation_id=auto_id, control_type=ctype, class_name=cls)


class SelectorMatchTests(unittest.TestCase):
    def test_name_exact_match(self):
        nodes = [_node(name="创建房间"), _node(name="开始游戏")]
        self.assertEqual(len(find_matching_nodes(nodes, UiaSelector(name="创建房间"))), 1)

    def test_name_regex_match(self):
        nodes = [_node(name="1-15"), _node(name="1-16"), _node(name="2-3")]
        hits = find_matching_nodes(nodes, UiaSelector(name_re=r"^1-(1[0-5]|[1-9])$"))
        self.assertEqual([n.name for n in hits], ["1-15"])  # 1-16 必须被拒

    def test_all_attributes_are_and(self):
        nodes = [
            _node(name="创建房间", auto_id="btnCreate", ctype=50000, cls="Button"),
            _node(name="创建房间", auto_id="btnCreate", ctype=50004, cls="Edit"),
        ]
        sel = UiaSelector(name="创建房间", automation_id="btnCreate", control_type=50000, class_name="Button")
        self.assertEqual(len(find_matching_nodes(nodes, sel)), 1)
        self.assertEqual(nodes[0].control_type, find_matching_nodes(nodes, sel)[0].control_type)

    def test_none_fields_do_not_participate(self):
        nodes = [_node(name="开始游戏", auto_id=None, ctype=None, cls=None)]
        self.assertEqual(len(find_matching_nodes(nodes, UiaSelector(name="开始游戏"))), 1)

    def test_index_semantics(self):
        nodes = [_node(name="确定"), _node(name="确定"), _node(name="取消")]
        self.assertIs(resolve_node(nodes, UiaSelector(name="确定")), nodes[0])
        self.assertIs(resolve_node(nodes, UiaSelector(name="确定", index=1)), nodes[1])
        self.assertIsNone(resolve_node(nodes, UiaSelector(name="确定", index=2)))
        self.assertIsNone(resolve_node(nodes, UiaSelector(name="不存在")))

    def test_control_type_accepts_enum(self):
        from gamescript.ui.uia.model import ControlType

        nodes = [_node(name="x", ctype=50000)]
        self.assertEqual(len(find_matching_nodes(nodes, UiaSelector(control_type=ControlType.BUTTON))), 1)

    def test_selector_validation(self):
        with self.assertRaises(ValueError):
            UiaSelector(name="a", name_re="a")
        with self.assertRaises(ValueError):
            UiaSelector(scope="bogus")

    def test_describe_node_renders_attributes(self):
        text = describe_node(_node(name="创建房间", auto_id="a1", ctype=50000, cls="Button"))
        self.assertIn("name='创建房间'", text)
        self.assertIn("autoId='a1'", text)
        self.assertIn("type=50000", text)


if __name__ == "__main__":
    unittest.main()
