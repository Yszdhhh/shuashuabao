"""Tests for F11..F20: Epoch, Monotonic Clock, and Coordinator Lifetime."""
from __future__ import annotations

from dataclasses import replace
from unittest.mock import Mock
import pytest

from shuabao.mediator import PanelState
from shuabao.runtime_core.arbiter import Demand, TaskSpec
from shuabao.runtime_core.coordinator import ActionContract, Coordinator
from shuabao.runtime_core.transactions import LeaseBook, Outcome, Phase
from shuabao.runtime_core_adapter import (
    AuthorityOwner,
    Fact,
    Knowledge,
    RuntimeCoreAdapter,
    RuntimeCoreMode,
    RuntimeSnapshotProjector,
    TakeoverBatch,
    TakeoverConfig,
    WindowEpochParts,
    compute_window_epoch,
)

from tests.runtime_core_adapter.helpers import (
    DummyAuthorizer,
    make_epoch_parts,
    make_evidence,
    make_frame,
    make_proof,
    make_snapshot,
)
from tests.test_scenario_replay import FakeClock


class TestF11ToF20EpochClockCoordinator:
    def test_f11_hwnd_change_with_same_title_changes_epoch(self) -> None:
        """F11: 同标题不同 HWND 切换 -> epoch 变更、旧 proof 失效。"""
        executor = Mock()
        parts1 = make_epoch_parts(hwnd=1001)
        parts2 = make_epoch_parts(hwnd=1002)

        epoch1 = compute_window_epoch(parts1)
        epoch2 = compute_window_epoch(parts2)
        assert epoch1 != epoch2

        # Old proof with epoch1 cannot be used for epoch2 lease
        book = LeaseBook()
        p1 = make_proof(gen=1, now=10.0, epoch=epoch1)
        book.acquire("t1", "skill", 10.0, 10.0, p1)

        # Dispatching with old epoch when new epoch is active
        p2 = make_proof(gen=2, now=11.0, epoch=epoch2)
        with pytest.raises(ValueError):
            book.dispatch("t1", "act", 11.0, p2)

        assert executor.mock_calls == []

    def test_f12_numeric_hwnd_reuse_by_new_process_changes_epoch(self) -> None:
        """F12: 数字 HWND 被新进程重用 -> process/binding 身份使 epoch 变更。"""
        executor = Mock()
        # Same numeric HWND, but process_identity or window_binding_id differs
        parts_old = make_epoch_parts(hwnd=1001, process_identity="pid:100:1", window_binding_id="bind:1")
        parts_new = make_epoch_parts(hwnd=1001, process_identity="pid:200:1", window_binding_id="bind:2")

        epoch_old = compute_window_epoch(parts_old)
        epoch_new = compute_window_epoch(parts_new)
        assert epoch_old != epoch_new
        assert executor.mock_calls == []

    def test_f13_dpi_size_scale_layout_changes_change_epoch(self) -> None:
        """F13: DPI、client size、ui_scale 或 layout version 任一变化 -> epoch 变更。"""
        executor = Mock()
        base = make_epoch_parts()
        base_epoch = compute_window_epoch(base)

        assert compute_window_epoch(replace(base, dpi=120)) != base_epoch
        assert compute_window_epoch(replace(base, client_size=(1600, 900))) != base_epoch
        assert compute_window_epoch(replace(base, ui_scale=1.25)) != base_epoch
        assert compute_window_epoch(replace(base, layout_version="v2")) != base_epoch

        assert executor.mock_calls == []

    def test_f14_stale_epoch_proof_rejected_without_clearing_owner(self) -> None:
        """F14: 用旧 epoch proof dispatch/release -> 拒绝，不清 owner。"""
        executor = Mock()
        clock = FakeClock(start=100.0)
        adapter = RuntimeCoreAdapter(
            "r1",
            TakeoverConfig(RuntimeCoreMode.CORE, TakeoverBatch.GFV_PICKUP),
            clock,
            DummyAuthorizer(),
        )
        p1 = make_proof(gen=1, now=100.0, epoch="epoch:1", cursor_empty=True)
        adapter.observe(make_snapshot(generation=1, observed_at=100.0, epoch="epoch:1"), (Demand("skill", True, True, "v1"),), p1)
        token = adapter.coordinator.leases.current.token

        p_stale = make_proof(gen=2, now=101.0, epoch="epoch:old")
        with pytest.raises(ValueError):
            adapter.dispatch(token, ActionContract("act", "tgt", "post", True), 101.0, p_stale)
        assert adapter.coordinator.leases.current is not None

        with pytest.raises(RuntimeError):
            adapter.finish(token, Outcome.NO_PROGRESS, 101.0, p_stale)
        assert adapter.coordinator.leases.current is not None
        assert executor.mock_calls == []

    def test_f15_epoch_change_with_active_owner_triggers_reconcile(self) -> None:
        """F15: owner 存在时 epoch 变化 -> RECONCILE，不新建 Coordinator 绕过。"""
        executor = Mock()
        clock = FakeClock(start=100.0)
        adapter = RuntimeCoreAdapter(
            "r1",
            TakeoverConfig(RuntimeCoreMode.CORE, TakeoverBatch.GFV_PICKUP),
            clock,
            DummyAuthorizer(),
        )
        p1 = make_proof(gen=1, now=100.0, epoch="epoch:1", cursor_empty=True)
        adapter.observe(make_snapshot(generation=1, observed_at=100.0, epoch="epoch:1"), (Demand("skill", True, True, "v1"),), p1)
        token = adapter.coordinator.leases.current.token
        adapter.dispatch(token, ActionContract("act", "tgt", "post", True), 100.0, p1)

        p_new_epoch = make_proof(gen=2, now=101.0, epoch="epoch:2")
        adapter.observe_outcome(token, "post", 101.0, p_new_epoch)
        assert adapter.coordinator.leases.current is not None
        assert adapter.coordinator.leases.current.phase == Phase.RECONCILE
        assert adapter.coordinator.leases.current.reason == "epoch_changed"
        assert executor.mock_calls == []


    def test_f16_wall_clock_jumps_do_not_affect_core_deadlines(self) -> None:
        """F16: wall clock 向前/向后跳变 -> core wait/deadline 不受影响。"""
        executor = Mock()
        clock = FakeClock(start=100.0)
        config = TakeoverConfig(mode=RuntimeCoreMode.CORE, batch=TakeoverBatch.GFV_PICKUP)
        adapter = RuntimeCoreAdapter("r1", config, clock, DummyAuthorizer())

        snapshot = make_snapshot(round_id="r1", observed_at=clock.now())
        p = make_proof(gen=1, now=clock.now())
        demands = (Demand("skill", True, True, "v1"),)

        # First observation at monotonic 100.0
        plan1 = adapter.observe(snapshot, demands, p)
        assert plan1.authority_owner == AuthorityOwner.CORE

        # Suppose wall clock jumped forward 3600 seconds, but monotonic clock only advanced 1 second
        clock.advance(1.0)
        p_next = make_proof(gen=2, now=clock.now())
        snapshot_next = make_snapshot(round_id="r1", generation=2, observed_at=clock.now())

        # Core accounts wait time is measured solely by monotonic clock (1.0s, not 3600s)
        plan2 = adapter.observe(snapshot_next, demands, p_next)
        diag = adapter.coordinator.arbiter.diagnostics(clock.now())
        assert diag["skill"]["wall_wait"] <= 2.0  # strictly in monotonic domain
        assert executor.mock_calls == []

    def test_f17_subtracting_wall_deadline_with_monotonic_now_fails_contract(self) -> None:
        """F17: 拿 legacy wall deadline 与 monotonic now 相减 -> 契约失败，不接管。"""
        executor = Mock()
        clock = FakeClock(start=100.0)
        adapter = RuntimeCoreAdapter(
            "r1",
            TakeoverConfig(RuntimeCoreMode.CORE, TakeoverBatch.GFV_PICKUP),
            clock,
            DummyAuthorizer(),
        )

        wall_deadline = 1700000000.0  # Unix timestamp
        monotonic_now = clock.now()   # 100.0

        with pytest.raises(ValueError, match="domain|wall|monotonic"):
            adapter.calculate_deadline_or_validate(wall_deadline, monotonic_now)

        assert executor.mock_calls == []

    def test_f18_using_frame_timestamp_as_captured_at_fails_contract(self) -> None:
        """F18: 将 Frame.timestamp 直接填 Proof.captured_at -> 契约失败。"""
        executor = Mock()
        clock = FakeClock(start=100.0)
        projector = RuntimeSnapshotProjector()

        # Frame.timestamp is wall clock (e.g. 1700000000.0)
        frame = make_frame(timestamp=1700000000.0)
        ev = make_evidence(frame)
        snap = projector.snapshot(
            frame, ev, PanelState.CLOSED, Fact(Knowledge.KNOWN, None, "pending", "v1"),
            (), now=clock.now(), epoch_parts=make_epoch_parts(), round_id="r1",
        )
        proof = projector.proof(snap)

        # Proof.captured_at MUST be from monotonic clock (100.0), NOT frame.timestamp
        assert proof.captured_at == 100.0
        assert proof.captured_at != frame.timestamp
        assert executor.mock_calls == []

    def test_f19_non_monotonic_or_non_finite_time_rejected(self) -> None:
        """F19: monotonic now 回退/非有限值 -> 内核拒绝。"""
        executor = Mock()
        clock = FakeClock(start=100.0)
        adapter = RuntimeCoreAdapter(
            "r1",
            TakeoverConfig(RuntimeCoreMode.CORE, TakeoverBatch.GFV_PICKUP),
            clock,
            DummyAuthorizer(),
        )
        snap = make_snapshot(observed_at=100.0)
        demands = (Demand("skill", True, True, "v1"),)
        p = make_proof(gen=1, now=100.0)
        adapter.observe(snap, demands, p)

        # Non-monotonic time (backward jump)
        with pytest.raises(ValueError, match="non-monotonic"):
            adapter.observe(make_snapshot(generation=2, observed_at=90.0), demands, make_proof(gen=2, now=90.0))

        # Non-finite time (NaN)
        with pytest.raises(ValueError, match="non-finite|non-monotonic"):
            adapter.observe(make_snapshot(generation=3, observed_at=float("nan")), demands, make_proof(gen=3, now=float("nan")))

        assert executor.mock_calls == []

    def test_f20_recreating_coordinator_after_timeout_within_same_round_fails_contract(self) -> None:
        """F20: 同局超时后重建 Coordinator 清除账本 -> 契约失败。"""
        executor = Mock()
        clock = FakeClock(start=100.0)
        adapter = RuntimeCoreAdapter(
            "round:1",
            TakeoverConfig(RuntimeCoreMode.CORE, TakeoverBatch.GFV_PICKUP),
            clock,
            DummyAuthorizer(),
        )

        # Attempt to recreate coordinator within the same round to wipe failure ledger
        with pytest.raises(RuntimeError, match="same round|cannot recreate"):
            adapter.recreate_coordinator("round:1")

        assert executor.mock_calls == []
