#!/usr/bin/env python3
"""L0 UIA 实机工具：导出 KK 平台 UIA 树 + 控件映射 dry-run 探针。

用法（需要用户先打开 KK 对战平台并停在想导出的页面）：
    python tools/dump_uia_tree.py dump --page map|room|dialog|stage
    python tools/dump_uia_tree.py probe
    python tools/dump_uia_tree.py loop --count 20 --out agent_out/lobby_dryrun.json

安全：默认只读。任何输出都不包含密码明文（读回值脱敏）。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from shuabao.ui.uia.adapter import AdapterOptions, LobbyUiaAdapter
from shuabao.ui.uia.backend import CtypesUiaBackend
from shuabao.ui.uia.mappings import KK_LOBBY_MAPPINGS
from shuabao.ui.uia.selector import describe_node
from shuabao.ui.uia.source import collect_nodes


def _mask(text: str | None) -> str | None:
    """trace 中的密码脱敏。"""
    if text is None:
        return None
    if len(text) <= 4:
        return "*" * len(text)
    return text[:2] + "*" * (len(text) - 4) + text[-2:]


def _find_kk_windows() -> list[dict]:
    from shuabao.vision.capture import find_window_targets

    targets = find_window_targets("KK", role="l0")
    return [
        {
            "hwnd": t.hwnd,
            "title": t.title,
            "class_name": t.class_name,
            "pid": t.pid,
            "size": f"{t.width}x{t.height}",
            "role": t.role,
        }
        for t in targets
    ]


def cmd_dump(args: argparse.Namespace) -> int:
    backend = CtypesUiaBackend()
    if not backend.is_available():
        print("UIA backend unavailable:", backend._error)
        return 2
    adapter = LobbyUiaAdapter(source=backend, mappings=KK_LOBBY_MAPPINGS)
    windows = _find_kk_windows()
    print(f"KK 候选窗口 {len(windows)} 个：")
    for w in windows:
        print(f"  hwnd={w['hwnd']:#x} title={w['title']!r} class={w['class_name']!r} pid={w['pid']} {w['size']}")
    if not windows:
        print("未找到 KK 窗口，请先打开 KK 对战平台。")
        return 1
    hwnd = windows[0]["hwnd"]
    tree = adapter.dump_tree(hwnd)
    out = Path(args.out) if args.out else ROOT / "agent_out" / "lobby_uia_tree.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(tree, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"树已导出：{out}（节点数 {tree.get('node_count')}，截断={tree.get('truncated')}）")

    def walk(node, prefix=""):
        name = _mask(node.get("name"))
        line = (
            f"{prefix}[type={node.get('control_type')} name={name!r} "
            f"autoId={node.get('automation_id')!r} class={node.get('class_name')!r} "
            f"rect={node.get('rect')}]"
        )
        print(line)
        for child in node.get("children", []):
            walk(child, prefix + "  ")

    if tree.get("root"):
        walk(tree["root"])
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    backend = CtypesUiaBackend()
    if not backend.is_available():
        print("UIA backend unavailable:", backend._error)
        return 2
    adapter = LobbyUiaAdapter(source=backend, mappings=KK_LOBBY_MAPPINGS)
    print("控件映射 dry-run 探针（只读，无任何输入动作）：")
    all_ok = True
    for key in KK_LOBBY_MAPPINGS:
        result = adapter.probe_mapping(key)
        status = "OK " if result.get("resolved") and result.get("pattern_available") else "FAIL"
        all_ok = all_ok and status == "OK "
        print(f"  [{status}] {key}: {result.get('selector', result.get('error'))}")
    print("全部就绪" if all_ok else "存在未命中控件（实机回填 selector 候选值）")
    return 0 if all_ok else 1


def cmd_loop(args: argparse.Namespace) -> int:
    """N 次只建房不进局 dry-run：每个 mapping 解析 + pattern 可用性统计。"""
    backend = CtypesUiaBackend()
    if not backend.is_available():
        print("UIA backend unavailable:", backend._error)
        return 2
    adapter = LobbyUiaAdapter(
        source=backend,
        mappings=KK_LOBBY_MAPPINGS,
        options=AdapterOptions(dry_run=True, snapshot_max_age_s=2.0),
    )
    count = args.count
    report: dict = {"dry_run": True, "iterations": [], "summary": {}}
    key_stats: dict[str, dict] = {}
    for key in KK_LOBBY_MAPPINGS:
        key_stats[key] = {"ok": 0, "fail": 0, "errors": []}
    for i in range(count):
        iteration: dict = {"index": i, "controls": {}}
        for key in KK_LOBBY_MAPPINGS:
            try:
                result = adapter.probe_mapping(key)
                ok = bool(result.get("resolved") and result.get("pattern_available"))
                key_stats[key]["ok" if ok else "fail"] += 1
                iteration["controls"][key] = {
                    "ok": ok,
                    "selector": result.get("selector"),
                    "readback_now": result.get("readback_now"),
                }
                if not ok:
                    key_stats[key]["errors"].append(result.get("error"))
            except Exception as exc:  # pragma: no cover - 环境异常
                key_stats[key]["fail"] += 1
                key_stats[key]["errors"].append(str(exc))
                iteration["controls"][key] = {"ok": False, "error": str(exc)}
        report["iterations"].append(iteration)
        time.sleep(0.3)
    report["summary"] = {
        key: {"ok": s["ok"], "fail": s["fail"], "rate": f"{s['ok'] / count:.0%}"}
        for key, s in key_stats.items()
    }
    all_pass = all(s["fail"] == 0 for s in key_stats.values())
    out = Path(args.out) if args.out else ROOT / "agent_out" / "lobby_dryrun_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{count} 次 dry-run 报告：{out}")
    for key, s in report["summary"].items():
        print(f"  {key}: 通过 {s['ok']}/{count} ({s['rate']})")
    print("20 次 dry-run 门禁：", "PASS" if all_pass and count >= 20 else "未满足（需 20 次且全过）")
    return 0 if all_pass else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p_dump = sub.add_parser("dump", help="导出当前前台 KK 窗口的 UIA 树")
    p_dump.add_argument("--out", default="")
    p_probe = sub.add_parser("probe", help="控件映射只读探针")
    p_loop = sub.add_parser("loop", help="N 次 dry-run 门禁")
    p_loop.add_argument("--count", type=int, default=20)
    p_loop.add_argument("--out", default="")
    args = parser.parse_args()
    if args.command == "dump":
        return cmd_dump(args)
    if args.command == "probe":
        return cmd_probe(args)
    return cmd_loop(args)


if __name__ == "__main__":
    raise SystemExit(main())
