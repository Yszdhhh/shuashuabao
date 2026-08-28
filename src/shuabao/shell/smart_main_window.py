"""Responsive four-skill route layer over the stable dashboard.

Keeping this as a thin subclass deliberately minimizes regression surface in the
large legacy main_window module: the base owns all existing runtime controls and
persistence behavior, while this layer only adds the smart-route card and
narrows advanced controls when exactly four skills are selected.
"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from shuabao.shell.main_window import (
    ATTR_LINE_OPTIONS,
    ATTR_ROUTES,
    OFFICIAL_BUILDS,
    SKILL_LABELS,
    MainWindow as BaseMainWindow,
)
from shuabao.shell.smart_route_panel import SmartRoutePanel
from shuabao.smart_route import RouteEvaluator, RouteRecommendation


_ATTR_LABELS = {
    str(row.get("id") or ""): str(row.get("label") or row.get("id") or "")
    for row in ATTR_LINE_OPTIONS
    if str(row.get("id") or "").strip()
}


class MainWindow(BaseMainWindow):
    """Dashboard with a route card that appears only for a complete 4-skill set."""

    def _build_normal_farm_page(self, lay) -> None:
        super()._build_normal_farm_page(lay)
        self.smart_route_evaluator = RouteEvaluator(
            official_builds=OFFICIAL_BUILDS,
            attr_routes=ATTR_ROUTES,
            skill_labels=SKILL_LABELS,
        )
        self.smart_route_panel = SmartRoutePanel(
            skill_labels=SKILL_LABELS,
            attr_labels=_ATTR_LABELS,
        )
        self.smart_route_panel.apply_requested.connect(self._apply_smart_recommendation)
        self.smart_route_panel.micro_tune_changed.connect(self._on_smart_micro_tune_changed)
        self.smart_route_panel.attr_route_toggled.connect(self._on_smart_attr_route_toggled)
        workspace_layout = self.right_main.layout()
        advanced_index = workspace_layout.indexOf(self.grp_advanced)
        workspace_layout.insertWidget(
            advanced_index if advanced_index >= 0 else workspace_layout.count(),
            self.smart_route_panel,
        )
        self._refresh_smart_route_panel()

    def _selected_attr_routes(self) -> tuple[str, ...]:
        selected = self._shell_extras.get("attr_route") or []
        if isinstance(selected, str):
            selected = [selected]
        return tuple(str(x) for x in selected if str(x).strip())

    def _set_archive_relevance(self, selected_codes: tuple[str, ...] | None) -> None:
        """Show only selected skill archive rows for a complete four-skill route."""
        wanted = set(selected_codes or ())
        show_all = len(wanted) != 4
        for code, box in self.archive_grid.boxes.items():
            holder = box.parentWidget()
            target: QWidget = holder if holder is not None else box
            target.setVisible(show_all or code in wanted)

    def _set_attr_route_relevance(self, relevant: tuple[str, ...] | None) -> None:
        """Hide unrelated route switches, but never hide an already-active route."""
        relevant_set = set(relevant or ())
        active = set(self._selected_attr_routes())
        show_all = len(self.skill_grid.get_skills()) != self.skill_grid.MAX_SKILLS
        for route_id, button in self.route_buttons.items():
            button.setVisible(show_all or route_id in relevant_set or route_id in active)

    def _refresh_smart_route_panel(self) -> None:
        if not hasattr(self, "smart_route_panel") or not hasattr(self, "smart_route_evaluator"):
            return
        selected = tuple(self.skill_grid.get_skills())
        levels = self.archive_grid.get_levels()
        carry_order = getattr(self.settings, "skill_priority", None) or []
        evaluation = self.smart_route_evaluator.evaluate(
            selected, levels,
            carry_priority=str(carry_order[0]) if carry_order else None,
        )
        disabled = tuple(
            str(x) for x in (
                getattr(self.settings, "smart_route_disabled_amplifiers", None) or []
            )
            if str(x).strip()
        )
        self.smart_route_panel.set_evaluation(
            evaluation,
            disabled_amplifiers=disabled,
            selected_attr_routes=self._selected_attr_routes(),
        )
        if len(selected) == self.skill_grid.MAX_SKILLS:
            self._set_archive_relevance(selected)
            self._set_attr_route_relevance(evaluation.relevant_attr_routes)
        else:
            self._set_archive_relevance(None)
            self._set_attr_route_relevance(None)

    def _on_skills_changed(self):
        super()._on_skills_changed()
        self._refresh_smart_route_panel()

    def _on_priority_order_changed(self) -> None:
        super()._on_priority_order_changed()
        self._refresh_smart_route_panel()

    def _on_archive_levels_changed(self):
        super()._on_archive_levels_changed()
        self._refresh_smart_route_panel()

    def _on_attr_route_clicked(self) -> None:
        super()._on_attr_route_clicked()
        self._refresh_smart_route_panel()

    def _on_smart_micro_tune_changed(self) -> None:
        if not hasattr(self, "smart_route_panel"):
            return
        self.settings.smart_route_disabled_amplifiers = list(
            self.smart_route_panel.disabled_amplifiers()
        )
        self._schedule_auto_save()

    def _on_smart_attr_route_toggled(self, route_id: str, checked: bool) -> None:
        button = self.route_buttons.get(route_id)
        if button is None:
            return
        button.blockSignals(True)
        try:
            button.setChecked(bool(checked))
        finally:
            button.blockSignals(False)
        self._shell_extras["attr_route"] = [
            rid for rid, item in self.route_buttons.items() if item.isChecked()
        ]
        self._schedule_auto_save()
        self._refresh_smart_route_panel()

    def _apply_smart_attr_routes(self, route_ids: tuple[str, ...]) -> None:
        wanted = set(route_ids)
        for route_id, button in self.route_buttons.items():
            button.blockSignals(True)
            try:
                button.setChecked(route_id in wanted)
            finally:
                button.blockSignals(False)
        self._shell_extras["attr_route"] = [
            rid for rid, button in self.route_buttons.items() if button.isChecked()
        ]
        self._schedule_auto_save()

    def _apply_smart_recommendation(self, recommendation: RouteRecommendation) -> None:
        if recommendation.build_id:
            super().apply_official_build(recommendation.build_id, confirm=False)
        self._apply_smart_attr_routes(recommendation.attr_routes)
        self._refresh_smart_route_panel()
        self.log(f"[智能流派] 已应用：{recommendation.name}", "info")

    def collect_settings_from_ui(self):
        settings = super().collect_settings_from_ui()
        if hasattr(self, "smart_route_panel") and not self.smart_route_panel.isHidden():
            settings.smart_route_disabled_amplifiers = list(
                self.smart_route_panel.disabled_amplifiers()
            )
        else:
            settings.smart_route_disabled_amplifiers = list(
                getattr(self.settings, "smart_route_disabled_amplifiers", None) or []
            )
        return settings

    def apply_settings_to_ui(self, settings, *, bond_default: bool = False):
        super().apply_settings_to_ui(settings, bond_default=bond_default)
        self._refresh_smart_route_panel()

    def apply_official_build(self, build_id: str, *, confirm: bool = True) -> bool:
        applied = super().apply_official_build(build_id, confirm=confirm)
        if applied:
            self._refresh_smart_route_panel()
        return applied
