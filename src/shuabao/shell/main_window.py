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
from shuabao.shell.dual_launch_widget import DualLaunchBoxWidget
from shuabao.shell.pet_hud import FloatingPetHud
from shuabao.shell.theme_styles import get_qss
from shuabao.shell.wizard_dialog import GameStyleWizardDialog

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

# user_settings.json 顶层 _shell_schema：user bundle 的 shell 结构版本。
# 2 = 新格式：attr_route 恒为 list，且只由属性线 UI 显式勾选写入（可证明确是用户选择）。
# 缺失/1 = 旧格式：attr_route 可能是字符串 "intelligence"/"strength"/"agility"——
# 那是旧版默认值或从 cards 推断的隐式值，与显式选择无法区分，加载时需一次性清空。
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


def skill_display_name(code: str) -> str:
    meta = SKILL_META.get(code) or {}
    return str(meta.get("label") or SKILL_LABELS.get(code, code))


def bond_display_name(code: str) -> str:
    return FETTER_LABELS.get(code, code)


def code_for_bond_name(name: str) -> str | None:
    return FETTER_NAME_TO_CODE.get(name)


# factory/no-user-scheme 的默认羁绊勾选集 = bond_priority.round1_must
# （祝福/成长/经济/贪婪/挑战）。round1_must 有短码用短码，无短码保留中文名
# （与基础卡组勾选框的 code 形态一致）。全部可编辑，可任意取消/清空。
DEFAULT_BOND_CODES: list[str] = [
    code_for_bond_name(str(name)) or str(name)
    for name in (BOND_PRIORITY.get("round1_must") or [])
    if str(name).strip()
]




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

    CARD_QSS = (
        "QPushButton { background:#151d2e; border:1px solid #243048; border-radius:8px;"
        " color:#cbd5e1; font-size:12px; padding:6px 4px; text-align:center; }"
        "QPushButton:hover { border:1px solid #38bdf8; color:#ffffff; background:#1e293b; }"
        "QPushButton:checked { background:qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0c4a6e, stop:1 #075985);"
        " border:2px solid #38bdf8; color:#f0f9ff; font-weight:bold; }"
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
        self.hint = QLabel(self._mode_hint_text())
        self.hint.setWordWrap(True)
        self.hint.setObjectName("hintLabel")
        lay.addWidget(self.hint)
        row = QHBoxLayout()
        clear_btn = QPushButton("清空")
        clear_btn.setToolTip("清空全部技能：技能面板将直接关闭/隐藏，不刷新、不放弃技能点，不学任何技能")
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


class SkillArchiveLevelGrid(QWidget):
    """技能存档等级：每系一个数字框，0=未知。"""

    MAX_LEVEL = 50
    levels_changed = Signal()

    def __init__(self, stems: list[str], labels: dict[str, str], parent=None):
        super().__init__(parent)
        self.boxes: dict[str, QSpinBox] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        grid = QGridLayout() if "QGridLayout" in globals() else QVBoxLayout()
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
        self.app_data = (app_data or Path.home() / "AppData" / "Local" / APP_NAME).resolve()
        self.app_data.mkdir(parents=True, exist_ok=True)
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION_LABEL} · 重生魔兽刷刷刷")
        self.resize(980, 760)
        self.setMinimumSize(820, 640)
        self.current_theme = "light"
        self.setStyleSheet(get_qss(self.current_theme))
        self.pet_hud = FloatingPetHud()
        self.pet_hud.hud_restored.connect(self._restore_from_pet_hud)
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

        self._setup_style()
        self._build_ui()
        self.overlay_hud = OverlayHud()
        self._setup_tray()
        self.load_local_settings(silent=True)
        self._wire_auto_save()
        self._show_mode_choice()

    def _setup_style(self):
        self.current_theme = "light"
        self.setStyleSheet(get_qss("light"))
    def _open_quick_wizard(self) -> None:
        from shuabao.shell.wizard_dialog import GameStyleWizardDialog
        wizard = GameStyleWizardDialog(self)
        wizard.run_requested.connect(lambda p: self.toggle_run())
        wizard.advanced_requested.connect(lambda p: self.showNormal())
        wizard.exec()

    def toggle_theme(self) -> None:
        self.current_theme = "light" if getattr(self, "current_theme", "dark") == "dark" else "dark"
        self.setStyleSheet(get_qss(self.current_theme))

    def _restore_from_pet_hud(self) -> None:
        if getattr(self, "pet_hud", None):
            self.pet_hud.hide()
        self.showNormal()
        self.activateWindow()

    def toggle_theme(self) -> None:
        self.current_theme = "light" if getattr(self, "current_theme", "dark") == "dark" else "dark"
        self.setStyleSheet(get_qss(self.current_theme))

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
        subtitle = QLabel("控制中心 · 先选运行方式，再配置任务")
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
        btn_wizard = QPushButton("🧙‍♂️ 快速开局向导")
        btn_wizard.setStyleSheet("background-color: #f1d48a; color: #78350f; font-weight: bold; border: 1px solid #d97706; padding: 4px 10px; border-radius: 6px;")
        btn_wizard.clicked.connect(self._open_quick_wizard)
        header.addWidget(btn_wizard)
        btn_theme = QPushButton("🌓 切换主题")
        btn_theme.clicked.connect(self.toggle_theme)
        header.addWidget(btn_theme)
        games_box = QHBoxLayout()
        self.lbl_games = QLabel("今日局数: 0")
        self.lbl_games_cap = QLabel("/ 100")
        self.lbl_games_cap.setObjectName("gamesCap")
        games_box.addWidget(self.lbl_games)
        games_box.addWidget(self.lbl_games_cap)
        header.addLayout(games_box)
        outer.addLayout(header)

        body = QVBoxLayout()
        body.setContentsMargins(12, 0, 12, 0)
        body.setSpacing(10)

        mode_box = QGroupBox("选择运行方式")
        self.mode_box = mode_box
        mode_layout = QVBoxLayout(mode_box)
        primary_row = QHBoxLayout()
        self.primary_mode_group = QButtonGroup(self)
        self.btn_solo_mode = QPushButton("🎮  单人刷图（快速建房）")
        self.btn_hitch_mode = QPushButton("🚗  蹭车 / 跟车（大厅进房）")
        for button in (self.btn_solo_mode, self.btn_hitch_mode):
            button.setCheckable(True)
            button.setMinimumHeight(56)
            button.setMinimumWidth(320)
            button.setStyleSheet("""
                QPushButton {
                    background-color: #2563eb;
                    color: white;
                    border: 2px solid #60a5fa;
                }
            """)
            self.primary_mode_group.addButton(button)
            primary_row.addWidget(button, 1)
        mode_layout.addLayout(primary_row)
        mode_layout.addStretch()

        self.btn_solo_mode.clicked.connect(lambda: self._select_mode("normal_farm"))
        self.btn_hitch_mode.clicked.connect(lambda: self._select_mode("lobby_hitch"))
        body.addWidget(mode_box)

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
        self.btn_choose_mode = QPushButton("切换运行方式")
        self.btn_choose_mode.clicked.connect(self._show_mode_choice)
        foot.addWidget(self.btn_choose_mode)
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
        run_box, run_lay = self._section("运行", "先选主线与关卡；默认刷完票")
        stage_row = QHBoxLayout()
        stage_row.addWidget(QLabel("主线"))
        self.cmb_chapter = QComboBox()
        self.cmb_chapter.setObjectName("stageChapter")
        for chapter, _count, label in MAINLINE_STAGES:
            self.cmb_chapter.addItem(MAINLINE_DISPLAY.get(chapter, label), chapter)
        self.cmb_stage = QComboBox()
        self.cmb_stage.setObjectName("stageIndex")
        self.txt_stage_target = QLineEdit("1-10")
        self.txt_stage_target.setObjectName("stageTarget")
        self.txt_stage_target.setVisible(False)
        self.txt_stage_target.setToolTip("由主线/关卡下拉生成，也可手改已开放的关")
        self._filling_stage = False
        self._refill_stage_combo(keep_stage=10)
        self.cmb_chapter.currentIndexChanged.connect(self._on_chapter_changed)
        self.cmb_stage.currentIndexChanged.connect(self._on_stage_combo_changed)
        self.txt_stage_target.textChanged.connect(self._on_stage_target_edited)
        stage_row.addWidget(self.cmb_chapter)
        stage_row.addWidget(QLabel("关卡"))
        stage_row.addWidget(self.cmb_stage)
        stage_row.addWidget(QLabel("关卡难度"))
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItem("普通", False)
        self.cmb_mode.addItem("英雄", True)
        stage_row.addWidget(self.cmb_mode)
        stage_row.addWidget(QLabel("局数"))
        self.spn_cycle_num = QSpinBox()
        self.spn_cycle_num.setRange(0, 999)
        self.spn_cycle_num.setSpecialValueText("手动停")
        self.spn_cycle_num.setToolTip("0 = 直到手动停止，不画满条")
        stage_row.addWidget(self.spn_cycle_num)
        stage_row.addStretch()
        run_lay.addLayout(stage_row)
        lay.addWidget(run_box)

        # 官方推荐构筑
        build_box = QGroupBox("✨ 官方推荐挂机构筑（点击直接一键套用）")
        build_box.setStyleSheet("QGroupBox { font-size: 14px; font-weight: bold; }")
        build_layout = QVBoxLayout(build_box)
        btn_grid = QGridLayout()
        row, col = 0, 0
        for b in OFFICIAL_BUILDS:
            bid = str(b.get("id") or "")
            bname = str(b.get("name") or "")
            btn = QPushButton(bname)
            btn.setCheckable(True)
            btn.setMinimumHeight(44)
            btn.setStyleSheet("""
                QPushButton {
                    font-size: 13px;
                    font-weight: 500;
                    padding: 6px 12px;
                    border-radius: 6px;
                    text-align: left;
                }
                QPushButton:checked {
                    background-color: #059669;
                    color: white;
                    font-weight: bold;
                    border: 2px solid #34d399;
                }
            """)
            self._build_btn_group.addButton(btn)
            self._build_btn_map[bid] = btn
            btn.clicked.connect(lambda checked, _bid=bid: self._apply_build(_bid))
            btn_grid.addWidget(btn, row, col)
            col += 1
            if col >= 2:
                col = 0
                row += 1
        build_layout.addLayout(btn_grid)
        lay.addWidget(build_box)
        core = QWidget()
        core_layout = QVBoxLayout(core)
        core_layout.setContentsMargins(0, 0, 0, 0)
        self.hero_options = QWidget()
        self.hero_options.setVisible(False)
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
        self.chk_secret_realm = QCheckBox("秘境")
        self.secret_options = QLabel("已启用秘境：按当前默认路线执行")
        self.secret_options.setObjectName("hintLabel")
        self.secret_options.setVisible(False)
        self.chk_secret_realm.toggled.connect(self.secret_options.setVisible)
        core_layout.addWidget(self.chk_learn)
        core_layout.addWidget(self.chk_secret_realm)
        core_layout.addWidget(self.secret_options)
        run_lay.addWidget(core)

        save_row = QHBoxLayout()
        self.btn_save_settings = QPushButton("保存设置")
        self.btn_save_settings.setObjectName("btnSaveSettings")
        self.btn_save_settings.clicked.connect(self._on_save_settings_clicked)
        save_row.addWidget(self.btn_save_settings)
        save_row.addStretch()
        run_lay.addLayout(save_row)
        lay.addWidget(run_box)

        quick_box, quick_lay = self._section("② 常用搭配", "官方推荐流派一键套用")
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
        self.btn_save_custom = QPushButton("自定义搭配…")
        self.btn_save_custom.clicked.connect(self._on_save_custom_build)
        combo_row.addWidget(self.btn_save_custom)
        quick_lay.addLayout(combo_row)
        lay.addWidget(quick_box)

        self.grp_advanced = QGroupBox("高级配置（手动技能 / 存档 / 羁绊 / 房间 / 诊断）")
        self.grp_advanced.setCheckable(True)
        self.grp_advanced.setChecked(False)
        advanced_layout = QVBoxLayout(self.grp_advanced)
        self.advanced_host = QWidget()
        adv_lay = QVBoxLayout(self.advanced_host)
        adv_lay.setContentsMargins(0, 0, 0, 0)

        room_box = QGroupBox("房间设置（默认：游戏结束后在原房间继续）")
        self.grp_room_settings = room_box
        room_box.setCheckable(True)
        room_box.setChecked(False)
        room_layout = QHBoxLayout(room_box)
        self.chk_auto_create_room = QCheckBox("自动创建房间")
        room_layout.addWidget(self.chk_auto_create_room)
        room_layout.addWidget(QLabel("房名"))
        self.txt_room_name = QLineEdit()
        self.txt_room_name.setPlaceholderText("留空使用游戏默认")
        room_layout.addWidget(self.txt_room_name, 1)
        room_layout.addWidget(QLabel("密码"))
        self.txt_room_password = QLineEdit()
        self.txt_room_password.setEchoMode(QLineEdit.Password)
        self.txt_room_password.setPlaceholderText("默认不显示")
        room_layout.addWidget(self.txt_room_password, 1)
        self.cmb_room_reuse = QComboBox()
        self.cmb_room_reuse.addItem("复用原房间", False)
        self.cmb_room_reuse.addItem("每局新建房间", True)
        room_layout.addWidget(self.cmb_room_reuse)
        room_box.toggled.connect(lambda expanded: [child.setVisible(expanded) for child in room_box.findChildren(QWidget) if child is not room_box])
        for child in room_box.findChildren(QWidget):
            child.setVisible(False)
        adv_lay.addWidget(room_box)

        skill_box, skill_lay = self._section("技能配置", "0=不自动学; 1-4=严格仅学已选")
        adj = QLabel("手动技能与存档等级")
        adj.setObjectName("sectionCap")
        skill_lay.addWidget(adj)
        self.grp_skill = QGroupBox("技能")
        self.grp_skill.setCheckable(True)
        self.grp_skill.setChecked(False)
        sl = QVBoxLayout(self.grp_skill)
        self.skill_grid = SkillCardGrid(SKILL_STEMS, SKILL_LABELS)
        sl.addWidget(self.skill_grid)
        self.skill_grid.setVisible(True)
        self.grp_skill.toggled.connect(self._set_skill_panel_expanded)
        self.skill_grid.skills_changed.connect(self._on_skills_changed)
        self.skill_grid.setVisible(False)
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
        adv_lay.addWidget(skill_box)

        bond_box, bond_lay = self._section("羁绊与卡包", "基础卡组默认生效；需要时再调整")
        route_row = QHBoxLayout()
        route_row.addWidget(QLabel("属性线"))
        self.route_buttons: dict[str, QCheckBox] = {}
        for row in ATTR_LINE_OPTIONS:
            rid = str(row.get("id") or "")
            btn = QCheckBox(str(row.get("label") or rid))
            self.route_buttons[rid] = btn
            btn.toggled.connect(self._on_attr_route_clicked)
            route_row.addWidget(btn)
        route_note = QLabel("属性线可多选。")
        route_note.setObjectName("hintLabel")
        route_row.addWidget(route_note)
        route_row.addStretch()
        bond_lay.addLayout(route_row)
        note = QLabel("无短码的高级卡组用中文名进白名单。EX 最终形态不进白名单。")
        note.setObjectName("hintLabel")
        note.setWordWrap(True)
        bond_lay.addWidget(note)
        self.bond_plan_host = QWidget()
        self.bond_plan_lay = QVBoxLayout(self.bond_plan_host)
        self.bond_plan_lay.setContentsMargins(0, 0, 0, 0)
        self._bond_plan_boxes: dict[str, QCheckBox] = {}
        self._advanced_pack_boxes: dict[str, QCheckBox] = {}
        self._rebuild_bond_plan()
        self.grp_bond_basic = QGroupBox("基础卡组（默认已启用；点击调整）")
        self.grp_bond_basic.setCheckable(True)
        self.grp_bond_basic.setChecked(False)
        basic_lay = QVBoxLayout(self.grp_bond_basic)
        basic_lay.addWidget(self.bond_plan_host)
        self.grp_bond_basic.toggled.connect(self.bond_plan_host.setVisible)
        self.bond_plan_host.setVisible(False)
        bond_lay.addWidget(self.grp_bond_basic)
        adv_lay.addWidget(bond_box)

        loot_box, loot_lay = self._section("宝物与资源", "特殊宝物默认全不放行")
        self.grp_negative = NegativeTreasureGroup(NEGATIVE_TREASURES)
        self.grp_negative.changed.connect(self._on_negative_changed)
        loot_lay.addWidget(self.grp_negative)

        gamble = QLabel("赌木（待验证 · 不可启动）")
        gamble.setObjectName("warnHint")
        gamble.setWordWrap(True)
        self.grp_gambling_mode = QGroupBox("高级模式 · 赌木")
        self.grp_gambling_mode.setCheckable(True)
        self.grp_gambling_mode.setChecked(False)
        gamble_lay = QVBoxLayout(self.grp_gambling_mode)
        gamble_lay.addWidget(gamble)
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
        gamble_lay.addLayout(g_row)
        self.grp_gambling_mode.toggled.connect(lambda expanded: [child.setVisible(expanded) for child in self.grp_gambling_mode.findChildren(QWidget) if child is not self.grp_gambling_mode])
        for child in self.grp_gambling_mode.findChildren(QWidget):
            child.setVisible(False)
        adv_lay.addWidget(self.grp_gambling_mode)

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

        pill = QLabel("吞噬丹与黑商（实验性 · 默认不执行自动操作）：bond_capacity 未实机验证连线，黑商/吞噬自动策略保持关断。")
        pill.setObjectName("warnHint")
        pill.setWordWrap(True)
        loot_lay.addWidget(pill)

        adv_lay.addWidget(loot_box)

        self._build_test_profiles(adv_lay)

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
        adv_lay.addWidget(self.grp_details)

        atlas = QLabel("图鉴入口：P2（本轮不做）。")
        atlas.setObjectName("hintLabel")
        adv_lay.addWidget(atlas)

        advanced_layout.addWidget(self.advanced_host)
        self.advanced_host.setVisible(False)
        self.grp_advanced.toggled.connect(self._set_advanced_expanded)

        lay.addWidget(self.grp_advanced)

        self.cmb_mode.currentIndexChanged.connect(self._update_hero_visibility)
        self._update_hero_visibility()

    def _build_test_profiles(self, lay: QVBoxLayout) -> None:
        box = QGroupBox("测试配置（仅配置，不自动启动）")
        row = QHBoxLayout(box)
        row.addWidget(QLabel("内置方案"))
        self.cmb_test_profile = QComboBox()
        self.cmb_test_profile.addItem("选择内置方案", None)
        try:
            self._test_profiles = load_test_profiles(TEST_PROFILES_PATH)
            profiles_available = True
        except (OSError, ValueError, json.JSONDecodeError):
            self._test_profiles = []
            profiles_available = False
            self.cmb_test_profile.addItem("内置方案不可用", None)
        for profile in self._test_profiles:
            self.cmb_test_profile.addItem(profile["name"], profile)
        row.addWidget(self.cmb_test_profile, 1)
        self.btn_apply_test_profile = QPushButton("查看差异并应用")
        self.btn_apply_test_profile.clicked.connect(self._on_apply_builtin_profile)
        self.btn_apply_test_profile.setEnabled(profiles_available)
        row.addWidget(self.btn_apply_test_profile)
        self.btn_import_test_profile = QPushButton("导入 JSON")
        self.btn_import_test_profile.clicked.connect(self._on_import_test_profile)
        row.addWidget(self.btn_import_test_profile)
        self.btn_export_test_profile = QPushButton("导出当前配置")
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
                f"将应用以下差异（学习模式保持当前选择）：\n\n{diff_text}\n\n导入不会自动启动。",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return False
        self.apply_settings_to_ui(updated)
        self._schedule_auto_save()
        self.log(f"[测试配置] 已应用 {document['name']}；未启动运行", "info")
        return True

    def _on_apply_builtin_profile(self) -> None:
        profile = self.cmb_test_profile.currentData()
        if not isinstance(profile, dict):
            QMessageBox.information(self, "测试配置", "请先选择一个内置方案。")
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
        self.log(f"[测试配置] 已导出到 {filename}（不含密码、学习模式）", "info")

    def _build_follow_page(self, lay: QVBoxLayout) -> None:
        box = QGroupBox("跟车（可启动）")
        bl = QVBoxLayout(box)
        switch = QPushButton("改为大厅找房蹭车")
        switch.clicked.connect(lambda: self._select_mode("lobby_hitch"))
        bl.addWidget(switch)
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
        box = QGroupBox("大厅找房蹭车（可启动）")
        bl = QVBoxLayout(box)
        switch = QPushButton("我已在房间，改为跟车")
        switch.clicked.connect(lambda: self._select_mode("follow_team"))
        bl.addWidget(switch)
        for text in (
            "只认 准备 / 已准备 / 取消准备。特殊房无「锁定」按钮；金/蓝两套只是颜色不同，识别以文字为主锚。",
            "F1 = 操作切回自身英雄。F2 = 回基地。",
            "已支持搜索 3 / 4 自动过滤密码房与满员房并自动进房准备。",
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
            "测试夹 bat 会读这份保存的技能/关卡/英雄模式/羁绊（看板 user_settings.json）。",
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
        self._advanced_pack_boxes = {}
        has_scheme = "bond_scheme" in self._shell_extras
        inverted = set(self._shell_extras.get("bond_inverted") or [])
        scheme = set(self._effective_scheme_codes())
        cap = QLabel("基础卡组（选择 / 反选）")
        cap.setObjectName("sectionCap")
        self.bond_plan_lay.addWidget(cap)
        tools = QHBoxLayout()
        btn_all = QPushButton("全选")
        btn_inv = QPushButton("反选")
        btn_all.clicked.connect(self._select_all_basic_pack)
        btn_inv.clicked.connect(self._invert_basic_pack)
        tools.addWidget(btn_all)
        tools.addWidget(btn_inv)
        tools.addStretch()
        tools_host = QWidget()
        tools_host.setLayout(tools)
        self.bond_plan_lay.addWidget(tools_host)
        row = QWidget()
        grid = QGridLayout(row)
        grid.setContentsMargins(0, 0, 0, 0)
        for col, name in enumerate(BASIC_PACK_NAMES):
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
        adv_cap = QLabel("高级卡组（后续可选；EX 不进白名单）")
        adv_cap.setObjectName("sectionCap")
        self.bond_plan_lay.addWidget(adv_cap)
        adv_row = QHBoxLayout()
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
        return code in FETTER_LABELS or code in getattr(self, "_bond_plan_boxes", {}) or code_for_bond_name(code) is not None

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
            # 隐式默认态（factory/no-user-scheme）：先把当前可见勾选集实体化为
            # 显式方案，再应用本次切换——取消一个默认不得连带取消其余默认。
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
        # 全选即写入显式完整方案：显式空卡组状态下按"全选"也必须全部生效。
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
        # 反选后的勾选集就是新方案（空方案 = 显式一张不选），保证 sync 不被旧键覆盖。
        self._shell_extras["bond_scheme"] = [
            code for code, box in self._bond_plan_boxes.items() if box.isChecked()
        ]
        inverted = [code for code, box in self._bond_plan_boxes.items() if not box.isChecked()]
        self._shell_extras["bond_inverted"] = inverted
        self._sync_bonds_from_scheme()
        self._schedule_auto_save()

    def _on_advanced_pack_toggled(self, pack_id: str, checked: bool) -> None:
        enabled = [str(x) for x in (self._shell_extras.get("advanced_packs") or []) if str(x)]
        if checked and pack_id not in enabled:
            enabled.append(pack_id)
        if not checked:
            enabled = [x for x in enabled if x != pack_id]
        self._shell_extras["advanced_packs"] = enabled
        self._schedule_auto_save()

    def _attr_line_tokens(self) -> list[str]:
        tokens: list[str] = []
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
                if token not in tokens:
                    tokens.append(token)
        return tokens

    def _advanced_pack_tokens(self) -> list[str]:
        enabled = set(self._shell_extras.get("advanced_packs") or [])
        banned = {"解放的圣剑", "帝炎", "法天象地"}
        tokens: list[str] = []
        for pack_id, spec in ADVANCED_PACKS.items():
            if pack_id not in enabled:
                continue
            banned.update(str(n) for n in (spec.get("exclude_ex") or []))
            for name in spec.get("cards") or []:
                text = str(name).strip()
                if not text or text in banned:
                    continue
                token = code_for_bond_name(text) or text
                if token not in tokens:
                    tokens.append(token)
        return tokens

    def assemble_whitelist_cards(self) -> list[str]:
        inverted = set(self._shell_extras.get("bond_inverted") or [])
        out: list[str] = []
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
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

    def _tray_stop(self) -> None:
        if self._is_running():
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
        self._refresh_chrome()

    def _show_mode_choice(self) -> None:
        self.mode_box.setVisible(True)
        self.right_stack.setVisible(False)
        self.footer.setVisible(False)
        self.btn_solo_mode.setEnabled(True)
        self.btn_hitch_mode.setEnabled(True)

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
        learn = "学习开" if self.chk_learn.isChecked() else "真机"
        self.lbl_summary.setText(f"{spec.label} · {stage} · {diff} · 技能{skill} · {learn}")

    def _refresh_precheck(self) -> None:
        mode_id = self.selected_mode_id()
        if not desktop_may_start(mode_id):
            self.lbl_precheck.setText("预检 ● 红")
            self.lbl_precheck.setToolTip("运行方式未验证，零输入")
            self.lbl_precheck.setStyleSheet("color:#f87171;")
            return
        if live_lock_busy(self.app_data) and not self._is_running():
            self.lbl_precheck.setText("预检 ● 红")
            self.lbl_precheck.setToolTip("live.lock 被占用")
            self.lbl_precheck.setStyleSheet("color:#f87171;")
            return
        if not self.chk_learn.isChecked() and not _is_admin():
            self.lbl_precheck.setText("预检 ● 黄")
            self.lbl_precheck.setToolTip("可学习；真机需要管理员")
            self.lbl_precheck.setStyleSheet("color:#fbbf24;")
            return
        self.lbl_precheck.setText("预检 ● 绿")
        self.lbl_precheck.setToolTip("可启动")
        self.lbl_precheck.setStyleSheet("color:#34d399;")

    def _refresh_progress(self) -> None:
        cycle = int(self.spn_cycle_num.value()) if hasattr(self, "spn_cycle_num") else 0
        prog = progress_from_counts(self._game_count, cycle, running=self._is_running())
        self.lbl_games.setText(str(prog.game_count) if prog.cycle_num <= 0 else f"{prog.game_count}/{prog.cycle_num}")
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

    def _update_hero_visibility(self):
        is_hero = bool(self.cmb_mode.currentData())
        self.hero_options.setVisible(is_hero)
        self._refresh_chrome()

    def _refresh_skill_title(self):
        count = len(self.skill_grid.get_skills())
        names = self.skill_grid.selected_names()
        if not names:
            self.grp_skill.setTitle("技能（未选 · 不学技能）")
        else:
            self.grp_skill.setTitle(f"技能（严格模式 {count}/4：{'、'.join(names)}）")

    def _set_advanced_expanded(self, expanded: bool):
        self.advanced_host.setVisible(expanded)

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
        self.chk_auto_create_room.toggled.connect(self._schedule_auto_save)
        self.txt_room_name.textChanged.connect(self._schedule_auto_save)
        self.txt_room_password.textChanged.connect(self._schedule_auto_save)
        self.cmb_room_reuse.currentIndexChanged.connect(self._schedule_auto_save)
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
        data["_shell_schema"] = SHELL_SCHEMA_VERSION
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def log(self, text: str, level: str = "info"):
        text = str(text)
        log_level = {"error": logging.ERROR, "warn": logging.WARNING}.get(level, logging.INFO)
        LOGGER.log(log_level, text)
        self.lbl_latest.setText(text)
        self.txt_log.appendPlainText(text)

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
            self.lbl_run_status.setToolTip(
                f"当前阶段：{self._runtime_phase} | OCR：{self._ocr_status}"
            )
            self.lbl_run_status.setProperty("state", "running")
        else:
            reason = str(terminal_reason or self._terminal_reason or "任务已停止").strip()
            self._terminal_reason = reason
            self._last_action = str(last_action or self._last_action)
            self.lbl_run_status.setText(f"已停止（{reason}）")
            self.lbl_run_status.setToolTip(
                f"终止原因：{reason} | 最后动作：{self._last_action or '无'}"
            )
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
                        # 旧 schema 一次性迁移：字符串型 attr_route 只可能是旧版默认
                        # 或从 cards 推断的隐式值（旧 UI 的显式勾选恒写 list），
                        # 无法与用户显式选择区分，视为隐式默认并清空。
                        # 不猜 cards 内容；带 _shell_schema 标记的新版数据原样保留。
                        route = extras.get("attr_route")
                        if isinstance(route, str):
                            extras["attr_route"] = []
                    self._shell_extras.update(extras)
                # 旧版错误持久化的 5+ 技能：警告观察原始 JSON 计数（不列技能名，
                # 避免泄露数据）；截断由 Settings._from_dict 解析边界统一执行。
                if isinstance(raw, dict):
                    raw_skills = raw.get("skills")
                    if isinstance(raw_skills, (list, tuple)) and len(raw_skills) > MAX_SELECTED_SKILLS:
                        self.log(
                            f"[加载] 已保存技能 {len(raw_skills)} 个超过上限 {MAX_SELECTED_SKILLS}，"
                            f"仅保留前 {MAX_SELECTED_SKILLS} 个（其余忽略）",
                            "warn",
                        )
                settings = Settings._from_dict(raw if isinstance(raw, dict) else {})
                source = "user_settings.json"
                # 无权威 _shell.bond_scheme 键且 cards 为空 = 无用户方案数据 →
                # 默认五张（round1_must）；缺 scheme 但 cards 非空 = 旧版显式
                # 历史选择，原样保留；显式 _shell.bond_scheme=[] = 显式空卡组。
                default_bond = (
                    "bond_scheme" not in self._shell_extras
                    and not (settings.cards or [])
                )
            elif FACTORY_SETTINGS.is_file():
                settings = Settings.load(FACTORY_SETTINGS)
                source = FACTORY_SETTINGS.name
                # 工厂默认 profile：无用户方案数据，基础卡组保持默认五张（round1_must）。
                default_bond = True
            else:
                return
            self.apply_settings_to_ui(settings, bond_default=default_bond)
            mode_id = str(self._shell_extras.get("selected_mode_id") or "normal_farm")
            self._select_mode(mode_id if mode_id in self._page_index else "normal_farm")
            if not silent:
                self.log(f"[加载] 已载入 {source}")
        except Exception as exc:
            self.log(f"[加载失败] {exc}", "error")

    def apply_settings_to_ui(self, settings: Settings, *, bond_default: bool = False):
        """把 Settings 铺到 UI。

        bond_default=True 仅用于工厂默认 profile 加载：cards 为空时表示"无方案数据"，
        基础卡组保持默认勾选 round1_must 五张（_shell_extras 不含 bond_scheme 键）。
        其余调用方把 cards=[] 视为显式空卡组——写入空 list 键，_rebuild_bond_plan
        不当作默认勾选。
        """
        self.settings = copy.deepcopy(settings)
        targets = [item.strip() for item in (settings.stage_targets or []) if item.strip()]
        target = targets[0] if targets else f"1-{max(1, int(settings.stage2))}"
        self._apply_stage_target(target)
        self.chk_learn.setChecked(bool(settings.dry_run))
        self.chk_secret_realm.setChecked(settings.auto_secret_realm)
        self.chk_auto_create_room.setChecked(bool(settings.auto_create_room))
        self.txt_room_name.setText(str(settings.room_name or ""))
        self.txt_room_password.setText(str(settings.room_password or ""))
        reuse_index = self.cmb_room_reuse.findData(bool(settings.new_room_every_times))
        self.cmb_room_reuse.setCurrentIndex(reuse_index if reuse_index >= 0 else 0)
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
        if card_stems:
            self._shell_extras["bond_scheme"] = list(card_stems)
            self._shell_extras["bond_inverted"] = [
                code for code in self._bond_plan_boxes if code not in set(card_stems)
            ]
        elif bond_default:
            # 默认 profile：无方案数据 → 键缺失 = 基础卡组默认全选。
            self._shell_extras.pop("bond_scheme", None)
            self._shell_extras.pop("bond_inverted", None)
        else:
            # 显式空卡组：空 list 键存在，_rebuild_bond_plan 视为"一张不选"。
            self._shell_extras["bond_scheme"] = []
            self._shell_extras["bond_inverted"] = []
        self._rebuild_bond_plan()
        self.grp_negative.set_allowed(list(getattr(settings, "treasure_allow_negative", []) or []))
        mode_index = self.cmb_mode.findData(bool(settings.auto_reputation))
        self.cmb_mode.setCurrentIndex(mode_index if mode_index >= 0 else 0)
        rep_type = max(1, min(6, int(getattr(settings, "reputation_type", 1) or 1)))
        rep_index = self.cmb_reputation.findData(rep_type)
        self.cmb_reputation.setCurrentIndex(rep_index if rep_index >= 0 else 0)
        self.spn_reputation_level.setValue(max(1, min(5, int(getattr(settings, "reputation_level", 1) or 1))))
        routes = self._shell_extras.get("attr_route") or []
        if isinstance(routes, str):
            routes = [routes]
        self._shell_extras["attr_route"] = routes
        for route, button in self.route_buttons.items():
            button.blockSignals(True)
            button.setChecked(route in routes)
            button.blockSignals(False)
        enabled = set(self._shell_extras.get("advanced_packs") or [])
        for pack_id, box in self._advanced_pack_boxes.items():
            box.blockSignals(True)
            box.setChecked(pack_id in enabled)
            box.blockSignals(False)
        self._sync_bonds_from_scheme()
        self._refresh_custom_builds_combo()
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
        if not skills:
            self.log("[设置] 未选择技能：技能面板直接关闭/隐藏，不刷新、不放弃技能点，不会学习其他技能", "info")
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
        settings.room_name = self.txt_room_name.text()
        settings.room_password = self.txt_room_password.text()
        settings.new_room_every_times = bool(self.cmb_room_reuse.currentData())
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
        settings.cards = self.assemble_whitelist_cards()
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
        new_cards = [str(c) for c in (build.get("cards") or [])]
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
        self._shell_extras["bond_inverted"] = [
            code for code in self._bond_plan_boxes if code not in set(new_cards)
        ]
        self._shell_extras["advanced_packs"] = []
        routes = self._shell_extras.get("attr_route") or []
        if isinstance(routes, str):
            routes = [routes]
        for route, button in self.route_buttons.items():
            button.blockSignals(True)
            button.setChecked(route in routes)
            button.blockSignals(False)
        for pack_id, box in self._advanced_pack_boxes.items():
            box.blockSignals(True)
            box.setChecked(False)
            box.blockSignals(False)
        self._sync_bonds_from_scheme()
        idx = self.cmb_reputation.findData(new_rep)
        if idx >= 0:
            self.cmb_reputation.setCurrentIndex(idx)
        self._refresh_chrome()
        return True

    def set_bond_scheme(self, codes: list[str], inverted: list[str] | None = None) -> None:
        self._shell_extras["bond_scheme"] = [c for c in codes if self._valid_scheme_code(c)]
        if inverted is not None:
            self._shell_extras["bond_inverted"] = [c for c in inverted if self._valid_scheme_code(c)]
        self._sync_bonds_from_scheme()

    def effective_bond_codes(self) -> list[str]:
        inverted = set(self._shell_extras.get("bond_inverted") or [])
        return [c for c in self._effective_scheme_codes() if c not in inverted]

    def _apply_build(self, build_id: str) -> None:
        if not build_id:
            return
        self.apply_official_build(build_id, confirm=False)

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
        worker.signals.status_updated.connect(self.update_status)
        worker.finished.connect(self._on_worker_finished)
        worker.start()
        self._status_timer.start()
        # CORE02：看板不再隐藏——窗口保持可见，状态栏「运行中」，主按钮由
        # _refresh_chrome 切换为「停止」；F12 或停止按钮可中断。
        self.log("[点火] 脚本运行中，看板保持显示；按 F12 或点击「停止」可中断", "warn")

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
                self.log("[关闭] 任务线程未在 15s 内退出，继续等待（不强制杀掉）", "warn")
                worker.wait(60000)
            if worker.isRunning():
                # worker 仍未退出：不关窗、不释放 live.lock、不强杀线程。
                # 保留窗口与锁，等待用户再次发起关闭（stop 已被再次请求）。
                self.log("[关闭] worker 仍在运行，窗口不关闭（live.lock 保留，不强制杀线程）", "warn")
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
