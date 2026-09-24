# -*- coding: utf-8 -*-
"""封神高级卡组必须完整包含真实出现的「肉身成圣」。"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from shuabao.choice_policy import assemble_policy_settings
from shuabao.mediator import Mediator
from shuabao.settings import Settings
from shuabao.vision.capture import Frame

ROOT = Path(__file__).resolve().parents[1]
REAL_FRAME = ROOT / "tests" / "fixtures" / "solo_live_20260914" / "fengshen_roushen_f0245.png"


def _policy(*, cards: list[str], attributes: list[str] | None = None):
    doc = json.loads((ROOT / "config" / "choice_policy.json").read_text(encoding="utf-8"))
    return assemble_policy_settings(
        settings=Settings(cards=cards, attributes=attributes or []),
        skill_labels={},
        fetter_labels={},
        policy_doc=doc,
    )


def test_selecting_one_fengshen_member_expands_the_catalog_group_only() -> None:
    policy = _policy(cards=["封神"], attributes=["int"])
    fengshen = ("封神", "封神榜", "打神鞭", "杏黄旗", "斩仙飞刀", "肉身成圣")
    assert all(name in policy.bond_presets for name in fengshen)
    assert all(name in policy.bond_advanced_presets for name in fengshen)
    assert any(set(fengshen).issubset(group) for group in policy.bond_advanced_groups)
    for chain_name in ("秘法师", "法神", "湮灭者"):
        assert chain_name in policy.bond_chain_presets
        assert chain_name not in policy.bond_advanced_presets


def test_real_f0245_selects_roushen_when_fengshen_pack_is_active() -> None:
    image = cv2.imdecode(np.fromfile(str(REAL_FRAME), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    med = Mediator(Settings(ocr_mode="live", cards=["封神"], bonds=[], attributes=[]), ROOT)
    choice = med._find_reward_choice(Frame(image))
    assert choice is not None
    kind, hit = choice
    assert kind == "bond"
    assert "肉身成圣" in hit.name


def test_real_f0245_reads_card_rarity_badge_letters_and_bands() -> None:
    image = cv2.imdecode(np.fromfile(str(REAL_FRAME), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    med = Mediator(Settings(ocr_mode="live", cards=["封神"], bonds=[], attributes=[]), ROOT)
    slots = med._ocr_panel_slots(Frame(image), "bond")
    assert len(slots) == 4
    letters = [s.get("rarity_letter") for s in slots]
    bands = [s.get("rarity") for s in slots]
    assert letters == ["SR", "R", "N", "R"]
    assert bands == ["purple", "blue", "green", "blue"]

