"""资料/素材提交快速检查（AGENTS.md §1.1，Owner 2026-09-24）。

纯资料提交（截图、录像抽帧、研究文档）不改代码，不跑 pytest、不构建、不重钉身份锚点，
只跑本脚本：
  1. 改动路径全部在 docs/ 或 fixtures/live_captures/ 下（docs/baselines/ 是门禁快照，不算资料）；
  2. 单个文件 ≤ 10MB，合计 ≤ 200MB；
  3. 文本文件里没有私钥、卡密、机器码这类敏感值。

用法：
  python tools/check_material_commit.py                 # 检查暂存区（git add 之后、commit 之前）
  python tools/check_material_commit.py --range A..B    # 检查已提交的一段，如 origin/main..HEAD
退出码 0 = 可走快速通道；1 = 不满足，按普通代码提交走门禁。
只读 git 与文件，不改任何东西。
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_PREFIXES = ("docs/", "fixtures/live_captures/")
FORBIDDEN_PREFIXES = ("docs/baselines/",)
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 200 * 1024 * 1024
TEXT_SUFFIXES = {".md", ".txt", ".json", ".jsonl", ".csv", ".yaml", ".yml", ".log", ".html"}
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(卡密|激活码|机器码|license[_ ]?key)\s*[:：=]\s*[A-Za-z0-9]{8,}", re.IGNORECASE),
)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8"
    ).stdout


def _changed(range_spec: str | None) -> list[tuple[str, str]]:
    """(status, path) for each changed path; renames report the new path."""
    base = ["diff", "--name-status", "-z", "--no-renames"]
    out = _git(*base, range_spec) if range_spec else _git(*base, "--cached")
    parts = [p for p in out.split("\0") if p]
    return list(zip(parts[0::2], parts[1::2]))


def _blob_bytes(path: str, range_spec: str | None) -> bytes:
    if range_spec:
        head = re.split(r"\.\.\.?", range_spec)[-1] or "HEAD"
        return subprocess.run(["git", "show", f"{head}:{path}"], cwd=ROOT, check=True, capture_output=True).stdout
    return subprocess.run(["git", "show", f":{path}"], cwd=ROOT, check=True, capture_output=True).stdout


def check(range_spec: str | None) -> list[str]:
    problems: list[str] = []
    changes = _changed(range_spec)
    if not changes:
        return ["没有改动"]
    total = 0
    for status, path in changes:
        if not path.startswith(ALLOWED_PREFIXES) or path.startswith(FORBIDDEN_PREFIXES):
            problems.append(f"不是资料路径：{path}")
            continue
        if status.startswith("D"):
            continue
        data = _blob_bytes(path, range_spec)
        total += len(data)
        if len(data) > MAX_FILE_BYTES:
            problems.append(f"单个文件超过 10MB：{path}（{len(data) / 1048576:.1f}MB）")
        if Path(path).suffix.lower() in TEXT_SUFFIXES:
            text = data.decode("utf-8", errors="ignore")
            for pattern in SECRET_PATTERNS:
                if pattern.search(text):
                    problems.append(f"疑似敏感值（{pattern.pattern[:24]}…）：{path}")
    if total > MAX_TOTAL_BYTES:
        problems.append(f"合计超过 200MB：{total / 1048576:.1f}MB")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--range", dest="range_spec", help="git 范围，如 origin/main..HEAD；缺省检查暂存区")
    args = parser.parse_args()
    problems = check(args.range_spec)
    if problems:
        print("MATERIAL CHECK: FAIL（不能走快速通道，按代码提交走门禁）")
        for item in problems:
            print(f"  - {item}")
        return 1
    print("MATERIAL CHECK: PASS（纯资料提交，不需要跑 pytest / 门禁 / 构建）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
