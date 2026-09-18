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
