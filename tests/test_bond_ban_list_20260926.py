"""Owner 2026-09-26 03:33：羁绊「禁拿卡永远不拿」；刷新耗尽兜底不拿看板未勾选的卡组。"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from shuabao.choice_policy import PolicyAction, SessionState, assemble_policy_settings, choose_action  # noqa: E402
from shuabao.settings import Settings  # noqa: E402
from test_choice_policy import bond_cands, settings, slot  # noqa: E402

DOC = json.loads((ROOT / "config" / "choice_policy.json").read_text(encoding="utf-8"))


def _assembled(**kw):
    base = dict(bonds=["成长", "经济", "贪婪"], cards=[], skills=[])
    base.update(kw)
    return assemble_policy_settings(
        settings=SimpleNamespace(**base), skill_labels={}, fetter_labels={}, policy_doc=DOC,
    )


def test_default_ban_list_is_empty_and_undead_is_not_banned():
    policy = _assembled()
    assert policy.bond_negative_names == ()
    assert "亡灵天灾" in policy.bond_unselected_advanced_names


def test_dashboard_ban_list_is_merged_and_sanitised():
    assert Settings._from_dict({"bond_banned": [" 贪婪 ", "", "贪婪"]}).bond_banned == ["贪婪"]
    assert "贪婪" in _assembled(bond_banned=["贪婪"]).bond_negative_names


def test_banned_card_is_never_taken_on_normal_or_fallback_path():
    policy = settings(bond_presets=["成长", "贪婪"], bond_negative_names=["贪婪"], bond_whitelist_mode="hard")
    normal = choose_action(bond_cands([slot(0, "贪婪"), slot(1, "成长")], settings=policy), SessionState())
    assert (normal.action, normal.index) == (PolicyAction.SELECT_SLOT, 1)

    only_banned = choose_action(bond_cands([slot(0, "贪婪")], settings=policy), SessionState(refreshes=3))
    assert only_banned.action != PolicyAction.SELECT_SLOT


def test_fallback_skips_unticked_packs_but_keeps_owned_progress():
    policy = _assembled()
    decision = choose_action(
        bond_cands([slot(0, "亡灵天灾"), slot(1, "白赚海盗"), slot(2, "固守")], settings=policy),
        SessionState(refreshes=3),
    )
    assert (decision.action, decision.index) == (PolicyAction.SELECT_SLOT, 2)

    only_unticked = choose_action(
        bond_cands([slot(0, "亡灵天灾"), slot(1, "白赚海盗")], settings=policy), SessionState(refreshes=3),
    )
    assert only_unticked.action != PolicyAction.SELECT_SLOT

    # A pack the dashboard ticked is not blocked.
    ticked = _assembled(cards=["亡灵"])
    assert "亡灵天灾" not in ticked.bond_unselected_advanced_names


def test_template_direct_pick_skips_banned_family():
    from shuabao.mediator import Frame, Mediator

    med = Mediator(Settings(dry_run=True, ocr_mode="off"), ROOT)
    policy = settings(bond_presets=["成长", "贪婪"], bond_negative_names=["贪婪"])
    slots_raw = [
        {"index": 0, "name": "贪婪", "template_score": 0.97, "source": "template"},
        {"index": 1, "name": "成长", "template_score": 0.97, "source": "template"},
    ]
    frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8))
    with patch.object(med, "_policy_settings", return_value=policy), \
         patch.object(med, "_confirmed_bond_cards", return_value=()):
        assert med._direct_template_bond_pick(frame, slots_raw) == 1
        assert med._direct_template_bond_pick(frame, slots_raw[:1]) is None
