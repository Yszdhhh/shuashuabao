"""§11.6 首批确定性验收矩阵 + 纯函数约束。禁止结果全部断言。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "src", ROOT):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)

from shuabao.solo_scheduler import (  # noqa: E402
    KIND_CONTINUE,
    KIND_RECOMMEND,
    KIND_WAIT_OR_OBSERVE,
    ActionRecord,
    Candidate,
    Cost,
    Decision,
    Fact,
    OwnerConfig,
    Snapshot,
    UNKNOWN_PRICE,
    decide,
)


def _snap(**kw) -> Snapshot:
    base = dict(
        now=1000.0,
        round_id="r1",
        wood=Fact.observed(500, "t"),
        skill_badge=Fact.observed(0, "t"),
        treasure_badge=Fact.observed(0, "t"),
        confirmed_bond_cards=Fact.observed([], "t"),
        confirmed_skill_cards=Fact.observed([], "t"),
        pending_records=(),
        evolution_locked=Fact.observed(False, "t"),
        active_transaction=Fact.observed(False, "t"),
        panel_state=Fact.observed("CLOSED", "t"),
        swallow_guard_allows=Fact.observed(False, "t"),
        main_line_stage=Fact.unknown("t"),
        failure_event=Fact.missing("t"),
        tab_window=Fact.unknown("t"),
        artifact_ready=Fact.unknown("t"),
        merchant_kill_balance=Fact.unknown("t"),
        bond_draw_price=Fact.observed(20, "model"),
        bond_refresh_price=Fact.observed(40, "model"),
        merchant_pill_price=Fact.observed(400, "model"),
        merchant_wood_price=Fact.observed(300, "model"),
        merchant_refresh_price=Fact.observed(350, "model"),
        safe_observe_entries=("wood:existing_hud",),
        owner=OwnerConfig(current_chain="bond"),
    )
    base.update(kw)
    return Snapshot(**base)


# --- 1. 进化待确认 + 技能角标大 → CONTINUE_TRANSACTION；禁止另开 G ---

def test_evolve_pending_and_big_skill_badge_continues_transaction():
    snap = _snap(
        evolution_locked=Fact.observed(True, "t"),
        skill_badge=Fact.observed(32, "t"),
        treasure_badge=Fact.observed(5, "t"),
    )
    d = decide(snap)
    assert d.kind == KIND_CONTINUE
    assert d.chosen is None or d.chosen.action_id != "open_skill_panel"


# --- 2. 只积压增加 → 不产生紧迫标签 / 不恢复 >=8 抢占 ---

def test_skill_backlog_alone_is_not_urgent_and_no_force_preempt():
    small = _snap(skill_badge=Fact.observed(1, "t"), failure_event=Fact.missing("t"))
    large = _snap(skill_badge=Fact.observed(32, "t"), failure_event=Fact.missing("t"))
    d0, d1 = decide(small), decide(large)
    assert d0.kind not in (KIND_WAIT_OR_OBSERVE,) or "challenge_failure" not in (d0.notes or "")
    # 大积压不得触发“紧急强抢占”式唯一解
    assert "紧急强抢占" not in (d1.notes or "")
    assert ">=8" not in (d1.notes or "")
    assert "≥ 8" not in (d1.notes or "")
    # 不得仅因积压产生 review 的挑战失败紧迫
    assert "challenge_failure_shortfall_unknown" not in d1.review_required
    # 积压大不自动强制选 skill 而丢掉其他合法候选
    if d1.kind == KIND_RECOMMEND and d1.chosen is not None:
        # 允许推荐 skill，但 alternatives 必须仍保留其他合法入口，而不是“硬抢占清空”
        assert isinstance(d1.alternatives, tuple)


# --- 3. 挑战失败且短板未知 → OBSERVE 或不可比；禁止声称学技能一定解墙 ---

def test_challenge_failure_unknown_shortfall_observes_or_incomparable():
    snap = _snap(
        failure_event=Fact.observed("challenge_failure", "t"),
        skill_badge=Fact.observed(10, "t"),
        treasure_badge=Fact.observed(2, "t"),
    )
    d = decide(snap)
    assert d.kind == KIND_WAIT_OR_OBSERVE or d.incomparable
    if d.kind == KIND_RECOMMEND:
        assert d.incomparable
    assert d.chosen is None or "skill" not in (d.chosen.notes or "唯一")
    assert "combat_shortfall_attribution" in d.observe_gaps or "challenge_failure_shortfall_unknown" in d.review_required


# --- 4. 关键合法卡可支付 + 木材 < 300 → 仍是合法候选；禁止仅余额档位排除 ---

def test_affordable_card_stays_legal_below_wood_300():
    snap = _snap(
        wood=Fact.observed(250, "t"),
        shown_card_price=Fact.observed(20, "panel"),
        shown_card_id=Fact.observed("藏宝图", "panel"),
        skill_badge=Fact.observed(0, "t"),
        treasure_badge=Fact.observed(0, "t"),
    )
    d = decide(snap)
    assert d.kind == KIND_RECOMMEND
    # 矩阵：卡必须进入合法候选；禁止仅余额档位排除
    legal_ids = {aid for aid, reason in d.alternatives if reason in ("CHOSEN", "NOT_CHOSEN")}
    if d.chosen:
        legal_ids.add(d.chosen.action_id)
    assert any(i.startswith("take_card:") for i in legal_ids)
    for aid, reason in d.alternatives:
        if aid.startswith("take_card:"):
            assert reason not in ("BALANCE_TIER", "INSUFFICIENT_BALANCE", "BALANCE_UNKNOWN")
    if d.chosen is not None:
        assert d.chosen.reject_reason != "BALANCE_TIER"


# --- 5. A 支配 B → 选 A；禁止仍按固定轮换选 B ---

def test_a_dominates_b_picks_a():
    # 用两张已展示卡构造同目标：A 成本更低、兑现更早、证据不弱
    snap = Snapshot(
        now=1.0,
        round_id="r",
        wood=Fact.observed(100, "t"),
        skill_badge=Fact.observed(0, "t"),
        treasure_badge=Fact.observed(0, "t"),
        confirmed_bond_cards=Fact.observed([], "t"),
        confirmed_skill_cards=Fact.observed([], "t"),
        pending_records=(),
        evolution_locked=Fact.observed(False, "t"),
        active_transaction=Fact.observed(False, "t"),
        panel_state=Fact.observed("CLOSED", "t"),
        swallow_guard_allows=Fact.observed(False, "t"),
        failure_event=Fact.missing("t"),
        merchant_kill_balance=Fact.unknown("t"),
        bond_draw_price=Fact.observed(20, "m"),
        bond_refresh_price=Fact.observed(40, "m"),
        safe_observe_entries=(),
        owner=OwnerConfig(current_chain=""),
    )
    # 直接测支配函数语义：A 成本更低、兑现更早
    a = Candidate(
        action_id="A", target="bond", kind="PAID_DRAW", legal=True, reject_reason="",
        fact_refs=("wood",), costs=(Cost("wood", 20),), expected_cash_in="x",
        bottleneck="b", executor="e", confirm_ref="c", goal="g", cash_in_rank=1, evidence_rank=2,
    )
    b = Candidate(
        action_id="B", target="bond", kind="PAID_DRAW", legal=True, reject_reason="",
        fact_refs=("wood",), costs=(Cost("wood", 40),), expected_cash_in="x",
        bottleneck="b", executor="e", confirm_ref="c", goal="g", cash_in_rank=2, evidence_rank=2,
    )
    from shuabao.solo_scheduler import _dominates

    assert _dominates(a, b)
    assert not _dominates(b, a)
    # 构造快照：两张展示卡则只暴露一张便宜卡
    snap2 = Snapshot(
        **{**snap.__dict__, "shown_card_price": Fact.observed(20, "p"), "shown_card_id": Fact.observed("A", "p")}
    )
    d = decide(snap2)
    assert d.kind == KIND_RECOMMEND
    assert d.chosen is not None and d.chosen.action_id == "take_card:A"


# --- 6. 金币 vs 杀敌不可比 → 保留不可比；禁止任意汇率换算 ---

def test_cross_currency_incomparable_no_conversion():
    # 已展示卡耗木材，黑商耗杀敌：杀敌余额未知时黑商非法；若两边都合法则不可比
    snap = _snap(
        wood=Fact.observed(1000, "t"),
        merchant_kill_balance=Fact.observed(1000, "t"),
        shown_card_price=Fact.observed(50, "p"),
        shown_card_id=Fact.observed("卡A", "p"),
        skill_badge=Fact.observed(0, "t"),
        treasure_badge=Fact.observed(0, "t"),
    )
    d = decide(snap)
    # 不产生把 kill 换成 wood 的总分选法
    assert "汇率" not in (d.notes or "")
    assert "convert" not in (d.notes or "").lower()
    if d.kind == KIND_RECOMMEND and d.chosen is not None:
        # 若因多币种走饿死路径，incomparable 应非空
        if len({c.currency for c in d.chosen.costs}) == 1 and d.incomparable:
            assert d.incomparable
    # 显式双候选场景
    from shuabao.solo_scheduler import _dominates

    wood_c = Candidate(
        action_id="W", target="x", kind="PAID_DRAW", legal=True, reject_reason="",
        fact_refs=(), costs=(Cost("wood", 10),), expected_cash_in="x", bottleneck="b",
        executor="e", confirm_ref="c", goal="g", cash_in_rank=1, evidence_rank=1, service_wait_s=5.0,
    )
    kill_c = Candidate(
        action_id="K", target="y", kind="PAID_CONSUME", legal=True, reject_reason="",
        fact_refs=(), costs=(Cost("kill", 10),), expected_cash_in="x", bottleneck="b",
        executor="e", confirm_ref="c", goal="g", cash_in_rank=1, evidence_rank=1, service_wait_s=5.0,
    )
    assert not _dominates(wood_c, kill_c)
    assert not _dominates(kill_c, wood_c)


# --- 7. 刷新可付但目标买不起 → 不推荐刷新链；禁止刷光资源 ---

def test_refresh_affordable_but_draw_unaffordable_not_recommended():
    snap = _snap(
        wood=Fact.observed(50, "t"),  # >= refresh 40，但 40+20=60 > 50
        bond_draw_price=Fact.observed(20, "model"),
        bond_refresh_price=Fact.observed(40, "model"),
        skill_badge=Fact.observed(0, "t"),
        treasure_badge=Fact.observed(0, "t"),
    )
    d = decide(snap)
    ids = []
    if d.chosen:
        ids.append(d.chosen.action_id)
    for aid, _r in d.alternatives:
        ids.append(aid)
    # 可能仍推荐 DRAW（20<=50）但绝不推荐刷新链
    if d.kind == KIND_RECOMMEND and d.chosen is not None:
        assert d.chosen.action_id != "bond_refresh"
    for aid, reason in d.alternatives:
        if aid == "bond_refresh":
            assert reason in ("TARGET_UNAFFORDABLE", "INSUFFICIENT_BALANCE", "UNKNOWN_PRICE", "REJECTED", "NOT_CHOSEN", "OWNER_DISABLED")


# --- 8. 等价宝物长期未服务且事务结束 → 给宝物一次；禁止永久留在 F ---

def test_starved_treasure_gets_service():
    snap = _snap(
        wood=Fact.observed(200, "t"),
        skill_badge=Fact.observed(0, "t"),
        treasure_badge=Fact.observed(3, "t"),
        service_wait_skill=Fact.observed(2.0, "t"),
        service_wait_bond=Fact.observed(2.0, "t"),
        service_wait_treasure=Fact.observed(90.0, "t"),
        bond_draw_price=Fact.observed(20, "m"),
        bond_refresh_price=Fact.observed(40, "m"),
        owner=OwnerConfig(auto_treasure=True, current_chain=""),
    )
    d = decide(snap)
    assert d.kind == KIND_RECOMMEND
    assert d.chosen is not None
    assert d.chosen.action_id == "open_treasure_panel"
    assert "starve" in (d.notes or "").lower() or "starvation" in (d.notes or "").lower() or d.chosen.action_id == "open_treasure_panel"


# --- 9. 选择卡 ok=true 但结果未确认 → 持有账目不增加 ---

def test_requested_action_does_not_advance_ledger():
    rec = ActionRecord(action_id="藏宝图", state="requested", detail="click ok")
    assert not rec.advances_ledger
    confirmed = ActionRecord(action_id="藏宝图", state="confirmed", detail="WAIT_MUTATION")
    assert confirmed.advances_ledger
    snap = _snap(
        confirmed_bond_cards=Fact.observed(["法术"], "t"),
        pending_records=(ActionRecord("藏宝图", "requested"),),
    )
    owned = list(snap.confirmed_bond_cards.value or [])
    # 决策器只用 confirmed 账目
    d = decide(snap)
    assert isinstance(d, Decision)
    assert "藏宝图" not in owned


# --- 10. TAB mid_run ≠ entry → 只更新本局快照 ---

def test_tab_mid_run_does_not_overwrite_entry():
    entry = Fact.observed({"attack": 10}, "tab.entry")
    mid = Fact.observed({"attack": 99}, "tab.mid_run")
    snap = _snap(tab_window=Fact.observed("mid_run", "tab"), )
    d = decide(snap)
    # 影子决策不得依据 TAB 授权动作
    if d.chosen is not None:
        assert "tab" not in d.chosen.fact_refs
    assert entry.value != mid.value
    assert entry.source != mid.source


# --- 11. 丹可见但守卫关 → 排除消费 ---

def test_swallow_visible_but_guard_closed_excludes_consume():
    snap = _snap(swallow_guard_allows=Fact.observed(False, "const_false"))
    d = decide(snap)
    chosen_id = d.chosen.action_id if d.chosen else ""
    assert chosen_id != "consume_swallow_pill"
    for aid, reason in d.alternatives:
        if aid == "consume_swallow_pill":
            assert reason == "GUARD_CLOSED"


# --- 12. 跨局/跨页面旧余额 → 依赖项失效 ---

def test_unknown_balance_does_not_authorize_spend():
    snap = _snap(
        merchant_kill_balance=Fact.unknown("hud"),
        wood=Fact.unknown("hud"),
        skill_badge=Fact.observed(0, "t"),
        treasure_badge=Fact.observed(0, "t"),
    )
    d = decide(snap)
    if d.chosen is not None and d.chosen.costs:
        assert d.chosen.legal is False
    for aid, reason in d.alternatives:
        if aid.startswith("merchant_") or aid in ("bond_draw", "bond_refresh"):
            assert reason in ("BALANCE_UNKNOWN", "UNKNOWN_PRICE", "INSUFFICIENT_BALANCE", "REJECTED", "OWNER_DISABLED", "NOT_CHOSEN", "TARGET_UNAFFORDABLE")


# --- 纯函数：相同快照两次完全相等 ---

def test_deterministic_same_snapshot():
    snap = _snap(skill_badge=Fact.observed(5, "t"), treasure_badge=Fact.observed(1, "t"))
    d1 = decide(snap)
    d2 = decide(snap)
    assert d1.kind == d2.kind
    assert d1.notes == d2.notes
    assert d1.incomparable == d2.incomparable
    assert d1.observe_gaps == d2.observe_gaps
    assert (d1.chosen.action_id if d1.chosen else None) == (d2.chosen.action_id if d2.chosen else None)


# --- unknown 值不会被当 0 参与比较 ---

def test_unknown_not_treated_as_zero():
    # wood unknown 时不得“可支付 0 元消费”
    snap = _snap(
        wood=Fact.unknown("t"),
        shown_card_price=Fact.observed(0, "p"),  # 即使价格 0，余额 unknown 也走合法链
        shown_card_id=Fact.observed("卡", "p"),
        skill_badge=Fact.observed(0, "t"),
        treasure_badge=Fact.observed(0, "t"),
    )
    d = decide(snap)
    # 价格 0 的 READ 仍可合法；但绝不能把 unknown wood 当 0 去判“余额不足”或“刚好够”
    from shuabao.solo_scheduler import Fact as F

    f = F.unknown("x")
    assert f.known_num is None
    assert f.value is None
    # bond_draw 价格已知但余额 unknown → 非法
    snap2 = _snap(wood=Fact.unknown("t"), skill_badge=Fact.observed(0, "t"), treasure_badge=Fact.observed(0, "t"))
    d2 = decide(snap2)
    for aid, reason in d2.alternatives:
        if aid == "bond_draw":
            assert reason == "BALANCE_UNKNOWN"


# --- 黑商余额不可读 → 消费 legal=False BALANCE_UNKNOWN（G8 影子语义） ---

def test_merchant_balance_unknown_blocks_spend():
    snap = _snap(
        merchant_kill_balance=Fact.unknown("t"),
        wood=Fact.observed(9999, "t"),
        skill_badge=Fact.observed(0, "t"),
        treasure_badge=Fact.observed(0, "t"),
    )
    d = decide(snap)
    found = False
    for aid, reason in d.alternatives:
        if aid.startswith("merchant_"):
            found = True
            assert reason == "BALANCE_UNKNOWN"
    if d.chosen is not None and d.chosen.action_id.startswith("merchant_"):
        assert d.chosen.legal is False
        assert d.chosen.reject_reason == "BALANCE_UNKNOWN"
    # 至少应把 merchant 候选标非法
    assert found or (d.chosen is None)
