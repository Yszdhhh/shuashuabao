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

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QAction, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
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
    QListWidget,
    QListWidgetItem,
    QListView,
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
from shuabao.subscription_client import (
    SUBSCRIPTION_LICENSE_KEY_ENV,
    validate_entitlement,
)
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
UI_DESIGN_REVISION = "OD12 · 87853C96"
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))
if not (ROOT / "config").is_dir():
    ROOT = Path(__file__).resolve().parents[3]

SHELL_SCHEMA_VERSION = 2


from shuabao.paths import get_canonical_app_data_dir, migrate_legacy_data


def _app_data_dir() -> Path:
    return get_canonical_app_data_dir()

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


def _reduce_motion() -> bool:
    """Offscreen tests and explicit reduce-motion skip overlay/scene animation."""
    flag = os.environ.get("SHUABAO_REDUCE_MOTION", "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        return True
    return os.environ.get("QT_QPA_PLATFORM", "").lower() == "offscreen"


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

FACTION_SLUGS = {
    1: "heifeng", 2: "yinse", 3: "kenrito",
    4: "tanxian", 5: "yuansu", 6: "shouhu",
}
FACTION_SHORT_NAMES = {
    1: "黑锋", 2: "银色", 3: "肯瑞托",
    4: "探险者", 5: "元素", 6: "守护龙",
}


def _is_admin() -> bool:
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


class LaunchCheckPanel(QFrame):
    """OD12 结构化核对窄栏；text() 继续提供可测试的纯文本投影。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("prototype12LaunchCheck")
        self.setMinimumWidth(196)
        self.setMaximumWidth(196)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        self._plain_text = ""
        self._skill_codes: list[str] = []
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(11, 10, 11, 10)
        self._lay.setSpacing(0)

    def text(self) -> str:
        return self._plain_text

    def set_skill_codes(self, codes: list[str]) -> None:
        self._skill_codes = [str(code) for code in codes[:4] if str(code)]

    def setText(self, text: str) -> None:
        self._plain_text = str(text)
        while self._lay.count():
            item = self._lay.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        lines = self._plain_text.splitlines()
        title = QLabel(lines[0] if lines else "启动前核对")
        title.setObjectName("launchCheckTitle")
        self._lay.addWidget(title)

        if len(lines) > 1:
            ready = QLabel(f"●  {lines[1]}")
            ready.setObjectName("launchCheckReady")
            ready.setWordWrap(True)
            self._lay.addWidget(ready)

        pairs = list(zip(lines[2::2], lines[3::2]))
        for heading, value in pairs:
            section = QFrame()
            section.setObjectName("launchCheckSection")
            section_lay = QVBoxLayout(section)
            section_lay.setContentsMargins(0, 8, 0, 7)
            section_lay.setSpacing(4)
            cap = QLabel(heading)
            cap.setObjectName("launchCheckCaption")
            section_lay.addWidget(cap)
            if heading == "已选技能" and self._skill_codes:
                for rank, code in enumerate(self._skill_codes, 1):
                    row = QWidget()
                    row_lay = QHBoxLayout(row)
                    row_lay.setContentsMargins(0, 0, 0, 0)
                    row_lay.setSpacing(6)
                    rank_label = QLabel(str(rank))
                    rank_label.setObjectName("launchSkillRank")
                    rank_label.setFixedSize(18, 18)
                    rank_label.setAlignment(Qt.AlignCenter)
                    row_lay.addWidget(rank_label)
                    icon = QLabel()
                    icon.setObjectName("launchSkillIcon")
                    icon.setFixedSize(22, 22)
                    icon_path = SKILL_ICON_DIR / f"{code}.png"
                    if icon_path.is_file():
                        icon.setPixmap(QPixmap(str(icon_path)).scaled(
                            22, 22, Qt.KeepAspectRatio, Qt.SmoothTransformation
                        ))
                    row_lay.addWidget(icon)
                    name = QLabel(skill_display_name(code))
                    name.setObjectName("launchCheckValue")
                    row_lay.addWidget(name, 1)
                    section_lay.addWidget(row)
            else:
                value_label = QLabel(value)
                value_label.setObjectName("launchCheckValue")
                value_label.setWordWrap(True)
                section_lay.addWidget(value_label)
            self._lay.addWidget(section)
        self._lay.activate()
        self.setMaximumHeight(self.sizeHint().height() + 8)


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
                    self._refresh_hint(blocked=True)
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
        full = len(self._selected) >= self.MAX_SKILLS
        for code, btn in self.cards.items():
            name = skill_display_name(code)
            btn.setText(f"{order[code]}. {name}" if code in order else name)
            dimmed = full and code not in order
            btn.setProperty("dimmed", dimmed)
            btn.setToolTip(
                self._tooltip_for(code) + ("<br/>已满 4 个，先取消一个再选" if dimmed else "")
            )
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _mode_hint_text(self, blocked: bool = False) -> str:
        count = len(self._selected)
        if blocked or count >= self.MAX_SKILLS:
            return f"已选 {count} / {self.MAX_SKILLS}：已满，先点已选技能取消后再选。"
        if count == 0:
            return "当前已选 0 个技能：不自动学习任何技能（技能面板直接关闭/隐藏，不刷新、不放弃技能点）。"
        return f"当前已选 {count} 个技能【严格模式】：仅学习勾选技能，未选中的永远不学。"

    def _refresh_hint(self, blocked: bool = False):
        if hasattr(self, "hint"):
            self.hint.setText(self._mode_hint_text(blocked=blocked))


class SkillPriorityBar(QWidget):
    """OD12 内联技能优先级：编号、图标、名称、路线展开、上/下移、移除。"""

    order_changed = Signal()
    route_changed = Signal(str, str)
    remove_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("skillRankList")
        self._families: dict = SKILL_ROUTE_FAMILIES
        self._route_prefs: dict[str, str] = {}
        self._codes: list[str] = []
        self._syncing = False
        self._expanded_route = ""
        self._cards: dict[str, QFrame] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(6)
        head = QHBoxLayout()
        cap = QLabel("技能优先级")
        cap.setObjectName("skillRankCaption")
        hint = QLabel("上移 / 下移调整顺序")
        hint.setObjectName("hintLabel")
        head.addWidget(cap)
        head.addWidget(hint, 1)
        lay.addLayout(head)
        self._cards_host = QWidget()
        self._cards_host.setObjectName("skillRankCards")
        self._cards_lay = QVBoxLayout(self._cards_host)
        self._cards_lay.setContentsMargins(0, 0, 0, 0)
        self._cards_lay.setSpacing(0)
        lay.addWidget(self._cards_host)

    def rebuild(self, codes: list[str], route_prefs: dict[str, str] | None = None) -> None:
        self._syncing = True
        try:
            self._codes = [str(code) for code in codes if str(code)]
            self._route_prefs = dict(route_prefs or {})
            if self._expanded_route not in self._codes:
                self._expanded_route = ""
            self._rebuild_cards()
        finally:
            self._syncing = False
        self.setVisible(bool(self._codes))

    def route_expanded(self) -> bool:
        return bool(self._expanded_route)

    def collapse_route_panel(self) -> None:
        if not self._expanded_route:
            return
        self._expanded_route = ""
        self._rebuild_cards()

    def _family(self, code: str) -> dict:
        item = (self._families or {}).get(code) or {}
        return item if isinstance(item, dict) else {}

    def _routes(self, code: str) -> list[dict]:
        raw = self._family(code).get("routes") or []
        return [item for item in raw if isinstance(item, dict) and item.get("id")]

    def _default_route(self, code: str) -> str:
        routes = self._routes(code)
        return str(routes[0].get("id") or "") if routes else ""

    def _route_label(self, code: str) -> str:
        current = self._route_prefs.get(code) or self._default_route(code)
        for spec in self._routes(code):
            if str(spec.get("id") or "") == current:
                return str(spec.get("label") or current)
        return current

    def _rebuild_cards(self) -> None:
        while self._cards_lay.count():
            item = self._cards_lay.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._cards = {}
        last = len(self._codes) - 1
        for index, code in enumerate(self._codes):
            card = self._make_card(index, code, last)
            self._cards[code] = card
            self._cards_lay.addWidget(card)

    def _make_card(self, index: int, code: str, last: int) -> QFrame:
        card = QFrame()
        card.setObjectName("skillRankCard")
        card.setProperty("code", code)
        card.setProperty("carry", index == 0)
        card.setFocusPolicy(Qt.StrongFocus)
        outer = QVBoxLayout(card)
        outer.setContentsMargins(2, 4, 2, 4)
        outer.setSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(6)
        rank = QLabel(str(index + 1))
        rank.setObjectName("skillRankNo")
        rank.setFixedSize(20, 20)
        rank.setAlignment(Qt.AlignCenter)
        icon = QLabel()
        icon.setObjectName("skillRankIcon")
        icon.setFixedSize(28, 28)
        path = SKILL_ICON_DIR / f"{code}.png"
        if path.is_file():
            icon.setPixmap(QPixmap(str(path)).scaled(
                28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation
            ))
        name_box = QVBoxLayout()
        name_box.setSpacing(0)
        name = QLabel(skill_display_name(code))
        name.setObjectName("skillRankName")
        aff = str(self._family(code).get("aff") or "")
        priority = "主 C · 第1优先级" if index == 0 else f"第{index + 1}优先级"
        sub = QLabel(priority + (f" · {aff}" if aff else ""))
        sub.setObjectName("hintLabel")
        name_box.addWidget(name)
        name_box.addWidget(sub)
        route_btn = QPushButton(self._route_label(code) or "路线")
        route_btn.setObjectName("skillRouteBtn")
        route_btn.setCursor(Qt.PointingHandCursor)
        route_btn.setVisible(bool(self._routes(code)))
        route_btn.clicked.connect(lambda _=False, c=code: self._toggle_route_panel(c))
        up = QPushButton("▲")
        down = QPushButton("▼")
        remove = QPushButton("×")
        for button, name_id in ((up, "skillRankMove"), (down, "skillRankMove"), (remove, "skillRankRemove")):
            button.setObjectName(name_id)
            button.setCursor(Qt.PointingHandCursor)
            button.setFixedSize(22, 20)
        up.setEnabled(index > 0)
        down.setEnabled(index < last)
        up.setToolTip(f"{skill_display_name(code)} 上移")
        down.setToolTip(f"{skill_display_name(code)} 下移")
        remove.setToolTip(f"移除 {skill_display_name(code)}")
        up.clicked.connect(lambda _=False, c=code: self._move_code(c, -1))
        down.clicked.connect(lambda _=False, c=code: self._move_code(c, 1))
        remove.clicked.connect(lambda _=False, c=code: self.remove_requested.emit(c))
        row.addWidget(rank)
        row.addWidget(icon)
        row.addLayout(name_box, 1)
        row.addWidget(route_btn)
        row.addWidget(up)
        row.addWidget(down)
        row.addWidget(remove)
        outer.addLayout(row)
        if self._expanded_route == code:
            panel = QWidget()
            panel.setObjectName("skillRoutePanel")
            panel_lay = QVBoxLayout(panel)
            panel_lay.setContentsMargins(48, 0, 0, 4)
            panel_lay.setSpacing(4)
            current = self._route_prefs.get(code) or self._default_route(code)
            for spec in self._routes(code):
                rid = str(spec.get("id") or "")
                option = QPushButton(str(spec.get("label") or rid))
                option.setObjectName("skillRouteOption")
                option.setCheckable(True)
                option.setChecked(rid == current)
                option.setCursor(Qt.PointingHandCursor)
                option.clicked.connect(lambda _=False, c=code, r=rid: self._pick_route(c, r))
                panel_lay.addWidget(option)
            outer.addWidget(panel)
        card.installEventFilter(self)
        return card

    def eventFilter(self, obj, event):
        code = str(obj.property("code") or "") if isinstance(obj, QWidget) else ""
        if code and event.type() == QEvent.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Up:
                self._move_code(code, -1)
                return True
            if key == Qt.Key.Key_Down:
                self._move_code(code, 1)
                return True
            if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                self.remove_requested.emit(code)
                return True
            if key == Qt.Key.Key_Escape and self._expanded_route:
                self.collapse_route_panel()
                obj.setFocus()
                return True
        return super().eventFilter(obj, event)

    def _toggle_route_panel(self, code: str) -> None:
        self._expanded_route = "" if self._expanded_route == code else code
        self._rebuild_cards()
        card = self._cards.get(code)
        if card is not None:
            card.setFocus()

    def _pick_route(self, code: str, route_id: str) -> None:
        self._route_prefs[str(code)] = str(route_id)
        self._expanded_route = ""
        if not self._syncing:
            self.route_changed.emit(str(code), str(route_id))
        self._rebuild_cards()

    def _move_code(self, code: str, delta: int) -> None:
        if code not in self._codes:
            return
        index = self._codes.index(code)
        target = index + delta
        if target < 0 or target >= len(self._codes):
            return
        self._codes[index], self._codes[target] = self._codes[target], self._codes[index]
        self._rebuild_cards()
        card = self._cards.get(code)
        if card is not None:
            card.setFocus()
        if not self._syncing:
            self.order_changed.emit()

    def order(self) -> list[str]:
        return list(self._codes)

    def route_selections(self) -> dict[str, str]:
        return {
            code: str(self._route_prefs[code])
            for code in self._codes
            if self._route_prefs.get(code)
        }


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
        "贪婪献祭": "每消耗500金币获得1点随机属性；收益待验证",
        "金转木": "断掉金币来源",
        "杀敌梭哈": "收益中断",
        "伐木契约": "之后不再获得木材",
        "等级优势": "立即获得当前等级×10的全属性；卡面未见副作用，完整描述待补帧",
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


class InlineOverlay(QFrame):
    """主窗口内锚定浮层：不是 QDialog，同时只开一个。"""

    dismissed = Signal()

    def __init__(self, host: QWidget):
        super().__init__(host)
        self.setObjectName("inlineOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self._trigger: QWidget | None = None
        self._filter_installed = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)
        head = QHBoxLayout()
        self._title = QLabel()
        self._title.setObjectName("inlineOverlayTitle")
        self._close = QPushButton("关闭")
        self._close.setObjectName("inlineOverlayClose")
        self._close.setCursor(Qt.PointingHandCursor)
        self._close.clicked.connect(self.dismiss)
        head.addWidget(self._title, 1)
        head.addWidget(self._close)
        lay.addLayout(head)
        self._scroll = QScrollArea()
        self._scroll.setObjectName("inlineOverlayBody")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        lay.addWidget(self._scroll, 1)
        self.hide()

    def trigger(self) -> QWidget | None:
        return self._trigger

    def present(self, trigger: QWidget, title: str, body: QWidget) -> None:
        old = self._scroll.takeWidget()
        if old is not None:
            old.deleteLater()
        self._trigger = trigger
        self._title.setText(title)
        self._scroll.setWidget(body)
        self.show()
        self.raise_()
        self.reposition()
        self._install_filter()
        if not _reduce_motion():
            effect = QGraphicsOpacityEffect(self)
            self.setGraphicsEffect(effect)
            animation = QPropertyAnimation(effect, b"opacity", self)
            animation.setDuration(160)
            animation.setStartValue(0.0)
            animation.setEndValue(1.0)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            animation.finished.connect(lambda: self.setGraphicsEffect(None))
            self._present_anim = animation
            animation.start()
        first = body.findChild(QPushButton) or body.findChild(QListWidget)
        if first is not None:
            first.setFocus()

    def dismiss(self) -> None:
        if not self.isVisible():
            return
        trigger = self._trigger
        self.hide()
        self._remove_filter()
        self._trigger = None
        old = self._scroll.takeWidget()
        if old is not None:
            old.deleteLater()
        self.setGraphicsEffect(None)
        if trigger is not None:
            trigger.setFocus()
        self.dismissed.emit()

    def reposition(self) -> None:
        host = self.parentWidget()
        if host is None or self._trigger is None:
            return
        hint = self.sizeHint()
        max_w = max(220, min(560, host.width() - 16))
        max_h = max(160, min(440, host.height() - 24))
        width = min(max(hint.width(), 280), max_w)
        height = min(max(hint.height(), 140), max_h)
        origin = self._trigger.mapTo(host, QPoint(0, self._trigger.height() + 4))
        rect = QRect(origin, QSize(width, height))
        bounds = host.rect().adjusted(8, 8, -8, -8)
        if rect.right() > bounds.right():
            rect.moveRight(bounds.right())
        if rect.left() < bounds.left():
            rect.moveLeft(bounds.left())
        if rect.bottom() > bounds.bottom():
            above = self._trigger.mapTo(host, QPoint(0, -height - 4))
            rect.moveTopLeft(above)
        if rect.top() < bounds.top():
            rect.moveTop(bounds.top())
        if rect.bottom() > bounds.bottom():
            rect.moveBottom(bounds.bottom())
        if rect.height() > bounds.height():
            rect.setHeight(bounds.height())
            rect.moveTop(bounds.top())
        window = host.window()
        avoid = getattr(window, "launch_check", None)
        if avoid is not None and avoid.isVisible() and host.width() >= 920:
            check = QRect(avoid.mapTo(host, QPoint(0, 0)), avoid.size())
            if rect.intersects(check):
                rect.moveRight(min(rect.right(), check.left() - 8))
                if rect.left() < bounds.left():
                    rect.moveLeft(bounds.left())
                    rect.moveTop(min(rect.top() + 24, bounds.bottom() - rect.height()))
        self.setGeometry(rect)

    def _install_filter(self) -> None:
        app = QApplication.instance()
        if app is not None and not self._filter_installed:
            app.installEventFilter(self)
            self._filter_installed = True

    def _remove_filter(self) -> None:
        app = QApplication.instance()
        if app is not None and self._filter_installed:
            app.removeEventFilter(self)
            self._filter_installed = False

    def eventFilter(self, obj, event):
        if not self.isVisible() or event.type() != QEvent.Type.MouseButtonPress:
            return False
        widget = obj if isinstance(obj, QWidget) else None
        if widget is None:
            return False
        if widget is self or self.isAncestorOf(widget):
            return False
        if self._trigger is not None and (widget is self._trigger or self._trigger.isAncestorOf(widget)):
            return False
        if hasattr(event, "globalPosition"):
            global_pos = event.globalPosition().toPoint()
            if self.rect().contains(self.mapFromGlobal(global_pos)):
                return False
        self.dismiss()
        return False

    def hideEvent(self, event) -> None:
        self._remove_filter()
        super().hideEvent(event)


class MainWindow(QMainWindow):
    def __init__(self, app_data: Path | None = None):
        super().__init__()
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.app_data = Path(app_data).resolve() if app_data is not None else _app_data_dir().resolve()
        self.app_data.mkdir(parents=True, exist_ok=True)
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION_LABEL} · {UI_DESIGN_REVISION} · 重生魔兽刷刷刷")
        self._window_role = "chooser"
        self.current_theme = "light"
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
            "selected_mode_variant": "solo",
            "custom_builds": [],
            "rep_alloc": {},
            "theme": "light",
        }
        self.runner = RunnerService(self.app_data, ROOT)
        self.worker_thread: MediatorWorker | None = None
        self._terminal_reason = ""
        self._runtime_phase = "IDLE"
        self._ocr_status = "未启动"
        self._last_action = ""
        self._subscription_key = os.environ.get(SUBSCRIPTION_LICENSE_KEY_ENV, "").strip()
        self._subscription_expires_at = ""
        self._subscription_status = "已配置 · 待校验" if self._subscription_key else "未激活"
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
        self.inline_overlay = InlineOverlay(self.centralWidget())
        self.overlay_hud = OverlayHud()
        self.overlay_hud.stop_requested.connect(self._hud_stop)

        for seq in ("F12", "Shift+F12"):
            shortcut = QShortcut(QKeySequence(seq), self)
            shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
            shortcut.activated.connect(self._hud_stop)

        self._setup_tray()
        restored_dashboard = self.user_settings_path().is_file()
        self.load_local_settings(silent=True)
        self._wire_auto_save()
        if not restored_dashboard:
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
        # OD12 的快速开局只负责选择队伍关系；关卡、挑战和技能都在看板内配置。
        # 复用主窗口选择页，避免维护第二套弹窗状态与两步“挑战”逻辑。
        self._show_mode_choice()

    def _animate_scene_in(self, widget: QWidget) -> None:
        """真实窗口的短促入场反馈；离屏测试、减少动态效果和未显示窗口不运行动画。"""
        if not self.isVisible() or _reduce_motion():
            return
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(140)
        animation.setStartValue(0.82)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.finished.connect(lambda w=widget: w.setGraphicsEffect(None))
        self._scene_animation = animation
        animation.start()

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
        for button in (
            getattr(self, "btn_solo_mode", None),
            getattr(self, "btn_lead_mode", None),
            getattr(self, "btn_follow_mode", None),
            getattr(self, "btn_hitch_mode", None),
        ):
            if button is not None:
                button.setStyleSheet(mode_qss)
                button.setMinimumWidth(0)
                button.setMaximumWidth(440)
                button.setMinimumHeight(60)
                button.setMaximumHeight(62)
                button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        build_qss = official_build_qss(theme)
        for btn in getattr(self, "_build_btn_map", {}).values():
            btn.setStyleSheet(build_qss)

    def toggle_theme(self) -> None:
        self.current_theme = "light" if getattr(self, "current_theme", "dark") == "dark" else "dark"
        self._shell_extras["theme"] = self.current_theme
        self._apply_component_theme()
        if hasattr(self, "btn_theme"):
            self.btn_theme.setText("深色" if self.current_theme == "light" else "浅色")
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

        # 顶部产品带：单行标题栏（logo · 名称/版本 · 状态 · 今日局数 · 弹性空白 · 主题/快速开局/窗口控制）
        header_frame = QFrame()
        header_frame.setObjectName("customTitleBar")
        header_frame.setFixedHeight(42)
        header = QHBoxLayout(header_frame)
        header.setContentsMargins(12, 0, 8, 0)
        header.setSpacing(8)

        logo_path = ROOT / "assets" / "branding" / "app_logo.png"
        if logo_path.exists():
            logo_lbl = QLabel()
            logo_pix = QPixmap(str(logo_path)).scaled(22, 22, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            logo_lbl.setPixmap(logo_pix)
            header.addWidget(logo_lbl)
            self.setWindowIcon(QIcon(str(logo_path)))

        title = QLabel(APP_NAME)
        title.setObjectName("brandTitle")
        title.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        header.addWidget(title)

        ver_lbl = QLabel(f"{APP_VERSION_LABEL} · {UI_DESIGN_REVISION}")
        ver_lbl.setObjectName("versionPill")
        self.lbl_version = ver_lbl
        self.lbl_subtitle = None
        header.addWidget(ver_lbl)

        # 状态胶囊指示器
        self.lbl_run_status = QLabel("待命")
        self.lbl_run_status.setObjectName("statusPill")
        self.lbl_run_status.setAlignment(Qt.AlignCenter)
        header.addWidget(self.lbl_run_status)

        self.lbl_subscription = QLabel("订阅：未激活")
        self.lbl_subscription.setObjectName("subscriptionPill")
        self.lbl_subscription.setAlignment(Qt.AlignCenter)
        self.lbl_subscription.setToolTip("订阅状态仅在激活密钥或启动校验时更新")
        header.addWidget(self.lbl_subscription)

        # 今日局数胶囊
        games_box = QHBoxLayout()
        games_box.setSpacing(4)
        self.lbl_games = QLabel("今日局数: 0")
        self.lbl_games.setStyleSheet("font-weight:700;")
        self.lbl_games_cap = QLabel("/ 100")
        self.lbl_games_cap.setObjectName("gamesCap")
        games_box.addWidget(self.lbl_games)
        games_box.addWidget(self.lbl_games_cap)
        header.addLayout(games_box)

        header.addStretch()

        self.btn_theme = QPushButton("浅色" if self.current_theme == "dark" else "深色")
        self.btn_theme.setObjectName("btnTheme")
        self.btn_theme.setCursor(Qt.PointingHandCursor)
        self.btn_theme.setToolTip("在深色与浅色外观间切换")
        self.btn_theme.clicked.connect(self.toggle_theme)
        header.addWidget(self.btn_theme)

        self.btn_wizard = QPushButton("快速开局")
        self.btn_wizard.setCursor(Qt.PointingHandCursor)
        self.btn_wizard.clicked.connect(self._open_quick_wizard)
        header.addWidget(self.btn_wizard)

        self._header_frame = header_frame
        header_frame.installEventFilter(self)
        self.btn_win_min = QPushButton("─")
        self.btn_win_min.setObjectName("btnWinMin")
        self.btn_win_min.setFixedSize(34, 26)
        self.btn_win_min.setToolTip("最小化")
        self.btn_win_min.clicked.connect(self.showMinimized)
        header.addWidget(self.btn_win_min)
        self.btn_win_close = QPushButton("✕")
        self.btn_win_close.setObjectName("btnWinClose")
        self.btn_win_close.setFixedSize(34, 26)
        self.btn_win_close.setToolTip("关闭")
        self.btn_win_close.clicked.connect(self.close)
        header.addWidget(self.btn_win_close)

        self._header_tool_row = header
        self._header_tool_widgets: list[QWidget] = [self.lbl_run_status]
        self._header_tool_widgets.append(self.btn_theme)
        self._header_tool_widgets.append(self.btn_wizard)

        outer.addWidget(header_frame)

        # 主内容区域 (严格 16px 边距与 12px 间距)
        body = QVBoxLayout()
        body.setContentsMargins(16, 12, 16, 12)
        body.setSpacing(12)

        mode_box = QWidget()
        mode_box.setObjectName("modeChooser")
        self.mode_box = mode_box
        mode_layout = QVBoxLayout(mode_box)
        mode_layout.setContentsMargins(20, 8, 20, 8)
        mode_layout.setSpacing(8)
        cap = QLabel("运行方式")
        cap.setObjectName("sectionCap")
        cap.setAlignment(Qt.AlignCenter)
        mode_layout.addWidget(cap)

        # 原型12：单人/组队分段 + 单人卡 / 组队行（跟车、蹭车），文案由 desktop_may_start 推导
        seg_row = QHBoxLayout()
        seg_row.setSpacing(0)
        self.btn_seg_solo = QPushButton("单人")
        self.btn_seg_team = QPushButton("组队")
        for btn in (self.btn_seg_solo, self.btn_seg_team):
            btn.setCheckable(True)
            btn.setFixedHeight(30)
            btn.setFixedWidth(110)
            btn.setCursor(Qt.PointingHandCursor)
            seg_row.addWidget(btn)
        self.btn_seg_solo.setChecked(True)
        self.seg_group = QButtonGroup(self)
        self.seg_group.setExclusive(True)
        self.seg_group.addButton(self.btn_seg_solo, 0)
        self.seg_group.addButton(self.btn_seg_team, 1)
        mode_layout.addLayout(seg_row)

        self.primary_mode_group = QButtonGroup(self)
        self.btn_solo_mode = QPushButton("单人刷图\n自己建房，自己点开始。")
        self.hitch_badge = badge_text(get_spec("lobby_hitch"))
        self.follow_badge = badge_text(get_spec("follow_team"))
        self.row_team = QWidget()
        team_lay = QVBoxLayout(self.row_team)
        team_lay.setContentsMargins(0, 0, 0, 0)
        team_lay.setSpacing(6)
        self.btn_lead_mode = QPushButton("车头  带车\n开房当车头，房间自动开始。")
        self.btn_follow_mode = QPushButton(f"跟车 · {self.follow_badge}\n已在房间，自动每局准备。")
        self.btn_hitch_mode = QPushButton(f"大厅蹭车 · {self.hitch_badge}\n自动在大厅找房蹭车。")

        for button in (self.btn_solo_mode, self.btn_lead_mode, self.btn_follow_mode, self.btn_hitch_mode):
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setStyleSheet(mode_button_qss(self.current_theme))
            button.setMinimumWidth(0)
            button.setMaximumWidth(440)
            button.setMinimumHeight(60)
            button.setMaximumHeight(62)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.primary_mode_group.addButton(button)

        team_lay.addWidget(self.btn_lead_mode)
        team_lay.addWidget(self.btn_follow_mode)
        team_lay.addWidget(self.btn_hitch_mode)
        self.row_team.setVisible(False)

        def _switch_seg(idx: int) -> None:
            self.btn_solo_mode.setVisible(idx == 0)
            self.row_team.setVisible(idx == 1)
            for btn in (self.btn_seg_solo, self.btn_seg_team):
                btn.setObjectName("btnPrimary" if btn.isChecked() else "")
                btn.style().unpolish(btn)
                btn.style().polish(btn)

        def _on_seg_toggled(btn, on):
            if on:
                _switch_seg(self.seg_group.id(btn))

        self.seg_group.buttonToggled.connect(_on_seg_toggled)
        _switch_seg(0)

        mode_layout.addWidget(self.btn_solo_mode)
        mode_layout.addWidget(self.row_team)
        self.btn_hitch_mode.setToolTip(
            "大厅蹭车当前可从看板启动；说明页保留风险与边界。" if desktop_may_start("lobby_hitch")
            else "大厅蹭车尚未验证，可查看说明，不能从看板点火。")
        self.btn_solo_mode.clicked.connect(lambda: self._select_mode("normal_farm"))
        self.btn_lead_mode.clicked.connect(lambda: self._select_mode("lead"))
        self.btn_follow_mode.clicked.connect(lambda: self._select_mode("follow_team"))
        self.btn_hitch_mode.clicked.connect(lambda: self._select_mode("lobby_hitch"))
        body.addWidget(mode_box, 1)

        # 页面堆叠区
        self.right_stack = QStackedWidget()
        self._page_index: dict[str, int] = {}
        self.team_launch_checks: dict[str, QLabel] = {}
        self.team_page_mains: dict[str, QWidget] = {}
        self.team_page_grids: dict[str, QGridLayout] = {}
        for spec in iter_specs():
            page = self._build_mode_page(spec.id)
            self._page_index[spec.id] = self.right_stack.addWidget(page)
        body.addWidget(self.right_stack, 1)

        outer.addLayout(body, 1)

        # 底部操作栏 (固定吸底液态玻璃)
        self.footer = QFrame()
        self.footer.setObjectName("footerBar")
        foot = QHBoxLayout(self.footer)
        foot.setContentsMargins(10, 6, 10, 6)
        foot.setSpacing(10)

        self.btn_choose_mode = QPushButton("切换运行方式")
        self.btn_choose_mode.setCursor(Qt.PointingHandCursor)
        self.btn_choose_mode.clicked.connect(self._show_mode_choice)
        foot.addWidget(self.btn_choose_mode)

        self.btn_more_settings = QPushButton("更多设置")
        self.btn_more_settings.setObjectName("btnMoreSettings")
        self.btn_more_settings.setCursor(Qt.PointingHandCursor)
        self.btn_more_settings.setToolTip("展开特殊宝物、存档等级、属性线与低频诊断配置")
        self.btn_more_settings.clicked.connect(self._toggle_more_settings)
        foot.addWidget(self.btn_more_settings)

        self.btn_activate_subscription = QPushButton("激活密钥")
        self.btn_activate_subscription.setObjectName("btnActivateSubscription")
        self.btn_activate_subscription.setCursor(Qt.PointingHandCursor)
        self.btn_activate_subscription.setToolTip("输入订阅 License Key 并校验有效期")
        self.btn_activate_subscription.clicked.connect(self._on_activate_subscription_clicked)
        foot.addWidget(self.btn_activate_subscription)

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
        self.btn_main.setFixedHeight(38)
        self.btn_main.setMinimumWidth(120)
        self.btn_main.setCursor(Qt.PointingHandCursor)
        self.btn_main.clicked.connect(self.toggle_run)
        foot.addWidget(self.btn_main)

        outer.addWidget(self.footer)

        self.lbl_latest = QLabel("就绪 · F12 / Shift+F12 紧急停止")
        self.lbl_latest.setVisible(False)

        self._selected_mode_id = "normal_farm"
        self.btn_solo_mode.setChecked(False)
        self.btn_lead_mode.setChecked(False)
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

    def _team_page_shell(self, lay: QVBoxLayout, mode_id: str) -> QVBoxLayout:
        shell = QWidget()
        shell.setObjectName(f"{mode_id}Dashboard")
        grid = QGridLayout(shell)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(12)
        main = QWidget()
        main_lay = QVBoxLayout(main)
        main_lay.setContentsMargins(0, 0, 0, 0)
        main_lay.setSpacing(12)
        check = QLabel()
        check.setObjectName("prototype12LaunchCheck")
        check.setWordWrap(True)
        check.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        check.setMinimumWidth(196)
        check.setMaximumWidth(196)
        grid.addWidget(main, 0, 0)
        grid.setColumnStretch(0, 1)
        check.setVisible(False)
        self.team_launch_checks[mode_id] = check
        self.team_page_mains[mode_id] = main
        self.team_page_grids[mode_id] = grid
        lay.addWidget(shell)
        return main_lay

    def _build_normal_farm_page(self, lay: QVBoxLayout) -> None:
        # OpenDesign v12 规范：宽窗三列（左栏 Rail + 工作区 + 启动前核对窄栏），窄于 920px 纵向堆叠。
        self.dashboard_shell = QWidget()
        self.dashboard_shell.setObjectName("prototype12Dashboard")
        self.dashboard_grid = QGridLayout(self.dashboard_shell)
        self.dashboard_grid.setContentsMargins(0, 0, 0, 0)
        self.dashboard_grid.setSpacing(16)
        self.dashboard_compact = False

        left_rail = QWidget()
        left_rail.setObjectName("prototype12Rail")
        left_rail.setFixedWidth(204)
        self.left_rail = left_rail
        left_rail_lay = QVBoxLayout(left_rail)
        left_rail_lay.setContentsMargins(0, 0, 0, 0)
        left_rail_lay.setSpacing(12)

        right_main = QWidget()
        right_main.setObjectName("prototype12Workspace")
        self.right_main = right_main
        right_main_lay = QVBoxLayout(right_main)
        right_main_lay.setContentsMargins(0, 0, 0, 0)
        right_main_lay.setSpacing(12)

        run_box, run_lay = self._section("运行目标", "")
        run_box.setObjectName("od12FlatSection")
        target_grid = QGridLayout()
        target_grid.setHorizontalSpacing(8)
        target_grid.setVerticalSpacing(6)

        target_grid.addWidget(QLabel("篇章"), 0, 0, 1, 2)
        self.cmb_chapter = QComboBox()
        self.cmb_chapter.setFixedHeight(34)
        for chapter, _count, label in MAINLINE_STAGES:
            self.cmb_chapter.addItem(MAINLINE_DISPLAY.get(chapter, label), chapter)
        self.cmb_chapter.setVisible(False)
        self.cmb_chapter.setFixedSize(0, 0)
        self.cmb_chapter.setParent(run_box)

        self.cmb_stage = QComboBox()
        self.cmb_stage.setFixedHeight(34)
        self.cmb_stage.setVisible(False)
        self.cmb_stage.setFixedSize(0, 0)
        self.cmb_stage.setParent(run_box)
        self.txt_stage_target = QLineEdit("1-10")
        self.txt_stage_target.setVisible(False)
        self._filling_stage = False
        self._refill_stage_combo(keep_stage=10)

        self.btn_chapter_picker = QPushButton()
        self.btn_chapter_picker.setObjectName("inlinePickRow")
        self.btn_chapter_picker.setCursor(Qt.PointingHandCursor)
        self.btn_chapter_picker.clicked.connect(self._open_chapter_overlay)
        self.btn_stage_picker = QPushButton()
        self.btn_stage_picker.setObjectName("inlinePickRow")
        self.btn_stage_picker.setCursor(Qt.PointingHandCursor)
        self.btn_stage_picker.clicked.connect(self._open_stage_overlay)

        self.cmb_chapter.currentIndexChanged.connect(self._on_chapter_changed)
        self.cmb_stage.currentIndexChanged.connect(self._on_stage_combo_changed)
        self.txt_stage_target.textChanged.connect(self._on_stage_target_edited)
        self.cmb_chapter.currentIndexChanged.connect(self._recommend_challenges_for_stage)
        self.cmb_stage.currentIndexChanged.connect(self._recommend_challenges_for_stage)
        self.txt_stage_target.textEdited.connect(self._recommend_challenges_for_stage)
        self.cmb_chapter.currentIndexChanged.connect(self._refresh_stage_picker_rows)
        self.cmb_stage.currentIndexChanged.connect(self._refresh_stage_picker_rows)

        target_grid.addWidget(self.btn_chapter_picker, 1, 0, 1, 2)
        target_grid.addWidget(QLabel("关卡"), 2, 0)
        target_grid.addWidget(QLabel("目标局数"), 2, 1)
        target_grid.addWidget(self.btn_stage_picker, 3, 0)
        self._refresh_stage_picker_rows()

        self.cmb_mode = QComboBox()
        self.cmb_mode.setFixedHeight(34)
        self.cmb_mode.addItem("普通", False)
        self.cmb_mode.addItem("英雄", True)
        self.cmb_mode.setVisible(False)
        self.chk_reputation_mode = QCheckBox("声望挑战")
        self.chk_reputation_mode.setObjectName("od12Switch")
        self.chk_reputation_mode.setCursor(Qt.PointingHandCursor)
        self.chk_reputation_mode.setToolTip("开启后分配声望阵营与挑战点数")
        self.chk_reputation_mode.toggled.connect(self._set_reputation_mode_from_switch)
        self.cmb_mode.currentIndexChanged.connect(self._sync_reputation_switch)
        self.spn_cycle_num = QSpinBox()
        self.spn_cycle_num.setRange(0, 999)
        self.spn_cycle_num.setFixedHeight(32)
        self.spn_cycle_num.setSpecialValueText("手动停")
        target_grid.addWidget(self.spn_cycle_num, 3, 1)
        target_grid.addWidget(self.chk_reputation_mode, 4, 0, 1, 2)
        target_grid.setColumnStretch(0, 1)
        target_grid.setColumnStretch(1, 1)
        run_lay.addLayout(target_grid)

        challenge_grid = QGridLayout()
        challenge_grid.setVerticalSpacing(6)

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

        self.cmb_cjb_boss = QComboBox()
        self.cmb_cjb_boss.setFixedHeight(34)
        _fill_challenge_combo(self.cmb_cjb_boss, "chuanjiaobao")
        self.cmb_cjb_boss.setVisible(False)
        self.btn_cjb_picker = QPushButton()
        self.btn_cjb_picker.setObjectName("challengePickRow")
        self.btn_cjb_picker.setCursor(Qt.PointingHandCursor)
        self.btn_cjb_picker.clicked.connect(
            lambda: self._open_challenge_picker(self.cmb_cjb_boss, "选择传家宝")
        )
        challenge_grid.addWidget(self.btn_cjb_picker, 0, 0)
        self.cmb_sgzx_boss = QComboBox()
        self.cmb_sgzx_boss.setFixedHeight(34)
        _fill_challenge_combo(self.cmb_sgzx_boss, "boss")
        self.cmb_sgzx_boss.setVisible(False)
        self.btn_boss_picker = QPushButton()
        self.btn_boss_picker.setObjectName("challengePickRow")
        self.btn_boss_picker.setCursor(Qt.PointingHandCursor)
        self.btn_boss_picker.clicked.connect(
            lambda: self._open_challenge_picker(self.cmb_sgzx_boss, "选择 Boss")
        )
        challenge_grid.addWidget(self.btn_boss_picker, 1, 0)
        self.cmb_cjb_boss.currentIndexChanged.connect(self._refresh_challenge_picker_rows)
        self.cmb_sgzx_boss.currentIndexChanged.connect(self._refresh_challenge_picker_rows)
        self._refresh_challenge_picker_rows()
        hint = QLabel("默认选中列表最后一项，可点开更换")
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        hint.setVisible(False)
        challenge_grid.addWidget(hint, 2, 0)
        challenge_host = QWidget()
        challenge_host.setLayout(challenge_grid)

        self.save_settings_host = QWidget()
        save_host_lay = QVBoxLayout(self.save_settings_host)
        save_host_lay.setContentsMargins(0, 0, 0, 0)
        save_host_lay.setSpacing(6)
        lab_hint = QLabel("测试夹 bat 会读这份保存；改动约 1 秒后自动保存。")
        lab_hint.setObjectName("hintLabel")
        lab_hint.setWordWrap(True)
        save_host_lay.addWidget(lab_hint)
        save_row = QHBoxLayout()
        save_row.setSpacing(10)
        self.btn_save_settings = QPushButton("保存设置")
        self.btn_save_settings.setObjectName("btnSaveSettings")
        self.btn_save_settings.setCursor(Qt.PointingHandCursor)
        self.btn_save_settings.clicked.connect(self._on_save_settings_clicked)
        save_row.addWidget(self.btn_save_settings)
        save_row.addStretch()
        save_host_lay.addLayout(save_row)

        core = QWidget()
        core_layout = QVBoxLayout(core)
        core_layout.setContentsMargins(0, 0, 0, 0)
        core_layout.setSpacing(8)

        self.hero_options = QWidget()
        self.hero_options.setVisible(False)
        hero_col = QVBoxLayout(self.hero_options)
        hero_col.setContentsMargins(0, 0, 0, 0)
        hero_col.setSpacing(8)

        self.rep_cards_host = QWidget()
        self.rep_cards_host.setObjectName("reputationCards")
        self.rep_cards_lay = QHBoxLayout(self.rep_cards_host)
        self.rep_cards_lay.setContentsMargins(0, 0, 0, 0)
        self.rep_cards_lay.setSpacing(6)
        hero_col.addWidget(self.rep_cards_host)

        rep_foot = QHBoxLayout()
        rep_foot.setSpacing(6)
        self.lbl_rep_cards_stats = QLabel("总 0 / 8 · 爆率 +0%")
        self.lbl_rep_cards_stats.setObjectName("hintLabel")
        rep_foot.addWidget(self.lbl_rep_cards_stats, 1)
        self.btn_adjust_reputation = QPushButton("调整")
        self.btn_adjust_reputation.setObjectName("reputationAdjust")
        self.btn_adjust_reputation.setFixedHeight(26)
        self.btn_adjust_reputation.clicked.connect(self._toggle_reputation_editor)
        rep_foot.addWidget(self.btn_adjust_reputation)
        hero_col.addLayout(rep_foot)

        self.rep_alloc_editor = QWidget()
        self.rep_alloc_editor.setObjectName("reputationEditor")
        self.rep_alloc_editor.setVisible(False)
        rep_editor_lay = QVBoxLayout(self.rep_alloc_editor)
        rep_editor_lay.setContentsMargins(0, 6, 0, 0)
        rep_editor_lay.setSpacing(8)

        alloc_head = QVBoxLayout()
        alloc_head.setSpacing(8)
        alloc_cap = QLabel("声望点数分配（单阵营上限 10）")
        alloc_cap.setObjectName("sectionCap")
        alloc_head.addWidget(alloc_cap)
        self.lbl_rep_budget = QLabel("可分配共 8 点（已分配 0 点）")
        self.lbl_rep_budget.setObjectName("hintLabel")
        alloc_head.addWidget(self.lbl_rep_budget)
        rep_editor_lay.addLayout(alloc_head)

        self.rep_alloc_spins: dict[int, QSpinBox] = {}
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
                logo.setFixedSize(22, 22)
                logo.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                logo.setPixmap(
                    QPixmap(str(logo_path)).scaled(
                        22, 22, Qt.KeepAspectRatio, Qt.SmoothTransformation
                    )
                )
                logo.setToolTip(FACTION_TIPS.get(fid, name))
                cell_lay.addWidget(logo)
            name_lbl = QLabel(name)
            name_lbl.setFixedWidth(52)
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
            alloc_grid.addWidget(cell, idx, 0)
        alloc_grid.setColumnStretch(0, 1)
        rep_editor_lay.addLayout(alloc_grid)

        hero_meta = QVBoxLayout()
        hero_meta.setSpacing(8)
        rep_fallback_pill = QLabel("今日声望耗尽时自动降级常规模式")
        rep_fallback_pill.setObjectName("versionPill")
        rep_fallback_pill.setWordWrap(True)
        hero_meta.addWidget(rep_fallback_pill)
        hero_hint = QLabel("可用点数随关卡进度增长（1-8 关 8 点 · 封顶 23 点）")
        hero_hint.setObjectName("hintLabel")
        hero_hint.setWordWrap(True)
        hero_meta.addWidget(hero_hint)
        rep_editor_lay.addLayout(hero_meta)

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
        rep_editor_lay.addWidget(self.rep_summary_card)
        hero_col.addWidget(self.rep_alloc_editor)
        core_layout.addWidget(self.hero_options)
        core_layout.addWidget(challenge_host)

        check_row = QVBoxLayout()
        check_row.setSpacing(8)
        self.chk_secret_realm = QCheckBox("自动进秘境（不归秘境未接线）")
        self.chk_secret_realm.setToolTip(
            "不归秘境：第四章起开放，20/25/30 层同战力更高；入口、层数选择和 NPC 锚点尚未验证。"
            "当前开关只控制既有通用秘境入口，默认关闭。"
        )
        self.secret_options = QLabel("已启用已验证入口")
        self.secret_options.setObjectName("hintLabel")
        self.secret_options.setVisible(False)
        self.chk_secret_realm.toggled.connect(self.secret_options.setVisible)

        self.chk_auto_close_main_line = QCheckBox("5-5后取消自动主线挑战")
        self.chk_auto_close_main_line.setToolTip("主线过 5-5 后自动取消自动主线复选框，避免打 5-10 翻车；10分钟直接提前打 Boss")

        self.chk_auto_archaeology = QCheckBox("票刷完自动考古")
        self.chk_auto_archaeology.setToolTip("黄色挑战券清空后自动进入考古模式并结算")

        check_row.addWidget(self.chk_secret_realm)
        check_row.addWidget(self.secret_options)
        check_row.addWidget(self.chk_auto_close_main_line)
        check_row.addWidget(self.chk_auto_archaeology)
        core_layout.addLayout(check_row)

        run_lay.addWidget(core)
        left_rail_lay.addWidget(run_box)
        left_rail_lay.addStretch()

        build_box = QGroupBox("技能搭配")
        build_box.setObjectName("od12FlatSection")
        self.grp_builds = build_box
        build_layout = QVBoxLayout(build_box)
        build_layout.setContentsMargins(10, 10, 10, 8)
        build_layout.setSpacing(8)
        self._build_list = QWidget()
        self._build_list_lay = QVBoxLayout(self._build_list)
        self._build_list_lay.setContentsMargins(0, 0, 0, 0)
        self._build_list_lay.setSpacing(0)
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
        self.skill_priority_bar = SkillPriorityBar()
        self.skill_priority_bar.setVisible(False)
        self.skill_priority_bar.order_changed.connect(self._on_priority_order_changed)
        self.skill_priority_bar.route_changed.connect(self._on_priority_route_changed)
        self.skill_priority_bar.remove_requested.connect(self._on_priority_remove)
        build_layout.addWidget(self.skill_priority_bar)
        right_main_lay.addWidget(build_box)

        # 高级配置（可折叠）
        self.grp_advanced = QGroupBox("低频设置（手动技能 / 存档等级 / 诊断）")
        self.grp_advanced.setObjectName("prototype12AdvancedDrawer")
        self.grp_advanced.setCheckable(True)
        self.grp_advanced.setChecked(False)
        advanced_layout = QVBoxLayout(self.grp_advanced)
        advanced_layout.setContentsMargins(10, 10, 10, 8)
        advanced_layout.setSpacing(12)

        self.advanced_host = QWidget()
        adv_lay = QVBoxLayout(self.advanced_host)
        adv_lay.setContentsMargins(0, 0, 0, 0)
        adv_lay.setSpacing(12)
        adv_lay.addWidget(self.save_settings_host)

        # 房间设置
        room_box = QGroupBox("房间设置（带车沿用）")
        room_box.setObjectName("subGroup")
        self.grp_room_settings = room_box
        self.grp_room_settings.setCheckable(True)
        self.grp_room_settings.setChecked(True)
        room_layout = QVBoxLayout(room_box)
        room_layout.setSpacing(8)
        self.chk_auto_create_room = QCheckBox("自动创建房间")
        room_layout.addWidget(self.chk_auto_create_room)
        room_layout.addWidget(QLabel("房间名称"))
        self.txt_room_name = QLineEdit()
        self.txt_room_name.setPlaceholderText("留空使用默认")
        room_layout.addWidget(self.txt_room_name)
        room_layout.addWidget(QLabel("房间密码"))
        self.txt_room_password = QLineEdit()
        self.txt_room_password.setEchoMode(QLineEdit.Password)
        self.txt_room_password.setPlaceholderText("无密码")
        room_layout.addWidget(self.txt_room_password)
        self.cmb_room_reuse = QComboBox()
        self.cmb_room_reuse.addItem("复用原房间", False)
        self.cmb_room_reuse.addItem("每局新建房间", True)
        room_layout.addWidget(self.cmb_room_reuse)
        lead_cycle_hint = QLabel("带车目标局数：使用上方目标局数")
        lead_cycle_hint.setObjectName("hintLabel")
        lead_cycle_hint.setWordWrap(True)
        room_layout.addWidget(lead_cycle_hint)
        room_box.toggled.connect(lambda expanded: [child.setVisible(expanded) for child in room_box.findChildren(QWidget) if child is not room_box])
        left_rail_lay.insertWidget(max(0, left_rail_lay.count() - 1), room_box)

        custom_lay = self.custom_editor.layout()
        self.grp_skill = QGroupBox("技能选择")
        self.grp_skill.setObjectName("subGroup")
        self.grp_skill.setCheckable(True)
        self.grp_skill.setChecked(False)
        sl = QVBoxLayout(self.grp_skill)
        sl.setContentsMargins(2, 6, 2, 2)
        self.skill_grid = SkillCardGrid(SKILL_STEMS, SKILL_LABELS)
        sl.addWidget(self.skill_grid)
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

        self.grp_bond_basic = QGroupBox("羁绊配置")
        self.grp_bond_basic.setObjectName("od12FlatSection")
        self.grp_bond_basic.setCheckable(False)
        self.bond_editor = self.grp_bond_basic
        bond_lay = QVBoxLayout(self.grp_bond_basic)
        bond_lay.setContentsMargins(8, 10, 8, 8)
        bond_lay.setSpacing(8)
        route_row = QHBoxLayout()
        route_row.setSpacing(6)
        attr_cap = QLabel("属性")
        attr_cap.setObjectName("bondCaption")
        route_row.addWidget(attr_cap)
        self.route_buttons: dict[str, QCheckBox] = {}
        for row_opt in ATTR_LINE_OPTIONS:
            rid = str(row_opt.get("id") or "")
            btn = QCheckBox(str(row_opt.get("label") or rid))
            btn.setObjectName("bondChip")
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

        bond_lay.addWidget(self.bond_plan_host)
        self.bond_plan_host.setVisible(True)
        # 20260822 实机反馈：羁绊自选此前挂在「自定义卡组」编辑器里，选了
        # 推荐方案后整个编辑器隐藏 → 用户看不到也无法改羁绊（经济等基础
        # 系全被刷新掉）。羁绊选择是推荐方案之上的人工裁决层，移到主页面
        # 常显（推荐方案只提供默认勾选，不锁死）。
        right_main_lay.addWidget(self.grp_bond_basic)

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
        right_main_lay.addWidget(self.grp_advanced)
        right_main_lay.addStretch()
        self.launch_check = self._build_launch_check()
        self.dashboard_grid.addWidget(left_rail, 0, 0)
        self.dashboard_grid.addWidget(right_main, 0, 1)
        self.dashboard_grid.addWidget(self.launch_check, 0, 2, Qt.AlignTop)
        self.dashboard_grid.setColumnStretch(0, 0)
        self.dashboard_grid.setColumnStretch(1, 1)
        self.dashboard_grid.setColumnStretch(2, 0)
        lay.addWidget(self.dashboard_shell)
        self._update_hero_visibility()

    def _build_launch_check(self) -> LaunchCheckPanel:
        """启动前核对窄栏：只投影现有控件与 lbl_precheck 结论，不自行判定能否启动。"""
        return LaunchCheckPanel()

    def _refresh_launch_check(self) -> None:
        if not hasattr(self, "launch_check"):
            return
        spec = get_spec(self.selected_mode_id())
        hero = bool(getattr(self, "cmb_mode", None) and self.cmb_mode.currentData())
        strategy = "声望挑战" if hero else "自动推进"
        if getattr(self, "chk_secret_realm", None) and self.chk_secret_realm.isChecked():
            strategy = "自动秘境"
        lines = [
            "启动前核对",
            f"{self.lbl_precheck.text()}（{self.lbl_precheck.toolTip()}）",
            "运行方式",
            f"{self.selected_mode_label()} · {strategy}",
        ]
        if hasattr(self, "txt_stage_target"):
            stage = self.txt_stage_target.text().strip() or "-"
            diff = "英雄" if hero else "普通"
            cycle = int(self.spn_cycle_num.value())
            cycle_text = "手动停" if cycle <= 0 else f"{cycle} 局"
            skill_codes = (
                self.skill_priority_bar.order()
                if hasattr(self, "skill_priority_bar") and self.skill_priority_bar.order()
                else self.skill_grid.get_skills()
            )
            names = [skill_display_name(code) for code in skill_codes]
            bonds = [bond_display_name(code) for code in self.effective_bond_codes()]
            detail_settings = []
            if self.chk_secret_realm.isChecked():
                detail_settings.append("自动秘境")
            if self.chk_auto_close_main_line.isChecked():
                detail_settings.append("5-5 后取消自动主线")
            if self.chk_auto_archaeology.isChecked():
                detail_settings.append("票尽后自动考古")
            if self.chk_auto_create_room.isChecked():
                room_name = self.txt_room_name.text().strip() or "默认房名"
                detail_settings.append(f"自动建房：{room_name}")
            advanced = [
                str(ADVANCED_PACKS[pack_id].get("label") or pack_id)
                for pack_id in (self._shell_extras.get("advanced_packs") or [])
                if pack_id in ADVANCED_PACKS
            ]
            cards = len(self.assemble_whitelist_cards())
            lines.extend(
                [
                    "目标关卡",
                    f"{stage} · {diff} · {cycle_text}",
                    "已选技能",
                    "/".join(names) if names else "未选（不自动学习）",
                    "声望挑战",
                    (
                        f"已分配 {sum(self._rep_allocations().values())}/{self._rep_available_points()} 点"
                        if hero
                        else "不适用（普通模式）"
                    ),
                    "传家宝 / Boss",
                    f"{self.cmb_cjb_boss.currentText()} · {self.cmb_sgzx_boss.currentText()}",
                    "细节设置",
                    "、".join(detail_settings) if detail_settings else "无额外自动项",
                    "基础卡组",
                    "羁绊：" + ("、".join(bonds) if bonds else "未勾选"),
                    "高级卡组",
                    ("、".join(advanced) if advanced else "未启用") + f" · 共 {cards} 项白名单",
                ]
            )
        self.launch_check.set_skill_codes(
            self.skill_priority_bar.order()
            if hasattr(self, "skill_priority_bar") and self.skill_priority_bar.order()
            else self.skill_grid.get_skills()
        )
        self.launch_check.setText("\n".join(lines))
        action_labels = {"solo": "去单人刷票", "arch": "去考古", "hitch": "转为大厅蹭车"}
        for mode_id, check in getattr(self, "team_launch_checks", {}).items():
            if mode_id == "follow_team":
                cycle = int(self.spn_follow_cycle_num.value())
                action = action_labels.get(str(self.cmb_follow_after_room.currentData()), "去单人刷票")
                extra = self.txt_follow_pair_code.text().strip() or "未填写（同步待接线）"
                trigger = "房间解散 / 被踢出后"
                extra_label = "带车端配对"
            else:
                cycle = int(self.spn_hitch_cycle_num.value())
                action = action_labels.get(str(self.cmb_hitch_after_goal.currentData()), "去单人刷票")
                extra = f"搜索 {self.cmb_hitch_prefix.currentData() or '3'}"
                trigger = "达到蹭车目标后"
                extra_label = "找房条件"
            cycle_text = "手动停" if cycle <= 0 else f"{cycle} 局"
            ready = "可启动" if desktop_may_start(mode_id) else "待验证 · 不可启动"
            check.setText("\n".join((
                "启动前核对",
                ready,
                "运行方式",
                get_spec(mode_id).label,
                "目标局数",
                cycle_text,
                trigger,
                action,
                extra_label,
                extra,
                "执行边界",
                "结束切换待接线",
            )))

    def _set_team_pages_compact(self, compact: bool) -> None:
        for mode_id, grid in getattr(self, "team_page_grids", {}).items():
            main = self.team_page_mains[mode_id]
            check = self.team_launch_checks[mode_id]
            grid.removeWidget(main)
            grid.removeWidget(check)
            grid.addWidget(main, 0, 0)
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 0)
            main.setVisible(True)
            check.setVisible(False)

    def _set_dashboard_compact(self, compact: bool) -> None:
        """宽窗三列 / 窄于 920px 纵向堆叠；三段始终可见，不水平裁剪。"""
        compact = bool(compact)
        self._set_team_pages_compact(compact)
        if not hasattr(self, "dashboard_grid") or compact == getattr(self, "dashboard_compact", False):
            return
        self.dashboard_compact = compact
        grid = self.dashboard_grid
        rail = getattr(self, "left_rail")
        main_w = getattr(self, "right_main")
        check = getattr(self, "launch_check")
        for widget in (rail, main_w, check):
            grid.removeWidget(widget)
        if compact:
            rail.setMinimumWidth(0)
            rail.setMaximumWidth(16777215)
            rail.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            check.setMinimumWidth(0)
            check.setMaximumWidth(16777215)
            check.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            grid.addWidget(rail, 0, 0)
            grid.addWidget(main_w, 1, 0)
            grid.addWidget(check, 2, 0)
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 0)
            grid.setColumnStretch(2, 0)
        else:
            rail.setFixedWidth(204)
            rail.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
            check.setFixedWidth(196)
            check.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
            grid.addWidget(rail, 0, 0)
            grid.addWidget(main_w, 0, 1)
            grid.addWidget(check, 0, 2, Qt.AlignTop)
            grid.setColumnStretch(0, 0)
            grid.setColumnStretch(1, 1)
            grid.setColumnStretch(2, 0)
        for widget in (rail, main_w, check):
            widget.setVisible(True)

    def _toggle_more_settings(self) -> None:
        self.grp_advanced.setChecked(not self.grp_advanced.isChecked())

    @staticmethod
    def _subscription_expiry_text(value: object) -> str:
        raw = str(value or "").strip()
        return raw.replace("T", " ").replace("Z", " UTC") if raw else ""

    def _refresh_subscription_display(self) -> None:
        if not hasattr(self, "lbl_subscription"):
            return
        status = str(getattr(self, "_subscription_status", "未激活") or "未激活")
        expiry = self._subscription_expiry_text(getattr(self, "_subscription_expires_at", ""))
        self.lbl_subscription.setText(f"订阅：{status}" + (f" · 到期 {expiry}" if expiry else ""))

    def _on_activate_subscription_clicked(self) -> None:
        key, accepted = QInputDialog.getText(
            self, "激活订阅密钥", "请输入 License Key：", QLineEdit.EchoMode.Password, self._subscription_key
        )
        if not accepted:
            return
        key = key.strip()
        self._subscription_status = "校验中"
        self._subscription_expires_at = ""
        self._refresh_subscription_display()
        env = dict(os.environ)
        env["SHUABAO_SUBSCRIPTION_MODE"] = "enforce"
        payload = validate_entitlement(key, env=env)
        allowed = bool(payload.get("valid")) and payload.get("can_start_runner") is True
        status = str(payload.get("status") or "UNKNOWN")
        if allowed:
            self._subscription_key = key
            os.environ[SUBSCRIPTION_LICENSE_KEY_ENV] = key
            self._subscription_status = status
            license_payload = payload.get("license") if isinstance(payload.get("license"), dict) else {}
            self._subscription_expires_at = str(payload.get("expires_at") or license_payload.get("expires_at") or "")
            self._refresh_subscription_display()
            self.log(f"[订阅] 已激活，状态 {status}，到期 {self._subscription_expiry_text(self._subscription_expires_at) or '未返回'}")
            QMessageBox.information(self, "订阅已激活", self.lbl_subscription.text())
            return
        self._subscription_status = status if status != "UNKNOWN" else "校验失败"
        self._refresh_subscription_display()
        QMessageBox.warning(self, "订阅激活失败", str(payload.get("message") or f"订阅状态不允许启动：{status}"))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            overlay = getattr(self, "inline_overlay", None)
            if overlay is not None and overlay.isVisible():
                overlay.dismiss()
                event.accept()
                return
            bar = getattr(self, "skill_priority_bar", None)
            if bar is not None and bar.route_expanded():
                bar.collapse_route_panel()
                event.accept()
                return
            if getattr(self, "grp_advanced", None) is not None and self.grp_advanced.isChecked():
                self._toggle_more_settings()
                event.accept()
                return
        super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "dashboard_grid") and getattr(self, "_window_role", "") != "chooser":
            self._set_dashboard_compact(self.width() < 920)
        overlay = getattr(self, "inline_overlay", None)
        if overlay is not None and overlay.isVisible():
            overlay.reposition()

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
        if not isinstance(raw, list):
            raw = []
            self._shell_extras["custom_builds"] = raw
        return raw

    def _rebuild_build_picker(self) -> None:
        lay = self._build_list_lay
        while lay.count():
            item = lay.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
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
            add_btn = QPushButton("自定义")
            add_btn.setObjectName("buildAddCustom")
            add_btn.setFixedHeight(34)
            add_btn.setCursor(Qt.PointingHandCursor)
            add_btn.clicked.connect(self._add_custom_build)
            lay.addWidget(add_btn)

    def _make_build_row(
        self, build_id: str, title: str, skills: list[str], *, deletable: bool = False
    ) -> QPushButton:
        btn = QPushButton()
        btn.setObjectName("officialBuildRow")
        btn.setCheckable(True)
        btn.setChecked(build_id == str(self._shell_extras.get("selected_build_id") or ""))
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(official_build_qss(getattr(self, "current_theme", "light")))
        btn.setFixedHeight(38)
        row = QHBoxLayout(btn)
        row.setContentsMargins(8, 4, 8, 4)
        row.setSpacing(8)

        name = QLabel(title)
        name.setObjectName("buildTitle")
        name.setFixedWidth(88)
        name.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        row.addWidget(name)

        codes = list(skills[:4])
        while len(codes) < 4:
            codes.append("")
        for code in codes:
            icon = QLabel()
            icon.setObjectName("buildSkillIcon" if code else "buildSlot")
            icon.setFixedSize(22, 22)
            icon.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            if code:
                path = SKILL_ICON_DIR / f"{code}.png"
                if path.is_file():
                    icon.setPixmap(QPixmap(str(path)).scaled(
                        22, 22, Qt.KeepAspectRatio, Qt.SmoothTransformation
                    ))
                icon.setToolTip(skill_display_name(code))
            row.addWidget(icon)
        row.addStretch()

        if deletable:
            del_btn = QPushButton("删除")
            del_btn.setObjectName("buildDelete")
            del_btn.setCursor(Qt.PointingHandCursor)
            del_btn.setFixedHeight(24)
            del_btn.setToolTip("删除该自定义流派")
            del_btn.clicked.connect(lambda _=False, bid=build_id: self._delete_custom_build(bid))
            row.addWidget(del_btn)
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
            if hasattr(self, "grp_skill"):
                self.grp_skill.setChecked(True)
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
        build_id = f"custom:{nxt}"
        items.append({"id": build_id, "name": f"自定义 {nxt}", "skills": []})
        self._shell_extras["custom_builds"] = items
        self._select_build(build_id)
        if hasattr(self, "grp_skill"):
            self.grp_skill.setChecked(True)

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
        page = self._team_page_shell(lay, "follow_team")
        head = QHBoxLayout()
        title = QLabel("组队 · 跟车")
        title.setObjectName("teamPageTitle")
        head.addWidget(title)
        badge = QLabel("可启动" if desktop_may_start("follow_team") else "待验证 · 不可启动")
        badge.setObjectName("teamStatusPill")
        head.addWidget(badge)
        head.addStretch()
        page.addLayout(head)
        intro = QLabel("已在房间自动准备；房间解散或被踢出后按预案切换。")
        intro.setObjectName("teamPageIntro")
        page.addWidget(intro)

        box = QFrame()
        box.setObjectName("teamRulesPanel")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(16, 14, 16, 14)
        bl.setSpacing(14)
        rules_head = QHBoxLayout()
        rules_title = QLabel("跟车结束规则")
        rules_title.setObjectName("teamRulesTitle")
        rules_head.addWidget(rules_title)
        rules_head.addStretch()
        saved = QLabel("仅保存配置")
        saved.setObjectName("teamRulesState")
        rules_head.addWidget(saved)
        bl.addLayout(rules_head)

        form = QGridLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)
        form.addWidget(QLabel("目标游戏局数"), 0, 0)
        form.addWidget(QLabel("房间解散 / 被踢出后"), 0, 1)
        self.spn_follow_cycle_num = QSpinBox()
        self.spn_follow_cycle_num.setRange(0, 999)
        self.spn_follow_cycle_num.setSpecialValueText("手动停")
        self.spn_follow_cycle_num.setFixedHeight(40)
        form.addWidget(self.spn_follow_cycle_num, 1, 0)
        self.cmb_follow_after_room = QComboBox()
        self.cmb_follow_after_room.setFixedHeight(40)
        self.cmb_follow_after_room.addItem("去单人刷票", "solo")
        self.cmb_follow_after_room.addItem("去考古", "arch")
        self.cmb_follow_after_room.addItem("转为大厅蹭车", "hitch")
        form.addWidget(self.cmb_follow_after_room, 1, 1)
        form.setColumnStretch(0, 1)
        form.setColumnStretch(1, 1)
        bl.addLayout(form)

        route = QFrame()
        route.setObjectName("teamRoute")
        route_lay = QHBoxLayout(route)
        route_lay.setContentsMargins(0, 0, 0, 0)
        route_lay.setSpacing(0)
        for index, text in enumerate(("对齐带车端", "同步准备与目标局数", "房间结束后切换"), 1):
            step = QLabel(f"{index:02d}\n{text}")
            step.setObjectName("teamRouteStep")
            step.setWordWrap(True)
            step.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            route_lay.addWidget(step, 1)
        bl.addWidget(route)

        pair = QFrame()
        pair.setObjectName("teamPairPanel")
        pair_lay = QGridLayout(pair)
        pair_lay.setContentsMargins(12, 10, 12, 10)
        pair_lay.setHorizontalSpacing(12)
        pair_title = QLabel("带车端配对")
        pair_title.setObjectName("teamPairTitle")
        pair_lay.addWidget(pair_title, 0, 0)
        pair_note = QLabel("两台脚本填写同一配对信息；同步接口待接线。")
        pair_note.setObjectName("hintLabel")
        pair_note.setWordWrap(True)
        pair_lay.addWidget(pair_note, 1, 0)
        self.txt_follow_pair_code = QLineEdit()
        self.txt_follow_pair_code.setMaxLength(24)
        self.txt_follow_pair_code.setPlaceholderText("输入配对码或角色名")
        self.txt_follow_pair_code.setFixedHeight(40)
        pair_lay.addWidget(self.txt_follow_pair_code, 0, 1, 2, 1)
        pair_lay.setColumnStretch(0, 1)
        pair_lay.setColumnStretch(1, 1)
        bl.addWidget(pair)

        boundary = QLabel("当前执行边界　自动准备与目标局数已接入；配对同步和结束后的模式切换待接线。")
        boundary.setObjectName("warnHint")
        boundary.setWordWrap(True)
        bl.addWidget(boundary)
        safety = QLabel(
            "操作边界　只认 准备 / 已准备 / 取消准备，无「锁定」按钮；"
            "F1 = 操作切回自身英雄，F2 = 回基地，F12 / Shift+F12 = 停止。"
        )
        safety.setObjectName("teamSafetyHint")
        safety.setWordWrap(True)
        bl.addWidget(safety)
        page.addWidget(box)
        switch = QPushButton("改为大厅蹭车")
        switch.setObjectName("teamSecondaryAction")
        switch.setCursor(Qt.PointingHandCursor)
        switch.clicked.connect(lambda: self._select_mode("lobby_hitch"))
        page.addWidget(switch, 0, Qt.AlignLeft)

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
        page = self._team_page_shell(lay, "lobby_hitch")
        head = QHBoxLayout()
        title = QLabel("组队 · 蹭车")
        title.setObjectName("teamPageTitle")
        head.addWidget(title)
        badge = QLabel(badge_text(get_spec("lobby_hitch")))
        badge.setObjectName("teamStatusPill")
        head.addWidget(badge)
        head.addStretch()
        page.addLayout(head)
        intro = QLabel("自动在大厅找房；达到蹭车目标后按预案切换任务。")
        intro.setObjectName("teamPageIntro")
        page.addWidget(intro)

        box = QFrame()
        box.setObjectName("teamRulesPanel")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(16, 14, 16, 14)
        bl.setSpacing(14)
        rules_head = QHBoxLayout()
        rules_title = QLabel("蹭车结束规则")
        rules_title.setObjectName("teamRulesTitle")
        rules_head.addWidget(rules_title)
        rules_head.addStretch()
        saved = QLabel("仅保存配置")
        saved.setObjectName("teamRulesState")
        rules_head.addWidget(saved)
        bl.addLayout(rules_head)

        form = QGridLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)
        form.addWidget(QLabel("目标游戏局数"), 0, 0)
        form.addWidget(QLabel("目标结束后"), 0, 1)
        self.spn_hitch_cycle_num = QSpinBox()
        self.spn_hitch_cycle_num.setRange(0, 999)
        self.spn_hitch_cycle_num.setSpecialValueText("手动停")
        self.spn_hitch_cycle_num.setFixedHeight(40)
        form.addWidget(self.spn_hitch_cycle_num, 1, 0)
        self.cmb_hitch_after_goal = QComboBox()
        self.cmb_hitch_after_goal.setFixedHeight(40)
        self.cmb_hitch_after_goal.addItem("去单人刷票", "solo")
        self.cmb_hitch_after_goal.addItem("去考古", "arch")
        form.addWidget(self.cmb_hitch_after_goal, 1, 1)
        form.setColumnStretch(0, 1)
        form.setColumnStretch(1, 1)
        bl.addLayout(form)

        search_row = QHBoxLayout()
        search_label = QLabel("找房条件")
        search_label.setObjectName("teamPairTitle")
        search_row.addWidget(search_label)
        self.cmb_hitch_prefix = QComboBox()
        self.cmb_hitch_prefix.setFixedHeight(36)
        self.cmb_hitch_prefix.addItem("搜索 3", "3")
        self.cmb_hitch_prefix.addItem("搜索 4", "4")
        self.cmb_hitch_prefix.setMaximumWidth(180)
        search_row.addWidget(self.cmb_hitch_prefix)
        search_row.addStretch()
        bl.addLayout(search_row)
        self.txt_hitch_exact = QLineEdit()
        self.txt_hitch_exact.setPlaceholderText("后续拓展")
        self.txt_hitch_exact.setEnabled(False)
        self.txt_hitch_exact.setVisible(False)

        route = QFrame()
        route.setObjectName("teamRoute")
        route_lay = QHBoxLayout(route)
        route_lay.setContentsMargins(0, 0, 0, 0)
        route_lay.setSpacing(0)
        for index, text in enumerate(("大厅自动找房", "入房后自动准备", "完成目标后切换"), 1):
            step = QLabel(f"{index:02d}\n{text}")
            step.setObjectName("teamRouteStep")
            step.setWordWrap(True)
            step.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            route_lay.addWidget(step, 1)
        bl.addWidget(route)

        boundary = QLabel("当前执行边界　大厅搜房、进房等待与目标局数已接入；目标完成后的任务切换待接线。")
        boundary.setObjectName("warnHint")
        boundary.setWordWrap(True)
        bl.addWidget(boundary)
        safety = QLabel(
            "操作边界　只认 准备 / 已准备 / 取消准备，无「锁定」按钮；"
            "F1 = 操作切回自身英雄，F2 = 回基地，F12 / Shift+F12 = 停止。"
        )
        safety.setObjectName("teamSafetyHint")
        safety.setWordWrap(True)
        bl.addWidget(safety)
        page.addWidget(box)
        switch = QPushButton("已经在房间里，改为跟车")
        switch.setObjectName("teamSecondaryAction")
        switch.setCursor(Qt.PointingHandCursor)
        switch.clicked.connect(lambda: self._select_mode("follow_team"))
        page.addWidget(switch, 0, Qt.AlignLeft)

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
                widget.setParent(None)
                widget.deleteLater()
        self._bond_plan_boxes = {}
        self._advanced_pack_boxes = {}
        has_scheme = "bond_scheme" in self._shell_extras
        inverted = set(self._shell_extras.get("bond_inverted") or [])
        scheme = set(self._effective_scheme_codes())

        custom_bonds = [str(x) for x in (self._shell_extras.get("custom_bonds") or []) if str(x).strip()]
        development = [name for name in BASIC_PACK_UI_NAMES if name in ("成长", "经济", "贪婪", "挑战")]
        basic = [name for name in BASIC_PACK_UI_NAMES if name not in development]

        def add_pack_group(caption: str, names: list[str]) -> None:
            cap = QLabel(caption)
            cap.setObjectName("bondCaption")
            self.bond_plan_lay.addWidget(cap)
            row = QWidget()
            flow = QHBoxLayout(row)
            flow.setContentsMargins(0, 0, 0, 0)
            flow.setSpacing(6)
            for name in names:
                code = code_for_bond_name(str(name)) or str(name)
                box = QCheckBox(str(name))
                box.setObjectName("bondChip")
                if has_scheme:
                    box.setChecked(code in scheme and code not in inverted)
                else:
                    box.setChecked(code in DEFAULT_BOND_CODES and code not in inverted)
                box.toggled.connect(lambda checked, c=code: self._on_plan_toggled(c, checked))
                self._bond_plan_boxes[code] = box
                flow.addWidget(box)
            flow.addStretch()
            self.bond_plan_lay.addWidget(row)

        add_pack_group("发育卡组", development)
        add_pack_group("基础卡组", [*basic, *custom_bonds])

        adv_cap = QLabel("高级卡组候选")
        adv_cap.setObjectName("bondCaption")
        self.bond_plan_lay.addWidget(adv_cap)
        adv_row = QHBoxLayout()
        adv_row.setSpacing(6)
        enabled = set(self._shell_extras.get("advanced_packs") or [])
        for pack_id, spec in ADVANCED_PACKS.items():
            box = QCheckBox(str(spec.get("label") or pack_id))
            box.setObjectName("bondChip")
            box.setChecked(pack_id in enabled)
            box.setToolTip("、".join(str(n) for n in (spec.get("cards") or [])))
            box.toggled.connect(lambda checked, pid=pack_id: self._on_advanced_pack_toggled(pid, checked))
            self._advanced_pack_boxes[pack_id] = box
            adv_row.addWidget(box)
        adv_row.addStretch()
        adv_host = QWidget()
        adv_host.setLayout(adv_row)
        self.bond_plan_lay.addWidget(adv_host)

        tools = QHBoxLayout()
        tools.setSpacing(6)
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
        tools_host.setObjectName("bondLowFrequencyTools")
        tools_host.setLayout(tools)
        tools_host.setVisible(False)
        self.bond_plan_lay.addWidget(tools_host)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        note = QLabel("可选多套，确认后排序")
        note.setObjectName("hintLabel")
        actions.addWidget(note, 1)
        confirm = QPushButton("确认选择")
        confirm.setObjectName("bondConfirm")
        confirm.setFixedHeight(32)
        confirm.clicked.connect(self._on_save_settings_clicked)
        actions.addWidget(confirm)
        actions_host = QWidget()
        actions_host.setLayout(actions)
        self.bond_plan_lay.addWidget(actions_host)

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
        self._refresh_launch_check()
        self._schedule_auto_save()

    def _on_attr_route_clicked(self) -> None:
        self._shell_extras["attr_route"] = [rid for rid, btn in self.route_buttons.items() if btn.isChecked()]
        self._schedule_auto_save()
        self._refresh_launch_check()

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
        self._refresh_launch_check()
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
        self._refresh_launch_check()
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
        self._refresh_launch_check()
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
        self._refresh_launch_check()
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
        enabled = [str(x) for x in (self._shell_extras.get("advanced_packs") or []) if str(x)]
        banned = {"解放的圣剑", "帝炎", "法天象地"}
        tokens_list: list[str] = []
        for pack_id in enabled:
            spec = ADVANCED_PACKS.get(pack_id) or {}
            banned.update(str(n) for n in (spec.get("exclude_ex") or []))
            for name in spec.get("cards") or []:
                text = str(name).strip()
                if not text or text in banned:
                    continue
                token = code_for_bond_name(text) or text
                if token not in tokens_list:
                    tokens_list.append(token)
        return tokens_list

    def _bond_codes_from_names(self, items) -> list[str]:
        out: list[str] = []
        for item in items or ():
            text = Path(str(item or "").strip()).stem
            if not text:
                continue
            code = code_for_bond_name(text) or text
            if code not in out:
                out.append(code)
        return out

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
        # Keep extras that live only in settings.cards (法术/暴击/魔能).
        # Do not re-inject a stale _shell.bond_scheme (that is how 箭术 leaked).
        for code in self._bond_codes_from_names(getattr(self.settings, "cards", None) or ()):
            if code in out or code in inverted:
                continue
            box = self._bond_plan_boxes.get(code)
            if box is not None and not box.isChecked():
                continue
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

    def _refresh_challenge_picker_rows(self, _index: int | None = None) -> None:
        if hasattr(self, "btn_cjb_picker"):
            name = self.cmb_cjb_boss.currentText() or "未选择"
            self.btn_cjb_picker.setText(f"传家宝 · {name}")
            self.btn_cjb_picker.setToolTip(f"当前传家宝：{name}。点击选择")
        if hasattr(self, "btn_boss_picker"):
            name = self.cmb_sgzx_boss.currentText() or "未选择"
            self.btn_boss_picker.setText(f"Boss · {name}")
            self.btn_boss_picker.setToolTip(f"当前 Boss：{name}。点击选择")

    def _refresh_stage_picker_rows(self, _index: int | None = None) -> None:
        if hasattr(self, "btn_chapter_picker"):
            name = self.cmb_chapter.currentText() or "选择篇章"
            self.btn_chapter_picker.setText(name)
            self.btn_chapter_picker.setToolTip(f"当前篇章：{name}")
        if hasattr(self, "btn_stage_picker"):
            chapter = int(self.cmb_chapter.currentData() or 1)
            stage = int(self.cmb_stage.currentData() or 1)
            label = f"{chapter}-{stage}"
            self.btn_stage_picker.setText(label)
            self.btn_stage_picker.setToolTip(f"当前关卡：{label}")

    def _overlay_is_for(self, trigger: QWidget) -> bool:
        overlay = getattr(self, "inline_overlay", None)
        return overlay is not None and overlay.isVisible() and overlay.trigger() is trigger

    def _open_choice_overlay(
        self,
        trigger: QWidget,
        title: str,
        rows: list[dict],
        on_pick,
        *,
        columns: int = 1,
    ) -> None:
        overlay = getattr(self, "inline_overlay", None)
        if overlay is None:
            return
        if self._overlay_is_for(trigger):
            overlay.dismiss()
            return
        body = QWidget()
        if columns > 1:
            layout = QGridLayout(body)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(6)
            for index, row in enumerate(rows):
                layout.addWidget(self._overlay_choice_button(row, on_pick), index // columns, index % columns)
        else:
            layout = QVBoxLayout(body)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(2)
            for row in rows:
                layout.addWidget(self._overlay_choice_button(row, on_pick))
            layout.addStretch()
        overlay.present(trigger, title, body)

    def _overlay_choice_button(self, row: dict, on_pick) -> QPushButton:
        button = QPushButton(str(row.get("label") or ""))
        button.setObjectName("inlineOverlayChoice")
        button.setCursor(Qt.PointingHandCursor)
        button.setCheckable(True)
        button.setChecked(bool(row.get("current")))
        icon = row.get("icon")
        if icon is not None and not icon.isNull():
            button.setIcon(icon)
            button.setIconSize(QSize(44, 44))
        disabled = bool(row.get("disabled"))
        button.setEnabled(not disabled)
        reason = str(row.get("reason") or "")
        if disabled and reason:
            button.setToolTip(reason)
        elif reason:
            button.setToolTip(reason)
        value = row.get("value")
        button.clicked.connect(lambda _=False, picked=value: on_pick(picked))
        return button

    def _open_chapter_overlay(self) -> None:
        rows = []
        current = self.cmb_chapter.currentData()
        for index in range(self.cmb_chapter.count()):
            value = self.cmb_chapter.itemData(index)
            rows.append({
                "label": self.cmb_chapter.itemText(index),
                "value": index,
                "current": value == current,
            })
        self._open_choice_overlay(
            self.btn_chapter_picker,
            "选择篇章",
            rows,
            lambda index: self._apply_combo_index(self.cmb_chapter, index),
        )

    def _open_stage_overlay(self) -> None:
        rows = []
        chapter = int(self.cmb_chapter.currentData() or 1)
        current = self.cmb_stage.currentData()
        for index in range(self.cmb_stage.count()):
            stage = int(self.cmb_stage.itemData(index) or index + 1)
            rows.append({
                "label": f"{chapter}-{stage}",
                "value": index,
                "current": stage == current,
            })
        self._open_choice_overlay(
            self.btn_stage_picker,
            "选择关卡",
            rows,
            lambda index: self._apply_combo_index(self.cmb_stage, index),
        )

    def _apply_combo_index(self, combo: QComboBox, index: int) -> None:
        if 0 <= int(index) < combo.count():
            combo.setCurrentIndex(int(index))
        if getattr(self, "inline_overlay", None) is not None:
            self.inline_overlay.dismiss()

    def _open_challenge_picker(self, combo: QComboBox, title: str) -> None:
        trigger = self.btn_cjb_picker if combo is self.cmb_cjb_boss else self.btn_boss_picker
        rows = []
        current = combo.currentIndex()
        for index in range(combo.count()):
            rows.append({
                "label": combo.itemText(index),
                "value": index,
                "icon": combo.itemIcon(index),
                "current": index == current,
            })
        columns = 6 if self.width() >= 920 else 4
        self._open_choice_overlay(
            trigger,
            title,
            rows,
            lambda index: self._apply_combo_index(combo, index),
            columns=columns,
        )

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

    def selected_mode_variant(self) -> str:
        stored = str(self._shell_extras.get("selected_mode_variant") or "")
        if stored in {"solo", "lead", "follow", "hitch"}:
            return stored
        mode_id = self.selected_mode_id()
        if mode_id == "follow_team":
            return "follow"
        if mode_id == "lobby_hitch":
            return "hitch"
        return "solo"

    def selected_mode_label(self) -> str:
        if self.selected_mode_variant() == "lead":
            return "组队 · 带车"
        return get_spec(self.selected_mode_id()).label

    def selected_hud_mode_label(self) -> str:
        """Return the full runtime mode name used by the external HUD."""
        return {
            "solo": "单人模式",
            "lead": "组队带车模式",
            "follow": "组队跟车模式",
            "hitch": "组队蹭车模式",
        }[self.selected_mode_variant()]

    def _select_mode(self, mode_id: str) -> None:
        requested = str(mode_id or "normal_farm")
        if requested in {"lead", "lead_team"}:
            actual_mode_id = "normal_farm"
            variant = "lead"
        elif requested == "follow_team":
            actual_mode_id = requested
            variant = "follow"
        elif requested == "lobby_hitch":
            actual_mode_id = requested
            variant = "hitch"
        else:
            actual_mode_id = requested
            variant = "solo"
        if actual_mode_id not in self._page_index:
            return
        self._selected_mode_id = actual_mode_id
        self._shell_extras["selected_mode_id"] = actual_mode_id
        self._shell_extras["selected_mode_variant"] = variant
        idx = self._page_index.get(actual_mode_id, 0)
        self.right_stack.setCurrentIndex(idx)
        controls = (self.btn_solo_mode, self.btn_lead_mode, self.btn_follow_mode, self.btn_hitch_mode)
        for control in controls:
            control.blockSignals(True)
        try:
            self.btn_solo_mode.setChecked(variant == "solo")
            self.btn_lead_mode.setChecked(variant == "lead")
            self.btn_follow_mode.setChecked(variant == "follow")
            self.btn_hitch_mode.setChecked(variant == "hitch")
        finally:
            for control in controls:
                control.blockSignals(False)
        if variant in {"lead", "follow", "hitch"}:
            self.btn_seg_team.setChecked(True)
        else:
            self.btn_seg_solo.setChecked(True)
        if hasattr(self, "grp_room_settings"):
            self.grp_room_settings.setVisible(variant == "lead")
        if variant == "lead" and hasattr(self, "chk_auto_create_room"):
            self.chk_auto_create_room.setChecked(True)
        self.mode_box.setVisible(False)
        self.right_stack.setVisible(True)
        self.footer.setVisible(True)
        self._apply_window_role("dashboard")
        self._refresh_chrome()
        self._animate_scene_in(self.right_stack)

    def _show_mode_choice(self) -> None:
        self.mode_box.setVisible(True)
        self.right_stack.setVisible(False)
        self.footer.setVisible(False)
        for control in (self.btn_solo_mode, self.btn_lead_mode, self.btn_follow_mode, self.btn_hitch_mode):
            control.setEnabled(True)
        self._apply_window_role("chooser")
        self._refresh_chrome()
        self._animate_scene_in(self.mode_box)

    def eventFilter(self, obj, event):
        """无边框窗口：按住头部空白区拖动（走系统移动，保留贴边分屏）。"""
        if obj is getattr(self, "_header_frame", None):
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                handle = self.windowHandle()
                if handle is not None and handle.startSystemMove():
                    return True
        return super().eventFilter(obj, event)

    def _apply_window_role(self, role: str) -> None:
        previous_role = self._window_role
        self._window_role = role
        compact = role == "chooser"
        for widget in (
            getattr(self, "lbl_run_status", None),
            getattr(self, "lbl_games", None),
            getattr(self, "lbl_games_cap", None),
            getattr(self, "lbl_version", None),
            getattr(self, "lbl_subscription", None),
            getattr(self, "btn_theme", None),
        ):
            if widget is not None:
                widget.setVisible(not compact)
        if compact:
            # 离开仪表板前保存有效尺寸，切回时恢复
            if previous_role == "dashboard" and self.width() >= 680 and self.height() >= 540:
                self._saved_dashboard_size = QSize(self.width(), self.height())
            self.setFixedSize(520, 360)
        else:
            # 先记录当前尺寸是否有效：setMinimumSize 会把过小窗口立即钳到最小，
            # 若在其后判断会误把 680x540 钳位结果当作有效用户尺寸。
            current_valid = self.width() >= 680 and self.height() >= 540
            saved = getattr(self, "_saved_dashboard_size", None)
            self.setMinimumSize(680, 540)
            self.setMaximumSize(16777215, 16777215)
            if saved is not None and saved.width() >= 680 and saved.height() >= 540:
                self.resize(saved)
                self._saved_dashboard_size = None  # 消费后清除，后续直接重入以当前尺寸为准
            elif current_valid:
                pass  # 已是有效仪表板尺寸（未经过 chooser 的直接重入）
            else:
                self.resize(1000, 780)

    def _is_running(self) -> bool:
        return bool(self.worker_thread and self.worker_thread.isRunning())

    def _refresh_chrome(self) -> None:
        if not hasattr(self, "btn_main"):
            return
        spec = get_spec(self.selected_mode_id())
        running = self._is_running()
        for control in (self.btn_solo_mode, self.btn_lead_mode, self.btn_follow_mode, self.btn_hitch_mode):
            control.setEnabled(not running)
        self.btn_main.setText(start_button_text(spec, running=running))
        can = desktop_may_start(spec.id) or running
        self.btn_main.setEnabled(can)
        self.btn_main.setObjectName("btnStop" if running else "btnStart")
        self.btn_main.setStyle(self.btn_main.style())
        self._refresh_summary()
        self._refresh_precheck()
        self._refresh_progress()
        self._refresh_launch_check()

    def _refresh_summary(self) -> None:
        spec = get_spec(self.selected_mode_id())
        if spec.id in {"follow_team", "lobby_hitch"}:
            cycle = self._current_cycle_num()
            cycle_text = "手动停" if cycle <= 0 else f"{cycle} 局"
            if spec.id == "follow_team":
                action = self.cmb_follow_after_room.currentText()
                trigger = "离房后"
            else:
                action = self.cmb_hitch_after_goal.currentText()
                trigger = "目标后"
            self.lbl_summary.setText(f"{self.selected_mode_label()} · {cycle_text} · {trigger}{action}")
            return
        stage = self.txt_stage_target.text().strip() or "-"
        diff = "英雄" if self.cmb_mode.currentData() else "普通"
        names = self.skill_grid.selected_names()
        skill = "/".join(names) if names else "未选技能"
        self.lbl_summary.setText(f"{self.selected_mode_label()} · {stage} · {diff} · 技能：{skill}")

    def _refresh_precheck(self) -> None:
        t = tokens(getattr(self, "current_theme", "light"))
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

    def _current_cycle_num(self) -> int:
        mode_id = self.selected_mode_id()
        if mode_id == "follow_team" and hasattr(self, "spn_follow_cycle_num"):
            return int(self.spn_follow_cycle_num.value())
        if mode_id == "lobby_hitch" and hasattr(self, "spn_hitch_cycle_num"):
            return int(self.spn_hitch_cycle_num.value())
        return int(self.spn_cycle_num.value()) if hasattr(self, "spn_cycle_num") else 0

    def _refresh_progress(self) -> None:
        cycle = self._current_cycle_num()
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
            cycle = self._current_cycle_num()
            target = self.txt_stage_target.text().strip() if hasattr(self, "txt_stage_target") else ""
            mode = self.selected_hud_mode_label()
            strategy = "声望挑战" if bool(self.cmb_mode.currentData()) else "自动推进"
            if hasattr(self, "chk_secret_realm") and self.chk_secret_realm.isChecked():
                strategy = "自动秘境"
            self.overlay_hud.anchor_to_target(getattr(mediator, "_last_frame", None))
            self.overlay_hud.update_status(
                True, phase, ocr_status, self._game_count, cycle,
                self._terminal_reason, self._last_action,
                target=target, mode=mode, strategy=strategy,
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
        self._refresh_reputation_cards()
        self._update_rep_summary()
        self._refresh_launch_check()
        self._schedule_auto_save()

    def _toggle_reputation_editor(self) -> None:
        expanded = self.rep_alloc_editor.isHidden()
        self.rep_alloc_editor.setVisible(expanded)
        self.btn_adjust_reputation.setText("收起" if expanded else "调整")

    def _set_reputation_mode_from_switch(self, checked: bool) -> None:
        """OD12 可见开关投影到既有普通/英雄设置源，不新增第二套状态。"""
        index = self.cmb_mode.findData(bool(checked))
        if index >= 0 and index != self.cmb_mode.currentIndex():
            self.cmb_mode.setCurrentIndex(index)
        self._update_hero_visibility()

    def _sync_reputation_switch(self, _index: int | None = None) -> None:
        checked = bool(self.cmb_mode.currentData())
        if self.chk_reputation_mode.isChecked() == checked:
            return
        self.chk_reputation_mode.blockSignals(True)
        self.chk_reputation_mode.setChecked(checked)
        self.chk_reputation_mode.blockSignals(False)

    def _refresh_reputation_cards(self) -> None:
        if not hasattr(self, "rep_cards_lay"):
            return
        while self.rep_cards_lay.count():
            item = self.rep_cards_lay.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        allocations = self._rep_allocations()
        faction_names = dict((fid, name) for name, fid in FACTIONS)
        for fid, points in allocations.items():
            card = QFrame()
            card.setObjectName("reputationCard")
            card_lay = QVBoxLayout(card)
            card_lay.setContentsMargins(5, 5, 5, 5)
            card_lay.setSpacing(3)
            art = QLabel()
            art.setObjectName("reputationArt")
            art.setFixedHeight(72)
            art.setAlignment(Qt.AlignCenter)
            path = ROOT / "assets" / "Images" / "lobby" / f"hero_{FACTION_SLUGS[fid]}_bright.png"
            if path.is_file():
                art.setPixmap(QPixmap(str(path)).scaled(
                    76, 72, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
                ))
            card_lay.addWidget(art)
            name = QLabel(f"{FACTION_SHORT_NAMES.get(fid, faction_names.get(fid, str(fid)))} ×{points}")
            name.setObjectName("reputationCardTitle")
            name.setAlignment(Qt.AlignCenter)
            card_lay.addWidget(name)
            card.setToolTip(FACTION_TIPS.get(fid, faction_names.get(fid, "")))
            self.rep_cards_lay.addWidget(card, 1)
        if not allocations:
            empty = QLabel("还没选择阵营，点“调整”分配声望点数。")
            empty.setObjectName("hintLabel")
            empty.setWordWrap(True)
            self.rep_cards_lay.addWidget(empty, 1)
        spent = sum(allocations.values())
        self.lbl_rep_cards_stats.setText(
            f"总 {spent} / {self._rep_available_points()} · 爆率 +{spent}%"
        )

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
        self._sync_reputation_switch()
        self.hero_options.setVisible(is_hero)
        if is_hero:
            self._refresh_reputation_cards()
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
        if hasattr(self, "btn_more_settings"):
            self.btn_more_settings.setText("收起设置" if expanded else "更多设置")

    def _set_skill_panel_expanded(self, expanded: bool):
        self.skill_grid.setVisible(expanded)
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
        self.skill_priority_bar.setVisible(bool(merged))

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

    def _on_priority_remove(self, code: str) -> None:
        skills = [item for item in self.skill_grid.get_skills() if item != code]
        self.skill_grid.set_skills(skills)

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
        self._refresh_launch_check()
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
        self.spn_follow_cycle_num.valueChanged.connect(self._schedule_auto_save)
        self.spn_hitch_cycle_num.valueChanged.connect(self._schedule_auto_save)
        self.cmb_follow_after_room.currentIndexChanged.connect(self._schedule_auto_save)
        self.cmb_hitch_after_goal.currentIndexChanged.connect(self._schedule_auto_save)
        self.txt_follow_pair_code.textChanged.connect(self._schedule_auto_save)
        self.cmb_hitch_prefix.currentIndexChanged.connect(self._schedule_auto_save)
        self.chk_secret_realm.toggled.connect(self._schedule_auto_save)
        self.chk_auto_archaeology.toggled.connect(self._schedule_auto_save)
        self.chk_auto_close_main_line.toggled.connect(self._schedule_auto_save)
        self.chk_auto_create_room.toggled.connect(self._schedule_auto_save)
        self.txt_room_name.textChanged.connect(self._schedule_auto_save)
        self.txt_room_password.textChanged.connect(self._schedule_auto_save)
        self.cmb_room_reuse.currentIndexChanged.connect(self._schedule_auto_save)
        self.cmb_cjb_boss.currentIndexChanged.connect(self._schedule_auto_save)
        self.cmb_sgzx_boss.currentIndexChanged.connect(self._schedule_auto_save)
        self.spn_cycle_num.valueChanged.connect(self._refresh_progress)
        self.spn_follow_cycle_num.valueChanged.connect(self._refresh_progress)
        self.spn_hitch_cycle_num.valueChanged.connect(self._refresh_progress)
        self.txt_stage_target.textChanged.connect(self._refresh_summary)
        self.txt_stage_target.textChanged.connect(self._on_rep_alloc_changed)
        self.txt_stage_target.textChanged.connect(self._refresh_launch_check)
        self.cmb_mode.currentIndexChanged.connect(self._refresh_launch_check)
        self.spn_cycle_num.valueChanged.connect(self._refresh_launch_check)
        self.spn_follow_cycle_num.valueChanged.connect(self._refresh_launch_check)
        self.spn_hitch_cycle_num.valueChanged.connect(self._refresh_launch_check)
        self.cmb_follow_after_room.currentIndexChanged.connect(self._refresh_chrome)
        self.cmb_hitch_after_goal.currentIndexChanged.connect(self._refresh_chrome)
        self.txt_follow_pair_code.textChanged.connect(self._refresh_launch_check)
        self.cmb_hitch_prefix.currentIndexChanged.connect(self._refresh_launch_check)
        self.chk_secret_realm.toggled.connect(self._refresh_launch_check)
        self.chk_auto_close_main_line.toggled.connect(self._refresh_launch_check)
        self.chk_auto_archaeology.toggled.connect(self._refresh_launch_check)
        self.chk_auto_create_room.toggled.connect(self._refresh_launch_check)
        self.txt_room_name.textChanged.connect(self._refresh_launch_check)
        self.cmb_cjb_boss.currentIndexChanged.connect(self._refresh_launch_check)
        self.cmb_sgzx_boss.currentIndexChanged.connect(self._refresh_launch_check)

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
        # `cards` is the worker whitelist. Mirror it for the dashboard, and
        # persist inverted from actual unchecked boxes so a stale scheme
        # cannot resurrect 箭术 etc. on the next launch.
        self._shell_extras["bond_scheme"] = list(settings.cards)
        self._shell_extras["bond_inverted"] = [
            code for code, box in getattr(self, "_bond_plan_boxes", {}).items()
            if not box.isChecked()
        ]
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
            cycle = self._current_cycle_num()
            target = self.txt_stage_target.text().strip() if hasattr(self, "txt_stage_target") else ""
            mode = self.selected_hud_mode_label()
            strategy = "声望挑战" if bool(self.cmb_mode.currentData()) else "自动推进"
            if hasattr(self, "chk_secret_realm") and self.chk_secret_realm.isChecked():
                strategy = "自动秘境"
            self.overlay_hud.update_status(
                bool(running), self._runtime_phase, self._ocr_status,
                self._game_count, cycle, self._terminal_reason, self._last_action,
                target=target, mode=mode, strategy=strategy,
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
            saved_theme = str(self._shell_extras.get("theme") or self.current_theme)
            if saved_theme not in {"light", "dark"}:
                saved_theme = "light"
            if saved_theme != getattr(self, "current_theme", "dark"):
                self.current_theme = saved_theme
                self._apply_component_theme()
            if hasattr(self, "btn_theme"):
                self.btn_theme.setText("深色" if self.current_theme == "light" else "浅色")
            mode_id = str(self._shell_extras.get("selected_mode_id") or "normal_farm")
            variant = str(self._shell_extras.get("selected_mode_variant") or "solo")
            requested = "lead" if mode_id == "normal_farm" and variant == "lead" else mode_id
            self._select_mode(requested if requested == "lead" or requested in self._page_index else "normal_farm")
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
        self.chk_auto_archaeology.setChecked(getattr(settings, "auto_archaeology", False))
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
        self.spn_follow_cycle_num.setValue(int(getattr(settings, "follow_cycle_num", 100) or 0))
        self.spn_hitch_cycle_num.setValue(int(getattr(settings, "hitch_cycle_num", 100) or 0))
        follow_action = self.cmb_follow_after_room.findData(str(getattr(settings, "follow_after_room", "solo") or "solo"))
        self.cmb_follow_after_room.setCurrentIndex(follow_action if follow_action >= 0 else 0)
        hitch_action = self.cmb_hitch_after_goal.findData(str(getattr(settings, "hitch_after_goal", "solo") or "solo"))
        self.cmb_hitch_after_goal.setCurrentIndex(hitch_action if hitch_action >= 0 else 0)
        self.txt_follow_pair_code.setText(str(getattr(settings, "follow_pair_code", "") or "")[:24])
        hitch_prefix = self.cmb_hitch_prefix.findData(str(getattr(settings, "hitch_stage_prefix", "3") or "3")[:1])
        self.cmb_hitch_prefix.setCurrentIndex(hitch_prefix if hitch_prefix >= 0 else 0)
        self.settings.skill_priority = [str(c) for c in (getattr(settings, "skill_priority", None) or [])]
        self.settings.skill_custom_routes = dict(getattr(settings, "skill_custom_routes", None) or {})
        self.skill_grid.set_skills(settings.skills or [])
        self.archive_grid.set_levels(dict(getattr(settings, "skill_archive_levels", None) or {}))

        whitelist = self._bond_codes_from_names(
            list(settings.cards or []) + list(getattr(settings, "bonds", None) or [])
        )
        if whitelist:
            self._shell_extras["bond_scheme"] = whitelist
            self._shell_extras["bond_inverted"] = []
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
        self._refresh_launch_check()

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
        settings.auto_create_room = self.chk_auto_create_room.isChecked()
        settings.room_name = self.txt_room_name.text().strip()
        settings.room_password = self.txt_room_password.text()
        settings.new_room_every_times = bool(self.cmb_room_reuse.currentData())
        settings.lab_focus = ""
        settings.dry_run = False
        settings.cjb_boss = str(self.cmb_cjb_boss.currentData() or "")
        settings.sgzx_boss = str(self.cmb_sgzx_boss.currentData() or "")
        settings.auto_secret_realm = self.chk_secret_realm.isChecked()
        settings.auto_close_main_line = self.chk_auto_close_main_line.isChecked()
        settings.cycle_num = int(self.spn_cycle_num.value())
        settings.follow_cycle_num = int(self.spn_follow_cycle_num.value())
        settings.hitch_cycle_num = int(self.spn_hitch_cycle_num.value())
        settings.follow_after_room = str(self.cmb_follow_after_room.currentData() or "solo")
        settings.hitch_after_goal = str(self.cmb_hitch_after_goal.currentData() or "solo")
        settings.follow_pair_code = self.txt_follow_pair_code.text().strip()[:24]
        settings.auto_archaeology = self.chk_auto_archaeology.isChecked()
        settings.skills = skills
        settings.skill_archive_levels = self.archive_grid.get_levels()
        settings.skill_priority = self.skill_priority_bar.order() or list(skills)
        settings.skill_custom_routes = {
            **(getattr(self.settings, "skill_custom_routes", None) or {}),
            **self.skill_priority_bar.route_selections(),
        }
        settings.cards = self.assemble_whitelist_cards()
        settings.bonds = [
            bond_display_name(code)
            for code, box in self._bond_plan_boxes.items()
            if box.isChecked()
        ]
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
        # The compact bond chips only represent the basic pack.  Attribute/UR
        # codes from an official build live in settings.cards and are merged by
        # assemble_whitelist_cards(); without this assignment the dashboard
        # silently dropped zhili/yanmiezhe/fs before starting a real run.
        self.settings.cards = list(new_cards)
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
        self.showMinimized()

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
