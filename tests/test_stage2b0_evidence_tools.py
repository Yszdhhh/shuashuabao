"""Stage 2B0 evidence-tool tests; no OCR inference or external input required."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Stage2B0EvidenceToolTests(unittest.TestCase):
    def test_legacy_description_selector_is_exact(self):
        from tools.replay_treasure_desc_equivalence import _legacy_description

        self.assertTrue(_legacy_description({"panel_id": "treasure:abc:desc"}))
        self.assertFalse(_legacy_description({"panel_id": "treasure:abc:desc:3:0"}))
        self.assertFalse(_legacy_description({"panel_id": "skill:abc:desc"}))

    def test_paired_replay_changes_only_description(self):
        from tools.replay_treasure_desc_equivalence import _load_policy_settings, _replay_pair

        row = {
            "frame_fingerprint": "1600x900:test",
            "ocr_suggestion": {
                "kind": "treasure",
                "slots": [
                    {
                        "index": 0,
                        "name": "普攻伤害",
                        "confidence": 0.95,
                        "raw_text": "普攻伤害",
                        "rarity": "blue",
                        "description": "",
                    },
                    {
                        "index": 1,
                        "name": None,
                        "confidence": 0.0,
                        "raw_text": "",
                        "rarity": "green",
                        "description": "",
                    },
                ],
            },
            "panel": [{"name": "treasure_refresh_btn"}],
        }
        enabled, disabled = _replay_pair(row, _load_policy_settings())
        self.assertEqual(enabled, disabled)

    def test_replay_report_requires_targeted_count_and_retains_policy_semantics(self):
        from tools.replay_treasure_desc_equivalence import replay

        with tempfile.TemporaryDirectory(prefix="shuabao_stage2b0_ocr_") as temp:
            root = Path(temp)
            ocr_trace = root / "ocr_shadow.jsonl"
            ocr_trace.write_text(
                "\n".join(
                    json.dumps(
                        {
                            "panel_id": "treasure:abc:desc",
                            "status": "unavailable",
                        }
                        , ensure_ascii=False)
                    for _ in range(2)
                )
                + "\n",
                encoding="utf-8",
            )
            tick_dir = root / "20260829"
            tick_dir.mkdir()
            (tick_dir / "trace_test.jsonl").write_text(
                json.dumps(
                    {
                        "tick": 1,
                        "ocr_suggestion": {
                            "kind": "treasure",
                            "slots": [
                                {
                                    "index": 0,
                                    "name": "普攻伤害",
                                    "confidence": 0.95,
                                    "raw_text": "普攻伤害",
                                    "rarity": "blue",
                                    "description": "",
                                }
                            ],
                        },
                        "actions": [],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            report = replay(
                ocr_trace=ocr_trace,
                tick_root=root,
                output=root / "report.json",
                expected_legacy_calls=2,
            )

        self.assertEqual(report["status"], "COMPLETED")
        self.assertEqual(report["legacy_description_calls"]["calls"], 2)
        self.assertTrue(report["legacy_description_calls"]["all_unavailable"])
        self.assertTrue(report["legacy_description_calls"]["count_matches_expected"])
        self.assertEqual(report["decision_equivalence"]["status"], "PASS")
        self.assertEqual(report["decision_equivalence"]["mismatch_count"], 0)
        self.assertEqual(report["business_semantics"]["description_field"], "retained")
        self.assertEqual(report["business_semantics"]["negative_patterns"], "retained")
        self.assertFalse(report["business_semantics"]["runtime_call_change_applied"])


if __name__ == "__main__":
    unittest.main()
