"""Responsive dashboard card for four-skill smart-route recommendations."""

from __future__ import annotations

from typing import Mapping

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from shuabao.smart_route import RouteEvaluation, RouteRecommendation, SkillRole


class SmartRoutePanel(QGroupBox):
    """Render role assignments, 1-2 recommendations, and only relevant tuning."""

    apply_requested = Signal(object)
    micro_tune_changed = Signal()
    attr_route_toggled = Signal(str, bool)

    def __init__(
        self,
        *,
        skill_labels: Mapping[str, str],
        attr_labels: Mapping[str, str],
        parent=None,
    ) -> None:
        super().__init__("🎯 核心流派与卡组配置", parent)
        self._skill_labels = dict(skill_labels)
        self._attr_labels = dict(attr_labels)
        self._amplifier_boxes: dict[str, QCheckBox] = {}
        self._attr_boxes: dict[str, QCheckBox] = {}
        self._evaluation = RouteEvaluation((), (), (), ())
        self.setObjectName("smartRoutePanel")
        self.setVisible(False)
        self._root = QVBoxLayout(self)
        self._root.setSpacing(8)
        self._root.setContentsMargins(12, 14, 12, 10)
        self._body = QWidget()
        self._body_lay = QVBoxLayout(self._body)
        self._body_lay.setContentsMargins(0, 0, 0, 0)
        self._body_lay.setSpacing(8)
        self._root.addWidget(self._body)

    @staticmethod
    def _clear_layout(layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.deleteLater()
            elif child_layout is not None:
                while child_layout.count():
                    nested = child_layout.takeAt(0)
                    nested_widget = nested.widget()
                    if nested_widget is not None:
                        nested_widget.deleteLater()

    def _name(self, code: str, fallback: str = "") -> str:
        return str(self._skill_labels.get(code, fallback or code))

    def set_evaluation(
        self,
        evaluation: RouteEvaluation,
        *,
        disabled_amplifiers: tuple[str, ...] = (),
        selected_attr_routes: tuple[str, ...] = (),
    ) -> None:
        self._evaluation = evaluation
        self._clear_layout(self._body_lay)
        self._amplifier_boxes = {}
        self._attr_boxes = {}
        if len(evaluation.roles) != 4:
            self.setVisible(False)
            return
        self.setVisible(True)

        carry = evaluation.carry
        if carry is not None:
            level = f" Lv{carry.archive_level}" if carry.archive_level is not None else " 等级未知"
            headline = QLabel(f"主 C · {self._name(carry.code, carry.family)}{level}")
            headline.setStyleSheet("font-size:14px;font-weight:700;color:#fbbf24;")
            self._body_lay.addWidget(headline)

        amp_names = [self._name(item.code, item.family) for item in evaluation.amplifiers]
        role_note = QLabel(
            "挂件 · " + " / ".join(amp_names)
            + "\n主C优先纯伤害与终极路线；挂件优先跨系增伤、易伤/控制、冷却与覆盖率。"
        )
        role_note.setWordWrap(True)
        role_note.setObjectName("hintLabel")
        self._body_lay.addWidget(role_note)

        for recommendation in evaluation.recommendations[:2]:
            self._body_lay.addWidget(self._recommendation_card(recommendation))

        tune = QGroupBox("与当前 4 技能相关的微调")
        tune_lay = QVBoxLayout(tune)
        disabled = set(disabled_amplifiers)
        for amp in evaluation.amplifiers:
            name = self._name(amp.code, amp.family)
            box = QCheckBox(f"{name}：优先为主C提供联动增伤 / 易伤 / 控制")
            box.setChecked(amp.code not in disabled)
            box.setToolTip("关闭后该挂件回到中性排序；不会扩大可选卡集合，也不会绕过前置/互斥。")
            box.toggled.connect(lambda _checked=False: self.micro_tune_changed.emit())
            self._amplifier_boxes[amp.code] = box
            tune_lay.addWidget(box)

        relevant = tuple(evaluation.relevant_attr_routes)
        if relevant:
            attr_row = QHBoxLayout()
            attr_row.addWidget(QLabel("绑定属性线"))
            selected = set(selected_attr_routes)
            for route_id in relevant:
                box = QCheckBox(self._attr_labels.get(route_id, route_id))
                box.setChecked(route_id in selected)
                box.toggled.connect(
                    lambda checked, rid=route_id: self.attr_route_toggled.emit(rid, bool(checked))
                )
                self._attr_boxes[route_id] = box
                attr_row.addWidget(box)
            attr_row.addStretch()
            tune_lay.addLayout(attr_row)
        self._body_lay.addWidget(tune)

    def _recommendation_card(self, recommendation: RouteRecommendation) -> QWidget:
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { background:#101827; border:1px solid #334155; border-radius:8px; padding:6px; }"
        )
        row = QHBoxLayout(frame)
        text_box = QVBoxLayout()
        title = QLabel(recommendation.name)
        title.setStyleSheet("font-weight:700;color:#e2e8f0;")
        reason = QLabel(recommendation.reason)
        reason.setWordWrap(True)
        reason.setObjectName("hintLabel")
        text_box.addWidget(title)
        text_box.addWidget(reason)
        row.addLayout(text_box, 1)
        button = QPushButton("应用搭配")
        button.setToolTip("应用当前流派卡组与属性线配置。")
        button.clicked.connect(lambda _checked=False, rec=recommendation: self.apply_requested.emit(rec))
        row.addWidget(button)
        return frame

    def disabled_amplifiers(self) -> tuple[str, ...]:
        return tuple(code for code, box in self._amplifier_boxes.items() if not box.isChecked())

    def selected_attr_routes(self) -> tuple[str, ...]:
        return tuple(route for route, box in self._attr_boxes.items() if box.isChecked())
