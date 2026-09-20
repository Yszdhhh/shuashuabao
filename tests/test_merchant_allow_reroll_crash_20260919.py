# -*- coding: utf-8 -*-
"""机会黑商路径的参数绑定崩溃（2026-09-19）。

Core 的 `_maybe_opportunistic_merchant` 用关键字参数调用黑商：

    src/shuabao/mediator.py:6465
        action = self._maybe_black_merchant(frame, allow_reroll=False)

而 RuntimeMediator 的覆写只有 `(self, frame)`，命中即 TypeError。这不是
推断：实机 LIVE 日志里有完整崩溃栈，14 份 run.log 里有 3 份终止于此，且
它是整个 captures 目录中**唯一**的异常类型。

    captures/pirate_necromancy_20260918_182507/run.log
    captures/pirate_necromancy_20260919_012405/run.log
    captures/pirate_necromancy_20260919_140828/run.log

    File "src/shuabao/mediator.py", line 6465, in _maybe_opportunistic_merchant
        action = self._maybe_black_merchant(frame, allow_reroll=False)
    TypeError: Mediator._maybe_black_merchant() got an unexpected keyword
               argument 'allow_reroll'

桌面入口 `shell/live_execute.py` 构造的同样是 RuntimeMediator，走的同样是
`_tick_main_line` → `_maybe_opportunistic_merchant`，所以这条崩溃不是 GT
专属，生产版本一样会中。

本文件只覆盖参数绑定本身，不改任何黑商业务行为：零真实输入，executor 一律
换成 MagicMock。
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
from shuabao.runtime_mediator import Mediator as RuntimeMediator
from shuabao.settings import Settings
from shuabao.vision.capture import Frame


def _frame() -> Frame:
    return Frame(np.zeros((900, 1600, 3), dtype=np.uint8),
                 window_title="英雄三国KK", hwnd=10001, role="l1")


def _med(cls):
    med = cls(Settings(ocr_mode="off"), ROOT)
    med.executor = MagicMock(name="executor")
    return med


@pytest.mark.parametrize("cls", [CoreMediator, RuntimeMediator])
def test_black_merchant_accepts_allow_reroll(cls):
    """两条入口的签名必须都收得下 allow_reroll，默认 True。"""
    sig = inspect.signature(cls._maybe_black_merchant)
    assert "allow_reroll" in sig.parameters, (
        f"{cls.__module__}._maybe_black_merchant 缺 allow_reroll，"
        f"机会黑商路径会 TypeError"
    )
    assert sig.parameters["allow_reroll"].default is True


def test_opportunistic_call_form_does_not_raise():
    """按 mediator.py:6465 的真实调用形态直调，不得抛 TypeError。"""
    med = _med(RuntimeMediator)
    with patch.object(CoreMediator, "_maybe_black_merchant",
                      lambda self, f, allow_reroll=True: None):
        med._maybe_black_merchant(_frame(), allow_reroll=False)
    assert med.executor.mock_calls == []


def test_runtime_forwards_allow_reroll_both_ways():
    """覆写不得吞掉参数：False 要原样传下去，缺省要还原成 True。"""
    med = _med(RuntimeMediator)
    frame = _frame()
    seen: list[bool] = []

    def _sentinel(self, f, allow_reroll: bool = True):
        seen.append(allow_reroll)
        return None

    with patch.object(CoreMediator, "_maybe_black_merchant", _sentinel):
        med._maybe_black_merchant(frame, allow_reroll=False)
        med._maybe_black_merchant(frame)
        med._maybe_black_merchant(frame, False)  # 位置参数同样要通
    assert seen == [False, True, False]
    assert med.executor.mock_calls == []


def test_core_call_site_still_passes_allow_reroll_false():
    """守住调用端：机会黑商必须继续禁止刷新，否则这个修复就失去意义。"""
    source = (ROOT / "src" / "shuabao" / "mediator.py").read_text(encoding="utf-8")
    assert "self._maybe_black_merchant(frame, allow_reroll=False)" in source
