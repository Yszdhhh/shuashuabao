"""单人动态调度影子决策器：纯函数，只依赖标准库。

语义唯一来源：``DYNAMIC_SOLO_ARCHITECTURE_V1.md`` §11。
线上动作 0 影响：本模块不读盘/不联网/不 OCR/不发输入/不读隐式时间。
相同快照 → 相同 Decision。

三类事实（§11.1）不得混用：observed / requested / confirmed。
未知永远不填 0；不同币种不换算；UNKNOWN_PRICE 不填 0。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Sequence

FACT_OBSERVED = "observed"
FACT_UNKNOWN = "unknown"
FACT_MISSING = "missing"
FACT_INVALID = "invalid"
FACT_STATES = (FACT_OBSERVED, FACT_UNKNOWN, FACT_MISSING, FACT_INVALID)

ACTION_OBSERVED = "observed"
ACTION_REQUESTED = "requested"
ACTION_CONFIRMED = "confirmed"
ACTION_STATES = (ACTION_OBSERVED, ACTION_REQUESTED, ACTION_CONFIRMED)

KIND_CONTINUE = "CONTINUE_TRANSACTION"
KIND_RECOMMEND = "RECOMMEND"
KIND_WAIT_OR_OBSERVE = "WAIT_OR_OBSERVE"

CAND_READ = "READ_EXISTING_PANEL"
CAND_DRAW = "PAID_DRAW"
CAND_REFRESH = "PAID_REFRESH"
CAND_CONSUME = "PAID_CONSUME"

# §11.4：UNKNOWN_PRICE 不填 0，用哨兵字符串贯穿成本链。
UNKNOWN_PRICE = "UNKNOWN_PRICE"


@dataclass(frozen=True)
class Fact:
    """带状态与出处的单点事实。unknown/missing/invalid 永不被当成 0。"""

    value: Any
    state: str = FACT_OBSERVED
    source: str = ""
    observed_at: float | None = None

    def __post_init__(self) -> None:
        if self.state not in FACT_STATES:
            object.__setattr__(self, "state", FACT_UNKNOWN)

    @property
    def ok(self) -> bool:
        return self.state == FACT_OBSERVED

    @property
    def known_num(self) -> float | None:
        if self.state != FACT_OBSERVED:
            return None
        v = self.value
        if isinstance(v, bool):
            return None
        if isinstance(v, (int, float)):
            return float(v)
        return None

    @property
    def price_known(self) -> bool:
        return self.state == FACT_OBSERVED and self.value != UNKNOWN_PRICE and isinstance(self.value, (int, float)) and not isinstance(self.value, bool)

    @classmethod
    def observed(cls, value: Any, source: str = "", observed_at: float | None = None) -> "Fact":
        return cls(value=value, state=FACT_OBSERVED, source=source, observed_at=observed_at)

    @classmethod
    def unknown(cls, source: str = "") -> "Fact":
        return cls(value=None, state=FACT_UNKNOWN, source=source)

    @classmethod
    def missing(cls, source: str = "") -> "Fact":
        return cls(value=None, state=FACT_MISSING, source=source)

    @classmethod
    def invalid(cls, source: str = "") -> "Fact":
        return cls(value=None, state=FACT_INVALID, source=source)


@dataclass(frozen=True)
class ActionRecord:
    """动作流水。只有 confirmed 能推进持有/已购/已进化账目（§11.1）。"""

    action_id: str
    state: str = ACTION_REQUESTED
    detail: str = ""

    def __post_init__(self) -> None:
        if self.state not in ACTION_STATES:
            object.__setattr__(self, "state", ACTION_REQUESTED)

    @property
    def advances_ledger(self) -> bool:
        return self.state == ACTION_CONFIRMED


@dataclass(frozen=True)
class Cost:
    """某一币种成本。amount 为 UNKNOWN_PRICE 时不可授权消费。"""

    currency: str
    amount: Any
    model_derived: bool = False
    note: str = ""

    @property
    def price_known(self) -> bool:
        return self.amount != UNKNOWN_PRICE and isinstance(self.amount, (int, float)) and not isinstance(self.amount, bool)


@dataclass(frozen=True)
class Candidate:
    """决策资料候选（§11.2），不是第二套执行器。"""

    action_id: str
    target: str
    kind: str
    legal: bool
    reject_reason: str
    fact_refs: tuple[str, ...]
    costs: tuple[Cost, ...]
    expected_cash_in: str
    bottleneck: str
    executor: str
    confirm_ref: str
    goal: str
    # 支配比较用的序数：cash_in_rank 越小兑现越早；evidence_rank 越大证据越强。
    cash_in_rank: int = 2
    evidence_rank: int = 1
    # 反饿死：距上次被服务的秒数（仅 observed 时有意义）。
    service_wait_s: float | None = None
    # 同币种成本合计的可比较值；跨币种绝不汇总。
    notes: str = ""

    def cost_of(self, currency: str) -> Cost | None:
        for c in self.costs:
            if c.currency == currency:
                return c
        return None


@dataclass(frozen=True)
class OwnerConfig:
    """Owner 配置约束。只约束边界，不注入新阈值。"""

    auto_bond: bool = True
    auto_treasure: bool = True
    auto_devour_dan: bool = False
    treasure_allow_negative: tuple[str, ...] = ()
    treasure_negative_names: tuple[str, ...] = ()
    treasure_negative_patterns: tuple[str, ...] = ()
    # 已验证目标偏好（保序）。空 = 不提供偏好锚。
    goal_preference: tuple[str, ...] = ()
    # 当前有效链（§11.3E：不可比时保持）。
    current_chain: str = ""


@dataclass(frozen=True)
class Snapshot:
    """本局观测快照 + Owner 煍置 + now。时间只从这里来。"""

    now: float
    round_id: str = ""
    # --- EVIDENCE 可用信号 ---
    wood: Fact = field(default_factory=lambda: Fact.unknown("wood"))
    skill_badge: Fact = field(default_factory=lambda: Fact.unknown("skill_badge"))
    treasure_badge: Fact = field(default_factory=lambda: Fact.unknown("treasure_badge"))
    confirmed_bond_cards: Fact = field(default_factory=lambda: Fact.missing("confirmed_bond_cards"))
    confirmed_skill_cards: Fact = field(default_factory=lambda: Fact.missing("confirmed_skill_cards"))
    pending_records: tuple[ActionRecord, ...] = ()
    evolution_locked: Fact = field(default_factory=lambda: Fact.unknown("evolution_locked"))
    active_transaction: Fact = field(default_factory=lambda: Fact.unknown("active_transaction"))
    panel_state: Fact = field(default_factory=lambda: Fact.unknown("panel_state"))
    swallow_guard_allows: Fact = field(default_factory=lambda: Fact.unknown("swallow_guard_allows"))
    # 不可授权动作信号（只记录，不驱动消费）
    main_line_stage: Fact = field(default_factory=lambda: Fact.unknown("main_line_stage"))
    failure_event: Fact = field(default_factory=lambda: Fact.unknown("failure_event"))
    tab_window: Fact = field(default_factory=lambda: Fact.unknown("tab_window"))
    artifact_ready: Fact = field(default_factory=lambda: Fact.unknown("artifact_ready"))
    merchant_kill_balance: Fact = field(default_factory=lambda: Fact.unknown("merchant_kill_balance"))
    # 跨页/跨局失效标记
    page_generation: Fact = field(default_factory=lambda: Fact.unknown("page_generation"))
    round_generation: Fact = field(default_factory=lambda: Fact.unknown("round_generation"))
    # 反饿死：各 kind 距上次服务秒数
    service_wait_skill: Fact = field(default_factory=lambda: Fact.unknown("service_wait_skill"))
    service_wait_bond: Fact = field(default_factory=lambda: Fact.unknown("service_wait_bond"))
    service_wait_treasure: Fact = field(default_factory=lambda: Fact.unknown("service_wait_treasure"))
    # 已展示商品/卡价格（若无则候选用 UNKNOWN_PRICE）
    bond_draw_price: Fact = field(default_factory=lambda: Fact.unknown("bond_draw_price"))
    bond_refresh_price: Fact = field(default_factory=lambda: Fact.unknown("bond_refresh_price"))
    merchant_pill_price: Fact = field(default_factory=lambda: Fact.unknown("merchant_pill_price"))
    merchant_wood_price: Fact = field(default_factory=lambda: Fact.unknown("merchant_wood_price"))
    merchant_refresh_price: Fact = field(default_factory=lambda: Fact.unknown("merchant_refresh_price"))
    # 安全读取入口（零成本/既有 OCR，不发起新识别）
    safe_observe_entries: tuple[str, ...] = ()
    owner: OwnerConfig = field(default_factory=OwnerConfig)
    # 额外：已展示的合法卡（可支付判定用）
    shown_card_price: Fact = field(default_factory=lambda: Fact.unknown("shown_card_price"))
    shown_card_id: Fact = field(default_factory=lambda: Fact.unknown("shown_card_id"))


@dataclass(frozen=True)
class Decision:
    kind: str
    chosen: Candidate | None = None
    alternatives: tuple[tuple[str, str], ...] = ()
    incomparable: tuple[str, ...] = ()
    review_required: tuple[str, ...] = ()
    observe_gaps: tuple[str, ...] = ()
    safe_entries: tuple[str, ...] = ()
    notes: str = ""


# ---------------------------------------------------------------------------
# 内部：合法性 / 支配 / 饿死
# ---------------------------------------------------------------------------


def _fact_ok(f: Fact) -> bool:
    return f is not None and f.state == FACT_OBSERVED


def _num(f: Fact) -> float | None:
    return f.known_num


def _paid_legal(costs: Sequence[Cost], balances: Mapping[str, Fact], *, spend_id: str) -> tuple[bool, str]:
    """§11.3B：消费类余额/价格不可信 → 不授权该消费。未知 ≠ 0。"""
    for cost in costs:
        bal = balances.get(cost.currency)
        if bal is None or not _fact_ok(bal):
            return False, "BALANCE_UNKNOWN"
        if not cost.price_known:
            return False, "UNKNOWN_PRICE"
        bal_v = _num(bal)
        if bal_v is None:
            return False, "BALANCE_UNKNOWN"
        if bal_v < float(cost.amount):
            return False, "INSUFFICIENT_BALANCE"
    return True, ""


def _dominates(a: Candidate, b: Candidate) -> bool:
    """§11.3D：A 支配 B 当且仅当全部维度不更差且至少一项明确更好。

    未知维度不算更好；不同币种不换算（要求双方币种集合一致才比成本）。
    """
    if a.goal != b.goal:
        return False
    if {c.currency for c in a.costs} != {c.currency for c in b.costs}:
        return False
    better = False
    for cur in {c.currency for c in a.costs} | {c.currency for c in b.costs}:
        ca, cb = a.cost_of(cur), b.cost_of(cur)
        # 缺失一侧成本视为未知 → 不能证明支配
        if ca is None or cb is None or not ca.price_known or not cb.price_known:
            return False
        if float(ca.amount) > float(cb.amount):
            return False
        if float(ca.amount) < float(cb.amount):
            better = True
    if a.evidence_rank < b.evidence_rank:
        return False
    if a.evidence_rank > b.evidence_rank:
        better = True
    if a.cash_in_rank > b.cash_in_rank:
        return False
    if a.cash_in_rank < b.cash_in_rank:
        better = True
    return better


def _balances(snap: Snapshot) -> dict[str, Fact]:
    return {
        "wood": snap.wood,
        "kill": snap.merchant_kill_balance,
        "gold": Fact.unknown("gold"),
    }


def _build_candidates(snap: Snapshot) -> list[Candidate]:
    """从快照事实构造候选。不发明展示之外的价格；UNKNOWN_PRICE 不填 0。"""
    bal = _balances(snap)
    cands: list[Candidate] = []

    # --- 已展示合法卡（若有）：仅余额可比即合法，禁止“余额档位”排除 ---
    if snap.shown_card_price.price_known and snap.shown_card_id.ok:
        price = float(snap.shown_card_price.value)
        legal, reason = _paid_legal(
            [Cost("wood", price, model_derived=bool(snap.shown_card_price.source.startswith("model")))],
            bal,
            spend_id="shown_card",
        )
        # 额外：木材档位（如 300）不得单独排除（§11.6 行 4）
        cands.append(Candidate(
            action_id=f"take_card:{snap.shown_card_id.value}",
            target=str(snap.shown_card_id.value),
            kind=CAND_READ if price == 0 else CAND_DRAW,
            legal=legal,
            reject_reason=reason,
            fact_refs=("shown_card_price", "shown_card_id", "wood"),
            costs=(Cost("wood", price, model_derived=False),),
            expected_cash_in="confirmed_card_ledger",
            bottleneck="card_slot",
            executor="choice_policy",
            confirm_ref="WAIT_MUTATION",
            goal="acquire_card",
            cash_in_rank=1,
            evidence_rank=2,
        ))

    # --- G 技能：READ_EXISTING_PANEL（角标 0=无待处理；未知仍可读取） ---
    skill_n = _num(snap.skill_badge)
    if snap.skill_badge.ok and skill_n == 0:
        pass
    else:
        wait = _num(snap.service_wait_skill)
        cands.append(Candidate(
            action_id="open_skill_panel",
            target="skill",
            kind=CAND_READ,
            legal=True,
            reject_reason="",
            fact_refs=("skill_badge",),
            costs=(),
            expected_cash_in="confirmed_skill_ledger",
            bottleneck="skill_backlog",
            executor="mediator.skill_panel",
            confirm_ref="WAIT_MUTATION",
            goal="spend_skill_points",
            cash_in_rank=1,
            evidence_rank=2 if (snap.skill_badge.ok and (skill_n or 0) > 0) else 1,
            service_wait_s=wait,
        ))

    # --- V 宝物：READ_EXISTING_PANEL ---
    tre_n = _num(snap.treasure_badge)
    if snap.treasure_badge.ok and tre_n == 0:
        pass
    else:
        wait = _num(snap.service_wait_treasure)
        cands.append(Candidate(
            action_id="open_treasure_panel",
            target="treasure",
            kind=CAND_READ,
            legal=bool(snap.owner.auto_treasure),
            reject_reason="" if snap.owner.auto_treasure else "OWNER_DISABLED",
            fact_refs=("treasure_badge", "treasure_allow_negative"),
            costs=(),
            expected_cash_in="confirmed_treasure_ledger",
            bottleneck="treasure_pending",
            executor="mediator.treasure_panel",
            confirm_ref="WAIT_MUTATION",
            goal="claim_treasure",
            cash_in_rank=1,
            evidence_rank=2 if (snap.treasure_badge.ok and (tre_n or 0) > 0) else 1,
            service_wait_s=wait,
        ))

    # --- F 抽卡 / 刷新：木材计价；价格未知则不可授权 ---
    draw_price = snap.bond_draw_price
    refresh_price = snap.bond_refresh_price
    draw_amt = float(draw_price.value) if draw_price.price_known else UNKNOWN_PRICE
    refresh_amt = float(refresh_price.value) if refresh_price.price_known else UNKNOWN_PRICE
    wait_bond = _num(snap.service_wait_bond)

    draw_legal, draw_reason = _paid_legal(
        [Cost("wood", draw_amt, model_derived=True, note="model:_bond_next_price")], bal, spend_id="bond_draw"
    ) if snap.owner.auto_bond else (False, "OWNER_DISABLED")
    cands.append(Candidate(
        action_id="bond_draw",
        target="bond",
        kind=CAND_DRAW,
        legal=draw_legal,
        reject_reason=draw_reason,
        fact_refs=("wood", "bond_draw_price"),
        costs=(Cost("wood", draw_amt, model_derived=True, note="model:_bond_next_price"),),
        expected_cash_in="confirmed_bond_ledger",
        bottleneck="bond_progress",
        executor="mediator.bond_draw",
        confirm_ref="WAIT_MUTATION",
        goal="progress_bond",
        cash_in_rank=2,
        evidence_rank=1,
        service_wait_s=wait_bond,
    ))

    # 刷新链：刷新可付但目标买不起 → 不推荐刷新（§11.6 行 7）
    refresh_legal, refresh_reason = (False, "OWNER_DISABLED")
    if snap.owner.auto_bond:
        refresh_legal, refresh_reason = _paid_legal(
            [Cost("wood", refresh_amt, model_derived=True, note="model:_bond_refresh_price")],
            bal, spend_id="bond_refresh",
        )
        if refresh_legal and draw_price.price_known and refresh_price.price_known and _fact_ok(snap.wood):
            wood_v = _num(snap.wood)
            if wood_v is not None and wood_v < float(refresh_amt) + float(draw_amt):
                refresh_legal = False
                refresh_reason = "TARGET_UNAFFORDABLE"
    cands.append(Candidate(
        action_id="bond_refresh",
        target="bond",
        kind=CAND_REFRESH,
        legal=refresh_legal,
        reject_reason=refresh_reason,
        fact_refs=("wood", "bond_refresh_price", "bond_draw_price"),
        costs=(Cost("wood", refresh_amt, model_derived=True, note="model:_bond_refresh_price"),),
        expected_cash_in="new_offered_cards",
        bottleneck="bond_stale_offers",
        executor="mediator.bond_refresh",
        confirm_ref="WAIT_MUTATION",
        goal="progress_bond",
        cash_in_rank=3,
        evidence_rank=1,
        service_wait_s=wait_bond,
    ))

    # --- 吞噬丹：守卫恒 False → 排除消费（§11.6 行 11） ---
    guard_ok = snap.swallow_guard_allows.ok and bool(snap.swallow_guard_allows.value)
    cands.append(Candidate(
        action_id="consume_swallow_pill",
        target="swallow_pill",
        kind=CAND_CONSUME,
        legal=guard_ok,
        reject_reason="" if guard_ok else "GUARD_CLOSED",
        fact_refs=("swallow_guard_allows",),
        costs=(),
        expected_cash_in="swallow_effect_unknown",
        bottleneck="unknown",
        executor="mediator.devour_dan",
        confirm_ref="WAIT_SWALLOW_PILL_CONFIRM",
        goal="use_pill",
        evidence_rank=0,
    ))

    # --- 黑商：余额不可读 → 消费 legal=False（G8 / §11.3B） ---
    for item, price_fact, pid in (
        ("merchant_buy_pill", snap.merchant_pill_price, "merchant_buy_pill"),
        ("merchant_buy_wood", snap.merchant_wood_price, "merchant_buy_wood"),
        ("merchant_refresh", snap.merchant_refresh_price, "merchant_refresh"),
    ):
        amt = float(price_fact.value) if price_fact.price_known else UNKNOWN_PRICE
        legal, reason = _paid_legal(
            [Cost("kill", amt, model_derived=True, note="model:code_price")], bal, spend_id=pid
        )
        # 刷新后买不起目标 → 不推荐刷新链
        if legal and item == "merchant_refresh" and price_fact.price_known and snap.merchant_pill_price.price_known:
            bal_kill = _num(snap.merchant_kill_balance)
            if bal_kill is not None and bal_kill < float(price_fact.value) + float(snap.merchant_pill_price.value):
                legal = False
                reason = "TARGET_UNAFFORDABLE"
        cands.append(Candidate(
            action_id=item,
            target=item,
            kind=CAND_REFRESH if item == "merchant_refresh" else CAND_CONSUME,
            legal=legal,
            reject_reason=reason,
            fact_refs=("merchant_kill_balance",),
            costs=(Cost("kill", amt, model_derived=True, note="model:code_price"),),
            expected_cash_in="merchant_goods",
            bottleneck="merchant_stock",
            executor="mediator.merchant",
            confirm_ref="merchant_fsm.VERIFYING",
            goal="merchant_spend",
            cash_in_rank=2,
            evidence_rank=1,
        ))

    return cands


def _in_txn(snap: Snapshot) -> bool:
    if snap.active_transaction.ok and bool(snap.active_transaction.value):
        return True
    if snap.evolution_locked.ok and bool(snap.evolution_locked.value):
        return True
    panel = snap.panel_state.value if snap.panel_state.ok else None
    if panel not in (None, "CLOSED", "COOLDOWN"):
        return True
    return False


def _urgent_blockage(snap: Snapshot) -> str | None:
    """紧迫阻塞：有证据的失败/停滞事件。仅积压增加不产生紧迫标签（§11.6 行 2）。"""
    if not snap.failure_event.ok:
        return None
    val = str(snap.failure_event.value or "")
    if val in ("challenge_failure", "same_stage", "challenge_failure_stall"):
        return val
    return None


def decide(snapshot: Snapshot) -> Decision:
    """§11.3 A–F 严格顺序。相同快照 → 相同结果。"""
    snap = snapshot

    # A. 事务/强恢复优先
    if _in_txn(snap):
        return Decision(kind=KIND_CONTINUE, notes="active transaction / evolve lock / open panel")

    cands = _build_candidates(snap)
    legal = [c for c in cands if c.legal]
    rejected = [(c.action_id, c.reject_reason or "REJECTED") for c in cands if not c.legal]

    # B. 合法性已筛选；保留 reject 供审计
    if not legal:
        return Decision(
            kind=KIND_WAIT_OR_OBSERVE,
            alternatives=tuple(rejected),
            observe_gaps=("no_legal_candidate",),
            safe_entries=tuple(snap.safe_observe_entries),
            notes="no legal candidates after §11.3B",
        )

    # C. 紧迫阻塞：失败只证明需检查战力；无效果依据不把某技能封成唯一解
    block = _urgent_blockage(snap)
    if block == "challenge_failure":
        # 效果/短板均未知 → 观察或不可比（§11.6 行 3）
        gaps = []
        if not _fact_ok(snap.skill_badge):
            gaps.append("skill_effect_map")
        gaps.append("combat_shortfall_attribution")
        safe = tuple(snap.safe_observe_entries)
        # 若存在不依赖缺失信息的合法候选且与“解墙”无证据绑定，仍可比较；
        # 但不得声称技能是唯一解 —— 把 skill/bond/treasure 标不可比。
        pool_ids = tuple(c.action_id for c in legal)
        return Decision(
            kind=KIND_WAIT_OR_OBSERVE,
            incomparable=pool_ids,
            alternatives=tuple(rejected),
            observe_gaps=tuple(gaps) or ("combat_shortfall_attribution",),
            safe_entries=safe,
            review_required=("challenge_failure_shortfall_unknown",),
            notes="challenge_failure observed; effect attribution unknown",
        )

    # 无展示卡等强目标时的普通候选比较池
    pool = list(legal)

    # D. 支配比较（同 goal 同币种）
    winners: list[Candidate] = []
    for a in pool:
        if any(_dominates(b, a) for b in pool if b is not a):
            continue
        winners.append(a)
    # 去掉被支配者
    front = [c for c in winners if not any(_dominates(o, c) for o in winners if o is not c)]

    # 跨币种、缺可比依据 → 不可比，不换算
    incomparable: list[str] = []
    if len(front) > 1:
        # 若 frontier 含不同币种成本且无共享证据尺度 → 全部保留为不可比
        cur_sets = [{c.currency for c in x.costs if c.price_known or c.costs} for x in front]
        # 空成本（READ）与带成本动作：READ 有确认时间价值则优先（E 的一部分）
        free = [c for c in front if not c.costs]
        paid = [c for c in front if c.costs]
        if free and paid:
            # 有确认时间价值的机会优先于仅推断收益 —— free READ 兑现 rank 更早时优先
            best_free_rank = min(c.cash_in_rank for c in free)
            paid_later = [c for c in paid if c.cash_in_rank >= best_free_rank]
            if paid_later and all(c.evidence_rank <= max(x.evidence_rank for x in free) for c in paid_later):
                front = free
        # 多币种同时在 frontier
        currencies = set()
        for c in front:
            for cost in c.costs:
                currencies.add(cost.currency)
        if len(currencies) > 1 and len(front) > 1:
            # 不同币种、收益缺可比依据 → 保留不可比（§11.6 行 6）
            ids = tuple(c.action_id for c in front)
            # 仍可继续用同币种子集决策？契约：保留不可比，不换算。
            # 若存在只含单一币种的严格支配子集则选之，否则标不可比。
            single = {}
            for c in front:
                curs = frozenset(cost.currency for cost in c.costs)
                single.setdefault(curs, []).append(c)
            # 无单一明确赢家 → 不可比 + 饿死让位
            by_wait = sorted(
                front,
                key=lambda c: (
                    -(c.service_wait_s if c.service_wait_s is not None else -1.0),
                    c.action_id,
                ),
            )
            if by_wait and by_wait[0].service_wait_s is not None:
                chosen = by_wait[0]
                return Decision(
                    kind=KIND_RECOMMEND,
                    chosen=chosen,
                    alternatives=tuple(
                        (c.action_id, "INCOMPARABLE_CURRENCY" if c.action_id != chosen.action_id else "CHOSEN_BY_STARVATION")
                        for c in front
                    ),
                    incomparable=ids,
                    notes="cross-currency incomparable; anti-starvation service",
                )
            return Decision(
                kind=KIND_WAIT_OR_OBSERVE,
                incomparable=ids,
                alternatives=tuple(rejected),
                observe_gaps=("currency_conversion_forbidden", "shared_benefit_scale"),
                safe_entries=tuple(snap.safe_observe_entries),
                review_required=("cross_currency_incomparable",),
                notes="different currencies, no conversion",
            )

    if len(front) > 1:
        # E. 有确认时间价值优先；仍不可比则保持当前链 / 饿死让位
        front_sorted = sorted(
            front,
            key=lambda c: (
                c.cash_in_rank,
                -c.evidence_rank,
                -(c.service_wait_s if c.service_wait_s is not None else -1.0),
                c.action_id,
            ),
        )
        # 同效且长期未服务的等价候选获得一次服务
        waits = [c for c in front_sorted if c.service_wait_s is not None]
        if len(waits) >= 2:
            waits_sorted = sorted(waits, key=lambda c: (-float(c.service_wait_s), c.action_id))
            # 显著更久未服务（更老）且无更紧迫证据时让位
            oldest, second = waits_sorted[0], waits_sorted[1]
            if (
                oldest.service_wait_s is not None
                and second.service_wait_s is not None
                and oldest.service_wait_s > second.service_wait_s
                and oldest.evidence_rank <= second.evidence_rank
            ):
                return Decision(
                    kind=KIND_RECOMMEND,
                    chosen=oldest,
                    alternatives=tuple(
                        (c.action_id, "STARVED_EQUIVALENT" if c.action_id == oldest.action_id else "YIELDED_TO_STARVED")
                        for c in front_sorted
                    ),
                    notes="§11.5 anti-starvation service",
                )
        chain = snap.owner.current_chain
        # §11.3E：先看有确认时间价值的展示机会；链偏好只在同级候选里生效。
        top_rank = (front_sorted[0].cash_in_rank, -front_sorted[0].evidence_rank)
        peers = [
            c for c in front_sorted
            if (c.cash_in_rank, -c.evidence_rank) == top_rank
        ]
        if chain:
            in_chain = [c for c in peers if c.target == chain or c.goal == chain]
            chosen = in_chain[0] if in_chain else peers[0]
        else:
            chosen = peers[0]
        alts = tuple(
            (c.action_id, "DOMINATED_IN_FRONT" if c is not chosen else "CHOSEN")
            for c in front_sorted
        )
        return Decision(kind=KIND_RECOMMEND, chosen=chosen, alternatives=alts, notes="frontier choice")

    if not front:
        return Decision(
            kind=KIND_WAIT_OR_OBSERVE,
            alternatives=tuple(rejected),
            observe_gaps=("all_dominated_or_empty",),
            safe_entries=tuple(snap.safe_observe_entries),
        )

    # 单一 frontier
    chosen = front[0]
    # F. 缺观测会改变选择且有安全读取入口 → OBSERVE
    missing = []
    if not _fact_ok(snap.wood) and chosen.costs:
        missing.append("wood")
    if not _fact_ok(snap.merchant_kill_balance) and any(c.currency == "kill" for c in chosen.costs):
        missing.append("merchant_kill_balance")
    if not _fact_ok(snap.skill_badge) and chosen.action_id == "open_skill_panel":
        missing.append("skill_badge")
    if not _fact_ok(snap.treasure_badge) and chosen.action_id == "open_treasure_panel":
        missing.append("treasure_badge")
    # 挑战失败且短板未知已在 C 处理
    if missing:
        safe = tuple(snap.safe_observe_entries)
        # 只有存在安全读取入口才 OBSERVE
        usable = tuple(e for e in safe if e.split(":")[0] in missing or e in missing or True)
        if safe:
            return Decision(
                kind=KIND_WAIT_OR_OBSERVE,
                observe_gaps=tuple(missing),
                safe_entries=safe,
                alternatives=tuple(rejected),
                notes="missing facts affect choice; safe observe available",
            )
        # 否则选不依赖缺失信息的候选或 WAIT
        indep = [c for c in legal if not any(m in c.fact_refs for m in missing)]
        if indep:
            chosen = indep[0]
        else:
            return Decision(
                kind=KIND_WAIT_OR_OBSERVE,
                observe_gaps=tuple(missing),
                alternatives=tuple(rejected),
                notes="missing facts and no safe observe entry",
            )

    return Decision(
        kind=KIND_RECOMMEND,
        chosen=chosen,
        alternatives=tuple(
            (c.action_id, "NOT_CHOSEN" if c is not chosen else "CHOSEN") for c in legal
        ) + tuple(rejected),
        notes="legal single recommendation",
    )


def snapshot_fingerprint(snap: Snapshot) -> str:
    """纯函数快照摘要，用于日志去重。"""
    parts = [
        str(snap.round_id),
        str(_num(snap.wood)),
        str(_num(snap.skill_badge)),
        str(_num(snap.treasure_badge)),
        str(snap.panel_state.value),
        str(snap.active_transaction.value),
        str(snap.evolution_locked.value),
        str(snap.owner.current_chain),
    ]
    return "|".join(parts)
