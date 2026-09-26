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
from shuabao.choice_policy import PanelCandidates, PolicyAction, PolicySettings, SessionState, SlotCandidate, choose_action

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
    ("祝福套装未凑满（need=3）前同页必拿且优先于成长/经济/高级组（已有1、2张时仍优先）",
     "Owner 2026-09-26（恢复口径）",
     "tests/test_owner_ingame_rules_lock_20260924.py::test_blessing_uncompleted_beats_growth_economy_and_advanced_on_same_page"),
    ("三国四选三：哪国先出先拿该国启动卡，拿满 3 国后不再拿第四国",
     "Owner 2026-09-26 03:03",
     "tests/test_sanguo_three_of_four_20260926.py::test_fourth_faction_is_never_taken_once_three_are_owned"),
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
    ("羁绊禁拿卡永远不拿（禁拿名单默认空，看板可配；常规、模板直拿、兜底都排除）",
     "Owner 2026-09-26 03:33",
     "tests/test_bond_ban_list_20260926.py::test_banned_card_is_never_taken_on_normal_or_fallback_path"),
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
    ("亡灵卡组进行中不为吞噬丹去黑商：_devour_hold_reason 判定 hold 时不因缺丹占格≥8去黑商",
     "Owner 2026-09-26（恢复口径）",
     "tests/test_owner_ingame_rules_lock_20260924.py::test_undead_pack_in_progress_does_not_visit_merchant_for_pill"),
    ("吞噬丹暂停只对亡灵：属性链等其它卡组照常拿、照常吃丹",
     "Owner 2026-09-26 06:57 原话：正常应该是专心做亡灵这一个高级 agent 的时候停止使用吞噬丹，"
     "等他自行时间到触发碎片获取。其他的都没有这个逻辑正常拿就好了，属性跟吞噬丹一直都没有什么冲突呀",
     "tests/test_attribute_line_protection_20260926.py::test_devour_is_not_held_by_attribute_chains"),
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

def test_blessing_uncompleted_beats_growth_economy_and_advanced_on_same_page() -> None:
    """Owner 2026-09-26：祝福套装未凑满（need=3）前，已有1、2张时同页祝福仍优先于成长/经济/高级卡组。"""
    settings = PolicySettings(
        bond_presets=("祝福", "成长", "经济", "齐天大圣", "大圣残躯"),
        bond_base_presets=("祝福", "成长", "经济"),
        bond_advanced_presets=("齐天大圣", "大圣残躯"),
        bond_advanced_groups=(("齐天大圣", "大圣残躯"),),
    )
    for owned in ((), ("祝福",), ("祝福(1/3)",), ("祝福", "祝福"), ("祝福(2/3)",)):
        decision = choose_action(
            PanelCandidates(
                panel_kind="bond",
                slots=(
                    SlotCandidate(index=0, name="成长", confidence=0.99),
                    SlotCandidate(index=1, name="经济", confidence=0.99),
                    SlotCandidate(index=2, name="齐天大圣", confidence=0.99),
                    SlotCandidate(index=3, name="祝福", confidence=0.99),
                ),
                owned_bond_cards=owned,
                settings=settings,
            ),
            SessionState(),
        )
        assert decision.action is PolicyAction.SELECT_SLOT
        assert decision.index == 3, f"owned={owned}: {decision.reason}"

    # 满 3 张不再抢占成长
    decision_full = choose_action(
        PanelCandidates(
            panel_kind="bond",
            slots=(
                SlotCandidate(index=0, name="成长", confidence=0.99),
                SlotCandidate(index=1, name="经济", confidence=0.99),
                SlotCandidate(index=2, name="齐天大圣", confidence=0.99),
                SlotCandidate(index=3, name="祝福", confidence=0.99),
            ),
            owned_bond_cards=("祝福", "祝福", "祝福"),
            settings=settings,
        ),
        SessionState(),
    )
    assert decision_full.action is PolicyAction.SELECT_SLOT
    assert decision_full.index == 0


def test_undead_pack_in_progress_does_not_visit_merchant_for_pill() -> None:
    """Owner 2026-09-26：亡灵卡组进行中（_devour_hold_reason 判定 hold 时），不因缺吞噬丹且占格≥8去黑商。"""
    med = Mediator(Settings(ocr_mode="off", cards=["亡灵", "亡灵天灾"]), ROOT)
    frame = Frame(np.zeros((600, 800, 3), dtype=np.uint8), window_title="英雄三国KK", hwnd=10001, role="l1")
    med._bond_cards_owned = ["亡灵天灾"]
    assert med._devour_hold_reason() is not None

    with patch.object(med, "_inventory_has_swallow_pill", return_value=False), \
         patch.object(med, "_bond_bar_occupancy", return_value=8):
        # 木材充足（2000）：不因缺丹去黑商
        med._wood_balance = 2000
        assert med._solo_wants_merchant(frame) is False
        assert med._urgent_merchant_reason(frame, 100.0) is None

        # 木材不足（200）：正常循环去黑商买木材，但不因缺丹紧急插队
        med._wood_balance = 200
        assert med._solo_wants_merchant(frame) is True
        assert med._urgent_merchant_reason(frame, 100.0) is None

    # 亡灵卡组完成后解除 hold，恢复缺丹去黑商
    med._advanced_groups_completed = 1
    assert med._devour_hold_reason() is None
    with patch.object(med, "_inventory_has_swallow_pill", return_value=False), \
         patch.object(med, "_bond_bar_occupancy", return_value=8):
        med._wood_balance = 2000
        assert med._solo_wants_merchant(frame) is True
        assert med._urgent_merchant_reason(frame, 100.0) == "物品栏没有吞噬丹"
