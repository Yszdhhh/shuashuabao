# -*- coding: utf-8 -*-
"""P0-2（2026-09-17）：普通吞噬丹在共享运行时闸门处失能。

羁绊栏只能读出「占了几格」，读不出逐格身份，所以「格数 > 3」不是
「可以随便吞掉一张」的授权。存档里既有的 auto_devour_dan=true 只是
用户偏好，不是授权：闸门 `_can_consume_inventory_swallow_pill` 无条件
False，core 与 runtime 两个消费者、以及 MAIN_LINE 的 opportunistic
调度全部经过它，谁都绕不过去。

本文件零真实输入：executor 一律换成 MagicMock 记录器，任何一次真的
SendInput 都会体现为 mock_calls 非空。
"""
from __future__ import annotations

import contextlib
import sys
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import pytest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.loop_action import LoopAction
from shuabao.mediator import Mediator as CoreMediator
from shuabao.mediator import PanelState, Phase
from shuabao.merchant_scanner import MerchantScanner, MerchantSlotItem
from shuabao.runtime_mediator import Mediator as RuntimeMediator
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult

FIX = ROOT / "tests" / "fixtures" / "solo_live_20260914"
_BOND_CELL_X = (603, 655, 707, 759, 811, 863, 915, 967, 1019, 1071)


def _bond_frame(occupied: int) -> Frame:
    """真帧几何：按 _bond_bar_occupancy 的 10 个格心涂满饱和色。

    不是 mock —— 下面的用例先断言真实识别确实读出 occupied 格，
    再断言闸门仍然拒绝，这样「4/5/6 格」是被识别出来的，不是被灌进去的。
    """
    bgr = np.zeros((900, 1600, 3), dtype=np.uint8)
    for cx in _BOND_CELL_X[:occupied]:
        bgr[635:680, cx - 20 : cx + 20] = (255, 0, 0)
    return Frame(bgr, window_title="英雄三国KK", hwnd=10001, role="l1")


def _unknown_bond_frame() -> Frame:
    """非受支持分辨率 -> _bond_bar_occupancy 返回 None（占用未知）。"""
    return Frame(np.zeros((600, 800, 3), dtype=np.uint8), window_title="英雄三国KK", hwnd=10001, role="l1")


def _fixture_frame(name: str = "hud_wood_1111_f0200.png") -> Frame:
    image = cv2.imdecode(np.fromfile(str(FIX / name), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None, name
    return Frame(image, window_title="英雄三国KK", hwnd=10001, role="l1")


def _med(cls, **kw):
    med = cls(Settings(ocr_mode="off", **kw), ROOT)
    med.set_phase(Phase.MAIN_LINE)
    med._panel_state = PanelState.CLOSED
    med._devour_dan_next_at = 0.0
    # 零真实输入：所有 act_* 最终都打在 executor 上，换成记录器。
    med.executor = MagicMock(name="executor")
    return med


def _pill_only_find(med, pill: MatchResult):
    """danGif 一律"看得见"，其余模板走真实 find，不整体 mock 业务识别。"""
    real_find = med.find

    def find(frame, names, **kwargs):
        if any("danGif" in str(n) or "swallow_pill" in str(n) for n in names):
            return pill
        return real_find(frame, names, **kwargs)

    return patch.object(med, "find", side_effect=find)


def _gate_spy(med):
    """真闸门 + 调用/返回记录：证明调度确实问过它，而不是分支没走到。"""
    real_gate = med._can_consume_inventory_swallow_pill
    results: list[bool] = []

    def spy(frame):
        value = real_gate(frame)
        results.append(value)
        return value

    return patch.object(med, "_can_consume_inventory_swallow_pill", side_effect=spy), results


# ---------------------------------------------------------------- settings


def test_default_settings_do_not_authorize_ordinary_devour() -> None:
    assert Settings().auto_devour_dan is False


def test_saved_true_is_preserved_and_missing_key_falls_back_to_disabled(tmp_path: Path) -> None:
    """显式 true/false 存取无损；缺字段 = 不授权（旧存档不得隐式开启）。"""
    path = tmp_path / "settings.json"

    Settings(auto_devour_dan=True).save(path)
    assert json.loads(path.read_text(encoding="utf-8"))["auto_devour_dan"] is True
    assert Settings.load(path).auto_devour_dan is True

    Settings(auto_devour_dan=False).save(path)
    assert json.loads(path.read_text(encoding="utf-8"))["auto_devour_dan"] is False
    assert Settings.load(path).auto_devour_dan is False

    path.write_text(json.dumps({"stage1": 7}), encoding="utf-8")
    loaded = Settings.load(path)
    assert loaded.stage1 == 7
    assert loaded.auto_devour_dan is False


# ---------------------------------------------------------------- the gate


def test_real_gate_refuses_every_recognized_occupancy() -> None:
    """4/5/6 格全部被真实识别读出，闸门依旧拒绝（无逐格身份=无授权）。"""
    med = _med(CoreMediator)
    for occupied in (4, 5, 6):
        frame = _bond_frame(occupied)
        assert med._bond_bar_occupancy(frame) == occupied
        assert med._can_consume_inventory_swallow_pill(frame) is False


# ------------------------------------------------------- the two consumers


@pytest.mark.parametrize("cls", [CoreMediator, RuntimeMediator])
@pytest.mark.parametrize("occupied", [4, 5, 6])
def test_consumer_never_clicks_pill_even_with_saved_true(cls, occupied: int) -> None:
    med = _med(cls, auto_devour_dan=True)
    frame = _bond_frame(occupied)
    assert med._bond_bar_occupancy(frame) == occupied
    pill = MatchResult("danGif", 0.95, 1100, 780, 20, 20, 1100, 780)

    with _pill_only_find(med, pill), patch.object(med, "act_click") as click:
        assert med._maybe_use_inventory_item(frame) is None

    click.assert_not_called()
    assert med.executor.mock_calls == []
    assert med._pending_action is None
    assert getattr(med._pending_action, "kind", None) not in ("WAIT_DEVOUR_DAN", "WAIT_SWALLOW_PILL_CONFIRM")



# --------------------------------------------------- MAIN_LINE opportunistic


@pytest.mark.parametrize("cls", [CoreMediator, RuntimeMediator])
def test_main_line_opportunistic_dispatch_cannot_bypass_the_gate(cls) -> None:
    """auto_devour_dan=true + 冷却已到 + 丹可见，真实 _tick_main_line 仍不吞。"""
    med = _med(cls, auto_devour_dan=True, auto_artifact=False)
    med._l1_cycle_step = "bond"
    med._main_line_started_at = 100.0
    med._auto_task_done = True
    med._pickup_next_at = 1e18  # 拾取不在本用例范围，别抢 opportunistic 槽
    frame = _fixture_frame()
    pill = MatchResult("danGif", 0.95, 1100, 780, 20, 20, 1100, 780)

    clicks: list[str] = []
    keys: list[str] = []
    gate_patch, gate_results = _gate_spy(med)
    with contextlib.ExitStack() as stack:
        stack.enter_context(patch("time.time", return_value=200.0))
        stack.enter_context(patch.object(med, "_post_game_state", return_value=None))
        stack.enter_context(patch.object(med, "_find_stage_page", return_value=False))
        stack.enter_context(patch.object(med, "_selection_anchor", return_value=None))
        stack.enter_context(patch.object(med, "_ensure_auto_task_enabled", return_value=None))
        stack.enter_context(patch.object(med, "_ensure_challenge_buttons", return_value=None))
        stack.enter_context(patch.object(med, "_maybe_ensure_hero_panel_focus", return_value=None))
        stack.enter_context(patch.object(med, "_maybe_click_tqtz", return_value=None))
        stack.enter_context(patch.object(med, "_maybe_clear_pressure_monsters", return_value=None))
        stack.enter_context(patch.object(med, "_handle_self_opened_compact_panel", return_value=None))
        stack.enter_context(patch.object(med, "_maybe_open_choice_panel", return_value=None))
        stack.enter_context(patch.object(med, "_is_in_game_hud", return_value=True))
        stack.enter_context(patch.object(med, "_black_merchant_present", return_value=False))
        stack.enter_context(patch.object(med, "_maybe_fire_artifacts", return_value=None))
        stack.enter_context(_pill_only_find(med, pill))
        stack.enter_context(gate_patch)
        stack.enter_context(
            patch.object(med, "act_click", side_effect=lambda _h, reason="", *a, **k: clicks.append(reason) or True)
        )
        stack.enter_context(
            patch.object(med, "act_key", side_effect=lambda _k, reason="", *a, **k: keys.append(reason) or True)
        )
        med._tick_main_line(frame)

    assert gate_results, "opportunistic 分支必须真的问过共享闸门"
    assert set(gate_results) == {False}
    assert "UseInventory-swallow_pill" not in clicks
    assert med.executor.mock_calls == []
    assert getattr(med._pending_action, "kind", None) not in ("WAIT_DEVOUR_DAN", "WAIT_SWALLOW_PILL_CONFIRM")


# ------------------------------------------------------ tightened verifier


def _forced_pending(frame: Frame):
    """仅本节：强开闸门以构造真实产线已不可达的 WAIT_DEVOUR_DAN pending。"""
    med = _med(RuntimeMediator, auto_devour_dan=True)
    pill = MatchResult("danGif", 0.95, 1100, 780, 20, 20, 1100, 780)
    with _pill_only_find(med, pill), patch.object(
        med, "_can_consume_inventory_swallow_pill", return_value=True
    ), patch.object(med, "act_click", return_value=True):
        assert med._maybe_use_inventory_item(frame) is LoopAction.Continue
    pending = med._pending_action
    assert pending is not None and pending.kind == "WAIT_DEVOUR_DAN"
    return pending


def test_devour_verifier_rejects_disappearance_without_occupancy_drop() -> None:
    """丹不见了 / 羁绊栏读不出来，都只是丢失识别，不是吞噬成功。"""
    pending = _forced_pending(_bond_frame(5))
    assert pending.is_confirmed(_bond_frame(5)) is False
    assert pending.is_confirmed(_unknown_bond_frame()) is False


def test_devour_verifier_accepts_real_occupancy_decrease() -> None:
    pending = _forced_pending(_bond_frame(5))
    assert pending.is_confirmed(_bond_frame(4)) is True


# ------------------------------------------- unrelated routes stay unchanged


def test_hero_card_route_still_fires_in_runtime_consumer() -> None:
    """同一函数里的英雄卡路线不得被吞噬丹的失能顺手打掉。"""
    med = _med(RuntimeMediator, auto_devour_dan=True)
    med._evolve_ok_this_cycle = True
    med._inventory_next_at = 0.0
    hero = MatchResult("hero_card_item", 0.95, 1150, 760, 20, 20, 1150, 760)

    with patch.object(med, "find", side_effect=lambda _f, names, **_k: hero if "hero_card_item" in names else None), \
            patch.object(med, "act_click", return_value=True) as click:
        assert med._maybe_use_inventory_item(_bond_frame(5)) is LoopAction.Continue

    click.assert_called_once_with(hero, "UseInventory-hero-card")
    assert med._pending_action.kind == "WAIT_HERO_CHOICE"


def test_merchant_pill_purchase_ranking_is_untouched() -> None:
    """黑商/蹭车的吞噬丹「买入」与「吞服」是两件事，闸门不得波及买入。"""
    scanner = MerchantScanner()
    items = [
        MerchantSlotItem(slot_index=1, center_ratio=(0.74, 0.72), item_type="devour_pill", label="吞噬丹"),
        MerchantSlotItem(slot_index=3, center_ratio=(0.88, 0.72), item_type="wood", label="merchant_wood"),
    ]
    assert [i.item_type for i in scanner.rank_purchases(items, bond_bar_nonempty=True)] == ["devour_pill"]
