#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GameScript-Local 原生 PySide6 桌面客户端软件
对齐 1.3.3.3 官方 WPF 版视觉与字段。纯 Native Windows GUI，无需 Web 浏览器与 HTTP 服务。
按 1.3.3.3 规则支持技能 4 项下拉选择、羁绊 4 项下拉选择与清晰分类排布。
"""

from __future__ import annotations

import builtins
import json
import os
import sys
import threading
import traceback
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtGui import QColor, QFont, QIcon, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

# 确保 src 在 PATH 中
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from gamescript.settings import OFFICIAL_SETTINGS, Settings


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
BOSS_MAIN = _stems(ROOT / "assets" / "Images" / "boss")
BOSS_CJB = _stems(ROOT / "assets" / "Images" / "chuanjiaobao")
SKILL_STEMS = _stems(ROOT / "assets" / "Images" / "skills") or [
    "asj", "asjg", "assx", "bsxx", "byj", "dcw", "dz", "hbj",
    "hq", "jf", "jq", "ljf", "pg", "sdl", "tl", "ys",
]
CARD_STEMS = _stems(ROOT / "assets" / "Images" / "cards")

SKILL_LABELS = _load_json_labels(ROOT / "config" / "skill_labels.json")
FETTER_LABELS = _load_json_labels(ROOT / "config" / "fetter_labels.json")


class LogSignal(QObject):
    log_emitted = Signal(str, str)  # (text, level)
    status_changed = Signal(bool, str, int)  # (running, phase, game_count)


class MediatorWorker(QThread):
    def __init__(self, settings: Settings, root_dir: Path, max_steps: int | None = None):
        super().__init__()
        self.settings = settings
        self.root_dir = root_dir
        self.max_steps = max_steps
        self.signals = LogSignal()
        self.mediator = None

    def run(self):
        try:
            from gamescript.mediator import Mediator, Phase
        except Exception as e:
            self.signals.log_emitted.emit(f"[错误] 无法加载 Mediator 自动化引擎: {e}", "error")
            self.signals.status_changed.emit(False, "错误", 0)
            return

        self.signals.status_changed.emit(True, "就绪", 0)
        self.signals.log_emitted.emit(
            f"[启动] 刷图任务启动 | Dry-run={self.settings.dry_run} | "
            f"关卡={self.settings.stage1}-{self.settings.stage2} | 技能={self.settings.skills}",
            "info"
        )

        real_print = builtins.print

        def hook_print(*args, **kwargs):
            text = " ".join(str(x) for x in args)
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
            self.mediator = Mediator(self.settings, self.root_dir)
            self.mediator.run(max_steps=self.max_steps)
        except Exception as e:
            self.signals.log_emitted.emit(f"[异常] 任务异常退出: {e}", "error")
        finally:
            builtins.print = real_print
            count = getattr(self.mediator, "game_count", 0) if self.mediator else 0
            self.signals.status_changed.emit(False, "空闲", count)
            self.signals.log_emitted.emit("[结束] 任务运行结束", "info")

    def stop(self):
        if self.mediator:
            self.mediator.stop()


class SkillCardGrid(QWidget):
    """中文技能卡片多选网格：显示中文名，内部存拼音短码，最多 4 个。"""

    MAX_SKILLS = 4

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
            cn = self.skill_labels.get(code, code)
            btn = QPushButton(f"{cn}\n({code})")
            btn.setCheckable(True)
            btn.setMinimumHeight(46)
            btn.setStyleSheet(
                "QPushButton { background:#0a101c; border:1px solid #243044; border-radius:6px;"
                " color:#cbd5e1; font-size:12px; padding:2px; }"
                "QPushButton:checked { background:#1e3a5f; border:2px solid #2563eb; color:#ffffff; }"
            )
            btn.clicked.connect(lambda checked, c=code: self._toggle(c, checked))
            self.cards[code] = btn
            grid.addWidget(btn, idx // 4, idx % 4)
        lay.addLayout(grid)

        # 摘要
        self.lbl_summary = QLabel("当前已选技能: 无")
        self.lbl_summary.setStyleSheet("color:#60a5fa; font-size:11px;")
        lay.addWidget(self.lbl_summary)

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
        self._refresh_summary()

    def set_skills(self, codes: list[str]):
        self._selected = [c for c in codes if c in self.cards][: self.MAX_SKILLS]
        for code, btn in self.cards.items():
            btn.setChecked(code in self._selected)
        self._refresh_summary()

    def get_skills(self) -> list[str]:
        return list(self._selected)

    def _refresh_summary(self):
        names = [self.skill_labels.get(c, c) for c in self._selected]
        if names:
            self.lbl_summary.setText(f"当前已选技能 ({len(names)}/{self.MAX_SKILLS}): {'、'.join(names)}")
        else:
            self.lbl_summary.setText("当前已选技能: 无")


class AdvancedSettingsDialog(QDialog):
    """高级设置抽屉：低频/调试参数集中收纳。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("高级与局内优化设置")
        self.setMinimumWidth(440)
        lay = QVBoxLayout(self)

        grp_toggle = QGroupBox("局内辅助开关")
        lt = QVBoxLayout(grp_toggle)
        self.chk_card = QCheckBox("自动卡组")
        self.chk_weapon = QCheckBox("自动武器")
        self.chk_dmg = QCheckBox("奥数增伤优先")
        self.chk_devpri = QCheckBox("发育优先")
        self.chk_secret = QCheckBox("局末自动秘境")
        self.chk_rep2 = QCheckBox("开启英雄声望模式")
        for c in (self.chk_card, self.chk_weapon, self.chk_dmg, self.chk_devpri, self.chk_secret, self.chk_rep2):
            lt.addWidget(c)
        lay.addWidget(grp_toggle)

        grp_time = QGroupBox("超时与识别")
        lt2 = QGridLayout(grp_time)
        lt2.addWidget(QLabel("龙珠收集数:"), 0, 0)
        self.spn_db = QSpinBox(); self.spn_db.setRange(1, 10); self.spn_db.setValue(7)
        lt2.addWidget(self.spn_db, 0, 1)
        lt2.addWidget(QLabel("等待UI超时(秒):"), 0, 2)
        self.spn_qto = QSpinBox(); self.spn_qto.setRange(10, 600); self.spn_qto.setValue(120)
        lt2.addWidget(self.spn_qto, 0, 3)
        lt2.addWidget(QLabel("找图阈值:"), 1, 0)
        self.spn_thresh = QDoubleSpinBox(); self.spn_thresh.setRange(0.50, 0.99); self.spn_thresh.setSingleStep(0.01); self.spn_thresh.setValue(0.85)
        lt2.addWidget(self.spn_thresh, 1, 1)
        lt2.addWidget(QLabel("窗口标题包含:"), 1, 2)
        self.txt_title = QLineEdit("英雄三国")
        lt2.addWidget(self.txt_title, 1, 3)
        lay.addWidget(grp_time)

        grp_room = QGroupBox("建房高级选项")
        lr = QVBoxLayout(grp_room)
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("创建按钮位置:"))
        self.cmb_room_side = QComboBox()
        self.cmb_room_side.addItem("左侧", "left")
        self.cmb_room_side.addItem("右侧", "right")
        r1.addWidget(self.cmb_room_side)
        r1.addStretch()
        lr.addLayout(r1)
        self.chk_new_room = QCheckBox("每局重建房间")
        lr.addWidget(self.chk_new_room)
        lay.addWidget(grp_room)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        lay.addWidget(btn_box)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("英雄三国挂机助手 (懒人系列之魔兽世界刷刷刷) · 1.3.3.3 本地版")
        self.resize(520, 880)
        self.setMinimumSize(460, 760)

        self.settings = Settings()
        self.worker_thread: MediatorWorker | None = None

        self._setup_style()
        self._build_ui()
        self.load_local_settings(silent=True)

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
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(8)

        # 1. 标题区
        title_box = QVBoxLayout()
        lbl_title = QLabel("懒人系列之魔兽世界刷刷刷")
        lbl_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #60a5fa;")
        lbl_sub = QLabel("1.3.3.3 本地版 · 功能整理与技能/羁绊多选择下拉界面")
        lbl_sub.setStyleSheet("font-size: 11px; color: #8b9bb4;")
        title_box.addWidget(lbl_title)
        title_box.addWidget(lbl_sub)
        main_layout.addLayout(title_box)

        # 模式声明与操作提示 (官方 1.3.3.3 规则)
        lbl_notice = QLabel(
            "⚠️ <b style='color:#f59e0b;'>【独狼模式说明】</b>："
            "独狼模式 (GameMode=0) 会优先在游戏窗口内自动识别并点击房间「开始游戏」，随后识别局内选关/主线 UI。<br/>"
            "若日志提示 <code>miss lobby start</code>，请确认窗口化 1600×900、缩放 100%，并更新 <code>assets/Images/lobby/room_start.png</code>。<br/>"
            "<span style='color:#94a3b8;'>（自动建房需勾选 L0；同名大厅/房间会按页面按钮内容选择；输入框/按钮识别不安全或窗口被完全遮挡时脚本会停住，不会盲点）</span>"
        )
        lbl_notice.setWordWrap(True)
        lbl_notice.setStyleSheet(
            "background-color: #1e293b; border: 1px solid #d97706; border-radius: 6px; padding: 8px 10px; font-size: 11px; color: #cbd5e1;"
        )
        main_layout.addWidget(lbl_notice)

        # 可滚动主体
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll_content = QWidget()
        lay = QVBoxLayout(scroll_content)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        # 2. 状态看板
        grp_status = self._create_card("状态看板")
        l_status = QVBoxLayout(grp_status)
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("<span style='color:#8b9bb4;'>认证状态:</span> <b style='color:#34d399;'>1.3.3.3 本地免证书</b>"))
        r1.addStretch()
        self.lbl_run_status = QLabel("空 闲")
        self.lbl_run_status.setStyleSheet("color:#94a3b8; font-weight:bold; font-size:13px;")
        r1.addWidget(self.lbl_run_status)
        l_status.addLayout(r1)

        r2 = QHBoxLayout()
        r2.addWidget(QLabel("当前局数:"))
        self.lbl_games = QLabel("0 局")
        self.lbl_games.setStyleSheet("color:#60a5fa; font-weight:bold; font-size:14px;")
        r2.addWidget(self.lbl_games)
        r2.addStretch()
        lbl_tip = QLabel("Shift+F12 停官方脚本 | 本窗点停止")
        lbl_tip.setStyleSheet("color:#8b9bb4; font-size:10px;")
        r2.addWidget(lbl_tip)
        l_status.addLayout(r2)
        lay.addWidget(grp_status)

        # 3. 核心配置区（一屏可见，无需滚动）
        grp_core = self._create_card("核心配置")
        l_core = QVBoxLayout(grp_core)

        # 关卡范围
        r_stage = QHBoxLayout()
        r_stage.addWidget(QLabel("目标关卡:"))
        self.spn_s1 = QSpinBox()
        self.spn_s1.setRange(1, 50)
        self.spn_s1.setValue(1)
        r_stage.addWidget(self.spn_s1)
        r_stage.addWidget(QLabel("—"))
        self.spn_s2 = QSpinBox()
        self.spn_s2.setRange(1, 50)
        self.spn_s2.setValue(10)
        r_stage.addWidget(self.spn_s2)
        r_stage.addWidget(QLabel("关"))
        r_stage.addWidget(QLabel("精确关卡(可选):"))
        self.txt_stage_targets = QLineEdit()
        self.txt_stage_targets.setPlaceholderText("如 1-10；留空用范围")
        self.txt_stage_targets.setMaximumWidth(120)
        r_stage.addWidget(self.txt_stage_targets)
        r_stage.addStretch()
        l_core.addLayout(r_stage)

        # 房间
        r_room = QHBoxLayout()
        self.chk_auto_room = QCheckBox("大厅自动建房")
        r_room.addWidget(self.chk_auto_room)
        r_room.addWidget(QLabel("房间名:"))
        self.txt_room_name = QLineEdit()
        self.txt_room_name.setPlaceholderText("可空")
        self.txt_room_name.setMaximumWidth(110)
        r_room.addWidget(self.txt_room_name)
        r_room.addWidget(QLabel("密码:"))
        self.txt_room_password = QLineEdit()
        self.txt_room_password.setEchoMode(QLineEdit.Password)
        self.txt_room_password.setPlaceholderText("可空")
        self.txt_room_password.setMaximumWidth(90)
        r_room.addWidget(self.txt_room_password)
        self.chk_dry = QCheckBox("Dry-run(测试不点击)")
        self.chk_dry.setChecked(True)
        self.chk_dry.setStyleSheet("color:#f59e0b; font-weight:bold;")
        r_room.addWidget(self.chk_dry)
        r_room.addStretch()
        l_core.addLayout(r_room)
        lay.addWidget(grp_core)

        # 4. 技能配置（折叠：勾选展开，取消折叠隐藏）
        grp_skill = QGroupBox("技能配置（设置完取消勾选即隐藏）")
        grp_skill.setCheckable(True)
        grp_skill.setChecked(True)
        l_skill = QVBoxLayout(grp_skill)
        self.skill_grid = SkillCardGrid(SKILL_STEMS, SKILL_LABELS)
        l_skill.addWidget(self.skill_grid)
        lay.addWidget(grp_skill)

        # 5. 英雄模式与声望（先阵营，后难度）
        grp_rep = QGroupBox("英雄模式与声望挑战（先选阵营，再选难度）")
        grp_rep.setCheckable(True)
        grp_rep.setChecked(False)
        l_rep = QVBoxLayout(grp_rep)

        r_rep_on = QHBoxLayout()
        self.chk_rep = QCheckBox("开启英雄声望模式")
        self.chk_rep.setChecked(False)
        r_rep_on.addWidget(self.chk_rep)
        r_rep_on.addStretch()
        l_rep.addLayout(r_rep_on)

        l_rep.addWidget(QLabel("① 选择阵营:"))
        rep_names = [
            (1, "黑锋骑士团"), (2, "银色北伐军"), (3, "肯瑞托"),
            (4, "探险者协会"), (5, "元素领主"), (6, "守护巨龙"),
        ]
        self.rep_group = QButtonGroup(self)
        self.rep_group.setExclusive(True)
        r_rep_cards = QGridLayout()
        self.rep_buttons: dict[int, QPushButton] = {}
        for i, (rid, rname) in enumerate(rep_names):
            btn = QPushButton(rname)
            btn.setCheckable(True)
            btn.setMinimumHeight(36)
            btn.setStyleSheet(
                "QPushButton { background:#0a101c; border:1px solid #243044; border-radius:6px; color:#cbd5e1; }"
                "QPushButton:checked { background:#1e3a5f; border:2px solid #2563eb; color:#ffffff; }"
            )
            self.rep_group.addButton(btn, rid)
            self.rep_buttons[rid] = btn
            r_rep_cards.addWidget(btn, i // 3, i % 3)
        l_rep.addLayout(r_rep_cards)
        self.rep_buttons[1].setChecked(True)

        l_rep.addWidget(QLabel("② 选择难度 (1-10):"))
        r_rep_level = QHBoxLayout()
        self.slider_rep_level = QSlider(Qt.Horizontal)
        self.slider_rep_level.setRange(1, 10)
        self.slider_rep_level.setValue(1)
        r_rep_level.addWidget(self.slider_rep_level)
        self.lbl_rep_level = QLabel("难度 1 级")
        self.lbl_rep_level.setStyleSheet("color:#60a5fa; font-weight:bold;")
        r_rep_level.addWidget(self.lbl_rep_level)
        l_rep.addLayout(r_rep_level)
        self.slider_rep_level.valueChanged.connect(lambda v: self.lbl_rep_level.setText(f"难度 {v} 级"))
        lay.addWidget(grp_rep)

        # 6. Boss 与传家宝（默认最后一个，指定才展开）
        grp_boss = QGroupBox("Boss 与传家宝设置")
        grp_boss.setCheckable(True)
        grp_boss.setChecked(False)
        l_boss = QVBoxLayout(grp_boss)
        self.radio_boss_last = QRadioButton("默认挑战最后一个 Boss（推荐）")
        self.radio_boss_last.setChecked(True)
        self.radio_boss_custom = QRadioButton("指定特定 Boss:")
        l_boss.addWidget(self.radio_boss_last)
        l_boss.addWidget(self.radio_boss_custom)
        grid_boss = QGridLayout()
        grid_boss.addWidget(QLabel("地图/Boss:"), 0, 0)
        self.cmb_sgzx = QComboBox()
        self.cmb_sgzx.addItems(BOSS_MAIN)
        grid_boss.addWidget(self.cmb_sgzx, 0, 1)
        grid_boss.addWidget(QLabel("传家宝 Boss:"), 0, 2)
        self.cmb_cjb = QComboBox()
        self.cmb_cjb.addItems(BOSS_CJB)
        grid_boss.addWidget(self.cmb_cjb, 0, 3)
        l_boss.addLayout(grid_boss)

        def _boss_mode_changed():
            custom = self.radio_boss_custom.isChecked()
            self.cmb_sgzx.setVisible(custom)
            self.cmb_cjb.setVisible(custom)
            for i in range(grid_boss.count()):
                grid_boss.itemAt(i).widget().setVisible(custom)

        self.radio_boss_last.toggled.connect(_boss_mode_changed)
        self.radio_boss_custom.toggled.connect(_boss_mode_changed)
        _boss_mode_changed()
        lay.addWidget(grp_boss)

        # 7. 环境（精简）
        grp_env = self._create_card("环境")
        l_env = QHBoxLayout(grp_env)
        btn_detect = QPushButton("🔍 侦测窗口")
        btn_detect.clicked.connect(self.detect_windows)
        l_env.addWidget(btn_detect)
        l_env.addWidget(QLabel("分辨率建议 1600×900 窗口化"))
        l_env.addStretch()
        lay.addWidget(grp_env)

        scroll.setWidget(scroll_content)
        main_layout.addWidget(scroll, stretch=1)

        # 8. 辅助操作与主开始大按钮
        lay_btns = QHBoxLayout()
        btn_sync = QPushButton("从官方 Settings 同步")
        btn_sync.clicked.connect(self.sync_official)
        btn_save = QPushButton("保存本地配置")
        btn_save.clicked.connect(self.save_local_settings)
        btn_adv = QPushButton("高级设置")
        btn_adv.clicked.connect(self.open_advanced_settings)

        lay_btns.addWidget(btn_sync)
        lay_btns.addWidget(btn_save)
        lay_btns.addWidget(btn_adv)
        lay_btns.addWidget(QLabel("测试步数:"))
        self.spn_steps = QSpinBox()
        self.spn_steps.setRange(0, 99999)
        self.spn_steps.setValue(0)
        lay_btns.addWidget(self.spn_steps)
        main_layout.addLayout(lay_btns)

        # 主按钮
        self.btn_main = QPushButton("开  始  游  戏")
        self.btn_main.setObjectName("btnStart")
        self.btn_main.clicked.connect(self.toggle_run)
        main_layout.addWidget(self.btn_main)

        # 9. 日志控制台
        self.txt_log = QPlainTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumHeight(160)
        main_layout.addWidget(self.txt_log)

    def _create_card(self, title: str) -> QWidget:
        box = QWidget()
        box.setStyleSheet("""
            QWidget {
                background-color: #151c2c;
                border: 1px solid #243044;
                border-radius: 8px;
            }
        """)
        return box

    def detect_windows(self):
        try:
            from gamescript.vision.capture import list_active_window_titles
            titles = list_active_window_titles()
            if not titles:
                self.log("[窗口侦测] 未发现独立游戏窗口，将使用全主屏降级匹配", "warn")
                return
            msg = " | ".join(titles[:5])
            self.log(f"[窗口侦测] 找到 {len(titles)} 个桌面窗口: {msg}", "info")
            QMessageBox.information(
                self,
                "活动窗口侦测结果",
                "在当前桌面上侦测到以下独立窗口:\n\n" + "\n".join(f"• {t}" for t in titles[:12]) +
                "\n\n已启用多关键字智能锁窗 (`" + self.txt_title.text() + "`)，只要窗口标题包含其中任何词即自动锁定进行识别！"
            )
        except Exception as e:
            self.log(f"[窗口侦测错误] {e}", "error")

    def log(self, text: str, level: str = "info"):
        if level == "error":
            color = "#f87171"
        elif level == "warn":
            color = "#fbbf24"
        else:
            color = "#cbd5e1"
        html = f"<span style='color:{color};'>{text}</span>"
        self.txt_log.appendHtml(html)

    def update_status(self, running: bool, phase: str, game_count: int):
        if running:
            self.lbl_run_status.setText(f"运行中 ({phase})")
            self.lbl_run_status.setStyleSheet("color:#34d399; font-weight:bold; font-size:13px;")
            self.btn_main.setText("停  止  游  戏")
            self.btn_main.setObjectName("btnStop")
            self.btn_main.setStyle(self.btn_main.style())
        else:
            self.lbl_run_status.setText("空 闲")
            self.lbl_run_status.setStyleSheet("color:#94a3b8; font-weight:bold; font-size:13px;")
            self.btn_main.setText("开  始  游  戏")
            self.btn_main.setObjectName("btnStart")
            self.btn_main.setStyle(self.btn_main.style())
        self.lbl_games.setText(f"{game_count} 局")

    def reset_official_skills(self):
        self.skill_grid.set_skills(["asj", "asjg", "assx", "jq"])

    def clear_skills(self):
        self.skill_grid.set_skills([])

    def load_local_settings(self, silent: bool = False):
        config_file = ROOT / "config" / "default_settings.json"
        if config_file.is_file():
            try:
                s = Settings.load(config_file)
                self.apply_settings_to_ui(s)
                if not silent:
                    self.log(f"[加载] 已载入 {config_file.name}", "info")
            except Exception as e:
                self.log(f"[加载失败] {e}", "error")

    def sync_official(self):
        try:
            s = Settings.load_official()
            self.apply_settings_to_ui(s)
            self.log(f"[同步成功] 来自 {OFFICIAL_SETTINGS}", "info")
            self.log(f"[同步技能] Skills={s.skills}", "info")
            QMessageBox.information(self, "同步成功", f"已成功从官方 Settings 同步配置！\nSkills={s.skills}")
        except Exception as e:
            self.log(f"[同步错误] 无法读取官方配置: {e}", "error")
            QMessageBox.warning(self, "同步失败", f"无法读取官方配置文件：\n{e}")

    def apply_settings_to_ui(self, s: Settings):
        self.settings = s
        self.spn_s1.setValue(s.stage1)
        self.spn_s2.setValue(s.stage2)
        self.txt_stage_targets.setText(",".join(s.stage_targets or []))
        self.chk_auto_room.setChecked(s.auto_create_room)
        self.txt_room_name.setText(s.room_name)
        self.txt_room_password.setText(s.room_password)
        self.chk_dry.setChecked(s.dry_run)

        # 技能卡片（中文）
        self.skill_grid.set_skills(s.skills or [])

        # 声望：阵营 + 难度
        self.chk_rep.setChecked(s.auto_reputation)
        rep_type = getattr(s, "reputation_type", 1) or 1
        btn = self.rep_buttons.get(rep_type)
        if btn is not None:
            btn.setChecked(True)
        self.slider_rep_level.setValue(getattr(s, "reputation_level", 1) or 1)

        # Boss：默认最后一个 / 指定
        last_main = BOSS_MAIN[-1] if BOSS_MAIN else ""
        last_cjb = BOSS_CJB[-1] if BOSS_CJB else ""
        custom = bool(
            (s.sgzx_boss and s.sgzx_boss != last_main)
            or (s.cjb_boss and s.cjb_boss != last_cjb)
        )
        self.radio_boss_custom.setChecked(custom)
        self.radio_boss_last.setChecked(not custom)
        if s.sgzx_boss and self.cmb_sgzx.findText(s.sgzx_boss) >= 0:
            self.cmb_sgzx.setCurrentText(s.sgzx_boss)
        if s.cjb_boss and self.cmb_cjb.findText(s.cjb_boss) >= 0:
            self.cmb_cjb.setCurrentText(s.cjb_boss)

    def collect_settings_from_ui(self) -> Settings:
        s = self.settings
        s.game_mode = 0
        s.stage1 = self.spn_s1.value()
        s.stage2 = self.spn_s2.value()
        s.stage_targets = [item.strip() for item in self.txt_stage_targets.text().split(",") if item.strip()]
        s.auto_create_room = self.chk_auto_room.isChecked()
        s.room_name = self.txt_room_name.text().strip()
        s.room_password = self.txt_room_password.text()
        s.dry_run = self.chk_dry.isChecked()

        # 技能卡片 → 短码列表
        s.skills = self.skill_grid.get_skills()

        # 声望：阵营 + 难度
        s.auto_reputation = self.chk_rep.isChecked()
        s.reputation_type = self.rep_group.checkedId() if self.rep_group.checkedId() > 0 else 1
        s.reputation_level = self.slider_rep_level.value()

        # Boss：默认最后一个 / 指定
        last_main = BOSS_MAIN[-1] if BOSS_MAIN else ""
        last_cjb = BOSS_CJB[-1] if BOSS_CJB else ""
        if self.radio_boss_last.isChecked():
            s.sgzx_boss = last_main
            s.cjb_boss = last_cjb
        else:
            s.sgzx_boss = self.cmb_sgzx.currentText().strip()
            s.cjb_boss = self.cmb_cjb.currentText().strip()

        # 高级抽屉参数（若已打开过，取抽屉值；否则保留 settings 现值）
        if hasattr(self, "_adv_dialog") and self._adv_dialog is not None:
            adv = self._adv_dialog
            s.dragon_ball_count = adv.spn_db.value()
            s.query_timeout = adv.spn_qto.value()
            s.match_threshold = float(adv.spn_thresh.value())
            s.window_title_contains = adv.txt_title.text().strip()
            s.room_create_side = adv.cmb_room_side.currentData() or "left"
            s.new_room_every_times = adv.chk_new_room.isChecked()
            s.auto_card = adv.chk_card.isChecked()
            s.auto_weapon = adv.chk_weapon.isChecked()
            s.damage_increase_card = adv.chk_dmg.isChecked()
            s.develop_priority = adv.chk_devpri.isChecked()
            s.auto_secret_realm = adv.chk_secret.isChecked()

        return s

    def open_advanced_settings(self):
        adv = AdvancedSettingsDialog(self)
        s = self.settings
        adv.spn_db.setValue(s.dragon_ball_count)
        adv.spn_qto.setValue(s.query_timeout)
        adv.spn_thresh.setValue(s.match_threshold)
        adv.txt_title.setText(s.window_title_contains)
        side = adv.cmb_room_side.findData(s.room_create_side)
        adv.cmb_room_side.setCurrentIndex(side if side >= 0 else 0)
        adv.chk_new_room.setChecked(s.new_room_every_times)
        adv.chk_card.setChecked(s.auto_card)
        adv.chk_weapon.setChecked(s.auto_weapon)
        adv.chk_dmg.setChecked(s.damage_increase_card)
        adv.chk_devpri.setChecked(s.develop_priority)
        adv.chk_secret.setChecked(s.auto_secret_realm)
        if adv.exec() == QDialog.Accepted:
            self._adv_dialog = adv
            self.log("[高级设置] 已应用高级参数（下次开始时生效）", "info")

    def save_local_settings(self):
        config_file = ROOT / "config" / "default_settings.json"
        s = self.collect_settings_from_ui()
        s.save(config_file)
        self.log(f"[保存成功] 配置已写入 {config_file.name}", "info")
        QMessageBox.information(self, "保存", f"已成功保存配置到：\n{config_file}")

    def toggle_run(self):
        if self.worker_thread and self.worker_thread.isRunning():
            self.log("[操作] 请求停止任务...", "warn")
            self.worker_thread.stop()
            return

        s = self.collect_settings_from_ui()

        # 真机提示 + 管理员硬门禁（UIPI：非提权进程点不进管理员 KK/游戏）
        if not s.dry_run:
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
                    "已关闭 Dry-run，但当前控制面板不是管理员进程。\n\n"
                    "原版 GameScript.exe 清单为 requireAdministrator；\n"
                    "KK 对战平台也通常以管理员运行。\n"
                    "Windows UIPI 会静默丢弃「普通权限 → 管理员窗口」的鼠标点击\n"
                    "（SendInput 返回成功，但游戏完全无响应）。\n\n"
                    "请关闭本窗口，用【启动面板.bat】或右键「以管理员身份运行」后再开真机。",
                )
                self.log("[阻断] dry_run=False 且未提权 — 已拒绝启动（UIPI）", "error")
                return

            ret = QMessageBox.warning(
                self,
                "准备发起真机点击",
                "您关闭了 Dry-run 模式！\n"
                "当前已是管理员进程，脚本将向游戏窗口发送真实鼠标点击（SendInput）。\n\n"
                "是否确认开始？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if ret != QMessageBox.Yes:
                return

        steps = self.spn_steps.value()
        max_steps = steps if steps > 0 else None

        self.worker_thread = MediatorWorker(s, ROOT, max_steps=max_steps)
        self.worker_thread.signals.log_emitted.connect(self.log)
        self.worker_thread.signals.status_changed.connect(self.update_status)
        self.worker_thread.start()


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
