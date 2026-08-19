from __future__ import annotations

import json
from pathlib import Path

from shuabao.settings import Settings
from shuabao.smart_route import (
    RouteEvaluator,
    SkillRole,
    assign_skill_roles,
    skill_role_rank,
)


LABELS = {
    "carry": "主炮",
    "amp1": "光线",
    "amp2": "射线",
    "amp3": "剑气",
}
KNOWLEDGE = {
    "family_to_code": {value: key for key, value in LABELS.items()},
    "cards": [
        {
            "name": "主炮终极",
            "family": "主炮",
            "effect": "主炮伤害+80%，进化为终极大招",
        },
        {
            "name": "光线易伤",
            "family": "光线",
            "effect": "被光线命中的敌人受伤+25%，持续3秒",
        },
        {
            "name": "光线终极",
            "family": "光线",
            "effect": "光线伤害+100%，进化为终极光束",
        },
        {
            "name": "双系增幅",
            "family": "射线",
            "effect": "主炮与射线伤害+50%",
        },
    ],
}


def test_highest_archive_level_becomes_carry_and_tie_uses_selection_order():
    roles = assign_skill_roles(
        ["carry", "amp1", "amp2", "amp3"],
        {"carry": 47, "amp1": 12, "amp2": 30, "amp3": 8},
        skill_labels=LABELS,
        knowledge_doc=KNOWLEDGE,
    )
    assert len(roles) == 4
    assert roles[0].role is SkillRole.CARRY
    assert roles[0].archive_level == 47
    assert all(item.role is SkillRole.AMPLIFIER for item in roles[1:])

    tied = assign_skill_roles(
        ["amp2", "carry", "amp1", "amp3"],
        {"amp2": 47, "carry": 47},
        skill_labels=LABELS,
        knowledge_doc=KNOWLEDGE,
    )
    assert tied[0].code == "amp2"
    assert tied[0].role is SkillRole.CARRY


def test_amplifier_support_is_upweighted_and_own_ultimate_is_downweighted():
    selected = ("主炮", "光线", "射线", "剑气")
    levels = {"主炮": 47, "光线": 12, "射线": 30, "剑气": 8}

    assert skill_role_rank(
        "光线易伤", selected, levels, knowledge_doc=KNOWLEDGE
    ) == 0
    assert skill_role_rank(
        "双系增幅", selected, levels, knowledge_doc=KNOWLEDGE
    ) == 0
    assert skill_role_rank(
        "光线终极", selected, levels, knowledge_doc=KNOWLEDGE
    ) == 2
    assert skill_role_rank(
        "主炮终极", selected, levels, knowledge_doc=KNOWLEDGE
    ) == 0


def test_disabled_amplifier_returns_to_neutral_ranking():
    selected = ("主炮", "光线", "射线", "剑气")
    levels = {"主炮": 47, "光线": 12, "射线": 30, "剑气": 8}
    assert skill_role_rank(
        "光线易伤",
        selected,
        levels,
        disabled_amplifiers=("光线",),
        knowledge_doc=KNOWLEDGE,
    ) == 1


def test_role_weight_is_neutral_until_exactly_four_skills_are_selected():
    assert skill_role_rank(
        "光线易伤",
        ("主炮", "光线", "射线"),
        {"主炮": 47},
        knowledge_doc=KNOWLEDGE,
    ) == 1


def test_route_evaluator_returns_official_match_then_adaptive_route():
    evaluator = RouteEvaluator(
        official_builds=(
            {
                "id": "arcane_open",
                "name": "奥术开荒",
                "skills": ["carry", "amp1", "amp2", "amp3"],
                "cards": ["zhili", "yanmiezhe"],
            },
        ),
        attr_routes={
            "intelligence": {
                "fetter_code": "zhili",
                "chain": ["yanmiezhe"],
            },
            "strength": {
                "fetter_code": "liliang",
                "chain": ["tuluzhe"],
            },
        },
        skill_labels=LABELS,
        knowledge_doc=KNOWLEDGE,
    )
    result = evaluator.evaluate(
        ["carry", "amp1", "amp2", "amp3"],
        {"carry": 47, "amp1": 12, "amp2": 30, "amp3": 8},
    )

    assert result.carry is not None
    assert result.carry.code == "carry"
    assert 1 <= len(result.recommendations) <= 2
    assert result.recommendations[0].build_id == "arcane_open"
    assert result.recommendations[0].exact_match is True
    assert "intelligence" in result.relevant_attr_routes
    assert result.recommendations[-1].name.startswith("自适应")


def test_smart_route_disabled_amplifiers_round_trip_and_sanitize():
    settings = Settings._from_dict(
        {
            "skills": ["asj", "asjg", "assx", "jq"],
            "smart_route_disabled_amplifiers": [
                "assx", "asjg", "assx", "", "jq", "extra",
            ],
        }
    )
    assert settings.smart_route_disabled_amplifiers == ["assx", "asjg", "jq", "extra"]

    restored = Settings._from_dict(
        {
            "skills": settings.skills,
            "smart_route_disabled_amplifiers": settings.smart_route_disabled_amplifiers,
        }
    )
    assert restored.smart_route_disabled_amplifiers == settings.smart_route_disabled_amplifiers


def test_verified_catalog_arcane_four_role_smoke():
    root = Path(__file__).resolve().parents[2]
    knowledge = json.loads(
        (root / "config" / "skill_card_knowledge.json").read_text(encoding="utf-8")
    )
    labels = json.loads(
        (root / "config" / "skill_labels.json").read_text(encoding="utf-8")
    )
    selected_codes = ("asj", "asjg", "assx", "jq")
    selected_families = tuple(labels[code] for code in selected_codes)
    levels = {"asj": 47, "asjg": 12, "assx": 30, "jq": 8}

    roles = assign_skill_roles(
        selected_codes,
        levels,
        skill_labels=labels,
        knowledge_doc=knowledge,
    )
    assert roles[0].code == "asj"
    assert roles[0].role is SkillRole.CARRY

    # Verified real cards: amplifier utility is promoted; its own ultimate is demoted.
    assert skill_role_rank(
        "瓦解光线",
        selected_families,
        levels,
        knowledge_doc=knowledge,
    ) == 0
    assert skill_role_rank(
        "奥能洪流",
        selected_families,
        levels,
        knowledge_doc=knowledge,
    ) == 2
    assert skill_role_rank(
        "奥术增幅β",
        selected_families,
        levels,
        knowledge_doc=knowledge,
    ) == 0
