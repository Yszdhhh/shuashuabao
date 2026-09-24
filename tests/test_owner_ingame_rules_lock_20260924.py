"""Owner 局内规则锁（2026-09-24）。

Owner 反复指出：写好的局内规则在一轮轮架构收敛里被悄悄删掉。这里做两件事：
1. 给还没有行为测试的规则补上（目前是「英雄卡前先点完进化」的物品栏路径）；
2. 登记表 OWNER_RULES：每条规则指向锁住它的行为测试。删规则会让那条测试
   变红；删测试本身会让 test_every_owner_rule_has_a_live_lock 变红。

清单正文见 docs/CURRENT_STATUS_AND_HANDOFF_20260924_UNIFIED.md「Owner 局内规则锁」。
改动或废止一条规则，必须同时改登记表并写明 Owner 原话日期。
"""
from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
import pytest

from shuabao.mediator import LoopAction, Mediator
from shuabao.runtime_mediator import Mediator as RuntimeMediator
from shuabao.settings import Settings
from shuabao.vision.capture import Frame

ROOT = Path(__file__).resolve().parents[1]
# 真机 2026-09-14：「点击进化」金条亮着，物品栏 2–6 五格全满。
EVOLVE_LIT_FULL_BAR = ROOT / "tests/fixtures/solo_live_20260914/f0581_action_before.png"

# (规则, Owner 来源与日期, 锁定测试 "路径::[类::]函数")
OWNER_RULES: tuple[tuple[str, str, str], ...] = (
    ("英雄卡使用前先把点击进化用完：金条亮着或进化未闭环时物品栏零点击",
     "B8-3 2026-08-10；Owner 2026-09-24 重申",
     "tests/test_owner_ingame_rules_lock_20260924.py::test_rule_evolve_before_item_bar_while_evolve_bar_is_lit"),
    ("英雄卡模板路径同样要求进化已确认",
     "B8-3 2026-08-10",
     "tests/test_solo_gt_regression_20260916.py::test_opportunistic_hero_card_evolve_gate_enforcement"),
    ("看板丢失（羁绊/技能/宝物栏不见）两帧确认后按 F1，不按 F2",
     "Owner 2026-09-24（纠正 09-15 的 F2）",
     "tests/test_solo_l1_starvation_20260915.py::test_monster_selected_during_bond_cooldown_gets_f1_hero_focus"),
    ("战斗主画面（打怪/Boss、存档/传家宝广场）飞走按 F2 返回阵地",
     "Owner 2026-09-24",
     "tests/test_battle_view_f2_20260924.py::test_main_line_tick_reaches_the_battle_view_check"),
    ("木材 < 500 且技能积压：先点技能",
     "Owner 2026-09-15，2026-09-24 定 500（待实机调）",
     "tests/unit/test_bond_priority_scheduling.py::TestBondPriorityScheduling::test_low_wood_with_skill_backlog_clicks_skills_first"),
    ("木材 ≥ 500 且基础羁绊未成型：先点羁绊（羁绊是主要战力）",
     "Owner 2026-09-20 优先羁绊；2026-09-24",
     "tests/unit/test_bond_priority_scheduling.py::TestBondPriorityScheduling::test_bond_first_from_500_wood_while_base_pending"),
    ("木材充足（≥1000）时羁绊压过技能积压",
     "Owner 2026-09-15",
     "tests/test_solo_planner_20260915.py::test_high_wood_bonds_preempt_the_skill_backlog"),
    ("预设基础羁绊与高级羁绊同页：先拿基础",
     "Owner 2026-09-24（80% 比例待实机调）",
     "tests/test_choice_policy.py::TestBondTreasureUnknown::test_missing_basic_bond_beats_advanced_on_the_same_page"),
    ("宝物在自己那一步能打开，不被 F 饿死",
     "Owner 2026-09-15",
     "tests/test_solo_planner_20260915.py::test_pending_treasure_is_opened_on_its_step"),
    ("拿齐预设后 F 整局不关（重复卡升级/合成）",
     "Owner 2026-09-24 审查恢复",
     "tests/unit/test_bond_priority_scheduling.py::TestBondPriorityScheduling::test_runtime_bond_presets_never_complete_the_round"),
    ("技能面板点真正的【刷新(N)】，不点「刷新次数+1」文字",
     "Owner 2026-09-24",
     "tests/contract/test_skill_refresh_btn_priority_contract.py::SkillRefreshClicksRealButton::test_giveup_panel_fixture_clicks_real_refresh_button"),
    ("满槽顶替只点 OCR 认出的非目标卡，认不出零输入",
     "AGENTS.md §5；Owner 2026-09-24 审查",
     "tests/test_bond_replace_and_hero_focus_20260924.py::test_bond_slot_replacement_never_guesses_unread_slots"),
    ("负面宝物默认不拿（OCR 读不到描述也拦）",
     "Owner 2026-09-22",
     "tests/contract/test_treasure_negative_fixtures_contract.py::TreasureNegativeNameAndDescription::test_default_negative_names_blocked_even_with_empty_description"),
    ("EX 宝物出现就拿，不受品质采样约束",
     "Owner 2026-09-15",
     "tests/test_choice_policy.py::TestTreasureMustTake::test_legacy_substring_privilege_ignores_quality"),
    ("已选 EX 卡组持续推进，不被基础 80% 阻挡",
     "Owner 2026-09-23",
     "tests/test_choice_policy.py::TestBondTreasureUnknown::test_selected_simple_ex_families_progress_before_base_eighty_percent"),
    ("单人物品栏满时 2–6 格左键试用（进化不可用时）",
     "Owner 2026-09-23",
     "tests/test_live_run_205044_regressions.py::LiveRun205044Tests::test_live_20260923_full_item_bar_is_used_without_evolution"),
    ("蹭车不动物品栏（队伍资产）",
     "Owner 2026-09-23",
     "tests/test_live_run_205044_regressions.py::LiveRun205044Tests::test_full_item_bar_stays_untouched_in_passenger_mode"),
    ("打不过自动降级：连续失败后选关目标降一级",
     "Owner 2026-09-15",
     "tests/test_solo_b9_downgrade_20260915.py::test_two_failures_downgrade_the_next_stage_target"),
    ("KK 平台弹窗先 Esc，关不掉再点叉",
     "Owner 2026-09-24",
     "tests/test_b15da05_real_regressions.py::test_real_platform_modal_uses_x_only_after_fresh_esc_reobserve"),
)


def _load(path: Path) -> Frame:
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None, path
    return Frame(image, window_title="英雄三国KK", hwnd=10001, role="l1")


def _defined_tests(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names.add(f"{node.name}::{item.name}")
    return names


def test_every_owner_rule_has_a_live_lock() -> None:
    missing = []
    for rule, source, node in OWNER_RULES:
        file_part, _, name = node.partition("::")
        path = ROOT / file_part
        if not path.is_file() or name not in _defined_tests(path):
            missing.append(f"{rule}（{source}）→ {node}")
    assert not missing, "Owner 规则的锁定测试被删除或改名：\n" + "\n".join(missing)


@pytest.mark.parametrize("cls", [Mediator, RuntimeMediator])
def test_rule_evolve_before_item_bar_while_evolve_bar_is_lit(cls) -> None:
    """Owner：英雄卡使用前先把点击进化用完（B8-3 2026-08-10，2026-09-24 重申）。

    逐格左键认不出哪格是英雄卡，所以金条亮着时物品栏一格都不点；进化闭环后
    才恢复逐格试用。
    """
    med = cls(Settings(ocr_mode="off"), ROOT)
    frame = _load(EVOLVE_LIT_FULL_BAR)
    assert med._has_evolve_button(frame)
    assert med._hud_item_bar_occupied_count(frame) == 5

    with patch.object(med, "act_click", return_value=True) as click:
        assert med._maybe_use_inventory_slot(frame, 100.0) is None
        assert med._maybe_use_inventory_item(frame) in (None, LoopAction.Continue)
    assert not [c for c in click.call_args_list if str(c.args[1]).startswith("UseInventory")]

    med._evolve_awaiting_hero_pick = True
    with patch.object(med, "act_click", return_value=True) as click:
        assert med._maybe_use_inventory_slot(frame, 200.0) is None
    click.assert_not_called()

    med._evolve_awaiting_hero_pick = False
    med._evolve_ok_this_cycle = True
    with patch.object(med, "act_click", return_value=True) as click:
        assert med._maybe_use_inventory_slot(frame, 300.0) is LoopAction.Continue
    assert str(click.call_args.args[1]).startswith("UseInventorySlot")
