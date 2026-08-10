"""N0 基准工具 smoke test：最小成本验证 benchmark_hot_path.py 可运行且输出可解析。

只跑 1 个轻量 fixture（victory，~0.5s/迭代）× 3 模式 × 1 迭代，断言：
- 工具返回码 0；
- N0_BENCHMARK.json 写入且 schema 完整；
- fixture 结果含 P50/P95、匹配次数、搜索像素、context_verified。
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

TOOL = ROOT / "tools" / "benchmark_hot_path.py"


class BenchmarkSmokeTest(unittest.TestCase):
    def test_smoke_run_single_fixture(self):
        # 用临时 out-dir，避免覆写官方 docs/baselines/N0_BENCHMARK.json
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            proc = subprocess.run(
                [
                    sys.executable,
                    str(TOOL),
                    "--fixture",
                    "victory",
                    "--iterations",
                    "1",
                    "--no-live-capture",
                    "--out-dir",
                    str(out_dir),
                ],
                capture_output=True,
                text=True,
                timeout=600,
            )
            self.assertEqual(proc.returncode, 0, msg=f"benchmark exit != 0: {proc.stderr[-800:]}")
            out_json = out_dir / "N0_BENCHMARK.json"
            self.assertTrue(out_json.is_file(), "N0_BENCHMARK.json not written")
            report = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertEqual(report["schema"], "N0-benchmark-v1")
        self.assertTrue(report["git"]["repo_head"], "repo_head missing")
        self.assertTrue(report["template_sha256"], "template sha missing")
        entries = [r for r in report["fixtures"] if r["fixture_id"] == "victory"]
        self.assertEqual(len(entries), 3, "expected 3 modes for victory fixture")
        for r in entries:
            self.assertGreater(r["total_ms"]["p50_ms"], 0.0)
            self.assertGreater(r["match_calls"]["p50_ms"], 0)
            self.assertGreater(r["match_pixels"]["p50_ms"], 0)
            self.assertEqual(r["contexts"], ["MAIN_LINE"])
            self.assertTrue(r["context_verified"])


if __name__ == "__main__":
    unittest.main()
