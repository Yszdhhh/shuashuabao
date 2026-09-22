"""The comparison tool must not turn failed or different runs green."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import pytest

PATH = Path(__file__).resolve().parents[1] / "tools" / "compare_solo_shadow_behavior.py"
spec = importlib.util.spec_from_file_location("audit_compare_shadow", PATH)
compare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compare)


@pytest.mark.parametrize("left,right", [
    ("exit=1\n2 failed, 15 passed in 0.1s", "exit=1\n2 failed, 15 passed in 0.1s"),
    ("exit=0\n15 passed in 0.1s", "exit=1\n1 failed, 15 passed in 0.1s"),
    ("exit=0\n15 passed in 0.1s", "exit=0\n14 passed in 0.2s"),
    ("exit=0\n15 passed in 0.1s", "exit=0\n15 passed, 1 skipped in 0.1s"),
    ("exit=2\n1 error in 0.1s", "exit=2\n1 error in 0.1s"),
    ("exit=0\nno tests ran in 0.1s", "exit=0\nno tests ran in 0.1s"),
    ("exit=0\n0 passed in 0.1s", "exit=0\n0 passed in 0.1s"),
    ("exit=0\n15 passed", "exit=0\n15 passed"),
    ("exit=0\n1 failed, 15 passed in 0.1s", "exit=0\n1 failed, 15 passed in 0.1s"),
])
def test_failed_different_or_unparseable_runs_fail_closed(monkeypatch, left, right):
    monkeypatch.setattr(compare, "run", lambda flag: left if flag == "0" else right)
    assert compare.main() == 1


def test_equal_success_ignores_duration_but_does_not_claim_behavior_proof(monkeypatch, capsys):
    logs = {"0": "exit=0\n15 passed, 2 skipped in 0.1s",
            "1": "exit=0\n15 passed, 2 skipped in 4.2s"}
    monkeypatch.setattr(compare, "run", logs.__getitem__)
    assert compare.main() == 0
    assert "NOT_BEHAVIOR_PROOF" in capsys.readouterr().out


def test_run_keeps_stderr_and_bounds_subprocess(monkeypatch):
    from types import SimpleNamespace
    calls = []
    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return SimpleNamespace(returncode=2, stdout="", stderr="collection traceback")
    monkeypatch.setattr(compare.subprocess, "run", fake_run)
    output = compare.run("1")
    assert output.startswith("exit=2\n") and "collection traceback" in output
    assert calls[0][1]["env"]["SHUABAO_SOLO_SHADOW"] == "1"
    assert calls[0][1]["timeout"] > 0
