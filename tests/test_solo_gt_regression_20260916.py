"""GT Regression tests for live bundle solo_ingame_chain_20260916_130010_901690.

Covers:
1. P0: Stall mode preserves confirmed owned bond cards (e.g. 智力) for synthesis.
2. P0: Bond refresh when no eligible card + unselected panel close backoff even with wood >= 1000.
3. P0: Real equipment affix modal recognition with colored text on fixture f0682.
4. P0: Post-game heirloom NPC click offset avoids right-side Boss + F1 hero focus recovery.
5. P0: Dismissing heirloom dialog without confirmed boss result never fakes boss_active.
6. P0: Solo heirloom boss waiting bounded by 120s timeout and falls back to secret realm.
7. P1: Opportunistic merchant buy in HUD_ONLY without long rerolls.
8. P1: Opportunistic hero card usage during core development in HUD_ONLY.
"""

from pathlib import Path
import time
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
import pytest

from shuabao.choice_policy import (
    PanelCandidates,
    PolicyAction,
    PolicyDecision,
    PolicySettings,
    SessionState,
    SlotCandidate,
    choose_action,
    WHITELIST_HARD,
)
from shuabao.mediator import Mediator, PanelState, LoopAction, RoundOutcome, Phase
from shuabao.vision.matcher import MatchResult
from shuabao.settings import Settings
from shuabao.vision.capture import Frame

ROOT = Path(__file__).resolve().parent.parent


def test_stall_preserves_and_synthesizes_owned_bond():
    """已持有且未满羁绊（如智力）在 stall 模式及 HARD 白名单下不被丢弃，并优先合成。"""
    med = Mediator(Settings(), ROOT)
    med._bond_cards_owned = ["智力"]

    # 1. Mediator._stall_combat_bond_slots retains "智力"
    slots = (
        SlotCandidate(index=1, name="智力", confidence=0.9),
        SlotCandidate(index=2, name="未知卡", confidence=0.9),
        SlotCandidate(index=3, name="急速", confidence=0.9),
    )
    stalled_slots = med._stall_combat_bond_slots(slots)
    names = [s.name for s in stalled_slots]
    assert "智力" in names, "Owned bond 智力 must be kept in stalled bond slots"
    assert "急速" in names, "Documented combat bond 急速 must be kept"
    assert "未知卡" not in names

    # 2. Mediator._stall_combat_bond_policy includes owned bonds in presets
    base_policy = PolicySettings(bond_presets=("经济",), bond_whitelist_mode=WHITELIST_HARD)
    stall_pol = med._stall_combat_bond_policy(base_policy)
    assert "智力" in stall_pol.bond_presets

    # 3. choose_action with WHITELIST_HARD prioritizes owned bond for synthesis
    cands = PanelCandidates(
        panel_kind="bond",
        slots=stalled_slots,
        owned_bond_cards=("智力",),
        can_refresh=True,
        settings=stall_pol,
    )
    decision = choose_action(cands)
    assert decision.action == PolicyAction.SELECT_SLOT
    assert decision.index == 1
    assert "已持有合成优先" in decision.reason


def test_bond_refresh_and_close_backoff():
    """页面无合法卡且有刷新控件时返回 REFRESH；关闭面板时即便 wood>=1000 也设置 backoff。"""
    cands = PanelCandidates(
        panel_kind="bond",
        slots=(SlotCandidate(index=1, name="无用卡", confidence=0.9),),
        owned_bond_cards=(),
        can_refresh=True,
        settings=PolicySettings(
            bond_presets=("急速",),
            bond_whitelist_mode=WHITELIST_HARD,
        ),
    )
    decision = choose_action(cands, SessionState(refreshes=0, max_refreshes=2))
    assert decision.action == PolicyAction.REFRESH

    med = Mediator(Settings(), ROOT)
    med._wood_balance = 500  # wood < 1000 applies backoff
    med._panel_kind = "bond"
    med._l1_cycle_owned_panel = True
    med._l1_cycle_step = "bond"
    med._l1_cycle_selected = False
    now = time.time()
    med._finish_panel_episode()
    assert med._bond_idle_until >= now + 25.0, "Must back off after unselected panel close when wood < 1000"


def test_high_wood_bond_unselected_close_does_not_set_idle_backoff():
    """wood>=1000 + 未选卡关闭 F 后不得设置 30s _bond_idle_until（高木材对称测试）。"""
    med = Mediator(Settings(), ROOT)
    med._wood_balance = 5000  # wood >= 1000
    med._panel_kind = "bond"
    med._l1_cycle_owned_panel = True
    med._l1_cycle_step = "bond"
    med._l1_cycle_selected = False
    now = time.time()
    med._bond_idle_until = 0.0
    med._finish_panel_episode()
    assert med._bond_idle_until < now + 1.0, "High wood (>=1000) must not set 30s idle backoff"


def test_equipment_affix_modal_real_fixture():
    """装备 1 号格升级后四词缀弹窗（含深蓝文字 智力+100）能在实机 fixture 上正确识别。"""
    fixture_path = ROOT / "tests" / "fixtures" / "real_equipment_affix_modal_frame.png"
    assert fixture_path.exists(), f"Fixture missing: {fixture_path}"
    bgr = cv2.imdecode(np.fromfile(str(fixture_path), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert bgr is not None
    frame = Frame(bgr)

    med = Mediator(Settings(), ROOT)
    hit = med._find_equipment_affix_choice(frame)
    assert hit is not None, "Real equipment affix modal must be detected"
    assert hit.name == "equipment_affix_2"
    assert hit.x == 800
    assert hit.y == 350


def test_post_game_hub_heirloom_offset_and_hero_focus():
    """传家宝 NPC 点击定位；广场丢失焦点 2 帧后发送 F1。"""
    med = Mediator(Settings(), ROOT)
    frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8))
    dummy_label = MatchResult("cjb", 0.9, 1000, 200, 100, 30, 1050, 215)

    with patch.object(med, "_find_post_game_hub_entry", return_value=dummy_label):
        hit = med._post_game_hub_entry_click(frame, "heirloom")
        assert hit is not None
        assert hit.screen_x == 1050

    # Test _maybe_ensure_post_game_hero_focus
    med._post_game_pending = True
    med._panel_state = PanelState.CLOSED
    now = time.time()

    with patch.object(med, "_post_game_state", return_value="NPC_HUB"), \
         patch.object(med, "find", return_value=None), \
         patch.object(med, "act_key", return_value=True) as mock_key:

        # Frame 1: missing focus, no key yet
        frame1 = Frame(np.zeros((900, 1600, 3), dtype=np.uint8))
        res1 = med._maybe_ensure_post_game_hero_focus(frame1, now)
        assert res1 is None
        mock_key.assert_not_called()

        # Frame 2: distinct frame, 2nd consecutive miss -> act_key("F1")
        frame2 = Frame(np.zeros((900, 1600, 3), dtype=np.uint8))
        res2 = med._maybe_ensure_post_game_hero_focus(frame2, now)
        assert res2 == LoopAction.Continue
        mock_key.assert_called_once_with("F1", "PostGameSelectHeroFocus")


def test_dismiss_heirloom_dialog_unconfirmed_decouple():
    """传家宝弹窗未确认 Boss 启动时关闭，不得假冒进入 boss_active 或 _solo_heirloom_boss_waiting。"""
    med = Mediator(Settings(auto_secret_realm=True), ROOT)
    med._post_game_route = "heirloom_active"
    med._post_game_pending = True
    med._victory_continue_since = None
    med._boss_challenge_attempts = 3
    med._heirloom_boss_confirm_unconfirmed = True
    now = time.time()
    frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8))

    close_hit = MatchResult("close", 0.9, 500, 500, 20, 20, 500, 500)
    with patch.object(med, "_post_game_state", return_value="HEIRLOOM_DIALOG"), \
         patch.object(med, "_find_heirloom_close", return_value=close_hit), \
         patch.object(med, "_heirloom_boss_result_visible", return_value=False), \
         patch.object(med, "_heirloom_boss_confirm_expired", return_value=True), \
         patch.object(med, "act_click", return_value=True):
        act = med._tick_main_line(frame)
        assert act == LoopAction.Continue
        assert med._solo_heirloom_boss_waiting is False
        assert med._post_game_route == "secret"  # Cleanly fell back to secret realm!


def test_solo_heirloom_boss_clear_success():
    """掉落代理确认 (is_clear=True) 时，正常进入大秘境路线并记为 clear。"""
    med = Mediator(Settings(auto_secret_realm=True), ROOT)
    med._solo_heirloom_boss_waiting = True
    med._solo_heirloom_boss_waiting_since = 1000.0
    now = 1050.0  # within 120s
    frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8))

    with patch.object(med, "_unattended_recovery_enabled", return_value=True), \
         patch.object(med, "_solo_heirloom_boss_is_clear", return_value=True), \
         patch.object(med, "_solo_boss_is_alive", return_value=False), \
         patch.object(med, "_post_game_state", return_value=None), \
         patch.object(med, "_is_in_game_hud", return_value=True):
        with patch("shuabao.mediator.time.time", return_value=now):
            act = med._tick_main_line(frame)
            assert act == LoopAction.Continue
            assert med._solo_heirloom_boss_waiting is False
            assert med._post_game_route == "secret"


def test_solo_heirloom_boss_alive_vetos_secret_at_timeout():
    """即使到达 120s 超时窗口，若画面仍有明确 ALIVE 证据，必须否决流转保持零输入等待。"""
    med = Mediator(Settings(auto_secret_realm=True), ROOT)
    med._post_game_route = "boss_active"
    med._post_game_pending = False
    med._solo_heirloom_boss_waiting = True
    med._solo_heirloom_boss_waiting_since = 1000.0
    now = 1000.0 + med._SOLO_HEIRLOOM_EXIT_S + 5.0  # 125s elapsed, timeout reached
    frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8))

    with patch.object(med, "_unattended_recovery_enabled", return_value=True), \
         patch.object(med, "_solo_boss_is_alive", return_value=True), \
         patch.object(med, "_solo_heirloom_boss_is_clear", return_value=False), \
         patch.object(med, "_post_game_state", return_value=None), \
         patch.object(med, "_is_in_game_hud", return_value=True):
        with patch("shuabao.mediator.time.time", return_value=now):
            act = med._tick_main_line(frame)
            # ALIVE vetos transition: returns Continue, keeps waiting True, post_game_pending remains False
            assert act == LoopAction.Continue
            assert med._solo_heirloom_boss_waiting is True
            assert med._post_game_pending is False
            assert med._post_game_route == "boss_active"


def test_solo_heirloom_boss_timeout_fallback_distinguished_from_clear():
    """单人传家宝等待 120s 超时且无 ALIVE 时流转到秘境，但不得记为 Boss CLEAR。"""
    med = Mediator(Settings(auto_secret_realm=False), ROOT)
    med._solo_heirloom_boss_waiting = True
    med._solo_heirloom_boss_waiting_since = 1000.0
    now = 1000.0 + med._SOLO_HEIRLOOM_EXIT_S + 1.0  # 121s elapsed
    frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8))

    with patch.object(med, "_unattended_recovery_enabled", return_value=True), \
         patch.object(med, "_solo_boss_is_alive", return_value=False), \
         patch.object(med, "_solo_heirloom_boss_is_clear", return_value=False), \
         patch.object(med, "_post_game_state", return_value=None), \
         patch.object(med, "_is_in_game_hud", return_value=True), \
         patch.object(med, "_record_round_outcome") as mock_record:
        with patch("shuabao.mediator.time.time", return_value=now):
            act = med._tick_main_line(frame)
            assert act == LoopAction.Continue
            assert med._solo_heirloom_boss_waiting is False
            # Verifies outcome reason is timeout fallback, NOT clear
            mock_record.assert_called_once_with(RoundOutcome.VICTORY, "solo heirloom boss timeout fallback")
            assert med.phase == Phase.QUIT


def test_opportunistic_merchant_single_buy():
    """HUD_ONLY 下黑商出现时单次购买吞噬丹/木材/折扣，不执行长耗时 reroll。"""
    med = Mediator(Settings(merchant_enabled=True), ROOT)
    frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8))
    now = time.time()

    with patch.object(med, "_black_merchant_present", return_value=True), \
         patch.object(med, "_maybe_black_merchant") as mock_merchant:
        mock_merchant.return_value = LoopAction.Continue
        res = med._maybe_opportunistic_merchant(frame, now)
        assert res == LoopAction.Continue
        mock_merchant.assert_called_once_with(frame, allow_reroll=False)
        assert med._opportunistic_merchant_next_at >= now + 7.5


def test_opportunistic_hero_card_evolve_gate_enforcement():
    """未确认进化完成 (_evolve_ok_this_cycle=False) 时绝对零输入；进化确认后才允许使用英雄卡。"""
    med = Mediator(Settings(), ROOT)
    frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8))
    now = time.time()
    hero_card_hit = MatchResult("hero_card_item", 0.9, 1100, 750, 30, 30, 1100, 750)

    # 1. 未进化 + 无 evolve button + 背包有 hero card -> act_click 必须 0 次，返回 None
    med._evolve_ok_this_cycle = False
    with patch.object(med, "_has_evolve_button", return_value=False), \
         patch.object(med, "find", return_value=hero_card_hit), \
         patch.object(med, "act_click") as mock_click:
        res = med._maybe_opportunistic_hero_card(frame, now)
        assert res is None
        mock_click.assert_not_called()

    # 2. 进化确认后 (_evolve_ok_this_cycle=True) -> 允许点击并建立 WAIT_HERO_CHOICE
    med._evolve_ok_this_cycle = True
    with patch.object(med, "_has_evolve_button", return_value=False), \
         patch.object(med, "find", return_value=hero_card_hit), \
         patch.object(med, "act_click", return_value=True) as mock_click:
        res = med._maybe_opportunistic_hero_card(frame, now)
        assert res == LoopAction.Continue
        mock_click.assert_called_once_with(hero_card_hit, "Opportunistic-hero-card")
        assert med._pending_action is not None
        assert med._pending_action.kind == "WAIT_HERO_CHOICE"
        assert med._evolve_awaiting_hero_pick is True
