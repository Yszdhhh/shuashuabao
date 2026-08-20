"""MechanicsPolicyView isolation tests — drive the shipped class, not a copy."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shuabao.policy.mechanics_view import MechanicsPolicyView

ROOT = Path(__file__).resolve().parents[2]


def _gated(**extra):
    body = {"live_verified": True, "wired_to_decision": True}
    body.update(extra)
    return body


def test_dual_gated_chain_and_card_are_returned():
    view = MechanicsPolicyView(
        {
            "chains": {
                "sword": _gated(
                    prerequisites=["基础剑气", "剑气强化"],
                    mutually_exclusive=["法杖"],
                )
            },
            "cards": {"巨型剑气": _gated(priority_modifier=1.5)},
            "auto_actions": {"EnableAutoTask": _gated(safe=True)},
        }
    )
    assert view.get_prerequisites("sword") == ["基础剑气", "剑气强化"]
    assert view.get_mutually_exclusive("sword") == ["法杖"]
    assert view.get_priority_modifier("巨型剑气") == pytest.approx(1.5)
    assert view.is_safe_auto_action("EnableAutoTask") is True


def test_guide_conflicts_and_unverified_flags_fail_closed():
    view = MechanicsPolicyView(
        {
            "guide": {
                "sword": _gated(prerequisites=["攻略前置"]),
            },
            "conflicts": {
                "sword": _gated(mutually_exclusive=["攻略互斥"]),
            },
            "chains": {
                "from_guide": {
                    "live_verified": True,
                    "wired_to_decision": True,
                    "guide": {"prerequisites": ["不该出现"]},
                    "conflicts": ["不该出现"],
                    "prerequisites": ["真前置"],
                },
                "unverified": {
                    "live_verified": False,
                    "wired_to_decision": True,
                    "prerequisites": ["未验证"],
                },
                "unwired": {
                    "live_verified": True,
                    "wired_to_decision": False,
                    "prerequisites": ["未接线"],
                    "mutually_exclusive": ["未接线互斥"],
                },
                "nested_verified": {
                    "live_verified": {"lab": True, "note": "实机对象不是布尔"},
                    "wired_to_decision": True,
                    "prerequisites": ["嵌套不算 True"],
                },
                "missing_flags": {"prerequisites": ["缺旗"]},
            },
            "cards": {
                "攻略卡": {
                    "live_verified": True,
                    "wired_to_decision": False,
                    "priority_modifier": 9.9,
                },
                "对象验证卡": {
                    "live_verified": {"ocr": True},
                    "wired_to_decision": True,
                    "priority_modifier": 3.0,
                },
            },
            "auto_actions": {
                "risky": {
                    "live_verified": True,
                    "wired_to_decision": True,
                    "safe": False,
                },
                "unwired_click": {
                    "live_verified": True,
                    "wired_to_decision": False,
                    "safe": True,
                },
            },
        }
    )
    assert view.get_prerequisites("from_guide") == ["真前置"]
    assert view.get_prerequisites("unverified") == []
    assert view.get_prerequisites("unwired") == []
    assert view.get_prerequisites("nested_verified") == []
    assert view.get_prerequisites("missing_flags") == []
    assert view.get_mutually_exclusive("unwired") == []
    assert view.get_priority_modifier("攻略卡") == 0.0
    assert view.get_priority_modifier("对象验证卡") == 0.0
    assert view.get_priority_modifier("missing") == 0.0
    assert view.is_safe_auto_action("risky") is False
    assert view.is_safe_auto_action("unwired_click") is False
    assert view.is_safe_auto_action("EnableAutoTask") is False


def test_corrupt_json_and_non_dict_schema_never_raise(tmp_path: Path):
    bad_file = tmp_path / "broken.json"
    bad_file.write_text("{not json", encoding="utf-8")
    assert MechanicsPolicyView.from_path(bad_file).get_prerequisites("x") == []
    assert MechanicsPolicyView.from_path(tmp_path / "missing.json").is_safe_auto_action("x") is False

    for payload in (
        None,
        [],
        "[]",
        123,
        b"null",
        {"chains": ["not-a-map"]},
        {"cards": "nope"},
        {"auto_actions": 1},
        {"facts": "bad"},
    ):
        view = MechanicsPolicyView(payload)
        assert view.get_prerequisites("any") == []
        assert view.get_mutually_exclusive("any") == []
        assert view.get_priority_modifier("any") == 0.0
        assert view.is_safe_auto_action("any") is False


def test_getters_are_pure_and_return_copies():
    view = MechanicsPolicyView(
        {"chains": {"c": _gated(prerequisites=["a", "b"], mutually_exclusive=["z"])}}
    )
    first = view.get_prerequisites("c")
    first.append("mutated")
    assert view.get_prerequisites("c") == ["a", "b"]
    mutex = view.get_mutually_exclusive("c")
    mutex.clear()
    assert view.get_mutually_exclusive("c") == ["z"]
    with pytest.raises(AttributeError):
        view._prereqs = {}  # type: ignore[misc]


def test_temp_kb_file_roundtrip(tmp_path: Path):
    path = tmp_path / "game_mechanics_kb.json"
    path.write_text(
        json.dumps(
            {
                "wired_to_decision": False,
                "chains": {
                    "arcane": _gated(prerequisites=["奥术箭矢"], mutually_exclusive=["磁暴"])
                },
                "cards": {"奥术箭矢": _gated(priority_modifier=0.25)},
                "auto_actions": {"press_f4": _gated(is_safe_auto_action=True)},
                "guide": {"arcane": _gated(prerequisites=["攻略"])},
            }
        ),
        encoding="utf-8",
    )
    view = MechanicsPolicyView.from_path(path)
    assert view.get_prerequisites("arcane") == ["奥术箭矢"]
    assert view.get_mutually_exclusive("arcane") == ["磁暴"]
    assert view.get_priority_modifier("奥术箭矢") == pytest.approx(0.25)
    assert view.is_safe_auto_action("press_f4") is True
    assert view.get_prerequisites("missing") == []


def test_production_kb_is_fail_closed_until_boolean_flags():
    view = MechanicsPolicyView.from_repo(ROOT)
    assert view.get_prerequisites("skill_choice_mode") == []
    assert view.get_mutually_exclusive("asymmetric_exclude") == []
    assert view.get_priority_modifier("审判之雷") == 0.0
    assert view.is_safe_auto_action("clear_challenge_f4") is False


def test_string_true_and_int_flags_are_not_boolean_true():
    view = MechanicsPolicyView(
        {
            "chains": {
                "s": {
                    "live_verified": "true",
                    "wired_to_decision": 1,
                    "prerequisites": ["假"],
                }
            },
            "cards": {
                "c": {
                    "live_verified": True,
                    "wired_to_decision": "true",
                    "priority_modifier": 4,
                }
            },
        }
    )
    assert view.get_prerequisites("s") == []
    assert view.get_priority_modifier("c") == 0.0
