"""控制中心主窗：液态玻璃排版、模式选择、流派卡牌与底栏控制."""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)
from shuabao.shell.pet_hud import FloatingPetHud
from shuabao.shell.theme_styles import (
    apply_app_palette,
    get_qss,
    mode_button_qss,
    official_build_qss,
    skill_card_qss,
    tokens,
)
from shuabao.shell.wizard_dialog import (
    GameStyleWizardDialog,
    apply_quick_start_to_settings,
    selection_from_payload,
)

from shuabao import __version__
from shuabao.settings import MAX_SELECTED_SKILLS, Settings
from shuabao.shell.mode_catalog import (
    collect_persistable_settings,
    badge_text,
    desktop_may_start,
    get_spec,
    iter_specs,
    start_button_text,
)
from shuabao.shell.runner_service import (
    MediatorWorker,
    ModeNotEnabled,
    RunnerService,
    live_lock_busy,
)
from shuabao.shell.runtime_status import progress_from_counts
from shuabao.shell.overlay_hud import OverlayHud
from shuabao.shell.test_profiles import (
    TestProfileError,
    apply_profile,
    export_profile,
    load_test_profiles,
    profile_diff,
    validate_profile_document,
)

APP_NAME = "刷刷宝"
APP_ID = "ShuaBao"
APP_VERSION_LABEL = f"V{__version__}" if not str(__version__).upper().startswith("V") else str(__version__)
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))
if not (ROOT / "config").is_dir():
    ROOT = Path(__file__).resolve().parents[3]

SHELL_SCHEMA_VERSION = 2


def _app_data_dir() -> Path:
    override = os.environ.get("SHUABAO_APP_DATA")
    if override:
        return Path(override)
    return Path(os.environ.get("LOCALAPPDATA", ROOT)) / APP_ID


APP_DATA = _app_data_dir()
FACTORY_SETTINGS = ROOT / "config" / "default_settings.json"
USER_SETTINGS_NAME = "user_settings.json"
TEST_PROFILES_PATH = ROOT / "config" / "dashboard_test_profiles.json"
LOG_FILE = APP_DATA / "logs" / f"{APP_ID}.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
LOGGER = logging.getLogger(APP_ID)
if not LOGGER.handlers:
    LOGGER.setLevel(logging.INFO)
    _handler = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOGGER.addHandler(_handler)


def _stems(folder: Path) -> list[str]:
    if not folder.is_dir():
        return []
    return sorted(p.stem for p in folder.glob("*.png"))


def _load_json_doc(file_path: Path) -> dict:
    if file_path.is_file():
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


SKILL_STEMS = _stems(ROOT / "assets" / "Images" / "skills") or [
    "asj", "asjg", "assx", "bsxx", "byj", "dcw", "dz", "hbj",
    "hq", "jf", "jq", "ljf", "pg", "sdl", "tl", "ys",
]
SKILL_LABELS = {
    str(k): str(v)
    for k, v in _load_json_doc(ROOT / "config" / "skill_labels.json").items()
    if not str(k).startswith("_") and isinstance(v, str)
}
SKILL_ICON_DIR = ROOT / "assets" / "Images" / "skills"
_SKILL_META_DOC = _load_json_doc(ROOT / "config" / "skill_meta.json")
SKILL_META: dict[str, dict] = _SKILL_META_DOC.get("skills") or {}
SKILL_PRESETS: list[dict] = _SKILL_META_DOC.get("presets") or []
_CHOICE_POLICY_DOC = _load_json_doc(ROOT / "config" / "choice_policy.json")
_TREASURE_POLICY = _CHOICE_POLICY_DOC.get("treasure") or {}
NEGATIVE_TREASURES: list[str] = list(_TREASURE_POLICY.get("negative_names") or [])
MUST_TAKE_TREASURES: list[str] = list(_TREASURE_POLICY.get("must_take_names") or [])
_FETTER_DOC = _load_json_doc(ROOT / "config" / "fetter_labels.json")
FETTER_LABELS: dict[str, str] = {
    str(k): str(v)
    for k, v in _FETTER_DOC.items()
    if not str(k).startswith("_") and isinstance(v, str) and v.strip()
}
FETTER_NAME_TO_CODE = {name: code for code, name in FETTER_LABELS.items()}
_STRATEGY = _load_json_doc(ROOT / "config" / "official_strategy_defaults.json")
OFFICIAL_BUILDS: list[dict] = [b for b in (_STRATEGY.get("builds") or []) if isinstance(b, dict)]
ATTR_ROUTES: dict[str, dict] = {
    k: v for k, v in (_STRATEGY.get("attr_routes") or {}).items()
    if isinstance(v, dict) and not str(k).startswith("_")
}
BOND_PRIORITY: dict = _STRATEGY.get("bond_priority") or {}
_CARD_PACKS = _STRATEGY.get("card_packs") or {}
BASIC_PACK_NAMES = [
    str(name) for name in ((_CARD_PACKS.get("basic") or {}).get("cards") or []) if str(name).strip()
] or ["祝福", "成长", "经济", "贪婪", "挑战", "提速", "体术", "固守", "陷阵", "急速", "力量", "智力", "敏捷"]
ADVANCED_PACKS: dict[str, dict] = {
    str(key): value
    for key, value in (_CARD_PACKS.get("advanced") or {}).items()
    if isinstance(value, dict) and not str(key).startswith("_")
}
ATTR_LINE_OPTIONS: list[dict] = [
    row for row in ((_CARD_PACKS.get("attr_line") or {}).get("options") or [])
    if isinstance(row, dict) and row.get("id")
] or [
    {"id": "intelligence", "label": "智力", "gate": "智力", "ur": "湮灭者"},
    {"id": "strength", "label": "力量", "gate": "力量", "ur": "屠戮者"},
    {"id": "agility", "label": "敏捷", "gate": "敏捷", "ur": "收割者"},
]
MAINLINE_STAGES: list[tuple[int, int, str]] = [
    (int(row["chapter"]), int(row["count"]), str(row.get("label") or f"主线{row['chapter']}"))
    for row in (_STRATEGY.get("mainline_stages") or [])
    if isinstance(row, dict) and row.get("chapter") and row.get("count")
] or [(1, 23, "主线1"), (2, 7, "主线2"), (3, 9, "主线3"), (4, 3, "主线4")]
STAGE_MAX = {chapter: count for chapter, count, _label in MAINLINE_STAGES}
MAINLINE_DISPLAY = {
    1: "旧世界大陆（一阶段）",
    2: "熔火之心（二阶段）",
    3: "黑翼之潮（三阶段）",
    4: "安琪拉（四阶段）",
}
_BOND_STACK = _load_json_doc(ROOT / "config" / "bond_stack_catalog.json")
BOND_STACK_NAMES = set((_BOND_STACK.get("needs") or {}).keys())
FACTIONS = (
    ("黑锋骑士团", 1),
    ("银色北伐军", 2),
    ("肯瑞托", 3),
    ("探险者协会", 4),
    ("元素领主", 5),
    ("守护巨龙", 6),
)

FACTION_TIPS = {
    1: "黑锋骑士团：亡灵 / 召唤 / 近战吸血",
    2: "银色北伐军：神圣 / 护甲 / 坦度与反伤",
    3: "肯瑞托：奥术 / 法术 / 冷却缩减（智力法系推荐）",
    4: "探险者协会：物理穿透 / 暴击 / 移动速度（敏捷物理流）",
    5: "元素领主：火 / 冰 / 电多元素混合爆发",
    6: "守护巨龙：龙族 / 生命上限 / 终极伤害",
}

_REPUTATION_KB_PATH = ROOT / "config" / "reputation_factions_kb.json"


def _load_reputation_kb() -> dict:
    try:
        return json.loads(_REPUTATION_KB_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"factions": {}, "bosses": {}}


_SKILL_ROUTES_PATH = ROOT / "config" / "skill_routes.json"


def _load_skill_routes() -> dict[str, str]:
    try:
        data = json.loads(_SKILL_ROUTES_PATH.read_text(encoding="utf-8"))
        routes = data.get("routes")
        return {str(k): str(v) for k, v in routes.items()} if isinstance(routes, dict) else {}
    except Exception:
        return {}


SKILL_ROUTES: dict[str, str] = _load_skill_routes()



def _load_skill_route_families() -> dict:
    """skill_routes.json v2 的 families 段；缺失/为空时返回空 dict（UI 隐藏路线下拉）。"""
    try:
        data = json.loads(_SKILL_ROUTES_PATH.read_text(encoding="utf-8"))
        fams = data.get("families")
        return {str(k): v for k, v in fams.items()} if isinstance(fams, dict) else {}
    except Exception:
        return {}


SKILL_ROUTE_FAMILIES: dict = _load_skill_route_families()


def _align_label(text: str, width: int) -> QLabel:
    """右对齐定宽标签：消除同行混排 label 的锯齿。"""
    lbl = QLabel(text)
    lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    lbl.setFixedWidth(width)
    return lbl


_STAGE_UNLOCKS_PATH = ROOT / "config" / "stage_unlocks.json"


def _load_stage_unlocks() -> dict[str, dict[str, str]]:
    try:
        data = json.loads(_STAGE_UNLOCKS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


STAGE_UNLOCKS: dict[str, dict[str, str]] = _load_stage_unlocks()


def _apply_native_titlebar_theme(widget, theme: str) -> None:
    """Windows：把系统标题栏染成跟随主题（深色 UI 配深标题栏），消除白色系统框。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        hwnd = int(widget.winId())
        value = ctypes.c_int(0 if str(theme).lower() == "light" else 1)
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE（旧版本号 19）
            if (
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd,
                    ctypes.c_int(attribute),
                    ctypes.byref(value),
                    ctypes.sizeof(value),
                )
                == 0
            ):
                break
    except Exception:
        pass


def skill_display_name(code: str) -> str:
    meta = SKILL_META.get(code) or {}
    return str(meta.get("label") or SKILL_LABELS.get(code, code))


def bond_display_name(code: str) -> str:
    return FETTER_LABELS.get(code, code)


def code_for_bond_name(name: str) -> str | None:
    return FETTER_NAME_TO_CODE.get(name)


DEFAULT_BOND_CODES: list[str] = [
    code_for_bond_name(str(name)) or str(name)
    for name in (BOND_PRIORITY.get("round1_must") or [])
    if str(name).strip()
]
BOND_ALWAYS_CODES = ["zhufu"]
BASIC_PACK_UI_NAMES = [name for name in BASIC_PACK_NAMES if name != "祝福"]
TREASURE_UI_HIDDEN = frozenset({"金转木"})


def _is_admin() -> bool:
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


class SkillCardGrid(QWidget):
    """中文技能卡片多选网格：显示中文名，内部存拼音短码，最多 4 个。"""

    MAX_SKILLS = MAX_SELECTED_SKILLS
    skills_changed = Signal()

    def __init__(self, skill_stems: list[str], skill_labels: dict[str, str], parent=None, theme: str = "dark"):
        super().__init__(parent)
        self.skill_stems = skill_stems
        self.skill_labels = skill_labels
        self.cards: dict[str, QPushButton] = {}
        self._selected: list[str] = []
        self._theme = theme
        self._init_ui()

    def apply_theme(self, theme: str = "dark") -> None:
        self._theme = theme
        qss = skill_card_qss(theme)
        for btn in self.cards.values():
            btn.setStyleSheet(qss)

    def _tooltip_for(self, code: str) -> str:
        meta = SKILL_META.get(code) or {}
        name = meta.get("label") or self.skill_labels.get(code, "未命名技能")
        desc = (meta.get("description") or "").strip()
        body = desc if desc else "说明待补（尚无实机卡面截图，未编造数值）"
        return f"<b>{name}</b><br/>{body}<br/><span style='color:#E5A93C'>短码 {code}</span>"

    def _init_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        self.hint = QLabel(self._mode_hint_text())
        self.hint.setObjectName("hintLabel")
        top_row.addWidget(self.hint, 1)

        clear_btn = QPushButton("清空技能")
        clear_btn.setFixedSize(80, 28)
        clear_btn.setCursor(Qt.PointingHandCursor)
        clear_btn.clicked.connect(lambda: self.set_skills([]))
        top_row.addWidget(clear_btn)
        lay.addLayout(top_row)

        grid = QGridLayout()
        grid.setSpacing(8)
        grid.setContentsMargins(0, 0, 0, 0)

        for idx, code in enumerate(self.skill_stems):
            cn = skill_display_name(code)
            btn = QPushButton(cn)
            btn.setCheckable(True)
            btn.setMinimumHeight(44)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.setCursor(Qt.PointingHandCursor)

            icon_path = SKILL_ICON_DIR / f"{code}.png"
            if icon_path.is_file():
                btn.setIcon(QIcon(str(icon_path)))
                btn.setIconSize(QSize(22, 22))

            btn.setStyleSheet(skill_card_qss(self._theme))
            btn.setToolTip(self._tooltip_for(code))
            btn.clicked.connect(lambda checked, c=code: self._toggle(c, checked))
            self.cards[code] = btn
            grid.addWidget(btn, idx // 4, idx % 4)

        lay.addLayout(grid)

    def _toggle(self, code: str, checked: bool):
        if checked:
            if code not in self._selected:
                if len(self._selected) >= self.MAX_SKILLS:
                    self.cards[code].setChecked(False)
                    QMessageBox.information(self, "技能限制", f"技能最多选择 {self.MAX_SKILLS} 个")
                    return
                self._selected.append(code)
        elif code in self._selected:
            self._selected.remove(code)
        self._refresh_cards()
        self._refresh_hint()
        self.skills_changed.emit()

    def set_skills(self, codes: list[str]):
        self._selected = [c for c in codes if c in self.cards][: self.MAX_SKILLS]
        for code, btn in self.cards.items():
            btn.setChecked(code in self._selected)
        self._refresh_cards()
        self._refresh_hint()
        self.skills_changed.emit()

    def get_skills(self) -> list[str]:
        return list(self._selected)

    def selected_names(self) -> list[str]:
        return [skill_display_name(code) for code in self._selected]

    def _refresh_cards(self):
        order = {code: index + 1 for index, code in enumerate(self._selected)}
        for code, btn in self.cards.items():
            name = skill_display_name(code)
            btn.setText(f"{order[code]}. {name}" if code in order else name)

    def _mode_hint_text(self) -> str:
        count = len(self._selected)
        if count == 0:
            return "当前已选 0 个技能：不自动学习任何技能（技能面板直接关闭/隐藏，不刷新、不放弃技能点）。"
        return f"当前已选 {count} 个技能【严格模式】：仅学习勾选技能，未选中的永远不学。"

    def _refresh_hint(self):
        if hasattr(self, "hint"):
            self.hint.setText(self._mode_hint_text())


class SkillPriorityBar(QWidget):
    """横向优先级 chips 条：拖拽排序=优先级（索引 0 最高），chip 内嵌属性路线下拉。"""

    order_changed = Signal()
    route_changed = Signal(str, str)  # slug, route_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self._families: dict = SKILL_ROUTE_FAMILIES
        self._route_prefs: dict[str, str] = {}
        self._syncing = False
        self._flush_pending = False
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        cap = QLabel("优先级")
        cap.setObjectName("hintLabel")
        lay.addWidget(cap)
        self.chip_list = QListWidget()
        self.chip_list.setObjectName("skillPriorityList")
        self.chip_list.setViewMode(QListWidget.IconMode)
        self.chip_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.chip_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.chip_list.setFixedHeight(46)
        self.chip_list.setSpacing(4)
        self.chip_list.model().rowsInserted.connect(self._queue_order_flush)
        self.chip_list.model().rowsRemoved.connect(self._queue_order_flush)
        lay.addWidget(self.chip_list, 1)

    def rebuild(self, codes: list[str], route_prefs: dict[str, str] | None = None) -> None:
        """按给定顺序重建 chips（调用方负责合并已有顺序与新选追加）。"""
        self._syncing = True
        try:
            self._route_prefs = dict(route_prefs or {})
            self.chip_list.clear()
            for code in codes:
                item = QListWidgetItem(skill_display_name(code))
                item.setData(Qt.ItemDataRole.UserRole, str(code))
                item.setSizeHint(QSize(176, 40))
                self.chip_list.addItem(item)
                self.chip_list.setItemWidget(item, self._make_chip(str(code)))
        finally:
            self._syncing = False

    def _make_chip(self, code: str) -> QWidget:
        host = QWidget()
        h = QHBoxLayout(host)
        h.setContentsMargins(10, 2, 6, 2)
        h.setSpacing(4)
        combo = QComboBox()
        combo.setObjectName("skillRouteCombo")
        routes = ((self._families or {}).get(code) or {}).get("routes") or []
        for spec in routes:
            rid = str(spec.get("id") or "")
            if rid:
                combo.addItem(str(spec.get("label") or rid), rid)
        if combo.count() > 0:
            preferred = self._route_prefs.get(code)
            idx = combo.findData(preferred)
            combo.setCurrentIndex(idx if idx >= 0 else 0)
            combo.currentIndexChanged.connect(
                lambda _i, c=code, cb=combo: self._on_route_changed(c, cb)
            )
        else:
            combo.setVisible(False)  # families 缺失/为空：优雅隐藏路线下拉
        h.addWidget(combo, 1)
        return host

    def _on_route_changed(self, code: str, combo: QComboBox) -> None:
        if self._syncing:
            return
        self.route_changed.emit(code, str(combo.currentData() or ""))

    def order(self) -> list[str]:
        out: list[str] = []
        for i in range(self.chip_list.count()):
            data = self.chip_list.item(i).data(Qt.ItemDataRole.UserRole)
            if data:
                out.append(str(data))
        return out

    def route_selections(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for i in range(self.chip_list.count()):
            item = self.chip_list.item(i)
            code = item.data(Qt.ItemDataRole.UserRole)
            widget = self.chip_list.itemWidget(item)
            combo = widget.findChild(QComboBox) if widget is not None else None
            if code and combo is not None and combo.currentData():
                out[str(code)] = str(combo.currentData())
        return out

    def _queue_order_flush(self, *_) -> None:
        # InternalMove 落子会连发 rowsRemoved+rowsInserted：通过 _flush_pending 真正合并到下一拍只报一次。
        if not self._syncing and not self._flush_pending:
            self._flush_pending = True
            QTimer.singleShot(0, self._flush_order)

    def _flush_order(self) -> None:
        self._flush_pending = False
        if not self._syncing:
            self.order_changed.emit()


class SkillArchiveLevelGrid(QWidget):
    """技能存档等级：每系一个数字框，0=未知。"""

    MAX_LEVEL = 50
    levels_changed = Signal()

    def __init__(self, stems: list[str], labels: dict[str, str], parent=None):
        super().__init__(parent)
        self.boxes: dict[str, QSpinBox] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        grid = QGridLayout()
        grid.setSpacing(8)
        grid.setContentsMargins(0, 0, 0, 0)

        for idx, code in enumerate(stems):
            cn = labels.get(code, code)
            box = QSpinBox()
            box.setRange(0, self.MAX_LEVEL)
            box.setSpecialValueText("未知")
            box.setFixedHeight(32)  # 全局步进器统一 32px
            box.valueChanged.connect(lambda _v: self.levels_changed.emit())
            self.boxes[code] = box

            cell = QHBoxLayout()
            cell.setSpacing(6)
            cell.setContentsMargins(0, 0, 0, 0)
            label = QLabel(cn)
            label.setObjectName("hintLabel")
            cell.addWidget(label)
            cell.addWidget(box)

            holder = QWidget()
            holder.setLayout(cell)
            grid.addWidget(holder, idx // 4, idx % 4)

        lay.addLayout(grid)

    def set_levels(self, levels: dict[str, int]):
        for code, box in self.boxes.items():
            try:
                value = int(levels.get(code, 0) or 0)
            except (TypeError, ValueError):
                value = 0
            box.setValue(max(0, min(self.MAX_LEVEL, value)))

    def get_levels(self) -> dict[str, int]:
        return {code: box.value() for code, box in self.boxes.items() if box.value() > 0}


class NegativeTreasureGroup(QGroupBox):
    """特殊宝物选择区（默认折叠、默认全不勾）。"""

    changed = Signal()

    TIP = {
        "透支力量": "透支型收益",
        "贪婪献祭": "长期期望为负",
        "金转木": "断掉金币来源",
        "杀敌梭哈": "收益中断",
        "伐木契约": "之后不再获得木材",
        "等级优势": "之后不再升级",
    }

    def __init__(self, names: list[str], prefix: str = "", parent=None):
        super().__init__(parent)
        self._prefix = prefix
        self._boxes: dict[str, QCheckBox] = {}
        self.setCheckable(True)
        self.setChecked(False)
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        lay.setContentsMargins(12, 12, 12, 10)

        self.body = QWidget()
        body_lay = QVBoxLayout(self.body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(8)

        if names:
            grid_host = QWidget()
            grid = QGridLayout(grid_host)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setSpacing(8)
            for idx, name in enumerate(names):
                box = QCheckBox(name)
                box.setToolTip(self.TIP.get(name, "特殊宝物"))
                box.toggled.connect(lambda _=False: self.changed.emit())
                self._boxes[name] = box
                grid.addWidget(box, idx // 3, idx % 3)
            body_lay.addWidget(grid_host)
        else:
            empty = QLabel("未配置特殊宝物名单")
            empty.setObjectName("hintLabel")
            body_lay.addWidget(empty)

        lay.addWidget(self.body)
        self.body.setVisible(False)
        self.toggled.connect(self._on_toggled)
        self.changed.connect(self._refresh_title)
        self._refresh_title()

    def _on_toggled(self, expanded: bool):
        self.body.setVisible(expanded)
        self._refresh_title()

    def _refresh_title(self):
        allowed = self.get_allowed()
        if allowed:
            body = f"特殊宝物（已放行 {len(allowed)}：{'、'.join(allowed)}）"
        else:
            body = "特殊宝物（默认全阻断）"
        self.setTitle(f"{self._prefix}{body}")

    def get_allowed(self) -> list[str]:
        return [name for name, box in self._boxes.items() if box.isChecked()]

    def set_allowed(self, names: list[str]):
        wanted = {str(n).strip() for n in (names or [])}
        for name, box in self._boxes.items():
            box.blockSignals(True)
            box.setChecked(name in wanted)
            box.blockSignals(False)
        self._refresh_title()


class MainWindow(QMainWindow):
    def __init__(self, app_data: Path | None = None):
        super().__init__()
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.app_data = Path(app_data).resolve() if app_data is not None else _app_data_dir().resolve()
        self.app_data.mkdir(parents=True, exist_ok=True)
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION_LABEL} · 重生魔兽刷刷刷")
        self._window_role = "chooser"
        self.current_theme = "dark"
        self.setStyleSheet(get_qss(self.current_theme))
        _apply_native_titlebar_theme(self, self.current_theme)
        self._suppress_challenge_rec = True

        self.pet_hud = FloatingPetHud()
        self.pet_hud.hud_restored.connect(self._restore_from_pet_hud)
        self.pet_hud.hide()
        self.settings = Settings()
        self._shell_extras: dict = {
            "chapter": 1,
            "difficulty": 0,
            "hero": 0,
            "attr_route": [],
            "secret_realm": False,
            "early_challenge": False,
            "treasure_allow_negative": [],
            "advanced_packs": [],
            "hitch_stage_prefix": "3",
            "selected_build_id": "",
            "custom_builds": [{"id": "custom:1", "name": "自定义 1", "skills": []}],
            "rep_alloc": {},
        }
        self.runner = RunnerService(self.app_data, ROOT)
        self.worker_thread: MediatorWorker | None = None
        self._terminal_reason = ""
        self._runtime_phase = "IDLE"
        self._ocr_status = "未启动"
        self._last_action = ""
        self.overlay_hud: OverlayHud | None = None
        self._game_count = 0
        self._syncing_bonds = False
        self._build_btn_group = QButtonGroup(self)
        self._build_btn_map: dict[str, QPushButton] = {}
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(800)
        self._save_timer.timeout.connect(self._save_settings_now)
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(200)
        self._status_timer.timeout.connect(self._poll_runtime)

        self._build_ui()
        self.overlay_hud = OverlayHud()
        self.overlay_hud.stop_requested.connect(self._hud_stop)

        for seq in ("F12", "Shift+F12"):
            shortcut = QShortcut(QKeySequence(seq), self)
            shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
            shortcut.activated.connect(self._hud_stop)

        self._setup_tray()
        self.load_local_settings(silent=True)
        self._wire_auto_save()
        self._show_mode_choice()
        self._apply_component_theme()
        self._suppress_challenge_rec = False

    def apply_quick_start_selection(self, payload) -> None:
        sel = selection_from_payload(payload)
        self.settings = apply_quick_start_to_settings(self.settings, sel)
        self.apply_settings_to_ui(self.settings)
        mode_id = str(self.settings.mode_id or "normal_farm")
        self._select_mode(mode_id if mode_id in self._page_index else "normal_farm")
        self._refresh_chrome()

    def _open_quick_wizard(self) -> None:
        wizard = GameStyleWizardDialog(self, settings=self.settings, theme=getattr(self, "current_theme", "dark"))
        wizard.run_requested.connect(self._on_wizard_run)
        wizard.advanced_requested.connect(self._on_wizard_advanced)
        wizard.exec()

    def _on_wizard_run(self, payload) -> None:
        self.apply_quick_start_selection(payload)
        self.showNormal()

    def _on_wizard_advanced(self, payload) -> None:
        self.apply_quick_start_selection(payload)
        self.showNormal()

    def _apply_component_theme(self) -> None:
        theme = getattr(self, "current_theme", "dark")
        apply_app_palette(theme)
        self.setStyleSheet(get_qss(theme))
        _apply_native_titlebar_theme(self, theme)
        if hasattr(self, "skill_grid"):
            self.skill_grid.apply_theme(theme)
        if getattr(self, "pet_hud", None) is not None:
            self.pet_hud.apply_theme(theme)
        if getattr(self, "overlay_hud", None) is not None:
            self.overlay_hud.apply_theme(theme)
        mode_qss = mode_button_qss(theme)
        for button in (getattr(self, "btn_solo_mode", None), getattr(self, "btn_hitch_mode", None)):
            if button is not None:
                button.setStyleSheet(mode_qss)
                button.setFixedSize(220, 128)
        build_qss = official_build_qss(theme)
        for btn in getattr(self, "_build_btn_map", {}).values():
            btn.setStyleSheet(build_qss)

    def toggle_theme(self) -> None:
        self.current_theme = "light" if getattr(self, "current_theme", "dark") == "dark" else "dark"
        self._shell_extras["theme"] = self.current_theme
        self._apply_component_theme()
        if hasattr(self, "btn_theme"):
            self.btn_theme.setText("切换深色" if self.current_theme == "light" else "切换浅色")
        self._schedule_auto_save()

    def _restore_from_pet_hud(self) -> None:
        if getattr(self, "pet_hud", None):
            self.pet_hud.hide()
        self.showNormal()
        self.activateWindow()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # 顶部产品带：品牌行 + 工具行
        header_frame = QFrame()
        header_frame.setObjectName("customTitleBar")
        header = QVBoxLayout(header_frame)
        header.setContentsMargins(16, 14, 16, 10)
        header.setSpacing(8)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)
        logo_path = ROOT / "assets" / "branding" / "app_logo.png"
        if logo_path.exists():
            logo_lbl = QLabel()
            logo_pix = QPixmap(str(logo_path)).scaled(28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            logo_lbl.setPixmap(logo_pix)
            brand_row.addStretch()
            brand_row.addWidget(logo_lbl)
            self.setWindowIcon(QIcon(str(logo_path)))
        else:
            brand_row.addStretch()

        title = QLabel(APP_NAME)
        title.setObjectName("brandTitle")
        title.setAlignment(Qt.AlignCenter)
        brand_row.addWidget(title)

        ver_lbl = QLabel(APP_VERSION_LABEL)
        ver_lbl.setObjectName("versionPill")
        self.lbl_version = ver_lbl
        self.lbl_subtitle = None
        brand_row.addWidget(ver_lbl)
        brand_row.addStretch()
        header.addLayout(brand_row)

        header_separator = QFrame()
        header_separator.setFrameShape(QFrame.HLine)
        header_separator.setObjectName("headerSeparator")
        header.addWidget(header_separator)

        tool_row = QHBoxLayout()
        tool_row.setSpacing(12)
        self._header_tool_row = tool_row

        # 状态胶囊指示器
        self.lbl_run_status = QLabel("待命")
        self.lbl_run_status.setObjectName("statusPill")
        self.lbl_run_status.setAlignment(Qt.AlignCenter)
        tool_row.addWidget(self.lbl_run_status)

        tool_row.addStretch()

        # 今日局数胶囊
        games_box = QHBoxLayout()
        games_box.setSpacing(4)
        self.lbl_games = QLabel("今日局数: 0")
        self.lbl_games.setStyleSheet("font-weight:700;")
        self.lbl_games_cap = QLabel("/ 100")
        self.lbl_games_cap.setObjectName("gamesCap")
        games_box.addWidget(self.lbl_games)
        games_box.addWidget(self.lbl_games_cap)
        tool_row.addLayout(games_box)

        self.btn_theme = QPushButton("切换浅色")
        self.btn_theme.setObjectName("btnTheme")
        self.btn_theme.setCursor(Qt.PointingHandCursor)
        self.btn_theme.setToolTip("在深色与浅色外观间切换")
        self.btn_theme.clicked.connect(self.toggle_theme)
        tool_row.addWidget(self.btn_theme)

        self.btn_wizard = QPushButton("快速开局")
        self.btn_wizard.setCursor(Qt.PointingHandCursor)
        self.btn_wizard.clicked.connect(self._open_quick_wizard)
        tool_row.addWidget(self.btn_wizard)

        self._header_frame = header_frame
        header_frame.installEventFilter(self)
        self.btn_win_min = QPushButton("─")
        self.btn_win_min.setObjectName("btnWinMin")
        self.btn_win_min.setFixedSize(34, 26)
        self.btn_win_min.setToolTip("最小化")
        self.btn_win_min.clicked.connect(self.showMinimized)
        tool_row.addWidget(self.btn_win_min)
        self.btn_win_close = QPushButton("✕")
        self.btn_win_close.setObjectName("btnWinClose")
        self.btn_win_close.setFixedSize(34, 26)
        self.btn_win_close.setToolTip("关闭")
        self.btn_win_close.clicked.connect(self.close)
        tool_row.addWidget(self.btn_win_close)

        self._header_tool_widgets: list[QWidget] = [self.lbl_run_status]
        self._header_tool_widgets.append(self.btn_theme)
        self._header_tool_widgets.append(self.btn_wizard)
        header.addLayout(tool_row)

        outer.addWidget(header_frame)

        # 主内容区域 (严格 16px 边距与 12px 间距)
        body = QVBoxLayout()
        body.setContentsMargins(16, 12, 16, 12)
        body.setSpacing(12)

        mode_box = QWidget()
        mode_box.setObjectName("modeChooser")
        self.mode_box = mode_box
        mode_layout = QVBoxLayout(mode_box)
        mode_layout.setContentsMargins(24, 16, 24, 16)
        mode_layout.setSpacing(12)
        cap = QLabel("运行方式")
        cap.setObjectName("sectionCap")
        cap.setAlignment(Qt.AlignCenter)
        mode_layout.addWidget(cap)

        primary_row = QHBoxLayout()
        primary_row.setSpacing(16)
        self.primary_mode_group = QButtonGroup(self)
        self.btn_solo_mode = QPushButton("自己刷图\n自动建房并作战")
        self.btn_hitch_mode = QPushButton("大厅蹭车\n待验证 · 不可启动")

        for button in (self.btn_solo_mode, self.btn_hitch_mode):
            button.setCheckable(True)
            button.setFixedSize(220, 128)
            button.setCursor(Qt.PointingHandCursor)
            button.setStyleSheet(mode_button_qss("dark"))
            self.primary_mode_group.addButton(button)

        primary_row.addStretch()
        primary_row.addWidget(self.btn_solo_mode)
        primary_row.addWidget(self.btn_hitch_mode)
        primary_row.addStretch()
        mode_layout.addStretch()
        mode_layout.addLayout(primary_row)
        mode_layout.addStretch()
        self.btn_hitch_mode.setToolTip("大厅蹭车尚未验证，可查看说明，不能从看板点火。")
        self.btn_solo_mode.clicked.connect(lambda: self._select_mode("normal_farm"))
        self.btn_hitch_mode.clicked.connect(lambda: self._select_mode("lobby_hitch"))
        body.addWidget(mode_box, 1)

        # 页面堆叠区
        self.right_stack = QStackedWidget()
        self._page_index: dict[str, int] = {}
        for spec in iter_specs():
            page = self._build_mode_page(spec.id)
            self._page_index[spec.id] = self.right_stack.addWidget(page)
        body.addWidget(self.right_stack, 1)

        outer.addLayout(body, 1)

        # 底部操作栏 (固定吸底液态玻璃)
        self.footer = QFrame()
        self.footer.setObjectName("footerBar")
        foot = QHBoxLayout(self.footer)
        foot.setContentsMargins(16, 12, 16, 12)
        foot.setSpacing(14)

        self.btn_choose_mode = QPushButton("切换运行方式")
        self.btn_choose_mode.setCursor(Qt.PointingHandCursor)
        self.btn_choose_mode.clicked.connect(self._show_mode_choice)
        foot.addWidget(self.btn_choose_mode)

        self.lbl_summary = QLabel("就绪")
        self.lbl_summary.setObjectName("statusLine")
        self.lbl_summary.setWordWrap(True)
        foot.addWidget(self.lbl_summary, 1)

        self.lbl_precheck = QLabel("预检 ● 绿")
        self.lbl_precheck.setObjectName("precheckLamp")
        self.lbl_precheck.setStyleSheet(f"color:{tokens('dark')['neon_success']}; font-weight:700;")
        foot.addWidget(self.lbl_precheck)

        self.btn_main = QPushButton("开始运行")
        self.btn_main.setObjectName("btnStart")
        self.btn_main.setMinimumHeight(42)
        self.btn_main.setMinimumWidth(180)
        self.btn_main.setCursor(Qt.PointingHandCursor)
        self.btn_main.clicked.connect(self.toggle_run)
        foot.addWidget(self.btn_main)

        outer.addWidget(self.footer)

        self.lbl_latest = QLabel("就绪 · F12 / Shift+F12 紧急停止")
        self.lbl_latest.setVisible(False)

        self._selected_mode_id = "normal_farm"
        self.btn_solo_mode.setChecked(False)
        self.btn_hitch_mode.setChecked(False)
        self._show_mode_choice()

    def _build_mode_page(self, mode_id: str) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(2, 4, 6, 12)
        lay.setSpacing(16)

        if mode_id == "normal_farm":
            self._build_normal_farm_page(lay)
        elif mode_id == "follow_team":
            self._build_follow_page(lay)
        elif mode_id == "gambling_wood":
            self._build_gamble_page(lay)
        elif mode_id == "raid_wait":
            self._build_raid_page(lay)
        elif mode_id == "lobby_hitch":
            self._build_hitch_page(lay)
        else:
            self._build_lab_page(lay)

        lay.addStretch()
        scroll.setWidget(inner)
        return scroll

    def _section(self, title: str, default_note: str, *, flat: bool = False) -> tuple[QGroupBox, QVBoxLayout]:
        box = QGroupBox(title)
        if flat:
            box.setObjectName("subGroup")
        lay = QVBoxLayout(box)
        if flat:
            lay.setContentsMargins(2, 8, 2, 4)
        else:
            lay.setContentsMargins(10, 10, 10, 8)
        lay.setSpacing(10)
        if default_note:
            cap = QLabel(default_note)
            cap.setObjectName("sectionCap")
            cap.setWordWrap(True)
            lay.addWidget(cap)
        return box, lay

    def _build_normal_farm_page(self, lay: QVBoxLayout) -> None:
        run_box, run_lay = self._section("① 运行目标配置", "")
        stage_row = QHBoxLayout()
        stage_row.setSpacing(10)

        stage_row.addWidget(_align_label("篇章", 60))
        self.cmb_chapter = QComboBox()
        self.cmb_chapter.setFixedHeight(34)
        for chapter, _count, label in MAINLINE_STAGES:
            self.cmb_chapter.addItem(MAINLINE_DISPLAY.get(chapter, label), chapter)

        self.cmb_stage = QComboBox()
        self.cmb_stage.setFixedHeight(34)
        self.txt_stage_target = QLineEdit("1-10")
        self.txt_stage_target.setVisible(False)
        self._filling_stage = False
        self._refill_stage_combo(keep_stage=10)

        self.cmb_chapter.currentIndexChanged.connect(self._on_chapter_changed)
        self.cmb_stage.currentIndexChanged.connect(self._on_stage_combo_changed)
        self.txt_stage_target.textChanged.connect(self._on_stage_target_edited)
        self.cmb_chapter.currentIndexChanged.connect(self._recommend_challenges_for_stage)
        self.cmb_stage.currentIndexChanged.connect(self._recommend_challenges_for_stage)
        self.txt_stage_target.textEdited.connect(self._recommend_challenges_for_stage)

        stage_row.addWidget(self.cmb_chapter, 2)
        stage_row.addWidget(_align_label("关卡", 60))
        stage_row.addWidget(self.cmb_stage, 1)

        stage_row.addWidget(_align_label("关卡难度", 60))
        self.cmb_mode = QComboBox()
        self.cmb_mode.setFixedHeight(34)
        self.cmb_mode.addItem("普通", False)
        self.cmb_mode.addItem("英雄", True)
        stage_row.addWidget(self.cmb_mode, 1)

        stage_row.addWidget(_align_label("局数", 60))
        self.spn_cycle_num = QSpinBox()
        self.spn_cycle_num.setRange(0, 999)
        self.spn_cycle_num.setFixedHeight(32)
        self.spn_cycle_num.setSpecialValueText("手动停")
        stage_row.addWidget(self.spn_cycle_num, 1)

        run_lay.addLayout(stage_row)

        challenge_row = QHBoxLayout()
        challenge_row.setSpacing(10)

        def _fill_challenge_combo(combo: QComboBox, subdir: str) -> None:
            folder = ROOT / "assets" / "Images" / subdir
            stems = sorted(
                f.stem for f in folder.glob("*.png") if f.is_file()
            ) if folder.is_dir() else []
            for stem in stems:
                icon = QIcon(str(folder / f"{stem}.png"))
                combo.addItem(icon, re.sub(r"^\d+", "", stem) or stem, stem)
            if combo.count() > 0:
                combo.setIconSize(QSize(22, 22))
                combo.setCurrentIndex(combo.count() - 1)

        challenge_row.addWidget(_align_label("传家宝挑战", 110))
        self.cmb_cjb_boss = QComboBox()
        self.cmb_cjb_boss.setFixedHeight(34)
        _fill_challenge_combo(self.cmb_cjb_boss, "chuanjiaobao")
        challenge_row.addWidget(self.cmb_cjb_boss)
        challenge_row.addWidget(_align_label("时光之穴 / Boss", 110))
        self.cmb_sgzx_boss = QComboBox()
        self.cmb_sgzx_boss.setFixedHeight(34)
        _fill_challenge_combo(self.cmb_sgzx_boss, "boss")
        challenge_row.addWidget(self.cmb_sgzx_boss)
        challenge_row.addStretch()
        hint = QLabel("默认选中列表最后一项，可点开更换")
        hint.setObjectName("hintLabel")
        challenge_row.addWidget(hint)
        run_lay.addLayout(challenge_row)

        lab_hint = QLabel("测试夹 bat 会读这份保存；改动约 1 秒后自动保存。")
        lab_hint.setObjectName("hintLabel")
        lab_hint.setWordWrap(True)
        run_lay.addWidget(lab_hint)
        save_row = QHBoxLayout()
        save_row.setSpacing(10)
        self.btn_save_settings = QPushButton("保存设置")
        self.btn_save_settings.setObjectName("btnSaveSettings")
        self.btn_save_settings.setCursor(Qt.PointingHandCursor)
        self.btn_save_settings.clicked.connect(self._on_save_settings_clicked)
        save_row.addWidget(self.btn_save_settings)
        save_row.addStretch()
        run_lay.addLayout(save_row)

        core = QWidget()
        core_layout = QVBoxLayout(core)
        core_layout.setContentsMargins(0, 0, 0, 0)
        core_layout.setSpacing(8)

        self.hero_options = QWidget()
        self.hero_options.setVisible(False)
        hero_col = QVBoxLayout(self.hero_options)
        hero_col.setContentsMargins(0, 0, 0, 0)
        hero_col.setSpacing(8)

        alloc_head = QHBoxLayout()
        alloc_head.setSpacing(8)
        alloc_cap = QLabel("声望点数分配（单阵营上限 10）")
        alloc_cap.setObjectName("sectionCap")
        alloc_head.addWidget(alloc_cap)
        alloc_head.addStretch()
        self.lbl_rep_budget = QLabel("可分配共 8 点（已分配 0 点）")
        self.lbl_rep_budget.setObjectName("hintLabel")
        alloc_head.addWidget(self.lbl_rep_budget)
        hero_col.addLayout(alloc_head)

        self.rep_alloc_spins: dict[int, QSpinBox] = {}
        FACTION_SLUGS = {
            1: "heifeng", 2: "yinse", 3: "kenrito",
            4: "tanxian", 5: "yuansu", 6: "shouhu",
        }
        alloc_grid = QGridLayout()
        alloc_grid.setSpacing(8)
        for idx, (name, fid) in enumerate(FACTIONS):
            cell = QWidget()
            cell_lay = QHBoxLayout(cell)
            cell_lay.setContentsMargins(0, 0, 0, 0)
            cell_lay.setSpacing(6)
            rep_logo = ROOT / "assets" / "Images" / "reputation" / f"hero_{FACTION_SLUGS[fid]}.png"
            logo_bright = ROOT / "assets" / "Images" / "lobby" / f"hero_{FACTION_SLUGS[fid]}_bright.png"
            logo_unsel = ROOT / "assets" / "Images" / "lobby" / f"hero_{FACTION_SLUGS[fid]}_unselected.png"
            logo_path = rep_logo if rep_logo.is_file() else (logo_bright if logo_bright.is_file() else logo_unsel)
            if logo_path.is_file():
                logo = QLabel()
                logo.setFixedSize(30, 30)
                logo.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                logo.setPixmap(
                    QPixmap(str(logo_path)).scaled(
                        30, 30, Qt.KeepAspectRatio, Qt.SmoothTransformation
                    )
                )
                logo.setToolTip(FACTION_TIPS.get(fid, name))
                cell_lay.addWidget(logo)
            name_lbl = QLabel(name)
            name_lbl.setFixedWidth(78)
            name_lbl.setToolTip(FACTION_TIPS.get(fid, name))
            cell_lay.addWidget(name_lbl)
            spin = QSpinBox()
            spin.setRange(0, 10)
            spin.setValue(5 if fid == 3 else 0)
            spin.setFixedHeight(32)
            spin.setToolTip(FACTION_TIPS.get(fid, name))
            spin.valueChanged.connect(self._on_rep_alloc_changed)
            self.rep_alloc_spins[fid] = spin
            cell_lay.addWidget(spin)
            cell_lay.addStretch()
            alloc_grid.addWidget(cell, idx // 3, idx % 3)
        for col in range(3):
            alloc_grid.setColumnStretch(col, 1)
        hero_col.addLayout(alloc_grid)

        hero_meta = QHBoxLayout()
        hero_meta.setSpacing(8)
        rep_fallback_pill = QLabel("今日声望耗尽时自动降级常规模式")
        rep_fallback_pill.setObjectName("versionPill")
        hero_meta.addWidget(rep_fallback_pill)
        hero_hint = QLabel("可用点数随关卡进度增长（1-8 关 8 点 · 封顶 23 点）")
        hero_hint.setObjectName("hintLabel")
        hero_meta.addWidget(hero_hint)
        hero_meta.addStretch()
        hero_col.addLayout(hero_meta)

        self.rep_summary_card = QFrame()
        self.rep_summary_card.setObjectName("repSummaryCard")
        rep_sum_lay = QVBoxLayout(self.rep_summary_card)
        rep_sum_lay.setContentsMargins(12, 8, 12, 8)
        rep_sum_lay.setSpacing(2)
        self.lbl_rep_summary_title = QLabel("挑战效果汇总")
        self.lbl_rep_summary_title.setObjectName("hintLabel")
        self.lbl_rep_summary = QLabel("")
        self.lbl_rep_summary.setWordWrap(True)
        self.lbl_rep_summary.setStyleSheet("font-weight:600;")
        rep_sum_lay.addWidget(self.lbl_rep_summary_title)
        rep_sum_lay.addWidget(self.lbl_rep_summary)
        hero_col.addWidget(self.rep_summary_card)
        core_layout.addWidget(self.hero_options)

        check_row = QHBoxLayout()
        check_row.setSpacing(16)
        self.chk_secret_realm = QCheckBox("自动进秘境")
        self.secret_options = QLabel("已启用秘境")
        self.secret_options.setObjectName("hintLabel")
        self.secret_options.setVisible(False)
        self.chk_secret_realm.toggled.connect(self.secret_options.setVisible)

        self.chk_auto_close_main_line = QCheckBox("5-5后取消自动主线挑战")
        self.chk_auto_close_main_line.setToolTip("主线过 5-5 后自动取消自动主线复选框，避免打 5-10 翻车；10分钟直接提前打 Boss")

        check_row.addWidget(self.chk_secret_realm)
        check_row.addWidget(self.secret_options)
        check_row.addWidget(self.chk_auto_close_main_line)
        check_row.addStretch()
        core_layout.addLayout(check_row)

        run_lay.addWidget(core)
        lay.addWidget(run_box)

        build_box = QGroupBox("② 技能搭配")
        self.grp_builds = build_box
        build_layout = QVBoxLayout(build_box)
        build_layout.setContentsMargins(10, 10, 10, 8)
        build_layout.setSpacing(8)
        self._build_list = QWidget()
        self._build_list_lay = QVBoxLayout(self._build_list)
        self._build_list_lay.setContentsMargins(0, 0, 0, 0)
        self._build_list_lay.setSpacing(8)
        build_layout.addWidget(self._build_list)
        self.btn_build_back = QPushButton("选择其他策略")
        self.btn_build_back.setCursor(Qt.PointingHandCursor)
        self.btn_build_back.clicked.connect(self._show_all_builds)
        self.btn_build_back.setVisible(False)
        build_layout.addWidget(self.btn_build_back)
        self.custom_editor = QWidget()
        self.custom_editor.setVisible(False)
        custom_lay = QVBoxLayout(self.custom_editor)
        custom_lay.setContentsMargins(0, 8, 0, 0)
        custom_lay.setSpacing(12)
        build_layout.addWidget(self.custom_editor)
        self._rebuild_build_picker()
        lay.addWidget(build_box)

        # 高级配置（可折叠）
        self.grp_advanced = QGroupBox("③ 高级配置（手动技能 / 存档等级 / 属性线 / 房间）")
        self.grp_advanced.setCheckable(True)
        self.grp_advanced.setChecked(False)
        advanced_layout = QVBoxLayout(self.grp_advanced)
        advanced_layout.setContentsMargins(10, 10, 10, 8)
        advanced_layout.setSpacing(12)

        self.advanced_host = QWidget()
        adv_lay = QVBoxLayout(self.advanced_host)
        adv_lay.setContentsMargins(0, 0, 0, 0)
        adv_lay.setSpacing(12)

        # 房间设置
        room_box = QGroupBox("房间设置")
        room_box.setObjectName("subGroup")
        self.grp_room_settings = room_box
        self.grp_room_settings.setCheckable(True)
        self.grp_room_settings.setChecked(False)
        room_layout = QHBoxLayout(room_box)
        room_layout.setSpacing(10)
        self.chk_auto_create_room = QCheckBox("自动创建房间")
        room_layout.addWidget(self.chk_auto_create_room)
        room_layout.addWidget(_align_label("房名", 44))
        self.txt_room_name = QLineEdit()
        self.txt_room_name.setPlaceholderText("留空使用默认")
        room_layout.addWidget(self.txt_room_name, 1)
        room_layout.addWidget(_align_label("密码", 44))
        self.txt_room_password = QLineEdit()
        self.txt_room_password.setEchoMode(QLineEdit.Password)
        self.txt_room_password.setPlaceholderText("无密码")
        room_layout.addWidget(self.txt_room_password, 1)
        self.cmb_room_reuse = QComboBox()
        self.cmb_room_reuse.addItem("复用原房间", False)
        self.cmb_room_reuse.addItem("每局新建房间", True)
        room_layout.addWidget(self.cmb_room_reuse)
        room_box.toggled.connect(lambda expanded: [child.setVisible(expanded) for child in room_box.findChildren(QWidget) if child is not room_box])
        for child in room_box.findChildren(QWidget):
            child.setVisible(False)
        adv_lay.addWidget(room_box)

        custom_lay = self.custom_editor.layout()
        self.grp_skill = QGroupBox("技能选择")
        self.grp_skill.setObjectName("subGroup")
        self.grp_skill.setCheckable(True)
        self.grp_skill.setChecked(False)
        sl = QVBoxLayout(self.grp_skill)
        sl.setContentsMargins(2, 6, 2, 2)
        self.skill_grid = SkillCardGrid(SKILL_STEMS, SKILL_LABELS)
        sl.addWidget(self.skill_grid)
        self.skill_priority_bar = SkillPriorityBar()
        sl.addWidget(self.skill_priority_bar)
        self.skill_priority_bar.setVisible(False)
        self.skill_priority_bar.order_changed.connect(self._on_priority_order_changed)
        self.skill_priority_bar.route_changed.connect(self._on_priority_route_changed)
        self.grp_skill.toggled.connect(self._set_skill_panel_expanded)
        self.skill_grid.skills_changed.connect(self._on_skills_changed)
        self.skill_grid.setVisible(False)
        custom_lay.addWidget(self.grp_skill)

        self.grp_archive = QGroupBox("技能存档等级")
        self.grp_archive.setObjectName("subGroup")
        self.grp_archive.setCheckable(True)
        self.grp_archive.setChecked(False)
        al = QVBoxLayout(self.grp_archive)
        al.setContentsMargins(10, 10, 10, 10)
        self.archive_grid = SkillArchiveLevelGrid(SKILL_STEMS, SKILL_LABELS)
        al.addWidget(self.archive_grid)
        self.archive_grid.setVisible(False)
        self.grp_archive.toggled.connect(self._set_archive_panel_expanded)
        self.archive_grid.levels_changed.connect(self._on_archive_levels_changed)
        adv_lay.addWidget(self.grp_archive)

        bond_box, bond_lay = self._section("羁绊", "祝福由系统必拿，无需勾选", flat=True)
        route_row = QHBoxLayout()
        route_row.setSpacing(10)
        route_row.addWidget(QLabel("属性线"))
        self.route_buttons: dict[str, QCheckBox] = {}
        for row_opt in ATTR_LINE_OPTIONS:
            rid = str(row_opt.get("id") or "")
            btn = QCheckBox(str(row_opt.get("label") or rid))
            self.route_buttons[rid] = btn
            btn.toggled.connect(self._on_attr_route_clicked)
            route_row.addWidget(btn)
        route_row.addStretch()
        bond_lay.addLayout(route_row)

        self.bond_plan_host = QWidget()
        self.bond_plan_lay = QVBoxLayout(self.bond_plan_host)
        self.bond_plan_lay.setContentsMargins(0, 0, 0, 0)
        self.bond_plan_lay.setSpacing(8)
        self._bond_plan_boxes: dict[str, QCheckBox] = {}
        self._advanced_pack_boxes: dict[str, QCheckBox] = {}
        self._rebuild_bond_plan()

        self.grp_bond_basic = QGroupBox("羁绊与卡组（已开放自定义）")
        self.grp_bond_basic.setObjectName("subGroup")
        self.grp_bond_basic.setCheckable(True)
        self.grp_bond_basic.setChecked(True)
        basic_lay = QVBoxLayout(self.grp_bond_basic)
        basic_lay.addWidget(self.bond_plan_host)
        self.grp_bond_basic.toggled.connect(self.bond_plan_host.setVisible)
        self.bond_plan_host.setVisible(True)
        # 20260822 实机反馈：羁绊自选此前挂在「自定义卡组」编辑器里，选了
        # 推荐方案后整个编辑器隐藏 → 用户看不到也无法改羁绊（经济等基础
        # 系全被刷新掉）。羁绊选择是推荐方案之上的人工裁决层，移到主页面
        # 常显（推荐方案只提供默认勾选，不锁死）。
        lay.addWidget(self.grp_bond_basic)
        # bond_box（属性线等）保留在自定义编辑器内，避免无父引用被 Qt 回收。
        custom_lay.addWidget(bond_box)

        # 宝物
        loot_box, loot_lay = self._section("宝物与资源", "", flat=True)
        self.grp_negative = NegativeTreasureGroup(
            [name for name in NEGATIVE_TREASURES if name not in TREASURE_UI_HIDDEN]
        )
        self.grp_negative.setObjectName("subGroup")
        self.grp_negative.changed.connect(self._on_negative_changed)
        loot_lay.addWidget(self.grp_negative)
        pending = QLabel("赌木 · 木材阈值 · 待接线；龙珠 · 待验证")
        pending.setObjectName("warnHint")
        pending.setWordWrap(True)
        loot_lay.addWidget(pending)
        w_row = QHBoxLayout()
        w_row.setSpacing(10)
        w_row.addWidget(_align_label("不开 F", 48))
        self.spn_wood_open_f = QSpinBox()
        self.spn_wood_open_f.setRange(0, 999)
        self.spn_wood_open_f.setFixedHeight(32)
        self.spn_wood_open_f.setValue(100)
        self.spn_wood_open_f.setEnabled(False)
        w_row.addWidget(self.spn_wood_open_f)
        w_row.addWidget(_align_label("不刷新", 48))
        self.spn_wood_refresh = QSpinBox()
        self.spn_wood_refresh.setRange(0, 999)
        self.spn_wood_refresh.setFixedHeight(32)
        self.spn_wood_refresh.setValue(40)
        self.spn_wood_refresh.setEnabled(False)
        w_row.addWidget(self.spn_wood_refresh)
        w_row.addStretch()
        loot_lay.addLayout(w_row)
        adv_lay.addWidget(loot_box)

        self._build_test_profiles(adv_lay)

        # 运行日志
        self.grp_details = QGroupBox("运行日志")
        self.grp_details.setObjectName("subGroup")
        self.grp_details.setCheckable(True)
        self.grp_details.setChecked(False)
        dl = QVBoxLayout(self.grp_details)
        self.txt_log = QPlainTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumHeight(140)
        self.txt_log.setVisible(False)
        self.txt_log.document().setMaximumBlockCount(1000)
        self.grp_details.toggled.connect(self.txt_log.setVisible)
        dl.addWidget(self.txt_log)
        adv_lay.addWidget(self.grp_details)

        advanced_layout.addWidget(self.advanced_host)
        self.advanced_host.setVisible(False)
        self.grp_advanced.toggled.connect(self._set_advanced_expanded)
        lay.addWidget(self.grp_advanced)

        self.cmb_mode.currentIndexChanged.connect(self._update_hero_visibility)
        self._update_hero_visibility()

    def _build_test_profiles(self, lay: QVBoxLayout) -> None:
        box = QGroupBox("测试方案配置")
        box.setObjectName("subGroup")
        row = QHBoxLayout(box)
        row.setSpacing(10)
        row.addWidget(QLabel("方案"))
        self.cmb_test_profile = QComboBox()
        self.cmb_test_profile.addItem("选择方案", None)
        try:
            self._test_profiles = load_test_profiles(TEST_PROFILES_PATH)
            profiles_available = True
        except (OSError, ValueError, json.JSONDecodeError):
            self._test_profiles = []
            profiles_available = False
            self.cmb_test_profile.addItem("无可用方案", None)
        for profile in self._test_profiles:
            self.cmb_test_profile.addItem(profile["name"], profile)
        row.addWidget(self.cmb_test_profile, 1)

        self.btn_apply_test_profile = QPushButton("应用方案")
        self.btn_apply_test_profile.setCursor(Qt.PointingHandCursor)
        self.btn_apply_test_profile.clicked.connect(self._on_apply_builtin_profile)
        self.btn_apply_test_profile.setEnabled(profiles_available)
        row.addWidget(self.btn_apply_test_profile)

        self.btn_import_test_profile = QPushButton("导入")
        self.btn_import_test_profile.setCursor(Qt.PointingHandCursor)
        self.btn_import_test_profile.clicked.connect(self._on_import_test_profile)
        row.addWidget(self.btn_import_test_profile)

        self.btn_export_test_profile = QPushButton("导出")
        self.btn_export_test_profile.setCursor(Qt.PointingHandCursor)
        self.btn_export_test_profile.clicked.connect(self._on_export_test_profile)
        row.addWidget(self.btn_export_test_profile)
        lay.addWidget(box)

    @staticmethod
    def _profile_diff_text(diff: dict) -> str:
        if not diff:
            return "没有可应用的差异。"
        return "\n".join(f"{key}: {old!r} → {new!r}" for key, (old, new) in diff.items())

    def _apply_test_profile_document(self, document: dict, *, confirm: bool = True) -> bool:
        try:
            current = self.collect_settings_from_ui()
            updated = apply_profile(current, document)
        except (TestProfileError, ValueError) as exc:
            QMessageBox.warning(self, "测试配置已拒绝", str(exc))
            return False
        diff_text = self._profile_diff_text(profile_diff(current, updated))
        if confirm:
            answer = QMessageBox.question(
                self,
                "应用测试配置",
                f"将应用以下差异：\n\n{diff_text}",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return False
        self.apply_settings_to_ui(updated)
        self._schedule_auto_save()
        self.log(f"[测试配置] 已应用 {document['name']}", "info")
        return True

    def _on_apply_builtin_profile(self) -> None:
        profile = self.cmb_test_profile.currentData()
        if not isinstance(profile, dict):
            QMessageBox.information(self, "测试配置", "请先选择一个方案。")
            return
        self._apply_test_profile_document(profile)

    def _on_import_test_profile(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "导入测试配置", str(self.app_data), "JSON 文件 (*.json)")
        if not filename:
            return
        try:
            document = validate_profile_document(json.loads(Path(filename).read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, TestProfileError) as exc:
            QMessageBox.warning(self, "测试配置已拒绝", str(exc))
            return
        self._apply_test_profile_document(document)

    def _on_export_test_profile(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self, "导出当前测试配置", str(self.app_data / "dashboard_test_profile.json"), "JSON 文件 (*.json)"
        )
        if not filename:
            return
        try:
            document = export_profile(self.collect_settings_from_ui())
            path = Path(filename)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "导出测试配置失败", str(exc))
            return
        self.log(f"[测试配置] 已导出到 {filename}", "info")

    def _build_must_take_row(self) -> QWidget:
        host = QWidget()
        grid = QGridLayout(host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)
        for idx, name in enumerate(MUST_TAKE_TREASURES):
            cell = QVBoxLayout()
            cell.setSpacing(4)
            cap = QLabel(f"{name}\n策略必拿")
            cap.setObjectName("hintLabel")
            cap.setAlignment(Qt.AlignCenter)
            cell.addWidget(cap)
            wrap = QWidget()
            wrap.setLayout(cell)
            grid.addWidget(wrap, 0, idx)
        if not MUST_TAKE_TREASURES:
            grid.addWidget(QLabel("未配置 must_take_names"))
        return host

    def _custom_builds(self) -> list[dict]:
        raw = self._shell_extras.get("custom_builds")
        if not isinstance(raw, list) or not raw:
            raw = [{"id": "custom:1", "name": "自定义 1", "skills": []}]
            self._shell_extras["custom_builds"] = raw
        return raw

    def _rebuild_build_picker(self) -> None:
        lay = self._build_list_lay
        while lay.count():
            item = lay.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._build_btn_map = {}
        selected = str(self._shell_extras.get("selected_build_id") or "")
        collapsed = bool(selected)
        self.btn_build_back.setVisible(collapsed)
        self.custom_editor.setVisible(selected.startswith("custom:"))

        def add_row(build_id: str, title: str, skills: list[str]) -> None:
            if collapsed and build_id != selected:
                return
            row = self._make_build_row(
                build_id, title, skills, deletable=build_id.startswith("custom:")
            )
            self._build_btn_map[build_id] = row
            lay.addWidget(row)

        for build in OFFICIAL_BUILDS:
            bid = str(build.get("id") or "")
            name = str(build.get("name") or bid).split("（", 1)[0].strip()
            skills = [str(c) for c in (build.get("skills") or [])[:4]]
            add_row(bid, name, skills)
        for item in self._custom_builds():
            add_row(str(item.get("id") or ""), str(item.get("name") or "自定义"), list(item.get("skills") or []))
        if not collapsed:
            add_btn = QPushButton("添加自定义")
            add_btn.setCursor(Qt.PointingHandCursor)
            add_btn.clicked.connect(self._add_custom_build)
            lay.addWidget(add_btn)

    def _make_build_row(
        self, build_id: str, title: str, skills: list[str], *, deletable: bool = False
    ) -> QPushButton:
        btn = QPushButton()
        btn.setCheckable(True)
        btn.setChecked(build_id == str(self._shell_extras.get("selected_build_id") or ""))
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(official_build_qss("dark"))
        col = QVBoxLayout(btn)
        col.setContentsMargins(14, 9, 14, 9)
        col.setSpacing(5)

        name_row = QHBoxLayout()
        name_row.setSpacing(6)
        name = QLabel(title)
        name.setObjectName("buildTitle")
        name.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        name_row.addWidget(name)
        if deletable:
            del_btn = QPushButton("删除")
            del_btn.setObjectName("buildDelete")
            del_btn.setCursor(Qt.PointingHandCursor)
            del_btn.setFixedHeight(24)
            del_btn.setToolTip("删除该自定义流派")
            del_btn.clicked.connect(lambda _=False, bid=build_id: self._delete_custom_build(bid))
            name_row.addStretch()
            name_row.addWidget(del_btn)
        else:
            name_row.addStretch()
        col.addLayout(name_row)

        skills_row = QHBoxLayout()
        skills_row.setSpacing(14)
        codes = list(skills[:4])
        while len(codes) < 4:
            codes.append("")
        for code in codes:
            cell = QHBoxLayout()
            cell.setSpacing(7)
            cell.setContentsMargins(0, 0, 0, 0)
            if code:
                path = SKILL_ICON_DIR / f"{code}.png"
                if path.is_file():
                    icon = QLabel()
                    icon.setFixedSize(26, 26)
                    icon.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                    icon.setPixmap(
                        QPixmap(str(path)).scaled(26, 26, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    )
                    cell.addWidget(icon)
                label = QLabel(skill_display_name(code))
                label.setObjectName("buildSkillName")
                label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                cell.addWidget(label)
                route = SKILL_ROUTES.get(code)
                if route:
                    route_lbl = QLabel(route)
                    route_lbl.setObjectName("buildRoute")
                    route_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                    cell.addWidget(route_lbl)
            else:
                slot = QLabel()
                slot.setObjectName("buildSlot")
                slot.setFixedSize(22, 22)
                slot.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                cell.addWidget(slot)
            cell.addStretch()
            holder = QWidget()
            holder.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            holder.setLayout(cell)
            skills_row.addWidget(holder, 1)
        col.addLayout(skills_row)
        btn.clicked.connect(lambda _=False, bid=build_id: self._select_build(bid))
        return btn

    def _select_build(self, build_id: str) -> None:
        self._shell_extras["selected_build_id"] = build_id
        if build_id.startswith("custom:"):
            skills = []
            for item in self._custom_builds():
                if item.get("id") == build_id:
                    skills = list(item.get("skills") or [])
                    break
            self.skill_grid.set_skills(skills)
        else:
            self.apply_official_build(build_id, confirm=False)
        QTimer.singleShot(0, self._rebuild_build_picker)
        self._schedule_auto_save()

    def _show_all_builds(self) -> None:
        self._shell_extras["selected_build_id"] = ""
        self._rebuild_build_picker()

    def _add_custom_build(self) -> None:
        items = self._custom_builds()
        nxt = len(items) + 1
        items.append({"id": f"custom:{nxt}", "name": f"自定义 {nxt}", "skills": []})
        self._shell_extras["custom_builds"] = items
        self._rebuild_build_picker()

    def _delete_custom_build(self, build_id: str) -> None:
        items = self._custom_builds()
        target = next((it for it in items if it.get("id") == build_id), None)
        if target is None:
            return
        name = str(target.get("name") or build_id)
        answer = QMessageBox.question(
            self,
            "删除自定义流派",
            f"确定删除「{name}」？该操作不可撤销。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self._shell_extras["custom_builds"] = [it for it in items if it.get("id") != build_id]
        if str(self._shell_extras.get("selected_build_id") or "") == build_id:
            self._shell_extras["selected_build_id"] = ""
            self.skill_grid.set_skills([])
        self._schedule_auto_save()
        self._rebuild_build_picker()

    def _build_follow_page(self, lay: QVBoxLayout) -> None:
        box = QGroupBox("跟车模式（自动准备）")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(14, 14, 14, 14)
        bl.setSpacing(10)
        switch = QPushButton("改为大厅找房蹭车")
        switch.setCursor(Qt.PointingHandCursor)
        switch.clicked.connect(lambda: self._select_mode("lobby_hitch"))
        bl.addWidget(switch)
        for text in (
            "• 跟车不建房、不点开始游戏，在房间等待队长开局。",
            "• F1 = 操作切回自身英雄，F2 = 回基地。",
            "• 只认 准备 / 已准备 / 取消准备；特殊房无「锁定」按钮。",
        ):
            lbl = QLabel(text)
            lbl.setObjectName("hintLabel")
            bl.addWidget(lbl)
        lay.addWidget(box)

    def _build_gamble_page(self, lay: QVBoxLayout) -> None:
        box = QGroupBox("赌木模式（实验性）")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(14, 14, 14, 14)
        bl.setSpacing(10)
        note = QLabel("首个宝物判定后自动重开。")
        note.setObjectName("warnHint")
        bl.addWidget(note)
        lay.addWidget(box)

    def _build_raid_page(self, lay: QVBoxLayout) -> None:
        box = QGroupBox("站团本模式（实验性）")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(14, 14, 14, 14)
        bl.setSpacing(10)
        note = QLabel("挂机等待团本。")
        note.setObjectName("hintLabel")
        bl.addWidget(note)
        lay.addWidget(box)

    def _build_hitch_page(self, lay: QVBoxLayout) -> None:
        box = QGroupBox("大厅找房蹭车（待验证 · 不可启动）")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(14, 14, 14, 14)
        bl.setSpacing(10)

        switch = QPushButton("已在房间内，改为跟车模式")
        switch.setCursor(Qt.PointingHandCursor)
        switch.clicked.connect(lambda: self._select_mode("follow_team"))
        bl.addWidget(switch)

        for text in (
            "• 只认 准备 / 已准备 / 取消准备。特殊房无「锁定」按钮。",
            "• F1 = 操作切回自身英雄。F2 = 回基地。",
            "• 自动在游戏大厅搜索房间并过滤密码房/满员房。",
        ):
            lbl = QLabel(text)
            lbl.setObjectName("hintLabel")
            bl.addWidget(lbl)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(QLabel("房间名前缀搜索"))
        self.cmb_hitch_prefix = QComboBox()
        self.cmb_hitch_prefix.setFixedHeight(34)
        self.cmb_hitch_prefix.addItem("搜索 3", "3")
        self.cmb_hitch_prefix.addItem("搜索 4", "4")
        row.addWidget(self.cmb_hitch_prefix)
        row.addStretch()
        bl.addLayout(row)
        exact_row = QHBoxLayout()
        exact_row.setSpacing(10)
        exact_row.addWidget(QLabel("精确关卡过滤"))
        self.txt_hitch_exact = QLineEdit()
        self.txt_hitch_exact.setPlaceholderText("后续拓展")
        self.txt_hitch_exact.setEnabled(False)
        exact_row.addWidget(self.txt_hitch_exact)
        bl.addLayout(exact_row)
        lay.addWidget(box)

    def _build_lab_page(self, lay: QVBoxLayout) -> None:
        box = QGroupBox("实验室（CLI 模式）")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(14, 14, 14, 14)
        bl.setSpacing(10)
        note = QLabel("实验室模式请通过 tools/lab_run.py 执行。")
        note.setObjectName("hintLabel")
        bl.addWidget(note)
        lay.addWidget(box)

    def _rebuild_bond_plan(self) -> None:
        while self.bond_plan_lay.count():
            item = self.bond_plan_lay.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._bond_plan_boxes = {}
        self._advanced_pack_boxes = {}
        has_scheme = "bond_scheme" in self._shell_extras
        inverted = set(self._shell_extras.get("bond_inverted") or [])
        scheme = set(self._effective_scheme_codes())

        tools = QHBoxLayout()
        tools.setSpacing(10)
        btn_all = QPushButton("全选")
        btn_all.setCursor(Qt.PointingHandCursor)
        btn_inv = QPushButton("反选")
        btn_inv.setCursor(Qt.PointingHandCursor)
        btn_all.clicked.connect(self._select_all_basic_pack)
        btn_inv.clicked.connect(self._invert_basic_pack)
        tools.addWidget(btn_all)
        tools.addWidget(btn_inv)
        self.txt_custom_bond = QLineEdit()
        self.txt_custom_bond.setPlaceholderText("自定义羁绊")
        self.txt_custom_bond.setFixedWidth(120)
        btn_add_bond = QPushButton("添加")
        btn_add_bond.setCursor(Qt.PointingHandCursor)
        btn_add_bond.clicked.connect(self._add_custom_bond)
        tools.addWidget(self.txt_custom_bond)
        tools.addWidget(btn_add_bond)
        tools.addStretch()

        tools_host = QWidget()
        tools_host.setLayout(tools)
        self.bond_plan_lay.addWidget(tools_host)

        row = QWidget()
        grid = QGridLayout(row)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)

        custom_bonds = [str(x) for x in (self._shell_extras.get("custom_bonds") or []) if str(x).strip()]
        for col, name in enumerate([*BASIC_PACK_UI_NAMES, *custom_bonds]):
            code = code_for_bond_name(str(name)) or str(name)
            box = QCheckBox(str(name))
            if has_scheme:
                box.setChecked(code in scheme and code not in inverted)
            else:
                box.setChecked(code in DEFAULT_BOND_CODES and code not in inverted)
            box.toggled.connect(lambda checked, c=code: self._on_plan_toggled(c, checked))
            self._bond_plan_boxes[code] = box
            grid.addWidget(box, col // 5, col % 5)
        self.bond_plan_lay.addWidget(row)

        adv_cap = QLabel("高级卡组")
        adv_cap.setObjectName("sectionCap")
        self.bond_plan_lay.addWidget(adv_cap)
        adv_row = QHBoxLayout()
        adv_row.setSpacing(10)
        enabled = set(self._shell_extras.get("advanced_packs") or [])
        for pack_id, spec in ADVANCED_PACKS.items():
            box = QCheckBox(str(spec.get("label") or pack_id))
            box.setChecked(pack_id in enabled)
            box.setToolTip("、".join(str(n) for n in (spec.get("cards") or [])))
            box.toggled.connect(lambda checked, pid=pack_id: self._on_advanced_pack_toggled(pid, checked))
            self._advanced_pack_boxes[pack_id] = box
            adv_row.addWidget(box)
        adv_row.addStretch()
        adv_host = QWidget()
        adv_host.setLayout(adv_row)
        self.bond_plan_lay.addWidget(adv_host)

    def _valid_scheme_code(self, code: str) -> bool:
        return (
            code in FETTER_LABELS
            or code in getattr(self, "_bond_plan_boxes", {})
            or code_for_bond_name(code) is not None
            or str(code) in {str(x) for x in (self._shell_extras.get("custom_bonds") or [])}
        )

    def _effective_scheme_codes(self) -> list[str]:
        if "bond_scheme" in self._shell_extras:
            return [c for c in (self._shell_extras.get("bond_scheme") or []) if self._valid_scheme_code(c)]
        return [c for c in (self.settings.cards or []) if self._valid_scheme_code(c)]

    def _sync_bonds_from_scheme(self) -> None:
        has_scheme = "bond_scheme" in self._shell_extras
        inverted = set(self._shell_extras.get("bond_inverted") or [])
        scheme = self._effective_scheme_codes()
        self._syncing_bonds = True
        try:
            for code, box in self._bond_plan_boxes.items():
                box.blockSignals(True)
                if has_scheme:
                    box.setChecked(code in scheme and code not in inverted)
                else:
                    box.setChecked(code in DEFAULT_BOND_CODES and code not in inverted)
                box.blockSignals(False)
        finally:
            self._syncing_bonds = False

    def _on_plan_toggled(self, code: str, checked: bool) -> None:
        if self._syncing_bonds:
            return
        inverted = [c for c in (self._shell_extras.get("bond_inverted") or []) if self._valid_scheme_code(c)]
        scheme = self._effective_scheme_codes()
        if "bond_scheme" not in self._shell_extras:
            scheme = [c for c, box in self._bond_plan_boxes.items() if box.isChecked()]
            self._shell_extras["bond_scheme"] = scheme
        if code not in scheme:
            scheme.append(code)
            self._shell_extras["bond_scheme"] = scheme
        if checked:
            inverted = [c for c in inverted if c != code]
        elif code not in inverted:
            inverted.append(code)
        self._shell_extras["bond_inverted"] = inverted
        self._sync_bonds_from_scheme()
        self._schedule_auto_save()

    def _on_attr_route_clicked(self) -> None:
        self._shell_extras["attr_route"] = [rid for rid, btn in self.route_buttons.items() if btn.isChecked()]
        self._schedule_auto_save()

    def _select_all_basic_pack(self) -> None:
        self._syncing_bonds = True
        try:
            for box in self._bond_plan_boxes.values():
                box.setChecked(True)
        finally:
            self._syncing_bonds = False
        self._shell_extras["bond_scheme"] = list(self._bond_plan_boxes.keys())
        self._shell_extras["bond_inverted"] = []
        self._sync_bonds_from_scheme()
        self._schedule_auto_save()

    def _invert_basic_pack(self) -> None:
        self._syncing_bonds = True
        try:
            for box in self._bond_plan_boxes.values():
                box.setChecked(not box.isChecked())
        finally:
            self._syncing_bonds = False
        self._shell_extras["bond_scheme"] = [
            code for code, box in self._bond_plan_boxes.items() if box.isChecked()
        ]
        inverted = [code for code, box in self._bond_plan_boxes.items() if not box.isChecked()]
        self._shell_extras["bond_inverted"] = inverted
        self._sync_bonds_from_scheme()
        self._schedule_auto_save()

    def _add_custom_bond(self) -> None:
        """非空去重追加自定义羁绊：写入 settings.cards 并勾选显示，可自由增删。"""
        name = self.txt_custom_bond.text().strip()
        if not name:
            return
        code = code_for_bond_name(name) or name
        customs = [str(x) for x in (self._shell_extras.get("custom_bonds") or [])]
        scheme = self._effective_scheme_codes()
        if name in customs or code in scheme:
            self.txt_custom_bond.clear()
            return
        customs.append(name)
        self._shell_extras["custom_bonds"] = customs
        if "bond_scheme" not in self._shell_extras:
            self._shell_extras["bond_scheme"] = list(scheme)
        if code not in self._shell_extras["bond_scheme"]:
            self._shell_extras["bond_scheme"].append(code)
        self._shell_extras["bond_inverted"] = [
            c for c in (self._shell_extras.get("bond_inverted") or []) if c != code
        ]
        cards = list(getattr(self.settings, "cards", None) or [])
        if code not in cards:
            cards.append(code)
        self.settings.cards = cards
        self.txt_custom_bond.clear()
        self._rebuild_bond_plan()
        self._schedule_auto_save()

    def set_bond_scheme(self, codes: list[str], inverted: list[str] | None = None) -> None:
        self._shell_extras["bond_scheme"] = [c for c in codes if self._valid_scheme_code(c)]
        if inverted is not None:
            self._shell_extras["bond_inverted"] = [c for c in inverted if self._valid_scheme_code(c)]
        self._sync_bonds_from_scheme()

    def effective_bond_codes(self) -> list[str]:
        inverted = set(self._shell_extras.get("bond_inverted") or [])
        return [c for c in self._effective_scheme_codes() if c not in inverted]

    def _on_advanced_pack_toggled(self, pack_id: str, checked: bool) -> None:
        enabled = [str(x) for x in (self._shell_extras.get("advanced_packs") or []) if str(x)]
        if checked and pack_id not in enabled:
            enabled.append(pack_id)
        if not checked:
            enabled = [x for x in enabled if x != pack_id]
        self._shell_extras["advanced_packs"] = enabled
        self._schedule_auto_save()

    def _attr_line_tokens(self) -> list[str]:
        tokens_list: list[str] = []
        selected = self._shell_extras.get("attr_route") or []
        if isinstance(selected, str):
            selected = [selected]
        for rid in selected:
            route = ATTR_ROUTES.get(rid) or {}
            names = (route.get("chain") or []) + (route.get("support") or [])
            for name in names:
                text = str(name or "").strip()
                if not text:
                    continue
                token = code_for_bond_name(text) or text
                if token not in tokens_list:
                    tokens_list.append(token)
        return tokens_list

    def _advanced_pack_tokens(self) -> list[str]:
        enabled = set(self._shell_extras.get("advanced_packs") or [])
        banned = {"解放的圣剑", "帝炎", "法天象地"}
        tokens_list: list[str] = []
        for pack_id, spec in ADVANCED_PACKS.items():
            if pack_id not in enabled:
                continue
            banned.update(str(n) for n in (spec.get("exclude_ex") or []))
            for name in spec.get("cards") or []:
                text = str(name).strip()
                if not text or text in banned:
                    continue
                token = code_for_bond_name(text) or text
                if token not in tokens_list:
                    tokens_list.append(token)
        return tokens_list

    def assemble_whitelist_cards(self) -> list[str]:
        inverted = set(self._shell_extras.get("bond_inverted") or [])
        out: list[str] = []
        for code in BOND_ALWAYS_CODES:
            if code not in out:
                out.append(code)
        for code, box in self._bond_plan_boxes.items():
            if box.isChecked() and code not in inverted and code not in out:
                out.append(code)
        for token in self._attr_line_tokens():
            if token not in out:
                out.append(token)
        for token in self._advanced_pack_tokens():
            if token not in out:
                out.append(token)
        for code in self._effective_scheme_codes():
            if code not in inverted and code not in out:
                out.append(code)
        return out

    def _refill_stage_combo(self, keep_stage: int | None = None) -> None:
        chapter = int(self.cmb_chapter.currentData() or 1)
        maximum = STAGE_MAX.get(chapter, 1)
        current = keep_stage
        if current is None:
            current = int(self.cmb_stage.currentData() or 1)
        self._filling_stage = True
        try:
            self.cmb_stage.clear()
            for index in range(1, maximum + 1):
                self.cmb_stage.addItem(str(index), index)
            self.cmb_stage.setCurrentIndex(max(0, min(maximum, current) - 1))
        finally:
            self._filling_stage = False

    def _write_stage_target_from_combos(self) -> None:
        chapter = int(self.cmb_chapter.currentData() or 1)
        stage = int(self.cmb_stage.currentData() or 1)
        text = f"{chapter}-{stage}"
        if self.txt_stage_target.text() == text:
            return
        self._filling_stage = True
        try:
            self.txt_stage_target.setText(text)
        finally:
            self._filling_stage = False

    def _recommend_challenges_for_stage(self) -> None:
        """按当前所选关卡，自动推荐截至该关最新解锁的传家宝 / 时光之穴 Boss。"""
        if getattr(self, "_suppress_challenge_rec", False):
            return
        stage_key = self.txt_stage_target.text().strip()
        entry = STAGE_UNLOCKS.get(stage_key)
        if not entry:
            return
        for combo, name_key in (
            (self.cmb_cjb_boss, "heirloom"),
            (self.cmb_sgzx_boss, "boss"),
        ):
            want = str(entry.get(name_key) or "")
            if not want:
                continue
            idx = combo.findText(want)
            if idx < 0:
                for i in range(combo.count()):
                    if str(combo.itemData(i) or "").endswith(want):
                        idx = i
                        break
            if idx >= 0:
                combo.setCurrentIndex(idx)

    def _on_chapter_changed(self) -> None:
        if self._filling_stage:
            return
        self._refill_stage_combo()
        self._write_stage_target_from_combos()
        self._schedule_auto_save()
        self._refresh_summary()

    def _on_stage_combo_changed(self) -> None:
        if self._filling_stage:
            return
        self._write_stage_target_from_combos()
        self._schedule_auto_save()
        self._refresh_summary()

    def _on_stage_target_edited(self, text: str) -> None:
        if self._filling_stage:
            return
        match = re.fullmatch(r"([1-9]\d*)-([1-9]\d*)", text.strip())
        if match is None:
            return
        chapter, stage = (int(value) for value in match.groups())
        if chapter not in STAGE_MAX or stage > STAGE_MAX[chapter]:
            return
        self._filling_stage = True
        try:
            idx = self.cmb_chapter.findData(chapter)
            if idx >= 0:
                self.cmb_chapter.setCurrentIndex(idx)
            self._refill_stage_combo(keep_stage=stage)
        finally:
            self._filling_stage = False

    def _apply_stage_target(self, text: str) -> None:
        self.txt_stage_target.setText(text)
        self._on_stage_target_edited(text)

    def _setup_tray(self) -> None:
        self.tray_menu = QMenu(self)
        act_show = QAction("打开控制中心", self)
        act_show.triggered.connect(self.showNormal)
        act_stop = QAction("停止运行", self)
        act_stop.triggered.connect(self._tray_stop)
        act_quit = QAction("退出", self)
        act_quit.triggered.connect(self.close)
        self.tray_menu.addAction(act_show)
        self.tray_menu.addAction(act_stop)
        self.tray_menu.addSeparator()
        self.tray_menu.addAction(act_quit)
        self.tray = QSystemTrayIcon(self)
        self.tray.setContextMenu(self.tray_menu)
        self.tray.setToolTip(APP_NAME)
        icon = self.windowIcon()
        if icon is None or icon.isNull():
            logo_ico = ROOT / "assets" / "branding" / "app_logo.ico"
            logo_png = ROOT / "assets" / "branding" / "app_logo.png"
            if logo_ico.exists():
                icon = QIcon(str(logo_ico))
            elif logo_png.exists():
                icon = QIcon(str(logo_png))
        if icon is not None and not icon.isNull():
            self.tray.setIcon(icon)
        if QSystemTrayIcon.isSystemTrayAvailable() and not self.tray.icon().isNull():
            self.tray.show()

    def _tray_stop(self) -> None:
        if self._is_running():
            self.runner.stop()

    def _hud_stop(self) -> None:
        if self._is_running():
            self.log("[操作] 停止任务（HUD / F12）", "warn")
            self.runner.stop()

    def selected_mode_id(self) -> str:
        return getattr(self, "_selected_mode_id", "normal_farm")

    def _select_mode(self, mode_id: str) -> None:
        if mode_id not in self._page_index:
            return
        self._selected_mode_id = mode_id
        self._shell_extras["selected_mode_id"] = mode_id
        idx = self._page_index.get(mode_id, 0)
        self.right_stack.setCurrentIndex(idx)
        for control in (self.btn_solo_mode, self.btn_hitch_mode):
            control.blockSignals(True)
        try:
            self.btn_solo_mode.setChecked(mode_id == "normal_farm")
            self.btn_hitch_mode.setChecked(mode_id in {"lobby_hitch", "follow_team"})
        finally:
            for control in (self.btn_solo_mode, self.btn_hitch_mode):
                control.blockSignals(False)
        self.mode_box.setVisible(False)
        self.right_stack.setVisible(True)
        self.footer.setVisible(True)
        self._apply_window_role("dashboard")
        self._refresh_chrome()

    def _show_mode_choice(self) -> None:
        self.mode_box.setVisible(True)
        self.right_stack.setVisible(False)
        self.footer.setVisible(False)
        self.btn_solo_mode.setEnabled(True)
        self.btn_hitch_mode.setEnabled(True)
        self._selected_mode_id = "normal_farm"
        self._apply_window_role("chooser")
        self._refresh_chrome()

    def eventFilter(self, obj, event):
        """无边框窗口：按住头部空白区拖动（走系统移动，保留贴边分屏）。"""
        if obj is getattr(self, "_header_frame", None):
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                handle = self.windowHandle()
                if handle is not None and handle.startSystemMove():
                    return True
        return super().eventFilter(obj, event)

    def _apply_window_role(self, role: str) -> None:
        self._window_role = role
        compact = role == "chooser"
        for widget in (
            getattr(self, "lbl_run_status", None),
            getattr(self, "lbl_games", None),
            getattr(self, "lbl_games_cap", None),
            getattr(self, "lbl_version", None),
            getattr(self, "btn_theme", None),
        ):
            if widget is not None:
                widget.setVisible(not compact)
        if compact:
            self.setFixedSize(520, 360)
        else:
            self.setFixedSize(1000, 780)

    def _is_running(self) -> bool:
        return bool(self.worker_thread and self.worker_thread.isRunning())

    def _refresh_chrome(self) -> None:
        if not hasattr(self, "btn_main"):
            return
        spec = get_spec(self.selected_mode_id())
        running = self._is_running()
        for control in (self.btn_solo_mode, self.btn_hitch_mode):
            control.setEnabled(not running)
        self.btn_main.setText(start_button_text(spec, running=running))
        can = desktop_may_start(spec.id) or running
        self.btn_main.setEnabled(can)
        self.btn_main.setObjectName("btnStop" if running else "btnStart")
        self.btn_main.setStyle(self.btn_main.style())
        self._refresh_summary()
        self._refresh_precheck()
        self._refresh_progress()

    def _refresh_summary(self) -> None:
        spec = get_spec(self.selected_mode_id())
        stage = self.txt_stage_target.text().strip() or "-"
        diff = "英雄" if self.cmb_mode.currentData() else "普通"
        names = self.skill_grid.selected_names()
        skill = "/".join(names) if names else "未选技能"
        self.lbl_summary.setText(f"{spec.label} · {stage} · {diff} · 技能：{skill}")

    def _refresh_precheck(self) -> None:
        t = tokens("dark")
        mode_id = self.selected_mode_id()
        if not desktop_may_start(mode_id):
            self.lbl_precheck.setText("预检 ● 红")
            self.lbl_precheck.setToolTip("运行方式未验证")
            self.lbl_precheck.setStyleSheet(f"color:{t['neon_danger']}; font-weight:700;")
            return
        if live_lock_busy(self.app_data) and not self._is_running():
            self.lbl_precheck.setText("预检 ● 红")
            self.lbl_precheck.setToolTip("live.lock 被占用")
            self.lbl_precheck.setStyleSheet(f"color:{t['neon_danger']}; font-weight:700;")
            return
        if not _is_admin():
            self.lbl_precheck.setText("预检 ● 黄")
            self.lbl_precheck.setToolTip("真机运行需要管理员权限")
            self.lbl_precheck.setStyleSheet(f"color:{t['neon_warning']}; font-weight:700;")
            return
        self.lbl_precheck.setText("预检 ● 绿")
        self.lbl_precheck.setToolTip("可启动")
        self.lbl_precheck.setStyleSheet(f"color:{t['neon_success']}; font-weight:700;")

    def _refresh_progress(self) -> None:
        cycle = int(self.spn_cycle_num.value()) if hasattr(self, "spn_cycle_num") else 0
        prog = progress_from_counts(self._game_count, cycle, running=self._is_running())
        self.lbl_games.setText(f"今日局数: {prog.game_count}" if prog.cycle_num <= 0 else f"今日局数: {prog.game_count}/{prog.cycle_num}")
        self.lbl_games_cap.setText(prog.label)

    def _poll_runtime(self) -> None:
        worker = self.worker_thread
        if worker is None or worker.mediator is None:
            return
        mediator = worker.mediator
        self._game_count = int(getattr(mediator, "game_count", 0) or 0)
        phase_value = getattr(mediator, "phase", "IDLE")
        phase = str(getattr(phase_value, "name", phase_value or "IDLE"))
        health = getattr(mediator, "_ocr_bootstrap_health", None) or {}
        ocr_status = "就绪" if health.get("healthy", True) else "不可用"
        actions = getattr(mediator, "_trace_actions", None) or ()
        last_action = ""
        if actions and isinstance(actions[-1], dict):
            last_action = str(actions[-1].get("reason") or actions[-1].get("action") or "")
        self._runtime_phase = phase
        self._ocr_status = ocr_status
        self._last_action = last_action or self._last_action
        if self.overlay_hud is not None:
            cycle = int(self.spn_cycle_num.value()) if hasattr(self, "spn_cycle_num") else 0
            self.overlay_hud.anchor_to_target(getattr(mediator, "_last_frame", None))
            self.overlay_hud.update_status(
                True, phase, ocr_status, self._game_count, cycle,
                self._terminal_reason, self._last_action,
            )
        self._refresh_progress()

    def _rep_available_points(self) -> int:
        """可用声望点数 = 严格绑定顶部目标关卡：1-8→8点，1-14→14点，2-1→24点……"""
        match = re.fullmatch(r"([1-9]\d*)-([1-9]\d*)", getattr(self, "txt_stage_target", None) and self.txt_stage_target.text().strip() or "1-8")
        chapter = int(match.group(1)) if match else 1
        stage = int(match.group(2)) if match else 8
        before = sum(count for ch, count, _ in MAINLINE_STAGES if ch < chapter)
        return max(0, before + stage)

    def _rep_allocations(self) -> dict[int, int]:
        if not getattr(self, "rep_alloc_spins", None):
            return {}
        return {
            fid: spin.value()
            for fid, spin in self.rep_alloc_spins.items()
            if spin.value() > 0
        }

    def _on_rep_alloc_changed(self) -> None:
        if not getattr(self, "rep_alloc_spins", None):
            return
        available = self._rep_available_points()
        spent = sum(self._rep_allocations().values())
        self.lbl_rep_budget.setText(f"可分配共 {available} 点（已分配 {spent} 点）")
        self._update_rep_summary()
        self._schedule_auto_save()
    def _update_rep_summary(self) -> None:
        """按多阵营分配累计各阵营 1..N 级挑战词条，汇总到看板。"""
        if not hasattr(self, "lbl_rep_summary"):
            return
        kb = _load_reputation_kb()
        allocations = self._rep_allocations()
        if not allocations:
            self.lbl_rep_summary_title.setText("挑战效果汇总")
            self.lbl_rep_summary.setText("尚未分配点数")
            return
        heads: list[str] = []
        chips: list[str] = []
        for fid in sorted(allocations):
            pts = allocations[fid]
            fac = (kb.get("factions") or {}).get(str(fid)) or {}
            name = str(fac.get("name") or f"阵营{fid}")
            theme = str(fac.get("theme") or "")
            heads.append(f"{name}×{pts}" + (f"（{theme}）" if theme else ""))
            for lv in range(1, pts + 1):
                for chip in (fac.get("levels") or {}).get(str(lv), []):
                    text = str(chip)
                    if text and text not in chips:
                        chips.append(text)
        boss = (kb.get("bosses") or {}).get(str(max(allocations.values())))
        head = " · ".join(heads)
        self.lbl_rep_summary_title.setText(f"挑战效果汇总 · {head}")
        summary = "累计效果：" + "；".join(chips) if chips else "累计效果：暂无词条数据"
        if boss:
            summary += f" · 最高{max(allocations.values())}级 BOSS：{boss}"
        self.lbl_rep_summary.setText(summary)

    def _update_hero_visibility(self):
        is_hero = bool(self.cmb_mode.currentData())
        self.hero_options.setVisible(is_hero)
        if is_hero:
            self._update_rep_summary()
        self._refresh_chrome()

    def _refresh_skill_title(self):
        count = len(self.skill_grid.get_skills())
        names = self.skill_grid.selected_names()
        if not names:
            self.grp_skill.setTitle("技能（未选 · 不学技能）")
        else:
            self.grp_skill.setTitle(f"技能（已选 {count}/4：{'、'.join(names)}）")

    def _set_advanced_expanded(self, expanded: bool):
        self.advanced_host.setVisible(expanded)

    def _set_skill_panel_expanded(self, expanded: bool):
        self.skill_grid.setVisible(expanded)
        self._sync_priority_bar()
        self._refresh_skill_title()

    def _sync_priority_bar(self) -> None:
        """与技能网格双向同步：保留已有优先级顺序，新选追加尾部，恒最多 4 个。"""
        if getattr(self, "_syncing_priority", False):
            return
        selected = self.skill_grid.get_skills()[: SkillCardGrid.MAX_SKILLS]
        prior = [
            c for c in (getattr(self.settings, "skill_priority", None) or [])
            if str(c) in selected
        ]
        merged = prior + [c for c in selected if c not in prior]
        if merged != selected:
            self._syncing_priority = True
            try:
                self.skill_grid.set_skills(merged)
            finally:
                self._syncing_priority = False
        self.skill_priority_bar.rebuild(
            merged, dict(getattr(self.settings, "skill_custom_routes", None) or {})
        )
        self.skill_priority_bar.setVisible(bool(merged) and self.grp_skill.isChecked())

    def _on_priority_order_changed(self) -> None:
        order = self.skill_priority_bar.order()
        self._syncing_priority = True
        try:
            self.skill_grid.set_skills(order)
        finally:
            self._syncing_priority = False
        self.settings.skill_priority = list(order)
        self._schedule_auto_save()

    def _on_priority_route_changed(self, code: str, route_id: str) -> None:
        routes = {
            str(k): str(v)
            for k, v in (getattr(self.settings, "skill_custom_routes", None) or {}).items()
        }
        if route_id:
            routes[str(code)] = route_id
        else:
            routes.pop(str(code), None)
        self.settings.skill_custom_routes = routes
        self._schedule_auto_save()

    def _on_skills_changed(self):
        names = self.skill_grid.selected_names()
        self._refresh_skill_title()
        # 选满 4 个技能保持展开，确保用户随时可见并可拖拽调整优先级与选择路线
        self.grp_skill.setChecked(True)
        bid = str(self._shell_extras.get("selected_build_id") or "")
        if bid.startswith("custom:"):
            for item in self._custom_builds():
                if item.get("id") == bid:
                    item["skills"] = self.skill_grid.get_skills()
                    break
        self._sync_priority_bar()
        self._refresh_summary()
        self._schedule_auto_save()

    def _refresh_archive_title(self):
        levels = self.archive_grid.get_levels()
        if levels:
            shown = "、".join(f"{SKILL_LABELS.get(code, code)}{lv}" for code, lv in levels.items())
            self.grp_archive.setTitle(f"技能存档等级（{shown}）")
        else:
            self.grp_archive.setTitle("技能存档等级（未填=未知）")

    def _set_archive_panel_expanded(self, expanded: bool):
        self.archive_grid.setVisible(expanded)
        self._refresh_archive_title()

    def _on_archive_levels_changed(self):
        self._refresh_archive_title()
        self._schedule_auto_save()

    def _on_negative_changed(self):
        self._schedule_auto_save()

    def _wire_auto_save(self):
        self.txt_stage_target.textChanged.connect(self._schedule_auto_save)
        self.cmb_mode.currentIndexChanged.connect(self._schedule_auto_save)
        self.spn_cycle_num.valueChanged.connect(self._schedule_auto_save)
        self.chk_secret_realm.toggled.connect(self._schedule_auto_save)
        self.chk_auto_close_main_line.toggled.connect(self._schedule_auto_save)
        self.chk_auto_create_room.toggled.connect(self._schedule_auto_save)
        self.txt_room_name.textChanged.connect(self._schedule_auto_save)
        self.txt_room_password.textChanged.connect(self._schedule_auto_save)
        self.cmb_room_reuse.currentIndexChanged.connect(self._schedule_auto_save)
        self.cmb_cjb_boss.currentIndexChanged.connect(self._schedule_auto_save)
        self.cmb_sgzx_boss.currentIndexChanged.connect(self._schedule_auto_save)
        self.spn_cycle_num.valueChanged.connect(self._refresh_progress)
        self.txt_stage_target.textChanged.connect(self._refresh_summary)
        self.txt_stage_target.textChanged.connect(self._on_rep_alloc_changed)

    def _schedule_auto_save(self):
        try:
            self._save_timer.start()
        except Exception:
            pass

    def user_settings_path(self) -> Path:
        return self.app_data / USER_SETTINGS_NAME

    def _save_settings_now(self):
        try:
            settings = self.collect_settings_from_ui()
            self.settings = copy.deepcopy(settings)
            self._write_user_bundle(settings)
        except (ValueError, Exception):
            pass

    def _on_save_settings_clicked(self) -> None:
        try:
            settings = self.collect_settings_from_ui()
            self.settings = copy.deepcopy(settings)
            self._write_user_bundle(settings)
        except ValueError as exc:
            QMessageBox.warning(self, "请检查运行设置", str(exc))
            return
        except Exception as exc:
            self.log(f"[保存失败] {exc}", "error")
            return
        self.log(f"[保存] 已写入 {self.user_settings_path()}")

    def _write_user_bundle(self, settings: Settings) -> None:
        path = self.user_settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        data = collect_persistable_settings(settings)
        data["_shell"] = dict(self._shell_extras)
        data["_shell_schema"] = SHELL_SCHEMA_VERSION
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def _on_worker_log(self, text: str, level: str = "info") -> None:
        text = str(text)
        self.lbl_latest.setText(text)
        if hasattr(self, "txt_log") and self.txt_log is not None:
            self.txt_log.appendPlainText(text)

    def log(self, text: str, level: str = "info"):
        text = str(text)
        log_level = {"error": logging.ERROR, "warn": logging.WARNING}.get(level, logging.INFO)
        LOGGER.log(log_level, text)
        self._on_worker_log(text, level)

    def update_status(
        self,
        running: bool,
        phase: str,
        game_count: int,
        terminal_reason: str = "",
        ocr_status: str = "",
        last_action: str = "",
    ):
        self._game_count = int(game_count or 0)
        self._runtime_phase = str(phase or "IDLE")
        if running:
            self._terminal_reason = ""
            if ocr_status:
                self._ocr_status = str(ocr_status)
            self._last_action = str(last_action or self._last_action)
            self.lbl_run_status.setText("运行中")
            self.lbl_run_status.setStyleSheet("")
            self.lbl_run_status.setProperty("state", "running")
        else:
            reason = str(terminal_reason or self._terminal_reason or "待命").strip()
            self._terminal_reason = reason
            self._last_action = str(last_action or self._last_action)
            self.lbl_run_status.setText("待命" if reason in {"待命", "待命中"} else reason)
            self.lbl_run_status.setStyleSheet("")
            self.lbl_run_status.setProperty("state", "idle")
            self.lbl_summary.setText(f"已停止：{reason}")
        self.lbl_run_status.setStyle(self.lbl_run_status.style())
        if self.overlay_hud is not None:
            cycle = int(self.spn_cycle_num.value()) if hasattr(self, "spn_cycle_num") else 0
            self.overlay_hud.update_status(
                bool(running), self._runtime_phase, self._ocr_status,
                self._game_count, cycle, self._terminal_reason, self._last_action,
            )
        self._refresh_progress()
        self._refresh_chrome()

    def load_local_settings(self, silent: bool = False):
        user_path = self.user_settings_path()
        try:
            if user_path.is_file():
                raw = json.loads(user_path.read_text(encoding="utf-8"))
                extras = raw.pop("_shell", {}) if isinstance(raw, dict) else {}
                if isinstance(extras, dict):
                    if raw.get("_shell_schema") != SHELL_SCHEMA_VERSION:
                        route = extras.get("attr_route")
                        if isinstance(route, str):
                            extras["attr_route"] = []
                    self._shell_extras.update(extras)
                settings = Settings._from_dict(raw if isinstance(raw, dict) else {})
                source = "user_settings.json"
                default_bond = (
                    "bond_scheme" not in self._shell_extras
                    and not (settings.cards or [])
                )
            elif FACTORY_SETTINGS.is_file():
                settings = Settings.load(FACTORY_SETTINGS)
                source = FACTORY_SETTINGS.name
                default_bond = True
            else:
                return
            self.apply_settings_to_ui(settings, bond_default=default_bond)
            saved_theme = str(self._shell_extras.get("theme") or "dark")
            if saved_theme != getattr(self, "current_theme", "dark"):
                self.current_theme = saved_theme
                self._apply_component_theme()
            if hasattr(self, "btn_theme"):
                self.btn_theme.setText("切换深色" if self.current_theme == "light" else "切换浅色")
            mode_id = str(self._shell_extras.get("selected_mode_id") or "normal_farm")
            self._select_mode(mode_id if mode_id in self._page_index else "normal_farm")
            if not silent:
                self.log(f"[加载] 已载入 {source}")
        except Exception as exc:
            self.log(f"[加载失败] {exc}", "error")

    def apply_settings_to_ui(self, settings: Settings, *, bond_default: bool = False):
        self.settings = copy.deepcopy(settings)
        targets = [item.strip() for item in (settings.stage_targets or []) if item.strip()]
        target = targets[0] if targets else f"1-{max(1, int(settings.stage2))}"
        self._apply_stage_target(target)
        self.chk_secret_realm.setChecked(settings.auto_secret_realm)
        self.chk_auto_close_main_line.setChecked(getattr(settings, "auto_close_main_line", False))
        for combo, value in (
            (self.cmb_cjb_boss, str(getattr(settings, "cjb_boss", "") or "")),
            (self.cmb_sgzx_boss, str(getattr(settings, "sgzx_boss", "") or "")),
        ):
            if value:
                idx = combo.findData(value)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
        self.chk_auto_create_room.setChecked(bool(settings.auto_create_room))
        self.txt_room_name.setText(str(settings.room_name or ""))
        self.txt_room_password.setText(str(settings.room_password or ""))
        reuse_index = self.cmb_room_reuse.findData(bool(settings.new_room_every_times))
        self.cmb_room_reuse.setCurrentIndex(reuse_index if reuse_index >= 0 else 0)
        self.spn_cycle_num.setValue(int(settings.cycle_num or 0))
        self.settings.skill_priority = [str(c) for c in (getattr(settings, "skill_priority", None) or [])]
        self.settings.skill_custom_routes = dict(getattr(settings, "skill_custom_routes", None) or {})
        self.skill_grid.set_skills(settings.skills or [])
        self.archive_grid.set_levels(dict(getattr(settings, "skill_archive_levels", None) or {}))

        card_stems = []
        for item in settings.cards or []:
            text = str(item or "").strip()
            if text:
                card_stems.append(Path(text).stem)
        if card_stems:
            self._shell_extras["bond_scheme"] = list(card_stems)
            self._shell_extras["bond_inverted"] = [
                code for code in self._bond_plan_boxes if code not in set(card_stems)
            ]
        elif bond_default:
            self._shell_extras.pop("bond_scheme", None)
            self._shell_extras.pop("bond_inverted", None)
        else:
            self._shell_extras["bond_scheme"] = []
            self._shell_extras["bond_inverted"] = []

        self._rebuild_bond_plan()
        self.grp_negative.set_allowed(list(getattr(settings, "treasure_allow_negative", []) or []))
        mode_index = self.cmb_mode.findData(bool(settings.auto_reputation))
        self.cmb_mode.setCurrentIndex(mode_index if mode_index >= 0 else 0)
        rep_alloc_raw = self._shell_extras.get("rep_alloc")
        if isinstance(rep_alloc_raw, dict) and rep_alloc_raw:
            rep_alloc: dict[int, int] = {}
            for key, value in rep_alloc_raw.items():
                try:
                    fid = int(key)
                    pts = int(value or 0)
                except (TypeError, ValueError):
                    continue
                if fid in self.rep_alloc_spins and 0 <= pts <= 10:
                    rep_alloc[fid] = pts
            for fid, spin in self.rep_alloc_spins.items():
                spin.blockSignals(True)
                spin.setValue(rep_alloc.get(fid, 0))
                spin.blockSignals(False)
            self._on_rep_alloc_changed()

        routes = self._shell_extras.get("attr_route") or []
        if isinstance(routes, str):
            routes = [routes]
        self._shell_extras["attr_route"] = routes
        for route, button in self.route_buttons.items():
            button.blockSignals(True)
            button.setChecked(route in routes)
            button.blockSignals(False)

        self._sync_bonds_from_scheme()
        self._update_hero_visibility()

    def collect_settings_from_ui(self) -> Settings:
        target = self.txt_stage_target.text().strip()
        match = re.fullmatch(r"([1-9]\d*)-([1-9]\d*)", target)
        if match is None:
            raise ValueError("目标关卡必须是“章节-关卡”，例如 1-10")
        chapter, stage_index = (int(value) for value in match.groups())
        if chapter not in STAGE_MAX or stage_index > STAGE_MAX[chapter]:
            raise ValueError(
                f"关卡 {target} 不在当前主线范围内（主线{chapter} 现有 1-{STAGE_MAX.get(chapter, 0)}）"
            )
        skills = self.skill_grid.get_skills()
        settings = copy.deepcopy(self.settings)
        settings.game_mode = 0
        settings.mode_id = self.selected_mode_id()
        prefix_widget = getattr(self, "cmb_hitch_prefix", None)
        if prefix_widget is not None:
            settings.hitch_stage_prefix = str(prefix_widget.currentData() or "3")[:1] or "3"
        settings.stage1 = stage_index
        settings.stage2 = stage_index
        settings.stage_targets = [target]
        settings.auto_create_room = True
        settings.room_name = ""
        settings.room_password = ""
        settings.new_room_every_times = False
        settings.lab_focus = ""
        settings.dry_run = False
        settings.cjb_boss = str(self.cmb_cjb_boss.currentData() or "")
        settings.sgzx_boss = str(self.cmb_sgzx_boss.currentData() or "")
        settings.auto_secret_realm = self.chk_secret_realm.isChecked()
        settings.auto_close_main_line = self.chk_auto_close_main_line.isChecked()
        settings.cycle_num = int(self.spn_cycle_num.value())
        settings.skills = skills
        settings.skill_archive_levels = self.archive_grid.get_levels()
        settings.skill_priority = self.skill_priority_bar.order() or list(skills)
        settings.skill_custom_routes = {
            **(getattr(self.settings, "skill_custom_routes", None) or {}),
            **self.skill_priority_bar.route_selections(),
        }
        settings.cards = self.assemble_whitelist_cards()
        settings.treasure_allow_negative = self.grp_negative.get_allowed()
        settings.auto_reputation = bool(self.cmb_mode.currentData())
        allocations = self._rep_allocations()
        available = self._rep_available_points()
        if settings.auto_reputation and not allocations:
            raise ValueError("英雄模式需要至少给一个声望阵营分配点数")
        if sum(allocations.values()) > available:
            raise ValueError(
                f"声望点数超限：已分配 {sum(allocations.values())} 点，"
                f"目标关卡 {target} 可分配共 {available} 点，请调低分配"
            )
        self._shell_extras["rep_alloc"] = {
            str(fid): pts for fid, pts in allocations.items()
        }
        settings.reputation_allocations = {
            str(fid): pts for fid, pts in allocations.items()
        }
        if allocations:
            primary = sorted(allocations.items(), key=lambda t: (-t[1], t[0]))[0][0]
            settings.reputation_type = primary
            settings.reputation_level = min(10, allocations[primary])
        return settings

    def official_build(self, build_id: str) -> dict | None:
        for item in OFFICIAL_BUILDS:
            if str(item.get("id")) == build_id:
                return item
        return None

    def apply_official_build(self, build_id: str, *, confirm: bool = True) -> bool:
        build = self.official_build(build_id)
        if not build:
            return False
        new_skills = [str(c) for c in (build.get("skills") or [])][: SkillCardGrid.MAX_SKILLS]
        new_cards = [str(c) for c in (build.get("cards") or [])]
        new_rep = int(build.get("reputation_type") or 3)

        if confirm:
            cur = self.collect_settings_from_ui()
            diff = (
                f"技能：{'/'.join(skill_display_name(c) for c in cur.skills) or '无'}"
                f" → {'/'.join(skill_display_name(c) for c in new_skills) or '无'}\n"
                f"羁绊：{'/'.join(bond_display_name(c) for c in cur.cards) or '无'}"
                f" → {'/'.join(bond_display_name(c) for c in new_cards) or '无'}"
            )
            answer = QMessageBox.question(
                self, "应用流派", f"将应用「{build.get('name') or build_id}」：\n\n{diff}",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return False

        self.skill_grid.set_skills(new_skills)
        self._shell_extras["selected_build_id"] = build_id
        self._shell_extras["bond_scheme"] = list(new_cards)
        self._shell_extras["bond_inverted"] = [
            code for code in self._bond_plan_boxes if code not in set(new_cards)
        ]
        self._sync_bonds_from_scheme()
        rep_spin = self.rep_alloc_spins.get(int(new_rep or 0))
        if rep_spin is not None and rep_spin.value() == 0:
            rep_spin.setValue(5)
        self._refresh_chrome()
        return True

    def _apply_build(self, build_id: str) -> None:
        if not build_id:
            return
        self.apply_official_build(build_id, confirm=False)

    def toggle_run(self):
        if self._is_running():
            self.log("[操作] 正在停止任务……", "warn")
            self.runner.stop()
            return
        mode_id = self.selected_mode_id()
        if not desktop_may_start(mode_id):
            self.log(f"[阻断] {mode_id} 未验证", "error")
            return
        try:
            settings = self.collect_settings_from_ui()
        except ValueError as exc:
            QMessageBox.warning(self, "请检查运行设置", str(exc))
            return
        try:
            self.settings = copy.deepcopy(settings)
            self._write_user_bundle(settings)
        except Exception:
            pass
        if not _is_admin():
            QMessageBox.critical(
                self, "需要管理员权限",
                "游戏通常以管理员身份运行。请以管理员身份启动程序。",
            )
            self.log("[阻断] 真机运行需要管理员权限", "error")
            return
        answer = QMessageBox.warning(
            self, "确认开始真机运行",
            "程序将向游戏窗口发送真实鼠标和键盘输入。\n\n确认开始吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            worker = self.runner.start(mode_id, settings)
        except ModeNotEnabled as exc:
            self.log(f"[阻断] {exc}", "error")
            return
        except Exception as exc:
            self.log(f"[阻断] {exc}", "error")
            return
        self.worker_thread = worker
        worker.signals.log_emitted.connect(self._on_worker_log)
        worker.signals.status_changed.connect(self.update_status)
        worker.signals.status_updated.connect(self.update_status)
        worker.finished.connect(self._on_worker_finished)
        worker.start()
        self._status_timer.start()
        self.log("[点火] 任务已启动。可按 F12 或点击 HUD 停止", "warn")

    def _on_worker_finished(self) -> None:
        self._status_timer.stop()
        worker = self.worker_thread
        count = int(getattr(getattr(worker, "mediator", None), "game_count", 0) or 0)
        reason = str(getattr(worker, "terminal_reason", "") or self._terminal_reason or "任务已停止")
        phase = str(getattr(worker, "phase", "IDLE") or "IDLE")
        ocr_status = str(getattr(worker, "ocr_status", "") or self._ocr_status)
        last_action = str(getattr(worker, "last_action", "") or self._last_action)
        self.runner.release_after_finish()
        self.worker_thread = None
        self.update_status(False, phase, count, reason, ocr_status, last_action)
        self.showNormal()
        self.raise_()

    def closeEvent(self, event):
        worker = getattr(self, "worker_thread", None)
        if worker is not None and worker.isRunning():
            self.runner.stop()
            if not worker.wait(15000):
                self.log("[关闭] 任务线程未在 15s 内退出，继续等待", "warn")
                worker.wait(60000)
            if worker.isRunning():
                self.log("[关闭] worker 仍在运行，窗口不关闭", "warn")
                event.ignore()
                return
        try:
            settings = self.collect_settings_from_ui()
            self.settings = copy.deepcopy(settings)
            self._write_user_bundle(settings)
        except Exception:
            pass
        self.runner.release_after_finish()
        if self.overlay_hud is not None:
            self.overlay_hud.close()
        event.accept()
