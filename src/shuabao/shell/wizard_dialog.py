# -*- coding: utf-8 -*-
import sys
from dataclasses import dataclass, field
from pathlib import Path
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QStackedWidget, QWidget, QRadioButton, QButtonGroup, QGridLayout,
    QComboBox, QCheckBox, QGroupBox, QScrollArea, QFrame
)

@dataclass
class QuickStartSelection:
    mode: str = "solo"
    stage1: int = 1
    stage2: int = 1
    preset_name: str = "电系爆发"
    skills: list[str] = field(default_factory=lambda: ["闪电链", "落雷术", "过载", "雷电精通"])
    bonds: list[str] = field(default_factory=lambda: ["元素", "施法", "急速"])
    is_custom: bool = False

WIZARD_LIGHT_QSS = """
QDialog { background-color: #F6F1E7; color: #2F2A24; font-family: 'Segoe UI', 'Microsoft YaHei'; }
QFrame.wizardCard { background-color: #FBF8F1; border: 1px solid #CDBA93; border-radius: 8px; }
QFrame.wizardCard:hover { border: 1px solid #D8A94A; }
QLabel.wizardTitle { font-size: 16px; font-weight: bold; color: #2F2A24; }
QLabel.wizardSub { font-size: 12px; color: #6A6257; }
QPushButton.goldBtn { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #E5B85C, stop:1 #C89B2D); border: 1px solid #A97822; border-radius: 6px; color: #FFFFFF; font-weight: bold; padding: 6px 16px; min-height: 24px; }
QPushButton.goldBtn:hover { background: #E5B85C; }
QPushButton.secondaryBtn { background-color: #EFE8DA; border: 1px solid #CDBA93; border-radius: 6px; color: #2F2A24; padding: 6px 14px; min-height: 24px; }
QPushButton.secondaryBtn:hover { background-color: #E2DAC8; }
QRadioButton { font-size: 14px; font-weight: bold; color: #2F2A24; spacing: 8px; }
"""

class GameStyleWizardDialog(QDialog):
    run_requested = Signal(dict)
    def __init__(self, parent=None, settings=None, initial_settings=None):
        super().__init__(parent)
        self.setWindowTitle('刷刷宝 - 快速开局向导')
        self.resize(760, 560)
        self.setStyleSheet(WIZARD_LIGHT_QSS)
        self.settings = settings or initial_settings or {}
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Header
        head_box = QHBoxLayout()
        title_lbl = QLabel('⚔️ 快速开局配置')
        title_lbl.setProperty('class', 'wizardTitle')
        head_box.addWidget(title_lbl)
        head_box.addStretch()
        self.step_lbl = QLabel('第 1 / 3 步：模式选择')
        self.step_lbl.setProperty('class', 'wizardSub')
        head_box.addWidget(self.step_lbl)
        layout.addLayout(head_box)

        # Stacked Steps
        self.stack = QStackedWidget()
        self.page_mode = self._create_mode_page()
        self.page_stage = self._create_stage_page()
        self.page_build = self._create_build_page()
        self.stack.addWidget(self.page_mode)
        self.stack.addWidget(self.page_stage)
        self.stack.addWidget(self.page_build)
        layout.addWidget(self.stack, 1)

        # Navigation Bar
        nav_box = QHBoxLayout()
        self.btn_adv = QPushButton('进入高级设置')
        self.btn_adv.setProperty('class', 'secondaryBtn')
        self.btn_adv.clicked.connect(self._on_advanced)
        nav_box.addWidget(self.btn_adv)
        nav_box.addStretch()

        self.btn_prev = QPushButton('上一步')
        self.btn_prev.setProperty('class', 'secondaryBtn')
        self.btn_prev.clicked.connect(self._on_prev)
        self.btn_prev.setEnabled(False)
        nav_box.addWidget(self.btn_prev)

        self.btn_next = QPushButton('下一步')
        self.btn_next.setProperty('class', 'goldBtn')
        self.btn_next.clicked.connect(self._on_next)
        nav_box.addWidget(self.btn_next)

        self.btn_run = QPushButton('直接开始 🚀')
        self.btn_run.setProperty('class', 'goldBtn')
        self.btn_run.clicked.connect(self._on_run)
        self.btn_run.setVisible(False)
        nav_box.addWidget(self.btn_run)

        layout.addLayout(nav_box)

    def _create_mode_page(self):
        w = QWidget()
        l = QVBoxLayout(w)
        desc = QLabel('请选择本次运行的核心模式：')
        desc.setProperty('class', 'wizardTitle')
        l.addWidget(desc)

        self.mode_group = QButtonGroup(w)
        self.rb_solo = QRadioButton('单人刷图模式 (自动建房/全自动化路线)')
        self.rb_ride = QRadioButton('大厅跟车/蹭车模式 (自动搜索车队/跟随压力转移)')
        self.rb_solo.setChecked(True)
        self.mode_group.addButton(self.rb_solo, 0)
        self.mode_group.addButton(self.rb_ride, 1)

        l.addWidget(self.rb_solo)
        l.addWidget(self.rb_ride)
        l.addStretch()
        return w

    def _create_stage_page(self):
        w = QWidget()
        l = QVBoxLayout(w)
        desc = QLabel('请选择挂机目标关卡：')
        desc.setProperty('class', 'wizardTitle')
        l.addWidget(desc)

        form = QHBoxLayout()
        self.cb_chapter = QComboBox()
        self.cb_chapter.addItems(['第 1 篇章 (1-1 ~ 1-6)', '第 2 篇章 (2-1 ~ 2-6)', '第 3 篇章 (3-1 ~ 3-6)'])
        self.cb_stage = QComboBox()
        self.cb_stage.addItems(['关卡 1-1', '关卡 1-2', '关卡 1-3', '关卡 1-4', '关卡 1-5', '关卡 1-6'])
        form.addWidget(QLabel('章节:'))
        form.addWidget(self.cb_chapter)
        form.addWidget(QLabel('关卡:'))
        form.addWidget(self.cb_stage)
        l.addLayout(form)
        l.addStretch()
        return w

    def _create_build_page(self):
        w = QWidget()
        l = QVBoxLayout(w)
        desc = QLabel('技能与羁绊构筑方案：')
        desc.setProperty('class', 'wizardTitle')
        l.addWidget(desc)

        self.cb_preset = QComboBox()
        self.cb_preset.addItems(['电系爆发流', '异火焚天流', '狂暴刀刀暴击流', '自定义技能搭配'])
        self.cb_preset.currentIndexChanged.connect(self._on_preset_changed)
        l.addWidget(QLabel('推荐方案:'))
        l.addWidget(self.cb_preset)

        grid = QGridLayout()
        self.skill_boxes = []
        preset_skills = ["闪电链", "落雷术", "过载", "雷电精通"]
        for i in range(4):
            cb = QComboBox()
            cb.addItems(["闪电链", "落雷术", "过载", "雷电精通", "青莲地心火", "陨落心炎", "电磁场", "暴风雪", "烈焰风暴", "圣光术"])
            cb.setCurrentText(preset_skills[i])
            cb.currentIndexChanged.connect(self._on_custom_changed)
            self.skill_boxes.append(cb)
            grid.addWidget(QLabel(f"技能 {i+1}:"), i // 2, (i % 2) * 2)
            grid.addWidget(cb, i // 2, (i % 2) * 2 + 1)
        l.addLayout(grid)

        self.lbl_status = QLabel("当前状态：预设方案 (电系爆发)")
        self.lbl_status.setProperty('class', 'wizardSub')
        l.addWidget(self.lbl_status)
        self.is_custom = False
        l.addStretch()
        return w

    def _on_preset_changed(self, idx):
        if idx == 3:
            self.is_custom = True
            self.lbl_status.setText("当前状态：自定义搭配")
        else:
            self.is_custom = False
            name = self.cb_preset.currentText()
            self.lbl_status.setText(f"当前状态：预设方案 ({name})")

    def _on_custom_changed(self):
        self.is_custom = True
        self.cb_preset.setCurrentIndex(3)
        self.lbl_status.setText("当前状态：自定义搭配 (已修改)")

    def _collect_payload(self) -> dict:
        mode = "solo" if self.rb_solo.isChecked() else "lobby_hitch"
        skills = [cb.currentText() for cb in getattr(self, "skill_boxes", [])]
        return {
            "mode": mode,
            "stage1": self.cb_chapter.currentIndex() + 1,
            "stage2": self.cb_stage.currentIndex() + 1,
            "preset_name": self.cb_preset.currentText() if hasattr(self, "cb_preset") else "电系爆发",
            "skills": skills or ["闪电链", "落雷术", "过载", "雷电精通"],
            "bonds": ["元素", "施法", "急速"],
            "is_custom": self.is_custom,
        }
    def _on_next(self):
        idx = self.stack.currentIndex()
        if idx < 2:
            self.stack.setCurrentIndex(idx + 1)
            self._update_nav_state()

    def _on_prev(self):
        idx = self.stack.currentIndex()
        if idx > 0:
            self.stack.setCurrentIndex(idx - 1)
            self._update_nav_state()

    def _update_nav_state(self):
        idx = self.stack.currentIndex()
        self.step_lbl.setText(f'第 {idx + 1} / 3 步')
        self.btn_prev.setEnabled(idx > 0)
        if idx == 2:
            self.btn_next.setVisible(False)
            self.btn_run.setVisible(True)
        else:
            self.btn_next.setVisible(True)
            self.btn_run.setVisible(False)

    def get_selection(self) -> QuickStartSelection:
        data = self._collect_payload()
        return QuickStartSelection(
            mode=data.get("mode", "solo"),
            stage1=data.get("stage1", 1),
            stage2=data.get("stage2", 1),
            preset_name=data.get("preset_name", "自定义" if self.is_custom else "电系爆发"),
            skills=data.get("skills", []),
            bonds=data.get("bonds", []),
            is_custom=self.is_custom,
        )

    def _on_run(self):
        self.run_requested.emit(self._collect_payload())
        self.accept()

    def _on_advanced(self):
        self.advanced_requested.emit(self._collect_payload())
        self.accept()
