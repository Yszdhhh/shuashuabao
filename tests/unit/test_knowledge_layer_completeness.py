import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_unified_skill_card_knowledge_contains_catalog_unlocks_and_evidence_status():
    """Verify the unified layer carries catalog cards, unlocks, and explicit rarity uncertainty."""
    data = json.loads((ROOT / "config" / "skill_card_knowledge.json").read_text(encoding="utf-8"))
    assert data["card_count"] == 220
    assert len(data["cards"]) == 220
    assert data["skill_family_count"] == 16
    assert data["rarity"]["rows"] == 220
    assert data["rarity"]["evidence_backed_rows"] == 213
    assert data["rarity"]["unverified_rows"] == 7

    arcane = next(card for card in data["cards"] if card["name"] == "奥术箭矢")
    # 图标对齐：奥术箭矢卡面是普攻弓箭图标 → family=普攻；跨系协同只留在 prereq。
    assert arcane["family"] == "普攻"
    assert arcane["prereq"] == "普攻,奥术箭"
    assert arcane["effect"]
    assert "prereq" in arcane
    assert "rarity" in arcane


def test_unified_bond_knowledge_preserves_effects_needs_and_uncertainty():
    data = json.loads((ROOT / "config" / "bond_knowledge.json").read_text(encoding="utf-8"))
    assert data["needs_count"] == 66
    assert data["tree_count"] > 0
    assert data["labels_count"] == 36
    assert data["rarity"]["status"] == "unverified"
    assert data["rarity"]["reason"]
    assert data["bond_priority"]
