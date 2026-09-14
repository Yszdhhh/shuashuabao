# -*- coding: utf-8 -*-
"""实机 2026-09-14（hitch_lobby_chain_20260914_000312_456716）战后广场回归。

- 广场上鼠标悬停的 NPC 标签是粗体，另一个是细体。第二局指针停在「存档挑战」，
  「传家宝挑战」为细体，旧的粗体模板只有 0.45-0.57 → 广场不分类 → 传家宝没点。
- 广场帧被 _find_stage_page 误判为选关页（f0353/f0707），在传家宝前后都会
  直接退出；顶栏模式标签（存档/团本）只在局内出现，真实选关页没有。
"""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from shuabao.mediator import LoopAction, Mediator, Phase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "hitch_postgame_20260914"
THIN = "plaza_thin_heirloom_label_f0707.png"
BOLD = "plaza_bold_heirloom_label_f0346.png"
STAGE = "real_stage_page_f0034.png"


def _frame(name: str) -> Frame:
    image = cv2.imdecode(np.fromfile(str(FIXTURES / name), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None, name
    return Frame(image, window_title="英雄三国KK", hwnd=10001, role="l1")


def _mediator() -> Mediator:
    med = Mediator(Settings(dry_run=True, ocr_mode="off", mode_id="lobby_hitch"), ROOT)
    med.set_phase(Phase.MAIN_LINE)
    return med


def _tick(med: Mediator, frame: Frame) -> list[tuple[str, MatchResult]]:
    clicks: list[tuple[str, MatchResult]] = []
    with patch.object(med, "act_click", side_effect=lambda hit, reason, *a, **k: clicks.append((reason, hit)) or True), \
         patch.object(med, "act_key", return_value=True):
        assert med._tick_main_line(frame) is LoopAction.Continue
    return clicks


def test_thin_heirloom_label_classifies_plaza_and_clicks_heirloom_npc() -> None:
    med = _mediator()
    med._post_game_pending = True
    med._post_game_route = "heirloom"
    frame = _frame(THIN)
    assert med._post_game_state(frame) == "NPC_HUB"
    clicks = _tick(med, frame)
    assert [reason for reason, _ in clicks] == ["OpenHeirloomChallenges"]
    hit = clicks[0][1]
    # 传家宝 NPC 在标签正下方（标签 x≈1015..1131, y≈220..247）。
    assert abs(hit.screen_x - 1073) <= 12
    assert med._post_game_route == "heirloom_active"


def test_bold_heirloom_label_still_detected() -> None:
    med = _mediator()
    med._post_game_pending = True
    entry = med._post_game_hub_entry_click(_frame(BOLD), "heirloom")
    assert entry is not None
    assert abs(entry.screen_x - 1081) <= 12


def test_heirloom_active_plaza_misread_as_stage_page_does_not_quit() -> None:
    med = _mediator()
    med._post_game_pending = True
    med._post_game_route = "heirloom_active"
    frame = _frame(THIN)
    # 固定住实机观测到的误判（f0707 上 _find_stage_page 为真），其余全部走真实帧。
    with patch.object(med, "_find_stage_page", return_value=True):
        _tick(med, frame)
    assert med.phase is Phase.MAIN_LINE


def test_post_heirloom_plaza_wait_keeps_60s_rule() -> None:
    frame = _frame(THIN)
    for waited, expected in ((14.0, Phase.MAIN_LINE), (61.0, Phase.QUIT)):
        med = _mediator()
        med._post_game_pending = False
        med._post_game_route = "boss_active"
        med._hitch_heirloom_exit_since = time.time() - waited
        with patch.object(med, "_find_stage_page", return_value=True):
            _tick(med, frame)
        assert med.phase is expected, waited


def test_real_stage_page_has_no_top_bar_mode() -> None:
    """保护只对局内生效：真实选关页没有顶栏模式标签，旧的退出路径不受影响。"""
    med = _mediator()
    frame = _frame(STAGE)
    assert med._find_stage_page(frame)
    assert med._top_bar_mode(frame) is None


def test_transition_route_closes_open_bag_before_waiting_for_entry() -> None:
    """背包盖住广场时入口不可见：必须先关背包，不能零输入干等到 300s 总预算。"""
    med = _mediator()
    med._post_game_pending = True
    med._post_game_route = "heirloom"
    frame = _frame(THIN)
    with patch.object(med, "_post_game_state", return_value=None), \
         patch.object(med, "_bag_layout", return_value=object()), \
         patch.object(med, "_toggle_bag_page", return_value=True) as toggle, \
         patch.object(med, "_post_game_hub_entry_click", return_value=None):
        clicks = _tick(med, frame)
    toggle.assert_called_once()
    assert toggle.call_args[0][1] == "PublicBackpackClose"
    assert clicks == []
    assert med._post_game_route == "heirloom"
