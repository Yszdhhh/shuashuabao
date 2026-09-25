"""Offline scalar log-integrity tests; not live-game or action-parity proof."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "solo_shadow_summary_integrity_target",
    Path(__file__).resolve().parents[1] / "tools" / "summarize_solo_shadow.py",
)
assert _SPEC and _SPEC.loader
summary = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(summary)


def row(action="open_skill_panel", target="skill", *, seq=1, schema=2):
    return {
        "schema": schema, "seq": seq, "round_id": "round-1",
        "boundary": "plan_in_window", "snapshot": {},
        "decision": {
            "kind": "RECOMMEND",
            "chosen": {"action_id": action, "target": target},
            "alternatives": [], "review_required": [], "incomparable": [],
        },
        "actual": {"plan_target": target, "act": target},
    }


def write_log(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def only_round(report):
    return next(iter(report["rounds"].values()))


def test_plan_match_is_never_action_proof():
    report = summary.summarize([row()])
    assert report["evidence_scope"] == "PLAN_TARGET_ONLY"
    assert report["behavior_proof"] is False
    assert report["actual_action_evidence"] == "NOT_AVAILABLE"
    assert only_round(report)["recommend_vs_plan_target_agree"] == 1
    assert "NOT_BEHAVIOR_PROOF" in summary.render(report)


@pytest.mark.parametrize("action,target", [
    ("open_skill_panel", "kill"), ("merchant_buy_pill", "pill"),
    ("bond_draw", "on"),
])
def test_substring_is_not_a_plan_family_match(action, target):
    r = row(action, target)
    r["decision"]["chosen"]["target"] = {
        "open_skill_panel": "skill", "merchant_buy_pill": "merchant_buy_pill",
        "bond_draw": "bond",
    }[action]
    result = only_round(summary.summarize([r]))
    assert result["recommend_vs_actual_agree"] == 0
    assert result["recommend_plan_uncomparable"] == 1


@pytest.mark.parametrize("action", ["bond_draw", "bond_refresh"])
def test_bond_family_agreement_does_not_claim_same_action(action):
    result = summary.summarize([row(action, "bond")])
    assert only_round(result)["recommend_vs_plan_target_agree"] == 1
    assert result["actual_action_evidence"] == "NOT_AVAILABLE"


def test_other_known_family_disagrees():
    r = row()
    r["actual"]["plan_target"] = "treasure"
    assert only_round(summary.summarize([r]))["recommend_vs_plan_target_disagree"] == 1


def test_no_plan_is_not_disagreement():
    r = row()
    r["actual"]["plan_target"] = None
    r["boundary"] = "phase_exit"
    result = only_round(summary.summarize([r]))
    assert result["recommend_no_actual_plan"] == 1
    assert result["recommend_vs_actual_disagree"] == 0


def test_legacy_unpaired_boundary_is_not_comparable():
    r = row(schema=1)
    r["boundary"] = "free"
    result = only_round(summary.summarize([r]))
    assert result["recommend_vs_actual_agree"] == 0
    assert result["recommend_plan_uncomparable"] == 1


@pytest.mark.parametrize("bad", ["{broken", "[]", "null", '{"schema": NaN}'])
def test_corrupt_rows_are_not_silently_dropped(tmp_path, bad):
    p = write_log(tmp_path / "solo_shadow_a.jsonl", [row()])
    with p.open("a", encoding="utf-8") as f:
        f.write(bad + "\n")
    with pytest.raises(ValueError, match=r"solo_shadow_a.jsonl:2"):
        summary.load([str(p)])


@pytest.mark.parametrize("field,value", [
    ("schema", 999), ("schema", True), ("seq", "1"),
    ("seq", 0), ("round_id", ""), ("decision", []), ("actual", []),
])
def test_malformed_record_is_rejected(tmp_path, field, value):
    r = row()
    r[field] = value
    p = write_log(tmp_path / "solo_shadow_a.jsonl", [r])
    with pytest.raises(ValueError):
        summary.load([str(p)])


def test_duplicate_json_keys_are_rejected(tmp_path):
    p = tmp_path / "solo_shadow_a.jsonl"
    p.write_text('{"schema":1,"schema":2}\n', encoding="utf-8")
    with pytest.raises(ValueError):
        summary.load([str(p)])


def test_duplicate_input_paths_are_not_counted_twice(tmp_path):
    p = write_log(tmp_path / "solo_shadow_a.jsonl", [row()])
    assert len(summary.load([str(tmp_path), str(p)])) == 1


def test_same_round_in_different_files_is_not_joined(tmp_path):
    write_log(tmp_path / "solo_shadow_a.jsonl", [row()])
    write_log(tmp_path / "solo_shadow_b.jsonl", [row()])
    report = summary.summarize(summary.load([str(tmp_path)]))
    assert report["totals"]["rounds"] == 2


def test_mixed_log_schema_is_not_joined():
    assert summary.summarize([row(schema=1), row(seq=2)])['totals']['rounds'] == 2


def test_sequence_reset_in_same_file_requires_review(tmp_path):
    p = write_log(tmp_path / "solo_shadow_a.jsonl", [row(), row()])
    with pytest.raises(ValueError):
        summary.load([str(p)])


def test_missing_input_does_not_silently_use_other_inputs(tmp_path):
    p = write_log(tmp_path / "solo_shadow_a.jsonl", [row()])
    with pytest.raises(ValueError):
        summary.load([str(p), str(tmp_path / "solo_shadow_missing.jsonl")])


def test_cli_rejects_corruption_without_partial_success(tmp_path, capsys):
    p = write_log(tmp_path / "solo_shadow_a.jsonl", [row()])
    with p.open("a", encoding="utf-8") as f:
        f.write('{broken\n')
    assert summary.main([str(p), "--json"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "INVALID_SHADOW_EVIDENCE" in captured.err


def test_cli_valid_log_reports_scope(tmp_path, capsys):
    p = write_log(tmp_path / "solo_shadow_a.jsonl", [row()])
    assert summary.main([str(p), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["behavior_proof"] is False


def test_empty_input_is_not_pass(tmp_path):
    assert summary.main([str(tmp_path)]) == 2
