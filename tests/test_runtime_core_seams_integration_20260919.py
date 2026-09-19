# -*- coding: utf-8 -*-
"""Runtime Core 接收（2026-09-19）：四个旧入口的**真实**集成契约。

云端交付包里的 `tests/runtime_core/test_integration_recipe.py` 只在合成
字符串上验证补丁生成器；它**不证明**真实 `shuabao.mediator` /
`shuabao.runtime_mediator` / `tools.live_scenario_capture._new_live_mediator`
接好了。本文件用真实类、真实工厂、真实 Settings 补上这一层：

* 审查结论 1.2：GT 工厂曾把 `RuntimeMediator._maybe_use_inventory_item`
  就地替换成 Core 方法 —— 同一个 SHA、同一个类名，行为却不同。
* 审查结论 1.2：Core 用 `allow_reroll=False` 调黑商，Runtime 覆写只有
  `(self, frame)`，命中即 `TypeError`。
* 审查结论 1.1：吞噬授权用品质排序表达"保护"，UR 悬赏令可放行核心卡。
* 审查结论 1.3：ROI 丢失/尺寸变化被当成"画面异变即成功"。

零真实输入：executor 一律换成 MagicMock，任何一次真的 SendInput 都会
体现为 mock_calls 非空。
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.mediator import Mediator as CoreMediator
from shuabao.mediator import PanelState, Phase
from shuabao.runtime_mediator import Mediator as RuntimeMediator
from shuabao.settings import Settings
from shuabao.stop_signal import StopSignal
from shuabao.vision.capture import Frame

# 海盗真实预设：审查要求闸门测试必须带真实 profile，而不是空 Settings。
_PIRATE_KW = dict(
    ocr_mode="off",
    cards=("海盗", "罗杰斯上将", "毁灭战舰"),
    bonds=("海盗", "祝福", "成长", "经济", "贪婪", "挑战"),
)


def _frame(w: int = 1600, h: int = 900) -> Frame:
    return Frame(np.zeros((h, w, 3), dtype=np.uint8), window_title="英雄三国KK", hwnd=10001, role="l1")


def _med(cls, **kw):
    merged = dict(_PIRATE_KW)
    merged.update(kw)
    med = cls(Settings(**merged), ROOT)
    med.set_phase(Phase.MAIN_LINE)
    med._panel_state = PanelState.CLOSED
    med.executor = MagicMock(name="executor")
    return med


# ---------------------------------------------------------------------------
# A. 工厂与真实方法绑定（审查 1.2 / 矩阵第 22 项的横切前提）
# ---------------------------------------------------------------------------

def test_factory_returns_runtime_mediator_without_error():
    from tools.live_scenario_capture import _new_live_mediator

    med, err = _new_live_mediator(
        Settings(**_PIRATE_KW), ROOT, stop_signal=StopSignal(), incident_dir=ROOT / "artifacts"
    )
    assert err is None, f"RuntimeMediator 构造失败，LIVE 会静默退回 Core：{err}"
    assert type(med) is RuntimeMediator


def test_factory_does_not_rebind_runtime_inventory_method():
    """GT 入口不得再把 Core 实现就地贴到 Runtime 类上。"""
    from tools.live_scenario_capture import _new_live_mediator

    before_run = RuntimeMediator.__dict__["_maybe_use_inventory_item"]
    before_core = CoreMediator.__dict__["_maybe_use_inventory_item"]

    _new_live_mediator(
        Settings(**_PIRATE_KW), ROOT, stop_signal=StopSignal(), incident_dir=ROOT / "artifacts"
    )

    assert RuntimeMediator.__dict__["_maybe_use_inventory_item"] is before_run
    assert CoreMediator.__dict__["_maybe_use_inventory_item"] is before_core
    # 绑定指纹：Runtime 的这一格必须仍属于 runtime_mediator，而不是被替换成 Core 的。
    assert RuntimeMediator._maybe_use_inventory_item.__module__ == "shuabao.runtime_mediator"
    assert RuntimeMediator._maybe_use_inventory_item is not CoreMediator._maybe_use_inventory_item


def test_factory_source_has_no_class_attribute_rebinding():
    """源码级回归守卫：整个工厂函数内不得出现 `RuntimeMediator.<attr> = `。"""
    from tools import live_scenario_capture as lsc

    src = inspect.getsource(lsc._new_live_mediator)
    assert "RuntimeMediator._maybe_use_inventory_item = " not in src
    assert " = Mediator._" not in src


def test_runtime_inventory_delegates_to_core_at_runtime():
    """委托必须在运行期真的落到 Core 实现，而不只是源码看起来像。"""
    med = _med(RuntimeMediator)
    frame = _frame()
    seen = {}

    def _sentinel(self, f):
        seen["frame"] = f
        return "CORE_REACHED"

    with patch.object(CoreMediator, "_maybe_use_inventory_item", _sentinel):
        result = med._maybe_use_inventory_item(frame)

    assert result == "CORE_REACHED"
    assert seen["frame"] is frame
    assert med.executor.mock_calls == []


# ---------------------------------------------------------------------------
# B. 黑商关键字参数（审查 1.2 的静态调用契约错误）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cls", [CoreMediator, RuntimeMediator])
def test_black_merchant_accepts_allow_reroll(cls):
    sig = inspect.signature(cls._maybe_black_merchant)
    assert "allow_reroll" in sig.parameters, f"{cls.__module__} 缺 allow_reroll，机会黑商路径会 TypeError"
    assert sig.parameters["allow_reroll"].default is True


def test_runtime_black_merchant_forwards_allow_reroll_false():
    """Core 用 `allow_reroll=False` 调机会黑商；Runtime 必须原样转交。"""
    med = _med(RuntimeMediator)
    frame = _frame()
    captured = {}

    def _sentinel(self, f, allow_reroll: bool = True):
        captured["allow_reroll"] = allow_reroll
        return None

    with patch.object(CoreMediator, "_maybe_black_merchant", _sentinel):
        med._maybe_black_merchant(frame, allow_reroll=False)
    assert captured["allow_reroll"] is False

    with patch.object(CoreMediator, "_maybe_black_merchant", _sentinel):
        med._maybe_black_merchant(frame)
    assert captured["allow_reroll"] is True


def test_opportunistic_black_merchant_call_site_does_not_raise_typeerror():
    """回放审查里那条真实调用形态：命中时不得因参数绑定抛 TypeError。"""
    med = _med(RuntimeMediator)
    frame = _frame()
    with patch.object(CoreMediator, "_maybe_black_merchant", lambda self, f, allow_reroll=True: None):
        med._maybe_black_merchant(frame, allow_reroll=False)  # 不抛即通过


# ---------------------------------------------------------------------------
# C. 吞噬授权 fail-closed（审查 1.1）
# ---------------------------------------------------------------------------

_BOUNTY_NAMES = (
    "haidao_bounty_ur_red",          # UR：最高品质，旧实现在这里放行核心卡
    "haidao_bounty_n_green",
    "haidao_inventory_ssr_orange_body",
    "haidao",                         # 共享普通丹闸门传的字面量
    "totally_unknown_bounty_token",   # 未知名称：旧实现默认落到最高等级
    "",
)


@pytest.mark.parametrize("cls", [CoreMediator, RuntimeMediator])
@pytest.mark.parametrize("auto_devour_dan", [True, False])
@pytest.mark.parametrize("bounty", _BOUNTY_NAMES)
def test_pirate_swallow_gate_is_fail_closed(cls, auto_devour_dan, bounty):
    med = _med(cls, auto_devour_dan=auto_devour_dan)
    assert med._has_swallowable_pirate_card(bounty, _frame()) is False
    assert med._has_swallowable_pirate_card(bounty, None) is False
    assert med.executor.mock_calls == []


@pytest.mark.parametrize("cls", [CoreMediator, RuntimeMediator])
@pytest.mark.parametrize("auto_devour_dan", [True, False])
def test_inventory_and_god_swallow_gates_are_fail_closed(cls, auto_devour_dan):
    med = _med(cls, auto_devour_dan=auto_devour_dan)
    frame = _frame()
    assert med._can_consume_inventory_swallow_pill(frame) is False
    assert med._can_consume_god_swallow_pill(frame) is False
    assert med._can_consume_god_swallow_pill(None) is False
    assert med.executor.mock_calls == []


def test_devour_gates_share_one_implementation_across_core_and_runtime():
    """Runtime 不得再各自覆写这三个闸门，否则两条入口会重新分叉。"""
    for name in (
        "_can_consume_inventory_swallow_pill",
        "_has_swallowable_pirate_card",
        "_can_consume_god_swallow_pill",
    ):
        assert name not in RuntimeMediator.__dict__, f"Runtime 重新覆写了 {name}"
        assert getattr(RuntimeMediator, name) is getattr(CoreMediator, name)


# ---------------------------------------------------------------------------
# D. 面板 mutation 后置（审查 1.3）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cls", [CoreMediator, RuntimeMediator])
def test_missing_roi_cannot_confirm_mutation(cls):
    med = _med(cls)
    med._panel_mutation_baseline = np.zeros((10, 10, 3), dtype=np.uint8)
    tiny = Frame(np.zeros((50, 50, 3), dtype=np.uint8), window_title="英雄三国KK", hwnd=10001, role="l1")
    assert med._panel_roi_region(tiny) is None       # 真的读不出 ROI
    assert med._panel_mutation_confirmed(tiny) is False


@pytest.mark.parametrize("cls", [CoreMediator, RuntimeMediator])
def test_resized_roi_cannot_confirm_mutation(cls):
    med = _med(cls)
    frame = _frame()
    roi = med._panel_roi_region(frame)
    assert roi is not None
    # baseline 来自另一套布局/缩放：形状不同不等于"选卡成功"。
    med._panel_mutation_baseline = np.zeros((roi.shape[0] + 7, roi.shape[1] + 7, 3), dtype=np.uint8)
    assert med._panel_mutation_confirmed(frame) is False


@pytest.mark.parametrize("cls", [CoreMediator, RuntimeMediator])
def test_no_baseline_cannot_confirm_mutation(cls):
    med = _med(cls)
    med._panel_mutation_baseline = None
    assert med._panel_mutation_confirmed(_frame()) is False


# ---------------------------------------------------------------------------
# E. 高级卡组顺序（审查 1.5：ratio=0 不得放开全部高级组）
# ---------------------------------------------------------------------------

def test_choice_policy_has_no_test_open_mode_bypass():
    source = (ROOT / "src" / "shuabao" / "choice_policy.py").read_text(encoding="utf-8")
    assert "test_open_mode" not in source, "ratio=0 放开全部高级预设的旁路又回来了"
