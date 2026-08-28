import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from shuabao.mediator import Mediator
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchMarginResult, MatchResult
from run_replay import main as replay_main, run_replay_fixture


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
                if fixture.get("required"):
                    self.assertTrue(res.required, f"Required fixture {fid} must be marked required")
            else:
                self.assertEqual(res.status, "PASS", f"Fixture {fid} failed: {res.notes}")

            # Every negative sample MUST have forbidden_click_count == 0 and status PASS
            if fixture.get("is_negative"):
                self.assertEqual(
                    res.forbidden_click_count, 0,
                    f"Negative sample {fid} had forbidden_click_count = {res.forbidden_click_count}"
                )
                self.assertEqual(res.status, "PASS", f"Negative sample {fid} failed: {res.notes}")

    def test_required_missing_fixture_fails_gatekeeper(self):
        # Run main() on manifest with required missing resources -> exit code 1
        exit_code = replay_main()
        self.assertEqual(exit_code, 1, "replay main() must return non-zero exit code when required resources are missing")

    def test_low_margin_rejects_candidate_action(self):
        # Test positive fixture with simulated low score margin
        sample_fixture = {
            "fixture_id": "low_margin_test",
            "file_path": "docs/runtime_sample/live_l0_0_857518.png",
            "page": "PLATFORM_MAP",
            "expected_state": "PLATFORM_MAP",
            "expected_action": "CreateRoom-open",
            "is_negative": False,
            "required": True,
            "margin_threshold": 0.30,
        }

        # Mock match_any_with_margin to return low margin (0.02 < threshold 0.30)
        low_margin_res = MatchMarginResult(
            best=MatchResult("lobby/create_room", 0.70, 600, 800, 200, 60, 600, 800),
            second_best=MatchResult("lobby/quick_join", 0.68, 600, 850, 200, 60, 600, 850),
            margin=0.02,
        )

        with patch("run_replay.match_any_with_margin", return_value=low_margin_res):
            res = run_replay_fixture(sample_fixture, self.med, ROOT)
            self.assertEqual(res.status, "FAIL")
            self.assertIsNone(res.click_point)


if __name__ == "__main__":
    unittest.main()
