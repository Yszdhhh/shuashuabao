from __future__ import annotations

from pathlib import Path

from tools.build_vision_corpus_coverage import build_coverage, scan_root


def test_scan_root_counts_only_supported_image_files(tmp_path: Path) -> None:
    (tmp_path / "a.png").write_bytes(b"png")
    (tmp_path / "b.JPG").write_bytes(b"jpg")
    (tmp_path / "notes.txt").write_bytes(b"not an image")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "c.webp").write_bytes(b"webp")

    result = scan_root("tmp", tmp_path, "TEST_ONLY")

    assert result["exists"] is True
    assert result["image_files"] == 3
    assert result["bytes"] == len(b"png") + len(b"jpg") + len(b"webp")


def test_coverage_matrix_keeps_non_choice_business_gaps_explicit() -> None:
    report = build_coverage(raw_roots=[])
    rows = {row["scene_id"]: row for row in report["matrix"]}

    assert report["scope"]["production_integration"] == "NOT_APPLIED"
    assert report["indexed_evaluation"]["vision_eval_samples"] == 155
    assert report["indexed_evaluation"]["ocr_treasure_description_calls"] == 12276
    assert report["indexed_evaluation"]["treasure_decision_replay_mismatches"] == 0
    assert rows["l0_hero_setup"]["compression_status"] == "RESEARCH_ONLY"
    assert rows["recovery_disconnect"]["compression_status"] == "MISSING"
    assert rows["recovery_disconnect"]["kpi"]["status"] == "BLOCKED"
    assert rows["l1_dragonball"]["hard_negative"]["units"] == 0
    assert rows["treasure_business_semantics"]["positive"]["units"] == 4


def test_coverage_generator_has_no_runtime_import_or_layer_hook() -> None:
    source = Path("tools/build_vision_corpus_coverage.py").read_text(encoding="utf-8")

    assert "from shuabao" not in source
    assert "import shuabao" not in source
    assert "src/shuabao" not in source.replace("\\", "/")
