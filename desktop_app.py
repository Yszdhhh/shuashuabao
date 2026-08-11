#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GameScript-Local 单人挂机桌面面板。"""

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

from PySide6.QtCore import QLockFile, QObject, Qt, QThread, QTimer, Signal
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
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

# 确保 src 在 PATH 中
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "src"))

from gamescript.settings import Settings

APP_DATA = Path(os.environ.get("LOCALAPPDATA", ROOT)) / "GameScript-Local"
LOG_FILE = APP_DATA / "logs" / "GameScript.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
LOGGER = logging.getLogger("GameScript-Local")
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


# 静态扫描资源
SKILL_STEMS = _stems(ROOT / "assets" / "Images" / "skills") or [
    "asj", "asjg", "assx", "bsxx", "byj", "dcw", "dz", "hbj",
    "hq", "jf", "jq", "ljf", "pg", "sdl", "tl", "ys",
]
SKILL_LABELS = _load_json_labels(ROOT / "config" / "skill_labels.json")


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
        # S0.5：incident 目录（默认 %LocalAppData%/GameScript-Local/incidents；
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
        room = self.settings.room_name or "<空>"
        password = "已设置" if self.settings.room_password else "未设置"
        width, height = (self.settings.window_size or [1600, 900])[:2]
        self.signals.log_emitted.emit(
            f"[启动] 刷图任务启动 | Dry-run={self.settings.dry_run} | "
            f"关卡={target} | 房间={room} | 密码={password} | "
            f"分辨率={width}x{height} | 技能={self.settings.skills}",
            "info"
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
        """桌面自动 trace：%LocalAppData%/GameScript-Local/YYYYMMDD/trace_<ts>.jsonl。

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

    def _init_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        # 流派预设
        preset = QHBoxLayout()
        preset.addWidget(QLabel("流派预设:"))
        presets = [
            ("奥术箭流", ["asj", "asjg", "assx", "jq"]),
            ("冰法控场", ["hbj", "bsxx", "jq", "pg"]),
            ("天雷狂轰", ["tl", "sdl", "dcw", "jq"]),
            ("清空", []),
        ]
        for label, codes in presets:
            btn = QPushButton(label)
            btn.clicked.connect(lambda _=False, c=codes: self.set_skills(c))
            preset.addWidget(btn)
        preset.addStretch()
        lay.addLayout(preset)

        # 卡片网格
        grid = QGridLayout()
        grid.setSpacing(6)
        for idx, code in enumerate(self.skill_stems):
            cn = self.skill_labels.get(code, "未命名技能")
            btn = QPushButton(cn)
            btn.setCheckable(True)
            btn.setMinimumHeight(38)
            btn.setStyleSheet(
                "QPushButton { background:#0a101c; border:1px solid #243044; border-radius:6px;"
                " color:#cbd5e1; font-size:12px; padding:2px; }"
                "QPushButton:checked { background:#1e3a5f; border:2px solid #2563eb; color:#ffffff; }"
            )
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
            name = self.skill_labels.get(code, "未命名技能")
            btn.setText(f"{order[code]}. {name}" if code in order else name)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("重生魔兽刷刷刷 · 单人挂机助手")
        self.resize(520, 460)
        self.setMinimumSize(460, 420)

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
                background-color: #0b1220;
            }
            QWidget {
                background-color: #0b1220;
                color: #e8eef8;
                font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
                font-size: 12px;
            }
            QGroupBox {
                background-color: #151c2c;
                border: 1px solid #243044;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 14px;
                font-weight: bold;
                color: #60a5fa;
            }
            QLabel {
                background-color: transparent;
            }
            QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
                background-color: #0a101c;
                border: 1px solid #243044;
                border-radius: 4px;
                color: #ffffff;
                padding: 4px 6px;
            }
            QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
                border: 1px solid #2563eb;
            }
            QComboBox::drop-down {
                border: none;
            }
            QCheckBox {
                background-color: transparent;
                spacing: 6px;
            }
            QCheckBox::indicator {
                width: 14px;
                height: 14px;
                border: 1px solid #243044;
                border-radius: 3px;
                background: #0a101c;
            }
            QCheckBox::indicator:checked {
                background-color: #2563eb;
                border: 1px solid #3b82f6;
            }
            QPushButton {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 6px;
                color: #e2e8f0;
                padding: 6px 12px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #334155;
                color: #ffffff;
            }
            QPushButton#btnStart {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2563eb, stop:1 #4f46e5);
                border: none;
                color: #ffffff;
                font-size: 14px;
                font-weight: bold;
                padding: 10px;
                border-radius: 8px;
            }
            QPushButton#btnStart:hover {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1d4ed8, stop:1 #4338ca);
            }
            QPushButton#btnStop {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #dc2626, stop:1 #be123c);
                border: none;
                color: #ffffff;
                font-size: 14px;
                font-weight: bold;
                padding: 10px;
                border-radius: 8px;
            }
            QPlainTextEdit {
                background-color: #080d16;
                border: 1px solid #243044;
                border-radius: 6px;
                color: #cbd5e1;
                font-family: "Consolas", monospace;
                font-size: 11px;
            }
            QScrollBar:vertical {
                background: #0b1220;
                width: 6px;
            }
            QScrollBar::handle:vertical {
                background: #243044;
                border-radius: 3px;
            }
        """)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        # 内容放进 QScrollArea：窗口被拖矮时技能卡片网格滚动而非压缩重叠
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        main_layout = QVBoxLayout(content)
        main_layout.setContentsMargins(14, 12, 14, 12)
        main_layout.setSpacing(10)
        main_layout.setAlignment(Qt.AlignTop)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        header = QHBoxLayout()
        title = QLabel("重生魔兽刷刷刷")
        title.setStyleSheet("font-size:17px; font-weight:bold; color:#60a5fa;")
        header.addWidget(title)
        header.addStretch()
        self.lbl_games = QLabel("0 局")
        self.lbl_games.setStyleSheet("color:#60a5fa; font-weight:bold;")
        header.addWidget(self.lbl_games)
        self.lbl_run_status = QLabel("空闲")
        self.lbl_run_status.setStyleSheet("color:#94a3b8; font-weight:bold;")
        header.addWidget(self.lbl_run_status)
        main_layout.addLayout(header)

        core = QGroupBox("运行设置")
        core_layout = QVBoxLayout(core)

        stage_row = QHBoxLayout()
        stage_row.addWidget(QLabel("目标关卡"))
        self.txt_stage_target = QLineEdit("1-10")
        self.txt_stage_target.setObjectName("stageTarget")
        self.txt_stage_target.setPlaceholderText("例如 1-10")
        self.txt_stage_target.setMaximumWidth(120)
        stage_row.addWidget(self.txt_stage_target)
        stage_row.addSpacing(12)
        stage_row.addWidget(QLabel("模式"))
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItem("普通模式", False)
        self.cmb_mode.addItem("英雄模式", True)
        self.cmb_mode.setItemData(
            1,
            "当前开放录像与实机证据完整的肯瑞托 1–5 级。",
            Qt.ToolTipRole,
        )
        stage_row.addWidget(self.cmb_mode)
        stage_row.addStretch()
        core_layout.addLayout(stage_row)

        self.hero_options = QWidget()
        hero_row = QHBoxLayout(self.hero_options)
        hero_row.setContentsMargins(0, 0, 0, 0)
        hero_row.addWidget(QLabel("英雄阵营"))
        self.cmb_reputation = QComboBox()
        self.cmb_reputation.addItem("肯瑞托", 3)
        hero_row.addWidget(self.cmb_reputation)
        hero_row.addWidget(QLabel("难度"))
        self.spn_reputation_level = QSpinBox()
        self.spn_reputation_level.setRange(1, 5)
        hero_row.addWidget(self.spn_reputation_level)
        hero_row.addStretch()
        core_layout.addWidget(self.hero_options)

        self.chk_dry = QCheckBox("安全测试（只识别，不点击）")
        self.chk_dry.setChecked(True)
        self.chk_dry.setStyleSheet("color:#f59e0b; font-weight:bold;")
        core_layout.addWidget(self.chk_dry)
        main_layout.addWidget(core)

        self.grp_skill = QGroupBox("技能搭配（可选，不选也能跑）")
        self.grp_skill.setCheckable(True)
        self.grp_skill.setChecked(True)
        self.grp_skill.setToolTip("勾选=展开技能卡片；选满 4 个自动收起；未选择时只刷新并放弃，不会学习其他技能")
        skill_layout = QVBoxLayout(self.grp_skill)
        self.skill_grid = SkillCardGrid(SKILL_STEMS, SKILL_LABELS)
        skill_layout.addWidget(self.skill_grid)
        self.grp_skill.toggled.connect(self._set_skill_panel_expanded)
        self.skill_grid.skills_changed.connect(self._on_skills_changed)
        main_layout.addWidget(self.grp_skill)

        self.btn_main = QPushButton("开  始  运  行")
        self.btn_main.setObjectName("btnStart")
        self.btn_main.clicked.connect(self.toggle_run)
        main_layout.addWidget(self.btn_main)

        self.lbl_latest = QLabel("就绪 · Shift+F12 可紧急停止")
        self.lbl_latest.setWordWrap(True)
        self.lbl_latest.setStyleSheet("color:#8b9bb4; font-size:11px;")
        main_layout.addWidget(self.lbl_latest)

        self.grp_details = QGroupBox("运行详情")
        self.grp_details.setCheckable(True)
        self.grp_details.setChecked(False)
        details_layout = QVBoxLayout(self.grp_details)
        self.txt_log = QPlainTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumHeight(150)
        self.txt_log.setVisible(False)
        self.grp_details.toggled.connect(self.txt_log.setVisible)
        details_layout.addWidget(self.txt_log)
        main_layout.addWidget(self.grp_details)

        self.cmb_mode.currentIndexChanged.connect(self._update_hero_visibility)
        self._update_hero_visibility()

    def _update_hero_visibility(self):
        self.hero_options.setVisible(bool(self.cmb_mode.currentData()))

    def _set_skill_panel_expanded(self, expanded: bool):
        self.skill_grid.setVisible(expanded)
        if not expanded:
            names = self.skill_grid.selected_names()
            self.grp_skill.setTitle(f"技能搭配（已选 {'、'.join(names)}，点勾展开）" if names else "技能搭配（点勾展开）")

    def _on_skills_changed(self):
        names = self.skill_grid.selected_names()
        if names:
            self.grp_skill.setTitle(f"技能搭配（已选 {'、'.join(names)}）")
        else:
            self.grp_skill.setTitle("技能搭配（可选，不选也能跑）")
        # 选满 4 个自动收起，保持面板简洁
        if len(names) == self.skill_grid.MAX_SKILLS:
            self.grp_skill.setChecked(False)
        self._schedule_auto_save()

    def _wire_auto_save(self):
        """控件变更 → 防抖自动保存（下次打开沿用上次设置）。"""
        self.txt_stage_target.textChanged.connect(self._schedule_auto_save)
        self.cmb_mode.currentIndexChanged.connect(self._schedule_auto_save)
        self.cmb_reputation.currentIndexChanged.connect(self._schedule_auto_save)
        self.spn_reputation_level.valueChanged.connect(self._schedule_auto_save)
        self.chk_dry.toggled.connect(self._schedule_auto_save)

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
            self.lbl_run_status.setText(f"运行中 · {phase}")
            self.lbl_run_status.setStyleSheet("color:#34d399; font-weight:bold; font-size:13px;")
            self.btn_main.setText("停  止  运  行")
            self.btn_main.setObjectName("btnStop")
        else:
            self.lbl_run_status.setText("空闲")
            self.lbl_run_status.setStyleSheet("color:#94a3b8; font-weight:bold; font-size:13px;")
            self.btn_main.setText("开  始  运  行")
            self.btn_main.setObjectName("btnStart")
        self.btn_main.setStyle(self.btn_main.style())
        self.lbl_games.setText(f"{game_count} 局")

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
        self.chk_dry.setChecked(settings.dry_run)
        self.skill_grid.set_skills(settings.skills or [])

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
        settings.new_room_every_times = False
        settings.dry_run = self.chk_dry.isChecked()
        settings.skills = skills
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
        room = settings.room_name or "<空>"
        password = "已设置" if settings.room_password else "未设置"
        width, height = (settings.window_size or [1600, 900])[:2]
        self.log(
            f"[启动配置] 关卡={target} 房间={room} 密码={password} 分辨率={width}x{height} "
            f"配置源={ROOT / 'config' / 'default_settings.json'}"
        )

        if not settings.dry_run:
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
                    "请关闭本窗口，右键 GameScript.exe，选择“以管理员身份运行”后再开始。",
                )
                self.log("[阻断] 真机运行需要管理员权限", "error")
                return

            answer = QMessageBox.warning(
                self,
                "确认开始真机运行",
                "安全测试已关闭，程序将向游戏窗口发送真实鼠标和键盘输入。\n\n"
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
        "GameScript 启动失败",
        f"程序遇到异常，详情已写入：\n{LOG_FILE}\n\n{exc_value}",
    )


def main():
    global _INSTANCE_LOCK
    app = QApplication(sys.argv)
    sys.excepthook = _handle_unhandled_exception

    _INSTANCE_LOCK = QLockFile(str(APP_DATA / "GameScript.lock"))
    if not _INSTANCE_LOCK.tryLock(100):
        QMessageBox.information(None, "GameScript", "程序已经在运行。")
        return

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
