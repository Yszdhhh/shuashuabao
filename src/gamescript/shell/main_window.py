"""控制中心主窗：左栏运行方式 + 右栏当前设置 + 底栏钉死。"""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
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

from gamescript import __version__
from gamescript.settings import Settings
from gamescript.shell.mode_catalog import (
    collect_persistable_settings,
    badge_text,
    desktop_may_start,
    get_spec,
    iter_specs,
    start_button_text,
)
from gamescript.shell.runner_service import (
    MediatorWorker,
    ModeNotEnabled,
    RunnerService,
    live_lock_busy,
)
from gamescript.shell.runtime_status import progress_from_counts

APP_NAME = "刷刷宝"
APP_ID = "ShuaBao"
APP_VERSION_LABEL = f"V{__version__}" if not str(__version__).upper().startswith("V") else str(__version__)
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))
if not (ROOT / "config").is_dir():
    ROOT = Path(__file__).resolve().parents[3]


def _app_data_dir() -> Path:
    override = os.environ.get("SHUABAO_APP_DATA")
    if override:
        return Path(override)
    return Path(os.environ.get("LOCALAPPDATA", ROOT)) / APP_ID


APP_DATA = _app_data_dir()
FACTORY_SETTINGS = ROOT / "config" / "default_settings.json"
USER_SETTINGS_NAME = "user_settings.json"
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
BOND_ICON_DIR = ROOT / "assets" / "Images" / "cards"
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
FETTER_STEMS: list[str] = sorted(FETTER_LABELS.keys(), key=lambda c: FETTER_LABELS[c])
FETTER_NAME_TO_CODE = {name: code for code, name in FETTER_LABELS.items()}
_STRATEGY = _load_json_doc(ROOT / "config" / "official_strategy_defaults.json")
OFFICIAL_BUILDS: list[dict] = [b for b in (_STRATEGY.get("builds") or []) if isinstance(b, dict)]
ATTR_ROUTES: dict[str, dict] = {
    k: v for k, v in (_STRATEGY.get("attr_routes") or {}).items()
    if isinstance(v, dict) and not str(k).startswith("_")
}
BOND_PRIORITY: dict = _STRATEGY.get("bond_priority") or {}
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


def skill_display_name(code: str) -> str:
    meta = SKILL_META.get(code) or {}
    return str(meta.get("label") or SKILL_LABELS.get(code, code))


def bond_display_name(code: str) -> str:
    return FETTER_LABELS.get(code, code)


def code_for_bond_name(name: str) -> str | None:
    return FETTER_NAME_TO_CODE.get(name)


def route_fetter_codes(route_id: str) -> list[str]:
    route = ATTR_ROUTES.get(route_id) or {}
    codes: list[str] = []
    for name in route.get("chain") or []:
        code = code_for_bond_name(str(name))
        if code and code not in codes:
            codes.append(code)
    extra = route.get("fetter_code")
    if extra and extra not in codes:
        codes.append(str(extra))
    return codes


def _is_admin() -> bool:
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


class SkillCardGrid(QWidget):
    """中文技能卡片多选网格：显示中文名，内部存拼音短码，最多 4 个。"""

    MAX_SKILLS = 4
    skills_changed = Signal()

    CARD_QSS = (
        "QPushButton { background:#ffffff; border:1px solid #d7dee8; border-radius:8px;"
        " color:#334155; font-size:12px; padding:6px 4px; text-align:center; }"
        "QPushButton:hover { border:1px solid #0ea5e9; color:#0f172a; background:#f0f9ff; }"
        "QPushButton:checked { background:#e0f2fe; border:2px solid #0284c7; color:#0c4a6e;"
        " font-weight:bold; }"
    )

    def __init__(self, skill_stems: list[str], skill_labels: dict[str, str], parent=None):
        super().__init__(parent)
        self.skill_stems = skill_stems
        self.skill_labels = skill_labels
        self.cards: dict[str, QPushButton] = {}
        self._selected: list[str] = []
        self._init_ui()

    def _tooltip_for(self, code: str) -> str:
        meta = SKILL_META.get(code) or {}
        name = meta.get("label") or self.skill_labels.get(code, "未命名技能")
        desc = (meta.get("description") or "").strip()
        body = desc if desc else "说明待补（尚无实机卡面截图，未编造数值）"
        return f"<b>{name}</b><br/>{body}<br/><span style='color:#64748b'>短码 {code}</span>"

    def _init_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        hint = QLabel("最多选 4 个；未选中的永远不学。都没命中时只刷新，刷完仍没有就放弃。")
        hint.setWordWrap(True)
        hint.setObjectName("hintLabel")
        lay.addWidget(hint)
        row = QHBoxLayout()
        clear_btn = QPushButton("清空")
        clear_btn.setToolTip("清空全部技能：技能面板将只刷新并放弃，不学任何技能")
        clear_btn.clicked.connect(lambda: self.set_skills([]))
        row.addWidget(clear_btn)
        row.addStretch()
        lay.addLayout(row)
        grid = QGridLayout()
        grid.setSpacing(8)
        for idx, code in enumerate(self.skill_stems):
            cn = skill_display_name(code)
            btn = QPushButton(cn)
            btn.setCheckable(True)
            btn.setMinimumHeight(64)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            icon_path = SKILL_ICON_DIR / f"{code}.png"
            if icon_path.is_file():
                btn.setIcon(QIcon(str(icon_path)))
                btn.setIconSize(QSize(30, 30))
            btn.setStyleSheet(self.CARD_QSS)
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
                    QMessageBox.information(self, "技能限制", f"主刷图技能最多选择 {self.MAX_SKILLS} 个")
                    return
                self._selected.append(code)
        elif code in self._selected:
            self._selected.remove(code)
        self._refresh_cards()
        self.skills_changed.emit()

    def set_skills(self, codes: list[str]):
        self._selected = [c for c in codes if c in self.cards][: self.MAX_SKILLS]
        for code, btn in self.cards.items():
            btn.setChecked(code in self._selected)
        self._refresh_cards()
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


class BondCardGrid(QWidget):
    """羁绊多选：中文名展示，内部存短码（写入 settings.cards），最多 6 个。"""

    MAX_BONDS = 6
    bonds_changed = Signal()
    CARD_QSS = SkillCardGrid.CARD_QSS

    def __init__(self, stems: list[str], labels: dict[str, str], parent=None):
        super().__init__(parent)
        self.stems = stems
        self.labels = labels
        self.cards: dict[str, QPushButton] = {}
        self._selected: list[str] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        hint = QLabel(
            "最多选 6 个套系；只拿勾选套系里的卡。这是最终生效白名单。"
            "智力 UR=湮灭者，力量 UR=屠戮者，敏捷 UR=收割者。"
        )
        hint.setWordWrap(True)
        hint.setObjectName("hintLabel")
        lay.addWidget(hint)
        row = QHBoxLayout()
        clear_btn = QPushButton("清空")
        clear_btn.clicked.connect(lambda: self.set_bonds([]))
        row.addWidget(clear_btn)
        row.addStretch()
        lay.addLayout(row)
        grid = QGridLayout()
        grid.setSpacing(6)
        for idx, code in enumerate(self.stems):
            cn = self.labels.get(code, code)
            btn = QPushButton(cn)
            btn.setCheckable(True)
            btn.setMinimumHeight(36)
            icon_path = BOND_ICON_DIR / f"{code}.png"
            if icon_path.is_file():
                btn.setIcon(QIcon(str(icon_path)))
                btn.setIconSize(QSize(22, 22))
            btn.setStyleSheet(self.CARD_QSS)
            btn.setToolTip(f"{cn}（短码 {code}）")
            btn.clicked.connect(lambda checked, c=code: self._toggle(c, checked))
            self.cards[code] = btn
            grid.addWidget(btn, idx // 5, idx % 5)
        lay.addLayout(grid)

    def _toggle(self, code: str, checked: bool):
        if checked:
            if code not in self._selected:
                if len(self._selected) >= self.MAX_BONDS:
                    self.cards[code].setChecked(False)
                    QMessageBox.information(self, "羁绊限制", f"羁绊最多选择 {self.MAX_BONDS} 个")
                    return
                self._selected.append(code)
        elif code in self._selected:
            self._selected.remove(code)
        self._refresh()
        self.bonds_changed.emit()

    def set_bonds(self, codes: list[str]):
        self._selected = [c for c in codes if c in self.cards][: self.MAX_BONDS]
        for code, btn in self.cards.items():
            btn.setChecked(code in self._selected)
        self._refresh()
        self.bonds_changed.emit()

    def get_bonds(self) -> list[str]:
        return list(self._selected)

    def selected_names(self) -> list[str]:
        return [self.labels.get(code, code) for code in self._selected]

    def _refresh(self):
        order = {code: i + 1 for i, code in enumerate(self._selected)}
        for code, btn in self.cards.items():
            name = self.labels.get(code, code)
            btn.setText(f"{order[code]}. {name}" if code in order else name)


class SkillArchiveLevelGrid(QWidget):
    """技能存档等级：每系一个数字框，0=未知。"""

    MAX_LEVEL = 50
    levels_changed = Signal()

    def __init__(self, stems: list[str], labels: dict[str, str], parent=None):
        super().__init__(parent)
        self.boxes: dict[str, QSpinBox] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        hint = QLabel(
            "填游戏里技能卡面标题的等级（如「奥术箭 Lv47」填 47）。0=未知，按最保守的前置规则走。"
        )
        hint.setWordWrap(True)
        hint.setObjectName("hintLabel")
        lay.addWidget(hint)
        grid = QGridLayout()
        grid.setSpacing(6)
        for idx, code in enumerate(stems):
            cn = labels.get(code, code)
            box = QSpinBox()
            box.setRange(0, self.MAX_LEVEL)
            box.setSpecialValueText("未知")
            box.setToolTip(f"{cn}（短码 {code}）存档等级；0=未知")
            box.valueChanged.connect(lambda _v: self.levels_changed.emit())
            self.boxes[code] = box
            cell = QHBoxLayout()
            cell.setSpacing(4)
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
        "透支力量": "先给力量、之后要还回去的透支型收益",
        "贪婪献祭": "用消耗换随机属性，长期期望为负",
        "金转木": "把金币转成木材，断掉金币来源",
        "杀敌梭哈": "一次性梭哈，之后收益中断",
        "伐木契约": "一次性木材，之后不再获得木材",
        "等级优势": "直接拉到某等级，之后不再升级",
    }

    def __init__(self, names: list[str], prefix: str = "", parent=None):
        super().__init__(parent)
        self._prefix = prefix
        self._boxes: dict[str, QCheckBox] = {}
        self.setCheckable(True)
        self.setChecked(False)
        self.setToolTip("特殊宝物：拿了可能断资源或断成长，默认不选。")
        lay = QVBoxLayout(self)
        lay.setSpacing(6)
        lay.setContentsMargins(0, 0, 0, 0)
        self.body = QWidget()
        body_lay = QVBoxLayout(self.body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(6)
        note = QLabel("勾选 = 允许选这张；不勾 = 永不选。逐张生效。与 choice_policy 同源。")
        note.setWordWrap(True)
        note.setObjectName("warnHint")
        body_lay.addWidget(note)
        if names:
            grid_host = QWidget()
            grid = QGridLayout(grid_host)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setSpacing(6)
            for idx, name in enumerate(names):
                box = QCheckBox(name)
                box.setToolTip(self.TIP.get(name, "拿了会中断某项收益"))
                box.toggled.connect(lambda _=False: self.changed.emit())
                self._boxes[name] = box
                grid.addWidget(box, idx // 2, idx % 2)
            body_lay.addWidget(grid_host)
        else:
            empty = QLabel("未配置特殊宝物名单（config/choice_policy.json）")
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
            body = f"特殊宝物选择（已选 {len(allowed)}：{'、'.join(allowed)}）"
        else:
            body = "特殊宝物选择（默认全不选）"
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
        self.app_data = Path(app_data) if app_data is not None else _app_data_dir()
        self.app_data.mkdir(parents=True, exist_ok=True)
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION_LABEL} · 重生魔兽刷刷刷")
        self.resize(720, 560)
        self.setMinimumSize(640, 500)

        self.settings = Settings()
        self._shell_extras: dict = {
            "selected_mode_id": "normal_farm",
            "custom_builds": [],
            "bond_scheme": [],
            "bond_inverted": [],
            "attr_route": "intelligence",
            "hitch_stage_prefix": "3",
        }
        self.runner = RunnerService(self.app_data, ROOT)
        self.worker_thread: MediatorWorker | None = None
        self._game_count = 0
        self._syncing_bonds = False

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(800)
        self._save_timer.timeout.connect(self._save_settings_now)
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(200)
        self._status_timer.timeout.connect(self._poll_runtime)

        self._setup_style()
        self._build_ui()
        self._setup_tray()
        self.load_local_settings(silent=True)
        self._wire_auto_save()
        self._refresh_chrome()

    def _setup_style(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #f4f7fb; }
            QWidget { background-color: #f4f7fb; color: #1e293b;
                font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif; font-size: 12px; }
            QGroupBox { background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px;
                margin-top: 12px; padding: 14px 12px 10px 12px; font-weight: bold; font-size: 13px; color: #0f172a; }
            QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 12px;
                padding: 2px 8px; background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 6px; color: #334155; }
            QLabel { background-color: transparent; }
            QLabel#brandTitle { font-size: 20px; font-weight: bold; color: #0f172a; }
            QLabel#brandSub { font-size: 11px; color: #94a3b8; }
            QLabel#hintLabel { color: #64748b; font-size: 11px; }
            QLabel#warnHint { color: #b45309; font-size: 11px; }
            QLabel#statusLine { color: #64748b; font-size: 11px; }
            QLabel#gamesCount { font-size: 18px; font-weight: bold; color: #0284c7; }
            QLabel#gamesCap { font-size: 10px; color: #94a3b8; }
            QLabel#statusPill { background-color: #e2e8f0; border: 1px solid #cbd5e1; border-radius: 11px;
                color: #64748b; font-weight: bold; padding: 3px 12px; }
            QLabel#statusPill[state="running"] { background-color: #dcfce7; border: 1px solid #86efac; color: #15803d; }
            QLabel#precheckLamp { font-weight: bold; padding: 2px 8px; border-radius: 8px; }
            QLabel#sectionCap { color: #64748b; font-size: 11px; font-weight: normal; }
            QCheckBox#chkLearn { color: #b45309; font-weight: bold; }
            QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
                background-color: #ffffff; border: 1px solid #cbd5e1; border-radius: 6px;
                color: #0f172a; padding: 5px 8px; min-height: 22px; }
            QListWidget#modeList { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; }
            QListWidget#modeList::item { padding: 8px; margin: 2px; border-radius: 6px; }
            QListWidget#modeList::item:selected { background: #e0f2fe; color: #0c4a6e; }
            QPushButton { background-color: #ffffff; border: 1px solid #cbd5e1; border-radius: 6px;
                color: #334155; padding: 6px 12px; font-weight: 500; }
            QPushButton#btnStart { background-color: #0284c7; border: none; color: #ffffff;
                font-size: 15px; font-weight: bold; padding: 12px; border-radius: 8px; }
            QPushButton#btnStop { background-color: #dc2626; border: none; color: #ffffff;
                font-size: 15px; font-weight: bold; padding: 12px; border-radius: 8px; }
            QPushButton:disabled { background-color: #e2e8f0; color: #94a3b8; border: 1px solid #e2e8f0; }
            QPlainTextEdit { background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px;
                color: #334155; font-family: Consolas, monospace; font-size: 11px; }
            QScrollArea { background: transparent; border: none; }
            QFrame#footerBar { background: #ffffff; border-top: 1px solid #e2e8f0; }
        """)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QHBoxLayout()
        header.setContentsMargins(16, 12, 16, 8)
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title = QLabel(f"{APP_NAME} {APP_VERSION_LABEL}")
        title.setObjectName("brandTitle")
        subtitle = QLabel("控制中心 · 运行方式与关卡难度分开")
        subtitle.setObjectName("brandSub")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch()
        self.lbl_run_status = QLabel("空闲")
        self.lbl_run_status.setObjectName("statusPill")
        self.lbl_run_status.setAlignment(Qt.AlignCenter)
        self.lbl_run_status.setMinimumWidth(72)
        header.addWidget(self.lbl_run_status)
        games_box = QVBoxLayout()
        games_box.setSpacing(0)
        self.lbl_games = QLabel("0")
        self.lbl_games.setAlignment(Qt.AlignRight)
        self.lbl_games.setObjectName("gamesCount")
        self.lbl_games_cap = QLabel("已完成")
        self.lbl_games_cap.setAlignment(Qt.AlignRight)
        self.lbl_games_cap.setObjectName("gamesCap")
        games_box.addWidget(self.lbl_games)
        games_box.addWidget(self.lbl_games_cap)
        header.addLayout(games_box)
        outer.addLayout(header)

        body = QHBoxLayout()
        body.setContentsMargins(12, 0, 12, 0)
        body.setSpacing(10)

        left = QVBoxLayout()
        left_cap = QLabel("运行方式")
        left_cap.setObjectName("sectionCap")
        left.addWidget(left_cap)
        self.mode_list = QListWidget()
        self.mode_list.setObjectName("modeList")
        self.mode_list.setFixedWidth(168)
        for spec in iter_specs():
            item = QListWidgetItem(f"{spec.label}\n{badge_text(spec)}")
            item.setData(Qt.UserRole, spec.id)
            self.mode_list.addItem(item)
        self.mode_list.currentRowChanged.connect(self._on_mode_row_changed)
        left.addWidget(self.mode_list)
        body.addLayout(left)

        self.right_stack = QStackedWidget()
        self._page_index: dict[str, int] = {}
        for spec in iter_specs():
            page = self._build_mode_page(spec.id)
            self._page_index[spec.id] = self.right_stack.addWidget(page)
        body.addWidget(self.right_stack, 1)
        outer.addLayout(body, 1)

        self.footer = QFrame()
        self.footer.setObjectName("footerBar")
        foot = QHBoxLayout(self.footer)
        foot.setContentsMargins(16, 10, 16, 10)
        foot.setSpacing(10)
        self.lbl_summary = QLabel("就绪")
        self.lbl_summary.setObjectName("statusLine")
        self.lbl_summary.setWordWrap(True)
        foot.addWidget(self.lbl_summary, 1)
        self.lbl_precheck = QLabel("预检 ●")
        self.lbl_precheck.setObjectName("precheckLamp")
        foot.addWidget(self.lbl_precheck)
        self.btn_main = QPushButton("开始运行")
        self.btn_main.setObjectName("btnStart")
        self.btn_main.setMinimumHeight(44)
        self.btn_main.setMinimumWidth(168)
        self.btn_main.clicked.connect(self.toggle_run)
        foot.addWidget(self.btn_main)
        outer.addWidget(self.footer)

        self.lbl_latest = QLabel("就绪 · Shift+F12 紧急停止")
        self.lbl_latest.setVisible(False)

        if self.mode_list.count():
            self.mode_list.setCurrentRow(0)

    def _build_mode_page(self, mode_id: str) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(4, 4, 8, 12)
        lay.setSpacing(10)
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

    def _section(self, title: str, default_note: str) -> tuple[QGroupBox, QVBoxLayout]:
        box = QGroupBox(title)
        lay = QVBoxLayout(box)
        cap = QLabel(f"默认设置 · {default_note}")
        cap.setObjectName("sectionCap")
        cap.setWordWrap(True)
        lay.addWidget(cap)
        return box, lay

    def _build_normal_farm_page(self, lay: QVBoxLayout) -> None:
        skill_box, skill_lay = self._section("① 技能", "出厂四系来自 default_settings / official_strategy_defaults")
        combo_row = QHBoxLayout()
        combo_row.addWidget(QLabel("常用搭配"))
        self.cmb_build = QComboBox()
        self.cmb_build.addItem("（不套用）", "")
        for build in OFFICIAL_BUILDS:
            self.cmb_build.addItem(str(build.get("name") or build.get("id")), str(build.get("id") or ""))
        combo_row.addWidget(self.cmb_build, 1)
        self.btn_apply_build = QPushButton("应用流派")
        self.btn_apply_build.clicked.connect(self._on_apply_build_clicked)
        combo_row.addWidget(self.btn_apply_build)
        self.btn_save_custom = QPushButton("保存自定义组合")
        self.btn_save_custom.clicked.connect(self._on_save_custom_build)
        combo_row.addWidget(self.btn_save_custom)
        skill_lay.addLayout(combo_row)
        adj = QLabel("可调设置 · 改格子后可另存为本地方案（不写仓库）")
        adj.setObjectName("sectionCap")
        skill_lay.addWidget(adj)
        self.grp_skill = QGroupBox("技能")
        self.grp_skill.setCheckable(True)
        self.grp_skill.setChecked(False)
        sl = QVBoxLayout(self.grp_skill)
        self.skill_grid = SkillCardGrid(SKILL_STEMS, SKILL_LABELS)
        sl.addWidget(self.skill_grid)
        self.skill_grid.setVisible(False)
        self.grp_skill.toggled.connect(self._set_skill_panel_expanded)
        self.skill_grid.skills_changed.connect(self._on_skills_changed)
        skill_lay.addWidget(self.grp_skill)
        self.grp_archive = QGroupBox("技能存档等级（未填=未知）")
        self.grp_archive.setCheckable(True)
        self.grp_archive.setChecked(False)
        al = QVBoxLayout(self.grp_archive)
        self.archive_grid = SkillArchiveLevelGrid(SKILL_STEMS, SKILL_LABELS)
        al.addWidget(self.archive_grid)
        self.archive_grid.setVisible(False)
        self.grp_archive.toggled.connect(self._set_archive_panel_expanded)
        self.archive_grid.levels_changed.connect(self._on_archive_levels_changed)
        skill_lay.addWidget(self.grp_archive)
        lay.addWidget(skill_box)

        bond_box, bond_lay = self._section("② 羁绊", "硬白名单 ≤6 短码；无短码条目只能看不能勾")
        route_row = QHBoxLayout()
        route_row.addWidget(QLabel("三线 UR 链"))
        self.route_group = QButtonGroup(self)
        self.route_buttons: dict[str, QRadioButton] = {}
        for rid, label in (("intelligence", "智力"), ("strength", "力量"), ("agility", "敏捷")):
            btn = QRadioButton(label)
            self.route_group.addButton(btn)
            self.route_buttons[rid] = btn
            route_row.addWidget(btn)
        self.route_buttons["intelligence"].setChecked(True)
        self.route_group.buttonClicked.connect(self._on_attr_route_clicked)
        route_row.addStretch()
        bond_lay.addLayout(route_row)
        note = QLabel("无短码的羁绊只能看不能勾（bond_stack_catalog 与 fetter_labels 不对称）。")
        note.setObjectName("hintLabel")
        note.setWordWrap(True)
        bond_lay.addWidget(note)
        self.bond_plan_host = QWidget()
        self.bond_plan_lay = QVBoxLayout(self.bond_plan_host)
        self.bond_plan_lay.setContentsMargins(0, 0, 0, 0)
        self._bond_plan_boxes: dict[str, QCheckBox] = {}
        self._rebuild_bond_plan()
        bond_lay.addWidget(self.bond_plan_host)
        self.grp_bond = QGroupBox("羁绊")
        self.grp_bond.setCheckable(True)
        self.grp_bond.setChecked(False)
        bl = QVBoxLayout(self.grp_bond)
        self.bond_grid = BondCardGrid(FETTER_STEMS, FETTER_LABELS)
        bl.addWidget(self.bond_grid)
        self.bond_grid.setVisible(False)
        self.grp_bond.toggled.connect(self._set_bond_panel_expanded)
        self.bond_grid.bonds_changed.connect(self._on_bonds_changed)
        bond_lay.addWidget(self.grp_bond)
        lay.addWidget(bond_box)

        loot_box, loot_lay = self._section("③ 宝物与资源", "EX 四宝策略必拿；负面宝物默认全不放行")
        loot_lay.addWidget(self._build_must_take_row())
        self.grp_negative = NegativeTreasureGroup(NEGATIVE_TREASURES)
        self.grp_negative.changed.connect(self._on_negative_changed)
        loot_lay.addWidget(self.grp_negative)

        gamble = QLabel("赌木（待接线）：auto_gambling_time 未进状态机；闭环属「赌木」运行方式，不可启动。")
        gamble.setObjectName("warnHint")
        gamble.setWordWrap(True)
        loot_lay.addWidget(gamble)
        g_row = QHBoxLayout()
        g_row.addWidget(QLabel("第几个宝物"))
        self.spn_treasure_num = QSpinBox()
        self.spn_treasure_num.setRange(0, 20)
        g_row.addWidget(self.spn_treasure_num)
        g_row.addWidget(QLabel("赌木时间"))
        self.spn_gambling_time = QSpinBox()
        self.spn_gambling_time.setRange(0, 3600)
        g_row.addWidget(self.spn_gambling_time)
        g_row.addStretch()
        loot_lay.addLayout(g_row)

        ball = QLabel("龙珠（待验证）：LONGZHU 链 Fail-Closed，开关可展示但真机链未通。")
        ball.setObjectName("warnHint")
        ball.setWordWrap(True)
        loot_lay.addWidget(ball)
        d_row = QHBoxLayout()
        d_row.addWidget(QLabel("龙珠数量"))
        self.spn_dragon_ball = QSpinBox()
        self.spn_dragon_ball.setRange(1, 10)
        self.spn_dragon_ball.setValue(7)
        d_row.addWidget(self.spn_dragon_ball)
        self.chk_longzhu_multi = QCheckBox("多局找龙珠")
        self.chk_longzhu_in_game = QCheckBox("局内找龙珠")
        d_row.addWidget(self.chk_longzhu_multi)
        d_row.addWidget(self.chk_longzhu_in_game)
        d_row.addStretch()
        loot_lay.addLayout(d_row)

        pill = QLabel("吞噬丹：满槽先吃丹→再黑商（bond_capacity）。黑商只买木/丹。不提供自动购买序开关。")
        pill.setObjectName("hintLabel")
        pill.setWordWrap(True)
        loot_lay.addWidget(pill)

        wood = QLabel("木材阈值（待接线 · 置灰）：<100 不开 F / <40 不刷新。由逻辑库板块接线。")
        wood.setObjectName("warnHint")
        wood.setWordWrap(True)
        loot_lay.addWidget(wood)
        w_row = QHBoxLayout()
        w_row.addWidget(QLabel("不开 F"))
        self.spn_wood_open_f = QSpinBox()
        self.spn_wood_open_f.setRange(0, 999)
        self.spn_wood_open_f.setValue(100)
        self.spn_wood_open_f.setEnabled(False)
        w_row.addWidget(self.spn_wood_open_f)
        w_row.addWidget(QLabel("不刷新"))
        self.spn_wood_refresh = QSpinBox()
        self.spn_wood_refresh.setRange(0, 999)
        self.spn_wood_refresh.setValue(40)
        self.spn_wood_refresh.setEnabled(False)
        w_row.addWidget(self.spn_wood_refresh)
        w_row.addStretch()
        loot_lay.addLayout(w_row)
        lay.addWidget(loot_box)

        run_box, run_lay = self._section("④ 运行", "关卡难度 ≠ 运行方式；局数 0=手动停")
        lab_hint = QLabel(
            "测试夹 bat 会读这份保存。改完等自动保存（约 1 秒）再双击 bat。不要同时开 LIVE。"
        )
        lab_hint.setObjectName("warnHint")
        lab_hint.setWordWrap(True)
        run_lay.addWidget(lab_hint)
        save_row = QHBoxLayout()
        self.btn_save_settings = QPushButton("保存设置")
        self.btn_save_settings.setObjectName("btnSaveSettings")
        self.btn_save_settings.clicked.connect(self._on_save_settings_clicked)
        save_row.addWidget(self.btn_save_settings)
        save_row.addStretch()
        run_lay.addLayout(save_row)
        core = QGroupBox("运行")
        core_layout = QVBoxLayout(core)
        stage_row = QHBoxLayout()
        stage_row.addWidget(QLabel("关卡"))
        self.txt_stage_target = QLineEdit("1-10")
        self.txt_stage_target.setObjectName("stageTarget")
        self.txt_stage_target.setPlaceholderText("例如 1-10")
        self.txt_stage_target.setMaximumWidth(100)
        stage_row.addWidget(self.txt_stage_target)
        stage_row.addWidget(QLabel("关卡难度"))
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItem("普通", False)
        self.cmb_mode.addItem("英雄", True)
        self.cmb_mode.setMinimumWidth(88)
        stage_row.addWidget(self.cmb_mode)
        stage_row.addWidget(QLabel("局数"))
        self.spn_cycle_num = QSpinBox()
        self.spn_cycle_num.setRange(0, 999)
        self.spn_cycle_num.setSpecialValueText("手动停")
        self.spn_cycle_num.setToolTip("0 = 直到手动停止，不画满条")
        stage_row.addWidget(self.spn_cycle_num)
        stage_row.addStretch()
        core_layout.addLayout(stage_row)
        self.hero_options = QWidget()
        hero_row = QHBoxLayout(self.hero_options)
        hero_row.setContentsMargins(0, 0, 0, 0)
        hero_row.addWidget(QLabel("阵营"))
        self.cmb_reputation = QComboBox()
        for name, faction_id in FACTIONS:
            self.cmb_reputation.addItem(name, faction_id)
        self.cmb_reputation.setCurrentIndex(self.cmb_reputation.findData(3))
        hero_row.addWidget(self.cmb_reputation)
        hero_row.addWidget(QLabel("难度"))
        self.spn_reputation_level = QSpinBox()
        self.spn_reputation_level.setRange(1, 5)
        hero_row.addWidget(self.spn_reputation_level)
        hero_note = QLabel("英雄阵营的 L0 门控另算；未验证阵营请谨慎。")
        hero_note.setObjectName("warnHint")
        hero_row.addWidget(hero_note)
        hero_row.addStretch()
        core_layout.addWidget(self.hero_options)
        self.chk_learn = QCheckBox("学习模式（只观察记录，不实操）")
        self.chk_learn.setObjectName("chkLearn")
        self.chk_dry = self.chk_learn
        self.chk_secret_realm = QCheckBox("胜利后自动挑战秘境")
        core_layout.addWidget(self.chk_learn)
        core_layout.addWidget(self.chk_secret_realm)
        run_lay.addWidget(core)
        self.grp_details = QGroupBox("运行日志")
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
        run_lay.addWidget(self.grp_details)
        atlas = QLabel("图鉴入口：P2（本轮不做）。")
        atlas.setObjectName("hintLabel")
        run_lay.addWidget(atlas)
        lay.addWidget(run_box)
        self.cmb_mode.currentIndexChanged.connect(self._update_hero_visibility)
        self._update_hero_visibility()

    def _build_must_take_row(self) -> QWidget:
        host = QWidget()
        grid = QGridLayout(host)
        grid.setContentsMargins(0, 0, 0, 0)
        for idx, name in enumerate(MUST_TAKE_TREASURES):
            cell = QVBoxLayout()
            icon = QLabel()
            icon.setFixedSize(56, 56)
            path = ROOT / "fixtures" / "treasure_must_take" / name / "source.png"
            if path.is_file():
                pix = QPixmap(str(path)).scaled(56, 56, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                icon.setPixmap(pix)
            else:
                icon.setText(name)
                icon.setStyleSheet("background:#e2e8f0; color:#64748b;")
                icon.setAlignment(Qt.AlignCenter)
            cap = QLabel(f"{name}\n策略必拿")
            cap.setObjectName("hintLabel")
            cap.setAlignment(Qt.AlignCenter)
            cell.addWidget(icon, alignment=Qt.AlignCenter)
            cell.addWidget(cap)
            wrap = QWidget()
            wrap.setLayout(cell)
            grid.addWidget(wrap, 0, idx)
        if not MUST_TAKE_TREASURES:
            grid.addWidget(QLabel("未配置 must_take_names"))
        return host

    def _build_follow_page(self, lay: QVBoxLayout) -> None:
        box = QGroupBox("跟车（待验证 · 不可启动）")
        bl = QVBoxLayout(box)
        for text in (
            "跟车不建房、不点开始游戏。已在房等队长。",
            "F1 = 操作切回自身英雄（防 G/V/F 无法操作）。",
            "F2 = 回基地（视角偏离，或要点秘境/传家宝时）。",
            "只认 准备 / 已准备 / 取消准备；特殊房无「锁定」按钮，金/蓝只是颜色不同。",
            "禁止快速加入 / 快速匹配 / 颜色兜底。",
            "找房大厅列表证据由找房专项提供；本卡不启动点击。",
        ):
            lbl = QLabel(text)
            lbl.setWordWrap(True)
            lbl.setObjectName("hintLabel")
            bl.addWidget(lbl)
        lay.addWidget(box)

    def _build_gamble_page(self, lay: QVBoxLayout) -> None:
        box = QGroupBox("赌木（待验证 · 不可启动）")
        bl = QVBoxLayout(box)
        note = QLabel("首个宝物判定后重开。词典无「赌木」卡名；auto_gambling_time 未接线。不展示技能网格，避免误以为会刷图。")
        note.setWordWrap(True)
        note.setObjectName("warnHint")
        bl.addWidget(note)
        row = QHBoxLayout()
        row.addWidget(QLabel("关卡（只读说明）"))
        hint = QLineEdit("沿用自己刷图的关卡字段")
        hint.setReadOnly(True)
        row.addWidget(hint)
        bl.addLayout(row)
        lay.addWidget(box)

    def _build_raid_page(self, lay: QVBoxLayout) -> None:
        box = QGroupBox("站团本（待验证 · 不可启动）")
        bl = QVBoxLayout(box)
        for text in (
            "展示等待 4–8 小时。不会自动进本。",
            "人工步骤：先在游戏内兑换魔团本，再考虑接线。",
            "LONGZHU 保持 Fail-Closed。缺「兑换魔团本」入口锚点。",
        ):
            lbl = QLabel(text)
            lbl.setWordWrap(True)
            lbl.setObjectName("hintLabel")
            bl.addWidget(lbl)
        lay.addWidget(box)

    def _build_hitch_page(self, lay: QVBoxLayout) -> None:
        box = QGroupBox("大厅找房蹭车（待验证 · 不可启动）")
        bl = QVBoxLayout(box)
        for text in (
            "只认 准备 / 已准备 / 取消准备。特殊房无「锁定」按钮；金/蓝两套只是颜色不同，识别以文字为主锚。",
            "F1 = 操作切回自身英雄。F2 = 回基地。",
            "禁止快速加入 / 颜色兜底。请用测试夹 09 跑识别，不要从看板启动。",
        ):
            lbl = QLabel(text)
            lbl.setWordWrap(True)
            lbl.setObjectName("hintLabel")
            bl.addWidget(lbl)
        row = QHBoxLayout()
        row.addWidget(QLabel("房间名前缀"))
        self.cmb_hitch_prefix = QComboBox()
        self.cmb_hitch_prefix.addItem("搜 3", "3")
        self.cmb_hitch_prefix.addItem("搜 4", "4")
        row.addWidget(self.cmb_hitch_prefix)
        row.addStretch()
        bl.addLayout(row)
        exact_row = QHBoxLayout()
        exact_row.addWidget(QLabel("精确关卡过滤"))
        self.txt_hitch_exact = QLineEdit()
        self.txt_hitch_exact.setPlaceholderText("后续拓展")
        self.txt_hitch_exact.setEnabled(False)
        exact_row.addWidget(self.txt_hitch_exact)
        tag = QLabel("后续拓展")
        tag.setObjectName("warnHint")
        exact_row.addWidget(tag)
        bl.addLayout(exact_row)
        lay.addWidget(box)

    def _build_lab_page(self, lay: QVBoxLayout) -> None:
        box = QGroupBox("实验室（CLI · 看板不启动）")
        bl = QVBoxLayout(box)
        for text in (
            "入口只有 tools/lab_run.py 或测试夹 bat。",
            "测试夹 bat 读控制室保存的技能/关卡/英雄模式/羁绊（看板 user_settings.json）。",
            "看板不启动实验室。实验室与看板抢 ShuaBao.live.lock，禁止双 LIVE。",
            "preset 与 lab_focus 只存在内存 overlay，不得写入用户默认。",
        ):
            lbl = QLabel(text)
            lbl.setWordWrap(True)
            lbl.setObjectName("hintLabel")
            bl.addWidget(lbl)
        lay.addWidget(box)

    def _rebuild_bond_plan(self) -> None:
        while self.bond_plan_lay.count():
            item = self.bond_plan_lay.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._bond_plan_boxes = {}
        route_id = self._shell_extras.get("attr_route") or "intelligence"
        route = ATTR_ROUTES.get(route_id) or {}
        rounds = [
            ("round1 必做", list(BOND_PRIORITY.get("round1_must") or [])),
            ("属性链", list(route.get("chain") or [])),
            ("生存", list(BOND_PRIORITY.get("round3_survival") or [])),
            ("必选急速", list(BOND_PRIORITY.get("must_take") or [])),
            ("第四轮选做", list(BOND_PRIORITY.get("round4_optional") or [])),
        ]
        inverted = set(self._shell_extras.get("bond_inverted") or [])
        scheme = set(self._effective_scheme_codes())
        for title, names in rounds:
            cap = QLabel(title)
            cap.setObjectName("sectionCap")
            self.bond_plan_lay.addWidget(cap)
            row = QWidget()
            grid = QGridLayout(row)
            grid.setContentsMargins(0, 0, 0, 0)
            col = 0
            for name in names:
                code = code_for_bond_name(str(name))
                if code:
                    box = QCheckBox(str(name))
                    box.setChecked(code in scheme and code not in inverted)
                    box.toggled.connect(lambda checked, c=code: self._on_plan_toggled(c, checked))
                    self._bond_plan_boxes[code] = box
                    grid.addWidget(box, col // 4, col % 4)
                else:
                    lbl = QLabel(f"{name}（仅知识，不能勾）")
                    lbl.setObjectName("hintLabel")
                    grid.addWidget(lbl, col // 4, col % 4)
                col += 1
            self.bond_plan_lay.addWidget(row)

    def _effective_scheme_codes(self) -> list[str]:
        scheme = [c for c in (self._shell_extras.get("bond_scheme") or []) if c in FETTER_LABELS]
        if not scheme:
            scheme = [c for c in (self.settings.cards or []) if c in FETTER_LABELS]
        return scheme[: BondCardGrid.MAX_BONDS]

    def _sync_bonds_from_scheme(self) -> None:
        inverted = set(self._shell_extras.get("bond_inverted") or [])
        effective = [c for c in self._effective_scheme_codes() if c not in inverted][: BondCardGrid.MAX_BONDS]
        self._syncing_bonds = True
        try:
            self.bond_grid.set_bonds(effective)
            for code, box in self._bond_plan_boxes.items():
                box.blockSignals(True)
                box.setChecked(code in effective)
                box.blockSignals(False)
        finally:
            self._syncing_bonds = False

    def _on_plan_toggled(self, code: str, checked: bool) -> None:
        if self._syncing_bonds:
            return
        inverted = [c for c in (self._shell_extras.get("bond_inverted") or []) if c in FETTER_LABELS]
        scheme = self._effective_scheme_codes()
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
        for rid, btn in self.route_buttons.items():
            if btn.isChecked():
                self._shell_extras["attr_route"] = rid
                break
        self._rebuild_bond_plan()
        self._schedule_auto_save()

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
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

    def _tray_stop(self) -> None:
        if self._is_running():
            self.runner.stop()

    def selected_mode_id(self) -> str:
        item = self.mode_list.currentItem()
        if item is None:
            return "normal_farm"
        return str(item.data(Qt.UserRole) or "normal_farm")

    def _on_mode_row_changed(self, _row: int) -> None:
        mode_id = self.selected_mode_id()
        self._shell_extras["selected_mode_id"] = mode_id
        idx = self._page_index.get(mode_id, 0)
        self.right_stack.setCurrentIndex(idx)
        self._refresh_chrome()

    def _is_running(self) -> bool:
        return bool(self.worker_thread and self.worker_thread.isRunning())

    def _refresh_chrome(self) -> None:
        if not hasattr(self, "btn_main"):
            return
        spec = get_spec(self.selected_mode_id())
        running = self._is_running()
        self.mode_list.setEnabled(not running)
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
        learn = "学习开" if self.chk_learn.isChecked() else "真机"
        self.lbl_summary.setText(f"{spec.label} · {stage} · {diff} · 技能{skill} · {learn}")

    def _refresh_precheck(self) -> None:
        mode_id = self.selected_mode_id()
        if not desktop_may_start(mode_id):
            self.lbl_precheck.setText("预检 ● 红")
            self.lbl_precheck.setToolTip("运行方式未验证，零输入")
            self.lbl_precheck.setStyleSheet("color:#b91c1c;")
            return
        if live_lock_busy(self.app_data) and not self._is_running():
            self.lbl_precheck.setText("预检 ● 红")
            self.lbl_precheck.setToolTip("live.lock 被占用")
            self.lbl_precheck.setStyleSheet("color:#b91c1c;")
            return
        if not self.chk_learn.isChecked() and not _is_admin():
            self.lbl_precheck.setText("预检 ● 黄")
            self.lbl_precheck.setToolTip("可学习；真机需要管理员")
            self.lbl_precheck.setStyleSheet("color:#b45309;")
            return
        self.lbl_precheck.setText("预检 ● 绿")
        self.lbl_precheck.setToolTip("可启动")
        self.lbl_precheck.setStyleSheet("color:#15803d;")

    def _refresh_progress(self) -> None:
        cycle = int(self.spn_cycle_num.value()) if hasattr(self, "spn_cycle_num") else 0
        prog = progress_from_counts(self._game_count, cycle, running=self._is_running())
        self.lbl_games.setText(str(prog.game_count) if prog.cycle_num <= 0 else f"{prog.game_count}/{prog.cycle_num}")
        self.lbl_games_cap.setText(prog.label)

    def _poll_runtime(self) -> None:
        worker = self.worker_thread
        if worker is None or worker.mediator is None:
            return
        self._game_count = int(getattr(worker.mediator, "game_count", 0) or 0)
        self._refresh_progress()

    def _update_hero_visibility(self):
        self.hero_options.setVisible(bool(self.cmb_mode.currentData()))
        self._refresh_chrome()

    def _refresh_skill_title(self):
        names = self.skill_grid.selected_names()
        self.grp_skill.setTitle(
            f"技能（已选 {'、'.join(names)}）" if names else "技能（未选 · 只刷新不学习）"
        )

    def _set_skill_panel_expanded(self, expanded: bool):
        self.skill_grid.setVisible(expanded)
        self._refresh_skill_title()

    def _on_skills_changed(self):
        names = self.skill_grid.selected_names()
        self._refresh_skill_title()
        if len(names) == self.skill_grid.MAX_SKILLS and self.grp_skill.isChecked():
            self.grp_skill.setChecked(False)
        self._refresh_summary()
        self._schedule_auto_save()

    def _refresh_archive_title(self):
        levels = self.archive_grid.get_levels()
        if levels:
            shown = "、".join(f"{SKILL_LABELS.get(code, code)}{lv}" for code, lv in levels.items())
            self.grp_archive.setTitle(f"技能存档等级（{shown}）")
        else:
            self.grp_archive.setTitle("技能存档等级（未填=未知 · 走最保守前置）")

    def _set_archive_panel_expanded(self, expanded: bool):
        self.archive_grid.setVisible(expanded)
        self._refresh_archive_title()

    def _on_archive_levels_changed(self):
        self._refresh_archive_title()
        self._schedule_auto_save()

    def _refresh_bond_title(self):
        names = self.bond_grid.selected_names()
        self.grp_bond.setTitle(
            f"羁绊（已选 {'、'.join(names)}）" if names else "羁绊（未选 · 只刷新后暂时隐藏）"
        )

    def _set_bond_panel_expanded(self, expanded: bool):
        self.bond_grid.setVisible(expanded)
        self._refresh_bond_title()

    def _on_bonds_changed(self):
        if not self._syncing_bonds:
            selected = self.bond_grid.get_bonds()
            scheme = self._effective_scheme_codes() or list(selected)
            self._shell_extras["bond_scheme"] = scheme
            self._shell_extras["bond_inverted"] = [c for c in scheme if c not in selected]
        names = self.bond_grid.selected_names()
        self._refresh_bond_title()
        if len(names) == self.bond_grid.MAX_BONDS and self.grp_bond.isChecked():
            self.grp_bond.setChecked(False)
        self._schedule_auto_save()

    def _on_negative_changed(self):
        self._schedule_auto_save()

    def _wire_auto_save(self):
        self.txt_stage_target.textChanged.connect(self._schedule_auto_save)
        self.cmb_mode.currentIndexChanged.connect(self._schedule_auto_save)
        self.cmb_reputation.currentIndexChanged.connect(self._schedule_auto_save)
        self.spn_reputation_level.valueChanged.connect(self._schedule_auto_save)
        self.spn_cycle_num.valueChanged.connect(self._schedule_auto_save)
        self.chk_learn.toggled.connect(self._schedule_auto_save)
        self.chk_secret_realm.toggled.connect(self._schedule_auto_save)
        self.spn_treasure_num.valueChanged.connect(self._schedule_auto_save)
        self.spn_gambling_time.valueChanged.connect(self._schedule_auto_save)
        self.spn_dragon_ball.valueChanged.connect(self._schedule_auto_save)
        self.chk_longzhu_multi.toggled.connect(self._schedule_auto_save)
        self.chk_longzhu_in_game.toggled.connect(self._schedule_auto_save)
        self.chk_learn.toggled.connect(self._refresh_chrome)
        self.spn_cycle_num.valueChanged.connect(self._refresh_progress)
        self.txt_stage_target.textChanged.connect(self._refresh_summary)

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
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def log(self, text: str, level: str = "info"):
        text = str(text)
        log_level = {"error": logging.ERROR, "warn": logging.WARNING}.get(level, logging.INFO)
        LOGGER.log(log_level, text)
        self.lbl_latest.setText(text)
        self.txt_log.appendPlainText(text)

    def update_status(self, running: bool, phase: str, game_count: int):
        self._game_count = int(game_count or 0)
        if running:
            self.lbl_run_status.setText("运行中")
            self.lbl_run_status.setToolTip(f"当前阶段：{phase}")
            self.lbl_run_status.setProperty("state", "running")
        else:
            self.lbl_run_status.setText("空闲")
            self.lbl_run_status.setToolTip("未运行")
            self.lbl_run_status.setProperty("state", "idle")
        self.lbl_run_status.setStyle(self.lbl_run_status.style())
        self._refresh_chrome()

    def load_local_settings(self, silent: bool = False):
        user_path = self.user_settings_path()
        try:
            if user_path.is_file():
                raw = json.loads(user_path.read_text(encoding="utf-8"))
                extras = raw.pop("_shell", {}) if isinstance(raw, dict) else {}
                if isinstance(extras, dict):
                    self._shell_extras.update(extras)
                settings = Settings._from_dict(raw if isinstance(raw, dict) else {})
                source = "user_settings.json"
            elif FACTORY_SETTINGS.is_file():
                settings = Settings.load(FACTORY_SETTINGS)
                source = FACTORY_SETTINGS.name
            else:
                return
            self.apply_settings_to_ui(settings)
            if not silent:
                self.log(f"[加载] 已载入 {source}")
        except Exception as exc:
            self.log(f"[加载失败] {exc}", "error")

    def apply_settings_to_ui(self, settings: Settings):
        self.settings = copy.deepcopy(settings)
        targets = [item.strip() for item in (settings.stage_targets or []) if item.strip()]
        target = targets[0] if targets else f"1-{max(1, int(settings.stage2))}"
        self.txt_stage_target.setText(target)
        self.chk_learn.setChecked(bool(settings.dry_run))
        self.chk_secret_realm.setChecked(settings.auto_secret_realm)
        self.spn_cycle_num.setValue(int(settings.cycle_num or 0))
        self.spn_treasure_num.setValue(int(settings.treasure_num or 0))
        self.spn_gambling_time.setValue(int(settings.auto_gambling_time or 0))
        self.spn_dragon_ball.setValue(int(settings.dragon_ball_count or 7))
        self.chk_longzhu_multi.setChecked(bool(settings.find_longzhu_where_multi_game))
        self.chk_longzhu_in_game.setChecked(bool(settings.find_longzhu_in_game))
        self.skill_grid.set_skills(settings.skills or [])
        self.archive_grid.set_levels(dict(getattr(settings, "skill_archive_levels", None) or {}))
        card_stems = []
        for item in settings.cards or []:
            text = str(item or "").strip()
            if text:
                card_stems.append(Path(text).stem)
        if not self._shell_extras.get("bond_scheme"):
            self._shell_extras["bond_scheme"] = list(card_stems)
        self._syncing_bonds = True
        try:
            self.bond_grid.set_bonds(card_stems)
        finally:
            self._syncing_bonds = False
        self._rebuild_bond_plan()
        self.grp_negative.set_allowed(list(getattr(settings, "treasure_allow_negative", []) or []))
        mode_index = self.cmb_mode.findData(bool(settings.auto_reputation))
        self.cmb_mode.setCurrentIndex(mode_index if mode_index >= 0 else 0)
        rep_type = max(1, min(6, int(getattr(settings, "reputation_type", 1) or 1)))
        rep_index = self.cmb_reputation.findData(rep_type)
        self.cmb_reputation.setCurrentIndex(rep_index if rep_index >= 0 else 0)
        self.spn_reputation_level.setValue(max(1, min(5, int(getattr(settings, "reputation_level", 1) or 1))))
        route = str(self._shell_extras.get("attr_route") or "intelligence")
        if route in self.route_buttons:
            self.route_buttons[route].setChecked(True)
        self._refresh_custom_builds_combo()
        self._update_hero_visibility()

    def collect_settings_from_ui(self) -> Settings:
        target = self.txt_stage_target.text().strip()
        match = re.fullmatch(r"([1-9]\d*)-([1-9]\d*)", target)
        if match is None:
            raise ValueError("目标关卡必须是“章节-关卡”，例如 1-10")
        skills = self.skill_grid.get_skills()
        if not skills:
            self.log("[设置] 未选择技能：技能面板只刷新并放弃，不会学习其他技能", "info")
        _, stage_index = (int(value) for value in match.groups())
        settings = copy.deepcopy(self.settings)
        settings.game_mode = 0
        settings.stage1 = stage_index
        settings.stage2 = stage_index
        settings.stage_targets = [target]
        settings.auto_create_room = True
        settings.room_name = ""
        settings.room_password = ""
        settings.new_room_every_times = False
        settings.lab_focus = ""
        settings.dry_run = self.chk_learn.isChecked()
        settings.auto_secret_realm = self.chk_secret_realm.isChecked()
        settings.cycle_num = int(self.spn_cycle_num.value())
        settings.treasure_num = int(self.spn_treasure_num.value())
        settings.auto_gambling_time = int(self.spn_gambling_time.value())
        settings.dragon_ball_count = int(self.spn_dragon_ball.value())
        settings.find_longzhu_where_multi_game = self.chk_longzhu_multi.isChecked()
        settings.find_longzhu_in_game = self.chk_longzhu_in_game.isChecked()
        settings.skills = skills
        settings.skill_archive_levels = self.archive_grid.get_levels()
        settings.cards = self.bond_grid.get_bonds()
        if not settings.cards:
            self.log("[设置] 未选择羁绊：羁绊面板只刷新，刷不动就暂时隐藏", "info")
        settings.treasure_allow_negative = self.grp_negative.get_allowed()
        if settings.treasure_allow_negative:
            self.log("[设置] 已放行特殊宝物：" + "、".join(settings.treasure_allow_negative), "warn")
        settings.auto_reputation = bool(self.cmb_mode.currentData())
        settings.reputation_type = int(self.cmb_reputation.currentData() or 3)
        settings.reputation_level = self.spn_reputation_level.value()
        return settings

    def official_build(self, build_id: str) -> dict | None:
        for item in OFFICIAL_BUILDS:
            if str(item.get("id")) == build_id:
                return item
        for item in self._shell_extras.get("custom_builds") or []:
            if isinstance(item, dict) and str(item.get("id") or item.get("name")) == build_id:
                return item
        return None

    def apply_official_build(self, build_id: str, *, confirm: bool = True) -> bool:
        build = self.official_build(build_id)
        if not build:
            return False
        new_skills = [str(c) for c in (build.get("skills") or [])][: SkillCardGrid.MAX_SKILLS]
        new_cards = [str(c) for c in (build.get("cards") or [])][: BondCardGrid.MAX_BONDS]
        new_rep = int(build.get("reputation_type") or 3)
        if confirm:
            cur = self.collect_settings_from_ui()
            diff = (
                f"技能：{'/'.join(skill_display_name(c) for c in cur.skills) or '无'}"
                f" → {'/'.join(skill_display_name(c) for c in new_skills) or '无'}\n"
                f"羁绊：{'/'.join(bond_display_name(c) for c in cur.cards) or '无'}"
                f" → {'/'.join(bond_display_name(c) for c in new_cards) or '无'}\n"
                f"声望：{cur.reputation_type} → {new_rep}"
            )
            answer = QMessageBox.question(
                self, "应用流派", f"将用「{build.get('name') or build_id}」覆盖当前设置：\n\n{diff}",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return False
        self.skill_grid.set_skills(new_skills)
        self._shell_extras["bond_scheme"] = list(new_cards)
        self._shell_extras["bond_inverted"] = []
        self._sync_bonds_from_scheme()
        idx = self.cmb_reputation.findData(new_rep)
        if idx >= 0:
            self.cmb_reputation.setCurrentIndex(idx)
        self._refresh_chrome()
        return True

    def set_bond_scheme(self, codes: list[str], inverted: list[str] | None = None) -> None:
        self._shell_extras["bond_scheme"] = [c for c in codes if c in FETTER_LABELS]
        if inverted is not None:
            self._shell_extras["bond_inverted"] = [c for c in inverted if c in FETTER_LABELS]
        self._sync_bonds_from_scheme()

    def effective_bond_codes(self) -> list[str]:
        inverted = set(self._shell_extras.get("bond_inverted") or [])
        return [c for c in self._effective_scheme_codes() if c not in inverted][: BondCardGrid.MAX_BONDS]

    def _on_apply_build_clicked(self) -> None:
        build_id = str(self.cmb_build.currentData() or "")
        if not build_id:
            return
        self.apply_official_build(build_id, confirm=True)

    def _on_save_custom_build(self) -> None:
        name, ok = QInputDialog.getText(self, "保存自定义组合", "方案名称")
        if not ok or not str(name).strip():
            return
        try:
            settings = self.collect_settings_from_ui()
        except ValueError as exc:
            QMessageBox.warning(self, "请检查运行设置", str(exc))
            return
        item = {
            "id": f"custom:{name.strip()}",
            "name": name.strip(),
            "skills": list(settings.skills),
            "cards": list(settings.cards),
            "reputation_type": int(settings.reputation_type),
        }
        builds = [b for b in (self._shell_extras.get("custom_builds") or []) if isinstance(b, dict)]
        builds = [b for b in builds if b.get("id") != item["id"] and b.get("name") != item["name"]]
        builds.append(item)
        self._shell_extras["custom_builds"] = builds
        self._refresh_custom_builds_combo()
        self._schedule_auto_save()

    def _refresh_custom_builds_combo(self) -> None:
        current = str(self.cmb_build.currentData() or "")
        while self.cmb_build.count() > 1 + len(OFFICIAL_BUILDS):
            self.cmb_build.removeItem(self.cmb_build.count() - 1)
        for item in self._shell_extras.get("custom_builds") or []:
            if isinstance(item, dict):
                self.cmb_build.addItem(str(item.get("name") or item.get("id")), str(item.get("id") or ""))
        idx = self.cmb_build.findData(current)
        if idx >= 0:
            self.cmb_build.setCurrentIndex(idx)

    def toggle_run(self):
        if self._is_running():
            self.log("[操作] 正在停止任务……", "warn")
            self.runner.stop()
            return
        mode_id = self.selected_mode_id()
        if not desktop_may_start(mode_id):
            self.log(f"[阻断] {mode_id} 未验证，零输入", "error")
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
        if settings.dry_run:
            self.log("[学习模式] 本次只观察记录、不实操", "warn")
        else:
            if not _is_admin():
                QMessageBox.critical(
                    self, "需要管理员权限",
                    "游戏和 KK 对战平台通常以管理员身份运行。请以管理员身份再开始。",
                )
                self.log("[阻断] 真机运行需要管理员权限", "error")
                return
            answer = QMessageBox.warning(
                self, "确认开始真机运行",
                "学习模式已关闭，程序将向游戏窗口发送真实鼠标和键盘输入。\n\n确认开始吗？",
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
        worker.signals.log_emitted.connect(self.log)
        worker.signals.status_changed.connect(self.update_status)
        worker.finished.connect(self._on_worker_finished)
        worker.start()
        self._status_timer.start()
        self.hide()

    def _on_worker_finished(self) -> None:
        self._status_timer.stop()
        self.runner.release_after_finish()
        count = 0
        if self.worker_thread is not None:
            count = int(getattr(self.worker_thread.mediator, "game_count", 0) or 0)
        self.worker_thread = None
        self.update_status(False, "空闲", count)
        self.showNormal()
        self.raise_()

    def closeEvent(self, event):
        worker = getattr(self, "worker_thread", None)
        if worker is not None and worker.isRunning():
            self.runner.stop()
            if not worker.wait(15000):
                self.log("[关闭] 任务线程未在 15s 内退出，继续等待（不强制杀掉）", "warn")
                worker.wait(60000)
        try:
            settings = self.collect_settings_from_ui()
            self.settings = copy.deepcopy(settings)
            self._write_user_bundle(settings)
        except Exception:
            pass
        self.runner.release_after_finish()
        event.accept()
