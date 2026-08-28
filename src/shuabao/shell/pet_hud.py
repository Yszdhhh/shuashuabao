"""沉浸式拟人悬浮伴侣 (Floating Mascot Pet HUD)."""
from __future__ import annotations

from pathlib import Path
import random
import sys
from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from shuabao.shell.theme_styles import tokens

class MascotStatusVoice:
    IDLE = ["☕ 挂机助手待命中，随时准备出发~", "🧘 正在闭目养神，点击开始带你飞！", "🍵 喝口茶，今天想刷第几关？"]
    COMBAT = ["🔥 正在全力刷怪中，全屏秒杀！", "⚔️ 走位走位，技能疯狂输出中~", "🌪️ 怪潮来袭，大招准备就绪！"]
    DISCOVER_BONDS = ["🧐 正在努力识别羁绊，找最强组合！", "✨ 发现极品羁绊，正在精准锁定！", "📚 翻阅攻略库，这把必须凑齐大炮/圣人！"]
    PICK_SKILL = ["🎯 俺来挑选最适合你的神级技能！", "⚡ 正在计算最高伤害倍率，锁定主C词条！", "🪄 技能池已刷新，必拿高阶进阶卡！"]
    BOSS_FIGHT = ["👑 正在与深渊领主激情互殴，稳住能赢！", "🛡️ Boss狂暴预警，减伤护盾已拉满！"]
    VICTORY = ["🎉 战斗胜利！爆了一地极品，芜湖起飞！", "💰 战利品丰收，正在自动清点材料~"]
    RECONNECT = ["📡 网络似乎打了个盹，正在努力重连中...", "🔄 正在自动找回房间，莫慌莫慌！"]

    @classmethod
    def get_line(cls, phase: str) -> str:
        lines = getattr(cls, phase, cls.COMBAT)
        return random.choice(lines)

class FloatingPetHud(QWidget):
    hud_restored = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.resize(320, 68)

        self._current_phase = "IDLE"
        self._is_click_through = False
        self._drag_pos = QPoint()
        self._theme = "light"
        self._palette = tokens("light")

        self._build_ui()
        self.apply_theme("dark")
        self._setup_voice_timer()
        self.hide()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        self.pet_avatar = QLabel()
        # 打包后 assets 在 _MEIPASS（_internal）下；源码模式按源树回溯仓库根。
        pet_path = (
            Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))
            / "assets" / "branding" / "pet_mode_1.png"
        )
        if pet_path.exists():
            pix = QPixmap(str(pet_path)).scaled(36, 36, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.pet_avatar.setPixmap(pix)
        else:
            self.pet_avatar.setText("🤖")
            self.pet_avatar.setStyleSheet("font-size: 26px; padding: 2px;")
        layout.addWidget(self.pet_avatar)
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)

        self.lbl_title = QLabel("刷刷宝 · 挂机伴侣")
        text_layout.addWidget(self.lbl_title)

        self.lbl_broadcast = QLabel("☕ 挂机助手就绪...")
        self.lbl_broadcast.setWordWrap(True)
        text_layout.addWidget(self.lbl_broadcast)
        layout.addLayout(text_layout)

        self.btn_lock = QPushButton("🔓")
        self.btn_lock.setObjectName("petLock")
        self.btn_lock.setToolTip("点击切换穿透/拖拽模式 (双击主屏可还原窗口)")
        self.btn_lock.setFixedSize(24, 24)
        self.btn_lock.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_lock.clicked.connect(self._toggle_lock)
        layout.addWidget(self.btn_lock)

    def apply_theme(self, theme: str = "light") -> None:
        self._theme = theme
        t = tokens(theme)
        self._palette = t
        self.lbl_title.setStyleSheet(
            f"font-size: 11px; font-weight: 700; color: {t['accent_gold']}; background: transparent;"
        )
        self.lbl_broadcast.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {t['text_primary']}; background: transparent;"
        )
        self.btn_lock.setStyleSheet(
            "QPushButton#petLock { background: transparent; border: none; font-size: 13px; padding: 0; }"
            f"QPushButton#petLock:hover {{ color: {t['accent_gold_light']}; }}"
        )
        self.update()

    def _setup_voice_timer(self) -> None:
        self._voice_timer = QTimer(self)
        self._voice_timer.setInterval(5000)
        self._voice_timer.timeout.connect(self._refresh_voice)
        self._voice_timer.start()

    def update_runtime_state(self, phase: str, raw_msg: str | None = None) -> None:
        self._current_phase = phase
        if phase in ["DISCOVER_BONDS", "PICK_SKILL"]:
            self.pet_avatar.setText("🧐")
        elif phase in ["IN_COMBAT", "BOSS_FIGHT"]:
            self.pet_avatar.setText("⚔️")
        elif phase == "VICTORY":
            self.pet_avatar.setText("🎉")
        elif phase == "RECONNECT":
            self.pet_avatar.setText("📡")
        else:
            self.pet_avatar.setText("🤖")

        if raw_msg:
            self.lbl_broadcast.setText(raw_msg)
        else:
            self._refresh_voice()

    def _refresh_voice(self) -> None:
        line = MascotStatusVoice.get_line(self._current_phase)
        self.lbl_broadcast.setText(line)

    def _toggle_lock(self) -> None:
        self._is_click_through = not self._is_click_through
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, self._is_click_through)
        self.btn_lock.setText("🔒" if self._is_click_through else "🔓")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        self.hud_restored.emit()
        event.accept()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(float(rect.x()), float(rect.y()), float(rect.width()), float(rect.height()), 14, 14)
        fill = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        fill.setColorAt(0, QColor(26, 33, 44, 230))
        fill.setColorAt(1, QColor(14, 18, 24, 240))
        painter.fillPath(path, fill)
        painter.setPen(QPen(QColor(255, 255, 255, 42), 1))
        painter.drawLine(rect.left() + 14, rect.top() + 1, rect.right() - 14, rect.top() + 1)
        gold = QColor(self._palette.get("accent_gold", "#E5A93C"))
        gold.setAlpha(190)
        painter.setPen(QPen(gold, 1.2))
        painter.drawPath(path)
