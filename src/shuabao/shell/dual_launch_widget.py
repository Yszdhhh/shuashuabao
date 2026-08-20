"""非对称双擎启动区组件 (Dual Launch Matrix)."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from shuabao.shell.theme_styles import tokens


class DualLaunchBoxWidget(QWidget):
    mode_triggered = Signal(str)

    def __init__(self, parent: QWidget | None = None, theme: str = "light") -> None:
        super().__init__(parent)
        self._theme = theme
        self._build_ui()
        self.apply_theme(theme)

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        self.box_solo = QFrame()
        self.box_solo.setObjectName("launchBoxSolo")
        solo_layout = QVBoxLayout(self.box_solo)
        solo_layout.setSpacing(8)

        self.lbl_solo_title = QLabel("🚀 单人挂机 · 自律刷图")
        solo_layout.addWidget(self.lbl_solo_title)

        self.lbl_solo_desc = QLabel("自动创建房间并进入选定关卡，自动选卡、打怪与结算。适合个人日常自律刷资源。")
        self.lbl_solo_desc.setWordWrap(True)
        solo_layout.addWidget(self.lbl_solo_desc)

        self.btn_solo = QPushButton("一键开始单人挂机")
        self.btn_solo.clicked.connect(lambda: self.mode_triggered.emit("normal_farm"))
        solo_layout.addWidget(self.btn_solo)
        layout.addWidget(self.box_solo)

        self.box_hitch = QFrame()
        self.box_hitch.setObjectName("launchBoxHitch")
        hitch_layout = QVBoxLayout(self.box_hitch)
        hitch_layout.setSpacing(8)

        self.lbl_hitch_title = QLabel("🏎️ 大厅蹭车 · 智能跟车")
        hitch_layout.addWidget(self.lbl_hitch_title)

        self.lbl_hitch_desc = QLabel("自动在大厅搜索 3/4 等非满员房间并双击进入准备，自动跟车作战。适合组队蹭车带飞。")
        self.lbl_hitch_desc.setWordWrap(True)
        hitch_layout.addWidget(self.lbl_hitch_desc)

        self.btn_hitch = QPushButton("一键开始大厅蹭车")
        self.btn_hitch.clicked.connect(lambda: self.mode_triggered.emit("lobby_hitch"))
        hitch_layout.addWidget(self.btn_hitch)
        layout.addWidget(self.box_hitch)
        self._active_mode: str | None = None

    def apply_theme(self, theme: str = "light") -> None:
        self._theme = theme
        self.update_state(self._active_mode)

    def _box_qss(self) -> str:
        t = tokens(self._theme)
        return (
            f"background-color: {t['bg_surface']}; border: 1.5px solid {t['border_subtle']}; "
            f"border-radius: 12px; padding: 14px;"
        )

    def _title_qss(self) -> str:
        t = tokens(self._theme)
        return f"font-size: 15px; font-weight: 700; color: {t['text_primary']};"

    def _desc_qss(self) -> str:
        t = tokens(self._theme)
        return f"font-size: 12px; color: {t['text_secondary']}; line-height: 1.4;"

    def _btn_qss(self, accent_key: str) -> str:
        t = tokens(self._theme)
        return (
            f"background-color: {t[accent_key]}; color: #fff; font-size: 13px; "
            f"font-weight: 700; padding: 8px 16px; border-radius: 6px;"
        )

    def _stop_qss(self) -> str:
        t = tokens(self._theme)
        return (
            f"background-color: {t['accent_danger']}; color: #fff; font-size: 13px; "
            f"font-weight: 700; padding: 8px 16px; border-radius: 6px;"
        )

    def update_state(self, active_mode: str | None) -> None:
        self._active_mode = active_mode
        t_box = self._box_qss()
        self.box_solo.setStyleSheet(t_box)
        self.box_hitch.setStyleSheet(t_box)
        self.lbl_solo_title.setStyleSheet(self._title_qss())
        self.lbl_hitch_title.setStyleSheet(self._title_qss())
        self.lbl_solo_desc.setStyleSheet(self._desc_qss())
        self.lbl_hitch_desc.setStyleSheet(self._desc_qss())
        if active_mode == "normal_farm":
            self.btn_solo.setText("停止单人挂机")
            self.btn_solo.setStyleSheet(self._stop_qss())
            self.btn_hitch.setEnabled(False)
            self.btn_hitch.setStyleSheet(self._btn_qss("accent_hitch"))
        elif active_mode in ["lobby_hitch", "follow_team"]:
            self.btn_hitch.setText("停止大厅蹭车")
            self.btn_hitch.setStyleSheet(self._stop_qss())
            self.btn_solo.setEnabled(False)
            self.btn_solo.setStyleSheet(self._btn_qss("accent_solo"))
        else:
            self.btn_solo.setText("一键开始单人挂机")
            self.btn_solo.setStyleSheet(self._btn_qss("accent_solo"))
            self.btn_solo.setEnabled(True)
            self.btn_hitch.setText("一键开始大厅蹭车")
            self.btn_hitch.setStyleSheet(self._btn_qss("accent_hitch"))
            self.btn_hitch.setEnabled(True)
