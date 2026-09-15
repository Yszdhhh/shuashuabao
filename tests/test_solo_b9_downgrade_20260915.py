# -*- coding: utf-8 -*-
"""B9（Owner 2026-09-15）：打不过自动降级 —— 连续失败 N 局后选关目标降一档。

看板新增 `downgrade_after_failures`（0=关闭）。失败口径与既有
`_record_round_outcome` 熔断计数（`_failure_streak`）同一变量；胜利/降级都
清零它，只有「已在 1-1 仍失败」才继续累积到 `failure_streak_limit` 熔断。
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from shuabao.mediator import Mediator, Phase, RoundOutcome
from shuabao.settings import Settings
from shuabao.vision.matcher import MatchResult

ROOT = Path(__file__).resolve().parents[1]


def _med(**kw) -> Mediator:
    med = Mediator(Settings(ocr_mode="off", stage_targets=["1-21"], **kw), ROOT)
    med.set_phase(Phase.MAIN_LINE)
    return med


def test_two_failures_downgrade_the_next_stage_target() -> None:
    med = _med(downgrade_after_failures=2)
    med._record_round_outcome(RoundOutcome.FAILURE, "round 1 failure")
    assert med.settings.stage_targets == ["1-21"], "第一次失败不降级"
    assert med._failure_streak == 1

    med._outcome_recorded = False
    med._record_round_outcome(RoundOutcome.FAILURE, "round 2 failure")
    assert med.settings.stage_targets == ["1-20"], "连续两局失败后目标应降为 1-20"
    assert med._failure_streak == 0, "降级后必须清零，避免降级那局还没打就被熔断"

    hit = MatchResult("stage_target_1-20", 1.0, 10, 10, 20, 20, 10, 10)
    frame = _frame()
    with patch("shuabao.mediator.find_stage_labels", return_value=hit) as find_labels:
        target = med._find_stage_target(frame)
    find_labels.assert_called_once_with(frame, med.images, ["1-20"])
    assert target is hit


def test_victory_clears_the_downgrade_counter() -> None:
    med = _med(downgrade_after_failures=2)
    med._record_round_outcome(RoundOutcome.FAILURE, "round 1 failure")
    assert med._failure_streak == 1

    med._outcome_recorded = False
    med._record_round_outcome(RoundOutcome.VICTORY, "round 2 victory")
    assert med._failure_streak == 0
    assert med.settings.stage_targets == ["1-21"], "胜利不触发降级"


def test_zero_disables_downgrade_entirely() -> None:
    med = _med(downgrade_after_failures=0)
    for i in range(5):
        med._outcome_recorded = False
        med._record_round_outcome(RoundOutcome.FAILURE, f"round {i + 1} failure")
    assert med.settings.stage_targets == ["1-21"], "N=0 时行为不变（不降级）"
    assert med._failure_streak == 5


def test_floor_at_1_1_lets_the_hard_fuse_trip_instead_of_looping_forever() -> None:
    med = _med(downgrade_after_failures=1)
    med.settings.stage_targets = ["1-1"]
    med.settings.failure_streak_limit = 3
    for i in range(3):
        med._outcome_recorded = False
        med._record_round_outcome(RoundOutcome.FAILURE, f"round {i + 1} failure at floor")
    assert med.settings.stage_targets == ["1-1"], "已在 1-1 不再降级"
    assert med._failure_streak == 3, "熔断口径必须继续累积，不能被降级逻辑清零"
    assert med._failure_streak >= med.settings.failure_streak_limit


def _frame():
    import numpy as np
    from shuabao.vision.capture import Frame

    return Frame(np.zeros((900, 1600, 3), dtype=np.uint8), window_title="英雄三国KK", hwnd=10001, role="l1")
