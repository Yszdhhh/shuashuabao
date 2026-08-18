"""Regression coverage for incident 20260818_113934."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from shuabao.choice_policy import (
    PANEL_TREASURE,
    PanelCandidates,
    PolicyAction,
    SessionState,
    SlotCandidate,
    assemble_policy_settings,
    choose_action,
)
from shuabao.vision.ocr_shadow.client import ShadowClient


ENV_ECHO_WORKER = r"""
import json, os, sys
print(json.dumps({
    'type': 'ready',
    'seq': 0,
    'status': 'ok',
    'candidates': [],
    'elapsed_ms': 0,
    'reason': os.environ.get('PYTHONPATH', ''),
}), flush=True)
for line in sys.stdin:
    request = json.loads(line)
    if request.get('type') == 'ping':
        print(json.dumps({
            'type': 'pong',
            'seq': request['seq'],
            'status': 'ok',
            'candidates': [],
            'elapsed_ms': 0,
        }), flush=True)
"""


def runtime_policy_settings():
    settings = SimpleNamespace(
        skills=[],
        cards=[],
        treasure_allow_negative=[],
        skill_archive_levels={},
    )
    return assemble_policy_settings(
        settings=settings,
        skill_labels={},
        fetter_labels={},
        policy_doc={},
    )


class TestOcrSubprocessEnvironmentRegression(unittest.TestCase):
    def test_relative_repo_root_becomes_absolute_and_src_heads_pythonpath(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            (repo / "src").mkdir(parents=True)
            old_cwd = Path.cwd()
            os.chdir(tmp)
            client = None
            try:
                client = ShadowClient(
                    repo_root="repo",
                    python_executable=sys.executable,
                    worker_command=[sys.executable, "-c", ENV_ECHO_WORKER],
                    startup_timeout_ms=1000,
                    timeout_ms=300,
                )
                self.assertEqual(client.repo_root, repo.resolve())
                self.assertEqual(client.src_dir, (repo / "src").resolve())
                self.assertTrue(client.repo_root.is_absolute())
                self.assertTrue(client.src_dir.is_absolute())
                self.assertTrue(client.ping())
                child_pythonpath = client._ready_reason or ""
                self.assertEqual(
                    child_pythonpath.split(os.pathsep)[0],
                    str((repo / "src").resolve()),
                )
            finally:
                if client is not None:
                    client.close()
                os.chdir(old_cwd)

    def test_default_worker_fails_fast_when_repo_has_no_shuabao_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = ShadowClient(
                repo_root=tmp,
                python_executable=sys.executable,
                max_restarts=1,
                restart_cooldown_s=0.0,
                startup_timeout_ms=200,
                timeout_ms=100,
            )
            try:
                self.assertFalse(client.ping())
                self.assertEqual(client._ready_reason, "spawn")
            finally:
                client.close()


class TestTreasureNoRefreshDeadlockRegression(unittest.TestCase):
    def test_runtime_defaults_disable_blind_refresh(self):
        policy = runtime_policy_settings()
        self.assertFalse(policy.treasure_refresh_on_no_safe)

        candidates = PanelCandidates(
            panel_kind=PANEL_TREASURE,
            slots=(
                SlotCandidate(index=0, name=None, confidence=0.99),
                SlotCandidate(index=1, name=None, confidence=0.99),
            ),
            has_giveup=True,
            settings=policy,
        )
        decision = choose_action(
            candidates,
            SessionState(waits=5, max_waits=5, refreshes=0, max_refreshes=3),
        )
        self.assertEqual(decision.action, PolicyAction.CLOSE)
        self.assertNotEqual(decision.action, PolicyAction.REFRESH)
        self.assertIn("直接关闭/隐藏面板", decision.reason)

    def test_no_giveup_button_closes_instead_of_refreshing(self):
        policy = runtime_policy_settings()
        candidates = PanelCandidates(
            panel_kind=PANEL_TREASURE,
            slots=(SlotCandidate(index=0, name=None, confidence=0.99),),
            has_giveup=False,
            settings=policy,
        )
        decision = choose_action(
            candidates,
            SessionState(waits=5, max_waits=5, refreshes=0, max_refreshes=3),
        )
        self.assertEqual(decision.action, PolicyAction.CLOSE)
        self.assertNotEqual(decision.action, PolicyAction.REFRESH)

    def test_quality_fallback_still_selects_known_safe_treasure(self):
        policy = runtime_policy_settings()
        candidates = PanelCandidates(
            panel_kind=PANEL_TREASURE,
            slots=(
                SlotCandidate(index=0, name="智力祝福", confidence=0.99, rarity="purple"),
                SlotCandidate(index=1, name="橙色安全宝物", confidence=0.99, rarity="orange"),
            ),
            has_giveup=True,
            settings=policy,
        )
        decision = choose_action(candidates, SessionState())
        self.assertEqual(
            (decision.action, decision.index),
            (PolicyAction.SELECT_SLOT, 1),
        )


if __name__ == "__main__":
    unittest.main()
