"""Tests for F28..F38: Takeover Batches, Authority Exclusivity, and Boundary Safety."""
from __future__ import annotations

from unittest.mock import Mock
import pytest

from shuabao.runtime_core.arbiter import Demand, TaskSpec
from shuabao.runtime_core.contracts import (
    CardInstance,
    ItemFact,
    ItemKind,
    Location,
    authorize_consumption,
)
from shuabao.runtime_core.coordinator import ActionContract
from shuabao.runtime_core_adapter import (
    AuthorityOwner,
    Fact,
    Knowledge,
    RuntimeCoreAdapter,
    RuntimeCoreMode,
    RuntimeSnapshotProjector,
    TakeoverBatch,
    TakeoverConfig,
    validate_takeover_config,
)
from tests.runtime_core_adapter.helpers import (
    DummyAuthorizer,
    make_proof,
    make_snapshot,
)
from tests.test_scenario_replay import FakeClock


class TestF28ToF38TakeoverAuthority:
    def test_f28_simultaneous_core_and_legacy_authority_fails_contract(self) -> None:
        """F28: 同 tick/transaction 同时给 CORE 和 LEGACY 输入授权 -> 契约失败。"""
        executor = Mock()
        clock = FakeClock(start=100.0)
        adapter = RuntimeCoreAdapter(
            "r1",
            TakeoverConfig(RuntimeCoreMode.CORE, TakeoverBatch.GFV_PICKUP),
            clock,
            DummyAuthorizer(),
        )
        snapshot = make_snapshot(observed_at=100.0)
        demands = (Demand("skill", True, True, "v1"),)
        proof = make_proof(gen=1, now=100.0)

        plan = adapter.observe(snapshot, demands, proof)

        # Plan must NEVER give both CORE and LEGACY authority simultaneously
        if plan.authority_owner == AuthorityOwner.CORE:
            assert plan.legacy_task is None
        elif plan.authority_owner == AuthorityOwner.LEGACY:
            assert plan.decision is None or plan.decision.grant is None

        assert executor.mock_calls == []

    def test_f29_switching_to_legacy_before_core_lease_settled_fails_contract(self) -> None:
        """F29: core lease/grant 未收口就切 legacy/回退 -> 契约失败。"""
        executor = Mock()
        clock = FakeClock(start=100.0)
        adapter = RuntimeCoreAdapter(
            "r1",
            TakeoverConfig(RuntimeCoreMode.CORE, TakeoverBatch.GFV_PICKUP),
            clock,
            DummyAuthorizer(),
        )
        snapshot = make_snapshot(observed_at=100.0)
        demands = (Demand("skill", True, True, "v1"),)
        proof = make_proof(gen=1, now=100.0)

        # Acquire a core lease
        adapter.observe(snapshot, demands, proof)
        assert adapter.coordinator.leases.current is not None

        # Attempt to switch authority to LEGACY while lease is unreleased
        can_switch = adapter.can_switch_authority(snapshot, proof, AuthorityOwner.LEGACY)
        assert can_switch is False

        assert executor.mock_calls == []

    def test_f30_enabling_later_batch_without_prerequisite_rejected(self) -> None:
        """F30: 后批开关在前批未开时启用 -> 配置拒绝。"""
        executor = Mock()

        # Batch 2 (EVOLUTION_EQUIPMENT) requires Batch 1 (GFV_PICKUP)
        with pytest.raises(ValueError, match="prerequisite|dependency|batch"):
            validate_takeover_config(
                TakeoverConfig(
                    mode=RuntimeCoreMode.CORE,
                    batch=TakeoverBatch.EVOLUTION_EQUIPMENT,
                    gfv_pickup=False,
                    evolution_equipment=True,
                )
            )

        # Batch 3 (ITEM_FLOW) requires Batch 2 (EVOLUTION_EQUIPMENT)
        with pytest.raises(ValueError, match="prerequisite|dependency|batch"):
            validate_takeover_config(
                TakeoverConfig(
                    mode=RuntimeCoreMode.CORE,
                    batch=TakeoverBatch.ITEM_FLOW,
                    gfv_pickup=True,
                    evolution_equipment=False,
                    item_flow=True,
                )
            )

        assert executor.mock_calls == []

    def test_f31_untaken_task_cannot_obtain_legacy_baton_while_core_owns_ui(self) -> None:
        """F31: 未接管任务在 core owner 存在时获得 legacy baton -> 契约失败。"""
        executor = Mock()
        clock = FakeClock(start=100.0)
        adapter = RuntimeCoreAdapter(
            "r1",
            TakeoverConfig(RuntimeCoreMode.CORE, TakeoverBatch.GFV_PICKUP),
            clock,
            DummyAuthorizer(),
        )
        snapshot = make_snapshot(observed_at=100.0)
        demands = (
            Demand("skill", True, True, "v1"),
            Demand("hero", True, True, "v1"),  # hero is untaken in Batch 1
        )
        proof = make_proof(gen=1, now=100.0)

        # First observe acquires lease for skill (core)
        plan1 = adapter.observe(snapshot, demands, proof)
        assert plan1.authority_owner == AuthorityOwner.CORE

        # In second tick while core lease is active, hero must NOT receive legacy baton!
        clock.advance(1.0)
        plan2 = adapter.observe(
            make_snapshot(generation=2, observed_at=clock.now()),
            demands,
            make_proof(gen=2, now=clock.now()),
        )
        assert plan2.legacy_task is None

        assert executor.mock_calls == []

    def test_f32_authorized_true_without_domain_authorizer_fails_contract(self) -> None:
        """F32: ActionContract.authorized=True 来自常量、开关、grant 或 match score -> 契约失败。"""
        executor = Mock()
        clock = FakeClock(start=100.0)
        # An authorizer that tries to return authorized=True when facts are UNKNOWN
        class RogueAuthorizer:
            def authorize(self, grant, snapshot):
                return ActionContract("act", "tgt", "post", authorized=True)

        adapter = RuntimeCoreAdapter(
            "r1",
            TakeoverConfig(RuntimeCoreMode.CORE, TakeoverBatch.GFV_PICKUP),
            clock,
            RogueAuthorizer(),
        )
        # Snapshot has unknown facts
        snapshot_unknown = make_snapshot(
            observed_at=100.0,
            task_facts={"skill_points": Fact(Knowledge.UNKNOWN, None, "ocr", "v1")},
        )
        grant = Mock(task="skill", token="t1", generation=1)

        # Adapter authorization MUST validate domain facts and refuse rogue authorization
        contract = adapter.authorize(grant, snapshot_unknown)
        assert contract is None

        assert executor.mock_calls == []

    def test_f32_full_known_snapshot_with_rogue_authorizer_rejected(self) -> None:
        """F32: 全 KNOWN snapshot + 假授权器 -> 必须拒绝。

        结构性审查属性说明：
        授权器内部是否真正执行了经审查的领域门禁（而非硬编码 return ActionContract(authorized=True)），
        在 Python 动态运行期无法直接通过对象自省完全得知，是依赖架构接线和代码审查保证的结构性属性。
        但在运行期，适配器必须对以下可检验属性做强校验：
        1. 授权器必须来自构造时登记的白名单实例，拒绝未登记的任意外部鸭子类型对象；
        2. Contract 的 action_id / target_id 必须与调度 grant 一致，严禁张冠李戴；
        3. Contract 的 postcondition_id 必须为非空且已注册的具名后置。
        任何一项不符均须拒绝授权（返回 None）。
        """
        executor = Mock()
        clock = FakeClock(start=100.0)

        # 假授权器：硬编码 authorized=True，且返回不匹配 grant 或未注册后置的 contract
        class FakeAuthorizer:
            def authorize(self, grant, snapshot):
                return ActionContract("wrong_action", "wrong_target", "arbitrary_postcondition", authorized=True)

        fake_authorizer = FakeAuthorizer()
        # 全 KNOWN 的 snapshot
        snapshot_all_known = make_snapshot(
            observed_at=100.0,
            task_facts={
                "skill_points": Fact(Knowledge.KNOWN, 1, "ocr", "v1"),
                "wood": Fact(Knowledge.KNOWN, 500, "ocr", "v1"),
                "bag_free_slots": Fact(Knowledge.KNOWN, 3, "bag", "v1"),
            },
        )
        grant = Mock(task="skill", token="t1", generation=1)

        adapter = RuntimeCoreAdapter(
            "r1",
            TakeoverConfig(RuntimeCoreMode.CORE, TakeoverBatch.GFV_PICKUP),
            clock,
            fake_authorizer,
        )

        # 即使 snapshot 全 KNOWN，假授权器也必须被拒绝
        contract = adapter.authorize(grant, snapshot_all_known)
        assert contract is None
        assert executor.mock_calls == []

    def test_f32_authorizer_mismatched_target_or_unregistered_postcondition_rejected(self) -> None:
        """F32: 校验 contract 的 target/action 必须与 grant 一致，postcondition 必须为已注册具名后置。"""
        executor = Mock()
        clock = FakeClock(start=100.0)

        snapshot_all_known = make_snapshot(
            observed_at=100.0,
            task_facts={
                "skill_points": Fact(Knowledge.KNOWN, 1, "ocr", "v1"),
            },
        )
        grant = Mock(task="skill", token="t1", generation=1)

        # 1. 任务张冠李戴：grant 是 skill，contract 返回 bond 的 action/target
        class MismatchedTaskAuthorizer:
            def authorize(self, grant, snapshot):
                return ActionContract("act:bond", "tgt:bond", "post:bond", authorized=True)

        mismatched_auth = MismatchedTaskAuthorizer()
        adapter1 = RuntimeCoreAdapter(
            "r1",
            TakeoverConfig(RuntimeCoreMode.CORE, TakeoverBatch.GFV_PICKUP),
            clock,
            mismatched_auth,
            allowed_authorizers=(mismatched_auth,),
        )
        assert adapter1.authorize(grant, snapshot_all_known) is None

        # 2. postcondition_id 为空或未注册的任意字符串
        class UnregisteredPostconditionAuthorizer:
            def authorize(self, grant, snapshot):
                return ActionContract("act:skill", "tgt:skill", "unregistered_random_postcondition_xyz", authorized=True)

        unregistered_auth = UnregisteredPostconditionAuthorizer()
        adapter2 = RuntimeCoreAdapter(
            "r1",
            TakeoverConfig(RuntimeCoreMode.CORE, TakeoverBatch.GFV_PICKUP),
            clock,
            unregistered_auth,
            allowed_authorizers=(unregistered_auth,),
        )
        assert adapter2.authorize(grant, snapshot_all_known) is None

        # 3. 授权器非构造时登记的白名单实例
        whitelisted_auth = DummyAuthorizer()
        rogue_auth = DummyAuthorizer()
        adapter3 = RuntimeCoreAdapter(
            "r1",
            TakeoverConfig(RuntimeCoreMode.CORE, TakeoverBatch.GFV_PICKUP),
            clock,
            rogue_auth,
            allowed_authorizers=(whitelisted_auth,),  # rogue_auth 不在白名单
        )
        assert adapter3.authorize(grant, snapshot_all_known) is None

        assert executor.mock_calls == []


    def test_f33_demand_revision_containing_time_or_gen_fails_contract(self) -> None:
        """F33: Demand.revision 包含 time/generation/frame hash，造成每帧清退避 -> 契约失败。"""
        executor = Mock()
        clock = FakeClock(start=100.0)
        projector = RuntimeSnapshotProjector()

        # Two snapshots at different times and generations, but identical game facts
        snap1 = make_snapshot(generation=1, observed_at=100.0)
        snap2 = make_snapshot(generation=2, observed_at=101.0)

        d1 = projector.demands(snap1)
        d2 = projector.demands(snap2)

        # Revisions for corresponding tasks must be IDENTICAL across frames
        rev1 = {d.task: d.revision for d in d1}
        rev2 = {d.task: d.revision for d in d2}
        assert rev1 == rev2

        assert executor.mock_calls == []

    def test_f34_candidate_or_resource_change_must_change_demand_revision(self) -> None:
        """F34: 相关候选/资源/规则改变而 revision 不变 -> 契约失败。"""
        executor = Mock()
        clock = FakeClock(start=100.0)
        projector = RuntimeSnapshotProjector()

        snap1 = make_snapshot(
            generation=1,
            observed_at=100.0,
            task_facts={"wood": Fact(Knowledge.KNOWN, 100, "ocr", "v1")},
        )
        snap2 = make_snapshot(
            generation=2,
            observed_at=101.0,
            task_facts={"wood": Fact(Knowledge.KNOWN, 200, "ocr", "v2")},
        )

        d1 = projector.demands(snap1)
        d2 = projector.demands(snap2)

        rev1 = {d.task: d.revision for d in d1}
        rev2 = {d.task: d.revision for d in d2}
        assert rev1["bond"] != rev2["bond"]

        assert executor.mock_calls == []

    def test_f35_pickup_due_with_unknown_bag_or_boss_cannot_input(self) -> None:
        """F35: pickup 到期但背包空位或 Boss/模态状态未知 -> 不得输入。"""
        executor = Mock()
        clock = FakeClock(start=100.0)
        projector = RuntimeSnapshotProjector()

        # Pickup requested, but bag slots or boss state unknown
        task_facts = {
            "pickup_due": Fact(Knowledge.KNOWN, True, "timer", "v1"),
            "bag_free_slots": Fact(Knowledge.UNKNOWN, None, "bag", "v1"),
            "boss_state": Fact(Knowledge.UNKNOWN, None, "vision", "v1"),
        }
        snapshot = make_snapshot(observed_at=100.0, task_facts=task_facts)
        demands = projector.demands(snapshot)

        pickup_demand = next(d for d in demands if d.task == "pickup")
        assert pickup_demand.requested is True
        assert pickup_demand.eligible is False

        assert executor.mock_calls == []

    def test_f36_batch1_routing_evolution_or_item_flow_to_core_fails(self) -> None:
        """F36: BATCH_1 中进化/装备或物品移动/消费从 core 发输入 -> 路由失败。"""
        executor = Mock()
        clock = FakeClock(start=100.0)
        adapter = RuntimeCoreAdapter(
            "r1",
            TakeoverConfig(RuntimeCoreMode.CORE, TakeoverBatch.GFV_PICKUP),
            clock,
            DummyAuthorizer(),
        )
        snapshot = make_snapshot(observed_at=100.0)

        # Attempt to route "hero" (evolution) or "personal_bag" (item flow) to core
        plan_hero = adapter.route_task("hero", snapshot)
        assert plan_hero.authority_owner != AuthorityOwner.CORE

        plan_bag = adapter.route_task("personal_bag", snapshot)
        assert plan_bag.authority_owner != AuthorityOwner.CORE

        assert executor.mock_calls == []

    def test_f37_public_asset_in_personal_slot_cannot_be_marked_self_consumable(self) -> None:
        """F37: 公共资产移到个人临时格就被标记为 self/可消费 -> 契约失败。"""
        executor = Mock()
        clock = FakeClock(start=100.0)
        adapter = RuntimeCoreAdapter(
            "r1",
            TakeoverConfig(RuntimeCoreMode.CORE, TakeoverBatch.GFV_PICKUP),
            clock,
            DummyAuthorizer(),
        )
        p = make_proof(gen=1, now=100.0, valid=True, cursor_empty=True)

        # Item moved from public bag/team asset
        item = ItemFact("item1", ItemKind.PILL, owner="team", location=Location.PERSONAL_BAG)
        targets = (CardInstance("c1", "can1", "fam", 1),)

        auth = adapter.authorize_consumption(
            item,
            targets,
            explicitly_enabled=True,
            solo=True,
            target_set_complete=True,
            mechanism_verified=True,
            transaction_active=False,
            proof=p,
            now=100.0,
        )

        assert auth.allowed is False
        assert auth.reason == "not_personal_asset"

        assert executor.mock_calls == []


    def test_f38_reusing_coordinator_or_epoch_without_new_round_boundary_fails(self) -> None:
        """F38: 新局未确认就复用上局 Coordinator/snapshot/epoch -> 局隔离失败。"""
        executor = Mock()
        clock = FakeClock(start=100.0)
        adapter = RuntimeCoreAdapter(
            "round:1",
            TakeoverConfig(RuntimeCoreMode.CORE, TakeoverBatch.GFV_PICKUP),
            clock,
            DummyAuthorizer(),
        )

        # New round begins, attempting to reuse round:1 coordinator without new round boundary
        with pytest.raises(ValueError, match="round mismatch|round isolation"):
            adapter.observe_round("round:2", reuse_coordinator=True)

        assert executor.mock_calls == []
