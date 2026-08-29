"""Stage 2A evidence-tool smoke tests; no OCR model inference is required."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Stage2AEvidenceToolTests(unittest.TestCase):
    def test_manifest_builder_recomputes_provenance_fields(self):
        from tools.build_vision_eval_manifest import build_manifest

        source = ROOT / "fixtures" / "ocr_choices" / "skill" / "rec1_ingame_boss_20260809" / "t_015s_技能面板_giveUp证据_slot0_name.png"
        with tempfile.TemporaryDirectory(prefix="shuabao_manifest_test_") as raw_dir:
            temp = Path(raw_dir)
            corpus = temp / "corpus"
            corpus.mkdir()
            shutil.copyfile(source, corpus / "slot.png")
            annotations = temp / "annotations.jsonl"
            annotations.write_text(
                json.dumps(
                    {
                        "sample_id": "test_slot",
                        "scene": "skill_choice",
                        "kind": "skill",
                        "label": "次级箭",
                        "truth_canonical": "次级箭",
                        "capture_session": "test_session",
                        "split": "BLIND_HOLDOUT",
                        "source_crop": "slot.png",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            meta, rows = build_manifest(
                annotations,
                corpus,
                generated_at="2026-08-29T00:00:00+00:00",
                source_manifest_path=annotations,
            )

        self.assertEqual(meta["schema_version"], 3)
        self.assertEqual(meta["counts"]["samples"], 1)
        self.assertEqual(rows[0]["source_crop"], "slot.png")
        self.assertRegex(rows[0]["sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(rows[0]["dhash"], r"^[0-9a-f]{16}$")
        self.assertRegex(rows[0]["phash"], r"^[0-9a-f]{16}$")
        self.assertRegex(rows[0]["duplicate_cluster_id"], r"^phash_dhash_cluster_\d{4}$")
        self.assertEqual(rows[0]["capture_group_id"], "capture_session:test_session")

    def test_current_manifest_has_session_and_cluster_boundaries(self):
        from tools.benchmark_vision_ocr import load_jsonl_manifest, resolve_corpus_root, validate_rows

        meta, rows = load_jsonl_manifest(ROOT / "docs" / "distillation" / "VISION_EVAL_MANIFEST.jsonl")
        stats = validate_rows(meta, rows, resolve_corpus_root(meta, rows, None))
        self.assertEqual(stats["samples"], 155)
        self.assertEqual(stats["sessions"], 7)
        self.assertEqual(stats["train_tune"], 44)
        self.assertEqual(stats["blind_holdout"], 111)
        self.assertEqual(stats["near_duplicate_clusters"], 4)

    def test_card_benchmark_operating_threshold_has_no_observed_false_fire(self):
        from tools.benchmark_card_templates import benchmark

        with tempfile.TemporaryDirectory(prefix="shuabao_card_test_") as raw_dir:
            report = benchmark(Path(raw_dir) / "cards.json")
        result = report["thresholds"]["operating_result"]
        self.assertEqual(result["positive_recall"]["hits"], 6)
        self.assertEqual(result["hard_negative_fp"]["hits"], 0)
        self.assertEqual(result["blank_fp"]["hits"], 0)
        self.assertEqual(result["idle_fp"]["hits"], 0)
        self.assertEqual(report["ocr_fallback_reference"]["status"], "REFERENCE_ONLY_NOT_COMPARABLE")

    def test_release_gate_asset_audit_passes(self):
        from tools.release_gate import stage_asset_leakage

        result = stage_asset_leakage()
        self.assertEqual(result.status, "PASS", result.detail)
        self.assertEqual(result.observed["files"], result.observed["allowlisted"])
        self.assertEqual(result.observed["hash_mismatch"], 0)


if __name__ == "__main__":
    unittest.main()
