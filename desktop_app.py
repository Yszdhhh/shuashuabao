#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""刷刷宝（ShuaBao）· 重生魔兽刷刷刷单人挂机桌面面板。"""

from __future__ import annotations

import builtins
import json
import logging
import os
import re
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

# 确保 src 在 PATH 中
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "src"))

from gamescript import __version__
from gamescript.settings import Settings

APP_NAME = "刷刷宝"
APP_ID = "ShuaBao"  # 文件/目录用 ASCII，避免非 ASCII 路径在打包与命令行工具里出问题
# 用户可见版本：0.1 → V0.1（桌面快捷方式 / 窗口标题都用这个）
APP_VERSION_LABEL = f"V{__version__}" if not str(__version__).upper().startswith("V") else str(__version__)
APP_DATA = Path(os.environ.get("LOCALAPPDATA", ROOT)) / APP_ID
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


def _load_json_labels(file_path: Path) -> dict[str, str]:
    if file_path.is_file():
        try:
            return json.loads(file_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _load_json_doc(file_path: Path) -> dict:
    if file_path.is_file():
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


# 静态扫描资源
SKILL_STEMS = _stems(ROOT / "assets" / "Images" / "skills") or [
    "asj", "asjg", "assx", "bsxx", "byj", "dcw", "dz", "hbj",
    "hq", "jf", "jq", "ljf", "pg", "sdl", "tl", "ys",
]
SKILL_LABELS = _load_json_labels(ROOT / "config" / "skill_labels.json")
SKILL_ICON_DIR = ROOT / "assets" / "Images" / "skills"

# 技能说明（悬停提示）与流派预设；缺说明的显示"说明待补"，绝不编游戏数值。
_SKILL_META_DOC = _load_json_doc(ROOT / "config" / "skill_meta.json")
SKILL_META: dict[str, dict] = _SKILL_META_DOC.get("skills") or {}
SKILL_PRESETS: list[dict] = _SKILL_META_DOC.get("presets") or [
    {"name": "奥术箭流", "codes": ["asj", "asjg", "assx", "jq"], "hint": ""},
    {"name": "冰法控场", "codes": ["hbj", "bsxx", "jq", "pg"], "hint": ""},
    {"name": "天雷狂轰", "codes": ["tl", "sdl", "dcw", "jq"], "hint": ""},
]

# 负面宝物（拿了会断资源/断成长）；默认一张都不选，逐张勾选才放行。
_CHOICE_POLICY_DOC = _load_json_doc(ROOT / "config" / "choice_policy.json")
NEGATIVE_TREASURES: list[str] = (
    (_CHOICE_POLICY_DOC.get("treasure") or {}).get("negative_names") or []
)


class LogSignal(QObject):
    log_emitted = Signal(str, str)  # (text, level)
    status_changed = Signal(bool, str, int)  # (running, phase, game_count)


class MediatorWorker(QThread):
    def __init__(
        self,
        settings: Settings,
        root_dir: Path,
        max_steps: int | None = None,
        incident_dir: str | Path | None = None,
    ):
        super().__init__()
        self.settings = settings
        self.root_dir = root_dir
        self.max_steps = max_steps
        # S0.5：incident 目录（默认 %LocalAppData%/ShuaBao/incidents；
        # 测试传 tempdir），异常/超时/恢复/未知/Fail-Closed 落图证据
        self.incident_dir = Path(incident_dir) if incident_dir else APP_DATA / "incidents"
        self.signals = LogSignal()
        self.mediator = None
        self._stop_requested = False

    def run(self):
        try:
            from gamescript.mediator import Mediator, Phase
        except Exception as e:
            self.signals.log_emitted.emit(f"[错误] 无法加载 Mediator 自动化引擎: {e}", "error")
            self.signals.status_changed.emit(False, "错误", 0)
            return

        if self._stop_requested:
            self.signals.log_emitted.emit("[启动] 已请求停止，取消本次启动", "info")
            self.signals.status_changed.emit(False, "空闲", 0)
            return

        self.signals.status_changed.emit(True, "就绪", 0)
        target = (self.settings.stage_targets or [
            f"{self.settings.stage1}-{self.settings.stage2}"
        ])[0]
        width, height = (self.settings.window_size or [1600, 900])[:2]
        mode = "英雄" if self.settings.auto_reputation else "普通"
        difficulty = (
            f"{self.settings.reputation_type}-{self.settings.reputation_level}"
            if self.settings.auto_reputation else "-"
        )
        learn = "开启" if self.settings.dry_run else "关闭"
        self.signals.log_emitted.emit(
            f"[启动] {APP_VERSION_LABEL} 刷图任务启动 | 学习模式={learn} | "
            f"关卡={target} | 模式={mode} | 难度={difficulty} | "
            f"分辨率={width}x{height} | 技能={self.settings.skills}",
            "info"
        )
        if self.settings.dry_run:
            self.signals.log_emitted.emit(
                "[学习模式] 只观察/记录，不向游戏发送真实点击；"
                f"观测写入 {APP_DATA / 'learning'}",
                "info",
            )

        real_print = builtins.print

        def hook_print(*args, **kwargs):
            text = " ".join(str(x) for x in args)
            if sys.stdout is not None:
                real_print(*args, **kwargs)
            log_type = "info"
            if "失败" in text or "中断" in text or "错误" in text or "timeout" in text:
                log_type = "error"
            elif "警告" in text or "miss" in text:
                log_type = "warn"
            self.signals.log_emitted.emit(text, log_type)

            if "phase " in text:
                try:
                    parts = text.split("phase ")
                    if len(parts) > 1:
                        p_str = parts[1].split()[0]
                        p_name = p_str.split("→")[-1].strip()
                        self.signals.status_changed.emit(True, p_name, getattr(self.mediator, "game_count", 0))
                except Exception:
                    pass

        builtins.print = hook_print

        try:
            self.mediator = Mediator(self.settings, self.root_dir, incident_dir=self.incident_dir)
            self._start_trace()
            self.mediator.run(max_steps=self.max_steps)
        except Exception as e:
            self.signals.log_emitted.emit(f"[异常] 任务异常退出: {e}", "error")
        finally:
            # 正常结束与异常结束都关闭 trace 句柄，保证最后一行 JSONL 完整落盘
            if self.mediator is not None:
                self.mediator.set_trace(None)
            builtins.print = real_print
            count = getattr(self.mediator, "game_count", 0) if self.mediator else 0
            self.signals.status_changed.emit(False, "空闲", count)
            self.signals.log_emitted.emit("[结束] 任务运行结束", "info")

    def _start_trace(self) -> str | None:
        """桌面自动 trace：%LocalAppData%/ShuaBao/YYYYMMDD/trace_<ts>.jsonl。

        按当天日期分目录，不写安装目录；启动失败只降级为无 trace，不阻断任务。
        """
        try:
            now = datetime.now()
            trace_dir = APP_DATA / now.strftime("%Y%m%d")
            trace_path = trace_dir / f"trace_{now.strftime('%Y%m%d_%H%M%S')}.jsonl"
            self.mediator.set_trace(str(trace_path))
            self.signals.log_emitted.emit(f"[Trace] 自动 trace: {trace_path}", "info")
            return str(trace_path)
        except Exception as e:
            self.signals.log_emitted.emit(f"[Trace] 无法开启 trace: {e}", "error")
            return None

    def stop(self):
        self._stop_requested = True
        if self.mediator:
            self.mediator.stop()


class SkillCardGrid(QWidget):
    """中文技能卡片多选网格：显示中文名，内部存拼音短码，最多 4 个。"""

    MAX_SKILLS = 4
    skills_changed = Signal()

    def __init__(self, skill_stems: list[str], skill_labels: dict[str, str], parent=None):
        super().__init__(parent)
        self.skill_stems = skill_stems
        self.skill_labels = skill_labels
        self.cards: dict[str, QPushButton] = {}
        self._selected: list[str] = []
        self._init_ui()

    CARD_QSS = (
        "QPushButton { background:#ffffff; border:1px solid #d7dee8; border-radius:8px;"
        " color:#334155; font-size:12px; padding:6px 4px; text-align:center; }"
        "QPushButton:hover { border:1px solid #0ea5e9; color:#0f172a; background:#f0f9ff; }"
        "QPushButton:checked { background:#e0f2fe; border:2px solid #0284c7; color:#0c4a6e;"
        " font-weight:bold; }"
    )

    def _tooltip_for(self, code: str) -> str:
        """悬停说明：中文名 + 卡面效果。没有实机证据的显示待补，不编数值。"""
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

        # 流派预设（一键套用；悬停看配置说明）
        preset = QHBoxLayout()
        preset.setSpacing(6)
        preset_label = QLabel("流派")
        preset_label.setObjectName("hintLabel")
        preset.addWidget(preset_label)
        for item in SKILL_PRESETS:
            codes = [str(c) for c in (item.get("codes") or [])]
            btn = QPushButton(str(item.get("name") or "预设"))
            names = "、".join(
                (SKILL_META.get(c) or {}).get("label") or self.skill_labels.get(c, c)
                for c in codes
            )
            tip = str(item.get("hint") or "").strip()
            btn.setToolTip(f"{names}<br/><span style='color:#8b9bb4'>{tip}</span>" if tip else names)
            btn.clicked.connect(lambda _=False, c=codes: self.set_skills(c))
            preset.addWidget(btn)
        clear_btn = QPushButton("清空")
        clear_btn.setToolTip("清空全部技能：技能面板将只刷新并放弃，不学任何技能")
        clear_btn.clicked.connect(lambda: self.set_skills([]))
        preset.addWidget(clear_btn)
        preset.addStretch()
        lay.addLayout(preset)

        # 卡片网格：图标 + 中文名 + 悬停说明
        grid = QGridLayout()
        grid.setSpacing(8)
        for idx, code in enumerate(self.skill_stems):
            meta = SKILL_META.get(code) or {}
            cn = meta.get("label") or self.skill_labels.get(code, "未命名技能")
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
        else:
            if code in self._selected:
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
        return [self.skill_labels.get(code, "未命名技能") for code in self._selected]

    def _refresh_cards(self):
        order = {code: index + 1 for index, code in enumerate(self._selected)}
        for code, btn in self.cards.items():
            meta = SKILL_META.get(code) or {}
            name = meta.get("label") or self.skill_labels.get(code, "未命名技能")
            btn.setText(f"{order[code]}. {name}" if code in order else name)


class NegativeTreasureGroup(QGroupBox):
    """负面宝物放行区（默认折叠、默认全不勾）。

    这些宝物拿了会断资源/断成长（如「获得一笔金币，之后不再获得金币」）。
    默认一张都不选；用户在这里逐张打勾才允许脚本选它。放行是逐卡的，
    不是全局开关——语义与 gamescript.choice_policy.is_negative_treasure 一致。
    """

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
        # 标题只有这一个写入源：外部改前缀请传 prefix，不要在外面 setTitle，
        # 否则分组自己刷新标题时（勾选/折叠）会把外部前缀冲掉。
        self._prefix = prefix
        self._boxes: dict[str, QCheckBox] = {}
        self.setCheckable(True)
        self.setChecked(False)
        self.setToolTip(
            "这些宝物拿了会断资源或断成长，默认不选。\n"
            "只有在这里打勾的那一张才会被脚本选择；不勾的永远不选。"
        )
        lay = QVBoxLayout(self)
        lay.setSpacing(6)
        lay.setContentsMargins(0, 0, 0, 0)

        # 说明与勾选框放同一个容器：收起时整块隐藏，不留空盒子。
        self.body = QWidget()
        body_lay = QVBoxLayout(self.body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(6)

        note = QLabel("勾选 = 允许选这张；不勾 = 永不选。逐张生效。")
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
            empty = QLabel("未配置负面宝物名单（config/choice_policy.json）")
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
            body = f"负面宝物放行（已放行 {len(allowed)}：{'、'.join(allowed)}）"
        else:
            body = "负面宝物放行（默认全不选）"
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
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION_LABEL} · 重生魔兽刷刷刷")
        # 首页精简后默认窗口更矮；技能/宝物/日志各自独立折叠，靠滚动区承接
        self.resize(480, 420)
        self.setMinimumSize(440, 360)

        self.settings = Settings()
        self.worker_thread: MediatorWorker | None = None

        # 设置自动保存（防抖 800ms；关闭/运行时也会落盘）
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(800)
        self._save_timer.timeout.connect(self._save_settings_now)

        self._setup_style()
        self._build_ui()
        self.load_local_settings(silent=True)
        self._wire_auto_save()

    def _setup_style(self):
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f4f7fb;
            }
            QWidget {
                background-color: #f4f7fb;
                color: #1e293b;
                font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
                font-size: 12px;
            }
            QGroupBox {
                background-color: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 10px;
                margin-top: 12px;
                padding: 14px 12px 10px 12px;
                font-weight: bold;
                font-size: 13px;
                color: #0f172a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 12px;
                padding: 2px 8px;
                background-color: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 6px;
                color: #334155;
            }
            QLabel {
                background-color: transparent;
            }
            QLabel#brandTitle {
                font-size: 22px;
                font-weight: bold;
                color: #0f172a;
            }
            QLabel#brandSub {
                font-size: 11px;
                color: #94a3b8;
            }
            QLabel#hintLabel {
                color: #64748b;
                font-size: 11px;
            }
            QLabel#warnHint {
                color: #b45309;
                font-size: 11px;
            }
            QLabel#statusLine {
                color: #64748b;
                font-size: 11px;
            }
            QLabel#gamesCount {
                font-size: 20px;
                font-weight: bold;
                color: #0284c7;
            }
            QLabel#gamesCap {
                font-size: 10px;
                color: #94a3b8;
            }
            QLabel#statusPill {
                background-color: #e2e8f0;
                border: 1px solid #cbd5e1;
                border-radius: 11px;
                color: #64748b;
                font-weight: bold;
                padding: 3px 12px;
            }
            QLabel#statusPill[state="running"] {
                background-color: #dcfce7;
                border: 1px solid #86efac;
                color: #15803d;
            }
            QLabel#statusPill[state="stopping"] {
                background-color: #ffedd5;
                border: 1px solid #fdba74;
                color: #c2410c;
            }
            QCheckBox#chkLearn {
                color: #b45309;
                font-weight: bold;
            }
            QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
                background-color: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                color: #0f172a;
                padding: 5px 8px;
                min-height: 22px;
            }
            QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
                border: 1px solid #0284c7;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QCheckBox {
                background-color: transparent;
                spacing: 6px;
            }
            QCheckBox::indicator {
                width: 14px;
                height: 14px;
                border: 1px solid #cbd5e1;
                border-radius: 3px;
                background: #ffffff;
            }
            QCheckBox::indicator:checked {
                background-color: #0284c7;
                border: 1px solid #0369a1;
            }
            QPushButton {
                background-color: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                color: #334155;
                padding: 6px 12px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #f1f5f9;
                border: 1px solid #94a3b8;
                color: #0f172a;
            }
            QPushButton#btnStart {
                background-color: #0284c7;
                border: none;
                color: #ffffff;
                font-size: 15px;
                font-weight: bold;
                padding: 12px;
                border-radius: 8px;
            }
            QPushButton#btnStart:hover {
                background-color: #0369a1;
            }
            QPushButton#btnStop {
                background-color: #dc2626;
                border: none;
                color: #ffffff;
                font-size: 15px;
                font-weight: bold;
                padding: 12px;
                border-radius: 8px;
            }
            QPushButton#btnStop:hover {
                background-color: #b91c1c;
            }
            QPlainTextEdit {
                background-color: #f8fafc;
                border: 1px solid #e2e8f0;
                border-radius: 6px;
                color: #334155;
                font-family: "Consolas", monospace;
                font-size: 11px;
            }
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 8px;
                margin: 2px;
            }
            QScrollBar::handle:vertical {
                background: #cbd5e1;
                border-radius: 4px;
                min-height: 24px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
            QFrame#homeDivider {
                color: #e2e8f0;
                max-height: 1px;
            }
        """)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        main_layout = QVBoxLayout(content)
        main_layout.setContentsMargins(16, 14, 16, 14)
        main_layout.setSpacing(10)
        main_layout.setAlignment(Qt.AlignTop)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        # —— 首页：品牌 + 状态 ——
        header = QHBoxLayout()
        header.setSpacing(10)
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title = QLabel(f"{APP_NAME} {APP_VERSION_LABEL}")
        title.setObjectName("brandTitle")
        subtitle = QLabel("重生魔兽刷刷刷 · 单人挂机")
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
        games_cap = QLabel("已完成")
        games_cap.setAlignment(Qt.AlignRight)
        games_cap.setObjectName("gamesCap")
        games_box.addWidget(self.lbl_games)
        games_box.addWidget(games_cap)
        header.addLayout(games_box)
        main_layout.addLayout(header)

        divider = QFrame()
        divider.setObjectName("homeDivider")
        divider.setFrameShape(QFrame.HLine)
        main_layout.addWidget(divider)

        # —— 首页：只留跑起来必需的项 ——
        core = QGroupBox("运行")
        core_layout = QVBoxLayout(core)
        core_layout.setSpacing(8)

        stage_row = QHBoxLayout()
        stage_row.setSpacing(8)
        stage_row.addWidget(QLabel("关卡"))
        self.txt_stage_target = QLineEdit("1-10")
        self.txt_stage_target.setObjectName("stageTarget")
        self.txt_stage_target.setPlaceholderText("例如 1-10")
        self.txt_stage_target.setMaximumWidth(100)
        stage_row.addWidget(self.txt_stage_target)
        stage_row.addSpacing(8)
        stage_row.addWidget(QLabel("模式"))
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItem("普通", False)
        self.cmb_mode.addItem("英雄", True)
        self.cmb_mode.setItemData(
            1,
            "当前开放录像与实机证据完整的肯瑞托 1–5 级。",
            Qt.ToolTipRole,
        )
        self.cmb_mode.setMinimumWidth(88)
        stage_row.addWidget(self.cmb_mode)
        stage_row.addStretch()
        core_layout.addLayout(stage_row)

        self.hero_options = QWidget()
        hero_row = QHBoxLayout(self.hero_options)
        hero_row.setContentsMargins(0, 0, 0, 0)
        hero_row.setSpacing(8)
        hero_row.addWidget(QLabel("阵营"))
        self.cmb_reputation = QComboBox()
        for name, faction_id in (
            ("黑锋骑士团", 1),
            ("银色北伐军", 2),
            ("肯瑞托", 3),
            ("探险者协会", 4),
            ("元素领主", 5),
            ("守护巨龙", 6),
        ):
            self.cmb_reputation.addItem(name, faction_id)
        self.cmb_reputation.setCurrentIndex(self.cmb_reputation.findData(3))
        hero_row.addWidget(self.cmb_reputation)
        hero_row.addWidget(QLabel("难度"))
        self.spn_reputation_level = QSpinBox()
        self.spn_reputation_level.setRange(1, 5)
        hero_row.addWidget(self.spn_reputation_level)
        hero_row.addStretch()
        core_layout.addWidget(self.hero_options)

        self.chk_learn = QCheckBox("学习模式（只观察记录，不实操）")
        self.chk_learn.setChecked(False)
        self.chk_learn.setObjectName("chkLearn")
        self.chk_learn.setToolTip(
            "开启后：脚本只识别画面、记录决策与面板观测，不向游戏发送真实点击。\n"
            "记录写入本机 %LocalAppData%\\ShuaBao\\learning\\，供后续自适应调参。\n"
            "要自动创房/刷图请保持关闭。"
        )
        # 兼容旧属性名（测试/外部脚本可能仍引用 chk_dry）
        self.chk_dry = self.chk_learn
        self.chk_secret_realm = QCheckBox("胜利后自动挑战秘境")
        self.chk_secret_realm.setToolTip(
            "开启后：胜利结算进入挑战广场，右键大秘境并确认；秘境失败后退出并重开下一局。"
        )
        core_layout.addWidget(self.chk_learn)
        core_layout.addWidget(self.chk_secret_realm)
        main_layout.addWidget(core)

        self.btn_main = QPushButton("开始运行")
        self.btn_main.setObjectName("btnStart")
        self.btn_main.setMinimumHeight(44)
        self.btn_main.clicked.connect(self.toggle_run)
        main_layout.addWidget(self.btn_main)

        self.lbl_latest = QLabel("就绪 · Shift+F12 紧急停止")
        self.lbl_latest.setWordWrap(True)
        self.lbl_latest.setObjectName("statusLine")
        main_layout.addWidget(self.lbl_latest)

        # —— 技能：独立可勾选分组，默认收起 ——
        self.grp_skill = QGroupBox("技能")
        self.grp_skill.setCheckable(True)
        self.grp_skill.setChecked(False)
        self.grp_skill.setToolTip(
            "点勾展开。选满 4 个自动收起。\n"
            "只学勾选的技能：都没出现时刷新，刷完仍没有就放弃。"
        )
        skill_layout = QVBoxLayout(self.grp_skill)
        self.skill_grid = SkillCardGrid(SKILL_STEMS, SKILL_LABELS)
        skill_layout.addWidget(self.skill_grid)
        self.skill_grid.setVisible(False)
        self.grp_skill.toggled.connect(self._set_skill_panel_expanded)
        self.skill_grid.skills_changed.connect(self._on_skills_changed)
        main_layout.addWidget(self.grp_skill)

        # —— 宝物：独立可勾选分组（负面宝物放行），默认收起 ——
        self.grp_negative = NegativeTreasureGroup(NEGATIVE_TREASURES)
        self.grp_negative.changed.connect(self._on_negative_changed)
        main_layout.addWidget(self.grp_negative)

        # —— 运行日志：独立折叠，默认收起 ——
        self.grp_details = QGroupBox("运行日志")
        self.grp_details.setCheckable(True)
        self.grp_details.setChecked(False)
        details_layout = QVBoxLayout(self.grp_details)
        self.txt_log = QPlainTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumHeight(140)
        self.txt_log.setVisible(False)
        self.grp_details.toggled.connect(self.txt_log.setVisible)
        details_layout.addWidget(self.txt_log)
        main_layout.addWidget(self.grp_details)

        self.cmb_mode.currentIndexChanged.connect(self._update_hero_visibility)
        self._update_hero_visibility()

    def _update_hero_visibility(self):
        self.hero_options.setVisible(bool(self.cmb_mode.currentData()))

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
        # 选满 4 个自动收起，保持面板简洁（仅在用户勾选过程中触发）
        if len(names) == self.skill_grid.MAX_SKILLS and self.grp_skill.isChecked():
            self.grp_skill.setChecked(False)
        self._schedule_auto_save()

    def _wire_auto_save(self):
        """控件变更 → 防抖自动保存（下次打开沿用上次设置）。"""
        self.txt_stage_target.textChanged.connect(self._schedule_auto_save)
        self.cmb_mode.currentIndexChanged.connect(self._schedule_auto_save)
        self.cmb_reputation.currentIndexChanged.connect(self._schedule_auto_save)
        self.spn_reputation_level.valueChanged.connect(self._schedule_auto_save)
        self.chk_learn.toggled.connect(self._schedule_auto_save)
        self.chk_secret_realm.toggled.connect(self._schedule_auto_save)

    def _on_negative_changed(self):
        self._schedule_auto_save()

    def _schedule_auto_save(self):
        try:
            self._save_timer.start()
        except Exception:
            pass

    def _save_settings_now(self):
        try:
            settings = self.collect_settings_from_ui()
            settings.save(ROOT / "config" / "default_settings.json")
        except (ValueError, Exception):
            # 非法/未完成配置（如空技能）不落盘，保留上次有效配置
            pass

    def log(self, text: str, level: str = "info"):
        text = str(text)
        log_level = {
            "error": logging.ERROR,
            "warn": logging.WARNING,
        }.get(level, logging.INFO)
        LOGGER.log(log_level, text)
        self.lbl_latest.setText(text)
        self.txt_log.appendPlainText(text)

    def update_status(self, running: bool, phase: str, game_count: int):
        if running:
            self.lbl_run_status.setText("运行中")
            self.lbl_run_status.setToolTip(f"当前阶段：{phase}")
            self.lbl_run_status.setProperty("state", "running")
            self.btn_main.setText("停止运行")
            self.btn_main.setObjectName("btnStop")
        else:
            self.lbl_run_status.setText("空闲")
            self.lbl_run_status.setToolTip("未运行")
            self.lbl_run_status.setProperty("state", "idle")
            self.btn_main.setText("开始运行")
            self.btn_main.setObjectName("btnStart")
        # 属性选择器换色需要重新求值样式
        for widget in (self.lbl_run_status, self.btn_main):
            widget.setStyle(widget.style())
        self.lbl_games.setText(str(game_count))

    def load_local_settings(self, silent: bool = False):
        config_file = ROOT / "config" / "default_settings.json"
        if not config_file.is_file():
            return
        try:
            settings = Settings.load(config_file)
            self.apply_settings_to_ui(settings)
            if not silent:
                self.log(f"[加载] 已载入 {config_file.name}")
        except Exception as exc:
            self.log(f"[加载失败] {exc}", "error")

    def apply_settings_to_ui(self, settings: Settings):
        self.settings = settings
        targets = [item.strip() for item in (settings.stage_targets or []) if item.strip()]
        target = targets[0] if targets else f"1-{max(1, int(settings.stage2))}"
        self.txt_stage_target.setText(target)
        self.chk_learn.setChecked(bool(settings.dry_run))
        self.chk_secret_realm.setChecked(settings.auto_secret_realm)
        self.skill_grid.set_skills(settings.skills or [])
        self.grp_negative.set_allowed(
            list(getattr(settings, "treasure_allow_negative", []) or [])
        )

        mode_index = self.cmb_mode.findData(bool(settings.auto_reputation))
        self.cmb_mode.setCurrentIndex(mode_index if mode_index >= 0 else 0)
        rep_type = max(1, min(6, int(getattr(settings, "reputation_type", 1) or 1)))
        rep_index = self.cmb_reputation.findData(rep_type)
        self.cmb_reputation.setCurrentIndex(rep_index if rep_index >= 0 else 0)
        self.spn_reputation_level.setValue(
            max(1, min(5, int(getattr(settings, "reputation_level", 1) or 1)))
        )
        self._update_hero_visibility()

    def collect_settings_from_ui(self) -> Settings:
        target = self.txt_stage_target.text().strip()
        match = re.fullmatch(r"([1-9]\d*)-([1-9]\d*)", target)
        if match is None:
            raise ValueError("目标关卡必须是“章节-关卡”，例如 1-10")

        skills = self.skill_grid.get_skills()
        # 技能可选：未配置时刷新后放弃，绝不学习配置外技能。
        if not skills:
            self.log("[设置] 未选择技能：技能面板只刷新并放弃，不会学习其他技能", "info")

        _, stage_index = (int(value) for value in match.groups())
        settings = self.settings
        settings.game_mode = 0
        settings.stage1 = stage_index
        settings.stage2 = stage_index
        settings.stage_targets = [target]
        settings.auto_create_room = True
        # The current control panel intentionally has no room-name/password
        # controls.  Do not let values from an older config re-enable the
        # experimental room-dialog fill path.
        settings.room_name = ""
        settings.room_password = ""
        settings.new_room_every_times = False
        # dry_run 底层字段 = 学习模式（观察记录、零真实输入）
        settings.dry_run = self.chk_learn.isChecked()
        settings.auto_secret_realm = self.chk_secret_realm.isChecked()
        settings.skills = skills
        # 负面宝物：只放行用户逐张勾选的；没勾就是一张都不选。
        settings.treasure_allow_negative = self.grp_negative.get_allowed()
        if settings.treasure_allow_negative:
            self.log(
                "[设置] 已放行负面宝物："
                + "、".join(settings.treasure_allow_negative),
                "warn",
            )
        settings.auto_reputation = bool(self.cmb_mode.currentData())
        settings.reputation_type = int(self.cmb_reputation.currentData() or 3)
        settings.reputation_level = self.spn_reputation_level.value()
        return settings

    def toggle_run(self):
        if self.worker_thread and self.worker_thread.isRunning():
            self.log("[操作] 正在停止任务……", "warn")
            self.worker_thread.stop()
            return

        try:
            settings = self.collect_settings_from_ui()
        except ValueError as exc:
            QMessageBox.warning(self, "请检查运行设置", str(exc))
            return
        # 运行前落盘，保证下次打开沿用本次设置
        try:
            settings.save(ROOT / "config" / "default_settings.json")
        except Exception:
            pass
        target = settings.stage_targets[0] if settings.stage_targets else f"{settings.stage1}-{settings.stage2}"
        width, height = (settings.window_size or [1600, 900])[:2]
        self.log(
            f"[启动配置] 版本={APP_VERSION_LABEL} 关卡={target} 分辨率={width}x{height} "
            f"秘境={'开启' if settings.auto_secret_realm else '关闭'} "
            f"学习模式={'开启' if settings.dry_run else '关闭'} "
            f"配置源={ROOT / 'config' / 'default_settings.json'}"
        )

        if settings.dry_run:
            self.log(
                "[学习模式] 本次只观察记录、不实操；可手动玩，脚本对照记录面板与决策",
                "warn",
            )
        else:
            is_admin = False
            try:
                import ctypes
                is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
            except Exception:
                pass

            if not is_admin:
                QMessageBox.critical(
                    self,
                    "需要管理员权限",
                    "游戏和 KK 对战平台通常以管理员身份运行，普通权限程序无法可靠点击它们。\n\n"
                    f"请关闭本窗口，右键 {APP_ID}.exe（或桌面「{APP_NAME} {APP_VERSION_LABEL}」快捷方式），"
                    "选择“以管理员身份运行”后再开始。",
                )
                self.log("[阻断] 真机运行需要管理员权限", "error")
                return

            answer = QMessageBox.warning(
                self,
                "确认开始真机运行",
                "学习模式已关闭，程序将向游戏窗口发送真实鼠标和键盘输入。\n\n"
                "确认开始吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return

        self.worker_thread = MediatorWorker(settings, ROOT)
        self.worker_thread.signals.log_emitted.connect(self.log)
        self.worker_thread.signals.status_changed.connect(self.update_status)
        self.worker_thread.start()

    def closeEvent(self, event):
        """Stop the worker before destroying the window (thread-safety)."""
        worker = getattr(self, "worker_thread", None)
        if worker is not None and worker.isRunning():
            worker.stop()
            if not worker.wait(3000):
                self.log("[关闭] 任务线程未在 3s 内退出，强制结束", "warn")
                worker.terminate()
                worker.wait(1000)
        # 关闭前持久化当前设置
        try:
            settings = self.collect_settings_from_ui()
            settings.save(ROOT / "config" / "default_settings.json")
        except Exception:
            pass
        event.accept()

_INSTANCE_LOCK: QLockFile | None = None


def _handle_unhandled_exception(exc_type, exc_value, exc_traceback):
    LOGGER.error(
        "未处理异常",
        exc_info=(exc_type, exc_value, exc_traceback),
    )
    QMessageBox.critical(
        None,
        f"{APP_NAME} 启动失败",
        f"程序遇到异常，详情已写入：\n{LOG_FILE}\n\n{exc_value}",
    )


def main():
    global _INSTANCE_LOCK
    app = QApplication(sys.argv)
    sys.excepthook = _handle_unhandled_exception

    _INSTANCE_LOCK = QLockFile(str(APP_DATA / f"{APP_ID}.lock"))
    if not _INSTANCE_LOCK.tryLock(100):
        QMessageBox.information(None, APP_NAME, "程序已经在运行。")
        return

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
