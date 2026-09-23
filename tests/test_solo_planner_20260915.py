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


def test_high_wood_bonds_preempt_the_skill_backlog() -> None:
    med = _med()
    assert med._bond_base_progress_pending()
    assert _open(med, wood=1800, skill=8, treasure=2) == ["OpenBondPanel"]


def test_small_skill_backlog_keeps_bonds_first_while_wood_lasts() -> None:
    assert _open(_med(), wood=1800, skill=3, treasure=2) == ["OpenBondPanel"]


def test_a_skill_visit_without_a_pick_backs_the_force_off() -> None:
    med = _med()
    med._skill_idle_until = time.time() + 20
    assert _open(med, wood=1800, skill=8, treasure=2) == ["OpenBondPanel"]


def test_low_wood_goes_to_skills() -> None:
    # wood < price (e.g. 10 < 20) skips F and goes to skills
    assert _open(_med(), wood=10, skill=3, treasure=2) == ["OpenSkillPanel"]


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


def test_bond_visit_cap_rotates_and_resumes_at_the_next_bond_step() -> None:
    """轮换走过别的步骤后回到另一个 bond 位再恢复。wood=500 时 cap=2。"""
    med = _med()
    med._round_started_at = time.time() - 300
    med._visit_kind = "bond"
    med._visit_picks = 2
    med._l1_cycle_step = "bond"
    med._l1_cycle_index = 0
    clicks = _open(med, wood=500, skill=2, treasure=0, ticks=1)
    assert clicks == [] and med._l1_cycle_step == "skill", "capped F -> the lock yields"
    assert _open(med, wood=500, skill=2, treasure=0) == ["OpenSkillPanel"]
    med._panel_state = med._panel_state.__class__.CLOSED
    med._l1_cycle_step = "bond"
    med._l1_cycle_index = 2
    assert _open(med, wood=500, skill=2, treasure=0) == ["OpenBondPanel"], "next bond step resumes F"


def test_opening_minute_allows_six_bond_picks_per_visit() -> None:
    med = _med()
    med._round_started_at = time.time() - 30
    med._visit_kind = "bond"
    med._visit_picks = 3
    assert not med._visit_capped("bond")
    med._visit_picks = 6
    assert med._visit_capped("bond")


def test_draw_price_follows_the_live_panel() -> None:
    med = _med()
    prices = []
    for picks in range(7):
        med._bond_picks_round = picks
        prices.append(med._bond_next_price())
    assert prices == [20, 40, 60, 80, 100, 100, 100]


def test_advanced_packs_unlock_after_eight_minutes_even_below_80_percent() -> None:
    med = _med()
    med._round_started_at = time.time() - 100
    assert med._bond_base_progress_pending()
    med._round_started_at = time.time() - 481
    assert not med._bond_base_progress_pending()


def test_new_round_resets_the_plan_state() -> None:
    med = _med()
    med._bond_picks_round = 9
    med._visit_kind = "bond"
    med._visit_picks = 3
    med._skill_points_seen = 30
    med._bond_priority_suspended_at = 0
    med.set_phase(Phase.STAGE_SELECT, "next round")
    med.set_phase(Phase.MAIN_LINE, "new game")
    assert med._bond_picks_round == 0 and med._visit_kind is None
    assert med._skill_points_seen is None and med._bond_priority_suspended_at is None


def _slot(index: int, name: str, conf: float) -> dict:
    return {"index": index, "name": name, "confidence": conf, "raw_text": f"{name}(0/3)", "rec_score": conf, "status": "ok"}


def test_confident_whitelist_bond_is_clicked_on_the_first_frame() -> None:
    """08-29 起选卡要等第二帧同结果；全名命中白名单且 ≥0.95 时单帧直接点。"""
    from shuabao.choice_policy import SlotCandidate

    med = _med()
    med._panel_opened_by_us = "bond"
    med._panel_kind = "bond"
    frame = _frame()
    for conf, expect_click in ((0.99, True), (0.80, False)):
        med._ocr_confirm_key = None
        slots = (SlotCandidate(index=0, name="祝福", confidence=conf), SlotCandidate(index=1, name="刀刀", confidence=0.5))
        with patch.object(med, "_ocr_panel_slots", return_value=[_slot(0, "祝福", conf)]), \
             patch.object(med, "_slots_to_candidates", return_value=slots), \
             patch.object(med, "_panel_can_refresh", return_value=False), \
             patch.object(med, "_panel_has_giveup", return_value=False), \
             patch.object(med, "_extract_live_set_progress", return_value=None), \
             patch.object(med, "_bond_bar_occupancy", return_value=None):
            hit = med._ocr_reward_choice(frame, "bond")
        assert (hit is not None) is expect_click, (conf, hit)
