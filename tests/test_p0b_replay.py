import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from run_replay import run_replay_fixture
from gamescript.mediator import Mediator
from gamescript.settings import Settings


class P0BReplayTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings()
        self.med = Mediator(self.settings, ROOT)
        self.manifest_path = ROOT / "fixtures" / "manifest.json"
        self.assertTrue(self.manifest_path.is_file(), "manifest.json must exist")
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            self.manifest_data = json.load(f)

    def test_replay_fixtures_and_negative_samples(self):
        fixtures = self.manifest_data.get("fixtures", [])
        self.assertGreater(len(fixtures), 0)

        for fixture in fixtures:
            res = run_replay_fixture(fixture, self.med, ROOT)
            fid = fixture["fixture_id"]
            if fixture.get("missing_resource"):
                self.assertEqual(res.status, "MISSING_RESOURCE", f"{fid} should be MISSING_RESOURCE")
            else:
                self.assertEqual(res.status, "PASS", f"Fixture {fid} failed: {res.notes}")

            # Every negative sample MUST have forbidden_click_count == 0
            if fixture.get("is_negative"):
                self.assertEqual(
                    res.forbidden_click_count, 0,
                    f"Negative sample {fid} had forbidden_click_count = {res.forbidden_click_count}"
                )


if __name__ == "__main__":
    unittest.main()
