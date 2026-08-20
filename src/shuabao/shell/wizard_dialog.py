# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from shuabao.settings import Settings
from shuabao.shell.theme_styles import wizard_qss

_ROOT = Path(__file__).resolve().parents[3]
_MODE_SIZE = (460, 300)
_PRESET_SIZE = (820, 600)


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


def _load_stage_max() -> dict[int, int]:
    path = _ROOT / "config" / "official_strategy_defaults.json"
    fallback = {1: 23, 2: 7, 3: 9, 4: 3}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback
    out = {}
    for row in doc.get("mainline_stages") or []:
        if isinstance(row, dict) and row.get("chapter") and row.get("count"):
            out[int(row["chapter"])] = int(row["count"])
    return out or fallback


SKILL_META, SKILL_PRESETS = _load_skill_catalog()
STAGE_MAX = _load_stage_max()
CHAPTER_LABELS = {
    1: "旧世界大陆",
    2: "熔火之心",
    3: "黑翼之潮",
    4: "安琪拉",
}


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
    cap = STAGE_MAX.get(chapter, stage)
    stage = min(stage, cap)
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


def _card_button(title: str, subtitle: str) -> QPushButton:
    btn = QPushButton(f"{title}\n{subtitle}")
    btn.setCheckable(True)
    btn.setObjectName("choiceCard")
    btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    btn.setMinimumHeight(92)
    btn.setCursor(Qt.PointingHandCursor)
    return btn


class GameStyleWizardDialog(QDialog):
    run_requested = Signal(dict)
    advanced_requested = Signal(dict)

    def __init__(self, parent=None, settings=None, initial_settings=None):
        super().__init__(parent)
        self.setWindowTitle("选择运行方式")
        self.setModal(True)
        self.resize(*_MODE_SIZE)
        self.setMinimumSize(420, 260)
        self.setStyleSheet(wizard_qss("light"))
        self.settings = settings or initial_settings
        self.is_custom = False
        self._filling = False
        self._preset_index = 0
        self._build_ui()
        self._restore_from_settings()
        self._apply_window_size()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 16)
        layout.setSpacing(14)

        head = QHBoxLayout()
        self.title_lbl = QLabel("选择运行方式")
        self.title_lbl.setObjectName("wizardTitle")
        head.addWidget(self.title_lbl)
        head.addStretch()
        self.step_lbl = QLabel("1 / 2")
        self.step_lbl.setObjectName("wizardSub")
        head.addWidget(self.step_lbl)
        layout.addLayout(head)

        self.stack = QStackedWidget()
        self.page_mode = self._create_mode_page()
        self.page_stage = self._create_preset_page()
        self.page_build = self.page_stage
        self.stack.addWidget(self.page_mode)
        self.stack.addWidget(self.page_stage)
        layout.addWidget(self.stack, 1)

        nav = QHBoxLayout()
        self.btn_adv = QPushButton("进入高级设置")
        self.btn_adv.setObjectName("secondaryBtn")
        self.btn_adv.clicked.connect(self._on_advanced)
        self.btn_adv.setVisible(False)
        nav.addWidget(self.btn_adv)
        nav.addStretch()
        self.btn_prev = QPushButton("上一步")
        self.btn_prev.setObjectName("secondaryBtn")
        self.btn_prev.clicked.connect(self._on_prev)
        self.btn_prev.setVisible(False)
        nav.addWidget(self.btn_prev)
        self.btn_next = QPushButton("下一步")
        self.btn_next.setObjectName("goldBtn")
        self.btn_next.clicked.connect(self._on_next)
        nav.addWidget(self.btn_next)
        self.btn_run = QPushButton("确认选择")
        self.btn_run.setObjectName("goldBtn")
        self.btn_run.clicked.connect(self._on_run)
        self.btn_run.setVisible(False)
        nav.addWidget(self.btn_run)
        layout.addLayout(nav)

    def _create_mode_page(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(0, 4, 0, 0)
        l.setSpacing(12)
        hint = QLabel("先选单人还是组队。确认后会弹出预设选择。")
        hint.setObjectName("wizardSub")
        hint.setWordWrap(True)
        l.addWidget(hint)

        row = QHBoxLayout()
        row.setSpacing(12)
        self.card_solo = _card_button("单人刷图", "自己建房 · 全自动")
        self.card_ride = _card_button("组队蹭车", "大厅搜 3/4 · 跟车")
        self.card_solo.setChecked(True)
        self.mode_group = QButtonGroup(w)
        self.mode_group.setExclusive(True)
        self.mode_group.addButton(self.card_solo, 0)
        self.mode_group.addButton(self.card_ride, 1)
        row.addWidget(self.card_solo, 1)
        row.addWidget(self.card_ride, 1)
        l.addLayout(row, 1)

        self.rb_solo = QRadioButton("单人刷图模式 (自动建房/全自动化路线)")
        self.rb_ride = QRadioButton("大厅跟车/蹭车模式 (自动搜索车队/跟随压力转移)")
        self.rb_solo.setChecked(True)
        self.rb_solo.hide()
        self.rb_ride.hide()
        self.rb_group = QButtonGroup(w)
        self.rb_group.setExclusive(True)
        self.rb_group.addButton(self.rb_solo, 0)
        self.rb_group.addButton(self.rb_ride, 1)
        self.card_solo.toggled.connect(lambda on: on and self.rb_solo.setChecked(True))
        self.card_ride.toggled.connect(lambda on: on and self.rb_ride.setChecked(True))
        self.rb_solo.toggled.connect(lambda on: on and self.card_solo.setChecked(True))
        self.rb_ride.toggled.connect(lambda on: on and self.card_ride.setChecked(True))
        return w

    def _create_preset_page(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(0, 4, 0, 0)
        l.setSpacing(12)

        form = QHBoxLayout()
        form.setSpacing(10)
        self.cb_chapter = QComboBox()
        for chapter in sorted(STAGE_MAX):
            count = STAGE_MAX[chapter]
            name = CHAPTER_LABELS.get(chapter, f"主线{chapter}")
            self.cb_chapter.addItem(f"第 {chapter} 篇章 · {name}（1-{count}）", chapter)
        self.cb_stage = QComboBox()
        form.addWidget(QLabel("篇章"))
        form.addWidget(self.cb_chapter, 1)
        form.addWidget(QLabel("关卡"))
        form.addWidget(self.cb_stage, 1)
        l.addLayout(form)
        self.cb_chapter.currentIndexChanged.connect(self._retarget_stage_combo)
        self._retarget_stage_combo(0)

        grid_host = QFrame()
        grid_host.setObjectName("presetGrid")
        grid = QGridLayout(grid_host)
        grid.setSpacing(12)
        grid.setContentsMargins(0, 0, 0, 0)
        self.preset_group = QButtonGroup(w)
        self.preset_group.setExclusive(True)
        self.preset_cards: list[QPushButton] = []
        shown = list(SKILL_PRESETS[:4])
        while len(shown) < 4:
            shown.append({"name": "预设", "codes": [], "hint": ""})
        for i, preset in enumerate(shown):
            name = str((preset or {}).get("name") or f"预设 {i + 1}")
            short = name.split("（", 1)[0].strip()
            codes = [skill_label(c) for c in (preset.get("codes") or [])[:4]]
            hint = str((preset or {}).get("hint") or " · ".join(codes) or "目录预设")
            btn = _card_button(short, hint)
            btn.setMinimumHeight(110)
            self.preset_group.addButton(btn, i)
            btn.clicked.connect(lambda _=False, idx=i: self._on_preset_changed(idx))
            self.preset_cards.append(btn)
            grid.addWidget(btn, i // 2, i % 2)
        l.addWidget(grid_host, 1)

        self.cb_preset = QComboBox()
        for preset in SKILL_PRESETS:
            name = str((preset or {}).get("name") or "")
            if name:
                self.cb_preset.addItem(name)
        self.cb_preset.addItem("自定义技能搭配")
        self.cb_preset.hide()
        self.cb_preset.currentIndexChanged.connect(self._on_preset_changed)

        codes = list(SKILL_META.keys()) or ["asj", "asjg", "assx", "jq"]
        self.skill_boxes = []
        skill_row = QHBoxLayout()
        skill_row.setSpacing(8)
        for i in range(4):
            cb = QComboBox()
            for code in codes:
                cb.addItem(skill_label(code), code)
            cb.currentIndexChanged.connect(self._on_custom_changed)
            self.skill_boxes.append(cb)
            skill_row.addWidget(cb, 1)
        self.skill_row_host = QWidget()
        self.skill_row_host.setLayout(skill_row)
        self.skill_row_host.setVisible(False)
        l.addWidget(self.skill_row_host)

        self.lbl_status = QLabel("点选一张预设卡片")
        self.lbl_status.setObjectName("wizardSub")
        l.addWidget(self.lbl_status)
        if self.preset_cards:
            self.preset_cards[0].setChecked(True)
            self._apply_preset_index(0)
        return w

    def _stage_cap(self, chapter: int) -> int:
        return max(1, int(STAGE_MAX.get(chapter, 1)))

    def _retarget_stage_combo(self, idx: int = 0) -> None:
        chapter = int(self.cb_chapter.currentData() or (idx + 1))
        cap = self._stage_cap(chapter)
        keep = int(self.cb_stage.currentData() or 1) if self.cb_stage.count() else 1
        self.cb_stage.blockSignals(True)
        self.cb_stage.clear()
        for n in range(1, cap + 1):
            self.cb_stage.addItem(f"{chapter}-{n}", n)
        self.cb_stage.setCurrentIndex(max(0, min(cap, keep) - 1))
        self.cb_stage.blockSignals(False)

    def _apply_preset_index(self, idx: int) -> None:
        preset = catalog_preset_by_index(idx)
        if not preset:
            self.is_custom = True
            self.lbl_status.setText("当前：自定义搭配")
            self.skill_row_host.setVisible(True)
            return
        self._filling = True
        try:
            self.is_custom = False
            self.skill_row_host.setVisible(False)
            codes = [str(c) for c in (preset.get("codes") or [])]
            for i, box in enumerate(self.skill_boxes):
                code = codes[i] if i < len(codes) else ""
                pos = box.findData(code) if code else -1
                if pos >= 0:
                    box.setCurrentIndex(pos)
            name = str(preset.get("name") or "")
            self.lbl_status.setText(f"已选：{name}")
            self._preset_index = idx
            if 0 <= idx < len(self.preset_cards):
                self.preset_cards[idx].setChecked(True)
            if idx < self.cb_preset.count():
                self.cb_preset.blockSignals(True)
                self.cb_preset.setCurrentIndex(idx)
                self.cb_preset.blockSignals(False)
        finally:
            self._filling = False

    def _on_preset_changed(self, idx: int):
        if idx >= len(SKILL_PRESETS):
            self.is_custom = True
            self.lbl_status.setText("当前：自定义搭配")
            self.skill_row_host.setVisible(True)
            self.cb_preset.blockSignals(True)
            self.cb_preset.setCurrentIndex(max(0, self.cb_preset.count() - 1))
            self.cb_preset.blockSignals(False)
            return
        self._apply_preset_index(idx)

    def _on_custom_changed(self):
        if self._filling:
            return
        self.is_custom = True
        self.skill_row_host.setVisible(True)
        custom_idx = self.cb_preset.count() - 1
        if self.cb_preset.currentIndex() != custom_idx:
            self.cb_preset.blockSignals(True)
            self.cb_preset.setCurrentIndex(custom_idx)
            self.cb_preset.blockSignals(False)
        self.lbl_status.setText("当前：自定义搭配（已改技能）")

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
            "stage1": int(self.cb_chapter.currentData() or 1),
            "stage2": int(self.cb_stage.currentData() or 1),
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
            self.card_ride.setChecked(True)
        targets = list(getattr(raw, "stage_targets", None) or [])
        target = str(targets[0]) if targets else ""
        if "-" in target:
            left, right = target.split("-", 1)
            try:
                chapter, stage = int(left), int(right)
            except ValueError:
                chapter, stage = 1, 1
            idx = self.cb_chapter.findData(chapter)
            if idx >= 0:
                self.cb_chapter.setCurrentIndex(idx)
            self._retarget_stage_combo()
            cap = self._stage_cap(chapter)
            self.cb_stage.setCurrentIndex(max(0, min(cap, stage) - 1))
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
                self.skill_row_host.setVisible(True)
                custom_idx = self.cb_preset.count() - 1
                self.cb_preset.setCurrentIndex(custom_idx)
                self.lbl_status.setText("当前：自定义搭配")
            finally:
                self._filling = False

    def _apply_window_size(self) -> None:
        if self.stack.currentIndex() == 0:
            self.setWindowTitle("选择运行方式")
            self.title_lbl.setText("选择运行方式")
            self.resize(*_MODE_SIZE)
            self.setMinimumSize(420, 260)
        else:
            self.setWindowTitle("选择预设")
            self.title_lbl.setText("选择预设")
            self.resize(*_PRESET_SIZE)
            self.setMinimumSize(720, 520)

    def _on_next(self):
        if self.stack.currentIndex() == 0:
            self.stack.setCurrentIndex(1)
            self._update_nav_state()

    def _on_prev(self):
        if self.stack.currentIndex() > 0:
            self.stack.setCurrentIndex(0)
            self._update_nav_state()

    def _update_nav_state(self):
        idx = self.stack.currentIndex()
        self.step_lbl.setText(f"{idx + 1} / 2")
        self.btn_prev.setVisible(idx > 0)
        self.btn_adv.setVisible(idx == 1)
        self.btn_next.setVisible(idx == 0)
        self.btn_run.setVisible(idx == 1)
        self._apply_window_size()

    def get_selection(self) -> QuickStartSelection:
        return selection_from_payload(self._collect_payload())

    def _on_run(self):
        self.run_requested.emit(self._collect_payload())
        self.accept()

    def _on_advanced(self):
        self.advanced_requested.emit(self._collect_payload())
        self.accept()
