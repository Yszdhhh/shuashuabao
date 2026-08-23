"""skill_routes.json v2 校验：顶层 routes 键兼容 _load_skill_routes，families 标签真实存在于知识库。"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_v2() -> dict:
    return json.loads((ROOT / "config" / "skill_routes.json").read_text(encoding="utf-8"))


def _knowledge_family_text() -> dict[str, str]:
    kb = json.loads((ROOT / "config" / "skill_card_knowledge.json").read_text(encoding="utf-8"))
    text: dict[str, str] = {}
    for card in kb["cards"]:
        text.setdefault(card["family"], "")
        text[card["family"]] += f"{card['name']} {card['effect']} "
    return text


def test_top_level_routes_key_loads_like_main_window():
    data = _load_v2()
    routes = data.get("routes")
    assert isinstance(routes, dict) and routes
    parsed = {str(k): str(v) for k, v in routes.items()}
    assert set(parsed) == {
        "pg", "asj", "asjg", "assx", "tl", "sdl", "dcw", "hq",
        "byj", "hbj", "bsxx", "jf", "ljf", "jq", "dz", "ys",
    }
    assert all(isinstance(v, str) and "/" in v for v in parsed.values())


def test_every_family_has_at_least_two_routes():
    data = _load_v2()
    families = data["families"]
    code_to_family = {
        code: name for name, code in json.loads(
            (ROOT / "config" / "skill_card_knowledge.json").read_text(encoding="utf-8")
        )["family_to_code"].items()
    }
    assert set(families) == set(code_to_family)
    for slug, fam in families.items():
        assert fam["name"] == code_to_family[slug]
        assert len(fam["routes"]) >= 2
        for route in fam["routes"]:
            assert route["id"] and route["label"]
            assert isinstance(route["prefer"], list)
            assert isinstance(route["avoid"], list)


def test_all_tags_exist_in_family_knowledge_text():
    data = _load_v2()
    family_text = _knowledge_family_text()
    missing: list[str] = []
    for slug, fam in data["families"].items():
        text = family_text[fam["name"]]
        for route in fam["routes"]:
            for tag in route["prefer"] + route["avoid"]:
                if tag not in text:
                    missing.append(f"{slug}/{route['id']}: {tag}")
    assert not missing, f"知识库该族效果原文中不存在的标签: {missing}"
