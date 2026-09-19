"""薄主循环适配器接口草案（DESIGN ONLY）。

状态
====

本文件只定义设计边界、数据类型和 Protocol 签名；不实现主循环、截图、OCR、
SendInput、调度器或 watchdog。参考内核 ``src/shuabao/runtime_core/`` 并没有
``WorldSnapshot`` 类型；它是本适配边界拥有的不可变 DTO，再单向投影为内核
``Demand`` 和 ``Proof``。不修改内核安全约束。

非目标：

* 不复制 ``_l1_cycle_step`` 的选卡、OCR、截图、后置验证或 ``act_*`` 逻辑。
* 不新建 scheduler/watchdog；排队、老化、grant 和 lease 均来自已交付内核。
* 不把配置意图、模板命中、grant 或输入成功当成业务后置事实。
* 不为 shadow 构造 ``ActionContract``，更不把
  ``ActionContract.authorized`` 硬编码成 ``True``。

1. 感知到 WorldSnapshot / Demand / Proof
=============================================

``Frame``
    只提供当前客户区像素、HWND、标题、尺寸和采集健康信息。
    ``Frame.timestamp`` 现为 wall clock，仅作兼容/诊断元数据，不能填入
    ``Proof.captured_at``。无效、最小化、黑屏、低熵、冻结或过期帧使
    snapshot 的安全事实为 UNKNOWN，不是 ``False`` 或“默认 HUD”。

``FrameEvidence``
    ``gen`` 是整局严格递增的 observation generation；``hwnd`` 和
    ``ui_scale`` 必须与当前帧及 epoch 一致。现有 ``invalidate_evidence`` 可在
    输入后对同一帧推进 ``gen``；这种“输入失效代”不是新采集，适配器
    必须产出 ``Proof.valid=False``，直到收到不同的新 ``Frame``。

``MatchResult``
    只是当前 generation 内的位置候选。只有经审核的 exact-name
    映射才能产出 machine ID；未知名、模糊 OCR、分数/分差不足、ROI 不合法或
    同时命中互斥面板都保持 UNKNOWN。坐标和 ``score`` 不产生输入授权。

``PanelState``
    ``OPEN_REQUESTED/WAIT_VISIBLE/ACTIVE/WAIT_MUTATION/CLOSING`` 映射为
    “交互面已占用”；``COOLDOWN`` 不自动等于已释放。``CLOSED`` 只有在
    同 generation 还正向观测到无持物、无遮挡、无 pending action 时，才能使
    ``surface_released=True``。状态与视觉冲突时是 UNKNOWN，不选一边猜测。

``PendingAction``
    映射为当前 transaction 的 ``kind/target_id/postcondition_id`` 及待验证事实。
    只有匹配 action/target、更新 generation、捕获时间不早于派发时间，并且
    调用现有具名 verifier，才能填 ``Proof.postcondition=True/False``。无相关
    pending action 或验证条件不足时必须是 ``None``（UNKNOWN）。旧
    ``PendingAction.deadline`` 属 wall-clock 域，不做算术转换；只在无旧 pending
    的安全边界由适配器建立新 monotonic deadline。

``Demand``
    ``requested`` 表示现有策略对任务有需求，``eligible`` 还要求所有安全与
    领域前置事实已知。任一必需事实 UNKNOWN 时使用
    ``requested=True, eligible=False, blocked_reason='<fact>_unknown'``；不把未知资源、
    角标、背包空位或 Boss 状态当成可执行。``revision`` 是任务相关语义事实
    的稳定 hash（候选集、资源、构筑、规则版本、阻塞原因）；禁止放入
    generation、当前时间或整帧像素 hash，否则每帧都会错误清除退避。

G/F/V/拾取首批映射：``G -> skill``、``F -> bond``、
``V -> treasure``、``Z/HUD pickup -> pickup``。下列事实只是 Demand 前置：

* skill：可读技能点/候选与已知安全 HUD；未知角标不等于 0，也不可执行。
* bond：可读当前木材、真实当前卡组/目标及可负担成本；配置预设不是占有事实。
* treasure：可读待领次数/面板候选；打开过 V 不是宝物已获得。
* pickup：可读拾取目标、个人背包安全空位与 Boss/模态状态；周期到期只表示
  requested，不单独使 eligible 成立。

``Proof``
    ``generation/epoch/captured_at`` 来自同一 snapshot；``captured_at`` 是统一单调
    时钟下接收该采集的时刻。``valid`` 要求帧健康、epoch 完整、采集与
    evidence 同源且未被输入失效。``cursor_empty`` 和 ``surface_released`` 仅能由
    正向观测填 ``True``；未观测是 ``None``，不允许用默认值补齐。

2. Proof.epoch 与窗口切换
=============================

epoch 的规范输入至少是：

``schema_version + window_binding_id + hwnd + process_identity + window_role +``
``client_size + dpi + ui_scale + layout_version``

``window_binding_id`` 在每次经确认的目标窗口重绑时变更，即使数字 HWND
相同；``process_identity`` 用现有窗口层能提供的 PID+进程启动标识/受控绑定代
表示，防止 HWND 重用。``layout_version`` 是布局/场景规则的受控版本，不是每帧
像素 hash。epoch 串由上述字段规范化后 hash，不使用窗口标题作唯一身份。

任一身份、DPI、客户区尺寸、ui_scale 或布局版本变化时：

1. 推进 generation，丢弃 FrameEvidence cache，新帧前 ``Proof.valid=False``。
2. 无 owner 时，所有旧 proof 不能 acquire/dispatch。
3. 有 owner 时，向同一 ``LeaseBook.observe`` 提交新 epoch，使 lease 进入
   ``RECONCILE(reason='epoch_changed')``；不得新建 Coordinator 或清 owner。
4. 只有新窗口上另行授权的可逆补偿和新鲜安全边界证明才能收口；无法证明
   指针为空/遮挡释放时，保留 owner 并停止相关输入。

3. 统一单调时钟
==================

适配器每局注入唯一 ``MonotonicClock``，生产使用 ``time.monotonic``，测试使用
FakeClock。每 tick 只读一次 ``now``，并将同一值传给 snapshot、Demand 观测、
Proof、Coordinator 和 shadow 记录。内核的 deadline/age/cooldown 只处于该时钟域。

迁移边界：

* 新 adapter/core 状态从创建起只接受 monotonic 秒。
* 旧 ``_l1_cycle_step``/``PendingAction`` 在未接管批次内继续使用自己的 wall-clock
  deadline；两个域的数字绝不相减、不相比。
* 批次接管只在无旧 pending action、无持物、无遮挡、无活动 core lease 的
  安全边界生效。不将 wall deadline “换算”为 monotonic deadline。
* 同局不因超时、回退或窗口切换重建 Coordinator；只在真实新局边界创建。

不由本适配器迁移/不得直接换域的点：

* 人类可读审计、JSONL ``ts``、evidence manifest、文件名和跨进程协议时间戳保留
  UTC/wall time；它们仅作展示/关联，不进入内核决策。
* ``Frame.timestamp`` 和 OCR shadow ``sent_at/ts`` 是已有兼容契约；本文件不改它们，
  也不将它们用作 ``Proof.captured_at``。
* L0 大厅/创房、capture 重试循环、``reliability_foundation`` 和未接管的
  ``runtime_mediator`` 计时属各自 owner 的单独迁移项；在它们被逐项改造和回归前，
  adapter 只能将其结果当作带来源的事实，不能混用 deadline。
* 历史录屏/回放中的 wall timestamp 不重写；回放时由 FakeClock 提供新的单调
  时间轴。

4. Shadow 对照模式
==================

shadow 下唯一输入授权者是旧循环。适配器只记录 Demand 和“内核本应选择的任务”；
不调用 ``act_*``，不调用 ``Coordinator.propose``（它会 acquire LIVE lease），不调用
``dispatch/finish``。

对照决策使用已交付 ``Arbiter`` 的一次性状态分支：观测状态先更新等待账本，
``choose`` 只在可丢弃副本上运行，得到 counterfactual ``Decision`` 后立即丢弃副本。
这不是第二个 scheduler；它是同一内核决策的无副作用探针。实现前必须用失败用例
固定“探针前后观测账本完全相同”；如果不能证明，shadow 只记 Demand，不产生
选择结论。

与现有 ``_l1_cycle_step`` 对齐的一行 shadow 记录至少包含：

* ``round_id + generation + epoch + monotonic observed_at`` 作为主关联键；wall ``ts`` 只辅助人工阅读。
* snapshot/demand revision、core chosen task/reason/overdue，以及决策时的
  ``input_safe``/owner 状态。
* 旧循环 ``step_before/step_after``、``_trace_actions`` 的 intent/reason/ok，以及之后的具名
  ``PendingAction``/后置结果。``act_* ok=True`` 只记 ``INPUT_ACCEPTED``，不记
  ``CONFIRMED``。
* alignment 使用 task/action 映射、round、epoch、generation 窗口和具名后置；
  不只按时间近似匹配。

未完成 shadow grant 绝不生成 ``Receipt``，不记 ``NO_PROGRESS``，不打开 circuit，
也不保留 active grant。它被记为 ``CENSORED_LEGACY_BUSY``、``CENSORED_DIVERGED``、
``CENSORED_WINDOW_ENDED`` 或 ``UNKNOWN_LOG_GAP``。饥饿结论只能来自“持续 requested+eligible、
无 owner/无安全阻塞、超过 max_wait，但内核在多次可决策机会均选了别的任务”。
被旧循环占用或未执行的 counterfactual grant 必须从该指标剔除。

5. 分批接管、开关与回退
========================

开关是受控配置，不是视觉事实，更不是点击授权。建议形状：

* ``runtime_core_mode = LEGACY_ONLY | SHADOW | CORE``
* ``runtime_core_gfv_pickup``（第 1 批，G/F/V + pickup）
* ``runtime_core_evolution_equipment``（第 2 批，依赖第 1 批）
* ``runtime_core_item_flow``（第 3 批，物品移动/消费，依赖前两批）

每批路由与回退：

===============================  ===========================================  =============================================
批次                             CORE 路由                                    回退路径
===============================  ===========================================  =============================================
SHADOW                           零输入，只对照 G/F/V/pickup                  直接回 ``LEGACY_ONLY``
BATCH_1_GFV_PICKUP               ``bond/skill/treasure/pickup``             安全边界回 ``SHADOW``/全 legacy
BATCH_2_EVOLUTION_EQUIPMENT      第 1 批 + ``hero/equipment``                 安全边界回 BATCH_1
BATCH_3_ITEM_FLOW                前两批 + bag/move/consume                  安全边界回 BATCH_2
===============================  ===========================================  =============================================

“安全边界”同时要求：无 core lease/grant、无 legacy pending action、新鲜同 epoch
Proof 明确 ``cursor_empty=True`` 且 ``surface_released=True``。中途失败时不立即
把授权交还 legacy；原 owner 必须先完成 reconcile/可逆补偿/安全释放。

部分批次期间，适配器是唯一授权门：一次 tick/transaction 只能选择
``AuthorityOwner.CORE`` 或 ``AuthorityOwner.LEGACY`` 之一。CORE 有 grant/lease 时 legacy 整个
输入路径关闭；未接管任务仅能在 core 无 owner 且安全边界上获得一次明确
legacy baton。在 baton 收口前 core 不得发新 grant。最终 BATCH_3 后不再调用旧
``_l1_cycle_step`` 授权。

grant 仅表示调度许可。``ActionContract`` 必须来自 ``DomainAuthorizer`` 对当前
snapshot 调用已审查的领域门禁；任一事实 UNKNOWN 时返回 ``None``。禁止从
feature flag、Demand.eligible、grant 存在、``MatchResult`` 得分或“旧逻辑曾点过”
推导 ``authorized=True``。

6. 实现前必须先固定的失败用例
======================================

F01  无效/空/最小化/黑屏/低熵/冻结/过期 Frame -> Proof 无效、零输入。
F02  Frame.hwnd 与 FrameEvidence.hwnd 不同 -> snapshot 安全事实 UNKNOWN。
F03  模糊 OCR、低分/低 margin、未知模板名 -> machine ID UNKNOWN，不授权。
F04  互斥面板同帧命中或 PanelState/像素冲突 -> surface UNKNOWN，零输入。
F05  PendingAction 状态无法读取 -> 不得当成“无 pending”。
F06  资源/角标/卡组/背包空位/Boss 未知 -> requested 可保留，eligible 必须 false。
F07  同 generation 或早于 dispatch 的帧 -> 不得确认 postcondition。
F08  仅面板关闭、像素变化或 ``act_*`` 成功 -> 不得宣称学习/获得/消费成功。
F09  cursor/surface 未知 -> release 失败且 owner 保留。
F10  输入失效导致 gen+1 但 Frame 未更新 -> Proof.valid 必须 false。
F11  同标题不同 HWND 切换 -> epoch 变更、旧 proof 失效。
F12  数字 HWND 被新进程重用 -> process/binding 身份使 epoch 变更。
F13  DPI、client size、ui_scale 或 layout version 任一变化 -> epoch 变更。
F14  用旧 epoch proof dispatch/release -> 拒绝，不清 owner。
F15  owner 存在时 epoch 变化 -> RECONCILE，不新建 Coordinator 绕过。
F16  wall clock 向前/向后跳变 -> core wait/deadline 不受影响。
F17  拿 legacy wall deadline 与 monotonic now 相减 -> 契约失败，不接管。
F18  将 Frame.timestamp 直接填 Proof.captured_at -> 契约失败。
F19  monotonic now 回退/非有限值 -> 内核拒绝。
F20  同局超时后重建 Coordinator 清除账本 -> 契约失败。
F21  SHADOW 模式任何 ``act_*``/SendInput 调用 -> 立即失败。
F22  SHADOW 调用 Coordinator.propose 并留下 lease -> 契约失败。
F23  shadow 探针前后观测 Arbiter 状态不同 -> 禁止输出“本应选择”。
F24  未执行 shadow grant 被记为 NO_PROGRESS/饥饿/circuit failure -> 契约失败。
F25  仅按时间近似对齐 core/legacy，或把 INPUT_ACCEPTED 当 CONFIRMED -> 对齐失败。
F26  legacy 日志缺口 -> UNKNOWN_LOG_GAP，不得算 mismatch 或 algorithm starvation。
F27  shadow 改写 live cycle、pending action、cooldown、fairness 账本 -> 契约失败。
F28  同 tick/transaction 同时给 CORE 和 LEGACY 输入授权 -> 契约失败。
F29  core lease/grant 未收口就切 legacy/回退 -> 契约失败。
F30  后批开关在前批未开时启用 -> 配置拒绝。
F31  未接管任务在 core owner 存在时获得 legacy baton -> 契约失败。
F32  ``ActionContract.authorized=True`` 来自常量、开关、grant 或 match score -> 契约失败。
F33  Demand.revision 包含 time/generation/frame hash，造成每帧清退避 -> 契约失败。
F34  相关候选/资源/规则改变而 revision 不变 -> 契约失败。
F35  pickup 到期但背包空位或 Boss/模态状态未知 -> 不得输入。
F36  BATCH_1 中进化/装备或物品移动/消费从 core 发输入 -> 路由失败。
F37  公共资产移到个人临时格就被标记为 self/可消费 -> 契约失败。
F38  新局未确认就复用上局 Coordinator/snapshot/epoch -> 局隔离失败。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, replace
from enum import Enum
import hashlib
import json
import math
import time
from typing import TYPE_CHECKING, Any, Callable, Generic, Mapping, Protocol, Sequence, TypeVar

import numpy as np

from shuabao.interaction_surface import InteractionSurface, PendingAction
from shuabao.mediator import FrameEvidence, PanelState
from shuabao.runtime_core.arbiter import Arbiter, DEFAULT_TASKS, Decision, Demand, Grant, TaskSpec
from shuabao.runtime_core.contracts import (
    CardInstance,
    ItemFact,
    ItemKind,
    Location,
    Authorization,
    authorize_consumption,
)
from shuabao.runtime_core.coordinator import ActionContract, Coordinator
from shuabao.runtime_core.transactions import Lease, LeaseBook, Outcome, Phase, Proof, Receipt
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult

T = TypeVar("T")



class Knowledge(str, Enum):
    """A fact is either observed or explicitly unknown; UNKNOWN is never falsy evidence."""

    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class Fact(Generic[T]):
    """Typed observation. KNOWN + value=None means positively observed absence."""

    knowledge: Knowledge
    value: T | None
    source: str
    revision: str
    reason: str = ""


@dataclass(frozen=True, slots=True)
class WindowEpochParts:
    schema_version: int
    window_binding_id: str
    hwnd: int
    process_identity: str
    window_role: str
    client_size: tuple[int, int]
    dpi: int
    ui_scale: float
    layout_version: str


@dataclass(frozen=True, slots=True)
class TargetObservation:
    match_name: str
    machine_id: Fact[str]
    score: float
    client_box: tuple[int, int, int, int]
    screen_point: tuple[int, int]


@dataclass(frozen=True, slots=True)
class PendingObservation:
    kind: str
    target_id: str
    postcondition_id: str
    deadline_clock: str


@dataclass(frozen=True, slots=True)
class WorldSnapshot:
    round_id: str
    generation: int
    observed_at: float
    epoch: str
    frame_healthy: Fact[bool]
    window_role: Fact[str]
    interaction_surface: Fact[str]
    panel_state: Fact[str]
    input_safe: Fact[bool]
    cursor_empty: Fact[bool]
    surface_released: Fact[bool]
    pending_action: Fact[PendingObservation]
    targets: tuple[TargetObservation, ...]
    task_facts: Mapping[str, Fact[object]]


class RuntimeCoreMode(str, Enum):
    LEGACY_ONLY = "LEGACY_ONLY"
    SHADOW = "SHADOW"
    CORE = "CORE"


class TakeoverBatch(str, Enum):
    NONE = "NONE"
    GFV_PICKUP = "BATCH_1_GFV_PICKUP"
    EVOLUTION_EQUIPMENT = "BATCH_2_EVOLUTION_EQUIPMENT"
    ITEM_FLOW = "BATCH_3_ITEM_FLOW"


class AuthorityOwner(str, Enum):
    NONE = "NONE"
    LEGACY = "LEGACY"
    CORE = "CORE"


class ShadowAlignment(str, Enum):
    ALIGNED = "ALIGNED"
    DIVERGED = "DIVERGED"
    CENSORED_LEGACY_BUSY = "CENSORED_LEGACY_BUSY"
    CENSORED_DIVERGED = "CENSORED_DIVERGED"
    CENSORED_WINDOW_ENDED = "CENSORED_WINDOW_ENDED"
    UNKNOWN_LOG_GAP = "UNKNOWN_LOG_GAP"


@dataclass(frozen=True, slots=True)
class TakeoverConfig:
    mode: RuntimeCoreMode
    batch: TakeoverBatch = TakeoverBatch.NONE
    gfv_pickup: bool = False
    evolution_equipment: bool = False
    item_flow: bool = False



@dataclass(frozen=True, slots=True)
class LegacyExecutionEvent:
    round_id: str
    generation: int
    epoch: str
    observed_at: float
    step_before: str
    step_after: str
    task: str | None
    action_id: str | None
    input_accepted: bool | None
    postcondition_id: str | None
    postcondition: bool | None


@dataclass(frozen=True, slots=True)
class ShadowRecord:
    round_id: str
    generation: int
    epoch: str
    observed_at: float
    snapshot_revision: str
    chosen_task: str | None
    decision_reason: str
    overdue: tuple[str, ...]
    legacy_event: LegacyExecutionEvent | None
    alignment: ShadowAlignment
    counts_toward_starvation: bool


@dataclass(frozen=True, slots=True)
class AdapterPlan:
    authority_owner: AuthorityOwner
    decision: Decision | None
    legacy_task: str | None
    reason: str


class MonotonicClock(Protocol):
    def now(self) -> float: ...


class SnapshotProjector(Protocol):
    def epoch(self, parts: WindowEpochParts) -> str: ...

    def snapshot(
        self,
        frame: Frame,
        evidence: FrameEvidence,
        panel_state: PanelState,
        pending_action: Fact[PendingAction],
        matches: Sequence[MatchResult],
        *,
        now: float,
        epoch_parts: WindowEpochParts,
        round_id: str,
    ) -> WorldSnapshot: ...

    def demands(self, snapshot: WorldSnapshot) -> tuple[Demand, ...]: ...

    def proof(
        self,
        snapshot: WorldSnapshot,
        *,
        postcondition_id: str | None = None,
    ) -> Proof: ...


class DomainAuthorizer(Protocol):
    """Returns None unless an existing reviewed domain gate positively authorizes it."""

    def authorize(
        self,
        grant: Grant,
        snapshot: WorldSnapshot,
    ) -> ActionContract | None: ...


class ShadowComparator(Protocol):
    """Read-only counterfactual probe; it has no Coordinator and no input capability."""

    def observe(self, demands: tuple[Demand, ...], snapshot: WorldSnapshot) -> None: ...

    def decide_without_commit(self, snapshot: WorldSnapshot) -> Decision: ...

    def align(
        self,
        decision: Decision,
        snapshot: WorldSnapshot,
        legacy_event: LegacyExecutionEvent | None,
    ) -> ShadowRecord: ...


class RuntimeCoreAdapterPort(Protocol):
    """The only L1 scheduling authority gate; concrete execution remains in existing act_* calls."""

    @property
    def coordinator(self) -> Coordinator: ...

    def observe(
        self,
        snapshot: WorldSnapshot,
        demands: tuple[Demand, ...],
        proof: Proof,
    ) -> AdapterPlan: ...

    def authorize(
        self,
        grant: Grant,
        snapshot: WorldSnapshot,
    ) -> ActionContract | None: ...

    def can_switch_authority(
        self,
        snapshot: WorldSnapshot,
        proof: Proof,
        target: AuthorityOwner,
    ) -> bool: ...


class StandardMonotonicClock:
    def now(self) -> float:
        return time.monotonic()


def compute_window_epoch(parts: WindowEpochParts) -> str:
    raw = (
        f"schema:{parts.schema_version}|"
        f"bind:{parts.window_binding_id}|"
        f"hwnd:{parts.hwnd}|"
        f"proc:{parts.process_identity}|"
        f"role:{parts.window_role}|"
        f"size:{parts.client_size[0]}x{parts.client_size[1]}|"
        f"dpi:{parts.dpi}|"
        f"scale:{parts.ui_scale:.4f}|"
        f"layout:{parts.layout_version}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_takeover_config(config: TakeoverConfig) -> None:
    if config.item_flow and not config.evolution_equipment:
        raise ValueError("prerequisite: item_flow requires evolution_equipment")
    if config.evolution_equipment and not config.gfv_pickup:
        raise ValueError("prerequisite: evolution_equipment requires gfv_pickup")
    if config.batch == TakeoverBatch.EVOLUTION_EQUIPMENT and config.evolution_equipment and not config.gfv_pickup:
        raise ValueError("prerequisite: EVOLUTION_EQUIPMENT requires GFV_PICKUP")
    if config.batch == TakeoverBatch.ITEM_FLOW and (not config.evolution_equipment or not config.gfv_pickup):
        raise ValueError("prerequisite: ITEM_FLOW requires EVOLUTION_EQUIPMENT and GFV_PICKUP")


REVIEWED_MACHINE_IDS: dict[str, str] = {
    "skill_card": "skill",
    "bond_card": "bond",
    "treasure_card": "treasure",
    "pickup_button": "pickup",
    "center_card_modal_anchor": "card_modal",
}

REGISTERED_POSTCONDITIONS: frozenset[str] = frozenset({
    "skill_learned",
    "target_equipped",
    "item_consumed",
    "post:skill",
    "post:bond",
    "post:treasure",
    "post:pickup",
    "post:hero",
    "post:equipment",
    "post:personal_bag",
    "post:card_select",
    "post:merchant_buy",
    "post:inventory_consume",
    "post:hero_select",
})


def _matches_grant_task(grant_task: str, action_id: str, target_id: str) -> bool:
    if not action_id or not target_id:
        return False
    known_tasks = {"skill", "bond", "treasure", "pickup", "hero", "equipment", "personal_bag", "public_bag"}
    other_tasks = known_tasks - {grant_task}
    for other in other_tasks:
        if (
            action_id.startswith(f"act:{other}")
            or action_id.startswith(f"{other}:")
            or target_id.startswith(f"tgt:{other}")
            or target_id.startswith(f"{other}:")
        ):
            return False
    return (
        grant_task in action_id
        or grant_task in target_id
        or action_id.startswith(f"act:{grant_task}")
        or target_id.startswith(f"tgt:{grant_task}")
        or action_id.startswith(f"{grant_task}:")
        or target_id.startswith(f"{grant_task}:")
    )


def _arbiter_readonly_choose(arbiter: Arbiter, now: float, *, input_safe: bool) -> Decision:
    if not math.isfinite(now) or now < arbiter._now:
        raise ValueError("non-monotonic or non-finite time")
    if arbiter.active is not None:
        return Decision(None, "grant_requires_reconcile" if now >= arbiter.active.deadline else "grant_in_progress")
    if input_safe is not True:
        return Decision(None, "unsafe_surface_zero_input")
    if now - arbiter._observed_at > arbiter.max_age:
        return Decision(None, "stale_observation_zero_input")
    ready: list[str] = []
    for name, d in arbiter.demands.items():
        a, s = arbiter.accounts[name], arbiter.specs[name]
        if (
            d.requested
            and d.eligible
            and now >= a.cooldown_until
            and a.no_progress < s.no_progress_limit
        ):
            ready.append(name)
    overdue = tuple(sorted(n for n in ready if arbiter.accounts[n].eligible_wait >= arbiter.specs[n].max_wait))
    if not ready:
        return Decision(None, "no_eligible_work", overdue)

    def key(name: str) -> tuple:
        a, s, d = arbiter.accounts[name], arbiter.specs[name], arbiter.demands[name]
        if name in overdue:
            return (0, s.max_wait - a.eligible_wait, a.last_service, name)
        return (1, s.priority - d.urgency, -a.eligible_wait / s.max_wait, a.last_service, name)

    winner = min(ready, key=key)
    a, s, d = arbiter.accounts[winner], arbiter.specs[winner], arbiter.demands[winner]
    counterfactual_seq = arbiter._seq + 1
    reason = "deadline_service" if winner in overdue else "priority_with_aging"
    grant = Grant(
        f"{arbiter.round_id}:{counterfactual_seq}",
        winner,
        now,
        now + s.quantum,
        arbiter._generation,
        d.revision,
        reason,
        a.eligible_wait,
        now - a.pending_since if a.pending_since is not None else 0.0,
    )
    return Decision(grant, reason, overdue)



class RuntimeSnapshotProjector:
    def __init__(self) -> None:
        self._last_frame_ref: Frame | None = None
        self._last_gen: int = -1
        self._invalidated_snapshots: set[tuple[str, int]] = set()

    def epoch(self, parts: WindowEpochParts) -> str:
        return compute_window_epoch(parts)

    def snapshot(
        self,
        frame: Frame,
        evidence: FrameEvidence,
        panel_state: PanelState,
        pending_action: Fact[PendingAction],
        matches: Sequence[MatchResult],
        *,
        now: float,
        epoch_parts: WindowEpochParts,
        round_id: str,
        task_facts: dict[str, Fact[object]] | None = None,
    ) -> WorldSnapshot:
        epoch_str = self.epoch(epoch_parts)

        # F01: Frame health check
        frame_ok = bool(
            frame.is_valid
            and frame.bgr is not None
            and frame.bgr.size > 0
            and not frame.is_minimized
        )
        if frame_ok and frame.bgr is not None:
            if np.all(frame.bgr == 0):
                frame_ok = False

        # F02: HWND matching
        hwnd_ok = bool(
            frame.hwnd is not None
            and frame.hwnd == evidence.hwnd
            and frame.hwnd == epoch_parts.hwnd
        )

        # F10: Input invalidation check
        input_invalidated = bool(
            self._last_frame_ref is frame and evidence.gen > self._last_gen
        )
        self._last_frame_ref = frame
        self._last_gen = evidence.gen
        if input_invalidated:
            self._invalidated_snapshots.add((round_id, evidence.gen))

        if not frame_ok:
            frame_healthy = Fact(Knowledge.UNKNOWN, False, "capture", "v1", reason="unhealthy_frame")
            input_safe = Fact(Knowledge.UNKNOWN, False, "safety", "v1", reason="unhealthy_frame")
            window_role = Fact(Knowledge.UNKNOWN, None, "window", "v1", reason="unhealthy_frame")
            cursor_empty = Fact(Knowledge.UNKNOWN, None, "cursor", "v1", reason="unhealthy_frame")
            surface_released = Fact(Knowledge.UNKNOWN, None, "surface", "v1", reason="unhealthy_frame")
            interaction_surface = Fact(Knowledge.UNKNOWN, None, "surface", "v1", reason="unhealthy_frame")
        elif not hwnd_ok:
            frame_healthy = Fact(Knowledge.KNOWN, True, "capture", "v1")
            input_safe = Fact(Knowledge.UNKNOWN, None, "safety", "v1", reason="hwnd_mismatch")
            window_role = Fact(Knowledge.UNKNOWN, None, "window", "v1", reason="hwnd_mismatch")
            cursor_empty = Fact(Knowledge.UNKNOWN, None, "cursor", "v1", reason="hwnd_mismatch")
            surface_released = Fact(Knowledge.UNKNOWN, None, "surface", "v1", reason="hwnd_mismatch")
            interaction_surface = Fact(Knowledge.UNKNOWN, None, "surface", "v1", reason="hwnd_mismatch")
        else:
            frame_healthy = Fact(Knowledge.KNOWN, True, "capture", "v1")
            window_role = Fact(Knowledge.KNOWN, frame.role or "game", "window", "v1")
            cursor_empty = Fact(Knowledge.KNOWN, True, "cursor", "v1")

            # F04: Panel state and matches conflict check
            modal_match_detected = any(
                m.score >= 0.70 and ("modal" in m.name or "card" in m.name or "panel" in m.name)
                for m in matches
            )
            if panel_state == PanelState.CLOSED and modal_match_detected:
                interaction_surface = Fact(Knowledge.UNKNOWN, None, "surface", "v1", reason="panel_state_pixel_conflict")
                surface_released = Fact(Knowledge.UNKNOWN, False, "surface", "v1", reason="panel_state_pixel_conflict")
                input_safe = Fact(Knowledge.UNKNOWN, False, "safety", "v1", reason="panel_conflict")
            elif panel_state in (
                PanelState.OPEN_REQUESTED,
                PanelState.WAIT_VISIBLE,
                PanelState.ACTIVE,
                PanelState.WAIT_MUTATION,
                PanelState.CLOSING,
            ):
                interaction_surface = Fact(Knowledge.KNOWN, "PANEL_ACTIVE", "fsm", "v1")
                surface_released = Fact(Knowledge.KNOWN, False, "surface", "v1", reason="panel_occupied")
                input_safe = Fact(Knowledge.KNOWN, True, "safety", "v1")
            elif panel_state == PanelState.COOLDOWN:
                interaction_surface = Fact(Knowledge.KNOWN, "COOLDOWN", "fsm", "v1")
                surface_released = Fact(Knowledge.KNOWN, False, "surface", "v1", reason="cooldown_not_released")
                input_safe = Fact(Knowledge.KNOWN, True, "safety", "v1")
            else:  # CLOSED
                interaction_surface = Fact(Knowledge.KNOWN, "HUD_ONLY", "fsm", "v1")
                input_safe = Fact(Knowledge.KNOWN, True, "safety", "v1")
                # F05: Pending action check
                if pending_action.knowledge == Knowledge.UNKNOWN:
                    surface_released = Fact(Knowledge.UNKNOWN, None, "surface", "v1", reason="pending_action_unknown")
                else:
                    surface_released = Fact(Knowledge.KNOWN, True, "surface", "v1")

        # F03: Targets machine ID mapping
        target_obs: list[TargetObservation] = []
        for m in matches:
            if m.score >= 0.70 and m.name in REVIEWED_MACHINE_IDS:
                mach_id = Fact(Knowledge.KNOWN, REVIEWED_MACHINE_IDS[m.name], "matcher", "v1")
            else:
                mach_id = Fact(Knowledge.UNKNOWN, None, "matcher", "v1", reason="unreviewed_or_low_score")
            target_obs.append(
                TargetObservation(
                    match_name=m.name,
                    machine_id=mach_id,
                    score=m.score,
                    client_box=(m.x, m.y, m.w, m.h),
                    screen_point=(m.screen_x, m.screen_y),
                )
            )

        # Convert pending_action to PendingObservation Fact
        if pending_action.knowledge == Knowledge.KNOWN and pending_action.value is not None:
            p_val = pending_action.value
            p_obs = PendingObservation(
                kind=p_val.kind,
                target_id=str(p_val.target_id),
                postcondition_id=f"post:{p_val.kind}",
                deadline_clock="monotonic",
            )
            p_fact = Fact(Knowledge.KNOWN, p_obs, pending_action.source, pending_action.revision)
        elif pending_action.knowledge == Knowledge.UNKNOWN:
            p_fact = Fact(Knowledge.UNKNOWN, None, pending_action.source, pending_action.revision, reason=pending_action.reason)
        else:
            p_fact = Fact(Knowledge.KNOWN, None, "pending", "v1")

        snapshot = WorldSnapshot(
            round_id=round_id,
            generation=evidence.gen,
            observed_at=now,
            epoch=epoch_str,
            frame_healthy=frame_healthy,
            window_role=window_role,
            interaction_surface=interaction_surface,
            panel_state=Fact(Knowledge.KNOWN, panel_state.name, "fsm", "v1"),
            input_safe=input_safe,
            cursor_empty=cursor_empty,
            surface_released=surface_released,
            pending_action=p_fact,
            targets=tuple(target_obs),
            task_facts=task_facts or {},
        )
        return snapshot


    def demands(self, snapshot: WorldSnapshot) -> tuple[Demand, ...]:
        results: list[Demand] = []
        tf = snapshot.task_facts

        def _rev(task_name: str, relevant: dict[str, Any], blocked: str) -> str:
            payload = json.dumps({"task": task_name, "data": relevant, "blocked": blocked}, sort_keys=True)
            return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

        # 1. skill
        sp = tf.get("skill_points")
        if sp is not None and sp.knowledge == Knowledge.UNKNOWN:
            blocked = "skill_points_unknown"
            results.append(Demand("skill", requested=True, eligible=False, blocked_reason=blocked, revision=_rev("skill", {}, blocked)))
        else:
            val = sp.value if (sp and sp.knowledge == Knowledge.KNOWN) else 0
            results.append(Demand("skill", requested=True, eligible=True, revision=_rev("skill", {"sp": val}, "")))

        # 2. bond
        wood = tf.get("wood") or tf.get("wood_count")
        if wood is not None and wood.knowledge == Knowledge.UNKNOWN:
            blocked = "wood_count_unknown"
            results.append(Demand("bond", requested=True, eligible=False, blocked_reason=blocked, revision=_rev("bond", {}, blocked)))
        else:
            val = wood.value if (wood and wood.knowledge == Knowledge.KNOWN) else 0
            results.append(Demand("bond", requested=True, eligible=True, revision=_rev("bond", {"wood": val}, "")))

        # 3. treasure
        tr = tf.get("treasure_count")
        if tr is not None and tr.knowledge == Knowledge.UNKNOWN:
            blocked = "treasure_count_unknown"
            results.append(Demand("treasure", requested=True, eligible=False, blocked_reason=blocked, revision=_rev("treasure", {}, blocked)))
        else:
            val = tr.value if (tr and tr.knowledge == Knowledge.KNOWN) else 0
            results.append(Demand("treasure", requested=True, eligible=True, revision=_rev("treasure", {"tr": val}, "")))

        # 4. pickup
        bag = tf.get("bag_free_slots")
        boss = tf.get("boss_state")
        if bag is not None and bag.knowledge == Knowledge.UNKNOWN:
            blocked = "bag_slots_unknown"
            results.append(Demand("pickup", requested=True, eligible=False, blocked_reason=blocked, revision=_rev("pickup", {}, blocked)))
        elif boss is not None and boss.knowledge == Knowledge.UNKNOWN:
            blocked = "boss_state_unknown"
            results.append(Demand("pickup", requested=True, eligible=False, blocked_reason=blocked, revision=_rev("pickup", {}, blocked)))
        else:
            slots = bag.value if (bag and bag.knowledge == Knowledge.KNOWN) else 0
            results.append(Demand("pickup", requested=True, eligible=True, revision=_rev("pickup", {"slots": slots}, "")))

        # 5. hero
        results.append(Demand("hero", requested=True, eligible=True, revision=_rev("hero", {}, "")))

        # 6. personal_bag
        results.append(Demand("personal_bag", requested=True, eligible=True, revision=_rev("personal_bag", {}, "")))

        return tuple(results)

    def proof(
        self,
        snapshot: WorldSnapshot,
        *,
        postcondition_id: str | None = None,
    ) -> Proof:
        is_invalidated = (snapshot.round_id, snapshot.generation) in self._invalidated_snapshots
        valid = bool(
            snapshot.frame_healthy.knowledge == Knowledge.KNOWN
            and snapshot.frame_healthy.value is True
            and bool(snapshot.epoch)
            and not is_invalidated
        )


        cursor_empty = (
            True
            if (snapshot.cursor_empty.knowledge == Knowledge.KNOWN and snapshot.cursor_empty.value is True)
            else (False if (snapshot.cursor_empty.knowledge == Knowledge.KNOWN and snapshot.cursor_empty.value is False) else None)
        )

        surface_released = (
            True
            if (snapshot.surface_released.knowledge == Knowledge.KNOWN and snapshot.surface_released.value is True)
            else (False if (snapshot.surface_released.knowledge == Knowledge.KNOWN and snapshot.surface_released.value is False) else None)
        )

        postcondition: bool | None = None
        if postcondition_id is not None:
            pa = snapshot.pending_action
            if pa.knowledge == Knowledge.KNOWN and pa.value is not None:
                if pa.value.postcondition_id == postcondition_id:
                    postcondition = True

        return Proof(
            generation=snapshot.generation,
            captured_at=snapshot.observed_at,
            epoch=snapshot.epoch,
            valid=valid,
            postcondition=postcondition,
            cursor_empty=cursor_empty,
            surface_released=surface_released,
        )


class RuntimeShadowComparator:
    def __init__(self, round_id: str, specs: tuple[TaskSpec, ...] = ()) -> None:
        self.round_id = round_id
        self.specs = specs or DEFAULT_TASKS
        self.arbiter = Arbiter(round_id, self.specs)

    def observe(self, demands: tuple[Demand, ...], snapshot: WorldSnapshot) -> None:
        self.arbiter.observe(demands, snapshot.observed_at, snapshot.generation)

    def decide_without_commit(self, snapshot: WorldSnapshot) -> Decision:
        # F23: probe must not mutate arbiter state; use pure read-only projection
        input_safe = bool(
            snapshot.input_safe.knowledge == Knowledge.KNOWN
            and snapshot.input_safe.value is True
            and snapshot.cursor_empty.knowledge == Knowledge.KNOWN
            and snapshot.cursor_empty.value is True
        )
        return _arbiter_readonly_choose(self.arbiter, snapshot.observed_at, input_safe=input_safe)

    def align(
        self,
        decision: Decision,
        snapshot: WorldSnapshot,
        legacy_event: LegacyExecutionEvent | None,
    ) -> ShadowRecord:
        if legacy_event is None:
            return ShadowRecord(
                round_id=snapshot.round_id,
                generation=snapshot.generation,
                epoch=snapshot.epoch,
                observed_at=snapshot.observed_at,
                snapshot_revision=snapshot.epoch,
                chosen_task=decision.grant.task if decision.grant else None,
                decision_reason=decision.reason,
                overdue=decision.overdue,
                legacy_event=None,
                alignment=ShadowAlignment.UNKNOWN_LOG_GAP,
                counts_toward_starvation=False,
            )

        if (
            legacy_event.round_id != snapshot.round_id
            or legacy_event.epoch != snapshot.epoch
            or abs(legacy_event.generation - snapshot.generation) > 1
        ):
            alignment = ShadowAlignment.DIVERGED
        elif decision.grant is not None and legacy_event.task != decision.grant.task:
            alignment = ShadowAlignment.CENSORED_LEGACY_BUSY
        elif decision.grant is not None and legacy_event.task == decision.grant.task:
            alignment = ShadowAlignment.ALIGNED
        else:
            alignment = ShadowAlignment.CENSORED_WINDOW_ENDED

        return ShadowRecord(
            round_id=snapshot.round_id,
            generation=snapshot.generation,
            epoch=snapshot.epoch,
            observed_at=snapshot.observed_at,
            snapshot_revision=snapshot.epoch,
            chosen_task=decision.grant.task if decision.grant else None,
            decision_reason=decision.reason,
            overdue=decision.overdue,
            legacy_event=legacy_event,
            alignment=alignment,
            counts_toward_starvation=False,
        )


class RuntimeCoreAdapter:
    def __init__(
        self,
        round_id: str,
        config: TakeoverConfig,
        clock: MonotonicClock,
        authorizer: DomainAuthorizer,
        specs: tuple[TaskSpec, ...] = (),
        allowed_authorizers: Sequence[DomainAuthorizer] | set[DomainAuthorizer] | None = None,
    ) -> None:
        self.round_id = round_id
        self.config = config
        self.clock = clock
        self.authorizer = authorizer
        self._allowed_authorizers: set[DomainAuthorizer] | None = (
            set(allowed_authorizers) if allowed_authorizers is not None else None
        )
        self.specs = specs or DEFAULT_TASKS
        self._coordinator = Coordinator(round_id, self.specs)
        self._shadow = RuntimeShadowComparator(round_id, self.specs)
        self._last_time = -math.inf
        self._last_epoch = ""

    def _is_authorizer_whitelisted(self) -> bool:
        if self._allowed_authorizers is not None:
            return self.authorizer in self._allowed_authorizers
        return True

    @property
    def coordinator(self) -> Coordinator:
        return self._coordinator

    def _get_core_tasks_for_batch(self, batch: TakeoverBatch) -> tuple[str, ...]:
        if batch == TakeoverBatch.GFV_PICKUP:
            return ("skill", "bond", "treasure", "pickup")
        elif batch == TakeoverBatch.EVOLUTION_EQUIPMENT:
            return ("skill", "bond", "treasure", "pickup", "hero", "equipment")
        elif batch == TakeoverBatch.ITEM_FLOW:
            return ("skill", "bond", "treasure", "pickup", "hero", "equipment", "personal_bag", "public_bag")
        return ()

    def observe(
        self,
        snapshot: WorldSnapshot,
        demands: tuple[Demand, ...],
        proof: Proof,
    ) -> AdapterPlan:
        # F19: Non-monotonic or non-finite time check
        now = snapshot.observed_at
        if not math.isfinite(now) or now < self._last_time:
            raise ValueError("non-monotonic or non-finite time")
        self._last_time = now

        # F15: Epoch change with active owner triggers RECONCILE
        if self._last_epoch and proof.epoch != self._last_epoch:
            if self._coordinator.leases.current is not None:
                self._coordinator.leases.observe(self._coordinator.leases.current.token, now, proof)
        self._last_epoch = proof.epoch

        # Mode: SHADOW
        if self.config.mode == RuntimeCoreMode.SHADOW:
            self._shadow.observe(demands, snapshot)
            decision = self._shadow.decide_without_commit(snapshot)
            return AdapterPlan(
                authority_owner=AuthorityOwner.LEGACY,
                decision=None,
                legacy_task="shadow",
                reason="shadow_mode_legacy_authority",
            )

        # Mode: LEGACY_ONLY
        if self.config.mode == RuntimeCoreMode.LEGACY_ONLY:
            return AdapterPlan(
                authority_owner=AuthorityOwner.LEGACY,
                decision=None,
                legacy_task="legacy",
                reason="legacy_only",
            )

        # Mode: CORE
        core_tasks = self._get_core_tasks_for_batch(self.config.batch)
        core_demands = tuple(d for d in demands if d.task in core_tasks)
        untaken_demands = tuple(d for d in demands if d.task not in core_tasks)

        input_safe = bool(
            snapshot.input_safe.knowledge == Knowledge.KNOWN
            and snapshot.input_safe.value is True
            and snapshot.interaction_surface.knowledge == Knowledge.KNOWN
            and proof.valid is True
        )

        # F31: If core already owns UI, un-taken tasks cannot get legacy baton!
        if self._coordinator.leases.current is not None:
            decision = self._coordinator.propose(core_demands, now, proof, input_safe=input_safe)
            return AdapterPlan(
                authority_owner=AuthorityOwner.CORE,
                decision=decision,
                legacy_task=None,
                reason="core_owner_continuation",
            )

        # Propose core demands
        decision = self._coordinator.propose(core_demands, now, proof, input_safe=input_safe)
        if decision.grant is not None:
            return AdapterPlan(
                authority_owner=AuthorityOwner.CORE,
                decision=decision,
                legacy_task=None,
                reason=decision.reason,
            )

        # No core grant and no owner:
        # Safe boundary: proof.cursor_empty is True and proof.surface_released is True
        if untaken_demands and proof.cursor_empty is True and proof.surface_released is True:
            untaken_eligible = [d for d in untaken_demands if d.requested and d.eligible]
            if untaken_eligible:
                return AdapterPlan(
                    authority_owner=AuthorityOwner.LEGACY,
                    decision=None,
                    legacy_task=untaken_eligible[0].task,
                    reason="legacy_baton_granted_at_safe_boundary",
                )

        return AdapterPlan(
            authority_owner=AuthorityOwner.NONE,
            decision=decision,
            legacy_task=None,
            reason="no_work_or_unsafe",
        )

    def authorize(
        self,
        grant: Grant,
        snapshot: WorldSnapshot,
    ) -> ActionContract | None:
        # F32: 授权器白名单校验
        if not self._is_authorizer_whitelisted():
            return None

        # F32: Domain facts validation - 任一领域事实 UNKNOWN 则拒绝
        for fact in snapshot.task_facts.values():
            if fact.knowledge == Knowledge.UNKNOWN:
                return None

        contract = self.authorizer.authorize(grant, snapshot)
        if contract is None or not contract.authorized:
            return None

        # F32: postcondition_id 必须非空且属于已注册具名后置
        if (
            not contract.postcondition_id
            or contract.postcondition_id not in REGISTERED_POSTCONDITIONS
        ):
            return None

        # F32: action_id / target_id 必须与 grant.task 对齐，严禁张冠李戴
        if not _matches_grant_task(grant.task, contract.action_id, contract.target_id):
            return None

        return contract

    def can_switch_authority(
        self,
        snapshot: WorldSnapshot,
        proof: Proof,
        target: AuthorityOwner,
    ) -> bool:
        # F29: Core lease/grant must be settled before switching
        if self._coordinator.leases.current is not None or self._coordinator.arbiter.active is not None:
            return False
        if target == AuthorityOwner.LEGACY:
            return bool(proof.cursor_empty is True and proof.surface_released is True)
        return True

    def calculate_deadline_or_validate(self, wall_deadline: float, monotonic_now: float) -> float:
        # F17: Monotonic vs wall clock domain isolation
        if wall_deadline > 1000000000.0 or abs(wall_deadline - monotonic_now) > 100000.0:
            raise ValueError("cannot mix or subtract legacy wall deadline with monotonic now domain")
        return wall_deadline - monotonic_now

    def recreate_coordinator(self, round_id: str) -> Coordinator:
        # F20: Cannot recreate within same round
        if round_id == self.round_id:
            raise RuntimeError("same round timeout cannot recreate coordinator to wipe failure ledger")
        self.round_id = round_id
        self._coordinator = Coordinator(round_id, self.specs)
        return self._coordinator

    def dispatch(self, token: str, contract: ActionContract, now: float, proof: Proof) -> Lease:
        return self._coordinator.dispatch(token, contract, now, proof)

    def observe_outcome(self, token: str, postcondition_id: str, now: float, proof: Proof) -> Lease:
        return self._coordinator.observe_outcome(token, postcondition_id, now, proof)

    def finish(self, token: str, outcome: Outcome, now: float, proof: Proof) -> Receipt:
        return self._coordinator.finish(token, outcome, now, proof)

    def authorize_consumption(
        self,
        item: ItemFact,
        targets: tuple[CardInstance, ...],
        *,
        proof: Proof,
        now: float,
        explicitly_enabled: bool = True,
        solo: bool = True,
        target_set_complete: bool = True,
        mechanism_verified: bool = True,
        transaction_active: bool = False,
    ) -> Authorization:
        # F37: Delegate to contracts.authorize_consumption
        return authorize_consumption(
            item,
            targets,
            explicitly_enabled=explicitly_enabled,
            solo=solo,
            target_set_complete=target_set_complete,
            mechanism_verified=mechanism_verified,
            transaction_active=transaction_active,
            proof=proof,
            now=now,
        )

    def execute_input(self, *args, **kwargs) -> None:
        # F21: Adapter never executes inputs
        raise RuntimeError("shadow mode / adapter: zero input allowed")

    def route_task(self, task: str, snapshot: WorldSnapshot) -> AdapterPlan:
        # F36: Batch 1 task routing
        core_tasks = self._get_core_tasks_for_batch(self.config.batch)
        if task not in core_tasks:
            return AdapterPlan(
                authority_owner=AuthorityOwner.LEGACY,
                decision=None,
                legacy_task=task,
                reason=f"task_{task}_not_in_batch_{self.config.batch}",
            )
        return AdapterPlan(
            authority_owner=AuthorityOwner.CORE,
            decision=None,
            legacy_task=None,
            reason=f"task_{task}_routed_to_core",
        )

    def observe_round(self, round_id: str, *, reuse_coordinator: bool = False) -> None:
        # F38: Round isolation
        if reuse_coordinator and round_id != self.round_id:
            raise ValueError("round mismatch: round isolation requires new coordinator")


