from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import desktop_app  # noqa: E402


class TestSmartRouteDashboard:
    @classmethod
    def setup_class(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setup_method(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.window = desktop_app.MainWindow(app_data=Path(self.tmp.name))

    def teardown_method(self):
        self.window.close()
        self.tmp.cleanup()

    def _select_arcane_four(self):
        self.window.archive_grid.set_levels(
            {"asj": 47, "asjg": 12, "assx": 30, "jq": 8}
        )
        self.window.skill_grid.set_skills(["asj", "asjg", "assx", "jq"])

    def test_panel_appears_only_when_four_skills_are_selected(self):
        self.window.skill_grid.set_skills(["asj", "asjg", "assx"])
        assert self.window.smart_route_panel.isHidden()

        self._select_arcane_four()
        assert not self.window.smart_route_panel.isHidden()
        assert self.window.smart_route_panel._evaluation.carry is not None
        assert self.window.smart_route_panel._evaluation.carry.code == "asj"
        assert 1 <= len(self.window.smart_route_panel._evaluation.recommendations) <= 2

        self.window.skill_grid.set_skills(["asj", "asjg"])
        assert self.window.smart_route_panel.isHidden()

    def test_only_relevant_archive_rows_and_attr_routes_expand_for_four_skills(self):
        self._select_arcane_four()
        selected = {"asj", "asjg", "assx", "jq"}
        for code, box in self.window.archive_grid.boxes.items():
            holder = box.parentWidget()
            if code in selected:
                assert not holder.isHidden()
            else:
                assert holder.isHidden()

        relevant = set(self.window.smart_route_panel._evaluation.relevant_attr_routes)
        active = set(self.window._selected_attr_routes())
        for route_id, button in self.window.route_buttons.items():
            if route_id in relevant or route_id in active:
                assert not button.isHidden()
            else:
                assert button.isHidden()

        self.window.skill_grid.set_skills(["asj", "asjg", "assx"])
        assert all(not button.isHidden() for button in self.window.route_buttons.values())
        assert all(
            not box.parentWidget().isHidden()
            for box in self.window.archive_grid.boxes.values()
        )

    def test_amplifier_micro_tune_round_trips_through_settings(self):
        self._select_arcane_four()
        assert "assx" in self.window.smart_route_panel._amplifier_boxes
        box = self.window.smart_route_panel._amplifier_boxes["assx"]
        box.setChecked(False)
        collected = self.window.collect_settings_from_ui()
        assert collected.smart_route_disabled_amplifiers == ["assx"]

        self.window.apply_settings_to_ui(collected)
        assert not self.window.smart_route_panel._amplifier_boxes["assx"].isChecked()

    def test_one_click_recommendation_does_not_start_runtime_and_applies_routes(self):
        self._select_arcane_four()
        recommendation = self.window.smart_route_panel._evaluation.recommendations[0]
        assert recommendation.build_id == "arcane_open"
        assert not self.window._is_running()

        self.window._apply_smart_recommendation(recommendation)

        assert not self.window._is_running()
        assert self.window.skill_grid.get_skills() == ["asj", "asjg", "assx", "jq"]
        assert tuple(self.window._selected_attr_routes()) == recommendation.attr_routes
