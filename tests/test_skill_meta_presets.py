"""config/skill_meta.json 官方流派预设契约。"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
META_PATH = ROOT / "config" / "skill_meta.json"
LABELS_PATH = ROOT / "config" / "skill_labels.json"


class SkillMetaPresetsContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.meta = json.loads(META_PATH.read_text(encoding="utf-8"))
        cls.labels = json.loads(LABELS_PATH.read_text(encoding="utf-8"))
        cls.codes = {
            k: v for k, v in cls.labels.items() if not str(k).startswith("_")
        }

    def test_presets_non_empty(self):
        presets = self.meta.get("presets") or []
        self.assertGreaterEqual(len(presets), 3)

    def test_preset_codes_in_labels(self):
        for preset in self.meta["presets"]:
            with self.subTest(name=preset.get("name")):
                self.assertTrue(preset.get("name"))
                self.assertTrue(preset.get("hint"))
                codes = preset.get("codes") or []
                self.assertTrue(codes, "codes must be non-empty")
                for code in codes:
                    self.assertIn(code, self.codes, f"unknown skill code {code}")

    def test_preset_names_unique(self):
        names = [p["name"] for p in self.meta["presets"]]
        self.assertEqual(len(names), len(set(names)))

    def test_arcane_default_codes(self):
        arcane = next(p for p in self.meta["presets"] if p["name"] == "奥术开荒")
        self.assertEqual(arcane["codes"], ["asj", "asjg", "assx", "jq"])


if __name__ == "__main__":
    unittest.main()
