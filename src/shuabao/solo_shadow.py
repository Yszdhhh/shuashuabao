"""单人影子调度适配器 + 记录器。默认关闭，零输入，绝不向主线抛。

开关
====
``SHUABAO_SOLO_SHADOW=1`` 才开；关时 Mediator 侧连本模块都不导入。
输出 ``SHUABAO_SOLO_SHADOW_DIR``（缺省与 observe 相同目录）下
``solo_shadow_*.jsonl``，一行一个事务边界。

纪律
====
* 只用 ``getattr`` 读 Mediator 已有字段，不写回、不新增识别。
* 任何异常自己吞掉计数，连续 5 次永久关闭。
* 蹭车/跟车模式不记录。
* 只在单人 MAIN_LINE 事务边界记录，不逐 tick 刷。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from shuabao.solo_scheduler import (
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

SOLO_SHADOW_ENV = "SHUABAO_SOLO_SHADOW"
SOLO_SHADOW_DIR_ENV = "SHUABAO_SOLO_SHADOW_DIR"

_MAX_FAILURES = 5
_SCHEMA = 1


def solo_shadow_enabled(env: Mapping[str, str] | None = None) -> bool:
    source = os.environ if env is None else env
    return str(source.get(SOLO_SHADOW_ENV, "")).strip().lower() in ("1", "true", "yes", "on")


def solo_shadow_dir(env: Mapping[str, str] | None = None) -> Path:
    source = os.environ if env is None else env
    override = str(source.get(SOLO_SHADOW_DIR_ENV, "")).strip()
    if override:
        return Path(override)
    from shuabao.observe_log import observe_dir

    return observe_dir()


def _plain(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return str(value)


def _fact_from_attr(obj: Any, name: str, *, default_state: str = "unknown") -> Fact:
    """getattr 读字段；读不到记 missing/unknown，绝不填 0。"""
    if not hasattr(obj, name):
        return Fact(value=None, state="missing", source=f"mediator.{name}:absent")
    try:
        value = getattr(obj, name)
    except Exception:
        return Fact(value=None, state="invalid", source=f"mediator.{name}:error")
    if value is None:
        return Fact(value=None, state="missing", source=f"mediator.{name}")
    return Fact(value=value, state="observed", source=f"mediator.{name}", observed_at=None)


def _fact_num(value: Any, source: str) -> Fact:
    if value is None:
        return Fact(value=None, state="missing", source=source)
    if isinstance(value, bool):
        return Fact(value=value, state="observed", source=source)
    if isinstance(value, (int, float)):
        return Fact(value=value, state="observed", source=source)
    return Fact(value=None, state="invalid", source=source)


def _confirmed_ledger_fact(obj: Any, name: str) -> Fact:
    """Keep unavailable/invalid ledgers distinct from a confirmed empty one."""
    source = f"mediator.{name}"
    try:
        value = getattr(obj, name, None)
        if callable(value):
            value = value()
    except Exception:
        return Fact.invalid(source)
    if value is None:
        return Fact.missing(source)
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(card, str) or not card.strip() for card in value
    ):
        return Fact.invalid(source)
    return Fact.observed(list(value), source)


def build_snapshot(mediator: Any, now: float | None = None) -> Snapshot:
    """只读 Mediator 已有字段构造快照。字段可用性按 EVIDENCE 矩阵。"""
    ts = float(now if now is not None else time.time())
    g = lambda n, d=None: getattr(mediator, n, d)

    wood = _fact_num(g("_wood_balance"), "mediator._wood_balance")
    skill = _fact_num(g("_skill_points_seen"), "mediator._skill_points_seen")
    # 角标 sticky：None 仅表示尚未首见 / 被遮挡沿用旧值 —— 照实标注
    if skill.state == "missing" and g("_skill_points_seen") is None:
        skill = Fact(value=None, state="missing", source="mediator._skill_points_seen:sticky_or_unread")
    treasure = _fact_num(g("_treasure_pending_seen"), "mediator._treasure_pending_seen")
    if treasure.state == "missing" and g("_treasure_pending_seen") is None:
        treasure = Fact(value=None, state="missing", source="mediator._treasure_pending_seen:sticky_or_unread")

    pending_records = tuple(
        ActionRecord(action_id=str(name), state="requested", detail="pending_not_confirmed")
        for name in (g("_bond_cards_pending") or ())
    ) + tuple(
        ActionRecord(action_id=str(name), state="requested", detail="pending_not_confirmed")
        for name in (g("_skill_cards_pending") or ())
    )

    evolve_locked = bool(g("_evolve_feedback_pending") or g("_evolve_awaiting_hero_pick"))
    pending_action = g("_pending_action") is not None
    eq_fsm = g("_equipment_fsm")
    eq_pending = getattr(eq_fsm, "pending_slot", None) is not None if eq_fsm is not None else False
    merch_fsm = g("_merchant_fsm")
    merch_verifying = getattr(getattr(merch_fsm, "phase", None), "name", "") == "VERIFYING"
    bag_fsm = g("_public_bag_fsm")
    bag_active = bool(getattr(bag_fsm, "active", False)) if bag_fsm is not None else False
    panel_state = getattr(g("_panel_state"), "name", None) or g("_panel_state")
    panel_open = panel_state not in (None, "CLOSED", "COOLDOWN")
    active_tx = bool(pending_action or eq_pending or evolve_locked or merch_verifying or bag_active or panel_open)

    # 吞噬丹守卫恒 False（生产代码 _can_consume_inventory_swallow_pill）
    swallow_ok = False
    try:
        fn = g("_can_consume_inventory_swallow_pill")
        if callable(fn):
            swallow_ok = bool(fn(None))
    except Exception:
        swallow_ok = False

    # 黑商余额：指纹缓存值；None → unknown（不可授权消费）
    merchant_bal = g("_merchant_kill_balance_value")
    merchant_fact = _fact_num(merchant_bal, "mediator._merchant_kill_balance_value")

    # 主线 X-Y / 失败：不可授权，只记录
    stage = g("_main_line_stall_stage")
    if stage is not None:
        main_stage = Fact(value=list(stage) if isinstance(stage, tuple) else stage, state="observed",
                          source="mediator._main_line_stall_stage")
    else:
        main_stage = Fact.unknown("mediator._main_line_stall_stage")
    fail_reason = g("_main_line_stall_reason")
    failure = Fact.observed(fail_reason, "mediator._main_line_stall_reason") if fail_reason else Fact.missing("mediator._main_line_stall_reason")

    # TAB：mid_run ≠ entry；只更新本局快照，不覆盖开局画像
    tab_window = Fact.unknown("player_profile.classify_tab_window:not_wired")
    artifact_ready = Fact.unknown("mediator._slot_has_artifact:effect_unverified")

    # Owner 约束
    settings = g("settings")
    policy_doc = g("_choice_policy_doc") or {}
    treasure_cfg = policy_doc.get("treasure") if isinstance(policy_doc, dict) else {}
    if not isinstance(treasure_cfg, dict):
        treasure_cfg = {}
    allow_neg = tuple(str(x) for x in (getattr(settings, "treasure_allow_negative", ()) or ()))
    neg_names = tuple(str(x) for x in (treasure_cfg.get("negative_names") or ()))
    neg_pats = tuple(str(x) for x in (treasure_cfg.get("negative_patterns") or ()))
    owner = OwnerConfig(
        auto_bond=bool(getattr(settings, "auto_bond", True)),
        auto_treasure=bool(getattr(settings, "auto_treasure", True)),
        auto_devour_dan=bool(getattr(settings, "auto_devour_dan", False)),
        treasure_allow_negative=allow_neg,
        treasure_negative_names=neg_names,
        treasure_negative_patterns=neg_pats,
        goal_preference=(),
        current_chain=str(g("_l1_cycle_step") or ""),
    )

    # 价格：模型价标 model-derived（经 solo_scheduler.Cost）
    picks = g("_bond_picks_round")
    try:
        picks_i = int(picks or 0)
        draw_price = 100 if picks_i >= 4 else 20 * (picks_i + 1)
        refresh_price = (40, 60, 80, 100)[min(picks_i, 3)]
    except Exception:
        draw_price = UNKNOWN_PRICE
        refresh_price = UNKNOWN_PRICE

    # 反饿死时钟
    def _wait(last_name: str) -> Fact:
        last = g(last_name)
        if last is None:
            return Fact.unknown(f"mediator.{last_name}")
        try:
            return Fact.observed(max(0.0, ts - float(last)), f"mediator.{last_name}")
        except Exception:
            return Fact.unknown(f"mediator.{last_name}")

    plan = g("_observe_plan") or (None, "")
    plan_target, plan_reason = plan[0], plan[1] if isinstance(plan, tuple) else (None, str(plan))

    snap = Snapshot(
        now=ts,
        round_id=str(g("_observe_round_id")() if callable(g("_observe_round_id")) else g("_round_started_at")),
        wood=wood,
        skill_badge=skill,
        treasure_badge=treasure,
        confirmed_bond_cards=_confirmed_ledger_fact(mediator, "_confirmed_bond_cards"),
        confirmed_skill_cards=_confirmed_ledger_fact(mediator, "_confirmed_skill_cards"),
        pending_records=pending_records,
        evolution_locked=Fact.observed(evolve_locked, "mediator._evolve_feedback_pending/_evolve_awaiting_hero_pick"),
        active_transaction=Fact.observed(active_tx, "mediator._has_active_transaction:state_only"),
        panel_state=Fact.observed(str(panel_state), "mediator._panel_state"),
        swallow_guard_allows=Fact.observed(swallow_ok, "mediator._can_consume_inventory_swallow_pill:const_false"),
        main_line_stage=main_stage,
        failure_event=failure,
        tab_window=tab_window,
        artifact_ready=artifact_ready,
        merchant_kill_balance=merchant_fact,
        service_wait_skill=_wait("_last_skill_panel"),
        service_wait_bond=_wait("_last_bond_attempt"),
        service_wait_treasure=_wait("_last_treasure_attempt"),
        bond_draw_price=Fact.observed(draw_price, "model:_bond_next_price", observed_at=ts),
        bond_refresh_price=Fact.observed(refresh_price, "model:_bond_refresh_price", observed_at=ts),
        merchant_pill_price=Fact.observed(400, "model:_MERCHANT_DEVOUR_PILL_KILL_COST", observed_at=ts),
        merchant_wood_price=Fact.observed(300, "model:_MERCHANT_WOOD_KILL_COST", observed_at=ts),
        merchant_refresh_price=Fact.observed(350, "model:_MERCHANT_REFRESH_KILL_COST", observed_at=ts),
        safe_observe_entries=("wood:existing_hud", "skill_badge:existing_hud", "treasure_badge:existing_hud"),
        owner=owner,
        shown_card_price=Fact.unknown("shown_card_price"),
        shown_card_id=Fact.unknown("shown_card_id"),
    )
    # plan 信息挂在 notes 外字段：由 note_boundary 单独传
    return snap


def snapshot_summary(snap: Snapshot) -> dict:
    def f(fact: Fact) -> dict:
        return {
            "state": fact.state,
            "value": _plain(fact.value),
            "source": fact.source,
            "observed_at": fact.observed_at,
        }

    return {
        "now": snap.now,
        "round_id": snap.round_id,
        "wood": f(snap.wood),
        "skill_badge": f(snap.skill_badge),
        "treasure_badge": f(snap.treasure_badge),
        "confirmed_bond_cards": f(snap.confirmed_bond_cards),
        "confirmed_skill_cards": f(snap.confirmed_skill_cards),
        "pending_count": len(snap.pending_records),
        "evolution_locked": f(snap.evolution_locked),
        "active_transaction": f(snap.active_transaction),
        "panel_state": f(snap.panel_state),
        "swallow_guard_allows": f(snap.swallow_guard_allows),
        "main_line_stage": f(snap.main_line_stage),
        "failure_event": f(snap.failure_event),
        "tab_window": f(snap.tab_window),
        "artifact_ready": f(snap.artifact_ready),
        "merchant_kill_balance": f(snap.merchant_kill_balance),
        "bond_draw_price": f(snap.bond_draw_price),
        "bond_refresh_price": f(snap.bond_refresh_price),
        "service_wait": {
            "skill": _plain(snap.service_wait_skill.value),
            "bond": _plain(snap.service_wait_bond.value),
            "treasure": _plain(snap.service_wait_treasure.value),
        },
        "owner": {
            "auto_bond": snap.owner.auto_bond,
            "auto_treasure": snap.owner.auto_treasure,
            "auto_devour_dan": snap.owner.auto_devour_dan,
            "treasure_allow_negative": list(snap.owner.treasure_allow_negative),
            "current_chain": snap.owner.current_chain,
        },
    }


def decision_payload(decision: Decision) -> dict:
    def cand(c: Candidate) -> dict:
        return {
            "action_id": c.action_id,
            "target": c.target,
            "kind": c.kind,
            "legal": c.legal,
            "reject_reason": c.reject_reason,
            "costs": [
                {
                    "currency": cost.currency,
                    "amount": _plain(cost.amount),
                    "model_derived": cost.model_derived,
                    "note": cost.note,
                }
                for cost in c.costs
            ],
            "goal": c.goal,
            "expected_cash_in": c.expected_cash_in,
            "bottleneck": c.bottleneck,
            "executor": c.executor,
            "confirm_ref": c.confirm_ref,
        }

    return {
        "kind": decision.kind,
        "chosen": cand(decision.chosen) if decision.chosen else None,
        "alternatives": list(decision.alternatives),
        "incomparable": list(decision.incomparable),
        "review_required": list(decision.review_required),
        "observe_gaps": list(decision.observe_gaps),
        "safe_entries": list(decision.safe_entries),
        "notes": decision.notes,
    }


class SoloShadowLog:
    """事务边界记录器。永不抛异常；连续 5 次失败永久关闭。"""

    def __init__(
        self,
        out_dir: Path | str | None = None,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self.disabled = False
        self.failures = 0
        self.boundaries_written = 0
        self._wall = wall_clock
        self._dir = Path(out_dir) if out_dir is not None else solo_shadow_dir()
        self._sink = None
        self._seq = 0
        self._last_key: tuple | None = None

    def close(self) -> None:
        sink, self._sink = self._sink, None
        if sink is not None:
            try:
                sink.close()
            except Exception:
                pass

    def _fail(self, where: str, exc: BaseException) -> None:
        self.failures += 1
        if self.failures >= _MAX_FAILURES:
            self.disabled = True
            self.close()

    def _file(self) -> Any:
        if self._sink is not None:
            return self._sink
        self._dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(self._wall()))
        path = self._dir / f"solo_shadow_{stamp}_{os.getpid()}.jsonl"
        self._sink = path.open("a", encoding="utf-8")
        return self._sink

    def note_boundary(
        self,
        *,
        snapshot: Snapshot,
        decision: Decision,
        actual_plan_target: object = None,
        actual_plan_reason: str = "",
        cycle_step: object = None,
        actual_act: str = "",
        boundary: str = "free",
    ) -> None:
        if self.disabled:
            return
        try:
            key = (
                snapshot.round_id,
                snapshot_summary(snapshot).__repr__(),
                decision_payload(decision).__repr__(),
                str(actual_plan_target),
                actual_plan_reason,
                str(cycle_step),
                actual_act,
            )
            if key == self._last_key:
                return
            self._seq += 1
            payload = {
                "schema": _SCHEMA,
                "ts": round(self._wall(), 3),
                "seq": self._seq,
                "round_id": snapshot.round_id,
                "boundary": boundary,
                "snapshot": snapshot_summary(snapshot),
                "decision": decision_payload(decision),
                "actual": {
                    "plan_target": _plain(actual_plan_target),
                    "plan_reason": actual_plan_reason,
                    "cycle_step": _plain(cycle_step),
                    "act": actual_act,
                },
            }
            fh = self._file()
            fh.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
            fh.flush()
            self._last_key = key
            self.boundaries_written += 1
        except Exception as exc:
            self._fail("note_boundary", exc)


def run_shadow_once(mediator: Any, now: float | None = None) -> Decision | None:
    """单次：建快照 → decide。失败返回 None。"""
    try:
        snap = build_snapshot(mediator, now=now)
        return decide(snap)
    except Exception:
        return None
