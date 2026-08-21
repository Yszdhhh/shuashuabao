"""Targeted coverage for runtime HUD status and skill-card ordering."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from shuabao.choice_policy import (
    DEFAULT_QUALITY_ORDER,
    PolicySettings,
    SlotCandidate,
    _rank_skill_candidates,
    _skill_effective_rarity_rank,
)
from shuabao.settings import Settings
from shuabao.shell.overlay_hud import OverlayHud
from shuabao.shell.runner_service import MediatorWorker
from shuabao.shell.theme_styles import ThemeTokens


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


def test_overlay_is_clickable_stop_and_updates_status(qapp):
    hud = OverlayHud()
    flags = hud.windowFlags()
    assert flags & Qt.WindowType.FramelessWindowHint
    assert flags & Qt.WindowType.WindowStaysOnTopHint
    assert flags & Qt.WindowType.Tool
    assert not (flags & Qt.WindowType.WindowTransparentForInput)
    assert not hud.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert hud.btn_stop is not None
    assert "停止" in hud.btn_stop.text()

    received = []
    hud.stop_requested.connect(lambda: received.append("stop"))
    hud.update_status(True, "MAIN_LINE", "OCR 就绪", 0, 1)
    assert "运行中" in hud.status_text
    assert "OCR 就绪" in hud.status_text
    assert "局数 0/1" in hud.status_text
    assert hud.status_state == "running"
    assert hud.btn_stop.isVisible()
    hud.btn_stop.click()
    assert received == ["stop"]

    hud.update_status(False, "COMPLETE", "OCR 就绪", 1, 1, "已完成指定局数")
    assert "已停止" in hud.status_text
    assert "已完成指定局数" in hud.status_text
    assert hud.status_state == "stopped"
    qss = hud.label.styleSheet().lower()
    assert ThemeTokens.LIGHT["text_primary"].lower() in qss
    assert ThemeTokens.LIGHT["border_focus"].lower() in qss
    hud.close()


def test_overlay_stays_pinned_to_last_game_rect(qapp):
    from PySide6.QtCore import QRect

    hud = OverlayHud()
    hud.anchor_to_target(QRect(100, 200, 1600, 900))
    hud.update_status(True, "STAGE_SELECT", "OCR 就绪", 0, 0)
    y1 = hud.y()
    hud.anchor_to_target(None)
    hud.update_status(True, "STAGE_SELECT", "OCR 就绪", 0, 0)
    assert hud.y() == y1
    hud.close()


def test_catalog_rarity_precedes_hsv_border_color():
    settings = PolicySettings(quality_order=DEFAULT_QUALITY_ORDER)
    # 爆炸箭矢 is catalog-orange; a misleading blue border must not downgrade it.
    slot = SlotCandidate(index=0, name="爆炸箭矢", confidence=0.99, rarity="blue")
    assert _skill_effective_rarity_rank(slot, settings) == DEFAULT_QUALITY_ORDER.index("orange")


def test_purple_arrow_burst_beats_blue_secondary_arrow():
    from shuabao.skill_catalog import expand_skill_preset_names

    families = ("奥术箭", "奥术激光", "奥术射线", "剑气")
    settings = PolicySettings(
        skill_focus_families=families,
        skill_presets=expand_skill_preset_names(families),
        quality_order=DEFAULT_QUALITY_ORDER,
    )
    slots = (
        SlotCandidate(index=0, name="次级箭", confidence=0.99, rarity="purple"),
        SlotCandidate(index=1, name="箭矢连发", confidence=0.99, rarity="purple"),
        SlotCandidate(index=2, name="射线增幅", confidence=0.99, rarity="white"),
    )
    ranked = _rank_skill_candidates(slots, settings, ())
    assert ranked[0] == 1


def test_owned_family_enhancement_beats_unrelated_card():
    settings = PolicySettings(skill_presets=("爆炸箭矢", "剑气"))
    slots = (
        SlotCandidate(index=0, name="爆炸箭矢", confidence=0.99, rarity="blue"),
        SlotCandidate(index=1, name="剑气", confidence=0.99, rarity="orange"),
    )
    assert _rank_skill_candidates(slots, settings, ("奥术箭",)) == [0, 1]


def test_worker_detailed_status_carries_terminal_reason_and_last_action():
    worker = MediatorWorker(Settings(), Path.cwd())
    received: list[tuple] = []
    worker.signals.status_updated.connect(lambda *payload: received.append(payload))
    worker._emit_status(
        False,
        "ERROR",
        2,
        terminal_reason="unhealthy frame timeout",
        ocr_status="就绪",
        last_action="capture",
    )
    assert received == [(False, "ERROR", 2, "unhealthy frame timeout", "就绪", "capture")]
    assert worker.terminal_reason == "unhealthy frame timeout"
    assert worker.last_action == "capture"
