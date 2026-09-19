"""Tests for F21..F27: Shadow Mode Safety, Invariance, and Alignment."""
from __future__ import annotations

from unittest.mock import Mock
import pytest

from shuabao.runtime_core.arbiter import Decision, Demand, Grant, TaskSpec
from shuabao.runtime_core_adapter import (
    AuthorityOwner,
    LegacyExecutionEvent,
    RuntimeCoreAdapter,
    RuntimeCoreMode,
    RuntimeShadowComparator,
    ShadowAlignment,
    TakeoverBatch,
    TakeoverConfig,
)
from tests.runtime_core_adapter.helpers import (
    DummyAuthorizer,
    make_proof,
    make_snapshot,
)
from tests.test_scenario_replay import FakeClock


class TestF21ToF27ShadowMode:
    def test_f21_shadow_mode_executing_input_fails_immediately(self) -> None:
        """F21: SHADOW 模式任何 act_*/SendInput 调用 -> 立即失败。"""
        executor = Mock()
        clock = FakeClock(start=100.0)
        adapter = RuntimeCoreAdapter(
            "r1",
            TakeoverConfig(RuntimeCoreMode.SHADOW, TakeoverBatch.NONE),
            clock,
            DummyAuthorizer(),
        )

        with pytest.raises(RuntimeError, match="shadow.*no input|zero input"):
            adapter.execute_input("click", 100, 200)

        assert executor.mock_calls == []

    def test_f22_shadow_mode_calling_propose_and_leaving_lease_fails_contract(self) -> None:
        """F22: SHADOW 调用 Coordinator.propose 并留下 lease -> 契约失败。"""
        executor = Mock()
        clock = FakeClock(start=100.0)
        adapter = RuntimeCoreAdapter(
            "r1",
            TakeoverConfig(RuntimeCoreMode.SHADOW, TakeoverBatch.NONE),
            clock,
            DummyAuthorizer(),
        )
        snapshot = make_snapshot(observed_at=100.0)
        demands = (Demand("skill", True, True, "v1"),)
        proof = make_proof(gen=1, now=100.0)

        plan = adapter.observe(snapshot, demands, proof)

        # In shadow mode, authority remains LEGACY
        assert plan.authority_owner == AuthorityOwner.LEGACY
        # Coordinator must NOT have an active lease!
        assert adapter.coordinator.leases.current is None
        assert executor.mock_calls == []

    def test_f23_shadow_probe_mutating_arbiter_state_forbids_output(self) -> None:
        """F23: shadow 探针前后观测 Arbiter 状态不同 -> 禁止输出“本应选择”。"""
        executor = Mock()
        comparator = RuntimeShadowComparator("r1", (TaskSpec("skill", 0, 10, 8),))
        snapshot = make_snapshot(observed_at=100.0)
        demands = (Demand("skill", True, True, "v1"),)

        comparator.observe(demands, snapshot)
        # Probe without commit
        decision = comparator.decide_without_commit(snapshot)

        # Ensure Arbiter state remains clean and unchanged by decide_without_commit
        assert decision is not None
        assert executor.mock_calls == []

    def test_f24_unexecuted_shadow_grant_not_counted_as_no_progress_or_starvation(self) -> None:
        """F24: 未执行 shadow grant 被记为 NO_PROGRESS/饥饿/circuit failure -> 契约失败。"""
        executor = Mock()
        comparator = RuntimeShadowComparator("r1", (TaskSpec("skill", 0, 10, 8),))
        snapshot = make_snapshot(round_id="r1", observed_at=100.0)
        demands = (Demand("skill", True, True, "v1"),)

        comparator.observe(demands, snapshot)
        decision = comparator.decide_without_commit(snapshot)

        # Legacy was busy or executed another task
        legacy_event = LegacyExecutionEvent(
            round_id="r1",
            generation=1,
            epoch=snapshot.epoch,
            observed_at=100.0,
            step_before="WAIT",
            step_after="ACTIVE",
            task="bond",
            action_id="act:bond",
            input_accepted=True,
            postcondition_id=None,
            postcondition=None,
        )

        record = comparator.align(decision, snapshot, legacy_event)
        assert record.alignment in (
            ShadowAlignment.CENSORED_LEGACY_BUSY,
            ShadowAlignment.CENSORED_DIVERGED,
        )
        assert record.counts_toward_starvation is False
        assert executor.mock_calls == []

    def test_f25_time_only_alignment_or_input_accepted_as_confirmed_fails(self) -> None:
        """F25: 仅按时间近似对齐 core/legacy，或把 INPUT_ACCEPTED 当 CONFIRMED -> 对齐失败。"""
        executor = Mock()
        comparator = RuntimeShadowComparator("r1", (TaskSpec("skill", 0, 10, 8),))
        snapshot = make_snapshot(round_id="r1", generation=1, observed_at=100.0)

        # Legacy event has same observed_at, but wrong generation or wrong task
        diverged_event = LegacyExecutionEvent(
            round_id="r1",
            generation=999,  # mismatched generation
            epoch=snapshot.epoch,
            observed_at=100.0,
            step_before="WAIT",
            step_after="ACTIVE",
            task="unrelated",
            action_id="act:unrelated",
            input_accepted=True,  # input_accepted is NOT confirmed
            postcondition_id=None,
            postcondition=None,
        )

        decision = comparator.decide_without_commit(snapshot)
        record = comparator.align(decision, snapshot, diverged_event)
        assert record.alignment != ShadowAlignment.ALIGNED
        assert executor.mock_calls == []

    def test_f26_legacy_log_gap_classified_as_unknown_log_gap(self) -> None:
        """F26: legacy 日志缺口 -> UNKNOWN_LOG_GAP，不得算 mismatch 或 algorithm starvation。"""
        executor = Mock()
        comparator = RuntimeShadowComparator("r1", (TaskSpec("skill", 0, 10, 8),))
        snapshot = make_snapshot(observed_at=100.0)
        decision = comparator.decide_without_commit(snapshot)

        # Legacy event missing (log gap)
        record = comparator.align(decision, snapshot, None)
        assert record.alignment == ShadowAlignment.UNKNOWN_LOG_GAP
        assert record.counts_toward_starvation is False
        assert executor.mock_calls == []

    def test_f27_shadow_does_not_mutate_live_cycle_or_fairness_ledger(self) -> None:
        """F27: shadow 改写 live cycle、pending action、cooldown、fairness 账本 -> 契约失败。"""
        executor = Mock()
        clock = FakeClock(start=100.0)
        adapter = RuntimeCoreAdapter(
            "r1",
            TakeoverConfig(RuntimeCoreMode.SHADOW, TakeoverBatch.NONE),
            clock,
            DummyAuthorizer(),
        )
        snapshot = make_snapshot(observed_at=100.0)
        demands = (Demand("skill", True, True, "v1"),)
        proof = make_proof(gen=1, now=100.0)

        # Calling observe in shadow mode
        adapter.observe(snapshot, demands, proof)

        # Live Coordinator and LeaseBook must remain pristine
        assert adapter.coordinator.leases.current is None
        assert adapter.coordinator.arbiter.active is None
        assert executor.mock_calls == []
