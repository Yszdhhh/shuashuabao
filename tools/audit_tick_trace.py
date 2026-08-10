#!/usr/bin/env python3
"""N2 验收：无法解释的 tick >1s = 0（可判定白名单）。

读 Mediator.set_trace() 输出的 JSONL tick trace，对 elapsed_ms > 1000 的 tick
按白名单 reason 分类（Codex N2 方案 §'无法解释 tick>1s=0'）：

1. capture_wait        : 本 tick 捕获耗时 >= 800ms
2. input_executor_wait : 本 tick 成功执行实际输入且 action 耗时 >= 800ms
3. incident_write      : 本 tick 触发 incident 归档
4. debug_trace_io      : 仅显式 debug trace mode（生产默认关闭）
5. external_pause      : 系统睡眠/调试器暂停（monotonic gap 标记）

其余（matcher、HSV、OCR、排序、缓存 miss、普通 JSON/日志、全窗枚举）一律
unexplained。退出码：0 = 无 >1s tick 或全部白名单；1 = 存在 unexplained。

用法:
    .venv\\Scripts\\python.exe tools/audit_tick_trace.py trace.jsonl
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

WHITELIST = {"capture_wait", "input_executor_wait", "incident_write", "debug_trace_io", "external_pause"}


def classify_tick(row: dict) -> str:
    """返回 'ok'（<=1000ms）/ 'unexplained' / 白名单 reason 名。"""
    elapsed = float(row.get("elapsed_ms") or 0.0)
    if elapsed <= 1000.0:
        return "ok"
    reason = row.get("reason")
    if isinstance(reason, str) and reason in WHITELIST:
        return reason
    return "unexplained"


def audit(path: Path) -> dict:
    slow: list[dict] = []
    unexplained: list[dict] = []
    per_reason: dict[str, int] = {}
    max_elapsed = 0.0
    total = 0
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            total += 1
            elapsed = float(row.get("elapsed_ms") or 0.0)
            max_elapsed = max(max_elapsed, elapsed)
            if elapsed <= 1000.0:
                continue
            slow.append(row)
            verdict = classify_tick(row)
            if verdict == "unexplained":
                unexplained.append(row)
            else:
                per_reason[verdict] = per_reason.get(verdict, 0) + 1
    return {
        "total_ticks": total,
        "max_elapsed_ms": round(max_elapsed, 1),
        "ticks_over_1s": len(slow),
        "unexplained": len(unexplained),
        "per_reason": per_reason,
        "unexplained_samples": [
            {"tick": r.get("tick"), "elapsed_ms": r.get("elapsed_ms"), "reason": r.get("reason")}
            for r in unexplained[:5]
        ],
    }


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print(__doc__)
        return 2
    result = audit(Path(args[0]))
    print(json.dumps(result, ensure_ascii=False, indent=1))
    if result["unexplained"] > 0:
        print("[ERROR] unexplained tick > 1s found (must be 0)")
        return 1
    print("[OK] no unexplained tick > 1s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
