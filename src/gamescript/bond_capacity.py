"""羁绊栏容量决策（纯函数）。

不读屏、不点击。把「满槽 / 丹 / 合成 / 放弃」收成一条不变量：

    自由度 = 空槽数 + 吞噬丹数

拿一张卡要么并入已有同名（have+1），要么新开一摞（have 从 0 起）。
同名凑满 ``need`` 张会合成，净腾出 need-1 格。所以：

- 差 1 张就能合成：永远优先拿（腾格）
- 自由度 0：先丹，再黑商买丹，再「顶替一张非同名 → 同名+1 后合成」，否则放弃
- 自由度 1 且没丹：禁止新开一摞，只拿能立刻合成的

替换卡牌界面点某一格是「用新卡换掉那一格」。要点同名格的话 have 不变，
合成不了；所以能合成时必须顶替一张「不是这张同名」的卡。
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any


def _catalog_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "config" / "bond_stack_catalog.json"
    return Path(__file__).resolve().parents[2] / "config" / "bond_stack_catalog.json"


CATALOG_PATH = _catalog_path()


class CapacityAction(str, Enum):
    TAKE = "TAKE"
    SKIP_NEW = "SKIP_NEW"
    USE_PILL = "USE_PILL"
    BUY_PILL = "BUY_PILL"
    REPLACE_THEN_MERGE = "REPLACE_THEN_MERGE"
    ABANDON = "ABANDON"
    NONE = "NONE"


@dataclass(frozen=True)
class CapacityDecision:
    action: CapacityAction
    reason: str
    replace_index: int | None = None
    replace_indices: tuple[int, ...] = ()


@lru_cache(maxsize=1)
def load_bond_stack_catalog() -> dict[str, Any]:
    try:
        data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {"needs": {}, "capacity": 10}
    if not isinstance(data, dict):
        return {"needs": {}, "capacity": 10}
    return data


def _need_from_catalog(name: str) -> int | None:
    entry = (load_bond_stack_catalog().get("needs") or {}).get(name)
    if isinstance(entry, dict):
        need = entry.get("need")
        if isinstance(need, int) and need > 1:
            return need
    return None


def _canonical_bond_name(name: str) -> str | None:
    try:
        from gamescript.vision.choice_ocr import lookup_lexicon
    except ImportError:
        return None
    looked = lookup_lexicon(name, kind="bond")
    return looked.canonical


def stack_need(name: str | None, progress: tuple[int, int] | None = None) -> int | None:
    """合成张数：先信本张 OCR 的 y，再信目录。没见过则 None。"""
    if progress is not None:
        need = int(progress[1])
        if need > 1:
            return need
    if not name:
        return None
    found = _need_from_catalog(name)
    if found is not None:
        return found
    canon = _canonical_bond_name(name)
    if canon and canon != name:
        return _need_from_catalog(canon)
    return None


def stack_have(
    name: str | None,
    bar: tuple[str | None, ...],
    progress: tuple[int, int] | None = None,
) -> int:
    """已有张数：优先本张 OCR 的 x（拿之前的进度），否则数栏上同名。"""
    if progress is not None:
        have = int(progress[0])
        if have >= 0:
            return have
    if not name:
        return 0
    return sum(1 for slot in bar if slot == name)


def _victim_indices(bar: tuple[str | None, ...], incoming: str) -> tuple[int, ...]:
    return tuple(i for i, name in enumerate(bar) if name and name != incoming)


def decide_bond_capacity(
    bar: tuple[str | None, ...],
    incoming: str | None,
    *,
    pills: int = 0,
    progress: tuple[int, int] | None = None,
    on_replace_ui: bool = False,
    merchant_exhausted: bool = False,
) -> CapacityDecision:
    """根据栏位/丹/能否并入，决定拿、买丹、顶替合成或放弃。"""
    if not incoming:
        return CapacityDecision(CapacityAction.NONE, "没有候选卡")

    empty = sum(1 for slot in bar if slot is None)
    pills = max(0, int(pills))
    have = stack_have(incoming, bar, progress)
    need = stack_need(incoming, progress)
    remain = (need - have) if need is not None else None
    completes = remain == 1
    extends = have > 0 and remain is not None and remain > 1
    freedom = empty + pills

    if completes:
        if empty > 0:
            return CapacityDecision(CapacityAction.TAKE, f"差一张合成：{incoming} {have}/{need}")
        if pills > 0:
            return CapacityDecision(CapacityAction.USE_PILL, f"满槽但差一张，先丹再拿 {incoming}")
        if not merchant_exhausted:
            return CapacityDecision(CapacityAction.BUY_PILL, "满槽无丹，黑商买丹后再合成")
        if on_replace_ui:
            victims = _victim_indices(bar, incoming)
            if victims:
                return CapacityDecision(
                    CapacityAction.REPLACE_THEN_MERGE,
                    f"满槽无丹无商，顶替非 {incoming} 后合成 {have}/{need}",
                    replace_index=victims[0],
                    replace_indices=victims,
                )
            return CapacityDecision(CapacityAction.ABANDON, "满槽无丹且没有可顶替的异名格")
        return CapacityDecision(CapacityAction.SKIP_NEW, "满槽无丹无商，三选里先不硬开")

    if empty == 0:
        if pills > 0:
            return CapacityDecision(CapacityAction.USE_PILL, "满槽，先丹腾格")
        if not merchant_exhausted:
            return CapacityDecision(CapacityAction.BUY_PILL, "满槽无丹，去黑商刷丹")
        if extends or have > 0:
            victims = _victim_indices(bar, incoming)
            if on_replace_ui and victims:
                return CapacityDecision(
                    CapacityAction.REPLACE_THEN_MERGE,
                    f"无丹可刷，顶替异名格并入 {incoming}",
                    replace_index=victims[0],
                    replace_indices=victims,
                )
        if on_replace_ui:
            return CapacityDecision(CapacityAction.ABANDON, "满槽无丹且不能并入，放弃")
        return CapacityDecision(CapacityAction.SKIP_NEW, "满槽无丹且不能立刻合成，不拿新卡")

    if empty == 1 and pills == 0:
        return CapacityDecision(
            CapacityAction.SKIP_NEW,
            "只空一格且没丹，不新开一摞",
        )

    return CapacityDecision(CapacityAction.TAKE, f"有空槽，可收入 {incoming}")
