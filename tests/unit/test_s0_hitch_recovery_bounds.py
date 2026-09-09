# -*- coding: utf-8 -*-
"""S0 回归：_recovery_failed 的模式隔离。

蹭车（lobby_hitch）：恢复重试耗尽不是终局。没有 fresh GAME-absent
+ PLATFORM 证据时不得清理、不得盲切 LOBBY_ROOM；有证据后才交大厅。
普通模式仍 Fail-Closed。
普通模式：保持 Fail-Closed —— ERROR + stop()。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from shuabao.loop_action import LoopAction
from shuabao.mediator import Mediator, Phase, RecoveryKind
from shuabao.settings import Settings


def _mediator(mode_id: str | None) -> Mediator:
    kwargs = dict(dry_run=True, ocr_mode="off")
    if mode_id is not None:
        kwargs["mode_id"] = mode_id
    return Mediator(Settings(**kwargs), ROOT)


def _begin_recovery(med: Mediator):
    med._begin_recovery(RecoveryKind.FAIL)
    assert med.phase == Phase.RECOVER_FAILURE
    rs = med._recovery_state
    assert rs is not None
    return rs


def test_hitch_recovery_failed_does_not_cleanup_before_evidence() -> None:
    """蹭车恢复耗尽不得先清理再找证据，也不得盲切 LOBBY_ROOM 或停机。"""
    med = _mediator("lobby_hitch")
    rs = _begin_recovery(med)
    with patch.object(med, "_hitch_after_exit") as after_exit, \
            patch.object(med, "stop") as stop, \
            patch.object(med, "_hitch_lobby_handoff_authorized", return_value=False):
        action = med._recovery_failed(rs, "input rejected, attempts exhausted")
    assert action == LoopAction.Continue
    after_exit.assert_not_called()
    assert med.phase == Phase.RECOVER_FAILURE
    stop.assert_not_called()
    assert med._run_exit_reason is None
    assert med._recovery_state is rs
    assert med._hitch_recovery_exhausted is True


def test_hitch_recovery_failed_handoff_only_with_fresh_lobby_evidence() -> None:
    """只有 fresh GAME-absent + PLATFORM 才清理并交大厅；那之前不得重新找房。"""
    med = _mediator("lobby_hitch")
    rs = _begin_recovery(med)
    with patch.object(med, "_hitch_lobby_handoff_authorized", return_value=False):
        assert med._recovery_failed(rs, "recovery timeout") == LoopAction.Continue
    assert med._hitch_re_search is False
    assert med.phase == Phase.RECOVER_FAILURE

    with patch.object(med, "_hitch_lobby_handoff_authorized", return_value=True):
        assert med._recovery_failed(rs, "recovery timeout") == LoopAction.Continue
    assert med._hitch_re_search is True
    assert med.phase == Phase.LOBBY_ROOM
    assert med._run_exit_reason is None


def test_normal_recovery_failed_still_fails_closed() -> None:
    """普通模式保持 Fail-Closed：ERROR + stop()，不进大厅观察。"""
    med = _mediator(None)
    rs = _begin_recovery(med)
    with patch.object(med, "_hitch_after_exit") as after_exit, \
            patch.object(med, "stop") as stop:
        action = med._recovery_failed(rs, "recovery timeout")
    assert action == LoopAction.Break
    assert med.phase == Phase.ERROR
    stop.assert_called_once()
    after_exit.assert_not_called()


def test_normal_recovery_failed_records_incident() -> None:
    """普通模式仍写 incident（hitch 路径不写，避免长期观察刷屏）。"""
    med = _mediator("normal_farm")
    rs = _begin_recovery(med)
    with patch.object(med, "_record_recovery_incident") as record, \
            patch.object(med, "stop"):
        med._recovery_failed(rs, "recovery timeout")
    record.assert_called_once()
