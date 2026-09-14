# -*- coding: utf-8 -*-
"""单人面板编排（Owner 2026-09-15：前期 羁绊>技能>其它；木材<500 先技能再支线）。

实机 000229：技能角标从 4 涨到 32 一次没点、宝物积压 14，4-5 打不过。
规划顺序：技能积压≥6 → G；基础羁绊<80% 且 F 能推进 → F；否则按轮换，
F 没木材跳过，G/V 角标为 0 跳过；角标读不到时不跳（保持旧行为）。
"""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from shuabao.mediator import Mediator, Phase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "solo_live_20260914"
OWNER = dict(
    bonds=["成长", "经济", "贪婪", "挑战", "祝福"],
    attributes=["int", "agi", "str"],
    cards=["封神", "封神榜", "打神鞭", "杏黄旗", "斩仙飞刀", "法术", "急速", "魔能", "暴击", "魔术"],
)


def _frame() -> Frame:
    image = cv2.imdecode(np.fromfile(str(FIX / "hud_wood_1111_f0200.png"), dtype=np.uint8), cv2.IMREAD_COLOR)
    return Frame(image, window_title="英雄三国KK", hwnd=10001, role="l1")


def _med() -> Mediator:
    med = Mediator(Settings(ocr_mode="off", **OWNER), ROOT)
    med.set_phase(Phase.MAIN_LINE)
    return med


def _open(med: Mediator, *, wood, skill, treasure, ticks: int = 3) -> list[str]:
    clicks: list[str] = []
    with patch.object(med, "_hud_wood_balance", return_value=wood), \
         patch.object(med, "_hud_skill_points", return_value=skill), \
         patch.object(med, "_hud_treasure_pending", return_value=treasure), \
         patch.object(med, "act_click", side_effect=lambda hit, reason, *a, **k: clicks.append(reason) or True):
        for _ in range(ticks):
            if clicks:
                break
            med._wood_next_read_at = 0.0
            med._maybe_open_choice_panel(_frame(), anchor=None)
    return clicks


def test_skill_backlog_preempts_the_early_bond_priority() -> None:
    med = _med()
    assert med._bond_base_progress_pending()
    assert _open(med, wood=1800, skill=8, treasure=2) == ["OpenSkillPanel"]


def test_small_skill_backlog_keeps_bonds_first_while_wood_lasts() -> None:
    assert _open(_med(), wood=1800, skill=3, treasure=2) == ["OpenBondPanel"]


def test_a_skill_visit_without_a_pick_backs_the_force_off() -> None:
    med = _med()
    med._skill_idle_until = time.time() + 20
    assert _open(med, wood=1800, skill=8, treasure=2) == ["OpenBondPanel"]


def test_low_wood_goes_to_skills() -> None:
    assert _open(_med(), wood=300, skill=3, treasure=2) == ["OpenSkillPanel"]


def test_zero_badges_skip_skill_and_treasure_steps() -> None:
    med = _med()
    med._l1_cycle_step = "skill"
    med._l1_cycle_index = 3
    clicks = _open(med, wood=300, skill=0, treasure=0, ticks=1)
    assert clicks == []
    assert med._l1_cycle_step == "treasure"
    clicks = _open(med, wood=300, skill=0, treasure=0, ticks=1)
    assert clicks == [] and med._l1_cycle_step == "evolve", "V 角标 0 → 直接去进化"


def test_pending_treasure_is_opened_on_its_step() -> None:
    med = _med()
    med._l1_cycle_step = "treasure"
    med._l1_cycle_index = 4
    assert _open(med, wood=300, skill=0, treasure=5) == ["OpenTreasurePanel"]


def test_unreadable_badges_never_skip_a_step() -> None:
    med = _med()
    med._l1_cycle_step = "skill"
    assert _open(med, wood=300, skill=None, treasure=None) == ["OpenSkillPanel"]


def test_skill_visit_without_selection_arms_the_idle_backoff() -> None:
    from shuabao.mediator import PanelState

    med = _med()
    med._panel_kind = "skill"
    med._panel_state = PanelState.COOLDOWN
    med._l1_cycle_owned_panel = True
    med._l1_cycle_selected = False
    med._finish_panel_episode()
    assert med._skill_idle_until > time.time() + 20
