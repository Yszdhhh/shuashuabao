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
    ("同页优先级：祝福 > 成长/经济 > 当前高级组 > 其它白名单",
     "Owner 2026-09-26 新口径",
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
    ("高级卡组不设硬门槛：不等基础羁绊 80%、不等开局 480s",
     "Owner 2026-09-23（EX 直通组）；2026-09-24 扩到全部高级卡组",
     "tests/test_choice_policy.py::TestBondTreasureUnknown::test_advanced_bond_has_no_basic_eighty_percent_gate"),
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
    ("基础羁绊同页顺序：祝福 → 成长 → 经济 → 挑战 → 力量线 → 智力线 → 敏捷线 → 其他基础卡（贪婪归其他）；只排勾选的",
     "Owner 2026-09-24（取代 09-15 的经济在祝福前）",
     "tests/test_attribute_bonds_whitelist_20260914.py::test_whitelist_order_blessing_growth_economy_challenge_then_attribute_lines"),
    ("同一时刻只推进一组高级卡组，羁绊栏出现蓝色 EX（海盗为 UR）才解锁下一组",
     "Owner 2026-09-24",
     "tests/test_choice_policy.py::TestBondTreasureUnknown::test_second_advanced_pack_unlocks_after_first_pack_ex"),
    ("EX 靠合成链得到，不从面板拿",
     "Owner 2026-09-24",
     "tests/test_slow_pack_pickup_lock_20260924.py::test_slow_pack_ex_final_is_never_picked_from_the_panel"),
    ("每个高级卡组的白名单都含卡族名本身（海贼王、异火等看到就拿）",
     "Owner 2026-09-26",
     "tests/test_owner_pack_whitelist_lock_20260926.py::test_ticked_pack_whitelist_contains_the_family_name"),
    ("刀刀含 8 件装备、修仙含五极山、海盗含藏宝图",
     "Owner 2026-09-26",
     "tests/test_owner_pack_whitelist_lock_20260926.py::test_owner_named_pack_cards_are_taken"),
    ("高级卡组之间的先后由看板优先级决定",
     "Owner 2026-09-26 03:10",
     "tests/test_owner_pack_whitelist_lock_20260926.py::test_advanced_pack_order_follows_dashboard_priority"),
    ("羁绊刷新耗尽兜底不拿未勾选高级卡组的卡",
     "Owner 2026-09-26 03:33",
     "tests/test_owner_pack_whitelist_lock_20260926.py::test_refresh_fallback_never_takes_an_unticked_advanced_pack"),
    ("羁绊没有放弃：100 木材刷新最多 3 次，还没目标就从当前页按优先级拿一张",
     "Owner 2026-09-26 03:33",
     "tests/test_solo_bond_refresh_limits_20260915.py::test_refresh_exhaustion_selects_best_readable_card_even_outside_whitelist"),
    ("有标签模板的卡族匹配到就直接拿，不做 OCR",
     "Owner 2026-09-26 04:59/05:09",
     "tests/test_direct_family_pick_20260926.py::test_direct_family_pick_obeys_owner_priority_and_skips_rarity_reads"),
    ("同一卡族优先拿高等级卡（徽标 N<R<SR<SSR<UR）",
     "Owner 2026-09-26",
     "tests/test_direct_family_pick_20260926.py::test_direct_family_pick_uses_rarity_only_for_same_priority_ties"),
    ("开局四挑战一次连点再核对，漏了补点（木材漏点要补）",
     "Owner 2026-09-26 04:59/05:09",
     "tests/test_direct_family_pick_20260926.py::test_four_challenge_batch_retries_still_off_wood_immediately"),
    ("木材溢出（≥500）且不缺吞噬丹：不去黑商，专心合 EX",
     "Owner 2026-09-26 03:43",
     "tests/test_solo_r2_issue2_merchant_bypass.py::test_solo_does_not_want_merchant_when_pill_and_wood_are_available"),
    ("装备词条按颜色 橙>紫>蓝>绿>白",
     "Owner 2026-09-25",
     "tests/test_solo_r2_issue6_affix_priority.py::test_equipment_affix_color_hierarchy"),
    ("背包清理看板开关默认关，关着零输入",
     "Owner 2026-09-25",
     "tests/test_backpack_clean_20260925.py::test_backpack_clean_disabled_zero_input"),
    ("背包清理认不出就退出不重试，45 秒未确认即停",
     "Owner 2026-09-25",
     "tests/test_backpack_clean_20260925.py::test_backpack_clean_45s_hard_cap_converges_and_no_retry"),
    ("刀刀/修仙/海盗/亡灵按看板勾选从首卡拿到白名单末卡",
     "Owner 2026-09-24（上线主线：卡组拿取跑通）",
     "tests/test_slow_pack_pickup_lock_20260924.py::test_slow_pack_is_walked_from_first_to_last_card"),
    ("单人默认吃吞噬丹（看板不加开关），羁绊栏空位≤2（≥8/10）就吃（亡灵例外见下）",
     "Owner 2026-09-24；Owner 2026-09-25 改为 ≥8/10（吞噬只腾格子，不影响合成进度）",
     "tests/test_p0_devour_failclosed_20260917.py::test_solo_eats_pill_over_half_even_with_saved_false"),
    ("羁绊栏空位≤2没丹、木材 < 500：插队去黑商，绕一趟回到被打断的步骤",
     "Owner 2026-09-24；Owner 2026-09-25",
     "tests/test_urgent_merchant_20260924.py::test_main_line_tick_detours_to_merchant_when_urgent"),
    ("黑商一步按 H 开店：羁绊栏空位≤2找吞噬丹，木材 < 500 买木材",
     "Owner 2026-09-24；Owner 2026-09-25",
     "tests/test_urgent_merchant_20260924.py::test_merchant_step_opens_the_shop_with_h"),
    ("亡灵卡组进行中（持有亡灵卡、兵主 EX 未出）不吃吞噬丹：提前吞倒计时卡会断碎片",
     "Owner 2026-09-24",
     "tests/test_p0_devour_failclosed_20260917.py::test_undead_pack_in_progress_holds_the_pill"),
    ("木材 < 500 以支线循环为主：F 每次最多 1 张（500–1000 两张，≥1000 十五张）",
     "Owner 2026-09-24",
     "tests/test_solo_l1_starvation_20260915.py::test_wood_tiers_visit_cap"),
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
    # 金条再次亮起：重置 _evolve_ok_this_cycle，且一律不点物品栏
    with patch.object(med, "act_click", return_value=True) as click:
        assert med._maybe_use_inventory_slot(frame, 300.0) is None
        assert med._maybe_use_inventory_item(frame) is None
        assert med._evolve_ok_this_cycle is False
    click.assert_not_called()

    # 进化已完成且金条不再亮起：恢复逐格试用
    med._evolve_ok_this_cycle = True
    with patch.object(med, "_has_evolve_button", return_value=False), \
         patch.object(med, "act_click", return_value=True) as click:
        assert med._maybe_use_inventory_slot(frame, 400.0) is LoopAction.Continue
    assert str(click.call_args.args[1]).startswith("UseInventorySlot")
