# -*- coding: utf-8 -*-
"""桌面入口 × GT 入口：同一候选下的**绑定等价性**（2026-09-19）。

审查结论 1.2 的核心不是"GT 有个 bug"，而是**证据等价性**被破坏：

    GT   : tools/live_scenario_capture._new_live_mediator
    桌面 : src/shuabao/shell/live_execute.execute_runtime_mediator

两条入口都声称构造"生产 RuntimeMediator"，candidate SHA 相同、类名相同，
但 GT 曾在构造后把 Core 的 `_maybe_use_inventory_item` 贴到 Runtime 类上。
于是「同一 SHA 的 GT 通过」并不蕴含「桌面通过」。本文件把两条入口放进同一
组用例，按**关键方法的 module/qualname/源码 hash** 逐项比对，而不是只比
`type(mediator)`。

为什么桌面入口这里要打桩 `run()`：真实 `Mediator.run()` 在进入循环前就会
`find_window_targets` + `activate_window`，那是对用户真实桌面窗口的操作。
本文件是零输入离线用例，所以 `run` 被换成只记录调用的替身——**覆盖范围到
"入口把 mediator 构造好并交给 run 为止"，不覆盖 run 内部**，这一点不隐瞒。
前置的 identity preflight 与订阅授权同样被打桩：它们与方法绑定无关，且在
无实机/无授权的离线主机上必然拒绝启动。
"""
from __future__ import annotations

import hashlib
import inspect
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.mediator import Mediator as CoreMediator
from shuabao.runtime_mediator import Mediator as RuntimeMediator
from shuabao.settings import Settings
from shuabao.shell import live_execute
from shuabao.stop_signal import StopSignal

# 审查要求"记录关键绑定方法的来源"，而不是只记 type(mediator)。
_BOUND_METHODS = (
    "_maybe_use_inventory_item",
    "_maybe_black_merchant",
    "_can_consume_inventory_swallow_pill",
    "_has_swallowable_pirate_card",
    "_can_consume_god_swallow_pill",
    "_panel_mutation_confirmed",
    "_public_bag_surface_ok",
    "_open_bag_page",
    "tick",
    "run",
)

_PIRATE_KW = dict(
    ocr_mode="off",
    cards=("海盗", "罗杰斯上将", "毁灭战舰"),
    bonds=("海盗", "祝福", "成长", "经济", "贪婪", "挑战"),
)


@pytest.fixture(autouse=True)
def _restore_class_bindings():
    """把两个 Mediator 类的关键属性在每个用例前后复位。

    GT 工厂的重绑定是**类级**副作用：一旦某个用例触发过，同进程里后续用例
    看到的"初始"绑定就已经是被改过的，于是"构造 GT 不得改写桌面绑定"这类
    断言会被前一个用例的污染掩盖成假绿。本夹具让每个用例都从干净类开始，
    顺带保证本文件不会把污染漏给 tests/ 里的其他文件。
    """
    saved = []
    for cls in (CoreMediator, RuntimeMediator):
        for name in _BOUND_METHODS:
            saved.append((cls, name, cls.__dict__.get(name, KeyError)))
    try:
        yield
    finally:
        for cls, name, value in saved:
            if value is KeyError:
                # 原本这个类自己没有该属性（靠继承拿到）；用例若新贴了一个，删掉。
                if name in cls.__dict__:
                    delattr(cls, name)
            else:
                setattr(cls, name, value)


def _binding_fingerprint(med) -> dict[str, str]:
    """每个关键方法记 module.qualname + 源码 sha256 前 16 位。"""
    out: dict[str, str] = {}
    for name in _BOUND_METHODS:
        func = getattr(type(med), name, None)
        if func is None:
            out[name] = "ABSENT"
            continue
        try:
            src = inspect.getsource(func)
            digest = hashlib.sha256(src.encode("utf-8")).hexdigest()[:16]
        except (OSError, TypeError):  # pragma: no cover - 纯防御
            digest = "NO_SOURCE"
        out[name] = f"{func.__module__}.{func.__qualname__}#{digest}"
    return out


def _gt_mediator(tmp_path: Path):
    from tools.live_scenario_capture import _new_live_mediator

    med, err = _new_live_mediator(
        Settings(**_PIRATE_KW), ROOT, stop_signal=StopSignal(), incident_dir=tmp_path
    )
    assert err is None, f"GT 工厂退回 Core，证据不可用：{err}"
    med.executor = MagicMock(name="executor")
    return med


def _desktop_mediator(tmp_path: Path):
    """走真实 execute_runtime_mediator，只打桩与绑定无关的前置与 run。"""
    captured: dict[str, object] = {}
    run_calls: list[object] = []

    def _on_mediator(med):
        captured["med"] = med
        med.executor = MagicMock(name="executor")

    def _stub_run(self, max_steps=None):
        run_calls.append(max_steps)

    stop = StopSignal()
    stop.trigger("offline binding parity test")

    with patch.object(live_execute, "runtime_identity_preflight",
                      return_value={"ready_for_gt": True, "blocked_reasons": []}), \
         patch.object(live_execute, "start_permission_allows", return_value=True), \
         patch.object(RuntimeMediator, "run", _stub_run):
        result = live_execute.execute_runtime_mediator(
            settings=Settings(**_PIRATE_KW),
            root_dir=ROOT,
            incident_dir=tmp_path,
            stop_signal=stop,
            max_steps=0,
            on_mediator=_on_mediator,
        )

    assert "med" in captured, f"桌面入口没构造出 mediator：{result.get('terminal_reason')}"
    assert run_calls == [0], "桌面入口没有走到 run()，本用例的覆盖前提不成立"
    return captured["med"], result


# ---------------------------------------------------------------------------
# 1. 桌面入口本身
# ---------------------------------------------------------------------------

def test_desktop_entry_builds_runtime_mediator(tmp_path):
    med, result = _desktop_mediator(tmp_path)
    assert type(med) is RuntimeMediator
    assert result["mediator"] is med
    assert med.executor.mock_calls == []


def test_desktop_entry_mutates_no_class_attribute(tmp_path):
    before_run = dict(RuntimeMediator.__dict__)
    before_core = dict(CoreMediator.__dict__)
    _desktop_mediator(tmp_path)
    assert RuntimeMediator.__dict__["_maybe_use_inventory_item"] is before_run["_maybe_use_inventory_item"]
    assert CoreMediator.__dict__["_maybe_use_inventory_item"] is before_core["_maybe_use_inventory_item"]


# ---------------------------------------------------------------------------
# 2. 桌面 × GT 绑定等价性（本文件的主契约）
# ---------------------------------------------------------------------------

def test_desktop_and_gt_share_identical_bindings(tmp_path):
    desktop, _ = _desktop_mediator(tmp_path)
    gt = _gt_mediator(tmp_path)

    assert type(desktop) is type(gt)
    desktop_fp = _binding_fingerprint(desktop)
    gt_fp = _binding_fingerprint(gt)
    diff = {k: (desktop_fp[k], gt_fp[k]) for k in desktop_fp if desktop_fp[k] != gt_fp[k]}
    assert not diff, f"桌面与 GT 的方法绑定不一致，GT 证据不能代表桌面：{diff}"


def test_gt_construction_does_not_change_desktop_bindings(tmp_path):
    """先建桌面、再建 GT，桌面那一份绑定不得被后来者改写。"""
    desktop, _ = _desktop_mediator(tmp_path)
    before = _binding_fingerprint(desktop)
    _gt_mediator(tmp_path)
    assert _binding_fingerprint(desktop) == before


def test_no_binding_is_missing_source(tmp_path):
    """指纹本身要有意义：任何 ABSENT / NO_SOURCE 都说明比对是空跑。"""
    desktop, _ = _desktop_mediator(tmp_path)
    fp = _binding_fingerprint(desktop)
    bad = {k: v for k, v in fp.items() if v in ("ABSENT", "NO_SOURCE")}
    assert not bad, f"这些方法没能取到可比对的来源：{bad}"


# ---------------------------------------------------------------------------
# 3. 两条入口下的安全闸门一致（审查 1.1）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bounty", ["haidao_bounty_ur_red", "haidao", "unknown_token"])
def test_devour_gate_fail_closed_on_both_entries(tmp_path, bounty):
    import numpy as np
    from shuabao.vision.capture import Frame

    frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8),
                  window_title="英雄三国KK", hwnd=10001, role="l1")
    desktop, _ = _desktop_mediator(tmp_path)
    gt = _gt_mediator(tmp_path)
    for med in (desktop, gt):
        assert med._has_swallowable_pirate_card(bounty, frame) is False
        assert med._can_consume_inventory_swallow_pill(frame) is False
        assert med._can_consume_god_swallow_pill(frame) is False
        assert med.executor.mock_calls == []


def test_black_merchant_allow_reroll_on_both_entries(tmp_path):
    import numpy as np
    from shuabao.vision.capture import Frame

    frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8),
                  window_title="英雄三国KK", hwnd=10001, role="l1")
    desktop, _ = _desktop_mediator(tmp_path)
    gt = _gt_mediator(tmp_path)
    seen: list[bool] = []

    def _sentinel(self, f, allow_reroll: bool = True):
        seen.append(allow_reroll)
        return None

    with patch.object(CoreMediator, "_maybe_black_merchant", _sentinel):
        for med in (desktop, gt):
            med._maybe_black_merchant(frame, allow_reroll=False)
    assert seen == [False, False]
