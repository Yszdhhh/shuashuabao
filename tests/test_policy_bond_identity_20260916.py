"""Tests for bond identity membership, completion semantics, and substring isolation (2026-09-16)."""
from pathlib import Path
import pytest

from shuabao.choice_policy import (
    PANEL_BOND,
    PanelCandidates,
    PolicyAction,
    PolicySettings,
    SessionState,
    SlotCandidate,
    WHITELIST_HARD,
    _active_advanced_presets,
    _bond_base_ready,
    _is_bond_must_take,
    canonical_bond_identity,
    choose_action,
    same_bond_identity,
)
from shuabao.settings import Settings

ROOT = Path(__file__).resolve().parent.parent


def test_bond_identity_truth_table():
    """规范化羁绊身份严格相等性真值表，防止子串混淆。"""
    assert not same_bond_identity("智力", "智力祝福")
    assert not same_bond_identity("力量", "力量提升")
    assert not same_bond_identity("海盗", "白赚海盗")
    assert not same_bond_identity("封神", "封神榜")
    assert same_bond_identity("成长", "成长之根")
    assert same_bond_identity("智力", "智力")
    assert same_bond_identity("智力(1/3)", "智力")
    assert same_bond_identity("海盗[2/4]", "海盗")


def test_bond_must_take_no_substring_pollution():
    """bond_must_take 严禁通过子串匹配非目标卡牌。"""
    assert not _is_bond_must_take("智力祝福", ("祝福",))
    assert not _is_bond_must_take("白赚海盗", ("海盗",))
    assert _is_bond_must_take("海盗", ("海盗",))
    assert _is_bond_must_take("海盗(1/3)", ("海盗",))

    # choose_action 集成验证：must_take 为海盗，面板出现白赚海盗，不可作为 must_take 选中
    settings = PolicySettings(
        bond_must_take=("海盗",),
        bond_presets=(),
        bond_whitelist_mode=WHITELIST_HARD,
    )
    cands = PanelCandidates(
        panel_kind=PANEL_BOND,
        slots=(
            SlotCandidate(index=0, name="白赚海盗", confidence=0.95),
            SlotCandidate(index=1, name="修仙", confidence=0.95),
        ),
        owned_bond_cards=(),
        can_refresh=False,
        settings=settings,
    )
    dec = choose_action(cands, SessionState())
    assert dec.action != PolicyAction.SELECT_SLOT or dec.index != 0


def test_bond_base_ready_no_substring_inflation():
    """80% 基础羁绊完成度检查不因包含子串而虚假计入已完成。"""
    settings = PolicySettings(
        bond_base_presets=("海盗", "力量"),
        bond_advanced_presets=("修仙",),
        bond_base_completion_ratio=0.8,
    )
    # 拥有白赚海盗和力量提升，不等于拥有海盗和力量
    cands_falsy = PanelCandidates(
        panel_kind=PANEL_BOND,
        slots=(),
        owned_bond_cards=("白赚海盗", "力量提升"),
        settings=settings,
    )
    assert not _bond_base_ready(cands_falsy, settings)

    # 真正拥有海盗和力量
    cands_truth = PanelCandidates(
        panel_kind=PANEL_BOND,
        slots=(),
        owned_bond_cards=("海盗", "力量"),
        settings=settings,
    )
    assert _bond_base_ready(cands_truth, settings)


def test_active_advanced_presets_no_substring_inflation():
    """高级卡组进度计算不因持有子串卡而错误推进。"""
    settings = PolicySettings(
        bond_advanced_groups=(("海盗", "探险"), ("封神", "修仙")),
        bond_base_completion_ratio=1.0,
    )
    # 拥有白赚海盗，不满足第一组 ("海盗", "探险")
    cands = PanelCandidates(
        panel_kind=PANEL_BOND,
        slots=(),
        owned_bond_cards=("白赚海盗",),
        settings=settings,
    )
    active = _active_advanced_presets(cands, settings)
    assert active == ("海盗", "探险")


def test_runtime_mediator_stage_bond_card_no_substring_leak():
    """RuntimeMediator _stage_bond_card 不通过 substring 误放行未配置的卡牌。"""
    from shuabao.runtime_mediator import Mediator as RuntimeMediator

    med = RuntimeMediator(Settings(cards=[]), ROOT)
    med._bond_cards_owned = ["海盗"]
    med._bond_cards_pending.clear()

    # 试图 stage 白赚海盗，既非 configured preset，也非已拥有的确切卡
    med._stage_bond_card("白赚海盗")
    assert "白赚海盗" not in med._bond_cards_pending
    assert not med._bond_cards_pending

    # 试图 stage 海盗，与已拥有的海盗相同，用于升级合并
    med._stage_bond_card("海盗")
    assert med._bond_cards_pending == ["海盗"]


def test_full_bond_bar_pirate_cannot_merge_or_trigger_replacement():
    """满槽 free_slots == 0 且全是海盗时，海盗无 need 无法合成，禁止选卡触发顶替卡牌弹窗卡死。"""
    from shuabao.bond_capacity import _victim_indices, decide_bond_capacity, stack_have, stack_need
    from shuabao.choice_policy import _bond_capacity_candidates, _is_uncompleted_merge_upgrade

    # 1. 验证海盗无合成 need，且 _is_uncompleted_merge_upgrade 必须返回 False
    slot_pirate = SlotCandidate(index=0, name="海盗", confidence=0.96)
    owned_pirates = ("海盗",) * 10
    assert stack_need("海盗") is None
    assert not _is_uncompleted_merge_upgrade(slot_pirate, owned_pirates)

    # 2. 满栏全为海盗时，无异名格可供顶替
    assert _victim_indices(owned_pirates, "海盗") == ()
    assert stack_have("海盗", owned_pirates) == 10

    # 3. capacity candidates 在 free_slots == 0 时必须将海盗过滤掉
    settings = PolicySettings(
        bond_presets=("海盗", "藏宝图(三)", "亡灵", "祝福", "经济"),
        bond_must_take=("藏宝图(三)",),
    )
    cands = PanelCandidates(
        panel_kind=PANEL_BOND,
        slots=(
            slot_pirate,
            SlotCandidate(index=1, name="成长", confidence=0.95),
            SlotCandidate(index=2, name="异火", confidence=0.85),
        ),
        owned_bond_cards=owned_pirates,
        free_slots=0,
        can_refresh=False,
        has_giveup=True,
        settings=settings,
        refresh_count=5,
    )
    eligible = _bond_capacity_candidates(cands, cands.slots, settings)
    assert slot_pirate not in eligible

    # 4. choose_action 决不可选择海盗，刷新耗尽时必须安全 CLOSE（绝不进入替换卡牌）
    dec = choose_action(cands, SessionState(refreshes=5, max_refreshes=5))
    assert dec.action == PolicyAction.CLOSE


def test_full_bond_bar_core_card_triggers_replacement_target():
    """满槽 free_slots == 0 时，如果拥有可顶替卡（如海盗成长卡），核心必拿卡可被选中并带上 replace_index。"""
    from shuabao.bond_capacity import _victim_indices
    # 假设已持有卡中包含一张海盗成长卡在位置 3
    owned = ("亡灵", "亡灵", "亡灵", "海盗成长卡", "亡灵", "亡灵", "亡灵", "亡灵", "亡灵", "亡灵")
    assert _victim_indices(owned, "亡灵核心") == (3,)

    settings = PolicySettings(
        bond_presets=("海盗", "亡灵", "祝福", "经济"),
        bond_must_take=("亡灵核心",),
    )
    cands = PanelCandidates(
        panel_kind=PANEL_BOND,
        slots=(
            SlotCandidate(index=0, name="亡灵核心", confidence=0.96),
            SlotCandidate(index=1, name="异火", confidence=0.85),
        ),
        owned_bond_cards=owned,
        free_slots=0,
        can_refresh=False,
        has_giveup=True,
        settings=settings,
        refresh_count=0,
    )
    dec = choose_action(cands, SessionState())
    assert dec.action == PolicyAction.SELECT_SLOT
    assert dec.index == 0
    assert dec.replace_index == 3


def test_pickup_bag_has_space_solo_vs_passenger():
    """验证背包空间判定：在背包界面未打开时，蹭车拒绝Z，单人允许Z。"""
    from shuabao.mediator import Mediator
    from shuabao.vision.capture import Frame
    import numpy as np

    med = Mediator(Settings(), ROOT)
    frame = Frame(
        bgr=np.zeros((900, 1600, 3), dtype=np.uint8),
        left=0,
        top=0,
        window_title="test",
    )

    # 1. 背包界面未打开且为单人模式 -> 返回 True
    med.settings.mode_id = "normal_farm"
    assert not med._passenger_mode()
    assert med._pickup_bag_has_space(frame) is True

    # 2. 蹭车模式 -> 返回 False
    med.settings.mode_id = "lobby_hitch"
    assert med._passenger_mode()
    assert med._pickup_bag_has_space(frame) is False


def test_handle_card_replacement_dialog_actions():
    """验证替换卡牌弹窗：有目标卡槽时点击卡槽，无目标卡槽时点击放弃按钮。"""
    from unittest.mock import patch
    from shuabao.mediator import Mediator, LoopAction
    from shuabao.vision.capture import Frame
    from shuabao.vision.matcher import MatchResult
    import numpy as np

    med = Mediator(Settings(), ROOT)
    frame = Frame(
        bgr=np.zeros((900, 1600, 3), dtype=np.uint8),
        left=0,
        top=0,
        window_title="test",
    )
    abandon_hit = MatchResult("replace_card_abandon_btn", 0.95, 800, 539, 50, 20, 800, 539)

    # Case 1: 有 _replace_slot_index = 3，检测到弹窗 -> 点击卡槽 3
    med._replace_slot_index = 3
    clicked_targets = []
    with patch.object(med, "find", return_value=abandon_hit), \
         patch.object(med, "act_click", side_effect=lambda hit, reason: clicked_targets.append((hit, reason)) or True):
        res = med._handle_card_replacement_dialog(frame)
        assert res == LoopAction.Continue
        assert med._replace_slot_index is None
        assert len(clicked_targets) == 1
        hit, reason = clicked_targets[0]
        assert reason == "ReplaceCard-slot-3"
        expected_x = int(453 + (3 + 0.5) * 69.2)
        assert hit.x == expected_x
        assert hit.y == 448

    # Case 2: 无 _replace_slot_index，检测到弹窗 -> 点击放弃按钮
    med._replace_slot_index = None
    med._replace_dialog_next_at = 0.0
    clicked_targets.clear()
    with patch.object(med, "find", return_value=abandon_hit), \
         patch.object(med, "act_click", side_effect=lambda hit, reason: clicked_targets.append((hit, reason)) or True):
        res = med._handle_card_replacement_dialog(frame)
        assert res == LoopAction.Continue
        assert len(clicked_targets) == 1
        hit, reason = clicked_targets[0]
        assert reason == "ReplaceCard-abandon"
        assert hit == abandon_hit


def test_bounty_order_consumed_in_inventory():
    """验证悬赏令使用：检测到悬赏令道具时，单机点击使用。"""
    from unittest.mock import patch
    from shuabao.mediator import Mediator, LoopAction
    from shuabao.vision.capture import Frame
    from shuabao.vision.matcher import MatchResult
    import numpy as np

    med = Mediator(Settings(), ROOT)
    frame = Frame(
        bgr=np.zeros((900, 1600, 3), dtype=np.uint8),
        left=0,
        top=0,
        window_title="test",
    )
    bounty_hit = MatchResult("haidao/haidao_bounty_ur_red", 0.85, 1145, 737, 30, 30, 1145, 737)

    with patch.object(med, "_hud_item_bar_state", return_value="items"), \
         patch.object(med, "find", return_value=bounty_hit), \
         patch.object(med, "act_click", return_value=True) as mock_click:
        res = med._maybe_use_inventory_item(frame)
        assert res == LoopAction.Continue
        mock_click.assert_called_once_with(bounty_hit, "UseInventory-bounty-haidao_bounty_ur_red")


def test_bond_preset_order_arbitration_when_multiple_present():
    """双轨选卡仲裁：面板同时出现多个已勾选基础羁绊时，严格按 祝福 > 成长 > 经济 默认顺序仲裁。"""
    settings = PolicySettings(
        bond_presets=("祝福", "成长", "经济"),
        min_confidence=0.6,
    )
    # 场景 1: 祝福 与 经济 同时出现 -> 必须选 祝福
    cands1 = PanelCandidates(
        panel_kind=PANEL_BOND,
        slots=(
            SlotCandidate(index=0, name="经济", confidence=0.9),
            SlotCandidate(index=1, name="祝福", confidence=0.9),
        ),
        settings=settings,
    )
    dec1 = choose_action(cands1, SessionState())
    assert dec1.action == PolicyAction.SELECT_SLOT and dec1.index == 1

    # 场景 2: 成长 与 经济 同时出现 -> 必须选 成长
    cands2 = PanelCandidates(
        panel_kind=PANEL_BOND,
        slots=(
            SlotCandidate(index=0, name="经济", confidence=0.9),
            SlotCandidate(index=1, name="成长", confidence=0.9),
        ),
        settings=settings,
    )
    dec2 = choose_action(cands2, SessionState())
    assert dec2.action == PolicyAction.SELECT_SLOT and dec2.index == 1

    # 场景 3: 祝福 与 成长 同时出现 -> 必须选 祝福
    cands3 = PanelCandidates(
        panel_kind=PANEL_BOND,
        slots=(
            SlotCandidate(index=0, name="成长", confidence=0.9),
            SlotCandidate(index=1, name="祝福", confidence=0.9),
        ),
        settings=settings,
    )
    dec3 = choose_action(cands3, SessionState())
    assert dec3.action == PolicyAction.SELECT_SLOT and dec3.index == 1


def test_near_complete_bond_priority_arbitration():
    """即将合成加权与仲裁：差一张合成优先于普通预设；若同时多个差一张合成，按默认优先级仲裁。"""
    settings = PolicySettings(
        bond_presets=("祝福", "成长", "经济"),
        min_confidence=0.6,
    )
    # 场景 1: 成长(2/3) 差一张合成 vs 祝福(0/3) 普通预设 -> 差一张合成秒选 成长
    cands1 = PanelCandidates(
        panel_kind=PANEL_BOND,
        slots=(
            SlotCandidate(index=0, name="成长(2/3)", confidence=0.9),
            SlotCandidate(index=1, name="祝福", confidence=0.9),
        ),
        owned_bond_cards=("成长", "成长"),
        settings=settings,
    )
    dec1 = choose_action(cands1, SessionState())
    assert dec1.action == PolicyAction.SELECT_SLOT and dec1.index == 0
    assert "差一张合成秒选" in dec1.reason

    # 场景 2: 成长(2/3) 与 经济(2/3) 同时差一张合成 -> 依默认优先级仲裁选 成长
    cands2 = PanelCandidates(
        panel_kind=PANEL_BOND,
        slots=(
            SlotCandidate(index=0, name="经济(2/3)", confidence=0.9),
            SlotCandidate(index=1, name="成长(2/3)", confidence=0.9),
        ),
        owned_bond_cards=("经济", "经济", "成长", "成长"),
        settings=settings,
    )
    dec2 = choose_action(cands2, SessionState())
    assert dec2.action == PolicyAction.SELECT_SLOT and dec2.index == 1


def test_bounty_swallow_pirate_tier_matching():
    """悬赏令与海盗卡品质匹配：持有 SR 海盗卡时，绿/蓝悬赏令不空放，紫/橙/红悬赏令方可吞噬。"""
    from shuabao.mediator import Mediator
    med = Mediator(Settings(), ROOT)

    # 1. 持有 SR 海盗劫掠者
    med._bond_cards_owned = ["海盗劫掠者", "祝福"]
    assert not med._has_swallowable_pirate_card("haidao/haidao_bounty_n_green")
    assert not med._has_swallowable_pirate_card("haidao/haidao_bounty_r_blue")
    assert med._has_swallowable_pirate_card("haidao/haidao_bounty_sr_purple")
    assert med._has_swallowable_pirate_card("haidao/haidao_bounty_ssr_orange")
    assert med._has_swallowable_pirate_card("haidao/haidao_bounty_ur_red")

    # 2. 完全无海盗卡且配置未开启海盗时，任何悬赏令均不盲目消耗
    med._bond_cards_owned = ["力量", "敏捷", "智力"]
    assert not med._has_swallowable_pirate_card("haidao/haidao_bounty_n_green")
    assert not med._has_swallowable_pirate_card("haidao/haidao_bounty_sr_purple")
    assert not med._has_swallowable_pirate_card("haidao/haidao_bounty_ur_red")


def test_bond_capacity_candidates_allows_core_when_free_slots_is_2():
    """free_slots == 2 时，必须放行 core 预设候选（如成长、祝福、海盗），防止误刷新。"""
    from shuabao.choice_policy import _bond_capacity_candidates

    slots = (
        SlotCandidate(index=0, name=None, confidence=0.44),
        SlotCandidate(index=1, name="成长", confidence=0.96),
        SlotCandidate(index=2, name="海盗", confidence=0.93),
    )
    ps = PolicySettings(
        bond_presets=("祝福", "成长", "经济", "海盗"),
        bond_whitelist_mode="hard",
    )
    cands = PanelCandidates(
        panel_kind=PANEL_BOND,
        slots=slots,
        free_slots=2,
        settings=ps,
        owned_bond_cards=(),
    )
    kept = _bond_capacity_candidates(cands, slots, ps)
    names = [s.name for s in kept]
    assert "成长" in names
    assert "海盗" in names


def test_bounty_swallow_with_untracked_bar_cards():
    """当配置了海盗卡组且羁绊栏有卡（如开局或手动预选），即使 owned 未同步也允许使用悬赏令。"""
    from shuabao.mediator import Mediator
    med = Mediator(Settings(cards=["海盗", "zhufu"]), ROOT)

    # 1. owned 无海盗记录，但配置了海盗卡且栏位有卡 (occ=8)
    med._bond_cards_owned = ["体术", "敏捷"]
    med._bond_bar_occupancy = lambda frame=None: 8
    assert med._has_swallowable_pirate_card("haidao/haidao_bounty_ssr_orange")

    # 2. 若配置未包含海盗卡组，则不盲目吞噬
    med_no_pirate = Mediator(Settings(cards=["zhufu", "chengzhang"]), ROOT)
    med_no_pirate._bond_cards_owned = ["体术", "敏捷"]
    med_no_pirate._bond_bar_occupancy = lambda frame=None: 8
    assert not med_no_pirate._has_swallowable_pirate_card("haidao/haidao_bounty_ssr_orange")


def test_boss_active_closes_personal_bag():
    """当检测到 Boss 存活时，必须立即关闭个人背包，让出全屏视野与操作空间。"""
    from shuabao.mediator import Mediator, Frame, LoopAction
    from shuabao.policy.public_bag import BagLayout
    import numpy as np

    med = Mediator(Settings(cards=["海盗", "zhufu"]), ROOT)
    frame = Frame(bgr=np.zeros((900, 1600, 3), dtype=np.uint8))

    med._bag_layout = lambda f: BagLayout(origin_x=100.0, origin_y=100.0, scale=1.0)
    med._solo_boss_is_alive = lambda f: True

    closed_reasons = []
    med._toggle_bag_page = lambda f, reason: (closed_reasons.append(reason), True)[1]

    res = med._maybe_use_inventory_item(frame)
    assert res == LoopAction.Continue
    assert "BossActiveCloseBag" in closed_reasons


def test_consumables_exhausted_closes_bag():
    """当个人背包内消耗品全部用完且无待移装备时，自动关闭背包。"""
    from shuabao.mediator import Mediator, Frame, LoopAction
    from shuabao.policy.public_bag import BagLayout
    import numpy as np

    med = Mediator(Settings(cards=["海盗", "zhufu"]), ROOT)
    frame = Frame(bgr=np.zeros((900, 1600, 3), dtype=np.uint8))

    med._bag_layout = lambda f: BagLayout(origin_x=100.0, origin_y=100.0, scale=1.0)
    med._solo_boss_is_alive = lambda f: False
    med._hud_item_bar_state = lambda f: "empty"
    med.find = lambda f, cand, **kwargs: None
    med._item_bar_slot_occupied = lambda f, l, idx: True
    med._bag_slot_occupied = lambda f, rect: False

    closed_reasons = []
    med._toggle_bag_page = lambda f, reason: (closed_reasons.append(reason), True)[1]

    res = med._maybe_use_inventory_item(frame)
    assert res == LoopAction.Continue
    assert "SoloBagCloseConsumablesExhausted" in closed_reasons


def test_bag_remains_open_while_consumables_present():
    """当个人背包内有悬赏令消耗品时，背包保持常驻开启，不提前关闭。"""
    from shuabao.mediator import Mediator, Frame, MatchResult
    from shuabao.policy.public_bag import BagLayout
    import numpy as np

    med = Mediator(Settings(cards=["海盗", "zhufu"]), ROOT)
    frame = Frame(bgr=np.zeros((900, 1600, 3), dtype=np.uint8))

    layout = BagLayout(origin_x=100.0, origin_y=100.0, scale=1.0)
    med._bag_layout = lambda f: layout
    med._solo_boss_is_alive = lambda f: False
    med._hud_item_bar_state = lambda f: "empty"

    center = layout.personal_slot_center(0, 0)
    hit = MatchResult("haidao/haidao_bounty_ssr_orange", 0.9, center[0], center[1], 30, 30, center[0], center[1])
    med.find = lambda f, cands, **kwargs: hit if "bag_roi" in kwargs or kwargs.get("threshold") == 0.65 else None
    med._has_swallowable_pirate_card = lambda name, f: False

    closed_reasons = []
    med._toggle_bag_page = lambda f, reason: (closed_reasons.append(reason), True)[1]

    med._maybe_use_inventory_item(frame)
    assert "SoloBagCloseConsumablesExhausted" not in closed_reasons
    assert "BossActiveCloseBag" not in closed_reasons


def test_bounty_in_item_bar_stashes_to_personal_bag_when_not_swallowable():
    """快捷栏有悬赏令但当前不可吞噬时，右键取出并准备存入个人格（腾出装备栏）。"""
    from shuabao.mediator import Mediator, Frame, LoopAction, MatchResult
    from shuabao.policy.public_bag import BagLayout
    import numpy as np

    med = Mediator(Settings(cards=["海盗", "zhufu"]), ROOT)
    frame = Frame(bgr=np.zeros((900, 1600, 3), dtype=np.uint8))

    layout = BagLayout(origin_x=100.0, origin_y=100.0, scale=1.0)
    med._bag_layout = lambda f: layout
    med._solo_boss_is_alive = lambda f: False
    med._hud_item_bar_state = lambda f: "occupied"

    # 模拟快捷栏中有悬赏令 (item_bar_bounty)
    center = layout.item_bar_slot_center(1)
    hit = MatchResult("haidao/haidao_bounty_n_green", 0.9, center[0], center[1], 30, 30, center[0], center[1])
    med.find = lambda f, cands, **kwargs: hit if "inventory_roi" in str(kwargs) or kwargs.get("roi") == (0.64, 0.77, 0.74, 0.98) else None

    # 当前不可吞噬
    med._has_swallowable_pirate_card = lambda name, f: False
    med._public_bag_empty_personal_slot = lambda f, l: (0, 0, MatchResult("target", 1.0, 200, 200, 10, 10, 200, 200))

    right_clicked = []
    med.act_right_click = lambda hit, reason: (right_clicked.append((hit, reason)), True)[1]

    res = med._maybe_use_inventory_item(frame)
    assert res == LoopAction.Continue
    assert len(right_clicked) == 1
    assert "SoloPickItemBarConsumable" in right_clicked[0][1]
    assert med._solo_stash_held_source is not None


def test_equipment_in_personal_grid_equips_to_empty_item_bar():
    """个人背包有装备且快捷栏有空位时，右键背包装备移入快捷栏（保留装备在物品栏）。"""
    from shuabao.mediator import Mediator, Frame, LoopAction, MatchResult
    from shuabao.policy.public_bag import BagLayout
    import numpy as np

    med = Mediator(Settings(cards=["海盗", "zhufu"]), ROOT)
    frame = Frame(bgr=np.zeros((900, 1600, 3), dtype=np.uint8))

    layout = BagLayout(origin_x=100.0, origin_y=100.0, scale=1.0)
    med._bag_layout = lambda f: layout
    med._solo_boss_is_alive = lambda f: False
    med._hud_item_bar_state = lambda f: "empty"
    med.find = lambda f, cand, **kwargs: None  # 无悬赏令消耗品

    # 模拟快捷栏第 2 格（index 1）为空
    med._item_bar_slot_occupied = lambda f, l, idx: False if idx == 1 else True

    # 模拟个人背包 (0, 0) 格有占用的装备
    med._bag_slot_occupied = lambda f, rect: True if rect == layout.personal_slot_rect(0, 0) else False

    right_clicked = []
    med.act_right_click = lambda hit, reason: (right_clicked.append((hit, reason)), True)[1]

    res = med._maybe_use_inventory_item(frame)
    assert res == LoopAction.Continue
    assert len(right_clicked) == 1
    assert "EquipBagItem-0-0" in right_clicked[0][1]


def test_4_slot_bond_choice_coordinate_with_stalled_filtering():
    """验证4槽面板在候选被过滤后仍使用4槽中心坐标，绝不点偏到黑色缝隙。"""
    from shuabao.mediator import Mediator, Frame
    from shuabao.choice_policy import PolicyDecision, SlotCandidate
    import numpy as np

    med = Mediator(Settings(), ROOT)
    frame = Frame(bgr=np.zeros((900, 1600, 3), dtype=np.uint8), left=286, top=108)

    # 模拟 4 槽面板扫描出 4 张卡
    med._choice_panel_slot_count = 4

    # 模拟被 _stall_combat_bond_slots 过滤后只有 2 张卡（Slot 0 和 Slot 2）
    cand0 = SlotCandidate(0, "挑战", "blue", "R", 0.86, "tz")
    cand2 = SlotCandidate(2, "成长", "blue", "R", 0.88, "chengzhang")
    filtered_slots = (cand0, cand2)

    decision = PolicyDecision.select(2, "羁绊差一张合成秒选【成长】")
    mapped = med._policy_decision_to_hit(frame, "bond", decision, filtered_slots)
    assert mapped is not None
    label, hit = mapped
    assert label == "bond"
    assert hit.name == "ocr_bond:成长"
    # 4 槽第 2 槽中心为 x=0.565, y=0.44 -> x=904, y=396 (绝对坐标 286+904=1190, 108+396=504)
    assert hit.x == int(1600 * 0.565)
    assert hit.screen_x == 286 + int(1600 * 0.565)
    assert hit.y == int(900 * 0.44)
    assert hit.screen_y == 108 + int(900 * 0.44)


def test_inventory_clicks_cooldown_reset():
    """验证物品栏点击计数器在超过冷却时间后自动重置，防止永久锁死。"""
    from shuabao.mediator import Mediator, Frame, PanelState, LoopAction
    from shuabao.vision.matcher import MatchResult
    from unittest.mock import patch
    import numpy as np
    import time

    med = Mediator(Settings(cards=["海盗"]), ROOT)
    frame = Frame(bgr=np.zeros((900, 1600, 3), dtype=np.uint8))

    # 模拟之前连续点击了 3 次达到上限
    med._inventory_clicks_this_visit = 3
    med._inventory_next_at = time.time() - 3.0  # 冷却已过去 3 秒

    bounty_hit = MatchResult("haidao/haidao_bounty_ssr_orange", 0.85, 1145, 737, 30, 30, 1145, 737)
    med._panel_state = PanelState.CLOSED
    med._has_swallowable_pirate_card = lambda name, f: True
    med._hud_item_bar_state = lambda f: "items"

    with patch.object(med, "find", return_value=bounty_hit), \
         patch.object(med, "act_click", return_value=True):
        res = med._maybe_use_inventory_item(frame)
        assert res == LoopAction.Continue
        # 验证计数器已被重置并重新计数为 1
        assert med._inventory_clicks_this_visit == 1


def test_passive_card_replacement_user_rules():
    """验证替换卡牌按用户规则智能顶替：
    1. N 级海盗直接放弃（重置刷新木材到40木）
    2. 核心卡（成长）顶替非核心槽（海盗），绝不顶替已有成长
    3. 高阶海盗（SR）顶替低阶海盗（N）
    4. 同阶海盗且无可顶替低阶时放弃
    """
    from shuabao.mediator import Mediator, Frame
    from unittest.mock import MagicMock
    import numpy as np

    med = Mediator(Settings(bonds=["成长", "祝福", "经济"]), ROOT)
    frame = Frame(bgr=np.zeros((900, 1600, 3), dtype=np.uint8))

    # 1. 进来 N 级空降海盗 -> 必须放弃
    med._ocr_client = MagicMock()
    med._ocr_client.is_ready = True
    med._ocr_client.shadow_predict = MagicMock(return_value=MagicMock(raw_text="空降海盗", rec_score=0.95))
    victim, reason = med._decide_passive_card_replacement(frame)
    assert victim is None
    assert "放弃以重置刷新木材到40木" in reason

    # 2. 进来 核心卡 成长 -> 顶替非核心卡槽 0（海盗），保护槽位 1 的成长
    med._ocr_client.shadow_predict = MagicMock(return_value=MagicMock(raw_text="成长", rec_score=0.98))
    victim, reason = med._decide_passive_card_replacement(frame)
    assert victim == 0
    assert "核心卡" in reason

    # 3. 进来 SR 级海盗 顶尖大盗 -> 顶替槽位 0 的 N 级海盗
    med._ocr_client.shadow_predict = MagicMock(return_value=MagicMock(raw_text="顶尖大盗", rec_score=0.95))
    victim, reason = med._decide_passive_card_replacement(frame)
    assert victim == 0
    assert "顶替低阶卡槽" in reason


def test_equipment_withdrawal_2_step_complete_flow():
    """验证背包装备取出穿戴的完整两步闭环：第1步右键背包装备，第2步左键红框空槽。"""
    from shuabao.mediator import Mediator, Frame, LoopAction, MatchResult
    from shuabao.policy.public_bag import BagLayout
    import numpy as np

    med = Mediator(Settings(cards=["海盗", "zhufu"]), ROOT)
    frame = Frame(bgr=np.zeros((900, 1600, 3), dtype=np.uint8))

    layout = BagLayout(origin_x=100.0, origin_y=100.0, scale=1.0)
    med._bag_layout = lambda f: layout
    med._solo_boss_is_alive = lambda f: False
    med._hud_item_bar_state = lambda f: "empty"
    med.find = lambda f, cand, **kwargs: None

    # 模拟快捷栏第 3 格（index 2）为空（如圣光之盾槽位）
    med._item_bar_slot_occupied = lambda f, l, idx: False if idx == 2 else True

    # 模拟个人背包 (0, 0) 格有圣光之盾
    med._bag_slot_occupied = lambda f, rect: True if rect == layout.personal_slot_rect(0, 0) else False

    right_clicked = []
    left_clicked = []
    med.act_right_click = lambda hit, reason: (right_clicked.append((hit, reason)), True)[1]
    med.act_click = lambda hit, reason: (left_clicked.append((hit, reason)), True)[1]

    # 第 1 步：右键拿起装备
    res1 = med._maybe_use_inventory_item(frame)
    assert res1 == LoopAction.Continue
    assert len(right_clicked) == 1
    assert "EquipBagItem-0-0" in right_clicked[0][1]
    assert med._solo_stash_held_source is not None
    assert med._solo_stash_held_source["action"] == "withdraw"
    assert med._solo_stash_held_source["target_slot"] == 2

    # 第 2 步：左键放入红框快捷栏第 3 格
    res2 = med._maybe_use_inventory_item(frame)
    assert res2 == LoopAction.Continue
    assert len(left_clicked) == 1
    assert "EquipPlaceItemBarSlot-3" in left_clicked[0][1]
    target_center = layout.item_bar_slot_center(2)
    assert left_clicked[0][0].x == target_center[0]
    assert left_clicked[0][0].y == target_center[1]
    # 流转完成，held 状态清除
    assert med._solo_stash_held_source is None


def test_haidao_gold_ape_activation_in_item_bar():
    """验证在红框物品栏中检测到黄金猿时，左键点击开启宝藏卡组。"""
    from shuabao.mediator import Mediator, Frame, LoopAction, MatchResult
    from shuabao.policy.public_bag import BagLayout
    import numpy as np

    med = Mediator(Settings(cards=["海盗", "zhufu"]), ROOT)
    frame = Frame(bgr=np.zeros((900, 1600, 3), dtype=np.uint8))

    layout = BagLayout(origin_x=100.0, origin_y=100.0, scale=1.0)
    med._bag_layout = lambda f: layout
    med._solo_boss_is_alive = lambda f: False
    med._hud_item_bar_state = lambda f: "occupied"

    ape_center = layout.item_bar_slot_center(3)
    ape_hit = MatchResult("haidao/haidao_gold_ape", 0.95, ape_center[0], ape_center[1], 30, 30, ape_center[0], ape_center[1])

    med.find = lambda f, cands, **kwargs: ape_hit if "haidao_gold_ape" in str(cands) else None

    clicked = []
    med.act_click = lambda hit, reason: (clicked.append((hit, reason)), True)[1]

    res = med._maybe_use_inventory_item(frame)
    assert res == LoopAction.Continue
    assert len(clicked) == 1
    assert "UseItemBar-gold_ape" in clicked[0][1]
    assert clicked[0][0].x == ape_center[0]
    assert clicked[0][0].y == ape_center[1]


def test_periodic_pickup_independent_of_item_bar_overflow():
    """验证定期 Z 拾取与物品栏满载解耦，非满载状态下到期也能触发一键拾取。"""
    from shuabao.mediator import Mediator, Frame, LoopAction, PanelState, Phase
    from shuabao.vision.matcher import MatchResult
    import numpy as np

    rng = np.random.default_rng(42)
    frame = Frame(bgr=rng.integers(50, 200, size=(900, 1600, 3), dtype=np.uint8), is_valid=True)
    med = Mediator(Settings(), ROOT)

    med._panel_state = PanelState.CLOSED
    med._l1_cycle_step = "equipment"
    med._pickup_next_at = 0.0
    # 模拟物品栏为空（未溢出）
    med._hud_item_bar_overflowed = lambda f: False

    clicked = []
    pickup_btn = MatchResult("bag/hud_pickup_button", 0.9, 1500, 750, 30, 30, 1500, 750)

    med.phase = Phase.MAIN_LINE
    med.see = lambda r: frame
    med.find = lambda f, cands, **kwargs: None
    med.find_scene = lambda f, s, **kwargs: None
    med._is_in_game_hud = lambda f: True
    med._auto_task_done = True
    med._maybe_ensure_hero_panel_focus = lambda f, n: None
    med._ensure_auto_task_enabled = lambda f: None
    med._ensure_challenge_buttons = lambda f: None
    med._maybe_click_tqtz = lambda f, n: None
    med._maybe_clear_pressure_monsters = lambda f, n: None
    med._maybe_fire_artifacts = lambda f: None
    med._maybe_use_inventory_item = lambda f: None
    med._selection_anchor = lambda f: None
    med._has_active_transaction = lambda f: False
    med._hud_item_bar_state = lambda f: "empty"
    med._hud_hotkey_button = lambda f, name: pickup_btn if name == "bag/hud_pickup_button" else None
    med.act_click = lambda hit, reason: (clicked.append((hit, reason)), True)[1]

    # 在 main loop 触发拾取检查
    res = med.tick()
    assert res == LoopAction.Continue
    assert len(clicked) == 1
    assert clicked[0][1] == "Pickup-Z"
    assert med._pickup_next_at > 0.0




