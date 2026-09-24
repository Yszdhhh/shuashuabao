"""局内观测记录器：默认关闭、零输入、零 live 改写、零新依赖。

用途
====

回答四个优化指标，不做任何决策：

1. **木材**：净囤积、峰值、高位滞留时长
2. **转化率**：花掉的木材 ÷ 进账木材
3. **决策机会分配**：羁绊 / 技能抢占 / 其它各占多少
4. **每次开 F 的产出**：拿到几张、是否白名单内、是否推进套装进度

它**不是** runtime_core 的对照探针 —— 那套要拉进内核与适配器（约 2000 行），
而上面四个指标只需要旧循环自己的事实。本模块因此只依赖标准库。

纪律
====

* 只从 Mediator 读 ``getattr``，不写回任何字段。
* 不调用 ``act_*``、不发输入、不做额外 OCR 或模板匹配。
* 任何内部失败自己吞掉并计数，连续 5 次永久关闭；绝不向主线抛。
* **读不出的值落 ``null``，不落 0。** 读不出和"没有"必须可区分。

开关
====

``SHUABAO_OBSERVE=1`` 打开；关闭时 Mediator 侧连本模块都不导入。
输出目录 ``SHUABAO_OBSERVE_DIR``，默认 ``<canonical app data>/observe``。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

OBSERVE_ENV = "SHUABAO_OBSERVE"
OBSERVE_DIR_ENV = "SHUABAO_OBSERVE_DIR"

_MAX_FAILURES = 5
_SCHEMA = 1


def observe_enabled(env: Mapping[str, str] | None = None) -> bool:
    """只有显式真值才打开；缺省、空串、乱填一律关闭。"""
    source = os.environ if env is None else env
    return str(source.get(OBSERVE_ENV, "")).strip().lower() in ("1", "true", "yes", "on")


def observe_dir(env: Mapping[str, str] | None = None) -> Path:
    source = os.environ if env is None else env
    override = str(source.get(OBSERVE_DIR_ENV, "")).strip()
    if override:
        return Path(override)
    from shuabao.paths import get_canonical_app_data_dir

    return get_canonical_app_data_dir() / "observe"


def _plain(value: object) -> object:
    """None 保持 None —— 读不出不等于 0。"""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return str(value)


class ObserveLog:
    """一局内的观测记录器。永不抛异常。"""

    def __init__(
        self,
        out_dir: Path | str | None = None,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self.disabled = False
        self.failures = 0
        self.ticks_written = 0
        self.choices_written = 0
        self._wall = wall_clock
        self._dir = Path(out_dir) if out_dir is not None else observe_dir()
        self._sinks: dict[str, Any] = {}
        self._seq = 0
        self._last_tick_key: tuple | None = None

    # ---------- 生命周期 ----------

    def close(self) -> None:
        sinks, self._sinks = self._sinks, {}
        for sink in sinks.values():
            try:
                sink.close()
            except Exception:
                pass

    def _fail(self, where: str, exc: BaseException) -> None:
        self.failures += 1
        if self.failures >= _MAX_FAILURES:
            self.disabled = True
            self.close()

    def _sink(self, kind: str) -> Any:
        sink = self._sinks.get(kind)
        if sink is not None:
            return sink
        self._dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(self._wall()))
        path = self._dir / f"{kind}_{stamp}_{os.getpid()}.jsonl"
        sink = path.open("a", encoding="utf-8")
        self._sinks[kind] = sink
        return sink

    def _write(self, kind: str, payload: dict) -> None:
        sink = self._sink(kind)
        sink.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        sink.flush()

    # ---------- 指标 1/2/3：每 tick 的资源与编排 ----------

    def note_tick(
        self,
        *,
        round_id: str,
        round_elapsed_s: object,
        phase: str,
        cycle_step: object,
        wood: object,
        skill_points: object,
        treasure_count: object,
        plan_target: object = None,
        plan_reason: str = "",
    ) -> None:
        """记录一个 MAIN_LINE tick。相同读数连续重复时只记一次，避免刷屏。"""
        if self.disabled:
            return
        try:
            key = (round_id, str(cycle_step), _plain(wood), _plain(skill_points),
                   _plain(treasure_count), str(plan_target), plan_reason)
            if key == self._last_tick_key:
                return
            self._last_tick_key = key
            self._seq += 1
            self._write("tick", {
                "schema": _SCHEMA,
                "ts": round(self._wall(), 3),
                "seq": self._seq,
                "round_id": round_id,
                "round_elapsed_s": _plain(round_elapsed_s),
                "phase": phase,
                "cycle_step": _plain(cycle_step),
                # 读不出一律 null，不要变成 0
                "wood": _plain(wood),
                "skill_points": _plain(skill_points),
                "treasure_count": _plain(treasure_count),
                # 指标 3：这一刻编排把机会给了谁、为什么
                "plan_target": _plain(plan_target),
                "plan_reason": plan_reason,
            })
            self.ticks_written += 1
        except Exception as exc:
            self._fail("note_tick", exc)

    # ---------- 指标 4：每次面板决策 ----------

    def note_choice(
        self,
        *,
        round_id: str,
        panel_kind: str,
        slots: Sequence[Any],
        decision: Any,
        set_progress: Mapping[str, object] | None,
        free_slots: object,
        refresh_count: object,
        can_refresh: object,
        has_giveup: object,
        round_elapsed_s: object,
        wood: object,
        refresh_price: object = None,
        downgraded_from: str | None = None,
        downgrade_reason: str = "",
    ) -> None:
        """记录一次面板决策。只记策略当时真正看得到的事实。"""
        if self.disabled:
            return
        try:
            self._write("choice", {
                "schema": _SCHEMA,
                "ts": round(self._wall(), 3),
                "round_id": round_id,
                "panel_kind": panel_kind,
                "slots": [self._slot(s) for s in slots],
                "set_progress": _plain(set_progress),
                "free_slots": _plain(free_slots),
                "refresh_count": _plain(refresh_count),
                "can_refresh": bool(can_refresh),
                "has_giveup": bool(has_giveup),
                "round_elapsed_s": _plain(round_elapsed_s),
                "wood": _plain(wood),
                "refresh_price": _plain(refresh_price),
                "decision_action": str(getattr(decision, "action", "") or ""),
                "decision_index": _plain(getattr(decision, "index", None)),
                "decision_reason": str(getattr(decision, "reason", "") or ""),
                # 刷新因木材不足被降级成隐藏时，原动作必须留痕
                "downgraded_from": downgraded_from,
                "downgrade_reason": downgrade_reason,
            })
            self.choices_written += 1
        except Exception as exc:
            self._fail("note_choice", exc)

    @staticmethod
    def _slot(slot: Any) -> dict:
        """badge-first：族系/稀有度/角标是承重事实，名字只是附带。"""
        return {
            "index": _plain(getattr(slot, "index", None)),
            "family": _plain(getattr(slot, "family", None)),
            "rarity": _plain(getattr(slot, "rarity", None)),
            "name": _plain(getattr(slot, "name", None)),
            "confidence": _plain(getattr(slot, "confidence", None)),
            "is_new": bool(getattr(slot, "is_new", False)),
            "prereq_marker": bool(getattr(slot, "prereq_marker", False)),
            "zero_cost": bool(getattr(slot, "zero_cost", False)),
        }
