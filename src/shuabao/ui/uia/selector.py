"""控件选择器匹配引擎（纯函数，可 mock 单测）。"""

from __future__ import annotations

from .model import UiaNode, UiaSelector


def find_matching_nodes(
    nodes: list[UiaNode],
    selector: UiaSelector,
) -> list[UiaNode]:
    """在节点列表中按选择器过滤（直接子级语义由调用方决定）。

    返回全部命中（保留树序），由 resolve_node 负责 index 语义。
    """
    compiled = selector.compile()
    return [n for n in nodes if compiled.matches(n)]


def resolve_node(nodes: list[UiaNode], selector: UiaSelector) -> UiaNode | None:
    """解析选择器到具体节点：index=None 取第一个，否则取第 n 个。

    命中不足时返回 None —— 调用方（adapter）据此 Fail-Closed，
    绝不在“找不到控件”时点击坐标。
    """
    hits = find_matching_nodes(nodes, selector)
    if not hits:
        return None
    idx = selector.index if selector.index is not None else 0
    if idx < 0 or idx >= len(hits):
        return None
    return hits[idx]


def describe_node(node: UiaNode) -> str:
    """节点属性摘要，用于 trace 的 selector_detail。"""
    parts = []
    if node.name is not None:
        parts.append(f"name={node.name!r}")
    if node.automation_id is not None:
        parts.append(f"autoId={node.automation_id!r}")
    if node.control_type is not None:
        parts.append(f"type={node.control_type}")
    if node.class_name is not None:
        parts.append(f"class={node.class_name!r}")
    if node.rect is not None:
        parts.append(f"rect={node.rect}")
    return " ".join(parts) or "<empty>"
