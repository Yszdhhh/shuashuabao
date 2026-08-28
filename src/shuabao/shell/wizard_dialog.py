# -*- coding: utf-8 -*-
"""向导选择弹窗：模式选择与关卡/预设搭配.

采用 220x160px 等宽等高对称双卡片、2x2 极简预设卡片与统一 36px 高度控件，
去除所有主观冗余废话，极简高级液态玻璃质感。
"""

from __future__ import annotations

import copy
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
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

from shuabao.shell.mode_catalog import badge_text, get_spec
from shuabao.shell.theme_styles import wizard_qss

# 打包后 config/assets 在 _MEIPASS（_internal）下；源码模式按源树回溯仓库根。
_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))
_MODE_SIZE = (480, 360)
_PRESET_SIZE = (840, 580)


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
    1: "第一篇章：旧世界大陆",
    2: "第二篇章：熔火之心",
    3: "第三篇章：黑翼之潮",
    4: "第四篇章：安琪拉",
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
    if mode in {"lobby_hitch", "hitch", "ride"}:
        out.mode_id = "lobby_hitch"
    elif mode in {"follow_team", "follow"}:
        out.mode_id = "follow_team"
    else:
        out.mode_id = "normal_farm"
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
    if out.mode_id in {"lobby_hitch", "follow_team"}:
        out.auto_create_room = False
        if out.mode_id == "lobby_hitch" and str(chapter) in {"3", "4"}:
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


def _card_button(title: str, subtitle: str, icon: str = "") -> QPushButton:
    """创建结构分明的选择卡片."""
    btn = QPushButton()
    btn.setCheckable(True)
    btn.setObjectName("choiceCard")
    btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    btn.setCursor(Qt.PointingHandCursor)

    # 使用整洁的多行富文本或文本排版
    if icon:
        btn.setText(f"{icon}\n\n{title}\n{subtitle}")
    else:
        btn.setText(f"{title}\n\n{subtitle}")
    return btn


class GameStyleWizardDialog(QDialog):
    run_requested = Signal(dict)
    advanced_requested = Signal(dict)

    def __init__(self, parent=None, settings=None, initial_settings=None, theme: str = "dark"):
        super().__init__(parent)
        self.setWindowTitle("快速开局向导")
        root = _ROOT
        logo_ico = root / "assets" / "branding" / "app_logo.ico"
        if not logo_ico.exists():
            logo_ico = root / "assets" / "branding" / "app_logo.png"
        if logo_ico.exists():
            self.setWindowIcon(QIcon(str(logo_ico)))
        self.setModal(True)
        self.resize(*_MODE_SIZE)
        self.setMinimumSize(460, 300)
        self.setStyleSheet(wizard_qss(theme))
        self.settings = settings or initial_settings
        self.is_custom = False
        self._filling = False
        self._preset_index = 0
        self._build_ui()
        self._restore_from_settings()
        self._apply_window_size()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 18)
        layout.setSpacing(16)

        # 顶部头部：应用标 + 眉题 + 标题（原型12 wiz-head）
        head = QHBoxLayout()
        head.setSpacing(10)
        self.mark_lbl = QLabel()
        self.mark_lbl.setFixedSize(30, 30)
        logo = Path(__file__).resolve().parents[3] / "assets" / "branding" / "app_logo.png"
        if not logo.exists():
            logo = Path(__file__).resolve().parents[3] / "assets" / "branding" / "app_logo.ico"
        if logo.exists():
            from PySide6.QtGui import QPixmap

            self.mark_lbl.setPixmap(QPixmap(str(logo)).scaled(
                30, 30, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
        head.addWidget(self.mark_lbl, 0, Qt.AlignTop)

        copy_col = QVBoxLayout()
        copy_col.setSpacing(2)
        self.eyebrow_lbl = QLabel("刷刷宝 · 运行设置")
        self.eyebrow_lbl.setObjectName("wizardStep")
        copy_col.addWidget(self.eyebrow_lbl)
        self.title_lbl = QLabel("选择运行方式")
        self.title_lbl.setObjectName("wizardTitle")
        copy_col.addWidget(self.title_lbl)
        self.copy_lbl = QLabel("先确定队伍关系，再进入看板配置关卡与技能。")
        self.copy_lbl.setObjectName("hintLabel")
        copy_col.addWidget(self.copy_lbl)
        head.addLayout(copy_col)
        head.addStretch()
        self.step_lbl = QLabel("1 / 2")
        self.step_lbl.setObjectName("wizardStep")
        head.addWidget(self.step_lbl, 0, Qt.AlignTop)
        layout.addLayout(head)

        # 分页堆叠区
        self.stack = QStackedWidget()
        self.page_mode = self._create_mode_page()
        self.page_stage = self._create_preset_page()
        self.page_build = self.page_stage
        self.stack.addWidget(self.page_mode)
        self.stack.addWidget(self.page_stage)
        layout.addWidget(self.stack, 1)

        # 底部导航按钮栏
        nav = QHBoxLayout()
        nav.setSpacing(12)
        self.btn_adv = QPushButton("取消")
        self.btn_adv.setObjectName("secondaryBtn")
        self.btn_adv.setCursor(Qt.PointingHandCursor)
        self.btn_adv.clicked.connect(self.reject)
        self.btn_adv.setVisible(True)
        nav.addWidget(self.btn_adv)

        nav.addStretch()

        self.btn_prev = QPushButton("上一步")
        self.btn_prev.setObjectName("secondaryBtn")
        self.btn_prev.setCursor(Qt.PointingHandCursor)
        self.btn_prev.clicked.connect(self._on_prev)
        self.btn_prev.setVisible(False)
        nav.addWidget(self.btn_prev)

        self.btn_next = QPushButton("下一步")
        self.btn_next.setObjectName("goldBtn")
        self.btn_next.setCursor(Qt.PointingHandCursor)
        self.btn_next.clicked.connect(self._on_next)
        nav.addWidget(self.btn_next)

        self.btn_run = QPushButton("应用到看板")
        self.btn_run.setObjectName("goldBtn")
        self.btn_run.setCursor(Qt.PointingHandCursor)
        self.btn_run.clicked.connect(self._on_advanced)
        self.btn_run.setVisible(False)
        nav.addWidget(self.btn_run)

        layout.addLayout(nav)

    def _create_mode_page(self) -> QWidget:
        """Page 1: 原型12 480px 头部卡片 — 单人/组队分段与真实运行方式."""
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(0, 8, 0, 8)
        l.setSpacing(12)

        # 单人/组队分段
        seg_row = QHBoxLayout()
        seg_row.setSpacing(0)
        self.btn_seg_solo = QPushButton("单人")
        self.btn_seg_team = QPushButton("组队")
        for btn in (self.btn_seg_solo, self.btn_seg_team):
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(32)
            seg_row.addWidget(btn)
        self.btn_seg_solo.setChecked(True)
        self.seg_group = QButtonGroup(w)
        self.seg_group.setExclusive(True)
        self.seg_group.addButton(self.btn_seg_solo, 0)
        self.seg_group.addButton(self.btn_seg_team, 1)
        l.addLayout(seg_row)

        # 单人卡（全宽）
        self.card_solo = QPushButton("单人刷图\n自己建房，自己点开始。")
        self.card_solo.setCheckable(True)
        self.card_solo.setObjectName("choiceCard")
        self.card_solo.setMinimumHeight(64)
        self.card_solo.setCursor(Qt.PointingHandCursor)
        self.card_solo.setChecked(True)
        l.addWidget(self.card_solo)

        # 组队行：跟车 / 蹭车（既有 mode id，徽标文案由 desktop_may_start 推导）
        self.row_team = QWidget()
        tl = QVBoxLayout(self.row_team)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(6)
        follow_badge = badge_text(get_spec("follow_team"))
        hitch_badge = badge_text(get_spec("lobby_hitch"))
        self.card_follow = QPushButton(f"跟车 · {follow_badge}\n已在房间，自动每局准备。")
        self.card_ride = QPushButton(f"蹭车 · {hitch_badge}\n自动在大厅找房蹭车。")
        for card in (self.card_follow, self.card_ride):
            card.setCheckable(True)
            card.setObjectName("choiceCard")
            card.setMinimumHeight(64)
            card.setCursor(Qt.PointingHandCursor)
            tl.addWidget(card)
        self.row_team.setVisible(False)
        l.addWidget(self.row_team)

        hint = QLabel("关卡和技能在看板上选，这里只定运行方式。")
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        l.addWidget(hint)
        l.addStretch()

        # 分段切换：单人/组队行可见性 + 金色选中态（复用现有 QSS 对象名）
        def _seg_style():
            for btn in (self.btn_seg_solo, self.btn_seg_team):
                btn.setObjectName("goldBtn" if btn.isChecked() else "secondaryBtn")
                btn.style().unpolish(btn)
                btn.style().polish(btn)

        def _on_seg(idx: int) -> None:
            self.row_team.setVisible(idx == 1)
            self.card_solo.setVisible(idx == 0)
            _seg_style()

        # 三张选择卡互斥
        self.mode_group = QButtonGroup(w)
        self.mode_group.setExclusive(True)
        self.mode_group.addButton(self.card_solo)
        self.mode_group.addButton(self.card_follow)
        self.mode_group.addButton(self.card_ride)

        def _on_seg_toggled(btn, on):
            if on:
                _on_seg(self.seg_group.id(btn))

        self.seg_group.buttonToggled.connect(_on_seg_toggled)
        _seg_style()

        # 隐藏单选组驱动 payload；卡片与单选互相同步
        self.rb_solo = QRadioButton("单人模式")
        self.rb_follow = QRadioButton("跟车模式")
        self.rb_ride = QRadioButton("多人模式")
        self.rb_solo.setChecked(True)
        self.rb_group = QButtonGroup(w)
        self.rb_group.setExclusive(True)
        self.rb_group.addButton(self.rb_solo, 0)
        self.rb_group.addButton(self.rb_follow, 1)
        self.rb_group.addButton(self.rb_ride, 2)
        for rb in (self.rb_solo, self.rb_follow, self.rb_ride):
            rb.hide()

        self.card_solo.toggled.connect(lambda on: on and self.rb_solo.setChecked(True))
        self.card_follow.toggled.connect(lambda on: on and self.rb_follow.setChecked(True))
        self.card_ride.toggled.connect(lambda on: on and self.rb_ride.setChecked(True))
        return w

    def _create_preset_page(self) -> QWidget:
        """Page 2: 统一 36px 下拉框 + 2x2 网格预设卡片."""
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(0, 4, 0, 0)
        l.setSpacing(14)

        # 篇章与关卡选择栏 (统一 36px 舒适高度)
        form = QHBoxLayout()
        form.setSpacing(12)

        lbl_ch = QLabel("篇章")
        lbl_ch.setObjectName("sectionCap")
        self.cb_chapter = QComboBox()
        self.cb_chapter.setFixedHeight(36)
        for chapter in sorted(STAGE_MAX):
            name = CHAPTER_LABELS.get(chapter, f"第{chapter}篇章")
            self.cb_chapter.addItem(name, chapter)

        lbl_st = QLabel("关卡")
        lbl_st.setObjectName("sectionCap")
        self.cb_stage = QComboBox()
        self.cb_stage.setFixedHeight(36)

        form.addWidget(lbl_ch)
        form.addWidget(self.cb_chapter, 3)
        form.addWidget(lbl_st)
        form.addWidget(self.cb_stage, 2)
        l.addLayout(form)

        self.cb_chapter.currentIndexChanged.connect(self._retarget_stage_combo)
        self._retarget_stage_combo(0)

        # 2x2 流派预设网格
        grid_host = QFrame()
        grid_host.setObjectName("presetGrid")
        grid = QGridLayout(grid_host)
        grid.setSpacing(12)
        grid.setContentsMargins(0, 4, 0, 4)

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
            skills_text = "  ·  ".join(codes) if codes else "无技能"

            btn = _card_button(short, skills_text)
            btn.setMinimumHeight(100)
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

        # 自定义技能微调行
        codes = list(SKILL_META.keys()) or ["asj", "asjg", "assx", "jq"]
        self.skill_boxes = []
        skill_row = QHBoxLayout()
        skill_row.setSpacing(8)
        for i in range(4):
            cb = QComboBox()
            cb.setFixedHeight(32)
            cb.addItem("未选择", "")
            for code in codes:
                cb.addItem(skill_label(code), code)
            cb.currentIndexChanged.connect(self._on_custom_changed)
            self.skill_boxes.append(cb)
            skill_row.addWidget(cb, 1)
        self.skill_row_host = QWidget()
        self.skill_row_host.setLayout(skill_row)
        self.skill_row_host.setVisible(False)
        l.addWidget(self.skill_row_host)

        self.lbl_status = QLabel("已选：推荐流派")
        self.lbl_status.setObjectName("hintLabel")
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
            self.lbl_status.setText(f"已选流派：{name}")
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
        self.lbl_status.setText("当前：自定义搭配（已微调技能）")

    def _skill_codes(self) -> list[str]:
        out = []
        for cb in getattr(self, "skill_boxes", []):
            code = cb.currentData()
            if code:
                out.append(str(code))
        return out

    def _collect_payload(self) -> dict:
        if self.rb_solo.isChecked():
            mode = "solo"
        elif self.rb_follow.isChecked():
            mode = "follow_team"
        else:
            mode = "lobby_hitch"
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
            if not self.row_team.isVisible():
                self.btn_seg_team.setChecked(True)
                self.seg_group.idClicked.emit(1)
        elif mode_id == "follow_team":
            self.rb_follow.setChecked(True)
            self.card_follow.setChecked(True)
            if not self.row_team.isVisible():
                self.btn_seg_team.setChecked(True)
                self.seg_group.idClicked.emit(1)
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
                    code = skills[i] if i < len(skills) else ""
                    pos = box.findData(code)
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
            self.setMinimumSize(460, 300)
        else:
            self.setWindowTitle("选择关卡与流派预设")
            self.title_lbl.setText("选择关卡与流派预设")
            self.resize(*_PRESET_SIZE)
            self.setMinimumSize(740, 520)

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
        self.btn_adv.setVisible(True)
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
