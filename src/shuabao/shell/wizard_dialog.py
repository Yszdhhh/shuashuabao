# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from shuabao.settings import Settings
from shuabao.shell.theme_styles import wizard_qss

_ROOT = Path(__file__).resolve().parents[3]
_WIZARD_STAGES_PER_CHAPTER = 6


def _load_skill_catalog() -> tuple[dict[str, dict], list[dict]]:
    path = _ROOT / "config" / "skill_meta.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}, []
    skills = doc.get("skills") if isinstance(doc, dict) else {}
    presets = doc.get("presets") if isinstance(doc, dict) else []
    if not isinstance(skills, dict):
        skills = {}
    if not isinstance(presets, list):
        presets = []
    return skills, presets


SKILL_META, SKILL_PRESETS = _load_skill_catalog()


def skill_label(code: str) -> str:
    meta = SKILL_META.get(code) or {}
    return str(meta.get("label") or code)


def catalog_preset_by_index(idx: int) -> dict | None:
    if 0 <= idx < len(SKILL_PRESETS):
        item = SKILL_PRESETS[idx]
        return item if isinstance(item, dict) else None
    return None


@dataclass
class QuickStartSelection:
    mode: str = "solo"
    stage1: int = 1
    stage2: int = 1
    preset_name: str = ""
    skills: list[str] = field(default_factory=list)
    bonds: list[str] = field(default_factory=list)
    is_custom: bool = False


def apply_quick_start_to_settings(settings: Settings, sel: QuickStartSelection) -> Settings:
    """Pure mapping: wizard selection → Settings fields. No Qt."""
    out = copy.deepcopy(settings)
    mode = str(sel.mode or "solo").strip()
    out.mode_id = "lobby_hitch" if mode in {"lobby_hitch", "hitch", "ride"} else "normal_farm"
    chapter = max(1, int(sel.stage1 or 1))
    stage = max(1, int(sel.stage2 or 1))
    target = f"{chapter}-{stage}"
    out.stage_targets = [target]
    out.stage1 = stage
    out.stage2 = stage
    codes = [str(c).strip() for c in (sel.skills or []) if str(c).strip()]
    out.skills = codes
    if out.mode_id == "lobby_hitch":
        out.auto_create_room = False
        if str(chapter) in {"3", "4"}:
            out.hitch_stage_prefix = str(chapter)
    else:
        out.auto_create_room = True
    return out


def selection_from_payload(payload: dict | QuickStartSelection | None) -> QuickStartSelection:
    if isinstance(payload, QuickStartSelection):
        return payload
    data = payload if isinstance(payload, dict) else {}
    skills = [str(c).strip() for c in (data.get("skills") or []) if str(c).strip()]
    bonds = [str(c).strip() for c in (data.get("bonds") or []) if str(c).strip()]
    return QuickStartSelection(
        mode=str(data.get("mode") or "solo"),
        stage1=int(data.get("stage1") or 1),
        stage2=int(data.get("stage2") or 1),
        preset_name=str(data.get("preset_name") or ""),
        skills=skills,
        bonds=bonds,
        is_custom=bool(data.get("is_custom")),
    )


class GameStyleWizardDialog(QDialog):
    run_requested = Signal(dict)
    advanced_requested = Signal(dict)

    def __init__(self, parent=None, settings=None, initial_settings=None):
        super().__init__(parent)
        self.setWindowTitle("刷刷宝 - 快速开局向导")
        self.resize(760, 560)
        self.setStyleSheet(wizard_qss("light"))
        self.settings = settings or initial_settings
        self.is_custom = False
        self._filling = False
        self._build_ui()
        self._restore_from_settings()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        head_box = QHBoxLayout()
        title_lbl = QLabel("⚔️ 快速开局配置")
        title_lbl.setProperty("class", "wizardTitle")
        head_box.addWidget(title_lbl)
        head_box.addStretch()
        self.step_lbl = QLabel("第 1 / 3 步：模式选择")
        self.step_lbl.setProperty("class", "wizardSub")
        head_box.addWidget(self.step_lbl)
        layout.addLayout(head_box)

        self.stack = QStackedWidget()
        self.page_mode = self._create_mode_page()
        self.page_stage = self._create_stage_page()
        self.page_build = self._create_build_page()
        self.stack.addWidget(self.page_mode)
        self.stack.addWidget(self.page_stage)
        self.stack.addWidget(self.page_build)
        layout.addWidget(self.stack, 1)

        nav_box = QHBoxLayout()
        self.btn_adv = QPushButton("进入高级设置")
        self.btn_adv.setProperty("class", "secondaryBtn")
        self.btn_adv.clicked.connect(self._on_advanced)
        nav_box.addWidget(self.btn_adv)
        nav_box.addStretch()

        self.btn_prev = QPushButton("上一步")
        self.btn_prev.setProperty("class", "secondaryBtn")
        self.btn_prev.clicked.connect(self._on_prev)
        self.btn_prev.setEnabled(False)
        nav_box.addWidget(self.btn_prev)

        self.btn_next = QPushButton("下一步")
        self.btn_next.setProperty("class", "goldBtn")
        self.btn_next.clicked.connect(self._on_next)
        nav_box.addWidget(self.btn_next)

        self.btn_run = QPushButton("直接开始 🚀")
        self.btn_run.setProperty("class", "goldBtn")
        self.btn_run.clicked.connect(self._on_run)
        self.btn_run.setVisible(False)
        nav_box.addWidget(self.btn_run)

        layout.addLayout(nav_box)

    def _create_mode_page(self):
        w = QWidget()
        l = QVBoxLayout(w)
        desc = QLabel("请选择本次运行的核心模式：")
        desc.setProperty("class", "wizardTitle")
        l.addWidget(desc)

        self.mode_group = QButtonGroup(w)
        self.rb_solo = QRadioButton("单人刷图模式 (自动建房/全自动化路线)")
        self.rb_ride = QRadioButton("大厅跟车/蹭车模式 (自动搜索车队/跟随压力转移)")
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
        desc = QLabel("请选择挂机目标关卡：")
        desc.setProperty("class", "wizardTitle")
        l.addWidget(desc)

        form = QHBoxLayout()
        self.cb_chapter = QComboBox()
        self.cb_chapter.addItems(["第 1 篇章 (1-1 ~ 1-6)", "第 2 篇章 (2-1 ~ 2-6)", "第 3 篇章 (3-1 ~ 3-6)"])
        self.cb_stage = QComboBox()
        form.addWidget(QLabel("章节:"))
        form.addWidget(self.cb_chapter)
        form.addWidget(QLabel("关卡:"))
        form.addWidget(self.cb_stage)
        l.addLayout(form)
        l.addStretch()
        self.cb_chapter.currentIndexChanged.connect(self._retarget_stage_combo)
        self._retarget_stage_combo(0)
        return w

    def _retarget_stage_combo(self, idx: int = 0) -> None:
        chapter = int(idx) + 1
        keep = self.cb_stage.currentIndex() if self.cb_stage.count() else 0
        self.cb_stage.blockSignals(True)
        self.cb_stage.clear()
        for n in range(1, _WIZARD_STAGES_PER_CHAPTER + 1):
            self.cb_stage.addItem(f"关卡 {chapter}-{n}", n)
        self.cb_stage.setCurrentIndex(max(0, min(_WIZARD_STAGES_PER_CHAPTER - 1, keep)))
        self.cb_stage.blockSignals(False)

    def _create_build_page(self):
        w = QWidget()
        l = QVBoxLayout(w)
        desc = QLabel("技能与羁绊构筑方案：")
        desc.setProperty("class", "wizardTitle")
        l.addWidget(desc)

        self.cb_preset = QComboBox()
        for preset in SKILL_PRESETS:
            name = str((preset or {}).get("name") or "")
            if name:
                self.cb_preset.addItem(name)
        self.cb_preset.addItem("自定义技能搭配")
        self.cb_preset.currentIndexChanged.connect(self._on_preset_changed)
        l.addWidget(QLabel("推荐方案:"))
        l.addWidget(self.cb_preset)

        grid = QGridLayout()
        self.skill_boxes = []
        codes = list(SKILL_META.keys()) or ["asj", "asjg", "assx", "jq"]
        for i in range(4):
            cb = QComboBox()
            for code in codes:
                cb.addItem(skill_label(code), code)
            cb.currentIndexChanged.connect(self._on_custom_changed)
            self.skill_boxes.append(cb)
            grid.addWidget(QLabel(f"技能 {i + 1}:"), i // 2, (i % 2) * 2)
            grid.addWidget(cb, i // 2, (i % 2) * 2 + 1)
        l.addLayout(grid)

        self.lbl_status = QLabel("当前状态：预设方案")
        self.lbl_status.setProperty("class", "wizardSub")
        l.addWidget(self.lbl_status)
        l.addStretch()
        if SKILL_PRESETS:
            self._apply_preset_index(0)
        return w

    def _apply_preset_index(self, idx: int) -> None:
        preset = catalog_preset_by_index(idx)
        if not preset:
            self.is_custom = True
            self.lbl_status.setText("当前状态：自定义搭配")
            return
        self._filling = True
        try:
            self.is_custom = False
            codes = [str(c) for c in (preset.get("codes") or [])]
            for i, box in enumerate(self.skill_boxes):
                code = codes[i] if i < len(codes) else ""
                pos = box.findData(code) if code else -1
                if pos >= 0:
                    box.setCurrentIndex(pos)
            name = str(preset.get("name") or "")
            self.lbl_status.setText(f"当前状态：预设方案 ({name})")
        finally:
            self._filling = False

    def _on_preset_changed(self, idx: int):
        if idx >= len(SKILL_PRESETS):
            self.is_custom = True
            self.lbl_status.setText("当前状态：自定义搭配")
            return
        self._apply_preset_index(idx)

    def _on_custom_changed(self):
        if self._filling:
            return
        self.is_custom = True
        custom_idx = self.cb_preset.count() - 1
        if self.cb_preset.currentIndex() != custom_idx:
            self.cb_preset.blockSignals(True)
            self.cb_preset.setCurrentIndex(custom_idx)
            self.cb_preset.blockSignals(False)
        self.lbl_status.setText("当前状态：自定义搭配 (已修改)")

    def _skill_codes(self) -> list[str]:
        out = []
        for cb in getattr(self, "skill_boxes", []):
            code = cb.currentData()
            if code:
                out.append(str(code))
        return out

    def _collect_payload(self) -> dict:
        mode = "solo" if self.rb_solo.isChecked() else "lobby_hitch"
        preset_name = self.cb_preset.currentText() if hasattr(self, "cb_preset") else ""
        if self.is_custom:
            preset_name = "自定义"
        return {
            "mode": mode,
            "stage1": self.cb_chapter.currentIndex() + 1,
            "stage2": self.cb_stage.currentIndex() + 1,
            "preset_name": preset_name,
            "skills": self._skill_codes(),
            "bonds": [],
            "is_custom": self.is_custom,
        }

    def _restore_from_settings(self) -> None:
        raw = self.settings
        if raw is None:
            return
        mode_id = str(getattr(raw, "mode_id", "") or "")
        if mode_id == "lobby_hitch":
            self.rb_ride.setChecked(True)
        targets = list(getattr(raw, "stage_targets", None) or [])
        target = str(targets[0]) if targets else ""
        if "-" in target:
            left, right = target.split("-", 1)
            try:
                chapter, stage = int(left), int(right)
            except ValueError:
                chapter, stage = 1, 1
            self.cb_chapter.setCurrentIndex(max(0, min(2, chapter - 1)))
            self._retarget_stage_combo(self.cb_chapter.currentIndex())
            self.cb_stage.setCurrentIndex(max(0, min(_WIZARD_STAGES_PER_CHAPTER - 1, stage - 1)))
        skills = [str(c) for c in (getattr(raw, "skills", None) or [])]
        if skills:
            self._filling = True
            try:
                for i, box in enumerate(self.skill_boxes):
                    if i >= len(skills):
                        break
                    pos = box.findData(skills[i])
                    if pos >= 0:
                        box.setCurrentIndex(pos)
                self.is_custom = True
                custom_idx = self.cb_preset.count() - 1
                self.cb_preset.setCurrentIndex(custom_idx)
                self.lbl_status.setText("当前状态：自定义搭配")
            finally:
                self._filling = False

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
        self.step_lbl.setText(f"第 {idx + 1} / 3 步")
        self.btn_prev.setEnabled(idx > 0)
        if idx == 2:
            self.btn_next.setVisible(False)
            self.btn_run.setVisible(True)
        else:
            self.btn_next.setVisible(True)
            self.btn_run.setVisible(False)

    def get_selection(self) -> QuickStartSelection:
        return selection_from_payload(self._collect_payload())

    def _on_run(self):
        self.run_requested.emit(self._collect_payload())
        self.accept()

    def _on_advanced(self):
        self.advanced_requested.emit(self._collect_payload())
        self.accept()
