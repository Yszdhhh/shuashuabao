"""LIGHT parchment ThemeTokens is the palette widgets actually paint."""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from shuabao.shell.dual_launch_widget import DualLaunchBoxWidget
from shuabao.shell.main_window import MainWindow, SkillCardGrid
from shuabao.shell.overlay_hud import OverlayHud
from shuabao.shell.pet_hud import FloatingPetHud
from shuabao.shell.theme_styles import ThemeTokens, skill_card_qss, wizard_qss
from shuabao.shell.wizard_dialog import GameStyleWizardDialog


ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_LIGHT_HEX = ("#0d1117", "#161b22", "#151d2e", "#2563eb", "#059669")


@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def _assert_light_qss(qss: str) -> None:
    blob = qss.lower()
    light_vals = {v.lower() for v in ThemeTokens.LIGHT.values()}
    assert any(val in blob for val in light_vals), qss
    for hex_color in FORBIDDEN_LIGHT_HEX:
        assert hex_color not in blob, hex_color


def test_wizard_qss_uses_light_tokens_not_private_island():
    src = (ROOT / "src" / "shuabao" / "shell" / "wizard_dialog.py").read_text(encoding="utf-8")
    assert "WIZARD_LIGHT_QSS" not in src
    assert "wizard_qss" in src
    _assert_light_qss(wizard_qss("light"))


def test_skill_card_grid_consumes_theme_tokens_not_card_qss(qapp):
    src = (ROOT / "src" / "shuabao" / "shell" / "main_window.py").read_text(encoding="utf-8")
    assert "CARD_QSS" not in src
    assert "skill_card_qss" in src
    grid = SkillCardGrid(["asj"], {"asj": "奥术箭"}, theme="light")
    qss = grid.cards["asj"].styleSheet()
    _assert_light_qss(qss)
    assert ThemeTokens.LIGHT["bg_surface"].lower() in qss.lower()
    grid.close()


def test_skill_card_dual_launch_hud_use_light_tokens(qapp):
    light = ThemeTokens.LIGHT
    grid_qss = skill_card_qss("light")
    _assert_light_qss(grid_qss)
    assert light["bg_surface"].lower() in grid_qss.lower()

    dual = DualLaunchBoxWidget(theme="light")
    dual.apply_theme("light")
    _assert_light_qss(dual.box_solo.styleSheet())
    _assert_light_qss(dual.btn_solo.styleSheet())
    _assert_light_qss(dual.box_hitch.styleSheet())
    _assert_light_qss(dual.btn_hitch.styleSheet())
    dual.close()

    pet = FloatingPetHud()
    pet.apply_theme("light")
    _assert_light_qss(pet.lbl_title.styleSheet())
    _assert_light_qss(pet.lbl_broadcast.styleSheet())
    assert pet._palette["bg_surface"] == light["bg_surface"]
    pet.close()

    hud = OverlayHud()
    hud.apply_theme("light")
    hud_qss = hud.label.styleSheet().lower()
    assert "#ffffff" in hud_qss
    assert ThemeTokens.LIGHT["border_focus"].lower() in hud_qss
    hud.close()

    wizard = GameStyleWizardDialog()
    blob = wizard.styleSheet().lower()
    for hex_color in FORBIDDEN_LIGHT_HEX:
        assert hex_color not in blob
    assert light["bg_app"].lower() in blob
    wizard.close()


def test_mainwindow_toggle_theme_defined_once(qapp, tmp_path):
    src = (ROOT / "src" / "shuabao" / "shell" / "main_window.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    count = 0
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "MainWindow":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "toggle_theme":
                    count += 1
    assert count == 1
    window = MainWindow(app_data=tmp_path)
    try:
        window.current_theme = "light"
        window._apply_component_theme()
        _assert_light_qss(window.skill_grid.cards[next(iter(window.skill_grid.cards))].styleSheet())
        _assert_light_qss(window.btn_solo_mode.styleSheet())
    finally:
        window.close()
