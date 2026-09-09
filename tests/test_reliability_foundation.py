"""reliability_foundation 单元测试：进度、代际、溯源、裁决、身份自述。"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.reliability_foundation import (  # noqa: E402
    ActionIntent,
    ActionSafetyPolicy,
    AuthorizationVerdict,
    BindingGeneration,
    BusinessOutcome,
    BusinessProgressToken,
    ExecutionAssessment,
    ObservationProvenance,
    ProgressTracker,
    RoundGeneration,
    RuntimeIdentityManifest,
    TransactionGeneration,
)


def _provenance(hwnd: int = 111, binding_gen: int = 1) -> ObservationProvenance:
    return ObservationProvenance(
        frame_id=42,
        timestamp=1000.0,
        backend="uia",
        hwnd=hwnd,
        pid=7,
        rect=(0, 0, 100, 200),
        dpi=96.0,
        binding_gen=binding_gen,
    )


class TestProgressTracker(unittest.TestCase):
    def test_records_progress_and_calculates_age(self) -> None:
        tracker = ProgressTracker()
        tracker.record(BusinessProgressToken.ROOM_ENTERED, now=100.0)
        self.assertIsNone(tracker.age(BusinessProgressToken.ROUND_RESOLVED, now=150.0))
        tracker.record(BusinessProgressToken.ROUND_RESOLVED, now=130.0)
        self.assertAlmostEqual(tracker.age(BusinessProgressToken.ROUND_RESOLVED, now=150.0), 20.0)
        self.assertAlmostEqual(tracker.age(BusinessProgressToken.ROOM_ENTERED, now=150.0), 50.0)

    def test_stagnation_and_threshold(self) -> None:
        tracker = ProgressTracker()
        self.assertTrue(tracker.is_stagnant(30.0, now=999.0))  # 从未进展 = 已停滞
        tracker.record(BusinessProgressToken.LOBBY_READY, now=100.0)
        self.assertAlmostEqual(tracker.stagnation(now=125.0), 25.0)
        self.assertFalse(tracker.is_stagnant(30.0, now=125.0))
        self.assertTrue(tracker.is_stagnant(30.0, now=200.0))


class TestBindingGeneration(unittest.TestCase):
    def test_bump_and_match(self) -> None:
        binding = BindingGeneration(hwnd=111)
        self.assertEqual(binding.generation, 0)
        self.assertTrue(binding.matches(111, 0))
        binding.bump()
        self.assertFalse(binding.matches(111, 0))
        self.assertTrue(binding.matches(111, 1))

    def test_rejects_mismatch(self) -> None:
        binding = BindingGeneration(hwnd=111, generation=2)
        self.assertFalse(binding.matches(222, 2))  # 错窗口
        self.assertFalse(binding.matches(111, 1))  # 旧代数
        with self.assertRaises(ValueError):
            binding.validate(111, 1)
        binding.validate(111, 2)  # 不抛


class TestRoundGeneration(unittest.TestCase):
    def test_bump_invalidates_old_generation(self) -> None:
        rounds = RoundGeneration()
        gen = rounds.bump()
        self.assertTrue(rounds.is_current(gen))
        rounds.bump()
        self.assertFalse(rounds.is_current(gen))
        self.assertTrue(rounds.is_current(rounds.generation))


class TestTransactionGeneration(unittest.TestCase):
    def test_active_then_committed(self) -> None:
        tx = TransactionGeneration()
        self.assertFalse(tx.is_active)
        gen = tx.open()
        self.assertTrue(tx.is_active)
        self.assertFalse(tx.is_resolved)
        tx.commit()
        self.assertEqual(tx.state, "committed")
        self.assertTrue(tx.is_resolved)
        self.assertFalse(tx.is_active)
        with self.assertRaises(RuntimeError):
            tx.commit()  # 已收敛，禁止二次收敛

    def test_active_then_ambiguous(self) -> None:
        tx = TransactionGeneration()
        tx.open()
        tx.mark_ambiguous()
        self.assertEqual(tx.state, "ambiguous")
        self.assertTrue(tx.is_resolved)

    def test_open_bumps_generation(self) -> None:
        tx = TransactionGeneration()
        first = tx.open()
        tx.commit()
        second = tx.open()
        self.assertEqual(second, first + 1)
        self.assertTrue(tx.is_active)


class TestObservationProvenance(unittest.TestCase):
    def test_matches_binding(self) -> None:
        binding = BindingGeneration(hwnd=111, generation=1)
        self.assertTrue(_provenance(hwnd=111, binding_gen=1).matches_binding(binding))
        self.assertFalse(_provenance(hwnd=222, binding_gen=1).matches_binding(binding))
        binding.bump()
        self.assertFalse(_provenance(hwnd=111, binding_gen=1).matches_binding(binding))


class TestActionSafetyPolicy(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = ActionSafetyPolicy()
        self.binding = BindingGeneration(hwnd=111, generation=3)

    def _intent(self, **kwargs) -> ActionIntent:
        base = dict(
            action="click",
            target_hwnd=111,
            binding_gen=3,
            context_known=True,
        )
        base.update(kwargs)
        return ActionIntent(**base)

    def test_allow(self) -> None:
        self.assertEqual(
            self.policy.authorize(self._intent(), self.binding),
            AuthorizationVerdict.ALLOW,
        )

    def test_deny_wrong_hwnd(self) -> None:
        self.assertEqual(
            self.policy.authorize(self._intent(target_hwnd=222), self.binding),
            AuthorizationVerdict.DENY_WRONG_HWND,
        )

    def test_deny_stale_binding(self) -> None:
        self.assertEqual(
            self.policy.authorize(self._intent(binding_gen=2), self.binding),
            AuthorizationVerdict.DENY_STALE_BINDING,
        )

    def test_deny_unknown_context(self) -> None:
        self.assertEqual(
            self.policy.authorize(self._intent(context_known=False), self.binding),
            AuthorizationVerdict.DENY_UNKNOWN_CONTEXT,
        )

    def test_deny_protected_personal_resource(self) -> None:
        self.assertEqual(
            self.policy.authorize(self._intent(personal_protected_resource=True), self.binding),
            AuthorizationVerdict.DENY_PROTECTED_PERSONAL_RESOURCE,
        )

    def test_deny_ambiguous_transaction(self) -> None:
        self.assertEqual(
            self.policy.authorize(self._intent(transaction_state="ambiguous"), self.binding),
            AuthorizationVerdict.DENY_AMBIGUOUS_TRANSACTION,
        )
        # 活跃事务不拦截
        self.assertEqual(
            self.policy.authorize(self._intent(transaction_state="active"), self.binding),
            AuthorizationVerdict.ALLOW,
        )


class TestExecutionAssessment(unittest.TestCase):
    def test_confirmed_outcomes(self) -> None:
        prov = _provenance()
        success = ExecutionAssessment(outcome=BusinessOutcome.CONFIRMED_SUCCESS, provenance=prov)
        no_effect = ExecutionAssessment(outcome=BusinessOutcome.CONFIRMED_NO_EFFECT)
        ambiguous = ExecutionAssessment(outcome=BusinessOutcome.AMBIGUOUS)
        self.assertTrue(success.is_confirmed)
        self.assertTrue(no_effect.is_confirmed)
        self.assertFalse(ambiguous.is_confirmed)


class TestRuntimeIdentityManifest(unittest.TestCase):
    def test_serialization_roundtrip(self) -> None:
        manifest = RuntimeIdentityManifest(
            source_sha="6a155a8",
            build_id="b20260910-01",
            model_id="glm-5.3-flash",
            asset_id="vault-v7",
            channel="release",
        )
        payload = json.loads(manifest.to_json())
        self.assertEqual(payload["source_sha"], "6a155a8")
        self.assertEqual(payload["channel"], "release")
        self.assertEqual(RuntimeIdentityManifest.from_json(manifest.to_json()), manifest)


if __name__ == "__main__":
    unittest.main()
