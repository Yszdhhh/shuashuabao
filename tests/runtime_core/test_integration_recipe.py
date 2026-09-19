"""Synthetic seam tests; full production-file application must be done locally."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from prepare_runtime_core_integration import blob_sha, normalize_source, prepare, replace_method, transform


class RecipeTests(unittest.TestCase):
    def test_runtime_delegation_and_signature(self):
        original = '''class Mediator:
    def _maybe_use_inventory_item(self, frame):
        return "old"

    def _maybe_black_merchant(self, frame):
        return None
'''
        result = transform("src/shuabao/runtime_mediator.py", original)
        self.assertIn("allow_reroll=allow_reroll", result)
        self.assertIn("super()._maybe_use_inventory_item(frame)", result)
        self.assertNotIn('return "old"', result)

    def test_harness_rebinding_removed(self):
        source = "def f():\n    if True:\n        RuntimeMediator._maybe_use_inventory_item = Mediator._maybe_use_inventory_item\n        return RuntimeMediator()\n"
        result = transform("tools/live_scenario_capture.py", source)
        self.assertNotIn(" = Mediator.", result)

    def test_unknown_method_refused(self):
        with self.assertRaises(ValueError):
            replace_method("class Mediator:\n    pass\n", "absent", "")

    def test_drift_rejected_without_mutating_source(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = root / "src/shuabao/mediator.py"
            p.parent.mkdir(parents=True)
            p.write_text("local work\n")
            with self.assertRaises(ValueError):
                prepare(root)
            self.assertEqual(p.read_text(), "local work\n")

    def test_crlf_normalizes_to_git_blob(self):
        self.assertEqual(blob_sha(normalize_source(b"x\r\ny\r\n")), blob_sha(b"x\ny\n"))

    def test_ambiguous_rebinding_is_not_silently_patched(self):
        statement = "        RuntimeMediator._maybe_use_inventory_item = Mediator._maybe_use_inventory_item\n"
        with self.assertRaises(ValueError):
            transform("tools/live_scenario_capture.py", "def f():\n    if True:\n" + statement * 2)


if __name__ == "__main__":
    unittest.main()
