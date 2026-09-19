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

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Generic, Mapping, Protocol, Sequence, TypeVar

if TYPE_CHECKING:
    from shuabao.interaction_surface import PendingAction
    from shuabao.mediator import FrameEvidence, PanelState
    from shuabao.runtime_core.arbiter import Decision, Demand, Grant
    from shuabao.runtime_core.coordinator import ActionContract, Coordinator
    from shuabao.runtime_core.transactions import Proof
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
    batch: TakeoverBatch


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
