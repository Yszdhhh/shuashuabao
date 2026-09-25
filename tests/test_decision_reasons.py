"""决策原因日志：_note_decision 收集与 trace 落盘。

离线测试，不启动游戏。决策行为本身由既有测试覆盖；这里只验证
"每次隐藏面板/跳过/刷新/去黑商/零输入/选卡决策都在本 tick 的
trace 行里写出 decision_reasons"。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from shuabao.mediator import Frame, LoopAction, Mediator, PanelState, Phase, Settings

ROOT = Path(__file__).resolve().parents[1]
HUD = ROOT / "tests" / "fixtures" / "solo_live_20260914" / "hud_wood_1111_f0200.png"


def _make_mediator(**kwargs) -> Mediator:
    settings = Settings(ocr_mode="off", dry_run=True, **kwargs)
    med = Mediator(settings, ROOT)
    med.set_phase(Phase.MAIN_LINE, "decision reasons unit test")
    med._panel_state = PanelState.CLOSED
    return med


def _hud_frame() -> Frame:
    image = cv2.imdecode(np.fromfile(str(HUD), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    return Frame(image, window_title="英雄三国KK", hwnd=10001, role="l1")


def _trace_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_note_decision_is_emitted_in_trace_row(tmp_path: Path) -> None:
    med = _make_mediator()
    trace_path = tmp_path / "trace.jsonl"
    med.set_trace(str(trace_path))
    try:
        med._note_decision("skip", "单人木材充足且不缺吞噬丹，跳过黑商", wood=2347, bond_occ=6)
        med._note_decision("pick", "选技能卡", panel="skill", card="奥术箭矢", confidence=0.97)
        med._trace_tick("MAIN_LINE", time.perf_counter())
    finally:
        med.set_trace(None)

    rows = _trace_rows(trace_path)
    assert len(rows) == 1
    assert rows[0]["decision_reasons"] == [
        {"kind": "skip", "rule": "单人木材充足且不缺吞噬丹，跳过黑商",
         "inputs": {"wood": 2347, "bond_occ": 6}},
        {"kind": "pick", "rule": "选技能卡",
         "inputs": {"panel": "skill", "card": "奥术箭矢", "confidence": 0.97}},
    ]


def test_note_decision_never_raises_and_defaults_to_empty() -> None:
    med = _make_mediator()
    assert med._tick_decision_reasons == []
    med._note_decision("zero_input", "进化英雄候选识别不清，零输入等下一帧")
    assert med._tick_decision_reasons == [
        {"kind": "zero_input", "rule": "进化英雄候选识别不清，零输入等下一帧", "inputs": {}},
    ]


def test_solo_skip_merchant_notes_decision_reasons() -> None:
    """单人木材充足跳过黑商：真实 _solo_wants_merchant 判 False，trace 留下 skip。"""
    med = _make_mediator()
    frame = _hud_frame()
    med._l1_cycle_step = "merchant"
    med._l1_cycle_index = med._L1_CYCLE_ORDER.index("merchant")
    # 800：≥500 且羁绊未满 → 真实 _solo_wants_merchant 为 False；
    # 又 <1000，不触发“木材充足羁绊优先”编排，能走到 merchant 步骤。
    med._wood_balance = 800
    med._DEVOUR_BOND_OCCUPANCY = 8

    with patch.object(med, "_refresh_solo_signals", return_value=None), \
        patch.object(med, "_evolve_button_hit", return_value=None), \
        patch.object(med, "_bond_bar_occupancy", return_value=6), \
        patch.object(med, "_inventory_has_swallow_pill", return_value=False), \
        patch.object(med, "_devour_hold_reason", return_value=None), \
        patch.object(med, "_maybe_black_merchant") as mock_merchant:
        assert not med._solo_wants_merchant(frame)
        res = med._tick_main_line(frame)
        assert res == LoopAction.Continue
        assert med._l1_cycle_step != "merchant"
        mock_merchant.assert_not_called()

    assert med._tick_decision_reasons == [
        {"kind": "skip", "rule": "单人木材充足且不缺吞噬丹，跳过黑商",
         "inputs": {"wood": 800, "bond_occ": 6}},
    ]
