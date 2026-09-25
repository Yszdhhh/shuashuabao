"""Real top-bar stage labels from the 2026-09-25 20-round hitch run.

Each fixture keeps the real top-bar pixels of one round's in-game frame; the
rest of the 1600x900 canvas is black.  Rounds 4-20 were 3-9 / 4-9, which the
detector used to read as 3-0 / 4-0, so the per-round stage stats were wrong.
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from shuabao.vision.capture import Frame
from shuabao.vision.stage_selector import detect_ingame_stage_label

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "hud_stage_20260925"
INDEX = json.loads((FIXTURES / "index.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", sorted(INDEX))
def test_live_topbar_stage_label(name: str) -> None:
    bgr = cv2.imdecode(np.fromfile(str(FIXTURES / name), dtype=np.uint8), cv2.IMREAD_COLOR)
    stage = detect_ingame_stage_label(Frame(bgr), ROOT / "assets" / "Images")
    assert str(stage) == INDEX[name]["expected"]


def test_stage_zero_is_never_a_real_stage() -> None:
    from shuabao.vision.stage_selector import StageId

    assert StageId.parse("4-0") is None
    assert StageId.parse("0-3") is None
    assert str(StageId.parse("4-10")) == "4-10"
    assert str(StageId.parse("1-1")) == "1-1"


def test_state_snapshot_carries_the_round_stage() -> None:
    """The per-round stage must land in the trace, not only on stdout."""
    import sys

    sys.path.insert(0, str(ROOT / "tools"))
    from live_scenario_capture import _state_snapshot
    from shuabao.mediator import Mediator
    from shuabao.settings import Settings

    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    med._hitch_stats_current_stage = "4-9"
    med._hitch_stats_stages = {"3-9": 1, "4-9": 16}
    med._hitch_stats_current_challenges = ["金币(确认开启)"]
    state = _state_snapshot(med)
    assert state["hitch_round_stage"] == "4-9"
    assert state["hitch_stage_counts"] == {"3-9": 1, "4-9": 16}
    assert state["hitch_round_challenges"] == ["金币(确认开启)"]
