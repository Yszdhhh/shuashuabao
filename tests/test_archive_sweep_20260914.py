# -*- coding: utf-8 -*-
"""存档 8 卡：先 1→8 扫一遍，再复查一轮（Owner 2026-09-14）。

实机 solo_ingame_chain_20260914_212509：宝石/战利品/密钥/祝福/技能2 各被连点 3 次，
旧逻辑每点一张就等它变绿、不绿就重点同一张。新规则：
- 已挑战（绿）或 0/8 的卡永远不点；
- 其它卡在扫卡轮各点一次、点完立即下一张；
- 复查轮只看扫卡轮点过的卡，仍未变绿且非 0/8 的最多补点一次。
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np

from shuabao.mediator import LoopAction, Mediator, Phase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult

ROOT = Path(__file__).resolve().parents[1]
NAMES = ("skill", "strengthen", "gem", "loot", "key", "recast", "blessing", "skill2")


def _med() -> Mediator:
    med = Mediator(Settings(ocr_mode="off"), ROOT)
    med.set_phase(Phase.MAIN_LINE)
    return med


def _frame() -> Frame:
    return Frame(np.zeros((900, 1600, 3), dtype=np.uint8), window_title="英雄三国KK", hwnd=1, role="l1")


def _run(med: Mediator, *, zero_eight: set[int], turns_green: set[int], max_ticks: int = 40):
    green: set[int] = set()
    clicks: list[str] = []
    t = [1000.0]

    def click(hit, reason, *a, **k):
        clicks.append(reason)
        idx = int(hit.name.rsplit("_", 1)[1])
        if idx in turns_green:
            green.add(idx)
        return True

    with patch.object(med, "_find_archive_challenge_card",
                      side_effect=lambda f, i: MatchResult(f"card_{i}", 0.9, 100 + i, 100, 10, 10, 105 + i, 105)), \
         patch.object(med, "_archive_challenge_completed", side_effect=lambda f, i: i in green), \
         patch.object(med, "_archive_hitch_card_unavailable", side_effect=lambda f, i: i in zero_eight), \
         patch.object(med, "act_click", side_effect=click):
        for _ in range(max_ticks):
            t[0] += 2.0
            if med._maybe_click_archive_challenge(_frame(), t[0]) is None:
                break
    return clicks


def test_sweep_clicks_each_available_card_once_and_never_0_8() -> None:
    clicks = _run(_med(), zero_eight={2, 3, 4, 6}, turns_green={0, 1, 5, 7})
    assert clicks == [
        "ArchiveChallenge-skill", "ArchiveChallenge-strengthen",
        "ArchiveChallenge-recast", "ArchiveChallenge-skill2",
    ]


def test_sweep_is_one_pass_left_to_right_without_waiting_for_green() -> None:
    # 没有一张变绿（例如渲染慢）：扫卡轮仍是 1→8 各一次，而不是在第一张上重点。
    clicks = _run(_med(), zero_eight=set(), turns_green=set())
    sweep = [f"ArchiveChallenge-{n}" for n in NAMES]
    verify = [f"ArchiveChallenge-{n}-verify" for n in NAMES]
    assert clicks[:8] == sweep
    assert clicks[8:] == verify, "复查轮每张最多补点一次"


def test_no_card_is_clicked_more_than_twice() -> None:
    clicks = _run(_med(), zero_eight=set(), turns_green=set(), max_ticks=80)
    for name in NAMES:
        assert sum(c.startswith(f"ArchiveChallenge-{name}") and (c == f"ArchiveChallenge-{name}" or c == f"ArchiveChallenge-{name}-verify") for c in clicks) <= 2


def test_already_challenged_cards_are_skipped() -> None:
    med = _med()
    green_before = {0, 1, 2, 3, 4, 5, 6, 7}
    with patch.object(med, "_find_archive_challenge_card",
                      side_effect=lambda f, i: MatchResult(f"card_{i}", 0.9, 1, 1, 1, 1, 1, 1)), \
         patch.object(med, "_archive_challenge_completed", side_effect=lambda f, i: i in green_before), \
         patch.object(med, "_archive_hitch_card_unavailable", return_value=False), \
         patch.object(med, "act_click") as click:
        assert med._maybe_click_archive_challenge(_frame(), 1000.0) is None
    click.assert_not_called()


def test_index_at_end_without_clicks_means_done() -> None:
    # 其它测试用 _archive_challenge_index = 8 表示"已点完"：没有点过的卡就没有复查。
    med = _med()
    med._archive_challenge_index = len(NAMES)
    assert med._maybe_click_archive_challenge(_frame(), 1000.0) is None
