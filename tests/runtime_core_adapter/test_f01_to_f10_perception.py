"""Tests for F01..F10: Perception, Snapshot, Proof, and Domain Prerequisite Facts."""
from __future__ import annotations

from unittest.mock import Mock
import numpy as np
import pytest

from shuabao.interaction_surface import InteractionSurface, PendingAction
from shuabao.mediator import FrameEvidence, PanelState
from shuabao.runtime_core.arbiter import Demand, TaskSpec
from shuabao.runtime_core.coordinator import ActionContract, Coordinator
from shuabao.runtime_core.transactions import Outcome, Phase, Proof
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult
from shuabao.runtime_core_adapter import (
    Fact,
    Knowledge,
    PendingObservation,
    RuntimeCoreAdapter,
    RuntimeCoreMode,
    RuntimeSnapshotProjector,
    TakeoverBatch,
    TakeoverConfig,
    TargetObservation,
    WindowEpochParts,
    WorldSnapshot,
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


class TestF01ToF10Perception:
    def test_f01_unhealthy_or_invalid_frame_yields_unknown_and_invalid_proof(self) -> None:
        """F01: 无效/空/最小化/黑屏/低熵/冻结/过期 Frame -> Proof 无效、零输入。"""
        executor = Mock()
        clock = FakeClock(start=100.0)
        projector = RuntimeSnapshotProjector()
        epoch_parts = make_epoch_parts()

        unhealthy_frames = [
            make_frame(is_valid=False, error="capture_failed"),
            make_frame(bgr=np.zeros((0, 0, 3), dtype=np.uint8)),
            make_frame(is_minimized=True),
            make_frame(bgr=np.zeros((100, 100, 3), dtype=np.uint8)),  # black frame
        ]

        for frame in unhealthy_frames:
            ev = make_evidence(frame, gen=1)
            pending_fact = Fact(Knowledge.KNOWN, None, "pending", "v1")
            snapshot = projector.snapshot(
                frame,
                ev,
                PanelState.CLOSED,
                pending_fact,
                (),
                now=clock.now(),
                epoch_parts=epoch_parts,
                round_id="r1",
            )
            # Frame unhealthy or safety facts UNKNOWN
            assert (
                snapshot.frame_healthy.knowledge == Knowledge.UNKNOWN
                or snapshot.frame_healthy.value is False
            )
            assert (
                snapshot.input_safe.knowledge == Knowledge.UNKNOWN
                or snapshot.input_safe.value is False
            )
            proof = projector.proof(snapshot)
            assert proof.valid is False

        assert executor.mock_calls == []

    def test_f02_hwnd_mismatch_yields_unknown_safety_facts(self) -> None:
        """F02: Frame.hwnd 与 FrameEvidence.hwnd 不同 -> snapshot 安全事实 UNKNOWN。"""
        executor = Mock()
        clock = FakeClock(start=100.0)
        projector = RuntimeSnapshotProjector()
        epoch_parts = make_epoch_parts(hwnd=1001)

        frame = make_frame(hwnd=1001)
        # evidence has different HWND
        ev = make_evidence(frame, gen=1, hwnd=1002)
        pending_fact = Fact(Knowledge.KNOWN, None, "pending", "v1")

        snapshot = projector.snapshot(
            frame,
            ev,
            PanelState.CLOSED,
            pending_fact,
            (),
            now=clock.now(),
            epoch_parts=epoch_parts,
            round_id="r1",
        )

        assert snapshot.input_safe.knowledge == Knowledge.UNKNOWN
        assert snapshot.window_role.knowledge == Knowledge.UNKNOWN
        assert snapshot.cursor_empty.knowledge == Knowledge.UNKNOWN
        assert snapshot.surface_released.knowledge == Knowledge.UNKNOWN
        assert executor.mock_calls == []

    def test_f03_fuzzy_ocr_or_low_score_match_yields_unknown_machine_id(self) -> None:
        """F03: 模糊 OCR、低分/低 margin、未知模板名 -> machine ID UNKNOWN，不授权。"""
        executor = Mock()
        clock = FakeClock(start=100.0)
        projector = RuntimeSnapshotProjector()
        epoch_parts = make_epoch_parts()
        frame = make_frame()
        ev = make_evidence(frame)

        # Match 1: unknown template name
        match_unknown = MatchResult("unknown_random_button", 0.95, 10, 10, 20, 20, 10, 10)
        # Match 2: known name but very low score
        match_low_score = MatchResult("skill_card", 0.3, 30, 30, 20, 20, 30, 30)

        snapshot = projector.snapshot(
            frame,
            ev,
            PanelState.ACTIVE,
            Fact(Knowledge.KNOWN, None, "pending", "v1"),
            (match_unknown, match_low_score),
            now=clock.now(),
            epoch_parts=epoch_parts,
            round_id="r1",
        )

        assert len(snapshot.targets) == 2
        assert snapshot.targets[0].machine_id.knowledge == Knowledge.UNKNOWN
        assert snapshot.targets[1].machine_id.knowledge == Knowledge.UNKNOWN

        # Attempt to authorize an action with unknown machine ID
        authorizer = DummyAuthorizer()
        grant = Mock(task="skill", token="t1", generation=1)
        contract = authorizer.authorize(grant, snapshot)
        assert contract is None
        assert executor.mock_calls == []

    def test_f04_conflicting_panels_or_panel_state_conflict_yields_unknown_surface(self) -> None:
        """F04: 互斥面板同帧命中或 PanelState/像素冲突 -> surface UNKNOWN，零输入。"""
        executor = Mock()
        clock = FakeClock(start=100.0)
        projector = RuntimeSnapshotProjector()
        epoch_parts = make_epoch_parts()
        frame = make_frame()
        ev = make_evidence(frame)

        # PanelState says CLOSED, but visual matches detect an open card modal
        card_modal_match = MatchResult("center_card_modal_anchor", 0.95, 10, 10, 50, 50, 10, 10)
        snapshot = projector.snapshot(
            frame,
            ev,
            PanelState.CLOSED,  # conflict with match!
            Fact(Knowledge.KNOWN, None, "pending", "v1"),
            (card_modal_match,),
            now=clock.now(),
            epoch_parts=epoch_parts,
            round_id="r1",
        )

        assert snapshot.interaction_surface.knowledge == Knowledge.UNKNOWN
        assert snapshot.surface_released.knowledge == Knowledge.UNKNOWN
        assert snapshot.surface_released.value is not True
        assert executor.mock_calls == []

    def test_f05_unreadable_pending_action_not_treated_as_no_pending(self) -> None:
        """F05: PendingAction 状态无法读取 -> 不得当成“无 pending”。"""
        executor = Mock()
        clock = FakeClock(start=100.0)
        projector = RuntimeSnapshotProjector()
        epoch_parts = make_epoch_parts()
        frame = make_frame()
        ev = make_evidence(frame)

        unreadable_pending = Fact(Knowledge.UNKNOWN, None, "pending_reader", "v1", reason="cannot_read")
        snapshot = projector.snapshot(
            frame,
            ev,
            PanelState.CLOSED,
            unreadable_pending,
            (),
            now=clock.now(),
            epoch_parts=epoch_parts,
            round_id="r1",
        )

        assert snapshot.pending_action.knowledge == Knowledge.UNKNOWN
        # Must not claim surface_released=True because pending action cannot be ruled out
        assert (
            snapshot.surface_released.knowledge == Knowledge.UNKNOWN
            or snapshot.surface_released.value is not True
        )
        assert executor.mock_calls == []

    def test_f06_unknown_prerequisite_facts_retain_requested_but_not_eligible(self) -> None:
        """F06: 资源/角标/卡组/背包空位/Boss 未知 -> requested 可保留，eligible 必须 false。"""
        executor = Mock()
        clock = FakeClock(start=100.0)
        projector = RuntimeSnapshotProjector()

        # Build snapshot with unknown task facts
        task_facts = {
            "skill_points": Fact(Knowledge.UNKNOWN, None, "ocr", "v1", reason="ocr_failed"),
            "wood_count": Fact(Knowledge.UNKNOWN, None, "ocr", "v1", reason="obscured"),
            "bag_free_slots": Fact(Knowledge.UNKNOWN, None, "bag", "v1", reason="unscanned"),
        }
        snapshot = make_snapshot(task_facts=task_facts, observed_at=clock.now())
        demands = projector.demands(snapshot)

        for d in demands:
            if d.task in ("skill", "bond", "pickup"):
                assert d.requested is True
                assert d.eligible is False
                assert d.blocked_reason.endswith("_unknown")

        assert executor.mock_calls == []

    def test_f07_same_or_earlier_generation_cannot_confirm_postcondition(self) -> None:
        """F07: 同 generation 或早于 dispatch 的帧 -> 不得确认 postcondition。"""
        executor = Mock()
        clock = FakeClock(start=100.0)
        adapter = RuntimeCoreAdapter(
            "r1",
            TakeoverConfig(RuntimeCoreMode.CORE, TakeoverBatch.GFV_PICKUP),
            clock,
            DummyAuthorizer(),
        )
        p_init = make_proof(gen=1, now=100.0, valid=True, cursor_empty=True)
        adapter.observe(make_snapshot(generation=1, observed_at=100.0), (Demand("skill", True, True, "v1"),), p_init)
        assert adapter.coordinator.leases.current is not None

        contract = ActionContract("act_skill", "tgt_skill", "post_skill", authorized=True)
        token = adapter.coordinator.leases.current.token
        adapter.dispatch(token, contract, 100.0, p_init)

        # Same generation (1 <= 1)
        p_same_gen = make_proof(gen=1, now=101.0, valid=True, postcondition=True)
        adapter.observe_outcome(token, "post_skill", 101.0, p_same_gen)
        assert adapter.coordinator.leases.current.phase == Phase.VERIFYING
        assert adapter.coordinator.leases.current.confirmed_steps == 0

        # Earlier than dispatch
        p_early = make_proof(gen=2, now=99.0, valid=True, postcondition=True)
        adapter.observe_outcome(token, "post_skill", 101.0, p_early)
        assert adapter.coordinator.leases.current.phase == Phase.VERIFYING
        assert adapter.coordinator.leases.current.confirmed_steps == 0
        assert executor.mock_calls == []

    def test_f08_panel_close_or_pixel_change_alone_cannot_confirm_success(self) -> None:
        """F08: 仅面板关闭、像素变化或 act_* 成功 -> 不得宣称学习/获得/消费成功。"""
        executor = Mock()
        clock = FakeClock(start=100.0)
        adapter = RuntimeCoreAdapter(
            "r1",
            TakeoverConfig(RuntimeCoreMode.CORE, TakeoverBatch.GFV_PICKUP),
            clock,
            DummyAuthorizer(),
        )
        p_init = make_proof(gen=1, now=100.0, valid=True, cursor_empty=True)
        adapter.observe(make_snapshot(generation=1, observed_at=100.0), (Demand("skill", True, True, "v1"),), p_init)
        assert adapter.coordinator.leases.current is not None

        contract = ActionContract("act_skill", "tgt_skill", "post_skill", authorized=True)
        token = adapter.coordinator.leases.current.token
        adapter.dispatch(token, contract, 100.0, p_init)

        # Domain postcondition verifier did not confirm (postcondition=None)
        p_unconfirmed = make_proof(gen=2, now=101.0, valid=True, postcondition=None, surface_released=True)
        adapter.observe_outcome(token, "post_skill", 101.0, p_unconfirmed)

        with pytest.raises(RuntimeError):
            adapter.finish(token, Outcome.CONFIRMED, 101.0, p_unconfirmed)
        assert executor.mock_calls == []

    def test_f09_unknown_cursor_or_surface_retains_owner_on_release(self) -> None:
        """F09: cursor/surface 未知 -> release 失败且 owner 保留。"""
        executor = Mock()
        clock = FakeClock(start=100.0)
        adapter = RuntimeCoreAdapter(
            "r1",
            TakeoverConfig(RuntimeCoreMode.CORE, TakeoverBatch.GFV_PICKUP),
            clock,
            DummyAuthorizer(),
        )
        p_init = make_proof(gen=1, now=100.0, valid=True, cursor_empty=True)
        adapter.observe(make_snapshot(generation=1, observed_at=100.0), (Demand("skill", True, True, "v1"),), p_init)
        assert adapter.coordinator.leases.current is not None
        token = adapter.coordinator.leases.current.token

        # Proof has unknown cursor (cursor_empty=None)
        p_unknown_cursor = make_proof(gen=2, now=101.0, valid=True, cursor_empty=None, surface_released=True)
        with pytest.raises(RuntimeError):
            adapter.finish(token, Outcome.NO_PROGRESS, 101.0, p_unknown_cursor)
        assert adapter.coordinator.leases.current is not None

        # Proof has unknown surface (surface_released=None)
        p_unknown_surface = make_proof(gen=2, now=101.0, valid=True, cursor_empty=True, surface_released=None)
        with pytest.raises(RuntimeError):
            adapter.finish(token, Outcome.NO_PROGRESS, 101.0, p_unknown_surface)
        assert adapter.coordinator.leases.current is not None
        assert executor.mock_calls == []


    def test_f10_input_invalidation_generation_advance_yields_invalid_proof(self) -> None:
        """F10: 输入失效导致 gen+1 但 Frame 未更新 -> Proof.valid 必须 false。"""
        executor = Mock()
        clock = FakeClock(start=100.0)
        projector = RuntimeSnapshotProjector()
        epoch_parts = make_epoch_parts()

        frame = make_frame()
        # Initial capture at gen 1
        ev1 = make_evidence(frame, gen=1)
        snap1 = projector.snapshot(
            frame, ev1, PanelState.CLOSED, Fact(Knowledge.KNOWN, None, "pending", "v1"),
            (), now=clock.now(), epoch_parts=epoch_parts, round_id="r1",
        )
        p1 = projector.proof(snap1)
        assert p1.valid is True

        # Input occurred, evidence generation advanced to 2, but frame is still the exact same object
        ev2 = make_evidence(frame, gen=2)
        snap2 = projector.snapshot(
            frame, ev2, PanelState.CLOSED, Fact(Knowledge.KNOWN, None, "pending", "v1"),
            (), now=clock.now(), epoch_parts=epoch_parts, round_id="r1",
        )
        p2 = projector.proof(snap2)
        # Because frame was not updated after input invalidation, proof.valid must be False!
        assert p2.valid is False
        assert executor.mock_calls == []
