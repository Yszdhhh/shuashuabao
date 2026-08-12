"""让 tests/ 下每个文件都能独立运行。

此前只有部分测试文件自己 `sys.path.insert(ROOT/"src")`，其余（如
tests/test_choice_policy.py）依赖同一次 pytest 会话里字母序更靠前的文件先插入
路径。整目录跑没问题，但单独跑某个文件会 ModuleNotFoundError: gamescript，
调试单个用例时很容易被误判成代码坏了。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "src", ROOT):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)
