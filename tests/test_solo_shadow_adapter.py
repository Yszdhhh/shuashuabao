"""影子适配器：开关、缺字段、失败熔断、蹭车不记。"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "src", ROOT):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)

import pytest  # noqa: E402


def test_disabled_does_not_import_module(monkeypatch, tmp_path):
    monkeypatch.setenv("SHUABAO_SOLO_SHADOW", "0")
    sys.modules.pop("shuabao.solo_shadow", None)

    class Med:
        pass

    med = Med()
    from shuabao.mediator import Mediator  # noqa: F401

    log = Mediator._solo_shadow_log(med)
    assert log is None
    assert "shuabao.solo_shadow" not in sys.modules


def test_enabled_builds_snapshot_marks_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("SHUABAO_SOLO_SHADOW", "1")
    monkeypatch.setenv("SHUABAO_SOLO_SHADOW_DIR", str(tmp_path))
    from shuabao import solo_shadow as ss

    class FakeMed:
        settings = SimpleNamespace(auto_bond=True, auto_treasure=True, auto_devour_dan=False, treasure_allow_negative=[])
        _wood_balance = 120
        _skill_points_seen = None  # 缺 → missing，不为 0
        _treasure_pending_seen = 2
        _bond_cards_owned = ["法术"]
        _skill_cards_owned = []
        _bond_cards_pending = ["藏宝图"]
        _skill_cards_pending = []
        _evolve_feedback_pending = False
        _evolve_awaiting_hero_pick = False
        _pending_action = None
        _equipment_fsm = SimpleNamespace(pending_slot=None)
        _merchant_fsm = SimpleNamespace(phase=None)
        _public_bag_fsm = SimpleNamespace(active=False)
        _panel_state = SimpleNamespace(name="CLOSED")
        _main_line_stall_stage = None
        _main_line_stall_reason = None
        _merchant_kill_balance_value = None
        _bond_picks_round = 1
        _l1_cycle_step = "bond"
        _observe_plan = ("bond", "按轮换")
        _choice_policy_doc = {}
        _round_started_at = 100.0

        def _confirmed_bond_cards(self):
            return tuple(self._bond_cards_owned)

        def _confirmed_skill_cards(self):
            return tuple(self._skill_cards_owned)

        def _passenger_mode(self):
            return False

        def _observe_round_id(self):
            return "r100"

        def _can_consume_inventory_swallow_pill(self, frame):
            return False

    med = FakeMed()
    snap = ss.build_snapshot(med, now=200.0)
    assert snap.wood.state == "observed" and snap.wood.value == 120
    assert snap.skill_badge.state in ("missing", "unknown")
    assert snap.skill_badge.value is None  # 绝不填 0
    assert snap.treasure_badge.value == 2
    assert list(snap.confirmed_bond_cards.value) == ["法术"]
    assert any(r.action_id == "藏宝图" and r.state == "requested" for r in snap.pending_records)
    assert snap.swallow_guard_allows.value is False
    assert snap.merchant_kill_balance.state == "missing"


def test_recorder_five_failures_disables_without_raise(tmp_path):
    from shuabao import solo_shadow as ss

    log = ss.SoloShadowLog(out_dir=tmp_path)

    class Boom:
        def write(self, *_a, **_k):
            raise RuntimeError("boom")

        def flush(self):
            raise RuntimeError("boom")

        def close(self):
            pass

    log._sink = Boom()
    med_snap = ss.Snapshot(
        now=1.0,
        round_id="r",
        wood=ss.Fact.unknown("t"),
    )
    from shuabao.solo_scheduler import Decision

    dec = Decision(kind="WAIT_OR_OBSERVE")
    for _ in range(5):
        log.note_boundary(snapshot=med_snap, decision=dec)
    assert log.disabled is True
    assert log.failures >= 5
    # 关闭后不再抛
    log.note_boundary(snapshot=med_snap, decision=dec)


def test_passenger_mode_does_not_write(tmp_path, monkeypatch):
    monkeypatch.setenv("SHUABAO_SOLO_SHADOW", "1")
    monkeypatch.setenv("SHUABAO_SOLO_SHADOW_DIR", str(tmp_path))
    from shuabao.mediator import Mediator

    class FakeMed:
        def _passenger_mode(self):
            return True

        def _solo_shadow_log(self):
            return Mediator._solo_shadow_log(self)

        phase = SimpleNamespace(name="MAIN_LINE")

    med = FakeMed()

    class Log:
        disabled = False

        def note_boundary(self, **kw):
            raise AssertionError("should not write")

    med._solo_shadow = Log()
    med._solo_shadow_ready = True
    Mediator._solo_shadow_tick(med)
    # 不抛即不写


def test_records_once_per_free_stretch(tmp_path, monkeypatch):
    monkeypatch.setenv("SHUABAO_SOLO_SHADOW", "1")
    monkeypatch.setenv("SHUABAO_SOLO_SHADOW_DIR", str(tmp_path))
    from shuabao.mediator import Mediator

    writes = []

    class Log:
        disabled = False

        def note_boundary(self, **kw):
            writes.append(kw)

    class FakeMed:
        phase = SimpleNamespace(name="MAIN_LINE")
        _solo_shadow = Log()
        _solo_shadow_ready = True

        def _solo_shadow_log(self):
            return Mediator._solo_shadow_log(self)
        _solo_shadow_at_boundary = False
        _pending_action = None
        _evolve_feedback_pending = False
        _evolve_awaiting_hero_pick = False
        _equipment_fsm = SimpleNamespace(pending_slot=None)
        _merchant_fsm = SimpleNamespace(phase=None)
        _public_bag_fsm = SimpleNamespace(active=False)
        _panel_state = SimpleNamespace(name="CLOSED")
        _observe_plan = ("bond", "x")
        _l1_cycle_step = "bond"
        _wood_balance = 10
        _skill_points_seen = 0
        _treasure_pending_seen = 0
        _bond_cards_owned = []
        _skill_cards_owned = []
        _bond_cards_pending = []
        _skill_cards_pending = []
        _bond_picks_round = 0
        _main_line_stall_stage = None
        _main_line_stall_reason = None
        _merchant_kill_balance_value = None
        _choice_policy_doc = {}
        settings = SimpleNamespace(auto_bond=True, auto_treasure=True, auto_devour_dan=False, treasure_allow_negative=[])
        _round_started_at = 1.0

        def _passenger_mode(self):
            return False

        def _confirmed_bond_cards(self):
            return ()

        def _confirmed_skill_cards(self):
            return ()

        def _observe_round_id(self):
            return "r"

        def _can_consume_inventory_swallow_pill(self, frame):
            return False

    med = FakeMed()
    Mediator._solo_shadow_tick(med)
    Mediator._solo_shadow_tick(med)
    Mediator._solo_shadow_tick(med)
    assert len(writes) == 1
    # 进入事务
    med._pending_action = object()
    Mediator._solo_shadow_tick(med)
    assert len(writes) == 1
    assert med._solo_shadow_at_boundary is False
    # 事务结束 → 再记一次
    med._pending_action = None
    Mediator._solo_shadow_tick(med)
    assert len(writes) == 2
