"""非对称双擎启动区组件 (Dual Launch Matrix)."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtGui import QColor

class DualLaunchBoxWidget(QWidget):
    mode_triggered = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        # 1. 单人挂机卡片
        self.box_solo = QFrame()
        self.box_solo.setObjectName("launchBoxSolo")
        self.box_solo.setStyleSheet("background-color: #161b22; border: 1.5px solid #30363d; border-radius: 12px; padding: 14px;")
        solo_layout = QVBoxLayout(self.box_solo)
        solo_layout.setSpacing(8)

        lbl_solo_title = QLabel("🚀 单人挂机 · 自律刷图")
        lbl_solo_title.setStyleSheet("font-size: 15px; font-weight: 700; color: #f0f6fc;")
        solo_layout.addWidget(lbl_solo_title)

        lbl_solo_desc = QLabel("自动创建房间并进入选定关卡，自动选卡、打怪与结算。适合个人日常自律刷资源。")
        lbl_solo_desc.setStyleSheet("font-size: 12px; color: #8b949e; line-height: 1.4;")
        lbl_solo_desc.setWordWrap(True)
        solo_layout.addWidget(lbl_solo_desc)

        self.btn_solo = QPushButton("一键开始单人挂机")
        self.btn_solo.setStyleSheet("background-color: #2563eb; color: #fff; font-size: 13px; font-weight: 700; padding: 8px 16px; border-radius: 6px;")
        self.btn_solo.clicked.connect(lambda: self.mode_triggered.emit("normal_farm"))
        solo_layout.addWidget(self.btn_solo)
        layout.addWidget(self.box_solo)

        # 2. 蹭车跟车卡片
        self.box_hitch = QFrame()
        self.box_hitch.setObjectName("launchBoxHitch")
        self.box_hitch.setStyleSheet("background-color: #161b22; border: 1.5px solid #30363d; border-radius: 12px; padding: 14px;")
        hitch_layout = QVBoxLayout(self.box_hitch)
        hitch_layout.setSpacing(8)

        lbl_hitch_title = QLabel("🏎️ 大厅蹭车 · 智能跟车")
        lbl_hitch_title.setStyleSheet("font-size: 15px; font-weight: 700; color: #f0f6fc;")
        hitch_layout.addWidget(lbl_hitch_title)

        lbl_hitch_desc = QLabel("自动在大厅搜索 3/4 等非满员房间并双击进入准备，自动跟车作战。适合组队蹭车带飞。")
        lbl_hitch_desc.setStyleSheet("font-size: 12px; color: #8b949e; line-height: 1.4;")
        lbl_hitch_desc.setWordWrap(True)
        hitch_layout.addWidget(lbl_hitch_desc)

        self.btn_hitch = QPushButton("一键开始大厅蹭车")
        self.btn_hitch.setStyleSheet("background-color: #059669; color: #fff; font-size: 13px; font-weight: 700; padding: 8px 16px; border-radius: 6px;")
        self.btn_hitch.clicked.connect(lambda: self.mode_triggered.emit("lobby_hitch"))
        hitch_layout.addWidget(self.btn_hitch)
        layout.addWidget(self.box_hitch)

    def update_state(self, active_mode: str | None) -> None:
        if active_mode == "normal_farm":
            self.btn_solo.setText("停止单人挂机")
            self.btn_solo.setStyleSheet("background-color: #dc2626; color: #fff; font-size: 13px; font-weight: 700; padding: 8px 16px; border-radius: 6px;")
            self.btn_hitch.setEnabled(False)
        elif active_mode in ["lobby_hitch", "follow_team"]:
            self.btn_hitch.setText("停止大厅蹭车")
            self.btn_hitch.setStyleSheet("background-color: #dc2626; color: #fff; font-size: 13px; font-weight: 700; padding: 8px 16px; border-radius: 6px;")
            self.btn_solo.setEnabled(False)
        else:
            self.btn_solo.setText("一键开始单人挂机")
            self.btn_solo.setStyleSheet("background-color: #2563eb; color: #fff; font-size: 13px; font-weight: 700; padding: 8px 16px; border-radius: 6px;")
            self.btn_solo.setEnabled(True)
            self.btn_hitch.setText("一键开始大厅蹭车")
            self.btn_hitch.setStyleSheet("background-color: #059669; color: #fff; font-size: 13px; font-weight: 700; padding: 8px 16px; border-radius: 6px;")
            self.btn_hitch.setEnabled(True)
