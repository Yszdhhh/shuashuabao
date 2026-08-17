"""Tests for Dashboard Window minimalism and Core03 preview."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from shuabao.settings import Settings
from shuabao.shell.dashboard_window import (
    DashboardWindow,
    MainWindow,
    SkillCardGrid,
    SkillArchiveLevelGrid,
    DEFAULT_BOND_CODES,
    BASIC_PACK_NAMES,
    ATTR_LINE_OPTIONS,
)
from shuabao.shell.core03_preview import main as preview_main, run_preview

_APP = None


def get_app():
    global _APP
    if _APP is None:
        _APP = QApplication.instance() or QApplication([])
    return _APP


class TestDashboardMinimalism(unittest.TestCase):
    def setUp(self):
        self.app = get_app()
        self.tmp = tempfile.TemporaryDirectory()
        self.save_patch = patch.object(Settings, "save", lambda *a, **k: None)
        self.save_patch.start()
        self.window = DashboardWindow(app_data=Path(self.tmp.name))

    def tearDown(self):
        try:
            self.window.close()
        finally:
            self.save_patch.stop()
            self.tmp.cleanup()

    def test_dashboard_window_is_main_window(self):
        self.assertIs(DashboardWindow, MainWindow)
        self.assertIsInstance(self.window, MainWindow)

    def test_skills_max_four_and_minimal_selection(self):
        grid = self.window.skill_grid
        self.assertEqual(4, grid.MAX_SKILLS)
        valid_stems = list(grid.cards.keys())[:5]
        self.assertGreaterEqual(len(valid_stems), 4)

        # Select 4 valid skills
        grid.set_skills(valid_stems[:4])
        self.assertEqual(valid_stems[:4], grid.get_skills())

        # Attempting to add a 5th skill is prevented
        with patch("shuabao.shell.main_window.QMessageBox.information") as info:
            grid._toggle(valid_stems[4], True)
        info.assert_called_once()
        self.assertEqual(4, len(grid.get_skills()))

    def test_skills_zero_mode_hint_indicates_close_panel(self):
        grid = self.window.skill_grid
        grid.set_skills([])
        self.assertEqual(0, len(grid.get_skills()))
        self.assertIn("关闭", grid._mode_hint_text())

    def test_bonds_default_five_and_editable(self):
        # Default bonds are 5 items: 祝福, 成长, 经济, 贪婪, 挑战
        cards = self.window.collect_settings_from_ui().cards
        self.assertEqual(
            {"zhufu", "chengzhang", "经济", "tanlan", "挑战"},
            set(cards),
        )
        self.assertEqual(5, len(cards))

    def test_attr_routes_independent_and_chain_support_expansion(self):
        # Attribute routes: intelligence, strength, agility
        route_ids = [row["id"] for row in ATTR_LINE_OPTIONS]
        self.assertIn("intelligence", route_ids)
        self.assertIn("strength", route_ids)
        self.assertIn("agility", route_ids)

        # Select intelligence
        self.window.route_buttons["intelligence"].setChecked(True)
        self.window._on_attr_route_clicked()
        cards = self.window.collect_settings_from_ui().cards
        # Must contain chain & support tokens
        self.assertIn("zhili", cards)
        self.assertIn("yanmiezhe", cards)

    def test_core03_preview_entry(self):
        with patch("shuabao.shell.core03_preview.run_preview", return_value=0) as mock_run:
            ret = preview_main()
            self.assertEqual(0, ret)

    def test_core03_preview_app_data_isolated_to_shuabao(self):
        with patch.dict(os.environ, {"LOCALAPPDATA": "C:\\fake\\localappdata"}):
            with patch("shuabao.shell.core03_preview.run_preview") as mock_run:
                preview_main()
                mock_run.assert_called_once()
                app_data_arg = mock_run.call_args.kwargs.get("app_data")
                self.assertIsNotNone(app_data_arg)
                self.assertTrue(str(app_data_arg).endswith("ShuaBao"))
            mock_run.assert_called_once()
