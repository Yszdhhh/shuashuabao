#!/usr/bin/env python3
"""Produce, but NEVER apply, a blob-locked patch for the reviewed legacy seams.

Default is read-only inspection. --write-patch writes a new patch artifact only.
Apply in a NEW integration worktree after reviewing `git apply --check`.
It does not wire the scheduler or authorize LIVE. See the cloud handoff.
"""
from __future__ import annotations

import argparse
import ast
import difflib
import hashlib
from pathlib import Path
import sys

BASE_SHA = "6d55cecb50ab38675db420ccc950fd30c232ef08"
EXPECTED_BLOBS = {
    "src/shuabao/mediator.py": "9c13603c50065776b2b6dfb1813209e92ecf29f2",
    "src/shuabao/runtime_mediator.py": "1fb448739ef213858c188b0e700b9ef29da7ce3e",
    "src/shuabao/choice_policy.py": "3a5c7b4c7b2b4ea7f896e393b1781ca8e1275e93",
    "tools/live_scenario_capture.py": "6da3d768af26f2ce9e41dd8c565c1f13d4ca7de6",
}


def blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def normalize_source(data: bytes) -> bytes:
    # Git stores these text files as LF; Windows may check them out as CRLF.
    return data.replace(b"\r\n", b"\n")


def replace_method(source: str, method: str, replacement: str) -> str:
    tree = ast.parse(source)
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Mediator"]
    if len(classes) != 1:
        raise ValueError("expected one Mediator class")
    nodes = [n for n in classes[0].body if isinstance(n, ast.FunctionDef) and n.name == method]
    if len(nodes) != 1 or nodes[0].decorator_list:
        raise ValueError(f"ambiguous or decorated method: {method}")
    node = nodes[0]
    lines = source.splitlines(keepends=True)
    lines[node.lineno - 1:node.end_lineno] = [replacement.rstrip() + "\n"]
    output = "".join(lines)
    ast.parse(output)
    return output


def replace_once(source: str, before: str, after: str) -> str:
    if source.count(before) != 1:
        raise ValueError("legacy seam missing or ambiguous; do not guess")
    return source.replace(before, after, 1)


def transform(path: str, source: str) -> str:
    if path == "src/shuabao/mediator.py":
        for name, signature in (
            ("_can_consume_inventory_swallow_pill", "self, frame: Frame"),
            ("_has_swallowable_pirate_card", "self, bounty_name: str, frame: Frame | None = None"),
            ("_can_consume_god_swallow_pill", "self, frame: Frame | None = None"),
        ):
            source = replace_method(source, name,
                f"    def {name}({signature}) -> bool:\n"
                '        """Safety stop: no current-instance/target-set proof is wired yet."""\n'
                "        # Preference and occupancy never authorize destructive consumption.\n"
                "        # Enable only through runtime_core.contracts + verified LIVE adapters.\n"
                "        return False\n")
        # Preserve the rest of the legacy mutation logic; invalid geometry is NOT success.
        tree = ast.parse(source)
        methods = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                   and n.name == "_panel_mutation_confirmed"]
        if len(methods) != 1:
            raise ValueError("mutation verifier missing or ambiguous")
        node = methods[0]
        condition = "roi is None or roi.shape != baseline.shape"
        candidates = [n for n in ast.walk(node) if isinstance(n, ast.If)
                      and ast.unparse(n.test) == condition]
        if len(candidates) != 1 or len(candidates[0].body) != 1:
            raise ValueError("mutation shape guard drifted")
        ret = candidates[0].body[0]
        if not isinstance(ret, ast.Return) or not isinstance(ret.value, ast.Constant) or ret.value.value is not True:
            raise ValueError("unexpected mutation shape behavior")
        lines = source.splitlines(keepends=True)
        lines[ret.lineno - 1:ret.end_lineno] = [
            " " * ret.col_offset + "return False  # Missing/resized ROI cannot confirm a game mutation.\n"]
        source = "".join(lines)
    elif path == "src/shuabao/runtime_mediator.py":
        source = replace_method(source, "_maybe_use_inventory_item",
            "    def _maybe_use_inventory_item(self, frame):\n"
            '        """One shared implementation for desktop and GT; no factory rebinding."""\n'
            "        return super()._maybe_use_inventory_item(frame)\n")
        source = replace_method(source, "_maybe_black_merchant",
            "    def _maybe_black_merchant(self, frame, allow_reroll: bool = True):\n"
            "        return super()._maybe_black_merchant(frame, allow_reroll=allow_reroll)\n")
    elif path == "tools/live_scenario_capture.py":
        source = replace_once(source,
            "        RuntimeMediator._maybe_use_inventory_item = Mediator._maybe_use_inventory_item\n", "")
    elif path == "src/shuabao/choice_policy.py":
        source = replace_once(source,
            "                test_open_mode = float(settings.bond_base_completion_ratio or 0.0) <= 0.0\n", "")
        source = replace_once(source,
            "                            or (test_open_mode and matches_bond_preset(slot.name, settings.bond_advanced_presets))\n", "")
    else:
        raise ValueError(f"not an approved seam: {path}")
    ast.parse(source)
    return source


def prepare(root: Path) -> str:
    """Validate EVERY original before producing any output; leave all files alone."""
    root = root.resolve()
    originals: dict[str, str] = {}
    for path, expected in EXPECTED_BLOBS.items():
        target = (root / path).resolve()
        target.relative_to(root)
        raw = normalize_source(target.read_bytes())
        if blob_sha(raw) != expected:
            raise ValueError(f"SOURCE_DRIFT: {path}; retain local work and request rebase")
        originals[path] = raw.decode("utf-8")
    patches = []
    for path, source in originals.items():
        after = transform(path, source)
        patches.extend(difflib.unified_diff(source.splitlines(keepends=True), after.splitlines(keepends=True),
                                           fromfile=f"a/{path}", tofile=f"b/{path}"))
    return "".join(patches)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--write-patch", type=Path)
    args = parser.parse_args()
    try:
        patch = prepare(args.repo_root)
        if args.write_patch:
            # Never silently replace an existing artifact, including local scratch files.
            with args.write_patch.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(patch)
        print(f"SEAMS_VERIFIED base={BASE_SHA} paths={len(EXPECTED_BLOBS)}")
        print("SCHEDULER_NOT_WIRED / FULL_GATE_NOT_RUN / LIVE_NOT_AUTHORIZED")
        return 0
    except (OSError, ValueError, SyntaxError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
