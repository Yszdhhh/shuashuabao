"""Owner 2026-09-26 03:03：三国四选三。

魏、蜀、吴、群雄四选三：哪国先出来就先拿该国启动卡，拿满 3 国后不再拿第四国。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from shuabao.choice_policy import (  # noqa: E402
    PolicyAction,
    SessionState,
    assemble_policy_settings,
    choose_action,
    sanguo_blocked_faction,
    sanguo_faction,
)
from test_choice_policy import bond_cands, settings, slot  # noqa: E402

FACTION_PRESETS = ["三国", "魏", "曹操", "司马懿", "蜀", "刘备", "赵云", "吴", "孙权", "孙策", "群雄", "董卓", "吕布"]
THREE_FACTIONS = ("曹操", "刘备(1/3)", "孙权")


def _policy():
    return settings(bond_presets=FACTION_PRESETS, bond_whitelist_mode="hard")


def test_faction_lookup_is_exact_identity():
    assert sanguo_faction("曹操") == "魏"
    assert sanguo_faction("刘备(2/3)") == "蜀"
    assert sanguo_faction("群雄") == "群雄"
    assert sanguo_faction("魏延") is None
    assert sanguo_faction("贪婪") is None


def test_first_faction_starter_is_taken_when_sanguo_ticked():
    decision = choose_action(
        bond_cands([slot(0, "贪婪"), slot(1, "董卓")], settings=_policy(), owned_bond_cards=()),
        SessionState(),
    )
    assert (decision.action, decision.index) == (PolicyAction.SELECT_SLOT, 1)


def test_third_faction_is_still_taken_with_two_owned():
    decision = choose_action(
        bond_cands([slot(0, "董卓")], settings=_policy(), owned_bond_cards=("曹操", "刘备")),
        SessionState(),
    )
    assert (decision.action, decision.index) == (PolicyAction.SELECT_SLOT, 0)


def test_fourth_faction_is_never_taken_once_three_are_owned():
    policy = _policy()
    assert sanguo_blocked_faction("董卓", THREE_FACTIONS)
    assert not sanguo_blocked_faction("司马懿", THREE_FACTIONS)

    # Owned faction keeps being collected; the fourth faction is skipped.
    decision = choose_action(
        bond_cands([slot(0, "董卓"), slot(1, "司马懿")], settings=policy, owned_bond_cards=THREE_FACTIONS),
        SessionState(),
    )
    assert (decision.action, decision.index) == (PolicyAction.SELECT_SLOT, 1)

    # Refresh budget spent: the fallback still skips the fourth faction.
    decision = choose_action(
        bond_cands([slot(0, "吕布"), slot(1, "贪婪")], settings=policy, owned_bond_cards=THREE_FACTIONS),
        SessionState(refreshes=3),
    )
    assert (decision.action, decision.index) == (PolicyAction.SELECT_SLOT, 1)

    # A page with only fourth-faction cards never selects one.
    decision = choose_action(
        bond_cands([slot(0, "吕布"), slot(1, "群雄")], settings=policy, owned_bond_cards=THREE_FACTIONS),
        SessionState(refreshes=3),
    )
    assert decision.action != PolicyAction.SELECT_SLOT


def test_ticking_sanguo_whitelists_every_faction_card():
    doc = json.loads((ROOT / "config" / "choice_policy.json").read_text(encoding="utf-8"))
    policy = assemble_policy_settings(
        settings=SimpleNamespace(bonds=["三国"], cards=[], skills=[]),
        skill_labels={},
        fetter_labels={},
        policy_doc=doc,
    )
    presets = policy.bond_presets
    assert "三国" in presets
    for name in ("魏", "曹操", "蜀", "刘备", "吴", "孙权", "群雄", "董卓"):
        assert name in presets, name


def test_template_direct_pick_skips_the_fourth_faction():
    from shuabao.mediator import Frame, Mediator, Settings
    import numpy as np

    med = Mediator(Settings(dry_run=True, ocr_mode="off"), ROOT)
    policy = _policy()
    slots_raw = [
        {"index": 0, "name": "群雄", "template_score": 0.97, "source": "template"},
        {"index": 1, "name": "魏", "template_score": 0.97, "source": "template"},
    ]
    frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8))
    with patch.object(med, "_policy_settings", return_value=policy), \
         patch.object(med, "_confirmed_bond_cards", return_value=THREE_FACTIONS):
        assert med._direct_template_bond_pick(frame, slots_raw) == 1
    with patch.object(med, "_policy_settings", return_value=policy), \
         patch.object(med, "_confirmed_bond_cards", return_value=THREE_FACTIONS):
        assert med._direct_template_bond_pick(frame, slots_raw[:1]) is None
