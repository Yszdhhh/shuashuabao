from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.shell.runtime_status import progress_from_counts  # noqa: E402


class ShellProgressTests(unittest.TestCase):
    def test_cycle_num_zero_is_count_not_full_bar(self):
        prog = progress_from_counts(3, 0, running=True)
        self.assertEqual("count", prog.kind)
        self.assertEqual(3, prog.game_count)
        self.assertIn("已完成 3 局", prog.label)

    def test_cycle_num_positive_is_ratio(self):
        prog = progress_from_counts(2, 5, running=True)
        self.assertEqual("ratio", prog.kind)
        self.assertEqual("第 2 / 5 局", prog.label)

    def test_idle_empty_is_none(self):
        prog = progress_from_counts(0, 0, running=False)
        self.assertEqual("none", prog.kind)
        self.assertEqual("空闲", prog.label)


if __name__ == "__main__":
    unittest.main()
