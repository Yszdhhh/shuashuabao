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
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
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
            "<span style='color:#94a3b8;'>（自动建房需勾选 L0；输入框/按钮识别不安全时脚本会停住，不会盲点）</span>"
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

        # 3. 常规刷图配置 (P0)
        grp_reg = self._create_card("1. 常规运行配置 (基础关卡与 BOSS)")
        l_reg = QVBoxLayout(grp_reg)

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
        r_stage.addWidget(QLabel("关 (目标范围 Stage1—Stage2)"))
        r_stage.addStretch()
        l_reg.addLayout(r_stage)

        # L0 大厅自动建房与精确选关
        r_l0 = QHBoxLayout()
        self.chk_auto_room = QCheckBox("大厅自动建房 (L0)")
        r_l0.addWidget(self.chk_auto_room)
        r_l0.addWidget(QLabel("房间名:"))
        self.txt_room_name = QLineEdit()
        self.txt_room_name.setPlaceholderText("可空")
        r_l0.addWidget(self.txt_room_name)
        r_l0.addWidget(QLabel("密码:"))
        self.txt_room_password = QLineEdit()
        self.txt_room_password.setEchoMode(QLineEdit.Password)
        self.txt_room_password.setPlaceholderText("可空")
        r_l0.addWidget(self.txt_room_password)
        r_l0.addWidget(QLabel("创建按钮:"))
        self.cmb_room_side = QComboBox()
        self.cmb_room_side.addItem("左侧", "left")
        self.cmb_room_side.addItem("右侧", "right")
        r_l0.addWidget(self.cmb_room_side)
        self.chk_new_room = QCheckBox("每局重建（需退出模板）")
        r_l0.addWidget(self.chk_new_room)
        l_reg.addLayout(r_l0)

        r_exact_stage = QHBoxLayout()
        r_exact_stage.addWidget(QLabel("精确关卡（可选，逗号分隔）:"))
        self.txt_stage_targets = QLineEdit()
        self.txt_stage_targets.setPlaceholderText("例如 1-10；留空则使用上面的范围")
        r_exact_stage.addWidget(self.txt_stage_targets)
        l_reg.addLayout(r_exact_stage)

        # Boss 下拉
        grid_boss = QGridLayout()
        grid_boss.addWidget(QLabel("地图/Boss:"), 0, 0)
        self.cmb_sgzx = QComboBox()
        self.cmb_sgzx.addItems(BOSS_MAIN)
        grid_boss.addWidget(self.cmb_sgzx, 0, 1)

        grid_boss.addWidget(QLabel("传家宝 Boss:"), 0, 2)
        self.cmb_cjb = QComboBox()
        self.cmb_cjb.addItems(BOSS_CJB)
        grid_boss.addWidget(self.cmb_cjb, 0, 3)
        l_reg.addLayout(grid_boss)

        # 龙珠数 / 超时 / 发育时间
        r_timers = QHBoxLayout()
        r_timers.addWidget(QLabel("龙珠数:"))
        self.spn_db = QSpinBox()
        self.spn_db.setRange(1, 10)
        self.spn_db.setValue(7)
        r_timers.addWidget(self.spn_db)

        r_timers.addWidget(QLabel("等待UI(秒):"))
        self.spn_qto = QSpinBox()
        self.spn_qto.setRange(10, 600)
        self.spn_qto.setValue(120)
        r_timers.addWidget(self.spn_qto)

        r_timers.addWidget(QLabel("发育时间:"))
        self.spn_dev = QSpinBox()
        self.spn_dev.setRange(0, 3000)
        self.spn_dev.setValue(0)
        r_timers.addWidget(self.spn_dev)
        l_reg.addLayout(r_timers)
        lay.addWidget(grp_reg)

        # 4. 主要技能选择区 (最多4个下拉框)
        grp_skill = self._create_card("2. 主要技能配置 (下拉选择，最多选择 4 个)")
        l_skill = QVBoxLayout(grp_skill)

        # 快捷重置按钮
        r_sk_top = QHBoxLayout()
        r_sk_top.addWidget(QLabel("<span style='color:#60a5fa;'>选择主要刷图技能:</span>"))
        btn_std_skills = QPushButton("重置官方标准 4 技能")
        btn_std_skills.clicked.connect(self.reset_official_skills)
        btn_clear_skills = QPushButton("清空技能")
        btn_clear_skills.clicked.connect(self.clear_skills)
        r_sk_top.addWidget(btn_std_skills)
        r_sk_top.addWidget(btn_clear_skills)
        r_sk_top.addStretch()
        l_skill.addLayout(r_sk_top)

        # 4 个下拉列表
        grid_sk_combos = QGridLayout()
        self.skill_combos: list[QComboBox] = []

        # 构造技能选项列表 (Code, Label)
        self.skill_items = [("", "无 (不选择)")]
        for code in SKILL_STEMS:
            c_name = SKILL_LABELS.get(code, "未知")
            self.skill_items.append((code, f"{c_name} ({code})"))

        for i in range(4):
            lbl = QLabel(f"技能 {i+1}:")
            cmb = QComboBox()
            for code, name in self.skill_items:
                cmb.addItem(name, code)
            self.skill_combos.append(cmb)
            grid_sk_combos.addWidget(lbl, i // 2, (i % 2) * 2)
            grid_sk_combos.addWidget(cmb, i // 2, (i % 2) * 2 + 1)

        l_skill.addLayout(grid_sk_combos)
        lay.addWidget(grp_skill)

        # 5. 主要羁绊/卡牌选择区 (下拉框 + 开关)
        grp_fetter = self._create_card("3. 羁绊与卡牌偏好 (下拉选择，最多 4 项)")
        l_fetter = QVBoxLayout(grp_fetter)

        grid_card_combos = QGridLayout()
        self.card_combos: list[QComboBox] = []

        self.card_items = [("", "无 (不选择)")]
        for code in CARD_STEMS:
            c_name = FETTER_LABELS.get(code, code)
            self.card_items.append((code, f"{c_name} ({code})"))

        for i in range(4):
            lbl = QLabel(f"羁绊 {i+1}:")
            cmb = QComboBox()
            for code, name in self.card_items:
                cmb.addItem(name, code)
            self.card_combos.append(cmb)
            grid_card_combos.addWidget(lbl, i // 2, (i % 2) * 2)
            grid_card_combos.addWidget(cmb, i // 2, (i % 2) * 2 + 1)

        l_fetter.addLayout(grid_card_combos)

        # 辅助功能开关
        r_chk = QHBoxLayout()
        self.chk_card = QCheckBox("自动卡组")
        self.chk_weapon = QCheckBox("自动武器")
        self.chk_dmg = QCheckBox("奥数增伤")
        self.chk_devpri = QCheckBox("发育优先")
        self.chk_secret = QCheckBox("自动秘境")

        for chk in [self.chk_card, self.chk_weapon, self.chk_dmg, self.chk_devpri, self.chk_secret]:
            chk.setChecked(True)
            r_chk.addWidget(chk)
        self.chk_secret.setChecked(False)
        l_fetter.addLayout(r_chk)
        lay.addWidget(grp_fetter)

        # 6. 声望运行配置 (P1)
        grp_rep = self._create_card("4. 声望运行配置 (平行于常规配置)")
        l_rep = QVBoxLayout(grp_rep)

        r_rep_top = QHBoxLayout()
        self.chk_rep = QCheckBox("开启自动声望")
        r_rep_top.addWidget(self.chk_rep)
        r_rep_top.addWidget(QLabel("声望关卡:"))
        self.spn_rs1 = QSpinBox()
        self.spn_rs1.setRange(1, 50)
        self.spn_rs1.setValue(1)
        r_rep_top.addWidget(self.spn_rs1)
        r_rep_top.addWidget(QLabel("—"))
        self.spn_rs2 = QSpinBox()
        self.spn_rs2.setRange(1, 50)
        self.spn_rs2.setValue(10)
        r_rep_top.addWidget(self.spn_rs2)
        l_rep.addLayout(r_rep_top)

        grid_rep_boss = QGridLayout()
        grid_rep_boss.addWidget(QLabel("声望Boss:"), 0, 0)
        self.cmb_rcjb = QComboBox()
        self.cmb_rcjb.addItems(BOSS_CJB)
        grid_rep_boss.addWidget(self.cmb_rcjb, 0, 1)

        self.cmb_rsgzx = QComboBox()
        self.cmb_rsgzx.addItems(BOSS_MAIN)
        grid_rep_boss.addWidget(self.cmb_rsgzx, 0, 2)
        l_rep.addLayout(grid_rep_boss)
        lay.addWidget(grp_rep)

        # 7. 环境与匹配
        grp_env = self._create_card("5. 环境检测与识别匹配")
        l_env = QVBoxLayout(grp_env)

        r_env1 = QHBoxLayout()
        r_env1.addWidget(QLabel("窗口标题包含:"))
        self.txt_title = QLineEdit("英雄三国,魔兽世界,Warcraft,KK,对战")
        self.txt_title.setToolTip("支持逗号分隔多个关键字，例：英雄三国,魔兽世界,KK,对战")
        r_env1.addWidget(self.txt_title)

        btn_detect = QPushButton("🔍 侦测窗口")
        btn_detect.clicked.connect(self.detect_windows)
        r_env1.addWidget(btn_detect)

        self.chk_dry = QCheckBox("Dry-run(只找图不点击)")
        self.chk_dry.setChecked(True)
        r_env1.addWidget(self.chk_dry)
        l_env.addLayout(r_env1)

        r_thresh = QHBoxLayout()
        r_thresh.addWidget(QLabel("找图阈值:"))
        self.spn_thresh = QDoubleSpinBox()
        self.spn_thresh.setRange(0.50, 0.99)
        self.spn_thresh.setSingleStep(0.01)
        self.spn_thresh.setValue(0.85)
        r_thresh.addWidget(self.spn_thresh)
        r_thresh.addWidget(QLabel("<span style='color:#60a5fa;'>提示: 请将游戏设为 1600×900 窗口化</span>"))
        r_thresh.addStretch()
        l_env.addLayout(r_thresh)
        lay.addWidget(grp_env)

        scroll.setWidget(scroll_content)
        main_layout.addWidget(scroll, stretch=1)

        # 8. 辅助操作与主开始大按钮
        lay_btns = QHBoxLayout()
        btn_sync = QPushButton("从官方 Settings 同步")
        btn_sync.clicked.connect(self.sync_official)
        btn_save = QPushButton("保存本地配置")
        btn_save.clicked.connect(self.save_local_settings)

        lay_btns.addWidget(btn_sync)
        lay_btns.addWidget(btn_save)
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
        std = ["asj", "asjg", "assx", "jq"]
        for i, cmb in enumerate(self.skill_combos):
            val = std[i] if i < len(std) else ""
            idx = cmb.findData(val)
            if idx >= 0:
                cmb.setCurrentIndex(idx)

    def clear_skills(self):
        for cmb in self.skill_combos:
            cmb.setCurrentIndex(0)

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
        side_index = self.cmb_room_side.findData(s.room_create_side)
        self.cmb_room_side.setCurrentIndex(side_index if side_index >= 0 else 0)
        self.chk_new_room.setChecked(s.new_room_every_times)
        self.spn_db.setValue(s.dragon_ball_count)
        self.spn_qto.setValue(s.query_timeout)
        self.spn_dev.setValue(s.develop_time)
        self.chk_card.setChecked(s.auto_card)
        self.chk_weapon.setChecked(s.auto_weapon)
        self.chk_dmg.setChecked(s.damage_increase_card)
        self.chk_devpri.setChecked(s.develop_priority)
        self.chk_secret.setChecked(s.auto_secret_realm)

        self.chk_rep.setChecked(s.auto_reputation)
        self.spn_rs1.setValue(s.reputation_stage1 or 1)
        self.spn_rs2.setValue(s.reputation_stage2 or 10)

        if s.sgzx_boss and self.cmb_sgzx.findText(s.sgzx_boss) >= 0:
            self.cmb_sgzx.setCurrentText(s.sgzx_boss)
        if s.cjb_boss and self.cmb_cjb.findText(s.cjb_boss) >= 0:
            self.cmb_cjb.setCurrentText(s.cjb_boss)
        if s.reputation_cjb_boss and self.cmb_rcjb.findText(s.reputation_cjb_boss) >= 0:
            self.cmb_rcjb.setCurrentText(s.reputation_cjb_boss)
        if s.reputation_sgzx_boss and self.cmb_rsgzx.findText(s.reputation_sgzx_boss) >= 0:
            self.cmb_rsgzx.setCurrentText(s.reputation_sgzx_boss)

        self.txt_title.setText(s.window_title_contains)
        self.chk_dry.setChecked(s.dry_run)
        self.spn_thresh.setValue(s.match_threshold)

        # 应用 4 个技能下拉框
        sk_list = s.skills or []
        for i, cmb in enumerate(self.skill_combos):
            code = sk_list[i] if i < len(sk_list) else ""
            idx = cmb.findData(code)
            cmb.setCurrentIndex(idx if idx >= 0 else 0)

        # 应用 4 个羁绊下拉框
        card_list = s.cards or []
        for i, cmb in enumerate(self.card_combos):
            code = card_list[i] if i < len(card_list) else ""
            idx = cmb.findData(code)
            cmb.setCurrentIndex(idx if idx >= 0 else 0)

    def collect_settings_from_ui(self) -> Settings:
        s = self.settings
        s.game_mode = 0
        s.stage1 = self.spn_s1.value()
        s.stage2 = self.spn_s2.value()
        s.stage_targets = [item.strip() for item in self.txt_stage_targets.text().split(",") if item.strip()]
        s.auto_create_room = self.chk_auto_room.isChecked()
        s.room_name = self.txt_room_name.text().strip()
        s.room_password = self.txt_room_password.text()
        s.room_create_side = self.cmb_room_side.currentData() or "left"
        s.new_room_every_times = self.chk_new_room.isChecked()
        s.dragon_ball_count = self.spn_db.value()
        s.query_timeout = self.spn_qto.value()
        s.develop_time = self.spn_dev.value()
        s.sgzx_boss = self.cmb_sgzx.currentText().strip()
        s.cjb_boss = self.cmb_cjb.currentText().strip()
        s.auto_card = self.chk_card.isChecked()
        s.auto_weapon = self.chk_weapon.isChecked()
        s.damage_increase_card = self.chk_dmg.isChecked()
        s.develop_priority = self.chk_devpri.isChecked()
        s.auto_secret_realm = self.chk_secret.isChecked()

        s.auto_reputation = self.chk_rep.isChecked()
        s.reputation_stage1 = self.spn_rs1.value()
        s.reputation_stage2 = self.spn_rs2.value()
        s.reputation_cjb_boss = self.cmb_rcjb.currentText().strip()
        s.reputation_sgzx_boss = self.cmb_rsgzx.currentText().strip()

        s.window_title_contains = self.txt_title.text().strip()
        s.dry_run = self.chk_dry.isChecked()
        s.match_threshold = float(self.spn_thresh.value())

        # 收集 4 个技能下拉
        selected_skills = []
        for cmb in self.skill_combos:
            c = cmb.currentData()
            if c and c not in selected_skills:
                selected_skills.append(c)
        s.skills = selected_skills

        # 收集 4 个羁绊下拉
        selected_cards = []
        for cmb in self.card_combos:
            c = cmb.currentData()
            if c and c not in selected_cards:
                selected_cards.append(c)
        s.cards = selected_cards

        return s

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

        # 真机提示
        if not s.dry_run:
            ret = QMessageBox.warning(
                self,
                "准备发起真机点击",
                "您关闭了 Dry-run 模式！\n脚本将向游戏窗口发送真实鼠标点击。\n\n是否确认开始？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
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
