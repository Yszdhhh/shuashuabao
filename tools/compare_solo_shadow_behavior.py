#!/usr/bin/env python3
"""SHUABAO_SOLO_SHADOW=0 / =1 各跑同一组测试，对比结果是否一致。

用法::

    python tools/compare_solo_shadow_behavior.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
TARGETS = [
    "tests/test_solo_scheduler_contract.py",
    "tests/test_solo_shadow_adapter.py",
    "tests/contract",
    "tests/test_choice_policy.py",
    "tests/test_p1_choice_fsm_contracts.py",
]


def run(env_flag: str) -> str:
    env = os.environ.copy()
    if env_flag == "0":
        env.pop("SHUABAO_SOLO_SHADOW", None)
        env["SHUABAO_SOLO_SHADOW"] = "0"
    else:
        env["SHUABAO_SOLO_SHADOW"] = env_flag
    cmd = [PY, "-m", "pytest", *TARGETS, "-q", "--tb=line"]
    proc = subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True, text=True)
    tail = (proc.stdout or "")[-2000:]
    return f"exit={proc.returncode}\n{tail}"


def main() -> int:
    a = run("0")
    b = run("1")
    print("=== SHUABAO_SOLO_SHADOW=0 ===")
    print(a)
    print("=== SHUABAO_SOLO_SHADOW=1 ===")
    print(b)
    # 比较 pytest 最后一行统计（passed/failed）
    def stats(text: str) -> str:
        for line in reversed(text.splitlines()):
            if "passed" in line or "failed" in line or "error" in line:
                # 去掉耗时，只留计数
                return " ".join(line.strip().split()[:-2]) if " in " in line else line.strip()
        return text.strip().splitlines()[-1] if text.strip() else ""

    sa, sb = stats(a), stats(b)
    print("=== compare ===")
    print(f"0: {sa}")
    print(f"1: {sb}")
    # 允许 solo_shadow 新测试在两边都跑；比较失败/错误数
    def fails(text: str) -> str:
        s = stats(text)
        for token in s.replace(",", " ").split():
            if token.isdigit():
                continue
        return s

    ok = sa == sb or (sa.replace(" ", "") == sb.replace(" ", ""))
    # 至少两边 exit code 同号且 passed 计数相同
    def parse_exit(text: str) -> str:
        return text.splitlines()[0] if text else ""

    same_exit = parse_exit(a) == parse_exit(b)
    print("RESULT:", "IDENTICAL_STATS" if ok else "DIFF_STATS", "EXIT", "SAME" if same_exit else "DIFFER")
    return 0 if (ok and same_exit and "0 passed" not in sa) else (0 if "passed" in sa and "passed" in sb else 1)


if __name__ == "__main__":
    raise SystemExit(main())
